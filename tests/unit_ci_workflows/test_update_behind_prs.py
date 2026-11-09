# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012 ——
#   见 `.github/cases/misc.yml` 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。
#   本包不新建用例族、不改 `cases/**`。）
r"""「全绿 + 已 arm + `mergeStateStatus=BEHIND` ⇒ 永不合并」的收口判据（issue #8850）。

## 被测行为（issue 的现场读数，逐字）

本仓分支保护 `strict: true`（要求 up-to-date）+ 仓库 `allow_update_branch=false`
（PR 页面**没有** "Update branch" 按钮、GitHub 也不会自动更新），而仓内没有任何 workflow 跑
`gh pr update-branch`；兜底扫描 `scripts/dangling_pr_scan.py` 又**明确排除 BEHIND**
（理由是「BEHIND 在 PR 页面上有显式可行动横幅」—— 而本仓把那个横幅关掉了）
⇒ **全绿 + 已 arm 的 PR 会永远停在 BEHIND**（#8846 实测：连打三次 update-branch 才合）。

## 本文件锁什么（每条都能单独变红；红证见文末 `test_red_proof_*`）

| # | 不变式 | 会红的形态 |
|---|---|---|
| 1 | 已 arm ∧ `BEHIND` ∧ required 全绿 ⇒ **恰好一次** `gh pr update-branch` | 一次都不动（机制空转）/ 动两次（无界重试） |
| 2 | dependabot 作者**不碰**（交给 #8845 的 rebase 腿） | 两条腿同时命中同一 PR ⇒ npm lock 再坏一次 |
| 3 | 未 arm 不碰（未 arm 归 #5235 的 arm 腿） | 把「没人 arm」也当成本脚本的活 |
| 4 | 非 `BEHIND`（`CLEAN`/`BLOCKED`/`DIRTY`/`UNKNOWN`…）不动作、**且不白读 API** | 在 `CLEAN` 上也 update（制造无意义的 CI 轮次） |
| 5 | required 有红 / 未跑完 ⇒ 不动作（不带着红 update） | 带着红 update ⇒ 白跑一轮 CI（`pr-merge-when-clean.sh` 的顺序①） |
| 6 | required **读不到 / 空清单 ⇒ `3`**（「判不了」≠「可以」，「空集合 ≠ 绿」） | 把读不到读成绿 ⇒ 拿「量不出来」当放行 |
| 7 | 冲突 / 422 ⇒ **`3` + 具名 warning**，job **不判红**、不重试 | 无限重试冲突 PR / 把「需要人工」渲染成 `::error::` |
| 8 | 机制自身失败（取不到 PR 列表 / 权限 / 其它 update 失败）⇒ **`1` + 具名 `::error::`** | 静默吞掉（「没跑成」长得像「没问题」） |
| 9 | 默认**只读**，`--apply` 才写；`--apply` ∧ `--dry-run` ⇒ 拒（互斥） | 默认就写（本地复跑会真的动 PR） |
| 10 | 宿主接线：`schedule`/`workflow_dispatch` 档、`pull-requests: write` + `contents: write`、真的带 `--apply` 跑脚本、存活读数在 | 在 `pull_request_target` 上跑 / 缺权限 / 不跑脚本 / 读数缺失 |
| 11 | **不改 `detect-dangling-prs`**（它的红证以「最后一步 = 跑判据脚本那一步」为前提） | 给它加一步 ⇒ 那条既有红证变空断言 |
| 12 | 不新增 cron（复用既有 `7 * * * *`）、不 `gh pr merge`、不 `git push`、无重试循环 | 新增周期面 / 抢合并 / 抢写分支 |

⚠️ **判据形态**：读的是**真脚本的行为**（子进程 + `gh` 替身，CLI 边界即注入点，沿用
`DANGLING_GH_BIN` / `AUTOMERGE_GH_BIN` 先例）与**真 YAML 真值**，不是「断言自己的文案」。
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "update_behind_prs.py"
REBASE_LEG = REPO_ROOT / "scripts" / "dependabot_rebase_sweep.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "automerge.yml"
JOB = "update-behind-prs"
DANGLING_JOB = "detect-dangling-prs"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


UBP = _load(SCRIPT, "update_behind_prs")


# ══════════════════════════════════════════════════════════════════════════════
# 夹具（形状取自 `gh pr list --json …` / `gh pr checks --required --json …` 的真实读数）
# ══════════════════════════════════════════════════════════════════════════════
GREEN_ROWS = [
    {"name": "QA Growth Gate", "state": "SUCCESS", "bucket": "pass"},
    {"name": "admin-api unit tests", "state": "SUCCESS", "bucket": "pass"},
    {"name": "UI Regression Check", "state": "SUCCESS", "bucket": "pass"},
]
RED_ROWS = [
    {"name": "QA Growth Gate", "state": "SUCCESS", "bucket": "pass"},
    {"name": "admin-web typecheck + unit tests", "state": "FAILURE", "bucket": "fail"},
]
PENDING_ROWS = [
    {"name": "QA Growth Gate", "state": "IN_PROGRESS", "bucket": "pending"},
]


def pr(number=8846, *, author="zhaokai-mgzn", state="BEHIND", armed=True, draft=False,
       labels=(), cross=False, base="main", title="feat(ci): 夹具 PR"):
    """`gh pr list --json` 的一条读数（字段名与脚本的 `PR_FIELDS` 逐字一致）。"""
    return {"number": number, "title": title, "author": {"login": author},
            "isDraft": draft, "baseRefName": base, "isCrossRepository": cross,
            "labels": [{"name": name} for name in labels],
            "autoMergeRequest": {"mergeMethod": "SQUASH"} if armed else None,
            "mergeStateStatus": state}


# ── `gh` 替身（夹具驱动；**退出码不可作判据**这一点也在桩里如实复刻）──────────────────
GH_STUB = r'''#!/usr/bin/env python3
"""`gh` 替身（夹具驱动）。注入点 = CLI 边界：`UPDATE_BEHIND_GH_BIN`。"""
import json, os, sys
from pathlib import Path

state_path = Path(os.environ["UBP_STUB_DIR"]) / "state.json"
state = json.loads(state_path.read_text(encoding="utf-8"))
args = sys.argv[1:]


def save():
    state_path.write_text(json.dumps(state), encoding="utf-8")


if args[:2] == ["pr", "list"]:
    if os.environ.get("STUB_LIST_FAIL") == "1":
        sys.stderr.write("stub: gh pr list 失败（注入）\n")
        sys.exit(1)
    print(json.dumps(state.get("prs") or []))
    sys.exit(0)

if args[:2] == ["pr", "checks"]:
    number = args[2]
    entry = (state.get("checks") or {}).get(number)
    if entry is None:                      # 读不到 required 面（桩没给这个 PR 的读数）
        sys.stderr.write("stub: no required checks reported on 'x' branch\n")
        sys.exit(1)
    print(json.dumps(entry))
    # 退出码**不可**作判据：gh 在有红/待跑时同样非 0（1 / 8）—— 桩如实复刻。
    sys.exit(8 if any(str(r.get("state") or "").upper() != "SUCCESS" for r in entry) else 0)

if args[:2] == ["pr", "update-branch"]:
    number = args[2]
    state.setdefault("calls", []).append(number)
    save()
    fail = (state.get("update_fail") or {}).get(number)
    if fail:
        sys.stderr.write(str(fail.get("stderr") or "stub: update-branch 失败\n"))
        sys.exit(int(fail.get("rc") or 1))
    # 真实读数（2026-11-09 本机现取）：分支未落后时 gh **rc=0** 且打印
    # `✓ PR branch already up-to-date` ⇒ 桩要能复刻这一形态（否则「已不落后」读不出来）。
    print((state.get("update_note") or {}).get(number) or "updated")
    sys.exit(0)

sys.stderr.write("stub: unhandled argv=%r\n" % (args,))
sys.exit(9)
'''


class Out:
    """一次运行的可观测结果（退出码 / 输出 / step summary / 替身记账）。"""

    def __init__(self, proc, summary, state):
        self.proc = proc
        self.summary = summary
        self.state = state

    @property
    def rc(self):
        return self.proc.returncode

    @property
    def out(self):
        return self.proc.stdout + self.proc.stderr

    @property
    def calls(self):
        return list(self.state.get("calls") or [])

    def has_error(self):
        return "\n::error::" in ("\n" + self.out)

    def has_warning(self):
        return "\n::warning::" in ("\n" + self.out)


def run_script(tmp_path, *, state=None, prs=None, checks=None, update_fail=None,
               update_note=None, extra_args=("--apply",), script=None, list_fail=False):
    """跑**真脚本**（子进程）对 `gh` 替身；返回 `Out`（含替身记录下的 update-branch 调用）。"""
    if state is None:
        state = {"prs": prs or [], "checks": checks or {}, "update_fail": update_fail or {},
                 "update_note": update_note or {}}
    tmp_path.mkdir(parents=True, exist_ok=True)
    stub = tmp_path / "gh"
    stub.write_text(GH_STUB, encoding="utf-8")
    stub.chmod(0o755)
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    summary = tmp_path / "summary.md"
    # 隔离宿主环境：不留 GH_* / STUB_*（否则可能读到本机真 gh 的凭据）
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GH_", "UBP_", "STUB_"))}
    env.update({
        "PATH": str(tmp_path) + os.pathsep + env.get("PATH", ""),
        "UPDATE_BEHIND_GH_BIN": str(stub),
        "UBP_STUB_DIR": str(tmp_path),
        "GITHUB_STEP_SUMMARY": str(summary),
    })
    if list_fail:
        env["STUB_LIST_FAIL"] = "1"
    proc = subprocess.run([sys.executable, str(script or SCRIPT), "--repo", "o/r", *extra_args],
                          capture_output=True, text=True, env=env, timeout=120)
    written = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    return Out(proc, summary.read_text(encoding="utf-8") if summary.exists() else "", written)


# ══════════════════════════════════════════════════════════════════════════════
# 一、纯判定面（口径可读、可单点验证）
# ══════════════════════════════════════════════════════════════════════════════
def test_required_verdict_has_four_states():
    assert UBP.required_verdict(GREEN_ROWS)[0] == "green"
    assert UBP.required_verdict(RED_ROWS)[0] == "red"
    # 「未跑完」与「读不到」必须**分开**：前者等下轮，后者要出声
    assert UBP.required_verdict(PENDING_ROWS)[0] == "not-green"
    assert UBP.required_verdict([])[0] == "unreadable", "空清单 ≠ 绿（本仓 required 现取 16 条）"
    assert UBP.required_verdict([])[1].count("空集合") == 1


def test_decide_is_two_phase_and_idempotent():
    candidate = pr()
    assert UBP.decide(candidate, None)["action"] == "need-checks", (
        "浅判据全过 ⇒ 必须先取 required 读数，不许直接动作")
    once = UBP.decide(candidate, GREEN_ROWS)
    twice = UBP.decide(candidate, GREEN_ROWS)
    assert once == twice == {"action": "update-branch", "reason": once["reason"]}, once


@pytest.mark.parametrize("kwargs,needle", [
    (dict(author="app/dependabot"), "dependabot"),          # 交给 #8845，两条腿互斥
    (dict(author="dependabot[bot]"), "dependabot"),
    (dict(armed=False), "未 arm"),
    (dict(draft=True), "draft"),
    (dict(labels=("block/merge",)), "block/merge"),
    (dict(cross=True), "fork"),
    (dict(base="release/1"), "base"),
    (dict(state="CLEAN"), "CLEAN"),
    (dict(state="UNKNOWN"), "UNKNOWN"),                     # #5113：可合并性尚在计算
    (dict(state="DIRTY"), "DIRTY"),                          # 冲突：update-branch 必 422
    (dict(state="BLOCKED"), "BLOCKED"),
])
def test_decide_skips_everything_that_is_not_a_candidate(kwargs, needle):
    verdict = UBP.decide(pr(**kwargs), GREEN_ROWS)
    assert verdict["action"] == "skip", verdict
    assert needle in verdict["reason"], verdict


@pytest.mark.parametrize("rows", [RED_ROWS, PENDING_ROWS])
def test_decide_never_updates_without_all_required_green(rows):
    verdict = UBP.decide(pr(), rows)
    assert verdict["action"] == "skip", verdict
    assert "不动作" in verdict["reason"], verdict


def test_decide_reports_unreadable_required_as_unjudgeable():
    verdict = UBP.decide(pr(), [])
    assert verdict["action"] == "unjudgeable", (
        "required 读不到 ⇒ 必须按「未判定」出声，**不许**当绿放行：%r" % (verdict,))


def test_classify_update_failure_has_three_buckets():
    assert UBP.classify_update_failure(1, "failed to update branch: merge conflict between base "
                                          "and head")[0] == "needs-human"
    assert UBP.classify_update_failure(1, "GraphQL: HTTP 422")[0] == "needs-human"
    assert UBP.classify_update_failure(1, "failed to update branch: branch is up to date")[0] == "benign"
    assert UBP.classify_update_failure(1, "error: HTTP 500 boom")[0] == "mechanism"


def test_dependabot_logins_stay_in_sync_with_the_rebase_leg():
    """互斥判据的**类级**守卫：两条腿的 bot 身份集合必须一致。

    不一致 ⇒ 要么同一 PR 被两条腿同时命中（npm lock 再坏一次），要么两边都不管（静默悬空）。
    """
    leg = _load(REBASE_LEG, "dependabot_rebase_sweep")
    assert tuple(UBP.DEPENDABOT_LOGINS) == tuple(leg.BOT_LOGINS), (
        "scripts/update_behind_prs.py::DEPENDABOT_LOGINS 与 "
        "scripts/dependabot_rebase_sweep.py::BOT_LOGINS 漂移了 ⇒ #8850 与 #8845 的互斥判据失效")


# ══════════════════════════════════════════════════════════════════════════════
# 二、端到端（gh 替身）：选人条件 / 恰好一次 / 三类失败 / 三态退出码
# ══════════════════════════════════════════════════════════════════════════════
def test_behind_armed_and_green_updates_exactly_once(tmp_path):
    """🔴 本单的**核心行为**：BEHIND + 已 arm + required 全绿 ⇒ 恰好一次 update-branch。"""
    out = run_script(tmp_path, prs=[pr()], checks={"8846": GREEN_ROWS})
    assert out.rc == 0, out.out
    assert out.calls == ["8846"], "必须**恰好一次** update-branch（有界：不重试、不循环）：%r" % (out.calls,)
    assert "已 update-branch" in out.out and "#8846" in out.out, out.out
    assert "动作 1" in out.summary, out.summary


def test_up_to_date_success_is_reported_as_noop(tmp_path):
    """现取读数（2026-11-09 本机）：分支未落后时 `gh pr update-branch` **rc=0** 且打印
    `✓ PR branch already up-to-date` ⇒ 读数必须与事实一致（「我做了」≠「别人已做」）。"""
    out = run_script(tmp_path, prs=[pr()], checks={"8846": GREEN_ROWS},
                     update_note={"8846": "✓ PR branch already up-to-date"})
    assert out.rc == 0, out.out
    assert out.calls == ["8846"], out.calls
    assert "已 update-branch" not in out.out, out.out
    assert "已不落后" in out.out, out.out


def test_dependabot_pr_is_left_to_the_rebase_leg(tmp_path):
    """bot 归 #8845：本脚本**一次都不许**对它动作（否则两条腿同时命中 ⇒ lock 再坏）。"""
    out = run_script(tmp_path, prs=[pr(number=8830, author="app/dependabot")],
                     checks={"8830": GREEN_ROWS})
    assert out.rc == 0, out.out
    assert out.calls == [], "dependabot 的 PR 不许被本腿 update-branch：%r" % (out.calls,)
    assert "dependabot" in out.out and "#8845" in out.out, out.out


def test_unarmed_pr_is_not_touched(tmp_path):
    out = run_script(tmp_path, prs=[pr(armed=False)], checks={"8846": GREEN_ROWS})
    assert out.rc == 0, out.out
    assert out.calls == [], "未 arm 归 #5235 的 arm 腿：%r" % (out.calls,)
    assert "未 arm" in out.out, out.out


def test_non_behind_pr_is_not_touched_and_costs_no_api_call(tmp_path):
    """`CLEAN` ⇒ 不动作**且不白读**：桩里根本没给该 PR 的 checks，一旦去读就会退 3。"""
    out = run_script(tmp_path, prs=[pr(state="CLEAN")], checks={})
    assert out.rc == 0, "非 BEHIND 不许产生任何「未判定」：%s" % out.out
    assert out.calls == [], out.calls


@pytest.mark.parametrize("rows,label", [(RED_ROWS, "判红"), (PENDING_ROWS, "未全部终态 SUCCESS")])
def test_required_not_green_does_not_update(tmp_path, rows, label):
    out = run_script(tmp_path, prs=[pr()], checks={"8846": rows})
    assert out.rc == 0, out.out
    assert out.calls == [], "required 非全绿时不许 update（白跑一轮 CI）：%r" % (out.calls,)
    assert label in out.out, out.out


def test_required_unreadable_is_exit_3_not_0(tmp_path):
    """🔴 读不到 required ⇒ `3` + 出声（**不当 0 读**、也不许默认放行）。"""
    out = run_script(tmp_path, prs=[pr()], checks={})
    assert out.rc == 3, "required 读不到却被报成 0 = 把「量不出来」当「可以」：rc=%d\n%s" % (out.rc, out.out)
    assert out.has_warning() and "未判定" in out.out, out.out
    assert not out.has_error(), "「判不了」不是机制故障，不该渲染成 ::error::：\n%s" % out.out
    assert out.calls == [], out.calls


def test_conflict_is_named_warning_and_does_not_red_the_job(tmp_path):
    """冲突 / 422 ⇒ 停手 + **具名** warning，`rc=3`（不当 0 读），且**不重试**。"""
    out = run_script(tmp_path, prs=[pr()], checks={"8846": GREEN_ROWS},
                     update_fail={"8846": {"rc": 1, "stderr":
                                           "failed to update branch: merge conflict between base "
                                           "and head"}})
    assert out.rc == 3, "冲突/422 必须退 3（不是 0、也不是机制失败 1）：rc=%d\n%s" % (out.rc, out.out)
    assert out.has_warning() and "需要人工" in out.out, out.out
    assert "#8846" in out.out, "warning 必须**具名**（点名哪个 PR 需要人工）：\n%s" % out.out
    assert not out.has_error(), "冲突不许把整个 job 判红（那是「需人工」不是「机制坏了」）：\n%s" % out.out
    assert out.calls == ["8846"], "冲突不许重试（每 PR 每轮最多一次）：%r" % (out.calls,)


def test_mechanism_failure_is_named_error_and_exit_1(tmp_path):
    out = run_script(tmp_path, prs=[pr()], checks={"8846": GREEN_ROWS},
                     update_fail={"8846": {"rc": 1, "stderr": "error: HTTP 500 boom"}})
    assert out.rc == 1, "机制自身失败必须非零退出（可见）：rc=%d\n%s" % (out.rc, out.out)
    assert out.has_error() and "机制失败" in out.out, out.out


def test_unreadable_pr_list_is_exit_1_not_zero(tmp_path):
    """🔴 取数失败 ⇒ `1`（比 3 更强的「机制没跑成」，绝不当 0 读）。"""
    out = run_script(tmp_path, prs=[pr()], checks={}, list_fail=True)
    assert out.rc == 1, "取不到 open PR 列表却报 0 = 把「没跑成」装成「没问题」：rc=%d\n%s" % (out.rc, out.out)
    assert out.has_error(), out.out


def test_second_run_after_update_branch_is_a_noop(tmp_path):
    """第二轮（GitHub 已把 head 拉平 ⇒ 不再 BEHIND）⇒ **0 次**调用（有界性的另一半）。"""
    first = run_script(tmp_path, prs=[pr()], checks={"8846": GREEN_ROWS})
    assert first.calls == ["8846"], first.out
    state = first.state
    state["prs"][0]["mergeStateStatus"] = "MERGEABLE"   # update-branch 之后 GitHub 的重算读数
    second = run_script(tmp_path, state=state)
    assert second.calls == ["8846"], "第二轮不许再调 update-branch（天然有界）：%r" % (second.calls,)
    assert second.rc == 0, second.out


def test_default_is_read_only(tmp_path):
    """脚本默认**只读**（本地复跑不会真的动 PR）；写要显式 `--apply`。"""
    out = run_script(tmp_path, prs=[pr()], checks={"8846": GREEN_ROWS}, extra_args=())
    assert out.rc == 0, out.out
    assert out.calls == [], "没给 --apply 时一个动作都不许有：%r" % (out.calls,)
    assert "将 update-branch" in out.out and "只读" in out.out, out.out


def test_apply_and_dry_run_are_mutually_exclusive(tmp_path):
    out = run_script(tmp_path, prs=[pr()], checks={"8846": GREEN_ROWS},
                     extra_args=("--apply", "--dry-run"))
    assert out.rc == 1 and out.has_error(), out.out
    assert out.calls == [], out.calls


def test_is_cross_repository_fork_is_skipped(tmp_path):
    out = run_script(tmp_path, prs=[pr(cross=True)], checks={"8846": GREEN_ROWS})
    assert out.rc == 0 and out.calls == [], out.out


# ══════════════════════════════════════════════════════════════════════════════
# 三、宿主 workflow 接线（宿主 = automerge.yml；本 job 只在定时/手动档上跑）
# ══════════════════════════════════════════════════════════════════════════════
def job_wiring_problems(doc):
    """纯函数：新 job 接线的问题清单（空 = 合规）。注入式红证与真值断言共用同一口径。"""
    problems = []
    triggers = doc.get("on") or doc.get(True) or {}
    crons = [str(entry.get("cron")) for entry in (triggers.get("schedule") or [])
             if isinstance(entry, dict)]
    if crons != ["7 * * * *"]:
        problems.append("宿主 `schedule` 必须**恰好**是既有的 `7 * * * *`（本单不新增 cron）：%r"
                        % (crons,))
    job = (doc.get("jobs") or {}).get(JOB)
    if not isinstance(job, dict):
        return problems + ["缺 job `%s`" % JOB]
    cond = " ".join(str(job.get("if") or "").split())
    if "schedule" not in cond or "workflow_dispatch" not in cond:
        problems.append("job 的 `if:` 必须限定在 schedule/workflow_dispatch（BEHIND 不产生事件）：%r"
                        % cond)
    if "pull_request" in cond:
        problems.append("job 的 `if:` 不许挂 pull_request_target 面（否则每个 PR 都多一条无关动作）：%r"
                        % cond)
    perms = job.get("permissions")
    if not isinstance(perms, dict):
        problems.append("job 权限必须是显式映射：%r" % (perms,))
        perms = {}
    if perms.get("pull-requests") != "write":
        problems.append("缺 pull-requests: write（读 required / update-branch 都需要它）")
    if perms.get("contents") != "write":
        problems.append("缺 contents: write —— 内置 token 是 **GitHub App** 凭据，官方文档对 "
                        "update-branch 明确要求「also have permissions to write the contents of the "
                        "head repository」⇒ 只给 pull-requests 会 403")
    if perms.get("actions") == "write" or perms.get("issues") == "write":
        problems.append("权限面超出需要（本 job 只动 PR 分支，不碰 actions/issues）：%r" % (perms,))
    steps = job.get("steps") or []
    run = "\n".join(str(step.get("run") or "") for step in steps)
    if "scripts/update_behind_prs.py" not in run:
        problems.append("没有任何 step 跑 scripts/update_behind_prs.py")
    if "--apply" not in run:
        problems.append("调脚本时没传 --apply（脚本默认只读 ⇒ 该 job 会静默空转）")
    if ".github/scripts/mechanism_liveness.sh emit automerge" not in run:
        problems.append("缺存活读数（机制兜底失败不可见，issue #5326）")
    if "发射器不在检出里" not in run:
        problems.append("缺「发射器不在检出里」的降级 warning（读数缺失不得静默）")
    if "secrets." in json.dumps(job, ensure_ascii=False):
        problems.append("job 里不许出现 secrets.* 引用（Danger Scan 对新增凭据引用判红）")
    if not any(str(step.get("uses") or "").startswith("actions/checkout") for step in steps):
        problems.append("缺 actions/checkout（gh 没有 git 上下文会 `failed to run git`，issue #2929）")
    if job.get("needs"):
        problems.append("本 job 必须独立（不 `needs:` 其它 job）：%r" % (job.get("needs"),))
    return problems


def dangling_last_step_problems(doc):
    """`detect-dangling-prs` 的**最后一步**必须仍是跑判据脚本那一步（本单不改它）。"""
    job = (doc.get("jobs") or {}).get(DANGLING_JOB) or {}
    steps = job.get("steps") or []
    if not steps:
        return ["缺 job `%s`" % DANGLING_JOB]
    last = steps[-1]
    problems = []
    if "dangling_pr_scan.py" not in str(last.get("run") or ""):
        problems.append("`%s` 的最后一步必须仍是跑 `scripts/dangling_pr_scan.py` 的那一步 —— 给它加一步会让"
                        "既有红证 test_dangling_pr_scan.py::test_host_workflow_wiring_guard_is_not_vacuous "
                        "变成空断言" % DANGLING_JOB)
    if "always()" not in str(last.get("if") or ""):
        problems.append("`%s` 的最后一步必须带 `if: always()`（存活读数的口径）" % DANGLING_JOB)
    return problems


def _workflow_doc():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_host_workflow_wiring_is_clean():
    assert SCRIPT.is_file(), "缺判据脚本 scripts/update_behind_prs.py"
    assert job_wiring_problems(_workflow_doc()) == []
    assert dangling_last_step_problems(_workflow_doc()) == []


def test_host_workflow_wiring_guard_is_not_vacuous():
    """注入式红证：每处各改一处 ⇒ 对应判据必须变红（证明它不恒真）。"""
    base = _workflow_doc()
    assert job_wiring_problems(base) == [], "先决条件：未变异的真文件必须合规"
    mutations = [
        ("去掉 schedule 入口", lambda d: d["jobs"][JOB].__setitem__("if", "true")),
        ("挂上 PR 事件面",
         lambda d: d["jobs"][JOB].__setitem__(
             "if", "github.event_name == 'workflow_dispatch' || github.event_name == 'pull_request_target'")),
        ("update-branch 权限降成 read",
         lambda d: d["jobs"][JOB]["permissions"].__setitem__("pull-requests", "read")),
        ("contents 降成 read",
         lambda d: d["jobs"][JOB]["permissions"].__setitem__("contents", "read")),
        ("步骤不跑脚本", lambda d: d["jobs"][JOB]["steps"][-1].__setitem__("run", "echo noop")),
        ("不传 --apply",
         lambda d: d["jobs"][JOB]["steps"][-1].__setitem__(
             "run", str(d["jobs"][JOB]["steps"][-1]["run"]).replace("--apply", ""))),
        ("摘掉存活读数",
         lambda d: d["jobs"][JOB]["steps"][-1].__setitem__(
             "run", "\n".join(line for line in
                              str(d["jobs"][JOB]["steps"][-1]["run"]).splitlines()
                              if "mechanism_liveness.sh emit" not in line
                              and "发射器不在检出里" not in line))),
        ("新增一条 cron",
         lambda d: (d.get("on") or d.get(True))["schedule"].append({"cron": "*/15 * * * *"})),
        ("加 needs 绑到别的 job",
         lambda d: d["jobs"][JOB].__setitem__("needs", "detect-dangling-prs")),
    ]
    for label, mutate in mutations:
        doc = copy.deepcopy(base)
        mutate(doc)
        assert job_wiring_problems(doc), "注入「%s」后仍判绿 ⇒ 该判据是空断言" % label


def test_dangling_scan_job_keeps_its_last_step():
    """负向钉住：**本包一个字都不许动** `detect-dangling-prs`（加一步就毁掉它的红证）。"""
    base = _workflow_doc()
    assert dangling_last_step_problems(base) == [], "先决条件：真文件的最后一步必须仍是判据脚本"
    for label, mutate in [
        ("在判据步之后加一步", lambda d: d["jobs"][DANGLING_JOB]["steps"].append({"run": "echo extra"})),
        ("删掉判据步", lambda d: d["jobs"][DANGLING_JOB].__setitem__("steps",
                                                                  d["jobs"][DANGLING_JOB]["steps"][:1])),
        ("摘掉 always()", lambda d: d["jobs"][DANGLING_JOB]["steps"][-1].pop("if")),
    ]:
        doc = copy.deepcopy(base)
        mutate(doc)
        assert dangling_last_step_problems(doc), "注入「%s」后仍判绿 ⇒ 判据是空断言" % label
    # 新 job 与它**互不缠绕**：各跑各的步骤、不共享 run 块
    new_run = "\n".join(str(step.get("run") or "") for step in base["jobs"][JOB]["steps"])
    assert "dangling_pr_scan.py" not in new_run, "新 job 不许复用悬空扫描脚本（职责不同）"


def test_workflow_does_not_grow_a_second_cron():
    """铁律 10：不新增 cron —— 本文件的周期面仍**恰好**一条（既有的 `7 * * * *`）。"""
    triggers = _workflow_doc().get("on") or _workflow_doc().get(True) or {}
    crons = [entry.get("cron") for entry in triggers.get("schedule") or []]
    assert crons == ["7 * * * *"], crons


# ══════════════════════════════════════════════════════════════════════════════
# 四、脚本自身的写面边界（不许抢合并 / 抢写 / 无界重试）
# ══════════════════════════════════════════════════════════════════════════════
def test_script_never_merges_or_pushes():
    """只认**真会被执行的 argv 形态**（散文里写「不 `gh pr merge`」不算越界，锚点也不该被文案喂绿）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ('"pr", "merge"', '"push"', '"git"', "--force", "reset --hard"):
        assert forbidden not in src, (
            "%r 越过本单半径：合并只能由 GitHub 的 native auto-merge 在 required 全绿后完成" % forbidden)


def test_script_has_no_retry_loop():
    """有界性：动作靠「只在 BEHIND 时才做（update-branch 会改 head sha）」有界，不靠重试。"""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "while " not in src, "不许出现重试/轮询循环（有界性来自「只在 BEHIND 才动作」）"
    assert src.count('"pr", "update-branch"') == 1, "update-branch 动作本体只许有一处实现"


# ══════════════════════════════════════════════════════════════════════════════
# 五、注入式红证：证明上面那些判据**会红**（且注入确实生效 —— 读回内容 + 哈希）
# ══════════════════════════════════════════════════════════════════════════════
def _mutant(tmp_path, anchor, replacement):
    """把真脚本变异成副本，并**自证注入落盘生效**（读回逐字 + 哈希都变了）。"""
    from unit_ci_workflows.injection import inject

    src = SCRIPT.read_text(encoding="utf-8")
    mutated = inject(src, anchor, replacement, where="scripts/update_behind_prs.py")
    path = tmp_path / "mutant_update_behind_prs.py"
    path.write_text(mutated, encoding="utf-8")
    read_back = path.read_text(encoding="utf-8")
    assert read_back == mutated, "注入后的副本与内存里的变异体不一致（写盘被截断？）"
    assert anchor not in read_back, "注入后锚点仍在 ⇒ 注入**没生效**（这条红证不成立）"
    assert hashlib.sha256(read_back.encode()).hexdigest() != hashlib.sha256(src.encode()).hexdigest(), \
        "变异体与原文哈希相同 ⇒ 注入是空操作"
    return path


def test_red_proof_dependabot_exclusion_has_teeth(tmp_path):
    """红证 ①：摘掉 dependabot 排除 ⇒ bot PR 会被本腿 update-branch（= 与 #8845 两条腿同时命中）。"""
    mutant = _mutant(tmp_path, "    if author in DEPENDABOT_LOGINS:",
                     "    if False:  # 注入：摘掉 dependabot 排除")
    out = run_script(tmp_path / "run", prs=[pr(number=8830, author="app/dependabot")],
                     checks={"8830": GREEN_ROWS}, script=mutant)
    assert out.calls == ["8830"], (
        "摘掉 dependabot 排除后 bot PR 仍未被动作 ⇒ 上面那条「bot 归 #8845」的判据没有判别力：\n%s"
        % out.out)


def test_red_proof_behind_gate_has_teeth(tmp_path):
    """红证 ②：摘掉「只在 BEHIND 才动作」⇒ `CLEAN` 的 PR 也会被 update-branch（无意义动作 + CI 轮次）。"""
    mutant = _mutant(tmp_path, "    if state != BEHIND:", "    if False:  # 注入：摘掉 BEHIND 闸")
    out = run_script(tmp_path / "run", prs=[pr(state="CLEAN")], checks={"8846": GREEN_ROWS},
                     script=mutant)
    assert out.calls == ["8846"], (
        "摘掉 BEHIND 闸后 `CLEAN` 的 PR 仍未被动作 ⇒ 上面那条「非 BEHIND 不动作」的判据没有判别力：\n%s"
        % out.out)


def test_red_proof_required_green_gate_has_teeth(tmp_path):
    """红证 ③：摘掉「required 全绿才动手」⇒ 红着也被 update（白跑一轮 CI，`pr-merge-when-clean.sh` ①）。"""
    mutant = _mutant(tmp_path, '    if kind != "green":',
                     "    if False:  # 注入：摘掉 required 全绿闸")
    out = run_script(tmp_path / "run", prs=[pr()], checks={"8846": RED_ROWS}, script=mutant)
    assert out.calls == ["8846"], (
        "摘掉 required 全绿闸后红 PR 仍未被动作 ⇒ 上面那条「非全绿不动作」的判据没有判别力：\n%s"
        % out.out)


def test_red_proof_self_verification_catches_a_drifted_anchor(tmp_path):
    """元判据：锚点漂了必须**当场报错**（否则红证会静默变成空操作 —— #7017 的形态）。"""
    from unit_ci_workflows.injection import AnchorDrift

    with pytest.raises(AnchorDrift):
        _mutant(tmp_path, "    if author in DEPENDABOT_LOGINS_BUT_THIS_ANCHOR_DRIFTED:",
                "    if False:")
