# case_ids: CH-043
"""CH-043 的计分断言**真的**钉住了 `fabric_widths` —— 用例面 + 渲染面 + 判据面三层红证（issue #5039）。

## 为什么需要本文件

`migao-acceptance` 铁律 2：「关键行为禁止只写进自然语义 `data_checks`，**每条断言都要有红证**
（不会红的断言 = 空断言）」。CH-043 要钉的是「**模型**读 `product_detail` 的 SKU 列表、
把门幅**去重**、填进 `curtain_calc.fabric_widths`」这一**纯 LLM 行为** ——
它的可执行性**完全依赖**两段别人的实现，任一处漂移都会让这条断言**静默变味**：

| 环节 | 实现 | 漂移后的形态（都是"看着还在、其实没测"） |
|---|---|---|
| 渲染 | `.github/render_cases.py` 的 `exp_to_str`（list ⇒ `k=[a, b]`） | 渲染成字符串 `fabric_widths=[2.8, 3.2]`（带引号）⇒ 值级比较**恒假** = **恒红空断言** |
| 判据 | `tests/agent_eval/local_runner.py` 的 `_arg_mismatch_reason`（期望是标量列表 ⇒ **子集**语义） | 改成"相等"⇒ 模型多传一个门幅就**假红**；改成"只要键在"⇒ 模型填 `[2.8]` 也算过 = **假绿** |

## 判据（三条，各自可单独变红）

| # | 判据 | 怎么让它单独红 |
|---|---|---|
| a | **用例面**：`.github/cases/chat.yml` 的 CH-043 计分断言里有 `fabric_widths`，且值 ⊇ {2.8, 3.2} | 删掉该键 / 只留 2.8 ⇒ 红 |
| b | **渲染面**：`render_cases.to_eval_py` 产出里含 `curtain_calc(fabric_widths=[2.8, 3.2])`，且该串经 runner 的 `_parse_expectation` 解析回**两个元素**的列表 | 把 `exp_to_str` 的 list 分支改成 `str(v)` ⇒ 红 |
| c | **判据面（红证）**：喂**负向轨迹**给 runner 的 `check_expectation` ⇒ 必判红；喂**正向轨迹** ⇒ 必判绿 | 把子集语义改成"只要键在"⇒「只填 [2.8]」那条红证失败 |

没有 c，a/b 只证明「文字写对了」，**不证明这条断言真会红** —— 那正是本仓库反复踩的
「看起来有覆盖」（`migao-acceptance` 假绿/假红节）。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"
sys.path.insert(0, str(REPO_ROOT / ".github"))          # render_cases / yaml_light
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

CASE_ID = "CH-043"
#: 本用例的题眼：候选门幅集（种子 `prod_eval_summer` 米白色散剪 SKU 的两种门幅）。
WANT_WIDTHS = {"2.8", "3.2"}
#: 渲染面期望的**字面形态**（键 + 列表；不是带引号的字符串）。
WANT_LITERAL = "curtain_calc(fabric_widths=[2.8, 3.2])"


def _load_runner():
    """导入 `local_runner`（L0 job 只装 pytest+pyyaml ⇒ 缺 httpx 时注入最小替身）。

    被锁的是**纯函数**（期望解析 / args 值级比对），不该因缺一个 HTTP 客户端而不可测。
    """
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()


def _case(case_id: str = CASE_ID) -> dict:
    from render_cases import load_case_dicts
    by_id = {c["id"]: c for c in load_case_dicts(str(CASES_DIR))}
    assert case_id in by_id, f"用例 {case_id} 不在 .github/cases/ 里（本文件锁的就是它）"
    return by_id[case_id]


def _result(calls: list[tuple[str, dict]]) -> dict:
    """最小轨迹替身：只要 `tool_calls` / `__all_tool_names`（`check_expectation` 的读面）。"""
    return {
        "tool_calls": [{"name": n, "args": a} for n, a in calls],
        "__all_tool_names": [n for n, _ in calls],
        "tool_results": [],
        "interactive": [],
        "final_text": "",
    }


# ── a. 用例面：计分断言真的断言了 fabric_widths ────────────────────────────────

class TestCaseAssertsFabricWidths:
    def test_expectation_declares_candidate_width_set(self):
        """`expectations[].args.fabric_widths` 必须在，且覆盖两个门幅。

        这是 CH-043 的**唯一**计分载体（`data_checks` 是散文、不计分）——
        删掉这个键，本用例就退化成「调过 curtain_calc 就算过」，
        而本单要覆盖的「模型会不会填候选集」重新变成裸奔。
        """
        exp = [e for e in (_case().get("expectations") or [])
               if isinstance(e, dict) and e.get("tool") == "curtain_calc"]
        assert exp, "CH-043 的计分断言里没有 curtain_calc 期望（题眼载体消失）"
        args = exp[0].get("args") or {}
        assert "fabric_widths" in args, (
            "CH-043 的 curtain_calc 期望缺 `fabric_widths` 参数 —— 本单的题眼（模型填候选集）"
            "失去计分载体，用例退化成「调过就算过」")
        got = {str(x) for x in args["fabric_widths"]}
        assert got == WANT_WIDTHS, (
            f"CH-043 期望的候选门幅集 = {sorted(got)}，与种子接地对象不一致"
            f"（应为 {sorted(WANT_WIDTHS)}；改了种子 SKU 门幅就必须同步改本行，"
            f"否则断言恒红 = 空断言）")

    def test_case_is_single_leg_xiaobu(self):
        """端别：`curtain_calc` 是小布专属 ⇒ 必须标 `persona: xiaobu`（否则米宝腿必挂）。"""
        assert _case().get("persona") == "xiaobu", (
            "CH-043 断言的是小布专属工具 curtain_calc ⇒ 必须 persona: xiaobu"
            "（并同步 tests/unit_ci_workflows/test_persona_filter.py 的 XIAOBU_ONLY）")


# ── b. 渲染面：list 必须渲染成 list 字面量，且能解析回列表 ─────────────────────

class TestRenderedExpectationShape:
    def test_renderer_emits_list_literal(self):
        """`render_cases.to_eval_py` 必须把列表渲染成 `k=[a, b]`（不是字符串）。"""
        from render_cases import to_eval_py
        out = to_eval_py([_case()])
        assert WANT_LITERAL in out, (
            f"生成物里没有 {WANT_LITERAL!r} —— 渲染器把 list 渲染成了别的形态"
            f"（字符串形态会让值级比较恒假 = 恒红空断言）")

    def test_live_case_round_trips_renderer_then_parser(self):
        """**闭环**：用例 YAML 的期望 → `exp_to_str` 渲染 → `_parse_expectation` 解析回列表。

        两侧任一漂移都会在这里红（渲染成带引号的字符串 / 解析退化成标量），
        而两者恰好是 CH-043 那条断言可执行性的**全部**依赖。
        """
        from render_cases import exp_to_str
        exp = next(e for e in (_case().get("expectations") or [])
                   if isinstance(e, dict) and e.get("tool") == "curtain_calc")
        rendered = exp_to_str(exp)
        assert rendered == WANT_LITERAL, (
            f"渲染结果 = {rendered!r}，期望 {WANT_LITERAL!r}（渲染器把 list 渲染成了别的形态）")
        tool, args = lr._parse_expectation(rendered)
        assert tool == "curtain_calc"
        assert isinstance(args.get("fabric_widths"), list), (
            f"期望串解析出的 fabric_widths 不是列表：{args.get('fabric_widths')!r} —— "
            f"runner 会走标量分支，『长度 ≥ 2』的语义随之丢失")
        assert {str(x) for x in args["fabric_widths"]} == WANT_WIDTHS, (
            f"解析出的门幅集 = {args['fabric_widths']!r}，与用例声明不一致")


# ── c. 判据面：负向轨迹必红 / 正向轨迹必绿（**这条才是红证**）────────────────────

class TestScoringIsLoadBearing:
    """`check_expectation` 对 CH-043 那条期望串的真实判定（零 LLM、零 docker）。"""

    def test_positive_trace_passes(self):
        """正向：模型填了去重后的两个门幅 ⇒ 必须**绿**（否则是恒红空断言）。"""
        ok, detail = lr.check_expectation(
            _result([("curtain_calc", {"window_width": 3, "window_height": 2.7,
                                       "fabric_widths": [2.8, 3.2]})]),
            WANT_LITERAL)
        assert ok is True, f"正向轨迹被判红（期望/判据对不上）：{detail}"

    def test_positive_trace_with_string_widths_passes(self):
        """正向（字符串形态）：LLM 常把门幅写成字符串 ⇒ 不得因此假红。"""
        ok, detail = lr.check_expectation(
            _result([("curtain_calc", {"fabric_widths": ["2.8", "3.2"]})]),
            WANT_LITERAL)
        assert ok is True, f"字符串门幅被判红（假红面）：{detail}"

    def test_single_width_is_red(self):
        """负向①：模型**没去重**（只填了 2.8）⇒ 必红。这是本用例真正要咬住的行为。"""
        ok, detail = lr.check_expectation(
            _result([("curtain_calc", {"fabric_widths": [2.8]})]),
            WANT_LITERAL)
        assert ok is False, (
            "只填一个门幅（未去重）竟然判绿 —— 『长度 ≥ 2 / 两个门幅都在』的语义已丢失")
        assert "3.2" in detail, f"失败详情没指出缺哪个门幅（归因不辨）：{detail}"

    def test_missing_key_is_red(self):
        """负向②：模型压根没填 `fabric_widths`（#5016 前的老行为）⇒ 必红。"""
        ok, detail = lr.check_expectation(
            _result([("curtain_calc", {"window_width": 3, "window_height": 2.7,
                                       "fabric_width": 2.8})]),
            WANT_LITERAL)
        assert ok is False, "没填 fabric_widths 竟然判绿 —— 键存在性断言失效"
        assert "fabric_widths" in detail, f"失败详情没指名缺哪个键：{detail}"

    def test_no_call_at_all_is_red(self):
        """负向③：agent 全程未调 `curtain_calc`（历史实证过的形态）⇒ 必红。"""
        ok, detail = lr.check_expectation(_result([]), WANT_LITERAL)
        assert ok is False, "压根没调工具竟然判绿 —— 期望没被计入评分"
        assert "unmatched expectation" in detail, f"失败形态不是「未命中期望」：{detail}"


if __name__ == "__main__":                    # pragma: no cover - 便于本地直接跑
    raise SystemExit(pytest.main([__file__, "-q"]))
