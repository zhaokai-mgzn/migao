# case_ids: MC-012
"""`verify-all.sh` quick 档的 ai-agent 选择集必须覆盖**全部顶层测试文件**（issue #3680）。

## 缺陷（2026-09-14 实测，非推断）

quick 档的 ai-agent 选择曾是 glob 白名单：

    pytest tests/unit tests/test_tools_*.py tests/test_graph_*.py tests/test_intent_router.py -q --no-cov

而 full 档是 `pytest tests/ -q --no-cov -n 4`。实测差距：

| 指标 | 实测值 |
|---|---|
| quick 的 ai-agent 选择 | 1103 passed / 13.8s 墙钟 |
| CI 的 ai-agent job | 3723 passed / 20 skipped / 130 deselected / 113s |
| `tests/` 顶层 `*.py` 文件数 | 169 |
| 其中被 quick 三个 glob 匹配 | 42（**127 个即 ~75% 被静默跳过**）|

**静默**是关键：不报错、不提示、退出码 0 —— 「本地 quick 绿」因此完全不构成
「顶层测试文件也绿」的证据。

## 受害者（本缺陷制造的第一例红 CI）

PR #3674 本地 `./verify-all.sh quick` **绿**，CI 却红在

    tests/test_order_create_quantity_bounds.py::test_write_tool_money_and_size_numeric_params_declare_lower_bound

（#3622 落地的 L0 静态不变式：写工具的金额/数量/**尺寸**类数值参数必须声明下限）。
该文件是 `tests/` 顶层文件、不匹配任何 glob ⇒ 被 quick 跳过；`gate` 档只跑 QA 预检、
不跑单测 ⇒ 开发者在本地**没有任何一层**能看到它。这与 `migao-dev-flow` §2.1 声称的
「quick 即可覆盖常规回归」直接矛盾（文档承诺 ≠ 实际覆盖面）。

## 本守卫锁什么（L0，零 LLM；含一次真实 `--collect-only`）

1. quick 档的 ai-agent 选择**包含整个 `tests/` 目录**（**失败关闭**：新增顶层文件默认被覆盖；
   旧 glob 白名单是**失败开放**的 —— 本缺陷会无限复发）；
2. quick 与 full 的 ai-agent 选择集**一致**（否则「quick 绿」不再蕴含「ai-agent 绿」）；
3. 行为验证：把 quick 档的命令行**真跑一遍 `--collect-only`**，断言收集到的用例**真的来自
   每个顶层 `test_*.py`**（防「文本看着对、语义已漂移」——误加 `-m`/`-k`/`--ignore`/`--deselect`
   会把选择集悄悄收窄，而命令行文本里仍有 `tests/`）；
4. 旧 glob 白名单必红（`test_glob_whitelist_reintroduction_is_caught`，含本次受害用例）。

任何一条被改坏，本测试红 —— 就地拦住「本地绿 / CI 红」复发。
"""
import glob
import re
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SCRIPT = REPO_ROOT / "verify-all.sh"
SERVICE_DIR = REPO_ROOT / "backend" / "ai-agent-service"
TESTS_DIR = SERVICE_DIR / "tests"

# 显式豁免：quick 不收集、且**允许**不收集的顶层测试文件（当前为空）。
# 加条目前必须写清理由 + issue；守卫会拒绝「陈旧豁免」（文件其实已被覆盖 = 该删条目）。
EXEMPT: frozenset = frozenset()

# 当前缺陷的受害用例（issue #3680 的实证）：顶层文件、不匹配旧 glob 白名单。
_VICTIM_FILE = "test_order_create_quantity_bounds.py"

_COLLECT_TIMEOUT = 300


def _code_of(script_text: str) -> str:
    """脚本的**有效代码行**（剥掉注释）——注释里会引用旧写法，裸 grep 会假绿。"""
    return "\n".join(ln.split("#", 1)[0] for ln in script_text.splitlines())


def _mode_block(code: str, mode: str) -> str:
    """抽取**顶层** `case "$MODE" in` 里 `mode)` 分支的代码（`;;` 结束）。

    ⚠️ 必须按 `case`/`esac` 配对找**顶层** case：脚本里的 `gate_check()` 函数体内含
    **嵌套** case（`case P in xiaobu|mibao)`），用 `;;` 裸切会把函数体当成分支内容。
    """
    lines = code.splitlines()
    marker = f"{mode})"
    start = next((i for i, ln in enumerate(lines) if 'case "$MODE" in' in ln), -1)
    # 用数值比较而非「非空存在」式断言：后者会命中 QA Growth Gate 的弱断言模式
    # （growth_gate.py `_WEAK_PATTERNS`，注释里复述该文本也会被计为 1 处），门禁会判本文件「凑数测试」。
    assert start >= 0, 'verify-all.sh 里找不到顶层 `case "$MODE" in`'
    bi, depth, i = None, 0, start + 1
    while i < len(lines):
        ln = lines[i]
        if re.match(r"\s*case\b", ln):
            depth += 1
        elif re.match(r"\s*esac\b", ln):
            if depth == 0:
                break
            depth -= 1
        if depth == 0:
            if ln.strip() == marker:
                bi = i + 1
            elif bi is not None and ln.strip() == ";;":
                return "\n".join(lines[bi:i])
        i += 1
    raise AssertionError(f"verify-all.sh 顶层 case 里找不到 `{mode})` 分支（或它没有被 `;;` 结束）")


# `report "名称" bash -c "命令行"`：命令行是最外层双引号内的内容（其中单引号是**字面量**，
# 因为 bash 在双引号内不把单引号当引号 —— 故 shlex.split 会直接报 "No closing quotation"，不能用）。
_REPORT_RE = re.compile(r"^\s*report\s+(?:\"[^\"]*\"|\S+)\s+bash\s+-c\s+\"(?P<cmd>[^\"]*)\"\s*$")

# 脚本顶层的简单赋值 `NAME="值"` / `NAME=值`（quick/full 共用选择集就靠这个变量）
_ASSIGN_RE = re.compile(r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<val>\"[^\"]*\"|'[^']*'|\S+)\s*$")


def _expand_vars(cmd: str, code: str) -> str:
    """展开 cmd 里引用的顶层 shell 变量（`$NAME` / `${NAME}`）——不展开就无法判定选择集。"""
    vars_ = {
        m.group("name"): m.group("val").strip("\"'")
        for line in code.splitlines()
        if (m := _ASSIGN_RE.match(line))
    }
    return re.sub(
        r"\$\{?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}?",
        lambda m: vars_.get(m.group("name"), m.group(0)),
        cmd,
    )


def _ai_agent_cmd(script_text: str, mode: str) -> str:
    """verify-all.sh 文本里 `mode` 档的 ai-agent 检查项命令行（已展开顶层变量）。

    只展开 `report` 行引用的**本脚本顶层**变量（如 `AI_AGENT_TESTS`）；`$ROOT` 等运行期变量
    不在展开范围（选择集判定用不到）。
    """
    code = _code_of(script_text)
    cmds = [
        _expand_vars(m.group("cmd"), code)
        for line in _mode_block(code, mode).splitlines()
        if (m := _REPORT_RE.match(line)) and "ai-agent-service" in m.group("cmd")
    ]
    assert len(cmds) == 1, (
        f"verify-all.sh 的 {mode} 档应当有且只有 1 个 ai-agent 检查项，实得 {cmds}"
    )
    return cmds[0]


def _pytest_argv(cmd: str) -> list:
    """`cd '…/ai-agent-service' && .venv/bin/python -m pytest <选择集…>` → 选择集之后的 argv。

    命令行里的单引号是字面量（双引号内）⇒ 先剥掉再按空白切分。
    """
    argv = shlex.split(cmd.replace("'", ""))
    assert "pytest" in argv, f"ai-agent 检查项里找不到 pytest：{cmd!r}"
    return argv[argv.index("pytest") + 1:]


def _expand_globs(argv: list) -> list:
    """模拟 bash 的 glob/目录展开（相对于 ai-agent-service 的 cwd）。

    选择集里若出现 `tests/test_tools_*.py` 这类**带引号**的 glob（旧白名单写法），
    bash 不展开、pytest 收到字面 `*` → 报 usage error 退出 4（"file or directory not found"）——
    那样守卫只会报"收集失败"，看不出**真正的**后果（静默跳过 127 个文件）。
    先按 bash 语义展开，缺口才能以「跳过 N 个顶层文件」的形式暴露。
    """
    out = []
    for a in argv:
        if a.startswith("-"):
            out.append(a)
            continue
        hits = glob.glob(a, root_dir=SERVICE_DIR)
        out.extend(hits if hits else [a])
    return out


def _selected_paths(script_text: str = None, mode: str = "quick") -> list:
    """quick/full 选择集里的**路径参数**（剥掉 `-q`/`--no-cov`/`-n`+`4` 等开关）。"""
    text = SCRIPT.read_text(encoding="utf-8") if script_text is None else script_text
    argv = _expand_globs(_pytest_argv(_ai_agent_cmd(text, mode)))
    out, skip_next = [], False
    for a in argv:
        if skip_next:
            skip_next = False
            continue
        if a.startswith("-"):
            skip_next = a == "-n"  # `-n 4` 的 4 不是路径
            continue
        out.append(a)
    return out


def _top_level_tests() -> list:
    return sorted(p.name for p in TESTS_DIR.glob("test_*.py"))


def _pytest_ignores() -> set:
    """`pytest.ini` 的 `addopts` 里 `--ignore=tests/xxx.py` 的顶层文件名。

    这些文件**从不**参与 `pytest tests/`（真实 LLM/真实环境/手动脚本），与"选择集漏掉"
    是两码事 —— 不能被当成缺口，但也**不许**把 EXEMPT 当垃圾桶（见陈旧豁免守卫）。
    """
    import configparser

    ini = SERVICE_DIR / "pytest.ini"
    if not ini.exists():
        return set()
    cp = configparser.ConfigParser()
    cp.read(ini, encoding="utf-8")
    addopts = cp.get("pytest", "addopts", fallback="")
    return {
        Path(m.group(1)).name
        for m in re.finditer(r"--ignore=(tests/[\w./-]+\.py)", addopts)
        if "/" not in m.group(1)[len("tests/"):]  # 只取 tests/ 顶层被 ignore 的文件
    }


# `--collect-only -q` 的两种输出形态（取决于是否有 `-n`/xdist）：`path: <count>` 或 `path::用例`
_COUNT_LINE_RE = re.compile(r"^(?P<path>\S+): \d+$")


def _collected_files() -> set:
    """把 quick 档的 ai-agent 命令真跑一遍 `--collect-only`，返回「至少贡献 1 个用例」的文件。

    行为验证：只静态看命令行文本挡不住「文本对、语义已漂移」。
    `--collect-only -q` 对每个收集到用例的文件打印一行（`path: <count>`），
    未贡献任何用例的文件**不会出现** —— 正是本守卫要的判据（静默跳过 = 不出现）。
    """
    argv = _expand_globs(_pytest_argv(_ai_agent_cmd(SCRIPT.read_text(encoding="utf-8"), "quick")))
    python = SERVICE_DIR / ".venv" / "bin" / "python"
    assert python.exists(), f"找不到 {python} —— L0 守卫依赖本地 venv 验证选择集"
    cmd = [str(python), "-m", "pytest", *argv, "--collect-only", "-q", "-p", "no:cacheprovider"]
    r = subprocess.run(cmd, cwd=SERVICE_DIR, capture_output=True, text=True,
                       timeout=_COLLECT_TIMEOUT)
    assert r.returncode == 0, (
        f"quick 档 ai-agent 选择性收集失败（exit {r.returncode}）：\n"
        f"$ {' '.join(cmd)}\n"
        + (
            "⚠️ exit 4 = pytest usage error（选项/路径无法识别）⇒ 选择集本身有问题：\n"
            "   ① 旧 glob 白名单被引号包住、bash 不展开 → pytest 收到字面 `*`（本守卫要拦的回归）；\n"
            "   ② 选择集里出现了未展开的 shell 变量（请同步本守卫的 `_expand_vars`）。\n"
            if r.returncode == 4
            else ""
        )
        + (r.stdout + r.stderr)[-3000:]
    )
    out = []
    for ln in r.stdout.splitlines():
        if m := _COUNT_LINE_RE.match(ln.strip()):
            out.append(m.group("path"))
        elif ln.startswith("tests") and "::" in ln:
            out.append(ln.split("::", 1)[0])
    assert len(out) > 100, (
        f"选择性收集到的文件数异常偏少（{len(out)}）—— 选择集可能已被收窄：\n"
        f"$ {' '.join(cmd)}\n{r.stdout[-2000:]}"
    )
    return set(out)


_COLLECTED_CACHE = {}


@pytest.fixture(scope="module")
def collected() -> set:
    """quick 选择集实际收集到的文件（跑一次 `--collect-only`，模块内共享）。"""
    if "files" not in _COLLECTED_CACHE:
        _COLLECTED_CACHE["files"] = _collected_files()
    return _COLLECTED_CACHE["files"]


class TestVerifyAllQuickScope:
    """quick 档 ai-agent 选择集 = 整个 `tests/` 目录（issue #3680）。"""

    def test_quick_targets_whole_tests_dir(self):
        """选择集必须含**整个 `tests/` 目录**（`tests` 或 `tests/` 这一条路径参数本身）。

        目录选择是**失败关闭**的（新增顶层文件默认被覆盖）；glob 白名单是**失败开放**的
        （本缺陷的根因）。判据必须是**整条路径参数相等**，不能用子串包含
        （否则 `tests/unit` 会被误判为「覆盖了 tests/」）。
        """
        paths = _selected_paths()
        assert any(p.rstrip("/") == "tests" for p in paths), (
            f"quick 档 ai-agent 选择集 {paths} 不含整个 `tests/` 目录 —— 退回 glob 白名单了？"
            "新增的顶层测试文件会被静默跳过（issue #3680：本地绿 / CI 红）"
        )

    def test_quick_and_full_share_the_same_ai_agent_selection(self):
        """quick 与 full 对 ai-agent 必须**判据一致**（full 的额外开销只在 admin-api 全量 Maven）。

        两档选择集不同 = 「quick 绿」不再蕴含「ai-agent 绿」，本缺陷会以新形态复发。
        """
        text = SCRIPT.read_text(encoding="utf-8")
        quick, full = _ai_agent_cmd(text, "quick"), _ai_agent_cmd(text, "full")
        assert _pytest_argv(quick) == _pytest_argv(full), (
            "quick 与 full 的 ai-agent 选择集不一致 —— quick 会漏掉 full 能跑到的文件：\n"
            f"  quick: {quick}\n  full : {full}"
        )

    def test_quick_collects_every_collectible_top_level_test_file(self, collected):
        """行为验证：quick 的命令**真跑**一遍，每个顶层 `test_*.py` 都必须被收集到。

        唯一的例外是 `pytest.ini` 里显式 `--ignore` 的文件（真实 LLM/真实环境/手动脚本，
        它们**从不**参与 `pytest tests/` —— 与"选择集漏掉"是两码事）。
        """
        ignored = _pytest_ignores()
        top = [f for f in _top_level_tests() if f not in EXEMPT and f not in ignored]
        assert len(top) > 100, f"顶层测试文件数异常偏少（{len(top)}）—— 路径解析出错？"
        missing = [f for f in top if f"tests/{f}" not in collected]
        assert not missing, (
            f"quick 档 ai-agent 静默跳过 {len(missing)}/{len(top)} 个顶层测试文件：\n  "
            + "\n  ".join(missing[:20])
            + "\n\n这正是 issue #3680（本地 quick 绿 / CI 红）的根因：顶层测试文件必须被 quick 覆盖。"
        )

    def test_top_level_files_accounted_for(self, collected):
        """每个顶层 `test_*.py` 都必须有归属：被收集 / EXEMPT / `pytest.ini --ignore`。

        防止"解析漏了"被伪装成缺口，也防止新豁免被静默塞进 EXEMPT（豁免必须显式 + 有理由）。
        """
        accounted = collected | {f"tests/{f}" for f in EXEMPT} | {
            f"tests/{f}" for f in _pytest_ignores()
        }
        unaccounted = [f for f in _top_level_tests() if f"tests/{f}" not in accounted]
        assert not unaccounted, (
            f"以下顶层测试文件既未被 quick 收集、也不在 EXEMPT/pytest.ini --ignore 里：{unaccounted}"
        )

    def test_exempt_list_has_no_stale_entries(self, collected):
        """陈旧豁免必须红：被豁免的文件其实已被覆盖 = 该删条目（防豁免清单变垃圾场）。"""
        stale = [f for f in EXEMPT if f"tests/{f}" in collected]
        assert not stale, f"EXEMPT 里的 {stale} 其实已被 quick 覆盖 —— 请删除这些陈旧豁免条目"

    def test_glob_whitelist_reintroduction_is_caught(self):
        """变异测试（失败关闭）：把 quick 改回旧 glob 白名单 → 判据必须识别出缺口。

        只断言"旧写法不含 tests/"太弱（换个 glob 集合就绕过）⇒ 这里**真展开 glob**，
        断言本次受害用例 `test_order_create_quantity_bounds.py` 落在缺口里。
        """
        old_selection = (
            "tests/unit tests/test_tools_*.py tests/test_graph_*.py "
            "tests/test_intent_router.py -q --no-cov"
        )
        covered = set()
        for pat in old_selection.split():
            if pat.startswith("-"):
                continue
            hits = glob.glob(pat, root_dir=TESTS_DIR)
            if hits:
                covered.update(Path(h).name for h in hits)
            else:  # `tests/unit` 是目录：整目录被覆盖
                covered.update(p.name for p in (TESTS_DIR / pat).glob("test_*.py"))
        assert not any(p in ("tests", "tests/") for p in old_selection.split()), "变异输入构造错误"
        gap = [f for f in _top_level_tests() if f not in covered and f not in _pytest_ignores()]
        assert _VICTIM_FILE in gap, (
            f"旧 glob 白名单竟覆盖了受害用例 {_VICTIM_FILE}？变异输入与实测不符（缺口 {len(gap)} 个）"
        )
        assert len(gap) > 50, (
            f"旧 glob 白名单的缺口只有 {len(gap)} 个顶层文件（预期 >50）—— 变异输入与实测不符"
        )
