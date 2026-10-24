"""活 seed SQL 的**静态**解析（issue #7583；规范 = docs/testing/smoke-data-quality.md 的 D1/D2/D3）。

为什么要有它：seed 是**数据真值源**之一（`docs/deployment/demo-seed.sql` 用 `psql -f` 打演示库、
`tests/agent_eval/fixtures/*.sql` 打评测栈），而数据质量的缺口（状态枚举越界 / SKU 矩阵残缺 /
金额链不闭合）在「列存在」类判据下**一条都不会红** —— 它们全部是**值**层面的问题。
判据必须在**零网络零 DB** 下可复算（CI 与包内定点跑），所以这里做纯文本解析。

只认本仓 seed 实际在用的形态（不写一个通用 SQL 引擎）：

* **字面量行**：`INSERT INTO <表> (<列…>) SELECT <表达式…> [FROM/WHERE …]`
  —— 表达式列表按**顶层逗号**切分；`:tenant_id` / `NOW()` 这类**表达式**原样保留，
  只有真字面量（`'…'` / 数字）才可参与取值判定。
* **元组行**：`INSERT INTO <表> (<列…>) SELECT … FROM (VALUES (…), (…)) AS v(<列…>) …`
  —— 矩阵以元组写出来时走这条（行 = 元组，列 = 别名清单）。

**边界（照实登记）**：不是 SQL 语义解析器 —— 不做 JOIN / 子查询求值、不展开数组。
⇒ seed 里凡是「判据要判的值」都必须写成**字面量**（这正是 issue #7583 缺陷 2 的修法：
SKU 矩阵逐行显式，判据才能逐行读）；遇到判不了的形态，调用方**必须 fail-closed**
（`rows()` 会对列数/值数不齐的语句抛错，**不许**静默跳过 —— 判不了 ≠ 通过）。
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from ._sql_schema import strip_sql_comments

_INSERT_RE = re.compile(r"INSERT\s+INTO\s+(\w+)\s*\(([^)]*)\)", re.I | re.S)
_VALUES_RE = re.compile(r"\(VALUES\b([\s\S]*?)\)\s*AS\s+\w+\s*\(([^)]*)\)", re.I)
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _split_top_level(text: str) -> list[str]:
    """按**顶层**逗号切分（跳过括号 / 引号内的逗号）。"""
    parts, buf, depth, quote = [], [], 0, ""
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _statements(sql: str) -> list[str]:
    """剥注释后按**引号之外**的 `;` 切语句。"""
    text = strip_sql_comments(sql)
    out, buf, quote = [], [], ""
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch == ";":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        out.append("".join(buf))
    return [s for s in out if s.strip()]


def _parse_tuples(text: str) -> list[list[str]]:
    """`(…), (…)` → 每行的顶层字段列表。"""
    rows, buf, depth, quote = [], [], 0, ""
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch == "(":
            depth += 1
            if depth == 1:
                buf = []
                continue
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            if depth == 0:
                rows.append(_split_top_level("".join(buf)))
                buf = []
                continue
            buf.append(ch)
        else:
            buf.append(ch)
    return rows


def parse_seed(sql: str) -> list[dict]:
    """一份 seed 原文 → 每条带显式列清单的 `INSERT INTO <表> (…)` 的解析结果。

    返回 `[{table, columns, literals, values, value_columns, sql}]`（`table` 小写）：
    `literals` = SELECT 后面的表达式列表（可能含 `:tenant_id` 等非字面量）；
    `values` = `(VALUES …)` 的元组列表（无该形态 ⇒ `None`）。
    """
    blocks = []
    for stmt in _statements(sql):
        m = _INSERT_RE.search(stmt)
        if not m:
            continue
        table = m.group(1).lower()
        columns = [c.strip().strip('"') for c in _split_top_level(m.group(2))]
        rest = stmt[m.end():]
        values = value_columns = None
        vm = _VALUES_RE.search(rest)
        if vm:
            values = _parse_tuples(vm.group(1))
            value_columns = [c.strip() for c in _split_top_level(vm.group(2))]
        literals = None
        sm = re.search(r"\bSELECT\b", rest, re.I)
        if sm:
            body = re.split(r"\bFROM\b|\bWHERE\b", rest[sm.end():], maxsplit=1, flags=re.I)[0]
            literals = _split_top_level(body)
        blocks.append({"table": table, "columns": columns, "literals": literals,
                       "values": values, "value_columns": value_columns, "sql": stmt})
    return blocks


def rows(sql: str, table: str) -> list[dict]:
    """`<table>` 的行 → `[{列: 原文}]`（元组形态用别名清单，字面量形态用 INSERT 列清单）。

    fail-closed：列数 / 值数不齐、或既不是 `VALUES` 也不是字面量 `SELECT` 形态 ⇒ 抛错
    （「判不了 ⇒ 跳过」正是本仓最忌讳的假绿）。
    """
    out = []
    for block in parse_seed(sql):
        if block["table"] != table.lower():
            continue
        if block["values"] is not None:
            cols = block["value_columns"]
            for tup in block["values"]:
                assert len(tup) == len(cols), (
                    f"fail-closed：表 `{table}` 的元组有 {len(tup)} 个值，别名清单 {len(cols)} 列 —— "
                    f"判不了。语句：{block['sql'][:180]}…")
                out.append(dict(zip(cols, tup)))
            continue
        literals = block["literals"]
        if literals is None:
            raise ValueError(
                f"fail-closed：表 `{table}` 的 INSERT 既无 `VALUES` 元组、也无 `SELECT` —— 判不了。"
                f"语句：{block['sql'][:180]}…")
        assert len(literals) == len(block["columns"]), (
            f"fail-closed：表 `{table}` 的列数 {len(block['columns'])} ≠ SELECT 值数 {len(literals)} —— "
            f"判不了（值不是字面量列表时，seed 侧请改成显式字面量）。语句：{block['sql'][:180]}…")
        out.append(dict(zip(block["columns"], literals)))
    return out


def literal(raw: str) -> Any:
    """表达式原文 → 值：引号串去引号 / 数字转 `Decimal` / 其余原样返回（`:tenant_id`、`NOW()` …）。

    判定「这个字段到底是不是字面量」的判据：`isinstance(literal(x), (str, Decimal))` 之外
    还可能是**表达式字符串** —— 调用方要判的列必须能转成数值/已知枚举，否则视为判不了。
    """
    s = raw.strip()
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if _NUMBER_RE.fullmatch(s):
        return Decimal(s)
    return s


def read(path: Path) -> str:
    """读 seed 文件（不存在 ⇒ 抛错，不静默返回空串）。"""
    assert path.is_file(), f"fail-closed：登记的 seed 不存在（读了 {path}）—— 扫描会空转成假绿"
    return path.read_text(encoding="utf-8")
