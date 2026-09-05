"""
Test eval-case smoke tier membership (issue #2786).

背景：OR-010 / PR-010（创建订单 / 商品全生命周期多轮工具流）是已知真实 LLM
模型漂移用例（2026-09-03 起 agent-eval-smoke 连续失败阻塞全部 PR 合并）。
修复：将两者从 smoke 降级至 normal（每日回归仍覆盖，但不再阻塞 PR 门禁）。
本测试锁定 smoke 集合，防止漂移用例被误改回 smoke。
"""
# case_ids: OR-010, PR-010
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))

from render_cases import load_case_dicts  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"

# 已知模型漂移用例（issue #2786）：agent-eval-smoke 若包含它们将单点阻塞 PR
DRIFT_PATHS = ["OR-010", "PR-010"]

# 降级后 smoke 集合（9 → 7）：全部为稳定单轮/双轮查询类用例
EXPECTED_SMOKE = {"AS-001", "CU-001", "HR-001", "HR-004", "OR-001", "PR-001", "PR-003"}


def _active_smoke_ids():
    cases = load_case_dicts(str(CASES_DIR))
    return {
        c["id"]
        for c in cases
        if c.get("tier") == "smoke" and not c.get("skip_reason")
    }


class TestSmokeTierFreeze:
    """smoke tier 集合锁定（防漂移用例回流阻塞 PR）"""

    def test_drift_paths_not_in_smoke(self):
        smoke = _active_smoke_ids()
        for cid in DRIFT_PATHS:
            assert cid not in smoke, f"{cid} 是已知漂移用例（#2786），不应在 smoke 档"

    def test_drift_paths_still_active_normal(self):
        cases = load_case_dicts(str(CASES_DIR))
        by_id = {c["id"]: c for c in cases}
        for cid in DRIFT_PATHS:
            assert cid in by_id, f"{cid} 不存在"
            assert not by_id[cid].get("skip_reason"), f"{cid} 不应被 skip（每日回归仍需覆盖）"
            assert by_id[cid].get("tier") == "normal", f"{cid} 应降级为 normal（仍跑每日回归）"

    def test_smoke_set_exact(self):
        assert _active_smoke_ids() == EXPECTED_SMOKE