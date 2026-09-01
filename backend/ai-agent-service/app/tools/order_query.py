"""
AI 智能客服系统 - 订单查询 Tool

根据各种条件查询订单，支持关键词、订单号、收货人、状态、日期等筛选。

筛选参数与后端 OrderController（GET /api/admin/orders）对齐：
keyword（通用关键词：客户姓名/手机号/订单号）/ orderId（订单号精确搜索）/
receiver（收货人姓名或手机号）/ status / startDate / endDate。
"""

from typing import Any, Dict, List, Optional
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


class OrderQueryTool(BaseTool):
    """订单查询 Tool
    
    根据关键词、订单号、收货人、状态、日期等条件查询订单列表。
    
    使用场景：
    - 用户询问"我的订单"
    - 用户查询某个订单号的信息
    - 客服按手机号/姓名查询客户订单
    - 按状态筛选订单（如"待发货的订单""生产中的订单"）
    """
    
    name = "order_query"
    description = (
        "【触发】查具体订单：用户说'查订单''我的订单''ORD-单号''待发货''某客户订单'时调用。【前置】action: list(翻页)/statistics(汇总)/follow_status_stats(跟进统计)。【参数】list 支持 keyword(关键词)/order_id(订单号)/receiver(收货人姓名或手机号)/status/start_date/end_date。【何时不用】经营看板的趋势/分布/概览用 dashboard_stats。查物流用 logistics_track。修改用 order_manage。【标注】READONLY — 查具体订单，经营分析用 dashboard_stats"
    )
    
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型："
                    "list（默认，订单列表查询，支持 keyword/order_id/receiver/status/start_date/end_date/page/page_size 参数） / "
                    "statistics（订单统计汇总数据，不接收其他参数，适用于“订单统计数据”“各状态订单汇总”场景） / "
                    "follow_status_stats（订单跟进状态统计，不接收其他参数，适用于“跟进状态统计”场景）"
                ),
                "enum": ["list", "statistics", "follow_status_stats"],
                "default": "list",
            },
            "keyword": {
                "type": "string",
                "description": "通用关键词（可选，仅 action=list 时生效）：匹配客户姓名/手机号/订单号",
            },
            "order_id": {
                "type": "string",
                "description": "订单号精确搜索（可选，仅 action=list 时生效，如 ORD-xxx）",
            },
            "receiver": {
                "type": "string",
                "description": "收货人姓名或手机号（可选，仅 action=list 时生效）",
            },
            "status": {
                "type": "string",
                "description": "订单状态筛选（可选，仅 action=list 时生效）：pending=待付款, confirmed=已确认（待发货）, producing=生产中, shipped=已发货, completed=已完成, cancelled=已取消",
                "enum": ["pending", "confirmed", "producing", "shipped", "completed", "cancelled"],
            },
            "start_date": {
                "type": "string",
                "description": "起始日期，格式 YYYY-MM-DD（可选，仅 action=list 时生效）",
            },
            "end_date": {
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
        keyword: Optional[str] = None,
        order_id: Optional[str] = None,
        receiver: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
        **kwargs,
    ) -> ToolResult:
        """执行订单查询

        Args:
            context: Tool 执行上下文
            action: 操作类型 list/statistics/follow_status_stats
            keyword: 通用关键词（客户姓名/手机号/订单号）
            order_id: 订单号（精确搜索）
            receiver: 收货人姓名或手机号
            status: 订单状态
            start_date: 起始日期
            end_date: 截止日期
            page: 页码
            page_size: 每页数量

        Returns:
            ToolResult: 订单查询结果
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询订单",
                suggestion="请联系管理员获取订单查询权限",
            )

        # 旧参数名兼容归一化：order_no/customer_phone/date_from/date_to 是历史 LLM
        # 可能传的旧名，后端 OrderController 不接收 orderNo/customerPhone/dateFrom/dateTo，
        # 直接透传会静默失效（报"查到 N 单"实为全量分页）。此处归一化到后端支持的参数。
        if not order_id and kwargs.get("order_no"):
            order_id = kwargs["order_no"]
        if not receiver and kwargs.get("customer_phone"):
            receiver = kwargs["customer_phone"]
        if not start_date and kwargs.get("date_from"):
            start_date = kwargs["date_from"]
        if not end_date and kwargs.get("date_to"):
            end_date = kwargs["date_to"]

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
                keyword=keyword,
                order_id=order_id,
                receiver=receiver,
                status=status,
                start_date=start_date,
                end_date=end_date,
                page=page,
                page_size=page_size,
            )
        except Exception as e:
            logger.error(f"[order-query] Query failed | tenant={context.tenant_id} error={type(e).__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="查询订单时出错，请稍后重试",
                suggestion="请检查查询条件是否正确，或稍后重试",
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
                suggestion="请检查参数是否正确，或稍后重试",
            )
        data = response.get("data", {})
        logger.info(f"[order-query] Statistics fetched | tenant={context.tenant_id}")
        # 后端 OrderStatisticsResponse 字段：totalCount/pendingCount/confirmedCount/
        # producingCount/shippedCount/completedCount/cancelledCount（+unpaid/paid/refunded）
        total_count = data.get("totalCount")
        if total_count is None:
            return ToolResult(
                success=True,
                data=data,
                message="订单统计数据已获取",
                summary="订单统计: N/A",
            )
        status_parts = []
        for key, label in (
            ("pendingCount", "待付款"),
            ("confirmedCount", "待发货"),
            ("producingCount", "生产中"),
            ("shippedCount", "已发货"),
            ("completedCount", "已完成"),
            ("cancelledCount", "已取消"),
        ):
            val = data.get(key)
            if val is not None:
                status_parts.append(f"{label}{val}")
        status_text = "、".join(status_parts) if status_parts else "无明细"
        return ToolResult(
            success=True,
            data=data,
            message="订单统计数据已获取",
            summary=f"订单统计: 共{total_count}单（{status_text}）",
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
                suggestion="请检查参数是否正确，或稍后重试",
            )
        data = response.get("data", {})
        logger.info(f"[order-query] Follow-status stats fetched | tenant={context.tenant_id}")
        # 构建摘要：汇总各跟进状态的数量（key 用中文业务术语，避免英文枚举流入用户可见回复）
        total_count = data.get("totalCount") or sum(
            v for k, v in (data or {}).items() if isinstance(v, (int, float)) and k != "totalCount"
        )
        FOLLOW_STATUS_LABELS = {
            "pending": "待跟进",
            "following": "跟进中",
            "processing": "跟进中",  # 兼容历史 key
            "completed": "已跟进",
            "totalCount": "总数",
        }
        summary_parts = [
            f"{FOLLOW_STATUS_LABELS.get(k, k)}:{v}"
            for k, v in (data or {}).items()
            if isinstance(v, (int, float))
        ]
        summary_text = "、".join(summary_parts[:5]) if summary_parts else "无数据"
        return ToolResult(
            success=True,
            data=data,
            message="订单跟进状态统计数据已获取",
            summary=f"订单跟进状态: {summary_text}",
        )

    async def _list_orders(
        self,
        context: ToolContext,
        keyword: Optional[str],
        order_id: Optional[str],
        receiver: Optional[str],
        status: Optional[str],
        start_date: Optional[str],
        end_date: Optional[str],
        page: int,
        page_size: int,
    ) -> ToolResult:
        """执行订单列表查询"""
        # Gap-4 安全加固: customer 角色必须有 user_id 才能查询
        if context.role == "customer" and not str(context.user_id).strip():
            return ToolResult(
                success=False,
                error="缺少用户标识",
                message="无法查询订单：缺少用户身份信息",
                suggestion="请重新登录后再试",
            )

        # 查询开始日志
        if keyword:
            logger.info(f"[order-query] Querying by keyword: {LogSanitizer.mask_phone(keyword)} | tenant={context.tenant_id}")
        elif order_id:
            logger.info(f"[order-query] Querying by order_id: {order_id} | tenant={context.tenant_id}")
        else:
            logger.info(f"[order-query] Querying orders: status={status} | tenant={context.tenant_id}")

        # 构建查询参数（与后端 OrderController.getOrders 支持的参数一一对应：
        # page/size/status/keyword/followStatus/hasProcessing/startDate/endDate/orderId/receiver）
        params: Dict[str, Any] = {
            "page": page,
            "size": page_size,
        }

        if status:
            params["status"] = status
        if keyword:
            params["keyword"] = keyword
        if order_id:
            params["orderId"] = order_id
        if receiver:
            params["receiver"] = receiver
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date

        # 调用 admin-api（租户隔离由后端 TenantLineInnerInterceptor 在 SQL 层保证，
        # Agent 通过 tenant_id header 传递租户上下文，客户端不再伪造过滤）
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
                suggestion="请稍后重试，或尝试输入订单号精确查询",
            )

        data = response.get("data", {})
        records = data.get("items", [])
        total = data.get("total", 0)

        # 格式化订单列表
        orders = self._format_orders(records)

        logger.info(
            f"[order-query] Found {len(orders)} orders, total={total} | tenant={context.tenant_id}"
        )

        if not orders:
            return ToolResult(
                success=True,
                data={"orders": [], "total": 0, "page": page, "page_size": page_size},
                message="未找到符合条件的订单",
                summary="未找到符合条件的订单",
            )

        # 构建摘要：取前3个订单号
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
            message=f"找到 {total} 个相关订单",
            summary=f"找到{total}个订单: {nos_str}",
        )
    
    def _format_orders(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """格式化订单列表，包含商品明细

        Args:
            records: 原始订单记录

        Returns:
            List: 格式化后的订单列表
        """
        orders = []
        for record in records:
            status = record.get("status", "")
            # 格式化商品明细
            raw_items = record.get("items", [])
            items = []
            for item in raw_items:
                unit_price = item.get("unitPrice")
                quantity = item.get("quantity")
                amount = item.get("amount") or item.get("subtotal")
                # amount 兜底计算
                if amount is None and unit_price is not None and quantity is not None:
                    try:
                        amount = float(unit_price) * int(quantity)
                    except (ValueError, TypeError):
                        amount = 0

                # 提取销售信息：颜色、售卖方式、门幅、SKU
                pi = item.get("processingInfo") or {}
                sales_info = {}
                if isinstance(pi, dict):
                    if pi.get("colorName"):
                        sales_info["颜色"] = pi["colorName"]
                    if pi.get("sellingMethod"):
                        SM = {"bulk_cut": "散剪", "full_roll": "整卷", "per_meter": "按米", "per_piece": "按件"}
                        sales_info["售卖方式"] = SM.get(pi["sellingMethod"], pi["sellingMethod"])
                    if pi.get("doorWidth"):
                        sales_info["门幅"] = pi["doorWidth"]
                    if pi.get("skuCode"):
                        sales_info["SKU编码"] = pi["skuCode"]
                    # 加工费
                    pf = pi.get("processingFee")
                    if pf is not None and float(pf) > 0:
                        sales_info["加工费"] = f"¥{float(pf):.2f}"

                items.append({
                    "product_name": item.get("productName"),
                    "product_code": item.get("productCode"),
                    "销售信息": sales_info if sales_info else None,
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
                "logistics": record.get("logistics"),
                "created_at": record.get("createdAt"),
                "updated_at": record.get("updatedAt"),
            }
            orders.append(order)

        return orders
