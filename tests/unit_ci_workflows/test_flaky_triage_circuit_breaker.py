# case_ids: MC-012
"""CI 限流风暴下的 **Flaky Triage 熔断**（issue #8444）—— L0，离线、零 LLM、秒级。

病（**实测读数**，2026-11-02 19:10 +08，不是推断）
--------------------------------------------------
安装令牌的 `Reset=1793615549`（18:32:29 +08）已过，但 38 分钟后仍 `X-RateLimit-Remaining=0`
（CI 日志里 10:35Z 的 403 逐字）⇒ **恢复即被吃光**；70 分钟内 **32 次 Flaky Triage**
+ 台账分支 **34 次 CI**。机制是**自激**，不是「负载高」：

    某 PR 的 job 失败
      → Flaky Triage #1（fetch + rerun 失败 job）
          → rerun 的完成事件 → Flaky Triage #2（`run_attempt > 1` ⇒ 过闸，第二次绿检测**必需**）
              → 若转绿 ⇒ 记 flaky ⇒ **推台账分支**
                  → 台账分支上 4 条 CI 各完成一次 → 4 次 Flaky Triage（脚本里 skip，但**job 已跑满**）
    而限流红本身就是「全仓失败」⇒ 每个完成事件都来一轮 ⇒ **闭环**。

本文件锁的四件事（每条都带**注入式红证**：把修复摘掉 / 把熔断做宽 ⇒ 必红）
--------------------------------------------------------------------------
1. **限流态整轮短路**：`403 rate limit` 或 `remaining == 0` ⇒ **零 rerun / 零记账 / 零推台账**，
   并且**必须**打出 `::warning::` 说明「这轮没跑（环境态，不是 flaky）」——
   **不许**把「没跑」读成「没有 flaky」（`migao-acceptance` 的「未跑 ≠ 通过」，只是不放大）。
2. **正常态不回归**：**非限流**的失败仍然 `rerun` 一次（既有 `MAX_ATTEMPTS` 语义一字不动）。
3. **台账分支的完成事件不创建 job**：job 级 `if:` 排除 `chore/flaky-ledger`
   （过去只有脚本里的 `skip` ⇒ job 已经跑满 checkout + 两次 API 取数）。
4. **同 `(workflow, head_sha)` 时间窗去重**：同一提交的多次完成事件**只分流一次**；
   窗口外自动失效（时间窗，**不是**计数器）。

同时钉住**不能动的那一半**：`run_attempt > 1`（第二次绿检测）在没有既往条目时照旧 `mark_flaky`
—— 熔断与去重都**不许**打断它（打断 = 降门禁）。

`case_ids` 沿用本目录的既有惯例：CI 结构类 L0 不变式统一挂 `MC-012`
（`.github/cases/misc.yml`：CI workflow 行为由 `tests/unit_ci_workflows/` 单测验证）。
⚠️ **未改 `cases/**`**（Case Trust 缴费要求）。
"""
import importlib.util
import json
import subprocess
import types
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".github" / "scripts"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "flaky-triage.yml"
REAL_WORKFLOW_TEXT = WORKFLOW_PATH.read_text(encoding="utf-8")
#: 脚本源码本体（红证用它做**内容变异** ⇒ 免疫 `.pyc` 缓存；判据读内容，不读 mtime/size）。
REAL_SCRIPT_SOURCE = (SCRIPTS / "flaky_ledger.py").read_text(encoding="utf-8")


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


FL = _load(SCRIPTS / "flaky_ledger.py", "migao_flaky_ledger_cb")


# ── 夹具（形状与 GitHub REST `/actions/runs/{id}` + `/attempts/{n}/jobs` 同源） ──


def make_run(name="PR Check", attempt=1, conclusion="failure", event="pull_request",
             branch="fix/8444-demo", pr=8444, run_id=8444,
             sha="a" * 40, updated="2026-11-02T10:00:00Z"):
    return {
        "id": run_id,
        "name": name,
        "event": event,
        "conclusion": conclusion,
        "run_attempt": attempt,
        "head_branch": branch,
        "head_sha": sha,
        "html_url": f"https://github.com/o/r/actions/runs/{run_id}",
        "updated_at": updated,
        "pull_requests": [{"number": pr}] if pr else [],
    }


def make_job(name="Run unit tests", conclusion="failure"):
    steps = ([{"name": "Set up job", "conclusion": "success"},
              {"name": name, "conclusion": "failure"}]
             if conclusion == "failure"
             else [{"name": name, "conclusion": "success"}])
    return {"name": name, "conclusion": conclusion, "steps": steps}


def bundle(run=None, jobs=None, prior_jobs=None, rate_limit=None):
    payload = {"run": run or make_run(), "jobs": jobs if jobs is not None else [make_job()],
               "prior_jobs": prior_jobs}
    if rate_limit is not None:
        payload["rate_limit"] = rate_limit
    return payload


def limited_bundle():
    """限流态 bundle = `fetch` 在限流时写出的形状（`run` / `jobs` 为空）。"""
    return {"run": {}, "jobs": [], "prior_jobs": None,
            "rate_limit": {"remaining": 0, "reset": 1793615549, "limited": True,
                           "source": "gh api rate_limit（与 X-RateLimit-Remaining 同源）"}}


# ── workflow 结构：job 闸门 + step 闸门（纯函数，注入变异体后复用同一路径） ─────


def _step_text(step) -> str:
    parts = [str(step.get("run") or "")]
    env = step.get("env")
    if isinstance(env, dict):
        parts.extend(str(v) for v in env.values())
    return "\n".join(parts)


def triage_job_condition(text: str) -> str:
    """triage job 的 `if:`（折叠成单行；**空** ⇒ 没有闸门 —— 调用方必须当缺陷）。"""
    doc = yaml.safe_load(text) or {}
    return " ".join(str(((doc.get("jobs") or {}).get("triage") or {}).get("if") or "").split())


def gate_holds(cond: str, *, conclusion: str, attempt: int, branch: str) -> bool:
    """把 job 闸门表达式按给定事件上下文求值（**行为**判据，不是字符串比对）。"""
    expr = cond.replace("&&", " and ").replace("||", " or ")
    expr = expr.replace("github.event.workflow_run.conclusion", repr(conclusion))
    expr = expr.replace("github.event.workflow_run.run_attempt", str(int(attempt)))
    expr = expr.replace("github.event.workflow_run.head_branch", repr(branch))
    return bool(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 - 仓内自有表达式


def ledger_branch_gate_violations(text: str) -> list:
    """③ 的判据本体（空 = 合规）：台账分支的完成事件**不许**创建 job，且**不许**动坏另两半。"""
    bad = []
    cond = triage_job_condition(text)
    if not cond:
        return ["triage job 没有 `if:` 闸门 ⇒ 每个完成事件都会创建一个 job（含台账分支自己的）"]
    if gate_holds(cond, conclusion="failure", attempt=1, branch=FL.LEDGER_BRANCH):
        bad.append(f"台账分支（{FL.LEDGER_BRANCH}）的完成事件仍会**创建 job** ⇒ 台账每推一次 "
                   f"白烧 4 轮 checkout + API 取数（#8444 ③）。实际闸门 {cond!r}")
    # ⚠️ **不能动的那一半**：`run_attempt > 1` = 第二次绿检测。摘掉它 = 降门禁。
    if not gate_holds(cond, conclusion="success", attempt=2, branch="fix/8444-demo"):
        bad.append("`run_attempt > 1`（重跑转绿的完成事件）被闸门挡在门外 ⇒ "
                   "「第二次绿 ⇒ mark_flaky + block/merge」这条机制被打断（= 降门禁）")
    if not gate_holds(cond, conclusion="failure", attempt=1, branch="fix/8444-demo"):
        bad.append("首次失败（attempt=1）被闸门挡住 ⇒ 分流机制整体失效")
    if gate_holds(cond, conclusion="success", attempt=1, branch="fix/8444-demo"):
        bad.append("上游**首次就成功**的腿仍会创建 job ⇒ #5814 的降频被回退（纯放大器）")
    return bad


def step_gate_results(text: str, outputs: dict) -> dict:
    """按 `decide` 的 gh-output 算每条 step 的 `if:` 是否成立。

    只裁**只引用 `steps.decide.outputs.*`** 的 step（引用了别的 step / 事件字段 ⇒ 跳过，
    **不猜**）；`always()` 恒真。返回 `{index: (是否跑, 正文)}`。
    """
    doc = yaml.safe_load(text) or {}
    steps = ((doc.get("jobs") or {}).get("triage") or {}).get("steps") or []
    result = {}
    for index, step in enumerate(steps):
        cond = " ".join(str(step.get("if") or "").split())
        text_body = _step_text(step)
        if not cond:
            result[index] = (True, text_body)
            continue
        if cond.startswith("always()"):
            result[index] = (True, text_body)
            continue
        expr = cond.replace("&&", " and ").replace("||", " or ")
        for key in ("action", "kind", "pr", "entry_count"):
            expr = expr.replace(f"steps.decide.outputs.{key}", repr(str(outputs.get(key, ""))))
        if "steps." in expr or "github." in expr:
            continue  # 依赖了本判据不裁的输入 ⇒ 不猜
        result[index] = (bool(eval(expr, {"__builtins__": {}}, {})),  # noqa: S307
                         text_body)
    return result


def steps_that_would_run(text: str, outputs: dict, needles) -> list:
    """在给定 `decide` 输出下，正文含 `needles` 且**真的会跑**的 step 序号。"""
    hits = []
    for index, (runs, body) in step_gate_results(text, outputs).items():
        if runs and any(needle in body for needle in needles):
            hits.append(index)
    return hits


# ── ① 限流熔断：零 rerun / 零记账 / 零推台账，且「没跑」必须长得像「没跑」 ────────


def rate_limit_violations(decide_fn, render_fn=None) -> list:
    """① 的判据本体（空 = 合规）。**不读实现结构**，只喂限流 bundle 看输出。"""
    render_fn = render_fn or FL.render_summary
    bad = []
    d = decide_fn(limited_bundle())
    if d["action"] != "skip":
        bad.append(f"限流态给出了 {d['action']!r} ⇒ 会继续点火（零动作是熔断的全部意义）")
    if d["entries"]:
        bad.append(f"限流态写了 {len(d['entries'])} 条条目 ⇒ 记账/推台账会被触发（放大）")
    if not d.get("environment_state") or not d.get("rate_limited"):
        bad.append("限流态**没有**被标成环境态（`environment_state` / `rate_limited`）⇒ "
                   "下游与读日志的人会把它读成「没有 flaky」（这正是本单要治的读数错位）")
    summary = render_fn(d)
    if "::warning::" not in summary:
        bad.append("限流态没有打 `::warning::` ⇒ 「这轮没跑」在 CI 上不可见（静默 ≠ 通过）")
    if "没跑" not in d["reason"] or "没有 flaky" not in d["reason"]:
        bad.append("限流态的 reason 没有明写「没跑 ≠ 没有 flaky」⇒ 留白会被读成结论")
    return bad


class TestRateLimitCircuitBreaker:
    def test_rate_limited_bundle_is_environment_skip(self):
        assert rate_limit_violations(FL.decide, FL.render_summary) == []

    def test_zero_quota_probe_short_circuits_before_any_quota_spend(self, monkeypatch):
        """`remaining == 0` ⇒ **一次取数都不发**（探测端点本身不消耗配额）。"""
        calls = []
        monkeypatch.setattr(FL, "_gh_api", lambda path, **kwargs: calls.append(path) or {})

        got = FL.fetch_bundle("o/r", 8444, rate_limit_probe=lambda: {
            "remaining": 0, "limited": True, "source": "probe"})
        assert got["rate_limit"]["limited"] is True, got
        assert got["run"] == {}, "限流态仍带回了 run 事实 ⇒ 说明取数真的发生了"
        assert calls == [], f"限流态发出了 {len(calls)} 次取数（应为 0）：{calls}"

    def test_403_rate_limit_during_fetch_becomes_environment_bundle(self):
        """探测通过、配额在半路耗尽（`403 rate limit`）⇒ 同样收敛成环境态，**不重试**。"""
        seen = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)
            raise subprocess.CalledProcessError(
                1, cmd, output="",
                stderr="gh: API rate limit exceeded for installation ID 1793615549. (HTTP 403)")

        original = FL.subprocess.run
        FL.subprocess.run = fake_run
        try:
            got = FL.fetch_bundle("o/r", 8444)
        finally:
            FL.subprocess.run = original
        assert got["rate_limit"]["limited"] is True, got
        assert got["run"] == {}, got
        # probe（rate_limit）+ 1 次真正的取数 = 2；**不许**重试/兜底重复取（那正是放大）
        assert len(seen) == 2, f"限流后仍发起了 {len(seen)} 次 gh 调用（应为 2）：{seen}"
        d = FL.decide(got)
        assert d["action"] == "skip", d
        assert d["entries"] == [], d

    def test_cli_end_to_end_no_rerun_and_no_ledger_push(self, monkeypatch, tmp_path, capsys):
        """**直连真实 CLI + 真实 workflow 闸门**（§28.2：判据本体绿 ≠ 接线在）。

        替身 `gh` 只做一件事：`rate_limit` 报 `remaining=0`，其余一律 403 限流。
        然后按 `decide` 的**真实输出**求值 workflow 的 step 闸门 ⇒ 重跑/台账/评论一步都不许跑。
        """
        gh = tmp_path / "gh"
        gh.write_text(
            "#!/bin/bash\n"
            'printf \'%s\\n\' "$*" >> "$GH_LOG"\n'
            "case \"$*\" in\n"
            "  *rate_limit*)\n"
            "    printf '%s' '{\"resources\":{\"core\":{\"remaining\":0,\"reset\":1793615549}}}' ;;\n"
            "  *)\n"
            "    printf '%s' 'gh: API rate limit exceeded. (HTTP 403)' >&2; exit 1 ;;\n"
            "esac\n",
            encoding="utf-8")
        gh.chmod(0o755)
        log = tmp_path / "gh-calls.log"
        monkeypatch.setenv("PATH", f"{tmp_path}:{__import__('os').environ['PATH']}")
        monkeypatch.setenv("GH_LOG", str(log))

        bundle_path = tmp_path / "bundle.json"
        entries_path = tmp_path / "entries.json"
        out_path = tmp_path / "gh-output.txt"
        ledger_path = tmp_path / "ledger.json"
        ledger_path.write_text(json.dumps({"entries": []}) + "\n", encoding="utf-8")
        ledger_before = ledger_path.read_text(encoding="utf-8")

        assert FL.main(["fetch", "--repo", "o/r", "--run-id", "8444",
                        "--out", str(bundle_path)]) == 0
        assert FL.main(["decide", "--bundle", str(bundle_path),
                        "--entries-out", str(entries_path),
                        "--gh-output", str(out_path),
                        "--ledger", str(ledger_path)]) == 0

        printed = capsys.readouterr().out
        assert "::warning::" in printed and "没跑" in printed, (
            "限流态没有在 CI 输出里说明「这轮没跑」⇒ 会被读成「没有 flaky」：\n" + printed)

        outputs = dict(line.split("=", 1) for line in
                       out_path.read_text(encoding="utf-8").splitlines() if "=" in line)
        assert outputs["action"] == "skip", outputs
        assert outputs["entry_count"] == "0", outputs
        assert json.loads(entries_path.read_text(encoding="utf-8")) == [], "限流态写了条目"

        called = log.read_text(encoding="utf-8").splitlines()
        assert [line for line in called if "rerun" in line] == [], f"限流态发了 rerun：{called}"
        # 台账：① 没有人跑 append ⇒ 文件一字未改 ② workflow 的 append 步骤被闸门挡住
        assert ledger_path.read_text(encoding="utf-8") == ledger_before, "限流态改了台账"
        would = steps_that_would_run(REAL_WORKFLOW_TEXT, outputs,
                                     ["gh run rerun", "flaky_ledger.py append", "git push",
                                      "issues/$PR_NUMBER/comments"])
        assert would == [], f"限流态下这些 step 仍会跑（序号 {would}）⇒ 放大未止"

    def test_non_rate_limit_permission_403_is_not_swallowed(self):
        """对照：`403` **权限**问题不是限流 ⇒ 不许被熔断吞掉（否则真失效会静默）。"""
        assert FL.is_rate_limit_error(
            "gh: API rate limit exceeded for installation. (HTTP 403)") is True
        assert FL.is_rate_limit_error(
            "HTTP 403: Resource not accessible by integration") is False
        assert FL.is_rate_limit_error("HTTP 404: Not Found") is False
        # 读不到 remaining ⇒ **不判限流**（读不到 ≠ 限流）
        assert FL.rate_limit_reading({})["limited"] is False
        assert FL.rate_limit_reading({"resources": {"core": {"remaining": 0}}})["limited"] is True


# ── ② 正常态不回归：非限流的失败仍然 rerun 一次 ────────────────────────────────


def rerun_violations(decide_fn) -> list:
    """② 的判据本体（空 = 合规）：**非限流**的首次失败必须 `rerun`，且不许记账。"""
    bad = []
    d = decide_fn(bundle(run=make_run(attempt=1, conclusion="failure")))
    if d["action"] != "rerun":
        bad.append(f"非限流的首次失败给出 {d['action']!r} ⇒ 分流机制被打断（`MAX_ATTEMPTS` 语义回归）")
    if d["entries"]:
        bad.append("首次失败就记账 ⇒ 终态判据被提前（重跑前不该有结论）")
    if d.get("rate_limited") or d.get("environment_state"):
        bad.append("普通失败被标成**环境态** ⇒ 熔断做宽了（会把真 flaky 一起放过）")
    return bad


class TestNormalPathUnchanged:
    def test_non_rate_limit_failure_still_reruns_once(self):
        assert rerun_violations(FL.decide) == []
        assert FL.MAX_ATTEMPTS == 2, "改大 MAX_ATTEMPTS = 允许无限重跑（红线）"
        third = FL.decide(bundle(run=make_run(attempt=3, conclusion="failure")))
        assert third["action"] == "record_both_red", third

    def test_workflow_runs_the_single_rerun_step(self):
        """真实 workflow 上：`rerun` 输出 ⇒ **恰好一条** step 会跑（且它就是 `gh run rerun`）。"""
        outputs = {"action": "rerun", "entry_count": "0", "pr": "8444", "kind": ""}
        rerun_steps = [i for i, (runs, body) in
                       step_gate_results(REAL_WORKFLOW_TEXT, outputs).items()
                       if "gh run rerun" in body]
        assert len(rerun_steps) == 1, f"`gh run rerun` 应恰好一处，实际 {len(rerun_steps)} 处"
        assert steps_that_would_run(REAL_WORKFLOW_TEXT, outputs, ["gh run rerun"]) == rerun_steps
        assert steps_that_would_run(REAL_WORKFLOW_TEXT, outputs,
                                    ["flaky_ledger.py append"]) == [], "重跑轮就推台账 ⇒ 放大"


# ── ③ 台账分支：job 级闸门（不是等 job 跑满再 skip） ───────────────────────────


class TestLedgerBranchJobGate:
    def test_real_workflow_excludes_the_ledger_branch_at_job_level(self):
        assert ledger_branch_gate_violations(REAL_WORKFLOW_TEXT) == []

    def test_ledger_branch_name_matches_the_script_constant(self):
        """闸门里的分支名必须与 `flaky_ledger.LEDGER_BRANCH` 同源（写第二份字面量必腐烂）。"""
        assert FL.LEDGER_BRANCH in triage_job_condition(REAL_WORKFLOW_TEXT)


# ── ④ 同 (workflow, head_sha) 时间窗去重：只分流一次 ──────────────────────────


def _ledger_after_first_triage(run_id=8444):
    """跑一次**终态**分流，把条目放进台账（= 上一轮已分流过的状态）。"""
    first = FL.decide(bundle(run=make_run(run_id=run_id, attempt=2, conclusion="failure")))
    assert first["action"] == "record_both_red", first
    assert len(first["entries"]) == 1, first
    return {"entries": list(first["entries"])}


def dedup_violations(decide_fn, now="2026-11-02T10:05:00Z") -> list:
    """④ 的判据本体（空 = 合规）：同 `(workflow, head_sha)` 的第二次完成事件**不再分流**。

    ⚠️ 同时钉住**不能动的那一半**：没有既往条目时，`attempt=2` 的转绿照旧 `mark_flaky`。
    """
    bad = []
    ledger = _ledger_after_first_triage()
    again = decide_fn(bundle(run=make_run(run_id=8445, attempt=2, conclusion="failure")),
                      ledger=ledger, now=now)
    if again["action"] != "skip":
        bad.append(f"同一 (workflow, head_sha) 的第二次完成事件仍给出 {again['action']!r} ⇒ 同一提交被重复分流")
    if again["entries"]:
        bad.append("第二次完成事件仍写了条目 ⇒ 台账会被重复追加/推送")
    if "去重" not in again["reason"] or "没有 flaky" not in again["reason"]:
        bad.append("去重态没有明写「去重，不是没有 flaky」⇒ 留白会被读成结论")

    # 窗口外必须**自动失效**（时间窗，不是计数器：不许永久压制同一提交）
    expired = decide_fn(bundle(run=make_run(run_id=8445, attempt=2, conclusion="failure")),
                        ledger=ledger, now="2026-11-02T12:00:01Z")
    if expired["action"] == "skip":
        bad.append("窗口外的同一提交仍被压制 ⇒ 去重变成了永久屏蔽（计数器形态的腐烂）")

    # ⚠️ 不能动的那一半：第二次绿（`run_attempt > 1`）在没有既往条目时照旧 mark_flaky
    green = decide_fn(bundle(run=make_run(run_id=8446, attempt=2, conclusion="success"),
                             jobs=[make_job(conclusion="success")],
                             prior_jobs=[make_job()]), ledger={"entries": []}, now=now)
    if green["action"] != "mark_flaky":
        bad.append(f"没有既往条目时第二次绿给出 {green['action']!r} ⇒ 第二次绿检测被打断（降门禁）")
    return bad


class TestDuplicateCompletionEvents:
    def test_same_commit_triaged_only_once(self):
        assert dedup_violations(FL.decide) == []

    def test_ledger_branch_is_also_caught_by_the_script_gate(self):
        """双保险：即使 job 闸门被绕过，脚本里的台账分支判据仍在（**不是**重复实现）。"""
        d = FL.decide(bundle(run=make_run(branch=FL.LEDGER_BRANCH)))
        assert d["action"] == "skip", d
        assert d["entries"] == [], d


# ══════════════════════════════════════════════════════════════════════════════
# 注入式红证：把修复**摘掉 / 做宽** ⇒ 上面四条判据各自必红
# （红证不写在断言消息里，而走**同一判据** ⇒ 判据的判别力可被机械自证）
# ══════════════════════════════════════════════════════════════════════════════


def _mutant(*replacements, name="mutant"):
    source = REAL_SCRIPT_SOURCE
    for old, new in replacements:
        assert old in source, f"注入锚点失效（先修本测试）：{old[:60]!r}"
        source = source.replace(old, new, 1)
    return _load_mutant(source, name)


class TestRedProofs:
    """每条红证 = 一次**真实注入** + 「注入后判据必红」+「未注入时判据绿」（对照）。"""

    def test_red_proof_1_removing_the_breaker_is_caught(self):
        """摘掉 `decide` 里的限流短路 ⇒ ① 必红（限流态被读成「workflow 不在白名单」）。"""
        mutant = _mutant((
            "    rate = (bundle or {}).get(\"rate_limit\") or {}\n"
            "    if isinstance(rate, dict) and rate.get(\"limited\"):\n"
            "        return _rate_limited_skip(run, rate)\n", ""), name="no_breaker")
        violations = rate_limit_violations(mutant.decide, mutant.render_summary)
        assert violations, "摘掉限流熔断后仍判绿 ⇒ 该判据是空断言"
        assert any("环境态" in v or "warning" in v for v in violations), violations

    def test_red_proof_1b_removing_the_warning_is_caught(self):
        """只删 `::warning::`（「没跑」不可见）⇒ ① 必红。"""
        mutant = _mutant(("    if decision.get(\"rate_limited\"):", "    if False:"),
                         name="no_warning")
        assert any("warning" in v for v in
                   rate_limit_violations(mutant.decide, mutant.render_summary))

    def test_red_proof_2_over_wide_breaker_is_caught(self):
        """熔断做宽（**任何**失败都当环境态）⇒ ② 必红（正常态不回归）。"""
        mutant = _mutant(("    if isinstance(rate, dict) and rate.get(\"limited\"):",
                          "    if True:"), name="overwide")
        assert rerun_violations(mutant.decide), "熔断做宽后仍判绿 ⇒ ② 是空断言"

    def test_red_proof_3_reverting_to_script_only_skip_is_caught(self):
        """改回「只靠脚本里 skip」（job 闸门不含台账分支）⇒ ③ 必红。"""
        reverted = REAL_WORKFLOW_TEXT.replace(
            "    if: >-\n"
            "      (github.event.workflow_run.conclusion == 'failure' ||\n"
            "       github.event.workflow_run.run_attempt > 1) &&\n"
            "      github.event.workflow_run.head_branch != 'chore/flaky-ledger'\n",
            "    if: >-\n"
            "      github.event.workflow_run.conclusion == 'failure' ||\n"
            "      github.event.workflow_run.run_attempt > 1\n", 1)
        assert reverted != REAL_WORKFLOW_TEXT, "注入锚点失效（先修本测试）"
        violations = ledger_branch_gate_violations(reverted)
        assert any(FL.LEDGER_BRANCH in v for v in violations), violations

    def test_red_proof_3b_removing_the_retry_half_is_caught(self):
        """顺手摘掉 `run_attempt > 1`（第二次绿那一半）⇒ ③ 必红（降门禁）。"""
        stripped = REAL_WORKFLOW_TEXT.replace(
            "      (github.event.workflow_run.conclusion == 'failure' ||\n"
            "       github.event.workflow_run.run_attempt > 1) &&\n",
            "      github.event.workflow_run.conclusion == 'failure' &&\n", 1)
        assert stripped != REAL_WORKFLOW_TEXT, "注入锚点失效（先修本测试）"
        assert any("第二次绿" in v for v in ledger_branch_gate_violations(stripped))

    def test_red_proof_4_removing_the_dedup_is_caught(self):
        """摘掉去重调用 ⇒ ④ 必红（同一提交的第二次完成事件又被分流一次）。"""
        mutant = _mutant(("    dup = _dedup_hit(ledger, run, now=now, window_minutes=window)",
                          "    dup = None"), name="no_dedup")
        violations = dedup_violations(mutant.decide)
        assert violations, "摘掉去重后仍判绿 ⇒ ④ 是空断言"
        assert any("重复分流" in v for v in violations), violations

    def test_red_proof_4b_permanent_suppression_is_caught(self):
        """把时间窗做成「永不过期」（计数器形态）⇒ ④ 必红。"""
        mutant = _mutant((
            "        if (now_dt - newest).total_seconds() / 60.0 <= window:",
            "        if True:"), name="permanent")
        assert any("窗口外" in v for v in dedup_violations(mutant.decide))


# ── 反空跑：坐标必须都在（文件被删/改名 ⇒ 红，不是静默跳过） ──────────────────────


def test_coordinates_exist():
    assert SCRIPTS.joinpath("flaky_ledger.py").is_file()
    assert WORKFLOW_PATH.is_file()
    assert triage_job_condition(REAL_WORKFLOW_TEXT) != "", "job 闸门读不到 ⇒ ③ 会静默空跑"
    assert callable(FL.fetch_bundle) and callable(FL.decide)
