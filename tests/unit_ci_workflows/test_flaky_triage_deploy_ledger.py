# case_ids: MC-012
"""部署腿的「**只记台账、不重跑**」承接面（issue #6455）—— L0，离线、零 LLM、秒级。

病（issue #6455 / PR #6452 实测，不是推断）
------------------------------------------
`Build and Deploy frontend (admin-web)` 的**单测步**偶发红（`CuttingHeightConfigPanel.test.tsx`
取配置与断言的时序竞争）⇒ 那次改动**没上线**（部署腿整条失败、`Post-Deploy Frontend Probe`
skipped），靠 `Deploy Reconcile` 的延迟补偿才生效，而用户在此期间看到的是**旧构建**。
为什么没有任何机制接住它：部署腿被**有意**排除在 `TRIAGED_WORKFLOWS` 之外（重跑**有副作用**：
会真的部署 —— 这条理由成立，本单**一个字都不动**）⇒ 它的失败**既不重跑、也不进台账**
（365 条里没有 `CuttingHeight`）⇒「偶发」**永远不可度量**（`flaky-triage.yml` 只对 PR 腿生效）。

裁定 = **方案 A**：只加承接面，不动「部署腿不重跑」。本文件锁的三件事
--------------------------------------------------------------------
① **部署腿失败 ⇒ 台账有条目、且 rerun 调用 0 次**：`decide()` 产出 `record_deploy`，
   条目的 `kind=unknown`（#5088：没有第二次尝试 ⇒ **无归因凭据**）+ `rerun_result=not_rerun`；
   且 workflow 里 `gh run rerun` **恰好一处**、只由 `action == 'rerun'` 独占
   ⇒ `record_deploy` **结构上**到不了重跑那一步。
② **PR 腿仍走既有 rerun 路径**（语义一字未动：首次失败 ⇒ `rerun`；第二次绿 ⇒ `mark_flaky`；
   第二次仍红 ⇒ `record_both_red`）。
③ **限流态 ⇒ 零动作**（#8444① 的熔断**不回归**：部署腿也不例外 —— `skip` + `rate_limited=True`，
   零 rerun / 零记账 / 零推台账）。

红证（每条**单独**都能变红；注入方式逐条见 `TestRedProofs`，PR body 也照抄一份）
------------------------------------------------------------------------------
· 摘掉部署腿的记账分支（`if name in DEPLOY_RECORD_WORKFLOWS:` → `if False:`）⇒ ① 红（退化成 `skip`）；
· 让部署腿**只走分流白名单**（`and name in TRIAGED_WORKFLOWS`）= 想复用它去重跑 ⇒ ① 红（`event !=
  pull_request` ⇒ `skip` ⇒ 台账空）；把部署腿塞进 `TRIAGED_WORKFLOWS` ⇒ 「不在重跑白名单」判据红；
· 把条目改成 `kind=flaky` ⇒ 台账 `ledger_violations` 红（「放行了未复现的失败」）；
· 摘掉评论步的 `pr != ''` 闸门 ⇒ 部署腿（无 PR）会去 POST `issues//comments` ⇒ fail-closed 判红；
· 摘掉限流熔断 ⇒ ③ 红（限流态被记账）；
· 从触发面删掉任一部署腿 ⇒ 接线判据红（且 `test_flaky_triage.py::audit_workflow` 同时红）。

`case_ids` 沿用本目录既有惯例：CI 结构类 L0 不变式统一挂 `MC-012`
（`.github/cases/misc.yml`：CI workflow 行为由 `tests/unit_ci_workflows/` 单测验证）——
与 10 个同族 `test_flaky_*.py` 一致。⚠️ **未改 `cases/**`**（Case Trust 缴费要求）。
"""
import copy
import importlib.util
import json
import re
import subprocess
import sys
import types
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".github" / "scripts"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
WORKFLOW_PATH = WORKFLOWS / "flaky-triage.yml"
REAL_WORKFLOW_TEXT = WORKFLOW_PATH.read_text(encoding="utf-8")
#: 脚本源码本体（红证用它做**内容变异** ⇒ 免疫 `.pyc` 缓存；判据读内容，不读 mtime/size）。
REAL_SCRIPT_SOURCE = (SCRIPTS / "flaky_ledger.py").read_text(encoding="utf-8")

#: 部署腿的**豁免**（不进「只记台账」面的具名理由；`registry_violations` 要求理由非空）。
#: 口径：只收「失败信号有自己的承接面 / 失败 = 受控动作被拒」的那些部署腿 ——
#: **不是**「重跑有副作用」的通用豁免（那会把这本台账变成「什么都没记」）。
DEPLOY_RECORD_EXEMPT = {
    "Deploy Production (受控发布)":
        "**手动受控发布**腿（`workflow_dispatch` 起）：失败 = 这一次发布被拒，发起人当场看到；"
        "它不承载「合入的构建是否正常」这个信号，且「受控」语义与自动记账/重跑都冲突。",
    "Deploy Reconcile (PR 对账补偿)":
        "**对账补偿**腿：它的失败由自己的值守面承接（对账汇总 / `deploy-watchdog`），"
        "记进 flaky 台账会把「对账动作失败」与「被测对象失败」混同（两病因两个出路）。",
}


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_mutant(source: str, name: str):
    """把**内容变异**后的脚本源码当模块加载（红证用：判据读内容，免疫 `.pyc` 缓存）。"""
    namespace = {"__name__": name, "__file__": str(SCRIPTS / "flaky_ledger.py")}
    exec(compile(source, f"<mutant:{name}>", "exec"), namespace)  # noqa: S102 - 自造变异体
    return types.SimpleNamespace(**namespace)


FL = _load(SCRIPTS / "flaky_ledger.py", "migao_flaky_ledger_deploy")


def _workflow(src=None):
    return yaml.safe_load(REAL_WORKFLOW_TEXT if src is None else src) or {}


def _on_section(wf):
    """YAML 1.1 把 `on:` 解析成布尔 `True`（既有同族判据也这样取，别只试 `"on"`）。"""
    return wf.get("on") or wf.get(True) or {}


def _steps(wf=None):
    return ((_workflow(wf).get("jobs") or {}).get("triage") or {}).get("steps") or []


def _step_text(step) -> str:
    parts = [step.get("run") or "", str((step.get("with") or {}).get("script") or "")]
    env = step.get("env")
    if isinstance(env, dict):
        parts.extend(str(v) for v in env.values())
    return "\n".join(parts)


def _rerun_steps(wf=None):
    return [s for s in _steps(wf) if "gh run rerun" in _step_text(s)]


def _comment_steps(wf=None):
    return [s for s in _steps(wf)
            if "issues/" in _step_text(s) and "comments" in _step_text(s)]


# ── 夹具（形状与 GitHub REST `/actions/runs/{id}` + `/attempts/{n}/jobs` 同源） ──


def make_run(name=None, attempt=1, conclusion="failure", event="push",
             branch="main", pr=None, run_id=6455,
             sha="b" * 40, updated="2026-11-02T10:00:00Z"):
    return {
        "id": run_id,
        "name": name if name is not None else FL.DEPLOY_RECORD_WORKFLOWS[1],
        "event": event,
        "conclusion": conclusion,
        "run_attempt": attempt,
        "head_branch": branch,
        "head_sha": sha,
        "html_url": f"https://github.com/o/r/actions/runs/{run_id}",
        "updated_at": updated,
        "pull_requests": [{"number": pr}] if pr else [],
    }


def make_job(name="admin-web typecheck + unit tests", conclusion="failure",
             failed_step="Run unit tests"):
    if conclusion != "failure":
        steps = [{"name": "Run unit tests", "conclusion": conclusion}]
    else:
        steps = [
            {"name": "Set up job", "conclusion": "success"},
            {"name": "Run actions/checkout@v7", "conclusion": "success"},
            {"name": failed_step, "conclusion": "failure"},
        ]
    return {"name": name, "conclusion": conclusion, "steps": steps}


def bundle(run=None, jobs=None, prior_jobs=None, rate_limit=None):
    return {"run": run if run is not None else make_run(),
            "jobs": jobs if jobs is not None else [make_job()],
            "prior_jobs": prior_jobs,
            "rate_limit": rate_limit}


# ── ① 部署腿失败 ⇒ 台账有条目、rerun 0 次 ──────────────────────────────────────


class TestDeployLegIsRecordedOnly:
    def test_every_registered_deploy_leg_records_exactly_one_entry(self):
        for name in FL.DEPLOY_RECORD_WORKFLOWS:
            d = FL.decide(bundle(run=make_run(name=name)))
            assert d["action"] == "record_deploy", (name, d)
            assert d["kind"] == "unknown", (name, d)
            assert len(d["entries"]) == 1, (name, d)
            entry = d["entries"][0]
            assert entry["workflow"] == name, entry
            assert entry["job"] == "admin-web typecheck + unit tests", entry
            assert entry["run_id"] == 6455, entry
            assert entry["first_failure_step"] == "Run unit tests", entry
            # 事实（不是「重跑失败」）：本腿**从不重跑**
            assert entry["rerun_result"] == "not_rerun", entry
            # #5088：没有第二次尝试 ⇒ 无归因凭据（不记 flaky、也不记 infra_suspect）
            assert entry["kind"] == "unknown" and entry["unknown_reason"].strip(), entry

    def test_zero_rerun_is_structural_not_just_a_decision_value(self):
        """`gh run rerun` **恰好一处**且只认 `action == 'rerun'` ⇒ `record_deploy` 到不了它。"""
        rerun = _rerun_steps()
        assert len(rerun) == 1, [s.get("name") for s in _steps()]
        assert str(rerun[0].get("if") or "").strip() == \
            "steps.decide.outputs.action == 'rerun'", rerun[0].get("if")
        for step in _steps():
            assert "record_deploy" not in str(step.get("if") or ""), step.get("name")

    def test_recorded_entry_passes_every_ledger_write_gate(self):
        """**真的能写进台账**（否则「有条目」只是判定里的一个字段）。"""
        entries = FL.decide(bundle())["entries"]
        assert FL.new_entry_tracking_violations(entries) == []
        ledger = {"version": 2, "note": "", "_schema": {}, "entries": entries}
        assert FL.ledger_violations(ledger) == []
        assert FL.reconcile(ledger) == {"new_events": [], "duplicates": [],
                                        "fixed_not_deducted": []}
        added, skipped = FL.append_entries({"entries": []}, entries)
        assert len(added) == 1 and skipped == []
        assert FL.append_entries({"entries": entries}, entries)[0] == []  # 幂等

    def test_non_failure_conclusions_are_zero_action(self):
        for conclusion in ("success", "cancelled", "timed_out", "startup_failure", "skipped"):
            d = FL.decide(bundle(run=make_run(conclusion=conclusion),
                                 jobs=[make_job(conclusion=conclusion)]))
            assert d["action"] == "skip", (conclusion, d)
            assert d["entries"] == [], (conclusion, d)

    def test_failure_without_any_failed_job_is_zero_action(self):
        d = FL.decide(bundle(jobs=[]))
        assert d["action"] == "skip" and d["entries"] == [], d

    def test_workflow_explains_why_record_only(self):
        """「部署腿偶发**不可度量**」必须写在 workflow 注释里（否则下一个人只会看到 `deploy-*`）。"""
        assert "不可度量" in REAL_WORKFLOW_TEXT

    def test_cli_end_to_end_emits_entry_count_and_no_pr(self, tmp_path):
        """直连**真入口**（CLI）：workflow 消费的三个输出必须齐（`action` / `entry_count` / `pr`）。"""
        bundle_path = tmp_path / "bundle.json"
        entries_path = tmp_path / "entries.json"
        out_path = tmp_path / "out.txt"
        bundle_path.write_text(json.dumps(bundle()), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "flaky_ledger.py"), "decide",
             "--bundle", str(bundle_path), "--entries-out", str(entries_path),
             "--gh-output", str(out_path)],
            capture_output=True, text=True, cwd=str(REPO_ROOT))
        assert proc.returncode == 0, proc.stderr
        out = out_path.read_text(encoding="utf-8")
        assert "action=record_deploy" in out, out
        assert "entry_count=1" in out, out
        assert "pr=\n" in out, out  # 部署腿没有 PR ⇒ 评论步必须靠 `pr != ''` 才不发
        assert len(json.loads(entries_path.read_text(encoding="utf-8"))) == 1
        # 汇总行（job summary 由 workflow 的 `| tee -a` 写）：action 必须**看得见**
        assert "action=`record_deploy`" in proc.stdout, proc.stdout


# ── ② PR 腿仍走既有 rerun 路径（不变） ────────────────────────────────────────


class TestPrLegsUnchanged:
    def test_first_failure_still_reruns_once(self):
        d = FL.decide(bundle(run=make_run(name="PR Check", event="pull_request", pr=6455)))
        assert d["action"] == "rerun", d
        assert d["entries"] == [], d

    def test_second_attempt_green_still_marks_flaky(self):
        d = FL.decide(bundle(
            run=make_run(name="PR Check", event="pull_request", pr=6455, attempt=2,
                         conclusion="success", updated="2026-11-02T10:10:00Z"),
            jobs=[make_job(conclusion="success")],
            prior_jobs=[make_job()]))
        assert d["action"] == "mark_flaky", d

    def test_second_attempt_red_is_record_both_red(self):
        d = FL.decide(bundle(
            run=make_run(name="PR Check", event="pull_request", pr=6455, attempt=2,
                         updated="2026-11-02T10:10:00Z"),
            jobs=[make_job()],
            prior_jobs=[make_job()]))
        assert d["action"] == "record_both_red", d

    def test_pr_leg_decisions_are_not_record_deploy(self):
        """部署腿的记账动作**不许**串到 PR 腿（否则 PR 腿会丢 rerun）。"""
        for conclusion, attempt in (("failure", 1), ("failure", 2), ("success", 1)):
            d = FL.decide(bundle(run=make_run(name="PR Check", event="pull_request",
                                              pr=6455, attempt=attempt,
                                              conclusion=conclusion)))
            assert d["action"] != "record_deploy", (conclusion, attempt, d)


# ── ③ 限流态 ⇒ 零动作（#8444① 不回归） ──────────────────────────────────────


class TestRateLimitBreakerNotRegressed:
    def test_deploy_leg_under_rate_limit_is_zero_action(self):
        d = FL.decide(bundle(rate_limit={"limited": True, "remaining": 0,
                                         "reset": "2026-11-02T12:00:00Z"}))
        assert d["action"] == "skip", d
        assert d.get("rate_limited") is True, d
        assert d["entries"] == [], d

    def test_pr_leg_under_rate_limit_is_zero_action(self):
        d = FL.decide(bundle(run=make_run(name="PR Check", event="pull_request", pr=6455),
                             rate_limit={"limited": True, "remaining": 0}))
        assert d["action"] == "skip" and d.get("rate_limited") is True, d
        assert d["entries"] == [], d

    def test_breaker_is_checked_before_the_deploy_branch(self):
        """顺序即判据：熔断**先于**部署腿分支（否则限流态会被记成「有失败」且放大闭环）。"""
        src = REAL_SCRIPT_SOURCE
        assert src.index("rate.get(\"limited\")") < src.index("if name in DEPLOY_RECORD_WORKFLOWS:")


# ── 接线与类级元守卫 ─────────────────────────────────────────────────────────


def _deploy_workflow_names():
    """现取 `.github/workflows/deploy-*.yml` 的 `name:`（真对象，不是硬编码清单）。"""
    found = {}
    for path in sorted(WORKFLOWS.glob("deploy-*.yml")):
        m = re.search(r"(?m)^name:\s*(.+?)\s*$", path.read_text(encoding="utf-8"))
        if m:
            found[path.name] = m.group(1).strip()
    return found


def registry_violations(found, registered, exempt):
    """**未登记即红**（纯函数，便于注入）。返回违规清单，空 = 合规。"""
    bad = []
    registered = list(registered or ())
    exempt = dict(exempt or {})
    names = set((found or {}).values())
    for fname, name in sorted((found or {}).items()):
        if name in registered:
            continue
        if name in exempt:
            if not str(exempt[name] or "").strip():
                bad.append(f"{fname}: 豁免 `{name}` 没有写明理由 ⇒ 豁免台账不许变成「什么都不记」")
            continue
        bad.append(f"{fname}: 部署腿 `{name}` 未登记 —— 要么进 `DEPLOY_RECORD_WORKFLOWS`"
                   f"（只记台账、不重跑），要么在 `DEPLOY_RECORD_EXEMPT` 里写明豁免理由")
    for name in registered:
        if name not in names:
            bad.append(f"登记了**不存在**的部署腿 `{name}`（phantom 登记 ⇒ 判据在自欺）")
    for name in exempt:
        if name not in names:
            bad.append(f"豁免了**不存在**的部署腿 `{name}`（phantom 豁免）")
    return bad


class TestRegistryMetaGuard:
    def test_every_deploy_workflow_is_registered_or_explicitly_exempt(self):
        assert registry_violations(_deploy_workflow_names(), FL.DEPLOY_RECORD_WORKFLOWS,
                                   DEPLOY_RECORD_EXEMPT) == []

    def test_registered_names_are_real_workflows(self):
        names = set(_deploy_workflow_names().values())
        for name in FL.DEPLOY_RECORD_WORKFLOWS:
            assert name in names, f"{name} 不在 .github/workflows/deploy-*.yml 的 `name:` 里"

    def test_deploy_legs_are_not_in_the_rerun_allowlist(self):
        """红线（#4717 既有裁定）：重跑有副作用的腿**绝不许**进分流白名单。"""
        assert set(FL.DEPLOY_RECORD_WORKFLOWS) & set(FL.TRIAGED_WORKFLOWS) == set()


class TestWorkflowWiring:
    def test_trigger_face_equals_allowlist_plus_record_legs(self):
        """接线（§28.2）：触发面必须**恰好**是「分流白名单 ∪ 记账腿」—— 多一个/少一个都红。"""
        wr = _on_section(_workflow())["workflow_run"]
        expected = sorted(set(FL.TRIAGED_WORKFLOWS) | set(FL.DEPLOY_RECORD_WORKFLOWS))
        assert sorted(wr.get("workflows") or []) == expected, wr.get("workflows")

    def test_comment_step_is_gated_on_having_a_pr(self):
        """部署腿没有 PR ⇒ 评论步必须带 `pr != ''`（否则 `issues//comments` 404 ⇒ 整条链红）。"""
        steps = _comment_steps()
        assert steps, "没有 PR 评论步骤（既有判据也要它）"
        for step in steps:
            assert "pr != ''" in str(step.get("if") or ""), step.get("name")


# ── 红证（各能**单独**变红；注入方式照抄进 PR body） ────────────────────────


class TestRedProofs:
    def test_red_proof_1_removing_the_record_branch(self):
        mutated = REAL_SCRIPT_SOURCE.replace(
            "    if name in DEPLOY_RECORD_WORKFLOWS:\n", "    if False:  # mutated\n", 1)
        assert mutated != REAL_SCRIPT_SOURCE, "注入锚点失效（先修本测试）"
        mutant = _load_mutant(mutated, "flaky_ledger_no_deploy_branch")
        d = mutant.decide(bundle(run=make_run(name=mutant.DEPLOY_RECORD_WORKFLOWS[0])))
        assert d["action"] == "skip" and d["entries"] == [], \
            f"摘掉记账分支后部署腿必须退化成 skip（台账空）⇒ ① 会红：{d}"

    def test_red_proof_2_reusing_the_rerun_allowlist_too(self):
        """`and name in TRIAGED_WORKFLOWS` = 想用重跑白名单兼做记账面 ⇒ 部署腿被 skip（① 红）。"""
        mutated = REAL_SCRIPT_SOURCE.replace(
            "    if name in DEPLOY_RECORD_WORKFLOWS:\n",
            "    if name in DEPLOY_RECORD_WORKFLOWS and name in TRIAGED_WORKFLOWS:  # mutated\n", 1)
        assert mutated != REAL_SCRIPT_SOURCE, "注入锚点失效（先修本测试）"
        mutant = _load_mutant(mutated, "flaky_ledger_allowlist_coupled")
        assert mutant.decide(bundle())["action"] == "skip", "耦合白名单后仍然记账 ⇒ 本红证没判别力"

    def test_red_proof_2b_allowlist_pollution_is_caught(self):
        mutated = REAL_SCRIPT_SOURCE.replace(
            '    "Bmini-App CI",\n)', '    "Bmini-App CI",\n    "Build and Deploy admin-api",\n)', 1)
        assert mutated != REAL_SCRIPT_SOURCE, "注入锚点失效（先修本测试）"
        mutant = _load_mutant(mutated, "flaky_ledger_allowlist_polluted")
        assert set(mutant.DEPLOY_RECORD_WORKFLOWS) & set(mutant.TRIAGED_WORKFLOWS) == \
            {"Build and Deploy admin-api"}, "污染注入没生效"
        # ⇒ `test_deploy_legs_are_not_in_the_rerun_allowlist` 会红

    def test_red_proof_3_kind_flaky_is_caught_by_the_ledger(self):
        """把条目记成 `flaky`（= 放行一条**没有重跑证据**的失败）⇒ 台账判据必红。"""
        entries = copy.deepcopy(FL.decide(bundle())["entries"])
        for entry in entries:
            entry["kind"] = "flaky"
        bad = FL.ledger_violations({"version": 2, "note": "", "_schema": {}, "entries": entries})
        assert any("放行了未复现的失败" in v for v in bad), bad

    def test_red_proof_4_removing_the_pr_gate(self):
        mutated = REAL_WORKFLOW_TEXT.replace(
            "        if: steps.decide.outputs.entry_count != '0' && steps.decide.outputs.pr != ''",
            "        if: steps.decide.outputs.entry_count != '0'", 1)
        assert mutated != REAL_WORKFLOW_TEXT, "注入锚点失效（先修本测试）"
        steps = _comment_steps(mutated)
        assert steps and all("pr != ''" not in str(s.get("if") or "") for s in steps), \
            "摘掉 pr 闸门后判据必须红（部署腿无 PR 会去 POST issues//comments ⇒ fail-closed）"

    def test_red_proof_5_removing_the_rate_limit_breaker(self):
        mutated = REAL_SCRIPT_SOURCE.replace(
            '    if isinstance(rate, dict) and rate.get("limited"):',
            "    if False:  # mutated", 1)
        assert mutated != REAL_SCRIPT_SOURCE, "注入锚点失效（先修本测试）"
        mutant = _load_mutant(mutated, "flaky_ledger_no_breaker")
        d = mutant.decide(bundle(rate_limit={"limited": True, "remaining": 0}))
        assert d["action"] == "record_deploy", \
            f"摘掉熔断后限流态的部署腿会被记账 ⇒ ③ 会红：{d}"

    def test_red_proof_6_trigger_face_missing_a_deploy_leg(self):
        mutated = REAL_WORKFLOW_TEXT.replace("      - Build and Deploy admin-api\n", "", 1)
        assert mutated != REAL_WORKFLOW_TEXT, "注入锚点失效（先修本测试）"
        wr = _on_section(_workflow(mutated))["workflow_run"]
        expected = sorted(set(FL.TRIAGED_WORKFLOWS) | set(FL.DEPLOY_RECORD_WORKFLOWS))
        assert sorted(wr.get("workflows") or []) != expected, \
            "删掉任一部署腿的触发面 ⇒ 接线判据必须红"

    def test_red_proof_7_unregistered_deploy_leg(self):
        found = dict(_deploy_workflow_names())
        found["deploy-brand-new.yml"] = "Build and Deploy brand-new"
        assert registry_violations(found, FL.DEPLOY_RECORD_WORKFLOWS, DEPLOY_RECORD_EXEMPT), \
            "新增部署腿却忘了登记 ⇒ 类级元守卫必须红（未登记即红）"

    def test_red_proof_8_exemption_without_reason(self):
        found = dict(_deploy_workflow_names())
        exempt = dict(DEPLOY_RECORD_EXEMPT)
        key = next(iter(exempt))
        exempt[key] = "   "
        assert registry_violations(found, FL.DEPLOY_RECORD_WORKFLOWS, exempt), \
            "豁免不写理由 ⇒ 元守卫必须红"
