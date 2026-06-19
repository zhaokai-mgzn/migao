"""
AI 智能客服系统 - C端售后创建 Tool (小布专用)

客户通过小布创建售后工单：退换货、维修、投诉等。
与 after_sales_manage（管理员使用）分开：客户只能创建，不能查列表/改状态。
"""
from typing import Optional, Dict, Any
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


VALID_TICKET_TYPES = {"refund", "exchange", "repair", "complaint", "other"}


class AftersaleCreateTool(BaseTool):
    """C端售后创建 Tool

    小布（C端客服）专用：客户想要退换货、维修、投诉时调用。
    必须关联已有订单号，只能创建自己的工单。

    安全:
    - 仅 customer 角色可用
    - 创建前必须弹 confirm 卡片
    - tenant_id + user_id 双重隔离
    """

    name = "aftersale_create"
    description = (
        "【触发】客户说'退货''换货''退款''维修''投诉'且有订单号时调用。"
        "【前置】必填: order_id + ticket_type + reason。缺信息时先收集，不要直接调。"
        "收集流程: 问订单号→问售后类型→问原因→展示汇总→用户确认→调用。"
        "【反例】用户只说'不满意'没提订单号时不要调，先问订单号。"
        "ticket_type: refund(退款), exchange(换货), repair(维修), complaint(投诉), other(其他)。"
        "【标注】WRITE|NON_IDEMPOTENT — 先确认再执行"
    )
    allowed_roles = ["customer"]

    read_only = False
    destructive = False
    idempotent = False

    parameters = {
        "type": "object",
        "properties": {
            "order_id": {
                "type": "string",
                "description": "关联订单ID（必填，必须先查订单确认订单属于当前客户）",
            },
            "ticket_type": {
                "type": "string",
                "description": "工单类型: refund(退款), exchange(换货), repair(维修), complaint(投诉), other(其他)",
                "enum": ["refund", "exchange", "repair", "complaint", "other"],
            },
            "reason": {
                "type": "string",
                "description": "售后原因说明（必填，如'窗帘收到后有色差''尺寸不合适需换货'）",
            },
            "description": {
                "type": "string",
                "description": "详细问题描述（可选）",
            },
            "images": {
                "type": "array",
                "description": "凭证图片URL列表（可选）",
                "items": {"type": "string"},
            },
            "priority": {
                "type": "string",
                "description": "优先级（可选，默认 normal）",
                "enum": ["normal", "urgent", "critical"],
            },
            "refund_amount": {
                "type": "number",
                "description": "退款金额（退款类型时填写）",
            },
        },
        "required": ["order_id", "ticket_type", "reason"],
    }

    async def execute(
        self,
        context: ToolContext,
        order_id: str,
        ticket_type: Optional[str] = None,
        reason: Optional[str] = None,
        description: Optional[str] = None,
        images: Optional[list] = None,
        priority: Optional[str] = None,
        refund_amount: Optional[float] = None,
    ) -> ToolResult:
        """执行售后工单创建

        Args:
            context: Tool 执行上下文
            order_id: 关联订单ID
            ticket_type: 工单类型
            reason: 售后原因
            description: 详细描述（可选）
            images: 凭证图片列表（可选）
            priority: 优先级（可选）
            refund_amount: 退款金额（可选）

        Returns:
            ToolResult: 创建结果
        """
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限创建售后工单",
                suggestion="售后工单创建仅对客户开放，请联系客服获取帮助",
            )

        # 参数校验
        if not order_id:
            return ToolResult(
                success=False,
                error="缺少订单ID",
                message="创建售后工单时必须提供关联订单ID",
                suggestion="请先查询您的订单，确认订单号后再提交售后申请",
            )

        if not ticket_type:
            return ToolResult(
                success=False,
                error="缺少工单类型",
                message="创建售后工单时必须选择工单类型",
                suggestion="请选择售后类型：退款、换货、维修、投诉或其他",
            )

        if ticket_type not in VALID_TICKET_TYPES:
            return ToolResult(
                success=False,
                error=f"无效的工单类型: {ticket_type}",
                message=f"不支持的售后类型，可选: {', '.join(VALID_TICKET_TYPES)}",
                suggestion=f"请从以下类型中选择: {', '.join(VALID_TICKET_TYPES)}",
            )

        if not reason:
            return ToolResult(
                success=False,
                error="缺少原因说明",
                message="创建售后工单时必须说明原因",
                suggestion="请描述您遇到的问题，例如：'窗帘收到后有色差''尺寸不合适需换货'",
            )

        try:
            json_data: Dict[str, Any] = {
                "orderId": order_id,
                "ticketType": ticket_type,
                "reason": reason,
                "source": "customer",
            }
            if description:
                json_data["description"] = description
            if images:
                json_data["images"] = images
            if priority:
                json_data["priority"] = priority
            if refund_amount is not None:
                json_data["refundAmount"] = refund_amount

            logger.info(
                f"[aftersale_create] Creating ticket: order_id={order_id}, "
                f"type={ticket_type}, reason={reason[:50]} | "
                f"tenant={context.tenant_id}, user={context.user_id}"
            )

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
                    message=f"创建售后工单失败：{error_msg}",
                    suggestion="请检查订单号是否正确，或稍后重试",
                )

            ticket_data = response.get("data", {})
            ticket_no = ticket_data.get("ticketNo", ticket_data.get("id", ""))

            logger.info(
                f"[aftersale_create] Ticket created: ticket_no={ticket_no}, "
                f"order_id={order_id}, type={ticket_type} | "
                f"tenant={context.tenant_id}, user={context.user_id}"
            )

            return ToolResult(
                success=True,
                data=ticket_data,
                message=(
                    f"售后工单已创建成功！工单编号：{ticket_no}。"
                    f"类型：{ticket_type}，原因：{reason}。"
                    "我们会尽快处理，感谢您的耐心等待 🙏"
                ),
                summary=f"售后工单创建成功: {ticket_no}, 类型{ticket_type}, 订单{order_id}",
            )

        except Exception as e:
            logger.error(
                f"[aftersale_create] Failed: order_id={order_id}, "
                f"error={type(e).__name__}: {e}"
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="创建售后工单失败，请稍后重试",
                suggestion="请检查信息是否完整，确认后重试。如持续失败请联系客服",
            )
