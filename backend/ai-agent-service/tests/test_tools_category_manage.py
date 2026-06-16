"""CategoryManageTool 单元测试 — 分类树/CRUD"""
import pytest
from unittest.mock import AsyncMock, patch
from app.tools.category_manage import CategoryManageTool


@pytest.fixture
def tool():
    return CategoryManageTool()


class TestCategoryTree:
    @patch("app.tools.category_manage.get_admin_api_client")
    async def test_get_tree(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": [
                {"id": "cat-1", "name": "窗帘", "children": [
                    {"id": "cat-2", "name": "遮光帘"}
                ]}
            ]
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="tree")

        assert result.success is True
        tree = result.data["tree"]
        assert len(tree) == 1
        assert tree[0]["name"] == "窗帘"

    @patch("app.tools.category_manage.get_admin_api_client")
    async def test_tree_empty(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": []})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="tree")

        assert result.success is True
        assert result.data["tree"] == []


class TestCategoryCreate:
    @patch("app.tools.category_manage.get_admin_api_client")
    async def test_create_success(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {"id": "cat-new", "name": "新分类"}
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="create",
            name="新分类",
        )

        assert result.success is True
        assert result.data["name"] == "新分类"

    @patch("app.tools.category_manage.get_admin_api_client")
    async def test_create_with_parent(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {"id": "cat-child", "name": "子分类", "parentId": "cat-1"}
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="create",
            name="子分类",
            parent_id="cat-1",
        )

        assert result.success is True

    @patch("app.tools.category_manage.get_admin_api_client")
    async def test_create_missing_name(self, mock_get_client, tool, admin_tool_context):
        mock_get_client.return_value = AsyncMock()

        result = await tool.execute(context=admin_tool_context, action="create")

        assert result.success is False


class TestCategoryDelete:
    @patch("app.tools.category_manage.get_admin_api_client")
    async def test_delete_success(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="delete",
            category_id="cat-to-delete",
        )

        assert result.success is True

    @patch("app.tools.category_manage.get_admin_api_client")
    async def test_delete_missing_id(self, mock_get_client, tool, admin_tool_context):
        mock_get_client.return_value = AsyncMock()

        result = await tool.execute(context=admin_tool_context, action="delete")

        assert result.success is False


class TestCategoryPermission:
    @patch("app.tools.category_manage.get_admin_api_client")
    async def test_customer_no_create(self, mock_get_client, tool, sample_tool_context):
        mock_get_client.return_value = AsyncMock()

        result = await tool.execute(
            context=sample_tool_context,
            action="create",
            name="test",
        )

        assert result.success is False
        assert "权限" in result.error
