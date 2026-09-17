"""写操作审计落库 — 工具层 → admin-api `/api/admin/agent/audit-logs`（issue #4039）

# case_ids: RG-001

背景（issue #4039 实测）：`registry.py` 的写审计此前**只进 loguru**，`audit_logs` 表当日 0 行
⇒ 多租户 SaaS 的写操作不可追溯（合规/取证缺口）。且真正的生产写路径
（`base_skill.execute_skill → _execute_tool_safe → tool.execute()`）**根本不经过**
`ToolRegistry.execute_tool` ⇒ 连 loguru 那两行也不会打（`[AUDIT]` 全仓仅出现在 registry.py）。
故本文件同时钉住「registry 路径」与「生产接线 `_execute_tool_safe` 路径」。

每条断言在实现前都是**红的**（红证见 PR body：同一命令在改前失败、改后通过）：
1. 写工具执行 → 经 HTTP 落库审计端点（字段映射 tool→action、tenant_id、user_id、session_id）；
2. **PII 纪律不得回退**：参数只以「字段名 → 类型占位」形态出网，真实手机号/地址不出现在请求体；
3. 只读工具**不落库**（R2 负例：不制造噪声行、不误伤查询）；
4. `success=false` 与执行异常路径**同样留痕**；
5. 审计落库失败 **fail-open 但可观测**（业务写不被打断 + 留 `[AUDIT] PERSIST_FAILED` 痕迹）；
6. 生产接线 `_execute_tool_safe` 也落库（否则「机制对、路径不通」= R5 声明无消费）。
"""
import json

import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.tools.registry import ToolRegistry

# 审计端点（admin-api 新增）：工具层不直连 DB，统一走 HTTP（本仓架构契约）
AUDIT_PATH = "/api/admin/agent/audit-logs"
# 审计落库失败的可观测标记（禁静默吞异常）
PERSIST_FAILED_MARK = "[AUDIT] PERSIST_FAILED"


class _WriteTool(BaseTool):
    """写工具替身（read_only=False）：不触真实业务副作用，只验证审计行为。"""

    name = "write_audit_double"
    description = "写审计测试替身"
    read_only = False
    parameters = {
        "type": "object",
        "properties": {
            "phone": {"type": "string", "description": "手机号"},
            "address": {"type": "string", "description": "地址"},
        },
    }

    def __init__(self, success: bool = True, raises: Exception | None = None):
        self._success = success
        self._raises = raises

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        if self._raises is not None:
            raise self._raises
        return ToolResult(success=self._success, data={}, message="done")


class _ReadTool(BaseTool):
    """只读工具替身：用于 R2 负例（不得因审计而多出落库行/多出请求）。"""

    name = "read_audit_double"
    description = "只读测试替身"
    read_only = True
    parameters = {"type": "object", "properties": {"keyword": {"type": "string"}}}

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        return ToolResult(success=True, data={"ok": True}, message="ok")


@pytest.fixture
def registry():
    r = ToolRegistry()
    yield r
    r.clear()


@pytest.fixture
def ctx():
    return ToolContext(tenant_id=7, user_id="u-audit-1", session_id="sess-audit-1", role="admin")


@pytest.fixture
def admin_client():
    """替身 admin-api 客户端；返回的 client 供断言捕获的请求体。"""
    client = AsyncMock()
    client.post = AsyncMock(return_value={"success": True, "data": {"action": "x"}})
    with patch("app.tools.registry.get_admin_api_client", return_value=client):
        yield client


def _payload(client) -> dict:
    """取最后一次审计上报的 JSON body。"""
    return client.post.await_args.kwargs["json_data"]


class TestRegistryWriteAuditPersisted:
    async def test_write_tool_persists_audit_row(self, registry, ctx, admin_client):
        """写工具执行 → 上报 admin-api 审计端点（字段映射 + 身份透传）。"""
        registry.register(_WriteTool())
        result = await registry.execute_tool("write_audit_double", ctx, phone="13800138000")

        assert result.success is True
        assert admin_client.post.await_count == 1
        call = admin_client.post.await_args
        assert call.args[0] == AUDIT_PATH
        assert call.kwargs["tenant_id"] == ctx.tenant_id
        assert call.kwargs["user_id"] == ctx.user_id
        payload = call.kwargs["json_data"]
        # tool → action（issue #4039 字段映射）
        assert payload["action"] == "write_audit_double"
        # 表无 session_id 列 ⇒ 落 action_details（迁移建议见 PR body，不自行加列）
        assert payload["actionDetails"]["sessionId"] == ctx.session_id
        assert payload["actionDetails"]["role"] == "admin"
        assert payload["actionDetails"]["success"] is True
        assert payload["actionDetails"]["durationMs"] >= 0

    async def test_read_only_tool_not_persisted(self, registry, ctx, admin_client):
        """R2 负例：只读工具不落库（审计只覆盖写操作，不制造噪声行）。"""
        registry.register(_ReadTool())
        result = await registry.execute_tool("read_audit_double", ctx, keyword="窗帘")

        assert result.success is True
        assert admin_client.post.await_count == 0

    async def test_pii_values_never_leave_the_process(self, registry, ctx, admin_client):
        """R2 负例（PII）：落库同样只记字段名与类型，真实手机号/地址不得出现在请求体。"""
        registry.register(_WriteTool())
        await registry.execute_tool(
            "write_audit_double", ctx, phone="13800138000", address="杭州西湖区文三路 100 号"
        )

        body = json.dumps(_payload(admin_client), ensure_ascii=False)
        assert "13800138000" not in body
        assert "杭州西湖区" not in body
        assert _payload(admin_client)["actionDetails"]["params"] == {
            "phone": "<str>",
            "address": "<str>",
        }

    async def test_failed_write_result_also_persisted(self, registry, ctx, admin_client):
        """失败留痕：success=false 的写调用同样落库（「尝试过但失败」可追溯）。"""
        registry.register(_WriteTool(success=False))
        result = await registry.execute_tool("write_audit_double", ctx, phone="13800138000")

        assert result.success is False
        assert admin_client.post.await_count == 1
        assert _payload(admin_client)["actionDetails"]["success"] is False

    async def test_raised_write_exception_also_persisted(self, registry, ctx, admin_client):
        """异常留痕：工具抛错的写调用同样落库，且返回泛化错误（不泄露内部细节）。"""
        registry.register(_WriteTool(raises=RuntimeError("secret internal detail")))
        result = await registry.execute_tool("write_audit_double", ctx, phone="13800138000")

        assert result.success is False
        assert result.error == "tool_execution_failed"
        assert admin_client.post.await_count == 1
        assert _payload(admin_client)["actionDetails"]["success"] is False


class TestAuditPersistenceFailureIsObservable:
    async def test_audit_failure_does_not_block_write_and_is_logged(
        self, registry, ctx, admin_client
    ):
        """审计端点不可用 ⇒ 业务写**不被阻断**（fail-open），但必须留可观测痕迹。"""
        admin_client.post = AsyncMock(side_effect=RuntimeError("connection refused"))
        registry.register(_WriteTool())
        with patch("app.tools.registry.logger") as mock_logger:
            result = await registry.execute_tool("write_audit_double", ctx, phone="13800138000")

        assert result.success is True  # 审计不是业务护栏
        warnings = [str(c.args[0]) for c in mock_logger.warning.call_args_list]
        assert any(PERSIST_FAILED_MARK in w for w in warnings), warnings

    async def test_audit_endpoint_business_failure_is_logged(self, registry, ctx, admin_client):
        """端点返回 success=false（如 422/租户上下文缺失）也须留痕，不得当成功吞掉。"""
        admin_client.post = AsyncMock(return_value={"success": False, "error": {"code": "X"}})
        registry.register(_WriteTool())
        with patch("app.tools.registry.logger") as mock_logger:
            result = await registry.execute_tool("write_audit_double", ctx, phone="13800138000")

        assert result.success is True
        warnings = [str(c.args[0]) for c in mock_logger.warning.call_args_list]
        assert any(PERSIST_FAILED_MARK in w for w in warnings), warnings

    async def test_hung_endpoint_is_bounded(self, registry, ctx, admin_client):
        """fail-open 必须**有界**：admin-api 挂住不得把写路径一起拖住（http_client 默认 25s）。"""
        import asyncio

        async def _hang(**_kwargs):
            await asyncio.sleep(30)

        admin_client.post = AsyncMock(side_effect=_hang)
        registry.register(_WriteTool())
        with patch("app.tools.registry._WRITE_AUDIT_TIMEOUT_S", 0.05), \
                patch("app.tools.registry.logger") as mock_logger:
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            result = await registry.execute_tool("write_audit_double", ctx, phone="13800138000")
            elapsed = loop.time() - t0

        assert result.success is True
        assert elapsed < 5, f"审计上报未被上限截断（耗时 {elapsed:.1f}s）"
        warnings = [str(c.args[0]) for c in mock_logger.warning.call_args_list]
        assert any(PERSIST_FAILED_MARK in w for w in warnings), warnings


class TestProductionWiring:
    """生产接线：米宝/小布真实执行入口 `_execute_tool_safe`（base_skill）必须落库。"""

    @staticmethod
    def _clear_cache():
        from app.graph.skills.base_skill import _execute_tool_safe

        if hasattr(_execute_tool_safe, "_cache"):
            _execute_tool_safe._cache = {}

    async def test_execute_tool_safe_persists_write_audit(self, ctx, admin_client):
        from app.graph.skills.base_skill import _execute_tool_safe

        self._clear_cache()
        tool = _WriteTool()
        state = {"session_id": "sess-audit-1", "tenant_id": 7}
        _str, result_dict = await _execute_tool_safe(
            tool, {"phone": "13800138000"}, ctx, state
        )

        assert result_dict["success"] is True
        assert admin_client.post.await_count == 1
        payload = _payload(admin_client)
        assert payload["action"] == "write_audit_double"
        assert payload["actionDetails"]["params"] == {"phone": "<str>"}
        assert admin_client.post.await_args.kwargs["user_id"] == ctx.user_id

    async def test_execute_tool_safe_persists_failure(self, ctx, admin_client):
        from app.graph.skills.base_skill import _execute_tool_safe

        self._clear_cache()
        tool = _WriteTool(raises=RuntimeError("boom"))
        state = {"session_id": "sess-audit-1", "tenant_id": 7}
        _str, result_dict = await _execute_tool_safe(tool, {"phone": "13800138000"}, ctx, state)

        assert result_dict["success"] is False
        assert admin_client.post.await_count == 1
        assert _payload(admin_client)["actionDetails"]["success"] is False

    async def test_execute_tool_safe_read_only_not_persisted(self, ctx, admin_client):
        """R2 负例：生产路径的只读工具同样不落库（不误伤查询、不制造噪声）。"""
        from app.graph.skills.base_skill import _execute_tool_safe

        self._clear_cache()
        tool = _ReadTool()
        state = {"session_id": "sess-audit-1", "tenant_id": 7}
        _str, result_dict = await _execute_tool_safe(tool, {"keyword": "窗帘"}, ctx, state)

        assert result_dict["success"] is True
        assert admin_client.post.await_count == 0