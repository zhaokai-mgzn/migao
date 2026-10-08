# case_ids: MC-012, MC-013
"""`.agent-presets/**` 版本单调性守卫（issue #3851）—— 含**红证**。

守的是这颗地雷：worktree 的 `.agent-presets/**` 是**创建时刻快照**，main 推进后工作区不会自动跟上
⇒ 这些文件相对 `origin/main` 就是「改动」（内容在**回退**）⇒ 一条 `git add -A` 就提交一个
**把研发模式回退若干版本**的 PR，而 **CI 不看 `.agent-presets/**` 的版本 ⇒ 不红**。

用例分三组：
① **红证**（判据必须能红）：版本下降 ⇒ 非零退出（真实形态用 `git checkout <旧sha> -- <文件>`）；
② **不许误伤**：合法升级必须绿（改研发模式本身不能被堵死）、与基准完全相同必须绿；
③ **fail-closed 边界**：不可判定（版本取不到 / 非 semver / ref 侧不存在）必须红，不得退化成放行；
④ `prune`：**只出清单、绝不删除**（不给 `--dry-run` 直接拒绝）。

夹具一律建在 `tmp_path` 的**真 git 仓库**里（不是 mock）——判据本体就是 git 语义，
mock 掉 git 等于把被测对象换成替身，红证会变成假绿（§18「绿了但没跑」）。
"""
from __future__ import annotations

import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from unit_ci_workflows import preset_corpus as pc

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "agent-presets-guard.py"
DEV_WORKTREE = REPO_ROOT / "scripts" / "dev-worktree.sh"
CHECK_SH = REPO_ROOT / "scripts" / "preset-anchor-check.sh"
REFRESH_SH = REPO_ROOT / "scripts" / "preset-anchor-refresh.sh"
#: **业务仓**里的预设路径（`check` 子命令仍按这个口径判 —— 与活锚无关）。
SKILL_REL = ".agent-presets/migao/skills/migao-dev-flow/SKILL.md"
#: **预设仓检出（活锚镜像）的仓根** —— S4（issue #6020）起仓根**就是** preset 目录
#: （`preset.yml` 在根，不再有 `.agent-presets/migao/` 这一层）。
#: 读那份内容的**唯一口径 = `tests/unit_ci_workflows/preset_corpus.py`**（`MIGAO_PRESET_MIRROR`
#: 由它自己按同源规则解析）。
SKILL_IN_PRESET = "skills/migao-dev-flow/SKILL.md"
PRESET_YML_IN_PRESET = "preset.yml"

SKILL_TMPL = """---
name: migao-dev-flow
version: {version}
description: 夹具技能
---

# 夹具技能 v{version}

正文占位（第 {filler} 号夹具）。
"""


def _preset_skills() -> list[Path]:
    """→ 真资产里全部技能的 `SKILL.md` 路径 —— **委派**给唯一口径 `preset_corpus`。

    🔴 本函数此前**自带第二份读取实现**（自己枚举 `PRESET_BASELINE_REFS` + `git ls-tree` +
    `git show` + 自己拼镜像候选）。它与唯一口径**各自腐烂**：候选表只覆盖固定 5 个 ref ⇒
    S4 之后（预设只在**历史**里）在 CI（无镜像）上整条读不到 ⇒
    `test_real_presets_frontmatter_is_loadable` 判红（实测：试过
    `origin/main / origin/main~1 / HEAD~1 / HEAD~2 / HEAD` 全部落空）。
    ⇒ 读法（本仓 → **历史候选** → 镜像）现在**只住在** `preset_corpus` 里，本文件零预处理。

    取不到 ⇒ **抛错**（刻意**不用** `pytest.skip`：那会污染 helper-leg 的 skip 冻结读数，
    而「判不了」也不该长得像「没东西可判」）。
    """
    root = pc.preset_root()
    if root is None:
        raise AssertionError(pc.corpus_help(SKILL_IN_PRESET))
    skills = sorted(root.glob("skills/*/SKILL.md"))
    if not skills:
        raise AssertionError(
            f"预设真资产为空（`{root}/skills/*/SKILL.md`）⇒ 判据会空跑（不许静默通过）"
        )
    return skills


def _load_guard():
    """按文件路径加载守卫模块（`scripts/` 不是包，无法 import）。

    取不到 spec/loader 时**抛错 fail-closed**（不用 `assert ... is not None`：
    那既是弱断言、又会在 `-O` 下被剥掉 —— 门禁依赖的加载不允许静默空转）。
    """
    spec = importlib.util.spec_from_file_location("agent_presets_guard", GUARD)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载守卫模块（判定本体缺失即门禁空转）：{GUARD}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD_MODULE = _load_guard()


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} 失败：{proc.stderr}"
    return proc


def _write_skill(repo: Path, version: str, filler: int = 1) -> Path:
    """写一份**业务仓形状**的技能（`repo/.agent-presets/migao/skills/<name>/SKILL.md`）。

    `check` 子命令的被检对象就是这一层（版本单调性守卫；S4 后业务仓无该路径，口径未变）。
    """
    path = repo / SKILL_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SKILL_TMPL.format(version=version, filler=filler), encoding="utf-8")
    return path


def _run_guard_anchor(repo: Path, *anchor_args: str) -> subprocess.CompletedProcess:
    """`anchor` 子命令的 CLI 调用 —— 带 S4 的**预设仓口径**参数。

    `--anchor-base ""`：预设内容在**预设仓仓根**（S4 / issue #6020；旧口径 `<仓>/.agent-presets/migao`）。
    ⚠️ 只影响 `anchor`（活锚）—— `check` 的版本单调性仍按**业务仓** `.agent-presets/**` 判，未动。
    """
    return _run_guard(repo, "anchor", *anchor_args, "--anchor-base=")


def _run_guard(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GUARD), "--repo", str(repo), *args],
        capture_output=True, text=True,
    )


@pytest.fixture()
def fixture_repo(tmp_path: Path) -> Path:
    """一个真 git 仓库：分支（= 工作区）上是 **v1.26.0**，基准 `main` 已到 **v1.28.0**。

    形状刻意与地雷一致：工作区（分支）**落后于基准**，即「创建时刻快照」。
    ⚠️ 夹具必须把 **v1.28.0 也提交**（`git reset --hard` 会连未跟踪文件一起清掉，
    只在工作区留旧文件会让夹具自己消失 —— 这不是被测对象的问题，是夹具的问题）。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "fixture")

    # ① v1.28.0 先提交（成为基准 main 的历史）
    _write_business_skill(repo, "1.28.0", filler=2)
    (repo / ".agent-presets/migao/preset.yml").write_text("name: migao\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "基准 v1.28.0")
    new_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # ② 分支（= 工作区）落在 v1.26.0：从基准分出、改成旧版并提交 —— 制造「分支落后基准」
    _git(repo, "checkout", "-q", "-b", "snapshot")
    _write_business_skill(repo, "1.26.0", filler=1)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "旧快照 v1.26.0")
    old_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # ③ 回工作区（= snapshot 分支，v1.26.0），main 仍指向 v1.28.0
    _git(repo, "checkout", "-q", "snapshot")
    _git(repo, "update-ref", "refs/heads/main", new_sha)

    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == old_sha
    assert _read_version(repo) == "1.26.0", "夹具起点必须是旧快照"
    return repo


def _write_business_skill(repo: Path, version: str, filler: int = 1) -> Path:
    """写一份**业务仓形状**（`.agent-presets/migao/skills/…`）的技能 —— `check` 子命令的被检对象。"""
    path = repo / SKILL_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SKILL_TMPL.format(version=version, filler=filler), encoding="utf-8")
    return path


def _read_version(repo: Path) -> str | None:
    text = (repo / SKILL_REL).read_text(encoding="utf-8")
    return GUARD_MODULE.parse_version(text)


def _aligned_to_ref(repo: Path) -> None:
    """把 `.agent-presets/**` 对齐到基准 `main`（即模拟「第①层防线已跑过」的起点）。

    ⚠️ 必须**同时对齐索引**：夹具仓库里分支的**索引**仍是旧快照内容，
    `git checkout <ref> -- <path>` 只更新工作区 ⇒ 会留下一个「假降级」的暂存区
    （夹具自己制造出的红，不是被测判据的红）。
    """
    _git(repo, "checkout", "main", "--", ".agent-presets/")
    _git(repo, "reset", "-q", "main")
    assert _read_version(repo) == "1.28.0"


# ── ① 红证：判据必须能红 ──────────────────────────────────────────────────────

def test_downgraded_version_is_rejected(fixture_repo: Path):
    """红证（手工改版号）：把技能 version 从 1.28.0 临时改成 1.27.0 ⇒ 必须非零退出。"""
    _aligned_to_ref(fixture_repo)                           # 先对齐 main（干净起点）
    assert _run_guard(fixture_repo, "check", "--ref", "main").returncode == 0

    _write_skill(fixture_repo, "1.27.0", filler=3)          # 只把版本号降一格
    proc = _run_guard(fixture_repo, "check", "--ref", "main")

    assert proc.returncode != 0, f"版本下降必须拒绝提交：\n{proc.stdout}"
    assert "版本下降" in proc.stdout
    assert "1.28.0 → 1.27.0" in proc.stdout
    assert "git checkout main -- .agent-presets/" in proc.stdout


def test_downgraded_file_checked_out_from_history_is_rejected(fixture_repo: Path):
    """红证（**真实形态**）：`git checkout <旧sha> -- <预设文件>` 把整份旧文件放回来 ⇒ 必须非零退出。

    这正是 issue #3851 实测的形状（某包 worktree 仍是 v1.27.0，靠人工 amend + force-push 拦住）。
    """
    old_sha = _git(fixture_repo, "rev-parse", "HEAD").stdout.strip()   # 旧快照提交（v1.26.0）
    _aligned_to_ref(fixture_repo)                                     # 先对齐 main（干净起点）

    _git(fixture_repo, "checkout", old_sha, "--", SKILL_REL)   # 旧版本文件（1.26.0）
    proc = _run_guard(fixture_repo, "check", "--ref", "main")

    assert proc.returncode != 0, f"checkout 旧版本文件必须被拦：\n{proc.stdout}"
    assert "版本下降" in proc.stdout
    assert "1.28.0 → 1.26.0" in proc.stdout


def test_unparsable_version_fails_closed(fixture_repo: Path):
    """fail-closed：`version:` 取不到 ⇒ 红。**不得**退化成「读不到就放行」。"""
    _aligned_to_ref(fixture_repo)
    (fixture_repo / SKILL_REL).write_text("---\nname: migao-dev-flow\n---\n\n# 无版本号\n", encoding="utf-8")

    proc = _run_guard(fixture_repo, "check", "--ref", "main")

    assert proc.returncode != 0
    assert "不可判定" in proc.stdout


def test_non_semver_version_fails_closed(fixture_repo: Path):
    """fail-closed：版本号不可比较（非 semver）⇒ 红。"""
    _aligned_to_ref(fixture_repo)
    (fixture_repo / SKILL_REL).write_text(
        SKILL_TMPL.format(version="latest", filler=3), encoding="utf-8"
    )

    proc = _run_guard(fixture_repo, "check", "--ref", "main")

    assert proc.returncode != 0
    assert "不可比较" in proc.stdout


def test_check_against_missing_ref_fails_closed(fixture_repo: Path):
    """fail-closed：基准 ref 不存在（git 不可判定）⇒ 红，绝不静默放行。"""
    proc = _run_guard(fixture_repo, "check", "--ref", "origin/nonexistent")

    assert proc.returncode != 0
    assert "fail-closed" in proc.stdout


# ── ② 不许误伤：升级必须绿、相同必须绿 ────────────────────────────────────────

def test_legitimate_upgrade_passes(fixture_repo: Path):
    """**合法升级必须绿**：1.28.0 → 1.29.0（改研发模式本身）不得被堵死。"""
    _aligned_to_ref(fixture_repo)
    _write_skill(fixture_repo, "1.29.0", filler=4)

    proc = _run_guard(fixture_repo, "check", "--ref", "main")

    assert proc.returncode == 0, f"合法升级被误伤：\n{proc.stdout}"
    assert "合法升级" in proc.stdout
    assert "1.28.0 → 1.29.0" in proc.stdout
    assert "拒绝提交" not in proc.stdout


def test_identical_to_ref_passes(fixture_repo: Path):
    """与基准**完全相同** ⇒ 绿（且必须把「未跑判定」说清楚，不伪装成「跑过且通过」）。"""
    _aligned_to_ref(fixture_repo)   # 逐字节对齐 main（含 preset.yml）

    proc = _run_guard(fixture_repo, "check", "--ref", "main")

    assert proc.returncode == 0, proc.stdout
    assert "未跑判定" in proc.stdout
    # 判定「没红」要看**拒绝标记**，不能拿「版本下降」当子串 —— 通过语里也含这四个字
    # （「无 `.agent-presets/**` 版本下降」），那样断言永远为真或永远误报
    assert "拒绝提交" not in proc.stdout
    assert "❌" not in proc.stdout


def test_same_version_different_content_is_rejected(fixture_repo: Path):
    """同号不同内容 ⇒ **非零退出**（跨包撞车；issue #5425 改判 —— 原先只告警、exit 0）。

    形态与「两个并行包各自只抬一格、撞到同一个号」（2026-09-24 一晚 2 次）逐字相同
    ⇒ 撞车必须当场可见，出口 = 抬号到「基准版本 + 1」。
    5 种形态的完整判据在 `tests/unit_ci_workflows/test_preset_version_collision.py`；
⚠️ S4（issue #6020）起该文件**已删** —— 预设内容迁出业务仓，同号撞车/版本单调性由**预设仓 CI**
（`.github/workflows/preset-guards.yml`）承担；本文件保留的是**业务仓读预设的链路**那一面。
    """
    _aligned_to_ref(fixture_repo)
    _write_skill(fixture_repo, "1.28.0", filler=99)   # 版本不变，正文变了

    proc = _run_guard(fixture_repo, "check", "--ref", "main")

    assert proc.returncode != 0, proc.stdout
    assert "同号不同内容 = 跨包撞车" in proc.stdout
    assert "抬号到 `1.29.0`" in proc.stdout


def test_non_versioned_preset_file_is_reported_not_judged(fixture_repo: Path):
    """无 `version:` 的预设文件（preset.yml / README.md）不参与单调性判定，但要**显式说明**。"""
    _aligned_to_ref(fixture_repo)
    (fixture_repo / ".agent-presets/migao/preset.yml").write_text(
        "name: migao\nnote: 手改\n", encoding="utf-8"
    )

    proc = _run_guard(fixture_repo, "check", "--ref", "main")

    assert proc.returncode == 0, proc.stdout
    assert "无 `version:` 字段，不参与单调性判定" in proc.stdout


def test_index_source_detects_staged_downgrade(fixture_repo: Path):
    """`--source index`：只看暂存区 —— 降级内容被 `git add` 后同样必须红。"""
    _aligned_to_ref(fixture_repo)
    _write_skill(fixture_repo, "1.26.0", filler=3)
    _git(fixture_repo, "add", "-A")   # 降级被暂存

    proc = _run_guard(fixture_repo, "check", "--ref", "main", "--source", "index")

    assert proc.returncode != 0, proc.stdout
    assert "版本下降" in proc.stdout
    assert "来源：暂存区" in proc.stdout


def test_live_lock_is_detected_and_stale_lock_is_not(tmp_path: Path):
    """会话锁判定：**活锁**（PID 存活）必须被捕获，**死锁**不得被当成占用。

    锁目录按 common git dir 定位（worktree 内 `$WT/.git` 是指针文件 —— 拼错就静默失效）。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    sessions = repo / ".git" / "sessions"
    sessions.mkdir()
    (sessions / "alive.lock").write_text(
        f"{os.getpid()}|2026-09-15 08:00:00|fix/alive-branch|{repo}", encoding="utf-8"
    )
    (sessions / "dead.lock").write_text(
        f"999999|2026-09-15 08:00:00|fix/dead-branch|{repo}", encoding="utf-8"
    )

    locked = GUARD_MODULE._locked_branches(repo)

    assert locked == {"fix/alive-branch"}


# ── ③ prune：只出清单，绝不删除 ───────────────────────────────────────────────

def test_prune_without_dry_run_is_refused(tmp_path: Path):
    """`prune` 不给 `--dry-run` ⇒ 直接拒绝（exit 2）—— 防「本意只是想看看」变成真删。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")

    proc = _run_guard(repo, "prune")

    assert proc.returncode == 2
    assert "不执行删除" in proc.stderr


def test_prune_classifies_merged_and_unmerged_worktrees(tmp_path: Path):
    """prune 判定：**已合入 + 干净** ⇒ 可安全移除；**有未合并提交 / 不干净** ⇒ 需人看。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "fixture")
    (repo / "f.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")

    merged_wt = tmp_path / "wt-merged"
    unmerged_wt = tmp_path / "wt-unmerged"
    dirty_wt = tmp_path / "wt-dirty"
    _git(repo, "worktree", "add", "-q", "-b", "fix/merged", str(merged_wt))
    _git(repo, "worktree", "add", "-q", "-b", "fix/unmerged", str(unmerged_wt))
    _git(repo, "worktree", "add", "-q", "-b", "fix/dirty", str(dirty_wt))
    # fix/merged：无独有提交（已合入）；fix/dirty：已合入但工作树脏
    (dirty_wt / "scratch.txt").write_text("未提交\n", encoding="utf-8")
    # fix/unmerged：有独有提交
    (unmerged_wt / "new.txt").write_text("未合并的工作\n", encoding="utf-8")
    _git(unmerged_wt, "add", "-A")
    _git(unmerged_wt, "commit", "-q", "-m", "未合入的提交")

    proc = _run_guard(repo, "prune", "--dry-run", "--ref", "main")

    assert proc.returncode == 0, proc.stdout
    assert "只出清单，不删除" in proc.stdout
    safe_block = proc.stdout.split("── 需人看")[0]
    manual_block = proc.stdout.split("── 需人看")[1]
    assert str(merged_wt) in safe_block
    assert str(unmerged_wt) not in safe_block and str(unmerged_wt) in manual_block
    assert "1 个提交未进 upstream" in manual_block
    assert str(dirty_wt) not in safe_block and str(dirty_wt) in manual_block
    assert "工作树不干净" in manual_block
    # 真删命令必须给出来，但脚本自己不执行
    assert "dev-worktree.sh rm" in proc.stdout
    assert merged_wt.is_dir() and unmerged_wt.is_dir() and dirty_wt.is_dir()


def _run_guard_with_env(repo: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    """同 `_run_guard`，但**可注入 env**（用于把假的 `gh` 放到 PATH 最前）。"""
    return subprocess.run(
        [sys.executable, str(GUARD), "--repo", str(repo), *args],
        capture_output=True, text=True, env=env,
    )


def _squash_repo(tmp_path: Path):
    """真 git 仓库 + 一个**squash 合并形态**的工作区。

    「squash 合并形态」= 分支有独有提交、**不是** `main` 的祖先、`git cherry` 也全是 `+`
    （本仓的合并方式含 squash ⇒ 这两条判据**结构上**看不见它）。
    返回 `(repo, worktree, fakebin)`。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "fixture")
    (repo / "f.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    wt = tmp_path / "wt-squash"
    _git(repo, "worktree", "add", "-q", "-b", "fix/squash-merged", str(wt))
    (wt / "new.txt").write_text("squash 合并前推的交付物\n", encoding="utf-8")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "squash 前的提交")
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    return repo, wt, fakebin


def _fake_gh(fakebin: Path, body: str) -> dict:
    gh = fakebin / "gh"
    gh.write_text(body, encoding="utf-8")
    gh.chmod(0o755)
    return {**os.environ, "PATH": f"{fakebin}{os.pathsep}{os.environ.get('PATH', '')}"}


def test_prune_sees_squash_merged_branch_via_pr_state(tmp_path: Path):
    """**实测缺陷**（2026-09-21）：`prune` 曾只按「祖先可达 / `git cherry` 无 `+`」判，
    而本仓含 **squash 合并** ⇒ 那两条**结构上看不见**（实测只认出 41/62）⇒ 垃圾持续堆积。

    本判据 = 「**GitHub 上 PR 已 MERGED**」这条补充判据。

    红证：把 `_pr_merged_branches` 的接入删掉（退回只按祖先/cherry）⇒ 本断言红
    （该工作区会落到「需人看」）。
    """
    repo, wt, fakebin = _squash_repo(tmp_path)
    env = _fake_gh(fakebin, '#!/bin/sh\necho \'[{"headRefName":"fix/squash-merged"}]\'\n')

    proc = _run_guard_with_env(repo, env, "prune", "--dry-run", "--ref", "main")

    assert proc.returncode == 0, proc.stdout
    safe_block = proc.stdout.split("── 需人看")[0]
    assert str(wt) in safe_block, f"squash 合并的工作区未被认出：\n{proc.stdout}"
    assert "经「PR 已合并」判据" in safe_block
    assert "「PR 已合并」这条判据**未跑**" not in proc.stdout


def test_prune_says_when_pr_state_check_did_not_run(tmp_path: Path):
    """`gh` 取不到（未登录 / 离线 / 限额）⇒ **必须显式打印「未跑」**。

    「没跑」必须长得像「没跑」—— 否则用户会把**少报的**清单当成全量
    （本仓纪律：未跑 ≠ 通过，见 `migao-dev-flow` §1/§2.1）。
    """
    repo, wt, fakebin = _squash_repo(tmp_path)
    env = _fake_gh(fakebin, "#!/bin/sh\nexit 1\n")

    proc = _run_guard_with_env(repo, env, "prune", "--dry-run", "--ref", "main")

    assert proc.returncode == 0, proc.stdout
    assert "「PR 已合并」这条判据**未跑**" in proc.stdout
    # 判不了 ⇒ **保守**落到「需人看」（不得因为查不到就判可移除）
    manual_block = proc.stdout.split("── 需人看")[1]
    assert str(wt) in manual_block


def test_prune_never_deletes_anything(tmp_path: Path):
    """红线：prune（含 --dry-run）跑完，工作区数量与目录**一个不少**。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "fixture")
    (repo / "f.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    wt = tmp_path / "wt-a"
    _git(repo, "worktree", "add", "-q", "-b", "fix/a", str(wt))
    before = _git(repo, "worktree", "list").stdout

    proc = _run_guard(repo, "prune", "--dry-run", "--ref", "main")

    assert proc.returncode == 0, proc.stdout
    assert _git(repo, "worktree", "list").stdout == before
    assert wt.is_dir()


# ── ④ 与 dev-worktree.sh 的接线 ───────────────────────────────────────────────

def test_dev_worktree_preset_guard_reads_its_own_worktree_index(tmp_path: Path):
    """回归：`preset-guard` 必须读**本工作区的索引**，而不是主仓库的索引。

    这是本单实测踩到的坑：脚本一度把 `--repo` 传成 `$REPO_ROOT`（主仓库根）⇒ 在 worktree 里跑
    `preset-guard` 时读的是**另一个仓库的索引** ⇒ 本工作区的降级在索引侧看不见 ⇒ **绿了但没跑**
    （判据静默通过，而它防的正是这种「以为查过、其实没查」）。故这里**在 worktree 内**制造降级，
    并要求判据能红 —— 判定源错了这条就会失败。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "fixture")
    _write_business_skill(repo, "1.28.0", filler=2)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "v1.28.0")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    # 主仓库根也要能解析到两件套（worktree 由它 add 出来）
    (repo / "scripts").mkdir()
    (repo / "scripts" / "dev-worktree.sh").write_bytes(DEV_WORKTREE.read_bytes())
    (repo / "scripts" / "agent-presets-guard.py").write_bytes(GUARD.read_bytes())

    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "fix/wt", str(wt))
    # worktree 内的脚本（与 `add` 后的真实布局一致）
    (wt / "scripts").mkdir(exist_ok=True)
    (wt / "scripts" / "dev-worktree.sh").write_bytes(DEV_WORKTREE.read_bytes())
    (wt / "scripts" / "agent-presets-guard.py").write_bytes(GUARD.read_bytes())

    # 在 worktree 内制造「旧快照 + 已暂存」：只改 worktree 的索引，主仓库索引保持干净
    _write_business_skill(wt, "1.26.0", filler=1)
    _git(wt, "add", "-A")

    proc = subprocess.run(
        ["bash", str(wt / "scripts" / "dev-worktree.sh"), "preset-guard", "--source", "index"],
        cwd=wt, capture_output=True, text=True,
    )

    assert proc.returncode != 0, (
        "worktree 内的降级没有被判出来 —— 判据很可能读错了仓库的索引（--repo 传成了主仓库根）\n"
        + proc.stdout + proc.stderr
    )
    assert "版本下降" in proc.stdout
    assert "1.28.0 → 1.26.0" in proc.stdout


def test_dev_worktree_script_wires_guard_and_refresh():
    """`dev-worktree.sh` 必须真的接上：① 有 preset-guard / prune 子命令；② **不再**有预设快照动作。

    🔴 S4（issue #6020）：预设迁出业务仓 ⇒ 「把 `.agent-presets/**` 刷到业务仓 origin/main」这套动作
    （`refresh_presets` / `discard_preset_snapshot`）**必须消失** —— 留着它就是对着一个不存在的路径
    空转，还会让人以为「预设随业务仓」。这条判据反向钉住它（旧形态写回 ⇒ 必红）。
    """
    source = DEV_WORKTREE.read_text(encoding="utf-8")

    assert "preset-guard)" in source
    assert "prune)" in source
    # 只看**代码**：整行注释里的沿革说明（「S4 删掉了 refresh_presets()」）必须能写，
    # 旧**动作**（函数定义 / 调用 / `checkout origin/main -- .agent-presets/`）才是不许回来的。
    code = "\n".join(l for l in source.splitlines() if not re.match(r"^\s*#", l))
    for gone in ("refresh_presets", "discard_preset_snapshot", "checkout origin/main -- .agent-presets/"):
        assert gone not in code, f"S4 后不得再有「预设随业务仓」的动作：{gone}"
    # 反面约束：不得**使用**「眼不见为净」的手法（会把合法的预设改动一起吞掉）。
    # 注释里提到这两个词是**禁止说明**，故只禁它们在 git 命令行里出现。
    for banned in ("update-index", "skip-worktree", "assume-unchanged"):
        assert banned not in source, f"脚本里出现了被禁手法：{banned}"


def test_dev_worktree_preset_guard_subcommand_is_wired_to_real_guard(tmp_path: Path):
    """端到端：`dev-worktree.sh preset-guard` 在真仓库上跑通（把判定接到脚本上，不是各自为政）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "fixture")
    _write_business_skill(repo, "1.28.0", filler=2)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "v1.28.0")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    # 脚本按相对自身位置解析 ROOT/守卫脚本，故把两件套复制进夹具仓库
    (repo / "scripts").mkdir()
    (repo / "scripts" / "dev-worktree.sh").write_bytes(DEV_WORKTREE.read_bytes())
    (repo / "scripts" / "agent-presets-guard.py").write_bytes(GUARD.read_bytes())

    ok = subprocess.run(
        ["bash", str(repo / "scripts" / "dev-worktree.sh"), "preset-guard"],
        cwd=repo, capture_output=True, text=True,
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr

    _write_business_skill(repo, "1.27.0", filler=2)   # 降级
    bad = subprocess.run(
        ["bash", str(repo / "scripts" / "dev-worktree.sh"), "preset-guard"],
        cwd=repo, capture_output=True, text=True,
    )
    assert bad.returncode != 0, bad.stdout
    assert "版本下降" in bad.stdout


def test_guard_script_itself_states_the_third_layer(monkeypatch=None):
    """文档/输出里必须点出**第三层防御**（`#3843` 的 drift_audit 单调性守卫），避免读者以为只有两层。"""
    text = GUARD.read_text(encoding="utf-8")

    assert "#3843" in text
    assert "drift_audit" in text


# ── ⑤ 活锚新鲜度（地雷 B，issue #4026）────────────────────────────────────────
# 守的是「内容全对，但**到不了加载点**」：活锚落后 main 时，下一次改预设的改进**永远进不来**，
# 而**没有任何东西会因此变红**（实测活锚曾指向落后 42 个提交的主工作区）。
# 夹具一律是**三个真 git 仓库**（origin / baseline / mirror），不 mock —— 判据本体就是 git 语义。


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "fixture@example.com")
    _git(path, "config", "user.name", "fixture")


def _write_preset_skill(preset_repo: Path, version: str, filler: int = 1) -> Path:
    """把技能写进一个**预设仓检出**的 `skills/<name>/SKILL.md`（仓根 = preset 目录）。"""
    path = preset_repo / SKILL_IN_PRESET
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SKILL_TMPL.format(version=version, filler=filler), encoding="utf-8")
    return path


def _seed_preset(repo: Path, version: str, filler: int = 1) -> None:
    """把一个「预设仓检出」pip 到 `repo` 的**仓根**（S4：仓根就是 preset 目录）。

    ⚠️ 与 `fixture_repo`（业务仓形状，`.agent-presets/migao/`）刻意不同：本函数服务**活锚**那组用例
    —— 换链后活锚指向的是**预设仓镜像的仓根**。
    """
    _write_preset_skill(repo, version, filler=filler)
    (repo / PRESET_YML_IN_PRESET).write_text("name: migao\n", encoding="utf-8")


@pytest.fixture()
def anchor_env(tmp_path: Path) -> dict:
    """三仓夹具：`origin`（裸仓 = 权威 main）+ `baseline`（= 你的工作区，已 fetch）+ `mirror`（活锚镜像）。

    历史形状刻意对齐 #4026 的两种落后形态：
      c1 = preset **v1.28.0** → c2 = preset **v1.29.0** → c3 = **与预设无关**的改动。
    ⇒ mirror 结账在 `c2`：**内容与 main 完全相同、sha 落后 1**（隐蔽形态，正是本单病灶）；
      结账在 `c1`：内容与版本都落后（显性形态）。
    """
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))

    seed = tmp_path / "seed"
    _init_repo(seed)
    _seed_preset(seed, "1.28.0")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "c1 v1.28.0")
    c1 = _git(seed, "rev-parse", "HEAD").stdout.strip()
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "origin", "main")

    _seed_preset(seed, "1.29.0", filler=2)
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "c2 v1.29.0")
    c2 = _git(seed, "rev-parse", "HEAD").stdout.strip()
    (seed / "unrelated.txt").write_text("与预设无关的改动\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "c3 与预设无关")
    c3 = _git(seed, "rev-parse", "HEAD").stdout.strip()
    _git(seed, "push", "-q", "origin", "main")

    baseline = tmp_path / "baseline"
    _git(tmp_path, "clone", "-q", str(origin), str(baseline))      # 已 fetch：origin/main = c3
    mirror = tmp_path / "mirror"
    _git(tmp_path, "clone", "-q", str(origin), str(mirror))
    # ⚠️ `git clone` **不写** user.name/email，而 macOS 的 git 会拿系统 GECOS 兜底 ⇒ 本机「看起来有
    # identity」、Linux CI 上直接 `fatal: empty ident name`（实测：本 PR 该腿唯一的红就是这个）。
    # ⇒ 夹具**自带** identity，绝不依赖运行环境的全局/系统配置。
    _git(mirror, "config", "user.email", "fixture@example.com")
    _git(mirror, "config", "user.name", "fixture")
    _git(mirror, "checkout", "-q", "--detach", c3)
    return {"origin": origin, "seed": seed, "baseline": baseline, "mirror": mirror,
            "c1": c1, "c2": c2, "c3": c3}


def _anchor_of(env: dict, which: str = "mirror") -> str:
    """活锚路径 = 镜像的**仓根**（S4 / issue #6020；旧口径是 `<镜像>/.agent-presets/migao`）。"""
    return str(env[which])


def _subdir_anchor(env: dict, which: str = "mirror") -> Path:
    """**业务仓**形状的活锚（`<检出>/.agent-presets/migao`）—— 只给 `judge_anchor` 的**默认口径**用例。

    S4 之后业务仓不再有这一层；保留它是为了钉住「`anchor_base` 默认值 = 历史口径」这条兼容性，
    以及用真实存在的目录当**显式 `--anchor`** 的被判对象。
    """
    return env[which] / ".agent-presets/migao"


def _check_env(env: dict) -> dict:
    """给脚本用的环境：镜像 + 活锚都指到夹具（避免读到本机真实活锚）。
    `check` 脚本**总是显式**传 `--anchor`，故「同历史」这条豁免不适用 —— 夹具自洽。"""
    return {
        **os.environ,
        "MIGAO_PRESET_MIRROR": str(env["mirror"]),
        # 基线仓 = 预设仓检出（默认就是镜像）；显式给上，免得依赖本机默认路径。
        "MIGAO_PRESET_BASELINE": str(env["baseline"]),
        # 「镜像是否还在上游远端 main 上」这条判据要 ls-remote ⇒ 指向**夹具的裸仓**（不是真预设仓）。
        "MIGAO_PRESET_REPO_URL": str(env["origin"]),
        "MIGAO_PRESET_LIVE": _anchor_of(env),
    }


def test_anchor_content_behind_is_red(anchor_env: dict):
    """红证（显性形态）：活锚检出停在 v1.28.0、基线已 v1.29.0 ⇒ 必须非零退出并给同步命令。"""
    _git(anchor_env["mirror"], "checkout", "-q", "--detach", anchor_env["c1"])

    proc = _run_guard_anchor(anchor_env["baseline"], "--anchor", _anchor_of(anchor_env))

    assert proc.returncode != 0, proc.stdout
    assert "活锚内容与 origin/main 不一致" in proc.stdout
    assert "活锚=1.28.0 基线=1.29.0" in proc.stdout
    assert "先同步再动手" in proc.stdout
    assert "preset-anchor-refresh.sh" in proc.stdout


def test_anchor_content_equal_but_sha_behind_is_red(anchor_env: dict):
    """红证（**隐蔽形态**，本单病灶本体）：内容与 main **逐字节相同**、只是 sha 落后 1 个提交。

    此刻无害，但「下一次有人改预设，改进就到不了加载点」—— 只比版本号/只比内容的判据**查不出它**，
    所以这条断言是这套判据存在的理由（判据不会红 = 空判据）。
    """
    _git(anchor_env["mirror"], "checkout", "-q", "--detach", anchor_env["c2"])

    proc = _run_guard_anchor(anchor_env["baseline"], "--anchor", _anchor_of(anchor_env))

    assert proc.returncode != 0, proc.stdout
    assert "落后 1 个提交" in proc.stdout
    assert "活锚=1.29.0 基线=1.29.0" in proc.stdout
    assert "先同步再动手" in proc.stdout
    # ⚠️ 刻意**不**断言「内容当前恰好一致」：c3 是「与预设无关的改动」（多一个 `unrelated.txt`），
    # 活锚停在 c2 时逐字节比对当然会报它 missing ⇒ 那句话是**另一格**（`behind` 且内容全同）的读数。
    # 本用例钉的是「sha 落后」这一格，故只钉落后读数与出口（断言写到不存在的那格上才是空/假断言）。


def test_anchor_fresh_is_green(anchor_env: dict):
    """不许误伤：活锚就在基线 tip 上 ⇒ 绿，且必须把「比了什么」说清楚（可自证）。"""
    proc = _run_guard_anchor(anchor_env["baseline"], "--anchor", _anchor_of(anchor_env))

    assert proc.returncode == 0, proc.stdout
    assert "✅ 活锚新鲜" in proc.stdout
    assert "逐字节一致" in proc.stdout
    assert "与基线同一提交" in proc.stdout
    assert "❌" not in proc.stdout


def test_dangling_anchor_is_red(anchor_env: dict, tmp_path: Path):
    """红证：悬空软链（#3956 的静默失效形态）⇒ 红，且必须说清后果与修法。"""
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "does-not-exist")

    proc = _run_guard_anchor(anchor_env["baseline"], "--anchor", str(dangling))

    assert proc.returncode != 0, proc.stdout
    assert "悬空" in proc.stdout
    assert "静默" in proc.stdout
    assert "3956" in proc.stdout


def test_absent_anchor_is_skipped_not_passed(anchor_env: dict, tmp_path: Path):
    """三态：本机没接线（CI / 容器 / 新队友未接线）⇒ `⏭️ 未跑判定`，**不得**说成「通过」。

    红了才是误伤：没有活锚要维持新鲜。但措辞必须让人读得出「这次没判」。
    """
    proc = _run_guard_anchor(anchor_env["baseline"], "--anchor", str(tmp_path / "nope"))

    assert proc.returncode == 0, proc.stdout
    assert "未跑判定" in proc.stdout
    assert "未接线" in proc.stdout
    assert "✅" not in proc.stdout


def test_handcopied_anchor_is_judged_by_content(anchor_env: dict, tmp_path: Path):
    """手抄副本（**不是 git 检出**）：判不了 sha，但内容照样要判 —— 旧的 ⇒ 红；一致 ⇒ 绿 + 形态警告。"""
    stale = tmp_path / "handcopy-old"
    _git(anchor_env["mirror"], "checkout", "-q", "--detach", anchor_env["c1"])
    shutil.copytree(anchor_env["mirror"], stale, ignore=shutil.ignore_patterns(".git"))  # 无 .git

    bad = _run_guard_anchor(anchor_env["baseline"], "--anchor", str(stale))

    assert bad.returncode != 0, bad.stdout
    assert "不是 git 检出" in bad.stdout
    assert "活锚内容与 origin/main 不一致" in bad.stdout

    _git(anchor_env["mirror"], "checkout", "-q", "--detach", anchor_env["c3"])
    fresh = tmp_path / "handcopy-new"
    shutil.copytree(anchor_env["mirror"], fresh, ignore=shutil.ignore_patterns(".git"))

    ok = _run_guard_anchor(anchor_env["baseline"], "--anchor", str(fresh))

    assert ok.returncode == 0, ok.stdout
    assert "不是 git 检出" in ok.stdout        # 形态警告仍在（没有跟随机制）
    assert "✅ 活锚新鲜" in ok.stdout


def test_unrelated_history_is_skipped_but_explicit_anchor_is_judged(anchor_env: dict, tmp_path: Path):
    """同上游豁免（**防假绿也要防假红**）：

    默认活锚只在「与基线同一上游」时才判落后 —— 否则拿无关仓库的 `main` 量活锚会污染所有
    夹具仓库（判据变成环境噪声，迟早被 `|| true` 掉）；而**显式 `--anchor` 一律判定**（你明确要比）。
    ⚠️ 判上游**不能比 `git config --get` 的原始 URL**：本机实测同一仓库有
    `https://github.com/…` 与 `ssh://git@ssh.github.com:443/…` 两种写法（`insteadOf` 重写）
    ⇒ 那样比会把真活锚静默跳过。判据用**生效 URL 归一**（+ 对象级退路），见 `_same_upstream`。
    """
    other = tmp_path / "other"
    _init_repo(other)
    _seed_preset(other, "9.9.9")
    _git(other, "add", "-A")
    _git(other, "commit", "-q", "-m", "别的仓库，另一份历史")

    implicit = io.StringIO()
    rc_implicit = GUARD_MODULE.judge_anchor(
        "origin/main", anchor_env["baseline"], other, anchor_base="",
        explicit=False, out=implicit,
    )

    assert rc_implicit == 0, implicit.getvalue()
    assert "未跑判定" in implicit.getvalue()
    assert "不是同一上游" in implicit.getvalue()
    assert "origin=" in implicit.getvalue()      # 两个 URL 都要打出来（可自证为什么跳过）

    explicit = io.StringIO()
    rc_explicit = GUARD_MODULE.judge_anchor(
        "origin/main", anchor_env["baseline"], other, anchor_base="",
        explicit=True, out=explicit,
    )

    assert rc_explicit == 1, explicit.getvalue()
    assert "活锚内容与 origin/main 不一致" in explicit.getvalue()


def test_default_anchor_is_judged_even_when_mirror_has_not_fetched(anchor_env: dict):
    """回归（本轮实测踩到，属**假绿**）：锚点检出**还没 fetch** 到基线新提交时，若判据要求
    「锚点检出里必须有基线那个提交」，就会判成「不同历史」⇒ **静默跳过** ⇒ 落后不红。

    而这恰恰是本单要治的形态：main 刚前进（预设 PR 合并）、锚点还没跟上 —— 判据必须判、必须红。
    """
    _git(anchor_env["mirror"], "checkout", "-q", "--detach", anchor_env["c1"])
    out = io.StringIO()

    rc = GUARD_MODULE.judge_anchor(
        "origin/main", anchor_env["baseline"], anchor_env["mirror"],
        explicit=False, out=out,
    )

    assert rc == 1, out.getvalue()
    assert "同一上游" in out.getvalue()
    assert "落后" in out.getvalue()
    assert "未跑判定" not in out.getvalue()


def test_unloadable_frontmatter_is_red_even_when_content_matches(anchor_env: dict):
    """红证：**内容与 main 一致**但技能加载不了（第 1 行不是 `---`）⇒ 红。

    这是「文件里写了 ≠ 加载器读到了」的形态（本批刚踩过：新节被插进 frontmatter 注释块内部
    ⇒ `description` 被静默切掉）。夹具刻意让**基线自己**就带坏 frontmatter，使「内容不同」这条
    红因不可能命中 —— 唯一红因只能是**可加载性**（否则这条断言会被别的红因顶替 = 空断言）。
    """
    seed, baseline, mirror = anchor_env["seed"], anchor_env["baseline"], anchor_env["mirror"]
    (seed / SKILL_IN_PRESET).write_text("# 没有 frontmatter\n\n正文\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "c4 frontmatter 坏掉")
    _git(seed, "push", "-q", "origin", "main")
    _git(baseline, "fetch", "-q", "origin", "main")
    _git(mirror, "fetch", "-q", "origin", "main")
    _git(mirror, "checkout", "-q", "--detach", "origin/main")

    proc = _run_guard(baseline, "anchor", "--anchor", _anchor_of(anchor_env))

    assert proc.returncode != 0, proc.stdout
    assert "第 1 行不是" in proc.stdout
    assert "整个技能被加载器忽略" in proc.stdout
    assert "活锚内容与 origin/main 不一致" not in proc.stdout   # 内容其实一致，红因只有一条


def test_plain_scalar_with_inline_hash_warns_but_passes(anchor_env: dict):
    """YAML 纯标量陷阱：`description` 里出现「空白 + `#`」⇒ 静默截断 ⇒ **告警**（不非零退出）。

    截断不致命（技能仍能加载），但「文件里写了、加载器读不到」必须被看见 —— 故这里是 warn 不是 red。
    """
    seed, baseline, mirror = anchor_env["seed"], anchor_env["baseline"], anchor_env["mirror"]
    _write_preset_skill(seed, "1.29.0", filler=2)
    text = (seed / SKILL_IN_PRESET).read_text(encoding="utf-8").replace(
        "description: 夹具技能", "description: 夹具技能 # 这后面会被 YAML 当成注释",
    )
    (seed / SKILL_IN_PRESET).write_text(text, encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "c5 纯标量行内 #")
    _git(seed, "push", "-q", "origin", "main")
    _git(baseline, "fetch", "-q", "origin", "main")
    _git(mirror, "fetch", "-q", "origin", "main")
    _git(mirror, "checkout", "-q", "--detach", "origin/main")

    proc = _run_guard(baseline, "anchor", "--anchor", _anchor_of(anchor_env))

    assert proc.returncode == 0, proc.stdout
    assert "静默截断" in proc.stdout
    assert "活锚新鲜" in proc.stdout


def test_real_presets_frontmatter_is_loadable():
    """守**真资产**：仓库里两个技能的 frontmatter 必须能被加载器读到（0 问题）。

    这条会红在「有人把新节插进 frontmatter 注释块 / 写坏 `description`」上 —— 而那正是本批踩过的形态。
    读那份真资产走**唯一口径** `preset_corpus`（业仓工作树 / 历史候选 / 镜像），不再自带第二份实现。
    """
    skills = _preset_skills()
    for skill in skills:
        assert GUARD_MODULE._frontmatter_problems(skill) == [], f"{skill} 的 frontmatter 有问题"


def test_check_reports_anchor_verdict(anchor_env: dict):
    """接线：`check`（= `dev-worktree.sh preset-guard` 的判定本体）必须**带上活锚判定**并影响退出码。"""
    _git(anchor_env["mirror"], "checkout", "-q", "--detach", anchor_env["c1"])

    bad = _run_guard(anchor_env["baseline"], "check", "--ref", "origin/main",
                     "--source", "worktree", "--anchor", _anchor_of(anchor_env),
                     "--anchor-base=")

    assert bad.returncode != 0, bad.stdout
    assert "活锚新鲜度" in bad.stdout
    assert "活锚内容与 origin/main 不一致" in bad.stdout

    _git(anchor_env["mirror"], "checkout", "-q", "--detach", anchor_env["c3"])

    ok = _run_guard(anchor_env["baseline"], "check", "--ref", "origin/main",
                    "--source", "worktree", "--anchor", _anchor_of(anchor_env),
                    "--anchor-base=")

    assert ok.returncode == 0, ok.stdout
    assert "✅ 活锚新鲜" in ok.stdout


def test_check_default_anchor_never_blocks_unrelated_repos(anchor_env: dict):
    """回归：默认活锚（本机 `~/.dsh/…`）与夹具仓库**不同历史** ⇒ 必须 `⏭️`，不得判红。

    否则本机活锚的状态会污染所有夹具/别的仓库（含既有单测），判据变成环境噪声 ⇒ 迟早被 `|| true` 掉。
    """
    proc = _run_guard(anchor_env["baseline"], "check", "--ref", "origin/main", "--source", "worktree")

    assert proc.returncode == 0, proc.stdout
    assert "活锚新鲜度" in proc.stdout
    assert "⏭️" in proc.stdout


def test_refresh_script_turns_red_green_end_to_end(anchor_env: dict):
    """端到端（真脚本、真仓库、无网络）：落后 ⇒ 自检红 → 跑刷新脚本 → 镜像跟上 → 自检转绿。"""
    _git(anchor_env["mirror"], "checkout", "-q", "--detach", anchor_env["c1"])
    env = _check_env(anchor_env)
    check_cmd = ["bash", str(CHECK_SH), "--anchor", _anchor_of(anchor_env), "--repo", str(anchor_env["baseline"])]

    before = subprocess.run(check_cmd, capture_output=True, text=True, env=env)
    assert before.returncode == 1, before.stdout + before.stderr
    assert "先同步再动手" in before.stdout

    refresh = subprocess.run(
        ["bash", str(REFRESH_SH), "--mirror", str(anchor_env["mirror"]), "--repo", str(anchor_env["baseline"])],
        capture_output=True, text=True, env=env,
    )

    assert refresh.returncode == 0, refresh.stdout + refresh.stderr
    assert "镜像已跟随 origin/main" in refresh.stdout
    assert "活锚自愈完成" in refresh.stdout
    assert _git(anchor_env["mirror"], "rev-parse", "HEAD").stdout.strip() == anchor_env["c3"]

    after = subprocess.run(check_cmd, capture_output=True, text=True, env=env)
    assert after.returncode == 0, after.stdout
    assert "✅ 活锚新鲜" in after.stdout


def test_refresh_refuses_worktree_as_mirror(anchor_env: dict, tmp_path: Path):
    """红证（#3956 教训固化成判据）：镜像**不是独立克隆**（是某仓库的 worktree）⇒ 拒绝刷新。

    worktree 在 `dev-worktree.sh rm` / `git worktree prune` 的清理半径内 —— 当活锚会被删没，
    软链悬空 ⇒ DSH 静默加载不到研发模式。故这里必须**拒**，且拒绝发生在任何写操作之前。
    """
    linked = tmp_path / "linked-wt"
    _git(anchor_env["seed"], "worktree", "add", "-q", "-b", "fix/linked", str(linked))
    head_before = _git(linked, "rev-parse", "HEAD").stdout.strip()

    proc = subprocess.run(
        ["bash", str(REFRESH_SH), "--mirror", str(linked), "--no-check"],
        capture_output=True, text=True, env=_check_env(anchor_env),
    )

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "不是**独立克隆**" in proc.stdout
    assert "3956" in proc.stdout
    assert _git(linked, "rev-parse", "HEAD").stdout.strip() == head_before


def test_refresh_refuses_in_place_edits(anchor_env: dict):
    """红证（fail-closed）：镜像是「只读」的 —— 有**已跟踪文件的本地改动** ⇒ 拒绝刷新，不静默覆盖。

    就地编辑 =「藏在软链目标里的第三份副本」：它直接生效，却没有 PR、没有评审、没有 diff 提醒。
    """
    (anchor_env["mirror"] / PRESET_YML_IN_PRESET).write_text("name: 手改\n", encoding="utf-8")
    head_before = _git(anchor_env["mirror"], "rev-parse", "HEAD").stdout.strip()

    proc = subprocess.run(
        ["bash", str(REFRESH_SH), "--mirror", str(anchor_env["mirror"]), "--no-check"],
        capture_output=True, text=True, env=_check_env(anchor_env),
    )

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "已跟踪文件的本地改动" in proc.stdout
    assert _git(anchor_env["mirror"], "rev-parse", "HEAD").stdout.strip() == head_before


def test_anchor_scripts_are_syntax_clean_and_zero_dep():
    """两个入口脚本必须 `bash -n` 过、且**零第三方依赖**（只用 bash/git/python3 标准库）。"""
    for script in (CHECK_SH, REFRESH_SH):
        assert script.is_file(), f"入口脚本缺失：{script}"
        proc = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert proc.returncode == 0, f"{script} 语法错误：{proc.stderr}"
        assert os.access(script, os.X_OK), f"{script} 不可执行"


def test_dev_worktree_points_at_the_anchor_scripts():
    """接线：`dev-worktree.sh` 必须①指向活锚自检/刷新脚本、②在**与主干同步的时机**顺带刷新镜像。

    ① 保证读者知道「内容单调性」只是防线的一半；② 才是「让活锚会跟随」——
    否则预设 PR 合并后锚点一直落后，改进到不了加载点（`#4026` 的病灶）。
    """
    source = DEV_WORKTREE.read_text(encoding="utf-8")

    assert "preset-anchor-check.sh" in source
    assert "preset-anchor-refresh.sh" in source
    assert "活锚" in source
    assert "refresh_anchor_mirror()" in source, "镜像刷新函数缺失（活锚不会跟随）"
    # 两个「与主干同步」的时机都要调（add 建工作区后 / rebase 到 main 后）
    add_body = source.split("cmd_add()", 1)[1].split("cmd_list()", 1)[0]
    rebase_body = source.split("cmd_rebase()", 1)[1].split("cmd_add()", 1)[0]
    assert "refresh_anchor_mirror" in add_body, "add 后没刷活锚镜像"
    assert "refresh_anchor_mirror" in rebase_body, "rebase 后没刷活锚镜像"


def test_dev_worktree_add_fetches_anchor_mirror_end_to_end(anchor_env: dict, tmp_path: Path):
    """端到端：`add` 必须把活锚镜像**真的 fetch 到最新 origin/main**（不是只打印一句话）。

    红证形状：镜像停在 `c1`、origin/main 已到 `c4` ⇒ `add` 跑完镜像 HEAD 必须是 `c4`
    （只打印不干活 ⇒ 这条会红）。
    """
    seed, mirror = anchor_env["seed"], anchor_env["mirror"]
    # 夹具仓库自带入口脚本（脚本按自身位置解析 ROOT）
    (seed / "scripts").mkdir(exist_ok=True)
    for src in (DEV_WORKTREE, GUARD, CHECK_SH, REFRESH_SH):
        dst = seed / "scripts" / src.name
        dst.write_bytes(src.read_bytes())
        dst.chmod(0o755)
    _git(seed, "branch", "fix/anchor-e2e")
    # origin/main 前进一格（c4，与预设无关），而镜像还停在 c1
    (seed / "later.txt").write_text("主干又前进了一格\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "c4 主干前进")
    c4 = _git(seed, "rev-parse", "HEAD").stdout.strip()
    _git(seed, "push", "-q", "origin", "main")
    _git(mirror, "checkout", "-q", "--detach", anchor_env["c1"])
    assert _git(mirror, "rev-parse", "HEAD").stdout.strip() == anchor_env["c1"]

    env = {
        **os.environ,
        "MIGAO_WT_BASE": str(tmp_path / "wt"),
        "MIGAO_PRESET_MIRROR": str(mirror),
        "MIGAO_PRESET_LIVE": _anchor_of(anchor_env),
    }
    proc = subprocess.run(
        ["bash", str(seed / "scripts" / "dev-worktree.sh"), "add", "fix/anchor-e2e"],
        cwd=seed, capture_output=True, text=True, env=env,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "活锚镜像已刷新" in proc.stdout
    assert _git(mirror, "rev-parse", "HEAD").stdout.strip() == c4, (
        "add 之后镜像没跟上 origin/main —— 活锚不会跟随，改进到不了加载点（#4026）"
    )


# ── ⑥ 与 drift_audit C1 的口径分工（防「第二份口径」）────────────────────────

def test_anchor_judgement_documents_its_division_of_labour_with_drift_audit():
    """`anchor` 段必须写明与 `drift_audit` C1 的**分工**，否则两处判据会互相矛盾。

    分工：C1 是机械对账（内容级，躲「每次主干合并都判红」的噪音红）；`anchor` 是开工/提交路径
    （sha 落后即红 = issue #4026 的要求），噪音由 add/rebase 的顺带刷新压掉。
    """
    guard_src = GUARD.read_text(encoding="utf-8")
    audit_src = (REPO_ROOT / "scripts" / "drift_audit.py").read_text(encoding="utf-8")

    assert "drift_audit" in guard_src, "guard 未点出与 C1 的分工（会有第二份口径）"
    assert "噪音红" in guard_src, "guard 未写明 C1 为什么停在内容级（读者会以为矛盾）"
    assert "preset-anchor-check.sh" in audit_src, "C1 未指向开工/提交路径的 sha 级判据"


# ── ⑦ 「取不到 ref」的三态（issue #5430）──────────────────────────────────────
# 病根（**一类**缺陷，不是一个缺陷）：判据在**取不到证据**时判「通过」。
# `git rev-parse <ref>` 在 ref 不存在时把 `<ref>` **原样回显**到 stdout（并返回非零），而当时那一行是
# `check=False` 且**没看 rc** ⇒ ① 回显被当基线 sha ⇒ 拿**字面量** `"origin/main"` 去活锚检出问
# 「有没有这个提交」（活锚里当然有）⇒ 判「同一上游（同一份历史）」= **伪造读数**；
# ② 活锚里恰好没有该字面量 ref 时反手判「不同源」⇒ `⏭️ 未跑判定` + **exit 0 = 与「通过」同一个码**。
# 本组：红证 A（改前 exit 0）、红证 B（改前打印伪造读数）、反向红证（ref 正常 ⇒ 照常判），
# 以及同族的两处（`_lag_state` 的假「分叉」/ `prune` 把读不到状态当「干净」）。


def _try_git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """**不断言**成败的 git（夹具自证用：判据不许在取不到证据时判通过，夹具也不许）。"""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _noref_repo(tmp_path: Path, name: str = "work") -> Path:
    """**没有 `origin/main`** 的真仓库（无 `origin` 远程、无 `refs/remotes/origin/main`）。

    这正是默认基准 `origin/main` 取不到的场景：浅检出 / 没 fetch / ref 名变了。
    """
    repo = tmp_path / name
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "fixture")
    _seed_preset(repo, "1.28.0")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base（无 origin/main）")
    if _try_git(repo, "rev-parse", "--verify", "-q", "origin/main").returncode == 0:
        raise AssertionError("夹具不成立：该仓库竟能解析 origin/main（本组判据会空跑成假绿）")
    return repo


def _plain_checkout(tmp_path: Path, name: str, bare: Path | None = None) -> Path:
    """活锚形态的检出：给 `bare` ⇒ 克隆（有 `refs/remotes/origin/main`，= 真实镜像形态）；否则本地 init。"""
    repo = tmp_path / name
    if bare is not None:
        _git(tmp_path, "clone", "-q", str(bare), str(repo))
        # ⚠️ `git clone` **不写** user.name/email ⇒ 在镜像里提交会撞「Author identity unknown」
        # （本机有全局 identity ⇒ 本地绿、CI 红：实测 CI 该腿唯一的红就是这里）。
        _git(repo, "config", "user.email", "fixture@example.com")
        _git(repo, "config", "user.name", "fixture")
        return repo
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "fixture")
    _seed_preset(repo, "1.28.0")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "anchor v1.28.0")
    return repo


def test_unresolvable_ref_is_undecidable_not_pass(tmp_path: Path):
    """**红证 A**（改前 **exit 0 = 通过**）：基线 `origin/main` 取不到 + 活锚检出里也没有该字面量 ref。

    改前：退路拿回显 `"origin/main"` 去活锚里问「有没有这个提交」⇒ 没有 ⇒ 判「不是同一上游」
    ⇒ `⏭️ 未跑判定` + **exit 0**（与「通过」同一个码）⇒ 判据在最需要它的场景下**静默失效**。
    改后：入口判 **`3` 无法判定**、说明「这次根本没判」、给出可行动出口（`git fetch` / `--ref`）。
    """
    work = _noref_repo(tmp_path)
    anchor = _plain_checkout(tmp_path, "anchor-no-ref")
    out = io.StringIO()

    rc = GUARD_MODULE.judge_anchor("origin/main", work, anchor, anchor_base="",
                                   explicit=False, out=out)
    text = out.getvalue()

    assert rc == 3, text                          # 改前为 0（= 通过）
    assert "无法判定" in text and "不可解析" in text
    assert "git fetch origin" in text             # 出口必须可行动
    assert "不是同一上游" not in text             # 旧版正是在这里下了**没有证据的结论**
    assert "✅" not in text                       # 不许长得像「绿」


def test_unresolvable_ref_never_fabricates_same_upstream(tmp_path: Path):
    """**红证 B**（改前打印**伪造读数**）：活锚检出里**有** `refs/remotes/origin/main`（真实镜像形态）。

    改前：回显 `"origin/main"` 被当基线 sha ⇒ 拿字面量去活锚问「有没有这个提交」⇒ 有 ⇒
    判「同一上游（**同一份历史**）」并把基线读数打成 `origin/main @?`；随后又用**同一个字面量**
    去取文件清单而红 ⇒ **判红的原因本身是伪造的读数**（把人引向「落后 / 分叉」而不是「前提缺失」）。
    """
    work = _noref_repo(tmp_path)
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = _plain_checkout(tmp_path, "seed")
    _git(seed, "remote", "add", "origin", str(bare))
    _git(seed, "push", "-q", "origin", "main")
    mirror = _plain_checkout(tmp_path, "mirror", bare=bare)
    if _try_git(mirror, "rev-parse", "--verify", "-q", "origin/main").returncode != 0:
        raise AssertionError("夹具不成立：活锚检出里没有 `origin/main`（本判据会退化成另一条红因）")

    out = io.StringIO()
    rc = GUARD_MODULE.judge_anchor("origin/main", work, mirror, anchor_base="",
                                   explicit=False, out=out)
    text = out.getvalue()

    assert rc == 3, text
    assert "拥有基线提交" not in text             # 改前逐字：活锚检出拥有基线提交 origin/main（同一份历史）
    assert "同一份历史" not in text
    assert "无法判定" in text


def test_resolvable_ref_still_judges_both_same_upstream_legs(anchor_env: dict, tmp_path: Path):
    """**反向红证**（别把判据改成「永远无法判定」）：`origin/main` 正常可解析时，同源判定的**两条腿**照常判。

    ① **生效 origin URL 腿**：活锚镜像与本仓库同一上游 ⇒ 判定（内容不一致 ⇒ 红，且**不是**「未跑判定」）；
    ② **对象级退路腿**：镜像的 origin URL 被改成别的路径（URL 腿失效），但**基线提交在它的历史里**
       ⇒ 仍判「同一上游（同一份历史）」并照常判内容。
    """
    baseline, mirror, c1 = anchor_env["baseline"], anchor_env["mirror"], anchor_env["c1"]
    _git(mirror, "checkout", "-q", "--detach", c1)

    url_out = io.StringIO()
    rc_url = GUARD_MODULE.judge_anchor("origin/main", baseline, mirror, anchor_base="",
                                       explicit=False, out=url_out)
    assert rc_url == 1, url_out.getvalue()
    assert "同一上游" in url_out.getvalue()
    assert "未跑判定" not in url_out.getvalue()
    assert "活锚内容与 origin/main 不一致" in url_out.getvalue()

    alias = tmp_path / "alias"
    _git(tmp_path, "clone", "-q", str(anchor_env["origin"]), str(alias))
    _git(alias, "remote", "set-url", "origin", str(tmp_path / "not-origin.git"))
    _git(alias, "checkout", "-q", "--detach", c1)

    obj_out = io.StringIO()
    rc_obj = GUARD_MODULE.judge_anchor("origin/main", baseline, alias, anchor_base="",
                                       explicit=False, out=obj_out)
    assert rc_obj == 1, obj_out.getvalue()
    assert "同一份历史" in obj_out.getvalue()      # 对象级退路腿
    assert "未跑判定" not in obj_out.getvalue()


def test_cli_reports_exit_code_3_when_only_undecidable(tmp_path: Path):
    """接线：只有「无法判定」时 `check` 必须退 **3**（改前：拿回显当 sha ⇒ `ls-tree` 失败 ⇒ 假红 1）。"""
    work = _noref_repo(tmp_path)
    anchor = _plain_checkout(tmp_path, "anchor-cli3")

    proc = _run_guard(work, "check", "--source", "index", "--ref", "origin/main",
                      "--anchor", str(anchor))

    assert proc.returncode == 3, proc.stdout
    assert "无法判定" in proc.stdout and "不得当 0 读" in proc.stdout
    assert "ls-tree" not in proc.stdout            # 旧版那条「拿回显去取文件清单」的假红因不得再出现


def test_red_wins_over_undecidable(tmp_path: Path):
    """三态合并：**有结论的红（1）优先于无法判定（3）** —— 一次运行里既有真红又有不可判时先修真红
    （与 `scripts/drift_audit.py::tri_state()` 同序）；且**两段确实都判了**（不是「没跑」）。
    """
    work = _noref_repo(tmp_path)
    anchor = _plain_checkout(tmp_path, "anchor-cli1")
    _write_business_skill(work, "1.26.0", filler=9)        # 降级（HEAD 上是 1.28.0）
    _git(work, "add", "-A")

    proc = _run_guard(work, "check", "--source", "index", "--ref", "origin/main",
                      "--anchor", str(anchor))

    assert proc.returncode == 1, proc.stdout                  # 1 优先于 3
    assert "不可判定（fail-closed）" in proc.stdout            # 单调性段的红因
    assert "无法判定（三态" in proc.stdout                     # 活锚段确实也判了 3（不是没跑）


def test_cross_repo_anchor_readout_names_the_real_reason(anchor_env: dict):
    """读数诚实性（#5430 同族：读数指向**错误对象**会把排查带偏 —— 本次实测踩到）：

    活锚**是** git 检出、只是它的 HEAD 提交**不在基准仓对象库**里（实测：活锚镜像比本工作区新）
    ⇒ 读数必须这么说；旧版一律打印「活锚不是 git 检出」（= 另一种 `unknown` 的原因）⇒ 读了会去查错东西。
    """
    mirror = anchor_env["mirror"]
    _git(mirror, "checkout", "-q", "--detach", anchor_env["c3"])
    (mirror / "local-only.txt").write_text("镜像上的本地提交\n", encoding="utf-8")
    _git(mirror, "add", "-A")
    _git(mirror, "commit", "-q", "-m", "镜像本地提交（不在基准仓对象库里）")
    sha = _git(mirror, "rev-parse", "HEAD").stdout.strip()
    if _try_git(anchor_env["baseline"], "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0:
        raise AssertionError("夹具不成立：该提交竟在基准仓对象库里（本判据会退化成另一格）")

    out = io.StringIO()
    rc = GUARD_MODULE.judge_anchor("origin/main", anchor_env["baseline"], mirror, anchor_base="",
                                   explicit=False, out=out)
    text = out.getvalue()

    assert rc == 0, text                          # 内容一致 ⇒ 绿（这一格本来就绿，改的只是读数）
    assert "不在基准仓对象库" in text
    assert "活锚不是 git 检出" not in text


def test_lag_state_is_unknown_when_ref_unresolvable(tmp_path: Path):
    """**红证**（同族，同一文件）：`_lag_state` 在 ref 取不到时必须是 `unknown`（**关系未判**），
    而不是有结论的 `divergent` —— 旧版：回显被当 sha ⇒ `merge-base` 随之失败 ⇒ 误判「分叉」。
    """
    work = _noref_repo(tmp_path)
    sha = _git(work, "rev-parse", "HEAD").stdout.strip()

    assert GUARD_MODULE._lag_state("origin/main", work, sha) == "unknown"    # 改前为 "divergent"


def test_locked_branches_is_undecidable_without_common_dir(tmp_path: Path):
    """**红证**（同族，同一文件）：`_locked_branches` 取不到 common git dir ⇒ **`None` = 无法判定**。

    改前：`rev-parse --git-common-dir` 失败 ⇒ stdout 空 ⇒ `or (cwd / ".git")` 兜底 ⇒ 返回**空集**
    ⇒ 被读成「无活跃会话锁」⇒ `prune` 会把**有会话在用**的工作区列进「可安全移除」。
    """
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    if _try_git(outside, "rev-parse", "--git-common-dir").returncode == 0:
        raise AssertionError("夹具不成立：该目录竟是 git 仓库（判据会空跑成假绿）")

    assert GUARD_MODULE._locked_branches(outside) is None, "取不到 common git dir 必须判「无法判定」"

    repo = tmp_path / "repo-ok"
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    assert GUARD_MODULE._locked_branches(repo) == set(), "正对照：确实没有锁时仍是空集（不是 None）"


def test_prune_does_not_read_unreadable_status_as_clean(tmp_path: Path):
    """**红证**（同族，同一文件）：读不到工作树状态（`git status` 失败）**不得**被读成「干净」。

    改前：stdout 空 ⇒ 「工作树干净」⇒ 该 worktree 落进**可安全移除**（取不到证据却判「安全」）。
    夹具：一个已注册、分支已合入的 worktree，把它的 `.git` 指针文件改坏（目录还在，git 读不了状态）。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "fixture")
    (repo / "f.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    wt = tmp_path / "wt-broken"
    _git(repo, "worktree", "add", "-q", "-b", "fix/broken", str(wt))
    (wt / ".git").write_text("这不是一个 gitdir 指针\n", encoding="utf-8")
    if _try_git(wt, "status", "--porcelain").returncode == 0:
        raise AssertionError("夹具不成立：工作树状态仍可读（判据会空跑成假绿）")

    proc = _run_guard(repo, "prune", "--dry-run", "--ref", "main")

    assert proc.returncode == 0, proc.stdout
    safe_block, manual_block = proc.stdout.split("── 需人看")[0], proc.stdout.split("── 需人看")[1]
    assert str(wt) not in safe_block, "读不到工作树状态却被判『可安全移除』（无证据的『安全』）"
    assert str(wt) in manual_block
    assert "读不到工作树状态" in manual_block


# ── ⑧ 换链后的**拓扑 A/B/C**（S4 / issue #6020；本批新增）────────────────────────
# 背景（实测 2026-10-02 21:4x，S3 换链之后）：默认口径曾经是**假绿** —— 脚本/守卫把基线仓默认成
# **业务仓**，而业务仓 `origin/main` 已无 `.agent-presets/**` ⇒ 比对集合是**空集** ⇒ 逐字节比对
# **恒等** ⇒ 打印「✅ 活锚新鲜：内容与 origin/main 逐字节一致（0 个文件）」+ exit 0 ——
# 「**没跑判定**」长得和「**跑了且绿**」一模一样（与「空跑 = 假绿」的口径直接冲突）。
#
# 现口径（判定本体 `judge_anchor`，**按拓扑自动选**；本组逐格钉住）：
#   · **拓扑 A**（活锚 = 预设仓检出的**仓根**，换链后的当前形态）：
#     ① 形态（`preset.yml` + `skills/` 缺一即红）② 工作树**干净**（读不到状态 ⇒ `3`）
#     ③ HEAD 就在**活锚自己的** `origin/main` 上（取不到 ⇒ `3`；不同 ⇒ 红）+ 打印两个技能 version；
#   · **拓扑 B**（活锚仍是基线仓里的 preset 子树，兼容窗口）：历史口径（内容逐字节比对）；
#   · **拓扑 C**（拓扑 B 形态 + 基线仓该前缀**空集**）：`⏭️ 未跑判定` + **`3`**。
# 夹具一律是真 git 仓库 / 真脚本（不 mock git —— mock 掉 git 等于把被测对象换成替身，红证会变假绿）。


def _business_repo(tmp_path: Path, name: str, version: str = "1.29.0") -> Path:
    """建一个**业务仓形状**的检出（仓内有 `.agent-presets/migao/**`）并返回**仓根**。

    `repo / ".agent-presets/migao"` 即**拓扑 B 形态的活锚**（S4 之前的真实活锚形状）；
    `anchor_env` 的 mirror 是**预设仓形状**（仓根就是 preset 目录），两者刻意不同。
    """
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "fixture")
    _write_business_skill(repo, version, filler=2)
    (repo / ".agent-presets/migao/preset.yml").write_text("name: migao\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"业务仓形状活锚 v{version}")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def _unrelated_baseline(tmp_path: Path, version: str = "1.29.0") -> Path:
    """一个**与活锚无共同历史**的基线仓（内容与活锚逐字节相同）—— 复现「假绿」那一格。"""
    repo = tmp_path / "unrelated-baseline"
    _init_repo(repo)
    _seed_preset(repo, version, filler=2)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"无关基线 v{version}（内容同、历史不同）")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def test_topology_a_gives_a_real_verdict_and_prints_both_skill_versions(anchor_env: dict):
    """拓扑 A（= 当前换链形态）：默认调用必须给出**真判定**，并打印**两个**技能 version 供人眼核对。

    红证形态（改前）：拿**业务仓**当基线 ⇒ 比对集合空集 ⇒ 「✅ 新鲜（0 个文件）」+ exit 0。
    本用例往真夹具里放**第二个技能**（`skills/migao-acceptance`），钉住「两个 version 都打印」。
    """
    seed, baseline, mirror = anchor_env["seed"], anchor_env["baseline"], anchor_env["mirror"]
    (seed / "skills/migao-acceptance").mkdir(parents=True, exist_ok=True)
    (seed / "skills/migao-acceptance/SKILL.md").write_text(
        SKILL_TMPL.format(version="1.14.0", filler=3).replace("migao-dev-flow", "migao-acceptance"),
        encoding="utf-8",
    )
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "c3b 第二个技能")
    _git(seed, "push", "-q", "origin", "main")
    _git(baseline, "fetch", "-q", "origin", "main")
    _git(mirror, "fetch", "-q", "origin", "main")
    _git(mirror, "checkout", "-q", "--detach", "origin/main")

    proc = subprocess.run(
        ["bash", str(CHECK_SH), "--anchor", _anchor_of(anchor_env), "--repo", str(baseline)],
        capture_output=True, text=True, env=_check_env(anchor_env),
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "✅ 活锚新鲜" in proc.stdout
    assert "migao-acceptance" in proc.stdout and "活锚=1.14.0" in proc.stdout
    assert "migao-dev-flow" in proc.stdout and "活锚=1.29.0" in proc.stdout
    # 存活读数：**跑了**必须看得见（否则与「没跑判定」无法区分）
    assert "拓扑 A 判据" in proc.stdout
    assert "工作树干净" in proc.stdout


def test_topology_a_dirty_worktree_is_red(anchor_env: dict):
    """**注入式红证**（拓扑 A ②）：把活锚工作树弄脏（未跟踪文件）⇒ 必须非零。

    刻意用**未跟踪**文件：它只让「多余文件」告警（⚠️，不非零）⇒ 这条红**只可能**来自新增的
    「工作树干净」判据（否则断言会被别的红因顶替 = 空断言）。
    """
    mirror = anchor_env["mirror"]
    _git(mirror, "checkout", "-q", "--detach", anchor_env["c3"])
    (mirror / "local-note.txt").write_text("就地编辑的残留\n", encoding="utf-8")

    proc = _run_guard_anchor(anchor_env["baseline"], "--anchor", _anchor_of(anchor_env))

    assert proc.returncode == 1, proc.stdout
    assert "工作树**不干净**" in proc.stdout
    assert "local-note.txt" in proc.stdout
    assert "活锚必须**只读**" in proc.stdout


def test_topology_a_head_behind_its_own_remote_main_is_red(anchor_env: dict, tmp_path: Path):
    """**注入式红证**（拓扑 A ③）：活锚 HEAD 不在**它自己的** `origin/main` 上 ⇒ 必须非零。

    注入方式刻意让**内容逐字节不变**（上游加一个**空提交**）⇒ 「内容比对」那一路必然全绿；
    基线仓刻意选**无关仓库**（无共同历史 ⇒ 旧口径 `state=unknown`）⇒ 唯一可能判红的只有新增的 ③。
    改前这一格就是**假绿**（✅ + 0 个文件 + exit 0）。
    """
    seed, mirror = anchor_env["seed"], anchor_env["mirror"]
    _git(mirror, "checkout", "-q", "--detach", anchor_env["c3"])
    _git(seed, "commit", "-q", "--allow-empty", "-m", "空提交（树相同，只有 sha 前进）")
    _git(seed, "push", "-q", "origin", "main")
    _git(mirror, "fetch", "-q", "origin", "main")
    if _git(mirror, "rev-parse", "HEAD").stdout.strip() == \
            _git(mirror, "rev-parse", "origin/main").stdout.strip():
        raise AssertionError("夹具不成立：活锚 HEAD 竟等于其 origin/main（判据会空跑成假绿）")

    unrelated = _unrelated_baseline(tmp_path)
    if _try_git(unrelated, "cat-file", "-e",
                f"{_git(mirror, 'rev-parse', 'HEAD').stdout.strip()}^{{commit}}").returncode == 0:
        raise AssertionError("夹具不成立：无关基线里竟有活锚的提交（红因会被旧判据顶替）")

    out = io.StringIO()
    rc = GUARD_MODULE.judge_anchor("origin/main", unrelated, mirror, anchor_base="",
                                   expected_remote="", explicit=True, out=out)
    text = out.getvalue()

    assert rc == 1, text
    assert "不在其远端 main 上" in text
    assert "落后 1 个提交" in text
    assert "✅" not in text


def test_topology_a_remote_main_unreachable_is_undecidable_not_green(anchor_env: dict, tmp_path: Path):
    """**注入式红证**（拓扑 A ③ 的三态格）：取不到**活锚自己的远端 main** ⇒ `3`，不许报绿。

    夹具：活锚是**真检出**、内容与基线逐字节一致，只是**没有 `origin`**（离线 / 没接远端）——
    「第二视角缺失」时旧口径照样能打印 ✅。`--fetch` 变体一并钉住（fetch 失败同样 `3`）。
    """
    detached = tmp_path / "anchor-no-origin"
    _git(tmp_path, "clone", "-q", str(anchor_env["origin"]), str(detached))
    _git(detached, "checkout", "-q", "--detach", anchor_env["c3"])
    _git(detached, "remote", "remove", "origin")
    if _try_git(detached, "rev-parse", "--verify", "-q", "origin/main").returncode == 0:
        raise AssertionError("夹具不成立：移除 origin 后仍能解析 origin/main（判据会空跑）")

    plain = _run_guard(anchor_env["baseline"], "anchor", "--anchor", str(detached), "--anchor-base=")
    assert plain.returncode == 3, plain.stdout
    assert "无法判定" in plain.stdout
    assert "取不到" in plain.stdout
    assert "✅" not in plain.stdout

    fetched = _run_guard(anchor_env["baseline"], "anchor", "--anchor", str(detached),
                         "--anchor-base=", "--fetch")
    assert fetched.returncode == 3, fetched.stdout
    assert "fetch origin main` 失败" in fetched.stdout
    assert "✅" not in fetched.stdout

    # 正对照（别把判据改成「永远无法判定」）：同一形状、**接了 origin** ⇒ 照常判绿
    ok = _run_guard_anchor(anchor_env["baseline"], "--anchor", _anchor_of(anchor_env))
    assert ok.returncode == 0, ok.stdout
    assert "✅ 活锚新鲜" in ok.stdout


def test_topology_a_missing_skills_is_red(anchor_env: dict, tmp_path: Path):
    """**注入式红证**（拓扑 A ①）：活锚是仓根检出、但**没有 `skills/`** ⇒ 加载面是空的 ⇒ 非零。"""
    broken = tmp_path / "anchor-no-skills"
    _git(tmp_path, "clone", "-q", str(anchor_env["origin"]), str(broken))
    _git(broken, "checkout", "-q", "--detach", anchor_env["c3"])
    shutil.rmtree(broken / "skills")
    if (broken / "skills").exists():
        raise AssertionError("夹具不成立：skills/ 还在（判据会空跑）")

    proc = _run_guard(anchor_env["baseline"], "anchor", "--anchor", str(broken), "--anchor-base=")

    assert proc.returncode == 1, proc.stdout
    assert "活锚形态不对" in proc.stdout
    assert "skills" in proc.stdout
    assert "模式不见了" in proc.stdout


def test_topology_b_subdir_anchor_keeps_the_byte_compare(tmp_path: Path):
    """**拓扑 B**（兼容窗口）：活锚仍指业务仓内的 `.agent-presets/migao` ⇒ 历史口径照常（内容逐字节）。

    S4 之前这就是真实活锚形态（软链 → `<镜像>/.agent-presets/migao`）；换链后只应作为兼容窗口存在。
    """
    repo = tmp_path / "biz-with-presets"
    _init_repo(repo)
    _write_business_skill(repo, "1.29.0", filler=2)
    (repo / ".agent-presets/migao/preset.yml").write_text("name: migao\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "业务仓 + 预设子树 v1.29.0")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    anchor = repo / ".agent-presets/migao"

    ok = _run_guard(repo, "anchor", "--anchor", str(anchor))

    assert ok.returncode == 0, ok.stdout
    assert "✅ 活锚新鲜" in ok.stdout
    assert "逐字节一致（2 个文件）" in ok.stdout


def test_topology_c_empty_baseline_prefix_is_undecided_not_green(tmp_path: Path):
    """**本批的核心判据：空集不许报绿**（拓扑 C），并配**双向对照**。

    形态 = 基线仓 `origin/main` 里该前缀**空集**（S4 之后业务仓的真实形态）+ 活锚**不是**预设仓检出。
    改前：`0 个文件` 比 `0 个文件` **恒等** ⇒ 「✅ 活锚新鲜：…逐字节一致（0 个文件）」+ exit 0（假绿）。
    改后：`⏭️ 未跑判定` + **`3`**，并明说「这条比对本就不适用」。
    """
    empty_baseline = tmp_path / "biz-post-s4"
    _init_repo(empty_baseline)
    (empty_baseline / "README.md").write_text("业务仓：已无 .agent-presets/**\n", encoding="utf-8")
    _git(empty_baseline, "add", "-A")
    _git(empty_baseline, "commit", "-q", "-m", "S4 后：业务仓不再承载预设")
    _git(empty_baseline, "update-ref", "refs/remotes/origin/main", "HEAD")
    anchor_repo = _business_repo(tmp_path, "anchor-b")
    anchor = anchor_repo / ".agent-presets/migao"

    proc = _run_guard(empty_baseline, "anchor", "--anchor", str(anchor))

    assert proc.returncode == 3, proc.stdout
    assert "未跑判定" in proc.stdout
    assert "本就不适用" in proc.stdout
    assert "假绿" in proc.stdout
    assert "✅" not in proc.stdout
    assert "0 个文件" not in proc.stdout, "空集不得被说成「逐字节一致（0 个文件）」"

    # 双向对照：**同一份活锚** + **非空**基线（业务仓形状，内容一致）⇒ 照常判绿
    green = _run_guard(_business_repo(tmp_path, "anchor-b2"), "anchor", "--anchor", str(anchor))
    assert green.returncode == 0, green.stdout
    assert "✅ 活锚新鲜" in green.stdout


@pytest.mark.parametrize("form", ["subdir-of-checkout", "handcopied"])
def test_empty_comparison_set_never_claims_freshness(tmp_path: Path, form: str):
    """**类级判据**（本包核心）：**任何**拓扑下，「比对的集合是空集」都不许被说成「比过且一致」。

    两种活锚形态各钉一遍（都是拓扑 B 形态 ⇒ 落进拓扑 C 分支）：
      · `subdir-of-checkout`：活锚 = 某检出的 `.agent-presets/migao` 子树（S4 前的业务仓形态）；
      · `handcopied`：手抄副本（无 `.git`，判不了 sha，但内容照样能比）。
    判据：`rc` = `3` + 输出里**没有** `✅`、**没有**「0 个文件」/「逐字节一致」。

    为什么是**类级**：不针对某个调用点，而是钉「**空集 ⇒ 不得声明新鲜**」这个**形状** ——
    将来任何人把基线换成空集（换链、迁仓、ref 改名）都会撞上它，而不是撞上假绿。
    """
    empty_baseline = tmp_path / f"empty-{form}"
    _init_repo(empty_baseline)
    (empty_baseline / "README.md").write_text("无预设前缀\n", encoding="utf-8")
    _git(empty_baseline, "add", "-A")
    _git(empty_baseline, "commit", "-q", "-m", "空前缀基线")
    _git(empty_baseline, "update-ref", "refs/remotes/origin/main", "HEAD")

    src = _business_repo(tmp_path, f"anchor-{form}") / ".agent-presets/migao"
    if form == "handcopied":
        anchor = tmp_path / "handcopied-anchor"
        shutil.copytree(src, anchor)          # 无 .git 的纯目录（拓扑 B 形态）
    else:
        anchor = src
    if _try_git(anchor, "rev-parse", "--show-toplevel").returncode != 0 and form != "handcopied":
        raise AssertionError("夹具不成立：subdir 形态的活锚不是检出内的子树")

    proc = _run_guard(empty_baseline, "anchor", "--anchor", str(anchor))

    assert proc.returncode == 3, proc.stdout
    assert "未跑判定" in proc.stdout
    assert "✅" not in proc.stdout
    assert "0 个文件" not in proc.stdout
    assert "逐字节一致" not in proc.stdout


def test_topology_a_empty_comparison_is_fail_closed_not_green(anchor_env: dict, tmp_path: Path):
    """**本单核心判据（issue #6178 实例面）**：拓扑 A 下**比对面解析出 0 个文件** ⇒ **fail-closed**。

    形态 = 活锚是**预设仓检出**（拓扑 A）+ 基线仓 `origin/main` 在 `<仓根>` 下**空集**（旧调用点
    `--repo <业务仓>`，业务仓已不再承载 `.agent-presets/**`）。

    改前实测（本单复现命令，读数逐字）：

        bash scripts/preset-anchor-check.sh --repo <0 文件的基线仓>
        ⇒ ✅ 活锚新鲜（拓扑 A：仓根检出）：内容比对**不适用**（…是空集 ⇒ 没有可比的字节）；
          本轮判定落在活锚自身远端：HEAD … == origin/main …，工作树干净、形态完整
        ⇒ rc=0

    —— 「0 个文件的比对面」证不了任何字节（空集比空集**恒等**），却与「真比过且一致」**同一个码**。
    改后：明说「判不了」+ 处置指引 + **非零（`3`）**，且**绝不**打印 `✅`。

    ⚠️ 「对象库不同刻」是**预期**情况、**不判失败**（本夹具里活锚 HEAD 多半不在基线仓对象库里 ⇒
    sha 关系 `unknown`）—— 但它同样**不是**「一致」的依据。
    """
    empty_baseline = tmp_path / "biz-post-s4-a"
    _init_repo(empty_baseline)
    _git(empty_baseline, "commit", "-q", "--allow-empty", "-m", "S4 后：业务仓不再承载预设（树是空的）")
    _git(empty_baseline, "update-ref", "refs/remotes/origin/main", "HEAD")
    if _git(empty_baseline, "ls-tree", "-r", "--name-only", "origin/main").stdout.strip():
        raise AssertionError("夹具不成立：基线仓 root 下竟有文件（比对面非空 ⇒ 判据会空跑）")

    out = io.StringIO()
    rc = GUARD_MODULE.judge_anchor("origin/main", empty_baseline, Path(_anchor_of(anchor_env)),
                                   anchor_base="", expected_remote="", explicit=True, out=out)
    text = out.getvalue()

    assert rc == 3, f"空比对面必须 fail-closed（3），实测 rc={rc}：\n{text}"
    assert "比对面解析出 0 个文件" in text
    assert "无法判定" in text
    assert "✅" not in text, "空比对不许报绿"
    assert "0 个文件" not in text.replace("比对面解析出 0 个文件", ""), \
        "不许把空集说成「一致（0 个文件）」"
    assert "preset-anchor-check.sh" in text, "判不了必须给可行动处置指引"


def test_topology_a_real_byte_compare_reports_a_nonzero_file_count(anchor_env: dict):
    """**正常拓扑 ⇒ 真比对通过**（判据必须能绿，且**真的比了文件**）：读数里文件数 **> 0**。

    这是上一条的**正向对照**：拿掉它，就分不清「改成永远 fail-closed」与「只有空集才 fail-closed」。
    断言钉住读数本身（`逐字节一致（N 个文件）` 的 N 由 `len(expected)` 现取，不钉手抄清单）——
    改前改后都必须是「**比过**」，而不是「因为没得比所以没红」。
    """
    proc = subprocess.run(
        ["bash", str(CHECK_SH), "--anchor", _anchor_of(anchor_env), "--repo", str(anchor_env["baseline"])],
        capture_output=True, text=True, env=_check_env(anchor_env),
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    match = re.search(r"逐字节一致（(\d+) 个文件）", proc.stdout)
    if match is None:
        raise AssertionError(f"读数里没有文件数 ⇒ 判据可能没真比文件：\n{proc.stdout}")
    assert int(match.group(1)) > 0, f"比对面是空集却报了绿（本单病灶）：\n{proc.stdout}"
    assert "内容比对**不适用**" not in proc.stdout


def test_refresh_selfcheck_uses_the_preset_repo_even_when_repo_flag_is_a_business_repo(
        anchor_env: dict, tmp_path: Path):
    """**端到端红证（issue #6178 的刷新路径）**：`preset-anchor-refresh.sh --repo <业务仓>` 下，
    自检的对照**仍必须是预设仓**（镜像自身）⇒ 刷新照常成功，且**真的比了文件**。

    改前实测（读数逐字）—— 同一夹具、同一调用形态，把对照交给业务仓 ⇒ **空比对 + 假绿**：

        ℹ️ 自检对照按拓扑选 …（改后新增的这一行不在改前输出里）
        ✅ 活锚新鲜（拓扑 A：仓根检出）：内容比对**不适用**（…`<仓根>` 下是空集 …）；…
        ✅ 活锚自愈完成：镜像已跟随 origin/main，且自检绿。          ← 空比对却报「自检绿」

    本用例还钉住「`--repo` 的忽略要**出声**」：不静默改写人给的参数。
    """
    seed, mirror = anchor_env["seed"], anchor_env["mirror"]
    (seed / "after-refresh.txt").write_text("与预设无关的改动\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "与预设无关的改动（只为让刷新有事可做）")
    _git(seed, "push", "-q", "origin", "main")
    _git(mirror, "checkout", "-q", "--detach", anchor_env["c1"])

    business = _business_repo(tmp_path, "biz-for-refresh")
    out = io.StringIO()
    rc = GUARD_MODULE.judge_anchor("origin/main", business, Path(_anchor_of(anchor_env)),
                                   anchor_base="", expected_remote="", explicit=True, out=out)
    if rc == 0 and "逐字节一致（0 个文件）" in out.getvalue():
        raise AssertionError("夹具不成立：拿业务仓当对照竟然「一致（0 个文件）」⇒ 本判据测不到那一格")

    proc = subprocess.run(
        ["bash", str(REFRESH_SH), "--mirror", str(mirror), "--repo", str(business)],
        capture_output=True, text=True, env=_check_env(anchor_env),
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "自检对照按拓扑选" in proc.stdout, "忽略 `--repo` 必须**出声**，不许静默改写人的参数"
    assert "活锚自愈完成" in proc.stdout
    match = re.search(r"逐字节一致（(\d+) 个文件）", proc.stdout)
    if match is None:
        raise AssertionError(f"刷新路径上没有真比对文件 ⇒ 可能又走了空比对：\n{proc.stdout}")
    assert int(match.group(1)) > 0, f"刷新路径拿空集报了绿（本单病灶）：\n{proc.stdout}"
    assert "内容比对**不适用**" not in proc.stdout


def test_fixture_baselines_are_decoupled_from_the_machine_live_anchor(anchor_env: dict, tmp_path: Path):
    """**夹具场景必须与本机活锚解耦**（本机专属 5 红的机制，实测 2026-10-02）。

    机制：这些用例拿 **pytest 临时夹具仓**当基线，且**没有钉住活锚** ⇒ guard 回落到本机活锚
    `~/.dsh/.agent-presets/migao`。S3 换链**前**活锚 = 业务仓 clone ⇒ 与夹具「有证据地不同源」⇒
    `⏭️ 未跑判定`（rc=0）。换链**后**活锚 = 预设仓检出，而 `#6034` 把「同上游」的参照物默认成
    **预设仓 URL 常量** ⇒ 与**任何**夹具仓都判「同一上游 ⇒ 要判」⇒ 拿夹具基线量真活锚 ⇒ 必然不一致 ⇒
    5 条既有判据**在本机误红**（CI 上因无活锚而看不到）。

    🔴 本用例把**真机形态**建出来（A 形态检出 + `origin` = 预设仓 URL），并钉死两件事：
      ① **隐式**活锚（调用方没指定要比谁）⇒ 必须 `⏭️ 未跑判定` + `0`，且**没有**拿夹具基线去量它；
      ② **判别力自证**：把旧口径（常量回落）显式喂给 `_same_upstream` ⇒ 同一个活锚**立刻**变「同一上游」
         ⇒ 说明本条判据真能测到那一格（改回旧口径 ⇒ ① 必红）。
    """
    live = tmp_path / "live-anchor"
    _git(tmp_path, "clone", "-q", str(anchor_env["origin"]), str(live))
    _git(live, "remote", "set-url", "origin", GUARD_MODULE.PRESET_REPO_URL)   # = 真机活锚的上游
    _git(live, "checkout", "-q", "--detach", anchor_env["c3"])

    fixture = tmp_path / "fixture-repo"
    _init_repo(fixture)
    _seed_preset(fixture, "1.28.0", filler=4)
    _git(fixture, "add", "-A")
    _git(fixture, "commit", "-q", "-m", "夹具基线（与活锚无共同历史）")
    _git(fixture, "update-ref", "refs/remotes/origin/main", "HEAD")
    if _try_git(fixture, "cat-file", "-e",
                f"{_git(live, 'rev-parse', 'HEAD').stdout.strip()}^{{commit}}").returncode == 0:
        raise AssertionError("夹具不成立：夹具仓里竟有活锚的提交（判据会空跑）")

    out = io.StringIO()
    rc = GUARD_MODULE.judge_anchor("origin/main", fixture, live, explicit=False, out=out)
    text = out.getvalue()

    assert rc == 0, text
    assert "未跑判定" in text
    assert "不是同一上游" in text
    assert "活锚内容与" not in text, "隐式活锚被拿去量无关夹具基线了（本机 5 红就是这个形态）"

    same, why = GUARD_MODULE._same_upstream("origin/main", fixture, live, GUARD_MODULE.PRESET_REPO_URL)
    assert same, f"夹具不成立：旧口径（常量回落）也没判「同上游」⇒ 本判据测不到那一格（why={why}）"
    assert "预设仓" in why


def test_anchor_scripts_stay_quiet_when_the_live_anchor_is_absent_or_unrelated(tmp_path: Path):
    """对照读数：把活锚指到**不存在**的路径（= CI / 新队友未接线的真实条件）⇒ `⏭️` + `rc=0`（不是红）。

    红才是误伤：没有活锚要维持新鲜。这条同时钉住「env 覆盖的活锚路径」这条线仍然通。
    """
    baseline = tmp_path / "baseline"
    _init_repo(baseline)
    _seed_preset(baseline, "1.28.0", filler=4)
    _git(baseline, "add", "-A")
    _git(baseline, "commit", "-q", "-m", "无关基线")
    _git(baseline, "update-ref", "refs/remotes/origin/main", "HEAD")

    env = {**os.environ, "MIGAO_PRESET_LIVE": str(tmp_path / "no-such-anchor")}
    proc = subprocess.run(
        ["bash", str(CHECK_SH), "--repo", str(baseline)],
        capture_output=True, text=True, env=env,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "未接线" in proc.stdout
    assert "未跑判定" in proc.stdout
    assert "✅" not in proc.stdout


# ── ⑨ 换机 / 新队友的**唯一上手路径**（`bootstrap_hint`）必须教**当前拓扑** ──────────
# 实测（本批）：这条提示是「一次性上手」的唯一载体 —— 教错拓扑 ⇒ 新队友 clone 一个**没有预设**的仓、
# 链到一个**不存在**的路径 ⇒ 活锚解析失败（DSH 读不到预设，且**不报错**，只是「模式不见了」#3956 同族）。
# 另一处同源载体是根 `AGENTS.md`「开发环境准备」的 ② ~ ⑤ —— **两处口径必须一致**（本组一起钉）。

#: 正确的「建镜像 + 换链」两行（软链目标 = **镜像仓根**，不是 `<镜像>/.agent-presets/migao`）。
_HINT_CLONE_LINE = r'git clone --no-checkout "${REPO_URL}" "\$HOME/migao-dev-preset-anchor"'
_HINT_LINK_ROOT = r'ln -sfn "\$HOME/migao-dev-preset-anchor" "\$HOME/.dsh/.agent-presets/migao"'
_HINT_LINK_SUBTARGET = (r'ln -sfn "\$HOME/migao-dev-preset-anchor/.agent-presets/migao"'
                        r' "\$HOME/.dsh/.agent-presets/migao"')
#: 备份必须**只对真目录**做（活锚是软链时 `mv` 它 = 把软链挪成一堆 `.bak`；实测清出过两个无主 .bak）。
_HINT_BACKUP_GATE = (r'if [ -d "\$HOME/.dsh/.agent-presets/migao" ]'
                     r' && [ ! -L "\$HOME/.dsh/.agent-presets/migao" ]; then')
_AGENTS_BACKUP_GATE = ('if [ -d "$HOME/.dsh/.agent-presets/migao" ]'
                       ' && [ ! -L "$HOME/.dsh/.agent-presets/migao" ]; then')
_AGENTS_LINK_LINE = 'ln -sfn "$MIRROR" "$HOME/.dsh/.agent-presets/migao"'
_OLD_MIRROR_NAME = "migao-preset-anchor"


def _bootstrap_hint(src: str | None = None) -> str:
    """`preset-anchor-refresh.sh` 的 `bootstrap_hint()` 正文（**结构化定位**，不靠行号）。"""
    text = REFRESH_SH.read_text(encoding="utf-8") if src is None else src
    start = text.find("bootstrap_hint() {")
    if start < 0:
        raise AssertionError("定位 `bootstrap_hint()` 失败（fail-closed，别静默跳过）")
    end = text.find("\nEOF\n", start)
    if end < 0:
        raise AssertionError("定位 `bootstrap_hint` 的 heredoc 结尾失败（fail-closed）")
    return text[start:end]


def _bootstrap_hint_problems(hint: str) -> list[str]:
    """提示里「教错拓扑」的形态（纯函数 ⇒ 红证可在内存里构造，不改磁盘）。"""
    bad: list[str] = []
    if _HINT_CLONE_LINE not in hint:
        bad.append("克隆源不是**预设仓**（`git clone --no-checkout \"${REPO_URL}\" …`）"
                   " —— 教人 clone 业务仓会拿到一个**没有预设**的检出")
    if "migao-dev-preset-anchor" not in hint:
        bad.append("镜像路径不是 `$HOME/migao-dev-preset-anchor`（S4 后的约定路径）")
    if _OLD_MIRROR_NAME in hint.replace("migao-dev-preset-anchor", ""):
        bad.append(f"还留着**旧**镜像路径 `{_OLD_MIRROR_NAME}`")
    if _HINT_LINK_ROOT not in hint:
        bad.append("软链目标不是**镜像仓根**（`ln -sfn \"$HOME/migao-dev-preset-anchor\" …`）")
    if _HINT_LINK_SUBTARGET in hint:
        bad.append("软链目标是 `<镜像>/.agent-presets/migao` —— S4 后**该路径不存在** ⇒ 活锚解析失败")
    if _HINT_BACKUP_GATE not in hint:
        bad.append("备份步骤没按「**真目录**才 mv 备份 / **软链**直接覆盖」区分 "
                   "⇒ `.bak` 会连着软链一起堆积")
    return bad


def test_bootstrap_hint_teaches_the_current_topology():
    """本机空镜像时打印的上手路径必须指向**预设仓 + 镜像仓根**，且备份只对真目录做。

    改前形态（S4 之前的提示）：`clone <业务仓>` + `ln -sfn <镜像>/.agent-presets/migao` ——
    照做 ⇒ 链到不存在的路径 ⇒ DSH 静默读不到预设。
    """
    hint = _bootstrap_hint()

    assert _bootstrap_hint_problems(hint) == [], "\n".join(_bootstrap_hint_problems(hint))
    assert "预设仓仓根" in hint, "提示必须写明「软链指向仓根，不再有 `.agent-presets/migao` 这一层」"


def test_bootstrap_hint_problems_have_discriminating_power():
    """**注入式红证**：四种旧形态各改一处 ⇒ 判据必须各自判红（否则这条判据是空的）。

    变异都在**内存**里做（不改磁盘）：判据吃文本，红证就没必要写盘（写盘反而制造假红风险）。
    """
    hint = _bootstrap_hint()
    assert _bootstrap_hint_problems(hint) == [], "正对照：未变异的提示必须是干净的"

    mutations = {
        "旧克隆源（业务仓）": hint.replace(_HINT_CLONE_LINE,
                                    'git clone --no-checkout "git@github.com:zhaokai-mgzn/migao.git"'),
        "旧软链目标（子路径）": hint.replace(_HINT_LINK_ROOT, _HINT_LINK_SUBTARGET),
        "旧镜像路径名": hint.replace("migao-dev-preset-anchor", _OLD_MIRROR_NAME),
        "无条件备份（软链也 mv）": hint.replace(_HINT_BACKUP_GATE,
                                        r'if [ -d "\$HOME/.dsh/.agent-presets/migao" ]; then'),
    }
    for name, mutated in mutations.items():
        assert mutated != hint, f"变异没生效（{name}）—— 判据测不到那一格"
        assert _bootstrap_hint_problems(mutated), f"变异没被判红：{name}"


def test_agents_md_and_refresh_hint_agree_on_the_current_topology():
    """两处同源载体（根 `AGENTS.md`「开发环境准备」⇄ `bootstrap_hint`）口径必须一致。

    实测口径：AGENTS.md 早就按 S4 的新拓扑写了（clone **预设仓** + 链**镜像仓根**）——
    本判据把这份一致**钉住**，防止任一处被改回旧拓扑而没人发现。
    """
    agents = Path(REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    hint = _bootstrap_hint()

    for face, text in (("AGENTS.md", agents), ("bootstrap_hint", hint)):
        assert _OLD_MIRROR_NAME not in text.replace("migao-dev-preset-anchor", ""), \
            f"{face} 里还有旧镜像路径 `{_OLD_MIRROR_NAME}`"
        assert "migao-dev-preset-anchor" in text, f"{face} 里没有 S4 后的镜像路径"
    assert _AGENTS_BACKUP_GATE in agents, "AGENTS.md 的备份步骤没按「真目录才 mv」设门"
    assert _AGENTS_LINK_LINE in agents, "AGENTS.md 的换链目标不是镜像仓根"
    assert _HINT_BACKUP_GATE in hint, "bootstrap_hint 的备份步骤没按「真目录才 mv」设门"
    assert _HINT_LINK_ROOT in hint, "bootstrap_hint 的换链目标不是镜像仓根"
    # AGENTS.md 的镜像克隆源也必须是**预设仓**（不是业务仓）
    assert "git clone --no-checkout <预设仓 URL>" in agents
