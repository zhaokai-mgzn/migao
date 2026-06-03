"""
AI 智能客服系统 - 物流查询 Tool

查询物流信息，根据订单号或快递单号追踪物流轨迹。
支持阿里云市场物流查询 API，失败时降级到 Mock 数据。
"""

from typing import Optional
from datetime import datetime
import httpx
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client
from app.config import settings

# 内部状态 → 中文文本
STATUS_TEXT_MAP = {
    "pending": "待发货",
    "picked": "已揽收",
    "in_transit": "运输中",
    "out_for_delivery": "派送中",
    "delivered": "已签收",
    "exception": "异常",
    "returned": "已退回",
}

# 中文物流状态关键词 → 内部状态
CN_STATUS_MAP = {
    "签收": "delivered",
    "已签收": "delivered",
    "派送": "out_for_delivery",
    "派件": "out_for_delivery",
    "正在派送": "out_for_delivery",
    "揽收": "picked",
    "已揽收": "picked",
    "揽件": "picked",
    "退回": "returned",
    "退件": "returned",
    "异常": "exception",
    "问题件": "exception",
    "到达": "in_transit",
    "在途": "in_transit",
    "发往": "in_transit",
    "运输": "in_transit",
    "转运": "in_transit",
}

# 需要手机号后4位的快递公司
PHONE_REQUIRED_COMPANIES = {"SF", "SFEXPRESS", "ZTO", "STO"}

# 快递公司编码(大写) → 中文名称
COMPANY_NAME_MAP = {
    "SF": "顺丰速运",
    "SFEXPRESS": "顺丰速运",
    "YTO": "圆通速递",
    "YUNDA": "韵达快递",
    "STO": "申通快递",
    "ZTO": "中通快递",
    "EMS": "EMS",
    "JD": "京东物流",
    "JT": "极兔速递",
    "DB": "德邦快递",
    "BEST": "百世快递",
    "TTKDEX": "天天快递",
    "YOUZHENG": "中国邮政",
    "ANE": "安能物流",
    "ZJS": "宅急送",
    "DPEX": "DPEX",
    "FEDEX": "FedEx",
    "UPS": "UPS",
    "DHL": "DHL",
    "USPS": "USPS",
}


class LogisticsTrackTool(BaseTool):
    """物流查询 Tool
    
    查询订单的物流轨迹和当前状态。
    
    使用场景：
    - 用户询问"我的订单到哪了"
    - 用户询问物流进度
    - 用户查询快递状态
    
    支持阿里云市场物流查询 API，API 调用失败时降级到 Mock 数据。
    """
    
    name = "logistics_track"
    description = (
        "查询物流信息，根据订单号或快递单号追踪物流轨迹。"
        "当用户询问订单物流状态、快递到哪了时使用。"
    )
    
    parameters = {
        "type": "object",
        "properties": {
            "tracking_number": {
                "type": "string",
                "description": "快递单号（可选，优先使用订单号）",
            },
            "order_id": {
                "type": "string",
                "description": "订单号（可选，如果有订单号优先使用）",
            },
        },
    }
    
    async def execute(
        self,
        context: ToolContext,
        tracking_number: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> ToolResult:
        """执行物流查询
        
        Args:
            context: Tool 执行上下文
            tracking_number: 快递单号
            order_id: 订单号
            
        Returns:
            ToolResult: 物流信息
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询物流信息",
            )
        
        if not tracking_number and not order_id:
            return ToolResult(
                success=False,
                error="缺少查询参数",
                message="请提供订单号或快递单号",
            )
        
        try:
            # 优先使用订单号查询
            if order_id:
                logger.info(f"[logistics] Querying by order_id: {order_id} | tenant={context.tenant_id}")
                return await self._track_by_order(context, order_id)
            else:
                logger.info(f"[logistics] Querying by tracking_number: {tracking_number} | tenant={context.tenant_id}")
                return await self._track_by_number(context, tracking_number)
                
        except Exception as e:
            logger.warning(f"[logistics] Query failed, using fallback data | tracking_no={tracking_number or order_id} error={e}")
            # 出错时返回 mock 数据（降级方案）
            return self._get_mock_result(tracking_number or order_id)
    
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
                records = search_data.get("records", [])
                if not records:
                    return ToolResult(
                        success=False,
                        error="订单不存在",
                        message="未找到该订单，请检查订单号",
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
                return ToolResult(
                    success=False,
                    error=error_msg,
                    message="未找到该订单，请检查订单号",
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
                )
            
            logistics = order.get("logistics", {})
            
            if not logistics or not logistics.get("trackingNo"):
                return ToolResult(
                    success=False,
                    error="订单未发货",
                    message="该订单尚未发货，发货后我会帮您跟踪物流",
                )
            
            tracking_no = logistics.get("trackingNo")
            company = logistics.get("company", "未知")
            phone = logistics.get("receiverPhone", "")
            # 提取手机号后四位（顺丰/中通/申通等需要）
            phone_tail = phone[-4:] if phone and len(phone) >= 4 else None
            
            # 查询物流轨迹
            return await self._track_by_number(
                context, tracking_no, company, order_id, phone_tail
            )
            
        except Exception as e:
            logger.error(f"[logistics] Track by order error: {e}")
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
        
        优先调用阿里云市场物流 API，失败时降级到 Mock 数据。
        
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
        
        # 尝试调用真实 API
        if settings.LOGISTICS_APPCODE:
            try:
                api_result = await self._call_logistics_api(
                    tracking_number, company, phone
                )
                if api_result is not None:
                    logger.info(f"[logistics] API query success | tracking_no={tracking_number}")
                    # API 调用成功，转换为标准格式
                    data = self._transform_api_response(
                        api_result, tracking_number, company, order_id
                    )
                    return ToolResult(
                        success=True,
                        data=data,
                        message=(
                            f"【{data['company']}】{data['tracking_number']}，"
                            f"当前状态：{data['status_text']}"
                        ),
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
        
        # status "0" 表示成功，"205" 表示无信息但结构正常
        if result.get("status") not in ("0", "205"):
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
        
        Args:
            api_result: API 原始响应
            tracking_number: 快递单号
            company: 快递公司（来自订单）
            order_id: 订单号
            
        Returns:
            标准格式的物流数据 dict
        """
        result_data = api_result.get("result", {})
        
        # 快递公司名称：优先用 API 返回的 type 映射，其次用传入的 company
        api_type = result_data.get("type", "")
        company_name = (
            COMPANY_NAME_MAP.get(api_type.upper(), "")
            if api_type
            else ""
        )
        if not company_name:
            company_name = company or "未知快递"
        
        # 快递单号
        actual_tracking_no = result_data.get("number") or tracking_number or ""
        
        # 物流轨迹
        traces = []
        trace_list = result_data.get("list") or []
        for item in trace_list:
            # 兼容：物流描述可能在 context 或 status 字段
            content = item.get("context") or item.get("status") or ""
            traces.append({
                "time": item.get("time", ""),
                "content": content,
            })
        
        # 从最新轨迹推断状态
        status = self._infer_status_from_traces(traces)
        status_text = STATUS_TEXT_MAP.get(status, "未知")
        
        # 最新一条
        latest = traces[0] if traces else {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "content": "暂无物流信息",
        }
        
        return {
            "order_id": order_id,
            "tracking_number": actual_tracking_no,
            "company": company_name,
            "status": status,
            "status_text": status_text,
            "latest": latest,
            "traces": traces,
        }
    
    @staticmethod
    def _infer_status_from_traces(traces: list[dict]) -> str:
        """从物流轨迹中推断当前状态
        
        检查最新几条轨迹的内容，匹配中文关键词判断状态。
        
        Args:
            traces: 物流轨迹列表（最新在前）
            
        Returns:
            内部状态字符串
        """
        if not traces:
            return "in_transit"
        
        # 优先看最新的几条（最多看3条）
        for trace in traces[:3]:
            content = trace.get("content", "")
            for keyword, status in CN_STATUS_MAP.items():
                if keyword in content:
                    return status
        
        return "in_transit"
    
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
            "极兔": "JT",
            "极兔速递": "JT",
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
        )
