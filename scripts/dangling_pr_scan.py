#!/usr/bin/env python3
"""悬空 PR 扫描 —— issue #5235「PR 悬空但零信号」的**可见性面**。

## 判据（逐字落码，口径由 issue/用户给定）

> 「一个 open PR 在 N 分钟内**既没变红、也没合入**，且其 required checks **未达可合状态**」
> ⇒ **必须产生一条可见信号**。

两条实测实例（都是本仓真实发生过的形态，见 issue #5235 的评论）：

| 实例 | PR 上的 check | 变红？ | 合得掉？ |
|---|---|---|---|
| 族 A：`Enable auto-merge` 腿失败（#5232 / #5234） | 有（其余全绿） | 不红 | 永不合（没人 arm） |
| 族 B：提交由 `GITHUB_TOKEN` 推（#5139） | **0 条** | 不红 | 永不合（required 永远 pending） |

族 B 的检测器在 `.github/workflows/flaky-ledger-reconcile.yml` 的 §⑤-C（只覆盖台账 PR）；
**本脚本是那一口径的通用面**：扫**全部** `--base main` 的 open PR。

## 判据为什么这样取（每条都对应一个**假红**或**漏报**的实际形态）

1. `draft` / `block/merge` 标签 ⇒ **有意不可合**（人工闸）⇒ 不算悬空（否则每一条草稿都刷红）。
2. 年龄 < N 分钟 ⇒ 还在正常窗口内（CI 本身要跑十几~几十分钟）⇒ 不算悬空。
3. `mergeStateStatus != BLOCKED` ⇒ `CLEAN`/`UNSTABLE` 表示 required 已达可合状态；
   `DIRTY`（真冲突）/`BEHIND`（分支落后）在 PR 页面上有**显式可行动横幅** ⇒ 另有可见信号，不重复报。
   `UNKNOWN` ⇒ GitHub 尚未算完 ⇒ **无法判定**（三态：不得当 0 读，也不得假红）。
4. 任一 check 判红（含 `cancelled` —— 本仓实测它与真红**长得一样**，见 `migao-dev-flow` §17.3）
   ⇒ **已经变红**（可见）⇒ 不重复报。这一条是防假红的关键，也解释了本扫描**不做**的事：
   已红的 PR 该由那些判据自己负责（含 14 条「裸判据」，它们判红是**设计如此**，本脚本不介入其语义）。
5. 有 pending check / 有在跑或排队的 run ⇒ **异步窗口** ⇒ 不许假红。
   ⚠️ 这里必须看 `status`（run 是否在跑）而**不是** `conclusion`：族 B 的 run 全是
   `completed` + `action_required`（**从未执行**，0s）⇒ 它们**不是**"还在跑"，正是要被抓到的形态。

## 三态退出码（与 `scripts/merge_gate.py` 同口径）

| 码 | 含义 |
|---|---|
| `0` | 扫到了、**没有**悬空 PR（脚本自印「扫描 N 条」⇒「扫了 0 条」也看得见） |
| `1` | 扫到了、**有**悬空 PR（逐条 `::error::` + step summary） |
| `3` | **无法判定**（读不到 open PR 列表 / gh 不可用 / 输出不是 JSON）—— **不得当 `0` 读** |

单条 PR 读不到深判所需数据（`gh run list` 失败 / `mergeable` 未算完）⇒ 记 `未判定` 并
`::warning::`，**不**把整轮扫描判红（避免瞬时 API 抖动刷红），但 summary 明写
「未判定 N 条（**不得当通过**）」——「没跑成」必须长得像「没跑成」。

## 注入点

`gh` 走 `DANGLING_GH_BIN` 替身可执行文件（沿用 `scripts/merge_gate.py` 的 `MG_GH_BIN`、
`scripts/resolve_stale_bot_threads.py` 的 `SBT_GH_BIN`、`automerge.yml` 的 `AUTOMERGE_GH_BIN` 先例）：
不 mock 被测逻辑，把 CLI 边界当注入点。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

GH = os.environ.get("DANGLING_GH_BIN") or "gh"

#: 判红（= 「已经变红」，PR 上已有可见信号 ⇒ 不重复报）
RED_CONCLUSIONS = frozenset({"FAILURE", "TIMED_OUT", "STARTUP_FAILURE", "CANCELLED"})
#: 尚未跑完的 check（异步窗口 ⇒ 不判红）
PENDING_CHECK_STATUSES = frozenset({"QUEUED", "IN_PROGRESS", "PENDING", "WAITING", "REQUESTED"})
#: 尚未跑完的 run status（注意：`completed` 才是"跑完了"，哪怕结论是 action_required）
RUNNING_STATUSES = frozenset({"QUEUED", "IN_PROGRESS", "PENDING", "WAITING", "REQUESTED"})
#: 人工闸标签（与 `automerge.yml` 的 `if:` 同一口径）
BLOCK_LABELS = frozenset({"block/merge"})

EXIT_CLEAN = 0
EXIT_DANGLING = 1
EXIT_UNJUDGEABLE = 3


class GhError(RuntimeError):
    """`gh` 调用失败或输出不可解析。"""


def _gh(args):
    try:
        proc = subprocess.run([GH, *args], capture_output=True, text=True, timeout=180)
    except OSError as exc:  # 二进制不存在 / 不可执行
        raise GhError("无法执行 %s：%s" % (GH, exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise GhError("gh %s 超时（180s）" % " ".join(args)) from exc
    if proc.returncode != 0:
        raise GhError("gh %s 返回 %d：%s" % (" ".join(args), proc.returncode,
                                            (proc.stderr or "").strip()[:300]))
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise GhError("gh %s 输出不是 JSON：%s" % (" ".join(args), exc)) from exc


PR_FIELDS = ("number,title,isDraft,createdAt,mergeStateStatus,labels,"
             "autoMergeRequest,headRefOid,statusCheckRollup")


def list_open_prs(repo, limit):
    args = ["pr", "list", "--state", "open", "--base", "main", "--limit", str(limit),
            "--json", PR_FIELDS]
    if repo:
        args += ["--repo", repo]
    return _gh(args)


def head_runs(repo, sha):
    args = ["run", "list", "--commit", sha, "--limit", "100", "--json",
            "status,conclusion,workflowName"]
    if repo:
        args += ["--repo", repo]
    return _gh(args)


def age_minutes(created_at, now):
    """`createdAt`（ISO8601 Z）→ 已 open 的分钟数；不可解析 ⇒ None（三态）。"""
    if not isinstance(created_at, str):
        return None
    try:
        stamp = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (now - stamp).total_seconds() / 60.0


def rollup_split(rollup):
    """PR 的 statusCheckRollup → `(判红的 check 名, 未跑完的 check 名)`。"""
    red, pending = [], []
    for item in rollup or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("context") or "?"
        if item.get("__typename") == "StatusContext":  # 旧式 commit status
            state = (item.get("state") or "").upper()
            if state in ("FAILURE", "ERROR"):
                red.append(name)
            elif state in ("PENDING", "EXPECTED"):
                pending.append(name)
            continue
        if (item.get("conclusion") or "").upper() in RED_CONCLUSIONS:
            red.append(name)
        elif (item.get("status") or "").upper() != "COMPLETED":
            pending.append(name)
    return red, pending


def dangling_reason(pr, runs, age, minutes):
    """悬空的**可行动**读数（写进 `::error::` 与 step summary）。"""
    bits = ["open %.0f 分钟(≥%d)、既未变红也未合入，且 mergeStateStatus=BLOCKED（required 未达可合状态）"
            % (age, minutes)]
    conclusions = [(r.get("conclusion") or "").lower() for r in (runs or [])]
    if not runs:
        bits.append("该 HEAD 上**没有任何 workflow run**（未触发 / 被 `on.pull_request.paths` 过滤掉）"
                    "⇒ 查是否有 required check 永远不会上报")
    elif conclusions and set(conclusions) == {"action_required"}:
        bits.append("该 HEAD 的 %d 条 run 全为 `action_required`（`completed`+0s = **从未执行**）"
                    "⇒ 典型病因：提交由 `GITHUB_TOKEN` 推 ⇒ GitHub 不为它触发 workflow（#5139 族 B）"
                    "⇒ 人工 approve 该 run，或改用非 `GITHUB_TOKEN` 凭据" % len(runs))
    if pr.get("autoMergeRequest"):
        bits.append("auto-merge **已 armed** 却仍卡住 ⇒ 卡在 required 面（未上报的 required check / "
                    "未解决的评审线程，后者见 `scripts/resolve_stale_bot_threads.py`）")
    else:
        bits.append("auto-merge **未 armed** ⇒ 连「required 全绿后自动合」的承诺都没有"
                    "（族 A：`Enable auto-merge` 腿失败且无人重试）")
    number = pr.get("number")
    bits.append("处置：`gh pr checks %s` / `python3 scripts/merge_gate.py --check %s` / "
                "`python3 scripts/resolve_stale_bot_threads.py %s`" % (number, number, number))
    return "；".join(bits)


def judge(pr, runs, now, minutes):
    """纯函数判定：`(verdict, reason)`，`verdict ∈ {ok, need_runs, dangling, unjudged}`。

    `runs=None` ⇒ 尚未取该 HEAD 的 run 列表；若浅判据已通过（候选）则返回 `need_runs`，
    由调用方取回 run 列表后用同一函数**重判一次**（幂等）。
    """
    number = pr.get("number")
    if pr.get("isDraft"):
        return "ok", "draft（有意不可合）"
    labels = {(l or {}).get("name") for l in (pr.get("labels") or []) if isinstance(l, dict)}
    if labels & BLOCK_LABELS:
        return "ok", "带 `%s` 标签（人工闸）" % "`,`".join(sorted(labels & BLOCK_LABELS))
    age = age_minutes(pr.get("createdAt"), now)
    if age is None:
        return "unjudged", "#%s 的 createdAt 不可解析：%r" % (number, pr.get("createdAt"))
    if age < minutes:
        return "ok", "#%s 仅 open %.0f 分钟（< %d）" % (number, age, minutes)
    state = (pr.get("mergeStateStatus") or "").upper()
    if state in ("", "UNKNOWN"):
        return "unjudged", "#%s 的 mergeStateStatus=%r（GitHub 尚未算完 ⇒ 无从判定，非红）" % (
            number, pr.get("mergeStateStatus"))
    if state != "BLOCKED":
        return "ok", "#%s mergeStateStatus=%s（required 已达可合状态，或另有页面级显式信号）" % (
            number, state)
    red, pending = rollup_split(pr.get("statusCheckRollup"))
    if red:
        return "ok", "#%s 已变红（%d 条判红：%s）" % (number, len(red), "、".join(red[:3]))
    if pending:
        return "ok", "#%s 仍在跑（%d 条未跑完：%s）" % (number, len(pending), "、".join(pending[:3]))
    if runs is None:
        return "need_runs", "#%s 浅判据全过 ⇒ 需读该 HEAD 的 run 列表" % number
    running = [r for r in runs
               if (r.get("status") or "").lower() not in ("completed",)]
    if running:
        return "ok", "#%s 仍有 %d 条 run 在跑/排队（%s）" % (
            number, len(running),
            "、".join(sorted({(r.get("workflowName") or "?") for r in running})[:3]))
    return "dangling", dangling_reason(pr, runs, age, minutes)


def _write_summary(path, lines):
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError as exc:  # summary 写不进去不得改变判定
        print("::warning::step summary 写入失败（判定不受影响）：%s" % exc)


def main(argv=None):
    parser = argparse.ArgumentParser(description="悬空 PR 扫描（issue #5235 可见性面）")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""),
                        help="owner/name（默认取 GITHUB_REPOSITORY）")
    parser.add_argument("--minutes", type=float,
                        default=float(os.environ.get("DANGLING_MINUTES", "60")),
                        help="「悬空」的年龄阈值（分钟）；默认 60 —— 远大于本仓 CI 的常规时长")
    parser.add_argument("--limit", type=int, default=100, help="最多扫多少条 open PR")
    parser.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY", ""),
                        help="step summary 落笔位置（默认取 GITHUB_STEP_SUMMARY）")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    try:
        prs = list_open_prs(args.repo, args.limit)
    except GhError as exc:
        print("::error::悬空 PR 扫描**无法判定**（不得当通过）：%s" % exc)
        return EXIT_UNJUDGEABLE

    dangling, unjudged, scanned = [], [], 0
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        scanned += 1
        verdict, reason = judge(pr, None, now, args.minutes)
        if verdict == "need_runs":
            try:
                runs = head_runs(args.repo, pr.get("headRefOid") or "")
            except GhError as exc:
                unjudged.append("#%s 读不到该 HEAD 的 run 列表：%s" % (pr.get("number"), exc))
                continue
            verdict, reason = judge(pr, runs, now, args.minutes)
        if verdict == "dangling":
            dangling.append("#%s %s —— %s" % (pr.get("number"), (pr.get("title") or "")[:60], reason))
        elif verdict == "unjudged":
            unjudged.append(reason)

    for line in dangling:
        print("::error::悬空 PR：%s" % line)
    for line in unjudged:
        print("::warning::未判定（不得当通过）：%s" % line)
    if not dangling:
        print("::notice::✅ 悬空 PR 扫描：扫了 %d 条 open PR（base=main，阈值 %g 分钟），"
              "无「既没变红也没合入且 required 未达可合」的悬空项；未判定 %d 条"
              % (scanned, args.minutes, len(unjudged)))

    _write_summary(args.summary, [
        "### 🔎 悬空 PR 扫描（issue #5235 可见性面）",
        "",
        "- 扫描范围：`base=main` 的 open PR **%d** 条（`--limit %d`）；阈值：**%g 分钟**"
        % (scanned, args.limit, args.minutes),
        "- 判据：「既没变红、也没合入，且 `mergeStateStatus=BLOCKED`（required 未达可合状态）」"
        "⇒ 必须报出（异步窗口 / 已变红 / draft / `block/merge` 均不报，防假红）",
        "- **悬空 %d 条** / 未判定 %d 条" % (len(dangling), len(unjudged)),
        "",
    ] + (["| PR | 读数 |", "|---|---|"] + ["| %s |" % l.split(" —— ", 1)[0] for l in dangling]
         if dangling else ["无悬空项。"])
      + ([ "", "未判定（**不得当通过**）：" ] + ["- %s" % l for l in unjudged] if unjudged else []))

    if dangling:
        print("::error::悬空 PR 扫描：%d 条 open PR 既没变红也没合入且 required 未达可合状态"
              "（#5235：这一族**不许静默**）" % len(dangling))
        return EXIT_DANGLING
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
