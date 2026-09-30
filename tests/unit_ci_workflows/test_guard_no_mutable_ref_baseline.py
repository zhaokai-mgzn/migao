# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""判据面**不得**把基线绑在「浅克隆下不可达的可变引用」上 —— issue #5814（本仓**第二次**踩同族）。

## 病：同一个机制，两个实例（都不是推断，各有实测）

| 实例 | 判据 | 形态 | 后果 |
|---|---|---|---|
| 第一次（#4313 / 实证 PR #4320） | `tests/unit_ci_workflows/test_admin_web_devserver_identity.py` | `git show origin/main:<path>` 取基线 | CI 里 `origin/main` **不可达** ⇒ 原写法走 **skip**（`1 skipped`）⇒ **CI 看不出问题**（最坏的一种：假绿） |
| 第二次（#5814 / 本 PR） | `tests/unit_ci_workflows/test_deploy_breaker_allowlist.py::test_build_step_keeps_existing_semantics` | 同一个形态 `git show origin/main:<path>` 取基线 | CI 里取不到 ⇒ `stdout` 为空（`capture_output=True` 把 stderr 吞掉）⇒ 基线退化成**空集** ⇒ 判据**恒红**（CI `1 failed, 5706 passed`；同一份代码**本机 `3 passed`**） |

**为什么 CI 取不到**（现取，不是推断）：跑本目录的 job 是 `.github/workflows/pr-check.yml`
的 `ci-workflow-tests`（`name: ci workflow helper unit tests`），它的 checkout 是**裸**
`actions/checkout@v7` —— **不给 `fetch-depth`** ⇒ 默认 **`fetch-depth: 1`（浅克隆）**
⇒ `origin/main` 这个 ref 在 job 的仓库里**根本不存在**。

⇒ 两次都**没有**任何机械锁会拦住「新判据又绑一个可变引用」。本文件落这把锁。

## 判据（未登记即红 / 台账只许缩短 / 台账不为存量背书）

1. **逐文件 AST 扫描**：找「**运行 git 的调用**」（`subprocess.run` / `check_output` / `Popen`
   / 同族，以及本仓判据常用的 `_out(work, …)` 包装）实参里出现的 `origin/<name>:` 形态
   **字符串**（含 `f"origin/main:{REL}"` 与 `"origin/main:x" + wf` 两种拼法）。
   命中 ⇒ 该文件必须在 `MUTABLE_REF_BASELINE` 里**逐字登记**（带 `why`）：**未登记即红**。
2. **反向**：台账里登记了**现取已不命中**的条目 ⇒ 红（**只许缩短**；修好一处就必须同步缩表）。
3. **台账不为存量背书**：它只把「已知 + 已具名理由」的那几处**显式化**，让它们可被检索、可被质疑；
   本判据**不**主张那几处是安全的（各自 `why` 说明为什么在那个**局部**成立）。

## 为什么用 AST + 「运行 git 的调用」限定（而不是朴素正则扫原文）

朴素的「扫原文找 `origin/main`」会有**两类假红**，都会把这条锁变成噪声（然后被关掉）：

- **注释 / 文档字符串里的纪律文字**：本仓有**大量**「不要读 `origin/main`」的说明
  （`test_admin_web_devserver_identity.py` / `test_swas_deploy_*.py` / `test_contract_ledger_reject_codes.py` …）
  ⇒ AST 里注释与 docstring 不是调用实参，结构上不可能被读成「取基线」；
- **字符串操纵**：如 `test_flaky_ledger_reconcile.py` 的
  `REAL_TRIAGE.replace("git show origin/main:…", …)` —— 它**不跑 git**，只是在**文本上做红证**；
  被调用的函数是 `str.replace`，不在「运行 git 的调用」集合里 ⇒ **不命中**（两条负控判据钉住这一点）。

## 残余（照实登记，不粉饰）

① 「运行 git 的调用」是**具名集合**（`RUNNER_CALLS`）—— 全新造一个**别的名字**的 git 包装函数、
   且它读可变引用 ⇒ 本判据**不命中**（假阴性）。反向的锁是：本仓判据面**已经**把
   `subprocess` 直用收敛到少数几处，新增包装会先出现在 `grep -rn "subprocess" tests/unit_ci_workflows/` 里；
② 射程 = **`tests/unit_ci_workflows/*.py`**（本 job 跑的判据面）；`.github/*.py` / `scripts/*.py`
   里的同类写法**不在面内**（那些脚本不在浅克隆的 pr-check job 里跑判据，风险面不同）；
③ 「`origin/<name>:`」是**形态**判定：把 ref 拆成两段字符串（`"origin/" + "main:x"`）能绕过
   （本判据**不**追求对抗性完备 —— 它拦的是**顺手写出来**的形态，那正是两次实例的形态）；
④ 射程内的命中**只做登记**：本判据不判断「那处到底可不可达」（判不了，需要运行时上下文）。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARDS_DIR = REPO_ROOT / "tests" / "unit_ci_workflows"
SELF = Path(__file__).name

# ── 「运行 git 的调用」的具名集合（见 docstring 残余①）───────────────────────────
RUNNER_CALLS = frozenset({
    "run", "check_output", "check_call", "call", "Popen", "popen",
    "getoutput", "getstatusoutput",
    # 本仓判据面常用的 git 包装（`_out(work, "show", "origin/main:x")` 就是这一族）
    "_out", "_git", "_run_git", "_sh", "sh", "git",
})

# 可变远端引用的**形态**：`origin/<name>:`（后随路径 / f-string 占位）
MUTABLE_REF = re.compile(r"\borigin/[A-Za-z0-9._/-]+:")

# ── 台账（**只许缩短**：条目必须逐字等于现取命中集合）────────────────────────────
# 现取（`python3 -m pytest tests/unit_ci_workflows/test_guard_no_mutable_ref_baseline.py -q -s`）：
# 射程内命中 **1** 个文件。每条的 `why` 必须说明「为什么那个局部是安全的」。
MUTABLE_REF_BASELINE = {
    "test_sync_main_case_surface_guard.py": (
        "`_out(work, \"show\", f\"origin/main:{CASES_REL}\")` 里的 `work` 是 `_build_repo(tmp_path)` "
        "**自建的临时仓库**（它自己 `update-ref refs/remotes/origin/main`）⇒ 该 `origin/main` "
        "与 CI 的浅克隆无关、永远可达。**不是**「读主仓的 origin/main」。"
    ),
}


# ══════════════════════════════════════════════════════════════════════════
# 扫描器（纯函数：源码字符串 ⇒ 命中行号列表）
# ══════════════════════════════════════════════════════════════════════════

def _callee_name(func: ast.AST) -> str:
    """取调用名的**末段**：`subprocess.run` ⇒ `run`；`_out` ⇒ `_out`。"""
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _string_constants(node: ast.AST) -> list[str]:
    """递归收集实参里**能静态取到**的字符串（含 f-string 的字面量段）。"""
    out: list[str] = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        out.append(node.value)
    elif isinstance(node, ast.JoinedStr):
        for v in node.values:
            out.extend(_string_constants(v))
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for e in node.elts:
            out.extend(_string_constants(e))
    elif isinstance(node, ast.BinOp):
        out.extend(_string_constants(node.left))
        out.extend(_string_constants(node.right))
    elif isinstance(node, ast.Starred):
        out.extend(_string_constants(node.value))
    return out


def mutable_ref_hits(source: str, where: str = "<memory>") -> list[tuple[int, str]]:
    """→ [(行号, 命中片段)]；只认「**运行 git 的调用**」实参里的 `origin/<name>:` 形态。

    `where` = 出错时的定位信息（`ast.parse` 对语法错误要能指名是谁）。空源码 / 解析失败
    ⇒ **显式报错**（fail-closed，不静默给空集 —— 静默给空集正是本文件要治的那类假绿）。
    """
    tree = ast.parse(source, filename=where)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _callee_name(node.func) not in RUNNER_CALLS:
            continue
        for arg in [*node.args, *(kw.value for kw in node.keywords)]:
            for text in _string_constants(arg):
                m = MUTABLE_REF.search(text)
                if m:
                    hits.append((node.lineno, m.group(0)))
    return hits


def scanned_files() -> list[Path]:
    """射程 = `tests/unit_ci_workflows/*.py`（**非递归**：本 job 跑的就是这一层）。"""
    files = sorted(p for p in GUARDS_DIR.glob("*.py") if p.name != SELF)
    assert files, f"反空跑锚点：{GUARDS_DIR} 下一个判据文件都没扫到（射程写错了）"
    return files


def live_hits() -> dict[str, list[tuple[int, str]]]:
    """现取：命中文件 ⇒ 命中行号列表（**跳过自身**：本文件的纪律文字里满是该形态）。"""
    out: dict[str, list[tuple[int, str]]] = {}
    for path in scanned_files():
        hits = mutable_ref_hits(path.read_text(encoding="utf-8"), where=str(path))
        if hits:
            out[path.name] = hits
    return out


def baseline_problems(hits: dict[str, list[tuple[int, str]]], baseline: dict[str, str]) -> list[str]:
    """两个方向都比：未登记即红 + 台账陈旧即红（**只许缩短**）。纯函数 ⇒ 可注入红证。"""
    problems: list[str] = []
    for name in sorted(set(hits) - set(baseline)):
        lines = ", ".join(f"{ln}:{frag}" for ln, frag in hits[name])
        problems.append(
            f"{name}：判据面出现**未登记**的「读可变远端引用取基线」调用（{lines}）—— "
            "CI 的 `ci workflow helper unit tests` job 是**浅克隆**（`actions/checkout@v7` 不给 "
            "`fetch-depth`）⇒ `origin/main` 不可达 ⇒ 该判据会静默退化（空集 / skip / 自红）。"
            "修法（二选一）：① 基线改成**绝对口径**（冻结表 / 逐字内联的不可变片段）；"
            f"② 确实读的是**自建临时仓库**的 `origin/main` ⇒ 在 `{SELF}` 的 `MUTABLE_REF_BASELINE` "
            "里逐字登记并写明 `why`。"
        )
    for name in sorted(set(baseline) - set(hits)):
        problems.append(
            f"{name}：台账里的这条**已不再是缺口**（现取零命中）⇒ 台账只许缩短，请删掉它"
        )
    return problems


# ══════════════════════════════════════════════════════════════════════════
# 判据 1/2：现取命中 == 台账（未登记即红 / 陈旧即红）
# ══════════════════════════════════════════════════════════════════════════

def test_no_unregistered_mutable_ref_baseline():
    """🔴 承重：射程内任何「读可变远端引用取基线」的调用都必须登记（含 `why`）。"""
    hits = live_hits()
    problems = baseline_problems(hits, MUTABLE_REF_BASELINE)
    assert not problems, "\n".join(problems)


def test_scanner_is_not_vacuous():
    """反空跑：射程真的覆盖了本 job 的判据面，且登记的每一条**现取真的命中**。

    「扫了 0 个文件」或「台账是空的」都会让上面那条判据在**空集上恒真** ⇒ 这里钉住规模。
    （305 是现取值；这里取一个**下界**，避免每加一个判据文件就要改它。）
    """
    files = scanned_files()
    assert len(files) >= 250, f"射程只扫到 {len(files)} 个判据文件（远低于本 job 的判据面）⇒ 疑似射程写错"
    hits = live_hits()
    assert set(MUTABLE_REF_BASELINE) <= set(hits), (
        f"台账里的这些条目**现取不命中**（陈旧 / 写错文件名）：{sorted(set(MUTABLE_REF_BASELINE) - set(hits))}"
    )
    assert MUTABLE_REF_BASELINE, "台账为空 ⇒ 本判据在空集上恒真（若真已清零，请连判据一起重审）"
    for name, why in MUTABLE_REF_BASELINE.items():
        assert len(why.strip()) >= 20, f"{name}: 台账条目的 `why` 太短（必须说明那个局部为什么安全）"


def test_baseline_problems_have_discriminating_power():
    """🔴 红证（内存构造）：未登记的新命中 ⇒ 红；台账里多一条陈旧条目 ⇒ 红。"""
    real = live_hits()
    assert baseline_problems(real, MUTABLE_REF_BASELINE) == [], "前提：真数据先绿"
    injected = dict(real)
    injected["test_ghost_guard.py"] = [(42, "origin/main:")]
    assert baseline_problems(injected, MUTABLE_REF_BASELINE), "未登记的新命中没被拦下 ⇒ 空断言"
    stale = dict(MUTABLE_REF_BASELINE)
    stale["test_gone_guard.py"] = "已不存在的条目（红证）"
    assert baseline_problems(real, stale), "台账里的陈旧条目没被拦下 ⇒ 「只许缩短」没锁住"


def test_live_baseline_is_not_extendable_by_luck():
    """🔴 红证：台账**不许**被顺手放宽 —— 加一个「现取不命中」的条目 ⇒ 立刻红。"""
    grown = dict(MUTABLE_REF_BASELINE)
    grown["test_deploy_breaker_allowlist.py"] = "（本 PR 已修掉的那处，不许再登记回来）"
    problems = baseline_problems(live_hits(), grown)
    assert any("test_deploy_breaker_allowlist.py" in p for p in problems), (
        "把已修掉的文件登记回台账竟然不红 ⇒ 台账可以被用来掩盖回退"
    )


# ══════════════════════════════════════════════════════════════════════════
# 判据 3：扫描器的判别力 + 两条**负控**（防假红 —— 假红会让这条锁被关掉）
# ══════════════════════════════════════════════════════════════════════════

def test_scanner_flags_the_two_real_forms():
    """🔴 判据主体：把**两次实例**的形态喂给扫描器 ⇒ 必须命中（否则扫描器是空壳）。"""
    instance_1 = (
        "import subprocess\n"
        "def f():\n"
        "    return subprocess.run(['git', 'show', 'origin/main:x.py'], capture_output=True).stdout\n"
    )
    instance_2 = (
        "def g(work, REL):\n"
        "    return subprocess.check_output(['git', 'show', 'origin/main:' + REL], cwd=work)\n"
    )
    instance_3 = (
        "def h(work, REL):\n"
        "    return _out(work, 'show', f'origin/main:{REL}')\n"
    )
    for label, src in (("#4313 的形态", instance_1), ("拼接形态", instance_2), ("f-string 形态", instance_3)):
        assert mutable_ref_hits(src, where=label), f"{label} 没被扫描器命中 ⇒ 扫描器无判别力"


def test_scanner_ignores_comments_and_docstrings():
    """🔴 **负控 1**：注释 / 文档字符串里的同一段文字**不得**命中。

    本仓有大量「不要读 `origin/main`」的**纪律文字**（`test_swas_deploy_*.py` /
    `test_admin_web_devserver_identity.py` / `test_contract_ledger_reject_codes.py` …）。
    朴素正则会把它们全判红 ⇒ 这条锁会被当成噪声关掉。AST 读法结构上不会。
    """
    src = (
        '"""模块 docstring 里提到 `git show origin/main:x.py` 会自红（纪律文字）。"""\n'
        "# 注释里也提到 git show origin/main:y.py（同样不算调用）\n"
        "def f():\n"
        "    return 1\n"
    )
    assert mutable_ref_hits(src, where="neg-control-comments") == []


def test_scanner_ignores_string_manipulation():
    """🔴 **负控 2**：`REAL_X.replace("git show origin/main:…", …)` 形态**不得**命中。

    存量实例（`tests/unit_ci_workflows/test_flaky_ledger_reconcile.py`）：它**不跑 git**，
    只是在文本上做红证 —— 被调函数是 `str.replace`，不在「运行 git 的调用」集合里。
    （若把它判红，就得为它开台账口子 ⇒ 台账变噪声。）
    """
    src = (
        "def f(text):\n"
        "    return text.replace('git show origin/main:.github/scripts/x.py',"
        " 'git show origin/branch:.github/scripts/x.py', 1)\n"
    )
    assert mutable_ref_hits(src, where="neg-control-replace") == []


def test_scanner_fails_closed_on_unparseable_source():
    """🔴 fail-closed：源码解析不了 ⇒ **显式报错**，不得静默给空集。

    静默给空集正是本文件要治的那类假绿（#5814 的 CI 红就是「基线悄悄变空集」）。
    """
    with pytest.raises(SyntaxError):
        mutable_ref_hits("def broken(:\n", where="unparseable")
