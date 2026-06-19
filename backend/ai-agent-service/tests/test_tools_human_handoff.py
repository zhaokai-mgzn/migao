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
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "ticket-handoff-001",
                "ticketNo": "AS-2024-H001",
                "ticketType": "complaint",
                "status": "pending",
                "reason": "客户请求转人工",
                "source": "customer",
            },
        })
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        result = await tool.execute(
            context=sample_tool_context,
            reason="我要投诉产品质量问题",
            description="窗帘收到后有色差，要求退货",
        )

        assert result.success is True
        assert "ticket-handoff-001" in str(result.data)
        mock_client.post.assert_called_once()

        # 验证创建的是投诉工单
        call_args = mock_client.post.call_args
        json_data = call_args[1]["json_data"]
        assert json_data["ticketType"] == "complaint"

    @patch("app.tools.human_handoff.get_admin_api_client")
    async def test_handoff_default_reason_when_empty(self, mock_get_client, sample_tool_context):
        """reason为空时使用默认值"""
        from app.tools.human_handoff import HumanHandoffTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {"id": "ticket-h-002", "ticketType": "complaint"},
        })
        mock_get_client.return_value = mock_client

        tool = HumanHandoffTool()
        result = await tool.execute(
            context=sample_tool_context,
        )

        assert result.success is True
        call_args = mock_client.post.call_args
        json_data = call_args[1]["json_data"]
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
