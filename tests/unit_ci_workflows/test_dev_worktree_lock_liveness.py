# case_ids: MC-118
"""dev-worktree 会话锁的**存活判据**：PID 已退出、但登记的工作区仍在 ⇒ 仍算「有人在用」（issue #7216）。

## 病（2026-10-18 项目卫生现取读数，可复算）

并行跑 4~5 个会话后，`./scripts/dev-worktree.sh lock` 的每一行都是 💀 —— **包括刚建好、还在里面干活的工作区**：

```
💀 7212-remove-settings-mobile-entry | PID 8053  | 2026-10-18 11:33:06 | .../migao-wt/7212-remove-settings-mobile-entry（进程已退出，锁失效）
💀 7213-cutting-preview-selects      | PID 10451 | 2026-10-18 11:37:13 | .../migao-wt/7213-cutting-preview-selects（进程已退出，锁失效）
```

根因：`lock_register` 写的是 `$$` = **`dev-worktree.sh add` 自己的 PID**；`add` 一返回该 PID 必已退出
⇒ `lock_alive`（只判 `kill -0`）永假 ⇒ ①「同一分支已有活跃锁 ⇒ 拒绝建区」永不触发；
② `list` / `lock` 永远读不到真状态；③ 失效锁只增不减（本次卫生前已累积 **84** 把，靠手动 `lock --prune` 才清掉）。

真实语义应是「这个分支还有人占着」：**PID 仍活着**（两个 `add` 并发重叠的窗口）**或登记的工作区仍在且仍检出该分支**
（会话可能还在里面干活 —— 保守方向：宁可不判「可安全移除」）。

## 本文件判的六条

| # | 判据 | 会怎么红 |
|---|---|---|
| 1 | 实例判据：`add` 返回后其 PID 已退出，锁仍必须显示 **🔒（工作区仍在 ⇒ 视为占用）** | 旧实现显示 💀 |
| 2 | 修前红（注入变体）：把判活退回「只按 PID」⇒ 同 fixture 必须显示 💀 | 注入未生效 / 退回后仍 🔒 ⇒ 判红 |
| 3 | `lock --prune` 只清「PID 死了**且**工作区不在（或不在该分支上）」的锁 | 清掉活锁（把并发会话的工作区判成可复用）⇒ 红 |
| 4 | `add` 入口自动清失效锁（事件驱动，不新增 cron） | 失效锁继续累积 ⇒ 红 |
| 5 | `rm` 释放锁（旧写法 `lock_alive` 前提在 `add` 后永假 ⇒ 锁从不在 `rm` 时释放） | 锁文件残留 ⇒ 红 |
| 6 | 跨消费者同源（类级元守卫）：`scripts/agent-presets-guard.py::_locked_branches`（`prune` 用）与 bash 判活同一口径 | 只改 bash ⇒ `prune` 仍把有会话的工作区判「可安全移除」⇒ 红 |

边界（照实登记，`migao-dev-flow` §19.1）：只跑定点判据；不跑 `verify-all.sh gate` / 全量 pytest
（重活串行，§27）。所有夹具都造在 `tmp_path`（真 `git init` + 真 worktree + 真锁文件），零网络、不碰真实工作区。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dev-worktree.sh"
GUARD = REPO_ROOT / "scripts" / "agent-presets-guard.py"

#: 一个**必然不存在**的 PID（Linux pid_max 上限 4_194_304 / macOS max 99_999 都远小于它）。
DEAD_PID = "2147483646"


# ── 真 fixture：真 git 仓库 + 真脚本副本（不 mock；红证只在 tmp_path 上跑）────────
def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def _chmod_exec(path: Path) -> None:
    path.chmod(0o755)


def build_fixture(base: Path, *, script_text: str | None = None) -> dict:
    """造真仓库 + 脚本副本（字节相同；`script_text` = 注入变体入口）+ 两个离线垫片。"""
    repo = base / "repo"
    (repo / "scripts").mkdir(parents=True)
    live = SCRIPT.read_text(encoding="utf-8")
    text = live if script_text is None else script_text
    if script_text is not None and text == live:
        raise AssertionError("注入没生效（源码与现役逐字相同）⇒ 下面的判红会变成空断言")
    script = repo / "scripts" / "dev-worktree.sh"
    script.write_text(text, encoding="utf-8")
    _chmod_exec(script)

    # `add` 以 `|| echo` best-effort 调用它；给个 rc=0 的最小桩，别让夹具里出现无关噪声。
    stub = repo / "scripts" / "issue-lifecycle.sh"
    stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    _chmod_exec(stub)

    # 判据 6 的跨消费者：prune 走 `scripts/agent-presets-guard.py`（真副本）。
    shutil.copy2(GUARD, repo / "scripts" / "agent-presets-guard.py")

    # 离线：gh 一律 rc=1（`prune` 会把「PR 已合并」判据标成未跑，不联网）。
    bindir = base / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    _chmod_exec(gh)

    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "init")
    return {"repo": repo, "script": script, "bindir": bindir, "home": base / "home"}


def run(fx: dict, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{fx['bindir']}:{env.get('PATH', '')}"
    env["HOME"] = str(fx["home"])  # 与真实活锚解耦：本文件不看 / 不写 ~/.dsh
    return subprocess.run(
        ["bash", str(fx["script"]), *args],
        cwd=str(fx["repo"]), capture_output=True, text=True, timeout=180, env=env,
    )


def lock_file(fx: dict, branch: str) -> Path:
    # 分支名不带走前/后缀（slug() 只剥 feat|fix|chore|docs|test|refactor 前缀）
    return fx["repo"] / ".git" / "sessions" / f"{branch}.lock"


def add_worktree(fx: dict, branch: str) -> None:
    _git(fx["repo"], "branch", branch, "main")
    proc = run(fx, "add", branch)
    if proc.returncode != 0:  # fail-closed：夹具没造出来就不许往下走
        raise AssertionError(f"夹具 add 失败（rc={proc.returncode}）：\n{proc.stdout}\n{proc.stderr}")
    if not lock_file(fx, branch).exists():
        raise AssertionError(f"夹具没造出锁文件：{lock_file(fx, branch)}")


def seed_stale_lock(fx: dict, branch: str = "stale-gone") -> Path:
    """造一把「PID 已退出 + 登记工作区不存在」的失效锁（与真实成因同形，不依赖时序）。"""
    lock = lock_file(fx, branch)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(f"{DEAD_PID}|2026-01-01 00:00:00|{branch}|{fx['repo'].parent / 'migao-wt' / branch}\n",
                    encoding="utf-8")
    return lock


def lock_line(listing: str, branch: str) -> str:
    for line in listing.splitlines():
        if line.strip().startswith(("🔒", "💀")) and branch in line:
            return line
    raise AssertionError(f"`lock` 输出里找不到分支 {branch} 的那一行：\n{listing}")


def add_process_pid_dead(lock: Path) -> int:
    pid = int(lock.read_text(encoding="utf-8").split("|")[0])
    try:
        os.kill(pid, 0)
    except OSError:
        return pid
    raise AssertionError(f"add 进程 PID {pid} 仍存活 —— 夹具无法证明「判活不是靠 PID」")


# ── 判据 1：实例判据（行为面）
def test_lock_stays_active_after_add_process_exits(tmp_path: Path) -> None:
    """`add` 返回后其 PID 已退出；锁仍必须 **🔒（工作区仍在 ⇒ 视为占用）**（旧实现 = 💀）。"""
    fx = build_fixture(tmp_path)
    add_worktree(fx, "live-7216")
    add_process_pid_dead(lock_file(fx, "live-7216"))  # 红证前提：PID 真的死了
    line = lock_line(run(fx, "lock").stdout, "live-7216")
    assert "🔒" in line, f"工作区仍在的锁被判失效（issue #7216 的形态）：{line}"
    assert "工作区仍在" in line, f"判活理由没写清（读的人分不出是 PID 活着还是工作区在）：{line}"


# ── 判据 2：修前红（注入变体，双向对照）
def test_injected_pid_only_liveness_regresses_to_stale(tmp_path: Path) -> None:
    """把判活退回「只按 PID」⇒ 同 fixture 必须 💀（否则判据 1 的绿是空断言）。"""
    live = SCRIPT.read_text(encoding="utf-8")
    anchor = '  [ -e "${path}/.git" ] || return 1\n'
    assert live.count(anchor) == 1, f"注入锚出现 {live.count(anchor)} 次（应为 1）⇒ 注入点漂了"
    injected = live.replace(anchor, "  return 1  # 注入：退回只按 PID 判活\n", 1)
    assert injected != live, "注入没生效 ⇒ 下面的判红会变成空断言"
    assert subprocess.run(["bash", "-n"], input=injected, capture_output=True, text=True).returncode == 0, (
        "注入变体语法坏掉了（判红会变成「语法错」而不是「判活错」）⇒ 先修注入"
    )

    fx = build_fixture(tmp_path, script_text=injected)
    add_worktree(fx, "live-7216")
    line = lock_line(run(fx, "lock").stdout, "live-7216")
    assert "💀" in line, f"旧的「只按 PID」形态注入后仍显示活跃（判据 1 缺少判别力）：{line}"


# ── 判据 3：prune 只清真的失效锁
def test_prune_drops_stale_but_keeps_live_worktree_lock(tmp_path: Path) -> None:
    fx = build_fixture(tmp_path)
    add_worktree(fx, "live-7216")
    stale = seed_stale_lock(fx, "stale-gone")
    proc = run(fx, "lock", "--prune")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not stale.exists(), f"失效锁没被清掉：{stale}"
    assert lock_file(fx, "live-7216").exists(), "活锁被 prune 清掉了（会把并发会话的工作区判成可复用）"
    assert "💀" not in lock_line(run(fx, "lock").stdout, "live-7216")


# ── 判据 3b：同一个工作区路径、但锁写的是**别的分支** ⇒ 不是占用
def test_lock_for_another_branch_is_stale(tmp_path: Path) -> None:
    """死锁不得把工作区永久锁住：路径在、但当前检出的不是锁里那个分支 ⇒ 失效锁。"""
    fx = build_fixture(tmp_path)
    add_worktree(fx, "live-7216")
    other = lock_file(fx, "other-branch")
    other.write_text(
        f"{DEAD_PID}|2026-01-01 00:00:00|other-branch|{fx['repo'].parent / 'migao-wt' / 'live-7216'}\n",
        encoding="utf-8",
    )
    proc = run(fx, "lock", "--prune")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not other.exists(), "指向别分支的失效锁没被清掉（会把工作区永久判成占用）"
    assert lock_file(fx, "live-7216").exists(), "误清了真正检出该分支的活锁"


# ── 判据 4：add 入口事件驱动自愈
def test_add_prunes_stale_locks(tmp_path: Path) -> None:
    fx = build_fixture(tmp_path)
    stale = seed_stale_lock(fx, "stale-gone")
    _git(fx["repo"], "branch", "live-7216", "main")
    proc = run(fx, "add", "live-7216")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not stale.exists(), "add 没有顺手清掉失效锁（失效锁会继续累积 —— 事件驱动自愈没生效）"


# ── 判据 5：rm 释放锁
def test_rm_releases_session_lock(tmp_path: Path) -> None:
    fx = build_fixture(tmp_path)
    add_worktree(fx, "live-7216")
    proc = run(fx, "rm", "live-7216", "--delete-branch")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not lock_file(fx, "live-7216").exists(), "rm 之后锁文件仍在（旧写法在 add 后永假 ⇒ 锁从不在 rm 时释放）"


# ── 判据 6：跨消费者同源（类级元守卫：bash 判活 ⇄ prune 的 python 判活）
def test_guard_prune_uses_same_liveness_rule(tmp_path: Path) -> None:
    fx = build_fixture(tmp_path)
    add_worktree(fx, "live-7216")
    kept = run(fx, "prune", "--dry-run")
    assert "有活跃会话锁" in kept.stdout, (
        f"prune 没把「工作区仍在」的锁算成活跃 ⇒ 有会话的工作区会被判可安全移除：\n{kept.stdout}"
    )

    # 工作区真的没了（锁留下）⇒ 同一条理由必须消失（负向对照：防「一律报有锁」）
    _git(fx["repo"], "worktree", "remove", "--force", str(fx["repo"].parent / "migao-wt" / "live-7216"))
    gone = run(fx, "prune", "--dry-run")
    assert "有活跃会话锁" not in gone.stdout, (
        f"工作区已不在，prune 仍报「有活跃会话锁」⇒ 判活依据错了：\n{gone.stdout}"
    )


# ── 类级元守卫：判活实现只能有一处（禁第二套 PID-only 判据）
def test_liveness_rule_has_single_implementation() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    guard = GUARD.read_text(encoding="utf-8")

    assert re.search(r"lock_alive\(\)\s*\{\s*lock_file_alive", script), (
        "lock_alive 没委托给 lock_file_alive（判活出现了第二套实现）"
    )
    prune_body = re.search(r"lock_prune\(\)\s*\{(.*?)\n\}", script, re.S)
    assert prune_body and "lock_file_alive" in prune_body.group(1), "lock_prune 没复用 lock_file_alive（口径会漂）"
    assert script.count("kill -0") == 1, (
        f"`kill -0` 在 dev-worktree.sh 出现 {script.count('kill -0')} 次（应只有 lock_file_alive 一处 PID 判据）"
    )
    locked = re.search(r"def _locked_branches\(.*?\n\ndef ", guard, re.S)
    assert locked, "找不到 agent-presets-guard.py::_locked_branches"
    body = locked.group(0)
    assert "pid_alive" in body and "worktree_present" in body, (
        "prune 侧判活没有同时看「PID 活着 / 工作区仍在」（与 bash 口径不一致）"
    )
    assert body.count("os.kill") == 1, "prune 侧的 PID 判据也不许多处"
