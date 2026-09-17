"""
AI 智能客服系统 - 通知管理 Tool

管理系统通知，支持查询通知列表、获取未读数、标记已读、全部已读、删除通知、创建通知。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"list", "unread_count", "mark_read", "read_all", "delete", "create"}

# 通知渠道
VALID_CHANNELS = {"system", "email", "sms", "wechat"}

# 通知状态
VALID_STATUSES = {"unread", "read"}

# 渠道值映射：tool 暴露给 LLM 的语义化值 → admin-api 实际使用的值
# admin-api 数据库中站内通知 channel 字段实际值为 "internal"，而非 "system"
CHANNEL_TO_API = {
    "system": "internal",
    "internal": "internal",
    "email": "email",
    "sms": "sms",
    "wechat": "wechat",
}

# 状态值映射：tool 暴露的语义化值 → admin-api 数据库实际状态
# admin-api notifications.status 实际值为 "sent"（未读）/ "read"（已读）
STATUS_TO_API = {
    "unread": "sent",
    "read": "read",
}

# ── 创建通知收件人（issue #3567，HIGH：B 端「创建通知」能力实际不可用）────────
# ⚠️ 后来者注意（这四条最容易再踩，issue #3567 与 #3553 同型）：
# ① admin-api `POST /api/admin/notifications` **按收件人落库，没有广播语义** ——
#    站内信按 recipientId 分发给该用户（NotificationController.getUnreadCount →
#    getCurrentUserId()），收件人必须由调用方**显式解析**，否则落库后谁也看不到。
# ② `recipientId` / `recipientType` 是 CreateNotificationRequest 的 @NotBlank 必填字段
#    —— 缺一即**恒 400**（此前漏发 recipientType，创建通知永远失败）。
# ③ `recipientType` 合法口径 = "employee"（口径同 NotificationService.triggerForTenantAdmins
#    L366 `ctx.put("recipientType", "employee")`；DTO 注释亦为 user / employee）。
# ④ `channel` 合法值只有 wechat / sms / email / internal（DTO L39-41，默认 internal）
#    —— tool schema 暴露的 "system" 只是语义化别名，必须经 CHANNEL_TO_API 映射后再发。
# 收件人来源：GET /api/admin/users（AdminUserController；服务令牌 ROLE_SERVICE 绕过
# employee:list 权限；UserService.getUserPage 默认排除 role=customer）。
_NOTIFY_RECIPIENT_TYPE = "employee"
_NOTIFY_RECIPIENT_LOOKUP_SIZE = 50
_NOTIFY_NO_RECIPIENT = "notification_skipped_no_recipient"
_NOTIFY_RECIPIENT_NOT_FOUND = "notification_recipient_not_found"
_NOTIFY_RESOLUTION_FAILED = "notification_recipient_resolution_failed"
_NOTIFY_SEND_FAILED = "notification_send_failed"


def _build_notification_payload(
    *,
    recipient_id: str,
    title: str,
    content: str,
    channel: Optional[str],
) -> Dict[str, Any]:
    """构造 CreateNotificationRequest 请求体（含全部 @NotBlank 必填字段）。

    issue #3567：此前漏发 recipientType（DTO @NotBlank）→ admin-api 恒 400；
    channel 走 CHANNEL_TO_API 映射，保证发出的值属合法集合（wechat/sms/email/internal）。
    """
    return {
        "recipientId": recipient_id,
        "recipientType": _NOTIFY_RECIPIENT_TYPE,
        "title": title,
        "content": content,
        "channel": CHANNEL_TO_API.get(channel or "system", "internal"),
    }


async def _resolve_tenant_recipients(context: ToolContext) -> tuple:
    """解析租户内可接收站内信的 B 端账号（员工/管理员，接口已排除 role=customer）。

    Returns:
        (recipients, error)：recipients 为 [{"id", "name", "role"}]，管理员优先；
        解析失败时 recipients 为空且 error 非空（由调用方决定分级语义）。
    """
    client = get_admin_api_client()
    try:
        response = await client.get(
            "/api/admin/users",
            params={"page": 1, "size": _NOTIFY_RECIPIENT_LOOKUP_SIZE, "status": "active"},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
    except Exception as e:
        logger.error(
            f"[notification_manage] 收件人解析异常: tenant={context.tenant_id}, "
            f"error={type(e).__name__}: {e}"
        )
        return [], f"{type(e).__name__}: {e}"

    if not response.get("success"):
        error = (response.get("error") or {}).get("message", "unknown")
        logger.error(
            f"[notification_manage] 收件人解析失败: tenant={context.tenant_id}, error={error}"
        )
        return [], str(error)

    items = (response.get("data") or {}).get("items") or []
    recipients = [
        {"id": u.get("id"), "name": u.get("name"), "role": u.get("role")}
        for u in items if u.get("id")
    ]
    # 优先管理员（口径同 NotificationService.triggerForTenantAdmins: users.role='admin'），
    # 其余在职 B 端账号一并保留（供 LLM 在收件人缺失时自纠）
    recipients.sort(key=lambda u: u.get("role") != "admin")
    return recipients, None


class NotificationManageTool(BaseTool):
    """通知管理 Tool

    管理系统通知：查询列表、获取未读数、标记已读、全部已读、删除通知、创建通知。

    使用场景：
    - 查询通知列表，按状态或渠道筛选
    - 获取未读通知数量
    - 标记单条通知为已读
    - 标记全部通知为已读
    - 删除通知
    - 创建新通知发送给指定用户
    """

    name = "notification_manage"
    description = (
        "【触发】用户问'通知''消息''未读''有没有通知''发送通知''标记已读'时调用。【前置】list/unread_count 可查询。mark_read 需要通知ID。create 需要标题+内容+接收人。【反例】系统配置用 settings_manage。【标注】WRITE(create/delete) — 发送/删除通知需确认。"
        "【铁律】用户明确要求写操作（禁用/创建/调整/删除/上下架/重置等）时：先查必要信息拿真实 ID → 展示操作预览 + 确认卡 → 用户确认后立即调用写工具执行，禁止只查询/展示列表就停（HR-003/PP-006/PR-005 实拍：agent 只 list/query 不执行写工具判失败）。"
        "【铁律】用户说标为已读/把XX通知标为已读时：先 list 拿通知 ID，必须立即调 mark_read（单条）或 read_all（全部已读）执行，禁止只展示未读列表就停（ST-005 实拍：只 list 不 mark_read 判失败）。"
    )
    allowed_roles = ["admin", "agent", "tenant_admin", "operator"]

    read_only = False
    requires_confirmation = True  # 审计 07 P0-L1: 高风险非 destructive 写操作需用户确认
    read_only_actions = {"list", "unread_count"}  # 只读 action 免确认
    destructive = False  # 通知的删除非破坏性（可重新发送）
    idempotent = False   # 创建/删除非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型：list（查询列表）/ unread_count（未读数）/ mark_read（标记已读）/ "
                    "read_all（全部已读）/ delete（删除）/ create（创建通知）"
                ),
                "enum": ["list", "unread_count", "mark_read", "read_all", "delete", "create"],
            },
            "notification_id": {
                "type": "string",
                "description": "通知 ID（mark_read/delete 时必填）",
            },
            "recipient_id": {
                "type": "string",
                "description": (
                    "接收人用户 ID（create 时必填）——必须是本租户**在职员工/管理员**账号 ID"
                    "（站内信按该 ID 分发给本人，无广播语义；不存在的 ID 会被拒绝）"
                ),
            },
            "title": {
                "type": "string",
                "description": "通知标题（create 时必填）",
            },
            "content": {
                "type": "string",
                "description": "通知内容（create 时必填）",
            },
            "channel": {
                "type": "string",
                "description": "通知渠道：system（站内）/ email（邮件）/ sms（短信）/ wechat（微信）",
                "enum": ["system", "email", "sms", "wechat"],
            },
            "status": {
                "type": "string",
                "description": "通知状态筛选：unread（未读）/ read（已读）",
                "enum": ["unread", "read"],
            },
            "page": {
                "type": "integer",
                "description": "页码，默认 1",
                "default": 1,
            },
            "size": {
                "type": "integer",
                "description": "每页数量，默认 10",
                "default": 10,
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        notification_id: Optional[str] = None,
        recipient_id: Optional[str] = None,
        title: Optional[str] = None,
        content: Optional[str] = None,
        channel: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 10,
        **kwargs,
    ) -> ToolResult:
        """执行通知管理操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行通知管理操作",
                suggestion="请联系管理员获取执行通知管理操作权限",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )

        try:
            if action == "list":
                return await self._list_notifications(context, page, size, status, channel)
            elif action == "unread_count":
                return await self._unread_count(context)
            elif action == "mark_read":
                return await self._mark_read(context, notification_id)
            elif action == "read_all":
                return await self._read_all(context)
            elif action == "delete":
                return await self._delete_notification(context, notification_id)
            elif action == "create":
                return await self._create_notification(context, recipient_id, title, content, channel)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )

        except Exception as e:
            logger.error(f"Notification manage error: action={action}, error={e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="通知操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    async def _list_notifications(
        self,
        context: ToolContext,
        page: int,
        size: int,
        status: Optional[str],
        channel: Optional[str],
    ) -> ToolResult:
        """查询通知列表"""
        page = int(page) if page else 1
        size = int(size) if size else 10
        params: Dict[str, Any] = {"page": page, "size": size}
        if status:
            if status not in VALID_STATUSES:
                return ToolResult(
                    success=False,
                    error=f"无效的通知状态: {status}",
                    message=f"不支持的状态筛选，可选：{', '.join(VALID_STATUSES)}",
                    suggestion="请改用合法状态筛选（见错误提示中的可选值）后重试，不要自行传其它状态",
                )
            # 映射为 admin-api 实际状态值（unread → sent）
            params["status"] = STATUS_TO_API.get(status, status)
        if channel:
            if channel not in VALID_CHANNELS:
                return ToolResult(
                    success=False,
                    error=f"无效的通知渠道: {channel}",
                    message=f"不支持的通知渠道，可选：{', '.join(VALID_CHANNELS)}",
                    suggestion="请改用合法通知渠道（见错误提示中的可选值）后重试，不要自行传其它渠道",
                )
            # 映射为 admin-api 实际渠道值（system → internal）
            params["channel"] = CHANNEL_TO_API.get(channel, channel)

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/notifications",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message=f"查询通知列表失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请改为不带筛选条件查询，或请用户联系管理员核对通知数据",
            )

        data = response.get("data", {})
        items = data.get("items", [])
        total = data.get("total", 0)

        logger.info(
            f"Notifications list: page={page}, size={size}, total={total}, "
            f"tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"items": items, "total": total, "page": page, "size": size},
            message=f"共找到 {total} 条通知",
        )

    async def _unread_count(
        self,
        context: ToolContext,
    ) -> ToolResult:
        """获取未读通知数量"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/notifications/unread-count",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message=f"获取未读数失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请改用 list 操作查询未读通知条数，或请用户稍后再看",
            )

        data = response.get("data", {})
        count = data.get("count", 0)

        logger.info(
            f"Notifications unread count: count={count}, tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"unread_count": count},
            message=f"您有 {count} 条未读通知",
        )

    async def _mark_read(
        self,
        context: ToolContext,
        notification_id: Optional[str],
    ) -> ToolResult:
        """标记通知为已读"""
        if not notification_id:
            return ToolResult(
                success=False,
                error="缺少通知 ID",
                message="标记已读时必须提供通知 ID（notification_id）",
                suggestion="缺少 notification_id，请先用 notification_manage 的 list 操作取到通知 ID 后重试",
            )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/notifications/{notification_id}/read",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "操作失败")
            return admin_api_failure(response,
                error=error_msg,
                message=f"标记已读失败：{error_msg}",
                suggestion="请先用 notification_manage 的 list 操作确认该通知存在且未读，再重新执行标记已读",
            )

        logger.info(
            f"Notification marked read: id={notification_id}, tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"notification_id": notification_id, "status": "read"},
            message="通知已标记为已读",
        )

    async def _read_all(
        self,
        context: ToolContext,
    ) -> ToolResult:
        """标记全部通知为已读"""
        client = get_admin_api_client()
        response = await client.put(
            "/api/admin/notifications/read-all",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "操作失败")
            return admin_api_failure(response,
                error=error_msg,
                message=f"全部标记已读失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请提示用户逐条标记已读，或请用户联系管理员核对通知服务",
            )

        logger.info(
            f"All notifications marked read: tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"status": "all_read"},
            message="所有通知已标记为已读",
        )

    async def _delete_notification(
        self,
        context: ToolContext,
        notification_id: Optional[str],
    ) -> ToolResult:
        """删除通知"""
        if not notification_id:
            return ToolResult(
                success=False,
                error="缺少通知 ID",
                message="删除通知时必须提供通知 ID（notification_id）",
                suggestion="缺少 notification_id，请先用 notification_manage 的 list 操作取到通知 ID 后重试",
            )

        client = get_admin_api_client()
        response = await client.delete(
            f"/api/admin/notifications/{notification_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "删除失败")
            return admin_api_failure(response,
                error=error_msg,
                message=f"删除通知失败：{error_msg}",
                suggestion="请先用 notification_manage 的 list 操作确认该通知仍在（已删除的不可重复删），再重试",
            )

        logger.info(
            f"Notification deleted: id={notification_id}, tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"notification_id": notification_id},
            message="通知已删除",
        )

    async def _create_notification(
        self,
        context: ToolContext,
        recipient_id: Optional[str],
        title: Optional[str],
        content: Optional[str],
        channel: Optional[str],
    ) -> ToolResult:
        """创建通知

        issue #3567：`POST /api/admin/notifications` 按收件人落库（无广播语义）且
        `recipientId`/`recipientType` 为 DTO @NotBlank 必填 —— 收件人必须**显式解析**
        为租户内在职 B 端账号（getUserPage 已排除 role=customer），并且
        **不允许兼容性猜测**：解析不到收件人时显式失败，绝不静默成功（落一条无人可见的通知）。

        分级语义（口径同 human_handoff #3553）：
        - 解析/投递失败 → `success=False`（`notification_recipient_resolution_failed` /
          `notification_recipient_not_found` / `notification_send_failed`）；
        - 租户内无在职 B 端账号（没人可通知）→ `success=True` 但显式带
          `error=notification_skipped_no_recipient` + `data.notificationSent=False` + ERROR 日志。
        """
        if not recipient_id:
            return ToolResult(
                success=False,
                error="缺少接收人 ID",
                message="创建通知时必须提供接收人用户 ID（recipient_id）",
                suggestion="缺少 recipient_id，请先用 employee_manage 的 list 操作查到在职员工后再重试",
            )

        if not title:
            return ToolResult(
                success=False,
                error="缺少通知标题",
                message="创建通知时必须提供通知标题（title）",
                suggestion="缺少通知标题 title，请向用户询问要发送的通知标题后重试",
            )

        if not content:
            return ToolResult(
                success=False,
                error="缺少通知内容",
                message="创建通知时必须提供通知内容（content）",
                suggestion="缺少通知内容 content，请向用户询问要发送的通知内容后重试",
            )

        if channel and channel not in VALID_CHANNELS:
            return ToolResult(
                success=False,
                error=f"无效的通知渠道: {channel}",
                message=f"不支持的通知渠道，可选：{', '.join(VALID_CHANNELS)}",
                suggestion="请改用合法通知渠道（见错误提示中的可选值）后重试，不要自行改写渠道名",
            )

        recipients, resolve_error = await _resolve_tenant_recipients(context)
        if resolve_error:
            # 投递/解析失败 → 显式失败（不猜、不静默）
            return ToolResult(
                success=False,
                error=_NOTIFY_RESOLUTION_FAILED,
                message=f"创建通知失败：无法确认接收人（{resolve_error}）",
                suggestion="收件人解析失败（admin-api 不可用或权限不足），请稍后重试",
            )

        if not recipients:
            # 租户内无在职 B 端账号：系统里没有「人」可通知 —— 站内信落库即无人可见，
            # 故不发出请求，但必须显式可见（error + data.notificationSent=false，绝不静默）
            logger.error(
                f"[notification_manage] 创建通知中止：租户内无在职 B 端账号（员工/管理员），"
                f"站内信无收件人 | recipient_id={recipient_id}, tenant={context.tenant_id}"
            )
            return ToolResult(
                success=True,
                data={
                    "notificationSent": False,
                    "recipientId": recipient_id,
                    "availableRecipients": [],
                },
                error=_NOTIFY_NO_RECIPIENT,
                message=f"通知未发送：租户内没有可接收站内信的在职账号（原定接收人 {recipient_id}）",
                suggestion=(
                    "请在「设置-员工管理」添加管理员/员工账号并置为在职后再发送通知"
                ),
            )

        matched = next((r for r in recipients if r["id"] == recipient_id), None)
        if matched is None:
            # 收件人不是租户内在职 B 端账号：落库也会成为无人可见的孤儿通知 → 显式失败，
            # 并回传真实可选收件人供 LLM 自纠（不做「随便换个人发」的兼容性猜测）
            available = [r["id"] for r in recipients]
            logger.error(
                f"[notification_manage] 创建通知中止：收件人不在租户在职 B 端账号内 | "
                f"recipient_id={recipient_id}, tenant={context.tenant_id}, available={available}"
            )
            return ToolResult(
                success=False,
                data={
                    "notificationSent": False,
                    "recipientId": recipient_id,
                    "availableRecipients": available,
                },
                error=_NOTIFY_RECIPIENT_NOT_FOUND,
                message=f"通知未发送：接收人 {recipient_id} 不是本租户在职员工/管理员账号",
                suggestion=(
                    f"接收人 ID 不存在或已停用，请改用真实在职账号 ID 后重试"
                    f"（可选：{', '.join(available)}）"
                ),
            )

        json_data = _build_notification_payload(
            recipient_id=recipient_id, title=title, content=content, channel=channel,
        )

        client = get_admin_api_client()
        try:
            response = await client.post(
                "/api/admin/notifications",
                json_data=json_data,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(
                f"[notification_manage] 创建通知投递异常: recipient={recipient_id}, "
                f"tenant={context.tenant_id}, error={type(e).__name__}: {e}"
            )
            return ToolResult(
                success=False,
                data={"notificationSent": False, "recipientId": recipient_id},
                error=_NOTIFY_SEND_FAILED,
                message="创建通知失败：通知投递异常，请稍后重试",
                suggestion="通知投递失败，请稍后重试；若持续失败请联系技术支持",
            )

        if not response.get("success"):
            error_msg = (response.get("error") or {}).get("message", "创建失败")
            logger.error(
                f"[notification_manage] 创建通知投递失败: recipient={recipient_id}, "
                f"tenant={context.tenant_id}, error={error_msg}"
            )
            return admin_api_failure(response,
                data={"notificationSent": False, "recipientId": recipient_id},
                error=_NOTIFY_SEND_FAILED,
                message=f"创建通知失败：{error_msg}",
                suggestion="通知未送达，请稍后重试；若持续失败请联系技术支持",
            )

        data = dict(response.get("data") or {})
        new_id = data.get("id", "")
        data["notificationSent"] = True
        data["recipientId"] = recipient_id
        data["recipientType"] = _NOTIFY_RECIPIENT_TYPE

        logger.info(
            f"Notification created: id={new_id}, recipient={recipient_id}, "
            f"title={title}, tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data=data,
            message=f"通知已创建并发送给用户 {recipient_id}",
        )
