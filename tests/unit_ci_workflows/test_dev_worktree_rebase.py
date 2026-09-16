# case_ids: MC-012, MC-013
"""`dev-worktree.sh rebase` —— 预设快照不再挡住 `git rebase origin/main`（issue #3972）。

守的这颗地雷（**夹具是真 git 仓库，不 mock**：判据本体就是 git 语义，mock 掉 git 等于把被测对象
换成替身，红证会变成假绿）：

`dev-worktree.sh add` 会用 `refresh_presets` 把 `.agent-presets/**` 对齐到 `origin/main`，
于是工作区相对**本分支 HEAD** 就出现了改动，`git rebase origin/main` 被 git 拒绝。实测两种形态：
  · 本分支 HEAD **未跟踪**该路径（旧分支，早于预设入库）⇒ 快照留在**索引**里（staged new files）
    → 「untracked working tree files would be overwritten by checkout」；
  · 本分支 HEAD 跟踪但版本较旧 ⇒ 相对 HEAD 变成**已修改** → 「cannot rebase: You have unstaged changes」。

用例分三组：
① **红证**：不加处置时 `git rebase origin/main` 必失败（直接断言失败，把形态钉住）；
② **绿证**：`dev-worktree.sh rebase <分支>` 一条命令成功、工作树干净、预设刷到 origin/main 版本；
③ **不许误伤**：预设内容与 origin/main **不一致**（= 开发者自己的研发模式改动）时必须**停手**：
   非零退出、且**不删除**那些文件（预设是主干资产，但别人的在办改动不能被静默吞掉）。

case_ids 口径：本测试属 **dev 工具链**，与同族 `test_agent_presets_guard.py`（#3851）沿用同一组
case id。仓库目前没有「开发工具链」用例族，本 PR **未新建**用例——它不是 agent 行为，
塞进行为用例库会污染覆盖矩阵（见 PR 说明）。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dev-worktree.sh"
PRESET_FILE = ".agent-presets/migao/preset.yml"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _script(repo: Path, *args: str, env: dict, check: bool = True):
    return subprocess.run(
        ["bash", str(repo / "scripts" / "dev-worktree.sh"), *args],
        cwd=str(repo),
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture()
def scenario(tmp_path: Path):
    """真 git 仓库：main 已入库预设（v2），分支 `old` 早于预设入库（HEAD 不含该路径）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "tester")

    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "branch", "old")  # ← 早于预设入库

    preset = repo / PRESET_FILE
    preset.parent.mkdir(parents=True)
    preset.write_text("version: 1.0.0\n", encoding="utf-8")
    _git(repo, "add", ".agent-presets")
    _git(repo, "commit", "-qm", "presets v1")
    preset.write_text("version: 2.0.0\n", encoding="utf-8")
    _git(repo, "add", ".agent-presets")
    _git(repo, "commit", "-qm", "presets v2")

    # 让脚本能解析到 origin/main（无远程时 refresh_presets 会警告并继续按本地 origin/main 刷新）
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    (repo / "scripts").mkdir()
    (repo / "scripts" / "dev-worktree.sh").write_bytes(SCRIPT.read_bytes())

    env = {**os.environ, "MIGAO_WT_BASE": str(tmp_path / "wt")}
    return repo, env, tmp_path / "wt" / "old"


def test_add_refreshes_presets_and_creates_the_trap(scenario):
    """① add 会把预设刷进工作区（这正是 rebase 被挡的来源）—— 红证的前提条件。"""
    repo, env, wt = scenario
    _script(repo, "add", "old", env=env)

    assert (wt / PRESET_FILE).read_text(encoding="utf-8") == "version: 2.0.0\n", (
        "add 应把 .agent-presets/** 刷新到 origin/main 版本（v2）"
    )

    # ② 红证：不加处置时 rebase 必失败（git 拒绝覆盖/丢弃这些「本地改动」）
    failed = _git(wt, "rebase", "origin/main", check=False)
    assert failed.returncode != 0, (
        "夹具没造出 #3972 的形态：rebase 竟然成功了（预设差异没能挡住它）"
    )
    _git(wt, "rebase", "--abort", check=False)


def test_rebase_subcommand_discards_snapshot_then_rebases(scenario):
    """② 绿证：`dev-worktree.sh rebase` 一条命令走通，且收尾状态干净。"""
    repo, env, wt = scenario
    _script(repo, "add", "old", env=env)

    out = _script(repo, "rebase", "old", env=env)
    assert "✅ rebase 完成" in out.stdout

    assert _git(wt, "log", "-1", "--format=%s").stdout.strip() == "presets v2", (
        "rebase 后应落在 origin/main 的最新提交上"
    )
    assert _git(wt, "status", "--porcelain").stdout.strip() == "", (
        "rebase 完成后工作树必须干净（预设差异已被丢弃并重新刷新）"
    )
    assert (wt / PRESET_FILE).read_text(encoding="utf-8") == "version: 2.0.0\n"

    # 幂等：再跑一次不应报错、状态不变
    _script(repo, "rebase", "old", env=env)
    assert _git(wt, "status", "--porcelain").stdout.strip() == ""


def test_rebase_subcommand_refuses_to_discard_foreign_preset_edits(scenario):
    """③ 不许误伤：预设与 origin/main 不一致（在办改动）⇒ 停手、非零退出、不删文件。"""
    repo, env, wt = scenario
    _script(repo, "add", "old", env=env)

    # 模拟开发者正在改研发模式：把刷新进来的快照改成与 origin/main 不同的内容
    edited = wt / PRESET_FILE
    edited.write_text("version: 9.9.9-local-wip\n", encoding="utf-8")

    failed = _script(repo, "rebase", "old", env=env, check=False)
    assert failed.returncode != 0, "与 origin/main 不一致的预设改动必须让子命令停手"
    assert "拒绝自动丢弃" in (failed.stdout + failed.stderr)
    assert edited.exists() and edited.read_text(encoding="utf-8") == "version: 9.9.9-local-wip\n", (
        "停手必须保留开发者的在办预设改动（不得静默删除）"
    )
