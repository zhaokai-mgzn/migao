# case_ids: MC-231, MC-232
"""**判红 ≠ 记账**：混合场景下限流 job 不再计入 flaky 台账（issue #8709 的残留缺陷）。

## 病灶（2026-11-05 现场读数，**不是推演**）

`flaky-triage` 的 run `41991584085` 日志逐字：

```
**失败 job 的日志分类（#8709）**：扫描面 6/6 个失败 job · 拉取日志 6 份 · 判限流 5 个 · 按真红 1 个 · **未判定 0 个**
action=`mark_suspect` kind=`suspect-window-deterministic` attempt=2 pr=8716 entries=6
```

⇒ **6 份日志里 5 份判为限流**，台账却记了 **6 条**（`entries=6`）。`origin/main` 的
`.github/flaky-ledger.json` 最后 6 条的 `job`：`ci workflow helper unit tests`（真红）、
`External Authorship Guard` / `Secret Scan (gitleaks)` / `QA Growth Gate` /
`Danger Scan (破坏性变更检测)`（这 4 条的 `failing_tests` 为空 = 判为限流）。

**为什么 #8709 的判据没挡住它**：#8709 只处理了「**全部** job 都判限流」这条路径
（`rate_limited_only()["rate_limited"]` ⇒ `_infra_rate_limited_decision` ⇒ 零条目）；
**混合场景**（既有真红又有判限流的）走的是 `_terminal()` ⇒ `build_entries()` 把 6 个 job
**全记**了进来。判据「限流产生的 flaky 不许混进证据台账」在混合路径上**漏了**。

## 修法（本文件钉的五条，每条都有注入式红证）

| # | 判据 | 会红在哪 |
|---|---|---|
| 1 | **混合场景：限流 job 零条目、真红 job 有条目** | 把 `exclude_jobs` 去掉 ⇒ 条目数 1 → 6 ⇒ 红 |
| 2 | **混合场景的 action 仍是「按真红」**（`mark_suspect` / `mark_flaky`，PR 仍被挡；全限流才走 `infra_rate_limited`） | 改成判 `infra_rate_limited` ⇒ 红（真红被一起放过） |
| 3 | **全限流仍走 `infra_rate_limited` + 零条目**（#8709 已交付的判据不许退化） | 全限流却产出条目 / 判成 flaky ⇒ 红 |
| 4 | **未判定（日志取不到）不许静默**：条目在，而且能从条目上看出「这是未判定，不是 flaky」 | 静默丢掉 / 当成限流排除 / 标不出未判定 ⇒ 红 |
| 5 | **扫描面非空自证**：判限流的 job 数 + 真红 job 数 = 总失败 job 数；`条目 ∪ 被排除 = 全部失败 job` 且不相交 | 有 job 两边都不在（漏算）⇒ 红 |

## 关键区分：**判红 ≠ 记账**

被判「其实只是限流」的那些 job **仍然是红的** ⇒ required 检查仍不满足 ⇒ PR 仍被挡
（action 照旧按真红那批派生）。本文件**只**改**台账面**（证据面）：
「判不了（exit 3）」不许写成 flaky 证据 —— 这与「放行」是两件事，本单一个字都没动退出码。

## 红证的形态

判据 1~5 由**独立检查器** `ledger_face_violations(mod)` 承担（只喂夹具看输出，不读实现内部结构
⇒ 注入版也能被它判）。四条红证都是**源码级单变量变异**（`inject()` 保证命中且唯一）：
把「排除 / 标注 / 分区」各自注回坏形态 ⇒ 对应判据**具名**判红；真模块上一条不报。
"""
import importlib.util
import types
from pathlib import Path

from unit_ci_workflows.injection import inject

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "flaky_ledger.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FL = _load(SCRIPT_PATH, "migao_flaky_ledger_mixed_entries_8709")
REAL_SOURCE = SCRIPT_PATH.read_text(encoding="utf-8")


# ── 语料：现场日志（限流 = exit 3「判不了」；真红 = pytest 失败行） ──────────────

RATE_LIMIT_LOG = """2026-11-05T02:41:11.0000000Z ⏳ gitleaks license 校验预检：限流（HTTP 403），2.0s 后重试（第 1/3 次）
2026-11-05T02:41:13.0000000Z ⏳ gitleaks license 校验预检：限流（HTTP 403），4.0s 后重试（第 2/3 次）
2026-11-05T02:41:17.0000000Z ⛔ gitleaks license 校验预检：限流退避用尽（次数上限，已尝试 3 次，最后一次 HTTP 403） —— **未判定**（exit 3，不得当 0 读）
"""

REAL_RED_LOG = """2026-11-05T02:41:11.0000000Z =========================== short test summary info ============================
2026-11-05T02:41:11.0000000Z FAILED tests/unit_ci_workflows/test_flaky_triage.py::TestRerunOnce::test_max_attempts_is_two - AssertionError: 3 != 2
2026-11-05T02:41:11.0000000Z ========================= 1 failed, 12 passed in 0.42s =========================
"""

#: 现场 `origin/main:.github/flaky-ledger.json` 里被判为限流的那批 job（`failing_tests` 全为空）。
RATE_LIMITED_JOBS = (
    "External Authorship Guard",
    "Secret Scan (gitleaks)",
    "QA Growth Gate",
    "Danger Scan (破坏性变更检测)",
    "Contribution Gate",
)
#: 现场唯一一条真红（`failing_tests` 有两条真失败 / `suspect-window-deterministic`）。
REAL_RED_JOB = "ci workflow helper unit tests"

#: 首次失败与重跑通过落在**不同时间桶**（现场就是 `suspect-window-deterministic`）：
#: 22:12Z 与 00:05Z 的 UTC 日期不同 ⇒ 跨桶（#5687）。
FAIL_TS = "2026-11-05T22:12:00Z"
RERUN_TS = "2026-11-06T00:05:00Z"


# ── 夹具（形状与 GitHub REST `/actions/runs/{id}` + `/attempts/{n}/jobs` 同源） ──


def _job(name, jid, *, conclusion="failure", step="Run gitleaks license 校验预检",
         completed_at=FAIL_TS):
    steps = [{"name": "Set up job", "conclusion": "success"},
             {"name": step, "conclusion": "success" if conclusion == "success" else "failure"}]
    job = {"id": jid, "name": name, "conclusion": conclusion, "steps": steps}
    if completed_at:
        job["completed_at"] = completed_at
    return job


def _run(attempt, conclusion, pr=8716, run_id=41991584085):
    return {
        "id": run_id,
        "name": "PR Check",
        "event": "pull_request",
        "conclusion": conclusion,
        "run_attempt": attempt,
        "head_branch": "feat/7813-p2b",
        "head_sha": "c" * 40,
        "html_url": f"https://github.com/o/r/actions/runs/{run_id}",
        "updated_at": RERUN_TS,
        "pull_requests": [{"number": pr}],
    }


def _logs(jobs, missing=()):
    """每个失败 job 一份日志；`missing` 里的 job **取不到**（模拟日志已被清理）。"""
    out = {}
    for job in jobs:
        if job["name"] in missing:
            continue
        out[job["id"]] = RATE_LIMIT_LOG if job["name"] in RATE_LIMITED_JOBS else REAL_RED_LOG
    return out


def _classify(mod, bundle, logs):
    """用**该模块自己的**取数函数把分类写进 bundle（不手搓 `failure_kinds` 形状）。"""
    def fetch_log(repo, jid):
        if jid not in logs:
            raise RuntimeError(f"job {jid} 的日志已被清理")
        return logs[jid]

    return mod.collect_failure_kinds(bundle, "o/r", fetch_log=fetch_log)


def _failed_jobs():
    jobs = [_job(name, 500 + i, step="Run guard")
            for i, name in enumerate(RATE_LIMITED_JOBS)]
    jobs.append(_job(REAL_RED_JOB, 599, step="Run unit tests"))
    return jobs


def mixed_second_green(mod, missing=()):
    """现场形态：首次尝试 6 个失败 job（5 判限流 + 1 真红，跨桶）⇒ 重跑后第二次绿。"""
    failed = _failed_jobs()
    rerun = [_job(job["name"], job["id"], conclusion="success", step="Run guard",
                  completed_at=RERUN_TS) for job in failed]
    bundle = {"run": _run(2, "success"), "jobs": rerun, "prior_jobs": failed}
    _classify(mod, bundle, _logs(failed, missing=missing))
    return bundle, mod.decide(bundle)


def all_rate_limited_second_green(mod):
    """对照面：6 个失败 job **全部**判限流（#8709 已交付的那条路径，本单不许它退化）。"""
    failed = [_job(name, 500 + i, step="Run guard") for i, name in enumerate(RATE_LIMITED_JOBS)]
    rerun = [_job(job["name"], job["id"], conclusion="success", step="Run guard",
                  completed_at=RERUN_TS) for job in failed]
    bundle = {"run": _run(2, "success"), "jobs": rerun, "prior_jobs": failed}
    _classify(mod, bundle, _logs(failed))
    return bundle, mod.decide(bundle)


def _names(entries):
    return [entry.get("job") for entry in entries]


# ── 独立检查器（只喂夹具看输出；注入版也判得动） ─────────────────────────────


def ledger_face_violations(mod):
    """#8709 残留的五条红线（空 = 合规）。**不读实现内部结构**，只看 `decide` 的输出。"""
    bad = []

    # ── ① 混合场景：限流 job 零条目、真红 job 有条目（判红 ≠ 记账） ─────────────
    bundle, d = mixed_second_green(mod)
    entries = {e.get("job") for e in d.get("entries") or []}
    excluded = set(d.get("entries_excluded") or [])
    leaked = entries & set(RATE_LIMITED_JOBS)
    if leaked:
        bad.append(f"判为限流的 job 混进了证据台账：{sorted(leaked)}"
                   f"（现场 entries=6，其中 5 条其实只是限流）")
    if entries != {REAL_RED_JOB}:
        bad.append(f"混合场景下的台账条目应**只有真红**那一条（`{REAL_RED_JOB}`），"
                   f"实际 {sorted(entries)}")
    if excluded != set(RATE_LIMITED_JOBS):
        bad.append(f"被排除的 job 集合应**恰好**是判为限流的 5 条，实际 {sorted(excluded)}")

    # ── ② 动作仍按真红（跨桶 ⇒ mark_suspect）；混合**不许**按限流处置 ──────────
    if d.get("action") == "infra_rate_limited":
        bad.append("混合场景（限流 + 真红）被按限流处置 ⇒ 真红被一起放过")
    elif d.get("action") != "mark_suspect":
        bad.append(f"混合场景的 action 应按真红派生（跨桶 ⇒ mark_suspect），实际 {d.get('action')!r}")
    if d.get("kind") != mod.SUSPECT_WINDOW_KIND:
        bad.append(f"混合场景的 kind 应取真红那条的结论（{mod.SUSPECT_WINDOW_KIND}），"
                   f"实际 {d.get('kind')!r}")

    # ── ③ 全限流仍走 infra_rate_limited + 零条目（#8709 已交付的判据不许退化） ──
    _bundle_all, d_all = all_rate_limited_second_green(mod)
    if d_all.get("action") != "infra_rate_limited":
        bad.append(f"全限流场景的 action 应为 infra_rate_limited，实际 {d_all.get('action')!r}")
    if d_all.get("entries"):
        bad.append(f"全限流场景产出了 {len(d_all['entries'])} 条台账条目（#8709 判据 4 退化）")

    # ── ④ 未判定（日志取不到）不许静默 ────────────────────────────────────────
    _b_miss, d_miss = mixed_second_green(mod, missing=("QA Growth Gate",))
    by_job = {e.get("job"): e for e in d_miss.get("entries") or []}
    miss = by_job.get("QA Growth Gate")
    if miss is None:
        bad.append("日志取不到的 job 被静默丢掉了（必须产出条目并标注「未判定」）")
    else:
        if miss.get(mod.UNDETERMINED_FIELD) is not True:
            bad.append(f"取不到日志的条目缺 `{mod.UNDETERMINED_FIELD}=True` ⇒ 读起来像「已确认 flaky」")
        if "未判定" not in str(miss.get("reason") or ""):
            bad.append("取不到日志的条目的 `reason` 里没有「未判定」字样 ⇒ 看不出它不是 flaky 结论")
        if "日志" not in str(miss.get("remedy") or ""):
            bad.append("取不到日志的条目没给出「先取回日志」的下一步（不可行动）")
    if "QA Growth Gate" in (d_miss.get("entries_excluded") or []):
        bad.append("把「未判定」当成限流排除了 ⇒ fail-closed 被破坏（会放过真红）")

    # ── ⑤ 扫描面非空自证：没有 job 在两边都消失 ───────────────────────────────
    all_failed = {job["name"] for job in (bundle.get("prior_jobs") or [])}
    if entries | excluded != all_failed:
        lost = all_failed - (entries | excluded)
        bad.append(f"失败 job 被漏算：{sorted(lost)} 既不在条目里也不在排除清单里"
                   f"（扫描面 {len(all_failed)} 个，entry ∪ excluded = {len(entries | excluded)} 个）")
    if entries & excluded:
        bad.append(f"同一个 job 既记账又被排除：{sorted(entries & excluded)}")
    if not set(excluded) <= set(mod.rate_limited_only(
            bundle, bundle["prior_jobs"], 1)["rate_limited_jobs"]):
        bad.append("被排除的 job 不在「判为限流」的集合里 ⇒ 排除面越界（会把真红也排掉）")
    kinds = d.get("failure_kinds") or {}
    surface = kinds.get("surface") or {}
    rate_n = len(kinds.get("rate_limited_jobs") or [])
    real_n = len(kinds.get("not_rate_limited_jobs") or [])
    if rate_n + real_n != kinds.get("total"):
        bad.append(f"扫描面自证失败：判限流 {rate_n} + 真红 {real_n} ≠ 总失败 job 数 "
                   f"{kinds.get('total')}")
    if surface.get("complete") is not True:
        bad.append(f"扫描面自证 `complete` 不为真：{surface}")
    return bad


class TestRealDecideIsClean:
    def test_real_decide_satisfies_every_ledger_face_red_line(self):
        assert ledger_face_violations(FL) == []

    def test_mixed_scenario_keeps_the_real_red_entry_only(self):
        """判据 1：6 个失败 job 里 5 个判限流 ⇒ 台账**只**留真红那 1 条（现场是 6 条）。"""
        _bundle, d = mixed_second_green(FL)
        assert _names(d["entries"]) == [REAL_RED_JOB]
        assert sorted(d["entries_excluded"]) == sorted(RATE_LIMITED_JOBS)
        assert d["entries"][0]["kind"] == FL.SUSPECT_WINDOW_KIND

    def test_mixed_scenario_action_is_still_the_real_red_one(self):
        """判据 2：**判红 ≠ 记账** —— PR 仍被挡（动作按真红，不是 infra）。"""
        _bundle, d = mixed_second_green(FL)
        assert d["action"] == "mark_suspect"
        assert d.get("kind") == FL.SUSPECT_WINDOW_KIND
        assert not d.get("infra_rate_limited")

    def test_pr_comment_says_the_excluded_jobs_are_not_ledger_evidence(self):
        """判据 2 的另一半：**PR 面**也要说得出「这些 job 没记账，但它们仍是红的」。"""
        _bundle, d = mixed_second_green(FL)
        comment = FL.render_comment(d)
        assert "判红 ≠ 记账" in comment
        for name in RATE_LIMITED_JOBS:
            assert name in comment

    def test_all_rate_limited_comment_does_not_claim_exclusions(self):
        """负控：全限流走 `infra_rate_limited`（零条目）⇒ 评论里**不**该出现「排除记账」那段。"""
        _bundle, d = all_rate_limited_second_green(FL)
        assert d["action"] == "infra_rate_limited"
        assert "判红 ≠ 记账" not in FL.render_comment(d)

    def test_first_failure_path_excludes_rate_limited_jobs_too(self):
        """另一条调用点（两次都红）：限流 job 同样零条目，真红照旧记账。"""
        failed = _failed_jobs()
        bundle = {"run": _run(2, "failure"), "jobs": failed, "prior_jobs": failed}
        _classify(FL, bundle, _logs(failed))
        d = FL.decide(bundle)
        assert d["action"] == "record_both_red"
        assert _names(d["entries"]) == [REAL_RED_JOB]
        assert sorted(d["entries_excluded"]) == sorted(RATE_LIMITED_JOBS)

    def test_undetermined_job_is_labelled_and_stays_visible(self):
        """判据 4：日志取不到 ⇒ 条目在、且说得出「这是未判定，不是 flaky」。"""
        _bundle, d = mixed_second_green(FL, missing=("QA Growth Gate",))
        by_job = {e["job"]: e for e in d["entries"]}
        assert set(by_job) == {REAL_RED_JOB, "QA Growth Gate"}
        miss = by_job["QA Growth Gate"]
        assert miss[FL.UNDETERMINED_FIELD] is True
        assert "未判定" in miss["reason"]
        assert "不是" in miss["undetermined_reason"] and "flaky" in miss["undetermined_reason"]
        assert "QA Growth Gate" not in d["entries_excluded"]
        # 可见性：job summary 也要说得出「这条/这批是未判定」
        summary = FL.render_summary(d)
        assert "未判定" in summary and "QA Growth Gate" in summary

    def test_every_failed_job_is_accounted_for_exactly_once(self):
        """判据 5：`条目 ∪ 被排除`== 全部失败 job，且两者不相交。"""
        bundle, d = mixed_second_green(FL)
        accounted = set(_names(d["entries"])) | set(d["entries_excluded"])
        assert accounted == {job["name"] for job in bundle["prior_jobs"]}
        assert not set(_names(d["entries"])) & set(d["entries_excluded"])
        fk = d["failure_kinds"]
        assert len(fk["rate_limited_jobs"]) + len(fk["not_rate_limited_jobs"]) == fk["total"]
        assert fk["surface"]["complete"] is True
        assert fk["undetermined_jobs"] == []


class TestRedProofs:
    """四条注入式红证（每条都是**单变量**变异；`inject()` 保证命中且唯一）。"""

    def _mutant(self, old, new, count=1):
        mutated = inject(REAL_SOURCE, old, new, count=count,
                         where=".github/scripts/flaky_ledger.py")
        mod = types.ModuleType("migao_flaky_ledger_mixed_mutant")
        mod.__file__ = str(SCRIPT_PATH)
        exec(compile(mutated, str(SCRIPT_PATH), "exec"), mod.__dict__)  # noqa: S102
        return mod

    def test_red_proof_dropping_the_exclusion_restores_six_entries(self):
        """判据 1 的红证：去掉 `exclude_jobs` ⇒ 条目数 1 → 6 ⇒ 判据红。"""
        mod = self._mutant('exclude_jobs=limit["rate_limited_jobs"],', "exclude_jobs=None,",
                           count=2)
        _bundle, d = mixed_second_green(mod)
        assert sorted(_names(d["entries"])) == sorted(
            list(RATE_LIMITED_JOBS) + [REAL_RED_JOB]), _names(d["entries"])
        violations = ledger_face_violations(mod)
        assert any("混进了证据台账" in v for v in violations), violations
        assert any("应**只有真红**" in v for v in violations), violations

    def test_red_proof_treating_the_mixed_scenario_as_infra(self):
        """判据 2 的红证：混合场景判 `infra_rate_limited` ⇒ 真红被一起放过 ⇒ 判据红。"""
        mod = self._mutant(
            '    elif other:\n        out["reason"] = (f"其中',
            '    elif other:\n        out["rate_limited"] = True\n        out["reason"] = (f"其中')
        _bundle, d = mixed_second_green(mod)
        assert d["action"] == "infra_rate_limited", d["action"]
        assert d["entries"] == []
        violations = ledger_face_violations(mod)
        assert any("真红被一起放过" in v for v in violations), violations

    def test_red_proof_dropping_the_undetermined_label(self):
        """判据 4 的红证：摘掉「未判定」标注 ⇒ 取不到日志的条目读起来像已确认 flaky ⇒ 判据红。"""
        mod = self._mutant("        if str(name) in undecided:", "        if False:")
        _bundle, d = mixed_second_green(mod, missing=("QA Growth Gate",))
        by_job = {e["job"]: e for e in d["entries"]}
        assert FL.UNDETERMINED_FIELD not in by_job["QA Growth Gate"]
        violations = ledger_face_violations(mod)
        assert any("读起来像「已确认 flaky」" in v for v in violations), violations

    def test_red_proof_a_job_silently_disappearing_from_the_accounting(self):
        """判据 5 的红证：让一个被判限流的 job 从「被排除清单」里消失 ⇒ 两边都不在 ⇒ 判据红。"""
        mod = self._mutant(
            '"entries_excluded": [str(n) for n in (exclude_jobs or [])]}',
            '"entries_excluded": [str(n) for n in (exclude_jobs or [])][1:]}')
        _bundle, d = mixed_second_green(mod)
        assert len(d["entries_excluded"]) == len(RATE_LIMITED_JOBS) - 1
        violations = ledger_face_violations(mod)
        assert any("被漏算" in v for v in violations), violations
