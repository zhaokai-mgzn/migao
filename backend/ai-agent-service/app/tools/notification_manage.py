"""
AI 智能客服系统 - 通知管理 Tool

管理系统通知，支持查询通知列表、获取未读数、标记已读、全部已读、删除通知、创建通知。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
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
        "通知管理工具，支持查询通知列表、获取未读通知数量、标记已读、全部已读、删除通知、创建通知。"
        "当需要查看或管理系统通知时使用。"
    )

    allowed_roles = ["admin", "agent", "tenant_admin"]

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
                "description": "接收人用户 ID（create 时必填）",
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
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
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
                )

        except Exception as e:
            logger.error(f"Notification manage error: action={action}, error={e}")
            return ToolResult(
                success=False,
                error=str(e),
                message="通知操作失败，请稍后重试",
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
        params: Dict[str, Any] = {"page": page, "size": size}
        if status:
            if status not in VALID_STATUSES:
                return ToolResult(
                    success=False,
                    error=f"无效的通知状态: {status}",
                    message=f"不支持的状态筛选，可选：{', '.join(VALID_STATUSES)}",
                )
            # 映射为 admin-api 实际状态值（unread → sent）
            params["status"] = STATUS_TO_API.get(status, status)
        if channel:
            if channel not in VALID_CHANNELS:
                return ToolResult(
                    success=False,
                    error=f"无效的通知渠道: {channel}",
                    message=f"不支持的通知渠道，可选：{', '.join(VALID_CHANNELS)}",
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
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"查询通知列表失败：{error_msg}",
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
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"获取未读数失败：{error_msg}",
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
            )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/notifications/{notification_id}/read",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "操作失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"标记已读失败：{error_msg}",
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
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"全部标记已读失败：{error_msg}",
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
            )

        client = get_admin_api_client()
        response = await client.delete(
            f"/api/admin/notifications/{notification_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "删除失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"删除通知失败：{error_msg}",
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
        """创建通知"""
        if not recipient_id:
            return ToolResult(
                success=False,
                error="缺少接收人 ID",
                message="创建通知时必须提供接收人用户 ID（recipient_id）",
            )

        if not title:
            return ToolResult(
                success=False,
                error="缺少通知标题",
                message="创建通知时必须提供通知标题（title）",
            )

        if not content:
            return ToolResult(
                success=False,
                error="缺少通知内容",
                message="创建通知时必须提供通知内容（content）",
            )

        json_data: Dict[str, Any] = {
            "recipientId": recipient_id,
            "title": title,
            "content": content,
        }
        if channel:
            if channel not in VALID_CHANNELS:
                return ToolResult(
                    success=False,
                    error=f"无效的通知渠道: {channel}",
                    message=f"不支持的通知渠道，可选：{', '.join(VALID_CHANNELS)}",
                )
            # 映射为 admin-api 实际渠道值（system → internal）
            json_data["channel"] = CHANNEL_TO_API.get(channel, channel)

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/notifications",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "创建失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"创建通知失败：{error_msg}",
            )

        data = response.get("data", {})
        new_id = data.get("id", "")

        logger.info(
            f"Notification created: id={new_id}, recipient={recipient_id}, "
            f"title={title}, tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data=data,
            message=f"通知已创建并发送给用户 {recipient_id}",
        )
