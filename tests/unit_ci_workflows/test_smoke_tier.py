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
EXPECTED_SMOKE = {"AS-001", "CU-001", "HR-001", "HR-004", "OR-001", "PR-001", "PR-003", "KN-001", "KN-003"}  # KN-001/003：双端知识问答冒烟（issue #3059）
# ── OR-012 / AS-008 于 2026-09-13 由 smoke 提为 normal（issue #3367 覆盖审计）──
# 原判断（issue #3266）是"升 smoke 以补 C 端覆盖缺口"，但 smoke 档对 C 端**根本没人跑**：
#   · pr-check 的 agent-eval-smoke 打的是共享 B 端环境、未设 PERSONA（默认米宝）
#     → persona: xiaobu 的用例被 persona 过滤排除（见下条 test_mibao_smoke_excludes_xiaobu_only）；
#   · xiaobu-acceptance 由 CI 以 tier=normal 派发。
# 结果：这两条（物流查询、售后进度查询，且带"仅限本人/拒绝越权直查"数据隔离断言）
# 成了**谁都不跑**的用例 —— 该能力在每日回归里零观测。提为 normal 后由 C 端每日回归承担。
# KN-001 仍是 smoke（其能力已被 normal 档的 KN-002/007/008 覆盖，不构成盲区）。
XIAOBU_ONLY_SMOKE = {"KN-001"}


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
    def test_mibao_smoke_excludes_xiaobu_only(self):
        """B 端 smoke 档不得含 C 端专属用例（issue #2855 persona 过滤）"""
        from render_cases import filter_by_persona  # noqa: E402
        mibao_smoke = {
            c["id"] for c in filter_by_persona(load_case_dicts(str(CASES_DIR)), "mibao")
            if c.get("tier") == "smoke" and not c.get("skip_reason")
        }
        leaked = mibao_smoke & XIAOBU_ONLY_SMOKE
        assert not leaked, f"B 端 smoke 混入 C 端专属用例: {sorted(leaked)}"
