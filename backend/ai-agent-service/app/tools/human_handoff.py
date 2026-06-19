"""
AI 智能客服系统 - 转人工 Tool (小布专用)

客户说"转人工"时调用，自动创建投诉工单并通知管理员。

安全（#518）:
- 转人工创建工单后必须通知管理员（系统消息通知）
- 通知失败不影响工单创建（工单已记录，管理员可通过工单列表查看）
"""
from typing import Optional, Dict, Any
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class HumanHandoffTool(BaseTool):
    """转人工 Tool

    小布（C端客服）专用：客户要求转人工时，自动创建投诉类型售后工单，
    通知管理员，并返回友好提示告知客户等待人工回电。

    使用场景:
    - 客户说"转人工""人工客服""找人工""我要投诉"
    - 多次沟通无法解决问题时的兜底路径
    - 客户情绪激动要求人工介入
    """

    name = "human_handoff"
    description = (
        "【触发】客户说'转人工''人工客服''找人工''我要投诉''找你们领导'时调用。"
        "【功能】自动创建投诉工单 → 通知管理员 → 返回安抚话术。"
        "reason参数选填:客户转人工原因(如'产品质量问题''物流太慢'等)。"
        "description参数选填:详细问题描述。"
        "【标注】WRITE|NON_IDEMPOTENT — 每次调用创建新工单"
    )
    allowed_roles = ["customer"]

    read_only = False
    destructive = False
    idempotent = False

    parameters = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "客户转人工原因（选填，如'产品质量问题''物流太慢'等），不填默认'客户请求转人工'",
            },
            "description": {
                "type": "string",
                "description": "详细问题描述（选填）",
            },
        },
    }

    @staticmethod
    async def _notify_admins(
        context: ToolContext,
        ticket_no: str,
        handoff_reason: str,
    ) -> None:
        """通知管理员：有新的转人工工单

        通过 admin-api 创建系统通知，发送给所有管理员。
        通知失败仅记录日志，不影响转人工主流程。

        Args:
            context: Tool 执行上下文
            ticket_no: 工单编号
            handoff_reason: 转人工原因
        """
        try:
            client = get_admin_api_client()
            notify_payload: Dict[str, Any] = {
                "content": (
                    f"🔔 客户请求转人工\n"
                    f"工单编号：{ticket_no}\n"
                    f"客户ID：{context.user_id}\n"
                    f"原因：{handoff_reason}"
                ),
                "title": f"客户请求转人工 - {ticket_no}",
                "channel": "system",
                "recipientRole": "admin",
                "type": "handoff",
            }
            response = await client.post(
                "/api/admin/notifications",
                json_data=notify_payload,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
            if response.get("success"):
                logger.info(
                    f"[human_handoff] Admin notified: ticket_no={ticket_no} | "
                    f"tenant={context.tenant_id}"
                )
            else:
                error = response.get("error", {}).get("message", "unknown")
                logger.warning(
                    f"[human_handoff] Admin notification failed (non-fatal): "
                    f"ticket_no={ticket_no}, error={error}"
                )
        except Exception as e:
            logger.warning(
                f"[human_handoff] Admin notification exception (non-fatal): "
                f"ticket_no={ticket_no}, error={type(e).__name__}: {e}"
            )

    async def execute(
        self,
        context: ToolContext,
        reason: Optional[str] = None,
        description: Optional[str] = None,
    ) -> ToolResult:
        """执行转人工操作

        创建投诉工单 → 通知管理员 → 返回安抚话术

        Args:
            context: Tool 执行上下文
            reason: 转人工原因
            description: 详细描述

        Returns:
            ToolResult: 包含安抚话术的返回结果
        """
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限使用转人工功能",
                suggestion="转人工功能仅供客户使用",
            )

        handoff_reason = reason or "客户请求转人工（未提供具体原因）"

        try:
            json_data: Dict[str, Any] = {
                "ticketType": "complaint",
                "reason": handoff_reason,
                "source": "customer",
            }
            if description:
                json_data["description"] = description

            logger.info(
                f"[human_handoff] Creating handoff ticket: reason={handoff_reason[:50]} | "
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
                error_msg = response.get("error", {}).get("message", "创建工单失败")
                return ToolResult(
                    success=False,
                    error=error_msg,
                    message=f"转人工失败：{error_msg}",
                    suggestion="请稍后重试转人工，或直接拨打客服热线联系人工客服",
                )

            ticket_data = response.get("data", {})
            ticket_no = ticket_data.get("ticketNo", ticket_data.get("id", ""))

            logger.info(
                f"[human_handoff] Handoff ticket created: ticket_no={ticket_no} | "
                f"tenant={context.tenant_id}, user={context.user_id}"
            )

            # Gap-3 安全加固: 通知管理员
            await self._notify_admins(context, ticket_no, handoff_reason)

            return ToolResult(
                success=True,
                data=ticket_data,
                message=(
                    f"已为您转接人工客服！工单编号：{ticket_no}。"
                    "我们的客服人员会在工作时间内尽快与您联系，感谢您的耐心等待 🙏"
                ),
                summary=f"转人工成功: 工单{ticket_no}, 原因:{handoff_reason[:30]}",
            )

        except Exception as e:
            logger.error(
                f"[human_handoff] Failed: reason={handoff_reason[:50]}, "
                f"error={type(e).__name__}: {e}"
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="转人工失败，请稍后重试",
                suggestion="系统暂时无法处理转人工请求，请稍后重试或直接拨打客服热线",
            )
