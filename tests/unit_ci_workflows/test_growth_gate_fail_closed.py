"""
QA Growth Gate fail-closed 守卫（issue #3631）。

growth_gate.py 的 --check-weak 分支在「读文件失败/路径不存在/解析异常」时曾静默
返回「0 处弱断言」并 exit 0（fail-open 假绿）——路径不可读 ≠ 无弱断言，
「断言空转」「扫描器空转」同一家族。本测试锁定修复后的语义：

- 路径不存在 / 传入目录 / 坏 UTF-8 → 必须报错并 exit 非零（fail-closed）；
- 文件存在且真无弱断言 → 保持 0 处 + exit 0（正常语义不回退）；
- 真弱断言 → 仍检出并 exit 1（检测能力不回退）；
- get_changed_files：git diff 失败 → 返回 None（fail-closed，扫描空转 ≠ 无变更）。

⚠️ 本文件自身会被 CI 的 --check-weak 扫描（新增测试文件），因此正文不得出现
字面弱断言模式（is not None 等存在性断言/恒真断言/空 pass），弱断言样本一律
拼接构造。
"""
# case_ids: MC-012
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
GATE_PY = REPO_ROOT / ".github" / "growth_gate.py"


def _load_gate():
    """从 .github/growth_gate.py 加载被测模块（零依赖，importlib 文件加载）。"""
    spec = importlib.util.spec_from_file_location("growth_gate_under_test", GATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_check_weak(gate, *paths):
    """调 growth_gate.main() 的 --check-weak 分支，返回退出码。"""
    return gate.main(["--check-weak", "--files", *paths])


# ── ① fail-closed：扫描失败必须非零，绝不允许「0 处弱断言」假绿 ──

def test_missing_file_fails_closed(tmp_path, capsys):
    """路径不存在 → exit 非零，且不得打印误导性的「0 处弱断言」。"""
    gate = _load_gate()
    missing = tmp_path / "does_not_exist.py"
    rc = _run_check_weak(gate, str(missing))
    out, err = capsys.readouterr()
    assert rc != 0, "路径不存在必须 exit 非零（fail-closed）"
    assert "0 处弱断言" not in out, "不得打印「0 处弱断言」假绿"
    assert "::error::" in err or "❌" in err, "必须输出明确错误"


def test_directory_fails_closed(tmp_path, capsys):
    """传入目录（IsADirectoryError）→ exit 非零，同样不许假绿。"""
    gate = _load_gate()
    rc = _run_check_weak(gate, str(tmp_path))
    out, _ = capsys.readouterr()
    assert rc != 0, "目录路径必须 exit 非零（fail-closed）"
    assert "0 处弱断言" not in out


def test_bad_utf8_fails_closed(tmp_path, capsys):
    """存在但编码异常的样本 → exit 非零（干净报错，不是裸 traceback）。"""
    gate = _load_gate()
    bad = tmp_path / "bad_utf8_test.py"
    bad.write_bytes(b"\xff\xfe\x00 bad utf8 \xff")
    rc = _run_check_weak(gate, str(bad))
    assert rc != 0, "编码异常必须 exit 非零（fail-closed）"
    out, err = capsys.readouterr()
    assert "Traceback" not in err, "应给干净报错而非裸 traceback"


# ── ② 正常语义不回退 ──

def test_clean_file_zero_and_exit_zero(tmp_path, capsys):
    """文件存在且真无弱断言 → 0 处 + exit 0（正常语义保留）。"""
    gate = _load_gate()
    f = tmp_path / "clean_test.py"
    f.write_text("def test_x():\n    assert result == 3\n")
    rc = _run_check_weak(gate, str(f))
    out, _ = capsys.readouterr()
    assert rc == 0, "真无弱断言必须 exit 0"
    assert "0 处弱断言" in out


def test_weak_assert_still_detected(tmp_path, capsys):
    """真弱断言仍检出并 exit 1（检测能力不回退）。样本拼接构造，避免本文件被扫。"""
    gate = _load_gate()
    weak_line = "assert x is " + "not None"
    f = tmp_path / "weak_test.py"
    f.write_text("def test_x():\n    " + weak_line + "\n")
    rc = _run_check_weak(gate, str(f))
    out, _ = capsys.readouterr()
    assert rc == 1, "真弱断言必须 exit 1"
    assert "1 处弱断言" in out


# ── ③ 真实 CLI 契约（sys.exit(main()) 端到端）──

def test_cli_subprocess_missing_file_nonzero(tmp_path):
    """真实 CLI：--check-weak 指向不存在路径必须非零退出。"""
    missing = tmp_path / "nope.py"
    r = subprocess.run(
        [sys.executable, str(GATE_PY), "--check-weak", "--files", str(missing)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert r.returncode != 0, "真实 CLI 路径不存在必须非零退出（fail-closed）"
    assert "0 处弱断言" not in r.stdout


# ── ④ 同类 fail-open：get_changed_files 扫描空转 ──

def test_get_changed_files_fail_closed(monkeypatch):
    """git diff 失败 → 返回 None（fail-closed），不允许返回空清单当「无变更」放行。"""
    gate = _load_gate()

    def boom(*a, **k):
        raise RuntimeError("git unavailable")

    monkeypatch.setattr(gate.subprocess, "run", boom)
    assert gate.get_changed_files("origin/main") is None


def test_main_base_mode_fails_closed_on_git_error(monkeypatch):
    """--base 模式 git diff 失败 → main() 非零退出（fail-closed）。"""
    gate = _load_gate()

    def boom(*a, **k):
        raise RuntimeError("git unavailable")

    monkeypatch.setattr(gate.subprocess, "run", boom)
    rc = gate.main(["--base", "origin/main"])
    assert rc != 0, "扫描失败必须让门禁非零退出（fail-closed）"


# ══════════════════════════════════════════════════════════════════════════════
# ⑤ 弱断言扫描的「测试文件」判定：本地 ≡ CI（issue #4077）
#
# 缺陷（2026-09-17 实证，非推断）：`verify-all.sh gate` 的弱断言扫描集是
# 「`git diff --diff-filter=A origin/main...HEAD` 的**全部**新增文件 ∪ 工作区新增文件」——
# **已提交那一臂没有 `test|spec` 过滤**，而 `pr-check.yml` 的同一 step 有。后果：新增**源文件**
# （现场：`app/services/greeting.py`，正文一条 `assert result is <not None>` 形状的防御式断言）
# 被当测试文件扫 ⇒ 本地报 1 处弱断言、gate ❌，CI 那步扫 0 个文件、✅ —— **假红**。
# 同处注释还写着「与 pr-check 的 Check weak asserts step 语义一致」= 注释漂移（读注释的人
# 会以为两地同口径），故本次一并改掉。
#
# 修法：判定收敛到**单一事实源** `growth_gate._is_test_file`（G5 用例追溯与弱断言扫描共用），
# 由 `--check-weak --new-tests-only` 施加 —— 本地脚本不再自己写一份 grep。
#
# 不变量（下面四个场景就是它的可执行形态，**两个方向都要**）：
#   · 假红方向：新增源文件**不得**让本地报红（CI 本来就不报）；
#   · 假绿方向：真弱断言测试**两边都红**（过滤只许缩小扫描集，不许放过真问题）；
#   · 判别性：强断言测试 + 源文件混合 ⇒ 不报；
#   · 变异红证：把 `--new-tests-only` 从本地脚本摘掉（= 旧行为）⇒ 场景 A 立刻变回 ❌（断言非空转）。
#
# 与 CI 的一致性口径（**两处注释写同一段**，见 issue #4077 的裁定）：
#   · 判定**本应相同** —— 都是「这个新增文件是不是测试文件」，唯一实现 `_is_test_file`；
#   · 扫描源**本应不同** —— CI 只可能看到已提交 diff（PR 的改动必然已提交）；本地还要并入
#     **工作区**未提交的新增文件（否则「提交前跑」对该文件是空跑，issue #3724）。
#   ⚠️ 本测试**不复刻** `pr-check.yml` 的 grep，也不读它的文本 —— CI 侧口径在运行期由本文件
#      场景 B 的文本 oracle 代表；把 workflow 文本焊进单测会让 workflow 一改（需 `workflow`
#      scope，本分支 token 无）就红，那是在制造假红而不是防假红。
# ══════════════════════════════════════════════════════════════════════════════

# ── 真跑 `bash verify-all.sh gate` 的最小 harness ──
# 与 `test_gate_uncommitted_noop.py` 同族但**不复用其模块**（那套 harness 要求恰好 1 个检查项
# 日志、还带 locale/report 专项，语义不同，互相牵连只会让两边都脆）。
VERIFY_ALL = REPO_ROOT / "verify-all.sh"
YAML_LIGHT = REPO_ROOT / ".github" / "yaml_light.py"
_RUN_TIMEOUT = 180

_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "ci-guard",
    "GIT_AUTHOR_EMAIL": "ci-guard@example.invalid",
    "GIT_COMMITTER_NAME": "ci-guard",
    "GIT_COMMITTER_EMAIL": "ci-guard@example.invalid",
    # CI 的 locale 是 C（LANG 未设）—— 显式钉住，让「本地绿」与「CI 绿」是同一件事
    "LC_ALL": "C",
    "LANG": "C",
}


def _git(repo, *args):
    env = dict(os.environ)
    env.update(_GIT_ENV)
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, env=env, check=True
    )


def _make_repo(tmp_path) -> Path:
    """最小 git 仓库：真实的 verify-all.sh / growth_gate.py + 桩规则源与覆盖体检。

    `refs/remotes/origin/main` 指向基线提交 ⇒ 之后 `git commit` 的内容都算「本 PR 新增文件」。
    """
    repo = tmp_path / "repo"
    (repo / ".github" / "cases").mkdir(parents=True)
    (repo / "scripts").mkdir()
    # 桩用例：MC-012 —— 临时仓库里也要能解析到该 ID，否则 G5 会独立报「用例不存在」，
    # 让「红是因为弱断言」这条判别力丢失
    (repo / ".github" / "cases" / "misc.yml").write_text(
        "cases:\n  - id: MC-012\n    title: stub\n    tier: normal\n", encoding="utf-8"
    )
    shutil.copy(VERIFY_ALL, repo / "verify-all.sh")
    shutil.copy(GATE_PY, repo / ".github" / "growth_gate.py")
    shutil.copy(YAML_LIGHT, repo / ".github" / "yaml_light.py")
    # 桩规则源：**一条无害规则**（不是空 modules）—— 本文件只关心「哪些文件进入弱断言扫描集」。
    # ⚠️ 2026-09-17 语义更新：growth_gate 现在把「规则源退化」当 **fail-closed**
    # （`modules` 为空 / 正则非法 ⇒ exit 2，见 `.github/growth_gate.py` 的 `rule_errors`
    # 与 `not rules` 分支）—— 旧桩图省事写的 `modules: []` 如今**本身就意味着
    # 「整条缺测门禁失效」**，会把本 harness 的每个场景都额外打红（红因变成「规则源退化」
    # 而不是「弱断言扫描集」⇒ 判别力丢失）。故换成一条真规则：它匹配不到本 harness 改动的
    # 任何文件（新增源文件 / 新增测试文件）⇒ 分类结果与旧桩逐字一致（unmatched）。
    (repo / ".github" / "tech-stack.yml").write_text(
        "modules:\n"
        "  - service: stub\n"
        "    language: python\n"
        "    patterns:\n"
        "      - pattern: 'stub/(.+)\\.py'\n"
        "        tests: ['tests/test_{1}.py']\n"
        "test_commands: {}\n",
        encoding="utf-8",
    )
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
    _git(repo, "update-ref", "refs/remotes/origin/main", base)
    return repo


def _run_gate(repo):
    """真跑 `bash verify-all.sh gate`，返回 (退出码, 控制台原文, 检查项日志原文)。

    `report()` 把检查项输出重定向进 `/tmp/verify-all-<PID>-<slug>.log`、**成功时只打印 ✅**，
    故用 `bash -c 'echo $$; exec bash …'` 让检查脚本与新 bash 同 PID（`exec` 不换 PID），
    再按 **PID 定位**日志 —— 只定位，绝不复刻 slug 的命名渲染（它曾在 locale 上踩过坑）。
    """
    env = dict(os.environ)
    env.update(_GIT_ENV)
    assert Path("/tmp").is_dir(), "本守卫依赖 /tmp 存放 report() 日志（CI 与 macOS 均有）"
    proc = subprocess.run(
        ["bash", "-c", 'echo "PID=$$"; exec bash verify-all.sh gate'],
        cwd=str(repo), capture_output=True, text=True, env=env, timeout=_RUN_TIMEOUT,
    )
    out = "%s%s" % (proc.stdout, proc.stderr)
    paths = []
    if m := re.search(r"PID=(\d+)", out):
        pid = m.group(1)
        paths = sorted(Path("/tmp").glob("verify-all-%s-*.log" % pid))
    assert paths, f"未能按 PID 定位 gate 检查项日志（断言会退化成没线索的空串）：\n{out}"
    log = paths[0].read_text(encoding="utf-8", errors="replace")
    for p in paths:
        p.unlink(missing_ok=True)  # 不留 /tmp 垃圾
    assert log.strip(), f"日志文件为空（{paths[0]}）——检查项没往日志写任何东西？\n{out}"
    return proc.returncode, out, log


# 弱断言样本一律**拼接构造**（本文件自身也是「新增测试文件」，会被 `--check-weak` 扫）
_WEAK_LINE = "    assert result is " + "not None\n"
# CI 那条 step 的过滤（pr-check.yml 的 `grep -E '\.(py|java|ts|tsx)$' | grep -iE 'test|spec'`）
# 的净化形态：只回答「CI 会不会把这个文件交给扫描器」——**故意不复刻 CI 的全文**。
_CI_CODE_EXT = re.compile(r"\.(py|java|ts|tsx)$", re.I)
_CI_TEST_NAME = re.compile(r"test|spec", re.I)

# 扫描器输出里「**真的扫过某个文件**」的唯一形态（`📄 <path>: N 处弱断言`）。
# ⚠️ 不能用「日志里有『弱断言』三个字」当判据 —— 固定表头「扫描新增测试文件的弱断言」
#    也含这三个字，那条断言会恒真（空断言）。
_SCANNED_RE = re.compile(r"📄 .*: \d+ 处弱断言")
_TOTAL_RE = re.compile(r"合计 \d+ 个测试文件，(\d+) 处弱断言")


# 临时仓库里的新增测试文件统一带上 case_ids 声明：G5 用例追溯是 gate 的**另一条**判据，
# 不声明会独立触发 ❌ ⇒ 本文件就分不清「红是因为弱断言」还是「红是因为没声明 case_ids」
# （断言失去判别力）。MC-012 是 `.github/cases/misc.yml` 里 CI 守卫类用例的既有关联 ID。
_CASE_IDS_HEADER = "# case_ids: MC-012\n"


def _write_new_source_file(repo, name="app/services/greeting.py"):
    """新增**源文件**：正文恰好含一条与弱断言同形的防御式断言。

    它**不是**测试文件 ⇒ 两地都不该扫它。CI 现场（改前）：这一步扫 0 个文件、✅。
    """
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def greet(name):\n    result = {'name': name}\n" + _WEAK_LINE +
                    "    return 'hi ' + name\n", encoding="utf-8")
    return name


# ── A 假红方向：新增源文件不得被当测试文件扫（改前：本地 ❌ / CI ✅）──

def _write_weak_test(repo, name="tests/test_weak_sample.py"):
    """新增**测试文件**：头部声明 case_ids（让 G5 那条判据不干扰），正文一条弱断言。"""
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _CASE_IDS_HEADER
        + "def test_sample():\n    result = {'ok': True}\n" + _WEAK_LINE,
        encoding="utf-8",
    )
    return name


def test_new_source_file_is_not_scanned_for_weak_asserts(tmp_path):
    """一个只新增源文件的 commit：`verify-all.sh gate` 必须 ✅（改前 ❌ 假红）。

    红证（改前实测）：同一 commit 下本地打印
    `📄 app/services/greeting.py: 1 处弱断言` + `合计 1 个测试文件` ⇒ gate ❌ / exit 1；
    而 CI 的同一 step 扫 0 个文件 ⇒ ✅。这是**假红**：报的是 CI 不会报的红。
    """
    repo = _make_repo(tmp_path)
    src = _write_new_source_file(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add a new source file")
    rc, out, log = _run_gate(repo)
    assert rc == 0, f"只新增源文件不得让 gate 红（改前此处 ❌ 假红）：\n{out}\n{log}"
    assert not _SCANNED_RE.search(log), (
        f"该 commit 里没有任何新增测试文件 ⇒ 不该扫过任何文件（📄…处弱断言）；日志：\n{log}"
    )
    assert src in log, (
        "过滤必须**可见**（否则「没扫」与「没跑」又不可区分）：日志里应留下被剔除的候选文件：\n"
        f"{log}"
    )


# ── B 假绿方向：真弱断言测试两边都红 ──

def test_real_weak_assert_caught_by_both_local_and_ci(tmp_path):
    """真弱断言**测试文件**：本地 ❌（真扫）∧ CI 口径的扫描集**必须**包含它（证明非漏判）。

    两向断言：本地这一半证「过滤没放宽到放过真问题」，CI 这一半证「本单不是靠缩小
    CI 的扫描集来达成一致」—— 若哪天有人把过滤写成 `test`-only 的变体（例如把 `spec`
    或某个扩展名漏掉），第二半立刻红。
    """
    repo = _make_repo(tmp_path)
    src = _write_new_source_file(repo)
    entry = _write_weak_test(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add a weak test among source files")
    rc, out, log = _run_gate(repo)
    assert rc != 0, f"真弱断言测试必须让本地 gate 红（过滤不得漏掉真问题）：\n{out}\n{log}"
    assert entry in log, f"命中的测试文件必须出现在日志里：\n{log}"
    assert f"📄 {src}:" not in log, f"同一 commit 里的源文件不得被扫：\n{log}"
    assert _TOTAL_RE.search(log) and _TOTAL_RE.search(log).group(1) == "1", (
        f"必须真的扫出那 1 处（不是空跑）：\n{log}"
    )
    # G5 的缺声明 blocker 都以此结尾（gate 抬头也含「case_ids」字样，故不按裸词判）
    assert "16-case-contract.md" not in log, (
        f"红必须来自弱断言本身——测试文件已声明 case_ids，G5 不该再插一脚：\n{log}"
    )

    added = _git(repo, "diff", "--diff-filter=A", "--name-only", "origin/main...HEAD").stdout
    candidates = [f for f in added.split("\n") if f.strip()]
    ci_scan = [f for f in candidates
               if _CI_CODE_EXT.search(f) and _CI_TEST_NAME.search(f)]
    assert entry in ci_scan, (
        "CI 口径必须把这个新增测试文件交给扫描器 —— 否则本地那一半红就是靠"
        f"「两边都漏扫」换来的（假绿）：{ci_scan}"
    )
    assert src not in ci_scan, (
        f"CI 口径本就不扫源文件（这正是本地假红的对照组）：{ci_scan}"
    )


# ── C 判别性：强断言测试 + 源文件混合 ⇒ 不报 ──

def test_strong_assert_test_file_shared_predicate(tmp_path):
    """**锐化过的**断言（值/集合/异常/抛错） + 源文件混合 ⇒ 两边都不报。

    这是 **R2 负例**：证明本单没有变成「见 assert 就报」的过宽门禁 —— 不可满足的断言
    （永远红）与永远不报的门禁同属「基于错误真相模型写出的护栏」。
    """
    repo = _make_repo(tmp_path)
    src = _write_new_source_file(repo)
    strong = repo / "tests" / "test_greeting_strong.py"
    strong.parent.mkdir(parents=True, exist_ok=True)
    strong.write_text(
        _CASE_IDS_HEADER
        + "import pytest\n"
        "from app.services.greeting import greet\n"
        "\n"
        "def test_value_and_set_and_exception():\n"
        "    assert greet('a') == 'hi a'\n"
        "    assert greet('b') in {'hi b', 'hello b'}\n"
        "    assert len(greet('c')) > 0\n"
        "    with pytest.raises(KeyError):\n"
        "        raise KeyError('boom')\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add a strong test among source files")
    rc, out, log = _run_gate(repo)
    assert rc == 0, f"强断言测试 + 源文件不该报红（负例）：\n{out}\n{log}"
    scanned = _SCANNED_RE.findall(log)
    assert len(scanned) == 1, (
        f"强断言文件必须被**真扫过**（否则这一半是空跑：没扫过 ≠ 扫了 0 处）；日志：\n{log}"
    )
    assert f"📄 {strong.relative_to(repo)}: 0 处弱断言" in log, (
        f"强断言测试文件必须进入扫描集且得 0 处：\n{log}"
    )
    assert f"📄 {src}:" not in log, f"源文件仍在候选里但必须被剔除：\n{log}"


# ── D 变异红证：摘掉 `--new-tests-only`（= 旧行为）⇒ 场景 A 变回 ❌ ──

def test_mutation_without_new_tests_only_reproduces_false_red(tmp_path):
    """把过滤摘掉 ⇒ 只新增源文件的 commit 又变 ❌（#4077 现场复现，证明场景 A 非空断言）。

    变异施加在**临时仓库的副本**上（与仓库自身真值解耦）：
    `verify-all.sh` 调 gate 时删掉 `--new-tests-only` —— 这正是改前的行为。

    ⚠️ 这同时锁住**本地脚本真的把该标志传下去了**：未来有人重构掉这个参数，
    本测试会红（而不是静默回到「本地没有过滤」的旧形态）。
    """
    repo = _make_repo(tmp_path)
    script = repo / "verify-all.sh"
    text = script.read_text(encoding="utf-8")
    mutated, hits = re.subn(r"--check-weak --new-tests-only ", "--check-weak ", text)
    assert hits == 1, (
        f"变异点丢失（命中 {hits} 处）：本地脚本没在弱断言扫描上施加共享判定"
        "（`--check-weak --new-tests-only`）？"
    )
    script.write_text(mutated, encoding="utf-8")
    src = _write_new_source_file(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add a new source file")
    rc, out, log = _run_gate(repo)
    assert rc != 0, (
        "旧行为（无过滤）本应把新增源文件当测试文件扫 ⇒ ❌；这里没红说明场景 A 的"
        f"结论不是由过滤决定的（断言空转）：\n{out}\n{log}"
    )
    assert f"📄 {src}: 1 处弱断言" in log, (
        f"旧行为应把源文件当测试文件并报出那处「弱断言」：\n{log}"
    )

# ── ⑥ 规则源退化必须 fail-closed（2026-09-17 收紧）─────────────────────────────
#
# 病根（实测，非推断）：`compile_rules` 用裸 `continue` 静默丢弃「空 pattern / 非法正则」，
# 而 `main()` 对「rules 为空」只打 `::warning::`。两条合起来是一条**现实的、不用改代码就能
# 关掉整条缺测门禁的路**：编辑 `.github/tech-stack.yml` **本身不需要任何测试**
# （该路径 unmatched ⇒ 既非 block 也非 warn），把 `modules:` 清空后每个变更文件都落进
# `classify_file` 的 `unmatched` 分支 —— 而 `unmatched` 既不是 blocker 也不是 warning
# ⇒ `blocker_count = 0` ⇒ CI 的 `Fail on blocking violations` 不触发、`verify-all.sh gate` 打 ✅。
# 2026-09-17 实测原文：真源码文件显示「ℹ️ 未识别，跳过」+「## ✅ 全部通过」+ exit 0。

_EMPTY_MODULES = "modules: []\ntest_commands: {}\n"

# 第一条 pattern 的括号未闭合（re.error）；第二条合法 —— 收紧前前者被静默丢弃
# ⇒ `builder.py` 落进 unmatched ⇒ ✅ 放行。
_BAD_REGEX_MODULES = (
    "modules:\n"
    "  - service: stub\n"
    "    language: python\n"
    "    patterns:\n"
    "      - pattern: 'app/(.+\\.py'\n"
    "        tests: ['tests/test_{1}.py']\n"
    "      - pattern: 'app/good/(.+)\\.py'\n"
    "        tests: ['tests/test_{1}.py']\n"
    "test_commands: {}\n"
)

_OK_MODULES = (
    "modules:\n"
    "  - service: stub\n"
    "    language: python\n"
    "    patterns:\n"
    "      - pattern: 'stub/(.+)\\.py'\n"
    "        tests: ['tests/test_{1}.py']\n"
    "test_commands: {}\n"
)

# 一个在磁盘上真实存在、且**不在**任何豁免清单里的文件（用它避免豁免分支先命中而掩盖分类）
_REAL_SOURCE = "backend/ai-agent-service/app/graph/builder.py"


def _tech_stack(tmp_path, body):
    p = tmp_path / "tech-stack.yml"
    p.write_text(body, encoding="utf-8")
    return str(p)


def _run_gate_with_tech_stack(gate, tech_path, *files):
    return gate.main(["--files", *files, "--tech-stack", tech_path, "--repo-root", str(REPO_ROOT)])


def test_compile_rules_reports_discarded_patterns():
    """被丢弃的规则必须**登记**出来（旧实现静默 continue，调用方无从知道规则少了）。"""
    gate = _load_gate()
    errors: list = []
    gate.compile_rules(
        [{"service": "s", "language": "python",
          "patterns": [{"pattern": ""}, {"pattern": "app/(.+"}, {"pattern": "ok/(.+)"}]}],
        {}, errors,
    )
    assert len(errors) == 2, f"空 pattern + 非法正则都必须登记，实得 {errors}"
    assert any("空 pattern" in e for e in errors)
    assert any("正则非法" in e for e in errors)


def test_empty_modules_fails_closed(tmp_path, capsys):
    """`modules: []` ⇒ 非零退出（收紧前 exit 0、blocker 0、显示「✅ 全部通过」）。"""
    gate = _load_gate()
    rc = _run_gate_with_tech_stack(gate, _tech_stack(tmp_path, _EMPTY_MODULES), _REAL_SOURCE)
    out, err = capsys.readouterr()
    assert rc != 0, "规则源为空必须让门禁失败（否则「清空 modules」就是关掉门禁的开关）"
    assert "::error::" in err, f"必须给出明确错误，实得 stderr={err!r}"
    assert "✅ 全部通过" not in out, "不得再打印「全部通过」"


def test_invalid_regex_fails_closed(tmp_path, capsys):
    """有 pattern 编译不过 ⇒ 非零退出（收紧前被静默丢弃 ⇒ 对应文件落入 unmatched ⇒ 放行）。"""
    gate = _load_gate()
    rc = _run_gate_with_tech_stack(gate, _tech_stack(tmp_path, _BAD_REGEX_MODULES), _REAL_SOURCE)
    out, err = capsys.readouterr()
    assert rc != 0, "规则源退化（有规则编译不过）必须让门禁失败"
    assert "正则非法" in err, f"错误里必须点名是哪条 pattern，实得 stderr={err!r}"
    assert "✅ 全部通过" not in out


def test_valid_rules_still_pass(tmp_path, capsys):
    """负例（防误伤）：合法规则源照旧静默通过 —— 收紧不得把正常路径变成假红。"""
    gate = _load_gate()
    rc = _run_gate_with_tech_stack(gate, _tech_stack(tmp_path, _OK_MODULES), "README.md")
    out, _ = capsys.readouterr()
    assert rc == 0, f"合法规则源 + 无规则命中必须 exit 0，实得 {rc}"
    assert "✅ 全部通过" in out


def test_repo_tech_stack_is_not_degenerate():
    """真值不回退：仓库自己的 `.github/tech-stack.yml` 必须产出可执行规则。

    否则收紧后 CI 会直接 exit 2 —— 这条断言让「谁把 modules 清空了」在单测层就可见。
    """
    gate = _load_gate()
    tech, err = gate._load_yaml(str(REPO_ROOT / ".github" / "tech-stack.yml"))
    assert not err, f"tech-stack.yml 读不出来：{err}"
    errors: list = []
    rules = gate.compile_rules(tech.get("modules") or [], tech.get("test_commands") or {}, errors)
    assert not errors, f"tech-stack.yml 有规则编译不过：{errors}"
    assert len(rules) >= 1, "tech-stack.yml 必须至少有一条可执行规则（否则缺测门禁整条失效）"
