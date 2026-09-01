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

        # 非营业时间转人工降级：没有坐席在线，返回 afterHoursMessage 引导留言，
        # 不创建工单。AI 机器人本身照常服务，此降级只针对「转人工」这个动作。
        try:
            from app.agents.tenant_config import get_tenant_ai_config, is_after_hours
            ai_config = await get_tenant_ai_config(context.tenant_id)
            if is_after_hours(ai_config):
                msg = (
                    ai_config.get("afterHoursMessage")
                    or "当前非营业时间，人工客服已休息，请您留言，我们会尽快回复您～"
                )
                logger.info(
                    f"[human_handoff] 非营业时间转人工降级 | tenant={context.tenant_id} "
                    f"afterHoursMode={ai_config.get('afterHoursMode')}"
                )
                return ToolResult(
                    success=True,
                    data={"handoff_deferred": True, "after_hours": True},
                    message=msg,
                    summary=f"非营业时间，转人工降级为留言：{msg[:30]}",
                )
        except Exception as e:
            logger.warning(
                f"[human_handoff] 非营业时间检查失败（非致命，继续正常转人工）: "
                f"{type(e).__name__}: {e}"
            )

        try:
            # 用 Agent 版接口（宽松校验，转人工工单无关联订单，不需要 orderId）
            json_data: Dict[str, Any] = {
                "ticketType": "complaint",
                "reason": handoff_reason,
            }
            if description:
                json_data["description"] = description

            logger.info(
                f"[human_handoff] Creating handoff ticket: reason={handoff_reason[:50]} | "
                f"tenant={context.tenant_id}, user={context.user_id}"
            )

            client = get_admin_api_client()
            response = await client.post(
                "/api/admin/agent/after-sales",
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

            # 创建人工客服会话（客服工作台可见、可对话）——转人工核心闭环
            agent_session_id = None
            try:
                session_response = await client.post(
                    "/api/admin/agent-sessions",
                    json_data={
                        "aiSessionId": context.session_id,
                        "customerId": context.user_id,
                        "reason": handoff_reason,
                    },
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
                if session_response.get("success") and session_response.get("data"):
                    agent_session_id = session_response["data"].get("id")
                    logger.info(
                        f"[human_handoff] 人工会话创建成功: agentSessionId={agent_session_id} "
                        f"| tenant={context.tenant_id}"
                    )
                else:
                    logger.warning(
                        f"[human_handoff] 创建人工会话失败（工单已创建，不影响主流程）: "
                        f"{session_response.get('error', {}).get('message', 'unknown')}"
                    )
            except Exception as e:
                logger.warning(
                    f"[human_handoff] 创建人工会话异常（工单已创建，不影响主流程）: "
                    f"{type(e).__name__}: {e}"
                )

            data = dict(ticket_data)
            if agent_session_id:
                data["agentSessionId"] = agent_session_id

            return ToolResult(
                success=True,
                data=data,
                message=(
                    f"已为您转接人工客服！工单编号：{ticket_no}。"
                    "我们的客服人员会在工作时间内尽快与您联系，感谢您的耐心等待 🙏"
                ),
                summary=f"转人工成功: 工单{ticket_no}, 原因:{handoff_reason[:30]}",
                # T2 事务终态：转人工完成 → 清空会话级状态（进入人工流程，AI 上下文不再续用）
                terminal=True,
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
