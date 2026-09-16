# case_ids: PR-016, OR-014, OR-022, CR-003
"""跨 run 波动指纹索引的**接线上锁**（issue #3806）—— 机制不许被静默拔掉。

判据政策（`local_runner.completion_verdict` 的 `systemic_recurrence`）只有拿到**历史**
才生效；历史由 `.github/scripts/flake_history.py` 从既有 flake 台账 artifact 汇总。
若没人调用它 / 没人把索引喂给 runner / runner 不读环境变量 ——
政策就成了**死代码**（"实现了但永不生效"，本仓库最贵的假绿形态）。
本文件把这条链**逐环**锁住（全部离线可跑，零 LLM）。
"""
import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".github" / "scripts"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
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
    assert callable(fh.lr.merge_flake_history), "脚本没复用 runner 的 merge_flake_history"
    assert fh.FLAKE_LEDGER_NAME == "agent-eval-flakes.json"


# ── ②b 「机制是否活着」的唯一开关：前缀必须命中**真实** artifact 名 ──────────────
# 病灶（抢救包 e2a094a1 复核，2026-09-15 实测）：常量写的是 `agent-eval-flakes`，
# 而仓库**真实**上传的名字是 `agent-eval-flake-ledger*` / `post-deploy-eval-*`
# （`flake` 后是 `-` 不是 `s`）⇒ 一个都匹配不上：
#
#     $ python3 .github/scripts/flake_history.py fetch --out /tmp/h.json --limit 12
#     ℹ️ 命中 flake 台账 artifact 0 个（limit=12）
#     📇 跨 run 指纹索引 → /tmp/h.json（0 条用例 / 0 个指纹）
#
# ⇒ #3806 的复发判据**永不生效**（放行政策照旧只看本次两次尝试 = 本单要修的口径）。
# 而旧守卫用的 fixture 名字（`agent-eval-flakes` / `agent-eval-flakes-mibao`）恰好是
# **编造**的 —— 于是守卫替这个缺口做了伪证。本类把 fixture 换成**从 workflow 源派生**，
# 漂移即红：上传点改名/新增而不更新前缀 → 这里先红。

UPLOAD_ARTIFACT_BLOCK = re.compile(
    r"uses:\s*actions/upload-artifact@\S+\s*\n\s*with:\s*\n(.*?)(?=\n\s*- name:|\Z)", re.S)


def _flake_ledger_producer_names() -> list:
    """从 workflow 源派生"哪个 artifact 里装着 flake 台账"（唯一事实源 = workflow 本身）。"""
    names = []
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        for m in UPLOAD_ARTIFACT_BLOCK.finditer(wf.read_text(encoding="utf-8")):
            block = m.group(1)
            if "agent-eval-flakes.json" not in block:      # 这个 artifact 不装台账
                continue
            nm = re.search(r"name:\s*(\S[^\n]*)", block)
            if nm:
                names.append(nm.group(1).strip())
    return names


class TestArtifactPrefixesMatchRealProducers:
    def test_every_real_ledger_artifact_is_matched_by_the_prefixes(self):
        """**核心**：workflow 里每个装着台账的 artifact 名都必须被前缀命中。"""
        fh = _flake_history()
        names = _flake_ledger_producer_names()
        assert names, ("一个台账 artifact 都没派生出来 —— 派生正则失效，本守卫会静默空跑"
                       "（先修 `_flake_ledger_producer_names`）")
        arts = [{"name": n, "created_at": "2026-09-15T00:00:00Z", "expired": False,
                 "workflow_run": {"id": i}} for i, n in enumerate(names)]
        selected = {a["name"] for a in fh.select_flake_artifacts(arts, limit=50)}
        missing = sorted(n for n in names if n not in selected)
        assert missing == [], (
            f"这些真实台账 artifact 被 `FLAKE_ARTIFACT_PREFIXES={fh.FLAKE_ARTIFACT_PREFIXES}` "
            f"漏掉 ⇒ 跨 run 索引取不到它们 ⇒ #3806 复发判据对它们**永不生效**（死代码）：\n  "
            + "\n  ".join(missing))

    def test_old_prefix_would_have_missed_everything(self):
        """**红证**：抢救包的原前缀 `agent-eval-flakes` 对真实名字命中 **0** 个。

        真随机波动会漂移，但 artifact 名不会 —— 这条断言把"前缀写错 = 机制静默死掉"
        这件事钉成可复算的红证（改回旧值 ⇒ 本用例红）。
        """
        fh = _flake_history()
        names = _flake_ledger_producer_names()
        assert names, "派生失效（见上一条）"
        hit_old = [n for n in names if n.startswith("agent-eval-flakes")]
        assert hit_old == [], (
            f"旧前缀竟命中 {hit_old} —— 若仓库真把 artifact 改名成 `agent-eval-flakes*`，"
            f"请同步更新本红证与 `FLAKE_ARTIFACT_PREFIXES`，而不是删掉这条断言")
        hit_new = [n for n in names if n.startswith(fh.FLAKE_ARTIFACT_PREFIXES)]
        assert sorted(hit_new) == sorted(names), f"新前缀没覆盖全部：{sorted(names)}"

    def test_unrelated_artifacts_are_not_selected(self):
        """反向守卫：与台账无关的 artifact 不许被选中（否则白下载 + 成本）。"""
        fh = _flake_history()
        arts = [{"name": n, "created_at": "2026-09-15T00:00:00Z", "expired": False,
                 "workflow_run": {"id": i}}
                for i, n in enumerate(["xiaobu-visual-diffs", "gitleaks-results.sarif",
                                       "xiaobu-acceptance-artifacts-shard0"])]
        assert fh.select_flake_artifacts(arts, limit=50) == []

    def test_expired_and_limit_still_apply(self):
        """剔除过期 + 新→旧排序 + limit（防止上面两条把纯函数契约覆盖掉）。"""
        fh = _flake_history()
        arts = [
            {"name": "agent-eval-flake-ledger", "created_at": "2026-09-14T00:00:00Z",
             "expired": False, "workflow_run": {"id": 1}},
            {"name": "post-deploy-eval-mibao", "created_at": "2026-09-15T00:00:00Z",
             "expired": False, "workflow_run": {"id": 2}},
            {"name": "agent-eval-flake-ledger-shard0", "created_at": "2026-09-16T00:00:00Z",
             "expired": True, "workflow_run": {"id": 3}},
        ]
        assert [a["workflow_run"]["id"] for a in fh.select_flake_artifacts(arts, limit=5)] == [2, 1]
        assert [a["workflow_run"]["id"] for a in fh.select_flake_artifacts(arts, limit=1)] == [2]
        assert fh.select_flake_artifacts([], limit=5) == []

    def test_string_prefix_is_not_char_exploded(self):
        """容错：传字符串不许被 `startswith` 当单字符元组（静默恒假 = 同一个坑）。"""
        fh = _flake_history()
        arts = [{"name": "post-deploy-eval-mibao", "created_at": "2026-09-15T00:00:00Z",
                 "expired": False, "workflow_run": {"id": 2}}]
        assert [a["workflow_run"]["id"] for a in
                fh.select_flake_artifacts(arts, limit=5, prefixes="post-deploy-eval-")] == [2]


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

    def test_empty_index_is_visible_not_silent(self, tmp_path, monkeypatch, capsys):
        """**不许静默退化**：索引为空 ⇒ 复发判据本次不生效 ⇒ 必须留 `::warning::`。

        为什么单列一条（#3806 与 #3803 同族）：`continue-on-error: true` 只保证"不因此
        变红"，**不保证看得见** —— 而"取不到历史"与"真的没有复发"在结论上长得一模一样。
        这正是本仓库最贵的形态（绿了但没跑）。红证：删掉 `fetch_history` 里的
        `::warning::` ⇒ 本用例红。
        """
        fh = _flake_history()
        monkeypatch.setattr(fh, "list_artifacts", lambda repo: [])
        hist = fh.fetch_history("o/r", 12, tmp_path / "h.json")
        out = capsys.readouterr().out
        assert hist == {}
        assert "::warning::" in out and "不生效" in out, (
            f"索引为空却没有任何可见信号（放行政策悄悄退回旧口径）：{out!r}")
        assert (tmp_path / "h.json").read_text(encoding="utf-8").strip() == "{}"
