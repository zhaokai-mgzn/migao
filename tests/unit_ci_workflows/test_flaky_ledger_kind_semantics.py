# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012 ——
#   「CI workflow 结构由 pytest 单测验证」是 `.github/cases/misc.yml` 里已登记的形态。）
"""#5088：台账 `kind` **不许当归因层用** —— fail-closed 语义 + 原始事实 + 读侧同步的判据
（L0，离线、零 LLM、秒级；**三条红证都会真断言失败**）。

病灶（**实测读数**，不是照抄 issue 文本）
----------------------------------------
旧口径 `kind` 由 `rerun_result` 推出（`build_entries`：第二次绿 ⇒ `flaky`；两次都红 ⇒
`confirmed_failure`「确定性失败」）。按 #5088 的包**逐条拉两次尝试的 job 日志**取证：
  · 台账 **21 条里 7 条判错**（issue 的 9 条错 2 · 后增 12 条错 5）；
  · 4 条 `confirmed_failure` 的两次尝试**红的不是同一条断言**（run `35866618242` / `35891090972`
    / `35927546366` / `35942147403`；例：`35866618242` 的 attempt1 = `OversizeThresholdPreview`
    收到占位 `—`，attempt2 = `SavingBoard` 找不到 `saving-saved-group-purchase-2026-09`）；
  · 2 条是**宽窗口竞态**（`ship-order` 的 `#4882` 那条用例：一个 run 里 a1 红 / a2 绿 ⇒ 记 `flaky`，
    另一个 run 里**同一条用例、同一条报错** a1/a2 都红 ⇒ 旧口径记 `confirmed_failure`）；
  · 1 条 `infra_suspect` 实为 dependabot 的 `npm ERESOLVE`（两次尝试逐字同一个错误 = 该 PR 的
    依赖**不可解析**，是确定性的，不是环境抖动）。

三条红证（改前必红；本文件用「注入旧口径 / 注入退化解」把判据的**非空转**也钉住）
--------------------------------------------------------------------------------
① `TestRaceCorpus` —— 同 SHA 两跑都红但它是**竞态** ⇒ 新分类**不给会误导的结论**
   （`unknown`，且不落在 `ATTRIBUTABLE_KINDS` 里）；
② `TestDeterministicCorpus` —— 真正确定性失败（两次尝试**同一断言同一错误**）⇒ 仍能**如实**
   标成确定性（防把分类改成「一律 unknown」）；
③ `TestReadSideCompat` —— 改字段后读侧**不许静默降级**（旧值仍在白名单、每个 kind 都有非空的
   `reason`/`remedy`、`unknown` 在聚合里**单列**且不进归因计数、出厂台账 `selftest`/`reconcile` 仍干净）。
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".github" / "scripts"
LEDGER_PATH = REPO_ROOT / ".github" / "flaky-ledger.json"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FL = _load(SCRIPTS / "flaky_ledger.py", "migao_flaky_ledger_kind_semantics")
REAL_LEDGER = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


# ── 夹具（形状与 GitHub REST `/actions/runs/{id}` + `/attempts/{n}/jobs` 同源） ──


def make_run(name="PR Check", attempt=2, conclusion="failure", event="pull_request",
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


def make_job(name="admin-web typecheck + unit tests", conclusion="failure",
             failed_step="Run unit tests"):
    if conclusion != "failure":
        steps = [{"name": "Run unit tests", "conclusion": "success"}]
    else:
        steps = [
            {"name": "Run actions/checkout@v7", "conclusion": "success"},
            {"name": failed_step, "conclusion": "failure"},
        ]
    return {"name": name, "conclusion": conclusion, "steps": steps}


def bundle(run=None, jobs=None, prior_jobs=None):
    return {"run": run or make_run(), "jobs": jobs if jobs is not None else [],
            "prior_jobs": prior_jobs}


def both_red_entry(prior_step="Run unit tests", step="Run unit tests"):
    """两次都红（同 SHA）的**自动路径**条目 —— #5088 之后必须是 `unknown` + 两次尝试的原始事实。"""
    decision = FL.decide(bundle(run=make_run(attempt=2, conclusion="failure"),
                                jobs=[make_job(failed_step=step)],
                                prior_jobs=[make_job(failed_step=prior_step)]))
    assert decision["entries"], decision
    return decision["entries"][0]


def ledger_with(entry) -> dict:
    return {"version": 2, "note": "", "_schema": {}, "entries": [entry]}


def attest(entry, a1, a2, evidence="run 900001 / attempts 1-2 的 job 日志"):
    led = ledger_with(entry)
    FL.apply_attestation(led, [0], attempt1_assertion=a1, attempt2_assertion=a2,
                         evidence=evidence)
    return led["entries"][0]


# ── 语料：**真实读数**（#5088 的包逐条拉两次尝试的 job 日志得到，逐字） ──────────

#: 同 SHA 两跑都红但**不是**同一条断言（run 35866618242 / PR 5222）
RACE_DIFFERENT_ASSERTIONS = {
    "attempt1": "OversizeThresholdPreview 收占位 `—`",
    "attempt2": "SavingBoard 找不到 `saving-saved-group-purchase-2026-09`",
}
#: 同 SHA 两跑都红且**同一条用例同一条报错** —— 但它仍是**宽窗口竞态**（#5088 §1.2 第 1、2 条）
RACE_SAME_ASSERTION = {
    "attempt1": "ship-order.test.tsx › #4882 含加工项订单：Unable to find an element with the "
                "text: 加工费合计（元）：37.50",
    "attempt2": "ship-order.test.tsx › #4882 含加工项订单：Unable to find an element with the "
                "text: 加工费合计（元）：37.50",
}
#: 真正的确定性失败：两次尝试**同一断言同一错误**（run 35505944070 / PR 4860 自己的类型错）
DETERMINISTIC_SAME_ASSERTION = {
    "attempt1": "frontend/admin-web/src/lib/order-fee-display.ts(146,9): error TS2322",
    "attempt2": "frontend/admin-web/src/lib/order-fee-display.ts(146,9): error TS2322",
}


# ── 独立检查器（刻意不读 FL 内部结构 ⇒ 注入版判据也能判；照 test_flaky_triage.py 形态） ──


def race_corpus_violations(decide_fn) -> list:
    """给「同 SHA 两跑都红（步骤级事实）」的语料，看会不会给出**会误导的结论**。"""
    decision = decide_fn(bundle(run=make_run(attempt=2, conclusion="failure"),
                                jobs=[make_job()], prior_jobs=[make_job()]))
    bad = []
    if decision.get("kind") != "unknown":
        bad.append(f"两次都红的语料给出结论 {decision.get('kind')!r} ⇒ 把「重跑仍红」当归因"
                   f"（#5088 实测 21 条里 7 条这样判错）")
    for entry in decision.get("entries") or []:
        kind = entry.get("kind")
        if kind in ("flaky", "deterministic", "confirmed_failure"):
            bad.append(f"条目 kind={kind!r} ⇒ 无凭据的归因（自动路径只有步骤级事实）")
        if not str(entry.get("unknown_reason") or "").strip():
            bad.append("unknown 条目没写明**为什么不归因** ⇒ 读的人无法复核")
        facts = entry.get("attempts") or []
        if len(facts) != 2:
            bad.append(f"两次都红必须记下**两次尝试**的原始事实，实际 {len(facts)} 条")
        elif [f.get("attempt") for f in facts] != [1, 2]:
            bad.append(f"原始事实的 attempt 序号应为 [1, 2]，实际 {[f.get('attempt') for f in facts]}")
    return bad


def deterministic_corpus_violations(classify_fn) -> list:
    """给「两次尝试**同一断言同一错误**」的语料，看结论是否为 `deterministic`（防一律 unknown）。"""
    a1 = {"attempt": 1, "job": "j", "step": "Run unit tests",
          "assertion": DETERMINISTIC_SAME_ASSERTION["attempt1"]}
    a2 = {"attempt": 2, "job": "j", "step": "Run unit tests",
          "assertion": DETERMINISTIC_SAME_ASSERTION["attempt2"]}
    kind, why = classify_fn(a1, a2)
    bad = []
    if kind != "deterministic":
        bad.append(f"两次同一断言同一错误的语料给出 {kind!r}（理由 {why!r}）"
                   f"⇒ **确定性失败被吞成不归因**")
    if kind not in FL.ATTRIBUTABLE_KINDS:
        bad.append(f"{kind!r} 不在可归因集合 `ATTRIBUTABLE_KINDS` 里")
    return bad


# ── 红证①：同 SHA 两跑都红，但它是竞态 ⇒ 不许给出会误导的结论 ─────────────────


class TestRaceCorpus:
    def test_both_red_is_unknown_and_not_attributable(self):
        """**改前必红**：旧口径在这里给 `confirmed_failure`「确定性失败」。"""
        decision = FL.decide(bundle(run=make_run(attempt=2, conclusion="failure"),
                                    jobs=[make_job()], prior_jobs=[make_job()]))
        entry = decision["entries"][0]
        assert decision["action"] == "record_both_red", decision
        assert decision["kind"] == "unknown", decision
        assert entry["kind"] == "unknown", entry
        assert entry["rerun_result"] == "failure", "事实层仍如实记录「两次都红」"
        assert "confirmed_failure" not in json.dumps(entry, ensure_ascii=False), entry
        assert race_corpus_violations(FL.decide) == []

    def test_unknown_never_enters_the_attribution_set(self):
        assert "unknown" not in FL.ATTRIBUTABLE_KINDS
        assert set(FL.ATTRIBUTABLE_KINDS) <= set(FL.ENTRY_KINDS)

    def test_same_assertion_race_on_the_auto_path_is_still_unknown(self):
        """**#5088 病灶的直接回归**：宽窗口竞态（同一用例、同一报错、两跑都红）在**自动路径**上
        仍只能是 `unknown`（`attempts[*].assertion` 取不到 ⇒ 不许假装有）。"""
        entry = both_red_entry()
        assert entry["kind"] == "unknown"
        assert [f["assertion"] for f in entry["attempts"]] == [None, None]
        assert "步骤级事实" in entry["unknown_reason"], entry["unknown_reason"]

    def test_different_step_both_red_records_both_attempts_verbatim(self):
        entry = both_red_entry(prior_step="TypeScript type check", step="Run unit tests")
        assert entry["kind"] == "unknown"
        assert [(f["attempt"], f["step"]) for f in entry["attempts"]] == [
            (1, "TypeScript type check"), (2, "Run unit tests")]
        assert "不是同一个步骤" in entry["unknown_reason"], entry["unknown_reason"]
        assert FL.ledger_violations(ledger_with(entry)) == []

    def test_attest_with_divergent_assertions_stays_unknown(self):
        """#5088 的建议口径：「两次尝试红的**不是同一条断言** ⇒ 不得记确定性」。"""
        entry = attest(both_red_entry(),
                       RACE_DIFFERENT_ASSERTIONS["attempt1"],
                       RACE_DIFFERENT_ASSERTIONS["attempt2"],
                       evidence="run 35866618242 / attempts 1-2 的 job 日志")
        assert entry["kind"] == "unknown", entry
        assert "不是同一条断言" in entry["unknown_reason"], entry["unknown_reason"]
        assert [f["assertion"] for f in entry["attempts"]] == [
            RACE_DIFFERENT_ASSERTIONS["attempt1"], RACE_DIFFERENT_ASSERTIONS["attempt2"]]
        assert entry["attested_evidence"].strip()
        assert FL.ledger_violations(ledger_with(entry)) == []

    def test_red_proof_injecting_the_legacy_rule_is_caught(self):
        """**红证（判据非空转）**：把旧口径（两次都红 ⇒ `confirmed_failure`）注回 ⇒ 判据**必须**红。"""
        def legacy(b, max_attempts=FL.MAX_ATTEMPTS):
            decision = FL.decide(b, max_attempts)
            if decision["action"] == "record_both_red":
                return dict(decision, action="record_confirmed_failure",
                            kind="confirmed_failure",
                            entries=[dict(e, kind="confirmed_failure")
                                     for e in decision["entries"]])
            return decision

        violations = race_corpus_violations(legacy)
        assert any("confirmed_failure" in v for v in violations), violations
        assert any("7 条" in v for v in violations), violations


# ── 红证②：真确定性失败仍能如实标成确定性（防「一律 unknown」） ────────────────


class TestDeterministicCorpus:
    def test_same_assertion_both_attempts_is_deterministic(self):
        entry = attest(both_red_entry(),
                       DETERMINISTIC_SAME_ASSERTION["attempt1"],
                       DETERMINISTIC_SAME_ASSERTION["attempt2"],
                       evidence="run 35505944070 / attempts 1-2 的 `Run unit tests` 日志逐字相同")
        assert entry["kind"] == "deterministic", entry
        assert entry["kind"] in FL.ATTRIBUTABLE_KINDS
        assert "unknown_reason" not in entry, "改成确定性后不得留下旧的不归因理由"
        assert [f["assertion"] for f in entry["attempts"]] == [
            DETERMINISTIC_SAME_ASSERTION["attempt1"], DETERMINISTIC_SAME_ASSERTION["attempt2"]]
        assert FL.ledger_violations(ledger_with(entry)) == []

    def test_real_classifier_satisfies_the_deterministic_corpus(self):
        assert deterministic_corpus_violations(FL.classify_both_red) == []

    def test_red_proof_degenerate_always_unknown_classifier_is_caught(self):
        """**红证**：把判据换成退化解（一律 `unknown`）⇒ 本类判据**必须**红。"""
        def degenerate(a1, a2):
            return "unknown", "退化解：一律不归因"

        violations = deterministic_corpus_violations(degenerate)
        assert violations, "退化解仍判绿 ⇒ 该判据是**空断言**"
        assert any("吞成不归因" in v for v in violations), violations

    def test_deterministic_without_evidence_is_a_violation(self):
        """「归因必须有凭据」：断言级事实齐了但缺 `attested_evidence` ⇒ 判违规。"""
        entry = attest(both_red_entry(),
                       DETERMINISTIC_SAME_ASSERTION["attempt1"],
                       DETERMINISTIC_SAME_ASSERTION["attempt2"])
        entry.pop("attested_evidence")
        bad = FL.ledger_violations(ledger_with(entry))
        assert any("attested_evidence" in b for b in bad), bad

    def test_deterministic_with_divergent_assertions_is_a_violation(self):
        entry = attest(both_red_entry(),
                       RACE_DIFFERENT_ASSERTIONS["attempt1"],
                       RACE_DIFFERENT_ASSERTIONS["attempt2"])
        entry["kind"] = "deterministic"          # 手改成结论（模拟「无凭据的归因」）
        bad = FL.ledger_violations(ledger_with(entry))
        assert any("无凭据的归因" in b for b in bad), bad

    def test_unknown_without_reason_is_a_violation(self):
        entry = both_red_entry()
        entry.pop("unknown_reason")
        bad = FL.ledger_violations(ledger_with(entry))
        assert any("unknown_reason" in b for b in bad), bad

    def test_fact_backed_kind_without_attempts_is_a_violation(self):
        entry = both_red_entry()
        entry.pop("attempts")
        bad = FL.ledger_violations(ledger_with(entry))
        assert any("attempts" in b for b in bad), bad

    def test_attest_is_idempotent_and_leaves_other_fields_alone(self):
        entry = both_red_entry()
        entry["follow_up"] = 5568
        first = attest(entry, DETERMINISTIC_SAME_ASSERTION["attempt1"],
                       DETERMINISTIC_SAME_ASSERTION["attempt2"])
        assert first["follow_up"] == 5568, "attest 只许改指定字段"
        led = ledger_with(first)
        before = json.dumps(led, ensure_ascii=False, sort_keys=True)
        result = FL.apply_attestation(led, [0],
                                      attempt1_assertion=DETERMINISTIC_SAME_ASSERTION["attempt1"],
                                      attempt2_assertion=DETERMINISTIC_SAME_ASSERTION["attempt2"],
                                      evidence=first["attested_evidence"])
        assert result["idempotent"] is True, result
        assert json.dumps(led, ensure_ascii=False, sort_keys=True) == before


# ── 红证③：读侧同步（不许「读旧字段拿到空值」的静默降级） ──────────────────────


class TestReadSideCompat:
    def test_shipped_ledger_kinds_are_all_known_and_legacy_values_survive(self):
        kinds = sorted({e["kind"] for e in REAL_LEDGER["entries"]})
        assert set(kinds) <= set(FL.ENTRY_KINDS), kinds
        assert "confirmed_failure" in kinds, "历史条目必须原样保留（台账是证据）"
        assert set(FL.LEGACY_ENTRY_KINDS) <= set(FL.ENTRY_KINDS)
        assert FL.ledger_violations(REAL_LEDGER) == []

    def test_every_kind_has_non_empty_reason_and_remedy(self):
        for kind in FL.ENTRY_KINDS:
            assert str(FL.KIND_REASON[kind]).strip(), kind
            assert str(FL.KIND_REMEDY[kind]).strip(), kind

    def test_legacy_entries_keep_their_original_reason_text(self):
        """历史条目的 `reason`/`remedy` 与常量**逐字**一致 ⇒ 改常量会让本判据红（不许改写历史语义）。"""
        legacy = [e for e in REAL_LEDGER["entries"] if e["kind"] in FL.LEGACY_ENTRY_KINDS]
        assert legacy, "历史条目不见了 ⇒ 迁移把证据删了"
        for entry in legacy:
            assert entry["reason"] == FL.KIND_REASON["confirmed_failure"], entry["run_id"]
            assert entry["remedy"] == FL.KIND_REMEDY["confirmed_failure"], entry["run_id"]

    def test_migration_did_not_rewrite_entries(self):
        """迁移只动顶层 `note`/`_schema`/`version`：历史条目**无** `attempts`（新口径才写），
        且迁移**没有**给历史条目补结论。"""
        for entry in REAL_LEDGER["entries"]:
            if entry["kind"] in FL.LEGACY_ENTRY_KINDS:
                assert "attempts" not in entry, ("历史条目被改写了", entry["run_id"])
        inferred = [e["run_id"] for e in REAL_LEDGER["entries"]
                    if e["kind"] in FL.FACT_BACKED_KINDS]
        assert inferred == [], f"迁移不许给历史条目补结论（那等于用新口径改写历史）：{inferred}"
        assert REAL_LEDGER["version"] >= 2, "版本号必须显式登记口径变更"
        assert "migration" in REAL_LEDGER["_schema"], "迁移动作与依据必须显式登记"

    def test_aggregate_keeps_unknown_out_of_attribution(self):
        job = "admin-web typecheck + unit tests"
        entries = [
            {"workflow": "PR Check", "job": job, "run_id": 1, "run_attempt": 2,
             "rerun_result": "success", "kind": "flaky", "observed_at": "t"},
            both_red_entry(),
            attest(both_red_entry(), DETERMINISTIC_SAME_ASSERTION["attempt1"],
                   DETERMINISTIC_SAME_ASSERTION["attempt2"]),
            {"workflow": "PR Check", "job": job, "run_id": 4, "run_attempt": 2,
             "rerun_result": "failure", "kind": "confirmed_failure", "observed_at": "t"},
            {"workflow": "PR Check", "job": job, "run_id": 5, "run_attempt": 2,
             "rerun_result": "failure", "kind": "infra_suspect", "observed_at": "t"},
        ]
        slot = FL.aggregate({"entries": entries})[f"PR Check :: {job}"]
        assert slot["total"] == 5, slot
        assert (slot["flaky"], slot["deterministic"], slot["unknown"],
                slot["confirmed_failure"], slot["infra_suspect"]) == (1, 1, 1, 1, 1), slot
        assert slot["attributed"] == 3, ("attributed 只统计 ATTRIBUTABLE_KINDS（unknown 不计入）", slot)

    def test_attributed_count_follows_the_single_source_of_truth(self):
        """`attributed` 由 `ATTRIBUTABLE_KINDS`（单一事实源）推出：把 `unknown` 塞进集合，计数**立刻**
        跟着变（⇒ 它既不是写死的，也证明「unknown 不进归因」是**可判**的、不是靠注释）。"""
        entry = both_red_entry()
        original = FL.ATTRIBUTABLE_KINDS
        assert FL.aggregate({"entries": [entry]})["PR Check :: admin-web typecheck + unit tests"][
            "attributed"] == 0
        try:
            FL.ATTRIBUTABLE_KINDS = frozenset(original | {"unknown"})
            slot = FL.aggregate({"entries": [entry]})[
                "PR Check :: admin-web typecheck + unit tests"]
            assert slot["attributed"] == 1, slot
        finally:
            FL.ATTRIBUTABLE_KINDS = original
        assert "unknown" not in FL.ATTRIBUTABLE_KINDS, "测试必须还原常量（否则污染其它用例）"

    def test_decide_never_emits_the_legacy_kind(self):
        """**结构锁**：新写入**不再产生**旧口径的 `confirmed_failure`（历史值只读）。"""
        produced = set()
        for attempt, conclusion in ((1, "failure"), (2, "failure"), (3, "failure")):
            decision = FL.decide(bundle(run=make_run(attempt=attempt, conclusion=conclusion),
                                        jobs=[make_job()], prior_jobs=[make_job()]))
            produced |= {e["kind"] for e in decision.get("entries") or []}
        assert produced == {"unknown"}, produced
        assert produced.isdisjoint(FL.LEGACY_ENTRY_KINDS)


# ── ④ CLI 面：fail-closed（不许静默无操作）+ happy path ─────────────────────────


def _write_ledger(tmp_path, entry):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger_with(entry), ensure_ascii=False), encoding="utf-8")
    return path


class TestAttestCli:
    def test_attest_cli_happy_path_marks_deterministic(self, tmp_path):
        path = _write_ledger(tmp_path, both_red_entry())
        rc = FL.main(["attest", "--ledger", str(path), "--run-id", "900001",
                      "--attempt1-assertion", DETERMINISTIC_SAME_ASSERTION["attempt1"],
                      "--attempt2-assertion", DETERMINISTIC_SAME_ASSERTION["attempt2"],
                      "--evidence", "run 900001 / attempts 1-2 的 job 日志"])
        assert rc == 0, rc
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["entries"][0]["kind"] == "deterministic", saved["entries"][0]

    def test_attest_cli_refuses_empty_evidence(self, tmp_path):
        before = _write_ledger(tmp_path, both_red_entry())
        payload = before.read_text(encoding="utf-8")
        rc = FL.main(["attest", "--ledger", str(before), "--run-id", "900001",
                      "--attempt1-assertion", "a", "--attempt2-assertion", "a",
                      "--evidence", "   "])
        assert rc == 1, rc
        assert before.read_text(encoding="utf-8") == payload, "拒绝时必须**不写盘**"

    def test_attest_cli_refuses_unknown_run_id(self, tmp_path):
        path = _write_ledger(tmp_path, both_red_entry())
        rc = FL.main(["attest", "--ledger", str(path), "--run-id", "424242",
                      "--attempt1-assertion", "a", "--attempt2-assertion", "a",
                      "--evidence", "x"])
        assert rc == 1, rc

    def test_report_and_reconcile_cli_still_clean_on_the_shipped_ledger(self):
        for argv in (["selftest"], ["reconcile"]):
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / "flaky_ledger.py"), *argv],
                cwd=str(REPO_ROOT), capture_output=True, text=True)
            assert proc.returncode == 0, (argv, proc.stdout, proc.stderr)