"""写操作审计落库 — 工具层 → admin-api `/api/admin/agent/audit-logs`（issue #4039）

# case_ids: RG-001

背景（issue #4039 实测）：`registry.py` 的写审计此前**只进 loguru**，`audit_logs` 表当日 0 行
⇒ 多租户 SaaS 的写操作不可追溯（合规/取证缺口）。且真正的生产写路径
（`base_skill.execute_skill → _execute_tool_safe → tool.execute()`）**根本不经过**
`ToolRegistry.execute_tool` ⇒ 连 loguru 那两行也不会打（`[AUDIT]` 全仓仅出现在 registry.py）。
故本文件同时钉住「registry 路径」与「生产接线 `_execute_tool_safe` 路径」。

字段语义由 issue #4071 裁定 ① 收敛：`action` = **动词**，工具名 → `toolName`（迁移 V52）。
本文件的第一条断言即该收敛的判据（把 `action` 改回工具名 ⇒ 红）；
动作**派生**本身（映射表 / 参数优先 / 漏登记）由
`tests/test_write_audit_action_semantics.py` 在 L0 层独立锁定。

每条断言在实现前都是**红的**（红证见 PR body：同一命令在改前失败、改后通过）：
1. 写工具执行 → 经 HTTP 落库审计端点（字段映射 action=动词 / toolName=工具名、tenant_id、
   user_id、session_id）；
2. **PII 纪律不得回退**：参数只以「字段名 → 类型占位」形态出网，真实手机号/地址不出现在请求体；
3. 只读工具**不落库**（R2 负例：不制造噪声行、不误伤查询）；
4. `success=false` 与执行异常路径**同样留痕**；
5. 审计落库失败 **有界 fail-open 但可观测**（业务写不被打断 + 留
   `[AUDIT] PERSIST_FAILED … suggestion=` 痕迹，issue #4071 裁定 ②）；
6. 生产接线 `_execute_tool_safe` 也落库（否则「机制对、路径不通」= R5 声明无消费）。
"""
import json

import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.tools import registry as registry_module
from app.tools.registry import ToolRegistry

# 审计端点（admin-api 新增）：工具层不直连 DB，统一走 HTTP（本仓架构契约）
AUDIT_PATH = "/api/admin/agent/audit-logs"
# 审计落库失败的可观测标记（禁静默吞异常）
PERSIST_FAILED_MARK = "[AUDIT] PERSIST_FAILED"
# 留痕里必须带的**行动指引**（issue #4071 裁定 ②：有界 fail-open 的可判定判据）
SUGGESTION_MARK = "suggestion="


class _WriteTool(BaseTool):
    """写工具替身（read_only=False）：不触真实业务副作用，只验证审计行为。

    `action` 参数存在 ⇒ 动作取自**调用参数**（issue #4071 裁定 ① 的第一档，
    与真实工具 `order_manage`/`product_manage` 同形）。测试替身**故意不进**
    `_NO_ACTION_PARAM_TOOL_ACTION` 映射表 —— 该表只登记真实工具。
    """

    name = "write_audit_double"
    description = "写审计测试替身"
    read_only = False
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "操作类型，如 update_status"},
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
        """写工具执行 → 上报 admin-api 审计端点（字段映射 + 身份透传）。

        ⚠️ **本断言即 issue #4071 裁定 ① 的判据**：`action` 必须是**动词**（取自工具调用的
        `action` 参数），工具名必须在 `toolName`。把 `action` 改回工具名 ⇒ 本断言红。
        """
        registry.register(_WriteTool())
        result = await registry.execute_tool(
            "write_audit_double", ctx, action="update_status", phone="13800138000"
        )

        assert result.success is True
        assert admin_client.post.await_count == 1
        call = admin_client.post.await_args
        assert call.args[0] == AUDIT_PATH
        assert call.kwargs["tenant_id"] == ctx.tenant_id
        assert call.kwargs["user_id"] == ctx.user_id
        payload = call.kwargs["json_data"]
        # action = **动词**（工具调用的 action 参数），不是工具名（issue #4071 裁定 ①）
        assert payload["action"] == "update_status"
        # 工具名另置 toolName（迁移 V52 的 tool_name 列）
        assert payload["toolName"] == "write_audit_double"
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
            "write_audit_double", ctx, action="update_status",
            phone="13800138000", address="杭州西湖区文三路 100 号"
        )

        body = json.dumps(_payload(admin_client), ensure_ascii=False)
        assert "13800138000" not in body
        assert "杭州西湖区" not in body
        assert _payload(admin_client)["actionDetails"]["params"] == {
            "action": "<str>",
            "phone": "<str>",
            "address": "<str>",
        }

    async def test_failed_write_result_also_persisted(self, registry, ctx, admin_client):
        """失败留痕：success=false 的写调用同样落库（「尝试过但失败」可追溯）。"""
        registry.register(_WriteTool(success=False))
        result = await registry.execute_tool(
            "write_audit_double", ctx, action="update_status", phone="13800138000"
        )

        assert result.success is False
        assert admin_client.post.await_count == 1
        assert _payload(admin_client)["actionDetails"]["success"] is False

    async def test_raised_write_exception_also_persisted(self, registry, ctx, admin_client):
        """异常留痕：工具抛错的写调用同样落库，且返回泛化错误（不泄露内部细节）。"""
        registry.register(_WriteTool(raises=RuntimeError("secret internal detail")))
        result = await registry.execute_tool(
            "write_audit_double", ctx, action="update_status", phone="13800138000"
        )

        assert result.success is False
        assert result.error == "tool_execution_failed"
        assert admin_client.post.await_count == 1
        assert _payload(admin_client)["actionDetails"]["success"] is False


class TestAuditPersistenceFailureIsObservable:
    async def test_audit_failure_does_not_block_write_and_is_logged(
        self, registry, ctx, admin_client
    ):
        """审计端点不可用 ⇒ 业务写**不被阻断**（fail-open，issue #4071 裁定 ②），但必须留
        可观测痕迹 —— 且痕迹里**必须带 `suggestion=`**（有界 fail-open 的可行动部分：
        只说「失败了」而不说「下一步查什么」等于把排障成本转嫁给下一个人）。
        """
        admin_client.post = AsyncMock(side_effect=RuntimeError("connection refused"))
        registry.register(_WriteTool())
        with patch("app.tools.registry.logger") as mock_logger:
            result = await registry.execute_tool(
                "write_audit_double", ctx, action="update_status", phone="13800138000"
            )

        assert result.success is True  # 审计不是业务护栏
        warnings = [str(c.args[0]) for c in mock_logger.warning.call_args_list]
        found = [w for w in warnings if PERSIST_FAILED_MARK in w]
        assert found, warnings
        # 留痕必须带 suggestion=（判据本体；去掉即红，见 tests/test_write_audit_action_semantics.py）
        assert any(SUGGESTION_MARK in w for w in found), found
        assert any("admin-api" in w for w in found if SUGGESTION_MARK in w), found

    async def test_audit_endpoint_business_failure_is_logged(self, registry, ctx, admin_client):
        """端点返回 success=false（如 422/租户上下文缺失）也须留痕，不得当成功吞掉。"""
        admin_client.post = AsyncMock(return_value={"success": False, "error": {"code": "X"}})
        registry.register(_WriteTool())
        with patch("app.tools.registry.logger") as mock_logger:
            result = await registry.execute_tool(
                "write_audit_double", ctx, action="update_status", phone="13800138000"
            )

        assert result.success is True
        warnings = [str(c.args[0]) for c in mock_logger.warning.call_args_list]
        found = [w for w in warnings if PERSIST_FAILED_MARK in w]
        assert found, warnings
        assert any(SUGGESTION_MARK in w for w in found), found

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
            result = await registry.execute_tool(
                "write_audit_double", ctx, action="update_status", phone="13800138000"
            )
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
            tool, {"action": "update_status", "phone": "13800138000"}, ctx, state
        )

        assert result_dict["success"] is True
        assert admin_client.post.await_count == 1
        payload = _payload(admin_client)
        # action = 动词 / toolName = 工具名（issue #4071 裁定 ①，生产接线同样成立）
        assert payload["action"] == "update_status"
        assert payload["toolName"] == "write_audit_double"
        assert payload["actionDetails"]["params"] == {"action": "<str>", "phone": "<str>"}
        assert admin_client.post.await_args.kwargs["user_id"] == ctx.user_id

    async def test_execute_tool_safe_persists_failure(self, ctx, admin_client):
        from app.graph.skills.base_skill import _execute_tool_safe

        self._clear_cache()
        tool = _WriteTool(raises=RuntimeError("boom"))
        state = {"session_id": "sess-audit-1", "tenant_id": 7}
        _str, result_dict = await _execute_tool_safe(
            tool, {"action": "update_status", "phone": "13800138000"}, ctx, state
        )

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


def _tools_declaring_before_price() -> set:
    """AST 扫 `app/tools/*.py`：`read_only = False` 且 schema 里声明了 `before_price` 的工具名。

    **从源码推出**（不维护第二份手抄清单）：`before_price` = 改前价，issue #5303 起是
    「传 price 就必须同时传」的必填预览字段 ⇒ 「声明了它」与「这个工具会改价」是同一件事。
    """
    import ast as _ast
    import pathlib as _pathlib

    tools_dir = _pathlib.Path(__file__).resolve().parents[1] / "app" / "tools"
    found = set()
    for path in sorted(tools_dir.glob("*.py")):
        tree = _ast.parse(path.read_text(encoding="utf-8"))
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.ClassDef):
                continue
            name = read_only = schema = None
            for stmt in node.body:
                if (isinstance(stmt, _ast.Assign) and len(stmt.targets) == 1
                        and isinstance(stmt.targets[0], _ast.Name)):
                    target = stmt.targets[0].id
                    if target == "name" and isinstance(stmt.value, _ast.Constant):
                        name = stmt.value.value
                    elif target == "read_only" and isinstance(stmt.value, _ast.Constant):
                        read_only = stmt.value.value
                    elif target == "parameters":
                        schema = stmt.value
            if not name or read_only is not False or schema is None:
                continue
            keys = {c.value for c in _ast.walk(schema)
                    if isinstance(c, _ast.Constant) and isinstance(c.value, str)}
            if "before_price" in keys:
                found.add(name)
    return found


class TestPriceChangeFactsAreRecorded:
    """issue #5388：**改价真值必须真的进审计行**（`action_details.priceChange`）。

    前提自证（本单证伪过的那一条）：`action_details.params` 按 PII 纪律只记类型占位
    （`desensitize_params`）⇒ 「改价的 before/after 已经在审计里」**原本不成立**
    （`params["price"]` 落库是字符串 `"<float>"`，规则将永远不可判定）。
    本类钉住修正后的形态：真值走**独立键**，`params` 的形状面一字不动。

    对照判据（会红吗）：把 `price_change_facts` 从载荷里摘掉 ⇒ 第 1 条必红；
    把价格键并回 `desensitize_params`（值被抹成占位）⇒ 同一条红；给非改价工具也发
    `priceChange` ⇒ 第 2 条红；新增改价工具漏登记 ⇒ 元守卫（第 4 条）红。
    """

    async def test_both_price_tools_carry_the_price_values(self, ctx, admin_client):
        """`product_update`（商品级统一定价）与 `sku_update`（单 SKU 调价）**都**带改价真值"""
        from app.tools.registry import audit_write_tool

        cases = (
            ("product_update",
             {"product_id": "P-1", "name": "雪尼尔-米白", "price": 12.5, "before_price": 10.0},
             {"price": 12.5, "before_price": 10.0, "product_id": "P-1"}),
            ("sku_update",
             {"product_id": "P-1", "color": "米白", "door_width": "2.8",
              "price": 250.0, "before_price": 500.0},
             {"price": 250.0, "before_price": 500.0, "product_id": "P-1",
              "color": "米白", "door_width": "2.8"}),
        )
        for tool_name, params, expected in cases:
            admin_client.post.reset_mock()
            await audit_write_tool(tool_name, ctx, params, True, 12.0)
            details = _payload(admin_client)["actionDetails"]
            assert details["priceChange"] == expected, tool_name
            # 🔴 形状面仍然脱敏（PII 纪律**不回退**）：同一行的 params 里没有任何真值
            assert details["params"]["price"] == "<float>"
            assert details["params"]["before_price"] == "<float>"
            assert not any(isinstance(v, (int, float)) for v in details["params"].values())

    async def test_other_write_tools_do_not_get_the_price_key(self, ctx, admin_client):
        """非改价工具不得多出 `priceChange`（审计载荷不许被隐式扩大），PII 照旧不出网"""
        from app.tools.registry import audit_write_tool

        await audit_write_tool("order_create", ctx,
                               {"customer_phone": "13800138000", "amount": 100.0}, True, 3.0)
        details = _payload(admin_client)["actionDetails"]
        assert "priceChange" not in details
        assert "13800138000" not in json.dumps(details, ensure_ascii=False)
        assert details["params"] == {"customer_phone": "<str>", "amount": "<float>"}

    async def test_absent_keys_are_not_invented(self, ctx, admin_client):
        """没传的键不进取证材料：缺 `before_price` ⇒ 记录里就没有它（**不是 0**）"""
        from app.tools.registry import audit_write_tool

        await audit_write_tool("product_update", ctx, {"product_id": "P-1", "price": 12.5}, True, 1.0)
        facts = _payload(admin_client)["actionDetails"]["priceChange"]
        assert facts == {"price": 12.5, "product_id": "P-1"}
        assert "before_price" not in facts

    def test_registry_covers_every_tool_declaring_before_price(self):
        """**类级元守卫**（§23 G1/G2）：声明 `before_price` 的写工具集 == 登记集（双向）。

        为什么需要它：病灶不是「漏了 `sku_update` 这一处」，而是
        「**新增一个改价工具 ⇒ 它的改价在审计里不可判定，而不会有任何东西变红**」。
        判据从源码推出（AST：`read_only` + schema 键），登记面漏一个/多一个都判红。
        """
        declared = _tools_declaring_before_price()
        assert declared, "一个都没解析出来 ⇒ 判据在空跑（锚点漂移，不是通过）"
        assert declared == set(registry_module._PRICE_CHANGE_TOOLS), (
            f"改了改价工具面而没同步登记：源码解析 {sorted(declared)} vs 登记 "
            f"{sorted(registry_module._PRICE_CHANGE_TOOLS)} —— 漏登记的工具其改价不会被任何规则发现")

    def test_batch_price_update_is_a_known_gap_not_a_silent_one(self):
        """已知缺口（照实登记）：批量改价**不在本项射程内**，但必须**披露**而不是静默漏掉。

        `product_batch_update` 的条目用 `oldValue/newValue`（不是 `before_price/price`），
        且属族 2（#5314）的批量写面 ⇒ 本单不扩射程；引擎侧 `price_change_over.caveats`
        逐字点名它 ⇒ 用户/调用方看得见这个缺口。
        """
        from app.briefing.proactive import RULES

        spec = next(r for r in RULES if r.rule_id == "price_change_over")
        assert "product_batch_update" in "；".join(spec.caveats), "已知缺口未披露 ⇒ 就是静默漏报"
        assert "product_batch_update" not in registry_module._PRICE_CHANGE_TOOLS