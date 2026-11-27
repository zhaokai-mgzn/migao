# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012 ——
#   「CI workflow 结构由 pytest 单测验证」是 `.github/cases/misc.yml` 里已登记的形态。）
"""#9269 缺陷 3：台账 `attempts` 必须「**一次尝试一条事实**」（L0，离线、零 LLM、秒级）。

病灶（现取读数，不是照抄 issue 文本）
------------------------------------
`build_entries` 旧实现：只要 `prior_failed_jobs` 里有同名 job，就把它的读数当成「上一次尝试」
记进 `attempts`，且 `prev_attempt = max(facts_attempt - 1, 1)`。于是「**重跑第二次绿**」这条路径上
（`prior_jobs` 与被记账的 `first_failed` 都来自 attempt 1）**同一次尝试被记两遍**：

    run_id=40497531264 / job=`admin-api unit tests`
    attempts = [{attempt: 1, timestamp: 2026-10-27T11:43:31Z},   ← 同一次
                {attempt: 1, timestamp: 2026-10-27T11:43:31Z}]   ← 同一份事实，记了第二遍

- 全库现取：1377 条里 **40 条**是这个形态，且 `rerun_result` **全部**是 `success`（= 全部来自那条路径）；
- 后果不是「难看」：`attest` 靠**两条事实**做断言比对 ⇒ 同源两条会被读成「两次都红、断言逐字相同」
  ⇒ 把「只有一次尝试」升级成**确定性失败**（假确定性）。而 `gh api …/attempts/2/jobs` 明明有 attempt 2。

判据（每条都会红）
------------------
1. 两次尝试的夹具 ⇒ `attempts` 必须是 `[attempt=1, attempt=2]` **两条不同事实**（序号升序、时刻不同）；
2. 重跑第二次绿的夹具（历史形态）⇒ 只能有 **1 条**事实，不许凭空造出第二条；
3. 判别力自证：把「同一次尝试记两遍」的条目喂给 `ledger_violations` ⇒ **具名红**；同一条目修好后 ⇒ 绿
   （没有这条，「判据恒绿」与「判据有效」在结果列上长得一样）；
4. 出厂台账不许有重复 attempt 事实（存量 40 条已在本次修复中按「同一次尝试只留一条」收敛为 0，
   条目总数 1377 不变 —— 只删重复事实，不删条目）。
"""
import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".github" / "scripts"
LEDGER_PATH = REPO_ROOT / ".github" / "flaky-ledger.json"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FL = _load(SCRIPTS / "flaky_ledger.py", "migao_flaky_ledger_attempt_facts")
REAL_LEDGER = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))

JOB = "admin-api unit tests"


# ── 夹具（形状与 GitHub REST `/actions/runs/{id}` + `/attempts/{n}/jobs` 同源） ──


def make_run(attempt=2, conclusion="failure", run_id=40497531264,
             updated="2026-10-27T11:53:10Z"):
    return {
        "id": run_id,
        "name": "PR Check",
        "event": "pull_request",
        "conclusion": conclusion,
        "run_attempt": attempt,
        "head_branch": "7902-print-center",
        "head_sha": "b77e1fa2f7d6b6ab5ed0f4d6af6807ddc4958429",
        "html_url": f"https://github.com/o/r/actions/runs/{run_id}",
        "updated_at": updated,
        "pull_requests": [{"number": 7907}],
    }


def make_job(completed_at, step="Run unit tests", name=JOB, conclusion="failure"):
    """一次尝试里那个 job 的读数（`completed_at` = 这次尝试的完成时刻 = `attempts[].timestamp`）。"""
    if conclusion == "success":
        steps = [{"name": step, "conclusion": "success"}]
    else:
        steps = [
            {"name": "Run actions/checkout@v7", "conclusion": "success"},
            {"name": step, "conclusion": "failure"},
        ]
    return {"name": name, "conclusion": conclusion, "completed_at": completed_at, "steps": steps}


def attempts_of(decision):
    assert len(decision["entries"]) == 1, decision
    return decision["entries"][0]["attempts"]


# ── 判据 1：两次尝试 = 两条不同事实 ─────────────────────────────────────────────


def test_two_attempts_are_recorded_as_two_distinct_facts():
    """两次都红（attempt 2 与它的上一轮）⇒ 两条事实必须**分开**、序号升序、时刻不同。"""
    prior = make_job("2026-10-27T11:43:31Z")          # attempt 1
    current = make_job("2026-10-27T12:31:07Z")        # attempt 2
    decision = FL.decide({"run": make_run(attempt=2, conclusion="failure"),
                          "jobs": [current], "prior_jobs": [prior]})
    facts = attempts_of(decision)

    assert [f["attempt"] for f in facts] == [1, 2], facts
    assert [f["timestamp"] for f in facts] == ["2026-10-27T11:43:31Z", "2026-10-27T12:31:07Z"], facts
    assert len({f["timestamp"] for f in facts}) == 2, (
        "两条事实必须是**两次尝试**的读数（时刻不同）；时刻相同 = 同一次被记两遍", facts)


# ── 判据 2：重跑第二次绿（历史形态）不许造出第二条事实 ──────────────────────────


def test_rerun_green_does_not_record_the_same_attempt_twice():
    """`conclusion=success` + attempt 2：被记账的是 **attempt 1 那批 job**，prior 也是同一批。

    ⇒ `attempts` 只能有 **1 条**（attempt=1）。旧实现让 `prev_attempt` 也等于 1 且照记不误
    ⇒ 两条 `attempt: 1`、`timestamp` 逐字相同（run 40497531264 的现场）。
    """
    first = make_job("2026-10-27T11:43:31Z")
    green = make_job("2026-10-27T11:53:03Z", conclusion="success")
    decision = FL.decide({"run": make_run(attempt=2, conclusion="success"),
                          "jobs": [green], "prior_jobs": [first]})
    facts = attempts_of(decision)

    assert len(facts) == 1, (
        "重跑第二次绿时**没有** attempt-2 的失败事实（attempt 2 是绿的）⇒ 只能记 attempt 1 那一条；"
        f"多出来的那条是同一次尝试的重复：{facts}")
    assert [f["attempt"] for f in facts] == [1], facts
    assert facts[0]["step"] == "Run unit tests", facts
    assert decision["entries"][0]["rerun_result"] == "success", decision["entries"][0]


# ── 判据 3：判别力自证（同一条目：坏形态具名红 / 修好后绿） ─────────────────────


def _historical_duplicate_entry():
    """`run_id=40497531264` 修复前的**逐字**形态（两条 attempt 1、timestamp 相同）。"""
    fact = {"attempt": 1, "job": JOB, "step": "Run unit tests",
            "assertion": None, "timestamp": "2026-10-27T11:43:31Z"}
    green = make_job("2026-10-27T11:53:03Z", conclusion="success")
    decision = FL.decide({"run": make_run(attempt=2, conclusion="success"),
                          "jobs": [green], "prior_jobs": [make_job("2026-10-27T11:43:31Z")]})
    entry = decision["entries"][0]
    entry["attempts"] = [dict(fact), dict(fact)]          # ← 注入改前形态
    return entry, fact


def test_red_proof_the_duplicated_same_attempt_shape_is_named_red():
    entry, fact = _historical_duplicate_entry()
    bad = FL.ledger_violations({"version": 3, "note": "", "_schema": {},
                                "entries": [entry]})
    hit = [m for m in bad if "attempt" in m and "多遍" in m]
    assert hit, f"同一次尝试记两遍必须**具名**判红，实际违规={bad}"
    assert "attempt=[1]" in hit[0], hit

    # 同一个条目（只把重复事实去掉）⇒ 零违规（证明上面那条红的是「重复」本身，不是别的字段）
    entry["attempts"] = [fact]
    assert [m for m in FL.ledger_violations({"version": 3, "note": "", "_schema": {},
                                             "entries": [entry]}) if "attempt" in m and "多遍" in m] == []


# ── 判据 4：出厂台账不许有重复 attempt 事实 ────────────────────────────────────


def test_shipped_ledger_has_no_duplicate_attempt_facts():
    offenders = []
    for entry in REAL_LEDGER["entries"]:
        numbers = [f.get("attempt") for f in (entry.get("attempts") or [])
                   if isinstance(f, dict)]
        if len(numbers) != len(set(numbers)):
            offenders.append((entry["run_id"], entry["job"], numbers))
    assert offenders == [], (
        f"台账里有条目把同一次尝试记了多遍（共 {len(offenders)} 条）：{offenders[:5]}")
    assert any(entry.get("attempts") for entry in REAL_LEDGER["entries"]), (
        "台账必须仍有带原始事实的条目（否则上面的判据是空跑：0 条可查 = 与「没有这个面」不可区分）")