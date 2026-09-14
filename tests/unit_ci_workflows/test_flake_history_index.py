# case_ids: PR-016, OR-014, OR-022, CR-003
"""跨 run 波动指纹索引的**接线上锁**（issue #3806）—— 机制不许被静默拔掉。

判据政策（`local_runner.completion_verdict` 的 `systemic_recurrence`）只有拿到**历史**
才生效；历史由 `.github/scripts/flake_history.py` 从既有 flake 台账 artifact 汇总。
若没人调用它 / 没人把索引喂给 runner / runner 不读环境变量 ——
政策就成了**死代码**（"实现了但永不生效"，本仓库最贵的假绿形态）。
本文件把这条链**逐环**锁住（全部离线可跑，零 LLM）。
"""
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".github" / "scripts"
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _flake_history():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return _load(SCRIPTS / "flake_history.py", "migao_flake_history")


def test_runner_exposes_the_history_env_contract():
    """① runner 侧：环境变量名 + 索引读写函数必须存在（否则脚本没地方喂）。"""
    lr = _load(RUNNER_PATH, "migao_eval_runner_flake_history_contract")
    assert lr.FLAKE_HISTORY_ENV == "AGENT_EVAL_FLAKE_HISTORY"
    for fn in ("load_flake_history", "merge_flake_history", "cross_run_recurrence",
               "annotate_cross_run_recurrence", "cross_case_fingerprint_cases"):
        assert callable(getattr(lr, fn, None)), f"runner 缺 {fn}（跨 run 判据没法落地）"
    src = RUNNER_PATH.read_text(encoding="utf-8")
    assert "os.environ.get(FLAKE_HISTORY_ENV" in src, (
        "runner 没有读 FLAKE_HISTORY_ENV —— 索引再全也不会被消费（死代码）")
    assert "annotate_cross_run_recurrence(results, flake_ledger, _history)" in src, (
        "runner 没有在台账生成处调用标注 —— 复发不会进 verdict")


def test_script_uses_the_single_implementation():
    """② 脚本侧：并入口径必须复用 runner 的实现（不许第二份平行实现）。"""
    fh = _flake_history()
    assert fh.lr.merge_flake_history is not None
    assert fh.FLAKE_ARTIFACT_PREFIX == "agent-eval-flakes"


def test_select_flake_artifacts_filters_and_sorts():
    """③ 纯函数：只挑 flake 台账、剔除过期、按新→旧、受 limit 约束。"""
    fh = _flake_history()
    arts = [
        {"name": "agent-eval-flakes", "created_at": "2026-09-14T00:00:00Z", "expired": False,
         "workflow_run": {"id": 1}},
        {"name": "post-deploy-eval-mibao", "created_at": "2026-09-15T00:00:00Z", "expired": False,
         "workflow_run": {"id": 2}},
        {"name": "agent-eval-flakes-mibao", "created_at": "2026-09-15T10:00:00Z", "expired": False,
         "workflow_run": {"id": 3}},
        {"name": "agent-eval-flakes", "created_at": "2026-09-16T00:00:00Z", "expired": True,
         "workflow_run": {"id": 4}},
    ]
    assert [a["workflow_run"]["id"] for a in fh.select_flake_artifacts(arts, limit=5)] == [3, 1]
    assert [a["workflow_run"]["id"] for a in fh.select_flake_artifacts(arts, limit=1)] == [3]
    assert fh.select_flake_artifacts([], limit=5) == []


def _workflow(name: str) -> str:
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


class TestCrossRunIndexIsWired:
    """④ 接线：判定用途的 workflow 必须**取索引 + 喂 runner + 滚动上传**，三环缺一即死代码。"""

    WF = "post-deploy-eval.yml"

    def test_fetch_step_exists_before_the_eval(self):
        src = _workflow(self.WF)
        assert "flake_history.py fetch" in src, (
            f"{self.WF} 没有取跨 run 索引 → 政策拿不到历史（永远不判复发）")
        i_fetch = src.index("flake_history.py fetch")
        i_eval = src.index("Run ${{ matrix.persona }}")
        assert i_fetch < i_eval, "取索引必须在评测**之前**（评测时才读得到索引）"

    def test_runner_env_points_at_the_index(self):
        src = _workflow(self.WF)
        assert "AGENT_EVAL_FLAKE_HISTORY: flake-history.json" in src, (
            "没把索引喂给 runner（runner 读 AGENT_EVAL_FLAKE_HISTORY）")

    def test_index_is_uploaded_for_the_next_run(self):
        """滚动：runner 结束会把本次台账并入索引 ⇒ 必须上传，否则下一跑没有历史。"""
        src = _workflow(self.WF)
        assert "flake-history.json" in src.split("Upload 汇总 + 波动台账")[1], (
            "索引没有随 artifact 上传 → 历史永不累积（政策只在第一跑生效）")

    def test_fetch_is_non_fatal(self):
        """取不到历史不是失败（首次/无凭据）—— 否则会造出一条与评测无关的红。"""
        src = _workflow(self.WF)
        block = src[src.index("flake_history.py fetch") - 1200:src.index("flake_history.py fetch")]
        assert "continue-on-error: true" in block, "取索引步骤必须 continue-on-error"
