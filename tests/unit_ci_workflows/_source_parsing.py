# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 `_migration_paths.py` / `_sql_schema.py` 的同款声明。本 PR 不新建用例族。）
"""判据面「读源码取值」的**唯一共享实现**（issue #5323 收口包）。

## 病根（一类缺陷，不是一个缺陷）

`#5272`（权限守卫按双引号扫原文 ⇒ 注释里的 `"settings"` 被读成绑定）与 `#5286`
（automerge 分类器第二把子串尺子）修的是**同一族**：**判据把「原文文本」当「代码」读**。
`#5323` 冻结清单里剩下的 6 条**是同一份实现被抄了多遍** ——

- 四处各自 `re.search(r"VALID_ACTIONS\\s*=\\s*[\\{\\[](.*?)[\\}\\]]", …)` + 按引号 `findall`；
-  Java 侧各自拿一把「按 `//` 截断」的尺子（字符串里的 `//` 会被当成注释起点）；
- Python 侧还有一把「按 `#` 截断」的尺子（字符串里的 `#` 会吃掉行尾）。

⇒ 本模块把这三类读法收敛成**一份**实现，四处调用点只调它（与 `#5286` 复用
`.github/danger_scan.py::strip_comment` 同一条纪律：**只留一份实现**）。

## 三种读法（各自为什么是这个读法）

| 输入 | 读法 | 为什么 |
|---|---|---|
| Python 声明式配置 | `ast`：`Name = {…} / […] / (…) / {k: v}` 的**字面量成员** | 注释与文档字符串**不是** AST 节点 ⇒ 结构上不可能被读成声明 |
| Python 源码（剥注释） | `tokenize`：只丢 `COMMENT`、**保留** `STRING` | 字符串里的 `#`（`"#FF0000"`）不得吃掉行尾（`#5323` 第 7 条，方向是**漏检**） |
| Java / TS 文本 | 词法走查（**引号感知**） | 字符串里的 `//`（`"http://x"`）不得被当成注释起点（`#5323` 第 1、3 条） |

## 纪律

判据面（`tests/unit_ci_workflows/**`、`.github/*.py`、`.github/scripts/*.py`、`scripts/*.py`）
里**不许**再出现第二份「按引号扫原文」或「朴素 `#` 截断」的实现 ——
元守卫 `tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py` 会拦（未登记即红）。

## 残余（照实登记）

① `ast` 侧只认**字面量**：成员若是变量引用（`"enum": list(VALID_ACTIONS)`）只解析**一层**
   名字回指；再深的间接（函数返回值、跨模块常量）⇒ 显式报错（fail-closed，不静默给空集）；
② Java 侧是**词法**走查不是语法解析：它不校验括号/语句结构，只保证「注释里的字面量不算、
   字符串里的注释符不算」；
③ 字面量取的是**原文**（未做转义解码）：`"a\\"b"` 交出 `a\\"b`。判据面用到的都是无转义的字面量；
④ 只覆盖 Python 与 Java 文本；SQL 另有既有实现（不在本模块射程）。
"""
from __future__ import annotations

import ast
import io
import tokenize

__all__ = [
    "assigned_mapping_keys",
    "assigned_strings",
    "code_without_comments",
    "declared_strings",
    "java_code",
    "java_literals",
    "nested_string_members",
]


# ══════════════════════════════════════════════════════════════════════════════
# 一、Python：AST 读「声明式配置」
# ══════════════════════════════════════════════════════════════════════════════


def _parse(source: str, where: str) -> ast.Module:
    """`ast.parse`；语法错 ⇒ 红（解析失配必须响，不许静默给空集）。"""
    try:
        return ast.parse(source, filename=where)
    except SyntaxError as exc:
        raise AssertionError(f"{where} 无法 ast.parse（{exc}）⇒ 解析失配 ⇒ 红（同步本判据）") from exc


def _named_assignments(source: str, name: str, where: str) -> list[ast.AST]:
    """源码里**所有** `name = <值>` / `name: T = <值>` 的值节点（按源码顺序）。

    不限作用域：工具类的 `name` / `parameters` 是**类体属性**（缩进声明），模块级与类体都要认。
    不做跨函数数据流追踪（判据面读的是声明式配置，追不到时的代价是静默假绿 —— 故宁可显式报错）。
    """
    found: list[tuple[int, ast.AST]] = []
    for node in ast.walk(_parse(source, where)):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if value is None:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            found.append((node.lineno, value))
    return [value for _lineno, value in sorted(found, key=lambda item: item[0])]


def _unwrap_single_call(node: ast.AST) -> ast.AST:
    """剥掉单参无关键字的名字调用包装（`frozenset({…})` / `MappingProxyType({…})` / `list(x)`）。"""
    while (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.func, ast.Name)
    ):
        node = node.args[0]
    return node


def _container_members(node: ast.AST, where: str, source: str) -> tuple[str, ...]:
    """字面量容器（`{…}` / `[…]` / `(…)`，或 `frozenset({…})` 这类包装）里的**字符串成员**（按源码顺序）。

    `"enum": list(VALID_ACTIONS)` 这类**一层名字回指**会顺着模块/类体声明解析（残余 ① 之外的部分）。
    """
    node = _unwrap_single_call(node)
    if isinstance(node, ast.Name):
        resolved = _named_assignments(source, node.id, where)
        assert resolved, f"{where} 的 `{node.id}` 找不到声明（一层回指解析失配 ⇒ 红）"
        return _container_members(resolved[0], f"{where}::{node.id}", source)
    assert isinstance(node, (ast.Set, ast.List, ast.Tuple)), (
        f"{where} 不是字面量集合（{type(node).__name__}）⇒ 口径漂移 ⇒ 红（本判据只认字面量声明）"
    )
    out: list[str] = []
    for item in node.elts:
        assert isinstance(item, ast.Constant) and isinstance(item.value, str), (
            f"{where} 的集合里有非字符串字面量成员（{ast.dump(item)[:80]}）⇒ 口径漂移 ⇒ 红"
        )
        out.append(item.value)
    return tuple(out)


def assigned_strings(source: str, name: str, where: str) -> tuple[str, ...]:
    """`name = {…} / […] / (…)`（含 `frozenset({…})` 包装）里的字符串成员；**未声明 ⇒ `()`**。

    `#5323` 第 2/4/5/6 条的唯一实现点：旧口径 `re.search(r"VALID_ACTIONS\\s*=…")` + 按引号
    `findall` 会把**注释或文档字符串**里同形的文本读成声明（假绿：工具动作集被喂大）。
    """
    found = _named_assignments(source, name, where)
    if not found:
        return ()
    return _container_members(found[0], f"{where}::{name}", source)


def assigned_mapping_keys(source: str, name: str, where: str) -> tuple[str, ...]:
    """`name = {…}` / `name = MappingProxyType({…})` 的**字符串键**（按源码顺序）。

    `#5323` 第 3 条（**涉钱面**）的唯一实现点：注释里写 `# "old_key": 弃用` 不会被读成键
    —— 注释不是 AST 节点；旧口径按原文扫 `"key":` ⇒ 引擎「多出一个键」= 与库列集对账**假红**。
    """
    found = _named_assignments(source, name, where)
    assert found, f"{where} 里找不到 `{name} = …`（改名？那是判据的定位锚点）"
    node = _unwrap_single_call(found[0])
    assert isinstance(node, ast.Dict), (
        f"{where} 的 `{name}` 不是字面量 dict（{type(node).__name__}）⇒ 口径漂移 ⇒ 红"
    )
    out: list[str] = []
    for key in node.keys:
        assert key is not None, f"{where} 的 `{name}` 含 `**` 展开 ⇒ 键集不完整 ⇒ 红"
        assert isinstance(key, ast.Constant) and isinstance(key.value, str), (
            f"{where} 的 `{name}` 有非字符串字面量键（{ast.dump(key)[:80]}）⇒ 口径漂移 ⇒ 红"
        )
        out.append(key.value)
    return tuple(out)


def declared_strings(source: str, name: str, where: str) -> tuple[str, ...]:
    """**所有** `name = "字面量"`（含类体属性）的值（按源码顺序）；未声明 ⇒ `()`。

    用于「类属性式声明」（工具类的 `name = "customer_manage"`）：旧口径
    `^\\s*name\\s*=\\s*"…"` 扫原文 ⇒ 注释/文档字符串里写一行同名文本即被读成声明。
    """
    out: list[str] = []
    for value in _named_assignments(source, name, where):
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            out.append(value.value)
    return tuple(out)


def nested_string_members(source: str, name: str, keys: tuple[str, ...], where: str) -> tuple[str, ...]:
    """`name = {…}` 里按 `keys` 逐层下钻到的字符串容器成员；**路径不存在 ⇒ `()`**。

    用于 schema 里的 `parameters → "action" → "enum"`：旧口径用
    `"action"\\s*:\\s*\\{[^}]*?"enum"\\s*:\\s*\\[([^\\]]*)\\]` 扫**全文原文**
    ⇒ 注释里的一句同形文本即可喂大动作集（`#5323` 第 2 条）。
    """
    found = _named_assignments(source, name, where)
    if not found:
        return ()
    node = _unwrap_single_call(found[0])
    for key in keys:
        if not isinstance(node, ast.Dict):
            return ()
        entry = None
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == key:
                entry = v
                break
        if entry is None:
            return ()
        node = _unwrap_single_call(entry)
    return _container_members(node, f"{where}::{name}{keys}", source)


def code_without_comments(source: str, where: str) -> str:
    """Python 源码去掉**注释**（`tokenize`：只丢 `COMMENT`，**保留** `STRING`）。

    为什么不是按 `#` 截断（`#5323` 第 7 条）：字符串里的 `#`（`"#FF0000"`）会被朴素截断
    **吃掉行尾** ⇒ 同一行后面的断言/期望值一起消失 ⇒ 判据**漏检**（假绿方向）。
    `tokenize` 由**词法**说了算：`#` 落在字符串里就不是注释。

    实现 = 把 `COMMENT` token 的**列区间**抹成空格，其余字节逐字保留
    （行号、缩进、字符串内容都不变 —— 也就避开了 `untokenize` 重新排版的额外差异）。
    """
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise AssertionError(f"{where} 无法 tokenize（{exc}）⇒ 解析失配 ⇒ 红（同步本判据）") from exc
    lines = source.splitlines(keepends=True)
    for tok in toks:
        if tok.type != tokenize.COMMENT:
            continue
        (row, col), (_end_row, end_col) = tok.start, tok.end
        line = lines[row - 1]
        lines[row - 1] = line[:col] + " " * (end_col - col) + line[end_col:]
    return "".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 二、Java / TS：引号感知的词法走查（剥注释 / 取字面量共用**一份**走查）
# ══════════════════════════════════════════════════════════════════════════════

#: 走查产出的片段类别：`code` = 可编译代码；其余三类都不是代码。
_KIND_CODE = "code"
_KIND_LINE_COMMENT = "line_comment"
_KIND_BLOCK_COMMENT = "block_comment"
_KIND_STRING = "string"
_KIND_TEXT_BLOCK = "text_block"
_KIND_CHAR = "char"


def _java_scan(text: str) -> list[tuple[str, int, int]]:
    """Java 文本的**词法**片段序列 `(类别, 起, 止)`（唯一一份走查，两个视图共用）。

    规则（只做词法，不做语法）：`//` 到行尾、块注释、双引号字符串（含转义）、
    三引号文本块、单引号字符字面量各自成段，其余是代码段。
    ⇒ **字符串里的 `//` 不是注释**（`"http://x"` 不被截断）。
    """
    spans: list[tuple[str, int, int]] = []
    i, n, code_start = 0, len(text), 0

    def flush(end: int) -> None:
        if end > code_start:
            spans.append((_KIND_CODE, code_start, end))

    while i < n:
        ch = text[i]
        if text.startswith("//", i):
            flush(i)
            i = text.find("\n", i)
            i = n if i < 0 else i
        elif text.startswith("/*", i):
            flush(i)
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif text.startswith('"""', i):
            flush(i)
            start = i
            end = text.find('"""', i + 3)
            i = n if end < 0 else end + 3
            spans.append((_KIND_TEXT_BLOCK, start, i))
        elif ch in "\"'":
            flush(i)
            quote = ch
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote:
                    j += 1
                    break
                j += 1
            spans.append((_KIND_STRING if quote == '"' else _KIND_CHAR, i, min(j, n)))
            i = min(j, n)
        else:
            i += 1
            continue
        code_start = i
    flush(n)
    return spans


def java_code(text: str) -> str:
    """剥掉 Java 注释（`//` + `/* */`）的源码 —— **引号感知**，字符串原样保留。

    全仓唯一一份 Java 剥注释实现（`#5323` 第 1、3 条）：按 `//` 截断的旧尺子会把
    `"http://x"` 这类字符串的**后半截**一起吃掉（判据读到残缺代码）。
    注释**抹成空格**（换行保留）⇒ 行号不变，报错定位照旧可用。
    """
    out: list[str] = []
    for kind, start, end in _java_scan(text):
        chunk = text[start:end]
        if kind in (_KIND_LINE_COMMENT, _KIND_BLOCK_COMMENT):
            out.append("".join("\n" if c == "\n" else " " for c in chunk))
        else:
            out.append(chunk)
    return "".join(out)


def java_literals(text: str) -> tuple[tuple[int, str], ...]:
    """Java 文本里**双引号字符串字面量**的 `(起点下标, 原文值)`（注释里的不算；按出现顺序）。

    调用方按**前缀**过滤即可表达「这是哪一处的字面量」（例：`text[:pos].rstrip().endswith("config.put(")`）——
    取值靠**词法**，不再靠「按引号扫原文」的正则；旧口径的引号正则即使改成 `re.findall(r'"…"')`
    也仍会把注释里的字面量读进来（本轮收口要治的正是它）。
    """
    out: list[tuple[int, str]] = []
    for kind, start, end in _java_scan(text):
        if kind == _KIND_STRING:
            out.append((start, text[start + 1: max(start + 1, end - 1)]))
    return tuple(out)