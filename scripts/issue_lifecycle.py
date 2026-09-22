#!/usr/bin/env python3
"""issue_lifecycle — 「一个 issue 收尾」的**单一入口**：事件驱动清理，非定时。

## 这治的是什么（用户指示）

研发模式的收尾**原先靠人或 agent「记得」**：验证完要手动 `worktree remove` + `branch -D`
+ `push origin --delete` + 清 `pr-body-*.md` / `tests/tmp/*`。漏一步就留下垃圾，而
**没有任何东西会变红**（存量分支/工作区只增不减）。⇒ 本单把收尾做成**一条命令**并**自证干净**。

## 为什么是**事件驱动**、不是定时任务（用户裁定，2026-09-21）

① 无人值守地删东西**不安全**（`migao-wt/*` 就在清理半径内，而活锚软链目标曾指向工作区）；
② 每个周期都烧 CI 分钟、**浪费时间成本**。
⇒ 判定落在「一个包收尾」这一刻，且**只由人/agent 显式调用**触发（不新增 `schedule:`、不改 cron）。

## 判据（复用既有实现，不另写第二套）

「该分支的 PR 已合并」的判据**必须**是「有已合并 PR」（`gh pr list --head <b> --state merged`）——
**不得**用 `--merged` / `git cherry` / commit 可达性：本仓的合并方式含 **squash**
⇒ 原分支的提交**永远不是** `origin/main` 的祖先，`git cherry` 也全是 `+` 行
（`scripts/agent-presets-guard.py` 的 `_pr_merged_branches` 同因，实测漏判 21/62）。
**取不到 ⇒ 三态**（exit 3 = 无法判定，**不得当 0 读**）。
**未合并 ⇒ fail-closed，什么都不删**（保护在飞分支）。

批量判定**不逐分支轮询**（实测 9 个分支 `git ls-remote` >60s 超时）：一次 `gh pr list` 取全量
（复用 `agent-presets-guard.py` 的 `_pr_merged_branches`）。

## 🔴 活锚硬保护（本仓特有，issue #3956 实证）

`$HOME/.dsh/.agent-presets/migao` 是指向**专职只读镜像**的软链，而 `migao-wt/*` 的 worktree
属清理半径 ⇒ **任何删除前**先 `readlink`，把解析出的目标（及其父目录，当父目录是 preset 目录时）
排除在外。误删软链目标 ⇒ DSH **静默**加载不到研发模式（不报错，只是「模式不见了」）。
落码位置：`anchor_protected_paths()` + `protected_reason()`；守卫测试
`tests/unit_ci_workflows/test_issue_lifecycle_finish.py` 有**能单独变红**的注入。

## 过程产物 vs 仓库资产（清理半径）

清：`pr-body*.md`（PR body 落点）/ `tests/tmp/*` / `.pytest_cache` / `__pycache__`
（限仓根、`tests/`、`scripts/`；worktree 内残留随 worktree 一起消失）。
**不碰**：`acceptance/**`、`docs/**`、`.agent-presets/**`、`node_modules`、`.venv`、`backend/**`、
`frontend/**` —— 仓库资产与既有架构契约永不砍。

## 用法

    ./scripts/issue-lifecycle.sh finish <分支|工作区路径> [--dry-run]   # 收尾一个包（自证干净）
    ./scripts/issue-lifecycle.sh prune [--apply]                        # 批量：默认 dry-run，--apply 才删

退出码：0 = 成功（含幂等空转）；1 = 用法/找不到目标；2 = 未合并（fail-closed，什么都不删）；
3 = 无法判定（gh 不可用 / 离线）—— **不得当 0 读**。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANCHOR_ENV = "MIGAO_ANCHOR"
GH_ENV = "MIGAO_GH_BIN"
DEFAULT_ANCHOR = Path.home() / ".dsh" / ".agent-presets" / "migao"
DEFAULT_REF = "origin/main"
PROTECTED_BRANCHES = ("main", "master")

EXIT_OK, EXIT_USAGE, EXIT_UNMERGED, EXIT_UNKNOWN = 0, 1, 2, 3


def _load_guard():
    """按路径加载既有守卫模块（复用其 PR 判据与 worktree 解析，**不另写第二套**）。"""
    spec = importlib.util.spec_from_file_location("agent_presets_guard", HERE / "agent-presets-guard.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载守卫模块（判定本体缺失即门禁空转）：{HERE / 'agent-presets-guard.py'}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD = _load_guard()


# ── git 封装 ──────────────────────────────────────────────────────────────────

def git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败：{proc.stderr.strip()}")
    return proc


def main_root(cwd: Path) -> Path:
    """主工作区根（`--git-common-dir` 总是指向主仓库 .git，在 worktree 内亦然）。"""
    common = git("rev-parse", "--git-common-dir", cwd=cwd).stdout.strip()
    return Path(common).resolve().parent if common else cwd.resolve()

# ── 收尾台账（幂等的**判据**，不是装饰）────────────────────────────────────────
# 为什么需要：`finish` 之后分支/工作区**全都消失** ⇒ 「已收尾」与「从未存在」在**状态上不可区分**
# （见 tests 的 test_finish_is_idempotent 与 test_unknown_target_is_an_error 两条相反要求）。
# ⇒ 收尾成功时落一条记录；再次收尾据此判「无需再做」(0)，从未存在则仍报错(2)。
# 台账落在 **git common dir**（不是工作区）⇒ 不进 `git status`、不污染仓库、不被过程产物清理命中。
LEDGER_NAME = "migao-lifecycle-cleaned"


def git_common_dir(cwd: Path) -> Path:
    common = git("rev-parse", "--git-common-dir", cwd=cwd).stdout.strip()
    p = Path(common)
    return (p if p.is_absolute() else (cwd / p)).resolve()


def ledger_file(cwd: Path) -> Path:
    return git_common_dir(cwd) / LEDGER_NAME


def ledger_has(branch: str, cwd: Path) -> bool:
    f = ledger_file(cwd)
    if not f.exists():
        return False
    return any(
        line.split("\t", 1)[0].strip() == branch
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip()
    )


def ledger_add(branch: str, cwd: Path) -> None:
    try:
        with ledger_file(cwd).open("a", encoding="utf-8") as fh:
            fh.write(f"{branch}\t{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
    except OSError:
        pass  # 台账写不进去不得让收尾失败（清理已完成，台账只是幂等判据）


# ── 活锚硬保护 ────────────────────────────────────────────────────────────────

def anchor_protected_paths(anchor: Path | None = None) -> list[Path]:
    """**绝不允许被清理**的路径：活锚软链解析出的目标 + （父目录是 preset 目录时的）父目录。

    三态：软链解析失败 / 不是软链 / 不存在 ⇒ 空清单（没有活锚要保护，不是「已通过」）。
    """
    link = anchor if anchor is not None else Path(os.environ.get(ANCHOR_ENV) or DEFAULT_ANCHOR)
    try:
        resolved = Path(os.path.realpath(link)) if link.is_symlink() else None
    except OSError:
        resolved = None
    if resolved is None:
        return []
    protected = [resolved]
    parent = resolved.parent
    if parent.name == ".agent-presets" and parent.is_dir():
        protected.append(parent)
    return protected


def protected_reason(path: Path, protected: list[Path]) -> str | None:
    """该路径是否落在活锚保护半径内（是 ⇒ 返回可读原因）。"""
    real = Path(os.path.realpath(path))
    for p in protected:
        if real == p or real.is_relative_to(p):
            return (
                f"它是**活锚**（`$HOME/.dsh/.agent-presets/migao` → {p}）—— 删了 DSH 会**静默**"
                f"加载不到研发模式（issue #3956 实证）。活锚必须是**专职只读镜像**，不是工作区。"
            )
    return None


# ── PR 已合并判据（唯一判据）──────────────────────────────────────────────────

def gh_bin() -> str:
    return os.environ.get(GH_ENV) or "gh"


def branch_pr_merged(branch: str, cwd: Path) -> bool | None:
    """该分支是否有**已合并** PR：True / False / **None = 无法判定**。

    判据只有一条 —— GitHub 侧的 PR 状态（squash 合并下 commit 可达性与 `git cherry` 结构性失效）。
    """
    try:
        proc = subprocess.run(
            [gh_bin(), "pr", "list", "--head", branch, "--state", "merged",
             "--limit", "1", "--json", "number,state"],
            cwd=str(cwd), capture_output=True, text=True, timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    try:
        rows = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(rows, list):
        return None
    return any(isinstance(r, dict) and r.get("state") == "MERGED" for r in rows)


def all_merged_branches(cwd: Path) -> set[str] | None:
    """全量已合并 PR 的 head 分支（批量判定用，**不逐分支轮询**）。复用守卫的实现。"""
    return GUARD._pr_merged_branches(cwd)


# ── 过程产物清理 ──────────────────────────────────────────────────────────────

def artifact_paths(root: Path) -> list[Path]:
    """工作过程中产生的**过程产物**（清）；仓库资产**不在**此清单内。"""
    found: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.is_file() and re.match(r"^pr[-_.]?body", child.name, re.IGNORECASE):
            found.append(child)
        if child.name in (".pytest_cache", "__pycache__") and child.is_dir():
            found.append(child)
    tmp = root / "tests" / "tmp"
    if tmp.is_dir():
        found.extend(sorted(p for p in tmp.iterdir()))
    for sub in ("tests", "scripts"):
        cache = root / sub / "__pycache__"
        if cache.is_dir():
            found.append(cache)
    return found


def clean_artifacts(root: Path, apply: bool) -> list[Path]:
    """清过程产物（`apply=False` 只列出）。返回**实际删除/将删除**的清单。"""
    targets = artifact_paths(root)
    for path in targets:
        if apply:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
    return targets


# ── 目标解析 ──────────────────────────────────────────────────────────────────

class Target:
    """一个待收尾的目标：worktree（可缺）+ 分支（可缺）。"""

    def __init__(self, branch: str, path: str | None, registered: bool, local: bool, remote: bool):
        self.branch, self.path, self.registered, self.local, self.remote = branch, path, registered, local, remote

    @property
    def exists(self) -> bool:
        return bool(self.registered or self.local or self.remote)


def resolve_target(target: str, cwd: Path) -> Target:
    """按分支名或工作区路径解析出「worktree 路径 + 分支名」的现状。"""
    path: str | None = None
    branch = ""
    if Path(target).is_dir():
        path = str(Path(target).resolve())
        branch = GUARD.wt_branch_of(Path(path)) or ""
    for e in GUARD._worktrees(cwd):
        if path is None and e["branch"] == target:
            path, branch = e["path"], e["branch"]
        if path is not None and Path(e["path"]).resolve() == Path(path).resolve():
            branch = branch or e["branch"]
    branch = branch or target
    local = git("show-ref", "--verify", "--quiet", f"refs/heads/{branch}", cwd=cwd, check=False).returncode == 0
    remote = git("show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}", cwd=cwd, check=False).returncode == 0
    return Target(branch, path, path is not None, local, remote)


# ── 删除动作（复用既有语义）──────────────────────────────────────────────────

def remove_worktree(path: str, cwd: Path) -> None:
    git("worktree", "remove", path, "--force", cwd=cwd)


def delete_local_branch(branch: str, cwd: Path) -> bool:
    if branch in PROTECTED_BRANCHES:
        print(f"🛡️  拒绝删除主干分支：{branch}")
        return False
    git("branch", "-D", branch, cwd=cwd)
    return True


def delete_remote_branch(branch: str, cwd: Path) -> bool:
    proc = git("push", "origin", "--delete", branch, cwd=cwd, check=False)
    if proc.returncode != 0:
        print(f"⚠️  远程分支删除失败（可能已被删/无权限）：{branch}\n     {proc.stderr.strip()}")
        return False
    return True


# ── 自证干净 ──────────────────────────────────────────────────────────────────

def verify_clean(target: Target, cwd: Path, root: Path) -> bool:
    """收尾后**自证**：worktree / 本地分支 / 远程分支 三项都为空或不存在。"""
    print("\n── 自证干净 ──")
    ok = True
    registered = {Path(e["path"]).resolve() for e in GUARD._worktrees(cwd)}
    gone_wt = not (target.path and Path(target.path).resolve() in registered)
    print(f"  {'✅' if gone_wt else '❌'} worktree list 里不再有它"
          + (f"（{target.path}）" if target.path else "（本就没有注册 worktree）"))
    ok = ok and gone_wt

    gone_local = git("show-ref", "--verify", "--quiet", f"refs/heads/{target.branch}",
                     cwd=cwd, check=False).returncode != 0
    print(f"  {'✅' if gone_local else '❌'} 本地分支不存在：{target.branch}")
    ok = ok and gone_local

    ls_remote = git("ls-remote", "--heads", "origin", target.branch, cwd=cwd, check=False)
    gone_remote = not ls_remote.stdout.strip()
    print(f"  {'✅' if gone_remote else '❌'} 远程分支不存在：origin/{target.branch}")
    ok = ok and gone_remote

    status = git("status", "--porcelain", cwd=root, check=False).stdout.strip()
    if not status:
        print("  ✅ 主工作区 git status --porcelain 为空")
    else:
        print(f"  ⚠️  主工作区仍有 {len(status.splitlines())} 条**既有**产物（非本次产生，如实登记）：")
        for line in status.splitlines()[:10]:
            print(f"       {line}")
    return ok


# ── 收尾：一个包 ──────────────────────────────────────────────────────────────

def cmd_finish(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    root = main_root(cwd)
    target = resolve_target(args.target, cwd)
    if not target.exists:
        if ledger_has(target.branch, cwd) or ledger_has(args.target, cwd):
            print(f"✅ 已收尾（收尾台账已记录：{target.branch or args.target}）—— 无需再做。")
            return EXIT_OK
        print(f"❌ 找不到目标（分支/工作区都不存在）：{args.target}", file=sys.stderr)
        return EXIT_USAGE

    print(f"🧹 收尾：{target.branch}"
          + (f"（worktree {target.path}）" if target.path else "（无注册 worktree）")
          + ("  [dry-run]" if args.dry_run else ""))

    protected = anchor_protected_paths()
    if target.path:
        why = protected_reason(Path(target.path), protected)
        if why:
            print(f"❌ 拒绝清理：{target.path}", file=sys.stderr)
            print(f"   {why}", file=sys.stderr)
            print("   ⇒ 什么都不删（活锚保护是硬保护，见 scripts/issue_lifecycle.py 的"
                  "anchor_protected_paths）", file=sys.stderr)
            return EXIT_UNMERGED

    merged = branch_pr_merged(target.branch, cwd)
    if merged is None:
        print("⏭️  无法判定「PR 已合并」（gh 不可用 / 未登录 / 离线）—— 判据**未跑**，"
              "故**什么都不删**（fail-closed）。", file=sys.stderr)
        return EXIT_UNKNOWN
    if not merged:
        print(f"❌ 分支 {target.branch} **未合并**（GitHub 上无已合并 PR）⇒ 什么都不删。", file=sys.stderr)
        print("   这是**在飞分支**的保护：收尾只在 PR 已合并后进行（squash 合并下 commit 可达性"
              "与 `git cherry` 结构性失效，故判据只认 PR 状态）。", file=sys.stderr)
        return EXIT_UNMERGED

    if args.dry_run:
        print("   ✅ PR 已合并。dry-run：不删任何东西。要真删请去掉 --dry-run。")
        return EXIT_OK

    if target.path:
        remove_worktree(target.path, cwd)
        print(f"✅ 已移除工作区：{target.path}")
    if target.local:
        if delete_local_branch(target.branch, cwd):
            print(f"✅ 已删除本地分支：{target.branch}")
    if target.remote:
        if delete_remote_branch(target.branch, cwd):
            print(f"✅ 已删除远程分支：origin/{target.branch}")

    removed = clean_artifacts(root, apply=True)
    print(f"🧽 已清过程产物 {len(removed)} 项（pr-body* / tests/tmp/* / .pytest_cache / __pycache__）")
    for path in removed:
        print(f"     - {path}")

    ledger_add(target.branch, cwd)

    ok = verify_clean(target, cwd, root)
    print("\n" + ("✅ 收尾完成，工作区干净。" if ok else "⚠️  收尾完成，但自证有未清项（见上）。"))
    return EXIT_OK if ok else EXIT_UNMERGED


# ── 批量：所有已注册 worktree（默认 dry-run）──────────────────────────────────

def cmd_prune(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    root = main_root(cwd)
    mode = "APPLY（真删）" if args.apply else "dry-run（零删除）"
    print(f"🧹 批量收尾（{mode}）—— 对所有已注册 worktree 做同样的判定\n")

    merged_set = all_merged_branches(cwd)
    protected = anchor_protected_paths()
    root_resolved = root.resolve()
    removable: list[Target] = []
    skipped: list[tuple[str, str]] = []
    unknown = 0

    for entry in GUARD._worktrees(cwd):
        path, branch = entry["path"], entry["branch"]
        if Path(path).resolve() == root_resolved:
            skipped.append((path, "主工作区，永不判可移除"))
            continue
        if not Path(path).is_dir():
            skipped.append((path, "目录已不存在（stale worktree 记录）→ `git worktree prune`"))
            continue
        if not branch:
            skipped.append((path, "detached HEAD，无分支可核合入状态"))
            continue
        why = protected_reason(Path(path), protected)
        if why:
            skipped.append((path, "**活锚保护**：" + why))
            continue
        if merged_set is None:
            unknown += 1
            skipped.append((path, "无法判定「PR 已合并」（gh 不可用）⇒ 不动"))
            continue
        if branch not in merged_set:
            skipped.append((path, f"分支 {branch} 未合并（GitHub 上无已合并 PR）⇒ 不动"))
            continue
        removable.append(Target(branch, path, True,
                                local=True, remote=True))

    print(f"── 可收尾：{len(removable)} 个 ──")
    for t in removable:
        print(f"  ✅ {t.path}  （分支 {t.branch}）")
    if not removable:
        print("  （无）")
    print(f"\n── 跳过 {len(skipped)} 个：")
    for path, why in skipped:
        print(f"  ⚠️  {path}：{why}")

    if merged_set is None:
        print("\n⏭️  「PR 已合并」这条判据**未跑**（gh 不可用 / 未登录 / 离线）"
              "⇒ 一个都不删（exit 3 = 无法判定，不得当 0 读）。", file=sys.stderr)
        return EXIT_UNKNOWN

    if not args.apply:
        print("\nℹ️  这是 dry-run（默认）—— **零删除**。要真删：./scripts/issue-lifecycle.sh prune --apply")
        return EXIT_OK

    failures = 0
    for t in removable:
        print(f"\n🧹 收尾：{t.branch}（{t.path}）")
        remove_worktree(t.path, cwd)
        if t.local and delete_local_branch(t.branch, cwd):
            print(f"✅ 已删除本地分支：{t.branch}")
        if delete_remote_branch(t.branch, cwd):
            print(f"✅ 已删除远程分支：origin/{t.branch}")
        if not verify_clean(t, cwd, root):
            failures += 1

    removed = clean_artifacts(root, apply=True)
    print(f"\n🧽 已清过程产物 {len(removed)} 项")
    print("✅ 批量收尾完成。" if not failures else f"⚠️  {failures} 个目标自证有未清项。")
    return EXIT_OK if not failures else EXIT_UNMERGED


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="issue-lifecycle",
        description="一个 issue 收尾的单一入口（事件驱动清理：worktree / 本地+远程分支 / 过程产物）",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_finish = sub.add_parser("finish", help="收尾一个包：验证 PR 已合并 → 删 worktree/本地分支/远程分支 → 清过程产物 → 自证")
    p_finish.add_argument("target", help="分支名或工作区路径")
    p_finish.add_argument("--dry-run", action="store_true", help="只判定与打印，不删任何东西")
    p_finish.set_defaults(func=cmd_finish)

    p_prune = sub.add_parser("prune", help="批量收尾所有已注册 worktree（默认 dry-run）")
    p_prune.add_argument("--apply", action="store_true", help="真删（默认只打印清单）")
    p_prune.set_defaults(func=cmd_prune)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
