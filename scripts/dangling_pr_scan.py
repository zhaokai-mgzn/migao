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

6. **未解决的评审线程**不是「提示文本」，而是一个**独立判定面**（issue #6997）：分支保护开了
   `required_conversation_resolution` ⇒ 一条 `isResolved=false` 的线程把 PR 钉在 `BLOCKED`，
   而 `statusCheckRollup` / `gh pr checks` **完全不含**这一项（#6987 实证：required **全绿**、
   auto-merge **已 arm**，却长期 `BLOCKED`、永不合并）⇒ 只能走 GraphQL 的 `reviewThreads` 单独判。
   口径与负控见下面 §⑤（**outdated 不算阻塞** —— 否则每个被密钥扫描命中过的 PR 会永远红）。

## ④ 冲突态：**事件投递 ≠ 检查存在**（issue #6815；本脚本的**第二个**判据族）

**病根（现场实证，issue #6815）**：PR 与 base **冲突**时，GitHub **造不出合并提交**
（`refs/pull/<n>/merge`）⇒ **`pull_request` 事件的工作流根本不创建 run**；而
`pull_request_target` 跑在 base 上、不需要合并提交 ⇒ **照常触发**。现场长成
「**只在跑不查的那一族在动，真正报门禁的那一族静默消失**」：

```
$ gh pr checks 6809     ⇒ 只有 Auto Merge（pull_request_target）的行，required 检查**连行都没有**
$ gh run list --branch … ⇒ 最近只剩 Auto Merge completed/skipped
$ gh pr view 6809 --json mergeable,mergeStateStatus ⇒ CONFLICTING / DIRTY
```

⇒ 本脚本新增 **态 ①** 的判红面：`mergeStateStatus == DIRTY ∧ head SHA 上没有任何
`event=pull_request` 的 run` ⇒ **判红**，读数里**具名**报出「required 检查在 head SHA 上
**不存在**（不是 pending）」。**为什么必须单独一条**：既有判据只认 `mergeStateStatus=BLOCKED`，
而冲突态的 `mergeStateStatus` 是 `DIRTY` ⇒ 既有判据把这一族**整个漏掉**（issue 里它正是 `skipping`）。

**三态必须分清（本单核心语义：把 ① 读成 ②「再等等」就是本次事故的心理机制）**：

| 态 | 形态 | 本脚本 |
|---|---|---|
| ① **run 未创建** | `DIRTY` ∧ head SHA 上无 `pull_request` run | **判红**（读数点名「不存在，不是 pending」+ 出口命令） |
| ② **run 创建但 pending** | head SHA 上有 `pull_request` run 且 `status != completed` | **不判红**（异步窗口；读数说「确实创建了、还在跑」） |
| ③ **run 创建且失败** | 该 run 的 `conclusion ∈ RED_CONCLUSIONS` | **不判红**（PR 上已有可见信号，与 §判据 4 同口径） |

**负控（缺了等于没修）**：① 非冲突 PR（`BLOCKED`/`CLEAN`/`UNSTABLE`/`UNKNOWN`）**一律不进**
这条判据 ⇒ 不得误报；② `paths:` 过滤导致的"未创建"**仍然**按既有判据
（`tests/unit_ci_workflows/test_required_check_no_paths_filter.py`）红 —— 本判据**不介入也不放宽**
（它只覆盖 `DIRTY` 这一个入口，`paths:` 形态的 `mergeStateStatus` 是 `BLOCKED`）。
⚠️ **边界（照实登记）**：`DIRTY` 在 PR 页面上另有 mergeable / 冲突横幅，故本判据的 `--minutes`
阈值同时约束它（年龄 < 阈值 ⇒ 不报）；`DIRTY` ∧ **有** `pull_request` run ⇒ 不报（那一族由既有
族 B 判据在 `BLOCKED` 上抓）。**判据不确定时不许"乐观跳闸"**：`event` 字段读不到 ⇒ 记未判定。
⚠️ **读到的 required 名单有两条腿**：attended 走 `gh api …/protection`（与 `scripts/merge_gate.py`
**同一读法**），CI 退到仓内快照 `tests/unit_ci_workflows/required_status_snapshot.json` ⇒ 读数里
**逐字报出「哪些 required 检查名在这条 HEAD 上不存在」**；两条都读不到 ⇒ 退 `3`（不得当 `0` 读）。
⚠️ **具名读数的边界（现取实测，照实登记）**：required 名 → 工作流的映射走
`merge_gate.py::scan_pr_jobs` 的**静态 `name:`** 口径 ⇒ **matrix 派生的检查名映射不上**
（现取：16 条 required 里 **14 条**能映射；映射不上的是 `pr-check.yml` 那条
`name: ci workflow helper unit tests${{ matrix.shard_suffix }}` 派生的两个名）。这**不影响判定**
（判红看的是 `event=pull_request` 的 run 有没有，与名字无关），影响的只是"具名清单少列两条"——
同一条 HEAD 上 `pr-check.yml` 的 run 本来就会出现在清单里，可行动性不受损。

## ⑤ 评审线程面（issue #6997）：本扫描器**判**什么 / **不判**什么

| 形态 | 本扫描器 |
|---|---|
| `isResolved == false ∧ isOutdated == false`（有人留了意见、代码也没改过） | **判**：计入「需要处置」（`::error::` + summary），报出 `path` + **首行摘要** + 分类计数 ⇒ 退出码 `1` |
| `isResolved == false ∧ isOutdated == true`（代码已改过、线程没人 resolve） | **不判**（**单独一类、不算阻塞**，只出声）—— 否则会**永远红**；处置面 = `scripts/resolve_stale_bot_threads.py`（**只**自动 resolve「bot ∧ 已过期」，人类线程永不自动 resolve） |
| `isResolved == true` | **不判**（已处置），只进计数读数 |
| 读不到（API 限流 / 权限 / PR 不存在 / 返回 `errors`） | **无法判定** ⇒ 整轮退 `3`（**不得当 `0` 读**），summary 明写「未判定」 |

⚠️ **命中悬空面时**（判据 ①/②）也要把线程面拼进 `::error::` 读数（issue #6997 的要求 2）——
否则就是「**报了警但说不清为什么**」（#6987 的真因正是靠这一步才落地的）；读不到时明写
「评审线程面**未判定**」，**不**静默。
⚠️ **为什么 outdated 不算阻塞**：`outdated ≠ resolved` —— 线程内容已被后续提交改掉，但它**仍然**把 PR
钉在 `BLOCKED`（#6987 的真因就是这一族）；把它当阻塞会让每个被 Gitleaks / 评审工具命中过的 PR **永久判红**。
本扫描器只做「可见 + 指名」，**不**自动 resolve 任何线程 —— 那会把「真存在且未修的密钥」一起静音
（issue #6997 的明确口径）。
⚠️ **边界（照实登记）**：① 只对浅判据已判 `ok` 的 PR 查线程面（draft / `block/merge` / 年龄 < `--minutes`
一律**不查、也不发**这次 API 调用 —— 异步窗口内留意见是正常工作，报它才是假红）；② 每 PR 一次 GraphQL
调用（`reviewThreads(first:100)`）⇒ 线程数 > 100 的 PR 只读前 100 条（计数即「本轮读到」）；③ 本扫描器
**不**读 `required_conversation_resolution` 这个开关（读不到保护配置时也能判）—— 线程面报的是
「有人留了意见、没人处置」这个**事实**，与该开关是否打开无关。

## 三态退出码（与 `scripts/merge_gate.py` 同口径）

| 码 | 含义 |
|---|---|
| `0` | 扫到了、**没有**悬空 PR，也**没有**「未解决且未过期」的评审线程（脚本自印「扫描 N 条」⇒「扫了 0 条」也看得见） |
| `1` | 扫到了、**有**悬空 PR **或**有「需要处置」的评审线程（逐条 `::error::` + step summary） |
| `3` | **无法判定**（读不到 open PR 列表 / **读不到评审线程面** / gh 不可用 / 输出不是 JSON）—— **不得当 `0` 读** |

单条 PR 读不到深判所需数据（`gh run list` 失败 / `mergeable` 未算完）⇒ 记 `未判定` 并
`::warning::`，**不**把整轮扫描判红（避免瞬时 API 抖动刷红），但 summary 明写
「未判定 N 条（**不得当通过**）」——「没跑成」必须长得像「没跑成」。
⚠️ **评审线程面的读失败是例外**（§⑤）：它是**判定所必需**的一维 ⇒ 退 `3`，不降级成 `0`。

## 注入点

`gh` 走 `DANGLING_GH_BIN` 替身可执行文件（沿用 `scripts/merge_gate.py` 的 `MG_GH_BIN`、
`scripts/resolve_stale_bot_threads.py` 的 `SBT_GH_BIN`、`automerge.yml` 的 `AUTOMERGE_GH_BIN` 先例）：
不 mock 被测逻辑，把 CLI 边界当注入点。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
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

#: ── issue #6815：冲突态（`DIRTY`）的判据面 ─────────────────────────────────────
#: 「合并提交造不出来」的 `mergeStateStatus` 取值。**只认 DIRTY**（不是 BEHIND）——
#: `BEHIND` 仍能造合并 ref、`pull_request` 腿照常跑（issue #6815 现场逐字 = `mergeState=DIRTY`）。
CONFLICT_STATES = frozenset({"DIRTY"})
#: 唯一需要合并提交的 PR 事件 —— `pull_request_target` 跑在 base 上、不需要它，
#: 所以**不能用**「有没有 run」粗判，必须按 `event` 区分（这就是「事件投递 ≠ 检查存在」）。
MERGE_REF_EVENT = "pull_request"
#: required 名单的两条腿：attended 现取 API；CI 退到此快照（与 merge_gate 同一读法）。
REQUIRED_SNAPSHOT = ("tests", "unit_ci_workflows", "required_status_snapshot.json")

#: ── issue #6997：评审线程面（`reviewThreads`）───────────────────────────────────
#: 「未解决会话线程」**只在 GraphQL 的 `reviewThreads` 里**（REST / `statusCheckRollup` /
#: `gh pr checks` 都不含）⇒ 这一维只能自己取。`isOutdated` 一并取（它是本面的负控口径）。
REVIEW_THREADS_QUERY = """
query($owner:String!,$name:String!,$number:Int!){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      reviewThreads(first:100){
        totalCount
        nodes{
          id isResolved isOutdated path
          comments(first:1){nodes{author{login} bodyText}}
        }
      }
    }
  }
}
"""
#: 首行摘要的截断宽度（读数要能一眼读出线程在说什么，又不把 summary 撑爆）
THREAD_SUMMARY_WIDTH = 96

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
            "status,conclusion,workflowName,event"]
    if repo:
        args += ["--repo", repo]
    return _gh(args)


# ── issue #6997：评审线程面（**提示文本 ≠ 判定**）────────────────────────────────
# 只有 GraphQL 的 `reviewThreads` 带 `isResolved` / `isOutdated`（REST / rollup 都不含）。
# 口径见脚本头 §⑤：未解决 ∧ 未过期 ⇒ 需要处置；未解决 ∧ 已过期 ⇒ 单独一类、**不算阻塞**。

def fetch_review_threads(repo, number):
    """一个 PR 的 `reviewThreads`（GraphQL 原件）。读不到 ⇒ `GhError`（= 未判定，**不准**当 0）。"""
    owner, _, name = str(repo or "").partition("/")
    if not owner or not name:
        raise GhError("读不到 owner/name（repo=%r）⇒ 无法查 reviewThreads" % (repo,))
    payload = _gh(["api", "graphql", "-f", "query=" + REVIEW_THREADS_QUERY,
                   "-f", "owner=" + owner, "-f", "name=" + name,
                   "-F", "number=%d" % int(number)])
    if not isinstance(payload, dict):
        raise GhError("gh api graphql 输出不是对象 ⇒ 未判定")
    if payload.get("errors"):
        raise GhError("gh api graphql 返回 errors（限流 / 权限 / 字段）：%s"
                      % json.dumps(payload["errors"], ensure_ascii=False)[:300])
    pull_request = ((payload.get("data") or {}).get("repository") or {}).get("pullRequest") or {}
    threads = pull_request.get("reviewThreads")
    if not isinstance(threads, dict):
        raise GhError("reviewThreads 读不到（限流 / 权限 / PR 不存在）⇒ 未判定，**不**当 0 读")
    return threads


def thread_first_line(body):
    """线程首条评论的**首行摘要**（空 ⇒ `<空首行>`；超宽截断并留 `…`）。"""
    for raw in str(body or "").splitlines():
        line = raw.strip().lstrip("#>*-").strip() or raw.strip()
        if line:
            return (line[:THREAD_SUMMARY_WIDTH] + "…") if len(line) > THREAD_SUMMARY_WIDTH else line
    return "<空首行>"


def normalize_threads(review_threads):
    """GraphQL `reviewThreads` → 归一化线程列表（判定只吃 `isResolved` / `isOutdated`）。"""
    threads = []
    for node in (review_threads or {}).get("nodes") or []:
        if not isinstance(node, dict):
            continue
        comments = ((node.get("comments") or {}).get("nodes") or [])
        first = comments[0] if comments and isinstance(comments[0], dict) else {}
        threads.append({
            "path": node.get("path") or "(未知路径)",
            "is_resolved": bool(node.get("isResolved")),
            "is_outdated": bool(node.get("isOutdated")),
            "author": ((first.get("author") or {}).get("login") or "(未知作者)"),
            "summary": thread_first_line(first.get("bodyText")),
        })
    return threads


def classify_threads(threads):
    """三分类 + 计数（**取数与判定分离**）：口径逐字见脚本头 §⑤。"""
    needs_disposition = [t for t in threads if not t["is_resolved"] and not t["is_outdated"]]
    outdated = [t for t in threads if not t["is_resolved"] and t["is_outdated"]]
    resolved = [t for t in threads if t["is_resolved"]]
    return {"needs_disposition": needs_disposition, "outdated": outdated,
            "resolved": resolved, "total": len(threads)}


def review_thread_reason(pr, classified):
    """线程面的**可行动读数**：分类与计数 + 每条的 `path` + 首行摘要 + 处置入口。"""
    number = pr.get("number")
    bits = ["评审线程面：**未解决且未过期 %d 条（需要处置）**/ 未解决但已过期 %d 条"
            "（**单独一类、不算阻塞**）/ 已解决 %d 条（共读到 %d 条）"
            % (len(classified["needs_disposition"]), len(classified["outdated"]),
               len(classified["resolved"]), classified["total"])]
    for thread in classified["needs_disposition"][:5]:
        bits.append("`%s`「%s」（%s）" % (thread["path"], thread["summary"], thread["author"]))
    rest = len(classified["needs_disposition"]) - 5
    if rest > 0:
        bits.append("……另有 %d 条（同上，`reviewThreads(first:100)` 已读到）" % rest)
    for thread in classified["outdated"][:5]:
        bits.append("（已过期）`%s`「%s」（%s）"
                    % (thread["path"], thread["summary"], thread["author"]))
    if classified["outdated"]:
        bits.append("已过期那 %d 条**代码已改过、但 `outdated ≠ resolved`**（仍会把 PR 钉在 `BLOCKED`）"
                    "⇒ 处置：`python3 scripts/resolve_stale_bot_threads.py %s`"
                    "（默认只读；人类线程永不自动 resolve）"
                    % (len(classified["outdated"]), number))
    bits.append("处置：按上面每个 `path` 处理意见后 resolve 该线程（本扫描器**不**自动 resolve —— "
                "那会把「真存在且未修的密钥」一起静音）")
    return "；".join(bits)


# ── issue #6815：冲突态判据（**事件投递 ≠ 检查存在**）──────────────────────────
# 复用 `scripts/merge_gate.py::scan_pr_jobs`（「检查名 → 工作流文件」的**单一实现**）与
# 「分支保护 API 优先、仓内快照退路」的既有读法 ⇒ 本脚本**不重写**这两块。

def _load_merge_gate():
    """按路径加载同目录的 `scripts/merge_gate.py`（不依赖 sys.path / CWD 是否含 `scripts`）。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "merge_gate.py")
    spec = importlib.util.spec_from_file_location("merge_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runs_for_pr_event(runs):
    """`event == 'pull_request'` 的 run 子集 —— **唯一**需要合并提交（`refs/pull/<n>/merge`）的一族。

    `event` 缺失（`None`）⇒ **既不算也不是**：调用方按「读不到 ⇒ 未判定」处置（不许乐观跳闸）。
    """
    return [r for r in (runs or [])
            if isinstance(r, dict) and (r.get("event") or "").strip() == MERGE_REF_EVENT]


def event_unreadable(runs):
    """任一 run 读不到 `event` ⇒ 本判据**无法判定**（退「未判定」，不当 ①/②/③ 读）。"""
    return any(not str((r or {}).get("event") or "").strip()
               for r in (runs or []) if isinstance(r, dict))


def _workflow_job_names(path):
    """`.github/workflows/*.yml` → `{job 显示名: job id}`（只用于**具名**读数）。

    GitHub 上报的检查名 = job 的 `name:`（缺省回落 job id）。**手工轻量解析**、不引依赖：
    只扫 `jobs:` 块，替身/最小改动下也不会因解析失败而误报（解析不出 ⇒ 名单为空、判据照旧判红）。
    """
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return {}
    jobs_indent = None
    entries = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if jobs_indent is None:
            if re.match(r"^jobs:\s*(#.*)?$", stripped):
                jobs_indent = indent
            continue
        if indent <= jobs_indent:
            break  # `jobs:` 块结束
        if indent != jobs_indent + 2:
            continue
        match = re.match(r"^([A-Za-z0-9_.\-]+):\s*(#.*)?$", stripped)
        if match:
            entries.append(match.group(1))
    names, current = {}, None
    for line in lines:
        if current is not None:
            indent = len(line) - len(line.lstrip(" "))
            if line.strip() and indent <= current[0]:
                current = None
            else:
                match = re.match(r"^\s+name:\s*(.+?)\s*$", line)
                if match:
                    names[current[1]] = match.group(1).strip().strip("'\"")
                    current = None
                    continue
        match = re.match(r"^(\s+)([A-Za-z0-9_.\-]+):\s*(#.*)?$", line)
        if match and len(match.group(1)) in {2, 4} and match.group(2) in entries:
            current = (len(match.group(1)), match.group(2))
    return {names.get(job, job): job for job in entries}


def required_context_workflows(required, workflows_dir):
    """required 检查名 → 提供它的**工作流文件 basename**（复现 `merge_gate` 的映射口径）。

    读不到工作流目录（CI 未检出 / 路径不对）⇒ `{}` —— 名单退化为"未读列"，**判据照旧**。
    """
    if not required:
        return {}
    try:
        names = _load_merge_gate().job_names_on_pull_requests(workflows_dir)
    except Exception:  # noqa: BLE001 - 名单读不到只影响读数详尽度，**不得**改变判定
        return {}
    by_workflow = {}
    for context in required:
        where = names.get(context)
        if where:
            by_workflow[str(context)] = where.split(":", 1)[0]
    return by_workflow


def missing_workflow_names(runs, required, workflows_dir):
    """该 HEAD 上**一个 run 都没有**的工作流文件名（= required 名单在这条 HEAD 上"不存在"）。

    返回 `(未读列的名字, 读得出但缺 run 的 sorted 文件名列表)`；`runs is None` ⇒ 无从判定。
    """
    if runs is None:
        return [], []
    by_workflow = required_context_workflows(required, workflows_dir)
    observed = {(r.get("workflowName") or "").strip() for r in runs if isinstance(r, dict)}
    unread = sorted(name for name, wf in by_workflow.items() if wf not in observed)
    return unread, sorted({by_workflow[name] for name in unread})


def conflict_reason(pr, runs, age, minutes, required, workflows_dir):
    """**态 ①** 的读数：具名报出「required 检查在 head SHA 上**不存在**（不是 pending）」+ 出口命令。"""
    number = pr.get("number")
    mergeable = (pr.get("mergeable") or "").strip()
    red, _ = rollup_split(pr.get("statusCheckRollup"))
    unread, workflows = missing_workflow_names(runs, required, workflows_dir)
    bits = [
        "**态 ①：run 未创建**（不是 pending，也不是失败 —— `::error::` 的措辞必须与本态一致）",
        "open %.0f 分钟(≥%d)、`mergeStateStatus=DIRTY`（`mergeable=%s`）⇒ PR 与 base **冲突** ⇒ "
        "GitHub 造不出合并提交 `refs/pull/%s/merge` ⇒ **`event=%s` 的工作流根本不创建 run**"
        % (age, minutes, mergeable or "<未读到>", number, MERGE_REF_EVENT),
        "该 HEAD(%s) 上 **%d 条 `%s` run**：%s（`pull_request_target` 跑在 base 上、不需要合并提交，"
        "所以它照常跑 —— 现场于是长成「只在跑不查的那一族在动」）"
        % (str(pr.get("headRefOid") or "")[:12], 0, MERGE_REF_EVENT,
           "无" if not runs else "、".join(sorted({(r.get("workflowName") or "?") for r in runs})[:5])),
    ]
    if required:
        bits.append("在 head SHA 上**读不到 run** 的工作流（本该上报 required 检查）：**%s**"
                    % ("、".join(workflows) if workflows else "<名单未读列>"))
        bits.append("对应的 required 检查名（**不存在**，不是 pending）：**%s**"
                    % ("、".join(unread) if unread else
                       "required 名单读到了，但按工作流名映射不上任何 run ⇒ 见上一条"))
    else:
        bits.append("required 名单**本轮读不到**（`gh api …/protection` 需 admin + 仓内快照缺失）"
                    "⇒ 读数不列名单，**但判定照旧**（本判据不因名单缺失而降级）")
    bits.append("⇒ 出口：`gh pr view %s --json mergeable,mergeStateStatus` 读 `%s`；"
                "解冲突（本地 `git fetch origin main && git merge origin/main` 后推）或 "
                "`gh pr update-branch %s` ⇒ `pull_request` 腿立即恢复创建"
                % (number, mergeable or "CONFLICTING", number))
    if age >= minutes and not red:
        bits.append("本态的**唯一**已知出路是解开冲突；在冲突解除前，**不会**有任何 required 检查到来"
                    "（等下去 = 本次事故浪费 1 小时的心理机制）")
    return "；".join(bits)


def judge_conflict(pr, runs, age, minutes, required, workflows_dir):
    """冲突态（`DIRTY`）的判定：`(verdict, reason)`，`verdict ∈ {ok, dangling, unjudged}`。

    ⚠️ `DIRTY` 时 GitHub **不保证**把每个 check 都放进 rollup（`event` 没投递就没有 check run
    对象）⇒ 本函数**不**用 rollup 的 pending 面判定 ②（否则「check 对象滞后」会被读成 ①）。
    """
    number = pr.get("number")
    if runs is None:
        return "unjudged", "#%s `DIRTY` 但未取该 HEAD 的 run 列表" % number
    if event_unreadable(runs):
        return "unjudged", ("#%s 该 HEAD 的 run 读不到 `event` 字段 ⇒ **无法区分**「未创建」与"
                            "「创建了但没查」—— 不当 ①/②/③ 读" % number)
    pr_runs = runs_for_pr_event(runs)
    if not pr_runs:
        return "dangling", conflict_reason(pr, runs, age, minutes, required, workflows_dir)
    # 态 ② 的判定**沿用本文件既有口径**（`status != completed` = 还在跑，哪怕结论是 action_required）
    # ⇒ 必须是 `not in {completed}`：只认白名单会把从未见过的 status 误判成"跑完了"。
    running = [r for r in pr_runs
               if (r.get("status") or "").lower() not in ("completed",)]
    if running:
        return "ok", ("#%s `DIRTY`（冲突）但 `%s` run **确实已创建**（态 ②：pending，%s）⇒ 不重复报"
                      "（冲突在 PR 页面已有横幅）" % (
                          number, MERGE_REF_EVENT,
                          "、".join(sorted({(r.get("workflowName") or "?") for r in running})[:3])))
    red = [r for r in pr_runs if (r.get("conclusion") or "").upper() in RED_CONCLUSIONS]
    if red:
        return "ok", ("#%s `DIRTY`（冲突）但 `%s` run **已创建且判红**（态 ③：%s）⇒ PR 上已有可见信号"
                      % (number, MERGE_REF_EVENT,
                         "、".join(sorted({(r.get("workflowName") or "?") for r in red})[:3])))
    return "ok", ("#%s `DIRTY`（冲突）且在该 HEAD 上有 %d 条 `%s` run（未判红；冲突本身在 PR 页面有横幅）"
                  % (number, len(pr_runs), MERGE_REF_EVENT))


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


def judge(pr, runs, now, minutes, required=(), workflows_dir=""):
    """纯函数判定：`(verdict, reason, note)`，`verdict ∈ {ok, need_runs, dangling, unjudged}`。

    `runs=None` ⇒ 尚未取该 HEAD 的 run 列表；若浅判据已通过（候选）则返回 `need_runs`，
    由调用方取回 run 列表后用同一函数**重判一次**（幂等）。

    `required` / `workflows_dir` **只影响读数的详尽度**（具名报出"哪些 required 检查不存在"），
    **不改变任何判定**（读不到名单时判据照旧判红，不降级）。

    第 3 项 `note` = **"跳过也要长得像跳过"**（issue #6815，§18.6「环境静默即缺陷」同族）：
    只对「`DIRTY`（冲突）∧ draft」这一**会永久静默的组合**出话（调用方印 `::warning::` + 计入
    summary 的「已跳过」栏）；其余跳过（标签 / 年龄 / 已绿…）**不**增加噪声，`note` 恒为 `""`。
    ⚠️ 这里**不改**「跳过 draft」这条既有口径（`isDraft ⇒ ok`，`automerge.yml` 的 arm 也只看非 draft；
    读的是 `gh pr list --json isDraft` 的真值）—— 本单只把它**变可见**。
    """
    number = pr.get("number")
    if pr.get("isDraft"):
        state = (pr.get("mergeStateStatus") or "").upper()
        if state in CONFLICT_STATES:
            return "ok", "draft（有意不可合）", (
                "#%s **draft ∧ 冲突** ⇒ 本扫描按既有口径**跳过**（`isDraft` ⇒ 有意不可合）、"
                "`pull_request` 腿在冲突期间也不会创建——这两个条件叠加时**本扫描不出声**，"
                "兜底面 = 作者自己 `gh pr ready` 那一刻（届时非 draft ⇒ 本判据当场判红）。"
                "复算：`gh pr view %s --json isDraft,mergeable,mergeStateStatus`"
                % (number, number))
        return "ok", "draft（有意不可合）", ""
    labels = {(l or {}).get("name") for l in (pr.get("labels") or []) if isinstance(l, dict)}
    if labels & BLOCK_LABELS:
        return "ok", "带 `%s` 标签（人工闸）" % "`,`".join(sorted(labels & BLOCK_LABELS)), ""
    age = age_minutes(pr.get("createdAt"), now)
    if age is None:
        return "unjudged", "#%s 的 createdAt 不可解析：%r" % (number, pr.get("createdAt")), ""
    if age < minutes:
        return "ok", "#%s 仅 open %.0f 分钟（< %d）" % (number, age, minutes), ""
    state = (pr.get("mergeStateStatus") or "").upper()
    if state in ("", "UNKNOWN"):
        return "unjudged", "#%s 的 mergeStateStatus=%r（GitHub 尚未算完 ⇒ 无从判定，非红）" % (
            number, pr.get("mergeStateStatus")), ""
    if state in CONFLICT_STATES:
        # issue #6815：冲突态**单独一条**判据 —— 它的 `mergeStateStatus` 是 `DIRTY`，
        # 而既有浅判据只认 `BLOCKED` ⇒ 现场（该 job `skipping`）正是被这条 `!= BLOCKED` 漏掉的。
        if runs is None:
            return "need_runs", "#%s mergeStateStatus=DIRTY（冲突态）⇒ 需读该 HEAD 的 run 列表" % number, ""
        verdict, reason = judge_conflict(pr, runs, age, minutes, required, workflows_dir)
        return verdict, reason, ""
    if state != "BLOCKED":
        return "ok", "#%s mergeStateStatus=%s（required 已达可合状态，或另有页面级显式信号）" % (
            number, state), ""
    red, pending = rollup_split(pr.get("statusCheckRollup"))
    if red:
        return "ok", "#%s 已变红（%d 条判红：%s）" % (number, len(red), "、".join(red[:3])), ""
    if pending:
        return "ok", "#%s 仍在跑（%d 条未跑完：%s）" % (number, len(pending), "、".join(pending[:3])), ""
    if runs is None:
        return "need_runs", "#%s 浅判据全过 ⇒ 需读该 HEAD 的 run 列表" % number, ""
    running = [r for r in runs
               if (r.get("status") or "").lower() not in ("completed",)]
    if running:
        return "ok", "#%s 仍有 %d 条 run 在跑/排队（%s）" % (
            number, len(running),
            "、".join(sorted({(r.get("workflowName") or "?") for r in running})[:3])), ""
    return "dangling", dangling_reason(pr, runs, age, minutes), ""


def _write_summary(path, lines):
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError as exc:  # summary 写不进去不得改变判定
        print("::warning::step summary 写入失败（判定不受影响）：%s" % exc)


def load_required_contexts(repo, gh_bin=None):
    """required 检查名 —— **两条腿**（与 `scripts/merge_gate.py` 同一读法/同一退路）+ 来源标签。

    ① 现取 `gh api …/protection`（attended / 本机）；② 退到仓内快照
    `tests/unit_ci_workflows/required_status_snapshot.json`（CI 读不到该 API：需 admin）。
    两条都读不到 ⇒ `([], "none")` —— 调用方**照旧判定**，只少一段具名读数（**不降级、不跳过**）。
    """
    gh_bin = gh_bin or GH
    try:
        required = _load_merge_gate().fetch_required(repo or gh_repo(gh_bin), "main", gh_bin)
        if required:
            return sorted(required), "api"
    except Exception:  # noqa: BLE001 - 读不到名单只影响读数详尽度，**不得**改变判定
        pass
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        *REQUIRED_SNAPSHOT)
    try:
        with open(path, encoding="utf-8") as fh:
            contexts = json.load(fh).get("contexts") or []
        return sorted(str(c) for c in contexts), "snapshot"
    except (OSError, ValueError, AttributeError):
        return [], "none"


def gh_repo(gh_bin=None):
    """`owner/name`（现取）；读不到 ⇒ 空串（由调用方退到快照腿）。"""
    try:
        proc = subprocess.run([gh_bin or GH, "repo", "view", "--json", "nameWithOwner",
                               "--jq", ".nameWithOwner"], capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def _required_from_file(path):
    """`--required-file` 的注入点（判据用）：读 `{contexts: […]}` ⇒ `(名单, "file")`。"""
    try:
        with open(path, encoding="utf-8") as fh:
            contexts = json.load(fh).get("contexts") or []
        return sorted(str(c) for c in contexts), "file"
    except (OSError, ValueError, AttributeError) as exc:
        print("::warning::--required-file 读不到（只影响读数详尽度，判定照旧）：%s" % exc)
        return [], "none"


def _classify_pr_threads(repo, number):
    """取 + 归一化 + 分类（悬空面归因 / 干净面判定**共用**；失败抛 `GhError` ⇒ 调用方按未判定处置）。"""
    return classify_threads(normalize_threads(fetch_review_threads(repo, number)))


def _account_threads(classified, stats):
    """把一次分类累加进 summary 计数（线程**条数** + 涉及「需要处置」的 **PR 数**）。"""
    if not classified:
        return
    stats["queried"] += 1
    stats["needs_disposition"] += len(classified["needs_disposition"])
    stats["outdated"] += len(classified["outdated"])
    stats["resolved"] += len(classified["resolved"])
    stats["prs_needing"] += bool(classified["needs_disposition"])  # PR 数（不是线程条数）


def review_thread_scope(pr, now, minutes):
    """该 PR 要不要查线程面 —— 与 `judge()` 的浅口径**同一组门**（draft / `block/merge` / 年龄）。

    只对「浅判据已判 `ok`」的 PR 调用（见 `main`）；返回 `False` ⇒ **不发**这次 API 调用
    （异步窗口内留意见是正常工作，报它才是假红）。`createdAt` 不可解析 ⇒ `False`
    （它已被 `judge()` 记成未判定，不在这里重复判定）。
    """
    if pr.get("isDraft"):
        return False
    labels = {(l or {}).get("name") for l in (pr.get("labels") or []) if isinstance(l, dict)}
    if labels & BLOCK_LABELS:
        return False
    age = age_minutes(pr.get("createdAt"), now)
    return age is not None and age >= minutes


def report(
    *,
    scanned,
    limit,
    minutes,
    dangling,
    conflict_ok,
    skipped,
    unjudged,
    needs_disposition,
    thread_outdated,
    threads_unjudged,
    threads_stats,
    required_count,
    required_source,
    summary_path,
):
    """三态读数与 step summary（**态 ①/②/③ 必须各自可见** —— 本单核心语义）。

    `skipped` = 「跳过但**值得出声**」的条目（现取口径 = `DIRTY` ∧ draft）——
    "跳过"必须长得像"跳过"（§18.6「环境静默即缺陷」同族），否则它会被读成"没问题"。

    `needs_disposition` / `thread_outdated` / `threads_unjudged` = 评审线程面（issue #6997）的
    **三个互斥读数**：需要处置（判红）/ 已过期（单独一类、不算阻塞）/ 读不到（未判定）；
    `threads_stats` = 分类与计数（`needs_disposition` / `outdated` / `resolved` 是**线程条数**）。
    """
    source = {"api": "现取 `gh api …/branches/main/protection`", "snapshot": "仓内快照",
              "file": "`--required-file` 注入", "none": "**读不到**（api 需 admin + 快照缺失）"}.get(
                  required_source, required_source)
    for line in dangling:
        print("::error::悬空 PR：%s" % line)
    for line in needs_disposition:
        print("::error::需要处置（评审线程：未解决且未过期）：%s" % line)
    for line in conflict_ok:
        print("::notice::冲突态但检查**已创建**（态 ②/③，不判红）：%s" % line)
    for line in thread_outdated:
        print("::notice::评审线程**已过期**（单独一类、**不算阻塞**；处置见 "
              "`resolve_stale_bot_threads.py`）：%s" % line)
    for line in skipped:
        print("::warning::已跳过（**不是「没问题」**）：%s" % line)
    for line in unjudged:
        print("::warning::未判定（不得当通过）：%s" % line)
    for line in threads_unjudged:
        print("::warning::评审线程面**未判定**（不得当通过）：%s" % line)
    if not dangling and not needs_disposition and not threads_unjudged:
        print("::notice::✅ 悬空 PR 扫描：扫了 %d 条 open PR（base=main，阈值 %g 分钟），"
              "无「既没变红也没合入且 required 未达可合」的悬空项，也无「未解决且未过期」的评审线程；"
              "冲突态但检查已创建（态 ②/③）%d 条；已跳过（可见）%d 条；未判定 %d 条"
              "（评审线程面：查了 %d 个 PR —— 未解决且未过期 %d 条 / 已过期 %d 条 / 已解决 %d 条）"
              % (scanned, minutes, len(conflict_ok), len(skipped), len(unjudged),
                 threads_stats.get("queried", 0), threads_stats.get("needs_disposition", 0),
                 threads_stats.get("outdated", 0), threads_stats.get("resolved", 0)))
    _write_summary(summary_path, [
        "### 🔎 悬空 PR 扫描（issue #5235 可见性面 + #6815 冲突态面 + #6997 评审线程面）",
        "",
        "- 扫描范围：`base=main` 的 open PR **%d** 条（`--limit %d`）；阈值：**%g 分钟**"
        % (scanned, limit, minutes),
        "- 判据 ①：「既没变红、也没合入，且 `mergeStateStatus=BLOCKED`（required 未达可合状态）」"
        "⇒ 必须报出（异步窗口 / 已变红 / draft / `block/merge` 均不报，防假红）",
        "- 判据 ②（issue #6815）：`mergeStateStatus=DIRTY`（冲突）∧ 该 HEAD 上**没有** "
        "`event=pull_request` 的 run ⇒ **态 ①「run 未创建」** ⇒ 必须报出（读数点名「不存在，不是 pending」）",
        "- 判据 ③（issue #6997）：`reviewThreads` 里 **`isResolved=false ∧ isOutdated=false`** ⇒ "
        "**需要处置**（报出 `path` + 首行摘要）；`isOutdated=true` ⇒ **单独一类、不算阻塞**；"
        "读不到（限流 / 权限）⇒ 退 `3`（**不得当 0**）",
        "- **required 名单来源**：%s（%d 条）—— 读不到**不**改变判定，只少一段具名读数" % (source, required_count),
        "- **悬空 %d 条**（其中**态 ①「run 未创建」**的全部计入此数）/ "
        "**需要处置的评审线程 %d 个 PR** / "
        "**冲突态但检查已创建（态 ②/③）%d 条** / **已跳过（可见）%d 条** / 未判定 %d 条"
        % (len(dangling), threads_stats.get("prs_needing", 0), len(conflict_ok), len(skipped),
           len(unjudged)),
        "- **评审线程面**：查了 **%d** 个 PR —— 未解决且未过期 **%d** 条（需要处置）/ "
        "已过期 **%d** 条（**单独一类、不算阻塞**）/ 已解决 **%d** 条 / 线程面未判定 **%d** 个 PR"
        % (threads_stats.get("queried", 0), threads_stats.get("needs_disposition", 0),
           threads_stats.get("outdated", 0), threads_stats.get("resolved", 0),
           len(threads_unjudged)),
        "",
    ] + (["| PR | 读数 |", "|---|---|"] + ["| %s |" % l.split(" —— ", 1)[0] for l in dangling]
         if dangling else ["无悬空项（态 ①）。"])
      + (["", "**需要处置（评审线程：未解决且未过期）**："] + ["- %s" % l for l in needs_disposition]
         if needs_disposition else [])
      + (["", "**评审线程已过期（单独一类、不算阻塞：`outdated ≠ resolved`，处置见 "
              "`resolve_stale_bot_threads.py`）**："] + ["- %s" % l for l in thread_outdated]
         if thread_outdated else [])
      + (["", "**态 ②/③（冲突但检查已创建，不判红）**："] + ["- %s" % l for l in conflict_ok]
         if conflict_ok else [])
      + (["", "**已跳过（`draft ∧ 冲突` 这一组合会永久静默 ⇒ 出声；跳过 ≠ 没问题）**："]
         + ["- %s" % l for l in skipped] if skipped else [])
      + (["", "未判定（**不得当通过**）："] + ["- %s" % l for l in unjudged] if unjudged else [])
      + (["", "评审线程面未判定（**不得当通过**）："] + ["- %s" % l for l in threads_unjudged]
         if threads_unjudged else []))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="悬空 PR 扫描（issue #5235 可见性面 + issue #6815 冲突态「run 未创建」面 "
                    "+ issue #6997 评审线程面）")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""),
                        help="owner/name（默认取 GITHUB_REPOSITORY）")
    parser.add_argument("--minutes", type=float,
                        default=float(os.environ.get("DANGLING_MINUTES", "60")),
                        help="「悬空」的年龄阈值（分钟）；默认 60 —— 远大于本仓 CI 的常规时长")
    parser.add_argument("--limit", type=int, default=100, help="最多扫多少条 open PR")
    parser.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY", ""),
                        help="step summary 落笔位置（默认取 GITHUB_STEP_SUMMARY）")
    parser.add_argument("--workflows-dir",
                        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                             ".github", "workflows"),
                        help="工作流目录（只用于把 required 检查名映射到工作流 ⇒ 具名读数）")
    parser.add_argument("--required-file", default="",
                        help="required 名单 JSON（`{contexts: [...]}`）；给了就用它，跳过两条腿")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    try:
        prs = list_open_prs(args.repo, args.limit)
    except GhError as exc:
        print("::error::悬空 PR 扫描**无法判定**（不得当通过）：%s" % exc)
        return EXIT_UNJUDGEABLE

    if args.required_file:
        required, required_source = _required_from_file(args.required_file)
    else:
        required, required_source = load_required_contexts(args.repo)

    dangling, conflict_ok, skipped, unjudged, scanned = [], [], [], [], 0
    # issue #6997：评审线程面的三个**互斥**读数（口径见脚本头 §⑤）
    needs_disposition, thread_outdated, threads_unjudged = [], [], []
    threads_stats = {"queried": 0, "prs_needing": 0, "needs_disposition": 0,
                     "outdated": 0, "resolved": 0}
    thread_repo = args.repo or gh_repo()  # 只取一次（`--repo` 缺省时才现取）
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        scanned += 1
        verdict, reason, note = judge(pr, None, now, args.minutes, required, args.workflows_dir)
        if verdict == "need_runs":
            try:
                runs = head_runs(args.repo, pr.get("headRefOid") or "")
            except GhError as exc:
                unjudged.append("#%s 读不到该 HEAD 的 run 列表：%s" % (pr.get("number"), exc))
                continue
            verdict, reason, note = judge(pr, runs, now, args.minutes, required,
                                          args.workflows_dir)
            if verdict == "ok" and (pr.get("mergeStateStatus") or "").upper() in CONFLICT_STATES:
                conflict_ok.append("#%s %s —— %s" % (pr.get("number"),
                                                     (pr.get("title") or "")[:60], reason))
                continue
        if verdict == "dangling":
            headline = "#%s %s" % (pr.get("number"), (pr.get("title") or "")[:60])
            # issue #6997 的要求 2：**命中后必须输出线程面**（`path` / 首行摘要 / 已过期与否）——
            # 否则就是「报了警但说不清为什么」（#6987 的真因正是靠这一步才落地的）。
            try:
                classified = _classify_pr_threads(thread_repo, pr.get("number"))
            except GhError as exc:
                threads_unjudged.append("%s —— 读不到 `reviewThreads`（限流 / 权限）⇒ "
                                        "**未判定，不得当 0 读**：%s" % (headline, exc))
                reason = "%s；评审线程面**未判定**（限流 / 权限）：%s" % (reason, exc)
            else:
                _account_threads(classified, threads_stats)
                if classified["total"]:
                    reason = "%s；%s" % (reason, review_thread_reason(pr, classified))
            dangling.append("%s —— %s" % (headline, reason))
        elif verdict == "unjudged":
            unjudged.append(reason)
        elif review_thread_scope(pr, now, args.minutes):
            # 浅判据已判「没问题」⇒ **只有这一维**还能把它翻成「需要处置」（issue #6997）
            headline = "#%s %s" % (pr.get("number"), (pr.get("title") or "")[:60])
            try:
                classified = _classify_pr_threads(thread_repo, pr.get("number"))
            except GhError as exc:
                # 读不到 ⇒ **未判定**（不得当 0 读）⇒ 整轮退 3（见脚本头 §⑤ / 三态退出码）
                threads_unjudged.append("%s —— 读不到 `reviewThreads`（限流 / 权限）⇒ "
                                        "**未判定，不得当 0 读**：%s" % (headline, exc))
            else:
                _account_threads(classified, threads_stats)
                if classified["needs_disposition"]:
                    needs_disposition.append(
                        "%s —— %s" % (headline, review_thread_reason(pr, classified)))
                elif classified["outdated"]:
                    # **单独一类、不算阻塞**（否则每个被密钥扫描命中过的 PR 会永远红）⇒ 只出声
                    thread_outdated.append(
                        "%s —— %s" % (headline, review_thread_reason(pr, classified)))
        if note:
            skipped.append("#%s %s —— %s" % (pr.get("number"), (pr.get("title") or "")[:60], note))

    report(scanned=scanned, limit=args.limit, minutes=args.minutes, dangling=dangling,
           conflict_ok=conflict_ok, skipped=skipped, unjudged=unjudged,
           needs_disposition=needs_disposition, thread_outdated=thread_outdated,
           threads_unjudged=threads_unjudged, threads_stats=threads_stats,
           required_count=len(required), required_source=required_source,
           summary_path=args.summary)

    if dangling or needs_disposition:
        print("::error::悬空 PR 扫描：悬空 %d 条（既没变红也没合入且 required 未达可合）"
              " + 需要处置的评审线程 %d 个 PR（#5235 / #6997：这两族**不许静默**）"
              % (len(dangling), threads_stats.get("prs_needing", 0)))
        return EXIT_DANGLING
    if threads_unjudged:
        print("::error::悬空 PR 扫描**无法判定**：%d 个 PR 的评审线程面读不到（限流 / 权限）"
              "⇒ 不得当 0 读" % len(threads_unjudged))
        return EXIT_UNJUDGEABLE
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
