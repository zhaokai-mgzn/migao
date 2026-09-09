"""CategoryManageTool 单元测试 — 分类树/CRUD"""
# case_ids: CT-001, CT-002, CT-003
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
    async def test_create_no_parent_field(self, mock_get_client, tool, admin_tool_context):
        """分类已扁平化（#2905），create 不再透传 parentId——对齐 admin-api 忽略 parentId。"""
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
        # 请求体不得含 parentId（admin-api 已忽略父子概念）
        json_data = mock_client.post.call_args[1]["json_data"]
        assert "parentId" not in json_data

    def test_schema_no_parent_id(self, tool):
        """schema 不得再暴露 parent_id（扁平分类，防 LLM 引导「子分类」错误语义）。"""
        assert "parent_id" not in tool.parameters["properties"]

    def test_description_no_subcategory_semantics(self, tool):
        """description 不得再提「子分类/顶级」（分类已扁平）。"""
        assert "子分类" not in tool.description
        assert "顶级" not in tool.description

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
