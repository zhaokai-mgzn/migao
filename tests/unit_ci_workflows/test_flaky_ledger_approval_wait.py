# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   「CI workflow 结构由 pytest 单测验证」是 misc.yml 里已登记的形态。）
"""#5417：台账 PR 的**审批队列** —— 幂等重试（不再单发一次）+ 可归因读数（不许静默）。

病根（**实测读数**，2026-09-25 push `425732992` / 台账 PR #5563；别再重新猜）
--------------------------------------------------------------------------
GitHub 把台账 PR 的 `pull_request` run 放进审批队列（`conclusion=action_required`、
**零 job ⇒ 零 check-run**）。机制侧（`flaky_ledger.py approve`）会去批准它们，但**单发一次**：

  ① **撞上「run 还没被创建」⇒ 静默 0 动作**：triage run `36116623413` 步骤⑤ 日志逐字
     `ℹ️ tip=425732992180fada5f187ae10e4f67ea49c61904 暂无待批准 run（尚未创建或已批准）⇒ 本轮零动作，下一轮触发会重试`
     —— 该步**退出 0、workflow 绿**；同刻（09:08:04）读数逐字
     `state=OPEN mergeStateStatus=BLOCKED autoMerge=armed / check 数=0` ⇒ 台账 PR 停在
     **0 个 check**，直到 **09:25:31**（**18 分钟**后）被**另一条** workflow 的兜底轮次顺手批上。
  ② **tip 上 10 个待批准，只批了 4 个**：reconcile run `36118293816` 日志逐字
     `🔓 历史待批准 102 个，其中属于分支 tip=425732992180fada5f187ae10e4f67ea49c61904 的 4 个 ⇒ 只批准这 4 个：[36116660804, 36116660821, 36116660826, 36116660877]`
     —— 另外 6 个（Drift Audit / PR Issue Link Check / Flaky Ledger Reconcile /
     Mechanism Liveness / Deploy Reconcile / Post-Merge Verify）**永远留在队列里**：批准面沿用了
     「重跑白名单」口径，而它们**不在 required 集合**（批了只会给台账 PR 添红）⇒ **有意不批**，
     属登记在册的残余（读数必须把这一类**显式报出来**，否则「机制失效」与「按设计不批」长得一样）。

本文件锁三件事（每条都有**注入式红证**：把坏形态注回 ⇒ 必红）
--------------------------------------------------------------
  ① **幂等重试**：`approve --wait-seconds` 必须轮询到审批队列清空 —— **迟到出现的 run 也要批上**；
  ② **失败关闭**：窗口用尽队列仍非空 ⇒ **非零退出** + 每条 run 的链接 + 人工出口命令
     （「还没跑起来」不许装成「已经处理」）；
  ③ **可归因读数**：`approval-queue` 把队列**分成三类**（机制面 / 按设计不批 / 陈旧推送），
     每条带链接，且分类**现取自活常量**（不写第二份名单）。
"""
from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / ".github" / "scripts"
WORKFLOWS = REPO / ".github" / "workflows"
SCRIPT = SCRIPTS / "flaky_ledger.py"
TRIAGE_YML = WORKFLOWS / "flaky-triage.yml"
RECONCILE_YML = WORKFLOWS / "flaky-ledger-reconcile.yml"

#: 台账分支 push `425732992` 那一次推送产生的 **10** 个 `pull_request` run（id / name 逐条取自
#: `gh api …/actions/runs?branch=chore/flaky-ledger`，2026-09-25 现取）。那一刻它们**全部**在审批
#: 队列里（`conclusion=action_required`）—— 逐条证据：其中 4 个的
#: `…/runs/<id>/attempts/1` 实测 `conclusion=action_required`（随后被批准 ⇒ 当前 `run_attempt=2`），
#: 另外 6 个**至今**仍是 `action_required`。
#: ⚠️ 只冻结**形状**（id / name），不冻结任何计数阈值（阈值会腐烂）。
PUSH_SHA = "425732992180fada5f187ae10e4f67ea49c61904"
QUEUE_425732992 = (
    (36116660775, "Mechanism Liveness (机制存活看门人)"),
    (36116660779, "PR Issue Link Check"),
    (36116660786, "Flaky Ledger Reconcile (台账落仓对账兜底)"),
    (36116660804, "AI Agent Service Unit Tests"),
    (36116660817, "Post-Merge Verify (main 侧守护腿)"),
    (36116660821, "Bmini-App CI"),
    (36116660823, "Drift Audit (真相源契约)"),
    (36116660826, "Mini-App CI"),
    (36116660846, "Deploy Reconcile (PR 对账补偿)"),
    (36116660877, "PR Check"),
)


def _load(path: Path, name: str) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FL = _load(SCRIPT, "migao_flaky_ledger_5417")
TRIAGE_SRC = TRIAGE_YML.read_text(encoding="utf-8")
RECONCILE_SRC = RECONCILE_YML.read_text(encoding="utf-8")


def _frozen_queue():
    """冻结读数的 REST 形状（`event` / `status` / `created_at` 按真实响应补全）。"""
    return [{"id": rid, "name": name, "event": "pull_request", "status": "completed",
             "conclusion": "action_required", "run_attempt": 1, "head_branch": FL.LEDGER_BRANCH,
             "head_sha": PUSH_SHA, "created_at": "2026-09-25T09:07:16Z"}
            for rid, name in QUEUE_425732992]


def _mutant_text(src: str, *replacements, count=1) -> str:
    """内容级单点变异。`count=None` ⇒ 替换**全部**出现（用于「同一个子命令被调用两次」的接线锚点）。"""
    for old, new in replacements:
        assert old in src, f"注入锚点失效（先修本测试）：{old!r}"
        src = src.replace(old, new) if count is None else src.replace(old, new, count)
    return src


def _mutant_ns(*replacements) -> dict:
    """把真实脚本源码做**内容级单点变异**后 `exec` 成命名空间（不写盘、不留变异产物）。"""
    src = _mutant_text(SCRIPT.read_text(encoding="utf-8"), *replacements)
    ns = {"__name__": "migao_flaky_ledger_5417_mutant", "__file__": str(SCRIPT)}
    exec(compile(src, str(SCRIPT), "exec"), ns)
    return ns


def _run_cli(ns, argv, *, runs_rounds, tip=PUSH_SHA, approve_fails=False, keep_queued=False):
    """桩掉 `_gh_api` / `approve_runs` / 时钟，跑一次 CLI（**绝不发真 POST**）。

    `runs_rounds` = 每次「查 run 列表」依次返回的数组（用完之后**重复最后一轮**，模拟
    「队列一直没清空」/「GitHub 一直没把 run 标成 action_required」两种形态）。
    `keep_queued=True` ⇒ 被批准的 run **仍留在**列表里（模拟「批准已发出、GitHub 还没把它移出
    action_required」的异步窗口）。时钟是**假钟**（每轮 +1s）⇒ 窗口判据不会真等满秒数。
    返回 `(rc, stdout, stderr, 批准调用记录列表, 查询次数)`。
    """
    approved, rounds, clock = [], {"n": 0}, {"t": 0.0}

    def fake_api(path):
        if "/branches/" in path:
            return {"commit": {"sha": tip}} if tip else {"name": ns["LEDGER_BRANCH"]}
        idx = min(rounds["n"], len(runs_rounds) - 1)
        rounds["n"] += 1
        runs = runs_rounds[idx]
        if not keep_queued:
            done = {rid for call in approved for rid in call}
            runs = [r for r in runs if r["id"] not in done]
        return {"workflow_runs": runs}

    def fake_approve(repo, ids):
        if approve_fails:
            raise RuntimeError(f"run {list(ids)[0]}：HTTP 403")
        approved.append(list(ids))
        return list(ids)

    def fake_clock():
        clock["t"] += 1.0
        return clock["t"]

    # 只桩**存在**的键（修复前的实现里没有 `_monotonic` / `APPROVE_POLL_SECONDS` ——
    # 「把修复前的实现喂给本判据」是红证的一部分，桩不能因为缺键就崩）。
    keys = ("_gh_api", "approve_runs", "APPROVE_POLL_SECONDS", "_monotonic")
    saved = {k: ns[k] for k in keys if k in ns}
    (ns["_gh_api"], ns["approve_runs"], ns["APPROVE_POLL_SECONDS"],
     ns["_monotonic"]) = fake_api, fake_approve, 0.0, fake_clock
    out, err, old = io.StringIO(), io.StringIO(), (sys.stdout, sys.stderr)
    sys.stdout, sys.stderr = out, err
    try:
        rc = ns["main"](argv)
    finally:
        sys.stdout, sys.stderr = old
        for k in keys:
            if k in saved:
                ns[k] = saved[k]
            else:
                ns.pop(k, None)
    return rc, out.getvalue(), err.getvalue(), approved, rounds["n"]


def _approve_argv(ns, wait="30", json_out=None):
    argv = ["approve", "--repo", "o/r", "--head-branch", ns["LEDGER_BRANCH"],
            "--wait-seconds", wait]
    if json_out:
        argv += ["--json-out", str(json_out)]
    return argv


def wait_retry_violations(ns, tmp_path=None) -> list:
    """**判据①**：run **迟到出现**（第一轮列表为空、第二轮才有）⇒ 仍须批上且退出 0。

    单发一次的旧实现下这里 `approved == []`（= 实测的「暂无待批准 run ⇒ 本轮零动作 ⇒ 退出 0」）。
    """
    bad = []
    late = [r for r in _frozen_queue() if r["name"] in ns["TRIAGED_WORKFLOWS"]]
    rc, out, err, approved, _ = _run_cli(ns, _approve_argv(ns), runs_rounds=[[], late])
    if rc != 0:
        bad.append(f"迟到出现的 run 批上后应退出 0，实际 {rc}（stderr={err!r}）")
    if approved != [[r["id"] for r in late]]:
        bad.append(f"未在窗口内重试到「迟到出现的 run」：批准记录={approved}、"
                   f"应={[[r['id'] for r in late]]}（单发一次 ⇒ 静默 0 动作）")
    if err:
        bad.append(f"正常路径不该写 stderr：{err!r}")
    return bad


def fail_closed_violations(ns) -> list:
    """**判据②**：窗口用尽队列**仍非空** ⇒ 非零退出 + 链接 + 人工出口命令。"""
    bad = []
    pending = [r for r in _frozen_queue() if r["name"] in ns["TRIAGED_WORKFLOWS"]]
    # 每轮都冒出一个**新** id（已批准过的那些会被 `attempted` 去重 ⇒ 队列永远清不空）。
    rounds = [[dict(r, id=r["id"] + 100 * i) for r in pending] for i in range(1, 4)]
    rc, out, err, approved, _ = _run_cli(ns, _approve_argv(ns, wait="0.15"), runs_rounds=rounds)
    if rc == 0:
        bad.append("窗口用尽、tip 上仍有 run 停在 action_required，却退出 0 ⇒ 非 fail-closed"
                   "（「还没跑起来」被装成「已经处理」）")
    if not approved:
        bad.append(f"窗口内一个都不批（连可见的候选都没批）：{approved}")
    if "action_required" not in err:
        bad.append(f"fail-closed 的报错没点明「仍停在 action_required」：{err!r}")
    candidates = {str(r["id"]) for rnd in rounds for r in rnd}
    links = set(re.findall(r"actions/runs/(\d+)", err))
    if not links or not links <= candidates:
        bad.append(f"fail-closed 的报错缺可点击的 run 链接（不可行动）：links={links} {err!r}")
    if "gh api -X POST" not in err:
        bad.append(f"fail-closed 的报错缺**人工出口命令**（判据 2：唯一入口要写在读数里）：{err!r}")
    if "用尽" not in err:
        bad.append(f"fail-closed 的报错没说清是「窗口用尽」：{err!r}")
    return bad


def idempotence_violations(ns) -> list:
    """**判据①（幂等那一半）**：同一 run 在窗口内被重复看到 ⇒ 只发**一次** approve。"""
    bad = []
    pending = [r for r in _frozen_queue() if r["name"] in ns["TRIAGED_WORKFLOWS"]]
    # 队列**一直**返回同一批（模拟「已批准但 GitHub 还没把它移出 action_required」的异步窗口）
    rc, out, err, approved, _ = _run_cli(ns, _approve_argv(ns, wait="20"),
                                         runs_rounds=[pending, pending, pending, pending],
                                         keep_queued=True)
    flat = [rid for call in approved for rid in call]
    if rc != 1:
        bad.append(f"窗口用尽队列仍非空 ⇒ 必须 fail-closed（退出 1），实际 {rc}")
    if "action_required" not in err:
        bad.append(f"fail-closed 的读数没说清队列仍非空：{err!r}")
    if len(flat) != len(set(flat)):
        bad.append(f"同一个 run 被重复 approve（幂等失效）：{flat}")
    if sorted(flat) != sorted(r["id"] for r in pending):
        bad.append(f"批准集合不是 tip 上那一批：{flat}")
    return bad


def reading_violations(ns) -> list:
    """**判据③**：读数必须把队列**分三类**、每条带链接、分类现取自活常量。"""
    bad = []
    runs = _frozen_queue()
    reading = ns["approval_queue_reading"](runs, repo="o/r", head_sha=PUSH_SHA,
                                           min_age_minutes=0)
    allowed = set(ns["TRIAGED_WORKFLOWS"])
    expect_in = sorted(rid for rid, name in QUEUE_425732992 if name in allowed)
    expect_out = sorted(rid for rid, name in QUEUE_425732992 if name not in allowed)
    got_in = sorted(e["id"] for e in reading["in_scope"])
    got_out = sorted(e["id"] for e in reading["out_of_scope"])
    if got_in != expect_in:
        bad.append(f"机制面（白名单内）分类不符：{got_in}、应 {expect_in}")
    if got_out != expect_out:
        bad.append(f"「按设计不批」分类不符：{got_out}、应 {expect_out}")
    if not got_out:
        bad.append("面外条目一条都没报 ⇒ 「机制失效」与「按设计不批」会长得一样（本单要治的形态）")
    if reading["in_scope_total"] != len(expect_in) or reading["out_of_scope_total"] != len(expect_out):
        bad.append(f"计数与清单不一致：{reading['in_scope_total']}/{reading['out_of_scope_total']}")
    for entry in reading["in_scope"] + reading["out_of_scope"]:
        if entry["url"] != f"https://github.com/o/r/actions/runs/{entry['id']}":
            bad.append(f"读数条目缺可点击链接（不可归因）：{entry}")
    # 陈旧推送只计数、不成条（tip 收窄的必然结果）
    stale = [dict(r, head_sha="0" * 40) for r in runs[:3]]
    reading2 = ns["approval_queue_reading"](runs + stale, repo="o/r", head_sha=PUSH_SHA)
    if reading2["stale"] != len(stale):
        bad.append(f"陈旧推送计数不符：{reading2['stale']}、应 {len(stale)}")
    if any(e["id"] in {r["id"] for r in stale} for e in reading2["in_scope"]):
        bad.append("陈旧推送的 run 混进了机制面清单（会让读数指向无贡献的 run）")
    return bad


def reading_cli_violations(ns) -> list:
    """**判据③（CLI 那一半）**：`approval-queue` 是可行动的读数（含 `::warning::` + 出口命令）。"""
    bad = []
    argv = ["approval-queue", "--repo", "o/r", "--head-branch", ns["LEDGER_BRANCH"],
            "--min-age-minutes", "0"]
    rc, out, err, _, _ = _run_cli(ns, argv, runs_rounds=[_frozen_queue()])
    if rc != 0:
        bad.append(f"读数是报告型（零写）⇒ 应退出 0，实际 {rc}（stderr={err!r}）")
    if "::warning::" not in out:
        bad.append(f"机制面仍有待批准 run 时没打 `::warning::`（静默）：{out!r}")
    if "36116660823" not in out and "Drift Audit" not in out:
        bad.append(f"读数没报出面外的具体 run（清单不可归因）：{out!r}")
    if "gh api -X POST" not in out:
        bad.append(f"读数没带**唯一入口**（人工出口命令）：{out!r}")
    if "故意不批" not in out:
        bad.append(f"读数没把「按设计不批」这一类显式标出：{out!r}")
    # tip 取不到 ⇒ 三态退出码 `3`（不许把「无法判定」读成「没有待批准 run」）
    rc2, out2, err2, _, _ = _run_cli(ns, argv, runs_rounds=[_frozen_queue()], tip=None)
    if rc2 != 3:
        bad.append(f"tip 取不到时应退 3（无法判定），实际 {rc2}（stdout={out2!r}）")
    return bad


def _code_lines(step_run: str) -> str:
    """只留**代码行**（注释里「提及」不算调用 —— 本仓已踩三次的形态）。"""
    return "\n".join(ln for ln in step_run.splitlines() if not ln.lstrip().startswith("#"))


def workflow_violations(triage_src: str, reconcile_src: str) -> list:
    """**判据④（类级固化）**：两条 workflow 的接线锚点必须在（重试 / 读数 / fail-closed）。"""
    bad = []
    triage = yaml.safe_load(triage_src) or {}
    steps = ((triage.get("jobs") or {}).get("triage") or {}).get("steps") or []
    approve_steps = [s for s in steps if re.search(r"flaky_ledger\.py\s+approve\b",
                                                  _code_lines(str(s.get("run") or "")))]
    if not approve_steps:
        bad.append("triage 丢了 `flaky_ledger.py approve` 步骤（台账 PR 的 run 会永远停在 "
                   "`action_required`）")
    else:
        txt = "\n".join(_code_lines(str(s.get("run") or "")) for s in approve_steps)
        if "--wait-seconds" not in txt:
            bad.append("triage 的 approve **没给窗口**（`--wait-seconds`）⇒ 撞上「run 还没创建」"
                       "就静默退出 0（实测 18 分钟空窗）")
        if "::error::" not in txt:
            bad.append("triage 的 approve 缺 `::error::` fail-closed 出口")
    recon = yaml.safe_load(reconcile_src) or {}
    rsteps = ((recon.get("jobs") or {}).get("reconcile") or {}).get("steps") or []
    # 只认**调用形态**（`flaky_ledger.py approval-queue`）：告警文案与 `--json-out` 路径里都提到过
    # 这个名字，按子串匹配会被自己的文案骗绿（本仓「提及 ≠ 调用」的既有形态）。
    read_steps = [s for s in rsteps
                  if re.search(r"flaky_ledger\.py\s+approval-queue\b",
                               _code_lines(str(s.get("run") or "")))]
    if not read_steps:
        bad.append("reconcile 没有 `approval-queue` 读数步 ⇒ 停在 `action_required` 的 run 无消费面")
    else:
        rtxt = "\n".join(_code_lines(str(s.get("run") or "")) for s in read_steps)
        if "--min-age-minutes" not in rtxt:
            bad.append("读数步没有年龄阈值（`--min-age-minutes`）⇒ 无法区分「刚创建」与「卡住」")
        if not re.search(r"::error::[^\n]*退 3", rtxt):
            bad.append("读数步缺「**无法判定**（退 3）⇒ 红」的出口 ⇒ 未跑会被读成「队列为空」")
        if not any(str(s.get("if") or "").strip() == "always()" for s in read_steps):
            bad.append("读数步不是 `always()` ⇒ 上游一红，读数就没了（而那时正是要看它的时候）")
    return bad


class TestApprovalQueueFix:
    """#5417：幂等重试 + 失败关闭 + 可归因读数（每条判据都单独可红）。"""

    def test_wait_retries_until_late_runs_appear(self):
        assert wait_retry_violations(vars(FL)) == []

    def test_window_exhausted_is_fail_closed(self):
        assert fail_closed_violations(vars(FL)) == []

    def test_approve_is_idempotent_within_the_window(self):
        assert idempotence_violations(vars(FL)) == []

    def test_reading_splits_the_queue_into_three_classes(self):
        assert reading_violations(vars(FL)) == []

    def test_reading_cli_is_actionable(self):
        assert reading_cli_violations(vars(FL)) == []

    def test_workflows_carry_the_retry_and_the_reading(self):
        assert workflow_violations(TRIAGE_SRC, RECONCILE_SRC) == []

    def test_missing_default_wait_is_visible(self, tmp_path):
        """接线自证：`--wait-seconds` 的**缺省值**是 0（= 只有 workflow 显式给窗口才重试）。"""
        argv = ["approve", "--repo", "o/r", "--head-branch", FL.LEDGER_BRANCH]
        out_json = tmp_path / "approved.json"
        argv += ["--json-out", str(out_json)]
        late = [r for r in _frozen_queue() if r["name"] in FL.TRIAGED_WORKFLOWS]
        rc, _, _, approved, queries = _run_cli(vars(FL), argv, runs_rounds=[[], late])
        assert rc == 0, "缺省（无窗口）路径必须保持既有语义：单轮、退出 0"
        assert approved == [], "缺省无窗口时不许偷偷重试（窗口是显式的）"
        assert queries == 1, f"缺省无窗口应只查一轮，实际 {queries} 轮"
        assert json.loads(out_json.read_text(encoding="utf-8")) == []


class TestEveryJudgmentCanGoRed:
    """**注入式红证**：把每个修复点单点变异回去 ⇒ 对应判据必须红（不会红的判据 = 空断言）。"""

    def test_red_proof_dropping_the_wait_window(self):
        mutant = _mutant_ns(('wait = max(0.0, float(getattr(args, "wait_seconds", 0.0) or 0.0))',
                             "wait = 0.0"))
        assert wait_retry_violations(vars(FL)) == [], "真实实现先要绿，红证才有意义"
        violations = wait_retry_violations(mutant)
        assert violations, "退回「单发一次」后仍判绿 ⇒ 重试判据是**空断言**"
        assert any("未在窗口内重试" in v for v in violations), violations

    def test_red_proof_dropping_the_fail_closed_exit(self):
        mutant = _mutant_ns((
            '                      file=sys.stderr)\n            return 1\n'
            '        print(f"✅ 窗口 {wait:.0f}s 内 tip={tip} 的审批队列已清空',
            '                      file=sys.stderr)\n            return 0\n'
            '        print(f"✅ 窗口 {wait:.0f}s 内 tip={tip} 的审批队列已清空'))
        assert fail_closed_violations(vars(FL)) == []
        violations = fail_closed_violations(mutant)
        assert violations, "去掉 fail-closed（改回退出 0）后仍判绿 ⇒ 该判据是**空断言**"
        assert any("非 fail-closed" in v for v in violations), violations

    def test_red_proof_mixing_the_out_of_scope_runs_into_the_mechanism_bucket(self):
        mutant = _mutant_ns((
            '        buckets["in_scope" if run.get("name") in allowed else "out_of_scope"].append(entry)',
            '        buckets["in_scope"].append(entry)'))
        assert reading_violations(vars(FL)) == []
        violations = reading_violations(mutant)
        assert violations, "把面外条目并进机制面后仍判绿 ⇒ 三分类判据是**空断言**"
        assert any("按设计不批" in v for v in violations), violations

    def test_red_proof_dropping_the_workflow_wiring(self):
        no_wait = _mutant_text(
            TRIAGE_SRC, ('--wait-seconds "${APPROVE_WAIT_SECONDS:-60}"',
                         '--no-wait-seconds "${APPROVE_WAIT_SECONDS:-60}"'))
        assert workflow_violations(TRIAGE_SRC, RECONCILE_SRC) == []
        assert any("没给窗口" in v for v in workflow_violations(no_wait, RECONCILE_SRC)), \
            "摘掉 triage 的 `--wait-seconds` 后判绿 ⇒ 接线判据是**空断言**"
        no_reading = _mutant_text(
            RECONCILE_SRC, ("flaky_ledger.py approval-queue", "flaky_ledger.py queue-read"),
            count=None)
        assert any("读数步" in v for v in workflow_violations(TRIAGE_SRC, no_reading)), \
            "摘掉 reconcile 的读数步后判绿 ⇒ 消费面判据是**空断言**"