"""
加工项价格查询 Tool 单元测试

测试 ProcessingItemsTool.execute() 的各种场景
"""

import pytest
from unittest.mock import patch, AsyncMock

from app.tools.processing_items import ProcessingItemsTool
from app.tools.base import ToolContext, ToolResult


@pytest.fixture
def tool():
    return ProcessingItemsTool()


@pytest.fixture
def sample_processing_items_response():
    """模拟 admin-api 返回的加工项数据"""
    return {
        "success": True,
        "data": {
            "items": [
                {
                    "id": "pi_001",
                    "name": "打孔",
                    "category": "基础加工",
                    "unit": "个",
                    "defaultPrice": 5.0,
                    "customPrice": 3.5,
                    "finalPrice": 3.5,
                },
                {
                    "id": "pi_002",
                    "name": "缝纫褶皱",
                    "category": "高级加工",
                    "unit": "米",
                    "defaultPrice": 15.0,
                    "customPrice": None,
                    "finalPrice": 15.0,
                },
                {
                    "id": "pi_003",
                    "name": "包边",
                    "category": "基础加工",
                    "unit": "米",
                    "defaultPrice": 8.0,
                    "customPrice": 6.0,
                    "finalPrice": 6.0,
                },
            ],
        },
    }


class TestProcessingItemsSuccess:
    """加工项查询 - 成功场景"""

    @patch("app.tools.processing_items.get_admin_api_client")
    async def test_query_processing_items_by_product_id(
        self, mock_get_client, tool, sample_tool_context, sample_processing_items_response
    ):
        """通过商品ID查询加工项"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=sample_processing_items_response)
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_id="prod_001",
        )

        assert result.success is True
        assert result.data["item_count"] == 3
        assert len(result.data["items"]) == 3

        # 验证第一个加工项
        item1 = result.data["items"][0]
        assert item1["name"] == "打孔"
        assert item1["default_price"] == 5.0
        assert item1["custom_price"] == 3.5
        assert item1["final_price"] == 3.5
        assert item1["has_custom_price"] is True

        # 验证第二个加工项（无自定义价格）
        item2 = result.data["items"][1]
        assert item2["name"] == "缝纫褶皱"
        assert item2["custom_price"] is None
        assert item2["final_price"] == 15.0
        assert item2["has_custom_price"] is False

    @patch("app.tools.processing_items.get_admin_api_client")
    async def test_query_processing_items_by_name(
        self, mock_get_client, tool, sample_tool_context, sample_processing_items_response
    ):
        """通过商品名称搜索后查询加工项"""
        mock_client = AsyncMock()
        search_response = {
            "success": True,
            "data": {"items": [{"id": "prod_001", "name": "雪尼尔窗帘"}]},
        }
        mock_client.get = AsyncMock(side_effect=[search_response, sample_processing_items_response])
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_name="雪尼尔",
        )

        assert result.success is True
        assert result.data["item_count"] == 3
        assert mock_client.get.call_count == 2

    @patch("app.tools.processing_items.get_admin_api_client")
    async def test_query_processing_items_empty(
        self, mock_get_client, tool, sample_tool_context
    ):
        """商品没有加工项"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": []},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_id="prod_002",
        )

        assert result.success is True
        assert result.data["item_count"] == 0
        assert "暂无" in result.message


class TestProcessingItemsValidation:
    """加工项查询 - 参数验证"""

    async def test_missing_both_params(self, tool, sample_tool_context):
        """product_id 和 product_name 都没提供"""
        result = await tool.execute(context=sample_tool_context)

        assert result.success is False
        assert "缺少参数" in result.error

    @patch("app.tools.processing_items.get_admin_api_client")
    async def test_product_name_not_found(
        self, mock_get_client, tool, sample_tool_context
    ):
        """通过名称搜索但未找到商品"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [], "total": 0},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_name="不存在的商品",
        )

        assert result.success is False
        assert "未找到" in result.message


class TestProcessingItemsError:
    """加工项查询 - 异常处理"""

    @patch("app.tools.processing_items.get_admin_api_client")
    async def test_api_error_response(
        self, mock_get_client, tool, sample_tool_context
    ):
        """admin-api 返回错误"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False,
            "error": {"message": "商品不存在"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_id="invalid_id",
        )

        assert result.success is False
        assert "失败" in result.message

    @patch("app.tools.processing_items.get_admin_api_client")
    async def test_network_exception(
        self, mock_get_client, tool, sample_tool_context
    ):
        """网络异常"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Timeout"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            product_id="prod_001",
        )

        assert result.success is False
        assert "出错" in result.message


class TestProcessingItemsPermission:
    """加工项查询 - 权限检查"""

    async def test_permission_denied(self, tool, unauthorized_tool_context):
        """无权限角色被拒绝"""
        result = await tool.execute(
            context=unauthorized_tool_context,
            product_id="prod_001",
        )

        assert result.success is False
        assert "权限" in result.message


class TestProcessingItemsFormat:
    """加工项查询 - 格式化逻辑"""

    def test_format_list_input(self, tool):
        """处理直接是列表的输入"""
        data = [
            {
                "id": "pi_001",
                "name": "打孔",
                "defaultPrice": 5.0,
                "customPrice": 3.0,
                "finalPrice": 3.0,
            },
        ]
        formatted = tool._format_processing_items(data)

        assert formatted["item_count"] == 1
        assert formatted["items"][0]["final_price"] == 3.0
        assert formatted["items"][0]["has_custom_price"] is True

    def test_format_fallback_final_price(self, tool):
        """final_price缺失时的fallback逻辑"""
        data = [
            {
                "id": "pi_001",
                "name": "打孔",
                "defaultPrice": 5.0,
                "customPrice": None,
                # 没有finalPrice
            },
        ]
        formatted = tool._format_processing_items(data)

        # 没有customPrice也没有finalPrice，应该回退到defaultPrice
        assert formatted["items"][0]["final_price"] == 5.0

    def test_format_custom_price_takes_precedence(self, tool):
        """customPrice优先于defaultPrice作为finalPrice"""
        data = [
            {
                "id": "pi_001",
                "name": "打孔",
                "defaultPrice": 5.0,
                "customPrice": 3.0,
                # 没有finalPrice
            },
        ]
        formatted = tool._format_processing_items(data)

        assert formatted["items"][0]["final_price"] == 3.0
