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
7. **变异红证**：把「未提交感知」摘掉（= 旧行为）⇒ 场景 1 立刻变回 ✅ 静默通过（断言不是空断言）；
8. **`report()` 的日志名与 locale 无关 + 纯 CJK 检查名仍唯一**（本文件首轮 CI 红的根因）：
   同一检查项在 C locale 与 UTF-8 locale 下必须是**同一个**路径；「检查项甲」/「检查项乙」
   这类 ASCII 部分为空的检查名必须拿到**不同**路径（否则后跑的覆盖先跑的，现场被销毁）。

⚠️ 本文件自身会被 CI 的 `--check-weak` 扫描（新增测试文件），因此正文不得出现字面弱断言
模式（存在性断言 / 恒真断言 / 空 `pass`），弱断言样本一律**拼接构造**。

## 踩过的坑（本文件首轮 CI 红，2026-09-14）

首轮 CI `ci workflow helper unit tests` = `5 failed, 699 passed`，五条失败同因：日志读成空串。
根因**不是** gate 逻辑，而是本文件**按检查名硬拼日志路径**——`report()` 的 slug 走
`tr -c '[:alnum:]'`，`[:alnum:]` **随 locale 变**（UTF-8 保留中文「预检」/ C locale 压成 `-`）
⇒ 本机与 CI 的文件名不同。现改为：按 **PID 定位**（不复刻命名渲染）+ 子进程显式钉
`LC_ALL=C`（本地跑 ≡ CI 跑）+ 定位不到/多于 1 条/日志为空一律**大声失败**并附控制台原文；
同时脚本侧把 slug 做成 locale 无关并加 `cksum` 兜底唯一性（场景 8 就是它的守卫）。
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

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

# CI 的 locale 是 C（LANG 未设）—— 本守卫**显式钉住**它，让"本地绿"与"CI 绿"是同一件事
# （历史教训：日志名/编码类断言只在某个 locale 下成立 ⇒ 本地绿 / CI 红）。
_C_LOCALE_ENV = {"LC_ALL": "C", "LANG": "C"}

# 备用 UTF-8 locale：用于证明脚本的日志命名**与 locale 无关**（见测试 ⑧）。
_UTF8_CANDIDATES = ("C.UTF-8", "en_US.UTF-8", "zh_CN.UTF-8")


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

    `report()` 把检查项输出重定向进 `/tmp/verify-all-<PID>-<slug>.log`，**成功时只打印
    ✅、不打印路径** ⇒ 这里用 `bash -c 'echo $$; exec bash …'` 让检查脚本与新 bash 同 PID
    （`exec` 不换 PID），再按 **PID 定位**日志 —— 只**定位**，绝不复刻被测脚本的命名渲染：

    ⚠️ 曾经踩过（issue #3724 首轮 CI 红，5 failed「log == ''」）：`report()` 的 slug 走
    `tr -c '[:alnum:]'`，其 `[:alnum:]` **随 locale 变** —— 本机 UTF-8 保留中文「预检」、
    CI（`LC_ALL=C`）把它逐字节压成 `-`，测试按名硬拼路径 ⇒ file-not-found、日志读成空串、
    断言全假失败。**本地绿 / CI 红，且失败信息里什么线索都没有。**

    因此本函数：① 按 PID 定位；② 子进程环境**显式钉 `LC_ALL=C`/`LANG=C`**（本地跑 ≡ CI 跑，
    把那次现场固化成可复现输入）；③ 定位不到就**大声失败**并附控制台原文，不再静默空串。
    """
    import os

    env = dict(os.environ)
    env.update(_GIT_ENV)
    env.update(_C_LOCALE_ENV)  # 本机 ≡ CI：不给 locale 留下"本地恰好能过"的机会
    assert Path("/tmp").is_dir(), "本守卫依赖 /tmp 存放 report() 日志（CI 与 macOS 均有）"
    proc = subprocess.run(
        ["bash", "-c", 'echo "PID=$$"; exec bash verify-all.sh gate'],
        cwd=str(repo), capture_output=True, text=True, env=env, timeout=_RUN_TIMEOUT,
    )
    out = "%s%s" % (proc.stdout, proc.stderr)
    paths = []
    if m := re.search(r"PID=(\d+)", out):
        pid = m.group(1)
        out = out.replace("PID=%s\n" % pid, "")
        paths = sorted(Path("/tmp").glob("verify-all-%s-*.log" % pid))
    if not paths:  # 回退：失败时 `report()` 会把日志路径打进控制台（PID 分支落空也要能兜住）
        paths = [Path(m.group("path")) for m in _LOG_RE.finditer(out)]
    assert paths, (
        "未能定位 gate 检查项的日志文件（PID 通配与「日志: <path>」回退都没命中）——"
        f"断言会退化成没线索的空串。控制台原文：\n{out}"
    )
    assert len(paths) == 1, (
        f"`gate` 档应只产生 1 个检查项日志，实得 {len(paths)}: {paths}\n"
        f"（多于 1 个说明日志定位过宽，取 [0] 会读到别人的现场）控制台原文：\n{out}"
    )
    log = paths[0].read_text(encoding="utf-8", errors="replace")
    paths[0].unlink(missing_ok=True)  # 不留 /tmp 垃圾
    assert log.strip(), f"日志文件为空（{paths[0]}）——检查项没往日志写任何东西？\n{out}"
    return proc.returncode, out, log


# ── ① 未提交 + 工作区有弱断言 ⇒ 必须红且打印 file:line（旧实现此处 ✅ 假绿）──

def test_uncommitted_workspace_weak_assert_is_caught(tmp_path):
    repo = _make_repo(tmp_path)
    name = _write_weak_test(repo)
    rc, out, log = _run_gate(repo)
    assert rc != 0, (
        "工作区未提交的新增测试里有弱断言 ⇒ 必须红（旧实现静默 return 0 = 假绿）：\n" + out
    )
    assert name in log, f"必须打印命中的文件（控制台：\n{out}）：\n{log}"
    assert "L3:" in log, f"必须打印行号（file:line 才算可行动；控制台：\n{out}）：\n{log}"


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
    assert "未提交" in log and "commit" in log, f"日志里同样要留证（控制台：\n{out}）：\n{log}"


def test_uncommitted_state_is_distinguishable_from_no_change(tmp_path):
    """「没提交」与「没有变更」的输出必须不同（同一句话 = 不可区分 = 本缺陷根因）。"""
    dirty = _make_repo(tmp_path / "dirty")
    (dirty / "README.md").write_text("baseline\ndirty edit\n", encoding="utf-8")
    _, dirty_out, _ = _run_gate(dirty)

    clean = _make_repo(tmp_path / "clean")
    clean_rc, clean_out, clean_log = _run_gate(clean)

    assert clean_rc == 0, f"真的没有变更时应保持「跳过」并通过（合法空跑）：\n{clean_out}\n{clean_log}"
    assert _SILENT_SKIP in clean_log, f"无变更时保留原提示（合法空跑）；控制台：\n{clean_out}\n{clean_log}"
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
    assert name in log, f"扫描集必须含该新增测试文件（控制台：\n{out}）：\n{log}"
    assert "1 处弱断言" in log, f"必须真的扫出弱断言（不是空跑）；控制台：\n{out}\n{log}"


# ── ④ 已 commit 后又新增未提交测试 ⇒ 仍要扫到（「提交前跑」也必须真的有效）──

def test_uncommitted_new_test_scanned_after_a_commit(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "README.md").write_text("baseline\ncommitted change\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "a committed change")
    name = _write_weak_test(repo)  # 仍未提交（CI 尚看不到）
    rc, out, log = _run_gate(repo)
    assert rc != 0, f"工作区未提交的新增弱断言测试也必须让 gate 红：\n{out}\n{log}"
    assert name in log, f"扫描集必须并入工作区未提交的新增测试文件（控制台：\n{out}）：\n{log}"
    assert "1 处弱断言" in log, f"必须真的扫出弱断言；控制台：\n{out}\n{log}"


# ── ⑤ 不误伤：无未提交改动时行为与修复前一致 ──

def test_no_uncommitted_change_behaviour_unchanged(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "README.md").write_text("baseline\ncommitted change\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "benign change")
    rc, out, log = _run_gate(repo)
    assert rc == 0, f"无未提交改动时不得变红（防误伤）：\n{out}\n{log}"
    assert "未提交" not in out, f"无未提交改动时不得出现告警：\n{out}"
    assert _SILENT_SKIP not in log, f"有已提交改动时必须真扫（不许走「跳过」）；控制台：\n{out}\n{log}"


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


# ── ⑧ report() 的日志名：与 locale 无关 + 纯 CJK 检查名仍唯一（本 PR 的根因根治）──

_UTF8_LOCALE = None


def _utf8_locale():
    """本机第一个可用的 UTF-8 locale（无则 None ⇒ 该半段 skip，不假绿也不假红）。"""
    global _UTF8_LOCALE
    if _UTF8_LOCALE is None:
        avail = subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout
        names = set(avail.replace("\n", " ").split())
        _UTF8_LOCALE = next((c for c in _UTF8_CANDIDATES if c in names), "")
    return _UTF8_LOCALE or None


def _report_paths(calls):
    """真跑 verify-all.sh 抽出的 `report()`，返回 (控制台里的日志路径列表, 控制台原文)。

    `calls` = [(locale_env, 检查项名), …]，全部在**同一个 bash 进程**内执行（`$$` 相同）⇒
    两次得到的路径可以直接比较：任何差异只可能来自 slug（日志命名），不会来自 PID。
    这也让"日志名是否随 locale 变化"成为一个**同进程内**可判定的纯事实。
    """
    script = VERIFY_ALL.read_text(encoding="utf-8")
    m = re.search(r"^report\(\) \{[\s\S]*?^\}", script, re.M)
    assert m, "未能从 verify-all.sh 中抽出 report() 函数"
    body = [
        "set -uo pipefail",
        "PASS=0; FAIL=0; declare -a FAILED",
        m.group(0),
    ]
    for locale_env, name in calls:
        prefix = " ".join("%s=%s" % (k, v) for k, v in sorted(locale_env.items()))
        body.append('%s report "%s" false' % (prefix, name))
    body.append("rm -f /tmp/verify-all-$$-*.log")  # 不留 /tmp 垃圾
    env = dict(os.environ)
    env.update(_GIT_ENV)
    r = subprocess.run(
        ["bash", "-c", "\n".join(body)], capture_output=True, text=True, env=env
    )
    out = "%s%s" % (r.stdout, r.stderr)
    return re.findall(r"日志: (\S+)", out), out


def test_report_log_path_is_locale_independent():
    """同一检查项在 C locale 与 UTF-8 locale 下必须得到**同一个**日志路径（同进程比较）。

    红证（改前实测）：`tr -c '[:alnum:]'` 的 `[:alnum:]` 随 locale 变 —— UTF-8 下保留中文
    「预检」、C locale 下逐字节压成 `-` ⇒ 同一句 `report "QA Growth Gate 预检"` 在本机与 CI
    得到**两个不同文件名**，任何按名重建路径的代码/人都会找错文件
    （这正是 issue #3724 首轮 CI 红的根因：5 条断言读成空串）。
    """
    utf8 = _utf8_locale()
    if not utf8:
        pytest.skip("本机无 UTF-8 locale（locale -a 未列出 C.UTF-8/en_US.UTF-8/zh_CN.UTF-8）")
    name = "QA Growth Gate 预检"
    paths, out = _report_paths([
        (_C_LOCALE_ENV, name),
        ({"LC_ALL": utf8, "LANG": utf8}, name),
    ])
    assert len(paths) == 2, f"应得 2 条日志路径，实得 {paths}：\n{out}"
    assert paths[0] == paths[1], (
        f"同一检查项的日志名随 locale 变化（C: {paths[0]} / {utf8}: {paths[1]}）——"
        "按名重建日志路径的代码会在另一个环境里 file-not-found（本地绿 / CI 红）"
    )


def test_report_log_paths_unique_for_pure_cjk_names():
    """纯 CJK 检查名（ASCII 部分为空）在 C locale 下也必须拿到**不同**日志路径。

    红证（改前实测）：钉住 C locale 后 `tr` 把「检查项甲」「检查项乙」都压成空 slug
    ⇒ 两项共用 `/tmp/verify-all-$$-.log`，后跑的覆盖先跑的（失败现场被销毁）。
    """
    paths, out = _report_paths([
        (_C_LOCALE_ENV, "检查项甲"),
        (_C_LOCALE_ENV, "检查项乙"),
    ])
    assert len(paths) == 2, f"应得 2 条日志路径，实得 {paths}：\n{out}"
    assert paths[0] != paths[1], (
        f"两个纯 CJK 检查名得到同一日志路径 {paths[0]!r} —— 唯一性丢失（cksum 兜底缺失？）"
    )
