# case_ids: MC-012, MC-095
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。
#   MC-095 = issue #6815「冲突态 ⇒ `pull_request` 工作流连 run 都不创建」的**三态**判据。）
r"""悬空 PR 扫描（`scripts/dangling_pr_scan.py`）的 L0 守卫 —— issue #5235 / #6815 的可见性面。

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
| 8 | **冲突态「run 未创建」（issue #6815）**：`mergeStateStatus=DIRTY` ∧ head SHA 上**没有** `event=pull_request` 的 run | **必红**（态 ①） | 现场形状（只剩 `Auto Merge`）⇒ rc 1 + `::error::` + 具名 required 名单 + 出口命令 |
| 9 | **三态必须分清**：① 未创建 / ② 创建但 pending / ③ 创建且失败 | **只有 ① 判红**；②/③ 的**读数**必须各自可见 | 四夹具并列（rc = 1/0/0/0）+ summary 分栏 |
| 10 | 负控：非 `DIRTY` / `DIRTY` 但 `pull_request` run 已创建（pending/红/绿）/ `BEHIND` | **一律不得红** | 单变量差分对（同 run 形状、只差 `mergeStateStatus`） |
| 11 | 既有 `BLOCKED` 族（族 B / `paths:` 过滤） | **逐字不变**（不许因本单放宽） | 读数仍点名 `on.pull_request.paths`，且**不得**被归因成"冲突" |
| 12 | **跳过也要长得像跳过**：`draft ∧ 冲突`（#6809 现场在冲突窗口内正是 draft） | **不判红**（既有 `isDraft` 口径不变）**但必须出声** | `::warning::` + summary「已跳过」栏 + 点名兜底面（`gh pr ready`）；负控 = 非冲突 draft **不出声** |

⚠️ **判据形态**：读的是**真脚本的行为**（子进程 + `gh` 替身，CLI 边界即注入点）与**真 YAML 真值**，
不是"断言自己的文案"。`scripts/` 侧的 `gh` 替身走 `DANGLING_GH_BIN`（沿用 `MG_GH_BIN` 先例）。
⚠️ **变异锚点必须指定"第几次出现"**：`if red:` / `if running:` 在脚本里**各有两处**（既有
`BLOCKED` 分支 + 新增冲突分支）⇒ 只换第一次会把变异打在**另一条**闸上（看起来"变异无效"，
其实是打错了对象）。本文件 `MUTATIONS` 表的第 3 项即 `count`。
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
       rollup=(), armed=True, sha="a" * 40, title="chore(ci): flaky 台账滚动追加", now=None,
       mergeable="MERGEABLE"):
    # ⚠️ 时间锚必须取**调用时的真实钟**：CLI 侧的被测脚本用 `datetime.now()` 算年龄，
    #    固定常量锚会让所有夹具的年龄随墙上时钟漂大（本文件初版就这么假红过一次）。
    now = now or datetime.now(timezone.utc)
    return {"number": number, "title": title, "isDraft": draft,
            "createdAt": (now - timedelta(minutes=age_min)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mergeStateStatus": state, "mergeable": mergeable,
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


# ══════════════════════════════════════════════════════════════════════════════
# 〇、冲突态（issue #6815）：`event 投递 ≠ 检查存在` —— 三态必须**各自可见**
# ══════════════════════════════════════════════════════════════════════════════
# 现场逐字（issue #6815）：PR 与 base 冲突 ⇒ GitHub 造不出合并提交 `refs/pull/<n>/merge`
# ⇒ **`pull_request` 事件的工作流根本不创建 run**；而 `pull_request_target` 跑在 base 上、
# 不需要合并提交 ⇒ 照常跑 ⇒ 长成「只在跑不查的那一族在动，报门禁的那一族静默消失」。

def conflict_runs(tmp_path, workflows=("pr-check.yml",)):
    """构造**判据用**的工作流目录 + required 名单（`--required-file` 注入，绕开 gh/网络）。

    唯一真值源 = `.github/workflows/<wf>` 里那个 job 的 `name:`（GitHub 上报名 = job display name）
    ⇒ required 名单与 run 的 `workflowName` 的对应关系由**真文件**给出，不硬编码在判据里。
    """
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    for name in workflows:
        (wf_dir / name).write_text(
            "name: {n}\non:\n  pull_request:\n    branches: [main]\njobs:\n"
            "  pr-check:\n    name: PR Check\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: echo ok\n".format(n=name),
            encoding="utf-8")
    req = tmp_path / "required.json"
    req.write_text(json.dumps({"contexts": ["PR Check"]}), encoding="utf-8")
    return str(wf_dir), str(req)


def run_conflict_scan(tmp_path, prs, runs, *, minutes=60, workflows=("pr-check.yml",), script=None):
    wf_dir, req = conflict_runs(tmp_path, workflows)
    return run_scan(tmp_path / "run", prs, runs, minutes=minutes, script=script,
                    extra_args=("--workflows-dir", wf_dir, "--required-file", req))


#: 现场形状：HEAD 上**只有** `pull_request_target` 那一族（`Auto Merge` = 0s/skipped 也可）
PTARGET_RUNS = [{"status": "completed", "conclusion": "skipped", "workflowName": "Auto Merge",
                 "event": "pull_request_target"}]
#: 态 ②：合并 ref 造出来了（`pull_request` run 存在）且**还在跑**
PR_PENDING_RUNS = [{"status": "in_progress", "conclusion": None, "workflowName": "PR Check",
                    "event": "pull_request"}]
#: 态 ③：合并 ref 造出来了，run **已创建且失败**
PR_RED_RUNS = [{"status": "completed", "conclusion": "failure", "workflowName": "PR Check",
                "event": "pull_request"}]
#: 态 ③′：`pull_request` run 已创建并跑完（绿）
PR_GREEN_RUNS = [{"status": "completed", "conclusion": "success", "workflowName": "PR Check",
                  "event": "pull_request"}]


def test_conflict_no_pr_run_is_state_one_and_red(tmp_path):
    """🔴 红证（**判据本体**，issue #6815）：`DIRTY` ∧ HEAD 上无 `event=pull_request` 的 run ⇒ 必红。

    形状逐字取自 issue：`mergeable=CONFLICTING` / `mergeState=DIRTY` / checks 里**连行都没有** /
    `gh run list` 只剩 `Auto Merge`（`pull_request_target`）。
    """
    out = run_conflict_scan(tmp_path, [pr(number=6809, state="DIRTY", mergeable="CONFLICTING")],
                            {"a" * 40: PTARGET_RUNS})
    assert out.rc == 1, f"冲突态「run 未创建」没有判红（本次事故的原形态）：rc={out.rc}\n{out.out}"
    assert out.has_error(), f"必须打 ::error::（可见信号）：\n{out.out}"
    # 三态的**措辞**必须可区分：本态 = ①（不存在），不是 ②（再等等）
    for token in ("态 ①", "不是 pending", "DIRTY", "CONFLICTING",
                  "refs/pull/6809/merge", "pull_request", "update-branch"):
        assert token in out.out, f"读数缺少可行动/可归因要素 {token!r}：\n{out.out}"
    # 具名报出「required 检查名在 head SHA 上不存在」——由**真工作流文件**的 job `name:` 反查
    assert "PR Check" in out.out and "pr-check.yml" in out.out, (
        f"必须具名报出哪些 required 检查/工作流在这条 HEAD 上不存在：\n{out.out}")
    assert "悬空 1 条" in out.summary, f"step summary 必须落笔：{out.summary!r}"


def test_conflict_states_are_three_distinct_readings(tmp_path):
    """**三态必须分清**（本单核心语义）：① 未创建 ⇒ 红；② pending / ③ 失败 ⇒ **不**红。

    把 ① 读成 ②（"再等等"）正是本次事故浪费 1 小时的**心理机制** ⇒ 三种读数的**措辞**必须不同，
    且只有 ① 判红（②/③ 在 PR 页面上另有可见信号）。
    """
    kwargs = dict(number=6809, state="DIRTY", mergeable="CONFLICTING")
    one = run_conflict_scan(tmp_path / "one", [pr(**kwargs)], {"a" * 40: PTARGET_RUNS})
    two = run_conflict_scan(tmp_path / "two", [pr(**kwargs)], {"a" * 40: PR_PENDING_RUNS})
    three = run_conflict_scan(tmp_path / "three", [pr(**kwargs)], {"a" * 40: PR_RED_RUNS})
    three_b = run_conflict_scan(tmp_path / "threeb", [pr(**kwargs)], {"a" * 40: PR_GREEN_RUNS})

    assert (one.rc, two.rc, three.rc, three_b.rc) == (1, 0, 0, 0), (
        f"三态判定必须是 ① 红 / ② 绿 / ③ 绿：{one.rc}/{two.rc}/{three.rc}/{three_b.rc}\n"
        f"{one.out}\n{two.out}\n{three.out}")
    assert "态 ②" in two.out and "确实已创建" in two.out, f"态 ② 的读数必须自己说清：\n{two.out}"
    assert "态 ③" in three.out, f"态 ③ 的读数必须自己说清：\n{three.out}"
    # ②/③ **必须也出现在 summary 里**（否则"冲突但检查已创建"这些条会从报告里消失，
    # 报告面与判定面就会错开 —— 正是 issue 里「检测面与要检测的形态错开」的同族形态）
    assert "态 ②/③" in two.summary and "态 ②/③" in three.summary, (
        f"summary 必须分开列出态 ②/③：\n{two.summary!r}\n{three.summary!r}")
    assert "悬空 1 条" in one.summary and "态 ①" in one.summary, f"{one.summary!r}"


def test_state_one_gate_has_discriminating_power(tmp_path):
    """**变异红证**：打掉冲突态那条闸（`if state in CONFLICT_STATES:`）⇒ 本判据的输出**整体消失**。

    没有它，`DIRTY` 会掉进 `state != "BLOCKED"` 的"另有页面级显式信号"分支 ⇒ 静默（**正是本缺陷**）。
    ⚠️ 断言不能只看退出码：`DIRTY` 落到 draft 分支时也会 `ok` ⇒ 「rc 变 0」不足以证明是**这条**闸
    挡住的。故这里同时钉住「判红 + 态 ① 读数」两者都消失。
    """
    # ⚠️ `if state in CONFLICT_STATES:` 出现**两次**（draft-可见面 + 本判据本体）⇒ 必须 `count=2`
    #    定位到 `judge()` 里那一处（只换第一处会打在"跳过可见面"上，判据本体照旧红 —— 打错对象）。
    mutated = mutate_script(tmp_path, "if state in CONFLICT_STATES:",
                            "if False:  # mutated: 打掉冲突态闸", count=2)
    out = run_conflict_scan(tmp_path, [pr(number=6809, state="DIRTY", mergeable="CONFLICTING")],
                            {"a" * 40: PTARGET_RUNS}, script=mutated)
    assert out.rc == 0 and not out.has_error(), (
        f"打掉 `if state in CONFLICT_STATES:` 后**仍然判红** ⇒ 该闸没在挡东西（判据无判别力）：\n{out.out}"
    )
    for token in ("态 ①", "refs/pull/6809/merge", "update-branch"):
        assert token not in out.out, (
            f"打掉该闸后仍输出 {token!r} ⇒ 判据本体没被这条闸解释：\n{out.out}")
    # 反向对照（防"改了就红"式的假判别力）：**未变异的真脚本**在同一夹具上必须红且有态 ①
    good = run_conflict_scan(tmp_path / "good",
                             [pr(number=6809, state="DIRTY", mergeable="CONFLICTING")],
                             {"a" * 40: PTARGET_RUNS})
    assert good.rc == 1 and "态 ①" in good.out, f"先决条件不成立：\n{good.out}"


def test_conflict_event_discriminator_has_discriminating_power(tmp_path):
    """**变异红证（核心）**：把「哪一族需要合并提交」换成 `pull_request_target` ⇒ 必假红。

    这一条锁的是本单的**语义核心**：判据认的是「**`pull_request`** 那一族（需要 `refs/pull/<n>/merge`）
    没有 run」，**不是**「HEAD 上没有任何 run」。现场正是这一族之差 —— `pull_request_target` 跑在
    base 上、不需要合并提交 ⇒ 照常跑 ⇒ 只按"有没有 run"判就会**漏报**（原缺陷），而把事件面认反
    则会**假红**（把照常跑的 `pull_request_target` 当成"检查已创建"或反之）。两个方向都必须红。
    """
    mutated = mutate_script(tmp_path, 'MERGE_REF_EVENT = "pull_request"',
                            'MERGE_REF_EVENT = "pull_request_target"  # mutated: 认错了事件面')
    out = run_conflict_scan(tmp_path, [pr(number=6809, state="DIRTY", mergeable="CONFLICTING")],
                            {"a" * 40: PTARGET_RUNS}, script=mutated)
    assert out.rc == 0, (
        "把事件面认成 `pull_request_target` 后，现场形状（只剩 Auto Merge）**仍判红** ⇒ "
        f"`MERGE_REF_EVENT` 这条区分没有判别力：\n{out.out}")
    # 反向：把事件面认成 `pull_request_target` 时，**真正只有 `pull_request`** 的形状不得再判红
    out2 = run_conflict_scan(tmp_path / "rev",
                             [pr(number=6809, state="DIRTY", mergeable="CONFLICTING")],
                             {"a" * 40: PR_PENDING_RUNS}, script=mutated)
    assert out2.rc == 1, (
        "事件面认反后，**只有** `pull_request` run（= 冲突已解、腿已恢复）的形状被漏报 ⇒ "
        f"该判据在假绿：\n{out2.out}")


def test_cannot_tell_when_event_field_is_missing_is_unjudged(tmp_path):
    """三态之外的**第四态**：run 读不到 `event` ⇒ 记「未判定」（不得当 ① 乐观跳闸，也不当 0）。"""
    runs = [{"status": "completed", "conclusion": "skipped", "workflowName": "Auto Merge"}]
    out = run_conflict_scan(tmp_path, [pr(number=6809, state="DIRTY", mergeable="CONFLICTING")],
                            {"a" * 40: runs})
    assert out.rc == 0, f"读不到 `event` 不得判红（那是猜）：\n{out.out}"
    assert out.has_warning() and "event" in out.out, f"必须出声说「判不了」：\n{out.out}"


CONFLICT_NEGATIVE_CASES = {
    # ⚠️ 「BLOCKED + 无 run」**不在这里**：它是**既有**族 B 判据的正形态（#5139），照旧判红；
    #    本单只新增 `DIRTY` 入口 ⇒ 它必须**逐字不变**（见 test_blocked_dangling_is_unchanged）。
    "非冲突 PR（CLEAN，无 run）": (dict(state="CLEAN", mergeable="MERGEABLE"), {}, PTARGET_RUNS),
    "非冲突 PR（UNSTABLE + 未跑完 check）": (dict(state="UNSTABLE", mergeable="MERGEABLE",
                                                rollup=(PENDING_CHECK,)), {}, PR_PENDING_RUNS),
    "DIRTY 但已有 pending 的 pull_request run": (dict(state="DIRTY", mergeable="CONFLICTING"),
                                                 {}, PR_PENDING_RUNS),
    "DIRTY 但 pull_request run 已判红": (dict(state="DIRTY", mergeable="CONFLICTING"),
                                        {}, PR_RED_RUNS),
    "DIRTY 但 pull_request run 已跑完（绿）": (dict(state="DIRTY", mergeable="CONFLICTING"),
                                              {}, PR_GREEN_RUNS),
    "BEHIND（落后 ≠ 冲突）": (dict(state="BEHIND", mergeable="UNKNOWN"), {}, PTARGET_RUNS),
}


def test_conflict_detector_does_not_false_positive(tmp_path):
    """**负控（一）**：非冲突 PR / 检查已创建的冲突 PR ⇒ 一律不得判红。"""
    for index, (label, (kwargs, _ignored, runs)) in enumerate(CONFLICT_NEGATIVE_CASES.items()):
        out = run_conflict_scan(tmp_path / str(index),
                               [pr(number=6809, **kwargs)], {"a" * 40: runs})
        assert out.rc == 0, f"负控「{label}」被误判为悬空（假红）：rc={out.rc}\n{out.out}"
        assert not out.has_error(), f"负控「{label}」打了 ::error::：\n{out.out}"


#: **负控（二）= 单变量差分对**：「无 `pull_request` run」这个形态**单独不足以**判红 ——
#: 同样的 run 形状、只把 `mergeStateStatus` 从 `DIRTY` 换成 `BLOCKED`，读数必须另走既有分支。
#: 这一对的用途：证明新判据认的是「**冲突** ∧ 检查未创建」而**不是**「检查未创建」本身
#: （否则每个"面内没碰必要路径"的 PR 都会被刷红 —— `paths:` 形态的 `mergeStateStatus` 正是 `BLOCKED`）。
STATE_ONE_DIFFERENTIAL = {
    "DIRTY + 只有 pull_request_target run": (dict(state="DIRTY", mergeable="CONFLICTING"),
                                             PTARGET_RUNS, 1, "态 ①"),
    "BLOCKED + 只有 pull_request_target run": (dict(state="BLOCKED"), PTARGET_RUNS, 1, "BLOCKED"),
}


def test_state_one_needs_the_conflict_condition_is_non_dirty_control(tmp_path):
    """**负控（二）**：同 run 形状、只差 `mergeStateStatus` ⇒ 读数**必须不同**且各自归因正确。

    左列 = 本单新增的态 ①（冲突 ⇒ 合并 ref 造不出）；右列 = 既有族 B（`BLOCKED` ⇒ required 未达可合）。
    两者**都判红**是对的（都是真缺陷），但**归因不同** —— 本判据不许把右列错记成"冲突"。
    """
    readings = {}
    for index, (label, (kwargs, runs, expect_rc, token)) in enumerate(
            STATE_ONE_DIFFERENTIAL.items()):
        out = run_conflict_scan(tmp_path / str(index), [pr(number=6809, **kwargs)],
                                {"a" * 40: runs})
        assert out.rc == expect_rc, f"「{label}」退出码应为 {expect_rc}：rc={out.rc}\n{out.out}"
        assert token in out.out, f"「{label}」读数必须落在 {token!r} 那条归因上：\n{out.out}"
        readings[label] = out.out
    blocked = readings["BLOCKED + 只有 pull_request_target run"]
    dirty = readings["DIRTY + 只有 pull_request_target run"]
    assert "mergeStateStatus=BLOCKED" in blocked, (
        f"`BLOCKED` 那一条必须归因到既有病因（required 未达可合）：\n{blocked}")
    assert "DIRTY" in dirty, f"`DIRTY` 那一条必须归因到冲突：\n{dirty}"
    assert dirty != blocked, (
        "两种归因的读数逐字相同 ⇒ 判据没有把「冲突」与「required 未达可合」分开")


def test_blocked_dangling_is_unchanged(tmp_path):
    """**不许因本单放宽既有判据**：`BLOCKED` + 无 check + 无 run（= 族 B / `paths:` 过滤形态）仍判红。

    读数里必须**逐字保留**既有病因点名（`on.pull_request.paths`）——那是常驻判据
    `tests/unit_ci_workflows/test_required_check_no_paths_filter.py` 的可见性面，本包**零改动**。
    """
    out = run_scan(tmp_path, [pr(number=5139, state="BLOCKED")], {})
    assert out.rc == 1, f"既有的族 B / `paths:` 形态必须仍判红：\n{out.out}"
    assert "on.pull_request.paths" in out.out, (
        f"既有读数必须逐字保留（点名 paths 过滤这条病因）：\n{out.out}")
    assert "态 ①" not in out.out, (
        f"非冲突 PR 不得被归因成「冲突态 ①」（归因必须落在真正的原因上）：\n{out.out}")


def mutate_script(tmp_path, old, new, count=1):
    """对**真脚本源码**做单点变异（锚点漂移即测试自身失败）。

    `count>1` = 只换**第 count 次**出现：本文件里 `if running:` 有两处（既有 `BLOCKED` 分支
    与新增的冲突分支），不区分就会把红证打在**另一条**闸上。
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert old in src, f"变异锚点不存在（脚本已漂移）：{old!r}"
    parts = src.split(old)
    assert len(parts) > count, f"变异锚点只出现 {len(parts) - 1} 次，取不到第 {count} 次：{old!r}"
    mutated_src = old.join(parts[:count]) + new + old.join(parts[count:])
    tmp_path.mkdir(parents=True, exist_ok=True)
    mutated = tmp_path / "mutated_scan.py"
    mutated.write_text(mutated_src, encoding="utf-8")
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
    # ⚠️ 这里必须是 **`BLOCKED`** 的「还在跑」形状：`DIRTY` 的对应形状由 issue #6815 的
    #    分支自己判（见下面 `CONFLICT_NEGATIVE_CASES`），否则两条闸会互相遮蔽、变异红证失效。
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
#: ⚠️ 第 3 项 = **第几次出现**（`count`）：`if red:` / `if running:` 在脚本里各有**两处**
#: （既有 `BLOCKED` 分支 + 新增的冲突态分支）⇒ 不指定就会把变异打在**另一条**闸上
#: （变异看似无效，其实是打错了对象 —— 本文件初版就这么假绿过一次）。
MUTATIONS = {
    "check 未跑完（pending）": ('if pending:', 'if False:', 1),
    "已经变红（required 判红）": ('if red:', 'if False:', 2),
    "仅 open 5 分钟（< 阈值）": ('if age < minutes:', 'if False:', 1),
    "draft": ('if pr.get("isDraft"):', 'if False:', 1),
    "带 block/merge 人工闸": ('if labels & BLOCK_LABELS:', 'if False:', 1),
    "required 已达可合（CLEAN）": ('if state != "BLOCKED":', 'if False:', 1),
}


def test_every_negative_case_gate_has_discriminating_power(tmp_path):
    """**变异红证**：逐条打掉负例依赖的闸 ⇒ 该负例必须变红（证明每条闸都在真的挡东西）。"""
    for index, (label, (old, new, count)) in enumerate(MUTATIONS.items()):
        kwargs, runs = NEGATIVE_CASES[label]
        mutated = mutate_script(tmp_path / str(index), old, new, count=count)
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
    """浅判据不足时才要 run 列表（省 API）；同一输入两次判定一致（幂等）。

    `judge` 返回 `(verdict, reason, note)`：`note` = 「跳过也要长得像跳过」的可见面
    （现取口径 = `DIRTY ∧ draft`，见 `test_draft_conflict_is_visible_not_silent`）。
    """
    anchor = datetime.now(timezone.utc)
    shallow_pr = pr(now=anchor)
    verdict, _reason, note = SCAN.judge(shallow_pr, None, anchor, 60)
    assert verdict == "need_runs", verdict
    assert note == "", f"普通候选不得产生跳过读数（防噪声）：{note!r}"
    once = SCAN.judge(shallow_pr, SUPPRESSED_RUNS, anchor, 60)
    twice = SCAN.judge(shallow_pr, SUPPRESSED_RUNS, anchor, 60)
    assert once == twice == ("dangling", once[1], ""), once


def test_draft_conflict_is_visible_not_silent(tmp_path):
    """🔴 **「跳过」必须长得像「跳过」**（issue #6815 的第二个成因）：`draft ∧ 冲突` 出话。

    现场（#6809）在冲突窗口内是 **draft** ⇒ 既有口径 `isDraft ⇒ ok` 让整条扫描**不出声**；
    叠加「`pull_request` 腿没创建」就成了**永久静默**的组合。本判据**不改**跳过口径（draft 有意不可合），
    只把它**变可见**：`::warning::` + summary「已跳过」栏 + 一句点名兜底面（作者 `gh pr ready` 那一刻）。
    """
    out = run_scan(tmp_path, [pr(number=6809, draft=True, state="DIRTY", mergeable="CONFLICTING")],
                   {"a" * 40: PTARGET_RUNS})
    assert out.rc == 0, f"draft 仍按既有口径跳过（不判红）：rc={out.rc}\n{out.out}"
    assert not out.has_error(), f"draft 不得打 ::error::：\n{out.out}"
    assert out.has_warning() and "已跳过" in out.out, (
        f"`draft ∧ 冲突` 必须出声（否则这一组合永久静默）：\n{out.out}")
    assert "draft ∧ 冲突" in out.out and "gh pr ready" in out.out, (
        f"跳过读数必须点名组合与兜底面：\n{out.out}")
    assert "已跳过" in out.summary, f"summary 必须分栏列出跳过项：{out.summary!r}"
    # 负控：**非冲突**的 draft 不得被这条可见面刷出声（否则每个草稿都刷一条噪声）
    quiet = run_scan(tmp_path / "quiet", [pr(number=6810, draft=True)], {})
    assert quiet.rc == 0 and not quiet.has_warning(), (
        f"普通 draft（非冲突）不得出声：\n{quiet.out}")


def test_reason_is_actionable():
    """读数必须可行动（点名病因 + 给出命令），不是"看起来悬空"。"""
    anchor = datetime.now(timezone.utc)
    _, reason, _note = SCAN.judge(pr(now=anchor), SUPPRESSED_RUNS, anchor, 60)
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
