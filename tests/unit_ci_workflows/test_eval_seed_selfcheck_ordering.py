# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 test_declaration_truth_guards.py / test_guard_scope_declaration.py 的同款声明；
#   本 PR 不新建用例族。）
"""评测栈 fixture 的**自检块不得引用「同文件后面才插入」的对象**（issue #5501）。

## 病灶（P1·活故障；真库实测连跑 3 次一致）

`tests/agent_eval/fixtures/mibao_eval_seed.sql` 的 **Phase 1 自检 DO 块**要求
`EVAL-MB-ORD-0006 >= 1`，而该订单由**同文件 Phase 3** 才 `INSERT` ⇒ **自检永远早于被检查对象**。
`scripts/eval_stack_seed.sh` 用 `psql -v ON_ERROR_STOP=1` ⇒ 首次运行即在该块 `RAISE EXCEPTION` 中止：

    NOTICE: ... 客户王五=1 订单0006=0
    ERROR:  B 端 fixture 注入失败：... 订单0006=0          # rc=3

⇒ **mibao persona 的评测栈根本装不起来**，且**不是幂等二跑能自救**的形态（每次都在同一行中止，
0006 永远不会被建）。既有静态守卫**全是绿的**：它们看的是「声明 / 列集 / 文本形态」，
**没有一条判「块与块之间的顺序」**（#4514 同族：静态全绿而真库必红）。

## 判据（位置性 + 机械可判）

射程 = `tests/agent_eval/fixtures/*.sql`（**冻结登记表** `SEED_FILES`；新增未登记 ⇒ 红）。
把每个文件切成**顶层语句**（注释被丢弃、字符串与 dollar-quoted 体各算一个 token），取两类事实：

| 面 | 取法 | 内容 |
|---|---|---|
| **插入面** | 首两个词是 `INSERT INTO` 的语句 | 表名 + 该语句里的**实体键字面量** + 语句起始偏移 |
| **自检面** | 首词是 `DO` 的语句 | 其 dollar-quoted 体内的**全部实体键字面量** + 块起始偏移 |

判据 = **自检块引用的实体键，若同文件里有 `INSERT` 写过它，则最早那条 `INSERT` 必须在自检块之前**；
否则判红并点名（字面量 / 自检块行号 / 最早插入行号）。

「实体键字面量」= 整串匹配 `[A-Za-z][A-Za-z0-9]*([_-][A-Za-z0-9]+)+`（`EVAL-MB-ORD-0006` /
`pi_eval_punch` / `cust_eval_wangwu` / `b1c2d3e4-…-000000000005`）。`'米'` / `'pending'` / `'active'`
这类**取值**不是被插入的对象，不在此列 —— 不筛会把取值也当键 ⇒ 假红（负控见下）。

## 红证（不会红的断言 = 空断言）

- `test_red_proof_moving_the_insert_back_is_detected`：在**真实种子文本**上重演原缺陷 ——
  把「含 `EVAL-MB-ORD-0006` 的那条 `INSERT`」整体挪到引用它的自检块**之后** ⇒ 判据必须点名它；
- `test_red_proof_reference_added_to_an_earlier_block_is_detected`：反向注入（把该读数**加回**
  文件里第一个 DO 块）⇒ 同样必红。两条各自单独能红（三臂可分辨，不是一句口号）。

## 负控（判据不能靠「文本里出现过」变红）

| 测试 | 注入 | 期望 |
|---|---|---|
| `test_negative_control_comment_mentions_are_not_references` | 自检块里写一行**注释**提及 `EVAL-MB-ORD-0006` | 绿（注释不是引用；#5323/#5325「原文口径」纪律） |
| `test_negative_control_external_entity_stays_silent` | 自检块里引用 **xiaobu seed 提供**的 `prod_eval_blackout` | 绿（跨文件依赖不在面内，见边界） |
| `test_negative_control_value_literals_are_not_entities` | 自检块里引用 `'米'` / `'pending'` | 绿（取值不是实体键） |
| `test_failclosed_on_unterminated_dollar_quote` | 未闭合的 `$$` | `AssertionError`（fail-closed，**不是**静默少扫几块） |

## 边界（照实登记，不是「已覆盖」）

- **跨文件依赖不在面内**：引用**另一个** seed 提供的实体（如 `prod_eval_blackout`）时，本文件里
  没有对应 `INSERT` ⇒ 判据**沉默**（分不清「外部对象」与「拼错了的键」）。
- **模式/前缀引用不在面内**：`LIKE 'EVAL-MB-ORD-%'` 与本文件 `INSERT` 的字面量不相等 ⇒ 沉默。
- **动态 SQL**（`EXECUTE` 拼表名/键）不在面内（本仓种子不用）。
- 本判据只判**顺序**，不判「对象在库上真的存在」—— 后者是同一批块里 `RAISE EXCEPTION` 的真库职责。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO / "tests" / "agent_eval" / "fixtures"

#: 射程 = 评测栈 fixture 的**冻结登记表**（新增 `.sql` 未登记 ⇒ 本判据漏判 ⇒ 必须红）。
SEED_FILES = ("mibao_eval_seed.sql", "xiaobu_eval_seed.sql")

#: 「实体键」字面量（口径见 docstring）—— 整串匹配才算（`fullmatch`），子串不算。
KEY_LITERAL_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[_-][A-Za-z0-9]+)+")

#: 自检块里**被核对**的实体键引用条数下限（**现取 = 23**，2026-09-25；
#: 删自检块 / 删引用会让它红，只许上调 —— 种子收缩时同 PR 下调并在 diff 里可见）。
CHECKED_REF_FLOOR = 23

_DOLLAR_OPEN_RE = re.compile(r"\$\$|\$[A-Za-z_][A-Za-z0-9_]*\$")
_WORD_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
)


@dataclass(frozen=True)
class Token:
    """词法单元：`kind` ∈ `string` / `dollar` / `word` / `semi`；`start` = 在**原文**里的偏移。"""

    kind: str
    value: str
    start: int


@dataclass(frozen=True)
class Insertion:
    """一条 `INSERT INTO <table> …`（文件顺序）。"""

    table: str
    literals: frozenset
    offset: int
    line: int


@dataclass(frozen=True)
class CheckedRef:
    """自检块里的一处实体键引用（按「块 + 字面量」去重）。"""

    literal: str
    block_line: int
    block_offset: int


def _tokens(text: str):
    """词法扫描 → `Token` 流。**注释不是 token**（直接丢弃）；字符串 / dollar-quoted 体各一个 token。

    为什么不用 `re.findall` 那类原文口径（§23「判据把原文当代码读」）：注释里写一句
    「见 EVAL-MB-ORD-0006」就会喂中那种写法 —— 本判据必须能分辨「说明文字」与「真引用」。
    未闭合的块注释 / 字符串 / dollar-quoted 块 ⇒ `AssertionError`（fail-closed，
    **不是**静默少扫几块后判绿）。
    """
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "-" and text.startswith("--", i):
            newline = text.find("\n", i)
            i = n if newline < 0 else newline + 1
            continue
        if ch == "/" and text.startswith("/*", i):
            depth, j = 1, i + 2
            while j < n and depth > 0:
                if text.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif text.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            assert depth == 0, f"未闭合的块注释（偏移 {i}）—— fail-closed"
            i = j
            continue
        if ch == "'":
            j = i + 1
            while j < n and text[j] != "'":
                j += 1
            assert j < n, f"未闭合的字符串字面量（偏移 {i}）—— fail-closed"
            value = text[i + 1:j]
            i = j + 1
            while i < n and text[i] == "'":  # PG 的 `''` = 字面单引号：整体仍是一个 token
                k = i + 1
                while k < n and text[k] != "'":
                    k += 1
                assert k < n, f"未闭合的字符串字面量（偏移 {i}）—— fail-closed"
                value += "'" + text[i + 1:k]
                i = k + 1
            yield Token("string", value, i)
            continue
        matched = _DOLLAR_OPEN_RE.match(text, i) if ch == "$" else None
        if matched is not None:
            tag = matched.group(0)
            end = text.find(tag, matched.end())
            assert end >= 0, f"未闭合的 dollar-quoted 块（偏移 {i}，tag={tag}）—— fail-closed"
            yield Token("dollar", text[matched.end():end], i)
            i = end + len(tag)
            continue
        if ch in _WORD_CHARS:
            j = i
            while j < n and text[j] in _WORD_CHARS:
                j += 1
            yield Token("word", text[i:j], i)
            i = j
            continue
        if ch == ";":
            yield Token("semi", ";", i)
            i += 1
            continue
        i += 1


def iter_statements(text: str):
    """→ `[(start, end, [Token, …]), …]`：按**顶层** `;` 切句（注释已丢；字符串/dollar 体是单 token）。

    `end` = 该句结束（含 `;`，末句无 `;` 时为文本末尾）—— 红证的「整条搬走」靠它做切片。
    """
    statements, current = [], []
    for token in _tokens(text):
        if token.kind == "semi":
            if current:
                statements.append((current[0].start, token.start + 1, current))
                current = []
            continue
        current.append(token)
    if current:  # 末句缺 `;`：fail-safe 收进来，不静默丢句
        statements.append((current[0].start, len(text), current))
    return statements


def _words(tokens) -> list:
    return [t.value.upper() for t in tokens if t.kind == "word"]


def _table_of(tokens) -> str:
    """`INSERT INTO <table>` 的表名（**保持原文大小写**，只用于报错点名）。"""
    words = [t for t in tokens if t.kind == "word"]
    for index, token in enumerate(words[:-1]):
        if token.value.upper() == "INTO":
            return words[index + 1].value
    return "?"


def key_literals(tokens) -> set:
    """token 流里的大括号**实体键**字面量（含义见 docstring；取值字面量不在内）。"""
    return {
        t.value for t in tokens
        if t.kind == "string" and KEY_LITERAL_RE.fullmatch(t.value)
    }


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def block_refs(tokens) -> set:
    """`DO` 语句的 dollar-quoted 体内引用的实体键（含 `SELECT … INTO` / `RAISE` / 条件分支）。"""
    refs = set()
    for token in tokens:
        if token.kind != "dollar":
            continue
        for _start, _end, body_tokens in iter_statements(token.value):
            refs |= key_literals(body_tokens)
    return refs


def parse_fixture(text: str):
    """→ `(插入面, 自检面)`：`[Insertion, …]`（文件顺序）+ `[CheckedRef, …]`（按块+字面量去重）。"""
    insertions, refs = [], {}
    for start, _end, tokens in iter_statements(text):
        words = _words(tokens)
        if words[:2] == ["INSERT", "INTO"]:
            insertions.append(Insertion(
                table=_table_of(tokens),
                literals=frozenset(key_literals(tokens)),
                offset=start,
                line=_line_of(text, start),
            ))
            continue
        if words[:1] != ["DO"]:
            continue
        body_tokens = [t for t in tokens if t.kind == "dollar"]
        block_line = _line_of(text, start)
        assert len(body_tokens) == 1, (
            f"DO 块（{block_line} 行）的 dollar-quoted 体不是恰好 1 个 —— fail-closed"
        )
        for literal in sorted(block_refs(body_tokens)):
            refs[(block_line, literal)] = CheckedRef(
                literal=literal, block_line=block_line, block_offset=start,
            )
    return insertions, sorted(refs.values(), key=lambda r: (r.block_line, r.literal))


def find_ordering_violations(text: str) -> list:
    """→ 违规清单（空 = 通过）：自检块引用了**同文件后面才插入**的对象。"""
    insertions, checks = parse_fixture(text)
    earliest = {}
    for insertion in insertions:  # 文件顺序 ⇒ 首次写入即最早
        for literal in insertion.literals:
            earliest.setdefault(literal, insertion)
    violations = []
    for check in checks:
        insertion = earliest.get(check.literal)
        if insertion is None or insertion.offset < check.block_offset:
            continue
        violations.append(
            f"自检块（{check.block_line} 行）引用 '{check.literal}'，"
            f"但它最早的 INSERT 在其后（{insertion.line} 行：INSERT INTO {insertion.table}）"
        )
    return violations


def _read(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


# ── 判据本体 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", SEED_FILES)
def test_selfcheck_never_references_a_later_insert(name):
    """承重判据：自检块只许引用「同文件里已经插入过」的实体（issue #5501）。"""
    violations = find_ordering_violations(_read(name))
    assert violations == [], (
        f"{name}：自检块引用了同文件后面才插入的对象 —— `psql -v ON_ERROR_STOP=1` 会当场中止，"
        f"评测栈装不起来（issue #5501 的形态）。改法二选一：把插入提前，或把该读数挪到插入之后。\n  - "
        + "\n  - ".join(violations)
    )


def test_sweep_is_frozen_to_every_eval_fixture():
    """射程冻结：`fixtures/*.sql` 与登记表逐字相等（新增未登记 ⇒ 漏判 ⇒ 红）。"""
    on_disk = sorted(p.name for p in FIXTURE_DIR.glob("*.sql"))
    assert on_disk == sorted(SEED_FILES), (
        "评测 fixture 射程与冻结登记表不一致（往 SEED_FILES 登记新文件，否则本判据漏判）："
        f"磁盘={on_disk} 登记表={sorted(SEED_FILES)}"
    )


def test_selfcheck_floor_is_live_printed_and_not_vacuous(capsys):
    """燃尽锚点：读数**现取**并打印；自检块/引用被删光 ⇒ 判据会退化成空断言 ⇒ 这里判红。"""
    readings, total = [], 0
    for name in SEED_FILES:
        insertions, checks = parse_fixture(_read(name))
        total += len(checks)
        readings.append(
            f"{name}: INSERT 语句={len(insertions)} 自检引用（块+键，去重）={len(checks)}"
        )
    report = "\n".join(readings) + f"\n合计自检引用={total} 下限={CHECKED_REF_FLOOR}"
    with capsys.disabled():  # 读数要进 CI 日志（不靠 `-s`）
        print(report)
    assert total >= CHECKED_REF_FLOOR, (
        f"自检引用条数 {total} < 下限 {CHECKED_REF_FLOOR} —— 自检块或引用被删（判据可能已空转）；"
        "确属种子收缩时请**同 PR** 下调该下限并在 diff 里可见，不许静默。\n" + report
    )


# ── 红证（注入式；在**真实种子文本**上重演缺陷形态）────────────────────────

def _relocate_insert_after_its_selfcheck(text: str, literal: str) -> str:
    """把「含 `literal` 的那条 `INSERT`」整体挪到「引用它的自检块」之后（= 重演 #5501）。

    整条语句搬运（不是拆行）：`EVAL-MB-ORD-0005/0006` 本就同处一条多行 `INSERT` ⇒ 两条一起搬，
    判据会逐条点名 —— 这正是「自检早于被检查对象」在文本上的形态。
    """
    statements = iter_statements(text)
    insert_span = None
    check_span = None
    for start, end, tokens in statements:
        words = _words(tokens)
        if insert_span is None and words[:2] == ["INSERT", "INTO"] and literal in key_literals(tokens):
            insert_span = (start, end)
        if check_span is None and words[:1] == ["DO"] and literal in block_refs(tokens):
            check_span = (start, end)
    if insert_span is None or check_span is None:
        # 显式抛错而不是裸存在性断言（本仓禁止「只证东西在」的弱断言；这里要的是**前提**校验）
        raise AssertionError(
            f"红证夹具前提不成立：含 '{literal}' 的 INSERT = {insert_span}，"
            f"引用它的自检块 = {check_span}（种子结构变了 ⇒ 先修夹具）"
        )
    moved = text[insert_span[0]:insert_span[1]]
    if insert_span[1] <= check_span[0]:
        # 修好后的形态：插入在自检之前 ⇒ 挪到该自检块**之后**（= 重演原缺陷的形态）
        return text[:insert_span[0]] + text[insert_span[1]:check_span[1]] + moved + text[check_span[1]:]
    # 缺陷态（未修的种子）：插入本就在自检之后 ⇒ 再往后挪到文件末尾，形态仍是「自检早于插入」
    return text[:insert_span[0]] + text[insert_span[1]:] + "\n" + moved


def test_red_proof_moving_the_insert_back_is_detected():
    """红证①：把插入挪回自检之后 ⇒ 承重判据必红（这条不会红就说明判据是空断言）。"""
    injected = _relocate_insert_after_its_selfcheck(_read("mibao_eval_seed.sql"), "EVAL-MB-ORD-0006")
    violations = find_ordering_violations(injected)
    assert violations != [], "把 EVAL-MB-ORD-0006 的 INSERT 挪到自检之后，判据居然没红 = 空断言"
    assert any("EVAL-MB-ORD-0006" in v for v in violations), (
        f"判据红了但没点名被搬走的那个键：{violations}"
    )


def test_red_proof_reference_added_to_an_earlier_block_is_detected():
    """红证②：反向注入 —— 把该读数**加回文件里第一个 DO 块**（在插入之前）⇒ 同样必红。"""
    text = _read("mibao_eval_seed.sql")
    first_do = next(s for s in iter_statements(text) if _words(s[2])[:1] == ["DO"])
    anchor = text.index("\nBEGIN\n", first_do[0], first_do[1]) + len("\nBEGIN\n")
    probe = (
        "  SELECT count(*) INTO v_probe FROM orders\n"
        "   WHERE order_no = 'EVAL-MB-ORD-0006' AND deleted = 0;\n"
    )
    violations = find_ordering_violations(text[:anchor] + probe + text[anchor:])
    assert any("EVAL-MB-ORD-0006" in v for v in violations), (
        f"把 0006 的读数加回更早的自检块，判据居然没点名它：{violations}"
    )


# ── 负控（判据不许靠「文本里出现过」变红）──────────────────────────────────

def _first_do_anchor(text: str) -> int:
    first_do = next(s for s in iter_statements(text) if _words(s[2])[:1] == ["DO"])
    return text.index("\nBEGIN\n", first_do[0], first_do[1]) + len("\nBEGIN\n")


def test_negative_control_comment_mentions_are_not_references():
    """注释里提及 ⇒ **必须绿**（说明文字不是引用；「原文口径」纪律 #5323/#5325）。

    注入点选**第一个 DO 块**（它在 `oit_mb_0002` 的 INSERT 之前）；被提及的键刻意挑
    **没有任何自检块真正引用**的那个（`oit_mb_0002`）—— 否则「违规清单里有没有它」分不清
    「注释被当引用」与「别处真实的顺序缺陷」。
    """
    text = _read("mibao_eval_seed.sql")
    anchor = _first_do_anchor(text)
    literal = "oit_mb_0002"  # 由后面的 INSERT INTO order_items 插入；自检块从不引用它
    _insertions, checks = parse_fixture(text)
    assert all(c.literal != literal for c in checks), f"负控前提不成立：'{literal}' 已被自检块引用"
    commented = (
        text[:anchor]
        + f"  -- 留档：{literal} 由后面的 INSERT 写入（本行只是说明文字，不是引用）\n"
        + text[anchor:]
    )
    violations = find_ordering_violations(commented)
    assert not any(literal in v for v in violations), (
        f"注释里的键被当成了引用（判据在吃自己的说明文字）：{violations}"
    )


def test_negative_control_external_entity_stays_silent():
    """引用**另一个 seed** 提供的实体（本文件没有它的 INSERT）⇒ 沉默 = 绿（边界，非漏洞）。"""
    text = _read("mibao_eval_seed.sql")
    external = "debug_customer_1"  # xiaobu_eval_seed.sql 的 C 端顾客；mibao 文件里零 INSERT 写它
    insertions, _checks = parse_fixture(text)
    assert all(external not in ins.literals for ins in insertions), (
        f"负控前提不成立：'{external}' 在 mibao 文件里有 INSERT（应换一个真正的外部实体）"
    )
    anchor = _first_do_anchor(text)
    probe = f"  SELECT count(*) INTO v_ext FROM users WHERE user_id = '{external}';\n"
    assert not any(external in v for v in find_ordering_violations(text[:anchor] + probe + text[anchor:]))


def test_negative_control_value_literals_are_not_entities():
    """取值字面量（`'米'` / `'pending'`）不是实体键 ⇒ 不进引用面（否则假红）。"""
    text = _read("mibao_eval_seed.sql")
    anchor = _first_do_anchor(text)
    probe = (
        "  SELECT count(*) INTO v_val FROM after_sales_tickets\n"
        "   WHERE status = 'pending' AND ticket_type = 'return' AND unit = '米';\n"
    )
    injected = text[:anchor] + probe + text[anchor:]
    _insertions, checks = parse_fixture(injected)
    flagged = {c.literal for c in checks if c.block_line <= 200}
    assert flagged.isdisjoint({"pending", "return", "米"}), f"取值字面量被当成实体键：{flagged}"
    violations = find_ordering_violations(injected)
    assert not any(literal in v for v in violations for literal in ("pending", "return", "米"))


def test_failclosed_on_unterminated_dollar_quote():
    """未闭合的 dollar-quoted 块 ⇒ fail-closed 抛错（**不是**静默判绿）。"""
    with pytest.raises(AssertionError):
        find_ordering_violations("DO $$\nBEGIN\n  RAISE NOTICE 'x';\nEND;\n")