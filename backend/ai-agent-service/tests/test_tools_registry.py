"""ToolRegistry 单元测试 — 工具注册/查找/执行"""
import pytest
from unittest.mock import AsyncMock, patch
from app.tools.base import ToolContext, ToolResult
from app.tools.registry import ToolRegistry


@pytest.fixture
def registry():
    r = ToolRegistry()
    yield r
    r.clear()


@pytest.fixture
def ctx():
    return ToolContext(tenant_id=1, user_id="u1", role="admin")


class TestRegistryRegister:
    def test_register_tool(self, registry):
        from app.tools.validate_input import ValidateInputTool
        tool = ValidateInputTool()
        registry.register(tool)
        assert registry.get_tool("validate_input") is tool

    def test_get_nonexistent(self, registry):
        assert registry.get_tool("nonexistent") is None

    def test_register_duplicate_overwrites(self, registry):
        from app.tools.validate_input import ValidateInputTool
        t1 = ValidateInputTool()
        t2 = ValidateInputTool()
        registry.register(t1)
        registry.register(t2)
        assert registry.get_tool("validate_input") is t2

    def test_unregister(self, registry):
        from app.tools.validate_input import ValidateInputTool
        tool = ValidateInputTool()
        registry.register(tool)
        registry.unregister("validate_input")
        assert registry.get_tool("validate_input") is None


class TestRegistryGetAll:
    def test_get_all(self, registry):
        from app.tools.validate_input import ValidateInputTool
        from app.tools.interact import InteractTool
        registry.register(ValidateInputTool())
        registry.register(InteractTool())
        tools = registry.get_all_tools()
        assert len(tools) >= 2
        names = {t.name for t in tools}
        assert "validate_input" in names
        assert "interact" in names  # InteractTool 已重新启用（对抗性审查修复）


class TestRegistryExecute:
    async def test_execute_tool(self, registry, ctx):
        from app.tools.validate_input import ValidateInputTool
        registry.register(ValidateInputTool())
        result = await registry.execute_tool(
            "validate_input", ctx,
            target_tool="product_manage", target_action="create",
            params={"name": "test", "price": 1, "category_id": "cat-test"})
        assert result.success is True

    async def test_execute_nonexistent(self, registry, ctx):
        result = await registry.execute_tool("nonexistent", ctx)
        assert result.success is False
        assert "未知" in result.message


class TestRegistryClear:
    def test_clear(self, registry):
        from app.tools.validate_input import ValidateInputTool
        registry.register(ValidateInputTool())
        registry.clear()
        assert registry.get_tool("validate_input") is None
