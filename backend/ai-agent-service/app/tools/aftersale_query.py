"""
AI 智能客服系统 - C端售后工单查询 Tool

Customer-facing aftersale ticket query.
Only allows customers to query their own tickets — customerId always injected from context.
"""
from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


VALID_ACTIONS = {"list", "detail"}


class AftersaleQueryTool(BaseTool):
    """C端售后工单查询 Tool

    Customer queries their own aftersale tickets.
    Always injects customerId from context.user_id for data isolation.

    使用场景：
    - 顾客询问"我的售后工单"
    - 顾客查询某个工单的详情/进度
    """

    name = "aftersale_query"
    description = (
        "【触发】顾客说'我的售后''查工单''退换货进度''投诉处理'时调用。【前置】action: list(查列表)/detail(查详情)。list 支持 status 筛选+pagination。detail 需 ticket_id。【何时不用】查订单用 order_query。创建工单用 aftersale_create。【标注】READONLY — C端查自己的工单"
    )

    allowed_roles = ["customer"]

    read_only = True
    destructive = False
    idempotent = True

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：list（默认，查询工单列表，支持 status/page/size） / detail（查看单个工单详情，需 ticket_id）",
                "enum": ["list", "detail"],
                "default": "list",
            },
            "ticket_id": {
                "type": "string",
                "description": "工单 ID（detail 时必填）",
            },
            "status": {
                "type": "string",
                "description": "工单状态筛选（可选，仅 list 时生效）：pending=待处理, processing=处理中, resolved=已解决, rejected=已拒绝, closed=已关闭",
                "enum": ["pending", "processing", "resolved", "rejected", "closed"],
            },
            "page": {
                "type": "integer",
                "description": "页码，默认 1（仅 list 时生效）",
                "default": 1,
            },
            "size": {
                "type": "integer",
                "description": "每页数量，默认 10（仅 list 时生效）",
                "default": 10,
            },
        },
    }

    async def execute(
        self,
        context: ToolContext,
        action: str = "list",
        ticket_id: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 10,
        **kwargs,
    ) -> ToolResult:
        """执行售后工单查询

        Args:
            context: Tool 执行上下文（customerId 从 context.user_id 注入）
            action: 操作类型 list/detail
            ticket_id: 工单 ID（detail 时必填）
            status: 工单状态筛选（list 时可选）
            page: 页码
            size: 每页数量

        Returns:
            ToolResult: 查询结果
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询售后工单",
                suggestion="请联系客服处理售后问题",
            )

        # 标准化 action
        action = (action or "list").strip().lower()
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message="不支持的操作类型，可选：list / detail",
            )

        try:
            if action == "detail":
                return await self._detail(context, ticket_id)
            return await self._list_tickets(context, status, page, size)

        except Exception as e:
            logger.error(
                f"[aftersale-query] Failed: action={action} "
                f"tenant={context.tenant_id} user={context.user_id} "
                f"error={type(e).__name__}: {e}"
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="查询售后工单失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系客服",
            )

    async def _list_tickets(
        self,
        context: ToolContext,
        status: Optional[str],
        page: int,
        size: int,
    ) -> ToolResult:
        """查询售后工单列表（自动注入 customerId）"""
        page = int(page) if page else 1
        size = int(size) if size else 10

        params: Dict[str, Any] = {
            "page": page,
            "size": size,
            "customerId": str(context.user_id),  # 强制注入，确保只查自己的工单
        }
        if status:
            params["status"] = status

        logger.info(
            f"[aftersale-query] Listing tickets: status={status} page={page} "
            f"tenant={context.tenant_id} user={context.user_id}"
        )

        response = await self._call_admin_api(
            method="GET",
            path="/api/admin/after-sales",
            params=params,
            context=context,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"查询售后工单失败：{error_msg}",
                suggestion="请稍后重试",
            )

        data = response.get("data", {})
        items = data.get("items", [])
        total = data.get("total", 0)

        logger.info(
            f"[aftersale-query] Found {len(items)} tickets, total={total} "
            f"tenant={context.tenant_id}"
        )

        if not items:
            return ToolResult(
                success=True,
                data={"items": [], "total": 0, "page": page, "size": size},
                message="暂无售后工单记录",
                summary="暂无售后工单",
            )

        return ToolResult(
            success=True,
            data={"items": items, "total": total, "page": page, "size": size},
            message=f"共找到 {total} 条售后工单记录",
            summary=f"找到{total}条售后工单",
        )

    async def _detail(
        self,
        context: ToolContext,
        ticket_id: Optional[str],
    ) -> ToolResult:
        """查看售后工单详情"""
        if not ticket_id:
            return ToolResult(
                success=False,
                error="缺少工单ID",
                message="查看工单详情必须提供工单ID（ticket_id）",
                suggestion="请提供要查看的工单ID",
            )

        logger.info(
            f"[aftersale-query] Detail: ticket_id={ticket_id} "
            f"tenant={context.tenant_id} user={context.user_id}"
        )

        response = await self._call_admin_api(
            method="GET",
            path=f"/api/admin/after-sales/{ticket_id}",
            params={"customerId": str(context.user_id)},
            context=context,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"查询工单详情失败：{error_msg}",
                suggestion="请确认工单ID是否正确",
            )

        data = response.get("data", {})
        return ToolResult(
            success=True,
            data=data,
            message=f"工单 {ticket_id} 详情已获取",
            summary=f"工单{ticket_id}详情已获取",
        )

    async def _call_admin_api(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        context: Optional[ToolContext] = None,
    ) -> Dict[str, Any]:
        """调用 admin-api（提取为独立方法，便于测试 mock）

        Args:
            method: HTTP method (GET/POST)
            path: API path
            params: Query params
            json_data: Request body (for POST)
            context: Tool context

        Returns:
            Dict: API response
        """
        client = get_admin_api_client()
        if method.upper() == "POST":
            return await client.post(
                path,
                json_data=json_data,
                tenant_id=context.tenant_id if context else None,
                user_id=context.user_id if context else None,
            )
        else:
            return await client.get(
                path,
                params=params,
                tenant_id=context.tenant_id if context else None,
                user_id=context.user_id if context else None,
            )
