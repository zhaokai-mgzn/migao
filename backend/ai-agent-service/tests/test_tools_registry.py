"""ToolRegistry 单元测试 — 工具注册/查找/执行审计"""
# case_ids: RG-001
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.tools.registry import (
    ToolRegistry,
    get_tool_registry,
    reset_tool_registry,
)


class _FakeTool(BaseTool):
    """只读假工具，用于注册/查询语义测试"""

    name = "fake_tool"
    description = "fake tool for tests"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "商品名"},
            "price": {"type": "number", "description": "价格", "default": 0.0},
        },
        "required": ["name"],
    }

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        return ToolResult(success=True, data={"ok": True}, message="done")


class _WriteTool(BaseTool):
    """写工具（read_only=False），用于执行审计测试"""

    name = "write_tool"
    description = "write tool"
    read_only = False
    allowed_roles = ["admin"]

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        return ToolResult(success=True, data={}, message="written")


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
        tool = _FakeTool()
        registry.register(tool)
        assert registry.get_tool("fake_tool") is tool

    def test_get_nonexistent(self, registry):
        assert registry.get_tool("nonexistent") is None

    def test_register_duplicate_overwrites(self, registry):
        t1 = _FakeTool()
        t2 = _FakeTool()
        registry.register(t1)
        registry.register(t2)
        assert registry.get_tool("fake_tool") is t2

    def test_unregister(self, registry):
        tool = _FakeTool()
        registry.register(tool)
        assert registry.unregister("fake_tool") is True
        assert registry.get_tool("fake_tool") is None

    def test_unregister_nonexistent(self, registry):
        assert registry.unregister("nonexistent") is False


class TestRegistryQueries:
    def test_get_all(self, registry):
        registry.register(_FakeTool())
        tools = registry.get_all_tools()
        assert len(tools) == 1
        assert tools[0].name == "fake_tool"

    def test_get_tool_names(self, registry):
        registry.register(_FakeTool())
        assert registry.get_tool_names() == ["fake_tool"]

    def test_has_tool(self, registry):
        registry.register(_FakeTool())
        assert registry.has_tool("fake_tool") is True
        assert registry.has_tool("nope") is False

    def test_get_schemas(self, registry):
        registry.register(_FakeTool())
        schemas = registry.get_schemas()
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "fake_tool"

    def test_get_tools_description_empty(self, registry):
        assert registry.get_tools_description() == "暂无可用工具"

    def test_get_tools_description(self, registry):
        registry.register(_FakeTool())
        desc = registry.get_tools_description()
        assert "- fake_tool: fake tool for tests" in desc

    def test_len_and_contains(self, registry):
        assert len(registry) == 0
        registry.register(_FakeTool())
        assert len(registry) == 1
        assert "fake_tool" in registry
        assert "nope" not in registry

    def test_get_langchain_tools(self, registry):
        registry.register(_FakeTool())
        tools = registry.get_langchain_tools()
        assert len(tools) == 1
        assert tools[0].name == "fake_tool"


class TestRegistryBuildArgsSchema:
    def test_build_args_schema(self):
        model = ToolRegistry._build_args_schema(_FakeTool())
        assert model is not None
        fields = model.model_fields
        assert "name" in fields
        assert "price" in fields
        # name 必填，price 可选（有默认值 None）
        assert fields["name"].is_required() is True
        assert fields["price"].is_required() is False

    def test_build_args_schema_empty_props(self):
        class _NoProps(BaseTool):
            name = "no_props"
            description = "no props"

            async def execute(self, context, **kwargs):
                return ToolResult(success=True)

        assert ToolRegistry._build_args_schema(_NoProps()) is None

    def test_create_langchain_tool(self, registry):
        lc = registry._create_langchain_tool(_FakeTool())
        assert lc is not None
        assert lc.name == "fake_tool"


class TestRegistryExecute:
    async def test_execute_tool(self, registry, ctx):
        registry.register(_FakeTool())
        result = await registry.execute_tool("fake_tool", ctx, price=9.9)
        assert result.success is True
        assert result.data == {"ok": True}

    async def test_execute_nonexistent(self, registry, ctx):
        result = await registry.execute_tool("nonexistent", ctx)
        assert result.success is False
        assert "未知" in result.message

    async def test_execute_permission_denied(self, registry):
        registry.register(_WriteTool())
        customer = ToolContext(tenant_id=1, user_id="u1", role="customer")
        result = await registry.execute_tool("write_tool", customer)
        assert result.success is False
        assert result.error == "Permission denied"

    @patch("app.tools.registry.logger")
    async def test_execute_write_audit_desensitized(self, mock_logger, registry, ctx):
        """写操作审计日志：参数脱敏，仅记类型不记值（防 phone/address PII）"""
        registry.register(_WriteTool())
        result = await registry.execute_tool(
            "write_tool", ctx, phone="13800138000", address="杭州西湖区"
        )
        assert result.success is True
        audit_calls = [
            c.args[0] for c in mock_logger.info.call_args_list
            if "[AUDIT] WRITE tool=write_tool" in str(c.args[0])
        ]
        assert audit_calls, "应记录 [AUDIT] WRITE 日志"
        assert "<str>" in audit_calls[0]
        assert "13800138000" not in audit_calls[0]
        assert "杭州西湖区" not in audit_calls[0]

    async def test_execute_exception_generalized(self, registry, ctx):
        class _Boom(BaseTool):
            name = "boom"
            description = "boom"

            async def execute(self, context, **kwargs):
                raise ValueError("secret internal detail")

        registry.register(_Boom())
        result = await registry.execute_tool("boom", ctx)
        assert result.success is False
        assert result.error == "tool_execution_failed"
        assert "secret" not in result.message


class TestRegistryClear:
    def test_clear(self, registry):
        registry.register(_FakeTool())
        registry.clear()
        assert registry.get_tool("fake_tool") is None
        assert len(registry) == 0


class TestRegistrySingleton:
    def test_get_and_reset(self):
        reset_tool_registry()
        r1 = get_tool_registry()
        r2 = get_tool_registry()
        assert r1 is r2
        reset_tool_registry()
        r3 = get_tool_registry()
        assert r3 is not r1

    def test_default_registry_registers_all(self):
        reset_tool_registry()
        reg = get_tool_registry()
        names = reg.get_tool_names()
        # 全量工具注册（含 part2 分组 8 个 + 其它；#3081 quick_reply_manage 已随快捷回复下线移除）
        for expected in (
            "logistics_track", "customer_logistics_track", "settings_manage", "order_manage", "dashboard_stats",
            "order_create", "inventory_manage",
            "product_search", "product_detail", "order_query",
        ):
            assert expected in names, f"{expected} 未注册"
        # #3081: quick_reply_manage 不得再注册
        assert "quick_reply_manage" not in names


class TestToolsFacadeCompleteness:
    """**不变式**：`app.tools` 门面必须导出注册表注册的**每一个** Tool 类（issue #4010 / A12）。

    病根：`app/tools/__init__.py` 的 import 与 `__all__` 是**手写清单**，与
    `create_default_registry()` 的注册清单各写一份 ⇒ 必然漂移（实测 registry 注册 35 个类，
    10 个未 import、14 个不在 `__all__`，含 `OrderCreateTool` —— 下单主链路）。
    漂移形态是**静默**的：`from app.tools import OrderCreateTool` 报 ImportError 才会发现，
    「类还在、只是门面没导出」不会让任何既有测试变红。

    适用域：`create_default_registry()` 注册的类名集合 ⊆ `app.tools.__all__`。
    不适用域：**未注册**的工具类（如 #3917 下线的 `ProcessingOrderGenerateTool`）**不要求**
    出现在门面里 —— 门面 = 可用工具面，不是「目录里所有文件」。
    """

    def test_registry_classes_are_all_exported(self):
        import app.tools as facade

        reset_tool_registry()
        registered = {type(t).__name__ for t in get_tool_registry().get_all_tools()}
        # 上界守卫：解析/注册静默失效时不得退化成「空集 ⇒ 恒真」（空断言）
        assert len(registered) >= 30, f"注册表只解析出 {len(registered)} 个类，判据疑似空转"
        missing = sorted(registered - set(facade.__all__))
        assert not missing, f"这些已注册的 Tool 类没有从 app.tools 门面导出：{missing}"
        # 导出即真的可导入（`__all__` 写了名字但没有 import = 门面谎报）
        for name in sorted(registered):
            assert getattr(facade, name, None) is not None, f"app.tools.{name} 不可访问"

    def test_every_exported_name_exists(self):
        """反向：`__all__` 不得列不存在的名字（`from app.tools import *` 会当场炸）。"""
        import app.tools as facade

        ghosts = sorted(n for n in facade.__all__ if getattr(facade, n, None) is None)
        assert not ghosts, f"app.tools.__all__ 列了不存在的名字：{ghosts}"
