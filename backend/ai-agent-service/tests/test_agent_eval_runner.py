"""Agent Eval runner 真实验收守卫单测（tests/agent_eval/local_runner.py）

覆盖 _last_round_error_verdict：最后一轮 error 且用例未预期错误 → 判失败。
背景（issue #2887 验收复盘）：expectations 是「任意一轮命中即过」，clearing 卡后
发图轮报错时，前面轮次可能已命中 success=true / tool 等 expectation，
旧逻辑把用例计为通过（假验收 —— 线上 sess_806703a2dcca4059 图片崩溃正是此类）。
"""
# case_ids: CH-021, CH-026
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("migao_eval_runner", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lr = _load_runner()


class TestLastRoundErrorVerdict:
    """最后一轮报错守卫（真实验收假阳性防线）"""

    def test_last_round_error_with_success_expectation_fails(self):
        """假验收回归：前面轮次命中 success=true，最后一轮（发图轮）报错 → 必须判失败。"""
        results = [
            {"error": None},
            {"error":  "抱歉，遇到问题: AttributeError: 'list' object has no attribute 'strip'"},
        ]
        verdict = lr._last_round_error_verdict(results, ["success=true"], [])
        assert verdict is not None
        assert "最后轮报错" in verdict

    def test_last_round_error_no_expectation_fails(self):
        results = [{"error": None}, {"error": "boom"}]
        assert lr._last_round_error_verdict(results, ["tool: product_search"], []) is not None

    def test_clean_last_round_passes(self):
        results = [{"error": None}, {"error": None}]
        assert lr._last_round_error_verdict(results, ["tool: product_search"], []) is None

    def test_mid_round_error_recovered_pass(self):
        """错误发生在中间轮、最后一轮正常 → 不影响（用例终点是干净的）。"""
        results = [{"error": "transient"}, {"error": None}]
        assert lr._last_round_error_verdict(results, [], []) is None

    def test_empty_results_passes(self):
        assert lr._last_round_error_verdict([], [], []) is None

    def test_expectation_error_code_exempts(self):
        """用例显式预期 error.code= → 不硬判失败（对抗用例 E001 类）。"""
        results = [{"error": None}, {"error": "error.code=NOT_FOUND"}]
        verdict = lr._last_round_error_verdict(
            results, ["tool: product_detail"], ["error.code=NOT_FOUND"]
        )
        assert verdict is None

    def test_data_checks_suggestion_exempts(self):
        results = [{"error": None}, {"error": "suggestion returned"}]
        assert lr._last_round_error_verdict(
            results, ["tool: product_search"], ["suggestion 非空且包含 product_search"]
        ) is None