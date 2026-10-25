# case_ids: PR-074
"""工具执行预算：慢工具（生图）单独放宽，不再被写死的 30s 截断（issue #7707）。

病灶（2026-10-25 实测）：`_execute_tool_safe` 里 `asyncio.wait_for(..., timeout=30.0)` 是**写死**的，
而 `product_image_generate` 是**慢工具**（成功路径实测 30~60s）：

    PR-074 trace: failed=product_image_generate!timeout  （wall_clock=37.3s，单条 36.1s）

后果比"慢"更糟 —— 超时出口的 `error="timeout"` 与「模型不接这类请求」在读数上不可区分，
归因被指向错误的层（这正是 #7707 的环境：内核读超时 `IMAGE_GEN_TIMEOUT=180s` 根本没被触发）。

判据（本文件）：
1. **默认值**：没被点名覆盖的工具用全局 `TOOL_TIMEOUT_S`；
2. **按名覆盖**：`TOOL_TIMEOUT_OVERRIDES="product_image_generate=120"` ⇒ 生图 120s、其它工具不受影响；
3. **坏条目只影响它自己**：`foo=bar` 这类解析不了的条目**忽略**，不能让工具全挂；
4. **非正值不生效**：`x=0` / `x=-5` 退回默认（预算是安全护栏，不能被配置成"立刻超时"）；
5. **调用点真的用了它**：AST 检查 `_execute_tool_safe` 里那次 `asyncio.wait_for` 的
   `timeout=` 是 `tool_timeout_s(tool_name)`，且该函数内不再有字面量 `timeout=30.0`
   —— 否则本文件的 1~4 全绿而线上仍被 30s 截断（"测了函数没接线"）。
"""

import ast
from pathlib import Path

import pytest

from app.config import settings
from app.graph.skills.base_skill import tool_timeout_s

BASE_SKILL = Path(__file__).resolve().parents[1] / "app/graph/skills/base_skill.py"


@pytest.fixture
def budget(monkeypatch):
    """把预算配置换成受控值（不读运行环境的 .env）。"""

    def _set(default: float = 30.0, overrides: str = "") -> None:
        monkeypatch.setattr(settings, "TOOL_TIMEOUT_S", default, raising=False)
        monkeypatch.setattr(settings, "TOOL_TIMEOUT_OVERRIDES", overrides, raising=False)

    _set()
    return _set


# ── 1. 默认值 ────────────────────────────────────────────────────────────────
def test_unnamed_tool_uses_global_default(budget):
    budget(default=30.0, overrides="product_image_generate=120")
    assert tool_timeout_s("product_search") == 30.0


def test_default_from_settings_is_respected(budget):
    budget(default=45.0, overrides="")
    assert tool_timeout_s("anything") == 45.0


# ── 2. 按名覆盖 ──────────────────────────────────────────────────────────────
def test_slow_tool_override_applies_to_named_tool_only(budget):
    budget(default=30.0, overrides="product_image_generate=120")
    assert tool_timeout_s("product_image_generate") == 120.0
    assert tool_timeout_s("product_search") == 30.0


def test_repo_default_config_widens_the_image_tool():
    """仓库默认配置必须真的放宽生图（不是靠部署时记得改 env）。"""
    assert "product_image_generate=" in settings.TOOL_TIMEOUT_OVERRIDES
    assert tool_timeout_s("product_image_generate") > settings.TOOL_TIMEOUT_S


def test_multiple_overrides_are_parsed_independently(budget):
    budget(default=20.0, overrides="a=5,b=7")
    assert tool_timeout_s("a") == 5.0
    assert tool_timeout_s("b") == 7.0
    assert tool_timeout_s("c") == 20.0


# ── 3/4. 坏条目与非正值 ──────────────────────────────────────────────────────
def test_malformed_entry_is_ignored_without_killing_others(budget):
    budget(default=30.0, overrides="foo=bar,product_image_generate=120")
    assert tool_timeout_s("foo") == 30.0          # 坏条目 ⇒ 退回默认
    assert tool_timeout_s("product_image_generate") == 120.0  # 其它条目照常生效


def test_non_positive_override_falls_back_to_default(budget):
    budget(default=30.0, overrides="product_image_generate=0")
    assert tool_timeout_s("product_image_generate") == 30.0
    budget(default=30.0, overrides="product_image_generate=-5")
    assert tool_timeout_s("product_image_generate") == 30.0


# ── 5. 调用点真的用了它（接线判据）────────────────────────────────────────────
def _execute_tool_safe_ast():
    tree = ast.parse(BASE_SKILL.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        # 它是 `async def`（Ast = AsyncFunctionDef），两种都认，免得判据因写法漂移而空转
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_execute_tool_safe":
            return node
    raise AssertionError("base_skill.py 里找不到 _execute_tool_safe")


def _wait_for_timeout_kwarg(func) -> ast.expr:
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        fname = getattr(node.func, "attr", getattr(node.func, "id", ""))
        if fname != "wait_for":
            continue
        for kw in node.keywords:
            if kw.arg == "timeout":
                return kw.value
    raise AssertionError("_execute_tool_safe 里找不到 asyncio.wait_for(..., timeout=...)")


def test_call_site_passes_per_tool_budget():
    value = _wait_for_timeout_kwarg(_execute_tool_safe_ast())
    assert isinstance(value, ast.Call), f"timeout 必须是函数调用，实际是 {ast.dump(value)[:80]}"
    assert getattr(value.func, "id", "") == "tool_timeout_s"
    assert [a.id for a in value.args if isinstance(a, ast.Name)] == ["tool_name"]


def test_call_site_has_no_hardcoded_budget():
    """字面量预算只要还在，就说明有一处调用绕过了按工具预算。"""
    func = _execute_tool_safe_ast()
    literals = [
        n.value
        for n in ast.walk(func)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
        and n.value in (30, 30.0)
    ]
    assert literals == [], f"_execute_tool_safe 里仍有字面量预算：{literals}"
