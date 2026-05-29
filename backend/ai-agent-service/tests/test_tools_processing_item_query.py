"""
加工项查询 Tool 单元测试

覆盖 ProcessingItemQueryTool.execute() 的列表查询、关键词搜索、详情查询、错误处理。
"""

import pytest
from unittest.mock import patch, AsyncMock

from app.tools.processing_item_query import ProcessingItemQueryTool
from app.tools.base import ToolContext


@pytest.fixture
def tool():
    return ProcessingItemQueryTool()


@pytest.fixture
def sample_processing_items():
    """模拟 admin-api 返回的加工项列表"""
    return [
        {
            "id": "pi_001",
            "name": "打孔",
            "categoryId": "cat_punch",
            "categoryName": "穿挂",
            "pricingMethod": "per_unit",
            "unitPrice": 2.0,
            "unit": "个",
            "minQuantity": 0,
            "maxQuantity": 200,
            "description": "金属圈打孔",
            "options": [],
            "processingDays": 1,
            "aiRecommended": True,
            "status": "active",
        },
        {
            "id": "pi_002",
            "name": "窗帘头",
            "categoryId": "cat_head",
            "categoryName": "造型",
            "pricingMethod": "per_meter",
            "unitPrice": 5.0,
            "unit": "米",
            "minQuantity": 1,
            "maxQuantity": 50,
            "description": "美式窗帘头",
            "options": [],
            "processingDays": 2,
            "aiRecommended": False,
            "status": "active",
        },
    ]


class TestProcessingItemList:
    """加工项列表查询场景"""

    @patch("app.tools.processing_item_query.get_admin_api_client")
    async def test_list_success(
        self, mock_get_client, tool, sample_tool_context, sample_processing_items
    ):
        """默认列表查询返回所有加工项"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": sample_processing_items, "total": 2},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=sample_tool_context)

        assert result.success is True
        assert result.data["total"] == 2
        assert len(result.data["items"]) == 2
        assert result.data["items"][0]["name"] == "打孔"
        # 验证字段映射 camelCase -> snake_case
        assert result.data["items"][0]["unit_price"] == 2.0
        assert result.data["items"][0]["category_name"] == "穿挂"
        assert result.data["items"][0]["pricing_method"] == "per_unit"
        assert result.data["page"] == 1
        assert result.data["size"] == 10

        # 验证调用参数
        call_args = mock_client.get.call_args
        assert call_args[0][0] == "/api/admin/processing-items"
        assert call_args[1]["params"] == {"page": 1, "size": 10}

    @patch("app.tools.processing_item_query.get_admin_api_client")
    async def test_list_with_keyword(
        self, mock_get_client, tool, sample_tool_context, sample_processing_items
    ):
        """关键词搜索"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [sample_processing_items[0]], "total": 1},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context, keyword="打孔", page=1, size=20
        )

        assert result.success is True
        assert result.data["total"] == 1
        params = mock_client.get.call_args[1]["params"]
        assert params["keyword"] == "打孔"
        assert params["page"] == 1
        assert params["size"] == 20

    @patch("app.tools.processing_item_query.get_admin_api_client")
    async def test_list_with_filters(
        self, mock_get_client, tool, sample_tool_context, sample_processing_items
    ):
        """带分类与状态过滤"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": sample_processing_items, "total": 2},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            category_id="cat_punch",
            status="active",
        )

        assert result.success is True
        params = mock_client.get.call_args[1]["params"]
        assert params["categoryId"] == "cat_punch"
        assert params["status"] == "active"

    @patch("app.tools.processing_item_query.get_admin_api_client")
    async def test_list_empty_result(
        self, mock_get_client, tool, sample_tool_context
    ):
        """无匹配结果时给出友好提示"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [], "total": 0},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=sample_tool_context, keyword="不存在")

        assert result.success is True
        assert result.data["items"] == []
        assert result.data["total"] == 0
        assert "不存在" in (result.message or "")

    @patch("app.tools.processing_item_query.get_admin_api_client")
    async def test_list_string_pagination_params(
        self, mock_get_client, tool, sample_tool_context, sample_processing_items
    ):
        """LLM 可能传字符串分页参数，应自动转换为 int"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": sample_processing_items, "total": 2},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context, page="1", size="10"  # type: ignore[arg-type]
        )

        assert result.success is True
        params = mock_client.get.call_args[1]["params"]
        assert params["page"] == 1
        assert params["size"] == 10


class TestProcessingItemDetail:
    """加工项详情查询场景"""

    @patch("app.tools.processing_item_query.get_admin_api_client")
    async def test_detail_success(
        self, mock_get_client, tool, sample_tool_context, sample_processing_items
    ):
        """按 ID 查询详情"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": sample_processing_items[0],
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=sample_tool_context, id="pi_001")

        assert result.success is True
        assert result.data["item"]["id"] == "pi_001"
        assert result.data["item"]["name"] == "打孔"
        assert mock_client.get.call_args[0][0] == "/api/admin/processing-items/pi_001"


class TestProcessingItemErrors:
    """错误场景"""

    @patch("app.tools.processing_item_query.get_admin_api_client")
    async def test_admin_api_error(self, mock_get_client, tool, sample_tool_context):
        """admin-api 返回失败"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False,
            "error": {"message": "internal error"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=sample_tool_context)

        assert result.success is False
        assert "internal error" in (result.message or "")

    @patch("app.tools.processing_item_query.get_admin_api_client")
    async def test_exception_handling(
        self, mock_get_client, tool, sample_tool_context
    ):
        """HTTP client 抛异常时返回友好错误"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("network down"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=sample_tool_context)

        assert result.success is False
        assert "稍后重试" in (result.message or "")

    async def test_permission_denied(self, tool):
        """非允许角色被拒绝"""
        ctx = ToolContext(
            tenant_id=1, user_id="u1", session_id="s1", role="anonymous"
        )
        result = await tool.execute(context=ctx)
        assert result.success is False
        assert "权限" in (result.message or "")
