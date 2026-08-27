"""ValidateInputTool 单元测试 — 纯本地校验，无 API 调用"""
# case_ids: PR-005
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.tools.validate_input import ValidateInputTool


@pytest.fixture
def tool():
    return ValidateInputTool()


class TestValidateInputSuccess:
    async def test_product_create_valid(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="create",
            params={"name": "遮光窗帘", "price": 299, "category_id": "cat-test-001"},
        )
        assert result.success is True
        assert result.data["validated"] is True

    async def test_no_rules_skip(self, tool, admin_tool_context):
        """未知工具/操作返回失败（防止绕过校验）"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="unknown_tool",
            target_action="unknown_action",
            params={"foo": "bar"},
        )
        assert result.success is False
        assert "未知" in result.message or "无法" in result.message

    async def test_update_has_product_id(self, tool, admin_tool_context):
        """update 带 product_id 通过校验"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="update",
            params={"product_id": "prod-001", "name": "新名称"},
        )
        assert result.success is True

    async def test_inventory_adjust_valid(self, tool, admin_tool_context):
        """生产回归：inventory_manage/adjust 必须有校验规则（旧实现返回"未知的工具"，
        且 LLM 绕过校验直接执行写操作）"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="inventory_manage",
            target_action="adjust",
            params={"product_id": "prod-001", "adjustment": 30, "reason": "盘点"},
        )
        assert result.success is True
        assert result.data["validated"] is True

    async def test_inventory_adjust_missing_reason(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="inventory_manage",
            target_action="adjust",
            params={"product_id": "prod-001", "adjustment": 30},
        )
        assert result.success is False
