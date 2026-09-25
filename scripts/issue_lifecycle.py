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
    ./scripts/issue-lifecycle.sh land <分支> [--dry-run] [--from 步骤] [--ci-timeout 秒]
    ./scripts/issue-lifecycle.sh reap-merged [--apply] [--except 分支]  # 自动收尾（默认 dry-run）

### `land`：一条命令完成「落地」（用户裁定 2026-09-24）

**为什么**：集成侧原先逐个手工做 `rebase` → `gate` → `gh pr ready` → 轮询等合并 →
`finish` →（改过预设再）`preset-anchor-refresh`，一晚重复十几次（用户逐字：
「我不希望每天要花 token 浪费在基建上和定期清理工作区」）。⇒ 固定序列做成**一条命令 + 一段总结**。

**🔴 顺序即安全顺序**（`LAND_STEPS`，执行体 `for` **遍历**它 —— 顺序只有一个来源）：

| # | 步骤 | 为什么必须在这个位置 |
|---|---|---|
| ① | `rebase` | 一切判定都要基于最新主线；用仓内入口 `dev-worktree.sh rebase`（**禁裸 rebase/merge**），先 `git fetch origin main`（fetch 不是 rebase/merge） |
| ② | `gate` | **判红即立即停**：不 ready、不等 CI、不收尾 |
| ③ | `ready` | ⚠️ **本步自己没有前置判据** —— 唯一的保护就是「②必须先跑且必须绿」这条顺序。把 `gh pr ready` 提到 `gate` 之前 = **把闸摘掉**（红的分支会被推成 ready 并交给 auto-merge） |
| ④ | `wait-ci` | `gh pr checks <PR> --watch`（**一次阻塞调用**，不写 sleep 轮询）；超时可配（`--ci-timeout`，默认 1800s）⇒ 超时 exit 3（未判定 ≠ 绿） |
| ⑤ | `wait-merge` | 合并是 GitHub 侧异步的 ⇒ **单发**读一次 `gh pr view --json state,mergedAt`（gh 2.97.0 的 `pr view` **没有** `--watch`，实测）；未观察到合并 ⇒ 报「未观察」+ 可续跑出口，**不猜** |
| ⑥ | `finish` | 只在**已确认合并**后收尾（`cmd_finish` 自己 fail-closed 复核「已合并」⇒ 双保险） |
| ⑦ | `preset-refresh` | 变更集含 `.agent-presets/**` ⇒ 跑 `scripts/preset-anchor-refresh.sh`（§18.2 硬纪律：活锚落后 = drift 面硬漂移）；不含 ⇒ **跳过并打印原因** |

`--from <步骤>` 只允许从 `LAND_RESUMABLE_FROM` 起（`wait-ci`/`wait-merge`/`finish`/`preset-refresh`）
—— **`rebase`/`gate`/`ready` 永不可跳过**，否则「顺序即安全顺序」失效。
幂等：PR 已 `MERGED`（= 「已合并但没人收尾」形态）⇒ 自动只做 ⑥⑦，其余逐步打「跳过 + 原因」。

### `reap-merged`：新工作前把「已合并但没人收尾」的自动收掉（用户裁定 2026-09-24）

**为什么**：`migao-wt/` 下有 77 个 worktree，其中一批是「PR 已合并但没人收尾」，
**没有任何机制会提醒或代办**（实测一晚手工清 15 个）。⇒ 在**建新工作区之前**（`dev-worktree.sh add`
调一行）把这一类收掉；仍是**事件驱动**，不新增 `schedule`/cron（用户 2026-09-21 裁定）。

判定口径（**一条**取数、两个条件同刻看，禁一半快照一半实时）：`gh pr list --state all` ⇒
**有已合并 PR** 且 **无 open PR**。理由：分支可能被复用（既有 merged 又有 open）⇒ 只认「已合并」
会删掉正在飞的那条 PR。另加四条 fail-closed 保护（任一命中即**不删**）：① 主干分支
② 活锚保护 ③ 有**活跃会话锁**（PID 存活 ⇒ 可能正在用）④ 是某个 open PR 的 **base**（stacked）。
worktree 必须在工作区根（`MIGAO_WT_BASE`，默认 `<主仓库根>/../migao-wt`）之下 ⇒ 半径外的检出
（别人的手工检出）**一律不动**。

**零动作也要出声**（G6）：没有可收尾的 ⇒ 打印「本轮零动作 + 逐类原因计数」——
「我判了、都不该动」必须与「我没跑」长得不一样。

`--no-artifacts`：跳过「过程产物清理」。理由 = 主工作区根是**跨会话共享写面**（§2.3 第 8 条同族）：
别人的 `pr-body-*.md` 可能正躺在那里用着 ⇒ `dev-worktree.sh add` 的**自动**收尾走这个口径；
显式 `finish` / `prune --apply` 的既有行为**不变**（它们由操作者针对自己的包调用）。

### 判据的替身注入点（只换 CLI/边界，不 mock 被测函数）

    MIGAO_GH_BIN=...              # gh 可执行文件（沿用既有替身注入点）
    MIGAO_DEVTREE_BIN=...         # dev-worktree.sh（默认 <主仓库根>/scripts/dev-worktree.sh）
    MIGAO_VERIFY_BIN=...          # verify-all.sh（默认 <分支检出>/verify-all.sh —— gate 必须在**分支自己的检出**里跑）
    MIGAO_PRESET_REFRESH_BIN=...  # preset-anchor-refresh.sh
    MIGAO_WT_BASE=...             # 工作区根（同 dev-worktree.sh）
    MIGAO_ANCHOR=...              # 活锚路径（默认 $HOME/.dsh/.agent-presets/migao）

退出码：0 = 成功（含幂等空转与「零动作」）；1 = 用法/找不到目标；2 = fail-closed（判红 / 未合并 /
有目标被拒）—— 该删的照删、不该删的一个不删；3 = **无法判定**（gh 不可用 / 离线 / CI 未跑完）——
**不得当 0 读**。
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
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANCHOR_ENV = "MIGAO_ANCHOR"
GH_ENV = "MIGAO_GH_BIN"
DEFAULT_ANCHOR = Path.home() / ".dsh" / ".agent-presets" / "migao"
DEFAULT_REF = "origin/main"
PROTECTED_BRANCHES = ("main", "master")

EXIT_OK, EXIT_USAGE, EXIT_UNMERGED, EXIT_UNKNOWN = 0, 1, 2, 3
TIMEOUT_RC = 124  # `_run` 的超时哨兵：必须与「真判红」分开（超时 = 无法判定 ⇒ exit 3）

# 替身注入点（只换 CLI/边界，不 mock 被测函数 —— 见模块 docstring）
DEVTREE_ENV = "MIGAO_DEVTREE_BIN"
VERIFY_ENV = "MIGAO_VERIFY_BIN"
PRESET_REFRESH_ENV = "MIGAO_PRESET_REFRESH_BIN"
WT_BASE_ENV = "MIGAO_WT_BASE"
DEFAULT_CI_TIMEOUT = 1800
PR_LIMIT = 500  # 一次取数的上限（与 GUARD._pr_merged_branches 同量级；截断后果见 read_pr_rows 调用点）
#: 临时（点号）worktree 的出声阈值（issue #5480 漏洞 1）：**只报不删**（无人值守删除不安全）
DOT_WT_WARN_THRESHOLD = 3

# ── `land` 的**顺序即安全顺序**（唯一顺序源：执行体 `for` 遍历它，不手写第二套）────────
# 把 `ready` 提到 `gate` 之前 ⇒ 把「gate 这道闸」摘掉（`ready` 自己没有前置判据）。
# 判据（计划序 + **实跑序**）见 tests/unit_ci_workflows/test_lifecycle_land_and_reap.py。
LAND_STEPS: tuple[str, ...] = (
    "rebase", "gate", "ready", "wait-ci", "wait-merge", "finish", "preset-refresh",
)
# `--from` 只允许从这些步骤起 —— `rebase`/`gate`/`ready` **永不可跳过**（跳了 = 顺序锁破）。
LAND_RESUMABLE_FROM: tuple[str, ...] = ("wait-ci", "wait-merge", "finish", "preset-refresh")


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


# ── 外部命令封装（land）：超时/缺失都不抛异常，而是回一个**可判**的结果 ──────────────

def _run(argv: list[str], cwd: Path, timeout: int | None = None) -> subprocess.CompletedProcess:
    """跑一条外部命令。超时 ⇒ `returncode = TIMEOUT_RC`（**无法判定 ≠ 判红**，调用方必须分开处置）。"""
    try:
        return subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, TIMEOUT_RC, "", f"超时（>{timeout}s）")
    except (FileNotFoundError, OSError) as exc:
        return subprocess.CompletedProcess(argv, 127, "", f"{type(exc).__name__}: {exc}")


def _tail(text: str | None, lines: int = 12) -> str:
    rows = [r for r in (text or "").strip().splitlines() if r.strip()]
    return "\n".join(f"     │ {r}" for r in rows[-lines:])


def _devtree_script(root: Path) -> str:
    return os.environ.get(DEVTREE_ENV) or str(root / "scripts" / "dev-worktree.sh")


def _verify_script(wt: Path) -> str:
    """gate 必须在**分支自己的检出**里跑（它按 `git diff origin/main...HEAD` 取变更集）。"""
    return os.environ.get(VERIFY_ENV) or str(wt / "verify-all.sh")


def _preset_refresh_script(root: Path) -> str:
    return os.environ.get(PRESET_REFRESH_ENV) or str(root / "scripts" / "preset-anchor-refresh.sh")


def worktree_path_of(branch: str, cwd: Path) -> Path | None:
    """该分支已注册 worktree 的路径（无 ⇒ None）。复用守卫的解析，不另写第二套。"""
    for entry in GUARD._worktrees(cwd):
        if entry["branch"] == branch:
            return Path(entry["path"])
    return None


def current_branch(path: Path) -> str | None:
    """该检出当前所在的分支（detached HEAD ⇒ None）。

    ⚠️ 为什么自己写：`agent-presets-guard.py` **没有** `wt_branch_of`（那是 dev-worktree.sh 的
    bash 函数），而 `resolve_target()` 里那句 `GUARD.wt_branch_of(...)` 因此**必抛 AttributeError**
    —— 只走 `finish <工作区路径>`（文档承诺的用法）才会踩到，故既有单测从未覆盖到。
    实测（2026-09-24）：`./scripts/issue-lifecycle.sh finish <worktree 路径> --dry-run`
    ⇒ `AttributeError: module 'agent_presets_guard' has no attribute 'wt_branch_of'`。
    """
    proc = git("rev-parse", "--abbrev-ref", "HEAD", cwd=path, check=False)
    name = proc.stdout.strip()
    return name if (proc.returncode == 0 and name and name != "HEAD") else None


# ── PR 读数（**一次取数**同时给出「有无 open PR」与「有无已合并 PR」）────────────────

PR_FIELDS = "number,state,isDraft,url,mergedAt,files"


class PrReading:
    """一个分支的 PR 现状：open / merged / none / **unknown**（未知 ≠ 无）。"""

    def __init__(self, state: str, number: int | None = None, is_draft: bool = False,
                 url: str = "", merged_at: str = "", files: list[str] | None = None):
        self.state, self.number, self.is_draft = state, number, is_draft
        self.url, self.merged_at, self.files = url, merged_at, list(files or [])

    @property
    def touches_presets(self) -> bool:
        return any(p.startswith(".agent-presets/") for p in self.files)


def _files_of(row: dict) -> list[str]:
    files = row.get("files")
    if not isinstance(files, list):
        return []
    return [f.get("path") for f in files if isinstance(f, dict) and f.get("path")]


def read_pr(branch: str, cwd: Path) -> PrReading:
    """`gh pr list --head <branch> --state all`（**一次**取数）⇒ 四态。

    一次取数给出**同刻**的两个事实（禁一半快照一半实时）：①有没有 open PR ②有没有已合并 PR。
    分支被复用时（既 open 又有 merged）⇒ **优先按 open 处置**（fail-closed：在飞的那个优先）。
    """
    proc = _run([gh_bin(), "pr", "list", "--head", branch, "--state", "all",
                 "--limit", "10", "--json", PR_FIELDS], cwd=cwd, timeout=60)
    if proc.returncode != 0:
        return PrReading("unknown")
    try:
        rows = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return PrReading("unknown")
    if not isinstance(rows, list):
        return PrReading("unknown")
    open_rows = [r for r in rows if isinstance(r, dict) and r.get("state") == "OPEN"]
    merged_rows = [r for r in rows if isinstance(r, dict) and r.get("state") == "MERGED"]
    if open_rows:
        row = open_rows[0]
        return PrReading("open", row.get("number"), bool(row.get("isDraft")),
                         row.get("url") or "", "", _files_of(row))
    if merged_rows:
        row = merged_rows[0]
        return PrReading("merged", row.get("number"), False,
                         row.get("url") or "", row.get("mergedAt") or "", _files_of(row))
    return PrReading("none")


def read_merge_state(number: int, cwd: Path) -> tuple[str, str] | None:
    """**单发**读一次合并状态（`gh pr view <num> --json state,mergedAt`）；取不到 ⇒ None。

    ⚠️ gh 2.97.0 的 `gh pr view` **没有** `--watch`（只有 `--web`，实测 `gh pr view --help`）
    ⇒ 「等合并」只能是「`gh pr checks --watch` 阻塞返回后**单发**读一次」，
    **不引入 sleep 轮询**（口径：等待不轮询）。
    """
    proc = _run([gh_bin(), "pr", "view", str(number), "--json", "state,mergedAt"], cwd=cwd, timeout=120)
    if proc.returncode != 0:
        return None
    try:
        row = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(row, dict):
        return None
    return str(row.get("state") or ""), str(row.get("mergedAt") or "")


# ── land：一条命令完成「落地」（顺序 = LAND_STEPS，执行体遍历它）──────────────────

class StepResult:
    """一步的读数：done / skipped / failed / stopped（**跳过也必须写清为什么**）。"""

    def __init__(self, step: str, status: str = "pending", why: str = "", code: int = EXIT_OK):
        self.step, self.status, self.why, self.code = step, status, why, code

    def line(self) -> str:
        icon = {"done": "✅", "skipped": "⏭️", "failed": "❌", "stopped": "⏸️"}.get(self.status, "…")
        return f"{self.step:<14} {icon} {self.why}"


def push_after_rebase(branch: str, wt: Path) -> tuple[bool, str]:
    """把 rebase 后的**新历史**推到远端（`--force-with-lease`）。→ (是否成功, 读数)

    🔴 为什么必须有这一步（issue #5489，2026-09-25 实测）：`land` 的 `rebase` 步原先**只 rebase 不推送**
    ⇒ rebase 重写历史后，`ready` / `wait-ci` 看到的仍是**远端旧 head**：等的是**别人那次提交**的 CI
    （§23.7 A1「判定对象与数据不同刻」同族），而且 PR 可能在**缺 commit** 的状态下被合并
    （当天实测：`git push` 被拒 `non-fast-forward`，而 ready+arm 已经执行）。
    `--force-with-lease` 在「远端有新提交（别人推过）」时**仍会拒**（fail-closed，不覆盖别人的工作）。
    """
    proc = _run(["git", "push", "--force-with-lease", "origin", f"HEAD:refs/heads/{branch}"], cwd=wt, timeout=300)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip()
    return True, f"已推 origin/{branch}（--force-with-lease）"


def assert_head_pushed(branch: str, wt: Path) -> tuple[bool, str]:
    """断言「本地 HEAD 已推到 `origin/<branch>`」→ (是否同步, 读数)。

    防的是同一条病灶的**另一半**：即使本次没 rebase（例如从 `wait-ci` 续跑），只要本地有**未推送**的提交，
    `wait-ci` 等的就**不是本次内容**。取不到 head（fetch 失败 / 空结果）⇒ **无法判定 ⇒ 停**（fail-closed）。
    """
    fetch = _run(["git", "fetch", "--quiet", "origin", branch], cwd=wt, timeout=120)
    if fetch.returncode != 0:
        return False, "`git fetch origin <branch>` 失败 ⇒ 无法判定远端 head（不继续，避免等错对象）"
    local = git("rev-parse", "HEAD", cwd=wt, check=False).stdout.strip()
    remote = git("rev-parse", f"origin/{branch}", cwd=wt, check=False).stdout.strip()
    if not local or not remote:
        return False, "取不到本地/远端 head ⇒ 无法判定"
    if local != remote:
        return False, (f"本地 HEAD {local[:9]} ≠ origin/{branch} {remote[:9]} ⇒ **你要等的 CI 不是本次内容**"
                       f"（先推送；rebase 过就 `git push --force-with-lease`）")
    return True, f"本地 HEAD == origin/{branch}（{local[:9]}）"


def _land_do_step(step: str, ctx: dict, args: argparse.Namespace) -> StepResult:
    branch, root, wt, pr = ctx["branch"], ctx["root"], ctx["wt"], ctx["pr"]

    if step == "rebase":
        # fetch **不是** rebase/merge（禁令针对裸 rebase/merge）—— 不 fetch 就谈不上「rebase 到**最新** main」
        fetch = _run(["git", "fetch", "origin", "main"], cwd=root, timeout=300)
        if fetch.returncode != 0:
            print(_tail(fetch.stderr))
            return StepResult(step, "failed", "`git fetch origin main` 失败 ⇒ 停（无法保证 rebase 到**最新** main）",
                              EXIT_UNMERGED)
        proc = _run(["bash", _devtree_script(root), "rebase", branch], cwd=root, timeout=900)
        if proc.returncode != 0:
            print(_tail(proc.stderr or proc.stdout))
            return StepResult(step, "failed", "rebase 失败 ⇒ 停（入口 = dev-worktree.sh rebase；禁裸 rebase/merge）",
                              EXIT_UNMERGED)
        pushed, why_push = push_after_rebase(branch, wt)
        if not pushed:
            print(_tail(why_push))
            return StepResult(step, "failed",
                              "rebase 后**推送失败** ⇒ 停（远端仍是旧 head，继续 ready/等 CI 会等错对象；"
                              "若远端有新提交，先核对再重试）", EXIT_UNMERGED)
        return StepResult(step, "done",
                          f"已 rebase 到最新 origin/main 并推送（{why_push}）")

    if step == "gate":
        print("   🔍 跑 ./verify-all.sh gate（在**分支自己的检出**里；与 CI 同规则）")
        proc = _run(["bash", _verify_script(wt), "gate"], cwd=wt, timeout=3600)
        print(_tail(proc.stdout or proc.stderr))
        if proc.returncode != 0:
            return StepResult(step, "failed",
                              "`./verify-all.sh gate` **判红** ⇒ 立即停：不 ready、不等 CI、不收尾（exit 2）",
                              EXIT_UNMERGED)
        return StepResult(step, "done", "gate 绿")

    if step == "ready":
        in_sync, why_sync = assert_head_pushed(branch, wt)
        print(f"   🔎 同步断言：{why_sync}")
        if not in_sync:
            return StepResult(step, "failed",
                              f"{why_sync} ⇒ 停（**不 ready、不等 CI**：否则等的是旧 head 的 CI）",
                              EXIT_UNMERGED)
        if not pr.is_draft:
            return StepResult(step, "skipped", f"PR #{pr.number} 已是 ready ⇒ 不重复调用 `gh pr ready`")
        proc = _run([gh_bin(), "pr", "ready", str(pr.number)], cwd=root, timeout=120)
        if proc.returncode != 0:
            print(_tail(proc.stderr or proc.stdout))
            return StepResult(step, "failed", f"`gh pr ready {pr.number}` 失败 ⇒ 停", EXIT_UNMERGED)
        return StepResult(step, "done", f"PR #{pr.number} 已转 ready（在 gate 绿**之后**）")

    if step == "wait-ci":
        print(f"   ⏳ 一次阻塞等 CI：`gh pr checks {pr.number} --watch`（超时上限 {args.ci_timeout}s；"
              "不写 sleep 轮询；超时 ⇒ exit 3，不得当绿读）")
        proc = _run([gh_bin(), "pr", "checks", str(pr.number), "--watch"], cwd=root, timeout=args.ci_timeout)
        if proc.returncode == TIMEOUT_RC:
            return StepResult(step, "stopped",
                              f"CI 在 {args.ci_timeout}s 内没跑完 ⇒ **未判定**（exit 3）。续跑："
                              f"./scripts/issue-lifecycle.sh land {branch} --from wait-ci", EXIT_UNKNOWN)
        print(_tail(proc.stdout))
        if proc.returncode != 0:
            return StepResult(step, "failed",
                              f"CI 判红/取消（复核：`gh pr checks {pr.number}`）⇒ 停：不收尾、不猜已合并",
                              EXIT_UNMERGED)
        return StepResult(step, "done", "CI 全绿（`gh pr checks --watch` 退出 0）")

    if step == "wait-merge":
        print(f"   ⏳ 单发读合并状态：`gh pr view {pr.number} --json state,mergedAt`"
              "（pr view 无 --watch，故不引入 sleep 轮询）")
        reading = read_merge_state(pr.number, root)
        if reading is None:
            return StepResult(step, "stopped", "合并状态取不到（gh 不可用 / 未登录 / 离线）⇒ 未判定（exit 3）",
                              EXIT_UNKNOWN)
        state, merged_at = reading
        if state == "MERGED":
            ctx["merged_at"] = merged_at
            return StepResult(step, "done", f"已合并（mergedAt {merged_at or '未知'}）")
        if state == "CLOSED":
            return StepResult(step, "failed", "PR 已 CLOSED 但**未合并** ⇒ 不收尾（fail-closed）", EXIT_UNMERGED)
        return StepResult(step, "stopped",
                          f"checks 已结束但仍**未观察到合并**（state={state}）—— 本步不猜、不收尾。续跑："
                          f"./scripts/issue-lifecycle.sh land {branch} --from wait-merge", EXIT_UNMERGED)

    if step == "finish":
        print("   🧹 收尾（复用 finish 的判定本体，不另写第二套）：worktree + 本地/远程分支 + 过程产物")
        rc = cmd_finish(argparse.Namespace(target=branch, dry_run=False))
        if rc != EXIT_OK:
            return StepResult(step, "failed",
                              f"finish 非零退出（exit {rc}）⇒ 见上方清单（未合并 / 活锚保护 / 自证未清）",
                              EXIT_UNMERGED)
        return StepResult(step, "done", "worktree + 本地分支 + 远程分支已清，且已自证干净")

    if step == "preset-refresh":
        if ctx["files"] and not pr.touches_presets:
            return StepResult(step, "skipped", "变更集不含 `.agent-presets/**` ⇒ 无需刷活锚（§18.2 只在预设变更后要求）")
        why = ("变更集含 `.agent-presets/**`（§18.2 硬纪律）" if pr.touches_presets
               else "变更集取不到 ⇒ **保守跑一次**（刷活锚幂等、零风险 —— 宁可多刷不可漏刷）")
        proc = _run(["bash", _preset_refresh_script(root)], cwd=root, timeout=600)
        print(_tail(proc.stdout or proc.stderr, 6))
        if proc.returncode != 0:
            return StepResult(step, "failed",
                              "活锚刷新失败（落后 ⇒ drift 面硬漂移）。手工复跑：./scripts/preset-anchor-refresh.sh",
                              EXIT_UNMERGED)
        return StepResult(step, "done", f"已跑 `preset-anchor-refresh.sh`（{why}）")

    return StepResult(step, "failed", f"未知步骤 {step}（LAND_STEPS 与实现不同步）⇒ fail-closed", EXIT_USAGE)


def cmd_land(args: argparse.Namespace) -> int:
    branch = args.branch
    cwd = Path.cwd()
    root = main_root(cwd)
    # ⚠️ 必须离开可能被删掉的检出目录：`finish` 会把调用者所在的 worktree 删掉，
    #    之后 `Path.cwd()` / `git -C <cwd>` 会当场失败（进程 cwd 已被 unlink）。
    os.chdir(root)
    print(f"🚀 land：{branch}")
    print(f"   顺序（顺序即安全顺序）：{' → '.join(LAND_STEPS)}")

    wt = worktree_path_of(branch, cwd)
    if wt is None or not wt.is_dir():
        print(f"❌ 分支 {branch} 没有可用的 worktree 检出（rebase / gate 都需要它）⇒ 零动作。", file=sys.stderr)
        print(f"   先建：./scripts/dev-worktree.sh add {branch}", file=sys.stderr)
        return EXIT_USAGE

    pr = read_pr(branch, cwd)
    if pr.state == "unknown":
        print("⏭️  无法判定 PR 状态（gh 不可用 / 未登录 / 离线）—— 判据**未跑** ⇒ 零动作（exit 3，不得当 0 读）。",
              file=sys.stderr)
        return EXIT_UNKNOWN
    if pr.state == "none":
        print(f"❌ 分支 {branch} 在 GitHub 上没有任何 PR ⇒ 零动作。", file=sys.stderr)
        print("   先开 **draft** PR 再来 land（改动全部 commit 完再开 PR：native auto-merge 会秒合，"
              "后补的 commit 会搁浅）。", file=sys.stderr)
        return EXIT_USAGE

    ctx = {"branch": branch, "root": root, "wt": wt, "pr": pr, "files": list(pr.files), "merged_at": ""}
    declared: list[StepResult] = []
    plan = list(LAND_STEPS)
    if pr.state == "merged":
        declared = [StepResult(s, "skipped", "PR 已合并 ⇒ 该步目的已达成（不重跑 rebase/gate，也不重复 ready）")
                    for s in ("rebase", "gate", "ready", "wait-ci", "wait-merge")]
        plan = ["finish", "preset-refresh"]
        print(f"ℹ️  PR #{pr.number} 已是 **MERGED**（= 「已合并但没人收尾」形态）⇒ 只做 finish + preset-refresh")
    if args.from_step:
        if args.from_step in plan:
            plan = plan[plan.index(args.from_step):]
            print(f"ℹ️  --from {args.from_step}：从该步起（前面的步骤按 --from 跳过；rebase/gate/ready 永不可跳）")
        else:
            print(f"ℹ️  --from {args.from_step} 落在已达成区间（PR 已合并）⇒ 从 {plan[0]} 起")

    if args.dry_run:
        print("ℹ️  --dry-run（**零动作**）：计划 = " + " → ".join(plan))
        for r in declared:
            print(f"   {r.line()}")
        print(f"   前置读数：worktree={wt}；PR #{pr.number}（state={pr.state}，draft={pr.is_draft}）；"
              f"变更集 {len(pr.files)} 个文件" + ("（含 .agent-presets/**）" if pr.touches_presets else ""))
        print("   要真做：去掉 --dry-run。")
        return EXIT_OK

    results: list[StepResult] = list(declared)
    for step in plan:                      # ★ 顺序的唯一来源：遍历 LAND_STEPS（不是手写调用序列）
        print(f"\n── [{len(results) + 1}] {step} ──")
        res = _land_do_step(step, ctx, args)
        results.append(res)
        print(f"   {res.line()}")
        if res.status in ("failed", "stopped"):
            break
    return _land_summary(branch, pr, results, ctx)


def _land_summary(branch: str, pr: PrReading, results: list[StepResult], ctx: dict) -> int:
    rc = next((r.code for r in results if r.status in ("failed", "stopped") and r.code), EXIT_OK)
    done = [r.step for r in results if r.status == "done"]
    skipped = [f"{r.step}（{r.why}）" for r in results if r.status == "skipped"]
    bad = next((r for r in results if r.status in ("failed", "stopped")), None)

    print("\n════════ land 总结 ════════")
    print(f"分支：{branch}    PR：#{pr.number} {pr.url}")
    for i, r in enumerate(results, 1):
        print(f"  {i}. {r.line()}")
    print(f"本轮做了什么：{'、'.join(done) if done else '（无）'}")
    print(f"跳过了什么：{('；'.join(skipped)) if skipped else '（无）'}")
    if bad is None:
        print(f"一行结论：✅ land 完成 —— {branch} 已合并并收尾（PR #{pr.number}）")
    else:
        icon = "⏸️" if bad.status == "stopped" else "❌"
        print(f"一行结论：{icon} land 停在 [{bad.step}]：{bad.why.splitlines()[0]}")
        print("           ⇒ 未收尾的分支保持原样（fail-closed）；复查后可续跑。")
    return rc


# ── reap-merged：新工作前把「已合并但没人收尾」的自动收掉 ──────────────────────────

class Candidate:
    """一个待判定对象：分支（+ 可能存在的 worktree / 本地 / 远程引用）。"""

    def __init__(self, branch: str, path: Path | None = None, local: bool = False,
                 remote: bool = False, stale: bool = False):
        self.branch, self.path, self.local, self.remote, self.stale = branch, path, local, remote, stale


def wt_base_dir(cwd: Path) -> Path:
    env = os.environ.get(WT_BASE_ENV)
    if env:
        return Path(env).resolve()
    return (main_root(cwd).parent / "migao-wt").resolve()


def dot_worktrees(cwd: Path) -> list[Path]:
    """`migao-wt/.xxx` 这类**临时（点号）worktree** 的现状清单（issue #5480 漏洞 1）。

    它们**不在**自动收尾半径内（多为 detached HEAD ⇒ 无分支可核合入状态），但会**堆积**：
    2026-09-25 实测残留 **7 个**，当天各花人工一次 `git worktree remove --force`。
    ⇒ 本函数只**让堆积可见**（计数 + 逐条路径），**不删任何东西**（真删的判据另议）。
    """
    out: list[Path] = []
    for entry in GUARD._worktrees(cwd):
        path = Path(entry["path"])
        if path.name.startswith(".") and path.is_dir():
            out.append(path)
    return sorted(out)


def warn_dot_worktrees(cwd: Path, label: str) -> int:
    """超过阈值 ⇒ 打印 `::warning::` + 逐条路径（返回条数）。**零删除**。"""
    dots = dot_worktrees(cwd)
    if len(dots) > DOT_WT_WARN_THRESHOLD:
        print(f"::warning:: [{label}] 临时（点号）worktree 堆积 {len(dots)} 个"
              f"（阈值 {DOT_WT_WARN_THRESHOLD}）—— 它们**不在**自动收尾半径内，"
              f"要清只能人工 `git worktree remove --force <path>`：", file=sys.stderr)
        for path in dots:
            print(f"  • {path}", file=sys.stderr)
    return len(dots)


def read_pr_rows(cwd: Path) -> list[dict] | None:
    """**一次**取全量 PR（`--state all`）⇒ 行列表；取不到 ⇒ None（无法判定，不得当 0 读）。"""
    proc = _run([gh_bin(), "pr", "list", "--state", "all", "--limit", str(PR_LIMIT),
                 "--json", "number,state,headRefName,baseRefName"], cwd=cwd, timeout=120)
    if proc.returncode != 0:
        return None
    try:
        rows = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return rows if isinstance(rows, list) else None


def classify_rows(rows: list[dict]) -> tuple[set[str], dict[str, int], set[str]]:
    """行 → （有已合并 PR 的分支集, open PR 的分支→号, open PR 的 base 集）。"""
    merged: set[str] = set()
    open_nums: dict[str, int] = {}
    open_bases: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        head, state = row.get("headRefName") or "", row.get("state") or ""
        if state == "MERGED":
            merged.add(head)
        elif state == "OPEN":
            number = row.get("number")
            open_nums[head] = number if isinstance(number, int) else -1
            if row.get("baseRefName"):
                open_bases.add(str(row["baseRefName"]))
    return merged, open_nums, open_bases


def reap_candidates(cwd: Path, root: Path) -> list[Candidate]:
    """候选 = 已注册 worktree（主工作区除外）+ 本地分支 + 远程分支（`origin/*`，去重成一行一分支）。"""
    by_branch: dict[str, Candidate] = {}

    def touch(branch: str, path: Path | None = None, local: bool = False,
              remote: bool = False, stale: bool = False) -> None:
        c = by_branch.get(branch)
        if c is None:
            by_branch[branch] = Candidate(branch, path, local, remote, stale)
            return
        c.path = c.path or path
        c.stale = c.stale or stale
        c.local, c.remote = c.local or local, c.remote or remote

    root_resolved = root.resolve()
    for entry in GUARD._worktrees(cwd):
        path, branch = Path(entry["path"]), entry["branch"]
        if not branch or path.resolve() == root_resolved:
            continue
        exists = path.is_dir()
        touch(branch, path if exists else None, stale=not exists)

    for line in git("for-each-ref", "refs/heads", "--format=%(refname:short)", cwd=cwd, check=False).stdout.splitlines():
        if line.strip():
            touch(line.strip(), local=True)
    for line in git("for-each-ref", "refs/remotes/origin", "--format=%(refname:short)",
                    cwd=cwd, check=False).stdout.splitlines():
        name = line.strip()
        if not name or name.endswith("/HEAD") or "/" not in name:
            continue
        touch(name.split("/", 1)[1], remote=True)
    return list(by_branch.values())


def classify_candidate(c: Candidate, merged: set[str], open_nums: dict[str, int], open_bases: set[str],
                       protected: list[Path], locked: set[str], self_branches: set[str],
                       wt_base: Path) -> tuple[bool, str, str]:
    """⇒ (可否收尾, 原因分类键, 可读原因)。**任一保护命中即不删**（fail-closed，顺序即处置优先级）。"""
    if c.branch in PROTECTED_BRANCHES:
        return False, "主干分支", "主干分支，永不判可移除"
    if c.branch in self_branches:
        return False, "本次目标/当前检出", "本次调用的目标分支或当前检出的分支（--except / cwd）"
    if c.path is not None:
        why = protected_reason(c.path, protected)
        if why:
            return False, "活锚保护", "**活锚保护**：" + why
        if not c.path.resolve().is_relative_to(wt_base):
            return False, "半径外 worktree", f"worktree 不在工作区根（{wt_base}）下 ⇒ 自动收尾半径外"
    if c.stale:
        return False, "stale worktree 记录", "stale worktree 记录（目录已不存在）→ 先 `git worktree prune`"
    if c.branch in open_nums:
        return False, "有 open PR", f"有 open PR（#{open_nums[c.branch]}）⇒ 在飞，不动"
    if c.branch in open_bases:
        return False, "是 open PR 的 base", "是某个 open PR 的 base（stacked PR）⇒ 删了会连带影响它"
    if c.branch in locked:
        return False, "活跃会话锁", "有**活跃会话锁**（PID 存活）⇒ 可能正在用"
    if c.branch not in merged:
        return False, "无已合并 PR", "GitHub 上没有已合并 PR（从未有 PR / 未合并）⇒ fail-closed"
    return True, "可收尾", "有已合并 PR 且无 open PR ⇒ 可收尾"


def cmd_reap_merged(args: argparse.Namespace) -> int:
    from collections import Counter

    cwd = Path.cwd()
    root = main_root(cwd)
    wt_base = wt_base_dir(cwd)
    mode = "APPLY（真删）" if args.apply else "dry-run（零删除）"
    print(f"🧹 自动收尾（{mode}）—— 判定：有**已合并** PR 且**无 open PR**")
    print("   （squash 合并下 `--merged` / `git cherry` 结构性失效 ⇒ 判据只认 GitHub PR 状态）")
    warn_dot_worktrees(cwd, "reap-merged")

    rows = read_pr_rows(cwd)
    if rows is None:
        print("⏭️  「PR 状态」这条判据**未跑**（gh 不可用 / 未登录 / 离线）⇒ 一个都不删"
              "（exit 3 = 无法判定，**不得当 0 读**）。", file=sys.stderr)
        return EXIT_UNKNOWN
    if not rows:
        print("⏭️  gh 可用但**一条 PR 都取不到**（空结果）⇒ 无法判定 ⇒ 一个都不删（exit 3）。", file=sys.stderr)
        return EXIT_UNKNOWN
    if len(rows) >= PR_LIMIT:
        print(f"⚠️  读数可能被 `--limit {PR_LIMIT}` **截断**（本次恰好拿到 {PR_LIMIT} 条）⇒ 更老的已合并 PR "
              "可能不在读数里。后果是**漏收**（fail-closed 方向：判不出「已合并」就不动），**不会误删**；"
              "要全量需分页，本单未做（如实登记为边界）。")

    merged, open_nums, open_bases = classify_rows(rows)
    protected = anchor_protected_paths()
    locked = GUARD._locked_branches(cwd)
    if locked is None:
        # `_locked_branches` 的 `None` = **无法判定**（#5430 同族：取不到 common git dir）。
        # 不得当成「无锁」继续收尾 —— 有会话在用的 worktree 会被删掉（fail-closed：本次一个都不收尾）。
        print("❌ 读不到 common git dir ⇒ **判不了活跃会话锁**（无法判定，exit 3）；本次一个都不收尾。",
              file=sys.stderr)
        return EXIT_UNKNOWN
    self_branches = {b for b in (current_branch(cwd), current_branch(root), *args.exclude) if b}
    candidates = reap_candidates(cwd, root)

    reapable: list[Candidate] = []
    skipped: list[tuple[Candidate, str, str]] = []
    for c in candidates:
        ok, key, why = classify_candidate(c, merged, open_nums, open_bases,
                                         protected, locked, self_branches, wt_base)
        if ok:
            reapable.append(c)
        else:
            skipped.append((c, key, why))

    print(f"\n读数（**一次取数** `gh pr list --state all`）：PR {len(rows)} 条 / 有已合并 PR 的分支 "
          f"{len(merged)} 个 / 有 open PR 的分支 {len(open_nums)} 个")
    print(f"候选 {len(candidates)} 个（{wt_base} 下的 worktree + 本地分支 + 远程分支）")
    print(f"\n── 可收尾：{len(reapable)} 个 ──")
    for c in reapable:
        print(f"  ✅ {c.branch}" + (f"（worktree {c.path}）" if c.path else "（无注册 worktree）"))
    if not reapable:
        print("  （无）")
    print(f"\n── 跳过：{len(skipped)} 个 ──")
    for c, _key, why in skipped:
        print(f"  ⚠️  {c.branch}：{why}")

    anchor_hits = [c for c, key, _why in skipped if key == "活锚保护"]
    if anchor_hits:
        print(f"\n❌ **活锚保护命中 {len(anchor_hits)} 个**：活锚必须是**专职只读镜像**，绝不能指向工作区"
              "（issue #3956 实证：误删 ⇒ DSH 静默加载不到研发模式）⇒ 这些路径零删除，整轮 exit 2 报警。",
              file=sys.stderr)

    if not reapable:
        digest = "、".join(f"{k} ×{v}" for k, v in Counter(key for _c, key, _w in skipped).most_common())
        print(f"\nℹ️  **本轮零动作**：0 个可收尾（判了、都不该动 —— 不是「没跑」）。"
              f"跳过原因分布：{digest or '（无候选）'}")
        return EXIT_UNMERGED if anchor_hits else EXIT_OK

    if not args.apply:
        print("\nℹ️  这是 dry-run（默认）—— **零删除**。要真删："
              "./scripts/issue-lifecycle.sh reap-merged --apply")
        return EXIT_UNMERGED if anchor_hits else EXIT_OK

    failures = 0
    for c in reapable:
        print(f"\n🧹 收尾：{c.branch}" + (f"（{c.path}）" if c.path else "（无注册 worktree）"))
        try:
            if c.path is not None:
                remove_worktree(str(c.path), cwd)
                print(f"✅ 已移除工作区：{c.path}")
            if c.local and delete_local_branch(c.branch, cwd):
                print(f"✅ 已删除本地分支：{c.branch}")
            if c.remote and delete_remote_branch(c.branch, cwd):
                print(f"✅ 已删除远程分支：origin/{c.branch}")
        except RuntimeError as exc:
            print(f"❌ 收尾失败：{exc}")
            failures += 1
            continue
        ledger_add(c.branch, cwd)
        target = Target(c.branch, str(c.path) if c.path else None, c.path is not None, c.local, c.remote)
        if not verify_clean(target, cwd, root):
            failures += 1

    removed = clean_artifacts(root, apply=True) if not args.no_artifacts else []
    if args.no_artifacts:
        print("\nℹ️  --no-artifacts：跳过过程产物清理 —— 主工作区根是**跨会话共享写面**"
              "（别人的 `pr-body-*.md` 可能正躺在那里在用；§2.3 第 8 条同族）")
    else:
        print(f"\n🧽 已清过程产物 {len(removed)} 项")
    print(f"✅ 自动收尾完成：{len(reapable) - failures}/{len(reapable)} 个目标已清。"
          if not failures else f"⚠️  {failures} 个目标自证有未清项（见上）。")
    return EXIT_UNMERGED if (failures or anchor_hits) else EXIT_OK


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
        branch = current_branch(Path(path)) or ""
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
    warn_dot_worktrees(cwd, "prune")

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


# ── 「已交付却悬挂」的发现面 + 「无证据不关单」的执行面（issue #5480 漏洞 2）──────────
#
# 病灶（2026-09-25 实测）：PR 是**部分交付**时按 §23 G9 有意**不写**关闭词 ⇒ issue 悬挂，
# 而**没有任何东西会变红** —— 当天靠人工逐条对账才发现 37 条「已交付 / 已被取代却仍 open」，
# 8 个核验员 + 逐条内容级取证的成本本可省掉（同族：#4411 的「已交付未关闭」形态）。
# ⇒ 两条命令：`pending-close`（**只发现，零写操作**）+ `close`（**无 `--evidence` 即拒**，默认 dry-run）。

CLOSE_KEYWORD = re.compile(r"(?:clos|fix|resolv)\w*\s*#(\d+)", re.I)
ISSUE_REF = re.compile(r"#(\d+)")
#: 判定 → `gh issue close --reason` 的取值（delivered = completed；其余 = not planned）
CLOSE_REASON_MAP = {"delivered": "completed", "superseded": "not planned", "stale-report": "not planned"}
CLOSE_REASON_HEAD = {
    "delivered": "诉求已在 `origin/main` 落地",
    "superseded": "已被后续 issue / 裁定取代",
    "stale-report": "一次性 CI 报告，已过期",
}


def _gh_json(argv: list[str], cwd: Path, timeout: int = 120):
    """跑一条 gh 并解析 JSON。**任何失败都回 None**（= 无法判定，调用方必须与「空集」分开）。"""
    proc = _run([gh_bin(), *argv], cwd, timeout=timeout)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        return None


def pending_close_rows(pr_rows: list[dict], open_nums: set[int],
                       since_days: int | None = None, today: str | None = None,
                       ) -> list[tuple[int, str, list[int]]]:
    """纯函数（可单测）：已合并 PR 里**引用了却没写关闭词**、且**仍 open** 的 issue。

    判定刻意**只做发现**：`关联 #N` 形式的引用大多是**合法的部分交付**（§23 G9 有意不写关闭词），
    所以这里不做任何「应该关」的判断 —— 关不关要人看「该 PR 交付了什么 / 剩余什么」。
    """
    floor = None
    if since_days is not None:
        base = date.fromisoformat(today) if today else date.today()
        floor = (base - timedelta(days=since_days)).isoformat()
    out: list[tuple[int, str, list[int]]] = []
    for row in pr_rows:
        if not isinstance(row, dict) or not row.get("number"):
            continue
        body = row.get("body") or ""
        day = str(row.get("mergedAt") or "")[:10]
        if floor is not None and day and day < floor:
            continue
        closed = {int(x) for x in CLOSE_KEYWORD.findall(body)}
        refs = {int(x) for x in ISSUE_REF.findall(body)}
        pend = sorted((refs - closed) & open_nums)
        if pend:
            out.append((int(row["number"]), day, pend))
    return out



#: 「人为要求」标记（2026-09-25 用户裁定：会话内零新开 issue，唯一例外 = 人类显式要求）
HUMAN_REQUEST_MARKER = "人为要求："


def is_human_requested(body: str) -> bool:
    """body 里出现 `人为要求：…` 标记 ⇒ 该单是**人类显式要求**开的（唯一合法例外）。

    口径：**不要求首行** —— 标记可能在标题下一行、或被 GitHub 模板挪位；只要正文里出现该标记即算。
    （判据侧的"首行"措辞是给人读的约定；机械判据用"出现即算"，**更不容易误伤**。)
    """
    return HUMAN_REQUEST_MARKER in (body or "")


def non_human_requested(rows: list[dict]) -> list[tuple[int, str, str]]:
    """纯函数（可单测）：从未带标记的 issue 行里挑出「非人为要求」的 ⇒ [(number, createdAt, title)]。"""
    out = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("number"):
            continue
        if is_human_requested(r.get("body") or ""):
            continue
        out.append((int(r["number"]), str(r.get("createdAt") or "")[:19], str(r.get("title") or "")[:70]))
    return sorted(out)


def cmd_pending_close(args: argparse.Namespace) -> int:
    """报告型：待人工关单清单。**零写操作**（只读 gh）。"""
    cwd = Path.cwd()
    prs = _gh_json(["pr", "list", "--state", "merged", "--limit", str(args.limit),
                    "--json", "number,title,body,mergedAt"], cwd)
    issues = _gh_json(["issue", "list", "--state", "open", "--limit", "500", "--json", "number"], cwd)
    if prs is None or issues is None:
        print("⏭️  无法判定（gh 不可用 / 未登录 / 取数失败）⇒ exit 3 —— **不得当 0 读**（空集 ≠ 取不到）",
              file=sys.stderr)
        return EXIT_UNKNOWN
    open_nums = {int(i["number"]) for i in issues if isinstance(i, dict) and i.get("number")}
    rows = pending_close_rows(prs, open_nums, args.since_days)
    total = sum(len(p) for _, _, p in rows)
    print(f"── 待人工关单：{len(rows)} 个已合并 PR / {total} 条仍 open 的 issue（计数**现取**，不写死）──")
    for num, day, pend in rows:
        print(f"  · PR #{num}（{day}）→ {', '.join('#' + str(i) for i in pend)}")
    if not rows:
        print("  （无）")
        return EXIT_OK
    print("\n可复算：`gh pr view <PR> --json body,mergedAt --jq .body` 看它交付了什么；"
          "`gh issue view <N> --json state,comments` 看剩余什么。")
    print("⚠️  本清单**只做发现**：`关联 #N` 大多是**合法的部分交付**（§23 G9 有意不写关闭词）"
          "⇒ 关不关要人判断剩余口径；本命令**不自动关、零写操作**。")
    return EXIT_OK


def _evidence_comment(issue: int, reason: str, evidence: str) -> str:
    return (f"## ✅ 关闭：{CLOSE_REASON_HEAD[reason]}\n\n"
            f"**判定依据（内容级证据）**：{evidence}\n\n"
            f"> 由 `./scripts/issue-lifecycle.sh close` 关闭；**无 `--evidence` 即拒**（fail-closed）。"
            f"若判定有误：`gh issue reopen {issue}`。\n")


def close_rows_from_text(text: str) -> list[tuple[int, str, str]]:
    """解析批量文件（TSV，每行 `<issue>\\t<reason>\\t<证据>`；空行与 `#` 注释行跳过）。"""
    out: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.rstrip().split("\t")
        if len(parts) != 3 or not parts[0].strip().isdigit():
            raise ValueError(f"第 {lineno} 行不是 `<issue>\\t<reason>\\t<证据>` 三列：{line[:80]!r}")
        out.append((int(parts[0]), parts[1].strip(), parts[2].strip()))
    if not out:
        raise ValueError("批量文件里没有可执行的行")
    return out


#: 「未实装登记」的**单一源**（门禁 `case_trust_gate.py` 从同一份文件读；**不要**抄第二份口径）。
UNIMPLEMENTED_REGISTRY = Path(".github/case-trust-unimplemented.json")


def unimplemented_tracking_issues(cwd: Path) -> dict[int, str]:
    """→ `{issue 号: 登记 code}` —— 这份登记册把某些 issue 当**未实装项的追踪单**在用。

    为什么关单前必须过这一关（issue #5506 实测代价）：追踪单一旦被关，门禁规则
    `CASE-TRUST-UNIMPL-ISSUE-CLOSED`（「已关闭的追踪单 = 过期借口」）会在**下一个 PR** 上判红 ——
    2026-09-25 实测一次：全队列 6 条 PR 同时 BLOCKED，而它们的 diff 与登记册**毫无关系**。

    口径：**文件在但读不出** ⇒ 抛 `ValueError`（fail-closed：宁可不关，也不误关）；
    **文件不存在**（在不含它的目录里跑）⇒ 返回空 dict + 出声（不是本仓结构 ⇒ 不拦）。
    """
    path = cwd / UNIMPLEMENTED_REGISTRY
    if not path.exists():
        print(f"⚠️  未找到 {UNIMPLEMENTED_REGISTRY}（不在仓库根跑？）⇒ **跳过**未实装登记的守卫",
              file=sys.stderr)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("unimplemented") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise ValueError("缺 `unimplemented` 列表")
        out: dict[int, str] = {}
        for e in entries:
            if isinstance(e, dict) and isinstance(e.get("issue"), int):
                out[e["issue"]] = str(e.get("code", "?"))
        return out
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"{UNIMPLEMENTED_REGISTRY} 不可解析：{exc}") from exc


def cmd_close(args: argparse.Namespace) -> int:
    """**无证据不关单**：先贴证据评论，再关（默认 dry-run；`--apply` 才写）。"""
    cwd = Path.cwd()
    if args.batch_file:
        try:
            rows = close_rows_from_text(Path(args.batch_file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"❌ 批量文件不可用：{exc}", file=sys.stderr)
            return EXIT_USAGE
    elif args.issue:
        rows = [(args.issue, args.reason, (args.evidence or "").strip())]
    else:
        print("❌ 需要 issue 号或 --batch-file", file=sys.stderr)
        return EXIT_USAGE

    unknown = sorted({r for _, r, _ in rows if r not in CLOSE_REASON_MAP})
    if unknown:
        print(f"❌ 未知 reason {unknown}（可选 {sorted(CLOSE_REASON_MAP)}）", file=sys.stderr)
        return EXIT_USAGE
    missing = [n for n, _, ev in rows if not ev]
    if missing:
        print(f"❌ issue {missing} 缺**内容级证据** —— 「无证据不关单」是本命令的硬约束（fail-closed）。\n"
              f"   证据要能复算：一条命令 + 关键输出，例："
              f"\"PR #1234 merged 2026-09-14T23:06Z；git grep -n X origin/main -- <path> ⇒ 命中\"",
              file=sys.stderr)
        return EXIT_USAGE

    try:
        tracked = unimplemented_tracking_issues(cwd)
    except ValueError as exc:
        print(f"❌ 未实装登记册不可读 ⇒ **拒绝关单**（fail-closed）：{exc}", file=sys.stderr)
        return EXIT_USAGE

    hits = sorted((n, tracked[n]) for n, _, _ in rows if n in tracked)
    if hits and not args.ack_unimplemented_registry:
        print("❌ 拒绝关闭：以下 issue 仍是「**未实装登记**」的追踪单 —— 关掉它们会让门禁在**下一个 PR** 上判红"
              "（规则 `CASE-TRUST-UNIMPL-ISSUE-CLOSED`；2026-09-25 实测一次全队列阻塞，见 issue #5506）：",
              file=sys.stderr)
        for n, code in hits:
            print(f"   · #{n} ← 登记 {code}", file=sys.stderr)
        print("   两个出口（门禁原文）：① **实装了 ⇒ 撤登记**（改 `.github/assertion_taxonomy.py` 的 "
              "`UNIMPLEMENTED` 并重落盘）；② **没实装 ⇒ 开新追踪单**，把登记的 `issue` 指过去 + 重设 `expires`。\n"
              "   已在别处同步该登记（例如同批修复 PR）时，可显式承担：`--ack-unimplemented-registry`",
              file=sys.stderr)
        return EXIT_USAGE

    mode = "**真关**" if args.apply else "dry-run（**零写操作**；加 `--apply` 才真关）"
    print(f"待关闭 {len(rows)} 条 —— {mode}")
    failures = 0
    for n, reason, ev in rows:
        if not args.apply:
            print(f"  [dry] #{n} {reason} :: {ev[:110]}")
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
            fh.write(_evidence_comment(n, reason, ev))
            tmp = fh.name
        try:
            posted = _run([gh_bin(), "issue", "comment", str(n), "--body-file", tmp], cwd, timeout=120)
            if posted.returncode != 0:
                failures += 1
                print(f"❌ #{n} 证据评论失败（**未关单**，不留无证据的关闭）：{_tail(posted.stderr, 3)}")
                continue
            closed = _run([gh_bin(), "issue", "close", str(n), "--reason", CLOSE_REASON_MAP[reason]],
                          cwd, timeout=120)
            if closed.returncode != 0:
                failures += 1
                print(f"⚠️  #{n} 证据已贴但关单失败：{_tail(closed.stderr, 3)}")
                continue
            print(f"✅ #{n} {reason}（证据评论 → `not planned`/`completed` 已按判定落）")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    if failures:
        print(f"\n⚠️  {failures} 条未完成（其余已处理；逐条可重跑，幂等靠「证据评论 + 关单」两步各自可重入）。")
        return EXIT_UNMERGED
    return EXIT_OK


# ── CLI ──────────────────────────────────────────────────────────────────────


def cmd_check_new_issues(args: argparse.Namespace) -> int:
    """报告型：现取「新建但**没有**人为要求标记」的 issue（会话内零新开政策的机械判据）。

    口径（2026-09-25 用户裁定）：一次 agent 会话**不得新建 issue**，唯一例外 = 人类显式要求，
    且该单正文里要有 `人为要求：…` 标记。本命令**只报告、零写**：
      · 退出码 0 = 窗口内没有违规；1 = 有违规（逐条列出）；3 = **无法判定**（gh 取不到 ⇒ 不得当 0 读）。
    为什么是报告型而不是"自动关"：判"这单到底有没有人为要求"要人看（人可能在对话里要求过但没写标记）
    ⇒ 本仓口径一贯是**发现面自动、处置面留人**。
    """
    cwd = Path.cwd()
    # ⚠️ `_gh_json` 的契约 = 失败回 **None**（不是元组）⇒ 调用方必须把 None 与「空集」分开（fail-closed）。
    rows = _gh_json([
        "issue", "list", "--state", "all", "--limit", str(args.limit),
        "--search", f"created:>={args.since}",
        "--json", "number,title,body,createdAt",
    ], cwd)
    if rows is None:
        print("❌ 无法判定：取不到 issue 列表（gh 不可用 / 未认证 / 输出非 JSON）—— **不得当 0 读**")
        # ⚠️ 三态必须分开：0 = 无违规 / 1 = **有违规** / 3 = **无法判定**。
        # 本判据第一版在这里写了 EXIT_USAGE（=1）⇒ 把"取不到数据"混同成"有违规"（我自己的判据当场抓到）。
        return EXIT_UNKNOWN
    bad = non_human_requested(rows)
    print(f"窗口 created:>={args.since}：抓到 {len(rows)} 条，其中**非人为要求** = {len(bad)} 条")
    for num, created, title in bad:
        print(f"  · #{num} {created} {title}")
        print(f"    ↳ 处置：① 链内修 ② 并入既有台账 ③ 在会话里向人类提出；若确系人为要求 ⇒ 在该单正文补 `人为要求：…`")
    return 1 if bad else 0


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

    p_land = sub.add_parser(
        "land",
        help="一条命令落地：" + " → ".join(LAND_STEPS) + "（顺序即安全顺序；gate 判红即停）",
    )
    p_land.add_argument("branch", help="要落地的分支（必须有已注册的 worktree 检出）")
    p_land.add_argument("--dry-run", action="store_true", help="只打印计划与前置读数，**零动作**")
    p_land.add_argument("--from", dest="from_step", choices=LAND_RESUMABLE_FROM,
                        help="从该步起续跑（只允许 " + "/".join(LAND_RESUMABLE_FROM)
                             + " —— rebase/gate/ready 是安全前置，永不可跳过）")
    p_land.add_argument("--ci-timeout", type=int, default=DEFAULT_CI_TIMEOUT,
                        help=f"`gh pr checks --watch` 的阻塞上限（秒，默认 {DEFAULT_CI_TIMEOUT}）；超时 ⇒ exit 3")
    p_land.set_defaults(func=cmd_land)

    p_reap = sub.add_parser(
        "reap-merged",
        help="自动收尾「有已合并 PR 且无 open PR」的 worktree/本地/远程分支（**默认 dry-run**）",
    )
    p_reap.add_argument("--apply", action="store_true", help="真删（默认只打印清单）")
    p_reap.add_argument("--dry-run", action="store_true", help="显式 dry-run（本身就是默认口径，写上只为可读）")
    p_reap.add_argument("--except", dest="exclude", action="append", default=[],
                        help="排除该分支（可重复；`dev-worktree.sh add` 用它排除本次要建的分支）")
    p_reap.add_argument("--no-artifacts", action="store_true",
                        help="跳过过程产物清理（主工作区根是**跨会话共享写面**：别人的 pr-body-*.md "
                             "可能正在用；`dev-worktree.sh add` 的自动收尾用它）")
    p_reap.set_defaults(func=cmd_reap_merged)

    p_pending = sub.add_parser(
        "pending-close",
        help="**报告型**：已合并 PR 引用了却没写关闭词、且仍 open 的 issue ⇒ 待人工关单清单（**零写操作**）",
    )
    p_pending.add_argument("--limit", type=int, default=200, help="扫最近 N 个已合并 PR（默认 200）")
    p_pending.add_argument("--since-days", type=int, default=None, help="只看最近 N 天合并的 PR")
    p_pending.set_defaults(func=cmd_pending_close)

    p_new = sub.add_parser(
        "check-new-issues",
        help="报告型：现取「新建但没有 `人为要求：` 标记」的 issue（会话内零新开政策的机械判据）",
    )
    p_new.add_argument("--since", default=str(date.today()), help="窗口起点（created:>= 的值，默认今天）")
    p_new.add_argument("--limit", type=int, default=200, help="抓最近 N 条（默认 200）")
    p_new.set_defaults(func=cmd_check_new_issues)
    p_close = sub.add_parser(
        "close",
        help="**无证据不关单**：先贴证据评论再关（默认 dry-run；delivered→completed，其余→not planned）",
    )
    p_close.add_argument("issue", nargs="?", type=int, help="issue 号（或用 --batch-file）")
    p_close.add_argument("--reason", choices=sorted(CLOSE_REASON_MAP), default="delivered",
                         help="delivered=已交付 / superseded=被取代 / stale-report=过期报告")
    p_close.add_argument("--evidence", help="一行**内容级证据**（必填；含可复算命令 + 关键输出）")
    p_close.add_argument("--batch-file", help="TSV 批量：`<issue>\\t<reason>\\t<证据>` 每行一条")
    p_close.add_argument("--apply", action="store_true", help="真关（默认只打印计划）")
    p_close.add_argument("--ack-unimplemented-registry", action="store_true",
                         help="显式承担「该 issue 仍是未实装登记的追踪单」仍要关（默认**拒关**，issue #5506）")
    p_close.set_defaults(func=cmd_close)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
