"""
AI 智能客服系统 - 售后工单管理 Tool

管理售后工单,支持查询列表 详情 创建工单 更新工单状态。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.enum_labels import (
    TICKET_PRIORITY_LABELS,
    TICKET_STATUS_LABELS,
    TICKET_TYPE_LABELS,
    attach_ticket_labels,
)
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"list", "detail"}

# 工单类型
VALID_TICKET_TYPES = {"refund", "exchange", "repair", "complaint", "other"}

# 工单状态
VALID_TICKET_STATUSES = {"pending", "processing", "resolved", "rejected", "closed"}

# 终态且必须留痕（原因）的状态：admin-api 只在 remark 非空时写 closeReason
CLOSE_STATUSES = {"closed", "rejected"}


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
    description = (
        "【触发】用户说'退货''退款''换货''投诉''查售后工单''工单进度'时调用；"
        "创建工单前先 order_query 确认订单，不要只查订单就停住。"
        "【参数】action 必填：**只有 list / detail 两个只读 action**（B 端已只读化，issue #5247）；"
        "detail 需 ticket_id；list 支持 status / ticket_type / keyword / 分页。"
        "【反例】只查订单本身（金额/明细/状态）用 order_query；顾客本人查自己的工单用 aftersale_query。"
        "【反例】建工单/改工单状态（关闭/拒绝）**不在本工具能力内**——引导用户到后台「售后工单」页处理。"
        "【标注】READONLY — 纯查询，不含任何写 action"
    )
    # 权限码（admin-api 目录）：AfterSalesController / AgentAfterSalesController 类级
    # `@RequirePermission("order:refund")`（售后工单 = 退款处理）。
    # 不再用 allowed_roles —— 手写角色白名单会与目录漂移（#4106 F4）。
    # 读码 after_sales:view（issue #5246）：与 `AfterSalesController` 的读端点
    # `@RequirePermission("after_sales:view")` 同码（列表/详情）；写端点仍为 order:refund。
    required_permissions = ["after_sales:view"]  # B 端只读化（#5247）：写码 order:refund 已随写 action 移除

    read_only = True
    read_only_actions = {"list", "detail"}  # 只读 action 免确认拦截
    idempotent = False   # 创建/状态变更非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型:list(查询列表)/ detail(查看详情) —— 均为只读",
                "enum": ["list", "detail"],
            },
            "ticket_id": {
                "type": "string",
                "description": "工单 ID(detail/update_status 时必填)",
            },
            "ticket_type": {
                "type": "string",
                "description": "工单类型:refund=退款/exchange=换货/repair=维修/complaint=投诉/other=其他",
                "enum": ["refund", "exchange", "repair", "complaint", "other"],
            },
            "status": {
                "type": "string",
                "description": "工单状态:pending=待处理/processing=处理中/resolved=已解决/rejected=已拒绝/closed=已关闭（回复用户时用中文术语）",
                "enum": ["pending", "processing", "resolved", "rejected", "closed"],
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
                suggestion="请联系管理员获取执行售后工单管理操作权限",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型,可选:{', '.join(VALID_ACTIONS)}",
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )

        try:
            if action == "list":
                return await self._list_tickets(context, page, size, status, ticket_type, keyword)
            elif action == "detail":
                return await self._get_detail(context, ticket_id)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )

        except Exception as e:
            logger.error(f"After-sales manage error: action={action}, error={e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="售后工单操作失败,请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
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
        page = int(page) if page else 1
        size = int(size) if size else 10
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
            return admin_api_failure(response,
                error=error_msg,
                message=f"查询售后工单列表失败:{error_msg}",
                suggestion="请稍后重试；若持续失败，请改为不带状态筛选查询，或请用户联系管理员核对工单数据",
            )

        data = response.get("data", {})
        items = data.get("items", [])
        total = data.get("total", 0)

        # 附中文业务术语标签（status_label/priority_label/ticket_type_label），
        # 防止 LLM 把 normal/urgent/critical 等英文枚举原样输出给用户
        items = [attach_ticket_labels(item) for item in items]

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
                suggestion="缺少 ticket_id，请先用 after_sales_manage 的 list 操作取到工单 ID 后重试",
            )

        client = get_admin_api_client()
        response = await client.get(
            f"/api/admin/after-sales/{ticket_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message=f"查询售后工单详情失败:{error_msg}",
                suggestion="请先用 after_sales_manage 的 list 操作确认该工单仍在（已删除的工单不可查看详情）后重试",
            )

        data = response.get("data", {})

        logger.info(
            f"After-sales detail: ticket_id={ticket_id}, tenant={context.tenant_id}"
        )

        # 附中文业务术语标签，防止英文枚举流入用户可见回复
        data = attach_ticket_labels(data)

        return ToolResult(
            success=True,
            data=data,
            message=f"售后工单 {ticket_id} 详情已获取",
        )