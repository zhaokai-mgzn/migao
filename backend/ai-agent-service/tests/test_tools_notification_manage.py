"""NotificationManageTool 单元测试 — 通知查询/标记已读/删除/创建。

issue #3567（HIGH）：`create` action 实际不可用 —— `_create_notification` 漏发
`CreateNotificationRequest.recipientType`（DTO `@NotBlank`）→ admin-api 恒 400。
"""
# case_ids: ST-004, ST-005
import re
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.notification_manage import NotificationManageTool

# ── issue #3567：站内信按 recipientId 落库（无广播语义），故必须解析真实收件人 ──
_ACTIVE_EMPLOYEE = {"id": "emp_001", "role": "operator", "status": "active"}


def _mock_notify_client(post_responses, *, recipients=None):
    """mock admin-api 客户端：GET /api/admin/users 解析收件人 + POST 按序返回。

    recipients=None → 默认一位在职 B 端账号；recipients=[] → 租户内无在职 B 端账号。
    """
    client = AsyncMock()
    items = (
        [{"id": r, "role": "operator", "status": "active"} for r in recipients]
        if recipients is not None
        else [_ACTIVE_EMPLOYEE]
    )
    client.get = AsyncMock(return_value={"success": True, "data": {"items": items}})
    client.post = AsyncMock(side_effect=post_responses)
    return client


def _notify_payloads(client):
    """取实际发往 /api/admin/notifications 的 payload 列表。"""
    return [
        call[1]["json_data"] for call in client.post.call_args_list
        if call[0][0] == "/api/admin/notifications"
    ]


@pytest.fixture
def tool():
    return NotificationManageTool()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    client.delete = AsyncMock()
    return client


@pytest.fixture
def agent_tool_context():
    return ToolContext(tenant_id=1, user_id="agent_001", session_id="sess", role="agent")


class TestNotificationPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="list")
        assert result.success is False
        assert "权限" in result.error

    async def test_agent_allowed(self, tool, agent_tool_context):
        with patch("app.tools.notification_manage.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
            mock_get_client.return_value = mock_client
            result = await tool.execute(context=agent_tool_context, action="list")
            assert result.success is True

    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="broadcast")
        assert result.success is False
        assert "无效的操作类型" in result.error


class TestNotificationList:
    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_list_passthrough_with_mapping(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={
            "success": True, "data": {"items": [{"id": "n1"}], "total": 1},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="list", page="2", size="5", status="unread", channel="system")
        assert result.success is True
        assert result.data["total"] == 1
        params = mock_client.get.call_args[1]["params"]
        assert params["page"] == 2
        assert params["size"] == 5
        # 状态映射 unread→sent；渠道映射 system→internal
        assert params["status"] == "sent"
        assert params["channel"] == "internal"

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_list_invalid_status(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="list", status="archived")
        assert result.success is False
        assert "无效的通知状态" in result.error
        mock_client.get.assert_not_called()

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_list_invalid_channel(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="list", channel="carrier_pigeon")
        assert result.success is False
        assert "无效的通知渠道" in result.error
        mock_client.get.assert_not_called()


class TestNotificationUnreadCount:
    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_unread_count(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"count": 5}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="unread_count")
        assert result.success is True
        assert result.data["unread_count"] == 5
        assert mock_client.get.call_args[0][0] == "/api/admin/notifications/unread-count"


class TestNotificationMarkRead:
    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_mark_read_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="mark_read")
        assert result.success is False
        assert "缺少通知 ID" in result.error
        mock_client.put.assert_not_called()

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_mark_read_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="mark_read", notification_id="n1")
        assert result.success is True
        assert mock_client.put.call_args[0][0] == "/api/admin/notifications/n1/read"

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_read_all(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="read_all")
        assert result.success is True
        assert mock_client.put.call_args[0][0] == "/api/admin/notifications/read-all"


class TestNotificationDelete:
    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_delete_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="delete")
        assert result.success is False
        assert "缺少通知 ID" in result.error
        mock_client.delete.assert_not_called()

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_delete_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delete", notification_id="n1")
        assert result.success is True
        assert mock_client.delete.call_args[0][0] == "/api/admin/notifications/n1"


class TestNotificationCreate:
    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_create_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(context=admin_tool_context, action="create", title="t", content="c")
        assert r1.success is False and "缺少接收人 ID" in r1.error
        r2 = await tool.execute(context=admin_tool_context, action="create", recipient_id="u1", content="c")
        assert r2.success is False and "缺少通知标题" in r2.error
        r3 = await tool.execute(context=admin_tool_context, action="create", recipient_id="u1", title="t")
        assert r3.success is False and "缺少通知内容" in r3.error
        mock_client.post.assert_not_called()

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_create_invalid_channel(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="create", recipient_id="u1", title="t", content="c",
            channel="carrier_pigeon")
        assert result.success is False
        assert "无效的通知渠道" in result.error
        mock_client.post.assert_not_called()

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_create_channel_mapping(self, mock_get_client, tool, admin_tool_context):
        mock_client = _mock_notify_client([{"success": True, "data": {"id": "n-new"}}])
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create", recipient_id="emp_001", title="t", content="c",
            channel="system")
        assert result.success is True
        assert result.data["id"] == "n-new"
        payload = _notify_payloads(mock_client)[0]
        assert payload["channel"] == "internal"

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_create_exception_generic(self, mock_get_client, tool, admin_tool_context):
        """投递阶段抛异常 → 显式失败带错误码，且不把内部异常细节透给用户。"""
        mock_client = _mock_notify_client(RuntimeError("boom"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create", recipient_id="emp_001", title="t", content="c")
        assert result.success is False
        assert result.error == "notification_send_failed"
        assert result.suggestion
        assert "boom" not in (result.message or "")


class TestNotificationCreateRecipientContract:
    """issue #3567（HIGH）：创建通知的 payload 必须满足 admin-api DTO 契约。

    修复前必红：payload 无 `recipientType`（DTO L23-24 `@NotBlank`）→ admin-api 恒 400
    → B 端「创建通知」能力实际不可用（success=False）。
    """

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_payload_carries_required_fields(self, mock_get_client, tool, admin_tool_context):
        """实际发出的 payload 必须含非空 recipientId/recipientType/title/content + 合法 channel。"""
        mock_client = _mock_notify_client([{"success": True, "data": {"id": "n-001"}}])
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create",
            recipient_id="emp_001", title="库存预警", content="A 款窗帘低于安全库存")

        assert result.success is True, f"创建通知不得再因缺字段而失败: {result.error}"
        payloads = _notify_payloads(mock_client)
        assert len(payloads) == 1, f"应恰好一条通知: {mock_client.post.call_args_list}"
        payload = payloads[0]

        # DTO @NotBlank 字段（缺一即恒 400）
        assert isinstance(payload.get("recipientId"), str) and payload["recipientId"].strip()
        assert payload["recipientId"] == "emp_001"
        # recipientType 口径与 NotificationService.triggerForTenantAdmins 一致（L366）
        assert payload["recipientType"] == "employee"
        assert payload["title"].strip() == "库存预警"
        assert payload["content"].strip()
        # channel 合法值只有 wechat/sms/email/internal（DTO L39-41，站内信 = internal）；
        # tool schema 暴露的 "system" 是语义化别名，绝不可原样下发
        assert payload["channel"] in {"wechat", "sms", "email", "internal"}
        assert payload["channel"] == "internal"

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_payload_covers_all_dto_not_blank_fields(self, mock_get_client):
        """契约（防再漏字段）：payload 覆盖 CreateNotificationRequest 全部 @NotBlank 字段。

        issue #3567 的根因是「payload 与 DTO 契约脱节且无人校验」——本用例把 DTO 的
        @NotBlank 字段集当单一事实源，直接解析 Java 源文件比对，漏字段必红。
        """
        from app.tools.notification_manage import _build_notification_payload

        dto_path = (
            Path(__file__).resolve().parents[2]
            / "admin-api" / "src" / "main" / "java" / "com" / "migao" / "admin"
            / "dto" / "CreateNotificationRequest.java"
        )
        assert dto_path.is_file(), f"DTO 源文件不存在（契约测试前提被破坏）: {dto_path}"
        dto_src = dto_path.read_text(encoding="utf-8")
        required = set(re.findall(r"@NotBlank\b[^;]*?\bprivate\s+String\s+(\w+)\s*;", dto_src))
        assert required == {"recipientId", "recipientType", "title", "content"}, (
            f"DTO @NotBlank 字段集与预期不符（DTO 契约已变更，请同步本用例）: {sorted(required)}"
        )

        payload = _build_notification_payload(
            recipient_id="emp_001", title="t", content="c", channel="system",
        )
        missing = required - set(payload)
        assert not missing, f"通知 payload 漏发 DTO 必填字段: {sorted(missing)}"
        blank = [k for k in required if not str(payload[k]).strip()]
        assert not blank, f"通知 payload 的必填字段为空值: {sorted(blank)}"


class TestNotificationCreateRecipientResolution:
    """issue #3567：`POST /api/admin/notifications` 按收件人落库（无广播语义），
    且**不允许兼容性猜测** —— 解析不到收件人时必须显式失败 / 显式带错误码，绝不静默成功。

    分级语义（口径同 human_handoff #3553）：投递/解析失败 → `success=False`；
    租户无人可通知 → `success=True` 但显式带 `error=` + `data.*=false`（绝不静默）。
    """

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_recipient_not_found_is_explicit_failure(self, mock_get_client, tool, admin_tool_context):
        """收件人不是租户内在职 B 端账号 → 显式失败（不得落一条谁也看不到的通知）。"""
        mock_client = _mock_notify_client([{"success": True, "data": {"id": "n-002"}}])
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create",
            recipient_id="not-a-real-user", title="t", content="c")

        assert result.success is False, "解析不到收件人不得报成功（兼容性猜测）"
        assert result.error == "notification_recipient_not_found"
        assert _notify_payloads(mock_client) == [], "收件人未解析成功时不得发出通知请求"
        assert result.suggestion, "必须给出可执行的 suggestion（改用真实收件人 ID）"

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_no_recipient_is_loud_not_silent(self, mock_get_client, tool, admin_tool_context):
        """租户内无在职 B 端账号 → 显式带错误码 + data.*=false，绝不静默成功。"""
        mock_client = _mock_notify_client([], recipients=[])
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create",
            recipient_id="emp_001", title="t", content="c")

        assert result.data.get("notificationSent") is False
        assert result.error == "notification_skipped_no_recipient"
        assert result.suggestion, "无收件人必须给出明确 suggestion（补 B 端账号）"
        assert _notify_payloads(mock_client) == [], "无收件人时不得发出必被 400 拒绝的请求"

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_recipient_resolution_failure_not_reported_as_success(self, mock_get_client, tool, admin_tool_context):
        """收件人解析本身失败（admin-api 不可用）→ 显式失败，不得静默成功。"""
        mock_client = _mock_notify_client([{"success": True, "data": {"id": "n-003"}}])
        mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create",
            recipient_id="emp_001", title="t", content="c")

        assert result.success is False
        assert result.error == "notification_recipient_resolution_failed"
        assert result.suggestion
        assert _notify_payloads(mock_client) == []

    @patch("app.tools.notification_manage.get_admin_api_client")
    async def test_delivery_failure_not_reported_as_success(self, mock_get_client, tool, admin_tool_context):
        """admin-api 拒绝投递 → 不得报成功（修复前漏字段导致恒 400，此处锁定不回归）。"""
        mock_client = _mock_notify_client([
            {"success": False, "error": {"message": "接收人类型不能为空"}},
        ])
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create",
            recipient_id="emp_001", title="t", content="c")

        assert result.success is False
        assert result.error == "notification_send_failed"
        assert result.suggestion
