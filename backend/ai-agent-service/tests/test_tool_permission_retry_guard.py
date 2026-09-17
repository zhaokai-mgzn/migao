# case_ids: DF-017, CH-001, DF-007
"""授权类失败不得被自修复重试（issue #4109，并入 #4106 交付）— 常驻 L0/L2 守卫。

## 病灶形状

`base_skill._self_correct_retry` 的判据是「`success=False` + `suggestion` 非空」，
**不看失败的性质**（先例 issue #3564 已为「非幂等写」补过一次同款护栏）。于是
**权限拒绝**（`error.code = PERMISSION_DENIED` / `FORBIDDEN` / 401 系列）也会被自动
重试一次：拿同一身份、同一权限再调一次**永远不可能成功**，只是把同一次拒绝又买了一遍；
而且重试入口会**改写失败提示**（`suggestion_llm` 按「参数怎么补」纠正参数），让模型以为
这是参数问题 —— 与 `app/tools/base.py::admin_api_failure` 给权限拒绝写的「不要重试」建议
互相打架，最终用户等来的仍是「稍后重试」。

## 修复（与 #3564 同款机制层护栏，不靠工具自觉）

`_self_correct_retry` 消费 `result_dict["error_code"]`（由 `_execute_tool_safe` 从
`ToolResult.error_code` 带出，后者由 `admin_api_failure` 从 admin-api 响应填充），
命中 `NON_RETRYABLE_ERROR_CODES` ⇒ **不重试**，把失败与 suggestion 原样交回模型决策，
并留日志 `non-retryable: retry suppressed`。

## fail-safe 语义（显式声明，不允许静默滑向任何一极）

`error_code` **缺失/为空 ⇒ 视为可重试**（= 既有行为不变）。理由：

- 缺码的失败面很宽（超时 / 异常兜底 / 上游未启用 `admin_api_failure` 的老路径），
  把它们一律判成「不可重试」等于**关掉既有自修复能力**（#3564 的教训：护栏只能
  收窄被点名的那一类，不得顺手扩大）；
- 授权拒绝**一定有码**（`admin_api_failure` 在授权分支无条件填 `error_code`，
  admin-api 侧 `PERMISSION_DENIED`/`FORBIDDEN`/`AUTH_*`/`UNAUTHORIZED` 都是显式字面量），
  所以「缺码」不构成对授权拒绝的漏判；
- 该语义由 `TestFailSafeSemantics` 逐条锁住，改判即红。

## 本文件锁的不变式（每条都有反例输入）

1. `TestNonRetryableDenialIsNotRetried` —— 授权码 ⇒ 零重放、不调 `suggestion_llm`、
   失败与 suggestion 原样交回；
2. `TestRetryableFailuresStillRetry` —— 其它码 / 缺码 / 幂等写工具**照旧重试**
   （既有能力不得被顺带关闭）；
3. `TestExecuteToolSafeCarriesTheCode` —— `_execute_tool_safe` 的五条出口都带
   `error_code`（判据名字**单点对齐**，不靠两处各写一份）；
4. `TestFieldNameIsSingleSourced` —— 静态锁：出口字典键名 == 重试闸门读的键名 ==
   `ToolResult` 声明字段名；任一处改名即红（照 `#4057 T4` 的形态）。
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.graph.skills.base_skill import _execute_tool_safe, _self_correct_retry
from app.tools.base import (
    NON_RETRYABLE_ERROR_CODES,
    BaseTool,
    ToolContext,
    ToolResult,
)

SERVICE_DIR = Path(__file__).resolve().parents[1]
BASE_SKILL = SERVICE_DIR / "app" / "graph" / "skills" / "base_skill.py"

FIELD = "error_code"


@pytest.fixture(autouse=True)
def _clear_read_only_tool_cache():
    """清空 `_execute_tool_safe` 的**只读工具缓存**（跨用例污染的已知形态）。

    替身工具同名、参数相同（`{"name": ""}` → 修正后 `{"name": "..."}`），
    上一条用例缓存下来的**成功结果**会让下一条用例「不执行就成功」：
    `tool.calls == []` 于是变成假绿/假红（实测：单跑通过、同文件连跑失败）。
    """
    _execute_tool_safe._cache = {}
    _execute_tool_safe._cache_lock = asyncio.Lock()
    yield
    _execute_tool_safe._cache = {}


# ── 替身 ────────────────────────────────────────────────────────────────────

class _CodedFailureTool(BaseTool):
    """幂等只读工具替身：按构造时给定的 `error_code` 失败，修正参数后成功。

    只读 + 幂等 ⇒ 除「授权码闸门」外没有任何理由抑制重试 ⇒ 结论只可能来自本单的护栏。
    """

    name = "fake_coded_failure"
    description = "授权码重试护栏替身"
    read_only = True
    idempotent = True
    parameters = {"type": "object", "properties": {"name": {"type": "string"}}}

    def __init__(self, error_code):
        super().__init__()
        self.error_code = error_code
        self.calls: list[dict] = []

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        self.calls.append(dict(kwargs))
        if not kwargs.get("name"):
            return ToolResult(
                success=False,
                error="权限不足" if self.error_code in NON_RETRYABLE_ERROR_CODES else "查不到",
                message="失败",
                suggestion="这是权限限制（不是参数问题）：请不要重试。",
                error_code=self.error_code,
            )
        return ToolResult(success=True, data={"ok": True}, message="成功")


class _FakeLLM:
    """`suggestion_llm` 替身：返回一组"修正后的参数"JSON（记录是否被调用）。"""

    def __init__(self, payload: dict):
        self.temperature = 0.0
        self._payload = payload
        self.invoked: list[str] = []

    async def ainvoke(self, messages):
        self.invoked.append(messages[0].content if messages else "")
        return MagicMock(content=json.dumps(self._payload, ensure_ascii=False))


_CTX = ToolContext(tenant_id=999, user_id="u-retry", session_id="s-retry", role="operator",
                   permissions=["order:list"])
_STATE = {"session_id": "s-retry", "tenant_id": 999}


async def _retry(tool, result_dict: dict) -> tuple:
    """复刻调用点语义（`base_skill` 的 `if corrected: result_str, result_dict = corrected`）。

    Returns:
        (outcome, effective)：outcome = `_self_correct_retry` 原返回值（None = 未重试）；
        effective = **模型最终看到的工具结果 dict**（断言以业务口径为准）。
    """
    original = dict(result_dict)
    outcome = await _self_correct_retry(
        tool, {"name": ""}, _CTX, "test_skill", dict(original), "s-retry", 999, dict(_STATE),
    )
    return outcome, (outcome[1] if outcome else original)


# ──────────────────────────────────────────────────────────────────────────────
# ① 授权类失败：零重放
# ──────────────────────────────────────────────────────────────────────────────

class TestNonRetryableDenialIsNotRetried:
    """授权码 ⇒ 不重试（重试拿同一身份再调一次永远不可能成功）。"""

    async def test_permission_denied_is_not_retried(self):
        tool = _CodedFailureTool("PERMISSION_DENIED")
        llm = _FakeLLM({"name": "修正后的名字"})
        with patch(
            "app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
            return_value=llm,
        ) as factory:
            _, effective = await _retry(tool, {
                "success": False, "error": "权限不足", "message": "失败",
                "suggestion": "这是权限限制，请不要重试。", "error_code": "PERMISSION_DENIED",
            })

        assert factory.call_count == 0, "权限拒绝不得触发 suggestion_llm（重试入口必须关闭）"
        assert llm.invoked == [], "权限拒绝不得调用修正 LLM（否则会把拒绝改写成参数问题）"
        assert tool.calls == [], f"权限拒绝不得被重放（实际 {tool.calls!r}）"
        assert effective["success"] is False, "模型必须收到原样的失败"
        assert effective["suggestion"] == "这是权限限制，请不要重试。", "suggestion 必须原样交回"
        assert effective["error_code"] == "PERMISSION_DENIED", "错误码必须保留给下游"

    async def test_every_non_retryable_code_is_suppressed(self):
        for code in sorted(NON_RETRYABLE_ERROR_CODES):
            tool = _CodedFailureTool(code)
            with patch(
                "app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
                return_value=_FakeLLM({"name": "x"}),
            ) as factory:
                _, effective = await _retry(tool, {
                    "success": False, "error": "拒绝", "message": "失败",
                    "suggestion": "请不要重试", "error_code": code,
                })
            assert factory.call_count == 0, f"{code}: 授权类失败不得触发重试"
            assert tool.calls == [], f"{code}: 授权类失败不得被重放"
            assert effective["success"] is False

    async def test_non_idempotent_denial_is_also_suppressed(self):
        """非幂等 + 授权码：两条护栏都不放行（且不因顺序不同而漏判）。"""
        tool = _CodedFailureTool("FORBIDDEN")
        tool.idempotent = False
        with patch(
            "app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
            return_value=_FakeLLM({"name": "x"}),
        ) as factory:
            await _retry(tool, {
                "success": False, "error": "拒绝", "message": "失败",
                "suggestion": "请不要重试", "error_code": "FORBIDDEN",
            })
        assert factory.call_count == 0
        assert tool.calls == []


# ──────────────────────────────────────────────────────────────────────────────
# ② 防回归：可重试失败必须照旧重试（红证的另一半）
# ──────────────────────────────────────────────────────────────────────────────

class TestRetryableFailuresStillRetry:
    """**:red_circle: 判别性红证** —— 同一替身换成可重试码/缺码就必须重试。

    这两条同时证明「闸门是按 `error_code` 判的」而不是「一律不重试」：
    若把 `NON_RETRYABLE_ERROR_CODES` 判据删掉，`TestNonRetryableDenialIsNotRetried`
    会红；若把判据写成恒真（一律抑制），本类会红。
    """

    async def test_retryable_code_still_retries(self):
        tool = _CodedFailureTool("NOT_FOUND")
        llm = _FakeLLM({"name": "修正后的名字"})
        with patch(
            "app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
            return_value=llm,
        ) as factory:
            outcome, effective = await _retry(tool, {
                "success": False, "error": "查不到", "message": "失败",
                "suggestion": "请改用 product_search 查询后重试", "error_code": "NOT_FOUND",
            })

        assert factory.call_count == 1, "可重试失败（NOT_FOUND）的既有自修复能力不得被关闭"
        assert tool.calls == [{"name": "修正后的名字"}], "应带修正参数重试一次"
        assert effective["success"] is True, "修正成功应把成功结果交回模型"
        assert json.loads(outcome[0])["data"] == {"ok": True}

    async def test_missing_error_code_still_retries(self):
        """**fail-safe 显式语义**：缺码 ⇒ 可重试（既有行为不变，见文件头）。"""
        tool = _CodedFailureTool(None)
        llm = _FakeLLM({"name": "修正后的名字"})
        with patch(
            "app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
            return_value=llm,
        ) as factory:
            _, effective = await _retry(tool, {
                "success": False, "error": "查不到", "message": "失败",
                "suggestion": "请检查参数后重试",
            })
        assert factory.call_count == 1, "缺 error_code 必须维持既有重试行为（不得默认抑制）"
        assert tool.calls == [{"name": "修正后的名字"}]
        assert effective["success"] is True

    async def test_empty_and_none_codes_are_treated_alike(self):
        tool = _CodedFailureTool(None)
        for empty in ("", None):
            with patch(
                "app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
                return_value=_FakeLLM({"name": "修正后的名字"}),
            ) as factory:
                await _retry(tool, {
                    "success": False, "error": "查不到", "message": "失败",
                    "suggestion": "请检查参数后重试", "error_code": empty,
                })
            assert factory.call_count == 1, f"error_code={empty!r} 必须与缺码等价（可重试）"
            tool.calls.clear()

    async def test_no_suggestion_still_no_retry(self):
        """既有语义不变：无 suggestion 时不重试。"""
        tool = _CodedFailureTool("NOT_FOUND")
        _, effective = await _retry(tool, {"success": False, "message": "失败"})
        assert tool.calls == []
        assert effective["success"] is False


# ──────────────────────────────────────────────────────────────────────────────
# ③ 出口必须带码（否则闸门永远读不到）
# ──────────────────────────────────────────────────────────────────────────────

class TestExecuteToolSafeCarriesTheCode:
    """`_execute_tool_safe` 的出口字典必须带 `error_code`（五条出口共用同一构造点）。"""

    async def test_success_exit_carries_the_field(self):
        tool = _CodedFailureTool("NOT_FOUND")
        _, result_dict = await _execute_tool_safe(
            tool, {"name": "ok"}, _CTX, dict(_STATE),
        )
        assert FIELD in result_dict, "成功出口也必须带该字段（出口字典单点构造，缺键即契约漂移）"

    async def test_failure_exit_carries_the_denial_code(self):
        tool = _CodedFailureTool("PERMISSION_DENIED")
        _, result_dict = await _execute_tool_safe(
            tool, {"name": ""}, _CTX, dict(_STATE),
        )
        assert result_dict["success"] is False
        assert result_dict[FIELD] == "PERMISSION_DENIED", (
            "工具层的 error_code 必须经出口传给重试闸门（否则 F5 护栏恒不触发）"
        )

    async def test_exception_exit_carries_the_field_too(self):
        """异常出口（无响应可映射）同样带键：值为空 = 可重试（fail-safe 语义可见）。"""
        class _BoomTool(_CodedFailureTool):
            name = "fake_boom"

            async def execute(self, context, **kwargs):
                raise RuntimeError("boom")

        _, result_dict = await _execute_tool_safe(_BoomTool(None), {}, _CTX, dict(_STATE))
        assert result_dict["success"] is False
        assert FIELD in result_dict, "异常出口缺键会让消费点 `result_dict.get(...)` 与缺省值同形"


# ──────────────────────────────────────────────────────────────────────────────
# ④ 静态锁：字段名单点对齐（防 #4057 T4 那类「两处各写一份」漂移）
# ──────────────────────────────────────────────────────────────────────────────

def _exit_dict_keys(tree: ast.AST) -> list[str]:
    """`_execute_tool_safe` 里**出口字典字面量**的键（形如 `"key": value,` 的赋值语句）。"""
    keys: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if targets != ["result_dict"] or not isinstance(node.value, ast.Dict):
            continue
        keys.extend(
            k.value for k in node.value.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        )
    return sorted(set(keys))


def _gate_reads_key(tree: ast.AST) -> list[str]:
    """`_self_correct_retry` 里对 `result_dict` 的字符串键读取（`.get("x")` / `["x"]`）。"""
    keys: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "get" and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id == "result_dict" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    keys.append(arg.value)
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                and node.value.id == "result_dict":
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                keys.append(sl.value)
    return sorted(set(keys))


class TestFieldNameIsSingleSourced:
    """静态锁：`ToolResult` 声明字段 / 出口字典键 / 重试闸门读取键，三处必须同名。"""

    def test_retry_gate_reads_a_declared_and_exported_field(self):
        tree = ast.parse(BASE_SKILL.read_text(encoding="utf-8"))
        assert FIELD in _exit_dict_keys(tree), (
            f"`_execute_tool_safe` 的出口字典没有 `{FIELD}` 键 ⇒ 消费点恒 None（#4057 T4 形态）"
        )
        assert FIELD in _gate_reads_key(tree), (
            f"`_self_correct_retry` 没有读 `result_dict[{FIELD!r}]` ⇒ F5 护栏形同不存在"
        )
        assert FIELD in ToolResult.model_fields, (
            f"`ToolResult` 未声明 `{FIELD}` —— 三处名字必须单点对齐"
        )

    def test_the_lock_can_go_red_on_a_renamed_key(self, tmp_path):
        """**红证**：把出口键改名（其余不动）⇒ 判据必须报出。"""
        fixture = tmp_path / "fixture_renamed.py"
        fixture.write_text(
            "def _execute_tool_safe():\n"
            "    result_dict = {\"success\": False, \"error_code_typo\": None}\n"
            "    return result_dict\n",
            encoding="utf-8",
        )
        tree = ast.parse(fixture.read_text(encoding="utf-8"))
        keys = _exit_dict_keys(tree)
        assert "error_code" not in keys, "改名后的键没被抓出（判据是空的）"
        assert keys == ["error_code_typo", "success"]

    def test_the_gate_detector_is_not_vacuous(self, tmp_path):
        """**红证**：闸门不读该键时判据必须报出。"""
        fixture = tmp_path / "fixture_gate.py"
        fixture.write_text(
            "def _self_correct_retry(result_dict):\n"
            "    return result_dict.get('message')\n",
            encoding="utf-8",
        )
        tree = ast.parse(fixture.read_text(encoding="utf-8"))
        assert _gate_reads_key(tree) == ["message"]
        assert FIELD not in _gate_reads_key(tree), "判据没在看闸门读什么键"