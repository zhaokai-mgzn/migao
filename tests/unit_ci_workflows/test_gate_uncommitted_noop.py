# case_ids: MC-012
"""`./verify-all.sh gate` 在「改动未提交」时**不得静默空跑通过**（issue #3724，L0 零 LLM）。

## 缺陷（2026-09-14 实证，非推断）

`gate_check()` 的扫描源是 `git diff … origin/main...HEAD` —— **只含已提交内容**。改动还没
`commit` 时 `HEAD == origin/main` ⇒ 集合恒为空 ⇒ 旧实现打印「无变更…跳过」+ `return 0`
⇒ **✅ 假绿**（形态属 `migao-acceptance` v1.3「空跑」：**绿了但没跑**）。实证：同一条命令
`git commit` 前 ✅ / `commit` 后 ❌（新增测试里的存在性断言命中 `_WEAK_PATTERNS`），CI 直接红
—— 即「本地绿 / CI 红」。这与 `growth_gate.py` 自身已采纳的 fail-closed 原则冲突：那里明确
写着「扫描失败 ≠ 无变更」，而「**因为没提交**所以扫不到」与「**确实没有新增**」此前
**不可区分**，前者被当成后者。

## 判据（2026-09-14 裁定：失败必须意味着一件真事）

- **扫到问题 ⇒ ❌**（未提交也一样红：工作区新增测试已并入扫描，命中即报 `file:line`）；
- **仅「未提交」⇒ 不 ❌**（`quick` 在第一次 commit 之前跑是正当工作流，只因「没提交」就红是**假红**），
  但必须**在控制台可见地**声明「按已提交 diff 扫描的那部分**未覆盖**未提交改动」——
  否则告警只躺在日志里 = 事实上的静默通过。

## 本守卫锁什么（真跑 `bash verify-all.sh gate`，不是文本 grep）

在 `tmp_path` 里造最小 git 仓库（真实 `verify-all.sh` + 真实 `growth_gate.py` + 桩规则源/覆盖体检），
`refs/remotes/origin/main` 指向基线提交：

1. **未提交 + 工作区有弱断言测试** ⇒ ❌，且打印 `file:line`（旧实现此处 ✅ 静默通过）；
2. **未提交 + 工作区无弱断言** ⇒ **不得 ❌**，但控制台必须出现「未提交…未覆盖」告警（两向证据）；
3. **已提交**同一份弱断言测试 ⇒ 真扫、真红（`--check-weak` 输出在日志里）；
4. **已 commit 后又新增未提交测试**（CI 尚看不到）⇒ 扫描集必须并入 ⇒ 仍真红；
5. **没有未提交改动**时行为与修复前一致（正常通过、无「未提交」提示）—— 防误伤；
6. **真的没有变更**（干净工作区 + HEAD == origin/main）仍按原样「跳过」并**不打**告警；
7. **变异红证**：把「未提交感知」摘掉（= 旧行为）⇒ 场景 1 立刻变回 ✅ 静默通过（断言不是空断言）。

⚠️ 本文件自身会被 CI 的 `--check-weak` 扫描（新增测试文件），因此正文不得出现字面弱断言
模式（存在性断言 / 恒真断言 / 空 `pass`），弱断言样本一律**拼接构造**。
"""
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
VERIFY_ALL = REPO_ROOT / "verify-all.sh"
GROWTH_GATE = REPO_ROOT / ".github" / "growth_gate.py"
YAML_LIGHT = REPO_ROOT / ".github" / "yaml_light.py"

# 弱断言样本（拼接构造，避免本文件自己被判弱断言）
_WEAK_LINE = "    assert result is " + "not None\n"

_LOG_RE = re.compile(r"日志: (?P<path>\S+)")
# 修复前的「静默空跑」提示原文（用整句匹配：growth_gate 的 md 里也有「未识别，跳过」字样）
_SILENT_SKIP = "无变更或无法对比 origin/main，跳过"
_RUN_TIMEOUT = 180

_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "ci-guard",
    "GIT_AUTHOR_EMAIL": "ci-guard@example.invalid",
    "GIT_COMMITTER_NAME": "ci-guard",
    "GIT_COMMITTER_EMAIL": "ci-guard@example.invalid",
}


def _git(repo, *args):
    import os

    env = dict(os.environ)
    env.update(_GIT_ENV)
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, env=env, check=True
    )


def _make_repo(tmp_path) -> Path:
    """最小 git 仓库：真实的 verify-all.sh / growth_gate.py + 桩规则源与覆盖体检脚本。"""
    repo = tmp_path / "repo"
    (repo / ".github" / "cases").mkdir(parents=True)
    (repo / "scripts").mkdir()
    shutil.copy(VERIFY_ALL, repo / "verify-all.sh")
    shutil.copy(GROWTH_GATE, repo / ".github" / "growth_gate.py")
    shutil.copy(YAML_LIGHT, repo / ".github" / "yaml_light.py")
    # 桩规则源：无模块规则（本守卫只关心「空集是否静默放行」，不测缺测分类）
    (repo / ".github" / "tech-stack.yml").write_text("modules: []\ntest_commands: {}\n")
    (repo / ".github" / "qa-exemptions.yml").write_text("exemptions: []\n")
    # 桩覆盖体检：`--check` 恒通过（判据在 scripts/*_coverage.py，与本缺陷无关）
    for persona in ("xiaobu", "mibao"):
        (repo / "scripts" / f"{persona}_coverage.py").write_text(
            "import sys\nsys.exit(0)\n", encoding="utf-8"
        )
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "baseline")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    # origin/main 指向基线 ⇒ 未提交时 `origin/main...HEAD` 为空（复现缺陷现场）
    _git(repo, "update-ref", "refs/remotes/origin/main", base)
    return repo


def _write_weak_test(repo, name="tests/test_weak_sample.py"):
    """写入一份含弱断言的**新增**测试文件（匹配 gate 的 `.py` + test/spec 过滤）。"""
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "def test_sample():\n    result = {'ok': True}\n" + _WEAK_LINE, encoding="utf-8"
    )
    return name


def _run_gate(repo):
    """真跑 `bash verify-all.sh gate`，返回 (退出码, 控制台输出, 检查项日志原文)。

    `report()` 把检查项输出重定向进 `/tmp/verify-all-<PID>-<检查名>.log`，**成功时只打印
    ✅、不打印路径** ⇒ 这里用 `bash -c 'echo $$; exec bash …'` 让检查脚本与新 bash 同 PID
    （`exec` 不换 PID），再按 **PID 通配**取日志。

    ⚠️ 不能按「检查名」拼路径：`report()` 的 slug 走 `tr -c '[:alnum:]'`，其结果**依赖
    locale** —— 本机（UTF-8）保留中文「预检」，CI（LC_ALL=C）把它压成 `-`。按名拼路径在
    CI 上会 file-not-found ⇒ 日志读成空串、断言全部假失败（**本 PR 首轮 CI 就是这么红的**）。
    """
    import os

    env = dict(os.environ)
    env.update(_GIT_ENV)
    proc = subprocess.run(
        ["bash", "-c", 'echo "PID=$$"; exec bash verify-all.sh gate'],
        cwd=str(repo), capture_output=True, text=True, env=env, timeout=_RUN_TIMEOUT,
    )
    out = "%s%s" % (proc.stdout, proc.stderr)
    if m := re.search(r"PID=(\d+)", out):
        pid = m.group(1)
        out = out.replace("PID=%s\n" % pid, "")
        paths = sorted(Path("/tmp").glob("verify-all-%s-*.log" % pid))
    elif m := _LOG_RE.search(out):  # 兜底：失败时 `report` 会把日志路径打进控制台
        paths = [Path(m.group("path"))]
    else:
        paths = []
    parts = []
    for p in paths:
        if p.exists():
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
            p.unlink(missing_ok=True)  # 不留 /tmp 垃圾
    return proc.returncode, out, "\n".join(parts)


# ── ① 未提交 + 工作区有弱断言 ⇒ 必须红且打印 file:line（旧实现此处 ✅ 假绿）──

def test_uncommitted_workspace_weak_assert_is_caught(tmp_path):
    repo = _make_repo(tmp_path)
    name = _write_weak_test(repo)
    rc, out, log = _run_gate(repo)
    assert rc != 0, (
        "工作区未提交的新增测试里有弱断言 ⇒ 必须红（旧实现静默 return 0 = 假绿）：\n" + out
    )
    assert name in log, f"必须打印命中的文件：\n{log}"
    assert "L3:" in log, f"必须打印行号（file:line 才算可行动）：\n{log}"


# ── ② 未提交 + 工作区无弱断言 ⇒ 不得红，但告警必须在控制台可见 ──

def test_uncommitted_without_findings_warns_visibly_but_does_not_fail(tmp_path):
    """仅「未提交」不构成失败（否则是假红）；但未覆盖范围必须**看得见**地声明。"""
    repo = _make_repo(tmp_path)
    (repo / "README.md").write_text("baseline\ndirty edit\n", encoding="utf-8")  # 有未提交改动，无新增测试
    rc, out, log = _run_gate(repo)
    assert rc == 0, (
        "「未提交」本身不得让 gate 失败（quick 在第一次 commit 前跑是正当工作流，红即假红）：\n"
        + out
    )
    assert "未提交" in out, (
        "告警必须出现在**控制台**（只躺在日志里 = 事实上的静默通过）：\n" + out
    )
    assert "未覆盖" in out and "commit" in out, f"必须点名未覆盖范围 + 给处置：\n{out}"
    assert "未提交" in log and "commit" in log, f"日志里同样要留证：\n{log}"


def test_uncommitted_state_is_distinguishable_from_no_change(tmp_path):
    """「没提交」与「没有变更」的输出必须不同（同一句话 = 不可区分 = 本缺陷根因）。"""
    dirty = _make_repo(tmp_path / "dirty")
    (dirty / "README.md").write_text("baseline\ndirty edit\n", encoding="utf-8")
    _, dirty_out, _ = _run_gate(dirty)

    clean = _make_repo(tmp_path / "clean")
    clean_rc, clean_out, clean_log = _run_gate(clean)

    assert clean_rc == 0, f"真的没有变更时应保持「跳过」并通过（合法空跑）：\n{clean_log}"
    assert _SILENT_SKIP in clean_log, f"无变更时保留原提示（合法空跑）：\n{clean_log}"
    assert "未提交" not in clean_out, f"无未提交改动时不得冒出告警（防误伤）：\n{clean_out}"
    assert "未提交" in dirty_out, (
        "两种状态的输出必须可区分（这正是 issue #3724 要消除的「不可区分」）"
    )


# ── ③ 已提交 ⇒ 真扫（对照：同一份文件 commit 后确实会被扫到）──

def test_committed_weak_test_is_really_scanned(tmp_path):
    repo = _make_repo(tmp_path)
    name = _write_weak_test(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add weak test")
    rc, out, log = _run_gate(repo)
    assert rc != 0, f"已提交的弱断言测试必须让 gate 非零退出：\n{out}\n{log}"
    assert name in log, f"扫描集必须含该新增测试文件：\n{log}"
    assert "1 处弱断言" in log, f"必须真的扫出弱断言（不是空跑）：\n{log}"


# ── ④ 已 commit 后又新增未提交测试 ⇒ 仍要扫到（「提交前跑」也必须真的有效）──

def test_uncommitted_new_test_scanned_after_a_commit(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "README.md").write_text("baseline\ncommitted change\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "a committed change")
    name = _write_weak_test(repo)  # 仍未提交（CI 尚看不到）
    rc, out, log = _run_gate(repo)
    assert rc != 0, f"工作区未提交的新增弱断言测试也必须让 gate 红：\n{out}\n{log}"
    assert name in log, f"扫描集必须并入工作区未提交的新增测试文件：\n{log}"
    assert "1 处弱断言" in log, f"必须真的扫出弱断言：\n{log}"


# ── ⑤ 不误伤：无未提交改动时行为与修复前一致 ──

def test_no_uncommitted_change_behaviour_unchanged(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "README.md").write_text("baseline\ncommitted change\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "benign change")
    rc, out, log = _run_gate(repo)
    assert rc == 0, f"无未提交改动时不得变红（防误伤）：\n{out}\n{log}"
    assert "未提交" not in out, f"无未提交改动时不得出现告警：\n{out}"
    assert _SILENT_SKIP not in log, f"有已提交改动时必须真扫（不许走「跳过」）：\n{log}"


# ── ⑥ 变异红证：旧行为（对「没提交」无感知）必须复现静默通过 ──

def test_old_behaviour_mutation_reproduces_silent_pass(tmp_path):
    """把修复点退化掉（未提交感知失效）⇒ 场景①立刻变回 ✅ 静默通过（守卫会红）。

    注入式红证：变异施加在**临时仓库的副本**上，与仓库自身真值解耦 ——
    证明场景①的断言不是空断言（不会红的断言 = 空断言）。
    """
    repo = _make_repo(tmp_path)
    script = repo / "verify-all.sh"
    text = script.read_text(encoding="utf-8")
    # 变异：把「未提交感知」摘掉 = 旧实现（对工作区状态无感知）
    mutated, hits = re.subn(
        r'UNCOMMITTED=\$\(git status --porcelain[^)]*\)', 'UNCOMMITTED=""', text
    )
    assert hits == 1, f"变异点丢失（命中 {hits} 处）：gate_check 的未提交感知被改名/改写了？"
    script.write_text(mutated, encoding="utf-8")
    # 变异**不提交**（提交会产生已提交 diff，就走不到早退分支，不等价于旧行为）
    _write_weak_test(repo)
    rc, out, log = _run_gate(repo)
    assert rc == 0, (
        "变异（旧行为）本应静默通过 —— 若这里已经非零，说明本守卫的场景①并非由"
        f"「未提交感知」决定（断言可能空转）：\n{out}\n{log}"
    )
    assert _SILENT_SKIP in log, f"旧行为应打印「跳过」并放行：\n{log}"
