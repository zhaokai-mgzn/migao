#!/usr/bin/env python3
"""Sensitive Path Guard —— 陌生人 PR 不得**静默**改动 CI / 部署面（issue #8395）。

## 为什么必须是 `pull_request_target` + base 定义

公开仓里，`pull_request` 型 workflow 的**执行体就是 PR 里的那份定义** ⇒ fork PR 的
workflow 审批放行之后，攻击者可以再推一个 commit 改 `.github/workflows/pr-check.yml`，
把 16 条 required 检查**伪造为绿**（名字可自造，一条不跑）。「0 个必需 review」下，
那条绿就是唯一的合并依据。

本守卫的 workflow 定义在 **base 分支**、只检出 base（`ref: main`）、**不执行任何 PR 代码**，
判定只读 REST API 的文件清单 ⇒ 「改 workflow 自证清白」这条路被堵死。

## 判定（fail-closed）

1. `changed_files` 与分页取到的文件名条数**必须相等**，否则判红 —— 列不全就不能证明清白；
2. 命中 `SENSITIVE_PREFIXES` ⇒ 唯下列**三种**豁免之一才放行，且**都打印具名理由**（不静默）：
   - 标签 `guard/allow-sensitive-paths`（加标签需要 write 权限 = 人工动作）；
   - 作者是 bot（dependabot 升 action 版本这类自动 PR）；
   - 作者是仓库 owner（维护者自己的 PR）。
3. 退出码：`0` 放行 / `1` 策略判红 / `2` 判不了（API 失败、清单不全）—— `2` 也是红（fail-closed）。

用法（workflow 里）：`python3 .github/scripts/sensitive_path_guard.py --repo R --pr N --author A --author-type T --owner O`
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

#: 敏感面：改动它们等于改动「门禁 / 部署 / 密钥扫描」本身。目录以 `/` 结尾，文件按全名。
SENSITIVE_PREFIXES = (
    ".github/workflows/",
    ".github/scripts/",          # 守卫自身的实现 —— self-protecting
    "deploy/",
    ".githooks/",
    ".github/CODEOWNERS",
    ".gitleaksignore",
)

#: 人工豁免标签（加标签需要 write 权限，陌生账号加不了）。
EXEMPT_LABEL = "guard/allow-sensitive-paths"


def is_sensitive(path: str) -> bool:
    """路径是否落在敏感面（目录前缀 / 全名精确匹配，不做模糊包含）。"""
    for entry in SENSITIVE_PREFIXES:
        if entry.endswith("/"):
            if path.startswith(entry):
                return True
        elif path == entry:
            return True
    return False


def sensitive_hits(paths: list[str]) -> list[str]:
    return sorted(p for p in paths if is_sensitive(p))


def decide(
    paths: list[str],
    labels: list[str],
    author: str,
    author_type: str,
    owner: str,
    changed_files: int | None = None,
) -> tuple[bool, str]:
    """纯判定：→ `(allowed, reason)`。`allowed=False` ⇒ 判红。"""
    if changed_files is not None and len(paths) != changed_files:
        return False, (
            f"无法完整列出改动文件（取到 {len(paths)} / 声明 {changed_files}）"
            "⇒ 不能证明未命中敏感面，fail-closed"
        )
    hits = sensitive_hits(paths)
    if not hits:
        return True, f"未命中敏感路径（{len(paths)} 个改动文件）"
    named = "、".join(hits[:10]) + ("…" if len(hits) > 10 else "")
    if author_type == "Bot":
        return True, f"bot 作者豁免（{author}）⇒ 命中：{named}"
    if author and author == owner:
        return True, f"仓库 owner 豁免（{author}）⇒ 命中：{named}"
    if EXEMPT_LABEL in labels:
        return True, f"已加豁免标签 {EXEMPT_LABEL} ⇒ 命中：{named}"
    return False, (
        f"PR 改动了敏感面（{len(hits)} 个文件）：{named}。"
        f"维护者确认这些改动可信后，加标签 `{EXEMPT_LABEL}` 解除（本检查会随 labeled 事件重跑）"
    )


def _gh(*args: str) -> str:
    out = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} 失败 rc={out.returncode}：{(out.stderr or '').strip()[:400]}")
    return out.stdout


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def collect(repo: str, pr: int) -> tuple[list[str], list[str], int]:
    """→ `(changed_paths, labels, changed_files)`；任一读取失败 ⇒ 抛（调用方按 fail-closed 处理）。"""
    meta = json.loads(_gh("api", f"repos/{repo}/pulls/{pr}"))
    paths = _lines(_gh("api", "--paginate", f"repos/{repo}/pulls/{pr}/files?per_page=100", "--jq", ".[].filename"))
    labels = _lines(_gh("api", "--paginate", f"repos/{repo}/issues/{pr}/labels?per_page=100", "--jq", ".[].name"))
    return paths, labels, int(meta.get("changed_files") or 0)


def _summary(line: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sensitive Path Guard（issue #8395）")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--author", default="")
    ap.add_argument("--author-type", default="")
    ap.add_argument("--owner", default="")
    args = ap.parse_args(argv)

    try:
        paths, labels, changed_files = collect(args.repo, args.pr)
    except (RuntimeError, json.JSONDecodeError, ValueError) as exc:
        print(f"::error::Sensitive Path Guard 无法判定 PR #{args.pr}（fail-closed）：{exc}")
        return 2

    allowed, reason = decide(paths, labels, args.author, args.author_type, args.owner, changed_files)
    print(("✅ " if allowed else "❌ ") + f"PR #{args.pr}：{reason}")
    print(f"   改动文件 {len(paths)} 个 / 敏感命中 {len(sensitive_hits(paths))} 个")
    _summary(f"- Sensitive Path Guard：{'✅ 放行' if allowed else '❌ 判红'} —— {reason}")
    if allowed:
        return 0
    print(f"::error::Sensitive Path Guard：{reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
