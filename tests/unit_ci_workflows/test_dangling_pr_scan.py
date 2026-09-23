# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
r"""悬空 PR 扫描（`scripts/dangling_pr_scan.py`）的 L0 守卫 —— issue #5235 的可见性面。

## 被测判据（issue/用户给的口径，逐字）

> 「一个 open PR 在 N 分钟内**既没变红、也没合入**，且其 required checks **未达可合状态**」
> ⇒ **必须产生一条可见信号**。

## 本文件锁什么（每条都要有**能单独让它变红**的对照）

| # | 形态 | 判据 | 红证 / 负例 |
|---|---|---|---|
| 1 | 族 B 实测形态（#5139：0 条 check + `action_required` 全 0s） | **必红** | 夹具 A ⇒ 退出码 1 + `::error::` + summary |
| 2 | 正常进行中（有 pending check / 有在跑的 run） | **不得红** | 夹具 B/C；变异（打掉该闸）⇒ 立刻变红 |
| 3 | 已经变红（任一 check 判红） | **不得红**（PR 上已有可见信号） | 夹具 D；同上 |
| 4 | draft / `block/merge` 标签 / 未到 N 分钟 / required 已达标 | **不得红** | 夹具 E~H；同上 |
| 5 | `mergeStateStatus` 读不到或 `UNKNOWN` | **三态 = 未判定**（记 warning，不假红） | 夹具 I |
| 6 | 根本读不到 open PR 列表 | **退出码 3**（「不得当 0 读」） | 夹具 J |
| 7 | workflow 接线：只在 `schedule`/`workflow_dispatch` 上跑、只读权限、跑的是本脚本 | 结构判据 + **注入式红证** | `job_wiring_problems()` |

⚠️ **判据形态**：读的是**真脚本的行为**（子进程 + `gh` 替身，CLI 边界即注入点）与**真 YAML 真值**，
不是"断言自己的文案"。`scripts/` 侧的 `gh` 替身走 `DANGLING_GH_BIN`（沿用 `MG_GH_BIN` 先例）。
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dangling_pr_scan.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "automerge.yml"
JOB = "detect-dangling-prs"

def _load_scan():
    spec = importlib.util.spec_from_file_location("dangling_pr_scan", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SCAN = _load_scan()

# ── 夹具构造（形状取自**真实读数**：`gh pr list --json …` 与 `gh run list --commit …`）──
GREEN_CHECK = {"__typename": "CheckRun", "name": "QA Growth Gate",
               "status": "COMPLETED", "conclusion": "SUCCESS"}
RED_CHECK = {"__typename": "CheckRun", "name": "admin-web typecheck + unit tests",
             "status": "COMPLETED", "conclusion": "FAILURE"}
PENDING_CHECK = {"__typename": "CheckRun", "name": "E2E quality gate",
                 "status": "IN_PROGRESS", "conclusion": None}
# 族 B 的真实形状：run 是 `completed` + `action_required`（**从未执行**，0s）
SUPPRESSED_RUNS = [{"status": "completed", "conclusion": "action_required",
                    "workflowName": "AI Agent Service Unit Tests"}] * 6
RUNNING_RUNS = [{"status": "in_progress", "conclusion": None, "workflowName": "PR Check"}]


def pr(number=5139, *, age_min=120, draft=False, state="BLOCKED", labels=(),
       rollup=(), armed=True, sha="a" * 40, title="chore(ci): flaky 台账滚动追加", now=None):
    # ⚠️ 时间锚必须取**调用时的真实钟**：CLI 侧的被测脚本用 `datetime.now()` 算年龄，
    #    固定常量锚会让所有夹具的年龄随墙上时钟漂大（本文件初版就这么假红过一次）。
    now = now or datetime.now(timezone.utc)
    return {"number": number, "title": title, "isDraft": draft,
            "createdAt": (now - timedelta(minutes=age_min)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mergeStateStatus": state,
            "labels": [{"name": n} for n in labels],
            "autoMergeRequest": ({"mergeMethod": "SQUASH"} if armed else None),
            "headRefOid": sha, "statusCheckRollup": list(rollup)}


GH_STUB = '''#!/usr/bin/env python3
"""`gh` 替身（夹具驱动）。沿用 merge_gate.py 的 MG_GH_BIN / dangling_pr_scan 的 DANGLING_GH_BIN 先例。"""
import json, os, sys

args = sys.argv[1:]
if args[:2] == ["pr", "list"]:
    if os.environ.get("STUB_PR_LIST_FAIL") == "1":
        sys.stderr.write("stub: pr list failed (injected)\\n")
        sys.exit(1)
    sys.stdout.write(open(os.environ["STUB_PRS"], encoding="utf-8").read())
    sys.exit(0)
if args[:2] == ["run", "list"]:
    sha = args[args.index("--commit") + 1]
    runs = json.load(open(os.environ["STUB_RUNS"], encoding="utf-8"))
    sys.stdout.write(json.dumps(runs.get(sha, [])))
    sys.exit(0)
sys.stderr.write("stub: unhandled argv=%r\\n" % (args,))
sys.exit(9)
'''


class Out:
    """一次扫描的可观测结果（退出码 / 输出 / step summary）。"""

    def __init__(self, proc, summary):
        self.proc = proc
        self.summary = summary

    @property
    def rc(self):
        return self.proc.returncode

    @property
    def out(self):
        return self.proc.stdout + self.proc.stderr

    def has_error(self):
        return "\n::error::" in ("\n" + self.out)

    def has_warning(self):
        return "\n::warning::" in ("\n" + self.out)


def run_scan(tmp_path, prs, runs=None, *, minutes=60, fail_list=False, script=None,
             extra_args=()):
    tmp_path.mkdir(parents=True, exist_ok=True)
    stub = tmp_path / "gh"
    stub.write_text(GH_STUB, encoding="utf-8")
    stub.chmod(0o755)
    (tmp_path / "prs.json").write_text(json.dumps(prs), encoding="utf-8")
    (tmp_path / "runs.json").write_text(json.dumps(runs or {}), encoding="utf-8")
    summary = tmp_path / "summary.md"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GH_", "STUB_"))}
    env.update({
        "PATH": str(tmp_path) + os.pathsep + env.get("PATH", ""),
        "DANGLING_GH_BIN": str(stub),
        "STUB_PRS": str(tmp_path / "prs.json"),
        "STUB_RUNS": str(tmp_path / "runs.json"),
        "GITHUB_STEP_SUMMARY": str(summary),
    })
    if fail_list:
        env["STUB_PR_LIST_FAIL"] = "1"
    proc = subprocess.run(
        [sys.executable, str(script or SCRIPT), "--repo", "o/r", "--minutes", str(minutes),
         *extra_args],
        capture_output=True, text=True, env=env, timeout=120,
    )
    return Out(proc, summary.read_text(encoding="utf-8") if summary.exists() else "")


def mutate_script(tmp_path, old, new):
    """对**真脚本源码**做单点变异（锚点漂移即测试自身失败）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    assert old in src, f"变异锚点不存在（脚本已漂移）：{old!r}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    mutated = tmp_path / "mutated_scan.py"
    mutated.write_text(src.replace(old, new, 1), encoding="utf-8")
    return mutated


# ══════════════════════════════════════════════════════════════════════════════
# 一、红证：族 B 的实测形态（#5139：0 条 check + 全 action_required + 超时）⇒ 必红
# ══════════════════════════════════════════════════════════════════════════════

def test_family_b_shape_is_flagged(tmp_path):
    """🔴 红证（**判据本体**）：0 条 check、required 永远 pending、已 open 120 分钟 ⇒ 必红。

    形状逐字取自 issue #5235 的实测读数：#5139 = `state=BLOCKED` / `checks=0` /
    `autoMerge=armed` / HEAD 上的 6 条 run 全是 `action_required`（`completed`+0s，从未执行）。
    """
    out = run_scan(tmp_path, [pr()], {"a" * 40: SUPPRESSED_RUNS})
    assert out.rc == 1, f"族 B 形态（PR 悬空 >N 分钟且零信号）没有判红：rc={out.rc}\n{out.out}"
    assert out.has_error(), f"必须打 ::error::（可见信号）：\n{out.out}"
    assert "GITHUB_TOKEN" in out.out, "读数必须点名族 B 的病因（提交由 GITHUB_TOKEN 推 ⇒ workflow 不触发）"
    assert "悬空 1 条" in out.summary, f"step summary 必须落笔：{out.summary!r}"


def test_clean_scan_is_green_and_says_how_many_it_scanned(tmp_path):
    """反向（防空跑）：没有悬空项 ⇒ 绿，且**说明扫了多少条**（"扫了 0 条"也看得见）。"""
    out = run_scan(tmp_path, [pr(age_min=5)], {})
    assert out.rc == 0, f"{out.out}"
    assert not out.has_error(), out.out
    assert "扫了 1 条" in out.out, f"必须报出扫描面（否则「空扫描」会被读成「没问题」）：\n{out.out}"


# ══════════════════════════════════════════════════════════════════════════════
# 二、负例（防「异步窗口假红」与「已有信号重复报」）
# ══════════════════════════════════════════════════════════════════════════════

NEGATIVE_CASES = {
    "仍在跑（run in_progress）": (dict(), {"a" * 40: RUNNING_RUNS}),
    "check 未跑完（pending）": (dict(rollup=(PENDING_CHECK,)), {}),
    "已经变红（required 判红）": (dict(rollup=(RED_CHECK,)), {}),
    "仅 open 5 分钟（< 阈值）": (dict(age_min=5), {}),
    "draft": (dict(draft=True), {}),
    "带 block/merge 人工闸": (dict(labels=("block/merge",)), {}),
    "required 已达可合（CLEAN）": (dict(state="CLEAN", rollup=(GREEN_CHECK,)), {}),
    "非 required 在红（UNSTABLE）": (dict(state="UNSTABLE", rollup=(GREEN_CHECK, RED_CHECK)), {}),
    "全绿且等合（armed + CLEAN）": (dict(state="CLEAN", rollup=(GREEN_CHECK,)), {}),
}


def test_negative_cases_stay_green(tmp_path):
    """每个负例都不得红（每条各一个夹具；下面另有逐条的变异红证）。"""
    for index, (label, (kwargs, runs)) in enumerate(NEGATIVE_CASES.items()):
        out = run_scan(tmp_path / str(index), [pr(**kwargs)], runs)
        assert out.rc == 0, f"负例「{label}」被误判为悬空（假红）：rc={out.rc}\n{out.out}"
        assert not out.has_error(), f"负例「{label}」打了 ::error::：\n{out.out}"


# 逐条变异：把该负例**依赖的那条闸**打掉 ⇒ 同一夹具必须变红（否则那条闸是空断言）
MUTATIONS = {
    "仍在跑（run in_progress）": ('if running:', 'if False:'),
    "check 未跑完（pending）": ('if pending:', 'if False:'),
    "已经变红（required 判红）": ('if red:', 'if False:'),
    "仅 open 5 分钟（< 阈值）": ('if age < minutes:', 'if False:'),
    "draft": ('if pr.get("isDraft"):', 'if False:'),
    "带 block/merge 人工闸": ('if labels & BLOCK_LABELS:', 'if False:'),
    "required 已达可合（CLEAN）": ('if state != "BLOCKED":', 'if False:'),
}


def test_every_negative_case_gate_has_discriminating_power(tmp_path):
    """**变异红证**：逐条打掉负例依赖的闸 ⇒ 该负例必须变红（证明每条闸都在真的挡东西）。"""
    for index, (label, (old, new)) in enumerate(MUTATIONS.items()):
        kwargs, runs = NEGATIVE_CASES[label]
        mutated = mutate_script(tmp_path / str(index), old, new)
        out = run_scan(tmp_path / str(index) / "run", [pr(**kwargs)], runs, script=mutated)
        assert out.rc == 1, (
            f"打掉「{label}」依赖的闸（{old!r} → {new!r}）后仍判绿 ⇒ 该负例没有被那条闸解释"
            f"（判据无判别力）：rc={out.rc}\n{out.out}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 三、三态：无从判定 ⇒ 不得当 0 读，也不得假红
# ══════════════════════════════════════════════════════════════════════════════

def test_unknown_merge_state_is_unjudged_not_red(tmp_path):
    """`mergeStateStatus=UNKNOWN`（GitHub 尚未算完）⇒ 记「未判定」+ `::warning::`，不假红。"""
    out = run_scan(tmp_path, [pr(state="UNKNOWN")], {})
    assert out.rc == 0, f"「还没算完」不得渲染成红（那是 #5113 同族的误报）：\n{out.out}"
    assert not out.has_error(), out.out
    assert out.has_warning(), f"未判定必须可见（不得静默）：\n{out.out}"
    assert "未判定" in out.summary and "不得当通过" in out.summary, f"{out.summary!r}"


def test_unreadable_pr_list_is_exit_3_not_zero(tmp_path):
    """🔴 读不到 open PR 列表 ⇒ 退出码 **3**（「无法判定」不得当 0 读）。"""
    out = run_scan(tmp_path, [pr()], {}, fail_list=True)
    assert out.rc == 3, f"读不到 PR 列表却报 0 = 把「没跑成」装成「没问题」：rc={out.rc}\n{out.out}"
    assert out.has_error(), out.out


# ══════════════════════════════════════════════════════════════════════════════
# 四、纯函数面（口径可读、可单点验证）
# ══════════════════════════════════════════════════════════════════════════════

def test_judge_is_pure_and_two_phase():
    """浅判据不足时才要 run 列表（省 API）；同一输入两次判定一致（幂等）。"""
    anchor = datetime.now(timezone.utc)
    shallow_pr = pr(now=anchor)
    verdict, _ = SCAN.judge(shallow_pr, None, anchor, 60)
    assert verdict == "need_runs", verdict
    once = SCAN.judge(shallow_pr, SUPPRESSED_RUNS, anchor, 60)
    twice = SCAN.judge(shallow_pr, SUPPRESSED_RUNS, anchor, 60)
    assert once == twice == ("dangling", once[1]), once


def test_reason_is_actionable():
    """读数必须可行动（点名病因 + 给出命令），不是"看起来悬空"。"""
    anchor = datetime.now(timezone.utc)
    _, reason = SCAN.judge(pr(now=anchor), SUPPRESSED_RUNS, anchor, 60)
    for token in ("action_required", "GITHUB_TOKEN", "merge_gate.py --check 5139",
                  "resolve_stale_bot_threads.py 5139", "armed"):
        assert token in reason, f"读数缺少可行动要素 {token!r}：{reason!r}"


# ══════════════════════════════════════════════════════════════════════════════
# 五、workflow 接线（宿主 = automerge.yml；本 job 只在定时/手动档上跑）
# ══════════════════════════════════════════════════════════════════════════════

def job_wiring_problems(doc):
    """纯函数：宿主接线的问题清单（空 = 合规）。注入式红证与真值断言共用同一口径。"""
    problems = []
    triggers = doc.get("on") or doc.get(True) or {}
    if "schedule" not in triggers:
        problems.append("缺 schedule（悬空 PR 不产生事件 ⇒ 没有定时入口就永远扫不到）")
    job = (doc.get("jobs") or {}).get(JOB)
    if not job:
        return problems + [f"缺 job `{JOB}`"]
    cond = str(job.get("if") or "")
    if "schedule" not in cond or "workflow_dispatch" not in cond:
        problems.append(
            "job 的 `if:` 没有限定在 schedule/workflow_dispatch ⇒ 会在 pull_request_target 上跑，"
            "把「别的 PR 悬空」变成**每个 PR 上一条无关的红 check**"
        )
    perms = job.get("permissions")
    if not isinstance(perms, dict) or any(str(v) != "read" for v in perms.values()):
        problems.append(f"job 权限必须是**只读**（本 job 只扫不改）：{perms!r}")
    body = "\n".join(str(s.get("run") or "") for s in job.get("steps") or [])
    if "dangling_pr_scan.py" not in body:
        problems.append("没有任何 step 跑 scripts/dangling_pr_scan.py")
    return problems


def _workflow_doc():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_host_workflow_wiring_is_clean():
    assert SCRIPT.is_file(), f"缺判据脚本 {SCRIPT.relative_to(REPO_ROOT)}"
    assert job_wiring_problems(_workflow_doc()) == []


def test_host_workflow_wiring_guard_is_not_vacuous():
    """注入式红证：四处各改一处 ⇒ 对应判据必须变红（证明它不恒真）。"""
    base = _workflow_doc()
    mutations = [
        ("去掉 schedule", lambda d: d[True].pop("schedule")),
        ("放开 if（会在 PR 事件上跑）", lambda d: d["jobs"][JOB].__setitem__("if", "true")),
        ("把权限放大成 write", lambda d: d["jobs"][JOB]["permissions"].__setitem__(
            "pull-requests", "write")),
        ("step 不再跑判据脚本", lambda d: d["jobs"][JOB]["steps"][-1].__setitem__(
            "run", "echo noop")),
    ]
    for label, mutate in mutations:
        doc = copy.deepcopy(base)
        mutate(doc)
        assert job_wiring_problems(doc), f"注入「{label}」后仍判绿 ⇒ 该判据是空断言"
    assert job_wiring_problems(base) == [], "先决条件：未变异的真文件必须合规"
