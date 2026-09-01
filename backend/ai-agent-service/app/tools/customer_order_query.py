"""
AI 智能客服系统 - C 端"我的订单"查询 Tool（小布专用）

与 B 端 order_query 物理隔离：
- 仅 customer 角色可用（allowed_roles=["customer"]，商户员工不可用）
- 无论 LLM 传什么参数，都强制按当前登录用户（context.user_id）过滤，
  调用 admin-api 的 C 端专用端点 GET /api/admin/agent/orders/mine（后端同样强制按用户过滤）
- 不支持 keyword/receiver 等模糊搜索（避免跨用户试探），仅支持状态筛选 + 分页
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client
from app.utils.log_sanitizer import LogSanitizer


# 订单状态中文映射（与后端 OrderService 状态机对齐：producing = 生产中）
ORDER_STATUS_TEXT = {
    "pending": "待付款",
    "confirmed": "已确认（待发货）",
    "producing": "生产中",
    "shipped": "已发货",
    "completed": "已完成",
    "cancelled": "已取消",
}


class CustomerOrderQueryTool(BaseTool):
    """C 端"我的订单"查询 Tool（小布专用，强制用户级隔离）

    仅查询当前登录用户的订单；不支持跨用户搜索，不支持任何写操作。
    """

    name = "customer_order_query"

    description = (
        "【触发】C 端顾客查询自己的订单时调用：'我的订单''查订单''订单到哪了''ORD-单号'。"
        "【前置】action: list(分页)。【参数】list 支持 status(状态筛选)/page(页码)/page_size(每页数量)。"
        "【何时不用】顾客问物流用 customer_logistics_track；商户员工查询/管理订单用 order_query/order_manage。"
        "【标注】READONLY — 仅查询当前登录顾客自己的订单，结果由系统强制按用户过滤，无需也无法传用户标识"
    )

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：list（默认，当前用户订单列表分页查询）",
                "enum": ["list"],
                "default": "list",
            },
            "status": {
                "type": "string",
                "description": "订单状态筛选（可选）：pending=待付款, confirmed=已确认, producing=生产中, shipped=已发货, completed=已完成, cancelled=已取消",
                "enum": ["pending", "confirmed", "producing", "shipped", "completed", "cancelled"],
            },
            "page": {
                "type": "integer",
                "description": "页码，默认 1",
                "default": 1,
            },
            "page_size": {
                "type": "integer",
                "description": "每页数量，默认 10",
                "default": 10,
            },
        },
    }

    # 物理隔离：仅 C 端顾客可用；商户员工/管理员一律拒绝（用 B 端 order_query）
    allowed_roles = ["customer"]

    async def execute(
        self,
        context: ToolContext,
        action: str = "list",
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
        **kwargs,
    ) -> ToolResult:
        """执行"我的订单"查询（强制按当前用户过滤）"""
        # 权限检查（customer 角色；非 customer 直接拒绝）
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="该查询仅限顾客本人使用，请联系人工客服",
                suggestion="如您是商家员工，请使用商家后台的订单管理功能",
            )

        # 用户标识硬校验：缺失即拒绝（后端同样会拒绝，这里提前拦截便于 LLM 引导）
        if not str(context.user_id).strip() or str(context.user_id).strip() in ("internal-service", "dev_user"):
            return ToolResult(
                success=False,
                error="缺少用户标识",
                message="无法查询订单：缺少用户身份信息",
                suggestion="请重新登录后再试",
            )

        action = (action or "list").strip().lower()
        if action not in ("list",):
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message="不支持的操作类型，可选：list",
            )

        # 分页参数强制 int（LLM 可能传字符串）
        try:
            page = int(page) if page else 1
            page_size = int(page_size) if page_size else 10
            page_size = min(max(page_size, 1), 50)
        except (ValueError, TypeError):
            page, page_size = 1, 10

        try:
            return await self._list_my_orders(context, status=status, page=page, page_size=page_size)
        except Exception as e:
            logger.error(
                f"[customer-order-query] Failed | tenant={context.tenant_id} "
                f"user={LogSanitizer.mask_phone(context.user_id)} error={type(e).__name__}: {e}",
                exc_info=True,
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="查询订单时出错，请稍后重试",
                suggestion="请稍后重试",
            )

    async def _list_my_orders(
        self,
        context: ToolContext,
        status: Optional[str],
        page: int,
        page_size: int,
    ) -> ToolResult:
        """执行当前用户订单列表查询（调用 C 端专用端点，强制按用户过滤）"""
        params: Dict[str, Any] = {
            "page": page,
            "size": page_size,
        }
        if status:
            params["status"] = status

        # 调用 admin-api C 端专用端点 /api/admin/agent/orders/mine
        # （后端从 X-User-Id 强制按当前用户过滤，即使此处不传 userId 也无法越权）
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/agent/orders/mine",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            logger.info(
                f"[customer-order-query] Query rejected | tenant={context.tenant_id} "
                f"error={error_msg}"
            )
            return ToolResult(
                success=False,
                error=error_msg,
                message="订单查询失败，请稍后重试",
                suggestion="请稍后重试，或联系人工客服帮您查询",
            )

        data = response.get("data", {})
        records = data.get("items", [])
        total = data.get("total", 0)

        orders = self._format_orders(records)

        if not orders:
            return ToolResult(
                success=True,
                data={"orders": [], "total": 0, "page": page, "page_size": page_size},
                message="您暂时没有相关订单",
                summary="您暂时没有相关订单",
            )

        top_nos = [o["order_no"] for o in orders[:3] if o.get("order_no")]
        nos_str = "、".join(top_nos)
        if len(orders) > 3:
            nos_str += "等"

        return ToolResult(
            success=True,
            data={
                "orders": orders,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size,
            },
            message=f"为您找到 {total} 个订单",
            summary=f"找到{total}个订单: {nos_str}",
        )

    def _format_orders(self, records: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        """格式化订单列表（与 B 端 order_query 一致，含商品明细摘要）"""
        orders = []
        for record in records:
            status = record.get("status", "")
            raw_items = record.get("items", [])
            items = []
            for item in raw_items:
                unit_price = item.get("unitPrice")
                quantity = item.get("quantity")
                amount = item.get("amount") or item.get("subtotal")
                if amount is None and unit_price is not None and quantity is not None:
                    try:
                        amount = float(unit_price) * int(quantity)
                    except (ValueError, TypeError):
                        amount = 0
                items.append({
                    "product_name": item.get("productName"),
                    "product_code": item.get("productCode"),
                    "unit_price": unit_price,
                    "quantity": quantity,
                    "amount": amount,
                })

            order = {
                "id": record.get("id"),
                "order_no": record.get("orderNo"),
                "customer_name": record.get("customerName"),
                "customer_phone": record.get("customerPhone"),
                "total_amount": record.get("totalAmount"),
                "status": status,
                "status_text": ORDER_STATUS_TEXT.get(status, status),
                "items_count": len(items),
                "items": items,
                "created_at": record.get("createdAt"),
            }
            orders.append(order)
        return orders
