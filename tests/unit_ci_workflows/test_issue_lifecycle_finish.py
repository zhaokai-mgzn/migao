# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 —— 见
#   tests/unit_ci_workflows/test_resolve_stale_bot_threads.py 的同款声明与 `.github/cases/misc.yml`
#   MC-012「CI workflow 结构由 pytest 单测验证」的登记。本 PR 不新建用例族。）
"""`scripts/issue-lifecycle.sh` —— 「一个 issue 收尾」的单一入口（事件驱动清理，非定时）。

## 这守的是什么

研发模式的收尾**原先靠人或 agent「记得」**：验证完要手动 `worktree remove` + `branch -D`
+ `push origin --delete` + 清 `pr-body-*.md` / `tests/tmp/*`。漏一步就留下垃圾，而
**没有任何东西会变红**（存量分支/工作区只增不减）。

⇒ 本单把收尾做成**一条命令**（`finish` / `prune --apply`），并**自证干净**。
**刻意不做定时任务**（用户裁定）：无人值守地删东西不安全，且每个周期都烧 CI 分钟。

## 用例分组（每组都要有能**单独**让它变红的注入）

① **fail-closed**：PR 仍 open / 从未有 PR ⇒ **什么都不删**（worktree、本地分支、远程分支三者
   逐项断言仍在）—— 这是最重要的一条：它保护**在飞分支**；
   且判据**不得**是 `--merged` / `git cherry` / commit 可达性（squash 合并下结构性失效）；
② **合并 ⇒ 三者都清**：worktree + 本地分支 + 远程分支，且**自证输出**三项都为空/不存在；
③ **活锚保护**：`readlink "$HOME/.dsh/.agent-presets/migao"` 解析出的目标进「待清理集合」
   ⇒ **拒删并报错**（#3956 实证：误删软链目标 ⇒ DSH 静默加载不到研发模式）；
④ **过程产物清 / 仓库资产不动**：`.pytest_cache` / `pr-body-*.md` / `tests/tmp/*` ⇒ 被清；
   `acceptance/**` / `docs/**` ⇒ **一字不动**；
⑤ **批量默认 dry-run ⇒ 零删除**，`--apply` 才删；
⑥ **幂等**：已清理过的分支再跑 ⇒ 不报错、不误删。

夹具一律是 `tmp_path` 下的**真 git 仓库 + 真 bare origin + 真 worktree**（不是 mock）：
判据本体就是 git 语义，mock 掉 git 等于把被测对象换成替身（`migao-acceptance` §19.1「绿了但没跑」）。
`gh` 用**替身可执行文件**注入（`MIGAO_GH_BIN`）—— 只换 CLI 边界，不 mock 被测函数。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "issue-lifecycle.sh"
MODULE = REPO_ROOT / "scripts" / "issue_lifecycle.py"

ANCHOR_REL = Path(".dsh") / ".agent-presets" / "migao"


def _load_module():
    """按文件路径加载被测模块（`scripts/` 不是包，无法 import）。"""
    spec = importlib.util.spec_from_file_location("issue_lifecycle", MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载被测模块（判定本体缺失即门禁空转）：{MODULE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} 失败：{proc.stderr}"
    return proc


def _branches(cwd: Path) -> set[str]:
    out = _git(cwd, "branch", "--format=%(refname:short)").stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


def _remote_branches(cwd: Path) -> set[str]:
    out = _git(cwd, "ls-remote", "--heads", "origin").stdout
    return {line.split("refs/heads/", 1)[1].strip() for line in out.splitlines() if "refs/heads/" in line}


def _worktree_paths(cwd: Path) -> set[str]:
    out = _git(cwd, "worktree", "list", "--porcelain").stdout
    return {line.split(" ", 1)[1] for line in out.splitlines() if line.startswith("worktree ")}


def _write_gh(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


class Fixture:
    """真 bare origin + 真克隆 + 真 worktree 的夹具句柄。"""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.origin = tmp_path / "origin.git"
        self.repo = tmp_path / "repo"
        self.wt_base = tmp_path / "migao-wt"
        self.home = tmp_path / "home"
        self.bin = tmp_path / "bin"
        self.home.mkdir()
        self.bin.mkdir()
        self.wt_base.mkdir()
        self.gh_log = tmp_path / "gh-calls.log"

        _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(self.origin))
        _git(tmp_path, "clone", "-q", str(self.origin), str(self.repo))
        _git(self.repo, "config", "user.email", "fixture@example.com")
        _git(self.repo, "config", "user.name", "fixture")
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        _git(self.repo, "add", "README.md")
        _git(self.repo, "commit", "-q", "-m", "init")
        _git(self.repo, "push", "-q", "-u", "origin", "main")

        # 默认替身：没有任何已合并 PR（= 「从未有 PR」形态）
        self.set_merged_prs([])

    # ── gh 替身 ────────────────────────────────────────────────────────────
    def set_merged_prs(self, branches: list[str]) -> None:
        """让 `gh pr list --state merged` 返回这些 head 分支（模拟 GitHub 侧事实）。"""
        # ⚠️ 必须同时给 `state` 与 `headRefName`：脚本的**逐分支**判据查 `--json number,state`
        # 并判 `state == "MERGED"`；**批量**判据（复用 agent-presets-guard 的 _pr_merged_branches）
        # 查 headRefName。只给一个 ⇒ 另一条路径被静默判成「未合并」（本文件初版即此错）。
        rows = ",".join(
            '{"number":%d,"state":"MERGED","headRefName":"%s"}' % (i + 1, b)
            for i, b in enumerate(branches)
        )
        _write_gh(
            self.bin / "gh",
            "printf '%s\\n' \"$*\" >> \"${GH_CALL_LOG:-/dev/null}\"\n"
            'if [ "${1:-}" = "pr" ] && [ "${2:-}" = "list" ]; then\n'
            f"  printf '%s\\n' '[{rows}]'\n"
            "  exit 0\n"
            "fi\n"
            "echo '替身 gh：只实现了 pr list' >&2\n"
            "exit 1\n",
        )

    # ── 仓库操作 ───────────────────────────────────────────────────────────
    def add_branch_with_worktree(self, branch: str, name: str | None = None) -> Path:
        """造一个「在飞分支」+ 它的 worktree（默认落在 wt_base/<name>）。"""
        path = self.wt_base / (name or branch.split("/", 1)[-1])
        _git(self.repo, "branch", branch, "main")
        _git(self.repo, "worktree", "add", "-q", str(path), branch)
        return path

    def push_branch(self, branch: str) -> None:
        _git(self.repo, "push", "-q", "origin", f"{branch}:{branch}")

    def anchor_link(self, target: str) -> Path:
        """把活锚软链指向 target（真软链，不是 mock）。"""
        link = self.home / ANCHOR_REL
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)
        return link

    # ── 调用被测脚本 ───────────────────────────────────────────────────────
    def env(self, extra: dict | None = None) -> dict:
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env["MIGAO_WT_BASE"] = str(self.wt_base)
        env["MIGAO_GH_BIN"] = str(self.bin / "gh")
        # ⚠️ 批量路径复用 `scripts/agent-presets-guard.py` 的 `_pr_merged_branches`，
        # 它调的是**裸 `gh`**（不认 MIGAO_GH_BIN）⇒ 必须把替身目录放进 PATH，
        # 否则批量判据会退化成「gh 不可用」⇒ exit 3（本文件初版即此错）。
        env["PATH"] = str(self.bin) + os.pathsep + env.get("PATH", "")
        env["GH_CALL_LOG"] = str(self.gh_log)
        env.pop("MIGAO_ANCHOR", None)
        env.update(extra or {})
        return env

    def run(self, *args: str, cwd: Path | None = None, extra_env: dict | None = None):
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            cwd=str(cwd or self.repo), capture_output=True, text=True,
            env=self.env(extra_env),
        )


@pytest.fixture()
def fx(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path)


# ── ① fail-closed ─────────────────────────────────────────────────────────

def test_open_pr_deletes_nothing(fx: Fixture):
    """PR 仍 open（= 不在 merged 集合里）⇒ 三者逐项仍在。"""
    wt = fx.add_branch_with_worktree("fix/inflight")
    fx.push_branch("fix/inflight")

    proc = fx.run("finish", "fix/inflight")

    assert proc.returncode != 0, f"未合并必须 fail-closed，实际 exit=0：\n{proc.stdout}\n{proc.stderr}"
    assert str(wt) in _worktree_paths(fx.repo), "未合并却删了 worktree"
    assert "fix/inflight" in _branches(fx.repo), "未合并却删了本地分支"
    assert "fix/inflight" in _remote_branches(fx.repo), "未合并却删了远程分支"
    assert "未合并" in (proc.stdout + proc.stderr), "必须明确说明拒绝原因"


def test_never_had_pr_deletes_nothing(fx: Fixture):
    """从未有 PR（merged 集合为空）⇒ 同样 fail-closed。"""
    wt = fx.add_branch_with_worktree("fix/no-pr")
    fx.set_merged_prs([])

    proc = fx.run("finish", "fix/no-pr")

    assert proc.returncode != 0, f"从未有 PR 必须 fail-closed：\n{proc.stdout}"
    assert str(wt) in _worktree_paths(fx.repo)
    assert "fix/no-pr" in _branches(fx.repo)
    # 「拒绝」必须是被**判出来**的，不是"脚本压根没跑"（后者会让本条恒绿）
    assert "未合并" in (proc.stdout + proc.stderr), f"必须点明拒绝原因：\n{proc.stdout}\n{proc.stderr}"


def test_gh_unavailable_is_three_not_zero(fx: Fixture):
    """`gh` 取不到 ⇒ **exit 3**（无法判定），不得当 0 读、更不得删。"""
    wt = fx.add_branch_with_worktree("fix/gh-missing")

    proc = fx.run("finish", "fix/gh-missing", extra_env={"MIGAO_GH_BIN": "/nonexistent/gh"})

    assert proc.returncode == 3, f"gh 缺失必须 exit=3（不是 0/1）：exit={proc.returncode}\n{proc.stdout}"
    assert str(wt) in _worktree_paths(fx.repo)


# ── ② 已合并 ⇒ 三者都清 + 自证 ─────────────────────────────────────────────

def test_merged_deletes_worktree_local_and_remote_branch(fx: Fixture):
    """已合并 ⇒ worktree + 本地分支 + 远程分支全清，且自证输出三项为空/不存在。"""
    wt = fx.add_branch_with_worktree("fix/done")
    fx.push_branch("fix/done")
    fx.set_merged_prs(["fix/done"])

    proc = fx.run("finish", "fix/done")

    assert proc.returncode == 0, f"已合并应成功：\n{proc.stdout}\n{proc.stderr}"
    assert str(wt) not in _worktree_paths(fx.repo), "worktree 未清"
    assert "fix/done" not in _branches(fx.repo), "本地分支未清"
    assert "fix/done" not in _remote_branches(fx.repo), "远程分支未清"
    out = proc.stdout
    assert "自证" in out, "必须打印自证段"
    assert "worktree" in out and "本地分支" in out and "远程分支" in out


def test_judgement_never_uses_commit_reachability(fx: Fixture):
    """判据**不得**是 `--merged` / `git cherry` / 祖先可达（squash 合并下结构性失效）。

    ⚠️ 断言的是**实际发出的 `gh` 调用参数**（结构化证据，替身已把它记进 `GH_CALL_LOG`），
    **不是源码文本**：源码注释里写着「squash 下 commit 可达性与 `git cherry` 结构性失效」
    是在**解释为什么不能用它** —— 读文本会把这段解释本身判红（判据被自己的文案喂红）。
    """
    fx.add_branch_with_worktree("fix/merge-probe")
    fx.set_merged_prs(["fix/merge-probe"])

    fx.run("finish", "fix/merge-probe", "--dry-run")

    calls = fx.gh_log.read_text(encoding="utf-8") if fx.gh_log.exists() else ""
    assert calls.strip(), "替身没有记录到任何 gh 调用 ⇒ 本判据未跑（不得当通过）"
    assert "--state merged" in calls, f"判据必须查 PR 状态：\n{calls}"
    for forbidden in ("--merged", "cherry", "merge-base", "is-ancestor"):
        assert forbidden not in calls, f"「PR 已合并」判据里出现了 commit 可达性手法：{forbidden}\n{calls}"


# ── ③ 活锚保护 ─────────────────────────────────────────────────────────────

def test_anchor_target_is_never_deleted(fx: Fixture):
    """活锚解析出的目标进「待清理集合」⇒ 拒删并报错（#3956 形态）。"""
    wt = fx.add_branch_with_worktree("fix/anchor-trap", name="anchor-trap")
    fx.anchor_link(str(wt))

    proc = fx.run("finish", "fix/anchor-trap")

    assert proc.returncode != 0, f"活锚目标必须拒删：\n{proc.stdout}"
    assert "活锚" in (proc.stdout + proc.stderr), "必须点明是活锚保护"
    assert str(wt) in _worktree_paths(fx.repo), "活锚目标被删了（DSH 会静默加载不到研发模式）"
    assert "fix/anchor-trap" in _branches(fx.repo), "活锚目标的本地分支被删了"


def test_anchor_protection_is_negative_controlled(fx: Fixture):
    """负控：同一条命令、同一个目标，**没有活锚指向它**时确实会删 —— 证明上一条不是恒绿。"""
    wt = fx.add_branch_with_worktree("fix/anchor-trap", name="anchor-trap")
    fx.set_merged_prs(["fix/anchor-trap"])

    proc = fx.run("finish", "fix/anchor-trap")

    assert proc.returncode == 0, f"无活锚指向时应正常清理：\n{proc.stdout}\n{proc.stderr}"
    assert str(wt) not in _worktree_paths(fx.repo), "负控失败：本应被清理"


# ── ④ 过程产物清 / 仓库资产不动 ────────────────────────────────────────────

def test_process_artifacts_removed_repo_assets_kept(fx: Fixture):
    """`.pytest_cache` / `pr-body-*.md` / `tests/tmp/*` 被清；`acceptance/**` / `docs/**` 一字不动。"""
    wt = fx.add_branch_with_worktree("fix/artifacts")
    fx.push_branch("fix/artifacts")
    fx.set_merged_prs(["fix/artifacts"])

    (fx.repo / "pr-body-5123.md").write_text("body\n", encoding="utf-8")
    (fx.repo / ".pytest_cache").mkdir(exist_ok=True)
    (fx.repo / ".pytest_cache" / "v").mkdir(exist_ok=True)
    (fx.repo / "tests" / "tmp").mkdir(parents=True, exist_ok=True)
    (fx.repo / "tests" / "tmp" / "scratch.txt").write_text("tmp\n", encoding="utf-8")
    (fx.repo / "scripts" / "__pycache__").mkdir(parents=True, exist_ok=True)
    (fx.repo / "scripts" / "__pycache__" / "x.pyc").write_text("x\n", encoding="utf-8")
    asset = fx.repo / "acceptance" / "2026-09" / "report.md"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_text("证据\n", encoding="utf-8")
    doc = fx.repo / "docs" / "wiki" / "INDEX.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("索引\n", encoding="utf-8")

    proc = fx.run("finish", "fix/artifacts")

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert not (fx.repo / "pr-body-5123.md").exists(), "PR body 落点文件未清"
    assert not (fx.repo / ".pytest_cache").exists(), ".pytest_cache 未清"
    assert not (fx.repo / "tests" / "tmp" / "scratch.txt").exists(), "tests/tmp 过程产物未清"
    assert not (fx.repo / "scripts" / "__pycache__").exists(), "__pycache__ 未清"
    assert asset.read_text(encoding="utf-8") == "证据\n", "仓库资产 acceptance/** 被动过"
    assert doc.read_text(encoding="utf-8") == "索引\n", "仓库资产 docs/** 被动过"


# ── ⑤ 批量：默认 dry-run ⇒ 零删除 ──────────────────────────────────────────

def test_prune_defaults_to_dry_run(fx: Fixture):
    """`prune` 默认 dry-run ⇒ **零删除**；`--apply` 才删。"""
    wt = fx.add_branch_with_worktree("fix/batch-a")
    fx.push_branch("fix/batch-a")
    fx.set_merged_prs(["fix/batch-a"])

    dry = fx.run("prune")
    assert dry.returncode == 0, f"{dry.stdout}\n{dry.stderr}"
    assert "dry-run" in dry.stdout, f"默认必须自报 dry-run：\n{dry.stdout}"
    assert str(wt) in _worktree_paths(fx.repo), "dry-run 竟然删了 worktree"
    assert "fix/batch-a" in _branches(fx.repo), "dry-run 竟然删了本地分支"
    assert "fix/batch-a" in _remote_branches(fx.repo), "dry-run 竟然删了远程分支"

    applied = fx.run("prune", "--apply")
    assert applied.returncode == 0, f"{applied.stdout}\n{applied.stderr}"
    assert str(wt) not in _worktree_paths(fx.repo), "--apply 未清 worktree"
    assert "fix/batch-a" not in _branches(fx.repo), "--apply 未清本地分支"
    assert "fix/batch-a" not in _remote_branches(fx.repo), "--apply 未清远程分支"


def test_prune_dry_run_leaves_unmerged_alone(fx: Fixture):
    """批量也 fail-closed：未合并的分支即使 `--apply` 也不动。"""
    wt = fx.add_branch_with_worktree("fix/batch-inflight")
    # ⚠️ 必须给**非空**已合并集合：`agent-presets-guard._pr_merged_branches` 对空结果返回 `None`
    #    （= 无法判定，与"取不到 gh"同义）⇒ 用空集合测"未合并"会变成测"无法判定"。
    fx.set_merged_prs(["fix/some-other-merged"])

    proc = fx.run("prune", "--apply")

    assert str(wt) in _worktree_paths(fx.repo), "未合并的分支被批量清理删了"
    assert "fix/batch-inflight" in _branches(fx.repo)
    # 同上：判定必须真的跑过（否则本条在"脚本不存在"时也绿）
    assert "未合并" in (proc.stdout + proc.stderr), f"必须点明拒绝原因：\n{proc.stdout}\n{proc.stderr}"


# ── ⑥ 幂等 ────────────────────────────────────────────────────────────────

def test_finish_is_idempotent(fx: Fixture):
    """已清理过的分支再跑 ⇒ 不报错、不误删。"""
    fx.add_branch_with_worktree("fix/once")
    fx.push_branch("fix/once")
    fx.set_merged_prs(["fix/once"])

    first = fx.run("finish", "fix/once")
    assert first.returncode == 0, f"{first.stdout}\n{first.stderr}"

    second = fx.run("finish", "fix/once")
    assert second.returncode == 0, f"幂等失败（第二次跑报错）：\n{second.stdout}\n{second.stderr}"
    assert "fix/once" not in _branches(fx.repo)


def test_unknown_target_is_an_error(fx: Fixture):
    """目标完全不存在（不是"已清理"）⇒ 报错，不得静默成功。"""
    proc = fx.run("finish", "fix/never-existed")
    assert proc.returncode != 0, "不存在的目标应报错"
    assert "找不到" in (proc.stdout + proc.stderr), f"必须点明找不到什么：\n{proc.stdout}\n{proc.stderr}"
