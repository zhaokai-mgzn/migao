# case_ids: MC-012
"""preset-guard：`.agent-presets/**` **同号不同内容 ⇒ 判红**（跨包撞车，issue #5425）。

## 病灶（实测，2026-09-24 一晚发生 2 次）

两个**并行**开发包**同时**改同一个技能文件的 `version:` —— 第一次双双写成 `1.56.0`、
第二次一个 `1.56.0` 一个 `1.57.0` ⇒ 后果是**同号两条沿革 / 同号不同内容**；
而当时的判定只判**版本下降**、对「同版本」一律**放行** ⇒ 撞车**只能靠人肉发现**，
发现后还要 rebase 解冲突 + 抬号 + **重跑整轮 CI**（正是用户裁定要消掉的那类浪费）。

## 判据（5 种形态，逐条带注入式红证）

| # | 形态 | 期望 |
|---|---|---|
| ① | 候选与基准**同号不同内容** | ❌ 非零退出 + 逐字出口：抬号到「基准版本 + 1」+「同号不同内容 = 跨包撞车（今晚已发生 2 次）」+ 出处单号 |
| ② | **抬号**（`1.28.0` → `1.29.0`） | ✅ 放行（改研发模式本身不能被堵死） |
| ③ | **无改动**（候选与基准都没改） | ✅ 放行 + **零动作出声**（§23 G6：不许静默退出） |
| ④ | **降号**（`1.28.0` → `1.27.0`） | ❌ 仍红 —— **既有语义未回退** |
| ⑤ | **同号同内容** | ✅ 仍放行，且读数必须证明**真的判定过**那条候选（防「走了零动作捷径」的空绿） |

另两条：**成本口径**（§23 G8：报「判定了几条 / 命中几条 / 跳过**原因**」，禁用挂钟时长当判据）、
**单号一致**（守卫的 `COLLISION_ISSUE` 与本文件同值 —— 红灯指向的出处不许漂）。

## 红证的形状（§23 G7：判据要会红，且注入要自证）

判据写成**纯函数**（`*_violations`）：真夹具与**注入副本**走同一条判据 ⇒
在**临时副本**上摘掉撞车分支 / 删掉读数 / 删掉零动作那一行，判据必须变红；
每次注入都自证 `mutated != src`（`_mutated_guard`，未命中即抛错）。

夹具一律建在 `tmp_path` 的**真 git 仓库**里（不是 mock）—— 判定本体就是 git 语义，
mock 掉 git 等于把被测对象换成替身（§18「绿了但没跑」）。工作区 = 与基准逐字节对齐的干净起点。
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "agent-presets-guard.py"
DEV_WORKTREE = REPO_ROOT / "scripts" / "dev-worktree.sh"
SKILL_REL = ".agent-presets/migao/skills/migao-dev-flow/SKILL.md"
PRESET_YML_REL = ".agent-presets/migao/preset.yml"
#: 与 `scripts/agent-presets-guard.py` 的 `COLLISION_ISSUE` **必须同值**（判据钉住两处一致）。
COLLISION_ISSUE = "#5425"
BASE_VERSION = "1.28.0"
NEXT_VERSION = "1.29.0"

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

    取不到 spec/loader 时**抛错 fail-closed**（门禁依赖的加载不允许静默空转）。
    """
    spec = importlib.util.spec_from_file_location("agent_presets_guard_collision", GUARD)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载守卫模块（判定本体缺失即门禁空转）：{GUARD}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD_MODULE = _load_guard()


# ── 夹具 ──────────────────────────────────────────────────────────────────────

def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"夹具 git {' '.join(args)} 失败：{proc.stderr}")
    return proc


def _write_skill(repo: Path, version: str, filler: int) -> Path:
    path = repo / SKILL_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SKILL_TMPL.format(version=version, filler=filler), encoding="utf-8")
    return path


def _run(repo: Path, guard: Path | None = None) -> subprocess.CompletedProcess:
    """跑**提交路径守卫**（与 `./scripts/dev-worktree.sh preset-guard` 同参数：`check` + 默认 both）。"""
    return subprocess.run(
        [sys.executable, str(guard or GUARD), "--repo", str(repo), "check", "--ref", "main"],
        capture_output=True, text=True,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """真 git 仓库：`main` 上是 `v1.28.0`，工作区与之**逐字节对齐**（干净起点）。

    ⑤ 需要「路径进 diff 但内容逐字节相同」这一形态 ⇒ 用 mode 变化造（`chmod +x`），
    它不会改动字节内容，却能让 git 把该路径报进 `--name-only`。
    """
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "fixture@example.com")
    _git(path, "config", "user.name", "fixture")
    _write_skill(path, BASE_VERSION, 2)
    (path / PRESET_YML_REL).write_text("name: migao\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", f"基准 v{BASE_VERSION}")
    return path


def _mutated_guard(tmp_path: Path, old: str, new: str, tag: str) -> Path:
    """把守卫的**临时副本**改一处（仓库文件零污染），并**自证注入生效**。

    `mutated != src` 是硬前置：未命中就抛错 —— 否则「注入版照样绿」会被误读成「判据没判别力」，
    而真相是注入根本没落进被测对象（§23 G7 的弱前提）。
    """
    src = GUARD.read_text(encoding="utf-8")
    mutated = src.replace(old, new, 1)
    if mutated == src:
        raise AssertionError(f"变异注入未生效（自证失败 ⇒ 后面的红证是空断言）：{old!r} 未命中")
    path = tmp_path / f"agent-presets-guard-{tag}.py"
    path.write_text(mutated, encoding="utf-8")
    return path


def _install_cli_into(repo: Path) -> Path:
    """把 `dev-worktree.sh` + 判定本体拷进夹具 ⇒ 用**真实 CLI 面**跑（不是只跑 python 本体）。

    脚本按 `${BASH_SOURCE[0]}/..` 定位 `$ROOT`，故副本会把**夹具**当仓库根：
    `preset-guard` 的输入面 = 夹具的索引/工作区，正是我们造形态的地方。
    """
    scripts = repo / "scripts"
    scripts.mkdir(exist_ok=True)
    for name in ("dev-worktree.sh", "agent-presets-guard.py"):
        shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
    return scripts / "dev-worktree.sh"


# ── 判据（纯函数：真夹具与注入副本走同一条）────────────────────────────────────

def collision_violations(rc: int, stdout: str) -> list[str]:
    """判据 ①：同号不同内容 ⇒ 非零退出 + 逐字可行动出口。空 = 合规。"""
    bad: list[str] = []
    if rc == 0:
        bad.append("同号不同内容**没有**判红（exit=0）—— 跨包撞车会静默通过")
    for needle in (
        "同号不同内容 = 跨包撞车",
        "今晚已发生 2 次",
        f"抬号到 `{NEXT_VERSION}`",
        f"基准版本 {BASE_VERSION} + 1",
        COLLISION_ISSUE,
        "拒绝提交",
    ):
        if needle not in stdout:
            bad.append(f"红灯缺少可行动出口 / 归因片段：{needle!r}")
    return bad


def upgrade_violations(rc: int, stdout: str) -> list[str]:
    """判据 ②：抬号 ⇒ 放行（且不得出现红标）。空 = 合规。"""
    bad: list[str] = []
    if rc != 0:
        bad.append(f"合法升级被误伤（exit={rc}）—— 改研发模式本身不能被堵死")
    if f"{BASE_VERSION} → {NEXT_VERSION}" not in stdout:
        bad.append("没有报出「基准 → 候选」的升级读数（分不清放行的是哪一格）")
    if "合法升级" not in stdout:
        bad.append("没有点明这是**合法升级**（放行理由必须可读）")
    if "❌" in stdout:
        bad.append("绿态输出里出现了 ❌（读起来像红）")
    return bad


def zero_action_violations(rc: int, stdout: str) -> list[str]:
    """判据 ③：无改动 ⇒ 放行 + **零动作出声**（§23 G6）。空 = 合规。"""
    bad: list[str] = []
    if rc != 0:
        bad.append(f"候选与基准都没改，却被判红（exit={rc}）")
    if "零动作" not in stdout:
        bad.append("候选 0 条时**没有**打印「零动作」——「我没做事」与「我没跑」必须长得不一样")
    if "原因" not in stdout:
        bad.append("零动作没有给出原因（读数不可解释）")
    if "候选 0 条" not in stdout:
        bad.append("总读数里没有「候选 0 条」（读数与事实不符）")
    return bad


def downgrade_violations(rc: int, stdout: str, old: str) -> list[str]:
    """判据 ④：降号 ⇒ 仍红（**既有语义未回退**）。空 = 合规。"""
    bad: list[str] = []
    if rc == 0:
        bad.append("版本下降没有判红 —— 既有语义被回退了")
    if "版本下降" not in stdout:
        bad.append("红灯没有点明「版本下降」")
    if f"{BASE_VERSION} → {old}" not in stdout:
        bad.append(f"红灯没报出降级幅度：{BASE_VERSION} → {old}")
    return bad


def same_content_violations(rc: int, stdout: str) -> list[str]:
    """判据 ⑤：同号同内容 ⇒ 仍放行，且**读数证明判定真的跑过那条候选**。空 = 合规。"""
    bad: list[str] = []
    if rc != 0:
        bad.append(f"同号同内容被误伤（exit={rc}）—— 「与基准相同」是合法态")
    if "内容也逐字节相同" not in stdout:
        bad.append("没有走到「同号且内容逐字节相同」这条支路（判据 ⑤ 可能是空绿）")
    if "候选 1 条" not in stdout or "同号同内容 1" not in stdout:
        bad.append("读数没证明那条候选被**判定过**（可能走了「零动作」捷径 ⇒ 判据 ⑤ 是空绿）")
    if "❌" in stdout:
        bad.append("绿态输出里出现了 ❌（读起来像红）")
    return bad


def reading_violations(rc: int, stdout: str) -> list[str]:
    """成本口径（§23 G8）：读数报**判定 / 命中 / 跳过及其原因**，且明示不报挂钟。空 = 合规。"""
    _ = rc  # 读数与红绿正交：本判据只看读数本身
    bad: list[str] = []
    if "📊" not in stdout:
        bad.append("没有读数行（§23 G8 要求每次运行报工作量）")
    for needle in (
        "判定 1 条",
        "命中 1 条（降级 0 / 同号撞车 1）",
        "跳过 1 条（无 `version:` 字段 1",
        "不报挂钟",
    ):
        if needle not in stdout:
            bad.append(f"读数缺少可核对的片段：{needle!r}")
    return bad


# ── ① 同号不同内容 ⇒ 红 ────────────────────────────────────────────────────────

def test_same_version_different_content_is_rejected(repo: Path):
    """判据 ①（**本单的核心形态**）：`version:` 不变、正文变了 ⇒ 必须非零退出 + 给出出口。"""
    _write_skill(repo, BASE_VERSION, 99)          # 版本不动，内容变了 = 跨包撞车的形状
    proc = _run(repo)

    assert collision_violations(proc.returncode, proc.stdout) == [], (
        "同号不同内容未被拦成可行动的红色：\n" + proc.stdout
    )


def test_preset_guard_cli_carries_the_collision_verdict(repo: Path):
    """**入口面**（`./scripts/dev-worktree.sh preset-guard`）也必须判红 —— 判定在 CLI 面上可达。

    夹具仓库没有 `origin`（默认基准是 `origin/main`）⇒ 显式给 `--ref main`（本子命令把 `"$@"`
    原样透传给判定本体，`preset-guard` 的其余行为一字未动）。
    """
    cli = _install_cli_into(repo)
    _write_skill(repo, BASE_VERSION, 99)

    proc = subprocess.run(["bash", str(cli), "preset-guard", "--ref", "main"], cwd=repo,
                          capture_output=True, text=True)

    assert collision_violations(proc.returncode, proc.stdout) == [], (
        "CLI 面（dev-worktree.sh preset-guard）没有带上新判定：\n" + proc.stdout + proc.stderr
    )


def test_collision_branch_injection_reds(repo: Path, tmp_path: Path):
    """判据 ① 的**判别力自证**：摘掉撞车分支（临时副本）⇒ 同一形态不再红 ⇒ 判据 ① 变红。"""
    _write_skill(repo, BASE_VERSION, 99)
    real = _run(repo)
    assert collision_violations(real.returncode, real.stdout) == [], (
        "注入前真守卫必须已判红，否则本红证分不清对象：\n" + real.stdout
    )

    injected = _run(repo, guard=_mutated_guard(tmp_path, "if same is False:", "if False:", "nobranch"))

    assert injected.returncode == 0, (
        "注入版（撞车分支被摘掉）竟然仍判红 ⇒ 该分支不是判红的来源：\n" + injected.stdout
    )
    assert collision_violations(injected.returncode, injected.stdout) != [], (
        "注入后判据 ① 仍报合规 ⇒ 它是空断言（怎么改都不红）"
    )


# ── ② 抬号 ⇒ 绿 ───────────────────────────────────────────────────────────────

def test_bumped_version_passes(repo: Path):
    """判据 ②：抬一格（`1.28.0` → `1.29.0`）⇒ 放行。"""
    _write_skill(repo, NEXT_VERSION, 99)
    proc = _run(repo)

    assert upgrade_violations(proc.returncode, proc.stdout) == [], (
        "合法升级被误伤：\n" + proc.stdout
    )


# ── ③ 无改动 ⇒ 绿 + 零动作出声 ────────────────────────────────────────────────

def test_untouched_candidate_passes_loudly(repo: Path):
    """判据 ③：候选与基准都没改 `.agent-presets/**` ⇒ 放行 + 零动作 + 原因（不许静默退出）。"""
    proc = _run(repo)

    assert zero_action_violations(proc.returncode, proc.stdout) == [], (
        "零动作没有出声：\n" + proc.stdout
    )


def test_zero_action_silence_injection_reds(repo: Path, tmp_path: Path):
    """判据 ③ 的判别力自证：把「零动作」那一段注入掉 ⇒ 判据 ③ 必须变红。"""
    injected = _run(repo, guard=_mutated_guard(
        tmp_path, 'if not stats.get("candidates"):', "if False:", "nosilence"))

    assert zero_action_violations(injected.returncode, injected.stdout) != [], (
        "把「零动作」删掉后判据 ③ 仍报合规 ⇒ 它测的不是出声"
    )


# ── ④ 降号 ⇒ 红（既有语义未回退）───────────────────────────────────────────────

def test_downgraded_version_still_rejected(repo: Path):
    """判据 ④：降号 ⇒ 仍红 —— 本单**只加**判定，既有语义不许回退。"""
    old = "1.27.0"
    _write_skill(repo, old, 99)
    proc = _run(repo)

    assert downgrade_violations(proc.returncode, proc.stdout, old) == [], (
        "既有「版本下降 ⇒ 红」被回退了：\n" + proc.stdout
    )


# ── ⑤ 同号同内容 ⇒ 绿（且读数证明真的判定过）───────────────────────────────────

def test_same_version_same_content_still_passes(repo: Path):
    """判据 ⑤：版本相同且内容逐字节相同 ⇒ 仍放行（「与基准相同」的合法态）。

    形态用 `chmod +x` 造：该路径进了 `git diff --name-only`（mode 变），但字节内容与基准相同
    ⇒ 必须走「同号同内容」支路（若走成「零动作」捷径，读数断言会红）。
    """
    (repo / SKILL_REL).chmod(0o755)
    proc = _run(repo)

    assert same_content_violations(proc.returncode, proc.stdout) == [], (
        "同号同内容被误判或没被真的判定：\n" + proc.stdout
    )


# ── 成本口径（§23 G8）────────────────────────────────────────────────────────

def test_cost_reading_reports_judged_hits_and_skip_reasons(repo: Path):
    """读数：同一条候选（撞车）+ 一条无版本号的预设文件（跳过）⇒ 三类读数都要出，且给跳过原因。"""
    _write_skill(repo, BASE_VERSION, 99)
    (repo / PRESET_YML_REL).write_text("name: migao\nnote: 手改\n", encoding="utf-8")
    proc = _run(repo)

    assert reading_violations(proc.returncode, proc.stdout) == [], (
        "成本读数不完整（§23 G8 要求「判定了几条 / 命中几条 / 跳过原因」）：\n" + proc.stdout
    )


def test_reading_removal_injection_reds(repo: Path, tmp_path: Path):
    """读数的判别力自证：把读数行注入掉 ⇒ 读数判据必须变红。"""
    _write_skill(repo, BASE_VERSION, 99)
    injected = _run(repo, guard=_mutated_guard(
        tmp_path, 'f"  📊 [{label}] 读数', 'f"  [读数被注入摘掉] {label}', "noreading"))

    assert reading_violations(injected.returncode, injected.stdout) != [], (
        "读数被摘掉后判据仍报合规 ⇒ 它测的不是读数"
    )


# ── 守卫本体的小判据（单号一致 + 抬号约定）──────────────────────────────────────

def test_collision_issue_is_pinned_in_both_places():
    """红灯指向的出处单号必须与守卫本体同值，且形如 `#数字`（避免指向一个不存在/已关的对象）。"""
    value = GUARD_MODULE.COLLISION_ISSUE
    assert value == COLLISION_ISSUE, (
        f"守卫的 COLLISION_ISSUE({value!r}) 与本判据({COLLISION_ISSUE!r}) 不一致 —— 两处必须同 PR 一起改"
    )
    assert re.fullmatch(r"#\d+", value), f"出处单号形态不对：{value!r}"


def test_next_version_bumps_the_minor_component():
    """抬号约定 = **次版本 +1、其后归零**（本仓实测形态 `1.56.0` → `1.57.0`）。"""
    assert GUARD_MODULE.next_version("1.57.0") == "1.58.0"
    assert GUARD_MODULE.next_version(BASE_VERSION) == NEXT_VERSION
    assert GUARD_MODULE.next_version("1.56.3") == "1.57.0"