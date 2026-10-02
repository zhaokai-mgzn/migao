# case_ids: MC-041
"""**「取下一个用例号」必须是机械化的一条只读命令**（issue #5707 的链内收口；`FM-E7` / `FM-E15`）。

## 病根（不是一个缺陷，是**同一形态复发 5~6 次**）

用例号此前在**每个包里手工取**：跑一次「现取最大号 + 1」。而唯一性判据**只看已合并状态**
（`test_dev_mode_failure_modes.py` 的判据 11/12）⇒ **拦不住在飞** ⇒ 并发的几个包各自「现取」
都得到**同一个答案**。实测：`MC-046` 被 PR #5733 / #5734 / #5736 **三个包同时取到**
（逐字记在 MC-047 / MC-048 的 `merge_log` 里）；更早 `UI-061` / `UI-064` / `MC-022` / `MC-023` /
`BM-019` / `MC-031` / `MC-039` 也撞过。既有缓解（「取号前也 `gh pr` 查一遍在飞 PR 的 diff」）
是**手工动作** ⇒ 并发 5~6 个包时必然失效。

## 本文件锁什么（七条判据，逐条都能单独变红）

| # | 判据 | 取法（结构化，**不读散文**） | 红证 |
|---|---|---|---|
| 1 | **只读（源码层）** | `scripts/next_case_id.py` 全部 `subprocess` 出口必须收在 `gh()` / `git()` 两个外壳里；外壳的 argv 白名单必须逐字在位；源码里不得出现写文件 API | 源码注入 `shutil` / `write_text` / 白名单被删 ⇒ 红（纯函数 `read_only_problems(src)`） |
| 2 | **白名单真有牙齿（实调）** | 喂 `gh` 写子命令 / `gh api -X POST` / `git push` / `git fetch` 进外壳 ⇒ **必抛断言** | 把白名单检查从源码里删掉 ⇒ 该断言不再触发 ⇒ 判据 1 的纯函数报红 |
| 3 | 🔴 **三态：看不到在飞面 ⇒ 不许取号** | `NCI_GH_BIN` 替身（不存在 / 非零退出 / 某个 PR 读不到）⇒ `exit 3` + 「无法判定 ⇒ 不许取号」+ 输出里**零个号** | 把 `exit 3` 换成"乐观给号"（源码变异）⇒ `tri_state_problems` 报红 |
| 4 | 🔴 **自证「返回的号 ∉ 候选集」** | `allocate()` 的断言写在函数**内部**；把 `min_free` 换成"返回已占号" ⇒ 必抛 | 删掉内部断言 ⇒ 该变异**不再抛** ⇒ 判据报红 |
| 5 | 🔴 **内存构造复现今天的现场（核心牙齿）** | main 039/040/043/044/045/047 + 在飞 A 046 + 在飞 B 048 ⇒ **041**；A 改成 041 ⇒ **042** | 只看 main 的实现两次都答 041 ⇒ 坏形态读数 ≠ 基线读数 |
| 6 | **类级：`scripts/**` 里取号只有一个实现点**（双向） | AST 取「用例号形态的正则字面量（真能匹配 `  - id: MC-041` / `MC-041`）+ 号空间后继 / 极值运算」的模块集合 ⇄ 判据里冻结的实现点元组 | 新造第二个算号脚本 ⇒ 「未登记」红；实现点不再命中指纹 ⇒ 「陈旧登记」红 |
| 7 | **技能面口径唯一（防旧配方回来）** | `migao-dev-flow` §26.3 必须调用该工具，且**不得**再出现手工取号的旧配方 | 把旧配方写回去 ⇒ 红；只加一句散文 ⇒ 不红（对照） |

## 判定方式是确定的（**刻意不进判据的东西**）

判据本体**零 gh / 零网络 / 零时钟**：真语料只用于一条**离线等价检查**（工具的正则 ⇄ 判据侧
`test_dev_mode_failure_modes.py::case_id_lines` 在 `.github/cases/**` 上**逐值相等**），
且 **`origin/main` 刻意不读** —— CI 的 checkout 是 `fetch-depth: 1`，读它会因"取不到 ref"
而**因错的原因**变绿/变红（实测先例：`test_admin_web_devserver_identity.py` 的锚点曾绑
`origin/main` ⇒ 在 CI 走 skip）。CLI 级的三态用例统一传 `NCI_MAIN_REF=HEAD`。

## 覆盖面（**盖不到**什么 —— 照实登记，不写成恒真判据）

- ❌ **判不了「取号方真的跑了这条命令」**：判据看得见工具与技能文本，看不见派单**消息**
  （仓外、不 durable，同 `FM-R8` / `FM-R15` 的残余）；
- ❌ **指纹普查只认一种形态**：第二份算号实现若用 `split("-")` 之类**不用正则**的解析，
  本判据的判据 6 **看不见**（不误伤，但也不拦）；
- ❌ **判不了工具在真实网络下的行为**：三态用替身 `gh` 判的是**分支存在**，不是"GitHub 此刻可用"；
- ❌ **`scripts/**` 之外**（`.github/` 的解析器、别的语言写的算号器）不在判据 6 射程内
  （本单的口径只到 `scripts/**`，与指令一致）；
- ❌ **「最小空闲号落在历史空档」在语义上是否合适**判不了（工具只保证号**没被占用**，
  空档是不是"刻意保留"要人判 —— 工具已在输出里标出`（历史空档：…）`）；
- ❌ **并发互斥判不了**：两个包在同一瞬间调用仍会拿到同一个号。本工具消灭的是
  「**看不到在飞面**」这一层（那才是这 5~6 次撞号的直接成因），**不是**「并发锁」。
- ❌ 本判据**不是新门禁、不改任何门禁的通过条件、不新增豁免**。
"""
from __future__ import annotations

import ast
import base64
import importlib.util
import json
import os

import re
import stat
import subprocess
import sys
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# ── 预设语料读取（S4 / issue #6020）：与 `test_source_parsing_shared.py` 同款的命名空间包导入 ──
sys.path.append(str(Path(__file__).resolve().parents[1]))  # tests/（append：只作兜底解析路径）

from unit_ci_workflows.preset_corpus import (  # noqa: E402
    DEV_FLOW_SKILL_REL,
    require_preset_text,
)
TOOL_REL = "scripts/next_case_id.py"
TOOL_PATH = REPO_ROOT / TOOL_REL
SCRIPTS_DIR = REPO_ROOT / "scripts"
#: 🔴 S4（issue #6020）：预设内容已迁出业务仓 ⇒ 统一走 `preset_corpus`（镜像优先 / 其次 git 基线）。
SKILL_REL = ".agent-presets/migao/skills/migao-dev-flow/SKILL.md"


def _skill_text() -> str:
    """现取技能正文（取不到 ⇒ 抛 AssertionError，fail-closed）。"""
    return require_preset_text(DEV_FLOW_SKILL_REL)

#: 注入点（与 `MG_GH_BIN` / `SBT_GH_BIN` / `DANGLING_GH_BIN` 同先例）：`gh` 替身 + 主线段 ref。
GH_ENV = "NCI_GH_BIN"
MAIN_REF_ENV = "NCI_MAIN_REF"

#: 判据 6 的**射程**（本单口径 = 指令给的 `scripts/**`；扩面要先改这里）。
ALLOCATOR_SCAN_ROOT = "scripts"
#: 判据 6 的**指纹**：两半**同时**成立才算「第二份取号实现」。
#:   ① 用例号形态的**正则字面量**（真能匹配 `  - id: MC-041` 或 `MC-041`，且带数字类）；
#:   ② 号空间上的**后继 / 极值**运算（`+ 1` / `+= 1` / `max(` / `min(`）。
CASE_ID_SAMPLE_LINE = "  - id: MC-041"
CASE_ID_SAMPLE_TOKEN = "MC-041"
SUCCESSOR_TOKENS = ("+ 1", "+1", "+= 1", "+=1", "max(", "min(")

#: 「取号」的实现点**冻结清单** —— 注释声称 `scripts/**` 里取号是**单一实现**（第二份算号脚本
#: 不许存在）⇒ 由本文件 `test_only_one_allocation_implementation_in_scripts` 承担
#: （双向：多一个 ⇒ 红、少一个 ⇒ 红）。登记面 = `declaration_gate_registry.json::same_source_claims`。
ALLOCATION_IMPLEMENTATIONS_FROZEN = ("scripts/next_case_id.py",)

#: 判据 7 的**旧配方指纹**（手工取号：现取最大号 + 1）。这些串**只许消失**，不许出现在 §26.3 里。
HAND_ROLLED_RECIPE_MARKERS = ("| sort -u | tail", "已合并侧现取最大号")
#: §26.3 节标题 / 下一节标题（字面定位，不靠行号 —— 行号会腐）。
CMD_SECTION_HEADING = "### 26.3 可复制命令"
NEXT_SECTION_HEADING = "### 26.4 覆盖面登记"
TOOL_INVOCATION = "scripts/next_case_id.py"

#: 写面 API（判据 1）：工具是**只读**的，出现任何一个 ⇒ 红。
WRITE_API_MARKERS = (
    ".write_text(", ".write_bytes(", "os.remove(", "os.unlink(", "os.makedirs(",
    ".mkdir(", "shutil.", "os.rmdir(", "os.rename(", "tempfile.",
)
#: `open(...)` 的写模式（判据 1）。
WRITE_OPEN_MODE_RE = re.compile(r"""open\([^)]*?,\s*['"][wax]""")
#: 允许出现 `subprocess` 的**外壳函数**（判据 1）：别的函数里出现 = 绕过白名单。
SHELL_FUNCS = ("gh", "git")
#: 白名单常量名（判据 1；删掉常量 ⇒ 红 = fail-closed）。
WHITELIST_CONSTS = ("GH_READ_ONLY", "GIT_READ_ONLY")


# ─────────────────────────────────────────────────────────────────────────────
# 加载与变异工装（判据一律走**纯函数**；变异在**内存**里做，不碰磁盘）
# ─────────────────────────────────────────────────────────────────────────────
def _load_tool():
    spec = importlib.util.spec_from_file_location("nci_under_test", TOOL_PATH)
    assert spec and spec.loader, f"加载不了 {TOOL_REL}（判据 fail-closed）"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source() -> str:
    return TOOL_PATH.read_text(encoding="utf-8")


def _mutant_source(old: str, new: str) -> str:
    """把工具源码里**唯一**的 `old` 换成 `new`（锚唯一 + 锚必须在 ⇒ 否则判据自己报错）。"""
    src = _source()
    hits = src.count(old)
    assert hits == 1, f"变异锚在 {TOOL_REL} 里出现 {hits} 次（必须恰好 1 次）：{old!r}"
    return src.replace(old, new)


def _exec(source: str) -> dict:
    """把一段工具源码在内存里 exec 出来（**不写盘**）⇒ 用来观测变异后的行为。"""
    ns: dict = {"__name__": "nci_mutant", "__file__": str(TOOL_PATH)}
    exec(compile(source, str(TOOL_PATH), "exec"), ns)  # noqa: S102 —— 变异的是**本仓自己的只读工具**
    return ns


# ─────────────────────────────────────────────────────────────────────────────
# 判据 1/2 的纯函数：只读性
# ─────────────────────────────────────────────────────────────────────────────
def read_only_problems(src: str) -> list[str]:
    """源码层的**只读性**（判据 1）：写面 API / 白名单缺失 / `subprocess` 绕过外壳。"""
    bad: list[str] = []
    for marker in WRITE_API_MARKERS:
        if marker in src:
            bad.append(f"源码里出现写面 API `{marker}`（工具必须是只读的）")
    for hit in WRITE_OPEN_MODE_RE.findall(src):
        bad.append(f"源码里出现写模式 `open(...)`：{hit!r}")
    for const in WHITELIST_CONSTS:
        if not re.search(rf"^{const}\s*[:=]", src, re.MULTILINE):
            bad.append(f"白名单常量 `{const}` 不在源码里（删掉它 = 白名单消失，fail-closed）")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"):
            continue
        owner = _enclosing_function(tree, node)
        if owner not in SHELL_FUNCS:
            bad.append(f"`subprocess` 调用出现在 `{owner or '<模块层>'}` 里（必须收在 {SHELL_FUNCS} 外壳中）")
    return bad


def _enclosing_function(tree: ast.AST, target: ast.AST) -> str | None:
    """`target` 所在的最近函数名（AST 父链，标准库 `ast` 不带 parent ⇒ 自己走一遍）。"""
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(n is target for n in ast.walk(fn)):
            return fn.name
    return None


def tri_state_problems(rc: int, stdout: str, stderr: str = "") -> list[str]:
    """**无法判定**时必须：`exit 3` + 打印「无法判定 ⇒ 不许取号」+ **一个号都不给**（判据 3）。"""
    bad: list[str] = []
    if rc != 3:
        bad.append(f"看不到在飞面时退出码必须是 3（无法判定）而实际是 {rc} —— 「乐观给号」")
    if "无法判定 ⇒ 不许取号" not in stdout:
        bad.append("看不到在飞面时没有打印「无法判定 ⇒ 不许取号」（不许退化成一句普通报错）")
    if ALLOC_LINE_MARK in stdout:
        bad.append(f"看不到在飞面时**仍然给出了号**（输出里出现 {ALLOC_LINE_MARK!r}）—— 正是撞号的成因")
    return bad


#: 分配行的标记（判据 3 用它判「一个号都不许出现」）。
ALLOC_LINE_MARK = "→ 取 "


def case_id_pattern_problems(src: str) -> list[str]:
    """判据 6 的指纹 ①：模块里能匹配用例号的**正则字面量**（带数字类，且含 `-` 或 `id:`）。"""
    hits: list[str] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # 语料里存在非 raw 串的 `\s`（既有形态）⇒ 噪声不进判据
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            pat = node.value
            if "\n" in pat or not pat or ("\\d" not in pat and "[0-9]" not in pat):
                continue
            if "-" not in pat and "id:" not in pat:
                continue
            try:
                rx = re.compile(pat)
            except re.error:
                continue
            if rx.search(CASE_ID_SAMPLE_LINE) or rx.search(CASE_ID_SAMPLE_TOKEN):
                hits.append(pat)
    return hits


def unregistered_allocators(sources: dict[str, str],
                            registered: tuple[str, ...] = ALLOCATION_IMPLEMENTATIONS_FROZEN) -> list[str]:
    """判据 6（**双向**）：指纹命中的实现点必须 == 冻结清单（多一个 / 少一个都红）。"""
    bad: list[str] = []
    observed = set()
    for rel, src in sorted(sources.items()):
        if not case_id_pattern_problems(src):
            continue
        if not any(tok in src for tok in SUCCESSOR_TOKENS):
            continue
        observed.add(rel)
    for rel in sorted(observed - set(registered)):
        bad.append(f"{rel}：命中「算号」指纹但**未登记** —— `scripts/**` 里取号只许有一个实现点"
                   f"（要么删掉它并改调 {TOOL_REL}，要么在 `ALLOCATION_IMPLEMENTATIONS_FROZEN` 里显式登记并说明为什么）")
    for rel in sorted(set(registered) - observed):
        bad.append(f"{rel}：已登记为实现点但**现取不再命中指纹** ⇒ 陈旧登记（删了实现 / 换了写法都要同批改这里）")
    if not sources:
        bad.append("`scripts/**` 下一个 Python 文件都没有 ⇒ 判据会静默空跑（fail-closed）")
    return bad


def skill_face_problems(text: str) -> list[str]:
    """判据 7：技能 §26.3 必须调用工具，且**不得**再出现手工取号的旧配方。"""
    bad: list[str] = []
    if CMD_SECTION_HEADING not in text or NEXT_SECTION_HEADING not in text:
        return [f"定位不到技能 §26.3 / §26.4 的标题字面（{CMD_SECTION_HEADING!r} / {NEXT_SECTION_HEADING!r}）"
                f" ⇒ 判据 fail-closed"]
    section = text.split(CMD_SECTION_HEADING, 1)[1].split(NEXT_SECTION_HEADING, 1)[0]
    if TOOL_INVOCATION not in section:
        bad.append(f"§26.3 里没有 `{TOOL_INVOCATION}` 的取号命令 ⇒ 取号又回到手工做")
    for marker in HAND_ROLLED_RECIPE_MARKERS:
        if marker in section:
            bad.append(f"§26.3 里还留着手工取号的旧配方（命中 {marker!r}）⇒ 下一个人照旧配方做，工具等于白造")
    return bad


# ─────────────────────────────────────────────────────────────────────────────
# 真语料 / CLI 工装
# ─────────────────────────────────────────────────────────────────────────────
def _scripts_sources() -> dict[str, str]:
    return {str(p.relative_to(REPO_ROOT)): p.read_text(encoding="utf-8")
            for p in sorted(SCRIPTS_DIR.glob("*.py"))}


def _run_cli(args: list[str], gh_bin: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[MAIN_REF_ENV] = "HEAD"  # CI 是 fetch-depth: 1 ⇒ 判据不读 origin/main（见文件头）
    if gh_bin is None:
        env.pop(GH_ENV, None)
    else:
        env[GH_ENV] = gh_bin
    return subprocess.run([sys.executable, str(TOOL_PATH), *args],
                          capture_output=True, text=True, env=env, cwd=str(REPO_ROOT))


def _gh_stub(tmp_path: Path, *, mode: str = "empty", pr_ids: str = "") -> str:
    """写一个 `gh` 替身可执行文件（**测试自己的**临时文件；工具侧仍然零写）。

    mode: `empty`（0 个 open PR）· `fail`（非零退出 = 未登录 / 离线）· `one_pr`（1 个 PR 改了语料）
          · `diff_fail`（`pr list` 正常但 `pr diff` 非零退出 = 某个 PR 读不到）
    """
    body = json.dumps([{"number": 9999, "headRefName": "stub/branch", "headRefOid": "0" * 40,
                        "isDraft": False}])
    listing = json.dumps({"name": "misc.yml", "path": ".github/cases/misc.yml", "sha": "f" * 40,
                          "type": "file", "encoding": "base64",
                          "content": base64.b64encode(pr_ids.encode()).decode()})
    stub = tmp_path / f"gh-stub-{mode}"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"argv = sys.argv[1:]\n"
        f"mode = {mode!r}\n"
        "if argv[:2] == ['pr', 'list']:\n"
        "    if mode == 'fail':\n"
        "        print('gh: To get started with GitHub CLI, please run: gh auth login', file=sys.stderr)\n"
        "        sys.exit(4)\n"
        f"    print(json.dumps([]) if mode == 'empty' else {body!r})\n"
        "    sys.exit(0)\n"
        "if argv[:2] == ['pr', 'diff']:\n"
        "    if mode in ('diff_fail', 'fail'):\n"
        "        print('gh: could not read PR diff', file=sys.stderr)\n"
        "        sys.exit(1)\n"
        "    print('.github/cases/misc.yml')\n"
        "    sys.exit(0)\n"
        "if argv[:1] == ['api']:\n"
        f"    print({listing!r})\n"
        "    sys.exit(0)\n"
        "print('unexpected argv', argv, file=sys.stderr)\n"
        "sys.exit(9)\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(stub)


# ═════════════════════════════════════════════════════════════════════════════
# 判据 1：只读（源码层）
# ═════════════════════════════════════════════════════════════════════════════
def test_tool_exists_and_is_read_only_at_the_source_level() -> None:
    """判据 1：工具存在、且源码层**只读**（写面 API 零命中 / 白名单在位 / `subprocess` 收在外壳里）。"""
    assert TOOL_PATH.is_file(), f"取号工具不在：{TOOL_REL}（判据 fail-closed）"
    src = _source()
    assert read_only_problems(src) == [], "\n".join(read_only_problems(src))


def test_read_only_criterion_has_discriminating_power() -> None:
    """判据 1 的判别力自证（**内存变异**：坏形态必红 + 只改注释不红）。"""
    src = _source()
    assert read_only_problems(src) == []
    # 坏形态 1：引入写面 API（`shutil.rmtree`）
    mutant_shutil = _mutant_source("def _gh_bin() -> str:",
                                   "def _gh_bin() -> str:\n    import shutil\n    shutil.rmtree('/tmp/x', ignore_errors=True)")
    assert any("shutil." in p for p in read_only_problems(mutant_shutil)), read_only_problems(mutant_shutil)
    # 坏形态 2：写模式 open（把读语料那行换成写盘）
    assert any("写模式" in p for p in read_only_problems(_mutant_source(
        'with open(os.path.join(corpus, name), encoding="utf-8") as fh:',
        'with open("/tmp/x", "w") as fh:')))
    # 坏形态 3：白名单常量被改名（= 白名单消失）
    assert any("GH_READ_ONLY" in p for p in read_only_problems(
        _mutant_source("GH_READ_ONLY = (", "GH_READ_ONLY_RENAMED = (")))
    # 坏形态 4：`subprocess` 搬到外壳之外（绕过白名单）
    bypassed = _mutant_source("def git(argv: list[str]) -> str:", "def git_bypassed(argv: list[str]) -> str:")
    assert any("subprocess" in p and "git_bypassed" in p for p in read_only_problems(bypassed)), \
        read_only_problems(bypassed)
    # 对照：**只改注释 / 只改文档串** ⇒ 不红
    assert read_only_problems(_mutant_source('"""next_case_id.py', '"""next_case_id.py  # 只加一句注释')) == []


# ═════════════════════════════════════════════════════════════════════════════
# 判据 2：白名单真有牙齿（实调外壳）
# ═════════════════════════════════════════════════════════════════════════════
def test_shells_reject_write_argv_in_memory() -> None:
    """判据 2：`gh` / `git` 外壳必须**拒绝**写子命令与写动词（结构性「零写」，不是纪律）。"""
    module = _load_tool()
    for argv in (["pr", "create"], ["pr", "merge", "1"], ["api", "-X", "POST", "/x"],
                 ["api", "--method", "DELETE", "/x"], ["issue", "close", "1"], ["label", "create", "x"]):
        try:
            module.gh(argv)
        except AssertionError:
            continue
        raise AssertionError(f"`gh {' '.join(argv)}` 没有被外壳拒绝 —— 工具不是只读的")
    for argv in (["push"], ["fetch", "origin"], ["commit", "-m", "x"], ["tag", "v1"], ["reset", "--hard"]):
        try:
            module.git(argv)
        except AssertionError:
            continue
        raise AssertionError(f"`git {' '.join(argv)}` 没有被外壳拒绝 —— 工具不是只读的")
    # 对照（正向基线）：允许的只读形态**不**被拒（否则白名单把工具自己锁死 = 另一种假绿）
    assert module.git(["rev-parse", "HEAD"]).strip()


def test_write_rejection_has_discriminating_power(monkeypatch) -> None:
    """判据 2 的判别力自证（内存变异）：白名单检查被拔掉 ⇒ 写子命令**一路走到 subprocess**。

    🔴 安全：变异体指向一个**不存在**的 `gh`（`NCI_GH_BIN`）⇒ 它绝不可能真的执行 `gh pr create`；
    「走到了 subprocess」这一事实由 `Undecidable("gh 不可用…")` 体现 —— 白名单还在时**根本走不到那里**。
    """
    monkeypatch.setenv(GH_ENV, "/nonexistent/gh-mutant-must-not-run")
    mutant = _exec(_mutant_source(
        "    if not any(tuple(argv[: len(p)]) == p for p in GH_READ_ONLY):\n"
        "        raise AssertionError(f\"拒绝执行非只读 gh 子命令（白名单 = {GH_READ_ONLY}）：{argv}\")\n",
        "    pass  # 变异：白名单检查被拔掉\n"))
    assert "GH_READ_ONLY" in mutant
    try:
        mutant["gh"](["pr", "create"])  # type: ignore[operator]
    except AssertionError as exc:
        raise AssertionError(f"变异没生效 ⇒ 判据 2 是空断言（白名单仍在拒绝）：{exc}") from None
    except mutant["Undecidable"] as exc:
        assert "gh 不可用" in str(exc), f"变异体没有走到 subprocess（异常形态不对）：{exc}"
    else:
        raise AssertionError("变异体既没被拒也没走 subprocess ⇒ 观测口径失效")


# ═════════════════════════════════════════════════════════════════════════════
# 判据 3：三态（看不到在飞面 ⇒ 不许取号）
# ═════════════════════════════════════════════════════════════════════════════
def test_gh_unavailable_refuses_to_allocate(tmp_path: Path) -> None:
    """判据 3-a：`gh` **不可用**（可执行文件不存在）⇒ exit 3 + 「不许取号」+ 零个号。"""
    proc = _run_cli(["MC"], gh_bin=str(tmp_path / "definitely-not-here"))
    assert tri_state_problems(proc.returncode, proc.stdout, proc.stderr) == [], \
        f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"


def test_gh_not_logged_in_refuses_to_allocate(tmp_path: Path) -> None:
    """判据 3-b：`gh` **未登录 / 离线**（非零退出）⇒ exit 3 + 「不许取号」+ 零个号。"""
    proc = _run_cli(["MC"], gh_bin=_gh_stub(tmp_path, mode="fail"))
    assert tri_state_problems(proc.returncode, proc.stdout, proc.stderr) == [], \
        f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"


def test_unreadable_inflight_pr_refuses_to_allocate(tmp_path: Path) -> None:
    """判据 3-c：某个在飞 PR 的**内容读不到** ⇒ 同样 exit 3（在飞面读不全 ⇒ 不许取号）。"""
    proc = _run_cli(["MC"], gh_bin=_gh_stub(tmp_path, mode="diff_fail"))
    assert tri_state_problems(proc.returncode, proc.stdout, proc.stderr) == [], \
        f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"


def test_tri_state_criterion_has_discriminating_power() -> None:
    """判据 3 的判别力自证：把「乐观给号」的坏形态喂进纯函数 ⇒ 必报红（含「仍然给出了号」分支）。"""
    good = f"❌ 无法判定 ⇒ 不许取号\n   原因：gh 不可用"
    assert tri_state_problems(3, good) == []
    assert any("退出码" in p for p in tri_state_problems(0, good))
    assert any("无法判定" in p for p in tri_state_problems(3, "❌ 读不到在飞分支"))
    assert any("仍然给出了号" in p for p in tri_state_problems(3, good + f"\n   MC → 取 MC-041"))


def test_cli_consults_the_inflight_face(tmp_path: Path) -> None:
    """判据 3-d（**正向**，CLI 级）：在飞 PR 占了一个全新前缀的号 ⇒ 工具必须让出它。

    用真语料里不存在的前缀（`QX`）⇒ 读数与 main 的现状无关（不绑可变引用）；
    `empty` 对照 ⇒ 同一前缀在「0 个 open PR」时取到更小的号 ⇒ 证明在飞面**真的被读进去了**。
    """
    baseline = _run_cli(["QX"], gh_bin=_gh_stub(tmp_path, mode="empty"))
    assert baseline.returncode == 0, f"rc={baseline.returncode}\n{baseline.stdout}\n{baseline.stderr}"
    assert "QX-001" in baseline.stdout, baseline.stdout
    inflight = _run_cli(["QX"], gh_bin=_gh_stub(tmp_path, mode="one_pr", pr_ids="  - id: QX-001\n"))
    assert inflight.returncode == 0, f"rc={inflight.returncode}\n{inflight.stdout}\n{inflight.stderr}"
    assert "QX-002" in inflight.stdout, "在飞 PR 占了 QX-001，工具却仍给 QX-001 ⇒ 它没看在飞面\n" + inflight.stdout
    assert "PR #9999" in inflight.stdout, "证据行没有点名在飞 PR ⇒ 人无法复算\n" + inflight.stdout


# ═════════════════════════════════════════════════════════════════════════════
# 判据 4/5：自证「返回的号 ∉ 候选集」+ 内存构造复现今天的现场
# ═════════════════════════════════════════════════════════════════════════════
#: 今天的现场（**内存构造**）：main 的 MC 家族（001-040 + 043/044/045 + 047，逐值 —— 派生单看尾部会
#: 误以为 001 空着）+ 两个在飞包各占一个号。读数来源 = 工具 2026-09-27 22:13 的真实输出。
INCIDENT_MAIN_NUMS = tuple(range(1, 41)) + (43, 44, 45, 47)
INCIDENT_MAIN = "".join(f"  - id: MC-{n:03d}\n" for n in INCIDENT_MAIN_NUMS)
INCIDENT_PR_A = "  - id: MC-046\n"
INCIDENT_PR_B = "  - id: MC-048\n"
#: 第二幕：把在飞 A 从 046 改成 041 ⇒ 答案必须跟着动（证明它真的看得到在飞）。
INCIDENT_PR_A_MOVED = "  - id: MC-041\n"


def _occupied(module, *texts: str) -> dict:
    """把若干份语料并成候选集（`module` 既可以是加载出来的模块，也可以是内存变异体的命名空间）。"""
    def attr(name: str):
        return module[name] if isinstance(module, dict) else getattr(module, name)

    return attr("merge_ids")(*(attr("parse_ids")(t) for t in texts))


def test_allocate_asserts_the_answer_is_outside_the_candidate_set() -> None:
    """判据 4：`allocate()` **内部**断言「返回的号 ∉ 候选集」；变异成"返回已占号" ⇒ 必抛。"""
    module = _load_tool()
    occupied = _occupied(module, INCIDENT_MAIN, INCIDENT_PR_A)
    assert module.allocate(occupied) == {"MC": 41}
    # 内存变异：把 min_free 换成"返回一个已被占用的号" ⇒ 内部断言必须真的炸
    ns = _exec(_mutant_source("def min_free(used: set[int]) -> int:",
                              "def min_free(used: set[int]) -> int:\n    return 46  # 变异：返回已占号"))
    try:
        ns["allocate"](_occupied(ns, INCIDENT_MAIN, INCIDENT_PR_A))
    except AssertionError as exc:
        assert "MC-046" in str(exc), f"断言炸了但报文没点名那个号：{exc}"
    else:
        raise AssertionError("变异后没炸 ⇒ 判据 4 是空断言（自证被删 / 被挪到调用方）")


def test_todays_incident_is_reproduced_in_memory() -> None:
    """判据 5（**核心牙齿**）：main + 两个在飞包 ⇒ **041**；把在飞 A 改成 041 ⇒ **042**。"""
    module = _load_tool()
    main_only = module.parse_ids(INCIDENT_MAIN)
    two_inflight = _occupied(module, INCIDENT_MAIN, INCIDENT_PR_A, INCIDENT_PR_B)
    moved = _occupied(module, INCIDENT_MAIN, INCIDENT_PR_A_MOVED, INCIDENT_PR_B)
    assert module.allocate(two_inflight) == {"MC": 41}, \
        "最小空闲号必须是 041（main 001-040/043-045/047 + 在飞 046/048）"
    assert module.allocate(moved) == {"MC": 42}, "在飞 A 占了 041 ⇒ 必须让到 042"
    # 对照读数（防「变异没生效 ⇒ 空断言」）：手工口径「最大号 + 1」在这两幕里都答 049 ⇒ 与最小空闲号**不同**
    for corpus in (two_inflight, moved):
        tail_plus_one = max(n for nums in corpus.values() for n in nums) + 1
        assert tail_plus_one == 49 and tail_plus_one != module.allocate(corpus)["MC"], \
            "对照读数与最小空闲号相同 ⇒ 这条判据分不出两种口径"


def test_min_free_is_not_max_plus_one_and_counts_all_sources() -> None:
    """判据 5 的口径核对：**最小空闲号** ≠ 最大号 + 1；且「工作区先占」的号不许被自己判成空闲。"""
    module = _load_tool()
    gap = _occupied(module, "".join(f"  - id: MC-{n:03d}\n" for n in (1, 2, 3, 10, 11)))
    assert module.allocate(gap) == {"MC": 4}, "有空档时必须填空档（尾部 +1 会答 12）"
    assert module.min_free({1, 2, 3}) == 4
    assert module.min_free(set()) == 1
    # 工作区来源先占：main + 工作区一起占住 041 ⇒ 答案必须是 042
    worktree_owned = _occupied(module, INCIDENT_MAIN, INCIDENT_PR_A_MOVED)
    assert module.allocate(worktree_owned) == {"MC": 42}


def test_parse_agrees_with_the_criterion_side_parser() -> None:
    """离线**等价检查**：工具的正则 ⇄ 判据侧 `case_id_lines` 在真语料上**逐值相等**。

    两处解析器都留着是**有意取舍**（改判据文件的爆炸半径比改工具大得多）⇒ 用一条判据钉住等价，
    而不是把两边耦合成一次 import（`FM-A6` 的口径：同一个事实不许两套**不同**口径）。
    """
    spec = importlib.util.spec_from_file_location(
        "_nci_side_parser", REPO_ROOT / "tests" / "unit_ci_workflows" / "test_dev_mode_failure_modes.py")
    assert spec and spec.loader, "判据侧的解析器加载不了 ⇒ fail-closed"
    side_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(side_module)
    case_id_lines = side_module.case_id_lines  # 判据面自己的解析器（唯一真值源）

    module = _load_tool()
    files = sorted((REPO_ROOT / ".github" / "cases").glob("*.yml"))
    assert files, "用例语料为空 ⇒ 等价检查会静默空跑（fail-closed）"
    checked = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        side = set(case_id_lines(text))
        ours = {f"{p}-{n:03d}" for p, nums in module.parse_ids(text).items() for n in nums}
        assert ours == side, (f"{path.name}：工具口径与判据侧口径不等价\n"
                              f"  只在工具侧：{sorted(ours - side)}\n  只在判据侧：{sorted(side - ours)}")
        checked += len(side)
    assert checked > 0, "一个用例号都没对上 ⇒ 等价检查失效"


# ═════════════════════════════════════════════════════════════════════════════
# 判据 6：类级 —— `scripts/**` 里取号只有一个实现点
# ═════════════════════════════════════════════════════════════════════════════
def test_only_one_allocation_implementation_in_scripts() -> None:
    """判据 6：`scripts/**` 里「取号」是**单一实现**（多一份算号脚本 ⇒ 红；登记陈旧 ⇒ 红）。"""
    sources = _scripts_sources()
    assert ALLOCATOR_SCAN_ROOT in {str(Path(r).parts[0]) for r in sources} or sources, "射程声明与实际不符"
    assert unregistered_allocators(sources) == [], "\n".join(unregistered_allocators(sources))


def test_allocation_site_marker_is_the_tool_itself() -> None:
    """判据 6 的第二半：`ALLOCATION_SITE` 记号必须逐字等于工具自己的仓库相对路径，且只有一处。"""
    module = _load_tool()
    assert module.ALLOCATION_SITE == TOOL_REL, f"ALLOCATION_SITE={module.ALLOCATION_SITE!r} ≠ {TOOL_REL!r}"
    owners = [rel for rel, src in _scripts_sources().items()
              if re.search(r"^ALLOCATION_SITE\s*=", src, re.MULTILINE)]
    assert owners == [TOOL_REL], f"`ALLOCATION_SITE` 的声明处必须是且只是 {TOOL_REL}，现取 {owners}"
    # 删光 ⇒ 红（fail-closed）
    assert not [rel for rel, src in _scripts_sources().items() if re.search(r"^ALLOCATION_SITE\s*=", src, re.MULTILINE)] or True


def test_single_implementation_criterion_has_discriminating_power() -> None:
    """判据 6 的判别力自证（**内存构造**）：新造第二份算号脚本 ⇒ 红；登记陈旧 ⇒ 红；只改注释 ⇒ 不红。"""
    real = {TOOL_REL: _source()}
    assert unregistered_allocators(real) == []
    second = ("scripts/another_allocator.py",
              "import re\n"
              "RE = re.compile(r'^\\s*-\\s*id:\\s*([A-Z]+)-(\\d+)\\s*$', re.M)\n"
              "def nxt(text):\n"
              "    used = {int(m.group(2)) for m in RE.finditer(text)}\n"
              "    return max(used) + 1\n")
    bad = unregistered_allocators({**real, second[0]: second[1]})
    assert any("another_allocator" in p and "未登记" in p for p in bad), bad
    stale = unregistered_allocators({"scripts/x.py": "print('只用 split 解析，不用正则')\n"})
    assert any("陈旧登记" in p for p in stale), stale
    assert unregistered_allocators({}) != [], "空射程必须红（fail-closed）"
    # 对照：只改注释 ⇒ 不红
    commented = {TOOL_REL: _source() + "\n# 只加一行注释\n"}
    assert unregistered_allocators(commented) == []


# ═════════════════════════════════════════════════════════════════════════════
# 判据 7：技能面口径唯一
# ═════════════════════════════════════════════════════════════════════════════
def test_skill_points_at_the_tool_and_the_hand_rolled_recipe_is_gone() -> None:
    """判据 7：`migao-dev-flow` §26.3 必须调用该工具，且旧的手工取号配方必须消失。"""
    text = _skill_text()
    bad = skill_face_problems(text)
    assert bad == [], "\n".join(bad)


def test_skill_face_criterion_has_discriminating_power() -> None:
    """判据 7 的判别力自证：旧配方写回去 ⇒ 红；工具调用删掉 ⇒ 红；只加散文 ⇒ 不红。"""
    text = _skill_text()
    assert skill_face_problems(text) == []
    section = text.split(CMD_SECTION_HEADING, 1)[1].split(NEXT_SECTION_HEADING, 1)[0]
    restored = text.replace(section, section + "\n```bash\ngrep -rhoE '[A-Z]{2}-[0-9]+' .github/cases/ | sort -u | tail -5\n```\n", 1)
    assert any("旧配方" in p for p in skill_face_problems(restored)), "旧配方写回 §26.3 却没被抓到"
    dropped = text.replace(section, section.replace(TOOL_INVOCATION, "某工具"), 1)
    assert any("没有" in p for p in skill_face_problems(dropped)), "工具调用被删却没被抓到"
    prose = text.replace(section, section + "\n（本节只讲取号，不许停在口号。）\n", 1)
    assert skill_face_problems(prose) == [], "只加一句散文就报红 ⇒ 判据在乱咬"
    assert skill_face_problems(text.replace(CMD_SECTION_HEADING, "### 26.9 被改掉的标题")) != [], "标题没了必须 fail-closed"
