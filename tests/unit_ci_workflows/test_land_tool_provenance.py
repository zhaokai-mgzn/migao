# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 —— 见
#   `.github/cases/misc.yml` MC-012「CI workflow 结构由 pytest 单测验证」的登记。本 PR **不新建用例族**。）
"""`land` 的 preflight 必须打印「**它用的是哪一份工具**」（issue #5721）。

## 这守的是什么（实测代价，独立复核见 PR 正文）

`land` 的 ①步（`rebase`）跑的不是你 worktree 里的 `scripts/dev-worktree.sh`，而是
`scripts/issue_lifecycle.py::_devtree_script` 解析出的 **`main_root()/scripts/dev-worktree.sh`**
= **主工作区那一份**。⇒ **任何包落地一个工具修复后，主工作区就落后了**，
**下一个包的 `land` 跑的是旧工具**。

实测（PR #5720 的作者）：主工作区落后 **3** 个提交（`97f29e43b` #5713 vs `ef8f34606` #5719），
旧副本**缺 #5719 的守卫**（`grep -c preset_has_uncommitted_drift`：主工作区 **0** / worktree **2**）
⇒ `land` ①步**连停 3 次**（17:52:41 / 17:55:46 / 17:57:42），而他**从 worktree 里手动跑同一子命令
rc=0**、失败后 5 秒六个判据全「无漂移」⇒ **白烧三轮才定位到「工具来源是主工作区」**。
⇒ 本文件钉住那条 **preflight 读数**：路径 + 内容 sha + 与 `origin/main` 的差 + behind 计数。

## 🔴 取舍：仅打印 + 落后即显式告警，**有意不** fail-closed

落后是**会话中的常态**（每个工具修复都会造成），一味 fail-closed 会变成**新的假阻塞**
（本仓刚修过一个同类：`land` 对预设面的假阻塞 —— 见 `tests/unit_ci_workflows/test_dev_worktree_rebase.py`；
⚠️ 该文件 S4 / issue #6020 起**已删**，同类假阻塞的判据现由 `test_agent_presets_guard.py` 的反向用例承担）。
真正致命的是**诊断路径太长**（三轮），而可见性正好治它 ⇒ 告警随带**可执行的解除命令**。
本文件把它钉成判据（落后形态下 `land --dry-run` 仍 rc=0）：改成 fail-closed 必须是有意的。

## 覆盖面登记：本判据面**覆盖不到**什么

- ❌ **派单消息里「仓库根已同步 origin/main」那句断言**：它在**仓外**（不 durable、判据读不到）——
  本文件只保证 `land` **自己**会打印它用的是哪一份、以及它与 `origin/main` 的差；
  派单侧的判别动作由技能 `migao-dev-flow` §26 与台账 `relay_entries` 承担（本 PR 的 `FM-R13`）。
- ❌ **本地 `origin/main` ref 自身过期 ⇒ 漏报**：读数是**下界**（对比的是本地 ref，preflight
  **不联网、不写盘**；①步的 `git fetch` 才刷新它）。⇒ 唯一消除办法是 preflight 也联网，
  那会给每次 `land` 引入网络依赖（有意不做）。
- ❌ **主工作区落后、但被用的那个工具文件恰好与 `origin/main` 一致**：此种形态**故意不告警**
  （避免假告警）⇒ 输出里只有 behind 计数、没有「旧工具」告警。
- ❌ **只覆盖 `land` 这条入口**：直接手跑 `bash <主工作区>/scripts/<工具> …`、
  或用别的方式派生 `main_root()` 的调用方不经这段 preflight。
- ❌ **判不了「落后有多严重」**：告警只说「可能是旧工具」，说不出**缺的是哪条守卫**（要人读 diff）。

夹具 = `tmp_path` 下的**真 git 仓库 + 真 bare origin + 真 worktree**（不是 mock）：判据本体就是
git 语义（`hash-object` / `rev-list` / `rev-parse`），mock 掉 git 等于把被测对象换成替身。
只换 `gh` 这一个 CLI 边界（替身可执行文件）；**不**注入 `MIGAO_DEVTREE_BIN`
—— 本文件测的正是「**默认解析到主工作区那一份**」这条路径。
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "issue-lifecycle.sh"
MODULE = REPO_ROOT / "scripts" / "issue_lifecycle.py"
GUARD_MODULE = REPO_ROOT / "scripts" / "agent-presets-guard.py"

BRANCH = "fix/land-tool"
#: `main_root()` 派生的工具（= 你 worktree 里可能有一份，而 `land` **不用**它）。
TOOL_NAMES = ("dev-worktree.sh", "preset-anchor-refresh.sh")
TOOL_MARK = "🧰 工具来源"

#: 注入锚点：**逐字**取自 `scripts/issue_lifecycle.py` 的 preflight 调用（唯一命中 1 次才允许变异）。
PREFLIGHT_CALL = "    print_tool_provenance(root, cwd)"
#: 注入锚点：工具清单的那一行（同类入口漏报的红证用）。
TOOLS_TUPLE_TAIL = '    ("preset-anchor-refresh.sh", PRESET_REFRESH_ENV, _preset_refresh_script),\n'

_GH_STUB = r'''#!/usr/bin/env python3
"""替身 gh：`land` 在 `--dry-run` 前只需要一次 `pr list` 读数 ⇒ 恒回一条在飞 draft PR。"""
import json, sys

print(json.dumps([{
    "number": 42, "state": "OPEN", "isDraft": True,
    "url": "https://example.invalid/42", "mergedAt": None,
    "headRefName": "fix/land-tool", "baseRefName": "main",
    "files": [{"path": "scripts/issue_lifecycle.py"}],
}]))
'''


# ── 判据本体（纯函数：吃 stdout，**不碰磁盘** ⇒ 红证可内存构造）──────────────────

def provenance_problems(stdout: str, *, tool_dir: Path, in_sync: bool) -> list[str]:
    """preflight 读数判据：空列表 = 全绿。坏形态逐条列出（红证每条都能单独变红）。"""
    bad: list[str] = []
    if TOOL_MARK not in stdout:
        return [f"没有工具来源读数（`{TOOL_MARK}`）—— 删掉 preflight 调用 ⇒ 这一条必红"]
    block = stdout.split(TOOL_MARK, 1)[1]
    for name in TOOL_NAMES:
        if name not in block:
            bad.append(f"工具来源读数里没有点名 `{name}`（**同类入口漏报** ⇒ 红）")
        if name in block and str(tool_dir / "scripts" / name) not in block:
            bad.append(f"工具来源读数里没有给出 `{name}` 的**路径**（接收方没法自己核）："
                       f"{tool_dir / 'scripts' / name}")
    if not re.search(r"sha=[0-9a-f]{7,40}", block):
        bad.append("工具来源读数里没有内容 sha（`sha=<hex>`）⇒ 判不了「用的是哪一份内容」")
    if "落后 origin/main" not in block:
        bad.append("工具来源读数里没有「落后 origin/main」这一项")
    if not re.search(r"口径：.*本地.*origin/main", block):
        bad.append("缺少口径行：必须写明这条对比用的是**本地** `origin/main` ref"
                   "（不联网 / 不写盘 / 自身过期时是下界）")
    if in_sync:
        if "旧工具" in block or "::warning::" in block:
            bad.append("主工作区与 origin/main **一致**时不得告警（假告警 = 新的噪音）")
        if not re.search(r"0（与本地 origin/main 一致）", block):
            bad.append("一致形态下必须**显式**给出 0 behind 读数（G6：零动作也要出声）")
    else:
        if "旧工具" not in block:
            bad.append("工具落后时**必须**显式告警「你跑的可能是旧工具」")
        if "merge --ff-only" not in block:
            bad.append("告警必须带**可执行**的解除命令（`merge --ff-only`）")
        if str(tool_dir) not in block:
            bad.append("解除命令里必须给出主工作区路径（否则接收方还得自己找）")
    return bad


# ── 夹具：真 git 仓库（= 主工作区）+ 真 bare origin + 真 worktree + 替身 gh ────────

def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} 失败：{proc.stderr}"
    return proc


class Fixture:
    """真仓库夹具。`repo` = **主工作区**（`land` 的工具来源就是它）。"""

    def __init__(self, base: Path):
        self.base = base
        base.mkdir(parents=True, exist_ok=True)
        self.origin = base / "origin.git"
        self.repo = base / "repo"
        self.wt_base = base / "migao-wt"
        self.home = base / "home"
        self.bin = base / "bin"
        for d in (self.wt_base, self.home, self.bin):
            d.mkdir(parents=True, exist_ok=True)

        _git(base, "init", "-q", "--bare", "-b", "main", str(self.origin))
        _git(base, "clone", "-q", str(self.origin), str(self.repo))
        _git(self.repo, "config", "user.email", "fixture@example.com")
        _git(self.repo, "config", "user.name", "fixture")
        (self.repo / "scripts").mkdir()
        for name in TOOL_NAMES:
            (self.repo / "scripts" / name).write_text(
                f"#!/usr/bin/env bash\n# {name} v1\n", encoding="utf-8")
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "init")
        _git(self.repo, "push", "-q", "-u", "origin", "main")
        self._write_gh_stub()

    def _write_gh_stub(self) -> None:
        gh = self.bin / "gh"
        gh.write_text(_GH_STUB, encoding="utf-8")
        gh.chmod(0o755)

    # ── 形态构造 ──
    def advance_origin(self, tool: str = "dev-worktree.sh") -> None:
        """origin/main 前进一个提交并改掉指定工具；主工作区 **fetch 过但没合并**（= 实测形态）。"""
        other = self.base / "other"
        _git(self.base, "clone", "-q", str(self.origin), str(other))
        _git(other, "config", "user.email", "fixture@example.com")
        _git(other, "config", "user.name", "fixture")
        path = other / "scripts" / tool
        path.write_text(path.read_text(encoding="utf-8") + "# v2：新守卫\n", encoding="utf-8")
        _git(other, "add", "-A")
        _git(other, "commit", "-q", "-m", "tool v2")
        _git(other, "push", "-q", "origin", "main")
        _git(self.repo, "fetch", "-q", "origin", "main")

    def add_worktree(self, branch: str, base_ref: str = "main") -> Path:
        path = self.wt_base / branch.split("/", 1)[-1]
        _git(self.repo, "branch", branch, base_ref)
        _git(self.repo, "worktree", "add", "-q", str(path), branch)
        assert str(path) in _worktree_paths(self.repo), f"夹具没造出 worktree：{path}"
        return path

    def blob_sha(self, rev_path: str) -> str:
        """某个 rev 下某路径的 blob sha（前 12 位，与 preflight 的显示口径一致）。"""
        return _git(self.repo, "rev-parse", rev_path).stdout.strip()[:12]

    # ── 调用 ──
    def env(self) -> dict:
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env["MIGAO_WT_BASE"] = str(self.wt_base)
        env["MIGAO_GH_BIN"] = str(self.bin / "gh")
        for name in ("MIGAO_DEVTREE_BIN", "MIGAO_VERIFY_BIN",
                     "MIGAO_PRESET_REFRESH_BIN", "MIGAO_ANCHOR"):
            env.pop(name, None)
        return env

    def run(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        """走**真入口** `issue-lifecycle.sh`（外壳 + 判定本体一起验）。"""
        return subprocess.run(["bash", str(SCRIPT), *args], cwd=str(cwd or self.repo),
                              capture_output=True, text=True, env=self.env())

    def run_module(self, module: Path, *args: str) -> subprocess.CompletedProcess:
        """直接跑**变异体**判定本体（与 `run` 同一套环境）。"""
        return subprocess.run([sys.executable, str(module), *args], cwd=str(self.repo),
                              capture_output=True, text=True, env=self.env())


def _worktree_paths(cwd: Path) -> set[str]:
    out = _git(cwd, "worktree", "list", "--porcelain").stdout
    return {line.split(" ", 1)[1] for line in out.splitlines() if line.startswith("worktree ")}


def _mutate_src(dest_dir: Path, old: str, new: str) -> Path:
    src = MODULE.read_text(encoding="utf-8")
    assert src.count(old) == 1, f"注入锚点必须恰好命中 1 次（源码漂移 ⇒ 红证失效）：{old!r}"
    mutated = src.replace(old, new)
    assert mutated != src, "变异没落到源码上"
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / "issue_lifecycle.py"
    target.write_text(mutated, encoding="utf-8")
    shutil.copy(GUARD_MODULE, dest_dir / "agent-presets-guard.py")
    compile(mutated, str(target), "exec")
    return target


@pytest.fixture()
def fx(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path)


# ── ①② 实跑读数：落后形态（告警）/ 一致形态（无声）────────────────────────────

def test_stale_main_root_tool_is_reported_loudly(fx: Fixture) -> None:
    """落后形态：主工作区落后 1 个提交且工具内容 ≠ origin/main ⇒ 路径 + sha + 告警 + 解除命令。

    判据从 **worktree 里**发起（实测形态：作者就在自己的 worktree 里跑 `land`），
    并顺带钉住「你 worktree 里那份**不是** `land` 用的那份」这条读数。
    """
    fx.advance_origin("dev-worktree.sh")
    # 分支从 **origin/main** 起（实测形态：包的分支在工具修复**之后**开，所以它自己那份是新的）
    wt = fx.add_worktree(BRANCH, base_ref="origin/main")
    used_before = fx.blob_sha("HEAD:scripts/dev-worktree.sh")
    used_after = fx.blob_sha("origin/main:scripts/dev-worktree.sh")
    assert used_before != used_after, "夹具没造出「主工作区那份 ≠ origin/main 那份」的形态"
    wt_copy = _git(wt, "hash-object", "scripts/dev-worktree.sh").stdout.strip()[:12]
    assert wt_copy == used_after, "夹具没造出「worktree 里那份 == 新那份」的形态"

    proc = fx.run("land", BRANCH, "--dry-run", cwd=wt)

    # 🔴 取舍钉成判据：落后 ⇒ **告警但不阻塞**（fail-closed 会变成新的假阻塞）
    assert proc.returncode == 0, (
        f"落后只是告警、不该阻塞（取舍：见本文件 docstring）：rc={proc.returncode}\n"
        f"{proc.stdout}\n{proc.stderr}")
    bad = provenance_problems(proc.stdout, tool_dir=fx.repo, in_sync=False)
    assert bad == [], "工具来源读数不合格：\n" + "\n".join(f"  - {p}" for p in bad)
    # 实跑读数（现取，不写死）：1 behind + 两个 sha 都要出现在输出里
    assert "落后 origin/main：**1** 个提交" in proc.stdout, proc.stdout
    assert used_before in proc.stdout, f"主工作区那份的 sha 没出现：{used_before}\n{proc.stdout}"
    assert used_after in proc.stdout, f"origin/main 那份的 sha 没出现：{used_after}\n{proc.stdout}"
    assert "你 worktree 里那份" in proc.stdout, (
        "从 worktree 发起时必须点名「你 worktree 里那份与它不同」（这正是白烧三轮的那条读数）\n"
        + proc.stdout)
    assert wt_copy in proc.stdout.split("你 worktree 里那份", 1)[1], (
        f"那条读数必须给出 worktree 那份的 sha（{wt_copy}）：\n{proc.stdout}")
    assert used_before == _git(fx.repo, "hash-object", "scripts/dev-worktree.sh").stdout.strip()[:12]


def test_reproduces_the_original_hole_and_shows_it_at_a_glance(fx: Fixture) -> None:
    """**复现原洞**（#5719 现场）：主工作区那份工具**缺守卫**（rc≠0）、worktree 里那份**有守卫**（rc=0）。

    实测代价 = 作者为此**白烧三轮**（`land` ①步连停 3 次、手动跑同一子命令 rc=0、六个判据全「无漂移」）。
    ⇒ 本判据钉住「**同一屏里就能读出结论**」：①步失败的那段输出**正上方**就是工具来源读数。
    """
    fx.advance_origin("dev-worktree.sh")
    # 主工作区那份（旧）改成「拒绝」= 缺 #5719 的守卫 ⇒ ①步 rc=1（实测形态）
    root_tool = fx.repo / "scripts" / "dev-worktree.sh"
    root_tool.write_text("#!/usr/bin/env bash\necho '❌ 旧副本：没有守卫' >&2\nexit 1\n", encoding="utf-8")
    wt = fx.add_worktree(BRANCH, base_ref="origin/main")

    proc = fx.run("land", BRANCH, cwd=wt)

    # ① 洞真的复现了：①步停下（不为零），且原因是那份**旧的**工具
    assert proc.returncode != 0, f"原洞没复现（①步竟然过了）：\n{proc.stdout}\n{proc.stderr}"
    assert "旧副本：没有守卫" in (proc.stdout + proc.stderr), proc.stdout + proc.stderr
    # ② 现在能**一眼看出**：告警与「用的是主工作区那份」在失败之前的同一屏里
    assert TOOL_MARK in proc.stdout, proc.stdout
    assert "旧工具" in proc.stdout, proc.stdout
    assert str(root_tool) in proc.stdout, proc.stdout
    assert proc.stdout.index(TOOL_MARK) < proc.stdout.index("旧副本：没有守卫"), (
        f"工具来源读数必须出现在 ①步失败**之前**：\n{proc.stdout}")
    # ③ 对照读数：**worktree 里那份**跑同一条子命令 rc=0（正是当年让人误判的那条读数）
    same = subprocess.run(["bash", str(wt / "scripts" / "dev-worktree.sh"), "rebase", BRANCH],
                          cwd=str(fx.repo), capture_output=True, text=True, env=fx.env())
    assert same.returncode == 0, f"对照那条必须成功（否则复现形态不对）：{same.stdout}{same.stderr}"


def test_in_sync_main_root_is_quiet(fx: Fixture) -> None:
    """一致形态（**对照**）：主工作区 == origin/main ⇒ 打印路径与 sha，但**无告警 / 无声**。"""
    fx.add_worktree(BRANCH)
    proc = fx.run("land", BRANCH, "--dry-run")

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    bad = provenance_problems(proc.stdout, tool_dir=fx.repo, in_sync=True)
    assert bad == [], "一致形态的读数不合格：\n" + "\n".join(f"  - {p}" for p in bad)
    assert fx.blob_sha("HEAD:scripts/dev-worktree.sh") in proc.stdout, proc.stdout


def test_missing_tool_file_does_not_break_land(fx: Fixture) -> None:
    """取不到那份工具（路径不存在）⇒ 仍然打印、仍然不阻塞（robustness：读数不是判据）。"""
    (fx.repo / "scripts" / "dev-worktree.sh").unlink()
    fx.add_worktree(BRANCH)

    proc = fx.run("land", BRANCH, "--dry-run")

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert TOOL_MARK in proc.stdout, proc.stdout
    assert "取不到" in proc.stdout, f"取不到 sha 时必须如实说「取不到」，不许静默：\n{proc.stdout}"


def test_every_main_root_derived_tool_is_named(fx: Fixture) -> None:
    """**同类可见性**：`main_root()` 派生的每一条入口都要在读数里点名（逐条给路径）。

    `dev-worktree.sh`（①步 rebase）与 `preset-anchor-refresh.sh`（⑦步 preset-refresh）**同源**
    （`scripts/issue_lifecycle.py` 的两个解析器都取 `root` = 主工作区）⇒ 只打印一处等于漏报另一处。
    """
    fx.add_worktree(BRANCH)
    proc = fx.run("land", BRANCH, "--dry-run")
    block = proc.stdout.split(TOOL_MARK, 1)[-1]
    for name in TOOL_NAMES:
        assert name in block, f"没点名 `{name}`：\n{proc.stdout}"
        assert str(fx.repo / "scripts" / name) in block, f"没给出 `{name}` 的路径：\n{proc.stdout}"


# ── 红证：变异体**真被读到**（实跑），外加「只改注释」对照读数 ────────────────────

def test_preflight_call_deleted_is_red(fx: Fixture) -> None:
    """红证：删掉 preflight 调用（**真跑变异体**，不是改注释）⇒ 判据必红。"""
    fx.advance_origin()
    fx.add_worktree(BRANCH)
    module = _mutate_src(fx.base / "mut-call", PREFLIGHT_CALL,
                         "    # 红证变异：preflight 调用被删\n")

    proc = fx.run_module(module, "land", BRANCH, "--dry-run")

    assert proc.returncode == 0, f"变异体自身要能跑起来（否则红证无效）：\n{proc.stderr}"
    assert provenance_problems(proc.stdout, tool_dir=fx.repo, in_sync=False) != [], (
        "删掉 preflight 调用后判据竟然还是绿的（= 空断言）")


def test_comment_only_change_stays_green(fx: Fixture) -> None:
    """对照读数：**只改注释** ⇒ 判据保持绿（证明上面那条红的不是「随便改点什么都红」）。"""
    fx.advance_origin()
    fx.add_worktree(BRANCH)
    module = _mutate_src(
        fx.base / "mut-comment", PREFLIGHT_CALL,
        "    # 只加一条注释：不动任何读数、不动任何工具来源\n" + PREFLIGHT_CALL)

    proc = fx.run_module(module, "land", BRANCH, "--dry-run")

    assert provenance_problems(proc.stdout, tool_dir=fx.repo, in_sync=False) == [], proc.stdout


def test_dropping_a_tool_from_the_list_is_red(fx: Fixture) -> None:
    """红证：把 `preset-anchor-refresh.sh` 从工具清单里删掉 ⇒ 「逐条点名」那条判据必红。"""
    fx.add_worktree(BRANCH)
    module = _mutate_src(fx.base / "mut-tools", TOOLS_TUPLE_TAIL, "")

    proc = fx.run_module(module, "land", BRANCH, "--dry-run")

    assert "preset-anchor-refresh.sh" not in proc.stdout, proc.stdout
    assert provenance_problems(proc.stdout, tool_dir=fx.repo, in_sync=True) != [], (
        "漏报一条同类入口后判据竟然还是绿的")


def test_the_reading_names_its_own_object(fx: Fixture) -> None:
    """读数必须自报口径（`FM-A5` / `FM-A12`）：对比的是**本地** `origin/main` ref（不联网、不写盘）。"""
    fx.add_worktree(BRANCH)
    proc = fx.run("land", BRANCH, "--dry-run")
    assert re.search(r"口径：.*本地.*origin/main", proc.stdout), proc.stdout
    # 反向：口径行说「本地」就不能同时声称联网核过远端
    assert "ls-remote" not in proc.stdout, proc.stdout


def test_helpers_are_wired_into_the_real_entry(fx: Fixture) -> None:
    """接线判据：真入口（`scripts/issue-lifecycle.sh`）跑出来的读数必须在**动手之前**出现。"""
    fx.add_worktree(BRANCH)
    proc = fx.run("land", BRANCH, "--dry-run")
    assert TOOL_MARK in proc.stdout, f"真入口没打印工具来源：\n{proc.stdout}\n{proc.stderr}"
    assert "🚀 land：" in proc.stdout, proc.stdout
    assert proc.stdout.index(TOOL_MARK) < proc.stdout.index("--dry-run"), (
        f"工具来源读数必须在**干任何事之前**打印（否则①步停了就看不到它）：\n{proc.stdout}")


def test_module_exposes_the_reading_as_a_pure_function() -> None:
    """判据本体必须以**可单测的纯函数**存在（否则红证只能靠整跑 `land`，脆弱且慢）。"""
    spec = importlib.util.spec_from_file_location("il_under_test", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.tool_provenance_lines), "缺少 tool_provenance_lines"
    assert callable(module.print_tool_provenance), "缺少 print_tool_provenance"
    assert isinstance(module.MAIN_ROOT_TOOLS, tuple), "工具清单必须是冻结的 tuple"
    names = [row[0] for row in module.MAIN_ROOT_TOOLS]
    assert names == list(TOOL_NAMES), f"工具清单与判据面不一致：{names}"
