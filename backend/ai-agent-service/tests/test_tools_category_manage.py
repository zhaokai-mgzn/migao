"""CategoryManageTool 单元测试 — 分类树（只读）

B 端只读化（issue #5247）：category_manage（商品分类） 的写 action 已删除 ⇒ 本次退休写路径用例（产品裁定，非放宽门禁）。
"""
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
    # [RETIRED #5247] test_create_success 已退休：建分类（create）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。

    # [RETIRED #5247] test_create_no_parent_field 已退休：建分类（create）已从 B 端移除（B 端只读化）：parentId 不下发的写断言无对象。

    def test_schema_no_parent_id(self, tool):
        """schema 不得再暴露 parent_id（扁平分类，防 LLM 引导「子分类」错误语义）。"""
        assert "parent_id" not in tool.parameters["properties"]

    def test_description_no_subcategory_semantics(self, tool):
        """description 不得再提「子分类/顶级」（分类已扁平）。"""
        assert "子分类" not in tool.description
        assert "顶级" not in tool.description

    # [RETIRED #5247] test_create_missing_name 已退休：建分类（create）已从 B 端移除（B 端只读化）：入参校验随之消失，断言无对象。


# [RETIRED #5247] TestCategoryDelete（2 例） 已退休：删分类（delete）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。


# [RETIRED #5247] TestCategoryPermission 已退休：建分类（create）已从 B 端移除（B 端只读化）：该权限断言的对象是写 action，写能力已不存在。
