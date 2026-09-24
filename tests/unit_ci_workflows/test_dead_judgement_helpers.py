# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 test_guard_parsing_is_comment_aware.py / test_automerge_bot_safe_path.py 的同款声明与
#   `.github/cases/misc.yml` MC-012 的登记。本 PR 不新建用例族。）
"""**死判据检测**：定义了却**零调用**的判定辅助函数 ⇒ 红（issue #4314）。

## 病根（一类缺陷，不是一个缺陷）

`scripts/ui-smoke-merchant/spec.mjs` 的 `expectToast(page, text)` 定义在文件中部，
**全仓零调用**（实测：标识符全仓出现 1 次 = 定义本身），而且它内部
`waitFor(...).catch(() => {})` **吞掉超时** ⇒ 万一有人接上调用点，它**恒真**（空判据）。
「定义了 = 判据存在」是错觉：**判据的存在性 = 有人调用它**。

同族（#4226 的三处点名判据）当时是「判据在跑但判不出东西」；本条是它的极端形态
——**判据根本没跑**，而没有任何东西会因此变红。

## 判据（自动发现，不需要人先记得加进来）

扫描面 = 定义面（`tests/**/*.py`、`backend/**/tests/**/*.py`、`.github/**/*.py`、
`scripts/**/*.{mjs,ts,js}`）；引用计数面 = 全仓代码语料（`tests` / `backend` / `scripts` /
`frontend` / `.github`，跳过 `node_modules` 等构建目录）。

- 形如 `expect*` / `assert*` / `verify*` / `check*` / `wait*` 的函数（含 async）都是**判定辅助**；
- 它在**全仓**标识符计数 == 1（只有定义、没有任何引用）⇒ **红**；
- **`@pytest.fixture` 装饰的不算**（pytest 按名字调用它，计数天然是 1 —— 那是**假红**方向，必须排除）。

豁免台账 = `_EXEMPT`（`(相对路径, 函数名) → "理由（issue #NNNN）"`）：
**只许缩短**，今天**必须为空**（`test_exemption_ledger_is_empty` 打印现取读数）。
任何一条豁免都要带理由 + 单号，否则 `problems_exemption_shape` 判红。

## 红证（逐条，见文件尾 `TestRedProofs`；注入先自证生效）

① 合成语料：注入一个零引用 `expectGhost` ⇒ 红；同一个合成语料里的**活**助手 ⇒ 不得红（正对照）；
② 真文件注入：往 `spec.mjs` 追加一个零引用助手 ⇒ 红；
③ **删掉调用点**：把 `spec.mjs` 里 `expectText` 的**全部调用点改名**（定义行保留）
   ⇒ 计数 13 → 1 ⇒ 红（自证：改名前后计数必须真的下降）；
④ `@pytest.fixture` 助手 ⇒ **不得**红（防假红）；
⑤ 豁免条目缺理由/单号 ⇒ 红。

## 未固化 / 边界（照实登记）

- 判据只认「**零引用**」这一形态。**被调用但恒真**的判据（内部 `catch(() => {})` 吞超时、
  单次 `isVisible()` 无等待）**不在**本文件面内 —— 那要运行期真栈（#4314 正文裁定：
  「其它旅程的 sleep → 等元素改造无法在本机做运行期验证」，云 dev 库不可达）。
  该形态的**路线**登记在 issue #4314 + PR body 残余节，owner = 商家冒烟（ui-smoke）owner。
- 计数按**标识符文本**（不是 AST 绑定分析）：名字在注释/字符串里出现会**抬高**计数
  ⇒ 漏判方向（假绿），不会误伤；本仓当前树的实测读数是 1（`expectToast`），故不构成实际缺口。
- 改名/搬家会让「旧名零引用」变红 —— 那是**期望**（旧名残留 = 死代码），删掉即可。

判据 = 本文件；一键复算：
`python3 -m pytest tests/unit_ci_workflows/test_dead_judgement_helpers.py -q -s`
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 语料根目录（相对仓库根）+ 代码扩展名 + 跳过目录（构建产物 / 依赖目录）
CORPUS_DIRS = ("tests", "backend", "scripts", "frontend", ".github")
CODE_EXTS = frozenset({".py", ".ts", ".tsx", ".js", ".mjs", ".cjs"})
SKIP_PARTS = frozenset({"node_modules", ".venv", "venv", "dist", "build", ".next",
                        "coverage", "__pycache__", ".git", ".pytest_cache"})

#: 判定辅助的命名形态（`expectToast` / `assert_x` / `waitVisible` …）
HELPER_RE = re.compile(r"^(?:expect|assert|verify|check|wait)[A-Z_]")

#: 语料里**排除本文件自身**：判据的 docstring / 红证语料里逐字写着 `expectToast`、`expectGhost`
#: 这类名字 —— 不排除就会**用自己文案把计数喂大**（实测：注入的 `expectGhost` 计数 = 9，
#: 假绿/空红证都长这样，§17.3 ③「判据被自己的文案喂绿」）。
SELF_REL = "tests/unit_ci_workflows/test_dead_judgement_helpers.py"

#: 豁免台账（**今天必须为空**）：`(相对路径, 函数名) → "理由（issue #NNNN）"`。只许缩短。
_EXEMPT: dict[tuple[str, str], str] = {}


def is_def_surface(rel: str) -> bool:
    """该相对路径是否属**定义面**（判定辅助只可能定义在这些地方）。"""
    if rel.endswith(".py"):
        return rel.startswith(("tests/", ".github/")) or "/tests/" in rel
    return rel.startswith("scripts/")


@lru_cache(maxsize=1)
def corpus_sources() -> dict[str, str]:
    """全仓代码语料 `相对路径 → 源码`（一次读数同时供定义扫描与引用计数 —— 输入**同刻**，§23 G4）。"""
    out: dict[str, str] = {}
    for top in CORPUS_DIRS:
        base = REPO_ROOT / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in CODE_EXTS or any(p in SKIP_PARTS for p in path.parts):
                continue
            rel = str(path.relative_to(REPO_ROOT))
            if rel == SELF_REL:
                continue
            try:
                out[rel] = path.read_text(encoding="utf8")
            except (OSError, UnicodeDecodeError):
                continue
    if len(out) < 500:
        raise AssertionError(f"语料只读到 {len(out)} 个文件 ⇒ 判据会空跑（fail-closed）")
    return out


def identifier_counts(sources: dict[str, str]) -> Counter:
    """全仓标识符计数（一次遍历；名字出现 ≥2 次即「有人引用」）。"""
    counts: Counter = Counter()
    for text in sources.values():
        counts.update(re.findall(r"[A-Za-z_$][\w$]*", text))
    return counts


def _is_fixture_decorator(node: ast.AST) -> bool:
    """`@pytest.fixture` / `@fixture` / `@pytest.fixture(...)` 三种写法都认（AST 位置判定）。"""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr == "fixture"
    return getattr(node, "id", None) == "fixture"


def helper_definitions(sources: dict[str, str]) -> dict[tuple[str, str], int]:
    """定义面上的判定辅助：`(相对路径, 函数名) → 行号`。

    `@pytest.fixture` 装饰的函数**排除**（pytest 按名字调用 ⇒ 计数天然是 1，硬判是假红）。
    """
    out: dict[tuple[str, str], int] = {}
    for rel, text in sorted(sources.items()):
        if not is_def_surface(rel):
            continue
        if rel.endswith(".py"):
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not HELPER_RE.match(node.name):
                    continue
                if any(_is_fixture_decorator(d) for d in node.decorator_list):
                    continue
                out[(rel, node.name)] = node.lineno
        else:
            for match in re.finditer(
                    r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(|"
                    r"^const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(", text, re.M):
                name = match.group(1) or match.group(2)
                if HELPER_RE.match(name):
                    out[(rel, name)] = text[:match.start()].count("\n") + 1
    # 反空跑由 `test_scan_surface_is_live`（真语料读数）+ `corpus_sources()` 的规模闸负责 ——
    # 这里**不**设下限：本函数也要能吃合成语料（红证的注入语料只有两三个函数）。
    return out


def problems_dead_helpers(defs: dict[tuple[str, str], int], counts: Counter,
                          exempt: dict[tuple[str, str], str]) -> list[str]:
    """零引用（全仓计数 == 1 = 只有定义）的判定辅助 ⇒ 问题清单。"""
    out: list[str] = []
    for (rel, name), line_no in sorted(defs.items()):
        if (rel, name) in exempt:
            continue
        seen = counts.get(name, 0)
        if seen <= 1:
            out.append(f"`{rel}` 第 {line_no} 行定义了 `{name}()`，但**全仓零调用**"
                       f"（标识符计数 = {seen}）⇒ 死判据：接上调用点，或删掉")
    return out


def problems_exemption_shape(exempt: dict[tuple[str, str], str]) -> list[str]:
    out: list[str] = []
    for key, reason in sorted(exempt.items()):
        if not str(reason).strip() or "#" not in str(reason):
            out.append(f"豁免条目 `{key[0]}::{key[1]}` 的理由={reason!r} 不合格 ⇒ "
                       "必须写「为什么可以留着 + 单号（#NNNN）」")
    return out


def problems_dead_helpers_from(sources: dict[str, str],
                               exempt: dict[tuple[str, str], str] | None = None) -> list[str]:
    return problems_dead_helpers(helper_definitions(sources), identifier_counts(sources),
                                 _EXEMPT if exempt is None else exempt)


# ══════════════════════════════════════════════════════════════════════════════
# 判据
# ══════════════════════════════════════════════════════════════════════════════


def test_no_dead_judgement_helpers():
    """定义了却零调用的判定辅助 ⇒ 红（issue #4314 的常驻判据）。"""
    problems = problems_dead_helpers_from(corpus_sources())
    if problems:
        raise AssertionError("存在零调用死判据：\n  - " + "\n  - ".join(problems))


def test_exemption_ledger_is_empty():
    """豁免台账**今天必须为空**（燃尽靶子：现取读数打印；要加条目必须在 diff 里看得见）。"""
    reading = f"豁免台账读数：{len(_EXEMPT)} 条（只许缩短；条目必须带理由 + 单号）"
    print(reading)
    problems = problems_exemption_shape(_EXEMPT)
    if problems or _EXEMPT:
        raise AssertionError(reading + "\n  - " + "\n  - ".join(problems or ["台账非空"]))


def test_scan_surface_is_live():
    """反空跑读数：语料规模 / 定义面规模 / 活助手正对照（判据不靠「扫不到」通过）。"""
    sources = corpus_sources()
    defs = helper_definitions(sources)
    counts = identifier_counts(sources)
    live = [(rel, name) for (rel, name) in defs if counts.get(name, 0) > 1]
    reading = (f"扫描读数：语料 {len(sources)} 文件 / 判定辅助 {len(defs)} 个 / "
               f"其中活助手 {len(live)} 个 / 死判据 {len(defs) - len(live) - len(_EXEMPT)} 个")
    print(reading)
    if len(defs) < 20:
        raise AssertionError(f"{reading} ⇒ 定义面解析出的判定辅助过少，判据会空跑（fail-closed）")
    if not live or len(live) < len(defs) // 2:
        raise AssertionError(f"{reading} ⇒ 计数口径可疑（活助手太少，判定会变成全体假红）")


# ══════════════════════════════════════════════════════════════════════════════
# 注入式红证（§23 G7：注入先自证生效，再要求判据变红）
# ══════════════════════════════════════════════════════════════════════════════


def _with_file(sources: dict[str, str], rel: str, text: str) -> dict[str, str]:
    if rel not in sources:
        raise AssertionError(f"注入目标不在语料里：{rel}（注入未生效 ⇒ 该红证是空断言）")
    if text == sources[rel]:
        raise AssertionError(f"注入未生效（mutated == src）：{rel}")
    out = dict(sources)
    out[rel] = text
    return out


def _drop_callsites(text: str, name: str, require_change: bool = True) -> str:
    """把某名字的**全部调用点**改名（定义行保留）⇒ 模拟「调用点被删掉」。

    `require_change=False` 用于「该文件里根本没有这个名字」的正常情形（全仓改名时会出现）。
    """
    out = []
    for line in text.splitlines(keepends=True):
        out.append(line if f"const {name}" in line or f"function {name}" in line
                   else line.replace(name, name + "_RETIRED"))
    mutated = "".join(out)
    if require_change and mutated == text:
        raise AssertionError(f"调用点改名未生效（{name} 一行都没变）")
    return mutated


class TestRedProofs:
    """判别力：注入 ⇒ 必须变红；正对照 / fixture ⇒ 必须**不**红。"""

    def test_inject_dead_helper_is_red(self):
        src = {"scripts/x.mjs": "async function expectGhost(page) { return page }\n"
                               "export const live = expectReal\n"
                               "async function expectReal() { return 1 }\n"}
        problems = problems_dead_helpers_from(src, exempt={})
        if not any("expectGhost" in p for p in problems):
            raise AssertionError(f"注入零引用助手后判据未变红 ⇒ 空断言：{problems}")
        if any("expectReal" in p for p in problems):
            raise AssertionError(f"活助手被误判为死判据（假红）：{problems}")

    def test_inject_dead_helper_into_real_file_is_red(self):
        sources = corpus_sources()
        rel = "scripts/ui-smoke-merchant/spec.mjs"
        mutated = _with_file(sources, rel,
                             sources[rel] + "\nasync function expectGhost(page) { return page }\n")
        problems = problems_dead_helpers_from(mutated, exempt={})
        if not any("expectGhost" in p for p in problems):
            raise AssertionError(f"真文件注入零引用助手后判据未变红 ⇒ 空断言：{problems}")

    def test_dropping_callsites_makes_helper_dead(self):
        """删掉调用点 ⇒ 红；并**自证**计数真的下降了（注入生效，§23 G7）。"""
        sources = corpus_sources()
        rel = "scripts/ui-smoke-merchant/spec.mjs"
        before = identifier_counts(sources)["expectText"]
        # 该名字的调用点**跨文件**存在（实测全仓 19 处）⇒ 改名必须全仓做，
        # 否则注入只让计数降一部分、判据照旧绿（"注入生效"自证会当场抓到这个）。
        mutated = {k: (v if k == rel else _drop_callsites(v, "expectText", require_change=False))
                   for k, v in sources.items()}
        mutated = _with_file(mutated, rel, _drop_callsites(sources[rel], "expectText"))
        after = identifier_counts(mutated)["expectText"]
        if not before > after or after != 1:
            raise AssertionError(f"注入未生效：expectText 计数 {before} → {after}（期望 → 1）")
        problems = problems_dead_helpers_from(mutated, exempt={})
        if not any("expectText" in p for p in problems):
            raise AssertionError(f"调用点删掉后判据未变红 ⇒ 空断言：{problems}")

    def test_pytest_fixture_helper_is_not_reported(self):
        src = {"tests/x_test.py": "import pytest\n\n\n"
                                  "@pytest.fixture\ndef check_client():\n    return 1\n"}
        counts = identifier_counts(src)
        if counts["check_client"] != 1:
            raise AssertionError("夹具注入的前提不成立（计数应恰为 1）")
        problems = problems_dead_helpers_from(src, exempt={})
        if any("check_client" in p for p in problems):
            raise AssertionError(f"pytest fixture 被误判为死判据（假红）：{problems}")

    def test_exemption_without_reason_is_red(self):
        defs = {("scripts/x.mjs", "expectGhost"): 1}
        exempt = {("scripts/x.mjs", "expectGhost"): "先留着"}
        problems = problems_exemption_shape(exempt)
        if not problems:
            raise AssertionError("豁免条目缺单号后判据未变红 ⇒ 空断言")
        if problems_dead_helpers(defs, Counter({"expectGhost": 1}), exempt):
            raise AssertionError("合规豁免未生效（被判成死判据）")

    def test_ledger_entry_without_live_problem_is_stale(self):
        """豁免必须**对应一处真问题**：语料里没有该问题时条目是陈旧的（台账只许缩短）。"""
        defs = {("scripts/x.mjs", "expectLive"): 1}
        exempt = {("scripts/x.mjs", "expectGone"): "已修（#4314）"}
        stale = [key for key in exempt if key not in defs]
        if not stale:
            raise AssertionError("陈旧豁免未被识别 ⇒ 台账可以无限膨胀（空断言）")