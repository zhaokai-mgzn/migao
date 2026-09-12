"""ProcessingOrderQueryTool 单元测试 — 加工单查询（issue #3340）"""
# case_ids: PG-011
import pytest
from unittest.mock import AsyncMock, patch
from app.tools.processing_order_query import ProcessingOrderQueryTool


@pytest.fixture
def tool():
    return ProcessingOrderQueryTool()


class TestQuery:
    @patch("app.tools.processing_order_query.get_admin_api_client")
    async def test_query_list(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": [
                {"id": "po-1", "processingOrderNo": "JG-20260912-0001", "orderNo": "ORD-1",
                 "customerName": "张三", "processor": "朝阳加工厂",
                 "expectedDeliveryDate": "2026-09-20", "status": "issued", "printCount": 0},
                {"id": "po-2", "processingOrderNo": "JG-20260912-0002", "orderNo": "ORD-2",
                 "customerName": "李四", "processor": None,
                 "expectedDeliveryDate": None, "status": "generated", "printCount": 0},
            ],
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, keyword="JG-20260912", status="issued")

        assert result.success is True
        assert "2 个加工单" in result.message
        call_args = mock_client.get.call_args
        assert "processing-orders" in call_args[0][0]
        params = call_args.kwargs.get("params", {})
        assert params.get("keyword") == "JG-20260912"
        assert params.get("status") == "issued"
        # 状态中文映射
        rows = result.data["list"]
        assert rows[0]["statusText"] == "已发加工"
        assert rows[1]["statusText"] == "已生成"

    @patch("app.tools.processing_order_query.get_admin_api_client")
    async def test_query_empty(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": []})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, keyword="JG-不存在")

        assert result.success is True
        assert "未找到加工单" in result.message

    async def test_permission_denied(self, tool, unauthorized_tool_context):
        result = await tool.execute(context=unauthorized_tool_context)
        assert result.success is False
        assert "没有权限" in result.message
