# case_ids: MC-012
"""CI 失败**重跑分流 + flaky 台账**的判据与结构锁（issue #4717）—— L0，离线、零 LLM、秒级。

本文件锁的是 **CI 基建**（不是产品行为），故不新增/改判任何评测用例；`case_ids` 取仓库里
**真实存在**的 CI 域用例 MC-012（`.github/cases/misc.yml`，CI workflow 行为由
`tests/unit_ci_workflows/` 单测验证）—— 与同目录 `test_merge_gate.py` / `test_danger_scan.py`
/ `test_gate_uncommitted_noop.py` 同一口径。⚠️ **未改 `cases/**`**（Case Trust 缴费要求）。

锁四件事（每条的**反向变异**都会让本文件红）
--------------------------------------------
1. **绝不静默放行**：「第二次绿」只能产出 `mark_flaky`，而 workflow 侧必须
   `gh pr merge --disable-auto` + `block/merge` + `flaky/rerun-green`
   （#4248 实证：`block/merge` 标签**拦不住已 arm** 的 auto-merge，只有 `--disable-auto` 停得住）；
2. **绝不无限重跑**：`MAX_ATTEMPTS == 2`（首次 + 最多 1 次），`gh run rerun` 在 workflow 里
   **恰好一处**且由 `action == 'rerun'` 独占；第二次仍红 ⇒ `record_both_red` + `kind=unknown`
   （#5088：**两次都红 ≠ 确定性失败**，判据与红证见 `test_flaky_ledger_kind_semantics.py`），**不放行**；
3. **绝不误判 infra**：cancelled / timed_out / startup_failure / 无 steps 的 job /
   只在「取代码 · 装依赖」步骤失败的 job ⇒ `skip` 或 `infra_suspect`，**不入 flaky**；
4. **绝不重复记账**：幂等键 `(workflow, run_id, job)`；台账**只追加**、不写硬编码计数；
5. **台账必须真的落 main**（**#4804**）：台账 PR 由 `GITHUB_TOKEN` 创建 ⇒ GitHub 抑制其
   `pull_request` run（`action_required`、**零 job**、check-runs 为空）⇒ `gh pr checks` 报
   「no checks reported」⇒ `--auto` **永不触发**。台账**直推 main 已被分支保护拒绝**
   （实测 409「Changes must be made through a pull request. 12 of 12 required status checks
   are expected.」）⇒ 唯一通路 = **自己 approve** 那批被抑制的 run（`actions: write`，
   **不绕过 required 检查**）。摘掉 approve 步骤 ⇒ 本文件必红。

红证卫生（照 §19.1 元规则 ③）
------------------------------
每条守卫都配一条**注入式红证**：把坏形态注回 ⇒ 必须红。判据读的是**文件内容**（不是
mtime/size），且注入走 `str.replace` 的**内容变异** ⇒ 无缓存可污染（纯文本，不 import 变异体）。
"""
import copy
import importlib.util
import io
import json
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".github" / "scripts"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "flaky-triage.yml"
LEDGER_PATH = REPO_ROOT / ".github" / "flaky-ledger.json"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FL = _load(SCRIPTS / "flaky_ledger.py", "migao_flaky_ledger")
REAL_WORKFLOW = WORKFLOW_PATH.read_text(encoding="utf-8")
#: 脚本源码本体（红证用它做**内容变异** ⇒ 免疫 `.pyc` 缓存；判据读内容，不读 mtime/size）。
REAL_SCRIPT_SOURCE = (SCRIPTS / "flaky_ledger.py").read_text(encoding="utf-8")


# ── 夹具（形状与 GitHub REST `/actions/runs/{id}` + `/attempts/{n}/jobs` 同源） ──


def make_run(name="PR Check", attempt=1, conclusion="failure", event="pull_request",
             branch="ci/some-branch", pr=4757, run_id=900001,
             updated="2026-09-20T10:00:00Z"):
    return {
        "id": run_id,
        "name": name,
        "event": event,
        "conclusion": conclusion,
        "run_attempt": attempt,
        "head_branch": branch,
        "head_sha": "a" * 40,
        "html_url": f"https://github.com/o/r/actions/runs/{run_id}",
        "updated_at": updated,
        "pull_requests": [{"number": pr}] if pr else [],
    }


def make_job(name="mini-app typecheck + unit tests", conclusion="failure",
             failed_step="Run unit tests"):
    if conclusion != "failure":
        steps = [{"name": "Run unit tests", "conclusion": "success"}]
    elif failed_step is None:
        steps = []  # 从未真正跑起来（runner 分配/启动失败）
    else:
        steps = [
            {"name": "Set up job", "conclusion": "success"},
            {"name": "Run actions/checkout@v7", "conclusion": "success"},
            {"name": failed_step, "conclusion": "failure"},
        ]
    return {"name": name, "conclusion": conclusion, "steps": steps}


def bundle(run=None, jobs=None, prior_jobs=None):
    return {"run": run or make_run(), "jobs": jobs if jobs is not None else [],
            "prior_jobs": prior_jobs}


# ── ① 重跑分流：纯函数判据 ────────────────────────────────────────────────────


class TestRerunOnce:
    def test_first_failure_triggers_exactly_one_rerun(self):
        d = FL.decide(bundle(run=make_run(attempt=1, conclusion="failure"),
                             jobs=[make_job()]))
        assert d["action"] == "rerun", d
        assert d["entries"] == [], "重跑前不许记账（终态才记账）"

    def test_second_attempt_green_marks_flaky_and_records_one_entry(self):
        d = FL.decide(bundle(run=make_run(attempt=2, conclusion="success"),
                             jobs=[make_job(conclusion="success")],
                             prior_jobs=[make_job()]))
        assert d["action"] == "mark_flaky", d
        assert d["kind"] == "flaky"
        assert len(d["entries"]) == 1
        e = d["entries"][0]
        assert e["kind"] == "flaky" and e["rerun_result"] == "success"
        assert e["run_id"] == 900001 and e["pr"] == 4757
        assert e["first_failure_step"] == "Run unit tests"

    def test_second_attempt_failure_is_unknown_and_never_reruns(self):
        """**反向护栏**：两次都失败 ⇒ 仍然失败（不放行、不重跑第三次）。

        #5088：`kind` **不再**由 `rerun_result` 单独推出 —— 自动路径只有步骤级事实，
        两次都红一律 `unknown`（fail-closed：不归因），但**照常失败**这条硬约束不变。
        """
        d = FL.decide(bundle(run=make_run(attempt=2, conclusion="failure"),
                             jobs=[make_job()], prior_jobs=None))
        assert d["action"] == "record_both_red", d
        assert d["kind"] == "unknown"
        assert d["entries"][0]["rerun_result"] == "failure"
        assert d["entries"][0]["kind"] == "unknown"

    def test_third_attempt_still_never_reruns(self):
        """上限是硬的：即使 run_attempt 被人为推高，也绝不重跑。"""
        d = FL.decide(bundle(run=make_run(attempt=3, conclusion="failure"),
                             jobs=[make_job()]))
        assert d["action"] == "record_both_red", d

    def test_green_first_attempt_is_noop(self):
        d = FL.decide(bundle(run=make_run(attempt=1, conclusion="success"),
                             jobs=[make_job(conclusion="success")]))
        assert d["action"] == "skip" and d["entries"] == []

    def test_max_attempts_is_two(self):
        assert FL.MAX_ATTEMPTS == 2, "改大 MAX_ATTEMPTS = 允许无限重跑（红线）"


# ── ② infra / 取消 / 超时：不许记成 flaky，也不许重跑 ─────────────────────────


class TestInfraIsNotFlaky:
    def test_cancelled_and_timed_out_are_skipped(self):
        """**反向护栏**：取消/超时 ⇒ 不记 flaky、也不重跑。"""
        for conclusion in ("cancelled", "timed_out", "startup_failure", "stale", "action_required"):
            d = FL.decide(bundle(run=make_run(attempt=1, conclusion=conclusion),
                                 jobs=[make_job()]))
            assert d["action"] == "skip", (conclusion, d)
            assert d["entries"] == [], (conclusion, d)

    def test_job_without_steps_is_infra(self):
        d = FL.decide(bundle(run=make_run(attempt=2, conclusion="success"),
                             jobs=[], prior_jobs=[make_job(failed_step=None)]))
        assert d["action"] == "record_infra", d
        assert d["entries"][0]["kind"] == "infra_suspect"

    def test_install_step_failure_is_infra_not_flaky(self):
        """装依赖失败 = 环境问题，**不是**被测对象 flaky。"""
        for step in ("Install dependencies", "Install test deps", "Run actions/checkout@v7",
                     "Set up job", "Setup Node.js", "npm ci", "pip install -q pytest pyyaml"):
            job = make_job(failed_step=step)
            assert FL.job_is_infra(job), f"{step} 应判 infra"
        assert not FL.job_is_infra(make_job(failed_step="Run unit tests"))
        assert not FL.job_is_infra(make_job(failed_step="TypeScript type check"))

    def test_infra_green_rerun_is_recorded_but_not_labelled_flaky(self):
        d = FL.decide(bundle(run=make_run(attempt=2, conclusion="success"),
                             jobs=[], prior_jobs=[make_job(failed_step="Install dependencies")]))
        assert d["action"] == "record_infra", d
        assert all(e["kind"] != "flaky" for e in d["entries"])

    def test_failure_without_any_failed_job_is_skipped(self):
        d = FL.decide(bundle(run=make_run(attempt=1, conclusion="failure"), jobs=[]))
        assert d["action"] == "skip", d


# ── ③ 触发面守卫：非 PR / 非白名单 / 台账分支自指 ─────────────────────────────


class TestTriggerScope:
    def test_non_pr_event_is_skipped(self):
        for event in ("push", "schedule", "workflow_dispatch"):
            d = FL.decide(bundle(run=make_run(event=event), jobs=[make_job()]))
            assert d["action"] == "skip", (event, d)

    def test_workflow_outside_allowlist_is_skipped(self):
        d = FL.decide(bundle(run=make_run(name="Post-Deploy Eval (部署后全量回归)"),
                             jobs=[make_job()]))
        assert d["action"] == "skip", d

    def test_deploy_workflows_are_not_in_allowlist(self):
        """重跑有副作用的 workflow **绝不许**进白名单（否则分流会真的触发部署）。"""
        for name in ("Build and Deploy admin-api", "Deploy Production (受控发布)",
                     "Deploy Reconcile (PR 对账补偿)", "Post-Deploy Eval (部署后全量回归)"):
            assert name not in FL.TRIAGED_WORKFLOWS, f"{name} 重跑有副作用/烧 token，不许分流"

    def test_ledger_branch_self_loop_is_skipped(self):
        """台账 PR 自己的 CI 不许再被分流（否则「分流 → 开台账 PR → 又被分流」自指递归）。"""
        d = FL.decide(bundle(run=make_run(branch=FL.LEDGER_BRANCH), jobs=[make_job()]))
        assert d["action"] == "skip", d
        assert "递归" in d["reason"] or "自指" in d["reason"], d


# ── ④ 策略不变式（与实现解耦的**独立**判据 + 注入式红证） ─────────────────────


def policy_violations(decide_fn) -> list:
    """三条红线的**独立**检查器：喂任意 `decide` 可调用，返回违规说明（空 = 合规）。

    刻意不读 `FL.decide` 的内部结构 —— 只喂夹具看输出 ⇒ 把「实现」换成「注入版」也能判。
    """
    bad = []

    d = decide_fn(bundle(run=make_run(attempt=2, conclusion="failure"), jobs=[make_job()]))
    if d["action"] == "rerun":
        bad.append("第二次仍失败却又重跑 ⇒ 违反「最多重跑 1 次」")
    if d["action"] in ("mark_flaky", "record_infra", "skip"):
        bad.append(f"第二次仍失败却给出 {d['action']!r} ⇒ **把确定性失败放行**（红线）")
    if d["kind"] != "unknown" or d["kind"] in FL.ATTRIBUTABLE_KINDS:
        bad.append(f"第二次仍失败的 kind 应为 unknown（**不归因**，事实不足以判确定性失败），"
                   f"实际 {d['kind']!r}")

    d = decide_fn(bundle(run=make_run(attempt=2, conclusion="success"), jobs=[],
                         prior_jobs=[make_job()]))
    if d["action"] != "mark_flaky":
        bad.append(f"第二次绿应标 flaky，实际 {d['action']!r}")
    for e in d["entries"]:
        if e["kind"] == "flaky" and e["rerun_result"] != "success":
            bad.append("flaky 条目的 rerun_result ≠ success ⇒ 放行了未复现的失败")

    d = decide_fn(bundle(run=make_run(attempt=2, conclusion="success"), jobs=[],
                         prior_jobs=[make_job(failed_step="Install dependencies")]))
    if d["action"] != "record_infra" or any(e["kind"] == "flaky" for e in d["entries"]):
        bad.append(f"装依赖失败被记成 flaky（{d['action']!r}）⇒ 把 infra 抖动记成 flaky")

    d = decide_fn(bundle(run=make_run(conclusion="cancelled"), jobs=[make_job()]))
    if d["action"] != "skip" or d["entries"]:
        bad.append(f"取消的运行给出 {d['action']!r} / {len(d['entries'])} 条 ⇒ 把 infra 记成 flaky")

    return bad


class TestPolicyInvariants:
    def test_real_decide_satisfies_all_invariants(self):
        assert policy_violations(FL.decide) == []

    def test_red_proof_injecting_pass_on_second_failure(self):
        """**红证**：注入「第二次失败也放行」⇒ 不变式**必须**红。"""
        def leaky(b, max_attempts=FL.MAX_ATTEMPTS):
            d = FL.decide(b, max_attempts)
            if d["action"] == "record_both_red":
                return dict(d, action="mark_flaky", kind="flaky")
            return d

        violations = policy_violations(leaky)
        assert violations, "注入「第二次失败也放行」后仍判绿 ⇒ 该判据是**空断言**"
        assert any("放行" in v for v in violations), violations

    def test_red_proof_injecting_infra_as_flaky(self):
        """**红证**：注入「把 infra 记成 flaky」⇒ 不变式**必须**红。"""
        def leaky(b, max_attempts=FL.MAX_ATTEMPTS):
            d = FL.decide(b, max_attempts)
            if d["action"] == "record_infra":
                return dict(d, action="mark_flaky", kind="flaky",
                            entries=[dict(e, kind="flaky") for e in d["entries"]])
            return d

        violations = policy_violations(leaky)
        assert any("infra" in v for v in violations), violations

    def test_red_proof_injecting_unbounded_rerun(self):
        """**红证**：注入「第二次仍失败也重跑」⇒ 不变式**必须**红。"""
        def leaky(b, max_attempts=FL.MAX_ATTEMPTS):
            d = FL.decide(b, max_attempts)
            if d["action"] == "record_both_red":
                return dict(d, action="rerun", kind=None, entries=[])
            return d

        assert any("重跑" in v for v in policy_violations(leaky))


# ── ⑤ 台账：只追加 + 幂等 + 自洽 ──────────────────────────────────────────────


def _entry(run_id=900001, job="mini-app typecheck + unit tests", kind="flaky",
           rerun_result="success", status="open", follow_up=None, fixed_by=None):
    entry = {"workflow": "PR Check", "job": job, "run_id": run_id, "run_attempt": 2,
             "run_url": f"https://x/{run_id}", "pr": 4757, "head_sha": "a" * 40,
             "head_branch": "ci/x", "first_failure_step": "Run unit tests",
             "rerun_result": rerun_result, "kind": kind,
             "observed_at": "2026-09-20T10:00:00Z",
             "reason": FL.KIND_REASON[kind], "remedy": FL.KIND_REMEDY[kind],
             "status": status, "follow_up": follow_up}
    if fixed_by:
        entry["fixed_by"] = fixed_by
    return entry


class TestLedgerAppend:
    def test_append_is_idempotent_across_calls(self):
        ledger = {"entries": []}
        added, skipped = FL.append_entries(ledger, [_entry()])
        assert len(added) == 1 and skipped == []
        added2, skipped2 = FL.append_entries(ledger, [_entry()])
        assert added2 == [] and len(skipped2) == 1, "同一次失败被追加两次 ⇒ 幂等失效"
        assert len(ledger["entries"]) == 1

    def test_append_dedupes_within_one_batch(self):
        ledger = {"entries": []}
        added, skipped = FL.append_entries(ledger, [_entry(), _entry()])
        assert len(added) == 1 and len(skipped) == 1

    def test_distinct_jobs_of_same_run_are_both_recorded(self):
        ledger = {"entries": []}
        added, _ = FL.append_entries(ledger, [_entry(job="A"), _entry(job="B")])
        assert len(added) == 2, "同 run 的不同 job 是不同失败 ⇒ 必须各记一条"

    def test_same_job_of_different_runs_are_both_recorded(self):
        ledger = {"entries": []}
        added, _ = FL.append_entries(ledger, [_entry(run_id=1), _entry(run_id=2)])
        assert len(added) == 2

    def test_append_never_mutates_existing_entries(self):
        first = _entry(run_id=1)
        ledger = {"entries": [dict(first)]}
        FL.append_entries(ledger, [_entry(run_id=2)])
        assert ledger["entries"][0] == first, "「只追加」被破坏（既有条目被改写）"


class TestLedgerSelfConsistency:
    def test_shipped_ledger_is_self_consistent(self):
        ledger = FL.load_ledger(LEDGER_PATH)
        assert FL.ledger_violations(ledger) == []

    def test_shipped_ledger_has_no_hardcoded_counts(self):
        ledger = FL.load_ledger(LEDGER_PATH)
        for key in FL.FORBIDDEN_LEDGER_KEYS:
            assert key not in ledger, f"台账写了硬编码计数 `{key}`（会腐烂 ⇒ 条数一律现取）"

    def test_violation_when_flaky_has_non_success_rerun(self):
        """**红证形态**：kind=flaky 但重跑没绿 ⇒ 必判违规（= 放行了未复现的失败）。"""
        bad = FL.ledger_violations({"version": 1, "note": "", "_schema": {},
                                    "entries": [_entry(kind="flaky", rerun_result="failure")]})
        assert bad and any("放行" in b for b in bad), bad

    def test_violation_on_duplicate_keys(self):
        bad = FL.ledger_violations({"version": 1, "note": "", "_schema": {},
                                    "entries": [_entry(), _entry()]})
        assert any("重复" in b for b in bad), bad

    def test_violation_on_missing_field_and_bad_kind(self):
        e = _entry()
        del e["observed_at"]
        e["kind"] = "maybe-flaky"
        bad = FL.ledger_violations({"version": 1, "note": "", "_schema": {}, "entries": [e]})
        assert any("observed_at" in b for b in bad), bad
        assert any("kind" in b for b in bad), bad

    def test_violation_on_hardcoded_count_key(self):
        bad = FL.ledger_violations({"version": 1, "note": "", "_schema": {},
                                    "count": 0, "entries": []})
        assert any("计数" in b for b in bad), bad

    def test_selftest_cli_is_fail_closed(self, tmp_path):
        """CLI 也走同一判据：坏台账 ⇒ 非零退出（不是「静默通过」）。"""
        bad_path = tmp_path / "bad.json"
        bad_path.write_text('{"version": 1, "note": "", "_schema": {}, "entries": "nope"}',
                            encoding="utf-8")
        assert FL.main(["selftest", "--ledger", str(bad_path)]) == 1
        assert FL.main(["selftest", "--ledger", str(LEDGER_PATH)]) == 0

    def test_append_cli_refuses_inconsistent_ledger(self, tmp_path):
        bad_path = tmp_path / "bad.json"
        bad_path.write_text('{"version": 1, "note": "", "_schema": {}, "entries": "nope"}',
                            encoding="utf-8")
        entries = tmp_path / "e.json"
        entries.write_text("[]", encoding="utf-8")
        assert FL.main(["append", "--ledger", str(bad_path), "--entries", str(entries)]) == 1

    def test_append_cli_writes_and_is_idempotent(self, tmp_path):
        ledger = tmp_path / "l.json"
        ledger.write_text('{"version": 1, "note": "", "_schema": {}, "entries": []}',
                          encoding="utf-8")
        entries = tmp_path / "e.json"
        entries.write_text(__import__("json").dumps([_entry()]), encoding="utf-8")
        assert FL.main(["append", "--ledger", str(ledger), "--entries", str(entries)]) == 0
        assert len(FL.load_ledger(ledger)["entries"]) == 1
        assert FL.main(["append", "--ledger", str(ledger), "--entries", str(entries)]) == 0
        assert len(FL.load_ledger(ledger)["entries"]) == 1, "第二次 append 不是空操作"


# ── ⑤b 台账消费接口：聚合（计数现取，不设阈值） ────────────────────────────────


class TestLedgerReport:
    def test_aggregate_counts_are_computed_not_stored(self):
        ledger = {"version": 1, "note": "", "_schema": {}, "entries": [
            _entry(run_id=1, job="A", kind="flaky"),
            _entry(run_id=2, job="A", kind="flaky"),
            _entry(run_id=3, job="A", kind="confirmed_failure", rerun_result="failure"),
            _entry(run_id=4, job="B", kind="infra_suspect"),
        ]}
        groups = FL.aggregate(ledger)
        a = groups["PR Check :: A"]
        assert (a["flaky"], a["confirmed_failure"], a["total"]) == (2, 1, 3)
        assert groups["PR Check :: B"]["infra_suspect"] == 1
        # 计数只存在于**返回值**里，台账本体一个计数键都没有
        assert FL.ledger_violations(ledger) == []

    def test_aggregate_of_empty_ledger_is_empty(self):
        assert FL.aggregate({"entries": []}) == {}

    def test_report_cli_runs_on_the_shipped_ledger(self, capsys):
        assert FL.main(["report", "--ledger", str(LEDGER_PATH)]) == 0
        out = capsys.readouterr().out
        assert "条目数现取" in out and "不设阈值" in out

    def test_report_cli_never_hardcodes_a_threshold(self, tmp_path):
        """报告型判据**不设阈值**：无论条目多少，退出码恒 0（阈值留给消费方）。"""
        ledger = tmp_path / "l.json"
        ledger.write_text(__import__("json").dumps(
            {"version": 1, "note": "", "_schema": {},
             "entries": [_entry(run_id=i, job="A") for i in range(9)]}), encoding="utf-8")
        assert FL.main(["report", "--ledger", str(ledger)]) == 0


# ── ⑤c 三态对账（照 #4757 存量账本口径，适配「事件追加日志」语义） ──────────────


class TestReconcile:
    def test_clean_ledger_reconciles_clean(self):
        ledger = {"entries": [_entry(follow_up=4717)]}
        assert FL.reconcile(ledger) == {"new_events": [], "duplicates": [],
                                        "fixed_not_deducted": []}

    def test_state1_new_event_without_follow_up_is_red(self):
        """态① 新事件：`kind=flaky` 且 `status=open` 却没有跟踪单 ⇒ 未登记修复路径。"""
        result = FL.reconcile({"entries": [_entry(follow_up=None)]})
        assert len(result["new_events"]) == 1, result
        assert "follow_up" in result["new_events"][0]["why"]

    def test_state2_duplicate_count_is_red(self):
        """态② 重复计数：幂等键重复 ⇒ 「N 次标 flaky」的 N 不可信。"""
        result = FL.reconcile({"entries": [_entry(follow_up=1), _entry(follow_up=1)]})
        assert len(result["duplicates"]) == 1, result

    def test_state3_fixed_without_evidence_is_red(self):
        """态③ 已修未销账（a）：标了 fixed 却没有 fixed_by 凭据。"""
        result = FL.reconcile({"entries": [_entry(status="fixed", follow_up=1)]})
        assert len(result["fixed_not_deducted"]) == 1, result
        assert "fixed_by" in result["fixed_not_deducted"][0]["why"]

    def test_state3_fixed_then_recurrence_is_red(self):
        """态③ 已修未销账（b）：标了 fixed，**之后又复发** ⇒ 修复不成立（假账）。"""
        ledger = {"entries": [
            _entry(run_id=1, status="fixed", fixed_by="PR 4700", follow_up=1),
            _entry(run_id=2, status="open", follow_up=2),
        ]}
        result = FL.reconcile(ledger)
        assert len(result["fixed_not_deducted"]) == 1, result
        assert "复发" in result["fixed_not_deducted"][0]["why"]

    def test_fixed_with_evidence_and_no_recurrence_is_clean(self):
        ledger = {"entries": [
            _entry(run_id=1, status="fixed", fixed_by="PR 4700", follow_up=1),
            _entry(run_id=2, job="another job", status="open", follow_up=2),
        ]}
        assert FL.reconcile(ledger)["fixed_not_deducted"] == []

    def test_reconcile_cli_is_three_state(self, tmp_path, capsys):
        dirty = tmp_path / "dirty.json"
        dirty.write_text(__import__("json").dumps(
            {"version": 1, "note": "", "_schema": {}, "entries": [_entry()]}), encoding="utf-8")
        assert FL.main(["reconcile", "--ledger", str(dirty)]) == 1
        assert "未接 required 门禁" in capsys.readouterr().out

        clean = tmp_path / "clean.json"
        clean.write_text(__import__("json").dumps(
            {"version": 1, "note": "", "_schema": {}, "entries": [_entry(follow_up=4717)]}),
            encoding="utf-8")
        assert FL.main(["reconcile", "--ledger", str(clean)]) == 0
        assert "对账干净" in capsys.readouterr().out

    def test_shipped_ledger_reconciles_clean(self):
        """出厂台账必须是干净的（否则一落地就是欠账）。

        ⚠️ #5307 判据②：**失败消息必须可行动** —— 断言消息带**欠账清单**（每条 `workflow` /
        `run_id` / `job`）+ **可直接复制**的回填命令（`FL.render_reconcile_report`）。旧形态只有
        `assert {...} == {...}` 的 diff：读的人不知道下一步做什么；而 schema 只写「由分诊方回填」、
        没写用哪个命令 ⇒ 回填成了「文档要求做、却没有合法工具做」的动作（= 台账自我死锁的一半）。
        """
        ledger = FL.load_ledger(LEDGER_PATH)
        violations = shipped_violations(ledger)
        assert violations == [], violations[0]


# ── ⑤f #5307：`follow_up` 的**回填路径**（字段级 ⇒ 不破坏「条目只追加」） ──────────

CLEAN_RECONCILE = {"new_events": [], "duplicates": [], "fixed_not_deducted": []}

#: 回填**只许**碰这三个字段（「条目只追加」在字段级的边界）。
FOLLOW_UP_FIELDS = ("follow_up", "status", "fixed_by")


def _load_mutant(source: str, name: str):
    """把**内容变异**后的脚本源码当模块加载（红证用：判据读内容，免疫 `.pyc` 缓存）。"""
    namespace = {"__name__": name, "__file__": str(SCRIPTS / "flaky_ledger.py")}
    exec(compile(source, f"<mutant:{name}>", "exec"), namespace)
    return types.SimpleNamespace(**namespace)


def shipped_violations(ledger, judge=None, render=None) -> list:
    """`test_shipped_ledger_reconciles_clean` 的**判据本体**（空 = 绿；非空 = 可行动清单）。

    抽成函数是为了让「注入欠账 ⇒ 必红」能被**单独**证明（红证不写在断言消息里，而走同一判据）：
    `judge` / `render` 可换成变异体 ⇒ 判据的判别力可被红证钉住（§19.1 元规则③）。
    """
    judge = judge or FL.reconcile
    render = render or FL.render_reconcile_report
    result = judge(ledger)
    if result == CLEAN_RECONCILE:
        return []
    return [render(ledger, result)]


def append_semantics_violations(before: dict, after: dict, targets) -> list:
    """「条目只追加」的机械判据（空 = 合规）：回填**不许**新增/删除/重排条目，
    且只许改 `targets` 里那些条目的 `follow_up`(/`status`/`fixed_by`)。"""
    bad = []
    rows_before, rows_after = before.get("entries") or [], after.get("entries") or []
    if len(rows_before) != len(rows_after):
        bad.append(f"条目数变了（{len(rows_before)} → {len(rows_after)}）⇒ 「条目只追加」被破坏")
    if [FL.entry_key(e) for e in rows_before] != [FL.entry_key(e) for e in rows_after]:
        bad.append("条目的键集合/顺序变了 ⇒ 「条目只追加」（不删、不重排）被破坏")
    targets = set(targets)
    for i, (eb, ea) in enumerate(zip(rows_before, rows_after)):
        if eb == ea:
            continue
        if i not in targets:
            bad.append(f"entries[{i}] 不在本次回填目标里却被改动 ⇒ 回填越界")
            continue
        for field in sorted(set(eb) | set(ea)):
            if field in FOLLOW_UP_FIELDS:
                continue
            if eb.get(field) != ea.get(field):
                bad.append(f"entries[{i}].{field} 被改动（回填只许改 {FOLLOW_UP_FIELDS}）")
    return bad


def fail_closed_violations(rc, before: dict, after: dict) -> list:
    """fail-closed 判据（空 = 合规）：`run_id` 不存在 / 单号非法 ⇒ **非零退出**且台账**一字未改**
    （「静默无操作」正是 #5307 的病灶形态：命令看起来成功了，死亡锁却还在）。"""
    bad = []
    if rc == 0:
        bad.append("静默无操作：该拒绝的输入却退 0（读的人会以为回填成功）")
    if before != after:
        bad.append("拒绝路径却改动了台账（fail-closed 必须是**无副作用**的）")
    return bad


def _fixture(tmp_path, name="ledger.json", inject=True, run_id=990000001):
    """出厂台账的副本（可选：注入一条 `kind=flaky`/`status=open`/`follow_up=null` 欠账）。"""
    ledger = copy.deepcopy(FL.load_ledger(LEDGER_PATH))
    entry = None
    if inject:
        entry = copy.deepcopy(ledger["entries"][-1])
        entry.update({"workflow": "PR Check", "job": "admin-web typecheck + unit tests",
                      "run_id": run_id, "run_attempt": 2, "kind": "flaky", "status": "open",
                      "follow_up": None, "rerun_result": "success",
                      "reason": FL.KIND_REASON["flaky"], "remedy": FL.KIND_REMEDY["flaky"]})
        entry.pop("fixed_by", None)
        ledger["entries"].append(entry)
    path = tmp_path / name
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, ledger, entry


class TestFollowUp:
    """#5307 判据①：**文档化的回填路径**（`follow-up` 子命令）；判据③：注入 ⇒ 红 / 回填 ⇒ 绿。

    ⚠️ 为什么必须有这条路径（**本单病灶**）：`append_entries` 对同幂等键**跳过**（幂等）⇒ 用
    `append` 回填 = 无效；CLI 又没有回填子命令 ⇒ schema 里那句「由分诊方回填」**没有合法工具**；
    而 required 测试判「台账必须 reconcile 干净」⇒ 一条欠账就让台账分支**永远绿不了**。
    """

    def test_debt_red_then_backfill_green(self, tmp_path):
        """判据③逐字：注入一条欠账 ⇒ 判据**必红**（消息含清单 + 可复制命令）；回填 ⇒ **归零**。"""
        path, ledger, _ = _fixture(tmp_path)
        injected = shipped_violations(ledger)
        assert injected, "注入 kind=flaky/status=open/follow_up=null 后判据仍绿 ⇒ 判据是空断言"
        report = injected[0]
        for anchor in ("990000001", "admin-web typecheck + unit tests", "PR Check"):
            assert anchor in report, f"欠账清单缺 `{anchor}`（读的人定位不到那条）：{report}"
        assert "flaky_ledger.py follow-up" in report, "清单里没有**可直接复制**的回填命令"
        assert "--issue <跟踪单号>" in report, "回填命令没说明单号位置（回填路径仍然不可执行）"

        assert FL.main(["follow-up", "--ledger", str(path), "--run-id", "990000001",
                        "--issue", "5088"]) == 0
        assert shipped_violations(FL.load_ledger(path)) == [], "回填后仍有欠账（判据没归零）"

    def test_backfill_keeps_append_only_semantics(self, tmp_path):
        """判据①后半：回填**只改字段** —— 条目数与顺序不变，其它条目一字未动。"""
        path, ledger, entry = _fixture(tmp_path)
        before = json.loads(path.read_text(encoding="utf-8"))
        target = len(before["entries"]) - 1
        assert FL.main(["follow-up", "--ledger", str(path), "--run-id", "990000001",
                        "--issue", "5088"]) == 0
        after = json.loads(path.read_text(encoding="utf-8"))
        assert append_semantics_violations(before, after, {target}) == []
        assert after["entries"][target]["follow_up"] == 5088
        assert [FL.entry_key(e) for e in after["entries"]] == [FL.entry_key(e) for e in before["entries"]]

    def test_backfill_is_idempotent(self, tmp_path, capsys):
        """幂等：重复回填同一值 = **无副作用**（文件一个字节都不动）。"""
        path, _, _ = _fixture(tmp_path)
        assert FL.main(["follow-up", "--ledger", str(path), "--run-id", "990000001",
                        "--issue", "5088"]) == 0
        first = path.read_bytes()
        capsys.readouterr()
        assert FL.main(["follow-up", "--ledger", str(path), "--run-id", "990000001",
                        "--issue", "5088"]) == 0
        out = capsys.readouterr().out
        assert "幂等" in out and "未改动" in out, out
        assert path.read_bytes() == first, "重复回填改动了文件（不是无副作用的空操作）"

    def test_unknown_run_id_fails_closed(self, tmp_path, capsys):
        """fail-closed：`run_id` 不在台账里 ⇒ 非零退出 + 明确报错 + **台账一字未改**。"""
        path, _, _ = _fixture(tmp_path)
        before = json.loads(path.read_text(encoding="utf-8"))
        rc = FL.main(["follow-up", "--ledger", str(path), "--run-id", "1", "--issue", "5088"])
        err = capsys.readouterr().err
        assert fail_closed_violations(rc, before, json.loads(path.read_text(encoding="utf-8"))) == []
        assert "不在台账里" in err and "拒绝回填" in err, err

    def test_run_id_must_be_positive(self, tmp_path, capsys):
        path, _, _ = _fixture(tmp_path)
        before = json.loads(path.read_text(encoding="utf-8"))
        rc = FL.main(["follow-up", "--ledger", str(path), "--run-id", "0", "--issue", "5088"])
        err = capsys.readouterr().err
        assert fail_closed_violations(rc, before, json.loads(path.read_text(encoding="utf-8"))) == []
        assert "正整数" in err, err

    def test_invalid_issue_number_fails_closed(self, tmp_path, capsys):
        """fail-closed：单号非正整数（`0` / 负数 / 非数字）⇒ 非零退出 + 明确报错。"""
        path, _, _ = _fixture(tmp_path)
        before = json.loads(path.read_text(encoding="utf-8"))
        for bad_issue in ("0", "-3", "5088x"):
            rc = FL.main(["follow-up", "--ledger", str(path), "--run-id", "990000001",
                          "--issue", bad_issue])
            err = capsys.readouterr().err
            assert fail_closed_violations(
                rc, before, json.loads(path.read_text(encoding="utf-8"))) == [], (bad_issue, err)
            assert "正整数" in err or "不是整数" in err, (bad_issue, err)

    def test_ambiguous_run_needs_job_and_lists_candidates(self, tmp_path, capsys):
        """同一 run 有多条（不同 job）⇒ **不许猜**：非零退出并给出可复制的候选命令。"""
        path, ledger, entry = _fixture(tmp_path, inject=False)
        for job in ("job A", "job B"):
            twin = copy.deepcopy(entry if entry else ledger["entries"][-1])
            twin.update({"job": job, "run_id": 990000002, "kind": "flaky", "status": "open",
                         "follow_up": None, "rerun_result": "success"})
            twin.pop("fixed_by", None)
            ledger["entries"].append(twin)
        path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
        before = json.loads(path.read_text(encoding="utf-8"))
        rc = FL.main(["follow-up", "--ledger", str(path), "--run-id", "990000002",
                      "--issue", "5088"])
        err = capsys.readouterr().err
        assert fail_closed_violations(rc, before, json.loads(path.read_text(encoding="utf-8"))) == []
        for anchor in ("命中 2 条", "--job 'job A'", "--job 'job B'"):
            assert anchor in err, f"候选命令缺 `{anchor}`：{err}"

    def test_backfill_can_deduct_with_evidence(self, tmp_path):
        """销账路径：`--status fixed --fixed-by <凭据>` 一次写完（否则 `reconcile` 判销账不成立）。"""
        path, _, _ = _fixture(tmp_path)
        assert FL.main(["follow-up", "--ledger", str(path), "--run-id", "990000001",
                        "--issue", "5088", "--status", "fixed",
                        "--fixed-by", "PR #9999"]) == 0
        entry = FL.load_ledger(path)["entries"][-1]
        assert (entry["status"], entry["fixed_by"], entry["follow_up"]) == ("fixed", "PR #9999", 5088)
        assert shipped_violations(FL.load_ledger(path)) == []

    def test_fixed_requires_fixed_by(self, tmp_path, capsys):
        """fail-closed：标 `fixed` 却不给凭据 ⇒ 拒绝（否则写出一条「销账不成立」的假账）。"""
        path, _, _ = _fixture(tmp_path)
        before = json.loads(path.read_text(encoding="utf-8"))
        rc = FL.main(["follow-up", "--ledger", str(path), "--run-id", "990000001",
                      "--issue", "5088", "--status", "fixed"])
        err = capsys.readouterr().err
        assert fail_closed_violations(rc, before, json.loads(path.read_text(encoding="utf-8"))) == []
        assert "--fixed-by" in err, err

    def test_how_to_is_documented_in_one_place(self):
        """schema 里那句「由分诊方回填」必须**点明用哪个命令**（死锁的另一半）。"""
        howto = FL.FOLLOW_UP_HOWTO
        for anchor in ("follow-up", "--run-id", "--issue", "--job", "--status fixed",
                       "--fixed-by", "非零退出", "幂等"):
            assert anchor in howto, f"回填口径缺 `{anchor}`：{howto}"

    def test_reconcile_branch_reads_the_ungated_branch_ledger(self, capsys):
        """#5307 可见性：`reconcile --branch` 对账的是**台账分支**那份（欠账正停在它上面）。"""
        original = FL.read_branch_ledger
        FL.read_branch_ledger = lambda branch="": {
            "version": 1, "note": "", "_schema": {}, "entries": [_entry(follow_up=None)]}
        try:
            assert FL.main(["reconcile", "--branch", "chore/flaky-ledger"]) == 1
        finally:
            FL.read_branch_ledger = original
        out = capsys.readouterr().out
        assert "follow-up --ledger" in out and "900001" in out, out

    def test_reconcile_branch_undeterminable_is_three(self, capsys):
        """三态：读不到台账分支 ⇒ 退 3（**不得**当「无欠账」读）。"""
        original = FL.read_branch_ledger

        def boom(branch=""):
            raise RuntimeError("stub: 读不到分支台账")

        FL.read_branch_ledger = boom
        try:
            assert FL.main(["reconcile", "--branch", "chore/flaky-ledger"]) == 3
        finally:
            FL.read_branch_ledger = original
        assert "未跑 ≠ 通过" in capsys.readouterr().err


class TestFollowUpRedProofs:
    """注入式红证：把坏实现 / 旧形态注回 ⇒ 上述判据**必须**红（不会红的判据 = 空断言）。"""

    def test_red_proof_reconcile_widened_to_ignore_missing_follow_up(self):
        """把「flaky 且 open 却没 follow_up」这条对账判据**摘掉**（= 为了变绿而放宽本意）⇒ 必红。"""
        mutated = REAL_SCRIPT_SOURCE.replace(
            'if entry.get("kind") == "flaky" and entry.get("status") != "fixed" '
            'and not entry.get("follow_up"):',
            "if False:", 1)
        assert mutated != REAL_SCRIPT_SOURCE, "注入锚点失效（先修本测试）"
        widened = _load_mutant(mutated, "m_flaky_widened")
        _, ledger, _ = _fixture(Path(tempfile.mkdtemp()), inject=True)
        assert widened.reconcile(ledger) == CLEAN_RECONCILE, "变异体前提变了（先修本测试）"
        assert shipped_violations(ledger, judge=widened.reconcile,
                                  render=FL.render_reconcile_report) == [], (
            "放宽对账判据后判据仍红 ⇒ 本红证没打在点子上")

    def test_red_proof_backfill_that_appends_instead_of_editing(self):
        """把回填实现成「追加一条」⇒ 「条目只追加」判据必须红（= #5307 里 append 回填无效的形态）。

        ⚠️ 直接调变异体的 `apply_follow_up`（不走 CLI）：CLI 的「回填后仍须自洽」闸会先一步拒绝
        写入（`ledger_violations` 抓幂等键重复）⇒ 那样测到的是那道闸，不是「只追加」判据本身。
        """
        mutated = REAL_SCRIPT_SOURCE.replace(
            '        for field in ("follow_up", "status", "fixed_by"):\n'
            '            if target[field] != before[field]:\n'
            '                entry[field] = target[field]\n',
            "        entries.append(__import__('copy').deepcopy(entry))\n", 1)
        assert mutated != REAL_SCRIPT_SOURCE, "注入锚点失效（先修本测试）"
        bad_mod = _load_mutant(mutated, "m_flaky_append")
        ledger = copy.deepcopy(FL.load_ledger(LEDGER_PATH))
        target = len(ledger["entries"])
        twin = copy.deepcopy(ledger["entries"][-1])
        twin.update({"run_id": 990000001, "job": "admin-web typecheck + unit tests",
                     "kind": "flaky", "status": "open", "follow_up": None,
                     "rerun_result": "success"})
        twin.pop("fixed_by", None)
        ledger["entries"].append(twin)
        before = copy.deepcopy(ledger)
        indices = bad_mod.follow_up_index(ledger, 990000001)
        bad_mod.apply_follow_up(ledger, indices, issue=5088)
        assert append_semantics_violations(before, ledger, {target}) != [], (
            "追加式回填没有被判红 ⇒ 「条目只追加」判据是空断言")

    def test_red_proof_fail_open_on_unknown_run_id(self, tmp_path, capsys):
        """把拒绝路径改成**静默无操作**（`return 0`）⇒ fail-closed 判据必须红。"""
        mutated = REAL_SCRIPT_SOURCE.replace(
            '            print(f"⛔ {exc}", file=sys.stderr)\n'
            '            print(f"   （回填口径：{FOLLOW_UP_HOWTO}）", file=sys.stderr)\n'
            "            return 1\n",
            "            return 0\n", 1)
        assert mutated != REAL_SCRIPT_SOURCE, "注入锚点失效（先修本测试）"
        bad_mod = _load_mutant(mutated, "m_flaky_failopen")
        path, _, _ = _fixture(tmp_path)
        before = json.loads(path.read_text(encoding="utf-8"))
        rc = bad_mod.main(["follow-up", "--ledger", str(path), "--run-id", "1", "--issue", "5088"])
        capsys.readouterr()
        assert fail_closed_violations(rc, before, json.loads(path.read_text(encoding="utf-8"))) != [], (
            "静默无操作没有被判红 ⇒ fail-closed 判据是空断言")

    def test_red_proof_invalid_issue_accepted(self, tmp_path, capsys):
        """把「单号必须正整数」的校验摘掉 ⇒ 非法单号被静默接受 ⇒ fail-closed 判据必须红。"""
        mutated = REAL_SCRIPT_SOURCE.replace(
            "    if num <= 0:\n"
            '        raise ValueError(f"{what}={value!r} 不是正整数")\n',
            "    if False:\n"
            '        raise ValueError(f"{what}={value!r} 不是正整数")\n', 1)
        assert mutated != REAL_SCRIPT_SOURCE, "注入锚点失效（先修本测试）"
        bad_mod = _load_mutant(mutated, "m_flaky_badissue")
        path, _, _ = _fixture(tmp_path)
        before = json.loads(path.read_text(encoding="utf-8"))
        rc = bad_mod.main(["follow-up", "--ledger", str(path), "--run-id", "990000001",
                           "--issue", "0"])
        capsys.readouterr()
        assert fail_closed_violations(rc, before, json.loads(path.read_text(encoding="utf-8"))) != [], (
            "非法单号被接受却没有被判红 ⇒ fail-closed 判据是空断言")


# ── ⑤d 条目必须**可行动**（照 #4757 形态：每条带 reason + remedy） ─────────────


class TestActionableEntries:
    def test_generated_entries_carry_reason_and_remedy(self):
        d = FL.decide(bundle(run=make_run(attempt=2, conclusion="success"), jobs=[],
                             prior_jobs=[make_job()]))
        entry = d["entries"][0]
        assert entry["reason"] and entry["remedy"]
        assert entry["status"] == "open" and entry["follow_up"] is None
        assert FL.ledger_violations({"version": 1, "note": "", "_schema": {},
                                     "entries": [entry]}) == []

    def test_empty_reason_or_remedy_is_a_violation(self):
        for field in ("reason", "remedy"):
            bad_entry = _entry(follow_up=1)
            bad_entry[field] = "   "
            bad = FL.ledger_violations({"version": 1, "note": "", "_schema": {},
                                        "entries": [bad_entry]})
            assert any(field in b for b in bad), (field, bad)

    def test_bad_status_is_a_violation(self):
        bad = FL.ledger_violations({"version": 1, "note": "", "_schema": {},
                                    "entries": [_entry(status="maybe")]})
        assert any("status" in b for b in bad), bad

    def test_bad_follow_up_type_is_a_violation(self):
        bad = FL.ledger_violations({"version": 1, "note": "", "_schema": {},
                                    "entries": [_entry(follow_up="4717")]})
        assert any("follow_up" in b for b in bad), bad


# ── ⑤e PR 评论：**为什么被停** + **人工恢复路径**（可见性 / 可恢复） ────────────


class TestCommentVisibility:
    def _mark_flaky_decision(self):
        return FL.decide(bundle(run=make_run(attempt=2, conclusion="success"), jobs=[],
                                prior_jobs=[make_job()]))

    def test_comment_says_why_it_was_stopped(self):
        body = FL.render_comment(self._mark_flaky_decision())
        assert "为什么被停" in body
        assert "mini-app typecheck + unit tests" in body      # 哪个 job
        assert "900001" in body                                # 哪次 run
        assert "第 2 次尝试通过" in body                        # 第几次才绿
        assert "PR Check/900001/mini-app typecheck + unit tests" in body   # 台账条目幂等键

    def test_comment_states_auto_merge_was_disarmed_and_gives_manual_recovery(self):
        body = FL.render_comment(self._mark_flaky_decision())
        assert "disable-auto" in body
        assert "block/merge" in body and "flaky/rerun-green" in body
        assert "人工恢复路径" in body
        assert "不是**自动恢复" in body or "不是自动恢复" in body

    def test_comment_carries_the_remedy(self):
        body = FL.render_comment(self._mark_flaky_decision())
        assert "定位机制" in body

    def test_comment_marker_is_stable_for_idempotent_update(self):
        body = FL.render_comment(self._mark_flaky_decision())
        assert body.startswith("<!-- flaky-triage: action=mark_flaky")

    def test_both_red_comment_says_it_stays_failed_and_is_unattributed(self):
        """#5088：评论**不许**再把「两次都红」写成「确定性失败」；要列两次尝试的原始事实。"""
        d = FL.decide(bundle(run=make_run(attempt=2, conclusion="failure"), jobs=[make_job()],
                             prior_jobs=[make_job()]))
        body = FL.render_comment(d)
        assert "仍然失败" in body and "不重跑第三次" in body
        assert "不归因" in body and "unknown" in body
        assert "确定性失败**" not in body.split("判据：")[0], body
        assert "a1：「Run unit tests」" in body and "a2：「Run unit tests」" in body, body


# ── ⑥ workflow 结构锁（读 YAML 真值 + 注入式红证） ────────────────────────────


def _step_text(step) -> str:
    parts = [step.get("run") or "", str((step.get("with") or {}).get("script") or "")]
    env = step.get("env")
    if isinstance(env, dict):
        parts.extend(str(v) for v in env.values())
    return "\n".join(parts)


def audit_workflow(src: str) -> list:
    """workflow 结构判据（空 = 合规）。纯函数，注入变异体后复用同一路径。"""
    bad = []
    try:
        wf = yaml.safe_load(src) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - 正常不会走到
        return [f"workflow YAML 解析失败：{exc}"]

    trig = wf.get("on") or wf.get(True) or {}
    if set(trig) != {"workflow_run"}:
        bad.append(f"触发面必须**只有** workflow_run，实际 {sorted(trig)}")
    else:
        wr = trig["workflow_run"] or {}
        if list(wr.get("types") or []) != ["completed"]:
            bad.append("workflow_run.types 必须是 [completed]（run 结束才分流）")
        if sorted(wr.get("workflows") or []) != sorted(FL.TRIAGED_WORKFLOWS):
            bad.append("workflow_run.workflows 必须与 flaky_ledger.TRIAGED_WORKFLOWS 逐字一致")

    perms = wf.get("permissions") or {}
    for scope in ("actions", "contents", "pull-requests", "issues"):
        if str(perms.get(scope) or "").lower() != "write":
            bad.append(f"permissions.{scope} 必须 write（缺它 ⇒ 对应动作静默 403 = 静默失效）")

    steps = ((wf.get("jobs") or {}).get("triage") or {}).get("steps") or []
    if not steps:
        return bad + ["triage job 没有 steps ⇒ 本守卫会静默空跑（先修 workflow）"]

    rerun_steps = []
    for i, step in enumerate(steps):
        text = _step_text(step)
        if step.get("continue-on-error") not in (None, False):
            bad.append(f"step[{i}] 用了 continue-on-error ⇒ 等于把失败改成通过（红线）")
        if "gh run rerun" in text:
            rerun_steps.append((i, str(step.get("if") or "")))
        extra = set(re.findall(r"secrets\.([A-Za-z0-9_]+)", text)) - {"GITHUB_TOKEN"}
        if extra:
            bad.append(f"step[{i}] 引用了 GITHUB_TOKEN 之外的 secrets {sorted(extra)}（红线）")

    if len(rerun_steps) != 1:
        bad.append(f"`gh run rerun` 必须**恰好一处**（无限重跑防线），实际 {len(rerun_steps)} 处")
    elif "action == 'rerun'" not in rerun_steps[0][1]:
        bad.append(f"`gh run rerun` 必须由 `action == 'rerun'` 独占（实际 if={rerun_steps[0][1]!r}）")

    flaky = [s for s in steps if "mark_flaky" in str(s.get("if") or "")]
    if not flaky:
        bad.append("没有 `action == 'mark_flaky'` 的步骤 ⇒ 标 flaky 无处落地")
    else:
        txt = "\n".join(_step_text(s) for s in flaky)
        # ⚠️ **只认调用形态**（`gh pr merge … --disable-auto`），不认子串：
        #    首版写成 `"--disable-auto" not in txt`，被同一 run 块里的**提示文案**
        #    （`|| echo "ℹ️ --disable-auto 无操作…"`）满足 ⇒ 摘掉真命令后守卫**不红** = 假绿。
        #    与 `test_workflow_issue_permissions.py`「提及 ≠ 调用」同一手法。
        if not re.search(r"gh pr merge\b[^\n]*--disable-auto", txt):
            bad.append("mark_flaky 缺 `gh pr merge … --disable-auto`（**调用形态**，非文案）"
                       "⇒ **已 arm 的 auto-merge 拦不住**（#4248）= 自动放行（红线）")
        if f'--add-label "{FL.BLOCK_LABEL}"' not in txt:
            bad.append(f"mark_flaky 缺 `--add-label \"{FL.BLOCK_LABEL}\"` ⇒ 防不住再次 arm（红线）")
        if f'--add-label "{FL.FLAKY_LABEL}"' not in txt:
            bad.append(f"mark_flaky 缺 `--add-label \"{FL.FLAKY_LABEL}\"` ⇒ 标注不可见（红线）")

    decide_steps = [s for s in steps if "flaky_ledger.py decide" in _step_text(s)]
    if not decide_steps:
        bad.append("没有调用 `flaky_ledger.py decide` 的步骤 ⇒ 分流判据根本不会被调用")
    else:
        decide_txt = "\n".join(_step_text(s) for s in decide_steps)
        # 判据输出接了管道（`| tee` 写 job summary）却没 `set -o pipefail` ⇒ 判据失败会被
        # `tee` 的 0 吞掉 ⇒ `action` 为空 ⇒ 所有 `if:` 全假 ⇒ **静默 no-op**（红线）。
        # ⚠️ **只认命令行形态**（整行 `set -o pipefail`），不认子串 —— 本文件同一 run 块的
        #    **注释**里就写着 `` `set -o pipefail` 必需 ``：子串判据会被自己的说明文案骗绿
        #    （这是本 PR 第三次踩「提及 ≠ 调用」，前两次：`--disable-auto`、`autoMergeRequest`）。
        if "|" in decide_txt and not re.search(r"(?m)^\s*set\s+-o\s+pipefail\s*$", decide_txt):
            bad.append("decide 步骤接了管道却无 `set -o pipefail`（**命令行形态**，非注释里的提及）"
                       "⇒ 判据失败被 `tee` 吞掉、`action` 为空 ⇒ 静默 no-op（红线）")

    ledger_steps = [s for s in steps if "flaky_ledger.py append" in _step_text(s)]
    if not ledger_steps:
        bad.append("没有调用 `flaky_ledger.py append` 的步骤 ⇒ 台账不落仓（红线）")
    else:
        txt = "\n".join(_step_text(s) for s in ledger_steps)
        if "git diff --quiet" not in txt:
            bad.append("台账步骤缺 `git diff --quiet` 幂等闸 ⇒ 同一次失败可能重复记账")
        if FL.LEDGER_BRANCH not in txt:
            bad.append(f"台账步骤未推 {FL.LEDGER_BRANCH}（台账必须落仓到分支/PR）")

    comment_steps = [s for s in steps if "issues/" in _step_text(s) and "comments" in _step_text(s)]
    if not comment_steps:
        bad.append("没有 PR 评论步骤 ⇒ 结论只在日志深处，不满足「可见标注」")

    # ── #4804：台账落 main 的**唯一通路**必须还在 ──────────────────────────────
    # 病根：台账 PR 由 GITHUB_TOKEN 建 ⇒ GitHub 抑制其 `pull_request` run（零 job、
    # `conclusion=action_required`、check-runs 为空）⇒ `gh pr checks` 报「no checks reported」
    # ⇒ required 集合永不满足 ⇒ `--auto` 永不触发 ⇒ 台账停在分支上。
    # 台账**直推 main 已被分支保护拒绝**（实测 409），故唯一通路 = 自己 approve 那批被抑制的
    # run（`actions: write`）。摘掉它 ⇒ 回到「台账永远落不到 main」⇒ 必须红。
    approve_steps = [s for s in steps
                     if re.search(r"flaky_ledger\.py\s+approve\b", _step_text(s))]
    if not approve_steps:
        bad.append("没有调用 `flaky_ledger.py approve` 的步骤 ⇒ 台账 PR 的 run 永远停在 "
                   "`action_required`（零 check）⇒ `--auto` 永不触发 ⇒ 台账落不到 main（#4804 红线）")
    else:
        approve_txt = "\n".join(_step_text(s) for s in approve_steps)
        if "::error::" not in approve_txt:
            bad.append("approve 步骤没有 `::error::` fail-closed 出口 ⇒ 批准失败会**静默**"
                       "（台账没 check 却看起来已放行）（红线）")
        if "--head-branch" not in approve_txt:
            bad.append("approve 步骤未限定 `--head-branch` ⇒ 可能误批准**别人**的 run（越权面）")
        # ⚠️ 分支过滤参数名必须是 `branch=`：实测 `head_branch=` 被 API **静默忽略**
        #    （返回全仓 11867 个 run，而不是本分支的 13 个）⇒ 读数指向无关 run。
        #    ⚠️ **只认命令行形态**（`&head_branch=`），不认注释/文案里的提及 —— 本文件同一 run 块的
        #    **注释**里恰好写着 `` `head_branch=` 会被静默忽略 ``：子串判据会被自己的说明文案骗红
        #    （这是本文件第三次踩「提及 ≠ 调用」：前两次 `--disable-auto`、`autoMergeRequest`）。
        if "branch=$BRANCH" not in approve_txt:
            bad.append("approve 步骤的分支过滤参数必须写成 `branch=`（`head_branch=` 会被 API "
                       "静默忽略 ⇒ 读数指向全仓无关 run）")
        if re.search(r"[?&]head_branch=", approve_txt):
            bad.append("approve 步骤出现了 `&head_branch=` 查询参数（API 静默忽略该参数名，红线）")

    # ── fail-closed 复核：三个「可见性 / 落仓」动作都必须**能红** ──────────────────
    # 否则动作失败 = 静默（标不上却照常放行 / 记账没落仓却看起来成功）= 本仓库最贵的形态
    # （「绿了但没跑」）。判据只看**可执行正文**，注释与文案不算。
    for label, group in (("台账", ledger_steps), ("PR 评论", comment_steps)):
        if not group:
            continue
        if "::error::" not in "\n".join(_step_text(s) for s in group):
            bad.append(f"{label} 步骤没有 `::error::` fail-closed 出口 ⇒ 动作失败会**静默**（红线）")
    flaky_txt = "\n".join(_step_text(s) for s in flaky)
    if flaky:
        # 每个可见标注 / 阻断动作都要有**各自**的 fail-closed 出口（泛泛一个 `::error::` 不够：
        # 少标一个标签照样是「静默放行」）。
        for label in (FL.FLAKY_LABEL, FL.BLOCK_LABEL):
            if not re.search(r"::error::[^\n]*" + re.escape(label), flaky_txt):
                bad.append(f"mark_flaky 缺 `{label}` 的 fail-closed 复核（`::error::` + exit 1）"
                           "⇒ 该标注没落地会**静默放行**（红线）")
        if not re.search(r"--json\s+autoMergeRequest\b", flaky_txt):
            bad.append("mark_flaky 未复核 `--json autoMergeRequest` ⇒ "
                       "「已 arm 的 auto-merge 是否真被卸下」无判据")
        if not re.search(r"::error::[^\n]*auto-merge", flaky_txt):
            bad.append("mark_flaky 对「auto-merge 未卸下」没有 fail-closed 出口（红线）")
    if ledger_steps and "git rev-parse FETCH_HEAD" not in "\n".join(_step_text(s) for s in ledger_steps):
        bad.append("台账步骤未复核**远端 ref** ⇒ 「落仓」无判据（本地 commit ≠ 已落仓）")
    return bad


class TestWorkflowStructure:
    def test_real_workflow_is_clean(self):
        assert audit_workflow(REAL_WORKFLOW) == []

    def test_empty_input_is_not_silently_green(self):
        assert audit_workflow("") != [], "空输入判绿 ⇒ 守卫会静默空跑"

    def test_triage_job_does_not_gate_other_prs(self):
        """本 workflow **不参与 required 集合**：不许出现 pull_request 触发（否则它会卡别人）。"""
        wf = yaml.safe_load(REAL_WORKFLOW) or {}
        assert "pull_request" not in (wf.get("on") or wf.get(True) or {})

    def test_ledger_path_is_the_shipped_file(self):
        assert FL.LEDGER_PATH == LEDGER_PATH, "脚本与台账文件路径必须同源"


class TestWorkflowGuardRedProofs:
    """注入式红证：每条结构守卫都必须能红（不会红的断言 = 空断言）。"""

    def test_inject_continue_on_error(self):
        mutated = REAL_WORKFLOW.replace(
            "        if: steps.decide.outputs.action == 'rerun'",
            "        continue-on-error: true\n        if: steps.decide.outputs.action == 'rerun'", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        assert any("continue-on-error" in v for v in audit_workflow(mutated))

    def test_inject_unguarded_second_rerun(self):
        mutated = REAL_WORKFLOW.replace(
            "      - name: ③ PR 评论",
            "      - run: gh run rerun 1 --failed\n      - name: ③ PR 评论", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        violations = audit_workflow(mutated)
        assert any("恰好一处" in v for v in violations), violations

    def test_inject_removing_the_rerun_condition(self):
        mutated = REAL_WORKFLOW.replace(
            "        if: steps.decide.outputs.action == 'rerun'\n", "", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        assert any("独占" in v for v in audit_workflow(mutated))

    def test_inject_removing_disable_auto(self):
        # 锚点必须落在**命令本体**上：文件头注释里也有一处同名文本（首版踩过 ⇒ 注入命中了注释、
        # 守卫「没红」⇒ 假绿。这正是「红证锚点要选对」的现场）
        mutated = REAL_WORKFLOW.replace(
            'gh pr merge "$PR_NUMBER" --disable-auto', 'gh pr merge "$PR_NUMBER"', 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        # 提示文案里**仍然**有 `--disable-auto` —— 首版守卫正是被它骗绿的；
        # 这里把它钉住：摘掉真命令后守卫**必须**红（只认调用形态，不认文案）。
        assert 'echo "ℹ️ --disable-auto' in mutated, "夹具前提变了（先修本测试）"
        assert any("自动放行" in v for v in audit_workflow(mutated))

    def test_inject_removing_block_merge_label(self):
        mutated = REAL_WORKFLOW.replace(
            f'          gh pr edit "$PR_NUMBER" --add-label "{FL.BLOCK_LABEL}"'
            f' --repo "$GITHUB_REPOSITORY"\n', "", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        assert any(FL.BLOCK_LABEL in v for v in audit_workflow(mutated))

    def test_inject_removing_flaky_label(self):
        mutated = REAL_WORKFLOW.replace(
            f'          gh pr edit "$PR_NUMBER" --add-label "{FL.FLAKY_LABEL}"'
            f' --repo "$GITHUB_REPOSITORY"\n', "", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        assert any(FL.FLAKY_LABEL in v for v in audit_workflow(mutated))

    def test_inject_extra_secret(self):
        mutated = REAL_WORKFLOW.replace("secrets.GITHUB_TOKEN", "secrets.DEPLOY_KEY", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        assert any("DEPLOY_KEY" in v for v in audit_workflow(mutated))

    def test_inject_narrowed_permissions(self):
        mutated = REAL_WORKFLOW.replace("  contents: write", "  contents: read", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        assert any("contents" in v for v in audit_workflow(mutated))

    def test_inject_removing_idempotency_gate(self):
        mutated = REAL_WORKFLOW.replace(
            "          if git diff --quiet -- .github/flaky-ledger.json; then",
            "          if false; then", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        assert any("幂等闸" in v for v in audit_workflow(mutated))

    def test_inject_trigger_change(self):
        mutated = REAL_WORKFLOW.replace("    types: [completed]", "    types: [requested]", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        assert any("completed" in v for v in audit_workflow(mutated))

    def test_inject_allowlist_drift(self):
        mutated = REAL_WORKFLOW.replace("      - Bmini-App CI\n", "", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        assert any("逐字一致" in v for v in audit_workflow(mutated))

    def test_inject_removing_fail_closed_exit_from_flaky_mark(self):
        """摘掉 mark_flaky 的 fail-closed 出口 ⇒ 标不上会**静默放行** ⇒ 守卫必红。"""
        mutated = REAL_WORKFLOW.replace(
            'echo "::error::可见标注未落地：flaky/rerun-green 不在 [$LABELS] ⇒ fail-closed"; exit 1;; esac',
            'echo "⚠️ 标注没上";; esac', 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        assert any("fail-closed 复核" in v for v in audit_workflow(mutated))

    def test_inject_removing_auto_merge_recheck(self):
        """摘掉 autoMergeRequest 复核 ⇒ 「auto-merge 是否真被卸下」失去判据 ⇒ 守卫必红。"""
        mutated = REAL_WORKFLOW.replace("--json autoMergeRequest", "--json autoMergeRequestX", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        assert any("autoMergeRequest" in v for v in audit_workflow(mutated))

    def test_inject_removing_remote_ref_verification(self):
        """摘掉远端 ref 复核 ⇒ 「本地 commit」会被当成「已落仓」⇒ 守卫必红。"""
        mutated = REAL_WORKFLOW.replace("git rev-parse FETCH_HEAD", "git rev-parse HEAD", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        assert any("远端 ref" in v for v in audit_workflow(mutated))

    def test_inject_removing_pipefail_from_decide(self):
        """摘掉 `set -o pipefail` ⇒ 判据失败被 `tee` 吞掉、`action` 为空 ⇒ 静默 no-op ⇒ 守卫必红。"""
        mutated = REAL_WORKFLOW.replace("          set -o pipefail\n", "", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        assert any("pipefail" in v for v in audit_workflow(mutated))

    def test_inject_removing_ledger_pr_approval(self):
        """摘掉 approve 步骤 ⇒ 台账 PR 的 run 永远 `action_required`（零 check）⇒ 守卫必红。"""
        mutated = REAL_WORKFLOW.replace("flaky_ledger.py approve", "flaky_ledger.py approveX", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        violations = audit_workflow(mutated)
        assert any("approve" in v for v in violations), violations

    def test_inject_removing_approve_fail_closed(self):
        """摘掉 approve 的 fail-closed 出口 ⇒ 批准失败会静默（台账没 check 却像已放行）⇒ 必红。"""
        mutated = REAL_WORKFLOW.replace(
            'echo "::error::approve 台账 PR 的 action_required run 失败（含「窗口用尽仍停在 '
            'action_required」）⇒ 台账 PR 拿不到 required 的 check、main 不增长（fail-closed）"; exit 1; }',
            'echo "⚠️ approve 没发出去"; }', 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        assert any("fail-closed 出口" in v for v in audit_workflow(mutated))

    def test_inject_wrong_branch_query_param(self):
        """把 `&branch=$BRANCH` 改成 `&head_branch=$BRANCH` ⇒ API 静默忽略、读数指向全仓 ⇒ 必红。

        ⚠️ 注释里**本来就有** `head_branch=` 这个字串（说明文案）—— 故判据只认 `[?&]head_branch=`
        的命令行形态；本红证注入的正是命令行形态。
        """
        mutated = REAL_WORKFLOW.replace("&branch=$BRANCH&per_page=1",
                                        "&head_branch=$BRANCH&per_page=1", 1)
        assert mutated != REAL_WORKFLOW, "注入锚点失效（先修本测试）"
        violations = audit_workflow(mutated)
        assert any("head_branch" in v for v in violations), violations
        # 变异体里 `branch=$BRANCH` 已不存在 ⇒ 两条判据中必有一条命中（本注入命中前一条）
        assert any(("branch=$BRANCH" in v) or ("head_branch" in v) for v in violations), violations


class TestLedgerPrApproval:
    """#4804：被 `GITHUB_TOKEN` 抑制的台账 PR run（`action_required`）必须能被挑出并批准。

    背景（**实测读数**，别再重新猜）：台账 PR #4775 由 `app/github-actions` 创建 ⇒ 其
    `pull_request` run 全部 `conclusion=action_required`、**零 job**、check-runs 为空 ⇒
    `gh pr checks 4775` 报「no checks reported」⇒ `--auto` 永不触发。
    实测**批准 run 35493666161 后**，`gh pr checks 4775` 变成 **13 条 check**（required 逐条 pass）
    ⇒ 「approve」是被证明有效的通路，故本类把它钉住。
    """

    @staticmethod
    def _run(**kw):
        base = {"id": 1, "event": "pull_request", "conclusion": "action_required",
                "status": "completed", "head_branch": FL.LEDGER_BRANCH, "run_attempt": 1,
                "name": FL.TRIAGED_WORKFLOWS[0]}
        base.update(kw)
        return base

    def test_selects_suppressed_pull_request_runs(self):
        runs = [self._run(id=7), self._run(id=3)]
        assert FL.runs_needing_approval(runs) == [3, 7], "必须升序（确定性输出）"

    def test_ignores_other_conclusions(self):
        runs = [self._run(id=1, conclusion="success"),
                self._run(id=2, conclusion="failure"),
                self._run(id=3, conclusion=None, status="in_progress")]
        assert FL.runs_needing_approval(runs) == [], "只有 action_required 才需要批准"

    def test_ignores_non_pull_request_events(self):
        """只批准 `pull_request` 事件：别的触发面（push/schedule）不归本机制管（越权面收敛）。"""
        runs = [self._run(id=1, event="push"), self._run(id=2, event="workflow_run"),
                self._run(id=3, event="schedule")]
        assert FL.runs_needing_approval(runs) == []

    def test_workflow_allowlist_narrows_the_approval_surface(self):
        """**实测**：台账分支上还有 `Drift Audit` / `PR Issue Link Check` / `Deploy Reconcile`
        的 `action_required` run —— 批准**别的** workflow 不属本机制职责 ⇒ 白名单必须真的过滤。"""
        runs = [self._run(id=1, name="PR Check"),
                self._run(id=2, name="Drift Audit (真相源契约)"),
                self._run(id=3, name="Deploy Reconcile (PR 对账补偿)"),
                self._run(id=4, name="PR Issue Link Check"),
                self._run(id=5, name="Mini-App CI")]
        assert FL.runs_needing_approval(runs, workflows=FL.TRIAGED_WORKFLOWS) == [1, 5]
        # 不给白名单 ⇒ 退回「只看事实」口径（本函数不硬编码白名单副本）
        assert FL.runs_needing_approval(runs) == [1, 2, 3, 4, 5]

    def test_already_approved_run_is_not_selected_again(self):
        """幂等：批准后 `conclusion` 变 null、`run_attempt` +1 ⇒ 不会被重复批准。"""
        assert FL.runs_needing_approval([self._run(conclusion=None, status="queued",
                                                   run_attempt=2)]) == []

    def test_empty_and_malformed_input_is_not_silently_green(self):
        """空/畸形输入 ⇒ 空集（**不是**「通过」）——调用方据空集报「无需 approve」。"""
        assert FL.runs_needing_approval([]) == []
        assert FL.runs_needing_approval(None) == []
        assert FL.runs_needing_approval(["not-a-dict", 42]) == []
        assert FL.runs_needing_approval([{"id": "7", "event": "pull_request",
                                          "conclusion": "action_required"}]) == [], \
            "id 不是整数 ⇒ 不猜（宁可不批准，不可批准错对象）"

    def test_approve_runs_calls_the_rest_endpoint_per_run(self):
        calls = []

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return _Proc()

        original = FL.subprocess.run
        FL.subprocess.run = fake_run
        try:
            assert FL.approve_runs("o/r", [11, 22]) == [11, 22]
        finally:
            FL.subprocess.run = original
        assert calls == [["gh", "api", "-X", "POST", "repos/o/r/actions/runs/11/approve"],
                         ["gh", "api", "-X", "POST", "repos/o/r/actions/runs/22/approve"]], calls

    def test_approve_runs_is_fail_closed_on_api_error(self):
        """approve 失败**必须**抛错（不许静默）—— 否则「台账没 check」会装成「已经放行」。"""
        class _Proc:
            returncode = 1
            stdout = ""
            stderr = "HTTP 403: Resource not accessible by integration"

        def fake_run(cmd, **kw):
            return _Proc()

        original = FL.subprocess.run
        FL.subprocess.run = fake_run
        try:
            try:
                FL.approve_runs("o/r", [5])
            except RuntimeError as exc:
                assert "run 5" in str(exc) and "403" in str(exc)
            else:  # pragma: no cover
                raise AssertionError("approve 失败却未抛错 ⇒ fail-closed 缺失")
        finally:
            FL.subprocess.run = original

    def test_approve_cli_returns_nonzero_when_approval_fails(self, monkeypatch, tmp_path):
        """CLI 层同样 fail-closed（三态：0 正常 / 1 违规）——空集才是 0。"""
        # #5264：`approve` 还会解析**分支 tip**（第二次 API 调用）⇒ 桩按 path 分派（语义不变）
        listing = {"workflow_runs": [self._run(id=99, head_sha="a" * 40)]}
        monkeypatch.setattr(FL, "_gh_api",
                            lambda path: ({"commit": {"sha": "a" * 40}}
                                          if "/branches/" in path else listing))

        def boom(repo, ids):
            raise RuntimeError("run 99：HTTP 403")

        monkeypatch.setattr(FL, "approve_runs", boom)
        assert FL.main(["approve", "--repo", "o/r", "--head-branch", FL.LEDGER_BRANCH]) == 1

        monkeypatch.setattr(FL, "approve_runs", lambda repo, ids: list(ids))
        out = tmp_path / "approved.json"
        assert FL.main(["approve", "--repo", "o/r", "--head-branch", FL.LEDGER_BRANCH,
                        "--json-out", str(out)]) == 0
        assert json.loads(out.read_text(encoding="utf-8")) == [99]

    def test_approve_cli_is_clean_when_nothing_is_suppressed(self, monkeypatch):
        monkeypatch.setattr(FL, "_gh_api", lambda path: {"workflow_runs": []})
        assert FL.main(["approve", "--repo", "o/r", "--head-branch", FL.LEDGER_BRANCH]) == 0

    def test_approve_cli_queries_the_right_api_parameter(self, monkeypatch):
        """**实测踩过的坑**：`/actions/runs` 的分支过滤参数是 **`branch=`**；写成 `head_branch=`
        会被 API **静默忽略**（实测返回**全仓** 11867 个 run，而不是本分支的 13 个）
        ⇒ 批准面从「本分支」扩到「全仓」= 越权 + 无意义调用。故把参数名钉死。"""
        seen = []
        monkeypatch.setattr(FL, "_gh_api", lambda path: seen.append(path) or {"workflow_runs": []})
        assert FL.main(["approve", "--repo", "o/r", "--head-branch", FL.LEDGER_BRANCH]) == 0
        assert len(seen) == 1
        assert "branch=chore/flaky-ledger" in seen[0], seen
        assert "head_branch=" not in seen[0], f"参数名写错会被 API 静默忽略：{seen[0]}"
        assert "event=pull_request" in seen[0], seen


# ── ⑧ #5264：`_gh_api` 分页合并 + 「只批准分支 tip 那一批」（逐条注入式红证） ────────
#
# 病根（**实测读数**，别再重新猜）：`_gh_api` 走 `gh api --paginate --slurp`，多页合并时把
# **列表字段**用 `dict.update` 覆盖（只累加 `jobs`）⇒ 分页后**只剩最后一页**。于是
# `runs_needing_approval()` 只看得见最老那几条早已作废的 run ⇒ 恒返回 `[]` ⇒ `approve`
# **一次都没发出去** ⇒ 台账 PR 的 run 永远停在 `action_required`（0 job / 0 check）⇒
# auto-merge 永不触发 ⇒ 台账冻结。**跨过一页之后才静默失效**：落地时该分支 run 数 < 100
# ⇒ `--slurp` 单页 ⇒ 走单页短路（**那条路径是对的**，不是"当年有效是错觉"）。
#
# 本节判据一律用**合成 fixture**（本文件既有口径：不写死任何线上条数/阈值 —— 那些数字会腐烂）。


def _slurped_pages(sizes=(100, 100, 11)):
    """`gh api --paginate --slurp` 的**真实形状**：`[{…}, {…}, {…}]`，每页一个 `workflow_runs`。"""
    total, pages, rid = sum(sizes), [], 1
    for size in sizes:
        runs = []
        for _ in range(size):
            runs.append({"id": rid,
                         "name": FL.TRIAGED_WORKFLOWS[rid % len(FL.TRIAGED_WORKFLOWS)],
                         "event": "pull_request", "conclusion": "action_required",
                         "head_sha": f"{rid:040d}",
                         "created_at": f"2026-09-{rid % 28 + 1:02d}T00:00:00Z"})
            rid += 1
        pages.append({"total_count": total, "workflow_runs": runs})
    return pages


def pagination_violations(ns) -> list:
    """**独立判据**（喂任意模块命名空间，含变异体）：多页 slurped 结构必须**跨页累加**列表字段。

    两问缺一不可：① `_merge_pages` 纯 helper 直判；② `_gh_api` **端到端**（桩掉 `subprocess`，
    **不真起 `gh`**）—— 只测 helper 会漏掉「helper 修了、调用点仍是旧口径」这种半修。
    """
    bad = []
    pages = _slurped_pages()
    expected = [r["id"] for p in pages for r in p["workflow_runs"]]  # 现取，不写死条数

    merged = ns["_merge_pages"](json.loads(json.dumps(pages)))
    got = [r["id"] for r in (merged.get("workflow_runs") or [])]
    if got != expected:
        bad.append(f"分页合并丢了条目：拿到 {len(got)} 条、应 {len(expected)} 条"
                   f"（列表字段被每页覆盖 ⇒ 只剩最后一页）")
    if merged.get("total_count") != pages[-1]["total_count"]:
        bad.append(f"标量字段未覆盖：total_count={merged.get('total_count')!r}")

    class _Proc:
        returncode, stderr, stdout = 0, "", json.dumps(pages)

    saved = ns["subprocess"].run
    ns["subprocess"].run = lambda cmd, **kw: _Proc()
    try:
        via_api = ns["_gh_api"]("repos/o/r/actions/runs?event=pull_request&branch=b&per_page=100")
    finally:
        ns["subprocess"].run = saved
    api_ids = [r["id"] for r in (via_api.get("workflow_runs") or [])]
    if api_ids != expected:
        bad.append(f"`_gh_api` 端到端仍丢条目：{len(api_ids)} 条、应 {len(expected)} 条"
                   f"（helper 改对了但调用点没接上 = 没修）")
    return bad


def _push_runs(head_sha, first_id, day, names=None, conclusion="action_required"):
    """**一次推送**（= 同一个 `head_sha`）产生的那一批 run（形状与 REST `/actions/runs` 同源）。"""
    names = list(FL.TRIAGED_WORKFLOWS) if names is None else names
    return [{"id": first_id + i, "name": name, "event": "pull_request",
             "conclusion": conclusion, "status": "completed", "run_attempt": 1,
             "head_branch": FL.LEDGER_BRANCH, "head_sha": head_sha,
             "created_at": f"2026-09-{day:02d}T0{i}:00:00Z"}
            for i, name in enumerate(names)]


def _push_fixture():
    """**真实形态**：多个**陈旧 sha**（各 4 条白名单 run，全 `action_required`，日期递增）+ 最新 sha
    的 4 条（**最新日期** = 分支 tip；外加 `Drift Audit` / `PR Issue Link Check` 各 1 条 ——
    白名单外，**不许**被批准）。

    返回 `(runs, tip_sha, 陈旧 sha 的 run id 列表)`。
    """
    tip = "d" * 40
    runs = []
    for day, (sha, first_id) in enumerate((("a" * 40, 1000), ("b" * 40, 2000), ("c" * 40, 3000)),
                                          start=20):
        runs += _push_runs(sha, first_id, day)
    runs += _push_runs(tip, 4000, 23)
    runs += _push_runs(tip, 5000, 23, names=["Drift Audit (真相源契约)", "PR Issue Link Check"])
    return runs, tip, [r["id"] for r in runs if r["head_sha"] != tip]


def head_narrowing_violations(ns) -> list:
    """**独立判据**：批准面必须收窄到**分支 tip 那一次推送**（陈旧 SHA 一个都不许批）。"""
    bad = []
    runs, tip, stale_ids = _push_fixture()
    needing = set(ns["runs_needing_approval"](runs, workflows=ns["TRIAGED_WORKFLOWS"]))
    candidates = [r for r in runs if r["id"] in needing]
    selected = sorted(r["id"] for r in ns["runs_for_head"](candidates, tip))
    expected = sorted(r["id"] for r in runs
                      if r["head_sha"] == tip and r["name"] in ns["TRIAGED_WORKFLOWS"])
    if selected != expected:
        bad.append(f"tip 收窄结果不符：选中 {selected}、应恰为 tip 的候选 {expected}")
    leaked = sorted(set(selected) & set(stale_ids))
    if leaked:
        bad.append(f"**陈旧 SHA** 的 run 被选中（批准它们对 required 判定零贡献、只会放大 CI）：{leaked}")
    if selected and sorted(selected) == sorted(needing):
        bad.append("收窄等于「全批准」口径 ⇒ 分页修好后会一次批准上百个 workflow（CI 雪崩）")
    return bad


def _run_approve(ns, *, runs, tip, json_out=None):
    """桩掉 `_gh_api` / `approve_runs` 跑一次 `approve`（**绝不发真 POST**）。

    返回 `(rc, stdout, stderr, 批准调用记录, 查询过的 path)`。`tip=None` ⇒ 分支接口取不到 sha。
    """
    seen, approved = [], []
    saved = {k: ns[k] for k in ("_gh_api", "approve_runs")}

    def fake_api(path):
        seen.append(path)
        if "/branches/" in path:
            return {"commit": {"sha": tip}} if tip else {"name": ns["LEDGER_BRANCH"]}
        return {"workflow_runs": runs}

    def fake_approve(repo, ids):
        approved.append(list(ids))
        return list(ids)

    ns["_gh_api"], ns["approve_runs"] = fake_api, fake_approve
    argv = ["approve", "--repo", "o/r", "--head-branch", ns["LEDGER_BRANCH"]]
    if json_out is not None:
        argv += ["--json-out", str(json_out)]
    out, err, old = io.StringIO(), io.StringIO(), (sys.stdout, sys.stderr)
    sys.stdout, sys.stderr = out, err
    try:
        rc = ns["main"](argv)
    finally:
        sys.stdout, sys.stderr = old
        ns.update(saved)
    return rc, out.getvalue(), err.getvalue(), approved, seen


def approve_cli_violations(ns) -> list:
    """**独立判据**：`approve` 子命令的**四态**（喂任意模块命名空间 ⇒ 变异体也判）。

    ① 候选为空 ⇒ 退出 0 且**不查 tip**（快速路径与既有读数一字不变）；
    ② 候选非空但 tip 解析不到 ⇒ **fail-closed（非 0）**且**一个都不批**（不许退回「最新可见推送」）；
    ③ tip 上没有待批准 run（尚未创建 / 已批准）⇒ 退出 0、**不许**改去批准陈旧 SHA；
    ④ tip 上有候选 ⇒ **恰好**批 tip 那一批，且读数自洽（历史候选 N / tip / 本轮 M）+ `--json-out` 写本轮实际批准的 id。
    """
    bad = []
    tmpdir = tempfile.mkdtemp(prefix="migao-5264-")
    try:
        # ① 候选为空 —— 快速路径
        rc, out, _, approved, seen = _run_approve(ns, runs=[], tip="d" * 40)
        if rc != 0:
            bad.append(f"候选为空时退出码应为 0，实际 {rc}")
        if approved:
            bad.append(f"候选为空却仍发起 approve：{approved}")
        if any("/branches/" in p for p in seen):
            bad.append("候选为空时仍查询分支 tip ⇒ 快速路径退化（多一次无谓 API 调用）")
        if "无需 approve" not in out:
            bad.append(f"候选为空时的读数不再是既有那句：{out!r}")

        runs, tip, stale_ids = _push_fixture()
        needing = len(ns["runs_needing_approval"](runs, workflows=ns["TRIAGED_WORKFLOWS"]))

        # ② tip 解析不到 ⇒ fail-closed，零动作
        rc, out, err, approved, _ = _run_approve(ns, runs=runs, tip=None)
        if rc == 0:
            bad.append("tip 解析不到却退出 0 ⇒ 非 fail-closed（会把『无法判定』装成『已处理』）")
        if approved:
            bad.append(f"tip 解析不到却批准了 run：{approved}")
        if "无法确定" not in err or "fail-closed" not in err:
            bad.append(f"tip 解析不到时的报错没说清为什么不敢退回「最新可见推送」：{err!r}")

        # ③-a tip 上根本没有 run（只有陈旧 SHA 有待批准）⇒ 零动作、诚实读数
        rc, out, _, approved, _ = _run_approve(
            ns, runs=[r for r in runs if r["head_sha"] != tip], tip=tip)
        if rc != 0:
            bad.append(f"tip 无待批准 run 时应零动作退出 0，实际 {rc}")
        if approved:
            bad.append(f"tip 无待批准 run 时却批准了**陈旧 SHA**：{approved}")
        if "暂无待批准 run" not in out:
            bad.append(f"tip 无待批准 run 时缺诚实读数（不许说成已批准）：{out!r}")

        # ③-b tip 的 run **已批准**（conclusion=None）⇒ 幂等，不再命中
        already = [dict(r, conclusion=None, status="queued", run_attempt=2, id=r["id"] + 90000)
                   for r in runs if r["head_sha"] == tip] + \
                  [r for r in runs if r["head_sha"] != tip]
        rc, out, _, approved, _ = _run_approve(ns, runs=already, tip=tip)
        if rc != 0 or approved:
            bad.append(f"tip 已批准的 run 被重复批准（幂等失效）：rc={rc} approved={approved}")

        # ④ tip 上有候选 ⇒ 恰好那一批 + 读数自洽 + json_out 写本轮实际批准
        out_json = Path(tmpdir) / "approved.json"
        rc, out, _, approved, _ = _run_approve(ns, runs=runs, tip=tip, json_out=out_json)
        expected = sorted(r["id"] for r in runs
                          if r["head_sha"] == tip and r["name"] in ns["TRIAGED_WORKFLOWS"])
        if rc != 0:
            bad.append(f"tip 有候选时退出码应为 0，实际 {rc}")
        if approved != [expected]:
            bad.append(f"批准集合不是「恰好 tip 那一批」：{approved}、应 {[expected]}")
        if set(approved[0] if approved else []) & set(stale_ids):
            bad.append("批准集合里混进了**陈旧 SHA** 的 run")
        if json.loads(out_json.read_text(encoding="utf-8")) != expected:
            bad.append("`--json-out` 写的不是本轮实际批准的 id 列表（workflow 侧据它读 PENDING）")
        for frag in (f"历史待批准 {needing} 个", f"属于分支 tip={tip} 的 {len(expected)} 个"):
            if frag not in out:
                bad.append(f"读数与事实不自洽（缺 `{frag}`）：{out!r}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return bad


def _mutant(*replacements):
    """把真实脚本源码做**内容级单点变异**后 `exec` 成命名空间（不写盘、不留变异产物）。

    `__file__` 指向真实路径 ⇒ 模块级 `LEDGER_PATH` 等派生量照旧可解析（本函数不落任何文件）。
    注入锚点写错 ⇒ **立刻断言失败**（防止"锚点失效 ⇒ 变异体其实没变 ⇒ 红证假绿"）。
    """
    src = (SCRIPTS / "flaky_ledger.py").read_text(encoding="utf-8")
    for old, new in replacements:
        assert old in src, f"注入锚点失效（先修本测试）：{old!r}"
        src = src.replace(old, new, 1)
    ns = {"__name__": "migao_flaky_ledger_mutant", "__file__": str(SCRIPTS / "flaky_ledger.py")}
    exec(compile(src, str(SCRIPTS / "flaky_ledger.py"), "exec"), ns)
    return ns


class TestApprovePaginationAndTipNarrowing:
    """#5264：**分页必须跨页累加** + **只批准分支 tip 那一批**（每问都可单独变红）。"""

    # ── ① 分页合并 ──────────────────────────────────────────────────────────

    def test_merge_pages_accumulates_lists_and_overwrites_scalars(self):
        pages = _slurped_pages()
        merged = FL._merge_pages(pages)
        assert [r["id"] for r in merged["workflow_runs"]] == \
            [r["id"] for p in pages for r in p["workflow_runs"]], \
            "列表字段必须**跨页累加**（旧口径 `update` 覆盖 ⇒ 只剩最后一页）"
        assert len(merged["workflow_runs"]) == sum(len(p["workflow_runs"]) for p in pages)
        assert merged["total_count"] == pages[-1]["total_count"], "标量字段取覆盖"

    def test_merge_pages_does_not_mutate_the_input_pages(self):
        pages = _slurped_pages((2, 3))
        before = json.dumps(pages, sort_keys=True)
        FL._merge_pages(pages)
        assert json.dumps(pages, sort_keys=True) == before, "合并不许就地改输入（既有调用方可能复用）"

    def test_gh_api_merges_end_to_end_and_keeps_single_page_shortcut(self):
        """只测 helper 会漏掉「helper 修了、调用点还是旧口径」⇒ 端到端桩掉 subprocess（**不真起 gh**）。"""
        def call(payload):
            class _Proc:
                returncode, stderr, stdout = 0, "", json.dumps(payload)

            saved = FL.subprocess.run
            FL.subprocess.run = lambda cmd, **kw: _Proc()
            try:
                return FL._gh_api("repos/o/r/x")
            finally:
                FL.subprocess.run = saved

        pages = _slurped_pages()
        merged = call(pages)
        assert [r["id"] for r in merged["workflow_runs"]] == \
            [r["id"] for p in pages for r in p["workflow_runs"]], "`_gh_api` 必须真的走修好的合并"
        assert merged["total_count"] == pages[-1]["total_count"]
        assert call([{"jobs": [{"name": "a"}]}, {"jobs": [{"name": "b"}]}])["jobs"] == \
            [{"name": "a"}, {"name": "b"}], "`jobs` 的最终形态仍是**扁平累加**（不是分页嵌套）"
        single = {"total_count": 1, "workflow_runs": [{"id": 7}], "jobs": [{"name": "j"}]}
        assert call([single]) == single, "单页必须走**短路**（原样返回；那条路径本来就是对的）"

    def test_real_flaky_ledger_satisfies_pagination_invariants(self):
        assert pagination_violations(vars(FL)) == []

    # ── ② 分支 tip 解析 + 收窄 ──────────────────────────────────────────────

    def test_branch_tip_parses_commit_sha_and_rejects_malformed(self):
        sha = "519250fe9bf175bcf0a735a0b08969e376382409"
        assert FL.branch_tip({"name": FL.LEDGER_BRANCH, "commit": {"sha": sha}}) == sha
        bads = [{}, {"commit": {}}, {"commit": {"sha": ""}}, {"commit": "not-a-dict"},
                [{"commit": {"sha": sha}}], None, {"commit": {"sha": 42}}, {"name": "x", "commit": None}]
        assert [FL.branch_tip(b) for b in bads] == [None] * len(bads), \
            "畸形/取不到 ⇒ 必须显式 `None`（调用方据此 fail-closed，不许猜）"

    def test_only_the_tip_push_is_selected(self):
        runs, tip, stale_ids = _push_fixture()
        needing = set(FL.runs_needing_approval(runs, workflows=FL.TRIAGED_WORKFLOWS))
        candidates = [r for r in runs if r["id"] in needing]
        selected = sorted(r["id"] for r in FL.runs_for_head(candidates, tip))
        expected = sorted(r["id"] for r in runs
                          if r["head_sha"] == tip and r["name"] in FL.TRIAGED_WORKFLOWS)
        assert selected == expected, (selected, expected)
        assert set(selected) & set(stale_ids) == set(), \
            "**陈旧 SHA** 的 run 绝不许被批准（挂在旧 commit 上，对 required 判定零贡献）"
        assert len(selected) < len(needing), \
            "收窄必须真的窄于「全批准」口径（分页修好后候选是几十上百个 ⇒ 全批准 = CI 雪崩）"
        unlisted = {r["id"] for r in runs if r["name"] not in FL.TRIAGED_WORKFLOWS}
        assert set(selected) & unlisted == set(), "白名单外的 run 不许被批准（白名单一字未动）"

    def test_real_flaky_ledger_satisfies_head_narrowing_invariants(self):
        assert head_narrowing_violations(vars(FL)) == []

    # ── ③ 幂等 / 边界 ──────────────────────────────────────────────────────

    def test_already_approved_tip_runs_are_not_reselected(self):
        """幂等沿用既有口径：批准后 `conclusion` 变 null、`run_attempt` +1 ⇒ 不再命中。"""
        runs, tip, _ = _push_fixture()
        already = [dict(r, conclusion=None, status="queued", run_attempt=2)
                   for r in runs if r["head_sha"] == tip]
        needing = set(FL.runs_needing_approval(already, workflows=FL.TRIAGED_WORKFLOWS))
        assert needing == set(), "tip 上已批准的 run 不许再进候选"
        assert FL.runs_for_head([r for r in already if r["id"] in needing], tip) == []

    def test_runs_for_head_without_a_sha_selects_nothing(self):
        runs, tip, _ = _push_fixture()
        assert [FL.runs_for_head(runs, s) for s in ("", None)] == [[], []], \
            "tip 为空 ⇒ 空集（**不是**「全批准」）"
        assert FL.runs_for_head(None, tip) == []
        assert FL.runs_for_head(["not-a-dict", 42], tip) == []

    # ── ④ CLI 四态 ─────────────────────────────────────────────────────────

    def test_cli_fast_path_when_nothing_is_suppressed(self):
        rc, out, _, approved, seen = _run_approve(vars(FL), runs=[], tip="d" * 40)
        assert (rc, approved) == (0, []), (rc, approved)
        assert [p for p in seen if "/branches/" in p] == [], "候选为空时不该多查一次 tip"
        assert "无需 approve" in out, out

    def test_cli_is_fail_closed_when_branch_tip_cannot_be_resolved(self):
        """**不许**退回「最新可见的待批准 run 的 sha」—— 那会把陈旧 SHA 当本次推送批准掉。"""
        runs, _, stale_ids = _push_fixture()
        rc, _, err, approved, _ = _run_approve(vars(FL), runs=runs, tip=None)
        assert (rc, approved) == (1, []), (rc, approved)
        assert len(stale_ids) > 0, "夹具前提：必须先存在陈旧 SHA 的待批准 run，否则本用例无意义"
        assert "无法确定" in err and "fail-closed" in err, err

    def test_cli_takes_zero_action_when_tip_has_no_pending_run(self):
        runs, tip, _ = _push_fixture()
        only_stale = [r for r in runs if r["head_sha"] != tip]
        rc, out, _, approved, _ = _run_approve(vars(FL), runs=only_stale, tip=tip)
        assert (rc, approved) == (0, []), (rc, approved)
        assert f"tip={tip}" in out and "暂无待批准 run" in out, out

    def test_cli_approves_exactly_the_tip_runs_with_self_consistent_readout(self, tmp_path):
        runs, tip, stale_ids = _push_fixture()
        out_json = tmp_path / "approved.json"
        rc, out, _, approved, _ = _run_approve(vars(FL), runs=runs, tip=tip, json_out=out_json)
        expected = sorted(r["id"] for r in runs
                          if r["head_sha"] == tip and r["name"] in FL.TRIAGED_WORKFLOWS)
        needing = len(FL.runs_needing_approval(runs, workflows=FL.TRIAGED_WORKFLOWS))
        assert (rc, approved) == (0, [expected]), (rc, approved, expected)
        assert set(approved[0]) & set(stale_ids) == set(), approved
        assert json.loads(out_json.read_text(encoding="utf-8")) == expected
        assert f"历史待批准 {needing} 个" in out and f"属于分支 tip={tip} 的 {len(expected)} 个" in out, out

    def test_real_approve_cli_satisfies_all_four_states(self):
        assert approve_cli_violations(vars(FL)) == []


class TestApproveFixRedProofs:
    """**红证**：把修复点**逐条单点变异**回去 ⇒ 对应判据必须红（不会红的判据 = 空断言）。

    变异走**源码文本**（`_mutant`）而不是 import 变异体文件 ⇒ 无缓存可污染，也**不提交**变异代码。
    """

    def test_red_proof_reverting_the_merge_to_overwrite(self):
        """变异点 ①：`_merge_pages` 的「列表 ⇒ 累加」退回旧口径（`update` 覆盖）⇒ 分页判据必红。"""
        mutant = _mutant(("                merged[key] = (prev if isinstance(prev, list) else []) + list(value)",
                          "                merged[key] = value"))
        assert pagination_violations(vars(FL)) == [], "真实实现先要绿，红证才有意义"
        violations = pagination_violations(mutant)
        assert violations, "退回覆盖式合并后仍判绿 ⇒ 分页判据是**空断言**"
        assert any("丢了条目" in v for v in violations), violations

    def test_red_proof_dropping_the_head_narrowing(self):
        """变异点 ②：`runs_for_head` 不再按 sha 过滤（= 退回「全批准」）⇒ 收窄判据必红。"""
        mutant = _mutant(('if isinstance(r, dict) and r.get("head_sha") == head_sha]',
                          'if isinstance(r, dict)]'))
        assert head_narrowing_violations(vars(FL)) == []
        violations = head_narrowing_violations(mutant)
        assert violations, "去掉按 tip 收窄后仍判绿 ⇒ 收窄判据是**空断言**"
        assert any("陈旧 SHA" in v for v in violations), violations

    def test_red_proof_cli_dropping_the_narrowing_step(self):
        """变异点 ③：CLI 里**不套用**收窄（直接批准全部候选）⇒ CLI 判据必红。"""
        mutant = _mutant(('pending = sorted(runs_for_head(candidates, tip), key=lambda r: r["id"])',
                          'pending = sorted(candidates, key=lambda r: r["id"])'))
        assert approve_cli_violations(vars(FL)) == []
        violations = approve_cli_violations(mutant)
        assert violations, "CLI 不套用收窄后仍判绿 ⇒ 四态判据是**空断言**"
        assert any("陈旧 SHA" in v for v in violations), violations

    def test_red_proof_replacing_branch_tip_with_latest_visible_run(self):
        """变异点 ④：tip 退回「最新**可见**的待批准 run 的 sha」（被明确禁止的退回）⇒ CLI 判据必红。"""
        mutant = _mutant(
            ('tip = branch_tip(_gh_api(f"repos/{args.repo}/branches/{args.head_branch}"))',
             'tip = max(candidates, key=lambda r: r.get("created_at") or "").get("head_sha")'))
        violations = approve_cli_violations(mutant)
        assert violations, "退回「最新可见推送」后仍判绿 ⇒ 该判据盖不住这个退回"
        assert any("陈旧 SHA" in v or "fail-closed" in v for v in violations), violations

    def test_red_proof_dropping_the_action_required_filter(self):
        """变异点 ⑤：`runs_needing_approval` 去掉 `action_required` 判定 ⇒ 幂等判据必红。"""
        mutant = _mutant(('if run.get("conclusion") != "action_required":', "if False:"))
        assert approve_cli_violations(vars(FL)) == []
        violations = approve_cli_violations(mutant)
        assert violations, "去掉 `action_required` 判定后仍判绿 ⇒ 幂等判据是**空断言**"
        assert any("幂等" in v for v in violations), violations
