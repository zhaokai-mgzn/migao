"""
测试 app.tools.human_handoff — 转人工工具

业务真值 #3: 客户说转人工→自动创建工单并通知管理员
"""
import pytest
from unittest.mock import patch, AsyncMock


class TestHumanHandoffPermission:
    """权限校验 — 只有customer角色可以使用"""

    async def test_customer_role_allowed(self, sample_tool_context):
        """customer角色可以调用转人工"""
        from app.tools.human_handoff import HumanHandoffTool
        tool = HumanHandoffTool()
        assert tool.check_permission(sample_tool_context) is True

    async def test_admin_role_denied(self, admin_tool_context):
        """admin角色不应使用转人工（只给C端用户）"""
        from app.tools.human_handoff import HumanHandoffTool
        tool = HumanHandoffTool()
        assert tool.check_permission(admin_tool_context) is False

    async def test_guest_role_denied(self, unauthorized_tool_context):
        """guest角色不能使用转人工"""
        from app.tools.human_handoff import HumanHandoffTool
        tool = HumanHandoffTool()
        assert tool.check_permission(unauthorized_tool_context) is False


class TestHumanHandoffSuccess:
    """成功创建转人工工单"""

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_xiaobu_handoff_creates_ticket(self, mock_get_client, sample_tool_context):
        """客户说转人工→自动创建投诉工单+通知管理员"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        # #518: 现在有2次 post 调用 — ① 创建工单 ② 通知管理员
        mock_client.post = AsyncMock(side_effect=[
            # 第1次: 创建工单
            {
                "success": True,
                "data": {
                    "id": "ticket-handoff-001",
                    "ticketNo": "AS-2024-H001",
                    "ticketType": "complaint",
                    "status": "pending",
                    "reason": "客户请求转人工",
                    "source": "customer",
                },
            },
            # 第2次: 通知管理员
            {"success": True, "data": {"id": "notif-001"}},
        ])
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        result = await tool.execute(
            context=sample_tool_context,
            reason="我要投诉产品质量问题",
            description="窗帘收到后有色差，要求退货",
        )

        assert result.success is True
        assert "ticket-handoff-001" in str(result.data)

        # 验证至少调用了2次 post（创建工单+通知管理员）
        assert mock_client.post.call_count >= 2, (
            f"应至少调用2次post: {mock_client.post.call_count}"
        )

        # 验证第1次调用创建的是投诉工单
        first_call = mock_client.post.call_args_list[0]
        json_data = first_call[1]["json_data"]
        assert json_data["ticketType"] == "complaint"

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_handoff_default_reason_when_empty(self, mock_get_client, sample_tool_context):
        """reason为空时使用默认值"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        # #518: 2次 post — ① 创建工单 ② 通知管理员
        mock_client.post = AsyncMock(side_effect=[
            {"success": True, "data": {"id": "ticket-h-002", "ticketType": "complaint"}},
            {"success": True, "data": {"id": "notif-002"}},
        ])
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        result = await tool.execute(
            context=sample_tool_context,
        )

        assert result.success is True
        first_call = mock_client.post.call_args_list[0]
        json_data = first_call[1]["json_data"]
        assert "转人工" in json_data["reason"]


class TestHumanHandoffFailure:
    """转人工失败处理"""

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_handoff_returns_suggestion_on_error(self, mock_get_client, sample_tool_context):
        """失败时返回suggestion字段引导用户"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": False,
            "error": {"message": "创建工单失败"},
        })
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        result = await tool.execute(
            context=sample_tool_context,
            reason="需要人工帮助",
        )

        assert result.success is False
        assert result.suggestion is not None
        assert len(result.suggestion) > 0

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_handoff_network_error_graceful(self, mock_get_client, sample_tool_context):
        """网络异常时优雅降级"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        result = await tool.execute(
            context=sample_tool_context,
            reason="请帮我转人工",
        )

        assert result.success is False
        assert result.suggestion is not None


# ============================================================
# GAP-3: 转人工 → 必须通知管理员
# 业务真值: 转人工创建工单后通知管理员（推送/钉钉/系统消息任一种）
# 当前状态: FAIL — 只创建工单，未通知管理员
# ============================================================

class TestHumanHandoffAdminNotification:
    """Gap-3: 转人工后必须通知管理员"""

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_handoff_notifies_admin_after_ticket_creation(self, mock_get_client, sample_tool_context):
        """转人工创建工单后 → 必须调用通知管理员"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        # 创建工单成功
        mock_client.post = AsyncMock(side_effect=[
            # 第一个 post: 创建售后工单
            {"success": True, "data": {"id": "ticket-h-001", "ticketNo": "AS-H-001", "ticketType": "complaint"}},
            # 第二个 post: 通知管理员（如果使用 notification 接口）
            {"success": True, "data": {"id": "notif-001"}},
        ])
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        result = await tool.execute(
            context=sample_tool_context,
            reason="产品质量问题",
            description="窗帘收到后有色差",
        )

        assert result.success is True, f"工单创建应成功: {result.error}"

        # 验证至少调用了两次（创建工单 + 通知管理员）
        assert mock_client.post.call_count >= 2, (
            f"应至少调用2次: 创建工单 + 通知管理员，实际调用{len(mock_client.post.call_args_list)}次"
        )

        # 验证第二次调用是通知内容
        # 检查至少有一个post调用包含通知内容
        found_notification = False
        for call_args in mock_client.post.call_args_list:
            json_data = call_args[1].get("json_data", {})
            # 通知调用：检查是否包含 recipient_role 或 channel 或 title 等通知字段
            if "notification" in str(call_args[0][0]).lower() or json_data.get("recipientRole") or json_data.get("channel"):
                found_notification = True
                break
        assert found_notification, (
            f"必须包含通知管理员调用: {mock_client.post.call_args_list}"
        )

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_handoff_succeeds_even_if_notification_fails(self, mock_get_client, sample_tool_context):
        """通知管理员失败不影响转人工成功（工单已创建）"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[
            # 工单创建成功
            {"success": True, "data": {"id": "ticket-h-002", "ticketNo": "AS-H-002"}},
            # 通知失败（如管理员不存在）
            Exception("Notification service unavailable"),
        ])
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        result = await tool.execute(
            context=sample_tool_context,
            reason="需要人工帮助",
        )

        # 工单创建成功了，转人工应该算成功
        assert result.success is True, (
            f"工单已创建，通知失败不应影响转人工结果: error={result.error}"
        )
