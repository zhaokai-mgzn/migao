"""
AI 智能客服系统 - 通知管理 Tool（**只读**）

查询站内通知列表与未读数。

🔴 **B 端米宝只读化**（issue #5247 用户裁定 2026-09-23；settings 域整域收编 = issue #5302）：
`mark_read` / `read_all` / `delete` / `create` 四个写 action **已从本工具删除**，
对应写方法与**写参数**（`notification_id` / `recipient_id` / `title` / `content`）一并删除，
连只服务 `create` 的收件人解析机具（`_resolve_tenant_recipients` /
`_build_notification_payload` / `_NOTIFY_*` 常量）也一并退场 —— 只读工具里留一套不可达的
写机具，下一个人加一行 `VALID_ACTIONS` 就能把能力接回来。

⚠️ `VALID_ACTIONS` 是本工具 action 面的**唯一真值**（判据：
`backend/ai-agent-service/tests/test_settings_domain_readonly.py` +
`tests/unit_ci_workflows/test_mibao_b_end_readonly.py` 的判据 6）。

⚠️ 权限面（#5302，与 admin-api 端点逐条对齐）：本工具**仍调用**的两个读端点
（`GET /api/admin/notifications`、`GET /api/admin/notifications/unread-count`）在
`NotificationController` 里**都没有** `@RequirePermission`（读面是自助语义）⇒ 本工具
**不声明权限码**、回到**角色层**（`allowed_roles` 必须在类体显式声明，见下）。
原 `["system:manage", "employee:list"]` 是写路径的码（前者 = `POST` 建通知，后者 = create
解析收件人用的 `GET /api/admin/users`）⇒ 随写 action 一并移除（判据：残留写码会把
「通知中心」这个全员可见页的能力收窄成"只有持码岗位可用"）。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型 —— **全部只读**（#5302）
VALID_ACTIONS = {"list", "unread_count"}

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


class NotificationManageTool(BaseTool):
    """通知管理 Tool（只读）

    查询站内通知列表与未读数。

    使用场景：
    - 查询通知列表，按状态或渠道筛选
    - 获取未读通知数量

    **不提供**：标记已读 / 全部已读 / 删除通知 / 创建通知 —— 引导用户到商户后台
    「通知中心」页自助处理。
    """

    name = "notification_manage"
    description = (
        "【触发】用户问'通知''消息''未读''有没有通知'时调用。"
        "【参数】action 必填：**只有 list（查询列表）/ unread_count（未读数）两个只读 action**"
        "（B 端已只读化，issue #5247 / #5302）。"
        "【反例】系统配置/AI 配置用 settings_manage；查会话用 session_manage。"
        "【反例】标记已读 / 全部已读 / 删除通知 / 发送通知**不在本工具能力内** —— "
        "如实告知用户，并引导其到商户后台「通知中心」页自助处理。"
        "【标注】READONLY — 纯查询，不含任何写 action"
    )
    # 角色层（**唯一**门禁）：两个读端点在 admin-api 里没有权限码（自助语义）⇒ 工具不持码。
    # 必须**显式**声明（不吃 `BaseTool` 默认值 —— 默认值含 C 端角色 `customer`/`agent`、
    # 幽灵角色 `tenant_admin` 与 `guest`，属横向越权/跨服务口径断裂，issue #5246 判据 6）。
    # 🔴 取值口径 = **零回归**（#5302 的最小行为变化）：改前本工具的权限码层实际只放行
    # admin（`*` 通配）+ operator（唯一持 `employee:list` 的商户岗位）⇒ 角色层按**同一集合**
    # 声明，读面既不放宽也不收窄。后台「通知中心」页面对全岗位可见，但**工具面**要不要跟着
    # 放开到其它岗位属产品裁定（会改变授权面），不在本单范围内 —— 要放开须同批改本声明
    # 与 `backend/ai-agent-service/tests/test_settings_domain_readonly.py` 的判据。
    # 判据：`tests/test_tool_permission_codes.py` 要求「无码的 B 端工具必须被显式登记
    # （ROLE_GATED_B_SIDE_TOOLS）且保留角色白名单」。
    allowed_roles = ["admin", "operator"]

    read_only = True
    read_only_actions = {"list", "unread_count"}  # 只读 action 免确认拦截

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：list（查询列表）/ unread_count（未读数）—— 均为只读",
                "enum": ["list", "unread_count"],
            },
            "channel": {
                "type": "string",
                "description": "通知渠道筛选：system（站内）/ email（邮件）/ sms（短信）/ wechat（微信）",
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
        channel: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 10,
        **kwargs,
    ) -> ToolResult:
        """执行通知**查询**操作"""
        # 权限检查（角色层：本工具没有目录权限码）
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行通知管理操作",
                suggestion="请联系管理员获取执行通知管理操作权限",
            )

        # 参数校验（写 action 在这里即被拒 —— 不是"描述里没写"，而是**不存在**）
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(sorted(VALID_ACTIONS))}",
                suggestion=(
                    "本工具只提供只读查询（list / unread_count）。"
                    "标记已读 / 全部已读 / 删除通知 / 发送通知不在本工具能力内 —— "
                    "请如实告知用户，并引导其到商户后台「通知中心」页自助处理"
                ),
            )

        try:
            if action == "list":
                return await self._list_notifications(context, page, size, status, channel)
            elif action == "unread_count":
                return await self._unread_count(context)
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
                    message=f"不支持的状态筛选，可选：{', '.join(sorted(VALID_STATUSES))}",
                    suggestion="请改用合法状态筛选（见错误提示中的可选值）后重试，不要自行传其它状态",
                )
            # 映射为 admin-api 实际状态值（unread → sent）
            params["status"] = STATUS_TO_API.get(status, status)
        if channel:
            if channel not in VALID_CHANNELS:
                return ToolResult(
                    success=False,
                    error=f"无效的通知渠道: {channel}",
                    message=f"不支持的通知渠道，可选：{', '.join(sorted(VALID_CHANNELS))}",
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