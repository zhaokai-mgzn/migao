# case_ids: OR-010, OR-015, PG-013
"""缺陷一红证：`unfailable_green` 标记 B 端漏标 2 条（实现不一致）。

盲审出处（判定跑 `34923425338`，mibao 腿 summary，`@7d930e34`）：`OR-015` /
`PG-013` 通过、`assertions_fired` profile 与已标记的 `OR-010` **逐字段相同**
（scoring 全 `failable=false`、四个 effect_layers 全 false），却没被标
`unfailable_green` ⇒ 标记逻辑实现不一致（同 profile 不同结果）。

根因：`_unfailable_green` 有一个**独立于 profile 的输入** `has_order_before`
（= 用例是否声明 `order_before` 时序断言）—— OR-015 / PG-013 都声明了
`order_before`（`.github/cases/order.yml` OR-015、`processing-order.yml` PG-013），
命中 `if has_order_before: return False` 分支 ⇒ 漏标；而 `order_before` **不进**
`assertions_fired` profile ⇒ 三个用例 profile 逐字段相同却得到不同标记。

修法（判据「同 profile 必同标记」）：标记**只读 profile**（scoring 可失败性 +
效果层触发），`order_before` 不再阻断标记。`has_order_before` 参数保留仅为
直陈该漏标机制（红证夹具按真实用例构造、显式传 `True`），判据已不读它。
（taxonomy 把 `order_before` 判为行为层，服务的是 `forbidden_text` 禁令规则
「不得单独承载」那个问题，与本标记是两回事。）

红证：
- 改前：三例同 profile 夹具（OR-015/PG-013 带 order_before）⇒ OR-015/PG-013
  `_unfailable_green` 返回 False（漏标，红）；
- 改后：三者一致返回 True（标出，绿）；
- 反向：真 failable（带 args 计分断言 / 效果层触发 / score<1.0）不得误标。
"""
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身，单测不得真实 HTTP）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()


# ── 三例同 profile 夹具（照判定跑 34923425338 的 artifact 真实形态构造）──────────

def _case(**effect):
    from types import SimpleNamespace
    defaults = {"must_succeed": [], "db_verify": [], "amount_verify": [],
                "output_verify": [], "order_before": []}
    defaults.update(effect)
    return SimpleNamespace(**defaults)


def _round(tool):
    return {"tool_calls": [{"name": tool, "args": {}}],
            "__all_tool_names": [tool], "final_text": "ok"}


def _profile(scoring_checks, round_tool, order_before=None):
    """真实路径构造 assertions_fired（与 `_run_one_case` 同一条调用链）。"""
    case = _case(order_before=order_before or [])
    af = lr._assertions_fired_summary(case, scoring_checks, [_round(round_tool)], 1.0)
    assert not any(c["failable"] for c in af["scoring"]), af
    assert not any(af["effect_layers"].values()), af
    return af


# OR-010 / OR-015 / PG-013 的**真实**计分断言（裸工具名，全部 failable=false）
OR010_CHECKS = ["validate_input", "order_create"]
OR015_CHECKS = ["validate_input", "order_create"]
PG013_CHECKS = ["order_query", "processing_order_generate"]


def _legacy_unfailable_green(score, scoring_checks, assertions_fired, has_order_before):
    """**改造前** `_unfailable_green`（独立复写，红证用 —— 不复用新实现，否则
    两边同源、红证失效；同 test_eval_verdict_trust 的 `_legacy_pass_bucket` 范式）。
    旧判据多了一条「无跨轮行为层（order_before）」分支 ⇒ 声明 order_before 的用例
    即便 profile 与 OR-010 逐字段相同也返回 False（漏标）。
    """
    if score < 1.0:
        return False
    if any(lr._scoring_check_is_failable(c) for c in scoring_checks):
        return False
    if any((assertions_fired.get("effect_layers") or {}).values()):
        return False
    if has_order_before:
        return False
    return True


class TestUnfailableGreenSameProfileSameMark:
    def test_legacy_red_misses_order_before_cases(self):
        """**改前红证**：旧逻辑对三例同 profile 给不同标记 —— OR-015/PG-013
        （带 order_before）漏标，正是盲审在 34923425338 里看到的形态。"""
        af_or010 = _profile(OR010_CHECKS, "validate_input")
        af_or015 = _profile(OR015_CHECKS, "validate_input")
        af_pg013 = _profile(PG013_CHECKS, "order_query")
        assert _legacy_unfailable_green(1.0, OR010_CHECKS, af_or010, False) is True
        assert _legacy_unfailable_green(1.0, OR015_CHECKS, af_or015, True) is False, (
            "旧逻辑漏标 OR-015（order_before 分支）—— 红证夹具没构造出漏标形态")
        assert _legacy_unfailable_green(1.0, PG013_CHECKS, af_pg013, True) is False, (
            "旧逻辑漏标 PG-013（order_before 分支）—— 红证夹具没构造出漏标形态")
        # 三例 profile 逐字段相同是前提（与盲审证据一致）
        assert af_or010["scoring"] == af_or015["scoring"]
        assert af_or010["effect_layers"] == af_or015["effect_layers"] == af_pg013["effect_layers"]

    def test_same_profile_all_three_marked(self):
        """**改后**：同 profile 必同标记 —— OR-010/OR-015/PG-013 三者一致标出
        （改前该断言红：OR-015/PG-013 返回 False = 漏标）。"""
        af_or010 = _profile(OR010_CHECKS, "validate_input")
        af_or015 = _profile(OR015_CHECKS, "validate_input")
        af_pg013 = _profile(PG013_CHECKS, "order_query")
        assert lr._unfailable_green(1.0, OR010_CHECKS, af_or010, False) is True
        assert lr._unfailable_green(1.0, OR015_CHECKS, af_or015, True) is True, (
            "OR-015 与 OR-010 同 profile 却未标 unfailable_green（漏标，34923425338 实证）")
        assert lr._unfailable_green(1.0, PG013_CHECKS, af_pg013, True) is True, (
            "PG-013 与 OR-010 同 profile 却未标 unfailable_green（漏标，34923425338 实证）")

    def test_reverse_truly_failable_not_marked(self):
        """反向：真 failable 的用例不得误标（判据其余三分支原样保留）。"""
        af = _profile([], "order_query")
        # ① 带 args 的计分断言（参数值校验，可证伪）—— 直接构造 af（该 check 本就 failable）
        af_failable = lr._assertions_fired_summary(
            _case(), ["after_sales_manage(action=list)"], [_round("order_query")], 1.0)
        assert af_failable["scoring"][0]["failable"] is True
        assert lr._unfailable_green(
            1.0, ["after_sales_manage(action=list)"], af_failable, True) is False
        # ② 效果层真触发（amount_verify）
        case = _case(amount_verify=[{"tool": "order_create", "checks": []}])
        af_effect = lr._assertions_fired_summary(case, [], [_round("order_create")], 1.0)
        assert af_effect["effect_layers"]["amount_verify"] is True
        assert lr._unfailable_green(1.0, [], af_effect, True) is False
        # ③ 失败用例（score<1.0）永不标
        assert lr._unfailable_green(0.0, [], af, True) is False
