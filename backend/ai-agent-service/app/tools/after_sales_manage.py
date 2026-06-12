"""
AI 智能客服系统 - 售后工单管理 Tool

管理售后工单,支持查询列表 详情 创建工单 更新工单状态。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"list", "detail", "create", "update_status"}

# 工单类型
VALID_TICKET_TYPES = {"refund", "exchange", "repair", "complaint", "other"}

# 工单状态
VALID_TICKET_STATUSES = {"pending", "processing", "resolved", "rejected", "closed"}


class AfterSalesManageTool(BaseTool):
    """售后工单管理 Tool

    管理售后工单:查询列表 查看详情 创建工单 更新状态。

    使用场景:
    - 查询售后工单列表,按状态或类型筛选
    - 查看某个售后工单的详细信息
    - 为订单创建售后工单(退款 换货 维修等)
    - 更新售后工单状态(处理中 已解决 已拒绝等)
    """

    name = "after_sales_manage"
    description = """售后工单管理。创建工单(action="create")收集齐后确认再调用。可用字段:
- ticket_type(string,必填): 工单类型 refund/exchange/repair/complaint/other
- order_id(string,必填): 关联订单ID
- reason(string,必填): 原因说明
- description(string): 详细描述
- images(string[]数组): 凭证图片URL列表
- priority(string): 优先级 normal/urgent/critical
- refund_amount(number): 退款金额(退款类型时填写)

查询(action="list"): keyword/status/ticket_type/page/size 可选
详情(action="detail"): ticket_id 必填
更新状态(action="update_status"): ticket_id+status 必填

铁律: 收集->确认->执行。确认词:"确认创建""确认""好的""行""可以"。"""

    allowed_roles = ["admin", "agent", "tenant_admin"]

    read_only = False
    destructive = True   # 可关闭/拒绝工单（不可逆）
    idempotent = False   # 创建/状态变更非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型:list(查询列表)/ detail(查看详情)/ create(创建工单)/ update_status(更新状态)",
                "enum": ["list", "detail", "create", "update_status"],
            },
            "ticket_id": {
                "type": "string",
                "description": "工单 ID(detail/update_status 时必填)",
            },
            "order_id": {
                "type": "string",
                "description": "关联订单 ID(create 时必填)",
            },
            "ticket_type": {
                "type": "string",
                "description": "工单类型:refund(退款)/ exchange(换货)/ repair(维修)/ complaint(投诉)/ other(其他)",
                "enum": ["refund", "exchange", "repair", "complaint", "other"],
            },
            "status": {
                "type": "string",
                "description": "工单状态:pending(待处理)/ processing(处理中)/ resolved(已解决)/ rejected(已拒绝)/ closed(已关闭)",
                "enum": ["pending", "processing", "resolved", "rejected", "closed"],
            },
            "reason": {
                "type": "string",
                "description": "原因说明(create 时必填,如'客户反馈尺寸不符要求退款')",
            },
            "description": {
                "type": "string",
                "description": "详细问题描述(create 时可选)",
            },
            "images": {
                "type": "array",
                "description": "凭证图片URL列表(可选)",
                "items": {"type": "string"},
            },
            "priority": {
                "type": "string",
                "description": "优先级(可选,默认normal)",
                "enum": ["normal", "urgent", "critical"],
            },
            "refund_amount": {
                "type": "number",
                "description": "退款金额(退款类型时填写)",
            },
            "keyword": {
                "type": "string",
                "description": "搜索关键词(list 时可选)",
            },
            "page": {
                "type": "integer",
                "description": "页码,默认 1",
                "default": 1,
            },
            "size": {
                "type": "integer",
                "description": "每页数量,默认 10",
                "default": 10,
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        ticket_id: Optional[str] = None,
        order_id: Optional[str] = None,
        ticket_type: Optional[str] = None,
        status: Optional[str] = None,
        reason: Optional[str] = None,
        description: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        size: int = 10,
        **kwargs,
    ) -> ToolResult:
        """执行售后工单管理操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行售后工单管理操作",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型,可选:{', '.join(VALID_ACTIONS)}",
            )

        try:
            if action == "list":
                return await self._list_tickets(context, page, size, status, ticket_type, keyword)
            elif action == "detail":
                return await self._get_detail(context, ticket_id)
            elif action == "create":
                return await self._create_ticket(context, order_id, ticket_type, reason, description)
            elif action == "update_status":
                return await self._update_status(context, ticket_id, status, reason)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                )

        except Exception as e:
            logger.error(f"After-sales manage error: action={action}, error={e}")
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="售后工单操作失败,请稍后重试",
            )

    async def _list_tickets(
        self,
        context: ToolContext,
        page: int,
        size: int,
        status: Optional[str],
        ticket_type: Optional[str],
        keyword: Optional[str],
    ) -> ToolResult:
        """查询售后工单列表"""
        params: Dict[str, Any] = {"page": page, "size": size}
        if status:
            params["status"] = status
        if ticket_type:
            params["ticketType"] = ticket_type
        if keyword:
            params["keyword"] = keyword

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/after-sales",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"查询售后工单列表失败:{error_msg}",
            )

        data = response.get("data", {})
        items = data.get("items", [])
        total = data.get("total", 0)

        logger.info(
            f"After-sales list: page={page}, size={size}, total={total}, "
            f"tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"items": items, "total": total, "page": page, "size": size},
            message=f"共找到 {total} 条售后工单记录",
        )

    async def _get_detail(
        self,
        context: ToolContext,
        ticket_id: Optional[str],
    ) -> ToolResult:
        """查看售后工单详情"""
        if not ticket_id:
            return ToolResult(
                success=False,
                error="缺少工单 ID",
                message="查看详情时必须提供工单 ID(ticket_id)",
            )

        client = get_admin_api_client()
        response = await client.get(
            f"/api/admin/after-sales/{ticket_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"查询售后工单详情失败:{error_msg}",
            )

        data = response.get("data", {})

        logger.info(
            f"After-sales detail: ticket_id={ticket_id}, tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data=data,
            message=f"售后工单 {ticket_id} 详情已获取",
        )

    async def _create_ticket(
        self,
        context: ToolContext,
        order_id: Optional[str],
        ticket_type: Optional[str],
        reason: Optional[str],
        description: Optional[str],
    ) -> ToolResult:
        """创建售后工单"""
        if not order_id:
            return ToolResult(
                success=False,
                error="缺少订单 ID",
                message="创建售后工单时必须提供关联订单 ID(order_id)",
            )

        if not ticket_type:
            return ToolResult(
                success=False,
                error="缺少工单类型",
                message="创建售后工单时必须提供工单类型(ticket_type)",
            )

        if ticket_type not in VALID_TICKET_TYPES:
            return ToolResult(
                success=False,
                error=f"无效的工单类型: {ticket_type}",
                message=f"不支持的工单类型,可选:{', '.join(VALID_TICKET_TYPES)}",
            )

        if not reason:
            return ToolResult(
                success=False,
                error="缺少原因说明",
                message="创建售后工单时必须提供原因说明(reason)",
            )

        json_data: Dict[str, Any] = {
            "orderId": order_id,
            "ticketType": ticket_type,
            "reason": reason,
        }
        if description:
            json_data["description"] = description

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/after-sales",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "创建失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"创建售后工单失败:{error_msg}",
            )

        data = response.get("data", {})
        new_ticket_id = data.get("id", "")

        logger.info(
            f"After-sales ticket created: ticket_id={new_ticket_id}, "
            f"order_id={order_id}, type={ticket_type}, "
            f"tenant={context.tenant_id}, user={context.user_id}"
        )

        return ToolResult(
            success=True,
            data=data,
            message=f"售后工单已创建,工单号:{new_ticket_id}",
        )

    async def _update_status(
        self,
        context: ToolContext,
        ticket_id: Optional[str],
        status: Optional[str],
        reason: Optional[str],
    ) -> ToolResult:
        """更新售后工单状态"""
        if not ticket_id:
            return ToolResult(
                success=False,
                error="缺少工单 ID",
                message="更新状态时必须提供工单 ID(ticket_id)",
            )

        if not status:
            return ToolResult(
                success=False,
                error="缺少状态参数",
                message="更新状态时必须提供新状态(status)",
            )

        if status not in VALID_TICKET_STATUSES:
            return ToolResult(
                success=False,
                error=f"无效的工单状态: {status}",
                message=f"不支持的状态值,可选:{', '.join(VALID_TICKET_STATUSES)}",
            )

        json_data: Dict[str, Any] = {"status": status}
        if reason:
            json_data["reason"] = reason

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/after-sales/{ticket_id}/status",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"更新售后工单状态失败:{error_msg}",
            )

        logger.info(
            f"After-sales status updated: ticket_id={ticket_id}, status={status}, "
            f"tenant={context.tenant_id}, user={context.user_id}"
        )

        return ToolResult(
            success=True,
            data={"ticket_id": ticket_id, "status": status},
            message=f"售后工单状态已更新为「{status}」",
        )
