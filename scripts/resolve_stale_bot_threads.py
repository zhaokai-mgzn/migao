#!/usr/bin/env python3
"""resolve_stale_bot_threads.py — #4231「CI 全绿却永久 BLOCKED」的判定与陈旧机器人线程解决。

## 病根（实测级，有前后对照）

`main` 的分支保护开了 **`required_conversation_resolution`**（实测 API 读回 `{'enabled': True}`）。
于是任何**未解决（unresolved）**的评审线程都会把 PR 钉在 `BLOCKED` —— 包括**已被后续提交修好**的
机器人线程：作者 force-push 修好后 `Secret Scan` 转绿、线程变 `isOutdated=true`，**但仍 `isResolved=false`**
⇒ **永久 BLOCKED，且没有任何检查会变红**（危险处：全绿却合不了，排查方向会被引向 CI/冲突/label）。

实证 **#4218**：`gh pr checks` 21 pass / 0 fail、`mergeable=MERGEABLE`、`labels=[]`、`isDraft=false`、
auto-merge（squash）已启用，却 25 分钟不合并；手动 `resolveReviewThread` 后 **46 秒**自动合并。

## 用法

    python3 scripts/resolve_stale_bot_threads.py <PR号> [--repo OWNER/NAME] [--apply]

**默认 dry-run（只读）**，与 `scripts/delete_orders.py` 同风格：`--apply` 才真正调用
`resolveReviewThread` 写操作。

## 退出码（与 `scripts/red_proof.py` / `.github/scripts/eval_slot_status.sh` 三态约定一致）

    0 = **未命中该形态**（不是 BLOCKED / 不是全绿 / 有阻塞 label / 无未解决机器人线程…）
    1 = **命中该形态**（CI 全绿 + `mergeable=MERGEABLE` + 无阻塞 label + 却 `mergeStateStatus=BLOCKED`
        + 存在**未解决的机器人评审线程**）⇒ 首查未解决评审线程，本脚本给出可行动命令
    3 = **无法判定**（gh 不在 PATH / API 报错 / `mergeStateStatus=UNKNOWN` 重算中 / checks 读不到）
        —— **「看不了」绝不谎报成 0**

`--apply` 模式：命中时才执行 resolve，退出码 0 = 需解决的线程都已解决（或本就没有），
1 = 有 resolve 调用失败；3 = 无法判定（此时**不发任何写操作**，fail-closed）。

## 安全边界（不得越级）

- **只 resolve「未解决 + 作者是机器人 + `isOutdated=true`」**：机器人已指出的、**当前仍在**的问题
  （`isOutdated=false`）**不自动关** —— 那会掩盖真实发现，只如实列出并给人工处置路径。
- **人类线程永不自动 resolve**：issue #4231 明确「不建议关掉 `required_conversation_resolution`
  —— 它对**人类**评审线程是有价值的护栏」。人类线程单列「需人工评审」，退 0（非本形态）。
- 本脚本**不判断**「问题是否真的修好了」；它只判「这条线程是否仍在机械地阻塞合并」。

## 自动化选项 (a)/(b) 的落位（保留类，见 issue #4231 判据 2）

issue 建议的 (a)「让机器人 job 在转绿时 resolve 自己的线程」与 (b)「加定时/事件 stale-bot-thread
resolver workflow」都需要改 `.github/workflows/**`；本机 gh token **无 `workflow` scope**
（`gh auth status` = repo / gist / read:org / admin:public_key）⇒ 此类提交会被 GitHub 拒绝推送。
故本 PR **不改任何 workflow**，改为交付本**不依赖 workflow** 的可执行脚本（人 / 主会话可直接调用，
也可在拿到 workflow scope 后由 (a)/(b) 复用同一判定函数）。

## 自测红证

`tests/unit_ci_workflows/test_resolve_stale_bot_threads.py`（case_ids: MC-012）：
夹具层 5 组（命中 + 反向 A/B/C + 三态），`gh` 用替身可执行文件注入（CLI 边界即注入点）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import namedtuple

EXIT_OK = 0
EXIT_HIT = 1
EXIT_UNDECIDABLE = 3

# 阻塞 label = 仓库的**人工闸**（`.github/workflows/automerge.yml` 里 auto-merge 会跳过带该标签的 PR，
# `.github/workflows/drift-audit.yml` 失败时打、恢复后摘）。带它 ⇒ BLOCKED 是**有意**的，不是本形态。
BLOCKING_LABELS = ("block/merge",)

# 判定为「机器人」的两条判据：GraphQL 的 `__typename == "Bot"`（实测 github-actions 即为 Bot），
# 以及 login 的 `[bot]` 后缀（`gh pr view --json` 路径拿不到 typename 时的兜底）。
BOT_LOGIN_SUFFIX = "[bot]"

GRAPHQL_PR_QUERY = """
query($owner:String!,$name:String!,$number:Int!){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      number state isDraft mergeable mergeStateStatus
      labels(first:50){nodes{name}}
      reviewThreads(first:100){
        totalCount
        nodes{
          id isResolved isOutdated path
          comments(first:1){nodes{author{login __typename}}}
        }
      }
    }
  }
}
"""

GRAPHQL_RESOLVE_MUTATION = (
    "mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}"
)

Verdict = namedtuple(
    "Verdict",
    "code form_matched reason stale_bot fresh_bot human counts labels mergeable merge_state_status undecidable",
)


class Undecidable(Exception):
    """读不到关键输入（gh 缺失 / API 失败 / 字段缺失）⇒ 退 3，绝不退 0。"""


# ── 纯函数（夹具可直调，无网络无副作用）──────────────────────────────────────

def is_bot_author(login, typename=None):
    """作者是不是机器人：`__typename == "Bot"`，或 login 以 `[bot]` 结尾。"""
    if typename == "Bot":
        return True
    return bool(login) and str(login).endswith(BOT_LOGIN_SUFFIX)


def parse_threads(pull_request):
    """GraphQL `reviewThreads.nodes` → 归一化线程列表（判定只吃这些字段）。"""
    threads = []
    for node in (pull_request.get("reviewThreads") or {}).get("nodes") or []:
        comments = ((node.get("comments") or {}).get("nodes") or [])
        author = (comments[0].get("author") or {}) if comments else {}
        login, typename = author.get("login"), author.get("__typename")
        threads.append({
            "id": node.get("id"),
            "is_resolved": bool(node.get("isResolved")),
            "is_outdated": bool(node.get("isOutdated")),
            "path": node.get("path") or "(未知路径)",
            "author": login or "(未知作者)",
            "is_bot": is_bot_author(login, typename),
        })
    return threads


def parse_checks(raw):
    """`gh pr checks --json name,state,bucket` 的 stdout → 列表；**读不到返回 None**（≠ 空列表）。"""
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, list):
        return None
    return [c for c in data if isinstance(c, dict)]


def checks_all_green(checks):
    """全绿 = 有检查、且没有 fail / pending / cancel（`skipping` 中性）。空集**不算**全绿。"""
    if not checks:
        return False
    for check in checks:
        bucket = str(check.get("bucket") or "").lower()
        state = str(check.get("state") or "").upper()
        if bucket in ("fail", "pending", "cancel"):
            return False
        if not bucket and state not in ("SUCCESS", "NEUTRAL", "SKIPPED"):
            return False
    return True


def check_counts(checks):
    counts = {"pass": 0, "fail": 0, "pending": 0, "total": 0}
    for check in checks or []:
        counts["total"] += 1
        bucket = str(check.get("bucket") or "").lower()
        if bucket == "fail":
            counts["fail"] += 1
        elif bucket == "pending":
            counts["pending"] += 1
        elif bucket == "cancel":
            counts["fail"] += 1
        elif bucket in ("pass", "skipping"):
            counts["pass"] += 1
        elif str(check.get("state") or "").upper() in ("SUCCESS", "NEUTRAL", "SKIPPED"):
            counts["pass"] += 1
    return counts


def build_snapshot(pull_request, checks):
    """GraphQL PR 载荷 + checks 读数 → 判定用的**归一化快照**（判定与取数分离）。"""
    return {
        "number": pull_request.get("number"),
        "state": pull_request.get("state"),
        "is_draft": bool(pull_request.get("isDraft")),
        "mergeable": pull_request.get("mergeable"),
        "merge_state_status": pull_request.get("mergeStateStatus"),
        "labels": [n.get("name") for n in (pull_request.get("labels") or {}).get("nodes") or []],
        "checks": checks,
        "threads": parse_threads(pull_request),
        "undecidable": pull_request.get("undecidable"),
    }


def decide(snapshot):
    """判定本体（纯函数）：返回三态退出码 + 证据 + 可行动的线程清单。"""
    checks = snapshot.get("checks")
    counts = check_counts(checks)
    labels = snapshot.get("labels") or []
    mergeable = snapshot.get("mergeable")
    merge_state = snapshot.get("merge_state_status")
    threads = snapshot.get("threads") or []
    unresolved = [t for t in threads if not t["is_resolved"]]
    stale_bot = [t for t in unresolved if t["is_bot"] and t["is_outdated"]]
    fresh_bot = [t for t in unresolved if t["is_bot"] and not t["is_outdated"]]
    human = [t for t in unresolved if not t["is_bot"]]
    blocking = [l for l in labels if l in BLOCKING_LABELS]

    def verdict(code, form, reason, undecidable=""):
        return Verdict(code, form, reason, stale_bot, fresh_bot, human, counts,
                       labels, mergeable, merge_state, undecidable)

    if snapshot.get("undecidable"):
        return verdict(EXIT_UNDECIDABLE, False, "无法判定", str(snapshot["undecidable"]))
    if snapshot.get("state") in ("MERGED", "CLOSED"):
        return verdict(EXIT_OK, False, f"PR 已 {snapshot['state']}，无需处理")
    if checks is None:
        return verdict(EXIT_UNDECIDABLE, False, "无法判定", "读不到 checks 读数（gh pr checks 未返回可解析 JSON）")
    if mergeable in (None, "UNKNOWN") or merge_state in (None, "UNKNOWN"):
        return verdict(EXIT_UNDECIDABLE, False, "无法判定",
                       f"mergeable={mergeable} / mergeStateStatus={merge_state} —— GitHub 仍在计算（§7.3：等 30~60s 再试）")

    if snapshot.get("is_draft"):
        return verdict(EXIT_OK, False, "PR 是 draft（draft 不参与 auto-merge）")
    if mergeable != "MERGEABLE":
        return verdict(EXIT_OK, False, f"mergeable={mergeable}（冲突/未就绪导致的 BLOCKED，不是本形态）")
    if blocking:
        return verdict(EXIT_OK, False, f"存在阻塞 label {blocking}（人工闸，BLOCKED 是有意的）")
    if merge_state != "BLOCKED":
        return verdict(EXIT_OK, False, f"mergeStateStatus={merge_state}（不是 BLOCKED）")
    if not checks_all_green(checks):
        return verdict(EXIT_OK, False,
                       f"检查未全绿（{counts['pass']} pass / {counts['fail']} fail / {counts['pending']} pending）"
                       "⇒ BLOCKED 属正常，先修检查")

    # 到这里 = 「全绿 + MERGEABLE + 无阻塞 label，却 BLOCKED」的形态**成立**
    if stale_bot or fresh_bot:
        return verdict(EXIT_HIT, True,
                       "全绿却 BLOCKED，且存在未解决的机器人评审线程 ⇒ required_conversation_resolution 生效")
    if human:
        return verdict(EXIT_OK, True,
                       f"未解决的是**人类**评审线程 {len(human)} 条：属人工评审护栏（issue #4231 明确保留），不自动 resolve")
    return verdict(EXIT_OK, True,
                   "无未解决评审线程 ⇒ BLOCKED 另有原因（缺 required review / 缺必填检查 / 队列中）")


# ── gh 取数（唯一的 IO 边界）─────────────────────────────────────────────────

def gh_run(args, gh_bin):
    try:
        return subprocess.run([gh_bin, *args], capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise Undecidable(f"找不到 gh 可执行文件 {gh_bin!r}（{exc}）") from exc
    except OSError as exc:
        raise Undecidable(f"无法执行 gh（{exc}）") from exc


def gh_repo(gh_bin):
    proc = gh_run(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], gh_bin)
    name = (proc.stdout or "").strip()
    if proc.returncode != 0 or not name:
        raise Undecidable(f"读不到仓库名（gh repo view 退出 {proc.returncode}）：{(proc.stderr or '').strip()[:200]}")
    return name


def fetch_pull_request(pr, repo, gh_bin):
    owner, _, name = repo.partition("/")
    proc = gh_run(["api", "graphql", "-f", f"query={GRAPHQL_PR_QUERY}",
                   "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"number={pr}"], gh_bin)
    try:
        payload = json.loads(proc.stdout or "")
    except ValueError:
        raise Undecidable(f"gh api graphql 未返回 JSON（退出 {proc.returncode}）："
                          f"{(proc.stderr or proc.stdout or '').strip()[:200]}")
    if payload.get("errors"):
        raise Undecidable(f"GraphQL 报错：{json.dumps(payload['errors'], ensure_ascii=False)[:200]}")
    node = ((payload.get("data") or {}).get("repository") or {}).get("pullRequest")
    if not node:
        raise Undecidable("GraphQL 未返回 pullRequest（PR 号 / 权限？）")
    return node


def fetch_checks(pr, repo, gh_bin):
    args = ["pr", "checks", str(pr), "--json", "name,state,bucket"]
    if repo:
        args += ["--repo", repo]
    proc = gh_run(args, gh_bin)
    checks = parse_checks(proc.stdout)
    if checks is None:
        raise Undecidable(f"gh pr checks 未返回可解析 JSON（退出 {proc.returncode}）："
                          f"{(proc.stderr or proc.stdout or '').strip()[:200]}")
    return checks


def read_snapshot(pr, repo=None, gh_bin="gh"):
    """取数 → 快照；任何读不到的关键输入都抛 `Undecidable`（由 main 转成 3）。"""
    repo = repo or gh_repo(gh_bin)
    node = fetch_pull_request(pr, repo, gh_bin)
    return build_snapshot(node, fetch_checks(pr, repo, gh_bin)), repo


def resolve_thread(thread_id, gh_bin):
    """执行 `resolveReviewThread`（唯一的写操作）；返回 (ok, 说明)。"""
    proc = gh_run(["api", "graphql", "-f", f"query={GRAPHQL_RESOLVE_MUTATION}",
                   "-F", f"id={thread_id}"], gh_bin)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip()[:200]
    return True, "已提交 resolve 请求"


# ── 输出（可行动：证据 + 一条能直接粘走的命令）───────────────────────────────

def resolve_command(thread_id, repo=None):
    cmd = ("gh api graphql -f query='mutation { resolveReviewThread(input:{threadId:\"%s\"}) "
           "{ thread { isResolved } } }'" % thread_id)
    if repo:
        cmd += f" --repo {repo}"
    return cmd


def render(verdict, pr, repo=None, apply=False):
    counts = verdict.counts
    labels = ", ".join(verdict.labels) if verdict.labels else "(无)"
    lines = [f"=== #4231 全绿却 BLOCKED 诊断 · PR #{pr} ==="]
    tag = {EXIT_OK: "✅ 未命中该形态", EXIT_HIT: "🎯 命中该形态", EXIT_UNDECIDABLE: "⚠️ 无法判定"}[verdict.code]
    lines.append(f"判定：{tag} —— {verdict.reason}")
    if verdict.undecidable:
        lines.append(f"原因：{verdict.undecidable}")
    lines.append(f"证据：checks {counts['pass']} pass / {counts['fail']} fail / {counts['pending']} pending"
                 f" · mergeable={verdict.mergeable} · mergeStateStatus={verdict.merge_state_status}"
                 f" · labels={labels}")
    if verdict.code == EXIT_UNDECIDABLE:
        return "\n".join(lines)

    if verdict.stale_bot or verdict.fresh_bot:
        lines.append("未解决的**机器人**评审线程：")
        for t in verdict.stale_bot:
            lines.append(f"  · [陈旧] id={t['id']} outdated=yes path={t['path']} 作者={t['author']} (bot)")
        for t in verdict.fresh_bot:
            lines.append(f"  · [非陈旧] id={t['id']} outdated=no path={t['path']} 作者={t['author']} (bot)"
                         " ⇒ 不自动 resolve（机器人指出的问题可能仍在），请人工确认后处理")
    if verdict.human:
        lines.append(f"未解决的**人类**评审线程 {len(verdict.human)} 条（需人工评审，不自动 resolve）：")
        for t in verdict.human:
            lines.append(f"  · id={t['id']} outdated={'yes' if t['is_outdated'] else 'no'}"
                         f" path={t['path']} 作者={t['author']}")

    if verdict.code == EXIT_HIT:
        lines.append("原因：main 分支保护的 required_conversation_resolution 生效 ⇒ 未解决评审线程把 PR 永久钉在"
                     " BLOCKED，且**没有任何检查会变红**（实证 #4218：手动 resolve 后 46 秒自动合并）")
        lines.append(f"可行动（{'--apply 已执行' if apply else 'dry-run：只读，未做任何写操作'}）：")
        for t in verdict.stale_bot:
            lines.append(f"  {resolve_command(t['id'], repo)}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="resolve_stale_bot_threads.py",
        description="#4231 全绿却 BLOCKED 的机器人评审线程判定（默认 dry-run，--apply 才 resolve）")
    parser.add_argument("pr", type=int, help="PR 号")
    parser.add_argument("--repo", default=None, help="OWNER/NAME（默认取 gh repo view）")
    parser.add_argument("--apply", action="store_true", help="真正调用 resolveReviewThread（默认只读）")
    args = parser.parse_args(argv)

    gh_bin = os.environ.get("SBT_GH_BIN", "gh")
    try:
        snapshot, repo = read_snapshot(args.pr, args.repo, gh_bin)
    except Undecidable as exc:
        snapshot, repo = {"undecidable": str(exc), "checks": None, "threads": []}, args.repo
    verdict = decide(snapshot)
    print(render(verdict, args.pr, repo, apply=args.apply))

    if not args.apply or verdict.code != EXIT_HIT:
        return verdict.code

    # --apply：只动「未解决 + bot + outdated」；人类线程与非陈旧 bot 线程一律不碰
    failed = []
    for t in verdict.stale_bot:
        ok, msg = resolve_thread(t["id"], gh_bin)
        print(f"  {'✅' if ok else '❌'} resolve {t['id']}：{msg}")
        if not ok:
            failed.append(t["id"])
    if failed:
        print(f"❌ {len(failed)} 条线程 resolve 失败：{', '.join(failed)}")
        return EXIT_HIT
    print(f"✅ 已解决 {len(verdict.stale_bot)} 条陈旧机器人线程。"
          f"复核：gh pr view {args.pr} --json mergeStateStatus（实测 resolve 后约 46 秒自动合并）")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
