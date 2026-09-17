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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "agent-presets-guard.py"
DEV_WORKTREE = REPO_ROOT / "scripts" / "dev-worktree.sh"
CHECK_SH = REPO_ROOT / "scripts" / "preset-anchor-check.sh"
REFRESH_SH = REPO_ROOT / "scripts" / "preset-anchor-refresh.sh"
SKILL_REL = ".agent-presets/migao/skills/migao-dev-flow/SKILL.md"
PRESET_YML_REL = ".agent-presets/migao/preset.yml"

SKILL_TMPL = """---
name: migao-dev-flow
version: {version}
description: 夹具技能
---

# 夹具技能 v{version}

正文占位（第 {filler} 号夹具）。
"""


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
    path = repo / SKILL_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SKILL_TMPL.format(version=version, filler=filler), encoding="utf-8")
    return path


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
    _write_skill(repo, "1.28.0", filler=2)
    (repo / ".agent-presets/migao/preset.yml").write_text("name: migao\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "基准 v1.28.0")
    new_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # ② 分支（= 工作区）落在 v1.26.0：从基准分出、改成旧版并提交 —— 制造「分支落后基准」
    _git(repo, "checkout", "-q", "-b", "snapshot")
    _write_skill(repo, "1.26.0", filler=1)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "旧快照 v1.26.0")
    old_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # ③ 回工作区（= snapshot 分支，v1.26.0），main 仍指向 v1.28.0
    _git(repo, "checkout", "-q", "snapshot")
    _git(repo, "update-ref", "refs/heads/main", new_sha)

    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == old_sha
    assert _read_version(repo) == "1.26.0", "夹具起点必须是旧快照"
    return repo


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


def test_same_version_different_content_warns_but_passes(fixture_repo: Path):
    """同版本但内容不同（**分叉**，不是升级）⇒ 告警，但不非零退出。

    分叉多为「在旧快照上改了预设」；本判据的职责是报出来，不是替人决定要不要提交。
    """
    _aligned_to_ref(fixture_repo)
    _write_skill(fixture_repo, "1.28.0", filler=99)   # 版本不变，正文变了

    proc = _run_guard(fixture_repo, "check", "--ref", "main")

    assert proc.returncode == 0, proc.stdout
    assert "分叉" in proc.stdout
    assert "不是升级" in proc.stdout


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
    _write_skill(repo, "1.28.0", filler=2)
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
    _write_skill(wt, "1.26.0", filler=1)
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
    """`dev-worktree.sh` 必须真的接上：① `add` 调刷新；② 有 preset-guard / prune 子命令。"""
    source = DEV_WORKTREE.read_text(encoding="utf-8")

    assert "refresh_presets \"$path\"" in source, "add 后没有调用预设刷新（地雷未根治）"
    assert "checkout origin/main -- .agent-presets/" in source
    assert "preset-guard)" in source
    assert "prune)" in source
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
    _write_skill(repo, "1.28.0", filler=2)
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

    _write_skill(repo, "1.27.0", filler=2)   # 降级
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


def _seed_preset(repo: Path, version: str, filler: int = 1) -> None:
    _write_skill(repo, version, filler=filler)
    (repo / PRESET_YML_REL).write_text("name: migao\n", encoding="utf-8")


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
    _git(mirror, "checkout", "-q", "--detach", c3)
    return {"origin": origin, "seed": seed, "baseline": baseline, "mirror": mirror,
            "c1": c1, "c2": c2, "c3": c3}


def _anchor_of(env: dict, which: str = "mirror") -> str:
    return str(env[which] / ".agent-presets/migao")


def _check_env(env: dict) -> dict:
    """给脚本用的环境：镜像 + 活锚都指到夹具（避免读到本机真实活锚）。
    `check` 脚本**总是显式**传 `--anchor`，故「同历史」这条豁免不适用 —— 夹具自洽。"""
    return {
        **os.environ,
        "MIGAO_PRESET_MIRROR": str(env["mirror"]),
        "MIGAO_PRESET_LIVE": _anchor_of(env),
    }


def test_anchor_content_behind_is_red(anchor_env: dict):
    """红证（显性形态）：活锚检出停在 v1.28.0、基线已 v1.29.0 ⇒ 必须非零退出并给同步命令。"""
    _git(anchor_env["mirror"], "checkout", "-q", "--detach", anchor_env["c1"])

    proc = _run_guard(anchor_env["baseline"], "anchor", "--anchor", _anchor_of(anchor_env))

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

    proc = _run_guard(anchor_env["baseline"], "anchor", "--anchor", _anchor_of(anchor_env))

    assert proc.returncode != 0, proc.stdout
    assert "落后 1 个提交" in proc.stdout
    assert "内容当前恰好一致" in proc.stdout
    assert "活锚=1.29.0 基线=1.29.0" in proc.stdout


def test_anchor_fresh_is_green(anchor_env: dict):
    """不许误伤：活锚就在基线 tip 上 ⇒ 绿，且必须把「比了什么」说清楚（可自证）。"""
    proc = _run_guard(anchor_env["baseline"], "anchor", "--anchor", _anchor_of(anchor_env))

    assert proc.returncode == 0, proc.stdout
    assert "✅ 活锚新鲜" in proc.stdout
    assert "逐字节一致" in proc.stdout
    assert "与基线同一提交" in proc.stdout
    assert "❌" not in proc.stdout


def test_dangling_anchor_is_red(anchor_env: dict, tmp_path: Path):
    """红证：悬空软链（#3956 的静默失效形态）⇒ 红，且必须说清后果与修法。"""
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "does-not-exist")

    proc = _run_guard(anchor_env["baseline"], "anchor", "--anchor", str(dangling))

    assert proc.returncode != 0, proc.stdout
    assert "悬空" in proc.stdout
    assert "静默" in proc.stdout
    assert "3956" in proc.stdout


def test_absent_anchor_is_skipped_not_passed(anchor_env: dict, tmp_path: Path):
    """三态：本机没接线（CI / 容器 / 新队友未接线）⇒ `⏭️ 未跑判定`，**不得**说成「通过」。

    红了才是误伤：没有活锚要维持新鲜。但措辞必须让人读得出「这次没判」。
    """
    proc = _run_guard(anchor_env["baseline"], "anchor", "--anchor", str(tmp_path / "nope"))

    assert proc.returncode == 0, proc.stdout
    assert "未跑判定" in proc.stdout
    assert "未接线" in proc.stdout
    assert "✅" not in proc.stdout


def test_handcopied_anchor_is_judged_by_content(anchor_env: dict, tmp_path: Path):
    """手抄副本（**不是 git 检出**）：判不了 sha，但内容照样要判 —— 旧的 ⇒ 红；一致 ⇒ 绿 + 形态警告。"""
    stale = tmp_path / "handcopy-old"
    _git(anchor_env["mirror"], "checkout", "-q", "--detach", anchor_env["c1"])
    shutil.copytree(anchor_env["mirror"] / ".agent-presets/migao", stale)   # 无 .git 的纯目录

    bad = _run_guard(anchor_env["baseline"], "anchor", "--anchor", str(stale))

    assert bad.returncode != 0, bad.stdout
    assert "不是 git 检出" in bad.stdout
    assert "活锚内容与 origin/main 不一致" in bad.stdout

    _git(anchor_env["mirror"], "checkout", "-q", "--detach", anchor_env["c3"])
    fresh = tmp_path / "handcopy-new"
    shutil.copytree(anchor_env["mirror"] / ".agent-presets/migao", fresh)

    ok = _run_guard(anchor_env["baseline"], "anchor", "--anchor", str(fresh))

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
        "origin/main", anchor_env["baseline"], other / ".agent-presets/migao",
        explicit=False, out=implicit,
    )

    assert rc_implicit == 0, implicit.getvalue()
    assert "未跑判定" in implicit.getvalue()
    assert "不是同一上游" in implicit.getvalue()
    assert "origin=" in implicit.getvalue()      # 两个 URL 都要打出来（可自证为什么跳过）

    explicit = io.StringIO()
    rc_explicit = GUARD_MODULE.judge_anchor(
        "origin/main", anchor_env["baseline"], other / ".agent-presets/migao",
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
        "origin/main", anchor_env["baseline"], anchor_env["mirror"] / ".agent-presets/migao",
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
    (seed / SKILL_REL).write_text("# 没有 frontmatter\n\n正文\n", encoding="utf-8")
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
    _write_skill(seed, "1.29.0", filler=2)
    text = (seed / SKILL_REL).read_text(encoding="utf-8").replace(
        "description: 夹具技能", "description: 夹具技能 # 这后面会被 YAML 当成注释",
    )
    (seed / SKILL_REL).write_text(text, encoding="utf-8")
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
    """
    skills = sorted((REPO_ROOT / ".agent-presets/migao/skills").glob("*/SKILL.md"))
    assert skills, "预设目录里找不到任何技能（判据会空跑，不许静默通过）"
    for skill in skills:
        assert GUARD_MODULE._frontmatter_problems(skill) == [], f"{skill} 的 frontmatter 有问题"


def test_check_reports_anchor_verdict(anchor_env: dict):
    """接线：`check`（= `dev-worktree.sh preset-guard` 的判定本体）必须**带上活锚判定**并影响退出码。"""
    _git(anchor_env["mirror"], "checkout", "-q", "--detach", anchor_env["c1"])

    bad = _run_guard(anchor_env["baseline"], "check", "--ref", "origin/main",
                     "--source", "worktree", "--anchor", _anchor_of(anchor_env))

    assert bad.returncode != 0, bad.stdout
    assert "活锚新鲜度" in bad.stdout
    assert "活锚内容与 origin/main 不一致" in bad.stdout

    _git(anchor_env["mirror"], "checkout", "-q", "--detach", anchor_env["c3"])

    ok = _run_guard(anchor_env["baseline"], "check", "--ref", "origin/main",
                    "--source", "worktree", "--anchor", _anchor_of(anchor_env))

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
    (anchor_env["mirror"] / PRESET_YML_REL).write_text("name: 手改\n", encoding="utf-8")
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
    """接线：`dev-worktree.sh` 的说明必须指向活锚自检/刷新脚本（否则读者只知道内容单调性那一半）。"""
    source = DEV_WORKTREE.read_text(encoding="utf-8")

    assert "preset-anchor-check.sh" in source
    assert "preset-anchor-refresh.sh" in source
    assert "活锚" in source
