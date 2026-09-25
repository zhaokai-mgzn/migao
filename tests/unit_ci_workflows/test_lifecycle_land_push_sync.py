# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012）
"""`land` 的**推送 + 同步断言**（issue #5489；`scripts/issue_lifecycle.py`）。

## 病根（2026-09-25 实测，就在本会话）

在 PR #5488 上：`rebase`（带回 main 的新提交）→ `gh pr ready` + `--auto` → **`git push` 才执行，且被拒**
（`non-fast-forward`：rebase 重写了历史）。当时 PR 已 ready + armed，而**远端 head 仍是旧提交**
⇒ 若那一刻 CI 绿，PR 会在**缺 commit** 的状态下合并（该 commit 随即搁浅）。当次靠 `--force-with-lease`
在合并前抢推成功。

代码级缺口：`LAND_STEPS = (rebase, gate, ready, wait-ci, …)` **没有 push 步**，`rebase` 步也不推
⇒ `ready` / `wait-ci` 看的是**远端旧 head**，等的是**别人那次提交**的 CI（§23.7 A1「判定对象与数据不同刻」同族）。

## 两个函数（本文件各给一条能单独变红的红证）

| 函数 | 断言 | 红证（注入 ⇒ 必红） |
|---|---|---|
| `push_after_rebase` | rebase 后的**新历史**必须推上去；用 `--force-with-lease`（远端被别人推过 ⇒ **仍拒**，不覆盖别人的工作） | 换成裸 `git push` ⇒ `test_push_after_rebase_survives_diverged_remote` 红 |
| `assert_head_pushed` | 本地 HEAD == `origin/<branch>`；取不到 head（fetch 失败/空）⇒ **无法判定 ⇒ 停** | 直接 `return True` ⇒ `test_..._detects_unpushed_commit` / `test_..._fail_closed` 红 |

夹具一律是 `tmp_path` 下的**真 git 仓库 + 真 bare origin**（判据本体就是 git 语义；mock 掉 git 等于换掉被测对象）。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("issue_lifecycle", REPO_ROOT / "scripts" / "issue_lifecycle.py")
assert SPEC and SPEC.loader
_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_mod)          # type: ignore[union-attr]

GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
BRANCH = "feat/x"


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          env=GIT_ENV, check=check)


def _fixture(tmp_path: Path):
    """真 bare origin + 真克隆（分支 `feat/x`，且已推送一次）。→ (clone, origin)"""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "-q", "-b", "main")
    clone = tmp_path / "clone"
    clone.mkdir()
    _git(clone, "init", "-q", "-b", "main")
    _git(clone, "remote", "add", "origin", str(origin))
    (clone / "a.txt").write_text("x", encoding="utf-8")
    _git(clone, "add", ".")
    _git(clone, "commit", "-qm", "init")
    _git(clone, "checkout", "-qb", BRANCH)
    _git(clone, "push", "-q", "-u", "origin", BRANCH)
    return clone, origin


def _remote_head(origin: Path, branch: str = BRANCH) -> str:
    return _git(origin, "rev-parse", branch).stdout.strip()


def _local_head(clone: Path, rev: str = "HEAD") -> str:
    return _git(clone, "rev-parse", rev).stdout.strip()


# ── push_after_rebase ────────────────────────────────────────────────────────

def test_push_after_rebase_survives_diverged_remote(tmp_path):
    """rebase 重写了历史（本地与远端分叉）⇒ 仍能推上去（证明用的是 `--force-with-lease`）。

    红证：把实现换成裸 `git push` ⇒ 本用例必红（non-fast-forward 被拒）。
    """
    clone, origin = _fixture(tmp_path)
    # ⚠️ 必须重写**已推送**的那个提交：先本地领先再 amend 只会得到**快进**（普通 push 也能过）——
    #    第一版夹具就是这么写的，实测「把 --force-with-lease 换成裸 push」**不红**（空红证）。
    (clone / "a.txt").write_text("rewritten", encoding="utf-8")
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "--amend", "-m", "rewritten history")   # 真分叉：本地不再包含远端那个提交
    ok, why = _mod.push_after_rebase(BRANCH, clone)
    assert ok, f"分叉历史应能推上去（--force-with-lease）：{why}"
    assert _remote_head(origin) == _local_head(clone), "远端 head 必须等于本地 HEAD"


def test_push_after_rebase_refuses_to_clobber_someone_else(tmp_path):
    """**别人推过**（本地远端跟踪引用已陈旧）⇒ `--force-with-lease` 必须拒 ⇒ fail-closed。"""
    clone, origin = _fixture(tmp_path)
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", "-b", BRANCH, str(origin), str(other))
    (other / "b.txt").write_text("theirs", encoding="utf-8")
    _git(other, "add", ".")
    _git(other, "commit", "-qm", "someone else")
    _git(other, "push", "-q", "origin", BRANCH)
    their_head = _remote_head(origin)
    (clone / "a.txt").write_text("mine", encoding="utf-8")
    _git(clone, "commit", "-qam", "mine")
    ok, why = _mod.push_after_rebase(BRANCH, clone)
    assert not ok, f"远端被别人推进过 ⇒ 不许覆盖（fail-closed）：{why}"
    assert _remote_head(origin) == their_head, "别人的提交必须原样保留"


# ── assert_head_pushed ───────────────────────────────────────────────────────

def test_assert_head_pushed_ok_when_in_sync(tmp_path):
    clone, _ = _fixture(tmp_path)
    ok, why = _mod.assert_head_pushed(BRANCH, clone)
    assert ok, why
    assert "==" in why, why


def test_assert_head_pushed_detects_unpushed_commit(tmp_path):
    """本地有**未推送**的提交 ⇒ 必须判「不同步」（这正是「等错 CI」的形态）。

    红证：把函数改成永远 `return True` ⇒ 本用例必红。
    """
    clone, _ = _fixture(tmp_path)
    (clone / "a.txt").write_text("local only", encoding="utf-8")
    _git(clone, "commit", "-qam", "not pushed")
    ok, why = _mod.assert_head_pushed(BRANCH, clone)
    assert not ok, f"未推送的提交必须被拦下：{why}"
    assert "不是本次内容" in why, why


def test_assert_head_pushed_fail_closed_when_branch_absent(tmp_path):
    """远端**没有**该分支（取不到 head）⇒ **无法判定 ⇒ 停**（不得当「同步」读）。"""
    clone, _ = _fixture(tmp_path)
    _git(clone, "checkout", "-qb", "feat/never-pushed")
    _git(clone, "commit", "-qam", "x", check=False)
    ok, why = _mod.assert_head_pushed("feat/never-pushed", clone)
    assert not ok, f"取不到远端 head 必须 fail-closed：{why}"
    assert "无法判定" in why, why