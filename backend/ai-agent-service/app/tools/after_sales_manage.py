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
VALID_ACTIONS = {"list", "detail", "create", "update_status"}

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
        "创建/查询售后工单。用户说退货/退款/换货/投诉时，先 order_query 确认订单，"
        "然后直接调此工具创建工单，不要只查订单就停住。"
        "create 必填: ticket_type(退款/换货/维修/投诉/其他) + order_id + reason。"
        "update_status: 关闭(closed)/拒绝(rejected)必须带 reason（写入关闭留痕 closeReason，"
        "缺原因会被本工具拒绝——先问用户原因再调用）。"
        "可选: refund_amount, priority, images。仅查工单用 list/detail action。WRITE"
    )
    # 权限码（admin-api 目录）：AfterSalesController / AgentAfterSalesController 类级
    # `@RequirePermission("order:refund")`（售后工单 = 退款处理）。
    # 不再用 allowed_roles —— 手写角色白名单会与目录漂移（#4106 F4）。
    required_permissions = ["order:refund"]

    read_only = False
    destructive = True   # 可关闭/拒绝工单（不可逆）
    read_only_actions = {"list", "detail"}  # 只读 action 免确认拦截
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
                "description": "订单 ID 或订单号（ORD-xxx）。支持 UUID / 订单号，服务端自动解析。create 时必填",
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
            "reason": {
                "type": "string",
                "description": (
                    "原因说明。create 时必填(如'客户反馈尺寸不符要求退款')；"
                    "update_status 置为 closed(关闭)/rejected(拒绝) 时**同样必填**"
                    "——原因会写入工单的关闭留痕 closeReason，缺原因本工具会拒绝"
                    "（关闭态不可再流转，事后无法补记）"
                ),
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
                "description": "优先级:normal=普通/urgent=紧急/critical=严重(可选,默认普通；回复用户时用中文术语)",
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
            elif action == "create":
                # 对抗编程：从 kwargs 提取被 LLM 传入但之前被丢弃的字段
                return await self._create_ticket(
                    context, order_id, ticket_type, reason, description,
                    images=kwargs.get("images"),
                    priority=kwargs.get("priority"),
                    refund_amount=kwargs.get("refund_amount"),
                )
            elif action == "update_status":
                return await self._update_status(context, ticket_id, status, reason)
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

    async def _create_ticket(
        self,
        context: ToolContext,
        order_id: Optional[str],
        ticket_type: Optional[str],
        reason: Optional[str],
        description: Optional[str],
        images: Optional[list] = None,
        priority: Optional[str] = None,
        refund_amount: Optional[float] = None,
    ) -> ToolResult:
        """创建售后工单"""
        if not order_id:
            return ToolResult(
                success=False,
                error="缺少订单 ID",
                message="创建售后工单时必须提供关联订单 ID(order_id)",
                suggestion="缺少订单 ID order_id，请先用 order_query 查到该订单后重试",
            )

        if not ticket_type:
            return ToolResult(
                success=False,
                error="缺少工单类型",
                message="创建售后工单时必须提供工单类型(ticket_type)",
                suggestion="缺少工单类型 ticket_type，请向用户确认是退货/换货/维修/投诉中的哪一类后重试",
            )

        if ticket_type not in VALID_TICKET_TYPES:
            valid_labels = "、".join(TICKET_TYPE_LABELS.get(t, t) for t in sorted(VALID_TICKET_TYPES))
            return ToolResult(
                success=False,
                error=f"无效的工单类型: {ticket_type}",
                message=f"不支持的工单类型,可选:{valid_labels}",
                suggestion="请改用错误提示中列出的合法工单类型后重试，不要自行新增类型名",
            )

        if not reason:
            return ToolResult(
                success=False,
                error="缺少原因说明",
                message="创建售后工单时必须提供原因说明(reason)",
                suggestion="缺少原因说明 reason，请向用户询问售后原因后重试（这是工单必填项）",
            )

        # 对抗编程：reason → description 字段映射 + 透传所有可选字段
        # `source` 不下发（issue #3605）：AgentAfterSalesCreateRequest 无该字段（下发即静默丢弃），
        # 且来源由服务端固化（AfterSalesTicketService.createTicket 内 ticket.setSource("agent")，
        # 表单入口与 Agent BFF 入口都经过它）——客户端指定来源既无效也多余。
        json_data: Dict[str, Any] = {
            "orderId": order_id,
            "ticketType": ticket_type,
            "description": description if description else reason,  # Java API 用 description
        }
        if images:
            json_data["images"] = images
        if priority:
            json_data["priority"] = priority
        if refund_amount is not None:
            json_data["refundAmount"] = refund_amount

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/agent/after-sales",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            # 工单真实来源（issue #3686）：本工具是米宝（B 端）管理工具，
            # context.ticket_source = "agent"（AI 建单）。放 header 不放 body（同 #3605 取舍）。
            headers={"X-Agent-Client": context.ticket_source},
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "创建失败")
            return admin_api_failure(response,
                error=error_msg,
                message=f"创建售后工单失败:{error_msg}",
                suggestion="请先用 order_query 确认订单存在且属于当前租户，再重新执行创建工单",
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
                suggestion="缺少 ticket_id，请先用 after_sales_manage 的 list 操作取到工单 ID 后重试",
            )

        if not status:
            return ToolResult(
                success=False,
                error="缺少状态参数",
                message="更新状态时必须提供新状态(status)",
                suggestion="缺少目标状态 status，请向用户确认工单要流转到哪个状态后重试",
            )

        if status not in VALID_TICKET_STATUSES:
            valid_labels = "、".join(TICKET_STATUS_LABELS.get(s, s) for s in VALID_TICKET_STATUSES)
            return ToolResult(
                success=False,
                error=f"无效的工单状态: {status}",
                message=f"不支持的状态值,可选:{valid_labels}",
                suggestion="请改用错误提示中列出的合法状态值后重试，不要自行新增状态名",
            )

        # 关闭/拒绝必须带原因（issue #3744 / AS-004）：admin-api 仅在 remark 非空时写
        # closeReason（AfterSalesTicketService#updateTicketStatus）⇒ 不带原因关单 =
        # 「关闭留痕缺失」（closedAt 有、closeReason 空），而 closed/rejected 是**终态**、
        # 不可事后补记。不能靠提示词赌模型一定会传 reason（本工具曾把 reason 声明成
        # 「create 时必填」→ 模型在 update_status 时压根不带），故在此失败关闭并给出
        # 可执行指引（同 #3365 接地闸门的代码兜底口径：同源缺陷不靠提示词赌）。
        if status in CLOSE_STATUSES and not reason:
            status_label = TICKET_STATUS_LABELS.get(status, status)
            return ToolResult(
                success=False,
                error=f"缺少{status_label}原因",
                message=(
                    f"把工单置为「{status_label}」时必须说明原因：原因会写入工单的关闭留痕"
                    "（closeReason），缺原因则关闭记录不完整；且「已关闭/已拒绝」是终态，"
                    "事后无法补记。请先向用户确认原因，再带 reason 重新调用本工具。"
                ),
                suggestion=f"先问用户「为什么{status_label}这张工单」，拿到原因后带 reason 重试",
            )

        # 对抗编程：reason → remark 字段映射。
        # AfterSalesStatusUpdateRequest 只声明 status/remark，Java 侧用 remark 写入
        # closeReason（closed/rejected 时）+ internalNotes；发 reason 会被 Spring
        # 静默丢弃（HTTP 200 但 closeReason 恒为空，issue #3540 / AS-004）。
        json_data: Dict[str, Any] = {"status": status}
        if reason:
            json_data["remark"] = reason

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/after-sales/{ticket_id}/status",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return admin_api_failure(response,
                error=error_msg,
                message=f"更新售后工单状态失败:{error_msg}",
                suggestion="请先用 after_sales_manage 的 detail 操作确认该工单当前状态，再按合法流转路径重新执行更新",
            )

        logger.info(
            f"After-sales status updated: ticket_id={ticket_id}, status={status}, "
            f"tenant={context.tenant_id}, user={context.user_id}"
        )

        status_label = TICKET_STATUS_LABELS.get(status, status)
        return ToolResult(
            success=True,
            data={"ticket_id": ticket_id, "status": status},
            message=f"售后工单状态已更新为「{status_label}」",
        )
