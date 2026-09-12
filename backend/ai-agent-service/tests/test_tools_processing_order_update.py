"""ProcessingOrderUpdateTool 单元测试 — 加工单状态更新（issue #3340）"""
# case_ids: PG-005, PG-006, PG-007, PG-008
import pytest
from unittest.mock import AsyncMock, patch
from app.tools.processing_order_update import ProcessingOrderUpdateTool


@pytest.fixture
def tool():
    return ProcessingOrderUpdateTool()


class TestUpdate:
    @patch("app.tools.processing_order_update.get_admin_api_client")
    async def test_issue(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={
            "success": True,
            "data": {"processingOrderNo": "JG-20260912-0001", "status": "issued"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, id="JG-20260912-0001", action="issue",
            processor="朝阳加工厂", expected_delivery_date="2026-09-20")

        assert result.success is True
        assert "已发加工" in result.message
        call_args = mock_client.patch.call_args
        assert "processing-orders/JG-20260912-0001" in call_args[0][0]
        json_data = call_args.kwargs["json_data"]
        assert json_data["action"] == "issue"
        assert json_data["processor"] == "朝阳加工厂"
        assert json_data["expectedDeliveryDate"] == "2026-09-20"

    @patch("app.tools.processing_order_update.get_admin_api_client")
    async def test_complete(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={
            "success": True,
            "data": {"processingOrderNo": "JG-1", "status": "completed"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, id="JG-1", action="complete")

        assert result.success is True
        assert "加工完成" in result.message

    @patch("app.tools.processing_order_update.get_admin_api_client")
    async def test_cancel_with_reason(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.patch = AsyncMock(return_value={
            "success": True,
            "data": {"processingOrderNo": "JG-1", "status": "cancelled"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, id="JG-1", action="cancel", reason="加工方排期冲突")

        assert result.success is True
        json_data = mock_client.patch.call_args.kwargs["json_data"]
        assert json_data["reason"] == "加工方排期冲突"

    async def test_cancel_without_reason(self, tool, admin_tool_context):
        """cancel 必填原因（人工确认语义，PG-008）"""
        result = await tool.execute(context=admin_tool_context, id="JG-1", action="cancel")
        assert result.success is False
        assert "必须填写原因" in result.message

    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, id="JG-1", action="delete")
        assert result.success is False
        assert "不支持的操作" in result.message

    async def test_permission_denied(self, tool, unauthorized_tool_context):
        result = await tool.execute(context=unauthorized_tool_context, id="JG-1", action="start")
        assert result.success is False
        assert "没有权限" in result.message
