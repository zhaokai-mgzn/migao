"""NotificationManageTool 单元测试 — 站内通知**查询**（列表 / 未读数）。

B 端只读化（issue #5247 用户裁定 2026-09-23；settings 域整域收口 = issue #5302）：
`notification_manage` 的写 action（`mark_read` / `read_all` / `delete` / `create`）已从工具
删除 ⇒ 本次退休写路径用例（**产品裁定，非放宽门禁**）。
issue #3567 的收件人解析 / payload 契约机具（只服务 `create`）随写 action 一并从实现删除
⇒ 对应断言无对象。写能力下线的判据在 `tests/test_settings_domain_readonly.py`。
"""
# case_ids: ST-004, ST-005
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.notification_manage import NotificationManageTool


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

    async def test_agent_role_denied(self, tool, agent_tool_context):
        """C 端角色 `agent` 不得读站内通知。

        🔴 #5302 改判（理由层，结论不变）：原措辞是「工具现强调权限码（system:manage +
        employee:list）⇒ C 端角色被移除」——那两个码都是**写路径**的码（`POST` 建通知 +
        create 解析收件人的 `GET /api/admin/users`），已随写 action 退场。现在本工具
        **不持码**（两个读端点在 admin-api 里没有权限码）⇒ 角色层是**唯一**门禁，
        `agent` 不在类体 `allowed_roles` 里 ⇒ 仍拒（C 端没有这条能力）。
        """
        result = await tool.execute(context=agent_tool_context, action="list")
        assert result.success is False
        assert "权限" in result.error

    async def test_merchant_employee_role_allowed(self, tool):
        """改前实际放行面必须仍可用（#5302 的**零回归**口径）。

        改前（权限码 `system:manage` + `employee:list`）实际只放行 admin（`*` 通配）
        + operator（唯一持 `employee:list` 的商户岗位）⇒ 角色层按同一集合显式声明。
        红证：把类体 `allowed_roles` 删掉（吃 `BaseTool` 默认值：含 C 端/幽灵角色）或收窄成
        只剩 admin ⇒ 本用例红。
        """
        for role in ("admin", "operator"):
            ctx = ToolContext(tenant_id=1, user_id=f"u_{role}", session_id="s_perf", role=role)
            assert tool.check_permission(ctx) is True, f"{role} 被误拒（读取面被收窄）"

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


# [RETIRED #5302] TestNotificationMarkRead（3 例） 已退休：标记已读 / 全部已读
#   （mark_read / read_all）已从工具删除（B 端只读化；settings 域整域收口）：
#   写能力不再存在，断言无对象（下线判据见 tests/test_settings_domain_readonly.py）。


# [RETIRED #5302] TestNotificationDelete（2 例） 已退休：删除通知（delete）已从工具删除（同上）。


# [RETIRED #5302] TestNotificationCreate（4 例） 已退休：创建/发送通知（create）已从工具删除
#   （同上；issue #3567 的 `_mock_notify_client` / payload 机具随之一并退场）。


# [RETIRED #5302] TestNotificationCreateRecipientContract（2 例） 已退休：创建通知 payload 与
#   `CreateNotificationRequest` DTO 的 @NotBlank 契约（issue #3567）随 create 与
#   `_build_notification_payload` 一并删除 —— 被测机具不存在（契约面并入 admin-api 侧单测）。


# [RETIRED #5302] TestNotificationCreateRecipientResolution（4 例） 已退休：收件人解析的
#   分级语义（recipient_not_found / skipped_no_recipient / resolution_failed / send_failed）
#   随 create 与 `_resolve_tenant_recipients` 一并删除 —— 只读工具里留一套不可达的写机具，
#   下一个人加一行 `VALID_ACTIONS` 就能把能力接回来（这正是 #5302 要拦的形态）。