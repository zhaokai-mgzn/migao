"""
AI 智能客服系统 - C端售后工单创建 Tool

Customer-facing aftersale ticket creation.
Wraps admin-api POST /api/admin/after-sales with customerId injection for data isolation.
"""
from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.tools.after_sales_manage import VALID_TICKET_TYPES
from app.utils.http_client import get_admin_api_client


class AftersaleCreateTool(BaseTool):
    """C端售后工单创建 Tool

    Customer creates aftersale tickets (refund/exchange/repair/complaint/other).
    Always injects customerId from context.user_id for data isolation.

    使用场景：
    - 顾客要求退款/退货
    - 顾客要求换货
    - 顾客投诉
    """

    name = "aftersale_create"
    description = (
        "【触发】顾客说'退款''退货''换货''维修''投诉'时调用。【前置】必填: order_id + ticket_type(refund/exchange/repair/complaint/other) + reason。缺信息时先收集，不要直接调。【反例】顾客只抱怨没提具体订单时先确认订单号。修改已有工单管理员用 after_sales_manage。【标注】WRITE|NON_IDEMPOTENT — 先确认再执行"
    )

    allowed_roles = ["customer"]

    read_only = False
    destructive = False
    idempotent = False  # 每次调用创建新工单

    # 关联校验工具
    related_tools = ["validate_input"]

    parameters = {
        "type": "object",
        "properties": {
            "order_id": {
                "type": "string",
                "description": "关联订单 ID（必填）",
            },
            "ticket_type": {
                "type": "string",
                "description": "工单类型：refund=退款, exchange=换货, repair=维修, complaint=投诉, other=其他",
                "enum": ["refund", "exchange", "repair", "complaint", "other"],
            },
            "reason": {
                "type": "string",
                "description": "原因说明（必填，如'尺寸不符要求退款'）",
            },
            "description": {
                "type": "string",
                "description": "详细问题描述（可选）",
            },
        },
        "required": ["order_id", "ticket_type", "reason"],
    }

    async def execute(
        self,
        context: ToolContext,
        order_id: Optional[str] = None,
        ticket_type: Optional[str] = None,
        reason: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """执行创建售后工单

        Args:
            context: Tool 执行上下文（customerId 从 context.user_id 注入）
            order_id: 关联订单 ID
            ticket_type: 工单类型
            reason: 原因说明
            description: 详细问题描述（可选）

        Returns:
            ToolResult: 创建结果
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限创建售后工单",
                suggestion="请联系客服处理售后问题",
            )

        # ── 参数校验 ──

        if not order_id:
            return ToolResult(
                success=False,
                error="缺少订单ID",
                message="创建售后工单时必须提供关联订单ID（order_id）",
                suggestion="请提供需要售后的订单号",
            )

        if not ticket_type:
            return ToolResult(
                success=False,
                error="缺少工单类型",
                message="创建售后工单时必须提供工单类型（ticket_type）",
                suggestion="请选择售后类型：退款(refund)、换货(exchange)、维修(repair)、投诉(complaint)、其他(other)",
            )

        if ticket_type not in VALID_TICKET_TYPES:
            return ToolResult(
                success=False,
                error=f"无效的工单类型: {ticket_type}",
                message=f"不支持的工单类型，可选：{', '.join(sorted(VALID_TICKET_TYPES))}",
                suggestion=f"请选择以下类型之一：{', '.join(sorted(VALID_TICKET_TYPES))}",
            )

        if not reason:
            return ToolResult(
                success=False,
                error="缺少原因说明",
                message="创建售后工单时必须提供原因说明（reason）",
                suggestion="请描述售后原因，如'尺寸不符'、'颜色与样品不符'、'物流损坏'等",
            )

        # ── 构建请求体（admin-api 使用 camelCase）──

        json_data: Dict[str, Any] = {
            "orderId": order_id,
            "ticketType": ticket_type,
            "reason": reason,
            "customerId": str(context.user_id),  # 强制注入，确保工单归属当前客户
        }

        if description:
            json_data["description"] = description

        try:
            logger.info(
                f"[aftersale-create] Creating ticket: order_id={order_id}, "
                f"type={ticket_type} tenant={context.tenant_id} user={context.user_id}"
            )

            response = await self._call_admin_api(
                method="POST",
                path="/api/admin/after-sales",
                json_data=json_data,
                context=context,
            )

            if not response.get("success"):
                error_msg = response.get("error", {}).get("message", "创建失败")
                return ToolResult(
                    success=False,
                    error=error_msg,
                    message=f"创建售后工单失败：{error_msg}",
                    suggestion="请检查订单号是否正确，确认后重试",
                )

            data = response.get("data", {})
            ticket_id = data.get("id", "")

            logger.info(
                f"[aftersale-create] Ticket created: id={ticket_id}, "
                f"order_id={order_id}, type={ticket_type} "
                f"tenant={context.tenant_id} user={context.user_id}"
            )

            return ToolResult(
                success=True,
                data=data,
                message=f"售后工单已创建！工单号：{ticket_id}，类型：{ticket_type}",
                summary=f"售后工单创建成功: 工单号{ticket_id}, 类型{ticket_type}",
            )

        except Exception as e:
            logger.error(
                f"[aftersale-create] Failed: order_id={order_id}, "
                f"type={ticket_type} error={type(e).__name__}: {e}"
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="创建售后工单失败，请稍后重试",
                suggestion="请检查订单信息是否完整，确认后重试",
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
