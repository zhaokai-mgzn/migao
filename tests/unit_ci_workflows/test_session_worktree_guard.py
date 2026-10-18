# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012。）
"""主工作树的 pre-commit 守卫（issue #7229）—— 防「提交落到别的会话的分支」。

## 这守的是什么（实测事故，逐字）

2026-10-18：两个 agent 会话共用主工作树。会话 B 在其中 `git checkout fix/7222-fabric-sale-form`，
会话 A（本会话）随后 `git add … && git commit` ⇒ **提交落在 B 的分支上**，并被 `git push` 推上去
（对方 PR 会带上一份与议题无关的改动）。同源事故：`git add -A` 把别人未跟踪的 `acceptance/**`
（含**活 JWT**）扫进提交 ⇒ 凭据守卫 + gitleaks 判红，机器人评审线程把合并卡成 BLOCKED。

远端侧（分支保护 / CI）对"提交落错分支"**零感知**：推送时一切看起来正常。唯一有效的位置是本地 commit 前，
而这里此前完全空白（`core.hooksPath` 未设）。

## 判据分组（每组都能**单独**变红）

① **主工作树 × 非 main 分支 ⇒ 拒提交**（红证 = 删掉钩子里那段判断 ⇒ 用例必红）。
② **防修过头**：独立工作区（`.git` 是**文件**）在同一分支上 ⇒ **必须放行**（否则并行开发的正常路径被拦死）。
③ **防修过头**：主工作树 × `main` 分支 ⇒ **必须放行**（既有正常路径）。
④ 逃逸口 `MIGAO_MAIN_TREE_COMMIT=1` ⇒ 放行且打印警告（"确有需要"的出口必须真可用）。
⑤ **接线**：`dev-worktree.sh hooks-install` 幂等设置 `core.hooksPath=.githooks`，且 `cmd_add` 会自动接线
   （否则钩子永远装不上 = 判据绿而现实空白）。

## 替身口径

用**真 git 仓库**（`git init` + 一次提交）跑钩子本体：主工作树 = 普通仓库（`.git` 是目录）；
独立工作区 = `git worktree add` 出来的目录（`.git` 是文件）。钩子通过 `bash .githooks/pre-commit` 直接执行，
cwd 设为目标树 —— 与 git 调用它的方式一致（git 在仓库根执行 hook）。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / ".githooks" / "pre-commit"
DEV_WORKTREE = REPO_ROOT / "scripts" / "dev-worktree.sh"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture()
def main_tree(tmp_path: Path) -> Path:
    """主工作树：普通 git 仓库（`.git` 是**目录**）。"""
    repo = tmp_path / "main-tree"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _run_hook(cwd: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("MIGAO_MAIN_TREE_COMMIT", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(["bash", str(HOOK)], cwd=str(cwd), env=env,
                          capture_output=True, text=True, timeout=60)


# ── ① 主工作树 × 非 main ⇒ 拒提交 ──────────────────────────────────────────────

def test_blocks_commit_in_main_tree_on_non_main_branch(main_tree: Path):
    _git(main_tree, "checkout", "-q", "-b", "fix/some-work")
    proc = _run_hook(main_tree)
    assert proc.returncode != 0, f"主工作树的非 main 分支上必须拒提交；实测退出码 {proc.returncode}\n{proc.stdout}{proc.stderr}"
    assert "拒绝提交" in proc.stderr, "必须给出中文拒绝理由（可归因）"
    assert "dev-worktree.sh add" in proc.stderr, "必须给出**真可行动**的出口（建独立工作区）"
    assert "fix/some-work" in proc.stderr, "必须点名当前分支（否则人不知道 HEAD 被谁换了）"


# ── ② 独立工作区 ⇒ 放行（防修过头）────────────────────────────────────────────

def test_allows_linked_worktree_on_non_main_branch(main_tree: Path, tmp_path: Path):
    wt = tmp_path / "wt"
    _git(main_tree, "worktree", "add", "-q", "-b", "fix/linked", str(wt))
    assert (wt / ".git").is_file(), "前提：linked worktree 的 .git 是文件（否则本用例测的不是那条路径）"
    proc = _run_hook(wt)
    assert proc.returncode == 0, f"独立工作区必须放行；实测 {proc.returncode}\n{proc.stdout}{proc.stderr}"


# ── ③ 主工作树 × main ⇒ 放行（防修过头）───────────────────────────────────────

def test_allows_main_branch_in_main_tree(main_tree: Path):
    proc = _run_hook(main_tree)
    assert proc.returncode == 0, f"主工作树的 main 分支必须放行；实测 {proc.returncode}\n{proc.stderr}"


# ── ④ 逃逸口 ──────────────────────────────────────────────────────────────────

def test_escape_hatch_allows_but_warns(main_tree: Path):
    _git(main_tree, "checkout", "-q", "-b", "fix/deliberate")
    proc = _run_hook(main_tree, {"MIGAO_MAIN_TREE_COMMIT": "1"})
    assert proc.returncode == 0, f"逃逸口必须真可用；实测 {proc.returncode}\n{proc.stderr}"
    assert "MIGAO_MAIN_TREE_COMMIT" in proc.stderr and "⚠️" in proc.stderr, "放行时必须打印醒目警告"


# ── ⑤ 软警告：acceptance/**/out/*.json(l) ─────────────────────────────────────

def test_warns_on_staged_acceptance_out_artifacts(main_tree: Path):
    out = main_tree / "acceptance" / "2026-10-18-demo" / "out"
    out.mkdir(parents=True)
    (out / "results.json").write_text("{}\n", encoding="utf-8")
    _git(main_tree, "add", "acceptance/2026-10-18-demo/out/results.json")
    proc = _run_hook(main_tree)
    assert proc.returncode == 0, "软警告不得升级成拦截（判红交给远端凭据守卫）"
    assert "acceptance/**/out" in proc.stderr, f"必须警告机器产物形态；实测：{proc.stderr}"
    assert "git restore --staged" in proc.stderr, "警告必须给出可复制的撤销命令"


# ── ⑥ 接线：hooks-install 幂等 + add 自动接线 ─────────────────────────────────

def test_hooks_install_is_idempotent_and_wired(main_tree: Path):
    body = DEV_WORKTREE.read_text(encoding="utf-8")
    assert "hooks-install)" in body, "dev-worktree.sh 必须提供 hooks-install 子命令（否则钩子无处安装）"
    assert "core.hooksPath .githooks" in body, "hooks-install 必须设置 core.hooksPath=.githooks"
    # 幂等：连跑两次都成功且读数一致（在真仓库上跑，避免自证空转）
    for _ in range(2):
        # 测试缝：`REPO_ROOT` 由脚本位置推导（env 改不动），故用 MIGAO_HOOKS_GIT_DIR 定向到临时仓库，
        # 避免判据把配置写进真仓库（那会让"自证"变成污染）。
        proc = subprocess.run(["bash", str(DEV_WORKTREE), "hooks-install"], cwd=str(main_tree),
                              capture_output=True, text=True, timeout=120,
                              env={**os.environ, "MIGAO_HOOKS_GIT_DIR": str(main_tree),
                                   "MIGAO_HOOKS_DIR": str(HOOK.parent)})
        assert proc.returncode == 0, f"hooks-install 必须幂等成功；实测 {proc.returncode}\n{proc.stderr}"
        got = subprocess.run(["git", "config", "--get", "core.hooksPath"], cwd=str(main_tree),
                             capture_output=True, text=True).stdout.strip()
        assert got == ".githooks", f"core.hooksPath 必须为 .githooks；实测 {got!r}"
    # add 路径自动接线：源码里 cmd_add 必须提到 core.hooksPath（事件驱动，用户不必记得）
    cmd_add_body = body[body.index("\ncmd_add() {"):]
    cmd_add_body = cmd_add_body[:cmd_add_body.index("\n}\n")]
    assert "core.hooksPath" in cmd_add_body, "cmd_add 必须自动接线钩子（否则新工作区里守卫常年空白）"


def test_hook_is_executable_and_declares_case_ids():
    assert HOOK.exists(), f"钩子缺失：{HOOK}"
    assert os.access(HOOK, os.X_OK), "钩子必须可执行（chmod +x；否则 git 调它时静默不跑）"
    assert "case_ids: MC-012" in HOOK.read_text(encoding="utf-8"), "钩子头部必须声明 case_ids（QA Growth Gate）"
