# case_ids: RG-001
"""写审计两处语义的可判定判据（issue #4071 两项裁定）。

裁定本体不在这里 —— 这里只把**已定的口径**变成「去掉就红」的判据
（`migao-acceptance`：不会红的断言 = 空断言）。两处语义各自成类：

## 一、`audit_logs.action` = **动词**（裁定 ①）

病灶：`action` 里放工具名 + `resource_type='agent_tool'` ⇒ **同一列两种语义**，
查询侧必须知道「action 的含义取决于 resource_type」这条隐式规则。

判据形态＝**两个集合的差集**（不是"当下恰好对"的真值主张）：
    （源码里 `read_only = False` 的工具）
      ⊖（有 `action` 参数的工具）  ==  `_NO_ACTION_PARAM_TOOL_ACTION` 的键集
增一个写工具忘了登记 ⇒ 红；登记了却不再需要 ⇒ 也红。

## 二、审计不可写时**有界 fail-open**（裁定 ②）

保持 fail-open（不做 fail-closed：后者新增业务写失败面，且与「审计是旁路」冲突），
但两条必须是**判据**而不是散文：
  ① `[AUDIT] PERSIST_FAILED …` 留痕里**必须带 `suggestion=`**（只说失败不说下一步＝把排障
     成本转嫁给下一个人）—— 去掉 `suggestion=` 即红（红证见本文件 `test_red_control_*`）；
  ② `3s` 硬上限**存在**且真的被 `wait_for` 使用（无上限的 fail-open 会把写路径一起拖住：
     `http_client` 默认 25s）。

L0 层（秒级、零外部依赖）—— 与 `tests/test_write_audit_persistence.py` 的分工：
那边跑**真实执行路径**（registry / base_skill），这边管**契约不变式**（集合相等、留痕格式）。
"""
import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "app" / "tools"
REGISTRY_PY = TOOLS_DIR / "registry.py"
MIGRATION_DIR = (REPO_ROOT.parent / "admin-api" / "src" / "main" / "resources"
                 / "db" / "migration")

# 工具被判定为「写工具」的**唯一**依据（与 registry 的执行分支同一字段）
_WRITE_MARKER = "read_only = False"
# 留痕标记（判据引用的字面量必须在实现里真出现，见 test_*_markers_exist_in_source）
_PERSIST_FAILED_MARK = "[AUDIT] PERSIST_FAILED"
_SUGGESTION_MARK = "suggestion="


def _tool_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _declared_name(src: str):
    """模块级工具名（`name = "xxx"`）—— 一个工具文件一个名字。"""
    m = re.search(r'^\s+name = "([^"]+)"', src, re.M)
    return m.group(1) if m else None


def _has_action_param(src: str) -> bool:
    """工具是否声明了 `action` 参数（决定动作取自参数还是映射表）。

    判据落在**调用契约** `parameters` 上，不是「源码里有没有出现 `action` 这个词」
    —— 后者会被注释/局部变量满足（本仓库的「断言匹配到注释」同族假绿）。
    """
    m = re.search(r"^\s+parameters\s*=\s*\{", src, re.M)
    if not m:
        return False
    # 从 parameters 起截到下一个顶层属性赋值（allowed_roles / read_only / …）
    tail = src[m.end():]
    nxt = re.search(r"\n    [a-z_]+ = ", tail)
    block = tail[: nxt.start()] if nxt else tail
    try:
        value = ast.literal_eval(block.rstrip().rstrip("}").rstrip() + "}")
    except (ValueError, SyntaxError):
        # 非字面量（含拼接/变量）⇒ 退回文本判定，但只在 properties 段内
        props = re.search(r'"properties"\s*:\s*\{(.*)', block, re.S)
        return bool(props) and re.search(r'"action"\s*:', props.group(1)) is not None
    return "action" in ((value or {}).get("properties") or {})


def _write_tools() -> dict:
    """{工具名: 是否有 action 参数} —— 源码扫描（写工具 = `read_only = False`）。

    非空断言是刻意的：解析失效时下面几条集合差集会在空集上恒真（空断言）。
    """
    out = {}
    for path in sorted(TOOLS_DIR.glob("*.py")):
        src = _tool_source(path)
        if _WRITE_MARKER not in src:
            continue
        name = _declared_name(src)
        if not name or name.startswith("_"):
            continue
        assert name not in out, f"工具名重复：{name}（{path.name}）—— 集合差集将失去意义"
        out[name] = _has_action_param(src)
    return out


def _mapping() -> dict:
    """`registry._NO_ACTION_PARAM_TOOL_ACTION`（实现里的唯一映射表）。"""
    from app.tools.registry import _NO_ACTION_PARAM_TOOL_ACTION

    return dict(_NO_ACTION_PARAM_TOOL_ACTION)


class TestActionMappingIsComplete:
    """裁定 ① 的集合差集：写工具集 ⊖ 有 action 参数的工具集 == 映射表键集。"""

    def test_write_tool_scan_is_non_trivial(self):
        """自检：确实扫到写工具与两类工具（否则下面几条空转 = 假绿）。"""
        tools = _write_tools()
        assert len(tools) >= 15, f"写工具扫描结果过少（{len(tools)}）—— 解析疑似失效：{tools}"
        assert any(tools.values()), "没有任何写工具声明 action 参数 —— 解析口径已坏"
        assert not all(tools.values()), (
            "所有写工具都被判为「有 action 参数」—— 解析口径已坏（无参数工具必然存在）"
        )

    def test_every_write_tool_without_action_param_is_mapped(self):
        """无 `action` 参数的工具**必须**在映射表里有动词（漏登记 ⇒ 红）。

        这条就是「禁止用工具名当动词」的落地判据：没有映射表就只能拿工具名顶替。
        """
        tools = _write_tools()
        need = {n for n, has in tools.items() if not has}
        missing = sorted(need - set(_mapping()))
        assert not missing, (
            f"以下写工具没有 `action` 参数、也未登记动作动词：{missing}\n"
            "修复：在 app/tools/registry.py 的 _NO_ACTION_PARAM_TOOL_ACTION 补 `工具名: 动词`"
            "（禁止用工具名当动词 —— 那正是 issue #4071 裁定 ① 要消灭的形态）"
        )

    def test_mapping_has_no_stale_entries(self):
        """登记的条目必须仍然需要（工具被删/加了 action 参数 ⇒ 销账未删即红）。"""
        tools = _write_tools()
        need = {n for n, has in tools.items() if not has}
        stale = sorted(set(_mapping()) - need)
        assert not stale, (
            f"映射表登记了已不再需要的工具：{stale}\n"
            "（已删除，或已自带 action 参数 ⇒ 从 _NO_ACTION_PARAM_TOOL_ACTION 删掉该条目）"
        )

    def test_mapping_values_are_verbs_not_tool_names(self):
        """映射值必须是**动词**：不得等于工具名，也不得含下划线（裁定 ① 本体）。

        动作词取自各工具 `action` 参数里的**单个**动词（create/update/delete/…、generate）；
        带下划线的复合形态是工具名（`order_create`/`product_update`/`human_handoff`）或
        `action` 参数的复合值（`update_status`）—— 前者禁止，后者不该出现在**兜底表**里
        （工具自带 action 参数时根本走不到映射表）。
        """
        tools = _write_tools()
        bad = sorted(
            f"{k} → {v!r}"
            for k, v in _mapping().items()
            if v in tools or "_" in v
        )
        assert not bad, (
            f"映射值不是单一动词（疑似把工具名/复合 action 值当动词）：{bad}\n"
            "兜底动词只能用 create/update/delete/generate 这类单词"
        )


class TestDeriveAuditAction:
    """`derive_audit_action` 的两档顺序：参数优先，其次映射表；**永不回退成工具名**。"""

    def test_action_param_wins_over_mapping(self):
        """参数优先：同一工具带 action 参数时，取参数值而不是映射表值。"""
        from app.tools.registry import derive_audit_action

        assert derive_audit_action("order_manage", {"action": "confirm_payment"}) == \
            "confirm_payment"
        # 参数值本身是动词，不受映射表是否存在该工具影响
        assert derive_audit_action("product_manage", {"action": "toggle_status"}) == \
            "toggle_status"

    def test_mapping_used_when_tool_has_no_action_param(self):
        """无 action 参数（含参数缺省/空白）⇒ 查映射表。"""
        from app.tools.registry import derive_audit_action

        mapping = _mapping()
        for tool, verb in mapping.items():
            assert derive_audit_action(tool, {}) == verb
            assert derive_audit_action(tool, {"action": "  "}) == verb
            assert derive_audit_action(tool, None) == verb

    def test_never_falls_back_to_tool_name(self):
        """**核心负例**：派生不出动作时返回 None，绝不把工具名当动作（裁定 ① 的题眼）。"""
        from app.tools.registry import derive_audit_action

        ghost = "ghost_tool_not_in_mapping"
        assert derive_audit_action(ghost, {}) is None, (
            "派生失败时回退了工具名 —— 那正是「同一列两种语义」的复发形态"
        )

    def test_unmapped_tool_persists_sentinel_and_logs(self):
        """漏登记的工具：action 落哨兵（不违反 NOT NULL）+ 打 ACTION_UNMAPPED 留痕。

        为什么这里是**哨兵**而不是抛错：审计上报在工具执行路径上，抛错会把
        「漏登记」升级成「业务写失败」—— 与裁定 ②「审计不得阻断业务写」冲突。
        漏登记本身由上面的集合差集在 L0 层拦（那时还没进生产）。
        """
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app.tools.base import ToolContext, ToolResult
        from app.tools.registry import ToolRegistry, _UNMAPPED_ACTION_SENTINEL
        from tests.test_write_audit_persistence import _WriteTool

        class _UnmappedWriteTool(_WriteTool):
            name = "ghost_write_tool_without_action"
            parameters = {"type": "object", "properties": {"phone": {"type": "string"}}}

            async def execute(self, context, **kwargs) -> ToolResult:
                return ToolResult(success=True, data={}, message="done")

        client = AsyncMock()
        client.post = AsyncMock(return_value={"success": True})
        registry = ToolRegistry()
        registry.register(_UnmappedWriteTool())
        ctx = ToolContext(tenant_id=7, user_id="u-audit-1", session_id="s", role="admin")
        try:
            with patch("app.tools.registry.get_admin_api_client", return_value=client), \
                    patch("app.tools.registry.logger") as mock_logger:
                result = asyncio.run(registry.execute_tool("ghost_write_tool_without_action", ctx))
        finally:
            registry.clear()

        assert result.success is True, "漏登记不得升级成业务写失败（审计是旁路）"
        payload = client.post.await_args.kwargs["json_data"]
        assert payload["action"] == _UNMAPPED_ACTION_SENTINEL
        assert payload["action"] != payload["toolName"], (
            "action 与 toolName 相等 ⇒ 工具名又回到了 action 列（裁定 ① 复发）"
        )
        warnings = [str(c.args[0]) for c in mock_logger.warning.call_args_list]
        assert any("ACTION_UNMAPPED" in w for w in warnings), warnings


class TestBoundedFailOpenContract:
    """裁定 ②：有界 fail-open 的两条判据（`suggestion=` + 3s 上限）。"""

    def test_timeout_bound_exists_and_is_three_seconds(self):
        """3s 硬上限**存在**：http_client 默认 25s，无上限的 fail-open 会拖住写路径。"""
        from app.tools import registry

        assert registry._WRITE_AUDIT_TIMEOUT_S == 3.0, (
            f"审计上报上限被改动（实为 {registry._WRITE_AUDIT_TIMEOUT_S}）—— "
            "裁定 ② 的「有界」即指此值；改它必须重跑本判据并说明理由"
        )

    def test_timeout_bound_is_actually_used_by_wait_for(self):
        """上限必须**真的**被 `wait_for` 使用（声明无消费 = R5 的静默失效）。

        判据用**配平括号**切出 `asyncio.wait_for(...)` 的实参（不是 `.{0,N}?` 窗口 ——
        窗口是长度猜测，参数一多就假红；而把窗口调大又会让「别处的 timeout=」误判为已使用）。
        """
        match = re.search(
            r"asyncio\.wait_for\(", _tool_source(REGISTRY_PY)
        )
        assert match, "registry.py 里已无 asyncio.wait_for —— 审计上报失去硬上限"
        depth, body = 1, ""
        for ch in _tool_source(REGISTRY_PY)[match.end():]:
            if ch == ")":
                depth -= 1
                if depth == 0:
                    break
            elif ch == "(":
                depth += 1
            body += ch
        assert "timeout=_WRITE_AUDIT_TIMEOUT_S" in body, (
            f"审计上报未用 _WRITE_AUDIT_TIMEOUT_S 截断，实参为：{body[:300]!r}"
        )

    def test_persist_failed_marker_exists_in_source(self):
        """留痕标记必须在实现里真出现（防判据指向一个谁也不打的标记）。"""
        src = _tool_source(REGISTRY_PY)
        assert _PERSIST_FAILED_MARK in src, f"实现里已无 {_PERSIST_FAILED_MARK!r} 这条留痕"
        assert _SUGGESTION_MARK in src, f"实现里已无 {_SUGGESTION_MARK!r}"

    def test_persist_failed_message_carries_suggestion(self, monkeypatch):
        """**判据本体**：`PERSIST_FAILED` 留痕消息必须含 `suggestion=`。

        走**真实实现**（不 mock logger，改为接管 sink）—— 去掉 `suggestion=` 即红。
        """
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app.tools.base import ToolContext
        from app.tools.registry import ToolRegistry
        from tests.test_write_audit_persistence import _WriteTool

        captured: list = []
        monkeypatch.setattr(
            "app.tools.registry.logger.warning",
            lambda message, *a, **kw: captured.append(str(message)),
        )

        client = AsyncMock()
        client.post = AsyncMock(side_effect=RuntimeError("connection refused"))
        registry = ToolRegistry()
        registry.register(_WriteTool())
        ctx = ToolContext(tenant_id=7, user_id="u-audit-1", session_id="s", role="admin")
        try:
            with patch("app.tools.registry.get_admin_api_client", return_value=client):
                result = asyncio.run(
                    registry.execute_tool("write_audit_double", ctx, action="update_status")
                )
        finally:
            registry.clear()

        assert result.success is True, "审计失败不得阻断业务写（裁定 ② 的 fail-open 部分）"
        found = [m for m in captured if _PERSIST_FAILED_MARK in m]
        assert found, f"端点不可用却没有 {_PERSIST_FAILED_MARK} 留痕：{captured}"
        assert any(_SUGGESTION_MARK in m for m in found), (
            f"留痕缺 {_SUGGESTION_MARK!r} —— 只说失败不说下一步（裁定 ② 的可判定判据）：{found}"
        )
        # suggestion= 后面必须真有内容（`suggestion=` 空尾 = 形式主义）
        assert any(re.search(r"suggestion=\S", m) for m in found), found

    def test_migration_backfill_never_guesses(self):
        """迁移 V52 的回填口径必须与裁定一致：派生不出动作的行**不猜**。

        判据落在迁移文件上（不是散文）：① 派生来源是 `action_details->>'action'`；
        ② 有一张**工具名拒收清单**（JSON 里仍是工具名 ⇒ 保持原值）；
        ③ 不回退成任何"最可能的动词"（无 `ELSE`/`COALESCE` 式兜底改写）。
        """
        path = MIGRATION_DIR / "V52__audit_logs_tool_name.sql"
        assert path.is_file(), f"迁移缺失：{path}"
        sql = path.read_text(encoding="utf-8")
        assert "ADD COLUMN IF NOT EXISTS tool_name" in sql, "V52 未新增 tool_name 列"
        assert "action_details ->> 'action'" in sql, (
            "回填未从 action_details->>'action' 派生（判据：唯一事实源是 registry 的派生结果）"
        )
        # 工具名拒收清单：至少含若干真实工具名，且注释里写明「不猜」
        for tool in ("order_create", "product_manage", "after_sales_manage"):
            assert f"'{tool}'" in sql, f"V52 的拒收清单缺 {tool} —— 工具名会被当动词回填"
        assert "不猜" in sql, "V52 未写明「派生不出来不猜」的口径（裁定明文要求）"
        # 无兜底改写：不得出现 COALESCE(..., 'create') 这类猜测式回填
        assert not re.search(r"COALESCE\([^)]*'(create|update|delete)'", sql, re.I), (
            "V52 出现猜测式兜底（COALESCE 到某个动词）—— 与「不猜」口径冲突"
        )


class TestRedControls:
    """红证：判据本身必须能变红（否则「仓库全绿」可能只是空断言）。

    用**注入式**红证（不依赖仓库真值）：把被测对象换成坏形态，断言判据会报出。
    """

    def test_red_control_mapping_completeness(self):
        """漏登记 ⇒ 集合差集必报出（模拟：写工具在映射表里查不到）。"""
        tools = _write_tools()
        need = {n for n, has in tools.items() if not has}
        assert need, "没有无 action 参数的写工具 —— 本红证失去被测对象"

        injected = {}  # 空映射表 = 全部漏登记
        missing = sorted(need - set(injected))
        assert missing, "注入空映射表后差集为空 ⇒ 集合差集判据恒真（空断言）"

    def test_red_control_suggestion_matcher(self):
        """去掉 `suggestion=` ⇒ 匹配器必报出（证明上面那条断言不是恒真）。"""
        without = f"{_PERSIST_FAILED_MARK} tool=x error=RuntimeError: boom"
        with_hint = (f"{_PERSIST_FAILED_MARK} tool=x error=RuntimeError: boom | "
                     f"suggestion=检查 admin-api 存活")

        assert _SUGGESTION_MARK not in without, "匹配器对无 suggestion 的留痕判为通过（恒真）"
        assert _SUGGESTION_MARK in with_hint, "匹配器对带 suggestion 的留痕判为缺失（恒假）"
        assert re.search(r"suggestion=\S", with_hint)
        assert not re.search(r"suggestion=\S", without.replace("suggestion= ", "suggestion= "))