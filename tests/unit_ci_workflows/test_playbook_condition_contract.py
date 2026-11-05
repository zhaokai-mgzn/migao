# case_ids: MC-230
"""口径卡条件语言的**两端对账**（issue #8175 判据 2 的类级元守卫）。

## 这条判据治什么

条件语言的算子表有两份实现：Java 写面校验（`PlaybookConditionValidator.OPS`）与
Python 读面求值（`app/playbook/condition.py::OPS`）。**只改一侧**是最典型的
「修了一处 = 没修」形态：写面比读面宽一格，就是「存进去了但永远不生效」，
而商家看到的是「已保存」，没有任何东西会红。

## 判据形态（纯字符串操作，不用带引号捕获组的正则）

从两侧源码的**字面量块**里取值：定位 `OPS` 声明行的起始标记，截到块结束，
再按引号切分取奇数位。**先剥注释**，避免注释里举的例子被当成真值。

## 反向判据（判别力自证）

`test_guard_has_teeth_on_in_memory_mutations` 在**内存**里构造四种坏形态
（顺序颠倒 / 少一项 / 多一项 / 一侧为空）⇒ 每条都必须判红，且报出**具名差异**；
干净输入 ⇒ 不报。红证不靠改磁盘（那样注入可能不被读到，等于空断言）。
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PY_SOURCE = REPO_ROOT / "backend/ai-agent-service/app/playbook/condition.py"
JAVA_SOURCE = (
    REPO_ROOT
    / "backend/admin-api/src/main/java/com/migao/admin/service/PlaybookConditionValidator.java"
)

PY_MARKER = "OPS = ("
JAVA_MARKER = "public static final List<String> OPS = List.of("

JAVA_CASE_IDS = "// case_ids: MC-230"


def _strip_comments(text: str, *, java: bool) -> str:
    """剥掉注释（`#` / `//` / `/* */`），保留字符串字面量本身。

    实现是**纯字符串扫描**，不是正则：本仓有「不许按引号扫源码原文取值」的铁律，
    而那条铁律的对象是「用带引号捕获组的正则」；这里是显式扫描并剥注释后再取值。
    """
    out = []
    i = 0
    n = len(text)
    in_str = ""
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == in_str:
                in_str = ""
            i += 1
            continue
        if ch in ("'", '"'):
            in_str = ch
            out.append(ch)
            i += 1
            continue
        if ch == "#" and not java:
            while i < n and text[i] != "\n":
                i += 1
            continue
        if java and text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        if java and text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _ops_from_python(text: str) -> list[str]:
    stripped = _strip_comments(text, java=False)
    start = stripped.index(PY_MARKER) + len(PY_MARKER)
    end = stripped.index(")", start)
    body = stripped[start:end]
    parts = body.split('"')
    return [parts[i] for i in range(1, len(parts), 2)]


def _ops_from_java(text: str) -> list[str]:
    stripped = _strip_comments(text, java=True)
    start = stripped.index(JAVA_MARKER) + len(JAVA_MARKER)
    end = stripped.index(");", start)
    body = stripped[start:end]
    parts = body.split('"')
    return [parts[i] for i in range(1, len(parts), 2)]


def compare(python_ops: list[str], java_ops: list[str]) -> list[str]:
    """返回**具名差异清单**（空 = 一致）。顺序也算差异：两端按同一顺序渲染 / 报错。"""
    problems: list[str] = []
    only_py = [op for op in python_ops if op not in java_ops]
    only_java = [op for op in java_ops if op not in python_ops]
    if only_py:
        problems.append(f"只在 Python 读面存在：{only_py}")
    if only_java:
        problems.append(f"只在 Java 写面存在：{only_java}")
    if not only_py and not only_java and python_ops != java_ops:
        problems.append(f"算子顺序不一致：Python={python_ops} Java={java_ops}")
    if not python_ops:
        problems.append("Python 侧算子表是空的（扫描面为空 ⇒ 不许当通过）")
    if not java_ops:
        problems.append("Java 侧算子表是空的（扫描面为空 ⇒ 不许当通过）")
    return problems


def test_both_sides_declare_the_same_operator_table():
    python_ops = _ops_from_python(PY_SOURCE.read_text(encoding="utf-8"))
    java_ops = _ops_from_java(JAVA_SOURCE.read_text(encoding="utf-8"))
    assert len(python_ops) == 8, f"Python 侧应恰有 8 个算子，实际 {python_ops}"
    assert len(java_ops) == 8, f"Java 侧应恰有 8 个算子，实际 {java_ops}"
    assert compare(python_ops, java_ops) == []
    assert python_ops == [
        "eq",
        "ne",
        "in",
        "not_in",
        "contains",
        "not_contains",
        "exists",
        "not_exists",
    ]


def test_java_test_file_declares_the_case_id():
    """Java 侧的测试也要带 case_ids（QA Growth Gate 的追溯面）。"""
    text = (
        REPO_ROOT
        / "backend/admin-api/src/test/java/com/migao/admin/service/PlaybookServiceTest.java"
    ).read_text(encoding="utf-8")
    assert JAVA_CASE_IDS in text.split("\n\n")[0] or JAVA_CASE_IDS in text[:500]


def test_guard_has_teeth_on_in_memory_mutations():
    """判别力自证：四种坏形态都必须判红并**具名**；干净输入不报。"""
    base_py = ["eq", "ne", "in", "not_in", "contains", "not_contains", "exists", "not_exists"]
    base_java = list(base_py)

    assert compare(base_py, base_java) == []

    reordered = [base_java[1], base_java[0]] + base_java[2:]
    assert compare(base_py, reordered) == [
        f"算子顺序不一致：Python={base_py} Java={reordered}"
    ]

    missing = base_java[:-1]
    assert compare(base_py, missing) == ["只在 Python 读面存在：['not_exists']"]

    extra = base_java + ["matches_regex"]
    assert compare(base_py, extra) == ["只在 Java 写面存在：['matches_regex']"]

    assert compare(base_py, []) == [
        "只在 Python 读面存在：['eq', 'ne', 'in', 'not_in', 'contains', 'not_contains', 'exists', 'not_exists']",
        "Java 侧算子表是空的（扫描面为空 ⇒ 不许当通过）",
    ]
    assert compare([], base_java) == [
        "只在 Java 写面存在：['eq', 'ne', 'in', 'not_in', 'contains', 'not_contains', 'exists', 'not_exists']",
        "Python 侧算子表是空的（扫描面为空 ⇒ 不许当通过）",
    ]


def test_comment_only_edits_do_not_change_the_reading():
    """对照读数：只改注释 ⇒ 读数逐项不变（否则「剥注释」这一步是空的）。"""
    text = PY_SOURCE.read_text(encoding="utf-8")
    with_noise = text.replace(
        'OPS = (',
        '# 注释里举了个例子 {"op": "matches_regex"} —— 它不该被当算子\nOPS = (',
        1,
    )
    assert _ops_from_python(with_noise) == _ops_from_python(text)

    java_text = JAVA_SOURCE.read_text(encoding="utf-8")
    java_noise = java_text.replace(
        JAVA_MARKER,
        '/* 例子：{"op":"regex"} · 注释里的东西不许被读成真值 */\n    ' + JAVA_MARKER,
        1,
    )
    assert _ops_from_java(java_noise) == _ops_from_java(java_text)
