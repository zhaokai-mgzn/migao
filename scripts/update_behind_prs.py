#!/usr/bin/env python3
"""全绿 + 已 arm + `mergeStateStatus=BEHIND` ⇒ 永不合并的收口（issue #8850）。

## 病（2026-11-09 09:13~09:27 +08 现取，逐字见 issue #8850）

一条 PR **28 条检查全 pass、`autoMergeRequest` 已 arm**，却长期停在 `BEHIND`、永不合并：

    09:13  #8846 全绿 + armed，仍 BEHIND（main 在 CI 跑的 12 分钟里前进了 #8829）
    09:26  gh pr update-branch 8846 ⇒ 全绿 ⇒ 又被推进（#8827 合入）⇒ 再 BEHIND
    09:27  第三次 update-branch 才合

根因是**三处都指向同一个空位**（现取）：
1. 分支保护 `strict: true`（合并瞬间必须与 main 同版本）+ 仓库 `allow_update_branch=false`
   ⇒ PR 页面**没有** "Update branch" 按钮，GitHub 也不会自动更新；
2. 仓内没有任何 workflow 跑 `gh pr update-branch`（只有人跑的 `scripts/pr-merge-when-clean.sh`）；
3. 兜底扫描 `scripts/dangling_pr_scan.py` **明确排除 `BEHIND`** —— 它的注释理由是
   「`BEHIND` 在 PR 页面上有显式可行动横幅」，而本仓把那个横幅关掉了 ⇒ **两处都不管**。

⇒ main 每动一次，所有在飞 PR 一起 `BEHIND`；谁都不能自动合，只能等人手工 update。

## 判据（每条都对应一个真实读数或一个**假红/漏报**形态）

1. **只治「已 arm 却合不了」**：`autoMergeRequest == null` 不碰（未 arm 是 arm 腿的事，issue #5235）。
2. **只治 `mergeStateStatus == BEHIND`**：缺失 / `UNKNOWN`（GitHub 尚在计算，issue #5113 口径）/
   `DIRTY`（冲突，update-branch 必 422）/ `BLOCKED`（required 未达标）/ `CLEAN` 一律不动作
   —— 这条也是**有界性**的来源：动作只发生在 `BEHIND` 上。
3. **required 必须全绿**（唯一读数面 = `gh pr checks <n> --required`，与 `scripts/merge_gate.py`
   的 `WAIT_GREEN_STATES` 同口径：只认终态 `SUCCESS`）：
   · 读不到 / 清单为空 ⇒ **`3`（跳过 + 出声）** —— 「空集合 ≠ 绿」，也不把「量不出来」读成「可以」；
   · 红 / 未跑完 ⇒ **不动作**（带着红 update 会白跑一轮 CI，顺序口径见 `pr-merge-when-clean.sh` ①）。
4. **dependabot 作者不碰**：交给 issue #8845 的 rebase 腿。`gh pr update-branch` 会把 main 合进来，
   对有 npm lock 的分支**正会**产出坏 lock（#7688 的形态）⇒ 两条腿**不许**同时命中同一 PR。
5. **动作只有一条**：`gh pr update-branch <n>`，**每个 PR 每轮最多一次、不重试、不循环**
   （update-branch 会改 head sha ⇒ 本轮之后它不再是 `BEHIND`，天然有界）。失败分三类：
   · 已不落后（幂等，通常由别的路径做完了）⇒ 跳过；
   · 冲突 / 422 ⇒ **需要人工**（`3`，具名 `::warning::`，**不**把整个 job 判红）；
   · 其余（权限 / 网络 / gh 报错）⇒ **机制自身失败**（`1`，具名 `::error::`）。
6. 其余护栏与 arm 腿同口径：`base=main`、`not draft`、同仓（fork 除外）、`block/merge` 跳过。

## 三态退出码（`3` **不得**当 `0` 读）

| 码 | 含义 |
|---|---|
| `0` | 无需动作，或动作全部成功 |
| `1` | **机制自身失败**（取不到 open PR 列表 / 权限 / gh 报错）—— 必须可见（job 判红） |
| `3` | **有 PR 需要人工**（update-branch 冲突 / 422）**或判不了**（required 读不到）—— 不当 0 读 |

## 边界（照实登记，§19.1）

- **默认只读**：不带 `--apply` 时一个字节都不写（只打印「将 update-branch」）；workflow 里显式传
  `--apply`。`--dry-run` 是同一件事的显式写法（二者互斥）。
- **只做第一步**：**不** `gh pr merge`、**不** `git push`、**不**改任何门禁语义（合并仍由 GitHub 的
  native auto-merge 在 required 全绿后完成）。
- 定时档 = `.github/workflows/automerge.yml` **既有**的 `cron: '7 * * * *'`（**不新增 cron**，
  铁律 10）；GitHub 对本仓节流到数小时级 ⇒ 它是**兜底**，不是实时。
- 只治理「人/agent 写的 PR」这一族；dependabot 的落后 / 坏 lock 由 #8845 承接（射程边界，不是缺陷）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_NEEDS_HUMAN = 3

#: 唯一需要动手的合并状态（GitHub 的 `mergeStateStatus`）：head 落后于 base。
BEHIND = "BEHIND"
#: 「人工闸」标签：打上即**有意不可合**（与 `automerge.yml` 的 arm `if:` 同口径）。
BLOCK_LABEL = "block/merge"
#: dependabot 在 GitHub 上的三种身份写法 —— **必须**与 `scripts/dependabot_rebase_sweep.py::BOT_LOGINS`
#: 同值（互斥判据：bot 走 rebase 腿、非 bot 走本脚本）。判据 =
#: `tests/unit_ci_workflows/test_update_behind_prs.py::test_dependabot_logins_stay_in_sync_with_the_rebase_leg`。
DEPENDABOT_LOGINS = ("app/dependabot", "dependabot[bot]", "dependabot")
#: required「绿」的**唯一**口径（同 `scripts/merge_gate.py::WAIT_GREEN_STATES`：只认终态 SUCCESS；
#: `SKIPPED` / `NEUTRAL` 等**终态非 SUCCESS** 一律不算 —— 宁可不动手，也不假绿）。
GREEN_STATES = ("SUCCESS",)
#: `gh pr checks --json` 的判红 bucket（`cancel` 与 `fail` 同处置，同 `merge_gate.RED_BUCKETS`）。
RED_BUCKETS = ("fail", "cancel")
#: update-branch 的**幂等**返回：分支已不落后（通常由人工/别的路径做完了）⇒ 跳过、不是失败。
UP_TO_DATE_MARKERS = ("up to date", "up-to-date", "already updated", "not behind")
#: 冲突 / 422 ⇒ **需要人工**（不是机制故障：本条不许重试，也不许把 job 判红）。
NEEDS_HUMAN_MARKERS = ("conflict", "422", "not mergeable", "unprocessable",
                       "cannot be updated", "can't be updated")

#: `gh pr list` 的取数面（选人条件所需的**全部**字段，一次取回）。
PR_FIELDS = ("number,title,author,isDraft,baseRefName,isCrossRepository,"
             "labels,autoMergeRequest,mergeStateStatus")


class GhError(RuntimeError):
    """`gh` 取数失败 / 输出不可解析（机制自身失败，或该 PR 的 required 面**判不了**）。"""


# ── gh 调用（测试注入点 = **CLI 边界**：`UPDATE_BEHIND_GH_BIN`，
#    沿用 `DANGLING_GH_BIN` / `MG_GH_BIN` / `AUTOMERGE_GH_BIN` 的既有先例）──────────────
def gh_bin():
    return os.environ.get("UPDATE_BEHIND_GH_BIN") or "gh"


def _run(args):
    try:
        return subprocess.run([gh_bin(), *args], capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:  # gh 不存在 / 卡死
        raise GhError("无法执行 %s：%s" % (gh_bin(), exc)) from exc


def _json(args):
    proc = _run(args)
    if proc.returncode != 0:
        raise GhError("gh %s ⇒ rc=%d：%s" % (" ".join(args[:2]), proc.returncode,
                                             (proc.stderr or proc.stdout).strip()[:300]))
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError as exc:
        raise GhError("gh %s 输出不是 JSON：%s" % (" ".join(args[:2]), exc)) from exc


def login_of(value):
    """`gh` 的 author 字段有时是 `{"login": …}`、有时是裸字符串 ⇒ 统一取登录名。"""
    if isinstance(value, dict):
        return value.get("login") or ""
    return value or ""


def labels_of(pr):
    return [str(item.get("name")) for item in (pr.get("labels") or []) if isinstance(item, dict)]


def list_open_prs(repo, limit):
    """`base=main` 的 open PR —— 选人条件的**唯一**取数入口（取不到 ⇒ 机制失败）。"""
    args = ["pr", "list", "--state", "open", "--base", "main", "--limit", str(limit),
            "--json", PR_FIELDS]
    if repo:
        args += ["--repo", repo]
    payload = _json(args)
    if not isinstance(payload, list):
        raise GhError("gh pr list 输出不是列表（%r）" % (type(payload).__name__,))
    return [item for item in payload if isinstance(item, dict)]


def read_required_checks(repo, number):
    """required 检查的**唯一**读数面：`gh pr checks <n> --required`。

    ⚠️ **退出码不可作判据**：有红 / 待跑时 `gh pr checks` 同样非 0（1 / 8）——
    判据 = 「stdout 能解析成列表」。取不到（gh 报错 / 输出不是 JSON）⇒ 抛 `GhError`
    （调用方按「未判定」处置：**不得**当「全绿」）。
    """
    args = ["pr", "checks", str(number), "--required", "--json", "name,state,bucket"]
    if repo:
        args += ["--repo", repo]
    proc = _run(args)
    try:
        rows = json.loads(proc.stdout or "")
    except json.JSONDecodeError as exc:
        raise GhError("`gh pr checks %s --required` 未返回可解析 JSON（rc=%d）：%s"
                      % (number, proc.returncode,
                         (proc.stderr or proc.stdout).strip()[:300])) from exc
    if not isinstance(rows, list):
        raise GhError("`gh pr checks %s --required` 输出不是列表（rc=%d）"
                      % (number, proc.returncode))
    return [row for row in rows if isinstance(row, dict)]


def required_verdict(rows):
    """required 检查快照 → `(kind, detail)`，`kind ∈ {green, red, not-green, unreadable}`。

    **空清单 = unreadable**（「空集合 ≠ 绿」，同 `merge_gate.judge_wait_snapshot`）：
    本仓分支保护现取 16 条 required，读到 0 条只可能是**读数坏了**。
    """
    if not rows:
        return "unreadable", "required 清单为空（空集合 ≠ 绿）：`gh pr checks --required` 可能不可用 / 无权限"
    red, not_green = [], []
    for row in rows:
        name = str(row.get("name") or "?")
        if str(row.get("bucket") or "").lower() in RED_BUCKETS:
            red.append(name)
        elif str(row.get("state") or "").upper() not in GREEN_STATES:
            not_green.append("%s[%s]" % (name, str(row.get("state") or "?")))
    if red:
        return "red", "required 判红 %d 条：%s" % (len(red), "、".join(red[:5]))
    if not_green:
        return "not-green", "required 未全部终态 SUCCESS：%s" % "、".join(not_green[:5])
    return "green", "required %d 条**全部终态 SUCCESS**" % len(rows)


def decide(pr, checks=None):
    """纯判定 → `{"action": …, "reason": …}`，`action ∈ {skip, need-checks, unjudgeable, update-branch}`。

    `checks=None` = required 面**尚未取**：浅判据已过（候选）⇒ 返回 `need-checks`，调用方取回
    真读数后用**同一函数**再判一次（幂等，同 `dangling_pr_scan.judge` 的两段式）。
    """
    author = login_of(pr.get("author"))
    if pr.get("isCrossRepository"):
        return {"action": "skip", "reason": "head 仓库不是本仓（fork PR，token 权限面不覆盖）"}
    if author in DEPENDABOT_LOGINS:
        return {"action": "skip",
                "reason": "dependabot 作者（%s）—— 交给 #8845 的 rebase 腿：两条腿**不许**同时命中同一 PR"
                          % (author or "<空>")}
    if pr.get("isDraft"):
        return {"action": "skip", "reason": "draft（有意不可合）"}
    base = str(pr.get("baseRefName") or "main")
    if base != "main":
        return {"action": "skip", "reason": "base 不是 main（%s）" % base}
    labels = labels_of(pr)
    if BLOCK_LABEL in labels:
        return {"action": "skip", "reason": "带 %s 标签（人工闸）" % BLOCK_LABEL}
    if not pr.get("autoMergeRequest"):
        return {"action": "skip",
                "reason": "auto-merge **未 arm**（本脚本只治「已 arm 却永不合并」，未 arm 归 #5235 的 arm 腿）"}
    state = str(pr.get("mergeStateStatus") or "").upper()
    if state != BEHIND:
        return {"action": "skip",
                "reason": "mergeStateStatus=%s（不是 BEHIND ⇒ 不需要 update-branch：UNKNOWN=尚在计算 / "
                          "DIRTY=冲突 / BLOCKED=required 未达标 / CLEAN=可合）" % (state or "<空>")}
    if checks is None:
        return {"action": "need-checks", "reason": "BEHIND + 已 arm ⇒ 需读 required 检查再判"}
    kind, detail = required_verdict(checks)
    if kind == "unreadable":
        return {"action": "unjudgeable", "reason": detail}
    if kind != "green":
        return {"action": "skip", "reason": "%s ⇒ 本轮不动作（带着非绿 update 会白跑一轮 CI）" % detail}
    return {"action": "update-branch", "reason": "BEHIND + 已 arm + %s" % detail}


def classify_update_failure(rc, text):
    """update-branch 失败的三分类：`(kind, detail)`，`kind ∈ {benign, needs-human, mechanism}`。"""
    low = str(text or "").lower()
    if any(marker in low for marker in UP_TO_DATE_MARKERS):
        return "benign", ("分支已不落后（update-branch 幂等；通常由人工 / 别的路径做完了）：%s"
                          % (text or "").strip()[:200])
    if any(marker in low for marker in NEEDS_HUMAN_MARKERS):
        return "needs-human", ("update-branch 被拒（冲突 / 422）⇒ **该 PR 需要人工**"
                               "（解冲突：`git fetch origin main && git merge origin/main` 后推）：%s"
                               % (text or "").strip()[:300])
    return "mechanism", "update-branch 失败（rc=%s）：%s" % (rc, (text or "").strip()[:300])


def request_update_branch(repo, number):
    """动作本体（每个 PR 每轮**最多一次**，不重试）。返回 `(rc, 输出文本)`。"""
    args = ["pr", "update-branch", str(number)]
    if repo:
        args += ["--repo", repo]
    try:
        proc = subprocess.run([gh_bin(), *args], capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "无法执行 %s：%s" % (gh_bin(), exc)
    return proc.returncode, ((proc.stderr or "") + "\n" + (proc.stdout or ""))


def _write_summary(path, lines):
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError as exc:  # summary 写不进去不得改变判定
        print("::warning::step summary 写入失败（判定不受影响）：%s" % exc)


def _report(actions, skipped, unjudged, needs_human, failed, apply_mode, scanned, summary_path):
    """三态读数 + step summary（**每一类都必须各自可见**，相邻类别不许同形）。"""
    for line in actions:
        print("✅ %s" % line)
    for line in skipped:
        print("⏭️  %s" % line)
    for line in unjudged:
        print("::warning::未判定（**不得当通过**，按 3 读）：%s" % line)
    for line in needs_human:
        print("::warning::需要人工（冲突 / 422 ⇒ 已停手，不重试）：%s" % line)
    for line in failed:
        print("::error::机制失败：%s" % line)
    mode = "写入（--apply）" if apply_mode else "只读（未给 --apply，零动作）"
    if not (actions or skipped or unjudged or needs_human or failed):
        print("::notice::✅ 落后分支收口：扫了 %d 条 open PR（base=main），本轮无需动作" % scanned)
    else:
        print("::notice::落后分支收口（模式=%s）：扫了 %d 条 —— 动作 %d / 跳过 %d / 需人工 %d / "
              "未判定 %d / 机制失败 %d"
              % (mode, scanned, len(actions), len(skipped), len(needs_human), len(unjudged),
                 len(failed)))
    _write_summary(summary_path, [
        "### 🔧 落后分支收口（issue #8850：全绿 + 已 arm + `BEHIND` ⇒ 永不合并）",
        "",
        "- 模式：**%s**" % mode,
        "- 判据：`base=main` ∧ `not draft` ∧ 同仓 ∧ 非 dependabot ∧ `autoMergeRequest != null` ∧ "
        "`mergeStateStatus == BEHIND` ∧ required **全绿** ⇒ `gh pr update-branch`（每 PR 每轮最多一次）",
        "- 扫描 %d 条 / **动作 %d** / 跳过 %d / **需人工 %d** / **未判定 %d** / 机制失败 %d"
        % (scanned, len(actions), len(skipped), len(needs_human), len(unjudged), len(failed)),
        "",
    ] + ["- ✅ %s" % line for line in actions]
      + ["- ⏭️ %s" % line for line in skipped]
      + ["- ⚠️ 需要人工 %s" % line for line in needs_human]
      + ["- ⚠️ 未判定（不得当通过）%s" % line for line in unjudged]
      + ["- ❌ 机制失败 %s" % line for line in failed])


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="全绿 + 已 arm + BEHIND ⇒ gh pr update-branch（issue #8850；默认只读）")
    parser.add_argument("--repo", default=os.environ.get("GH_REPO", ""),
                        help="owner/repo（默认取 GH_REPO）")
    parser.add_argument("--limit", type=int, default=100, help="最多扫多少条 open PR")
    parser.add_argument("--apply", action="store_true", help="真的执行 update-branch（缺省只读）")
    parser.add_argument("--dry-run", action="store_true", help="显式只读（与 --apply 互斥）")
    parser.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY", ""),
                        help="step summary 落点（默认取 GITHUB_STEP_SUMMARY）")
    args = parser.parse_args(argv)

    if args.apply and args.dry_run:
        print("::error::--apply 与 --dry-run 互斥 ⇒ 无法判定要不要写（不当 0 读）")
        return EXIT_FAIL

    try:
        prs = list_open_prs(args.repo, args.limit)
    except GhError as exc:
        print("::error::取 open PR 列表失败 ⇒ 机制无法运行（不当 0 读）：%s" % exc)
        return EXIT_FAIL

    actions, skipped, unjudged, needs_human, failed = [], [], [], [], []
    for pr in prs:
        number = pr.get("number")
        verdict = decide(pr, None)
        if verdict["action"] == "need-checks":
            try:
                checks = read_required_checks(args.repo, number)
            except GhError as exc:
                unjudged.append("#%s required 面读不到 ⇒ **不动作**：%s" % (number, exc))
                continue
            verdict = decide(pr, checks)

        if verdict["action"] == "update-branch":
            headline = "#%s %s" % (number, (pr.get("title") or "")[:60])
            if not args.apply:
                actions.append("%s ⇒ 将 update-branch（%s）" % (headline, verdict["reason"]))
                continue
            rc, text = request_update_branch(args.repo, number)
            if rc == 0:
                if any(marker in text.lower() for marker in UP_TO_DATE_MARKERS):
                    # 现取读数（2026-11-09 本机）：分支未落后时 gh **rc=0** 且打印
                    # `✓ PR branch already up-to-date` ⇒ 「我做了」与「别人已做」必须长得不一样。
                    skipped.append("%s ⇒ 已不落后（GitHub 幂等返回 up-to-date，本轮零改动）" % headline)
                else:
                    actions.append("%s ⇒ 已 update-branch（%s）" % (headline, verdict["reason"]))
                continue
            kind, detail = classify_update_failure(rc, text)
            if kind == "benign":
                skipped.append("%s ⇒ %s" % (headline, detail))
            elif kind == "needs-human":
                needs_human.append("%s —— %s" % (headline, detail))
            else:
                failed.append("%s —— %s" % (headline, detail))
        elif verdict["action"] == "unjudgeable":
            unjudged.append("#%s %s —— %s"
                            % (number, (pr.get("title") or "")[:60], verdict["reason"]))
        else:
            skipped.append("#%s ⇒ %s" % (number, verdict["reason"]))

    _report(actions, skipped, unjudged, needs_human, failed, args.apply, len(prs), args.summary)

    if failed:
        return EXIT_FAIL
    if needs_human or unjudged:
        return EXIT_NEEDS_HUMAN
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
