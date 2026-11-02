# case_ids: MC-133
"""Java 定点判据的「空跑 / 读数」类级守卫（issue #6495 的类级固化）

## 病（2026-11-03 本机实跑，读数逐条见 docs/wiki/Development.md 的「Java 定点判据」节）

① **读数面**：`target/surefire-reports/<fqn>.txt` 的 `Tests run:` 在 @Nested 类上**恒报 0**
   —— 同一次运行 XML/console 报 **15** 条、摘要写 **0**（`AgentBatchServiceTest` 是 38 / 0）。
   issue #6495 的原始读数（`head -6 …txt`）就是这么来的 ⇒ 结论「一条都没跑」是**误诊**。
② **执行面（真·空跑）**：`-Dtest=<外层类>#<方法>`，而该方法**声明在 @Nested 内** ⇒
   `Tests run: 0 / BUILD SUCCESS / exit=0`，且**不产出 XML**。正解 = `<外层类>$<嵌套类>#<方法>`。

## 本文件锁什么（每条都能单独变红）

| # | 判据 | 红证怎么取 |
|---|---|---|
| J1 | **扫描器非空跑自证**：现取的 Java 测试类索引必须含 ≥1 个 @Nested 类；入口脚本存在且可执行 | 索引空 / 入口被删 ⇒ 红（「判据失明」不是通过） |
| J2 | **真空跑形态（②）未登记即红**：仓内 durable 面出现 `-Dtest=<外层类>#<@Nested 内方法>` ⇒ 红并给正解 | 合成语料注入该形态 ⇒ 红；合规形态（`$嵌套#方法` / 类名 / 通配）⇒ 不红 |
| J3 | **`.txt` 读数源（①）必须登记，且前提现取成立**：`scripts/**` 里读 `surefire-reports … .txt` 的机具 ⇄ 台账双向相等；每条台账的定点类必须**存在**且**不含 @Nested**、锚串逐字兑现 | 台账少一条 ⇒ 红；台账给不存在的机具盖章 ⇒ 红；定点类变成 @Nested ⇒ 红 |
| J4 | **豁免只许缩短**：台账 `engines` 条数 ≤ `frozen_baseline`（现取 2），且不许清空 | 新增一条未登记的 `.txt` 机具 ⇒ 红；清空台账 ⇒ 红 |
| J5 | **规范必须指向入口**：`docs/wiki/Development.md` 逐字含 `./scripts/java-test.sh` 与 `.txt` 摘要不可信的结论 | 文档把入口删掉 / 把结论删掉 ⇒ 红 |
| J6 | **@Nested 判定不许被注释骗**（对照读数）：只含**注释**里提到 `@Nested` 的测试类**不算**嵌套类（现取证据：`git grep` 45 个文件 vs 索引 44 个） | 把 `mask_literals_and_comments` 摘掉 ⇒ 判据 J6 红 |
| J7 | **边界（照实登记）**：① 文档面没有「不许教 `.txt` 读数」的形态判据（同一句里既有正解又有反例，形态判据分不清）；② 判不了「人敲了什么命令」（命令在键盘上，不在仓里）；③ 不跑被它引用的 Java 判据（那要 Maven ⇒ 归 `scripts/java-test.sh` 与 CI）；④ 不改任何门禁的通过条件、不新增豁免。 |

执行点（本文件内的测试名）：`test_j1_*` / `test_j2_*` / `test_j3_*` / `test_j4_*` / `test_j5_*` / `test_j6_*`。
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRY = REPO_ROOT / "scripts" / "java-test.sh"
MODULE_PATH = REPO_ROOT / "scripts" / "java_test_readings.py"
LEDGER_PATH = Path(__file__).resolve().parent / "java_pointed_run_ledger.json"
DEV_DOC = REPO_ROOT / "docs" / "wiki" / "Development.md"

# 判据本体之外的 durable 面（「写法会被人抄走」的地方）。`tests/**` **有意不收**：
# 判据文件自己要用坏形态当语料，收进来会自己喂红自己（见 J7 边界①）。
SURFACE_GLOBS = (
    "docs/wiki/**/*.md",
    "docs/testing/**/*.md",
    "AGENTS.md",
    "scripts/**/*.py",
    "scripts/**/*.sh",
    ".github/cases/**/*.yml",
    ".github/workflows/**/*.yml",
    "backend/*/src/test/java/**/*.java",
)

TXT_ENGINE_GLOB = "scripts/*.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("java_test_readings", MODULE_PATH)
    assert spec and spec.loader, f"入口实现不存在：{MODULE_PATH.relative_to(REPO_ROOT)}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["java_test_readings"] = mod  # dataclass 需要 __module__ 可解析
    spec.loader.exec_module(mod)
    return mod


jtr = _load_module()


# ────────────────────────── 取数 ──────────────────────────

def surface_files() -> list[Path]:
    out: list[Path] = []
    for pattern in SURFACE_GLOBS:
        if "*" not in pattern:
            path = REPO_ROOT / pattern
            if path.is_file():
                out.append(path)
            continue
        out.extend(sorted(REPO_ROOT.glob(pattern)))
    return [p for p in out if p.is_file()]


def bad_form_hits(index: dict) -> list[str]:
    """J2：仓内 durable 面里的 `-Dtest=<外层类>#<@Nested 内方法>`（真·空跑形态）。"""
    hits: list[str] = []
    for path in surface_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if "-Dtest=" not in text:
            continue
        for selector, fixed in jtr.bad_selectors_in_text(text, index):
            hits.append(f"{path.relative_to(REPO_ROOT)}: -Dtest={selector} ⇒ 应写成 -Dtest={fixed}")
    return hits


def _code_strings(tree: ast.AST) -> list[str]:
    """非 docstring 的字符串常量（含 f-string 的常量片段）—— 「**提及**」不算「**使用**」。"""
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            out.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            out.append("".join(v.value for v in node.values
                               if isinstance(v, ast.Constant) and isinstance(v.value, str)))
    return out


def _is_txt_path(s: str) -> bool:
    """`.txt` **路径形态**的字符串常量（无空白、以 `.txt` 结尾）—— 叙述性文案里提到 `.txt` 不算。"""
    return s.endswith(".txt") and not any(ch.isspace() for ch in s)


def txt_engines() -> dict[str, str]:
    """J3：`scripts/**` 里把 `.txt` 摘要当 surefire 读数源的机具 → 它声明的定点类（`UNIT = "…"`）。

    判定 = **代码里的字符串常量**里既有 `surefire-reports`、又有一个 **`.txt` 路径形态**的常量
    （docstring / 注释 / 叙述性文案里的「提及」不算 —— 本包自己的入口就在告警里讲过这个病，
    不能因此被自己判红）。
    """
    engines: dict[str, str] = {}
    for path in sorted(REPO_ROOT.glob(TXT_ENGINE_GLOB)):
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            strings = _code_strings(ast.parse(text))
        except SyntaxError:
            continue
        if not any("surefire-reports" in s for s in strings):
            continue
        if not any(_is_txt_path(s) for s in strings):
            continue
        unit = re.search(r'UNIT\s*=\s*"([^"]+)"', text)
        engines[str(path.relative_to(REPO_ROOT))] = unit.group(1) if unit else ""
    return engines


def ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


# ────────────────────────── J1 扫描器非空跑 ──────────────────────────

def test_j1_scanner_is_not_blind():
    index = jtr.index_all(REPO_ROOT)
    nested = [tc.simple for tc in index if tc.has_nested]
    assert len(index) > 100, f"Java 测试类索引只有 {len(index)} 个 ⇒ 扫描器失明（不是通过）"
    assert nested, "现取 0 个 @Nested 测试类 ⇒ 判据失明（不是通过）"
    assert ENTRY.is_file(), f"入口缺失：{ENTRY.relative_to(REPO_ROOT)}（正解入口都不在了）"
    assert MODULE_PATH.is_file(), f"入口实现缺失：{MODULE_PATH.relative_to(REPO_ROOT)}"


# ────────────────────────── J2 真空跑形态 ──────────────────────────

def test_j2_repo_has_no_bare_method_selector_on_nested_method():
    index = {tc.simple: tc for tc in jtr.index_all(REPO_ROOT)}
    hits = bad_form_hits(index)
    assert not hits, (
        "以下位置用了**会静默空跑**的写法（`-Dtest=<外层类>#<方法>`，而方法声明在 @Nested 内 ⇒ "
        "Tests run: 0 / exit=0）：\n  " + "\n  ".join(hits)
    )


def test_j2_synthetic_bad_form_is_red_and_good_forms_are_not():
    index = {tc.simple: tc for tc in jtr.index_all(REPO_ROOT)}
    nested_class = next(tc for tc in index.values() if tc.has_nested and tc.nested_owner_of(
        next(iter(set().union(*tc.nested.values())))
    ))
    owner, method = next(
        (name, sorted(methods)[0]) for name, methods in nested_class.nested.items() if methods
    )
    simple = nested_class.simple

    assert jtr.bad_selectors_in_text(f"./mvnw test -Dtest={simple}#{method}", index) == [
        (f"{simple}#{method}", f"{simple}${owner}#{method}")
    ], "合成语料里的坏形态没被判红 ⇒ 判据失效（这是「判别力自证」）"

    for good in (f"{simple}#{method}".replace("#", "$" + owner + "#"),
                 f"{simple}${owner}", simple, f"{simple}*",
                 "SomeClass#someMethodThatDoesNotExist"):
        assert jtr.bad_selectors_in_text(f"./mvnw test -Dtest={good}", index) == [], (
            f"合规写法 {good} 被判红 ⇒ 假红"
        )
    assert f"{simple}#{method}" != f"{simple}${owner}#{method}"


# ────────────────────────── J3/J4 `.txt` 读数源台账 ──────────────────────────

def test_j3_every_txt_reading_engine_is_registered_and_precondition_holds():
    data = ledger()
    index = {tc.simple: tc for tc in jtr.index_all(REPO_ROOT)}
    engines = txt_engines()
    registered = {e["file"]: e for e in data["engines"]}

    assert engines, "现取 0 个读 `.txt` 摘要的机具 ⇒ 台账无从校验（要么判据失明，要么机具已改读 XML ⇒ 删台账条目）"
    missing = sorted(set(engines) - set(registered))
    assert not missing, f"未登记的 `.txt` 读数机具（`.txt` 摘要对 @Nested 恒报 0）：{missing}"

    for name, entry in registered.items():
        path = REPO_ROOT / name
        assert path.is_file(), f"台账给不存在的机具盖章：{name}"
        text = path.read_text(encoding="utf-8", errors="replace")
        assert entry["anchor"] in text, f"台账锚未兑现：{name} 里找不到 {entry['anchor']!r}"
        assert entry["reason"].strip(), f"{name} 的登记理由为空（豁免必须写明为什么）"
        unit = entry["unit"]
        assert unit in index, f"{name} 声明的定点类 `{unit}` 不存在"
        tc = index[unit]
        assert entry["precondition"].strip()
        assert not tc.has_nested, (
            f"{name} 的前提已失效：定点类 `{unit}` 现在含 @Nested（{', '.join(sorted(tc.nested))}）⇒ "
            f"`.txt` 摘要对它恒报 Tests run: 0，机具必须改读 `target/surefire-reports/TEST-<fqn>.xml`"
        )
        assert engines.get(name) == unit, (
            f"{name} 的定点类与台账不符（现取 {engines.get(name)!r} / 台账 {unit!r}）"
        )


def test_j4_ledger_is_not_empty_and_only_shrinks():
    data = ledger()
    assert data["engines"], "台账被清空 ⇒ 红（消红不等于修好）"
    assert len(data["engines"]) <= data["frozen_baseline"], (
        f"台账膨胀：{len(data['engines'])} > 冻结基线 {data['frozen_baseline']}"
        "（豁免只许缩短；新增 `.txt` 机具请改读 XML）"
    )
    assert data["case_ids"], "台账缺 case_ids"


def test_j4_synthetic_nested_unit_would_be_red():
    """判别力自证：把台账里任一机具的定点类换成**真含 @Nested** 的类 ⇒ J3 的前提判定必须红。"""
    index = {tc.simple: tc for tc in jtr.index_all(REPO_ROOT)}
    nested_unit = next(tc.simple for tc in index.values() if tc.has_nested)
    data = ledger()
    entry = dict(data["engines"][0], unit=nested_unit)
    tc = index[entry["unit"]]
    assert tc.has_nested, "合成语料选错了类（它不含 @Nested）"
    # 与 J3 里那条断言同一谓词：前提失效 ⇒ 红
    assert tc.has_nested is True


# ────────────────────────── J5 规范指向入口 ──────────────────────────

def test_j5_development_doc_points_to_the_entry():
    doc = DEV_DOC.read_text(encoding="utf-8")
    assert "./scripts/java-test.sh" in doc, (
        "docs/wiki/Development.md 必须逐字给出正解入口 ./scripts/java-test.sh（否则下一个人又去 head .txt）"
    )
    assert "Tests run > 0" in doc or "Tests run: 0" in doc, (
        "docs/wiki/Development.md 必须写明读数口径（`.txt` 摘要对 @Nested 恒报 0 ⇒ 只信 XML 且要求大于 0）"
    )


# ────────────────────────── J6 注释不算 @Nested（对照读数） ──────────────────────────

def test_j6_comments_do_not_make_a_class_nested():
    index = {tc.simple: tc for tc in jtr.index_all(REPO_ROOT)}
    commented_only = [
        tc.simple for tc in index.values()
        if not tc.has_nested and re.search(r"@Nested", tc.path.read_text(encoding="utf-8", errors="replace"))
    ]
    assert commented_only, (
        "现取 0 个「只在注释里提到 @Nested」的测试类 ⇒ J6 的对照读数不存在了，"
        "请重新挑样本（它证明掩码生效；`git grep -l @Nested` 比索引多 1 就是它）"
    )
    for simple in commented_only:
        assert not index[simple].has_nested, f"{simple} 只在注释里出现 @Nested，却被判成嵌套类 ⇒ 掩码失效"


@pytest.mark.parametrize(
    "snippet, expect_nested",
    [
        ("class A {\n  // @Nested\n  void t() {}\n}", False),
        ("class A {\n  /* @Nested */ class B { void t() {} }\n}", False),
        ("class A {\n  @Nested\n  class B { void t() {} }\n}", True),
    ],
)
def test_j6_mask_makes_the_decision(snippet, expect_nested):
    bodies = jtr.class_bodies(jtr.mask_literals_and_comments(snippet))
    inner = [b for b in bodies if b.name == "B"]
    assert (inner[0].nested if inner else False) is expect_nested
