"""
AI 智能客服系统 - 物流查询 Tool

查询物流信息，根据订单号或快递单号追踪物流轨迹。
支持阿里云市场物流查询 API，失败时降级到 Mock 数据。
"""

from typing import Optional
from datetime import datetime
import httpx
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client
from app.config import settings

# 第三方轨迹 API 结果缓存（issue #6185：该 API 按次计费）。
# 顶层导入，便于测试用 patch 把它替换成 fake —— 与 `get_admin_api_client` 同款接缝。
from app.core.logistics_trace_cache import (
    CN_STATUS_MAP,
    COMPANY_NAME_MAP,
    STATUS_TEXT_MAP,
    get_logistics_trace_cache,
)

# 说明（issue #6185）：上面三张表与「轨迹 → 状态」推断的**唯一实现**现在都在
# `app/core/logistics_trace_cache.py` —— 实时查询与缓存命中必须共用同一份解析，
# 各写一份一旦漂移就会出现「实时查是已签收 / 命中缓存是在途」的分歧（TTL 分档也跟着错）。
# 这里按原样 re-export，保持既有对外符号（`tests/test_tools_logistics_track.py`
# 直接从本模块 import `STATUS_TEXT_MAP`）不破。

# 需要手机号后4位的快递公司
PHONE_REQUIRED_COMPANIES = {"SF", "SFEXPRESS", "ZTO", "STO"}


class LogisticsTrackTool(BaseTool):
    """物流查询 Tool
    
    查询订单的物流轨迹和当前状态。
    
    使用场景：
    - 用户询问"我的订单到哪了"
    - 用户询问物流进度
    
    **安全铁律（2026-09 收紧）：仅支持通过真实订单号（order_id/订单号）查询物流，
    禁止直接通过快递单号查询**——防止用他人运单号刺探物流信息。快递单号只能由
    系统从订单详情中读取后内部用于查询轨迹，不接受用户直接提供。
    
    支持阿里云市场物流查询 API，API 调用失败时降级到 Mock 数据。
    """
    
    name = "logistics_track"
    description = (
        "【触发】用户问'物流''快递''到哪了''发货了吗''配送''签收'时调用。【参数】必须提供 order_id（真实订单号）。"
        "用户只说'查物流'但没提供订单号时，先问订单号，不要空调。"
        "【链条】顾客要物流时**交付物是轨迹**：订单号只是入参——你用 order_query 查到订单号后"
        "**必须继续调用本工具**（order_id=该订单号）把轨迹/状态交付给顾客；"
        "查到订单号就停下汇报订单信息＝这条链**没做完**。本工具答'尚未发货/未找到'也是有效结果，如实转述。"
        "【铁律】不接受用户提供的快递单号/运单号直接查询——用户给单号时引导其提供订单号，"
        "运单号只能由系统从订单详情中读取。"
        "【反例】查订单详情(金额/商品/客户)用 order_query，不要混淆。【标注】READONLY"
    )

    # 权限码（admin-api 目录）：AgentOrderController 的物流/轨迹端点 `@RequirePermission("order:list")`
    # （物流是订单读面的一部分）⇒ 与 controller 同码。
    required_permissions = ["order:list"]
    read_only = True   # 只读（BaseTool 默认值，显式声明以便权限面自检）

    parameters = {
        "type": "object",
        "properties": {
            "order_id": {
                "type": "string",
                "description": "真实订单号（必填，如 ORD-20260531-4186447007，或订单 UUID）",
            },
        },
        "required": ["order_id"],
    }
    
    async def execute(
        self,
        context: ToolContext,
        order_id: Optional[str] = None,
        tracking_number: Optional[str] = None,
    ) -> ToolResult:
        """执行物流查询
        
        Args:
            context: Tool 执行上下文
            order_id: 真实订单号（必填）
            tracking_number: 已废弃——拒绝直接按快递单号查询
            
        Returns:
            ToolResult: 物流信息
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询物流信息",
                suggestion="请联系管理员获取查询物流信息权限",
            )
        
        # 铁律：拒绝直接按快递单号查询（无论通过哪个参数传入）
        if tracking_number:
            return ToolResult(
                success=False,
                error="不支持快递单号查询",
                message="仅支持通过真实订单号查询物流，请提供订单号",
                suggestion="请用户提供真实订单号（如 ORD-xxx）后调用本工具，不要用快递单号；"
                           "拿到订单号后**立即**调用 logistics_track(order_id=…) 查轨迹"
                           "（订单号只是入参，不是交付物）",
            )
        
        if not order_id:
            return ToolResult(
                success=False,
                error="缺少查询参数",
                message="请提供订单号",
                suggestion="用户只说'查物流'时，先询问其订单号再查询；"
                           "拿到订单号后**立即**调用本工具查轨迹（不要只把订单号回给顾客）",
            )
        
        try:
            logger.info(f"[logistics] Querying by order_id: {order_id} | tenant={context.tenant_id}")
            return await self._track_by_order(context, order_id)
        except Exception as e:
            logger.warning(f"[logistics] Query failed, using fallback data | order_id={order_id} error={e}")
            # 出错时返回 mock 数据（降级方案）
            return self._get_mock_result(None, order_id=order_id)
    
    async def _track_by_order(
        self,
        context: ToolContext,
        order_id: str,
    ) -> ToolResult:
        """通过订单号查询物流

        Args:
            context: Tool 执行上下文
            order_id: 订单号（如 ORD-20260531-4186447007）

        Returns:
            ToolResult: 物流信息
        """
        try:
            client = get_admin_api_client()

            # 判断是否为 UUID 格式，如果不是则先通过 keyword 搜索获取真实 UUID
            import re
            is_uuid = bool(re.match(r'^[0-9a-fA-F-]{36}$', order_id))

            if not is_uuid:
                # 订单号格式（如 ORD-xxx），通过 keyword 搜索获取 UUID
                search_response = await client.get(
                    "/api/admin/orders",
                    params={"keyword": order_id, "page": 1, "size": 1},
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
                search_data = search_response.get("data", {})
                # 生产回归修复：admin-api 列表接口实际返回 items（旧实现读 records 永远为空，
                # 导致按订单号查物流恒定"订单不存在"）。兼容两种字段名。
                records = search_data.get("items") or search_data.get("records") or []
                if not records:
                    return ToolResult(
                        success=False,
                        error="订单不存在",
                        message="未找到该订单，请检查订单号",
                        suggestion="请检查ID是否正确，或尝试其他搜索条件",
                    )
                # 取第一条匹配的 UUID
                actual_uuid = records[0].get("id")
                logger.info(f"[logistics] Resolved order_no={order_id} → uuid={actual_uuid}")
            else:
                actual_uuid = order_id

            # 用 UUID 查询订单详情获取物流单号
            order_response = await client.get(
                f"/api/admin/orders/{actual_uuid}",
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
            
            if not order_response.get("success"):
                error_msg = order_response.get("error", {}).get("message", "查询失败")
                return admin_api_failure(order_response,
                    error=error_msg,
                    message="未找到该订单，请检查订单号",
                    suggestion="请检查ID是否正确，或尝试其他搜索条件",
                )
            
            order = order_response.get("data", {})
            
            # 验证响应数据的 tenant_id
            resp_tenant_id = order.get("tenantId") or order.get("tenant_id")
            if resp_tenant_id is not None and str(resp_tenant_id) != str(context.tenant_id):
                logger.error(
                    f"Tenant data integrity violation in logistics_track: "
                    f"response tenant_id={resp_tenant_id}, expected={context.tenant_id}"
                )
                return ToolResult(
                    success=False,
                    error="订单不存在",
                    message="未找到该订单，请检查订单号",
                    suggestion="请检查ID是否正确，或尝试其他搜索条件",
                )
            
            logistics = order.get("logistics", {})
            
            if not logistics or not logistics.get("trackingNo"):
                return ToolResult(
                    success=False,
                    error="订单未发货",
                    message="该订单尚未发货，发货后我会帮您跟踪物流",
                    suggestion="该订单尚未发货，请告知用户发货后再查询物流，不要编造物流轨迹",
                )
            
            tracking_no = logistics.get("trackingNo")
            # 后端 OrderDetailResponse.LogisticsInfo 字段是 logisticsCompany（无 company 字段）
            company = logistics.get("logisticsCompany", "未知")
            # 物流类型（issue #3984，V47）：express 快递 / logistics 物流专线（四季安等）
            logistics_type = logistics.get("logisticsType", "express")
            # 顺丰/中通/申通等需要「运单号:收件人手机号后4位」才能查全量轨迹：
            # 收件人手机号 = 订单根级 customerPhone（OrderDetailResponse 提供），取末 4 位。
            # （2026-09 修复：此前误以为后端不提供手机号 → 尾号恒为 None → 此类快递恒降级 mock）
            phone_tail = None
            order_phone = order.get("customerPhone") or order.get("customer_phone")
            if order_phone and len(str(order_phone).strip()) >= 4:
                phone_tail = str(order_phone).strip()[-4:]
            
            # 查询物流轨迹
            result = await self._track_by_number(
                context, tracking_no, company, order_id, phone_tail
            )
            # 注入物流类型（issue #3984，V47）：express 快递 / logistics 物流专线
            if result.success and isinstance(result.data, dict):
                result.data["logistics_type"] = logistics_type
            return result
            
        except Exception as e:
            logger.error(f"[logistics] Track by order error: {e}", exc_info=True)
            raise
    
    async def _track_by_number(
        self,
        context: ToolContext,
        tracking_number: Optional[str],
        company: Optional[str] = None,
        order_id: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> ToolResult:
        """通过快递单号查询物流

        缓存优先（issue #6185）：命中即返回，**不再调用按次计费的第三方 API**；
        未命中才查 API，并把成功响应写回缓存。
        API 失败（或未配置 APPCODE）时仍降级到 Mock 数据。

        Args:
            context: Tool 执行上下文
            tracking_number: 快递单号
            company: 快递公司
            order_id: 订单号
            phone: 收/寄件人手机号后四位

        Returns:
            ToolResult: 物流信息
        """
        logger.info(
            f"[logistics] Tracking: tracking_no={tracking_number}, company={company}, "
            f"order_id={order_id} | tenant={context.tenant_id}"
        )

        # 缓存 key 的快递公司一维用「编码」：顺丰 203 重试时 `type` 会被摘掉，
        # 用同一个 key 才能让两次尝试共享同一份缓存（详见 tests/unit/test_logistics_trace_cache.py）
        com_code = self._get_company_code(company) if company else None

        # 尝试调用真实 API
        if settings.LOGISTICS_APPCODE:
            try:
                # ── 先查缓存：命中即返回，第三方调用次数直接减一 ──
                cached = await get_logistics_trace_cache().get(
                    context.tenant_id, tracking_number, com_code, phone
                )
                if cached is not None:
                    # order_id 属于**本次**查询的上下文，不能沿用缓存里的那份
                    # （同一运单可能被不同订单引用），与 `logistics_type` 同款按次注入
                    data = {**cached, "order_id": order_id}
                    return ToolResult(
                        success=True,
                        data=data,
                        message=(
                            f"【{data['company']}】{data['tracking_number']}，"
                            f"当前状态：{data['status_text']}"
                        ),
                        summary=f"物流状态: {data['company']} {data['tracking_number']}, {data['status_text']}",
                    )

                api_result = await self._call_logistics_api(
                    tracking_number, company, phone
                )
                if api_result is not None:
                    logger.info(f"[logistics] API query success | tracking_no={tracking_number}")
                    # API 调用成功，转换为标准格式
                    data = self._transform_api_response(
                        api_result, tracking_number, company, order_id
                    )
                    # 成功响应写回缓存（含 status=205「无信息」，它同样按次计费）
                    await get_logistics_trace_cache().set(
                        context.tenant_id, tracking_number, com_code, phone, api_result
                    )
                    return ToolResult(
                        success=True,
                        data=data,
                        message=(
                            f"【{data['company']}】{data['tracking_number']}，"
                            f"当前状态：{data['status_text']}"
                        ),
                        summary=f"物流状态: {data['company']} {data['tracking_number']}, {data['status_text']}",
                    )
            except Exception as e:
                logger.warning(
                    f"[logistics] API call failed, falling back to mock | tracking_no={tracking_number} error={e}"
                )
        else:
            logger.warning(
                "[logistics] LOGISTICS_APPCODE not configured, using mock data"
            )
        
        # 降级到 mock 数据
        logger.warning("[logistics] Using mock logistics data as fallback")
        return self._get_mock_result(tracking_number, company, order_id)
    
    async def _call_logistics_api(
        self,
        tracking_number: str,
        company: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> Optional[dict]:
        """调用阿里云市场物流查询 API（wuliu.market.alicloudapi.com/kdi）
        
        Args:
            tracking_number: 快递单号
            company: 快递公司名称或编码
            phone: 收/寄件人手机号后四位
            
        Returns:
            API 响应 dict，失败返回 None
        """
        headers = {
            "Authorization": f"APPCODE {settings.LOGISTICS_APPCODE}",
        }
        
        # 构建 no 参数：需要手机号的快递公司拼接 :手机后4位
        no_param = tracking_number
        com_code = self._get_company_code(company) if company else None
        if phone and com_code and com_code in PHONE_REQUIRED_COMPANIES:
            no_param = f"{tracking_number}:{phone}"
        
        params = {
            "no": no_param,
        }
        
        if com_code:
            params["type"] = com_code
        
        logger.info(
            f"Calling logistics API: url={settings.LOGISTICS_API_URL}, "
            f"no={params['no']}, type={params.get('type')}"
        )
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                settings.LOGISTICS_API_URL,
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            result = response.json()
        
        logger.info(
            f"Logistics API response: status={result.get('status')}, "
            f"msg={result.get('msg')}, result_type={result.get('result', {}).get('type')}"
        )
        
        # 显式快递公司代码不被该 API 识别（如极兔需 JITU 而非 JT）→ 去掉 type 走自动识别重试一次
        # （单号自动识别 95% 准确，见商品文档；避免因 code 映射偏差整单降级 mock）
        if str(result.get("status")) == "203" and "type" in params:
            logger.warning(
                f"[logistics] Company code '{params['type']}' rejected (203), "
                f"retrying with auto-detect | no={params['no']}"
            )
            params.pop("type")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    settings.LOGISTICS_API_URL,
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                result = response.json()
        
        # status "0" 表示成功，"205" 表示无信息但结构正常
        if str(result.get("status")) not in ("0", "205"):
            logger.warning(
                f"Logistics API returned error: "
                f"status={result.get('status')}, msg={result.get('msg')}"
            )
            return None
        
        return result
    
    def _transform_api_response(
        self,
        api_result: dict,
        tracking_number: Optional[str],
        company: Optional[str],
        order_id: Optional[str],
    ) -> dict:
        """将 API 响应转换为项目标准格式

        **解析复用** `LogisticsTraceCache._decode`（issue #6185）：缓存写的是同一份标准格式，
        两处各写一份解析，一旦漂移就会出现「实时查是已签收 / 命中缓存是在途」的分歧。
        本方法只补上只有调用方才知道的兜底与 order_id。

        Args:
            api_result: API 原始响应
            tracking_number: 快递单号
            company: 快递公司（来自订单）
            order_id: 订单号

        Returns:
            标准格式的物流数据 dict
        """
        # 延迟导入：本模块在 import 期被缓存模块导入（避免循环导入）
        from app.core.logistics_trace_cache import LogisticsTraceCache

        data = LogisticsTraceCache._decode(api_result) or {}

        # 快递公司名称：API type 映射不到时用传入的 company
        if not data.get("company") or data["company"] == "未知快递":
            data["company"] = company or data.get("company") or "未知快递"

        # 快递单号：API 未回传时用传入的单号
        data["tracking_number"] = data.get("tracking_number") or tracking_number or ""
        data["order_id"] = order_id
        return data

    @staticmethod
    def _infer_status_from_traces(traces: list[dict]) -> str:
        """从物流轨迹中推断当前状态

        实现已迁到 `app/core/logistics_trace_cache.py::infer_status_from_traces`
        （issue #6185）：缓存 TTL 分档与 Tool 显示必须用同一份关键词表，否则同一段轨迹会
        出现「显示已签收 / 按在途计 TTL」的分歧。本方法保留为薄转发，不改变既有调用点。

        Args:
            traces: 物流轨迹列表（最新在前）

        Returns:
            内部状态字符串
        """
        from app.core.logistics_trace_cache import infer_status_from_traces

        return infer_status_from_traces(traces)
    
    def _get_company_code(self, company: str) -> Optional[str]:
        """将快递公司名称或编码转换为 API 所需的公司编码（大写）
        
        Args:
            company: 快递公司名称或编码
            
        Returns:
            大写公司编码，无法识别时返回 None（让 API 自动识别）
        """
        # 如果已经是编码格式（全英文），直接返回大写
        if company and company.isascii() and company.isalpha():
            return company.upper()
        
        # 中文名称 → 大写编码
        name_to_code = {
            "顺丰": "SFEXPRESS",
            "顺丰速运": "SFEXPRESS",
            "圆通": "YTO",
            "圆通速递": "YTO",
            "韵达": "YUNDA",
            "韵达快递": "YUNDA",
            "申通": "STO",
            "申通快递": "STO",
            "中通": "ZTO",
            "中通快递": "ZTO",
            "EMS": "EMS",
            "京东": "JD",
            "京东物流": "JD",
            "极兔": "JITU",
            "极兔速递": "JITU",
            "德邦": "DB",
            "德邦快递": "DB",
            "百世": "BEST",
            "百世快递": "BEST",
            "天天快递": "TTKDEX",
            "邮政": "YOUZHENG",
            "中国邮政": "YOUZHENG",
        }
        return name_to_code.get(company)
    
    def _get_mock_result(
        self,
        tracking_number: Optional[str],
        company: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> ToolResult:
        """获取 mock 物流数据（降级方案）
        
        Args:
            tracking_number: 快递单号
            company: 快递公司
            order_id: 订单号
            
        Returns:
            ToolResult: mock 物流信息
        """
        mock_data = {
            "order_id": order_id,
            "tracking_number": tracking_number or "SF1234567890",
            "company": company or "顺丰速运",
            "status": "in_transit",
            "status_text": "运输中",
            "latest": {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "content": "快件已到达【杭州转运中心】",
            },
            "traces": [
                {
                    "time": "2026-04-18 14:30:00",
                    "content": "快件已到达【杭州转运中心】",
                },
                {
                    "time": "2026-04-18 10:15:00",
                    "content": "快件已发往【杭州转运中心】",
                },
                {
                    "time": "2026-04-18 08:00:00",
                    "content": "顺丰速运 已收取快件",
                },
                {
                    "time": "2026-04-18 07:30:00",
                    "content": "商家正在打包商品",
                },
            ],
        }
        
        return ToolResult(
            success=True,
            data=mock_data,
            message=f"【{mock_data['company']}】{mock_data['tracking_number']}，当前状态：{mock_data['status_text']}",
            summary=f"物流状态: {mock_data['company']} {mock_data['tracking_number']}, {mock_data['status_text']}",
        )
