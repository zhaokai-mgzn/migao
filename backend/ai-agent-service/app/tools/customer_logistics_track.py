"""
AI 智能客服系统 - C 端"查物流" Tool（小布专用）

与 B 端 logistics_track 物理隔离，落实 C 端物流查询两条铁律：
1. **不支持顾客提供快递单号直接查询**：本工具无 tracking_number 参数，
   LLM 即使传了也会被拒绝——物流轨迹只从「用户名下的订单」关联获取。
2. **只能查询当前用户「在途（已发货）」订单的物流**：
   - 先调用 admin-api C 端专用端点 GET /api/admin/agent/orders/mine?status=shipped
     （后端强制按当前登录用户过滤，列表内订单必然属于该用户）
   - 再对每个在途订单取详情中的物流单号/快递公司，查询轨迹

轨迹查询复用 B 端 LogisticsTrackTool 的 API 调用 + Mock 降级逻辑，不重复实现。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.tools.logistics_track import LogisticsTrackTool
from app.utils.http_client import get_admin_api_client
from app.utils.log_sanitizer import LogSanitizer

# 订单状态中文映射（与 OrderService 状态机对齐；本工具只处理 shipped=已发货/在途）
ORDER_STATUS_TEXT = {
    "pending": "待付款",
    "confirmed": "已确认（待发货）",
    "producing": "生产中",
    "shipped": "已发货",
    "completed": "已完成",
    "cancelled": "已取消",
}

# 单次最多处理的在途订单数（每个订单需要 1 次详情 + 1 次轨迹查询，防止 N+1 放大）
MAX_TRACKED_ORDERS = 5


class CustomerLogisticsTrackTool(BaseTool):
    """C 端"查物流" Tool（小布专用）

    仅查询当前登录顾客「已发货（在途）」订单的物流信息；
    不支持按快递单号直接查询，不支持跨用户查询，纯只读。
    """

    name = "customer_logistics_track"

    description = (
        "【触发】C 端顾客问'物流''快递''到哪了''发货了吗''配送''签收'时调用。"
        "【前置】无需任何参数，默认列出顾客本人所有在途（已发货）订单的物流；"
        "可选 order_id 缩小到某一笔在途订单。"
        "【铁律】本工具只查顾客本人已发货订单的物流——顾客提供快递单号要求直接查询时，"
        "礼貌拒绝并解释只能查其名下订单的物流，不要调用本工具也不要编造物流信息。"
        "【反例】查订单状态/列表用 customer_order_query；商户员工查物流用 logistics_track。"
        "【标注】READONLY — 结果由系统强制按用户过滤并按状态过滤（仅 shipped），无法越权"
    )

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：list（默认，列出当前用户所有在途订单的物流）",
                "enum": ["list"],
                "default": "list",
            },
            "order_id": {
                "type": "string",
                "description": "订单ID或订单号（可选，必须是当前用户已发货的在途订单；传其他订单会被拒绝）",
            },
        },
    }

    # 物理隔离：仅 C 端顾客可用；商户员工/管理员一律拒绝（用 B 端 logistics_track）
    allowed_roles = ["customer"]
    read_only = True
    read_only_actions = frozenset({"list"})

    def __init__(self) -> None:
        # 复用 B 端轨迹查询逻辑（阿里云 API + Mock 降级），避免重复实现
        self._tracker = LogisticsTrackTool()

    async def execute(
        self,
        context: ToolContext,
        action: str = "list",
        order_id: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """执行"查物流"（强制用户级隔离 + 仅限在途订单 + 拒绝物流号直查）"""
        # 权限检查（customer 角色；非 customer 直接拒绝）
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="该查询仅限顾客本人使用，请联系人工客服",
                suggestion="如您是商家员工，请使用商家后台的物流查询功能",
            )

        # 用户标识硬校验：缺失即拒绝（后端同样会拒绝，这里提前拦截便于 LLM 引导）
        if not str(context.user_id).strip() or str(context.user_id).strip() in ("internal-service", "dev_user"):
            return ToolResult(
                success=False,
                error="缺少用户标识",
                message="无法查询物流：缺少用户身份信息",
                suggestion="请重新登录后再试",
            )

        action = (action or "list").strip().lower()
        if action not in ("list",):
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message="不支持的操作类型，可选：list",
            )

        # 铁律 1：拒绝快递单号直查（无论 LLM 通过哪个参数传入）
        tracking_number = kwargs.get("tracking_number") or kwargs.get("tracking_no") or kwargs.get("track_no")
        if tracking_number:
            logger.info(
                f"[customer-logistics] Rejected direct tracking-number query "
                f"| tenant={context.tenant_id} user={LogSanitizer.mask_phone(context.user_id)}"
            )
            return ToolResult(
                success=False,
                error="不支持快递单号查询",
                message="抱歉，我不能根据快递单号直接查询物流～您可以告诉我订单，我帮您查名下在途订单的物流哦",
                suggestion="引导顾客选择其名下的一笔在途订单（可用 customer_order_query 列出），"
                           "再调用本工具（不带 tracking_number）查询",
            )

        try:
            return await self._list_my_in_transit_logistics(
                context, order_id=order_id
            )
        except Exception as e:
            logger.error(
                f"[customer-logistics] Failed | tenant={context.tenant_id} "
                f"user={LogSanitizer.mask_phone(context.user_id)} error={type(e).__name__}: {e}",
                exc_info=True,
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="查询物流时出错，请稍后重试",
                suggestion="请稍后重试",
            )

    async def _list_my_in_transit_logistics(
        self,
        context: ToolContext,
        order_id: Optional[str],
    ) -> ToolResult:
        """列出当前用户所有在途（shipped）订单的物流信息

        Args:
            context: Tool 执行上下文
            order_id: 可选缩小范围（必须是本人已发货订单）

        Returns:
            ToolResult: 物流列表结果
        """
        client = get_admin_api_client()

        # 铁律 2：只从"我的订单"（后端强制按用户过滤）中取已发货订单
        response = await client.get(
            "/api/admin/agent/orders/mine",
            params={"status": "shipped", "page": 1, "size": 20},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            logger.info(
                f"[customer-logistics] Mine list rejected | tenant={context.tenant_id} "
                f"error={error_msg}"
            )
            return ToolResult(
                success=False,
                error=error_msg,
                message="物流查询失败，请稍后重试",
                suggestion="请稍后重试，或联系人工客服帮您查询",
            )

        data = response.get("data", {})
        records = data.get("items", []) or []
        total = data.get("total", len(records))

        if not records:
            return ToolResult(
                success=True,
                data={"logistics": None, "logistics_list": [], "total": 0},
                message="您暂时没有在途的订单～订单发货后我就能帮您跟踪物流啦",
                summary="没有在途订单",
            )

        # 可选：缩小到指定订单（必须在本人在途订单列表中，否则拒绝）
        if order_id:
            narrowed = [
                r for r in records
                if str(r.get("id", "")) == str(order_id)
                or str(r.get("orderNo", "")) == str(order_id)
            ]
            if not narrowed:
                return ToolResult(
                    success=False,
                    error="订单不在在途订单中",
                    message="该订单不在您的在途订单中，无法查询物流",
                    suggestion="用 customer_order_query 列出顾客的在途订单，让顾客选择后再查",
                )
            records = narrowed

        # 逐单取物流：详情 → trackingNo/company → 轨迹
        logistics_list: List[Dict[str, Any]] = []
        for record in records[:MAX_TRACKED_ORDERS]:
            item = await self._track_order_logistics(context, client, record)
            if item is not None:
                logistics_list.append(item)

        if not logistics_list:
            return ToolResult(
                success=True,
                data={"logistics": None, "logistics_list": [], "total": 0},
                message="您的在途订单暂未查询到物流轨迹，请稍后再试或联系人工客服",
                summary="在途订单暂无可查物流轨迹",
            )

        first = logistics_list[0]
        return ToolResult(
            success=True,
            data={
                "logistics": first,          # 卡片数据：取第一笔在途订单的物流（扁平结构）
                "logistics_list": logistics_list,
                "total": len(logistics_list),
                "all_in_transit_total": total,  # 顾客全部在途订单数（含未展示的）
            },
            message=self._build_message(logistics_list, total),
            summary=self._build_summary(logistics_list, total),
        )

    async def _track_order_logistics(
        self,
        context: ToolContext,
        client: Any,
        record: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """查询单个订单的物流轨迹（返回扁平结构，查不到返回 None）"""
        order_uuid = record.get("id")
        order_no = record.get("orderNo") or order_uuid
        if not order_uuid:
            return None

        try:
            detail_response = await client.get(
                f"/api/admin/orders/{order_uuid}",
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.warning(
                f"[customer-logistics] Order detail failed | order={order_no} "
                f"error={type(e).__name__}: {e}"
            )
            return None

        if not detail_response.get("success"):
            logger.warning(
                f"[customer-logistics] Order detail rejected | order={order_no} "
                f"error={detail_response.get('error', {}).get('message', '')}"
            )
            return None

        order = detail_response.get("data", {}) or {}

        # 防御纵深：详情里的 customerId 若存在且与当前用户不符 → 拒绝（不应发生，列表已按用户过滤）
        order_customer_id = (
            order.get("customerId")
            or order.get("customer_id")
            or order.get("userId")
        )
        if order_customer_id is not None and str(order_customer_id) != str(context.user_id):
            logger.error(
                f"[customer-logistics] Ownership mismatch | order={order_no} "
                f"detail_customer={order_customer_id} expected={context.user_id}"
            )
            return None

        logistics = order.get("logistics") or {}
        tracking_no = logistics.get("trackingNo") or logistics.get("tracking_no")
        if not tracking_no:
            # 已发货但无物流单号（异常数据）→ 跳过，不编造
            logger.warning(
                f"[customer-logistics] Shipped order without trackingNo | order={order_no}"
            )
            return None

        company = logistics.get("logisticsCompany") or logistics.get("company") or "未知"

        # 顺丰/中通/申通等需「运单号:收件人手机后4位」：取订单根级 customerPhone 末 4 位
        # （与 B 端 logistics_track 同规则，保证此类快递不降级 mock）
        phone_tail = None
        order_phone = order.get("customerPhone") or order.get("customer_phone")
        if order_phone and len(str(order_phone).strip()) >= 4:
            phone_tail = str(order_phone).strip()[-4:]

        track_result = await self._tracker._track_by_number(
            context, tracking_no, company, order_id=order_no, phone=phone_tail
        )
        if not track_result.success or not track_result.data:
            return None

        tdata = track_result.data
        return {
            "order_id": order_uuid,
            "order_no": order_no,
            "tracking_number": tdata.get("tracking_number"),
            "company": tdata.get("company"),
            "status": tdata.get("status"),
            "status_text": tdata.get("status_text"),
            "latest": tdata.get("latest"),
            "traces": tdata.get("traces") or [],
        }

    def _build_message(self, logistics_list: List[Dict[str, Any]], all_total: int) -> str:
        """生成面向顾客的汇总文案"""
        lines = []
        for item in logistics_list:
            lines.append(
                f"订单 {item['order_no']}：{item.get('company', '快递')} "
                f"{item.get('tracking_number', '')}，当前{item.get('status_text', '运输中')}"
            )
        head = "为您查到 " + ("、".join(i["order_no"] for i in logistics_list))
        tail = "。您可以继续问我某笔订单的物流轨迹详情～"
        if all_total > len(logistics_list):
            tail = f"。您共 {all_total} 笔在途订单，先展示其中 {len(logistics_list)} 笔～"
        return head + "：" + "；".join(lines) + tail

    def _build_summary(self, logistics_list: List[Dict[str, Any]], all_total: int) -> str:
        """LLM 友好摘要"""
        nos = "、".join(i["order_no"] for i in logistics_list[:3])
        if len(logistics_list) > 3:
            nos += "等"
        return f"在途订单物流 {len(logistics_list)} 笔(共{all_total}笔): {nos}"
