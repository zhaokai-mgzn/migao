#!/usr/bin/env python3
"""dependabot 依赖 PR 的「分支落后 main ⇒ 合并结果 lock 与 package.json 不一致」自动收口。

## 病（2026-11-09 实测，关联 #8845）

一条 dependabot PR 落后 main 之后，**合并结果**（`refs/pull/<n>/merge`，也正是 squash 合入会落地的
形状）里的 `package.json` 与 `package-lock.json` 会不一致 —— 逐字读数（run 42325543438）：

    npm error code EUSAGE
    npm error `npm ci` can only install packages when your package.json and package-lock.json … are in sync
    npm error Missing: msw@2.15.0 from lock file
    npm error Missing: @mswjs/interceptors@0.41.9 from lock file

两侧各自都是自洽的：**只有合出来的那一棵树坏**。于是 required 腿恒红 ⇒ auto-merge 永不触发
⇒ PR 停在「没人合」，而**没有任何东西会自己变**（页面也没有「Update branch」按钮：
本仓分支保护 `strict: true` + 仓库 `allow_update_branch=false`）。

单变量反证：同一 CI npm 版本下，dependabot 自己 rebase 之后（2026-11-09T00:41Z）
#8830 的 `Demo path specs` 由 15s 红变 2m33s 绿、`E2E quality gate` 由红变绿 ⇒
**病根是「分支落后」，不是 npm 版本**。

## 判据（每条都对应一个真实读数）

1. **只动 dependabot 作者的 open PR** —— 人写的 PR 由人处置（`block/merge` 是人工闸）。
2. **draft / `block/merge` 跳过**：那是**有意不可合**，不是「该 rebase」。
3. **触发条件（二选一，任一成立即需 rebase）**：
   a. `mergeStateStatus ∈ {BEHIND, DIRTY}` —— 分支落后 / 冲突，GitHub 的 up-to-date 要求永远不满足；
   b. **合并结果的 lock 与 package.json 不一致** —— 即上面那条 EUSAGE 的因（本脚本自己算，不解析日志）。
4. **动作 = 评论 `@dependabot rebase`**（官方入口，由 dependabot 用**它自己的** npm 重建 lock）。
   ⛔ **不往分支推提交**：① 那会与 dependabot 的下一次推送抢写（§34.13 同一分支不许两个写者）；
   ② `GITHUB_TOKEN` 推送会被 GitHub 反递归抑制 ⇒ **新一轮 CI 根本不跑** ⇒ PR 卡死得更彻底。
5. **幂等 + 有界**：评论里带 `<!-- migao:dependabot-rebase:<head sha> -->`，
   **同一 head 只发一次**（rebase 后 head 变新，若仍坏才该再发 —— 这正是「有界」的含义）；
   每条 PR 累计**最多 `MAX_REBASE_REQUESTS` 次**，到顶 ⇒ 只出声（`::warning::` + summary），
   不再自动动作 —— 到顶说明「rebase 治不了」，需要人看。

## 三态退出码（`3` 不得当 `0` 读）

- `0`：无需动作，或动作全部成功（含「已达上限、只出声」）。
- `1`：有动作**失败**（评论被拒 / 权限 / GraphQL 报错）—— 可行动，重跑即可。
- `3`：**无法判定**（取数失败：取不到 merge 结果 / 读不到 lock）—— 不得渲染成「本 PR 没问题」。

## 边界（照实登记）

- 只覆盖 dependabot（npm / pip 等任意生态）：判据落在 `mergeStateStatus` 与 npm 的 lock 上，
  **非 npm 生态**只会命中 3a（落后/冲突），不会命中 3b —— 这不是缺陷，是射程。
- 不负责「人写的 PR 落后」（那是 `scripts/pr-merge-when-clean.sh` 的口径），也不改任何门禁语义。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_UNJUDGEABLE = 3

#: dependabot 在 GitHub 上的三种身份写法（`gh` 的读数在不同接口下不完全一致）。
BOT_LOGINS = ("app/dependabot", "dependabot[bot]", "dependabot")
#: 「人工闸」标签：打上即**有意不可合**，本脚本不许绕。
BLOCK_LABEL = "block/merge"
#: 幂等标记前缀（评论里隐藏 HTML 注释；按 **head sha** 去重）。
MARKER_PREFIX = "<!-- migao:dependabot-rebase:"
#: 每条 PR 的自动请求上限：到顶只出声，不再自动动作。
MAX_REBASE_REQUESTS = 2
#: 官方入口命令（dependabot 读评论触发）。
REBASE_COMMAND = "@dependabot rebase"


class GhError(RuntimeError):
    """`gh` 取数 / 动作失败（限流、权限、GraphQL 瞬时错误）。"""


class LockUnreadable(ValueError):
    """lock / manifest 的形状读不懂 ⇒ 无法判定（不得当「一致」读）。"""


def login_of(value):
    """`gh` 的 author 字段有时是 `{"login": …}`、有时是裸字符串 ⇒ 统一取登录名。"""
    if isinstance(value, dict):
        return value.get("login") or ""
    return value or ""


def marker_for(head_sha):
    return "%s%s -->" % (MARKER_PREFIX, head_sha)


def rebase_request_count(comments):
    """已发过几次 rebase 请求（含不同 head 的）。"""
    return sum(1 for c in comments or [] if MARKER_PREFIX in (c.get("body") or ""))


def already_requested(comments, head_sha):
    marker = marker_for(head_sha)
    return any(marker in (c.get("body") or "") for c in comments or [])


def lock_mismatches(manifest, lock):
    """`package.json` 声明了、`package-lock.json` 的 `packages` 里**没有条目**的依赖。

    这就是 `npm ci` 的 `Missing: <name>@<spec> from lock file` 的因（本脚本自己算，不解析日志）。
    形状读不懂 ⇒ 抛 `LockUnreadable`（**fail-closed**：判不了 ≠ 一致）。
    """
    if not isinstance(manifest, dict):
        raise LockUnreadable("package.json 不是对象")
    if not isinstance(lock, dict):
        raise LockUnreadable("package-lock.json 不是对象")
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        # lockfileVersion 1 没有 `packages` 段（本仓已全 v2/v3）⇒ 判不了，不许当一致。
        raise LockUnreadable("package-lock.json 没有 packages 段（lockfileVersion=%r）"
                             % (lock.get("lockfileVersion"),))
    declared = {}
    for field in ("dependencies", "devDependencies"):
        section = manifest.get(field) or {}
        if not isinstance(section, dict):
            raise LockUnreadable("package.json 的 %s 不是对象" % field)
        declared.update(section)
    missing = []
    for name in sorted(declared):
        if ("node_modules/" + name) not in packages:
            missing.append((name, declared[name]))
    return missing


def lock_dirs_from_files(files):
    """从 PR 的改动文件里取「lock 所在目录」——**不硬编码目录清单**（dependabot.yml 加目录自动覆盖）。"""
    dirs = []
    for item in files or []:
        path = item.get("path") if isinstance(item, dict) else item
        if not isinstance(path, str):
            continue
        if not path.endswith("/package-lock.json"):
            continue
        directory = path[: -len("/package-lock.json")]
        if directory not in dirs:
            dirs.append(directory)
    return dirs


def decide(pr, comments, lock_report):
    """纯判定。返回 `{"action": "skip"|"rebase"|"unjudgeable", "reason": str}`。

    - `pr`：`{number, author, isDraft, labels:[str], headRefOid, mergeStateStatus}`
    - `lock_report`：`None`（未探测）或 `{"dir": str, "missing": [(name, spec), …]}`
    """
    author = (pr.get("author") or "")
    if author not in BOT_LOGINS:
        return {"action": "skip", "reason": "非 dependabot 作者（%s）" % (author or "<空>")}
    if pr.get("isDraft"):
        return {"action": "skip", "reason": "draft（有意不可合）"}
    if BLOCK_LABEL in (pr.get("labels") or []):
        return {"action": "skip", "reason": "带 %s 标签（人工闸）" % BLOCK_LABEL}

    head = pr.get("headRefOid") or ""
    if already_requested(comments, head):
        return {"action": "skip", "reason": "同一 head 已请求过（幂等）"}
    if rebase_request_count(comments) >= MAX_REBASE_REQUESTS:
        return {"action": "skip",
                "reason": "已达自动请求上限 %d 次 ⇒ 需人工（rebase 治不了）" % MAX_REBASE_REQUESTS}

    state = (pr.get("mergeStateStatus") or "").upper()
    if state in ("BEHIND", "DIRTY"):
        return {"action": "rebase",
                "reason": "分支落后/冲突（mergeStateStatus=%s）" % state}

    if lock_report is None:
        return {"action": "unjudgeable", "reason": "合并结果的 lock 未探测（取数失败）"}
    missing = lock_report.get("missing") or []
    if missing:
        names = ", ".join("%s@%s" % (n, s) for n, s in missing[:5])
        more = "" if len(missing) <= 5 else " 等 %d 个" % len(missing)
        return {"action": "rebase",
                "reason": "%s 的合并结果 lock 缺条目：%s%s" % (lock_report.get("dir"), names, more)}
    return {"action": "skip", "reason": "锁与声明一致、且不落后"}


# ── gh 取数 / 动作（测试用 DEPENDABOT_REBASE_GH_BIN 替换成替身） ──────────────────
def gh_bin():
    return os.environ.get("DEPENDABOT_REBASE_GH_BIN", "gh")


def _gh(args):
    proc = subprocess.run([gh_bin(), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise GhError("gh %s ⇒ rc=%d：%s" % (" ".join(args[:2]), proc.returncode,
                                             (proc.stderr or proc.stdout).strip()[:400]))
    return proc.stdout


def _json(args):
    out = _gh(args)
    try:
        return json.loads(out) if out.strip() else {}
    except json.JSONDecodeError as exc:
        raise GhError("gh %s 返回的不是 JSON：%s" % (" ".join(args[:2]), exc))


def list_open_prs(repo, limit):
    return _json(["pr", "list", "--repo", repo, "--state", "open", "--limit", str(limit),
                  "--json", "number,author,isDraft,labels,headRefOid,mergeStateStatus,title"])


def pr_detail(repo, number):
    return _json(["pr", "view", str(number), "--repo", repo, "--json",
                  "number,author,isDraft,labels,headRefOid,mergeStateStatus,title,comments,files,mergeCommit"])


def read_file_at(repo, path, ref):
    payload = _json(["api", "repos/%s/contents/%s?ref=%s" % (repo, path, ref)])
    content = payload.get("content")
    if not isinstance(content, str):
        raise GhError("contents API 没给 content：%s@%s" % (path, ref))
    return base64.b64decode(content).decode("utf-8")


def probe_lock(repo, detail):
    """读**合并结果**（`mergeCommit.oid`）里的 manifest + lock，算缺条目。

    没有改动任何 lock 目录 ⇒ 返回 `{"dir": None, "missing": []}`（不适用，不是「一致」）。
    """
    dirs = lock_dirs_from_files(detail.get("files"))
    if not dirs:
        return {"dir": None, "missing": []}
    merge_sha = (detail.get("mergeCommit") or {}).get("oid")
    if not merge_sha:
        raise GhError("取不到 mergeCommit.oid（PR #%s 可能已冲突/不可合并）" % detail.get("number"))
    merged_missing = []
    for directory in dirs:
        manifest = json.loads(read_file_at(repo, "%s/package.json" % directory, merge_sha))
        lock = json.loads(read_file_at(repo, "%s/package-lock.json" % directory, merge_sha))
        merged_missing.extend((directory, name, spec) for name, spec in lock_mismatches(manifest, lock))
    if merged_missing:
        first_dir = merged_missing[0][0]
        return {"dir": first_dir,
                "missing": [(name, spec) for d, name, spec in merged_missing if d == first_dir]}
    return {"dir": dirs[0], "missing": []}


def request_rebase(repo, number, head_sha, reason):
    body = ("%s\n%s —— %s\n\n（本评论由 CI 自动发出：同一 head 只发一次；本仓分支保护要求"
            " up-to-date，落后分支的合并结果 lock 会与 package.json 不一致 ⇒ required 腿恒红。）"
            % (marker_for(head_sha), REBASE_COMMAND, reason))
    _gh(["pr", "comment", str(number), "--repo", repo, "--body", body])


def _write_summary(path, lines):
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="dependabot PR 落后 / 合并结果 lock 不一致 ⇒ 评论 @dependabot rebase（幂等、有界）")
    parser.add_argument("--repo", default=os.environ.get("GH_REPO", ""),
                        help="owner/repo（默认取 GH_REPO）")
    parser.add_argument("--pr", type=int, default=0, help="只处理这一条 PR（缺省 = 扫全部 open PR）")
    parser.add_argument("--limit", type=int, default=50, help="最多扫多少条 open PR")
    parser.add_argument("--dry-run", action="store_true", help="只打印判定，不发评论")
    parser.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY", ""),
                        help="step summary 落点")
    args = parser.parse_args(argv)

    if not args.repo:
        print("::error::缺 --repo（或 GH_REPO）⇒ 无法判定")
        return EXIT_UNJUDGEABLE

    try:
        if args.pr:
            targets = [pr_detail(args.repo, args.pr)]
        else:
            targets = list_open_prs(args.repo, args.limit)
    except GhError as exc:
        print("::error::取 open PR 列表失败 ⇒ 无法判定（不得当 0 读）：%s" % exc)
        return EXIT_UNJUDGEABLE

    actions, skipped, unjudged, failed = [], [], [], []
    exit_code = EXIT_OK

    for entry in targets:
        number = entry.get("number")
        if login_of(entry.get("author")) not in BOT_LOGINS:
            continue
        detail = dict(entry)
        try:
            if not args.pr:
                detail = pr_detail(args.repo, number)
        except GhError as exc:
            unjudged.append("#%s 取详情失败：%s" % (number, exc))
            exit_code = EXIT_UNJUDGEABLE
            continue

        pr = {"number": number,
              "author": login_of(detail.get("author")),
              "isDraft": bool(detail.get("isDraft")),
              "labels": [l.get("name") for l in (detail.get("labels") or []) if isinstance(l, dict)],
              "headRefOid": detail.get("headRefOid") or "",
              "mergeStateStatus": detail.get("mergeStateStatus") or ""}
        comments = detail.get("comments") or []

        # 只有走到「需要看 lock」时才付 API 取数成本（落后/冲突已足够判定）
        report = None
        state = (pr["mergeStateStatus"] or "").upper()
        if state not in ("BEHIND", "DIRTY") and pr["author"] in BOT_LOGINS \
                and not pr["isDraft"] and BLOCK_LABEL not in pr["labels"]:
            try:
                report = probe_lock(args.repo, detail)
            except (GhError, LockUnreadable, json.JSONDecodeError) as exc:
                unjudged.append("#%s 合并结果 lock 读不懂/读不到 ⇒ 无法判定：%s" % (number, exc))
                exit_code = EXIT_UNJUDGEABLE
                continue

        verdict = decide(pr, comments, report)
        if verdict["action"] == "rebase":
            if args.dry_run:
                actions.append("#%s ⇒ 将请求 rebase：%s" % (number, verdict["reason"]))
                continue
            try:
                request_rebase(args.repo, number, pr["headRefOid"], verdict["reason"])
            except GhError as exc:
                failed.append("#%s 请求 rebase 失败：%s" % (number, exc))
                exit_code = EXIT_FAIL
            else:
                actions.append("#%s ⇒ 已请求 rebase：%s" % (number, verdict["reason"]))
        elif verdict["action"] == "unjudgeable":
            unjudged.append("#%s：%s" % (number, verdict["reason"]))
            exit_code = EXIT_UNJUDGEABLE
        else:
            skipped.append("#%s ⇒ %s" % (number, verdict["reason"]))

    _write_summary(args.summary, ["### dependabot rebase 收口", ""]
                   + ["- ✅ %s" % a for a in actions]
                   + ["- ⏭️ %s" % s for s in skipped]
                   + ["- ⚠️ %s" % u for u in unjudged]
                   + ["- ❌ %s" % f for f in failed])

    for line in actions:
        print("✅ %s" % line)
    for line in skipped:
        print("⏭️  %s" % line)
    for line in unjudged:
        print("::warning::%s" % line)
    for line in failed:
        print("::error::%s" % line)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
