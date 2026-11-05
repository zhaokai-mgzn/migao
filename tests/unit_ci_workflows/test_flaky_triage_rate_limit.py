# case_ids: MC-221
"""限流导致的首红 ≠ 测试红：`flaky-triage` 必须判 `infra_rate_limited`，不许洗成 flaky（issue #8709）。

## 病灶（2026-11-05 实测，PR #8699，**不是推演**）

Actions token 小时配额耗尽时，5 条互不相干的守卫（Secret Scan / Danger Scan / External Authorship /
Contribution Gate / QA Growth Gate）同时 fail-closed，日志原文：

```
⏳ gitleaks license 校验预检：限流（HTTP 403），2.0s 后重试（第 1/3 次）
⛔ gitleaks license 校验预检：限流退避用尽（次数上限，已尝试 3 次，最后一次 HTTP 403） —— **未判定**（exit 3，不得当 0 读）
```

旧口径把这次「**判不了**」（exit 3）当成**测试红** ⇒ `rerun` ⇒ 配额恢复后第二次绿 ⇒
`mark_flaky` + `block/merge` + `flaky/rerun-green` + `gh pr merge --disable-auto`
⇒ **一个与 flaky 完全无关的 PR 被人工闸挡住**，还要人手工摘标签。

机制的核心判据「**第二次绿 ≠ 通过**」是**对的、本单一个字都不动**。它唯一的隐含前提是
「第一次红**是测试红**」—— 本单只修这个**前提判定**：

| # | 判据 | 会红在哪 |
|---|---|---|
| 1 | 失败 job 的日志**只有限流特征**（中英都认）⇒ 判 `infra_rate_limited`：**零重跑 / 零记账 / 零 flaky 标 / 不卸 auto-merge**，但**也不放行** | 判成 `flaky` / 有台账条目 / 打了 `flaky/rerun-green` ⇒ 红 |
| 2 | **负控**：真测试失败（`FAILED tests/…::test_x`）仍走原路径（重跑 ⇒ 第二次绿 ⇒ `mark_flaky`） | 把真 flaky 一起放过 ⇒ 红 |
| 3 | **混合**（一个 job 限流 + 一个 job 真测试红）⇒ 按**真红**处置 | 按限流处置 ⇒ 红（宁可多判一次 flaky，不许放过真红） |
| 4 | 台账不许混进限流条目（`entries` 必须为空） | 限流产生 `flaky` 条目 ⇒ 红 |
| 5 | `exit 3` 的**可见性不许降**：判了 `infra_rate_limited` 仍必须在 job summary / PR 面可见「未判定」 | 静默 / 读起来像「通过」 ⇒ 红 |
| 6 | **机制自证**：扫描面必须**非空**（日志取不到 = **盲**，不是「判定为非限流」） | 0 份日志却报「无异常」⇒ 红 |

## 同一个病的**第二出口**（2026-11-05 现取，实测）

`origin/main` 的 `.github/flaky-ledger.json`：`kind` ∈ {flaky, suspect-window-deterministic} 共 **45** 条，
其中带 `failing_tests` 的 **9** 条 —— 而 **5** 条的失败测试恰好是**同两条**：

```
tests/unit_ci_workflows/test_case_id_claims.py::test_repo_case_id_claims_are_clean
tests/unit_ci_workflows/test_case_id_claims.py::test_repo_corpus_face_is_clean
```

job 全是 `ci workflow helper unit tests`，`rerun_result` 全是 `success`，时间跨度 2026-10-31 → 11-05。
**同两条测试 5 次不是随机波动，是机制**：这两条是「跨在飞 PR 取号」判据 7 的常驻出口，而判据 7 是该文件
**唯一**的联网面（文件头逐字：「**看不到 ⇒ 红**（fail-closed）……❓ 不许读成 ✅」）⇒ Actions token 限流时
**必然红**，配额恢复后重跑就绿。

⇒ 这一族**有** `FAILED <node id>` 行，所以「有 FAILED 行就是真测试红」这条朴素规则会**原样复现**本单的病。
判据必须下沉到失败**记录的整段错误文本**（`FAILED <node> - …` 及其**续行** —— 真实失败文本是多行的，
实测 `取号登记台账判据报红：` 的下一行才是 `HTTP 403（**限流**：X-RateLimit-Remaining=…）`）：

- **每一条**失败记录的错误文本都带限流特征 ⇒ 环境态（`rate_limited`）；
- **任一条**不带 ⇒ 真红（宁缺勿滥）；
- node id 里自带 rate-limit 字样**不算**（匹配只看错误文本，不看测试名）；
- `判定不了` / `无法判定` **有意不收**：它们也用于「无 token」「超预算」「超页数上限」「缺字段」
  —— 那不是限流（无 token 更是真配置缺失），收进来就是把真失效洗成环境态 ⇒ 那些仍走原路径。

## 为什么选「读失败 job 日志」（修法 A）而不是另两个

- **B（已知限流守卫名单）**：名单是**第二份会腐烂的真值** —— 今天 5 条，明天新加一条守卫就静默失效，
  且判据只能钉住「名单 == workflow 真取数面」，钉不住「新守卫叫什么」。日志判据与 job 名无关。
- **C（限流时让守卫判 `neutral`）**：把 fail-closed 的 `exit 3` 洗成「没红」= 本仓最贵的
  「绿了但没跑」同族；且要动 5 个守卫脚本（爆炸半径大）。本单**不改任何守卫的退出码**。
- **A** 的代价是「一次日志读」（≤ `MAX_LOG_FETCHES` 份；`…/logs` 端点不计 `core` 配额），
  而它**结构性无法放行**：那次 job 仍然是红的 ⇒ required 检查仍不满足 ——
  本类只是「不把它记成 flaky、不白烧一次重跑、并在 PR 面写清为什么」。

## 红证（每条判据都有注入式红证，见 `TestRedProofs`）

源码级红证用**内容变异**（把中文 marker 从 `RATE_LIMIT_MARKERS` 里摘掉）再 `exec` 成模块：
同一份 bundle 在真模块上判 `infra_rate_limited`、在变异体上判 `mark_flaky` ⇒ 单变量对照，
且注入**自证生效**（变异前后源码必须不同、替换必须恰好命中 1 处）。
"""
import importlib.util
import types
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".github" / "scripts"
SCRIPT_PATH = SCRIPTS / "flaky_ledger.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "flaky-triage.yml"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FL = _load(SCRIPT_PATH, "migao_flaky_ledger_rate_limit_8709")
REAL_SOURCE = SCRIPT_PATH.read_text(encoding="utf-8")
REAL_WORKFLOW_TEXT = WORKFLOW_PATH.read_text(encoding="utf-8")
WORKFLOW = yaml.safe_load(REAL_WORKFLOW_TEXT)
STEPS = WORKFLOW["jobs"]["triage"]["steps"]


# ── 语料：现场日志原文（issue #8709 body 逐字；中文限流 + exit 3 未判定） ─────────

INCIDENT_LOG = """2026-11-05T02:41:11.0000000Z ⏳ gitleaks license 校验预检：限流（HTTP 403），2.0s 后重试（第 1/3 次）
2026-11-05T02:41:13.0000000Z ⏳ gitleaks license 校验预检：限流（HTTP 403），4.0s 后重试（第 2/3 次）
2026-11-05T02:41:17.0000000Z ⛔ gitleaks license 校验预检：限流退避用尽（次数上限，已尝试 3 次，最后一次 HTTP 403） —— **未判定**（exit 3，不得当 0 读）
"""

#: 真测试红的日志（pytest `short test summary info` 段 + 一条失败行）。**负控的语料**。
REAL_TEST_FAILURE_LOG = """2026-11-05T02:41:11.0000000Z =========================== short test summary info ============================
2026-11-05T02:41:11.0000000Z FAILED tests/unit_ci_workflows/test_flaky_triage.py::TestRerunOnce::test_max_attempts_is_two - AssertionError: 3 != 2
2026-11-05T02:41:11.0000000Z ========================= 1 failed, 12 passed in 0.42s =========================
"""

#: 「任意 403」不是限流（权限问题必须照旧 fail-closed）。
PERMISSION_403_LOG = "2026-11-05T02:41:11.0000000Z 403 Resource not accessible by integration\n"

#: 🔴 #8709 的**第二出口**（实测，同一份台账）：`ci workflow helper unit tests` 里的两条**联网判据**
#: （`tests/unit_ci_workflows/test_case_id_claims.py` 的判据 7）在限流时 fail-closed，失败文本由该文件的
#: `_http_error_text()` 产出 —— 形态是 `HTTP 403（**限流**：X-RateLimit-Remaining=0 · Reset=… · Retry-After=…）`
#: 或 `HTTP 403（疑似限流，但响应头读不到）`。`origin/main` 现取：`kind` ∈ {flaky, suspect-window-deterministic}
#: 共 **45** 条，其中带 `failing_tests` 的 **9** 条，而这**两条** node id 占 **5** 条（同源、非随机波动）。
CI_HELPER_RATE_LIMIT_LOG = """2026-11-05T02:41:10.0000000Z =========================== short test summary info ============================
2026-11-05T02:41:10.0000000Z FAILED tests/unit_ci_workflows/test_case_id_claims.py::test_repo_case_id_claims_are_clean - AssertionError: 取号登记台账判据报红：
2026-11-05T02:41:10.0000000Z   - PR #8709 的 claims 目录读不到：HTTP 403（**限流**：X-RateLimit-Remaining=0 · Reset=1762340000 · Retry-After=60）
2026-11-05T02:41:10.0000000Z FAILED tests/unit_ci_workflows/test_case_id_claims.py::test_repo_corpus_face_is_clean - AssertionError: 跨在飞 PR 的语料取号面判红：
2026-11-05T02:41:10.0000000Z   - ❓ 判定不了：open PR 列表读不到；HTTP 403（疑似限流，但响应头读不到）
2026-11-05T02:41:10.0000000Z ========================= 2 failed, 15 passed in 41.2s ========================
"""

#: 「真的没权限」的 403（**不是**限流）：`_http_error_text` 在 `_is_rate_limited()` 为假时只写 `HTTP 403`。
#: 它**必须**照旧走原路径（fail-closed：真失效不许被洗成环境态）。
CI_HELPER_PERMISSION_LOG = """2026-11-05T02:41:10.0000000Z =========================== short test summary info ============================
2026-11-05T02:41:10.0000000Z FAILED tests/unit_ci_workflows/test_case_id_claims.py::test_repo_case_id_claims_are_clean - AssertionError: 取号登记台账判据报红：
2026-11-05T02:41:10.0000000Z   - PR #8709 的 claims 目录读不到：HTTP 403
2026-11-05T02:41:10.0000000Z ========================= 1 failed, 16 passed in 12.0s ========================
"""

#: **无凭据**的「判定不了」（`GITHUB_TOKEN` / `GH_TOKEN` 都没有）⇒ **不是**限流，重跑也不会变好。
#: 🔴 这也是**有意不收** `判定不了`/`无法判定` 这两个词当 marker 的原因（它们同时用于无 token /
#: 超预算 / 超页数上限 / 缺字段 —— 收进来会把真失效洗成环境态）。
CI_HELPER_NO_TOKEN_LOG = """2026-11-05T02:41:10.0000000Z =========================== short test summary info ============================
2026-11-05T02:41:10.0000000Z FAILED tests/unit_ci_workflows/test_case_id_claims.py::test_repo_case_id_claims_are_clean - AssertionError: 取号登记台账判据报红：
2026-11-05T02:41:10.0000000Z   - ❓ 判定不了（无 token）：GITHUB_TOKEN / GH_TOKEN 都没有
2026-11-05T02:41:10.0000000Z ========================= 1 failed, 16 passed in 1.0s ========================
"""

GUARD_JOB = "Secret Scan"


# ── 夹具（形状与 GitHub REST `/actions/runs/{id}` + `/attempts/{n}/jobs` 同源） ──


def make_run(attempt=1, conclusion="failure", pr=8699, run_id=8709):
    return {
        "id": run_id,
        "name": "PR Check",
        "event": "pull_request",
        "conclusion": conclusion,
        "run_attempt": attempt,
        "head_branch": "fix/some-branch",
        "head_sha": "c" * 40,
        "html_url": f"https://github.com/o/r/actions/runs/{run_id}",
        "updated_at": "2026-11-05T02:50:00Z",
        "pull_requests": [{"number": pr}],
    }


def make_job(name=GUARD_JOB, conclusion="failure", jid=111,
             failed_step="Run gitleaks license 校验预检"):
    if conclusion == "failure":
        steps = [{"name": "Set up job", "conclusion": "success"},
                 {"name": failed_step, "conclusion": "failure"}]
    else:
        steps = [{"name": "Set up job", "conclusion": "success"},
                 {"name": failed_step, "conclusion": "success"}]
    return {"id": jid, "name": name, "conclusion": conclusion, "steps": steps}


def make_bundle(run=None, jobs=None, prior_jobs=None):
    return {"run": run if run is not None else make_run(),
            "jobs": list(jobs or []), "prior_jobs": prior_jobs}


def classify(bundle, logs):
    """用**真的取数函数**把「每个失败 job 的日志分类」写进 bundle。

    `logs` = `{job_id: 日志文本}`（缺 key ⇒ 抛 ⇒ 走「拉不到」路径，用于**扫描面为空**的判据）。
    刻意**不手搓** `bundle[FAILURE_KINDS_FIELD]`：手搓就是第二份形状定义，会与实现悄悄漂开。
    """
    def fetch_log(repo, jid):
        if jid not in logs:
            raise RuntimeError(f"job {jid} 的日志已被清理")
        return logs[jid]

    return FL.collect_failure_kinds(bundle, "o/r", fetch_log=fetch_log)


def incident_second_green():
    """现场形态：第一次红是**限流**（guard job），配额恢复后**第二次绿**。"""
    b = make_bundle(run=make_run(attempt=2, conclusion="success"),
                    jobs=[make_job(conclusion="success", jid=111)],
                    prior_jobs=[make_job(jid=111)])
    classify(b, {111: INCIDENT_LOG})
    return b


# ── ① marker 射程：中英都认，但不许把「任意 403」当限流 ────────────────────────


class TestRateLimitMarkers:
    def test_chinese_retry_line_is_recognised(self):
        assert FL.is_rate_limit_error(
            "⏳ gitleaks license 校验预检：限流（HTTP 403），2.0s 后重试（第 1/3 次）") is True

    def test_chinese_exhausted_backoff_line_is_recognised(self):
        assert FL.is_rate_limit_error(
            "⛔ gitleaks license 校验预检：限流退避用尽（次数上限，已尝试 3 次，"
            "最后一次 HTTP 403） —— **未判定**（exit 3，不得当 0 读）") is True

    def test_english_marker_still_recognised(self):
        assert FL.is_rate_limit_error(
            "API rate limit exceeded for installation ID 12345") is True

    def test_bare_403_is_not_a_rate_limit(self):
        """负控：`403 Resource not accessible by integration` 是**权限**问题，照旧 fail-closed。"""
        assert FL.is_rate_limit_error(PERMISSION_403_LOG) is False

    def test_markers_are_english_and_chinese(self):
        assert "限流" in FL.RATE_LIMIT_MARKERS
        assert "rate limit" in FL.RATE_LIMIT_MARKERS


# ── ② 单份日志的判定（纯函数） ────────────────────────────────────────────────


class TestLogVerdict:
    def test_rate_limit_only_log_is_rate_limited(self):
        e = FL.rate_limit_only_evidence(INCIDENT_LOG)
        assert e["verdict"] == FL.FEATURE_RATE_LIMITED
        assert e["markers"] == ["限流"]
        assert e["test_failures"] == []

    def test_real_test_failure_log_is_not_rate_limited(self):
        e = FL.rate_limit_only_evidence(REAL_TEST_FAILURE_LOG)
        assert e["verdict"] == FL.FEATURE_NOT_RATE_LIMITED
        assert e["test_failures"] == [
            "tests/unit_ci_workflows/test_flaky_triage.py::TestRerunOnce::test_max_attempts_is_two"]

    def test_mixed_log_is_not_rate_limited(self):
        """同一份日志里既有真测试红又有「限流」字样 ⇒ **按真红**（宁缺勿滥）。"""
        e = FL.rate_limit_only_evidence(INCIDENT_LOG + REAL_TEST_FAILURE_LOG)
        assert e["verdict"] == FL.FEATURE_NOT_RATE_LIMITED

    def test_permission_403_log_is_not_rate_limited(self):
        e = FL.rate_limit_only_evidence(PERMISSION_403_LOG)
        assert e["verdict"] == FL.FEATURE_NOT_RATE_LIMITED
        assert e["markers"] == []

    def test_empty_log_is_undecided_not_non_rate_limited(self):
        """0 命中 = **盲**，不是「判定为非限流」。"""
        e = FL.rate_limit_only_evidence("")
        assert e["verdict"] == FL.FEATURE_UNKNOWN
        assert "未判定" in e["why"]

    def test_verdict_carries_the_matched_marker_text(self):
        """可见性：判定必须能说出**命中了什么**（不是只有一个布尔）。"""
        e = FL.rate_limit_only_evidence(INCIDENT_LOG)
        assert "限流退避用尽" in e["why"] or "限流" in e["markers"]


# ── ②′ pytest 面（**同一个病的第二出口**）：判「失败行的错误文本」而不是「有没有 FAILED 行」──


class TestPytestOutlet:
    """`ci workflow helper unit tests` 的形态：**有** `FAILED` 行，但失败原因是限流。

    这一族是「只看有没有 FAILED 行」这条朴素规则的**反例**：真测试红与「限流致的判不了」
    都会产出 `FAILED <node> - …` ⇒ 判据必须下沉到 **错误文本**（`FAILED <node> - ` 之后那段）。
    """

    def test_rate_limit_in_every_failure_text_is_rate_limited(self):
        e = FL.rate_limit_only_evidence(CI_HELPER_RATE_LIMIT_LOG)
        assert e["verdict"] == FL.FEATURE_RATE_LIMITED
        assert e["test_failures"] == [
            "tests/unit_ci_workflows/test_case_id_claims.py::test_repo_case_id_claims_are_clean",
            "tests/unit_ci_workflows/test_case_id_claims.py::test_repo_corpus_face_is_clean"]

    def test_real_permission_403_stays_real_red(self):
        """**负控**：`HTTP 403`（没被判定为限流的 403）⇒ 真红，不许洗成环境态。"""
        e = FL.rate_limit_only_evidence(CI_HELPER_PERMISSION_LOG)
        assert e["verdict"] == FL.FEATURE_NOT_RATE_LIMITED
        assert e["markers"] == []

    def test_missing_credentials_stays_real_red(self):
        """**负控**：`判定不了（无 token）` **不是**限流（无 token 重跑一万次也一样）。"""
        e = FL.rate_limit_only_evidence(CI_HELPER_NO_TOKEN_LOG)
        assert e["verdict"] == FL.FEATURE_NOT_RATE_LIMITED

    def test_marker_only_in_the_test_name_is_not_rate_limited(self):
        """判据只落在**错误文本**上：node id 自带 rate-limit 字样 ⇒ 仍按真红（否则会把主题当原因）。"""
        log = ("2026-11-05T02:41:10Z short test summary info\n"
               "2026-11-05T02:41:10Z FAILED tests/x/test_rate_limit_guard.py::"
               "test_rate_limit_returns_429 - AssertionError: 3 != 2\n")
        e = FL.rate_limit_only_evidence(log)
        assert e["verdict"] == FL.FEATURE_NOT_RATE_LIMITED

    def test_one_unmarked_failure_is_enough_to_go_the_real_red_path(self):
        """混合（一条带限流、一条纯断言）⇒ 按真红（宁缺勿滥）。"""
        log = CI_HELPER_RATE_LIMIT_LOG + (
            "2026-11-05T02:41:10Z FAILED tests/x/test_y.py::test_z - AssertionError: 3 != 2\n")
        e = FL.rate_limit_only_evidence(log)
        assert e["verdict"] == FL.FEATURE_NOT_RATE_LIMITED

    def test_second_green_after_the_pytest_outlet_is_not_flaky(self):
        """端到端：这条形态的「第二次绿」**不得**被判 flaky（台账里就是这个被记成了 flaky）。"""
        b = make_bundle(run=make_run(attempt=2, conclusion="success"),
                        jobs=[make_job(name="ci workflow helper unit tests",
                                       conclusion="success", jid=333)],
                        prior_jobs=[make_job(name="ci workflow helper unit tests",
                                             jid=333, failed_step="Run ci workflow helper tests")])
        classify(b, {333: CI_HELPER_RATE_LIMIT_LOG})
        d = FL.decide(b)
        assert d["action"] == "infra_rate_limited"
        assert d["entries"] == []

    def test_permission_403_second_green_still_marks_flaky(self):
        """**负控的端到端**：真的没权限 ⇒ 仍走原路径（第二次绿 ⇒ flaky），证明判据没变成「一律 infra」。"""
        b = make_bundle(run=make_run(attempt=2, conclusion="success"),
                        jobs=[make_job(name="ci workflow helper unit tests",
                                       conclusion="success", jid=333)],
                        prior_jobs=[make_job(name="ci workflow helper unit tests",
                                             jid=333, failed_step="Run ci workflow helper tests")])
        classify(b, {333: CI_HELPER_PERMISSION_LOG})
        assert FL.decide(b)["action"] == "mark_flaky"


# ── ③ 扫描面自证（判据 6）：0 份日志 = 盲，不是通过 ─────────────────────────────


class TestScanSurfaceSelfProof:
    def test_real_incident_log_hits_the_markers(self):
        """机制自证：现场日志**真的**命中标记（不是「假定它命中」）。"""
        assert FL.rate_limit_only_evidence(INCIDENT_LOG)["markers"] == ["限流"]

    def test_reading_reports_scanned_and_total(self):
        b = make_bundle(run=make_run(attempt=1, conclusion="failure"),
                        jobs=[make_job(jid=111)], prior_jobs=None)
        reading = classify(b, {111: INCIDENT_LOG})
        assert reading["total"] == 1
        assert reading["scanned"] == 1
        assert reading["blind"] is False

    def test_unreachable_logs_are_blind_not_green(self):
        b = make_bundle(run=make_run(attempt=1, conclusion="failure"),
                        jobs=[make_job(jid=111)], prior_jobs=None)
        reading = classify(b, {})          # 日志已被清理 ⇒ 一份都取不到
        assert reading["total"] == 1
        assert reading["scanned"] == 0
        assert reading["blind"] is True
        assert reading["failed"][0]["key"] == [1, GUARD_JOB]

    def test_blind_scan_surface_is_visible_in_the_summary(self):
        b = make_bundle(run=make_run(attempt=1, conclusion="failure"),
                        jobs=[make_job(jid=111)], prior_jobs=None)
        classify(b, {})
        text = FL.render_summary(FL.decide(b))
        assert "扫描面" in text
        assert "::warning::" in text
        assert "未判定" in text

    def test_classification_is_wired_into_the_workflow(self):
        names = [str(s.get("name") or "") for s in STEPS]
        assert any(FL.CLASSIFY_FAILURES_COMMAND in str(s.get("run") or "") for s in STEPS)
        classify_idx = next(i for i, s in enumerate(STEPS)
                            if FL.CLASSIFY_FAILURES_COMMAND in str(s.get("run") or ""))
        decide_idx = next(i for i, s in enumerate(STEPS) if s.get("id") == "decide")
        assert classify_idx < decide_idx, f"分类步骤必须先于 decide：{names}"
        body = str(STEPS[classify_idx].get("run") or "")
        assert "--bundle /tmp/flaky-bundle.json" in body
        assert "exit 1" in body, "分类没跑成必须 fail-closed（未跑 ≠ 通过）"


# ── ④ 分流判定（判据 1/2/3/4/5） ─────────────────────────────────────────────


class TestDecideRateLimited:
    def test_first_failure_with_rate_limit_log_does_not_rerun(self):
        b = make_bundle(run=make_run(attempt=1, conclusion="failure"),
                        jobs=[make_job(jid=111)], prior_jobs=None)
        classify(b, {111: INCIDENT_LOG})
        d = FL.decide(b)
        assert d["action"] == "infra_rate_limited"
        assert d["kind"] is None
        assert d["entries"] == []

    def test_second_green_after_rate_limited_first_red_is_not_flaky(self):
        d = FL.decide(incident_second_green())
        assert d["action"] == "infra_rate_limited"
        assert d["infra_rate_limited"] is True
        assert d["environment_state"] is True
        assert d["kind"] is None

    def test_rate_limited_never_writes_a_ledger_entry(self):
        """判据 4：台账不许混进限流条目（`entries` 必须为空 ⇒ 不会 append）。"""
        d = FL.decide(incident_second_green())
        assert d["entries"] == []
        assert "flaky" not in {e.get("kind") for e in d["entries"]}

    def test_negative_control_real_test_failure_still_marks_flaky(self):
        """判据 2（**负控**）：真测试红仍走原路径 ⇒ 重跑 ⇒ 第二次绿 ⇒ `mark_flaky`。"""
        jobs = [make_job(jid=222, failed_step="Run unit tests")]
        first = make_bundle(run=make_run(attempt=1, conclusion="failure"),
                            jobs=jobs, prior_jobs=None)
        classify(first, {222: REAL_TEST_FAILURE_LOG})
        d1 = FL.decide(first)
        assert d1["action"] == "rerun"

        second = make_bundle(run=make_run(attempt=2, conclusion="success"),
                             jobs=[make_job(conclusion="success", jid=222,
                                            failed_step="Run unit tests")],
                             prior_jobs=jobs)
        classify(second, {222: REAL_TEST_FAILURE_LOG})
        d2 = FL.decide(second)
        assert d2["action"] == "mark_flaky"
        assert [e["kind"] for e in d2["entries"]] == ["flaky"]

    def test_mixed_jobs_follow_the_real_red_path(self):
        """判据 3：一个 job 限流 + 一个 job 真测试红 ⇒ **按真红**处置。"""
        jobs = [make_job(jid=111),
                make_job(name="mini-app typecheck + unit tests", jid=222,
                         failed_step="Run unit tests")]
        logs = {111: INCIDENT_LOG, 222: REAL_TEST_FAILURE_LOG}
        first = make_bundle(run=make_run(attempt=1, conclusion="failure"),
                            jobs=jobs, prior_jobs=None)
        classify(first, logs)
        assert FL.decide(first)["action"] == "rerun"

        second = make_bundle(run=make_run(attempt=2, conclusion="success"),
                             jobs=[make_job(conclusion="success", jid=111),
                                   make_job(name="mini-app typecheck + unit tests",
                                            conclusion="success", jid=222,
                                            failed_step="Run unit tests")],
                             prior_jobs=jobs)
        classify(second, logs)
        d = FL.decide(second)
        assert d["action"] == "mark_flaky"
        assert "flaky" in [e["kind"] for e in d["entries"]]

    def test_partially_unscanned_mix_is_treated_as_real_red(self):
        """一个 job 限流 + 另一个 job 日志取不到 ⇒ **不判限流**（宁缺勿滥）。"""
        jobs = [make_job(jid=111), make_job(name="Danger Scan", jid=222)]
        first = make_bundle(run=make_run(attempt=1, conclusion="failure"),
                            jobs=jobs, prior_jobs=None)
        reading = classify(first, {111: INCIDENT_LOG})   # 222 取不到
        assert reading["scanned"] == 1
        assert reading["total"] == 2
        assert reading["blind"] is False
        assert FL.decide(first)["action"] == "rerun"

    def test_the_incident_shape_of_five_simultaneous_guards_is_fully_covered(self):
        """🔴 **现场形态回归**：5 条守卫同时红（#8709 实测）⇒ 必须**全部**读到日志 ⇒ 判限流。

        这条钉的是「取数上限」这个**最容易把修复变成空修**的参数：现场是 5 条，
        若上限取成台账面的 4 ⇒ 恰好漏一条 ⇒ `unknown` ⇒ 退回重跑 ⇒ **本单没修**。
        """
        guards = ["Secret Scan", "Danger Scan", "External Authorship",
                  "Contribution Gate", "QA Growth Gate"]
        jobs = [make_job(name=name, jid=500 + i) for i, name in enumerate(guards)]
        assert FL.MAX_CLASSIFY_FETCHES >= len(jobs), (
            f"分类上限 {FL.MAX_CLASSIFY_FETCHES} 必须覆盖现场的 {len(jobs)} 条守卫")
        first = make_bundle(run=make_run(attempt=1, conclusion="failure"),
                            jobs=jobs, prior_jobs=None)
        reading = classify(first, {500 + i: INCIDENT_LOG for i in range(len(guards))})
        assert reading["scanned"] == len(guards)
        assert reading["total"] == len(guards)
        assert len(reading["rate_limited"]) == len(guards)
        assert FL.decide(first)["action"] == "infra_rate_limited"

        second = make_bundle(run=make_run(attempt=2, conclusion="success"),
                             jobs=[make_job(name=name, conclusion="success", jid=500 + i)
                                   for i, name in enumerate(guards)],
                             prior_jobs=jobs)
        classify(second, {500 + i: INCIDENT_LOG for i in range(len(guards))})
        d = FL.decide(second)
        assert d["action"] == "infra_rate_limited"
        assert d["entries"] == []

    def test_over_budget_truncation_is_loud_and_falls_back(self):
        """超上限只可能发生在病态 run：截断必须**出声**，且分流按原路径（宁缺勿滥）。"""
        jobs = [make_job(name=f"guard-{i}", jid=900 + i) for i in range(4)]
        b = make_bundle(run=make_run(attempt=1, conclusion="failure"),
                        jobs=jobs, prior_jobs=None)
        reading = classify(b, {900 + i: INCIDENT_LOG for i in range(4)})
        # 用**显式小上限**模拟截断（不靠现场数据凑到 20 条）
        b2 = make_bundle(run=make_run(attempt=1, conclusion="failure"),
                         jobs=jobs, prior_jobs=None)
        reading = FL.collect_failure_kinds(b2, "o/r",
                                          fetch_log=lambda repo, jid: INCIDENT_LOG,
                                          max_fetches=2)
        assert reading["scanned"] == 2
        assert reading["total"] == 4
        assert len(reading["failed"]) == 2
        assert "MAX_LOG_FETCHES" in reading["failed"][0]["why"] or "上限" in reading["failed"][0]["why"]
        assert FL.decide(b2)["action"] == "rerun"

    def test_verdict_is_attached_for_visibility(self):
        b = make_bundle(run=make_run(attempt=1, conclusion="failure"),
                        jobs=[make_job(jid=111)], prior_jobs=None)
        classify(b, {111: INCIDENT_LOG})
        d = FL.decide(b)
        assert d["failure_kinds"]["scanned"] == 1
        assert d["failure_kinds"]["total"] == 1
        assert d["failure_kinds"]["jobs"][0]["job"] == GUARD_JOB


# ── ⑤ 可见性（判据 5）：判了「未判定」必须**看得出来** ─────────────────────────


class TestUndecidedStaysVisible:
    def test_summary_says_undecided_and_warns(self):
        text = FL.render_summary(FL.decide(incident_second_green()))
        assert "infra_rate_limited" in text
        assert "::warning::" in text
        assert "未判定" in text

    def test_summary_never_reads_like_a_pass(self):
        """反形态：读起来像「通过 / 没有失败」就是「绿了但没跑」的同族。"""
        text = FL.render_summary(FL.decide(incident_second_green()))
        for word in ("已通过", "全部通过", "没有失败"):
            assert word not in text, f"限流的「未判定」不得渲染成「{word}」：{text}"

    def test_comment_says_undecided_and_not_flaky(self):
        text = FL.render_comment(FL.decide(incident_second_green()))
        assert "infra_rate_limited" in text
        assert "未判定" in text
        assert "flaky/rerun-green" not in text, (
            "限流致 exit 3 的评论不得出现 flaky 标签名 —— 那会把「未判定」读成「已查清是 flaky」")
        assert "重跑才绿" not in text

    def test_comment_tells_the_human_what_to_do_after_the_quota_window(self):
        text = FL.render_comment(FL.decide(incident_second_green()))
        assert "配额" in text
        assert "gh run rerun" in text


# ── ⑥ workflow 接线：打了什么标、**没**做什么 ────────────────────────────────


class TestWorkflowWiring:
    def _rate_limited_step(self):
        return next(s for s in STEPS
                    if str(s.get("if") or "") ==
                    "steps.decide.outputs.action == 'infra_rate_limited'")

    def test_rate_limited_step_exists_and_labels_infra(self):
        body = str(self._rate_limited_step().get("run") or "")
        assert '--add-label "infra/rate-limited"' in body
        assert 'gh label create "infra/rate-limited"' in body
        assert "infra/rate-limited" in body.split("复核")[0]

    def test_rate_limited_step_never_marks_flaky(self):
        body = str(self._rate_limited_step().get("run") or "")
        assert '--add-label "flaky/rerun-green"' not in body
        assert '--add-label "block/merge"' not in body

    def test_rate_limited_step_never_disables_auto_merge(self):
        body = str(self._rate_limited_step().get("run") or "")
        assert "--disable-auto" not in body

    def test_label_landing_is_verified_fail_closed(self):
        body = str(self._rate_limited_step().get("run") or "")
        assert "::error::" in body
        assert "exit 1" in body
        assert 'case ",$LABELS," in *",infra/rate-limited,"*' in body

    def test_comment_step_covers_the_rate_limited_action(self):
        step = next(s for s in STEPS if "③ PR 评论" in str(s.get("name") or ""))
        cond = str(step.get("if") or "")
        assert "infra_rate_limited" in cond
        assert "pr != ''" in cond

    def test_rerun_step_is_still_owned_by_the_rerun_action(self):
        """红线不变：`gh run rerun` 仍只由 `action == 'rerun'` 独占（限流不许触发重跑）。"""
        rerun_steps = [s for s in STEPS
                       if "gh run rerun" in str(s.get("run") or "")]
        assert len(rerun_steps) == 1
        assert str(rerun_steps[0].get("if") or "") == "steps.decide.outputs.action == 'rerun'"


# ── ⑦ 独立不变式检查器 + 注入式红证 ──────────────────────────────────────────


def rate_limit_policy_violations(decide_fn) -> list:
    """#8709 的红线（**独立**检查器：只喂夹具看输出，换掉实现也能判）。

    刻意不读 `decide` 的内部结构 ⇒ 注入版（变异体）也能被它判。
    """
    bad = []

    def first_failure(log_text, job=None):
        b = make_bundle(run=make_run(attempt=1, conclusion="failure"),
                        jobs=[job or make_job(jid=111)], prior_jobs=None)
        classify(b, {111: log_text})
        return decide_fn(b)

    def second_green(log_text, job=None):
        j = job or make_job(jid=111)
        b = make_bundle(run=make_run(attempt=2, conclusion="success"),
                        jobs=[make_job(conclusion="success", jid=111)], prior_jobs=[j])
        classify(b, {111: log_text})
        return decide_fn(b)

    # ① 限流首红 ⇒ 不许重跑（重跑只会再撞配额）
    d = first_failure(INCIDENT_LOG)
    if d["action"] == "rerun":
        bad.append("限流致 exit 3 的首次红仍触发重跑（白烧一次配额）")
    # ② 限流首红 + 第二次绿 ⇒ 不许 flaky / 不许记账
    d = second_green(INCIDENT_LOG)
    if d["action"] in ("mark_flaky", "mark_suspect"):
        bad.append(f"限流致 exit 3 被洗成 {d['action']!r}（本单要治的误判）")
    if d["entries"]:
        bad.append(f"限流产生了 {len(d['entries'])} 条台账条目（台账是证据，不许混假证据）")
    if d.get("kind") == "flaky":
        bad.append("限流判出 kind=flaky")
    # ③ 负控：真测试红**必须**照旧被放过（不许「一律判 infra」）
    d = first_failure(REAL_TEST_FAILURE_LOG,
                      make_job(jid=222, failed_step="Run unit tests"))
    if d["action"] != "rerun":
        bad.append(f"真测试红的首次失败给出 {d['action']!r}（应为 rerun）⇒ 真 flaky 被一起放过")
    d = second_green(REAL_TEST_FAILURE_LOG,
                     make_job(jid=111, failed_step="Run unit tests"))
    if d["action"] != "mark_flaky":
        bad.append(f"真测试红的第二次绿给出 {d['action']!r}（应为 mark_flaky）⇒ 真 flaky 被放过")
    # ④ 混合 ⇒ 按真红（宁可多判一次 flaky，不许放过真红）
    jobs = [make_job(jid=111),
            make_job(name="mini-app typecheck + unit tests", jid=222,
                     failed_step="Run unit tests")]
    b = make_bundle(run=make_run(attempt=1, conclusion="failure"), jobs=jobs, prior_jobs=None)
    classify(b, {111: INCIDENT_LOG, 222: REAL_TEST_FAILURE_LOG})
    if decide_fn(b)["action"] != "rerun":
        bad.append("混合（限流 + 真红）被按限流处置 ⇒ 真红被放过")
    # ⑤ 未判定必须可见（防「看起来全绿」）
    text = FL.render_summary(second_green(INCIDENT_LOG))
    if "未判定" not in text or "::warning::" not in text:
        bad.append(f"限流的「未判定」在 job summary 上不可见：{text!r}")
    return bad


class TestPolicyInvariants:
    def test_real_decide_satisfies_every_red_line(self):
        assert rate_limit_policy_violations(FL.decide) == []


class TestRedProofs:
    def test_red_proof_leaking_rate_limited_into_flaky(self):
        """红证：把 `infra_rate_limited` 换成 `mark_flaky` ⇒ 不变式**必须**红。"""
        def leaky(b, max_attempts=FL.MAX_ATTEMPTS, **kw):
            d = FL.decide(b, max_attempts, **kw)
            if d["action"] == "infra_rate_limited":
                return dict(d, action="mark_flaky", kind="flaky",
                            entries=[{"kind": "flaky"}])
            return d

        violations = rate_limit_policy_violations(leaky)
        assert any("洗成" in v for v in violations), violations
        assert any("台账条目" in v for v in violations), violations

    def test_red_proof_treating_everything_as_infra(self):
        """红证：把「一律判 infra」注回 ⇒ 负控**必须**红（证明负控有牙）。"""
        def leaky(b, max_attempts=FL.MAX_ATTEMPTS, **kw):
            d = FL.decide(b, max_attempts, **kw)
            if d["action"] in ("rerun", "mark_flaky"):
                return dict(d, action="infra_rate_limited", kind=None, entries=[])
            return d

        violations = rate_limit_policy_violations(leaky)
        assert any("真 flaky 被一起放过" in v or "真 flaky 被放过" in v for v in violations), \
            violations

    def test_red_proof_removing_the_chinese_marker_brings_the_misjudgement_back(self):
        """**源码级单变量对照**：摘掉中文 marker ⇒ 同一份 bundle 退回 `mark_flaky`。

        这一条同时是「修了但没证明它原来会红」的反面：变异体**就是改前的行为**。
        """
        # 注入锚 = markers 表里的**中文**那一项（它是「认不认中文日志」的单变量开关）
        anchor = '"ratelimit",\n                      "限流")'
        assert REAL_SOURCE.count(anchor) == 1, (
            "注入锚必须恰好命中 1 处（锚漂了 ⇒ 注入没生效会把「判据没牙」报成「已修复」）")
        mutated_source = REAL_SOURCE.replace(anchor, '"ratelimit")')
        assert mutated_source != REAL_SOURCE, "变异没生效"

        mod = types.ModuleType("migao_flaky_ledger_rate_limit_mutant")
        mod.__file__ = str(SCRIPT_PATH)
        exec(compile(mutated_source, str(SCRIPT_PATH), "exec"), mod.__dict__)  # noqa: S102

        b = make_bundle(run=make_run(attempt=2, conclusion="success"),
                        jobs=[make_job(conclusion="success", jid=111)],
                        prior_jobs=[make_job(jid=111)])
        def fetch_log(repo, jid):
            return INCIDENT_LOG
        mod.collect_failure_kinds(b, "o/r", fetch_log=fetch_log)
        mutant_decision = mod.decide(b)
        assert mutant_decision["action"] == "mark_flaky", mutant_decision
        assert [e["kind"] for e in mutant_decision["entries"]] == ["flaky"]

        real_b = make_bundle(run=make_run(attempt=2, conclusion="success"),
                             jobs=[make_job(conclusion="success", jid=111)],
                             prior_jobs=[make_job(jid=111)])
        FL.collect_failure_kinds(real_b, "o/r", fetch_log=fetch_log)
        assert FL.decide(real_b)["action"] == "infra_rate_limited"

    def test_red_proof_dropping_the_classification_step_from_the_workflow(self):
        """红证：从 workflow 摘掉分类步骤 ⇒ 接线判据**必须**红。"""
        anchor = "classify-failures"
        assert REAL_WORKFLOW_TEXT.count(anchor) == 1, "注入锚必须恰好命中 1 处"
        mutated = yaml.safe_load(REAL_WORKFLOW_TEXT.replace(anchor, "noop-classify"))
        steps = mutated["jobs"]["triage"]["steps"]
        assert not any(FL.CLASSIFY_FAILURES_COMMAND in str(s.get("run") or "")
                       for s in steps), "变异没生效"
