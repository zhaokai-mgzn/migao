# case_ids: MC-017
"""六个红证机具必须**真的有人调用**，且「腐烂」必须能被检出（issue #5193，L0 零 LLM、零网络）。

## 缺陷（issue #5193，独立验收锚 `c5adc883d`，非推断）

    git grep -nE "red-proof|red_proof" origin/main -- '.github/workflows/' verify-all.sh
    ⇒ 零命中

`scripts/{pool-board,saving-metrics-red-proof-backend,saving-metrics-red-proof-web,auto-batch,
auto-batch-due-scan,cutting-plan}-red-proof*.py` 六个机具**真实存在且可执行**，却**没有任何
CI / 门禁调用它们** ⇒ 「每条断言都要有红证」落地成了**手工动作**。手工动作的结局是**静默腐烂**：
被测源码一重构，注入锚点（源码原文片段）就对不上；判据方法一改名，「期望变红」的目标就不存在
—— 而**没有任何东西会因此变红**（本仓反复点名的「不会红的断言 = 空断言」的同族形态：
**没人跑的红证机具 = 没有红证**）。

## 本守卫锁什么（每条判据都带注入式红证）

1. **接线**（纯文本判据 + 注入验证判别力）：`verify-all.sh` 的 `gate` 档必须按「命中红证面」派发
   `redproof_preflight()` 作为**独立检查项**、未命中时**显式声明「未跑」**且不得出现 ✅；
   `redproof` 实跑档必须对**每个**机具都有**实跑**调用（不带 `--check`）。
   红证 = 把派发/调用/未跑声明逐条删掉 ⇒ 接线判据必须变红。
2. **机具真的能被调用**：逐个**真跑子进程** `python3 scripts/<机具> --check`（不是 import）——
   退出 0、打印统一报告行、声明条数 ≥ 登记下限 `TOOLS[tool].floor`。
3. **腐烂可检出（三类注入，逐机具各一条参数化用例）**：
   ① 被守卫**文件消失**；② 被守卫源码**标识符改名**（= 注入锚点失配，模拟源码重构）；
   ③ 「期望变红」的**判据改名/判据文件消失**。三者都必须让 `--check` **非零退出并具名报出**；
   注入前后按 **sha256 内容指纹**自证、`finally` 里**逐字节还原**，随后复跑必须**回到绿**
   （对照组：证明「红」是注入造成的，不是本来就红）。
4. **机具被削弱可检出**：从机具源码里**删掉一条变异**（`ast` 定位模块级 `MUTATIONS` 列表字面量的
   最后一个元素，按行号删除）⇒ 登记表判据必须红 —— 这正是 issue #5193 判据 1 的形态
   （「把某条变异从机具里删掉 ⇒ 门禁红」）。
5. **接线腿不吞退出码（三态，真跑 shell）**：抽出 `redproof_preflight()` 在桩环境里跑：
   桩机具非零 ⇒ 腿**非零**（不许 `|| true` / `set +e` 吞掉）；没有机具（桩仓库，如
   `tests/unit_ci_workflows` 里复制本脚本的最小仓库）⇒ 显式「未跑」且**不红**；桩机具绿 ⇒ 腿绿。
6. **三态退出码契约**：`report_and_exit` 的 `0`（全绿）/ `1`（有腐烂）/ `3`（无法判定 = 没有声明）。

## 为什么不是「实跑」在 CI 里（边界，如实登记）

实跑 = 真注入 + 真跑判据，实测单机具 **107s ~ __ELAPSED_CP__**（`cutting-plan` 逐条判据强制重编译
35 次 Maven），且要 JDK / npm / PG 二进制 ⇒ 接进任何**每 PR** 的 required job 都会显著变慢
（`ci workflow helper unit tests` 的 `timeout-minutes: 8` 前科见 #5170：+269s 即被自身超时 CANCELLED）。
⇒ 本守卫只把**前提面**（零依赖、~0.1s/机具）接进 CI；**实跑面**的入口 =
`./verify-all.sh redproof`（本地可直接跑，三态 + 「未跑」显式声明），未接 CI —— 该边界在此登记。

⚠️ **并发假红（实测登记）**：`--check` 读工作区原文 ⇒ 与**实跑**并发时会把「刚注入的变异」读成
「腐烂」（实测：`cutting-plan` 跑 M5 期间 `--check` 报「M5 锚点命中 0 次」，而 `origin/main`
原文命中 1 次）。本守卫与实跑**不并发**（CI 不跑实跑；`redproof` 档先自检后实跑），
本机手工并发时等实跑结束再定论。

## 缓存卫生（为什么不复用 `scripts/red_proof.py` 的清缓存纪律）

`migao-acceptance` 的红证纪律（注入前后清缓存 + 内容指纹）针对的是**被 import 的 Python 模块**
（同秒同长度替换 ⇒ `.pyc` 被复用 ⇒ 注入未生效）。本文件的注入对象是 ① 机具脚本（**以 `__main__`
执行，CPython 不为其写/读 `.pyc`**；且文件名带 `-`，**根本无法被 import**）与
② Java/TS/SQL 源文件（不经 Python 导入系统）⇒ 该形态**结构上不可达**。故这里用
**sha256 内容指纹自证注入/还原**（`_injected`），不调用 `clear_caches()` —— 后者会顺手删掉
`target/classes` / `.next/cache` / `node_modules/.vite`，把 CI 的编译缓存打掉。
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
VERIFY_ALL = REPO_ROOT / "verify-all.sh"
SCRIPT_TEXT = VERIFY_ALL.read_text(encoding="utf-8")

# append（不是 insert）：只作兜底解析路径，避免遮蔽同名模块。
sys.path.append(str(SCRIPTS))

import red_proof_harness as harness  # noqa: E402

TOOL_RELS = sorted(harness.TOOLS)
_CHECK_TIMEOUT = 180

#: 统一报告行（`harness.counts_line()` 的形态）—— 机具必须逐字打印它，「没跑」才长得像「没跑」。
COUNTS_RE = re.compile(
    r"前提自检：跑了 (?P<ok>\d+) 条 / 未跑 (?P<bad>\d+) 条（腐烂）｜"
    r"实跑未跑 (?P<heavy>\d+) 条（原因：需 (?P<why>.+?)；入口 \./verify-all\.sh redproof）"
)
#: 注入用的标识符词表：只取「机具源码里出现过、且被守卫源码里也有」的名字（见 `_rot_source`）。
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{4,}")


# ── 文本层工具（与同族守卫同款：剥注释 + 抽顶层 case 分支）────────────────────

def _code_of(text: str) -> str:
    """剥掉注释后的**代码行** —— 注释里会出现 `redproof_preflight` 等字样，裸 grep 会假绿。"""
    return "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())


def _mode_branch(text: str, mode: str) -> str:
    """抽取顶层 `case "$MODE" in` 里 `mode)` 分支（到 `;;` 为止，已剥注释）。"""
    lines = _code_of(text).splitlines()
    start = next((i for i, ln in enumerate(lines) if 'case "$MODE" in' in ln), -1)
    assert start >= 0, 'verify-all.sh 里找不到顶层 `case "$MODE" in`'
    for i in range(start, len(lines)):
        if lines[i].strip() == f"{mode})":
            body, j = [], i + 1
            while j < len(lines) and lines[j].strip() != ";;":
                body.append(lines[j])
                j += 1
            assert j < len(lines), f"`{mode})` 分支没有被 `;;` 结束"
            return "\n".join(body)
    raise AssertionError(f"verify-all.sh 顶层 case 里找不到 `{mode})` 分支")


def _wiring_problems(text: str) -> list[str]:
    """接线判据（**纯函数** ⇒ 可对文本注入验证判别力，见 `test_wiring_removal_is_caught`）。"""
    problems: list[str] = []
    try:
        gate = _mode_branch(text, "gate")
    except AssertionError as exc:
        return [f"gate 档抽不出来：{exc}"]
    if "redproof_face_hit" not in gate:
        problems.append("gate 档没有按「命中红证面」判定就派发（会把不碰红证面的 PR 卡住）")
    if not re.search(r'^\s*report\s+"[^"]*前提自检[^"]*"\s+redproof_preflight\s*$', gate, re.M):
        problems.append("gate 档命中红证面时没有把 redproof_preflight 作为独立检查项真跑")
    if not re.search(r"红证机具门禁.*未跑", gate):
        problems.append("gate 档未命中红证面时必须显式声明「未跑」（不许静默通过）")
    try:
        heavy = _mode_branch(text, "redproof")
    except AssertionError as exc:
        return problems + [f"redproof 实跑档抽不出来：{exc}"]
    if not re.search(r'^\s*report\s+"[^"]*前提自检[^"]*"\s+redproof_preflight\s*$', heavy, re.M):
        problems.append("redproof 档没有跑前提自检")
    for tool in TOOL_RELS:
        name = tool.split("/", 1)[1]
        lines = [ln for ln in heavy.splitlines() if name in ln]
        if not lines:
            problems.append(f"redproof 实跑档没有调用 {name}")
        elif any("--check" in ln for ln in lines):
            problems.append(f"{name} 在实跑档被换成了 --check（实跑面被摘掉）")
    return problems


# ── 子进程 + 注入（都只在仓库根跑，绝不并发：pytest 默认串行）────────────────

def _run_check(tool_rel: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, tool_rel, "--check"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=_CHECK_TIMEOUT,
    )


def _check_green(tool_rel: str) -> str:
    """跑一次 `--check` 并断言**真跑了且全绿**；返回 stdout（供解析报告行）。"""
    r = _run_check(tool_rel)
    assert r.returncode == harness.OK, (
        f"{tool_rel} --check 应退出 0，实得 {r.returncode}\n--- stdout ---\n{r.stdout}\n"
        f"--- stderr ---\n{r.stderr}")
    return r.stdout


def _counts_of(out: str, tool_rel: str) -> re.Match:
    m = COUNTS_RE.search(out)
    if m is None:
        raise AssertionError(
            f"{tool_rel} --check 没有打印统一报告行（「没跑」必须长得像「没跑」）：\n{out[-800:]}")
    return m


@contextlib.contextmanager
def _injected(rel: str, mutate):
    """把 `rel` 的内容换成 `mutate(原文)`，跑完（含异常）**逐字节还原**并按 sha256 自证。

    原字节同时留在内存与磁盘（`assert` 自证）⇒ 还原失败即**大声失败**，绝不静默留下变异源码。
    """
    path = REPO_ROOT / rel
    original = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()
    mutated = mutate(original)
    assert mutated != original, f"注入没有改变 {rel} ⇒ 判据无从判定（注入未生效，不是「通过」）"
    path.write_text(mutated, encoding="utf-8")
    try:
        yield
    finally:
        path.write_text(original, encoding="utf-8")
        now = hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        assert now == digest, f"{rel} 未还原（sha256 不符）—— 停手，先人工核对"


@contextlib.contextmanager
def _moved_away(rel: str):
    """把文件暂时挪走（比「写坏内容」更安全：原字节始终在磁盘上，任何路径都能还原）。"""
    path = REPO_ROOT / rel
    aside = path.with_name(path.name + ".rot-aside")
    assert path.is_file(), f"{rel} 不在（前置不成立）"
    assert not aside.exists(), f"{aside.name} 已存在 ⇒ 上一次注入没清干净，先人工核对"
    path.rename(aside)
    try:
        yield
    finally:
        if aside.exists():
            aside.rename(path)
        assert path.is_file(), f"{rel} 未还原 —— 停手人工核对"


def _rot_source(tool_rel: str, impl_rel: str):
    """注入②：把「机具源码里出现过、被守卫源码里也有」的标识符统一改名（模拟源码重构）。

    词表取自**机具自身**（单一事实源）⇒ 只动机具真正依赖的那些名字，其余部分保持原样
    （改名后仍是合法标识符，不会把文件弄成语法错误）。
    """
    tool_text = (REPO_ROOT / tool_rel).read_text(encoding="utf-8")
    impl_text = (REPO_ROOT / impl_rel).read_text(encoding="utf-8")
    names = {m for m in _IDENT_RE.findall(tool_text) if m in impl_text}
    assert names, (
        f"{impl_rel} 里没有任何「{tool_rel} 源码中出现过的标识符」⇒ 注入无从进行"
        f"（机具结构变了就同步本守卫）")

    def mutate(text: str) -> str:
        out = text
        for name in sorted(names, key=len, reverse=True):
            out = out.replace(name, name + "_ROT")
        return out

    return mutate


def _first_target(out: str) -> str:
    """从 `--check` 输出取第一条「期望变红」的目标（守卫不必自己知道判据名）。"""
    m = re.search(r"→ 期望变红：(.+)", out)
    if m is None:
        raise AssertionError(f"--check 输出里找不到「期望变红」行：\n{out[-800:]}")
    return m.group(1).split("、")[0].strip()


def _rot_criteria(tool_rel: str, target: str):
    """注入③：按目标形态选一种「判据腐烂」——判据文件挪走 / 方法改名。

    目标形态有三种（都由 `--check` 输出决定，守卫不必自己知道判据名）：`Class#method`
    （真库机具）/ 纯方法名（Java 机具）/ 文件路径（web 机具的判据面是文件存在性）。
    """
    spec = harness.TOOLS[tool_rel]
    if "#" in target:
        target = target.split("#", 1)[1].strip()
    if "/" in target or target.endswith((".ts", ".tsx")):
        # web 机具的判据面是**文件存在性**（`TESTS`）⇒ 让第一个判据文件消失。
        rel = next((c for c in spec.criteria if c.endswith(target)), None)
        assert rel, f"{tool_rel} 的目标 {target!r} 不在登记表 criteria 里（登记表漂移了？）"
        return "moved", rel
    return "renamed", target


def _rename_method(text: str, method: str) -> str:
    out = re.sub(rf"(?<![\w.]){re.escape(method)}(\s*\()", rf"{method}_ROT\1", text)
    assert out != text, f"判据源码里找不到方法 {method} ⇒ 注入无从进行"
    return out


def _mutation_element_lines(tool_rel: str) -> tuple[int, int]:
    """`MUTATIONS = [...]` 里**最后一个元素**的起止行号（1-based，含）——删掉它 = 削弱机具。"""
    text = (REPO_ROOT / tool_rel).read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign):
            target, value = node.targets[0], node.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id == "MUTATIONS" and isinstance(value, ast.List):
            last = value.elts[-1]
            return last.lineno, last.end_lineno
    raise AssertionError(
        f"{tool_rel} 的模块级 MUTATIONS 不是列表字面量 —— 结构变了就同步本守卫")


def _drop_last_mutation(text: str, span: tuple[int, int]) -> str:
    first, last = span
    lines = text.splitlines(keepends=True)
    return "".join(lines[:first - 1] + lines[last:])


def _extract_fn(name: str) -> str:
    """从 `verify-all.sh` 抽出 `name() { ... }`（结束于第 0 列的 `}`）——同族守卫的既有口径。"""
    m = re.search(rf"^{name}\(\) \{{[\s\S]*?^\}}", SCRIPT_TEXT, re.M)
    if m is None:
        raise AssertionError(f"verify-all.sh 里抽不出 {name}() —— 结构变了就同步本守卫")
    return m.group(0)


def _shell_harness(snippet: str) -> str:
    """装三个红证函数 + 桩环境，真跑一遍（三态的行为判据，不是文本 grep）。"""
    return ("set -uo pipefail\n"
            + _extract_fn("redproof_face_paths") + "\n"
            + _extract_fn("redproof_face_hit") + "\n"
            + _extract_fn("redproof_preflight") + "\n"
            + snippet)


def _bash(code: str, cwd: Path):
    return subprocess.run(["bash", "-c", code], capture_output=True, text=True,
                          cwd=str(cwd), timeout=60)


# ══════════════════ ① 接线（含注入式红证） ══════════════════

class TestWiring:
    """`gate` 命中才派发 + 显式「未跑」；`redproof` 档逐机具实跑；红证 = 删掉接线即变红。"""

    def test_real_script_passes_the_wiring_judgment(self):
        assert _wiring_problems(SCRIPT_TEXT) == [], (
            "verify-all.sh 的红证机具接线不完整：" + repr(_wiring_problems(SCRIPT_TEXT)))

    def test_gate_branch_has_no_pass_mark_on_the_not_run_path(self):
        gate = _mode_branch(SCRIPT_TEXT, "gate")
        assert "✅" not in gate, "gate 档分支里不得出现 ✅（「没跑」与「通过」必须可区分）"

    def test_wiring_removal_is_caught(self):
        """注入式红证（纯文本，零副作用）：三种「接线被摘掉」都必须被接线判据抓到。"""
        cases = {
            "gate 派发被删": SCRIPT_TEXT.replace(
                'report "红证机具前提自检（前提能否成立）" redproof_preflight', "", 1),
            "实跑被换成 --check": SCRIPT_TEXT.replace(
                "python3 '$ROOT/scripts/pool-board-red-proof.py'",
                "python3 '$ROOT/scripts/pool-board-red-proof.py' --check", 1),
            "未跑声明被删": SCRIPT_TEXT.replace(
                "红证机具门禁**未跑**", "红证机具门禁已就绪", 1),
            "实跑档被整段删掉": SCRIPT_TEXT.replace("  redproof)\n", "  never-used-mode)\n", 1),
        }
        for label, mutated in cases.items():
            assert mutated != SCRIPT_TEXT, f"{label}：注入没生效（锚点失配）—— 同步本守卫"
            assert _wiring_problems(mutated), f"{label}：接线判据没有变红 ⇒ 它是空断言"

    def test_face_judgment_is_load_bearing(self):
        """红证面判定必须**同时**做到「命中」与「不命中」（否则要么卡无关 PR，要么永不触发）。"""
        r_hit = _bash(_shell_harness(
            'CHANGE_SET=backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java\n'
            "redproof_face_hit && echo HIT || echo NOHIT"), REPO_ROOT)
        assert r_hit.stdout.strip().endswith("HIT"), r_hit.stdout + r_hit.stderr
        r_miss = _bash(_shell_harness(
            "CHANGE_SET=verify-all.sh\nbackend/admin-api/src/main/java/Demo.java\n"
            "redproof_face_hit && echo HIT || echo NOHIT"), REPO_ROOT)
        assert r_miss.stdout.strip().endswith("NOHIT"), r_miss.stdout + r_miss.stderr


# ══════════════════ ② 机具真的能被调用 ══════════════════

class TestHarnessRegistry:
    """登记表 = 机具的单一事实源；机具集合、路径、声明条数下限三者必须对得上。"""

    def test_every_red_proof_tool_is_registered(self):
        found = sorted(p.name for p in SCRIPTS.glob("*-red-proof*.py"))
        assert found, "scripts/ 下找不到任何红证机具（目录变了就同步本守卫）"
        registered = sorted(Path(t).name for t in TOOL_RELS)
        assert found == registered, f"机具与登记表不一致：实得 {found} / 登记 {registered}"

    def test_registry_guarded_paths_exist(self):
        missing = [rel for spec in harness.TOOLS.values()
                   for rel in (*spec.impl, *spec.criteria) if not (REPO_ROOT / rel).is_file()]
        assert missing == [], f"登记表里的被守卫路径不存在（漂移了）：{missing}"

    @pytest.mark.parametrize("tool", TOOL_RELS)
    def test_check_runs_and_reports_counts(self, tool):
        out = _check_green(tool)
        m = _counts_of(out, tool)
        declared = int(m.group("ok")) + int(m.group("bad"))
        assert declared >= harness.TOOLS[tool].floor, (
            f"{tool} 的前提自检覆盖 {declared} 条 < 登记下限 {harness.TOOLS[tool].floor}")
        assert int(m.group("bad")) == 0, f"{tool} 有腐烂的前提：\n{out[-800:]}"


# ══════════════════ ③ 腐烂必须被检出（三类注入，逐机具） ══════════════════

class TestRotIsCaught:
    """三类注入都必须让 `--check` 非零退出并具名报出；还原后复跑必须回到绿。"""

    @pytest.mark.parametrize("tool", TOOL_RELS)
    def test_missing_guarded_file_is_rot(self, tool):
        rel = harness.TOOLS[tool].impl[0]
        with _moved_away(rel):
            r = _run_check(tool)
            assert r.returncode == harness.ROT, (
                f"{tool}：被守卫文件 {rel} 消失时 --check 应判「有腐烂」，实得 {r.returncode}\n"
                f"{r.stdout[-600:]}")
            assert rel in r.stdout, f"{tool} 的腐烂未被具名（{rel} 不在输出里）：\n{r.stdout[-600:]}"
        _check_green(tool)   # 对照组：还原后必须回到绿

    @pytest.mark.parametrize("tool", TOOL_RELS)
    def test_source_refactor_is_rot(self, tool):
        rel = harness.TOOLS[tool].impl[0]
        with _injected(rel, _rot_source(tool, rel)):
            r = _run_check(tool)
            assert r.returncode == harness.ROT, (
                f"{tool}：被守卫源码标识符改名（注入锚点失配）后 --check 应判「有腐烂」，"
                f"实得 {r.returncode}\n{r.stdout[-600:]}")
            assert "锚点" in r.stdout, (
                f"{tool} 的腐烂未被归因到「注入锚点失配」：\n{r.stdout[-600:]}")
        _check_green(tool)

    @pytest.mark.parametrize("tool", TOOL_RELS)
    def test_renamed_criterion_is_rot(self, tool):
        out = _check_green(tool)
        kind, payload = _rot_criteria(tool, _first_target(out))
        if kind == "moved":
            with _moved_away(payload):
                r = _run_check(tool)
                assert r.returncode == harness.ROT, (
                    f"{tool}：判据文件 {payload} 消失后 --check 应判「有腐烂」，"
                    f"实得 {r.returncode}\n{r.stdout[-600:]}")
        else:
            hit = [c for c in harness.TOOLS[tool].criteria
                   if re.search(rf"(?<![\w.]){re.escape(payload)}\s*\(", (REPO_ROOT / c).read_text(
                       encoding="utf-8"))]
            assert hit, f"{tool} 的目标判据 {payload} 不在登记表的 criteria 源码里（漂移了？）"
            with _injected(hit[0], lambda text: _rename_method(text, payload)):
                r = _run_check(tool)
                assert r.returncode == harness.ROT, (
                    f"{tool}：判据方法 {payload} 改名后 --check 应判「有腐烂」，"
                    f"实得 {r.returncode}\n{r.stdout[-600:]}")
                assert payload in r.stdout, (
                    f"{tool} 的腐烂未被具名（{payload} 不在输出里）：\n{r.stdout[-600:]}")
        _check_green(tool)

    @pytest.mark.parametrize("tool", TOOL_RELS)
    def test_deleting_a_mutation_is_rot(self, tool):
        """issue #5193 判据 1 的形态：把一条变异从机具里删掉 ⇒ 登记表判据必须红。"""
        span = _mutation_element_lines(tool)
        with _injected(tool, lambda text: _drop_last_mutation(text, span)):
            r = _run_check(tool)
            assert r.returncode == harness.ROT, (
                f"{tool}：删掉一条变异后 --check 应判「有腐烂」（机具被削弱），"
                f"实得 {r.returncode}\n{r.stdout[-800:]}")
            assert "被削弱" in r.stdout, f"{tool} 没有把腐烂归因到「机具被削弱」：\n{r.stdout[-800:]}"
        _check_green(tool)


# ══════════════════ ④ 接线腿的三态 + 不吞退出码（真跑 shell） ══════════════════

class TestLegTriState:
    """`redproof_preflight()`：桩机具非零 ⇒ 腿非零；无机器具 ⇒ 显式「未跑」且不红；桩绿 ⇒ 腿绿。"""

    def _stub_tool(self, tmp_path: Path, rc: int) -> str:
        stub = tmp_path / "scripts" / "stub-red-proof.py"
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text(f"import sys\nprint('桩机具：前提自检跑了 1 条 / 未跑 0 条')\n"
                        f"sys.exit({rc})\n", encoding="utf-8")
        return str(tmp_path)

    def test_nonzero_tool_makes_the_leg_nonzero(self, tmp_path):
        root = self._stub_tool(tmp_path, 1)
        r = _bash(_shell_harness("redproof_preflight; echo LEG_RC=$?"), Path(root))
        assert "LEG_RC=1" in r.stdout, f"机具非零时腿必须非零（吞码 = 假绿）：\n{r.stdout}{r.stderr}"

    def test_green_tool_makes_the_leg_green(self, tmp_path):
        root = self._stub_tool(tmp_path, 0)
        r = _bash(_shell_harness("redproof_preflight; echo LEG_RC=$?"), Path(root))
        assert "LEG_RC=0" in r.stdout, f"机具全绿时腿应为 0：\n{r.stdout}{r.stderr}"

    def test_no_tool_is_explicit_not_run_and_not_red(self, tmp_path):
        """桩仓库（无 `scripts/*-red-proof.py`）⇒ 显式「未跑」+ 非零**不得**出现。"""
        (tmp_path / "scripts").mkdir()
        r = _bash(_shell_harness("redproof_preflight; echo LEG_RC=$?"), tmp_path)
        assert "LEG_RC=0" in r.stdout, f"无机器具时腿不得判红（桩仓库会被打红）：\n{r.stdout}{r.stderr}"
        assert "未跑" in r.stdout and "::warning::" in r.stdout, (
            f"无机器具必须显式声明「未跑」（并抬到控制台）：\n{r.stdout}{r.stderr}")

    def test_real_leg_is_green_with_the_real_tools(self):
        r = _bash(_shell_harness("redproof_preflight; echo LEG_RC=$?"), REPO_ROOT)
        assert "LEG_RC=0" in r.stdout, f"真实机具下前提自检必须全绿：\n{r.stdout[-1500:]}{r.stderr}"


# ══════════════════ ⑤ 三态退出码契约 ══════════════════

class TestExitCodeContract:
    """`0` 全绿 / `1` 有腐烂 / `3` 无法判定 —— 「没跑」不得被读成「通过」。"""

    def test_unknown_when_nothing_is_declared(self, capsys):
        tool = "scripts/pool-board-red-proof.py"
        assert harness.report_and_exit(tool, []) == harness.UNKNOWN
        assert "无法判定" in capsys.readouterr().out

    def test_rot_when_tool_is_unregistered(self, capsys):
        decl = harness.Declaration("x", "y", True)
        assert harness.report_and_exit("scripts/nope-red-proof.py", [decl]) == harness.ROT
        assert "未登记" in capsys.readouterr().out

    def test_ok_only_when_every_declaration_holds(self, capsys):
        """声明条数达到登记下限且全部成立 ⇒ `0`；任一条腐烂 ⇒ `1`（且具名）。"""
        tool = "scripts/pool-board-red-proof.py"
        good = [harness.Declaration(f"m{i}", "y", True) for i in range(harness.TOOLS[tool].floor)]
        bad = good + [harness.Declaration("rot", "y", False, "注入锚点命中 0 次")]
        assert harness.report_and_exit(tool, good) == harness.OK
        capsys.readouterr()
        assert harness.report_and_exit(tool, bad) == harness.ROT
        out = capsys.readouterr().out
        assert "腐烂" in out, out
        assert "注入锚点命中 0 次" in out, out

    def test_weakened_floor_is_rot(self, capsys):
        """声明条数**低于**登记下限（= 有人删了变异）⇒ `1`，且归因到「机具被削弱」。"""
        tool = "scripts/pool-board-red-proof.py"
        short = [harness.Declaration("m", "y", True)]
        assert harness.report_and_exit(tool, short) == harness.ROT
        assert "被削弱" in capsys.readouterr().out
