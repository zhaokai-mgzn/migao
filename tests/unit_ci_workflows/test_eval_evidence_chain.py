# case_ids: CH-037, CH-036, CH-024, CH-025, CH-034, CH-035, OR-026, AS-005, CH-002, OR-006, PR-011, PR-012, API-010, BM-001, CH-008, CH-017, PR-019, PR-014
"""用例「机器证据链」必须真的存在 —— `traces` 引用与「以单测覆盖为由 skip」的 L0 守卫（零 LLM，秒级）。

## 病灶（issue #4120，2026-09-18 实测）

`CH-037`（窗帘澄清清单引擎）是「**行业能力评测零证据 + 假证据链**」的标本 —— 三个环节同时成立：

| 环节 | 事实（改前） |
|---|---|
| 用例声明 | `traces.tests: backend/ai-agent-service/tests/test_curtain_checklist.py` |
| 该路径 | **不存在**（真实文件在 `tests/test_clarification/curtain_checklist.py`） |
| 该文件 | 名为 `curtain_checklist.py` ⇒ 不匹配 `pytest.ini` 的 `python_files = test_*.py` ⇒ **永不被 pytest 收集**（18 个 `def test_` 一个都没跑过） |
| 用例本身 | `skip_reason` 以「由单元测试全量覆盖（`test_curtain_checklist.py`）」为由**跳过冒烟** |

⇒ 这条用例的机器证据为**零**，而**没有任何东西会变红**：case_ids 只查「声明有无」、
`traces` 不校验存在性、`skip_reason` 只是一段散文（永远不会被任何检查读到）。
同族存量本次穷举结果：**11 条幽灵 `traces.tests` + 7 条幽灵 `traces.ci`**（已逐条修掉，
**不留豁免白名单** —— 白名单就是把「这条引用可以是假的」写进契约）。

## 本文件锁三条判据（都建在**事实/结构**上，不读散文措辞）

1. **`traces.tests` 必须存在**：路径相对仓库根 `is_file()`。
2. **`traces.ci` 必须是真实存在的 workflow**：`.github/workflows/<name>`。
3. **「以单测覆盖为由 skip」点名的测试文件必须** ① 存在，且 ② **会被 pytest 收集**。
   判据（全部读真值，不写死）：
   - **是不是「测试覆盖」声明** = 该提及的文件名匹配 `python_files` 模式（形如 `test_*.py`），
     或路径落在 `tests/` 目录里 —— 且不是 `conftest.py` / `__init__.py`（pytest 保留基础设施名，
     永远不会被当作测试模块收集）；
   - **会被收集吗** = 文件名匹配**离它最近的** `pytest.ini` 的 `python_files`；
     位于某个**真实执行的收集根**内（各 `pytest.ini` 的 `testpaths` + CI/`verify-all.sh` 里
     **显式给出**的 pytest 路径参数，如 `pr-check.yml` 的 `tests/unit_ci_workflows`）；
     且不被 `addopts` 的 `--ignore=` 排除。
   ⚠️ 判据**不看**「skip_reason 里有没有『单测』二字」：措辞判据会随写法漂移（R5 禁语料判据），
   本判据只读**文件名形态 + pytest 配置 + CI 命令**这三样事实。

## 红证（两条，均实测；`TestRedProofs` 用注入式夹具把同一个判据钉在测试里）

| 判据 | 红证 |
|---|---|
| ① 引用存在性 | 把任一用例的 `traces.tests` 改成不存在的路径（本次实测 = CH-037 原值）⇒ 红，报出用例 ID + 路径 |
| ③ 单测被收集 | 把 `tests/test_clarification/test_curtain_checklist.py` 改回 `curtain_checklist.py`、并在 `skip_reason` 里点名其真实路径 ⇒ 红（**存在但不会被收集**）；改回 `test_curtain_checklist.py` ⇒ 绿 |
| ③ 引用存在性 | `skip_reason` 点名 `test_curtain_checklist.py` 而真名是 `curtain_checklist.py`（本次实测原形态）⇒ 红 |

## 负例（R2：合法形态不得判红）

`TestNegativeCases` 逐条锁定三种**合法写法**（裸文件名 / 模块内相对路径 / 仓库根相对路径）
与真实存在的 workflow ⇒ 判据**不报**。

## 本文件**不**判（如实登记边界，防被读成「有硬门禁」）

- `traces.verifies`：全库当前为空，判据没有对象；
- `traces.ci` 与 `traces.tests` 的**语义匹配**（那个 workflow 是否真会跑那个测试文件）：
  需要 workflow→路径映射（模块内相对 vs 仓库根相对两种写法都有），误报面大 ⇒ **未落码**；
- `render_cases.py` **不渲染 `traces`** ⇒ 生成物账本（`eval_cases.py` / casebook md）里看不到证据链，
  幽灵引用在账本上是**盲区**（§18.5）。本守卫直接读 `cases/*.yml`，不受该盲区影响，但账本侧仍是缺口；
- `skip_reason` 的**语义**是否成立（「这些单测真的覆盖了这条用例吗」是语义判断）；
  静态只能判「它点名的文件**跑得起来**」——语义残留交 LLM 复核格（#3483）。
"""
from __future__ import annotations

import fnmatch
import re
import sys
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
MODULE_ROOT = REPO_ROOT / "backend" / "ai-agent-service"

sys.path.insert(0, str(REPO_ROOT / ".github"))
# 用例库的**唯一**装载路径（与 eval runner 的 `--cases` 同源）：第二套解析口径必然漂移。
import render_cases  # noqa: E402

# pytest 无 ini 时的内置 `python_files` 默认（本仓根 `tests/` 无 ini；真值 = pytest 实现）
DEFAULT_PYTHON_FILES = ("test_*.py", "*_test.py")
# pytest 保留的基础设施名：永远不是「测试模块」，不构成覆盖声明
PYTEST_INFRA_NAMES = frozenset({"conftest.py", "__init__.py"})
# 结构上不可能被 pytest 收集的目录
PRUNED_DIRS = frozenset({"__pycache__", "node_modules", ".venv", "venv", ".git"})
# skip_reason 里点名的 `.py`（含裸文件名形态；反引号/中文括号天然终止匹配）
_PY_MENTION_RE = re.compile(r"[A-Za-z0-9_./-]+\.py")
# 下限守卫（只在装载/判据静默失效时才触发；现值见 docstring 的穷举小节）
_MIN_CASES = 200
_MIN_CLAIMS = 10


# ══════════════════════════════════════════════════════════════════════════════
# 输入层
# ══════════════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=1)
def load_cases() -> tuple[dict, ...]:
    """用例库（唯一源 `.github/cases/*.yml`，经 runner 同款装载路径）。"""
    return tuple(render_cases.load_case_dicts(str(CASES_DIR)))


@lru_cache(maxsize=1)
def _pytest_inis() -> tuple[Path, ...]:
    """仓库里的 pytest 配置（真值源；深度受限，避免爬进 node_modules / .venv）。"""
    found = set()
    for pattern in ("pytest.ini", "*/pytest.ini", "*/*/pytest.ini"):
        for p in REPO_ROOT.glob(pattern):
            if p.is_file() and not (PRUNED_DIRS & set(p.parts)):
                found.add(p)
    return tuple(sorted(found))


def _ini_list(ini: Path, key: str) -> tuple[str, ...]:
    """取 pytest.ini 里某个多值键（`python_files` / `testpaths`）—— 读真值，不写死模式。"""
    m = re.search(rf"^{re.escape(key)}\s*=\s*(.+)$", ini.read_text(encoding="utf-8"), re.M)
    return tuple(m.group(1).split()) if m else ()


@lru_cache(maxsize=1)
def _all_python_files_patterns() -> tuple[str, ...]:
    """全仓生效的 `python_files` 模式并集（用于判「这个文件名像不像测试模块」）。"""
    pats = set(DEFAULT_PYTHON_FILES)
    for ini in _pytest_inis():
        pats.update(_ini_list(ini, "python_files"))
    return tuple(sorted(pats))


def _effective_python_files(path: Path) -> tuple[str, ...]:
    """离该文件**最近**的 pytest 配置里的 `python_files`（无配置 ⇒ pytest 内置默认）。"""
    for parent in path.parents:
        ini = parent / "pytest.ini"
        if ini.is_file():
            pats = _ini_list(ini, "python_files")
            if pats:
                return pats
        if parent == REPO_ROOT:
            break
    return DEFAULT_PYTHON_FILES


def _pytest_path_args(text: str) -> list[str]:
    """从 CI/脚本文本里提取 pytest 命令的**路径参数**（跳过 `-x`/`--foo` 选项与 `$VAR`）。

    fail-safe 方向：这里**宽松**（多认几个收集根只会让判据更少误报红），
    严格性由 `python_files` 模式 + 存在性 + `--ignore` 三者承担。
    """
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") or "pytest" not in s:
            continue
        for tok in s.split("pytest", 1)[1].split():
            if tok.startswith("-") or "$" in tok or "=" in tok:
                continue
            tok = tok.strip("\\'\"")
            if "/" in tok or tok.endswith(".py"):
                out.append(tok)
                break
    return out


@lru_cache(maxsize=1)
def collect_roots() -> tuple[Path, ...]:
    """pytest **真实会遍历**的目录（从事实推导，不写死）：

    ① 每个 `pytest.ini` 的 `testpaths`（如 `backend/ai-agent-service` 的 `tests`）；
    ② CI workflow / `verify-all.sh` 里**显式给出**的 pytest 路径参数
       （如 `pr-check.yml` 的 `tests/unit_ci_workflows` —— 根 `tests/` 没有 ini，
       不看这条就会把「真被 CI 收集」的合法文件判红，见 R2）。
    """
    roots: set[Path] = set()
    for ini in _pytest_inis():
        for t in _ini_list(ini, "testpaths"):
            cand = (ini.parent / t).resolve()
            if cand.is_dir():
                roots.add(cand)
    sources = [*sorted(WORKFLOWS_DIR.glob("*.yml")), REPO_ROOT / "verify-all.sh"]
    for src in sources:
        if not src.is_file():
            continue
        for tok in _pytest_path_args(src.read_text(encoding="utf-8")):
            for base in (REPO_ROOT, MODULE_ROOT):
                cand = base / tok
                if cand.is_dir():
                    roots.add(cand.resolve())
                elif cand.is_file():
                    roots.add(cand.parent.resolve())
    return tuple(sorted(roots))


@lru_cache(maxsize=1)
def ignored_paths() -> tuple[Path, ...]:
    """`pytest.ini` 的 `addopts` 里 `--ignore=<path>`（相对该 ini 所在目录解析）。"""
    out = set()
    for ini in _pytest_inis():
        for m in re.finditer(r"--ignore=([^\s]+)", ini.read_text(encoding="utf-8")):
            out.add((ini.parent / m.group(1)).resolve())
    return tuple(sorted(out))


# ══════════════════════════════════════════════════════════════════════════════
# 判据层（纯函数；红证/负例直接打在它们上）
# ══════════════════════════════════════════════════════════════════════════════

def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def collected_by_pytest(path: Path) -> tuple[bool, str]:
    """**结构性**判定：pytest 真的会收集这个文件吗？返回 `(会被收集, 不会的原因)`。"""
    pruned = PRUNED_DIRS & set(path.parts)
    if pruned:
        return False, f"位于不可能被收集的目录（{'/'.join(sorted(pruned))}）"
    patterns = _effective_python_files(path)
    if not any(fnmatch.fnmatch(path.name, p) for p in patterns):
        return False, (f"文件名不匹配生效的 python_files={list(patterns)}"
                       f"（真值读最近的 pytest.ini）⇒ 不是测试模块，pytest 不收集")
    if not any(_is_under(path, r) for r in collect_roots()):
        return False, ("不在任何 pytest 收集根内（收集根 = 各 pytest.ini 的 testpaths "
                       "+ CI/verify-all.sh 里显式给出的 pytest 路径参数）")
    for ig in ignored_paths():
        if path == ig or _is_under(path, ig):
            return False, f"被 pytest 的 --ignore={ig.relative_to(REPO_ROOT)} 排除"
    return True, ""


def trace_ghosts(cases) -> list[dict]:
    """`traces.tests` / `traces.ci` 里解析不到的引用 = [{case_id, field, ref}]。"""
    out = []
    for c in cases:
        traces = c.get("traces") or {}
        for ref in traces.get("tests") or []:
            if not (REPO_ROOT / str(ref)).is_file():
                out.append({"case_id": str(c.get("id")), "field": "traces.tests", "ref": str(ref)})
        for ref in traces.get("ci") or []:
            if not (WORKFLOWS_DIR / str(ref)).is_file():
                out.append({"case_id": str(c.get("id")), "field": "traces.ci", "ref": str(ref)})
    return out


def looks_like_test_claim(mention: str) -> bool:
    """该提及是否构成「这里有测试覆盖」的**结构**声明（不读散文措辞）。"""
    p = Path(mention)
    if p.name in PYTEST_INFRA_NAMES:
        return False
    if any(fnmatch.fnmatch(p.name, pat) for pat in _all_python_files_patterns()):
        return True
    return "tests" in p.parts


def resolve_mention(mention: str) -> list[Path]:
    """把提及解析为候选文件：仓库根 → 模块根 → 各收集根内按 basename 查。"""
    for base in (REPO_ROOT, MODULE_ROOT):
        cand = base / mention
        if cand.is_file():
            return [cand]
    name = Path(mention).name
    hits = set()
    for root in collect_roots():
        for p in root.rglob(name):
            if p.is_file() and not (PRUNED_DIRS & set(p.parts)):
                hits.add(p)
    return sorted(hits)


def skip_claims(cases) -> list[dict]:
    """所有「以测试文件为由 skip」的声明 = [{case_id, mention, paths, problems}]。"""
    out = []
    for c in cases:
        sr = c.get("skip_reason")
        if not isinstance(sr, str) or not sr:
            continue
        for mention in _PY_MENTION_RE.findall(sr):
            if not looks_like_test_claim(mention):
                continue
            paths = resolve_mention(mention)
            problems = []
            if not paths:
                problems.append("点名的测试文件**不存在**（在任何 pytest 收集根内都查不到）")
            for p in paths:
                ok, why = collected_by_pytest(p)
                if not ok:
                    problems.append(f"{p.relative_to(REPO_ROOT)} 存在但**不会被 pytest 收集**：{why}")
            out.append({"case_id": str(c.get("id")), "mention": mention,
                        "paths": [str(p.relative_to(REPO_ROOT)) for p in paths],
                        "problems": problems})
    return out


def _render(rows: list[dict]) -> str:
    return "\n".join(
        f"  · {r['case_id']} [{r['field']}] {r['ref']}" if "field" in r
        else f"  · {r['case_id']} skip_reason 点名 {r['mention']!r}：{'；'.join(r['problems'])}"
        for r in rows
    )


# ══════════════════════════════════════════════════════════════════════════════
# 前置守卫（防「空跑」——绿了但没跑）
# ══════════════════════════════════════════════════════════════════════════════

class TestGuardPremise:
    def test_case_library_loaded(self):
        cases = load_cases()
        assert len(cases) >= _MIN_CASES, (
            f"只装载到 {len(cases)} 条用例（< {_MIN_CASES}）—— 装载路径失效会让本守卫静默空跑"
            f"（`{CASES_DIR}`）")
        ids = {c.get("id") for c in cases}
        assert {"CH-037", "CH-036", "CH-025"} <= ids, (
            f"锚点用例不在装载结果里：{sorted({'CH-037', 'CH-036', 'CH-025'} - ids)}")

    def test_claims_are_found(self):
        claims = skip_claims(load_cases())
        assert len(claims) >= _MIN_CLAIMS, (
            f"只解析出 {len(claims)} 条「以单测覆盖为由 skip」的声明（< {_MIN_CLAIMS}）——"
            f"判据静默失效（提及提取 / 解析 / 收集根推导三者之一坏掉）")
        anchors = {"CH-036", "CH-037"} & {c["case_id"] for c in claims}
        assert anchors, "锚点用例 CH-036 / CH-037 都没被解析出覆盖声明 —— 判据跑偏了"

    def test_collect_roots_are_real(self):
        roots = collect_roots()
        assert roots, "推导出的 pytest 收集根为空 —— 判据会退化成「什么都不收集」"
        assert (MODULE_ROOT / "tests").resolve() in roots, (
            f"模块 testpaths 未进入收集根：{[str(r) for r in roots]}")
        assert (REPO_ROOT / "tests" / "unit_ci_workflows").resolve() in roots, (
            "pr-check.yml 里显式给出的 tests/unit_ci_workflows 未进入收集根"
            "（缺它会把真被 CI 收集的文件判红）")


# ══════════════════════════════════════════════════════════════════════════════
# 判据 ①②：引用必须解析得到（fail-closed，列全量、无白名单）
# ══════════════════════════════════════════════════════════════════════════════

class TestTraceRefsExist:
    def test_traces_tests_and_ci_resolve(self):
        ghosts = trace_ghosts(load_cases())
        assert not ghosts, (
            f"用例声明了 {len(ghosts)} 条**不存在**的证据引用（幽灵引用 = 机器证据为零，"
            f"而现有门禁抓不到：case_ids 只查声明有无、traces 不校验存在性）：\n"
            f"{_render(ghosts)}\n"
            f"  修法：改成真实路径（相对仓库根）；确属误删则连同用例一起修，"
            f"**不得**加豁免白名单（那等于把「引用可以是假的」写进契约）")

    def test_traces_tests_volume(self):
        """退化守卫：被扫的 `traces.tests` 条目数不得塌成 0（否则上面那条恒绿）。"""
        n = sum(len((c.get("traces") or {}).get("tests") or []) for c in load_cases())
        assert n >= 100, f"只扫到 {n} 条 traces.tests —— 判据在空跑"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 ③：以单测覆盖为由 skip ⇒ 那个文件必须真被收集
# ══════════════════════════════════════════════════════════════════════════════

class TestSkipReasonEvidence:
    def test_claimed_unit_tests_are_collected(self):
        bad = [c for c in skip_claims(load_cases()) if c["problems"]]
        assert not bad, (
            f"有 {len(bad)} 条用例以「由单元测试覆盖」为由 skip，但点名的单测**跑不起来**"
            f"（存在性/收集二者之一不成立）—— 该用例的机器证据为**零**，而没有任何东西会变红：\n"
            f"{_render(bad)}")


# ══════════════════════════════════════════════════════════════════════════════
# 红证（注入式夹具：构造已知缺陷形态，断言判据**必报**）
# ══════════════════════════════════════════════════════════════════════════════

class TestRedProofs:
    def test_red_proof_ghost_trace_ref(self):
        """① 幽灵 `traces.tests`（载荷逐字取自 CH-037 改前值）⇒ 必报。"""
        ghost = "backend/ai-agent-service/tests/test_curtain_checklist.py"
        rows = trace_ghosts([{"id": "ZZ-001", "traces": {"tests": [ghost]}}])
        assert [r["ref"] for r in rows] == [ghost], "幽灵 traces.tests 未被判出 —— 判据恒绿"
        assert rows[0]["case_id"] == "ZZ-001"

    def test_red_proof_ghost_ci_ref(self):
        """① 幽灵 `traces.ci`（载荷逐字取自存量值）⇒ 必报。"""
        rows = trace_ghosts([{"id": "ZZ-002", "traces": {"ci": ["admin-api-tests.yml"]}}])
        assert [r["ref"] for r in rows] == ["admin-api-tests.yml"], "幽灵 traces.ci 未被判出"

    def test_red_proof_missing_mentioned_test_file(self):
        """③ 形态一：`skip_reason` 点名的单测**不存在**（CH-037 改前的完整形态）⇒ 必报。

        载荷用不会存在的合成名：判据要能在**任何**仓库状态上红（钉的是判据本身，
        不是 CH-037 当时的仓库状态 —— 后者已被本 PR 修掉）。
        """
        claims = skip_claims([{
            "id": "ZZ-003",
            "skip_reason": "由单元测试全量覆盖（test_zz_ghost_probe.py），非 LLM 行为",
        }])
        assert len(claims) == 1, "提及未被识别为覆盖声明 —— 判据对该形态无感"
        assert claims[0]["problems"], "点名不存在的单测未被判红 —— 判据恒绿"
        assert "不存在" in claims[0]["problems"][0], claims[0]["problems"]

    def test_red_proof_existing_but_uncollected_file(self):
        """③ 形态二：文件**存在**但 pytest 不会收集它（`--ignore` 排除的真实例）⇒ 必报。"""
        ignored_test = MODULE_ROOT / "tests" / "e2e" / "real" / "test_xiaobu_acceptance.py"
        assert ignored_test.is_file(), f"夹具失效：{ignored_test} 不存在"
        ok, why = collected_by_pytest(ignored_test)
        assert not ok, f"被 --ignore 排除的文件被判成「会被收集」：{why}"
        assert "--ignore" in why, why

    def test_red_proof_uncollected_basename(self):
        """③ 形态三：点名**不被收集**的单测名（CH-037 改前的真实路径）⇒ 必报。

        该路径改前 = 「存在但文件名不匹配 `python_files`」；本 PR 改名后 = 「不存在」。
        两种形态都落在同一个判据上（点名的单测跑不起来），故断言只要求**必报**。
        """
        pre_fix_path = "backend/ai-agent-service/tests/test_clarification/curtain_checklist.py"
        claims = skip_claims([{"id": "ZZ-004", "skip_reason": f"由 {pre_fix_path} 覆盖"}])
        assert len(claims) == 1, "落在 tests/ 下的 .py 提及未被当作覆盖声明"
        assert claims[0]["problems"], (
            f"点名 {pre_fix_path}（不被收集的名字）未被判红 —— 判据对零证据形态无感")

    def test_red_proof_wrong_python_files_name(self):
        """③ 形态四：文件**存在**却不匹配 `python_files` ⇒ 判据按文件名形态报红。"""
        engine = MODULE_ROOT / "app" / "clarification" / "curtain_checklist.py"
        assert engine.is_file(), f"夹具失效：{engine} 不存在"
        ok, why = collected_by_pytest(engine)
        assert not ok, "不匹配 python_files 的文件被判成「会被收集」"
        assert "python_files" in why, why


# ══════════════════════════════════════════════════════════════════════════════
# 负例（R2：合法形态不得判红）
# ══════════════════════════════════════════════════════════════════════════════

class TestNegativeCases:
    @pytest.mark.parametrize("mention", [
        "test_curtain_calc.py",                                      # 裸文件名（CH-036 现形态）
        "tests/test_chat.py",                                        # 模块内相对路径（API-001 现形态）
        "tests/unit_ci_workflows/test_issue_dedup_guard.py",         # 仓库根相对路径（MC-012 现形态）
        "backend/ai-agent-service/tests/test_ontology_schema.py",    # 仓库根全路径（ON-001 现形态）
    ])
    def test_legit_mentions_not_reported(self, mention):
        claims = skip_claims([{"id": "ZZ-005", "skip_reason": f"由单元测试覆盖（{mention}）"}])
        assert len(claims) == 1, f"{mention} 未被识别为覆盖声明"
        assert not claims[0]["problems"], f"合法形态被判红：{mention} ⇒ {claims[0]['problems']}"

    def test_engine_file_is_not_a_claim(self):
        """`app/clarification/curtain_checklist.py`（**被测引擎**，非测试）不得被当覆盖声明。"""
        claims = skip_claims([{
            "id": "ZZ-006",
            "skip_reason": "澄清清单引擎是确定性纯函数（app/clarification/curtain_checklist.py）",
        }])
        assert not claims, f"被测引擎文件被误判成「测试覆盖声明」：{claims}"

    def test_infra_names_are_not_claims(self):
        claims = skip_claims([{
            "id": "ZZ-007",
            "skip_reason": "由 backend/ai-agent-service/tests/conftest.py 的 fixture 支撑",
        }])
        assert not claims, f"pytest 保留基础设施名被误判成测试模块：{claims}"

    def test_real_library_mentions_pass(self):
        """整库负例：CH-036 的 `test_curtain_calc.py` 声明必须判绿（真被收集）。"""
        by_id = {c["case_id"]: c for c in skip_claims(load_cases())}
        assert by_id["CH-036"]["problems"] == [], by_id["CH-036"]
        assert (MODULE_ROOT / "tests" / "test_curtain_calc.py").is_file()

    def test_real_workflow_ref_not_reported(self):
        """整库负例：真实存在的 workflow 引用不得判红。"""
        ghosts = trace_ghosts([{"id": "ZZ-008", "traces": {"ci": ["pr-check.yml"]}}])
        assert not ghosts, ghosts
        assert (WORKFLOWS_DIR / "pr-check.yml").is_file()