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
import pathlib as _pathlib

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


# ── 改价**路径**台账的元守卫（§23 G1/G2；issue #5411 把射程从「工具」收到「路径」）──────

#: 会改价的**路径**能从 schema 里认出的字面量 —— **键**与 **enum 取值**两类（描述文本一律不取）。
#: 🔴 为什么必须认 enum 取值（本单 core）：批量改价的 schema 里**没有 `price` 键** ——
#: 它的价格面在 `batch_type: ["product_price", …]` 与 `field: ["basePrice", …]` 两个 enum 里
#: ⇒ 只认键的旧口径**结构上看不见这条路径**（这正是 #5411 那个缺口的形状）。
PRICE_TOKEN_KEYS = frozenset({"price", "before_price", "basePrice"})
PRICE_TOKEN_ENUM_VALUES = frozenset({"basePrice", "product_price"})
#: 「**改前值**」字面量 = 改价**可判定**的前提（幅度要两头）：豁免「改前价不可得」必须靠它可证。
BEFORE_VALUE_TOKENS = frozenset({"before_price", "oldValue"})
#: 已登记的**取数面**（新面要在这里加，并同步装配层 + 判据）。
PRICE_EVIDENCE_SOURCES = frozenset({"audit_price_change", "batch_items"})

#: 豁免台账的**冻结基线**（§23 G2「只许缩短」）：加/删一条都要动这一行 + 引擎 caveats 点名 +
#: 过活体判据（工具侧「改前价仍不可得」/ HTTP 侧「锚点仍在且仍不写 agent_tool 审计」）。
EXEMPT_PATH_BASELINE = ("http:admin-web-product-edit", "product_manage")

#: 豁免台账里 HTTP 路径的活体锚点：该路径**真的存在**（锚点现取命中恰好 1 次），且**仍不写**
#: `agent_tool` 审计（补上了 ⇒ 该豁免的理由被推翻 ⇒ 红）。
JAVA_HTTP_PATH_SOURCES = (
    "backend/admin-api/src/main/java/com/migao/admin/controller/ProductController.java",
)
AGENT_TOOL_MARK = "agent_tool"

_TOOLS_DIR = _pathlib.Path(__file__).resolve().parents[1] / "app" / "tools"
#: 仓库根（`<repo>/backend/ai-agent-service/tests/…` ⇒ parents[3]）—— 跨模块判据按**仓库相对路径**取源
_REPO_ROOT = _pathlib.Path(__file__).resolve().parents[3]


def _write_tools_with_schema(tools_dir: _pathlib.Path) -> dict:
    """AST 扫 `app/tools/*.py`：`read_only = False` 的工具 → 它 schema 里**结构化的**字面量。

    返回 `{工具名: {"keys": set, "enums": set}}`：
    · `keys`  = `properties`（**任意深度**，含 `items.properties`）下的键；
    · `enums` = 任意 `enum` 列表里的常量取值。

    **不取 description / 任何散文文本**（「描述里提一句 price」不算会改价 —— #5388 的既有纪律，
    也是 `.github/growth_gate.py` 那类「原文当代码读」的反面）。
    """
    import ast as _ast

    found = {}
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
            keys, enums = set(), set()
            for inner in _ast.walk(schema):
                if not isinstance(inner, _ast.Dict):
                    continue
                for key, value in zip(inner.keys, inner.values):
                    if not isinstance(key, _ast.Constant):
                        continue
                    if key.value == "properties" and isinstance(value, _ast.Dict):
                        keys |= {k.value for k in value.keys if isinstance(k, _ast.Constant)}
                    elif key.value == "enum" and isinstance(value, (_ast.List, _ast.Tuple)):
                        enums |= {e.value for e in value.elts
                                  if isinstance(e, _ast.Constant) and isinstance(e.value, str)}
            found[name] = {"keys": keys, "enums": enums}
    return found


def _price_paths_from_sources(tools_dir: _pathlib.Path) -> dict:
    """**会改价**的写工具（= 路径）—— 判据 = schema 里**结构化的价格字面量**（键或 enum 取值）。

    ⚠️ 前一版（#5388 / PR #5410）只认 `properties` 的**键**里的 `price`。那不叫「按会改价的
    **路径**收口」：**射程决定了缺口会在哪里出现** —— 批量改价恰好落在那个射程之外
    （它的 schema 里没有 `price` 键，价格面在 `batch_type` / `field` 的 enum 取值里）。
    """
    return {name: schema for name, schema in _write_tools_with_schema(tools_dir).items()
            if (schema["keys"] & PRICE_TOKEN_KEYS) or (schema["enums"] & PRICE_TOKEN_ENUM_VALUES)}


def price_path_ledger_problems(*, derived: dict, tracked: dict, exempt: dict, caveats: str,
                               tool_names: set, sources: dict, baseline) -> list:
    """改价路径台账的**纯函数**判据（⇒ 可用构造的缺陷载荷自证判别力，见 `TestPricePathGuardSelfProof`）。

    入参（全部**现取**，不维护第二份手抄清单）：
    · `derived`    = `{路径: {"keys","enums"}}` —— 现取（源码 AST）
    · `tracked`    = `{路径: 取数面 id}` —— 生产台账 `registry.PRICE_EVIDENCE_PATHS`
    · `exempt`     = `{路径 id: {"kind","reason","issue",…}}` —— `registry._UNTRACKED_PRICE_PATHS`
    · `caveats`    = 引擎 `price_change_over.caveats` 拼接文本（缺口不许只活在代码注释里）
    · `tool_names` = 源码里全部写工具名（豁免条目的活体判据）
    · `sources`    = `{仓库相对路径: 文本}`（HTTP 路径豁免的活体判据）
    · `baseline`   = 冻结基线（只许缩短）
    """
    problems = []
    derived_names, tracked_names, exempt_names = set(derived), set(tracked), set(exempt)

    missing = sorted(derived_names - tracked_names - exempt_names)
    if missing:
        problems.append(
            f"会改价的路径既未登记取数面、也未登记为显式豁免：{missing} —— 它的改价不会被 "
            f"price_change_over 发现，而没有任何东西会红。出口（二选一，都可行动）："
            f"① 登记进 registry.PRICE_EVIDENCE_PATHS（并在装配层真的产出该路径的改价行）；"
            f"② 登记进 registry._UNTRACKED_PRICE_PATHS（带 reason + issue）并由引擎 caveats 点名")
    wider = sorted(tracked_names - derived_names)
    if wider:
        problems.append(f"登记面比现实宽：{wider} 并未声明任何价格字面量 ⇒ 口径漂移（谁在改价？）")
    both = sorted(tracked_names & exempt_names)
    if both:
        problems.append(f"同一路径不得既登记取数面又登记为豁免：{both}")

    for path, source in sorted(tracked.items()):
        if source not in PRICE_EVIDENCE_SOURCES:
            problems.append(
                f"{path} 的取数面 {source!r} 不在已登记集合 {sorted(PRICE_EVIDENCE_SOURCES)} ⇒ "
                f"新取数面必须登记并同步装配层 + 判据（不许匿名新增取数面）")

    for path, entry in sorted(exempt.items()):
        kind = entry.get("kind")
        reason, issue = str(entry.get("reason") or ""), str(entry.get("issue") or "")
        if len(reason) < 8:
            problems.append(f"豁免 {path} 缺 reason（豁免必须写清「为什么接不上」，不许留白）")
        if not issue.startswith("#"):
            problems.append(f"豁免 {path} 缺 issue（豁免要能回溯到单号，不许留白）")
        if kind == "tool":
            if path not in tool_names:
                problems.append(f"豁免 {path} 在源码里已不存在（陈旧条目必须销账）")
            elif derived.get(path, {}).get("keys", set()) & BEFORE_VALUE_TOKENS:
                problems.append(
                    f"豁免 {path} 已**可判定**（schema 里出现了改前值 "
                    f"{sorted(derived[path]['keys'] & BEFORE_VALUE_TOKENS)}）⇒ 必须移进 "
                    f"PRICE_EVIDENCE_PATHS，不许继续挂豁免")
        elif kind == "http":
            anchor_path, anchor = entry.get("alive_anchor", ("", ""))
            text = sources.get(anchor_path)
            if text is None:
                problems.append(f"豁免 {path} 的活体锚点文件读不到：{anchor_path}")
            elif text.count(anchor) != 1:
                problems.append(
                    f"豁免 {path} 的活体锚点失配（{anchor_path} 里命中 {text.count(anchor)} 次，"
                    f"要求恰好 1 次）⇒ 该路径已改名/删除 ⇒ 条目过期，必须重新取证")
            elif AGENT_TOOL_MARK in text:
                problems.append(
                    f"豁免 {path} 的理由已被推翻：{anchor_path} 现在**写了** {AGENT_TOOL_MARK} 审计"
                    f" ⇒ 该路径进了取数面 ⇒ 豁免作废（移进 PRICE_EVIDENCE_PATHS）")
        else:
            problems.append(f"豁免 {path} 的 kind={kind!r} 既不是 tool 也不是 http ⇒ 条目形态不明")
        token = str(entry.get("caveat_token") or path)
        if token not in caveats:
            problems.append(f"豁免 {path} 未在引擎 caveats 里点名（找 {token!r}）⇒ 那就是静默漏报")

    if sorted(exempt) != sorted(baseline):
        problems.append(
            f"豁免台账与冻结基线不一致：现取 {sorted(exempt)} vs 基线 {sorted(baseline)} —— "
            f"台账**只许缩短**：修好一条就在基线里销掉它；新增一条要动基线（diff 可见）"
            f"+ 过活体判据 + 引擎 caveats 点名")
    return problems


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

    def test_python_and_java_price_tool_lists_agree(self):
        """**跨模块字面量必须机械钉住**（复核 P2）：Python 侧与 Java 侧的工具表 / resource_type 逐字相等。

        漂移方向是**静默漏报**（Python 加了工具、Java 没加 ⇒ 快照里那类改价永远不出现，
        而两侧各自单测都绿）⇒ 判据读 Java 源码字面量比对，不靠「注释声称逐字相同」。
        """
        import re

        java = (_REPO_ROOT / "backend" / "admin-api" / "src" / "main"
                / "java" / "com" / "migao" / "admin" / "service" / "DailyBriefingService.java"
                ).read_text(encoding="utf-8")
        tools = re.search(r"PRICE_CHANGE_TOOLS = List\.of\(([^)]*)\)", java)
        assert tools, "Java 侧找不到 PRICE_CHANGE_TOOLS 字面量 ⇒ 锚点漂移（判据不得静默通过）"
        java_tools = set(re.findall(r'"([^"]+)"', tools.group(1)))
        assert java_tools == set(registry_module._PRICE_CHANGE_TOOLS), (
            f"两侧改价工具表漂移：Java {sorted(java_tools)} vs Python "
            f"{sorted(registry_module._PRICE_CHANGE_TOOLS)} —— 漂移方向是静默漏报")
        resource = re.search(r'AGENT_TOOL_RESOURCE_TYPE = "([^"]+)"', java)
        assert resource, "Java 侧找不到 AGENT_TOOL_RESOURCE_TYPE 字面量 ⇒ 锚点漂移"
        assert resource.group(1) == registry_module._WRITE_AUDIT_RESOURCE_TYPE

    def test_python_and_java_batch_leg_literals_agree(self):
        """**批量腿**（issue #5411）的跨模块字面量同样机械钉住 —— 这条腿的三处必须逐字同源：

        ① Java 的批量工具名 == Python 台账里「取数面 = batch_items」的那条路径 id；
        ② Java 的批次类型 / 字段名 ∈ Python 工具 schema 自己声明的 enum 取值（真值在**工具**那一侧）；
        ③ Python 侧不得把批量腿冒充成审计腿（`_PRICE_CHANGE_TOOLS` 是审计腿的工具集合）。

        漂移方向仍是**静默漏报**：两边字面量不一致 ⇒ 装配层筛不到那些批次行，
        而两侧各自单测都绿（本单的 P0 就是这个形状）。
        """
        import re

        java = (_REPO_ROOT / "backend" / "admin-api" / "src" / "main"
                / "java" / "com" / "migao" / "admin" / "service" / "DailyBriefingService.java"
                ).read_text(encoding="utf-8")
        batch_tool = re.search(r'BATCH_PRICE_TOOL = "([^"]+)"', java)
        batch_type = re.search(r'BATCH_TYPE_PRICE = "([^"]+)"', java)
        batch_field = re.search(r'BATCH_FIELD_BASE_PRICE = "([^"]+)"', java)
        assert batch_tool and batch_type and batch_field, "Java 侧找不到批量腿字面量 ⇒ 锚点漂移"
        python_batch_paths = sorted(
            name for name, source in registry_module.PRICE_EVIDENCE_PATHS.items()
            if source == "batch_items")
        assert [batch_tool.group(1)] == python_batch_paths, (
            f"批量腿两侧漂移：Java 工具 {batch_tool.group(1)!r} vs Python 登记 "
            f"{python_batch_paths} —— 装配层筛的名字与台账不在同一处")
        declared = _price_paths_from_sources(_TOOLS_DIR)[batch_tool.group(1)]["enums"]
        assert {batch_type.group(1), batch_field.group(1)} <= declared, (
            f"Java 的批次类型/字段字面量 {batch_type.group(1)!r}/{batch_field.group(1)!r} "
            f"不在工具 schema 声明的 enum 取值 {sorted(declared)} 里 ⇒ 其中一侧改名了（真值在工具那一侧）")
        assert batch_tool.group(1) not in registry_module._PRICE_CHANGE_TOOLS, (
            "批量改价**不是**审计腿的工具（执行批量时参数只有 batch_id，审计行里没有价格可落）"
            " ⇒ 混进审计腿会让「审计里有改价真值」变成一句假话")


class TestPricePathLedgerIsScopedToPriceChangingPaths:
    """🔴 issue #5411：元守卫按「**会改价的路径**」收口（而不是「声明 `price` 的工具」）。

    ## 病灶（类）：**射程决定了缺口会在哪里出现**

    #5388 / PR #5410 把射程从「声明 `before_price`」扩到「声明 `price`」—— 修好了
    `product_manage` 那一处，但**批量改价**根本不在这个射程里：它的 schema 里没有 `price` 键，
    价格面在 `batch_type: ["product_price"]` / `field: ["basePrice"]` 两个 **enum 取值**里。
    ⇒ 元守卫覆盖不到的路径，**不会有任何东西变红**（这才是本单要治的类）。

    ## 判据（值一律现取；判据源 = 源码 AST + 生产台账 + 引擎 caveats + 冻结基线）

    | # | 判据 | 红证（怎么让它单独变红） |
    |---|---|---|
    | ① | 会改价的路径 ⊆ 登记取数面 ∪ 显式豁免（**未登记即红**） | 加一个声明 `basePrice` 的写工具 ⇒ 红 |
    | ② | 登记面 ⊆ 现取派生（口径漂移 ⇒ 红） | 登记一个不声明价格字面量的工具 ⇒ 红 |
    | ③ | 取数面 id 必须在册（不许匿名新增取数面） | 把某条路径的取数面改成 `"guess"` ⇒ 红 |
    | ④ | 豁免必须**活着**：工具侧「改前价仍不可得」、HTTP 侧「锚点在 + 仍不写 agent_tool 审计」 | 给 `product_manage` 补 `before_price` ⇒ 红；在 `ProductController` 里写 `agent_tool` ⇒ 红 |
    | ⑤ | 每条豁免带 `reason` + `issue`，且**在引擎 caveats 里被点名** | 删掉 caveats 里的点名 ⇒ 红 |
    | ⑥ | 豁免台账 == **冻结基线**（只许缩短：加/删都要动基线那一行） | 台账里加一条而不动基线 ⇒ 红 |

    ⇒ **燃尽锚点**（现取，不写死）：派生路径数 / 登记数 / 豁免数 / 基线数 —— 由本文件每次打印。
    """

    def _live_ledgers(self):
        derived = _price_paths_from_sources(_TOOLS_DIR)
        tool_names = set(_write_tools_with_schema(_TOOLS_DIR))
        sources = {rel: (_REPO_ROOT / rel).read_text(encoding="utf-8")
                   for rel in JAVA_HTTP_PATH_SOURCES}
        return derived, tool_names, sources

    def test_every_price_changing_path_is_registered(self):
        from app.briefing.proactive import RULES

        derived, tool_names, sources = self._live_ledgers()
        assert derived, "一条会改价的路径都没解析出来 ⇒ 判据在空跑（锚点漂移，不是通过）"
        tracked = dict(registry_module.PRICE_EVIDENCE_PATHS)
        exempt = dict(registry_module._UNTRACKED_PRICE_PATHS)
        caveats = "；".join(next(r for r in RULES if r.rule_id == "price_change_over").caveats)

        print(f"[燃尽锚点 改价路径] 现取派生={len(derived)} {sorted(derived)}"
              f" / 登记取数面={len(tracked)} {sorted(tracked)}"
              f" / 豁免={len(exempt)} {sorted(exempt)} / 冻结基线={len(EXEMPT_PATH_BASELINE)}")
        problems = price_path_ledger_problems(
            derived=derived, tracked=tracked, exempt=exempt, caveats=caveats,
            tool_names=tool_names, sources=sources, baseline=EXEMPT_PATH_BASELINE)
        assert not problems, (
            "改价路径台账不合格（未登记即红 / 豁免过期即红）—— 逐条修法见下面的每一行：\n"
            + "\n".join(f"  - {p}" for p in problems))

    def test_batch_price_change_is_in_scope_through_the_batch_items(self):
        """🔴 #5411 的成果：批量改价**在射程内**（取数面 = 批次明细），且**不是**靠审计腿冒充的。"""
        assert registry_module.PRICE_EVIDENCE_PATHS.get("product_batch_update") == "batch_items", (
            "批量改价必须以 batch_items 为取数面登记（它的价格事实落在 "
            "agent_batch_items.old_value/new_value，不在审计行里）")
        assert "product_batch_update" not in registry_module._UNTRACKED_PRICE_PATHS, (
            "批量改价已进射程 ⇒ 不许继续挂在豁免台账里（那会把已修的缺口重新写成「已知缺口」）")
        assert registry_module._PRICE_CHANGE_TOOLS == frozenset({"product_update", "sku_update"}), (
            "审计腿的工具集合不得被批量腿污染（执行批量时只带 batch_id ⇒ 元守卫必须用**另一条腿**覆盖它）")


class TestPricePathGuardSelfProof:
    """红证前提自证（§23 G7）：把构造的缺陷载荷喂给同一判据内核 ⇒ **必须**逐条报出。

    「不会红的断言 = 空断言」—— 上面那条主判据要能被这些注入单独打红，否则它在空跑。
    每条注入都配一个**同载荷不注入必须干净**的对照（证明红是注入造成的）。
    """

    CLEAN = {
        "derived": {
            "product_update": {"keys": {"price", "before_price"}, "enums": set()},
            "product_batch_update": {"keys": {"batch_id"}, "enums": {"product_price", "basePrice"}},
            "product_manage": {"keys": {"price"}, "enums": set()},
        },
        "tracked": {"product_update": "audit_price_change",
                    "product_batch_update": "batch_items"},
        "exempt": {
            "product_manage": {"kind": "tool", "reason": "改前价不可得（无 before_price 预览约束）",
                               "issue": "#5411", "caveat_token": "product_manage"},
            "http:admin-web-product-edit": {
                "kind": "http", "reason": "后台页面直接改价不经 Agent ⇒ 不写 agent_tool 审计",
                "issue": "#5411", "caveat_token": "后台页面直接改价",
                "alive_anchor": ("backend/admin-api/src/main/java/com/migao/admin/controller/"
                                 "ProductController.java", "public ApiResponse<ProductResponse> updateProduct("),
            },
        },
        "caveats": "product_manage 与 后台页面直接改价 是本项显式豁免的两条路径",
        "tool_names": {"product_update", "product_batch_update", "product_manage"},
        "sources": {"backend/admin-api/src/main/java/com/migao/admin/controller/ProductController.java":
                    "public ApiResponse<ProductResponse> updateProduct( ... ) { ... }"},
        "baseline": ("http:admin-web-product-edit", "product_manage"),
    }

    def _payload(self, **overrides):
        payload = {key: (dict(value) if isinstance(value, dict) else value)
                   for key, value in self.CLEAN.items()}
        payload.update(overrides)
        return payload

    def test_the_clean_payload_is_silent(self):
        assert price_path_ledger_problems(**self._payload()) == [], "对照载荷本身就不干净 ⇒ 下面的红证不算证据"

    def test_injected_defects_are_each_reported(self):
        cases = (
            ("未登记的新改价路径",
             {"derived": {**self.CLEAN["derived"],
                          "product_ai_edit": {"keys": {"basePrice"}, "enums": set()}}},
             "既未登记取数面、也未登记为显式豁免"),
            ("登记面比现实宽",
             {"tracked": {**self.CLEAN["tracked"], "order_create": "audit_price_change"}},
             "登记面比现实宽"),
            ("匿名取数面",
             {"tracked": {"product_update": "guess", "product_batch_update": "batch_items"}},
             "不在已登记集合"),
            ("豁免已可判定（改前价有了）",
             {"derived": {**self.CLEAN["derived"],
                          "product_manage": {"keys": {"price", "before_price"}, "enums": set()}}},
             "已**可判定**"),
            ("HTTP 豁免的理由被推翻（该路径写了 agent_tool 审计）",
             {"sources": {list(JAVA_HTTP_PATH_SOURCES)[0]:
                          "public ApiResponse<ProductResponse> updateProduct( ... ) { "
                          "audit(\"agent_tool\"); }"}},
             "理由已被推翻"),
            ("HTTP 豁免的活体锚点失配（路径改名/删除）",
             {"sources": {list(JAVA_HTTP_PATH_SOURCES)[0]: "class ProductController {}"}},
             "活体锚点失配"),
            ("豁免缺 issue",
             {"exempt": {**self.CLEAN["exempt"],
                         "product_manage": {**self.CLEAN["exempt"]["product_manage"], "issue": ""}}},
             "缺 issue"),
            ("豁免未在引擎 caveats 里点名",
             {"caveats": "（谁也没提）"},
             "未在引擎 caveats 里点名"),
            ("台账与冻结基线不一致（悄悄加一条豁免）",
             {"exempt": {**self.CLEAN["exempt"],
                         "http:legacy-page": {"kind": "http", "reason": "先挂上再说",
                                              "issue": "#5411", "caveat_token": "后台页面直接改价",
                                              "alive_anchor": (list(JAVA_HTTP_PATH_SOURCES)[0],
                                                               "class ProductController")}}},
             "与冻结基线不一致"),
            ("豁免条目在源码里已不存在（陈旧条目）",
             {"tool_names": {"product_update", "product_batch_update"}},
             "已不存在（陈旧条目必须销账）"),
        )
        reported = []
        for label, overrides, expected in cases:
            problems = price_path_ledger_problems(**self._payload(**overrides))
            hit = [p for p in problems if expected in p]
            assert hit, (f"注入「{label}」没被任何判据报出 ⇒ 该判据是空断言；"
                         f"现取问题清单={problems}")
            reported.append((label, hit[0][:90]))
        print(f"[红证自证 改价路径台账] 注入 {len(cases)} 条 ⇒ 全部独立报出：")
        for label, first in reported:
            print(f"  · {label} ⇒ {first}")