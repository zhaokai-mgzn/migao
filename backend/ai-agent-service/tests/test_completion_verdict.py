"""评测完成判定谓词单测（tests/agent_eval/local_runner.py::completion_verdict）

#3483 T2「完成定义前置」：评测完成 = 确定性失败清零 + 关键旅程 case 全过 +
已知波动（llm-noise/unstable）由 flake 台账放行。取代「全量 100% 绿才算完」的
旧判据（B 端 80 轮差距分析实证：最后 5-10% 是 LLM 方差，追 100% 边际收益为负——
三测自述「逐个校准 case 追波动边际收益递减」）。

判定语义：
- 确定性失败（reproducible / error / no-retry-budget / infra / 未知分类但 score<1）
  = 代码缺陷或本轮不可信，必须处理 → 未完成；
- 关键旅程用例（KEY_JOURNEYS_*，P0 跨域核心链路）任何一条 score<1 → 未完成
  （旅程是用户真会走的路，波动也不放行）；
- llm-noise / unstable（已由 runner 记入 flake 台账）→ 放行但列出。
"""
# case_ids: OR-016, PR-019, PR-020, AS-007, FN-004, HR-003, DA-002, CU-003, CT-002, OR-012, CH-010, OR-017, KN-001, CH-008, CH-024
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("migao_eval_runner3", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lr = _load_runner()

JOURNEY = ("OR-016", "PR-019")


def _r(case_id, score, classification="pass"):
    return {"case_id": case_id, "score": score, "classification": classification}


class TestCompletionVerdict:
    def test_all_pass_is_complete(self):
        v = lr.completion_verdict([_r("OR-001", 1.0), _r("OR-016", 1.0)], JOURNEY)
        assert v["ok"] is True

    def test_empty_results_blocks(self):
        v = lr.completion_verdict([], JOURNEY)
        assert v["ok"] is False
        assert "0 个用例" in v["reason"]

    def test_reproducible_blocks(self):
        v = lr.completion_verdict([_r("FN-004", 0.0, "reproducible")], JOURNEY)
        assert v["ok"] is False
        assert "FN-004" in v["deterministic_failures"]

    def test_error_blocks(self):
        v = lr.completion_verdict([_r("HR-003", 0.0, "error")], JOURNEY)
        assert v["ok"] is False
        assert "HR-003" in v["deterministic_failures"]

    def test_no_retry_budget_blocks(self):
        """重试预算用尽 = 未重试未分类，保守视为确定性失败（诚实报告，不得放行）"""
        v = lr.completion_verdict([_r("DA-002", 0.0, "no-retry-budget")], JOURNEY)
        assert v["ok"] is False

    def test_infra_blocks_this_run(self):
        """infra 失败使本轮不可信（环境问题可整跑重试，但结论不能基于本轮）"""
        v = lr.completion_verdict([_r("CT-002", 0.0, "infra")], JOURNEY)
        assert v["ok"] is False

    def test_llm_noise_released(self):
        v = lr.completion_verdict([_r("AS-007", 0.0, "llm-noise")], JOURNEY)
        assert v["ok"] is True
        assert "AS-007" in v["flake_released"]

    def test_unstable_released(self):
        v = lr.completion_verdict([_r("CU-003", 0.0, "unstable")], JOURNEY)
        assert v["ok"] is True
        assert "CU-003" in v["flake_released"]

    def test_journey_failure_blocks_even_llm_noise(self):
        """关键旅程不放行：P0 旅程 score<1 即使分类 llm-noise 也判未完成"""
        v = lr.completion_verdict([_r("OR-016", 0.0, "llm-noise")], JOURNEY)
        assert v["ok"] is False
        assert "OR-016" in v["journey_failures"]

    def test_unknown_classification_blocks_conservative(self):
        """无分类证据的失败（旧数据/异常形态）按确定性失败处理，不放行"""
        v = lr.completion_verdict([_r("X-001", 0.0, "")], JOURNEY)
        assert v["ok"] is False
        assert "X-001" in v["deterministic_failures"]

    def test_pass_classification_with_low_score_blocks(self):
        """no-classify 兼容路径的形态：classification=pass 但 score<1 → 保守按确定性失败"""
        v = lr.completion_verdict([_r("X-002", 0.5, "pass")], JOURNEY)
        assert v["ok"] is False

    def test_legacy_shape_without_classification_ok_when_pass(self):
        v = lr.completion_verdict([{"case_id": "A", "score": 1.0}], JOURNEY)
        assert v["ok"] is True

    def test_reason_mentions_both_groups(self):
        v = lr.completion_verdict(
            [_r("FN-004", 0.0, "reproducible"), _r("OR-016", 0.0, "llm-noise")], JOURNEY)
        assert v["ok"] is False
        assert "FN-004" in v["reason"] and "OR-016" in v["reason"]

    def test_journey_ids_are_sane_constants(self):
        """关键旅程常量必须引用真实存在的用例（防拼错 = 完成判定空转）"""
        import sys
        sys.path.insert(0, str(REPO_ROOT / ".github"))
        from render_cases import load_case_dicts
        ids = {c["id"] for c in load_case_dicts(str(REPO_ROOT / ".github" / "cases"))}
        for jid in (set(lr.KEY_JOURNEYS_MIBAO) | set(lr.KEY_JOURNEYS_XIAOBU)):
            assert jid in ids, f"关键旅程 {jid} 不存在于 cases/（完成判定将空转）"
