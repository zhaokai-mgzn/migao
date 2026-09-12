"""ProcessingOrderGenerateTool 单元测试 — 加工单生成（issue #3340）"""
# case_ids: PG-001, PG-002, PG-003, PG-004
import pytest
from unittest.mock import AsyncMock, patch
from app.tools.processing_order_generate import ProcessingOrderGenerateTool


@pytest.fixture
def tool():
    return ProcessingOrderGenerateTool()


class TestGenerate:
    @patch("app.tools.processing_order_generate.get_admin_api_client")
    async def test_generate_success(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": [{"orderRef": "order-1", "success": True, "processingOrderNo": "JG-20260912-0001"}],
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, order_ids=["order-1", "ORD-xxx"])

        assert result.success is True
        assert "已生成 1 个加工单" in result.message
        call_args = mock_client.post.call_args
        assert "processing-orders/generate" in call_args[0][0]
        assert call_args.kwargs["json_data"] == {"orderIds": ["order-1", "ORD-xxx"]}

    @patch("app.tools.processing_order_generate.get_admin_api_client")
    async def test_generate_partial_failure(self, mock_get_client, tool, admin_tool_context):
        """部分失败：已存在加工单/无加工项 → 结果列表带失败原因（幂等/条件化联动）"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": [
                {"orderRef": "order-1", "success": True, "processingOrderNo": "JG-1"},
                {"orderRef": "order-2", "success": False, "message": "订单已有加工单 JG-2，请勿重复生成"},
                {"orderRef": "order-3", "success": False, "message": "订单无加工项，无需生成加工单"},
            ],
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, order_ids=["order-1", "order-2", "order-3"])

        assert result.success is True  # 至少一个成功
        assert "1/3" in result.message
        assert "已有加工单" in result.message
        assert "无加工项" in result.message

    async def test_generate_empty_list(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, order_ids=[])
        assert result.success is False
        assert "请提供" in result.message

    async def test_generate_too_many(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, order_ids=[f"o{i}" for i in range(101)])
        assert result.success is False
        assert "100" in result.message

    async def test_permission_denied(self, tool, unauthorized_tool_context):
        result = await tool.execute(context=unauthorized_tool_context, order_ids=["order-1"])
        assert result.success is False
        assert "没有权限" in result.message
