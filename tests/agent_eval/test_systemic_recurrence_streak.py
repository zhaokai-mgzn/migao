# case_ids: PP-015, PR-108
"""连续未绿出声判据（issue #7327，用户 2026-10-19 裁定 **N=3**）。

判据分两个问，不能混：
  · `cross_run_recurrence` 问「这个指纹**出现过**吗」（≥2 次即复发，不按波动放行）；
  · 本套件问「它**连续**几次没绿」—— 中间通过一次就清零，达到 `SYSTEMIC_RECURRENCE_MIN_STREAK`
    才**主动出声**（`systemic=True` + `::warning`）。

为什么必须测「通过清零」：索引原本只记「失败出现过」，于是「失败/失败/通过/失败/失败」
会被数成 4 次连续未绿 —— 那正是不存在的东西。判据的失败模式不是"不响"，而是**乱响**。
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "agent_eval"))

import local_runner as R  # noqa: E402


def _entry(case_id="PP-015", fp="no_success(craft_calc_config_query)"):
    # ⚠️ 复发键 = `(case_id, first_attempt_signature)`（见 `flake_fingerprint_key`）；
    # 只写 `signature` 会得到空键 ⇒ 判据恒不命中（假绿），本套件因此两个键都写。
    return {"case_id": case_id, "signature": fp, "first_attempt_signature": fp,
            "classification": "reproducible", "released": False}


def _hist(*runs, case_id="PP-015", fp="no_success(craft_calc_config_query)"):
    return {case_id: {fp: {"runs": list(runs)}}}


def test_threshold_is_three_per_user_ruling():
    """用户 2026-10-19 裁定 N=3 —— 这个数字是口径，不是实现细节。"""
    assert R.SYSTEMIC_RECURRENCE_MIN_STREAK == 3


def test_two_prior_failures_make_three_and_speak_up():
    """历史 2 次 + 本次 = 连续 3 次 ⇒ 出声（systemic=True）。"""
    info = R.cross_run_recurrence(_entry(), _hist("r1", "r2"))
    assert isinstance(info, dict), f"连续 3 次未绿必须被判定为复发，实际={info!r}"
    assert info["streak_with_current"] == 3
    assert info["systemic"] is True


def test_one_prior_failure_is_not_enough():
    """历史 1 次 + 本次 = 连续 2 次 ⇒ 不算连续未绿（但仍是「跨 run 复发」）。"""
    info = R.cross_run_recurrence(_entry(), _hist("r1"))
    assert isinstance(info, dict), "出现过 1 次仍属跨 run 复发（另一条判据）"
    assert info["streak_with_current"] == 2
    assert info["systemic"] is False


def test_pass_clears_the_streak():
    """「失败/失败/通过/失败」再失败时 streak 必须从 1 重算 —— 不是 3。"""
    hist = R.merge_flake_history(_hist("r1", "r2"), [], "r3", passed_case_ids=["PP-015"])
    assert "PP-015" not in hist, "通过后该用例的指纹条目必须清零"
    info = R.cross_run_recurrence(_entry(), hist)
    assert not info, "清零后应连「复发」都不成立"


def test_failed_case_keeps_counting():
    """本次仍失败 ⇒ 条目保留并追加 run_id（不被清零误伤）。"""
    hist = R.merge_flake_history(_hist("r1"), [_entry()], "r2", passed_case_ids=[])
    assert hist["PP-015"]["no_success(craft_calc_config_query)"]["runs"] == ["r1", "r2"]


def test_reset_is_per_case_not_global():
    """清零只作用于**通过的那个用例** —— 别的用例的 streak 不得被一起抹掉。"""
    hist = {"PP-015": {"fpA": {"runs": ["r1", "r2"]}},
            "PR-108": {"fpB": {"runs": ["r1"]}}}
    out = R.merge_flake_history(hist, [], "r3", passed_case_ids=["PR-108"])
    assert out["PP-015"]["fpA"]["runs"] == ["r1", "r2"], "没通过的用例不得被清零"
    assert "PR-108" not in out
