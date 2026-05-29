"""
AI 智能客服系统 - 订单查询 Tool

根据各种条件查询订单，支持订单号、客户手机号、状态、日期等筛选。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client
from app.utils.log_sanitizer import LogSanitizer


# 订单状态中文映射
ORDER_STATUS_TEXT = {
    "pending": "待确认",
    "confirmed": "已确认",
    "processing": "生产中",
    "shipped": "已发货",
    "completed": "已完成",
    "cancelled": "已取消",
}


class OrderQueryTool(BaseTool):
    """订单查询 Tool
    
    根据订单号、客户手机号、状态、日期等条件查询订单列表。
    
    使用场景：
    - 用户询问"我的订单"
    - 用户查询某个订单号的信息
    - 客服按手机号查询客户订单
    - 按状态筛选订单（如"待发货的订单"）
    """
    
    name = "order_query"
    description = (
        "订单查询工具，支持三种操作："
        "action=list（默认，按订单号/手机号/状态/日期等条件翻页查询订单列表）、"
        "action=statistics（订单统计汇总，调用 GET /api/admin/orders/statistics，返回各状态订单总数、订单金额总计等“订单统计数据”）、"
        "action=follow_status_stats（订单跟进状态统计，调用 GET /api/admin/orders/follow-status/stats，返回各跟进状态的订单数量）。"
        " \n常见调用示例：\n"
        "- 查“我的订单”/某个订单号 → action=list, order_no=...\n"
        "- 查某手机号的订单 → action=list, customer_phone=...\n"
        "- 查待发货订单 → action=list, status=confirmed/processing\n"
        "- “订单统计数据”/“订单总览”/“各状态订单数量汇总” → action=statistics\n"
        "- “跟进状态统计”/“订单跟进情况” → action=follow_status_stats\n"
        "当用户说“订单统计数据”请使用 action=statistics，不要错误传 action=list。"
    )
    
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型："
                    "list（默认，订单列表查询，支持 order_no/customer_phone/status/date_from/date_to/page/page_size 参数） / "
                    "statistics（订单统计汇总数据，不接收其他参数，适用于“订单统计数据”“各状态订单汇总”场景） / "
                    "follow_status_stats（订单跟进状态统计，不接收其他参数，适用于“跟进状态统计”场景）"
                ),
                "enum": ["list", "statistics", "follow_status_stats"],
                "default": "list",
            },
            "order_no": {
                "type": "string",
                "description": "订单编号（可选，仅 action=list 时生效）",
            },
            "customer_phone": {
                "type": "string",
                "description": "客户手机号（可选，仅 action=list 时生效）",
            },
            "status": {
                "type": "string",
                "description": "订单状态筛选（可选，仅 action=list 时生效）：pending/confirmed/processing/shipped/completed/cancelled",
                "enum": ["pending", "confirmed", "processing", "shipped", "completed", "cancelled"],
            },
            "date_from": {
                "type": "string",
                "description": "起始日期，格式 YYYY-MM-DD（可选，仅 action=list 时生效）",
            },
            "date_to": {
                "type": "string",
                "description": "截止日期，格式 YYYY-MM-DD（可选，仅 action=list 时生效）",
            },
            "page": {
                "type": "integer",
                "description": "页码，默认 1（仅 action=list 时生效）",
                "default": 1,
            },
            "page_size": {
                "type": "integer",
                "description": "每页数量，默认 10（仅 action=list 时生效）",
                "default": 10,
            },
        },
    }
    
    async def execute(
        self,
        context: ToolContext,
        action: str = "list",
        order_no: Optional[str] = None,
        customer_phone: Optional[str] = None,
        status: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
        # LLM 可能传 order_id 而非 order_no，兼容别名
        order_id: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """执行订单查询

        Args:
            context: Tool 执行上下文
            action: 操作类型 list/statistics/follow_status_stats
            order_no: 订单编号
            customer_phone: 客户手机号
            status: 订单状态
            date_from: 起始日期
            date_to: 截止日期
            page: 页码
            page_size: 每页数量
            order_id: 订单编号（order_no 的别名，兼容 LLM 传参）

        Returns:
            ToolResult: 订单查询结果
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询订单",
            )

        # 兼容 LLM 传入 order_id 作为 order_no 的别名
        if not order_no and order_id:
            order_no = order_id

        # 标准化 action
        action = (action or "list").strip().lower()
        if action not in ("list", "statistics", "follow_status_stats"):
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message="不支持的操作类型，可选：list / statistics / follow_status_stats",
            )

        try:
            if action == "statistics":
                return await self._statistics(context)
            if action == "follow_status_stats":
                return await self._follow_status_stats(context)

            # action == "list"
            # 强制转换分页参数为 int（LLM 可能传字符串）
            page = int(page) if page else 1
            page_size = int(page_size) if page_size else 10
            return await self._list_orders(
                context,
                order_no=order_no,
                customer_phone=customer_phone,
                status=status,
                date_from=date_from,
                date_to=date_to,
                page=page,
                page_size=page_size,
            )
        except Exception as e:
            logger.error(f"[order-query] Query failed | tenant={context.tenant_id} error={type(e).__name__}: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                message="查询订单时出错，请稍后重试",
            )

    async def _statistics(self, context: ToolContext) -> ToolResult:
        """获取订单统计汇总数据"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/orders/statistics",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message="订单统计查询失败，请稍后重试",
            )
        data = response.get("data", {})
        logger.info(f"[order-query] Statistics fetched | tenant={context.tenant_id}")
        return ToolResult(
            success=True,
            data=data,
            message="订单统计数据已获取",
        )

    async def _follow_status_stats(self, context: ToolContext) -> ToolResult:
        """获取订单跟进状态统计数据"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/orders/follow-status/stats",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message="订单跟进状态统计查询失败，请稍后重试",
            )
        data = response.get("data", {})
        logger.info(f"[order-query] Follow-status stats fetched | tenant={context.tenant_id}")
        return ToolResult(
            success=True,
            data=data,
            message="订单跟进状态统计数据已获取",
        )

    async def _list_orders(
        self,
        context: ToolContext,
        order_no: Optional[str],
        customer_phone: Optional[str],
        status: Optional[str],
        date_from: Optional[str],
        date_to: Optional[str],
        page: int,
        page_size: int,
    ) -> ToolResult:
        """执行订单列表查询"""
        # 查询开始日志
        if customer_phone:
            logger.info(f"[order-query] Querying by phone: {LogSanitizer.mask_phone(customer_phone)} | tenant={context.tenant_id}")
        elif order_no:
            logger.info(f"[order-query] Querying by order_no: {order_no} | tenant={context.tenant_id}")
        else:
            logger.info(f"[order-query] Querying orders: status={status} | tenant={context.tenant_id}")

        # 构建查询参数
        params: Dict[str, Any] = {
            "page": page,
            "size": page_size,
        }

        if order_no:
            params["orderNo"] = order_no
        if customer_phone:
            params["customerPhone"] = customer_phone
        if status:
            params["status"] = status
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to

        # 调用 admin-api
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/orders",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        # 解析响应
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message="订单查询失败，请稍后重试",
            )

        data = response.get("data", {})
        records = data.get("items", [])
        total = data.get("total", 0)

        # 验证响应数据的 tenant_id，过滤不属于当前租户的记录
        verified_records = []
        filtered_count = 0
        for record in records:
            resp_tenant_id = record.get("tenantId") or record.get("tenant_id")
            if resp_tenant_id is not None and str(resp_tenant_id) != str(context.tenant_id):
                logger.error(
                    f"Tenant data integrity violation in order_query: "
                    f"response tenant_id={resp_tenant_id}, expected={context.tenant_id}"
                )
                filtered_count += 1
                continue
            verified_records.append(record)

        if filtered_count > 0:
            logger.warning(
                f"Order query filtered {filtered_count} records due to tenant_id mismatch, "
                f"tenant={context.tenant_id}"
            )
            total = max(0, total - filtered_count)

        # 格式化订单列表
        orders = self._format_orders(verified_records)

        logger.info(
            f"[order-query] Found {len(orders)} orders, total={total} | tenant={context.tenant_id}"
        )

        if not orders:
            return ToolResult(
                success=True,
                data={"orders": [], "total": 0, "page": page, "page_size": page_size},
                message="未找到符合条件的订单",
            )

        return ToolResult(
            success=True,
            data={
                "orders": orders,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size,
            },
            message=f"找到 {total} 个相关订单",
        )
    
    def _format_orders(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """格式化订单列表
        
        Args:
            records: 原始订单记录
            
        Returns:
            List: 格式化后的订单列表
        """
        orders = []
        for record in records:
            status = record.get("status", "")
            order = {
                "id": record.get("id"),
                "order_no": record.get("orderNo"),
                "customer_name": record.get("customerName"),
                "customer_phone": record.get("customerPhone"),
                "total_amount": record.get("totalAmount"),
                "status": status,
                "status_text": ORDER_STATUS_TEXT.get(status, status),
                "items_count": len(record.get("items", [])),
                "logistics": record.get("logistics"),
                "created_at": record.get("createdAt"),
                "updated_at": record.get("updatedAt"),
            }
            orders.append(order)
        
        return orders
