#!/usr/bin/env python3
"""agent-presets-guard — `.agent-presets/**` 版本单调性守卫 + worktree 存量体检（issue #3851）。

## 这守的是什么（地雷）

worktree 的 `.agent-presets/**` 是**创建时刻的快照**；此后 main 上预设再推进，工作区**不会自动跟上**
⇒ 这些文件相对 `origin/main` 就是「改动」（内容在**回退**）⇒ 一条 `git add -A` + push 就提交一个
**把研发模式回退若干版本**的 PR，而 **CI 不看 `.agent-presets/**` 的版本 ⇒ 不红**。

- **第一层防线（创建路径）**：`scripts/dev-worktree.sh add` 建完工作区后自动刷新到 `origin/main`。
- **第二层防线（提交路径，本脚本）**：`check` 判定暂存/工作区的 `.agent-presets/**` 是否构成
  **版本下降** ⇒ 命中即**非零退出**（fail-closed）。**合法升级必须绿**（改研发模式本身不能被堵死）。
- **第三层防线（机械安全网，别的单在做）**：`#3843` 的统一审计 `drift_audit --check` 将加
  「`.agent-presets/**` 版本单调性」守卫。本脚本与之**互补**：本脚本管**提交路径**（增量、贴合工作区），
  审计管**全库机械对账**（存量、定时）。详见 `docs/wiki/DEV-FLOW.md` 的「预设快照地雷」节。
  （本文件的落地单是 `#3859`；事实单是 `#3851`。）

## 为什么不用 `git update-index --skip-worktree`

那会把**合法的预设改动**（改研发模式本身）一起吞掉 —— 「眼不见为净」在这里等于把正事也堵死。
本脚本只**判定版本方向**，升级照样放行。

## 用法

    # 提交路径守卫（默认同时看暂存区与工作区；有任何一处版本下降即 exit 1）
    python3 scripts/agent-presets-guard.py check
    python3 scripts/agent-presets-guard.py check --source index     # 只看暂存区
    python3 scripts/agent-presets-guard.py check --source worktree  # 只看工作区文件
    python3 scripts/agent-presets-guard.py check --ref origin/main

    # 存量体检（只打印清单，绝不删除；--dry-run 必须显式给出）
    python3 scripts/agent-presets-guard.py prune --dry-run

退出码：0 = 绿；1 = 判定为「版本下降 / 不可判定」（fail-closed）；2 = 用法错误。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

PRESETS_DIR = ".agent-presets/"
DEFAULT_REF = "origin/main"
#: worktree 里唯一带 `version:` 的预设文件形态（技能 SKILL.md）。
#: 其余预设文件（preset.yml / agent.cordis.yml / README.md）**无版本号**，不参与单调性判定，
#: 只由创建路径的刷新负责带上 main 的最新内容。
VERSION_FILE_RE = re.compile(r"/skills/[^/]+/SKILL\.md$")


class GitError(RuntimeError):
    """git 调用不可用/不可判定 —— 一律 fail-closed，不得退化成「放行」。"""


def git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} 失败（exit {proc.returncode}）：{proc.stderr.strip()}")
    return proc


def parse_version(text: str) -> str | None:
    """从 SKILL.md 的 YAML frontmatter 里取 `version:`。

    只认**首个 frontmatter 块**（第 1 行 `---` 到下一个 `---`）内的顶层标量，
    避免正文里的 `version:` 字样（本文件自己的文档、版本沿革里的叙述）被误当版本号。
    按 YAML 标量规则丢掉行尾注释（`#` 起），并剥引号。
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for raw in lines[1:]:
        if raw.strip() == "---":
            break
        m = re.match(r"^version\s*:\s*(.+)$", raw)
        if not m:
            continue
        val = m.group(1).split("#", 1)[0].strip().strip("'\"")
        return val or None
    return None


def version_key(version: str) -> tuple[int, ...]:
    """`1.28.0` → (1, 28, 0)。非数字段（如 `1.29.0-rc1`）取数字前缀。"""
    parts: list[int] = []
    for chunk in version.split("."):
        m = re.match(r"^(\d+)", chunk.strip())
        if not m:
            raise ValueError(f"无法解析版本号：{version!r}")
        parts.append(int(m.group(1)))
    if not parts:
        raise ValueError(f"空版本号：{version!r}")
    return tuple(parts)


def blobs_equal(ref: str, path: str, source: str, cwd: Path) -> bool | None:
    """ref 版内容 vs 被检内容是否逐字节相同。None = 不可判定（路径在 ref 侧不存在）。"""
    existed = git("cat-file", "-e", f"{ref}:{path}", cwd=cwd, check=False)
    if existed.returncode != 0:
        return None
    if source == "worktree":
        target = (cwd / path)
        if not target.is_file():
            return False
        content = target.read_text(encoding="utf-8")
    else:
        content = git("show", f":{path}", cwd=cwd).stdout
    ref_content = git("show", f"{ref}:{path}", cwd=cwd).stdout
    return content == ref_content


def ref_version(ref: str, path: str, cwd: Path) -> str | None:
    proc = git("show", f"{ref}:{path}", cwd=cwd, check=False)
    if proc.returncode != 0:
        return None
    return parse_version(proc.stdout)


def changed_paths(ref: str, source: str, cwd: Path) -> list[str]:
    """被检的 `.agent-presets/**` 路径（相对仓库根）。

    `--diff-filter=d` 排除**删除**路径（只判「版本下降」这一种回退；预设在基准里被删是**另一类**
    回退，归 `#3843` 的 `drift_audit --check` 全库对账管，本脚本不越界）。
    """
    if source == "index":
        proc = git("diff", "--cached", "--name-only", "--diff-filter=d", ref, cwd=cwd, check=False)
        # 无 HEAD/无索引基线时退化到「暂存 vs HEAD」
        if proc.returncode != 0:
            proc = git("diff", "--cached", "--name-only", "--diff-filter=d", cwd=cwd)
        paths = proc.stdout.splitlines()
    else:
        proc = git("diff", "--name-only", "--diff-filter=d", ref, cwd=cwd)
        paths = proc.stdout.splitlines()
    return [p for p in paths if p.startswith(PRESETS_DIR)]


def check_source(ref: str, source: str, cwd: Path, out=sys.stdout, seen: dict | None = None) -> int:
    """单来源判定。返回 0（绿）/ 1（红）。

    `seen` 跨来源共享：同一路径在另一来源已被报过（如 `git checkout <sha> -- <path>` 会**同时**改
    工作区与索引）就**只报一次** —— 否则 `both` 模式把同一条降级打印两遍，读起来像两个问题。
    """
    seen = {} if seen is None else seen
    try:
        paths = changed_paths(ref, source, cwd)
    except GitError as exc:
        print(f"❌ [{source}] 无法判定（fail-closed）：{exc}", file=out)
        return 1

    label = {"index": "暂存区", "worktree": "工作区文件"}[source]
    downgrades: list[str] = []
    upgrades: list[str] = []
    forks: list[str] = []
    unchecked: list[str] = []

    for path in paths:
        if seen.get(path, "").startswith("downgrade"):
            print(f"  ℹ️  {path}：{label}同为此降级（已在另一来源报出，不重复列）", file=out)
            continue
        if not VERSION_FILE_RE.search(path):
            if seen.get(path) != "unchecked":
                unchecked.append(path)
                seen[path] = "unchecked"
            continue
        target = (cwd / path)
        if source == "index":
            proc = git("show", f":{path}", cwd=cwd, check=False)
            new_text = proc.stdout if proc.returncode == 0 else ""
        else:
            new_text = target.read_text(encoding="utf-8") if target.is_file() else ""
        new_v = parse_version(new_text)
        base_v = ref_version(ref, path, cwd)

        if base_v is None:
            print(f"❌ [{label}] {path}：{ref} 侧不存在或读不出版本 —— 不可判定（fail-closed）", file=out)
            return 1
        if new_v is None:
            print(f"❌ [{label}] {path}：取不到 `version:`（{ref} 侧为 {base_v}）—— 不可判定（fail-closed）", file=out)
            return 1
        try:
            new_k, base_k = version_key(new_v), version_key(base_v)
        except ValueError as exc:
            print(f"❌ [{label}] {path}：版本号不可比较（{exc}）—— 不可判定（fail-closed）", file=out)
            return 1

        if new_k < base_k:
            seen[path] = "downgrade"
            downgrades.append(
                f"  ❌ {path}\n     版本下降：{base_v} → {new_v}（相对 {ref}，来源：{label}）\n"
                f"     修：git checkout {ref} -- {PRESETS_DIR}"
            )
        elif new_k > base_k:
            seen[path] = "upgrade"
            upgrades.append(f"  ✅ {path}：{base_v} → {new_v}（合法升级，来源：{label}）")
        else:
            same = blobs_equal(ref, path, source, cwd)
            if same is False:
                seen[path] = "fork"
                forks.append(
                    f"  ⚠️  {path}：版本同为 {new_v} 但**内容与 {ref} 不同**（分叉，不是升级；来源：{label}）\n"
                    f"     多为「在旧快照上改了预设」⇒ 请 rebase 到最新 {ref} 后再改，避免把旧内容带回去"
                )
            else:
                seen[path] = "same"
                print(f"  ✅ {path}：版本与 {ref} 相同（{new_v}）", file=out)

    for line in upgrades:
        print(line, file=out)
    for line in forks:
        print(line, file=out)
    for line in unchecked:
        print(f"  ℹ️  {line}：无 `version:` 字段，不参与单调性判定", file=out)

    if downgrades:
        print(f"\n❌ 检出 {len(downgrades)} 处 `.agent-presets/**` **版本下降**（相对 {ref}）—— 拒绝提交：", file=out)
        for line in downgrades:
            print(line, file=out)
        print(
            "\n根因：worktree 的 `.agent-presets/**` 是**创建时刻快照**，main 推进后工作区不会自动跟上；\n"
            "      `git add -A` 就会把它当作改动提交（**内容回退**），而 CI 不看预设版本 ⇒ 不红。\n"
            f"修：git checkout {ref} -- {PRESETS_DIR}   # 然后重跑本检查\n"
            "     （若你**就是**要改研发模式：先把分支 rebase 到最新 main，再在此基础上改 + 升 version）",
            file=out,
        )
        return 1

    if not paths:
        print(f"  ⏭️  [{label}] 无 `.agent-presets/**` 变更（与 {ref} 对比）—— 本来源未跑判定", file=out)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    cwd = Path(args.repo).resolve()
    sources = [args.source] if args.source != "both" else ["index", "worktree"]
    print(f"🔎 `.agent-presets/**` 版本单调性守卫（基准 {args.ref}）")
    seen: dict = {}
    rc = 0
    for source in sources:
        rc |= check_source(args.ref, source, cwd, seen=seen)
    if rc == 0:
        print("✅ 通过：无 `.agent-presets/**` 版本下降（升级与「与基准相同」均放行）")
    return rc


def _worktrees(cwd: Path) -> list[dict]:
    proc = git("worktree", "list", "--porcelain", cwd=cwd)
    entries: list[dict] = []
    cur: dict = {}
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            if cur:
                entries.append(cur)
            cur = {"path": line.split(" ", 1)[1], "branch": "", "sha": ""}
        elif line.startswith("branch refs/heads/") and cur:
            cur["branch"] = line[len("branch refs/heads/"):]
        elif line.startswith("HEAD ") and cur:
            cur["sha"] = line.split(" ", 1)[1]
        elif line.startswith("detached") and cur:
            cur["branch"] = ""
    if cur:
        entries.append(cur)
    return entries


def _unmerged_commits(ref: str, branch: str, cwd: Path) -> int:
    """该分支相对 ref 还有多少提交**未被合入**（`git cherry` 的 `+` 行数）。"""
    proc = git("cherry", ref, branch, cwd=cwd, check=False)
    if proc.returncode != 0:
        return -1
    return sum(1 for line in proc.stdout.splitlines() if line.startswith("+ "))


def _merged_into(ref: str, branch: str, cwd: Path) -> bool:
    """分支是否**已合入** ref。

    squash 合并后 commit 可达性不是判据（§17.3/§17.4），故：
    ① 祖先可达 → 已合入；② 否则用 `git cherry` 看有无「未进 upstream」的提交（`+` 行）。
    """
    if not branch:
        return False
    if git("merge-base", "--is-ancestor", branch, ref, cwd=cwd, check=False).returncode == 0:
        return True
    return _unmerged_commits(ref, branch, cwd) == 0


def _locked_branches(cwd: Path) -> set[str]:
    """活跃会话锁涉及的分支（PID 仍存活）—— 被锁的工作区一律不判「可安全移除」。

    锁目录一律按 **common git dir** 定位（worktree 内的 `$WT/.git` 是指针文件、不是目录，
    直接拼 `.git/sessions` 会永远读不到 —— 那会让守卫**静默失效**）。
    """
    common = git("rev-parse", "--git-common-dir", cwd=cwd, check=False)
    lock_dir = Path(common.stdout.strip() or (cwd / ".git"))
    if not lock_dir.is_absolute():
        lock_dir = cwd / lock_dir
    lock_dir = lock_dir / "sessions"
    if not lock_dir.is_dir():
        return set()
    alive: set[str] = set()
    for f in lock_dir.glob("*.lock"):
        try:
            fields = f.read_text(encoding="utf-8").split("|")
        except OSError:
            continue
        pid = fields[0].strip() if fields else ""
        branch = fields[2].strip() if len(fields) > 2 else ""
        if not (pid.isdigit() and branch):
            continue
        try:
            os.kill(int(pid), 0)
        except (OSError, ValueError):
            continue
        alive.add(branch)
    return alive


def cmd_prune(args: argparse.Namespace) -> int:
    cwd = Path(args.repo).resolve()
    if not args.dry_run:
        print("❌ 本子命令**只出判定与清单，不执行删除**（存量工作区可能有未合并工作）。", file=sys.stderr)
        print("   请传 --dry-run 看清单；真删请按清单后打印的单条命令人工执行。", file=sys.stderr)
        return 2
    ref = args.ref
    entries = _worktrees(cwd)
    root = Path(git("rev-parse", "--show-toplevel", cwd=cwd).stdout.strip())
    locked = _locked_branches(cwd)

    safe: list[tuple[str, str]] = []
    manual: list[tuple[str, str, str]] = []
    for e in entries:
        path, branch = e["path"], e["branch"]
        if Path(path).resolve() == root.resolve():
            manual.append((path, branch or "(detached)", "主工作区，永不判可移除"))
            continue
        if not Path(path).is_dir():
            manual.append((path, branch or "(detached)", "目录已不存在（stale worktree 记录）→ 用 `git worktree prune` 清理"))
            continue
        dirty = git("status", "--porcelain", cwd=Path(path), check=False).stdout.strip()
        reasons = []
        if dirty:
            reasons.append(f"工作树不干净（{len(dirty.splitlines())} 条改动）")
        if not branch:
            reasons.append("detached HEAD，无分支可核合入状态")
        elif branch in locked:
            reasons.append("有活跃会话锁（可能有会话在用）")
        elif not _merged_into(ref, branch, cwd):
            ahead = _unmerged_commits(ref, branch, cwd)
            reasons.append(
                f"分支未合入 {ref}（{ahead if ahead >= 0 else '?'} 个提交未进 upstream，可能仍有未合并工作）"
            )
        if reasons:
            manual.append((path, branch or "(detached)", "；".join(reasons)))
        else:
            safe.append((path, branch))

    print(f"🧹 worktree 存量体检（基准 {ref}，工作区共 {len(entries)} 个）—— **只出清单，不删除**\n")
    print(f"── 可安全移除（分支已合入 {ref} + 工作树干净 + 无活跃锁）：{len(safe)} 个 ──")
    for path, branch in safe:
        print(f"  ✅ {path}  （分支 {branch}）")
    if not safe:
        print("  （无）")
    print(f"\n── 需人看（其余 {len(manual)} 个）：")
    for path, branch, why in manual:
        print(f"  ⚠️  {path}  （{branch}）：{why}")
    print(
        "\n如何真删（**人工逐条确认后执行**，本脚本不代劳）：\n"
        "  ./scripts/dev-worktree.sh rm <分支或路径> --delete-branch\n"
        f"⚠️ 判据是「已合入 {ref}」的**内容级**判定（祖先可达 + `git cherry` 无 `+` 行）；\n"
        "   若你不确定，先 `git -C <path> log --oneline -3` 与 `git status` 人工过一遍。"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-presets-guard",
        description="`.agent-presets/**` 版本单调性守卫（提交路径 fail-closed）+ worktree 存量体检（只列清单）",
    )
    parser.add_argument("--repo", default=".", help="仓库根（默认当前目录）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="判定被检内容是否构成 `.agent-presets/**` 版本下降")
    p_check.add_argument("--ref", default=DEFAULT_REF, help=f"基准 ref（默认 {DEFAULT_REF}）")
    p_check.add_argument(
        "--source", choices=["both", "index", "worktree"], default="both",
        help="both=暂存区+工作区（默认）；index=只看 `git diff --cached`；worktree=只看工作区文件",
    )
    p_check.set_defaults(func=cmd_check)

    p_prune = sub.add_parser("prune", help="worktree 存量体检（只打印清单，不删除）")
    p_prune.add_argument("--ref", default=DEFAULT_REF, help=f"合入判定基准（默认 {DEFAULT_REF}）")
    p_prune.add_argument("--dry-run", action="store_true", help="必须显式给出；本子命令只出清单")
    p_prune.set_defaults(func=cmd_prune)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
