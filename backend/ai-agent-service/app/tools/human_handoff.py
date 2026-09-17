"""
AI 智能客服系统 - 转人工 Tool (小布专用)

客户说"转人工"时调用，自动创建投诉工单并通知管理员。

安全（#518）:
- 转人工创建工单后必须通知管理员（系统消息通知）
- 通知失败不影响工单创建（工单已记录，管理员可通过工单列表查看）
"""
from typing import Optional, Dict, Any
import re
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.tools.order_create import CLIENT_REQUEST_ID_HEADER, _request_window_id
from app.utils.http_client import get_admin_api_client

# ── GB/T 47746-2026 转人工上下文同步（issue #2776）────────────────────
# 转人工时把 AI 会话最近 N 轮 user/assistant 文本快照带给人工客服，
# 让人工客服无需顾客复述即可了解已沟通内容。
_AI_CONTEXT_HISTORY_LIMIT = 12      # SessionMemory.get_history 拉取上限
_AI_CONTEXT_MAX_TURNS = 20          # 快照最多携带轮数
_AI_CONTEXT_MAX_CHARS_PER_TURN = 500
_THINK_PATTERN = re.compile(r"<think>[\s\S]*?</think>")

# ── 转人工通知收件人（issue #3553，HIGH：客户求助无门 + 静默失败）────────────
# ⚠️ 后来者注意（这三条最容易再踩，issue #3553 的根因）：
# ① admin-api `POST /api/admin/notifications` **按收件人落库，没有广播语义** ——
#    站内信按 recipientId 分发给当前登录用户（NotificationController.getUnreadCount →
#    getCurrentUserId()），"发给所有管理员"必须由调用方**逐个收件人**发。
# ② `recipientRole` / `type` **不在 CreateNotificationRequest 内** → Jackson 静默忽略
#    （写了也无效，只会让读代码的人误以为它生效），故 payload 不再携带。
# ③ `channel` 合法值只有 wechat / sms / email / internal（DTO 注释；站内信 = internal），
#    此前的 `channel="system"` 同样不合法。
# ④ `recipientId` / `recipientType` 是 DTO 的 @NotBlank 必填字段 —— 缺一即**恒 400**
#    （曾因此让转人工通知永远发不出去，而失败被降级为 warning 后仍返回成功）。
# 收件人来源：GET /api/admin/users（AdminUserController；服务令牌 ROLE_SERVICE 绕过
# employee:list 权限，UserService.getUserPage 默认排除 role=customer）。
# recipientType 口径与 NotificationService.triggerForTenantAdmins 一致（users 表 = employee）。
_NOTIFY_RECIPIENT_PAGE_SIZE = 50
_NOTIFY_RECIPIENT_TYPE = "employee"
_NOTIFY_CHANNEL = "internal"        # 合法值仅 wechat / sms / email / internal
_NOTIFY_NO_RECIPIENT = "recipient_not_found"


def _build_notify_payload(
    *,
    ticket_no: str,
    handoff_reason: str,
    customer_id: Optional[str],
    recipient_id: str,
) -> Dict[str, Any]:
    """构造 CreateNotificationRequest 请求体（含全部 @NotBlank 必填字段）。

    issue #3553：此前漏发 recipientId/recipientType（DTO @NotBlank）→ admin-api 恒 400
    且被静默吞掉；`recipientRole`/`type` 不被 DTO 消费（静默忽略）、`channel="system"`
    亦非合法渠道值。字段集由测试对 DTO @NotBlank 做契约校验（防再漏字段）。
    """
    return {
        "recipientId": recipient_id,
        "recipientType": _NOTIFY_RECIPIENT_TYPE,
        "title": f"客户请求转人工 - {ticket_no}",
        "content": (
            f"🔔 客户请求转人工\n"
            f"工单编号：{ticket_no}\n"
            f"客户ID：{customer_id}\n"
            f"原因：{handoff_reason}"
        ),
        "channel": _NOTIFY_CHANNEL,
    }


def _clean_ai_context_message(msg: dict) -> Optional[dict]:
    """把 session_messages 行清洗为快照 turn；非 user/assistant 返回 None。

    - assistant 内容剥离 <think>...</think>（同 chat.py 对历史消息的处理）
    - 文本为空的多模态消息（图片等）以「[图片]」占位，不透传 URL（PII）
    - 每条 content 超长截断
    """
    role = msg.get("role")
    if role not in ("user", "assistant"):
        return None
    content_type = msg.get("content_type") or "text"
    content = (msg.get("content") or "").strip()
    if not content and content_type == "text":
        return None
    if not content:
        # 多模态（图片等）：占位，不透传 URL
        return {
            "role": role,
            "content": "[图片]",
            "contentType": content_type,
            "createdAt": str(msg.get("created_at") or ""),
        }
    if role == "assistant":
        content = _THINK_PATTERN.sub("", content).strip()
    if not content:
        return None
    if len(content) > _AI_CONTEXT_MAX_CHARS_PER_TURN:
        content = content[:_AI_CONTEXT_MAX_CHARS_PER_TURN] + "…（已截断）"
    turn: Dict[str, str] = {"role": role, "content": content}
    if content_type != "text":
        turn["contentType"] = content_type
    if msg.get("created_at"):
        turn["createdAt"] = str(msg["created_at"])
    return turn


async def _load_ai_context(session_id: Optional[str]) -> Dict[str, Any]:
    """取当前 AI 会话最近对话快照。

    非致命：任何异常仅记日志并返回空快照，绝不阻塞转人工主流程。
    """
    if not session_id:
        return {"summary": "", "messages": []}
    try:
        from app.memory.session_memory import SessionMemory
        messages = await SessionMemory().get_history(
            session_id, limit=_AI_CONTEXT_HISTORY_LIMIT
        )
    except Exception as e:
        logger.warning(
            f"[human_handoff] AI 上下文收集失败（非致命，转人工继续）: "
            f"{type(e).__name__}: {e}"
        )
        return {"summary": "", "messages": []}
    turns: list = []
    for msg in messages or []:
        turn = _clean_ai_context_message(msg)
        if turn:
            turns.append(turn)
        if len(turns) >= _AI_CONTEXT_MAX_TURNS:
            break
    return {"summary": "", "messages": turns}


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
    # requires_confirmation **刻意保持 False**（显式豁免，登记于
    # tests/test_write_tool_confirm_gate_invariant.py::CONFIRM_GATE_EXEMPT_WRITE_TOOLS，
    # issue #3594 确认门禁分类审计）：
    # 本工具虽是写操作（建工单/发通知/建人工会话），但**确认发生在上游流程**——
    #   D1 客户显式请求词命中 → intent_router 短路直转 complaint → 本工具；
    #   D2 商家 autoHandoffKeywords 命中 → 直转；
    #   D3 AI 主动建议 → handoff_offer 节点先发建议卡、**用户点卡确认后**才到本工具。
    # 三条入口都不存在「未确认即转人工」，在工具层再加一道 = 让顾客「求人还要再点一次卡」，
    # 且直接破坏用例锁定的语义（CH-008/CH-015/UI-010/ST-008）。
    # 该豁免是既有产品决策：docs/design/xiaobu-ai-handoff-guidance.md（第 25/64/244/264 行）
    # 明文「D1/D2 直转是产品共识…再加确认是负体验」，并把 requires_confirmation=True
    # 列为「会改变 CH-008 语义，须单独评审」。
    # 残留风险（已登记 #3594）：idempotent=False，重复调用产生重复工单 + 重复管理员通知；
    # 收敛点是幂等/去重（admin-api 或会话级一次性守卫），不是工具层确认门禁。

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
            "summary": {
                "type": "string",
                "description": "（选填）转人工前问题的简短摘要（1-2 句，可含订单号/商品等关键信息），供人工客服快速了解",
            },
        },
    }

    @staticmethod
    async def _notify_admins(
        context: ToolContext,
        ticket_no: str,
        handoff_reason: str,
    ) -> Dict[str, Any]:
        """通知租户 B 端账号：有新的转人工工单

        先解析真实收件人（优先 users.role='admin'，无管理员时回退租户内其他在职 B 端账号），
        再逐人创建站内信（一人失败不影响其余人）。

        issue #3553：此前不带 recipientId/recipientType → 恒 400，且失败只记 warning
        后仍返回成功 —— 通知永远发不出去而表面无异常。现在把「是否真的送达」返回给
        调用方，由 execute 决定结果，**不再静默降级**。

        Returns:
            {"delivered": int, "error": Optional[str]}
            - delivered > 0：至少一位收件人收到站内信；
            - delivered == 0：error 为未送达原因（`recipient_not_found` = 租户无在职
              B 端账号；`recipient_resolution_failed` / 其它 = 解析或投递失败）。
        """
        client = get_admin_api_client()
        try:
            users_response = await client.get(
                "/api/admin/users",
                params={
                    "page": 1,
                    "size": _NOTIFY_RECIPIENT_PAGE_SIZE,
                    "status": "active",
                },
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(
                f"[human_handoff] 通知收件人解析异常: ticket_no={ticket_no}, "
                f"error={type(e).__name__}: {e}"
            )
            return {"delivered": 0, "error": f"recipient_resolution_failed: {type(e).__name__}"}

        if not users_response.get("success"):
            error = (users_response.get("error") or {}).get("message", "unknown")
            logger.error(
                f"[human_handoff] 通知收件人解析失败: ticket_no={ticket_no}, error={error}"
            )
            return {"delivered": 0, "error": f"recipient_resolution_failed: {error}"}

        items = (users_response.get("data") or {}).get("items") or []
        # 优先管理员（与 NotificationService.triggerForTenantAdmins 的 users.role='admin' 口径一致）
        recipients = [u.get("id") for u in items if u.get("role") == "admin" and u.get("id")]
        if not recipients:
            # 无管理员账号时回退到租户内其他在职 B 端账号（接口已排除 role=customer）
            recipients = [u.get("id") for u in items if u.get("id")]
        if not recipients:
            logger.error(
                f"[human_handoff] 通知无收件人：租户内无在职 B 端账号（员工/管理员），"
                f"转人工站内信无法投递 | ticket_no={ticket_no}, tenant={context.tenant_id}"
            )
            return {"delivered": 0, "error": _NOTIFY_NO_RECIPIENT}

        delivered = 0
        last_error: Optional[str] = None
        for recipient_id in recipients:
            payload = _build_notify_payload(
                ticket_no=ticket_no,
                handoff_reason=handoff_reason,
                customer_id=context.user_id,
                recipient_id=recipient_id,
            )
            try:
                response = await client.post(
                    "/api/admin/notifications",
                    json_data=payload,
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.error(
                    f"[human_handoff] 转人工通知投递异常: ticket_no={ticket_no}, "
                    f"recipient={recipient_id}, error={last_error}"
                )
                continue
            if response.get("success"):
                delivered += 1
            else:
                last_error = (response.get("error") or {}).get("message", "unknown")
                logger.error(
                    f"[human_handoff] 转人工通知投递失败: ticket_no={ticket_no}, "
                    f"recipient={recipient_id}, error={last_error}"
                )

        if delivered:
            logger.info(
                f"[human_handoff] Admin notified: ticket_no={ticket_no}, "
                f"recipients={delivered}/{len(recipients)} | tenant={context.tenant_id}"
            )
        return {
            "delivered": delivered,
            "error": None if delivered else (last_error or "delivery_failed"),
        }

    async def execute(
        self,
        context: ToolContext,
        reason: Optional[str] = None,
        description: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> ToolResult:
        """执行转人工操作

        创建投诉工单 → 通知管理员 → 创建人工会话（携带 AI 对话上下文快照）→ 返回安抚话术

        Args:
            context: Tool 执行上下文
            reason: 转人工原因
            description: 详细描述
            summary: 一句话摘要（选填，供人工客服快速了解）

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
                # 工单真实来源（issue #3686）：转人工工单的发起方就是当前会话调用方 ——
                # C 端小布顾客转人工 → "customer"；B 端米宝转人工 → "agent"。
                # 放 header 不放 body（同 #3605 取舍：来源不由 payload 决定）。
                headers={
                    "X-Agent-Client": context.ticket_source,
                    # 幂等键（issue #4037 / F19）：同一重试窗内取值相同 ⇒ 服务端去重，
                    # 「已建单但客户端报失败」后重试**只落一张工单**。
                    CLIENT_REQUEST_ID_HEADER: _request_window_id(),
                },
            )

            if not response.get("success"):
                error_msg = response.get("error", {}).get("message", "创建工单失败")
                return admin_api_failure(response,
                    error=error_msg,
                    message=f"转人工失败：{error_msg}",
                    suggestion=("请先核实转人工工单是否已经建好（不要重复调用）；"
                                "顾客着急时可直接拨打客服热线"),
                )

            ticket_data = response.get("data", {})
            ticket_no = ticket_data.get("ticketNo", ticket_data.get("id", ""))

            logger.info(
                f"[human_handoff] Handoff ticket created: ticket_no={ticket_no} | "
                f"tenant={context.tenant_id}, user={context.user_id}"
            )

            # Gap-3 安全加固: 通知管理员（issue #3553：失败不再静默，见下方结果判定）
            notify = await self._notify_admins(context, ticket_no, handoff_reason)

            # GB-01（GB/T 47746-2026）：转人工时点携带 AI 对话上下文快照，
            # 让人工客服无需顾客复述即可了解已沟通内容（非致命，失败留空继续）。
            ai_context = await _load_ai_context(context.session_id)
            if summary:
                ai_context["summary"] = (summary or "").strip()[:_AI_CONTEXT_MAX_CHARS_PER_TURN]

            # 创建人工客服会话（客服工作台可见、可对话）——转人工核心闭环
            agent_session_id = None
            try:
                session_response = await client.post(
                    "/api/admin/agent-sessions",
                    json_data={
                        "aiSessionId": context.session_id,
                        "customerId": context.user_id,
                        "reason": handoff_reason,
                        "aiContextSummary": ai_context.get("summary") or "",
                        "aiContextMessages": ai_context.get("messages") or [],
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
            data["adminNotified"] = notify["delivered"] > 0

            # issue #3553：通知是否真的送达必须体现在结果里 —— 不允许「发失败还报成功」。
            if notify["delivered"] <= 0:
                if notify["error"] == _NOTIFY_NO_RECIPIENT:
                    # 租户内没有在职 B 端账号 → 系统里没有"人"可通知（工单与人工会话仍已创建、
                    # 客服工作台可见），转人工本身已被受理（success=True），但必须显式可见：
                    # ERROR 日志 + error/suggestion 让 LLM 与运营都能发现配置缺口。
                    return ToolResult(
                        success=True,
                        data=data,
                        error="admin_notification_skipped_no_recipient",
                        message=(
                            f"已为您转接人工客服！工单编号：{ticket_no}。"
                            "我们的客服人员会在工作时间内尽快与您联系，感谢您的耐心等待 🙏"
                        ),
                        summary=(
                            f"转人工成功但无通知收件人: 工单{ticket_no}, "
                            f"租户内无在职 B 端账号"
                        ),
                        suggestion=(
                            "转人工站内信无收件人（租户内无在职 B 端账号）：请先在"
                            "「设置-员工管理」添加管理员/员工账号并置为在职，否则客服不会收到转人工提醒"
                        ),
                        terminal=True,
                    )
                return ToolResult(
                    success=False,
                    data=data,
                    error="admin_notification_failed",
                    message=(
                        f"已为您登记转人工工单（编号：{ticket_no}），但通知人工客服失败。"
                        "请直接拨打客服热线联系我们，我们会尽快为您处理 🙏"
                    ),
                    summary=(
                        f"转人工通知未送达: 工单{ticket_no}, error={notify['error']}"
                    ),
                    # 明确 suggestion 且禁止重试（human_handoff 非幂等，重试会重复建单）
                    suggestion=(
                        f"转人工站内信未送达（管理员不会收到提醒），原因：{notify['error']}。"
                        "工单已创建，**不要再次调用 human_handoff**（会重复建单）；"
                        "请告知顾客拨打客服热线，或稍后由运营在通知中心/工单列表兜底跟进"
                    ),
                )

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
                # 话术去「重试」（issue #4037 / F19）：HTTP 超时 25s < 工具超时 30s
                # ⇒ 这次失败**可能已经建单**，让模型重试等于重复建单。
                message="转人工没有成功返回。**先不要重复转人工** —— 请先核实工单是否已经建好。",
                suggestion=("先核实转人工工单/人工会话是否已经建好（不要重复调用 human_handoff）；"
                            "确实没有，再重新转一次，顾客着急时可直接拨打客服热线"),
            )
