# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 test_agent_permission_parity.py / test_automerge_bot_safe_path.py / test_merge_gate.py
#   的同款声明与 `.github/cases/misc.yml` MC-012 的登记。本 PR 不新建用例族。）
r"""判据面的「原文口径」**元守卫**（issue #5325 类别 1；冻结清单 = issue #5323）。

## 病根（一类缺陷，不是一个缺陷）

`#5272`（权限守卫按双引号扫源码原文 ⇒ 注释里的 `"settings"` 被读成「仍绑定」）与
`#5286`（automerge 分类器第二把子串尺子）修的是**同一族**：**判据把「原文文本」当「代码」读**。
`#5323` 清扫后仍列出 6 处未收口 —— 说明这一族**没有机制拦得住「下一个同类」**：
每一条都靠人发现、人修、人再发现。本文件就是那条机制。

## 本守卫钉的**形态**（为什么是语义、不是一行字面量）

对**每一个**「取值型正则调用」（`re.findall` / `re.finditer` / `re.search` / `re.match` /
`re.fullmatch`），从 **AST** 取它的**实际实参**（pattern 字面量 / 模块级常量 / `re.compile(literal)`；
非常量则退化为「该表达式里所有字符串字面量拼接」当见证），再要求**两个条件同时成立**：

| 条件 | 取法（结构化 / 位置性证据） | 语义 |
|---|---|---|
| **① 引号定界的捕获组** | 在 pattern **本身**上走一遍（跳过 `\\` 转义与 `[...]` 字符类），看是否有引号字符**紧跟** `(` | 正则的取值区间落在**引号之间** ⇒ 它是「按引号扫原文取值」 |
| **② 注释/字符串喂得中** | 把该正则**真跑一遍**（带调用点实参里的 `flags`）在「注释语料 + 文档字符串语料」上 | 它**分不清**注释/字符串与代码 ⇒ 注释或 docstring 里一句「看起来像声明」的话就能喂中它 |

条件 ② 是**判别力实验**，不是文案匹配：判定的取值来自**被扫描文件的 AST 实参**与**正则引擎的实际行为**，
不来自「某文件里出现了一句注释」。所以：

- 只写一句说明性注释 / docstring / 字符串**不会**让本守卫变红（守卫读的是 `re.*` 的实参，不是全文）；
- 把值**真**写进代码仍照旧会被**原判据**判红（本守卫不动任何既有判据的强度）；
- **合法重构不误伤**：锚点足够具体的正则（`@JsonProperty\s*\(\s*"([^"]+)"\s*\)`、`new MenuNode\("..."`、
  `TIMESTAMPTZ\s+'([^']+)'`）+ 先剥注释/字符串再取值的实现，都不会命中（② 喂不中）。

**为什么不按「target 是不是从源码文件读来的」判**：那需要跨函数数据流追踪，而本仓的解析器普遍
把文本当**参数**传（`_jsonb_list(text)` / `_tool_action_enum(src)`）⇒ 追不到就**静默假绿**，
比这里「按形态判、宽一点但看得见」更坏。**宽出来的部分全部落进白名单台账**（见下），不隐藏。

## 白名单 = 台账（数据文件 `guard_parsing_allowlist.json`）

- 每条含 `path` / `rule` / `hits`（**现取条数**）/ `reason` / `issue`；
  **缺 `reason` 或 `issue` ⇒ 必红**（`test_every_ledger_entry_carries_reason_and_issue`）。
- **只许缩短**：台账是**燃尽**用的。① 未登记的命中 ⇒ 红（`*_is_ledgered`）；
  ② 已登记的文件命中数**变了**（涨或跌）⇒ 红（`test_every_ledger_entry_is_live_and_exact`）；
  ③ 文件已无命中而条目还在（**陈旧条目**）⇒ 红。⇒ 想"加一条豁免吸收新债务"必须先改这个数据文件，
  在 diff 里**看得见**；想"修好了不销账"同样会红。**燃尽锚点 = 现取的条目数与命中数**（见各测打印）。
- 台账里**没有**兜底条目、**没有**「其余全部豁免」的口子。

## 残余（照实登记，见 PR body）

① 条件是「引号**紧跟** `(`」⇒ 形如 `"?(...)` 的 SQL 可选引号解析不在命中面（有意：它不是引号定界取值）；
② 见证语料是**样本**不是全集：锚点奇特到喂不中的原文口径仍可能漏判（**假绿方向**，不会误伤）；
③ 非常量 pattern 走「字面量拼接」退化见证，动态拼出的引号口径可能漏判；
④ 只覆盖 4 个判据面（`tests/unit_ci_workflows/**`、`.github/*.py`、`.github/scripts/*.py`、`scripts/*.py`），
   `.github/workflows/**`、`scripts/*.sh` 与业务测试面**不在**面内；
⑤ 性能预筛（`_may_contain_candidate`）按「源码里是否留下引号紧跟 `(` 的痕迹」跳过 `ast.parse` ⇒
   把 pattern **动态拼接**（`'"' + '('`）且源码里无该痕迹的写法会漏判（假绿方向）。

判据 = 本文件；一键复算：
`python3 -m pytest tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py -q -s`
"""

from __future__ import annotations

import ast
import json
import re
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_CI_DIR = REPO_ROOT / "tests" / "unit_ci_workflows"
GITHUB_DIR = REPO_ROOT / ".github"
GITHUB_SCRIPTS_DIR = GITHUB_DIR / "scripts"
SCRIPTS_DIR = REPO_ROOT / "scripts"
ALLOWLIST_PATH = UNIT_CI_DIR / "guard_parsing_allowlist.json"
SELF_REL = "tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py"

RULE_QUOTE = "quote-parse"
RULE_HASH = "naive-hash-cut"

#: 取值型调用（**返回匹配内容**）。`re.sub` 不在内 —— 它是「替换/清洗」，属 RULE_HASH 的面。
EXTRACT_FNS = frozenset({"findall", "finditer", "search", "match", "fullmatch"})

#: **性能预筛**（不是判定）：凡命中形态，其 pattern 字面量必然在源码里留下痕迹 ——
#: RULE_QUOTE 留下「引号紧跟 `(`」；RULE_HASH 留下 `re.sub` / `.split('#')` / `.partition('#')`。
#: 没有痕迹的文件**不可能**产出命中，跳过它的 `ast.parse`（判据面 244 文件 / 5.06MB 源码，
#: 全量 parse 实测 2.4s~15s（随机器负载），预筛后 118 文件 / 1.5s~4s —— 该 job 只有 12 分钟预算，
#: 本守卫不该把自己变成这套件的成本项）。
#: **残余（假绿方向，已登记为下方 ⑤）**：把 pattern 写成 `'"' + '('` 这类**动态拼接**、源码里
#: 看不到引号与 `(` 相邻时会被跳过。实测取证（PR body）：关掉本预筛重扫，命中集**逐条一致**（57=57）。
_QUOTE_TRACES = ('"(', "'(")
_HASH_TRACES = ("re.sub", '.split("#', ".split('#", '.partition("#', ".partition('#")

#: 判据面：**按路径取**（结构性证据），逐个面各取一次，缺面 ⇒ fail-closed。
SURFACE_SPECS = (
    (UNIT_CI_DIR, True, "tests/unit_ci_workflows/**"),
    (GITHUB_DIR, False, ".github/*.py"),
    (GITHUB_SCRIPTS_DIR, False, ".github/scripts/*.py"),
    (SCRIPTS_DIR, False, "scripts/*.py"),
)

#: 见证语料 A：**注释行**里的「看起来像声明」的值（Python `#` / Java-Shell `//` 两种注释形态）。
COMMENT_WITNESS = "\n".join(
    [
        '# 说明："settings" 已从该 skill 解绑（issue #5247）',
        '// 说明："settings" 已从该 skill 解绑（issue #5247）',
        "# 说明：'settings' 已解绑",
        '# name="settings" 这一行已删除',
        '// name = "settings";',
        '# fallback_skill = "settings"',
        '# "settings": 1,',
        "# key: 'settings',",
        '# permissionCode: "settings",',
        '# config.put("settings", null) 已移除',
        '// menus.add(menuItem("settings", "设置"))',
        '// new MenuNode("settings", "设置", List.of("a"))',
        '// permissions.contains("settings")) { menus.add(menuItem("settings", "设置"))',
        '# {"action": "query"}',
        '# REQUIRED_ENV = "1"',
        "// shot('settings')",
        '# variant(names, "a", "b", "c")',
        '// view.put("settings", null)',
    ]
)

#: 见证语料 B：**文档字符串 / 字符串**里的同一批形状（`#5272` 的现场就是「举例被读成声明」）。
STRING_WITNESS = "\n".join(
    [
        '"""示例（不是代码）：',
        '    name="settings"',
        '    fallback_skill = "settings"',
        '    "settings": 1,',
        "    key: 'settings',",
        '    config.put("settings", null)',
        '    new MenuNode("settings", "设置", List.of("a"))',
        '    menus.add(menuItem("settings", "设置"))',
        '    skill_names=["settings"]',
        '    view.put("settings", null)',
        '    {"a", "b", "c"}',
        '"""',
    ]
)


# ══════════════════════════════════════════════════════════════════════════════
# 一、pattern 的形态判定（全部走字符串走查：跳过转义与字符类，不依赖正则套正则）
# ══════════════════════════════════════════════════════════════════════════════


def _quote_delimited_group(pattern: str) -> bool:
    """条件 ①：pattern 里存在**引号紧跟 `(`** —— 取值区间在引号之间的形态签名。"""
    i, n, in_class = 0, len(pattern), False
    while i < n:
        char = pattern[i]
        if char == "\\":  # 转义：跳过下一个字符（`\"` 不算引号定界）
            i += 2
            continue
        if in_class:  # `[...]` 内：`["\']` 这类字符类不算引号定界
            if char == "]":
                in_class = False
            i += 1
            continue
        if char == "[":
            in_class = True
            i += 1
            continue
        if char in "\"'" and i + 1 < n and pattern[i + 1] == "(":
            return True
        i += 1
    return False


def _bites_on_witness(pattern: str, flags: int) -> bool | None:
    """条件 ②：**判别力实验** —— 该正则能否从注释/文档字符串语料里取到一个非空值。

    `True` = 喂得中（分不清注释/字符串与代码 ⇒ 原文口径）；
    `False` = 喂不中（锚点够具体，或实现已是注释/字符串无关的）；
    `None` = 编译不了（无法判定 —— 另行计数，不进命中面）。
    """
    try:
        rx = re.compile(pattern, flags)
    except re.error:
        return None
    for witness in (COMMENT_WITNESS, STRING_WITNESS):
        for got in rx.findall(witness):
            values = got if isinstance(got, tuple) else (got,)
            if any(str(v).strip() for v in values):
                return True
    return False


def _bare_hash(pattern: str) -> bool:
    """pattern 里是否存在**未被转义、且不在字符类内**的 `#`（注释起点）。"""
    i, n, in_class = 0, len(pattern), False
    while i < n:
        char = pattern[i]
        if char == "\\":
            i += 2
            continue
        if in_class:
            if char == "]":
                in_class = False
            i += 1
            continue
        if char == "[":
            in_class = True
            i += 1
            continue
        if char == "#":
            return True
        i += 1
    return False


def _cuts_to_eol(pattern: str) -> bool:
    """该 pattern 是否把匹配区间延伸到**行尾**（行内注释截断的形态：`#...` / `#[^\\n]*` / `#.*`）。"""
    stripped = pattern.strip()
    if stripped == "#":
        return True
    return r"[^\n]*" in pattern or ".*" in pattern


# ══════════════════════════════════════════════════════════════════════════════
# 二、扫描（AST：取值取自**实参**，不是文件全文）
# ══════════════════════════════════════════════════════════════════════════════


def _surface() -> tuple[Path, ...]:
    """判据面（按路径）。四个面各自取，**缺面 ⇒ 红**（由 `test_surface_is_complete_and_anchored` 钉）。"""
    found: set[Path] = set()
    for base, recursive, _label in SURFACE_SPECS:
        if not base.is_dir():
            continue
        found.update(base.rglob("*.py") if recursive else base.glob("*.py"))
    return tuple(sorted(p for p in found if "__pycache__" not in p.parts))


def _may_contain_candidate(source: str) -> bool:
    """**性能预筛**：该文件文本是否可能承载任一规则的命中形态（见 `_QUOTE_TRACES` / `_HASH_TRACES`）。

    只用来省掉 `ast.parse`，**不参与判定** —— 判定一律走 AST 实参 + 正则引擎行为。
    """
    if any(trace in source for trace in _HASH_TRACES):
        return True
    return "re." in source and any(trace in source for trace in _QUOTE_TRACES)


def _module_string_consts(tree: ast.Module) -> dict[str, str]:
    """模块级字符串常量（`NAME = "..."` / `NAME: str = "..."`）—— 供 pattern 溯源到常量。"""
    consts: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                consts[target.id] = value.value
    return consts


def _iter_calls(tree: ast.Module) -> list[tuple[str, ast.Call]]:
    """**单趟**遍历：产出 `(归属符号, Call 节点)`。

    归属符号 = 函数/类限定名（模块级为 `<module>`）—— 位置性证据，不用行号定位（行号会漂）。
    刻意不建「id → qualname」全树映射、也不重复 `ast.walk`：判据面 240+ 文件 / 60 万 AST 节点，
    多趟遍历会把本守卫自己的成本抬到十几秒（实测过），而这套件有 12 分钟 job 预算。
    """
    found: list[tuple[str, ast.Call]] = []
    stack: list[tuple[ast.AST, str]] = [(tree, "")]
    while stack:
        node, prefix = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                stack.append((child, f"{prefix}{child.name}."))
                continue
            if isinstance(child, ast.Call):
                found.append((prefix.rstrip(".") or "<module>", child))
            stack.append((child, prefix))
    return found


def _pattern_of(node: ast.AST, consts: dict[str, str]) -> tuple[str | None, bool]:
    """pattern 溯源：字面量 / 模块级常量 / `re.compile(literal)`。返回 (pattern, 是否常量口径)。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, True
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id], True
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "compile"
        and node.args
    ):
        return _pattern_of(node.args[0], consts)
    return None, False


def _literal_join(node: ast.AST) -> str | None:
    """非常量 pattern 的**退化见证**：把该表达式里所有字符串字面量拼起来当候选 pattern。

    （挡住「把 pattern 挪进变量/拼接里」这条规避路径 —— 实测当前命中 0 条，留着是防回归。）
    """
    parts = [
        c.value
        for c in ast.walk(node)
        if isinstance(c, ast.Constant) and isinstance(c.value, str)
    ]
    return "".join(parts) if len(parts) > 1 else None


def _call_flags(call: ast.Call) -> int:
    """调用点**实参**里的 flags（第 3 个位置实参或 `flags=`）—— 见证实验必须带同一组 flag。"""
    flags = 0

    def flag_value(node: ast.AST) -> int:
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "re":
            value = getattr(re, node.attr, 0)
            return value if isinstance(value, int) else 0
        return 0

    for arg in call.args[2:]:
        flags |= flag_value(arg)
    for keyword in call.keywords:
        if keyword.arg == "flags":
            flags |= flag_value(keyword.value)
    return flags


@lru_cache(maxsize=1)
def _scan() -> dict[str, object]:
    """扫一遍判据面。返回 hits / undecided / surface_sizes（供各测与打印共用，只算一次）。"""
    hits: dict[tuple[str, str], list[str]] = {}
    undecided: list[str] = []
    face_sizes: dict[str, int] = {}

    for base, recursive, label in SURFACE_SPECS:
        if base.is_dir():
            face_sizes[label] = len(
                [p for p in (base.rglob("*.py") if recursive else base.glob("*.py")) if "__pycache__" not in p.parts]
            )

    for path in _surface():
        rel = str(path.relative_to(REPO_ROOT))
        source = path.read_text(encoding="utf-8")
        if not _may_contain_candidate(source):
            continue  # 性能预筛（**不是判定**），见 `_may_contain_candidate` 的残余登记
        tree = ast.parse(source, filename=str(path))
        consts = _module_string_consts(tree)
        for qualname, node in _iter_calls(tree):
            if not node.args:
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            owner = func.value.id if isinstance(func.value, ast.Name) else None
            where = f"{qualname}:{node.lineno}"
            first = node.args[0]

            # ── RULE_QUOTE：取值型正则 + 引号定界捕获组 + 注释/字符串喂得中 ──
            if owner == "re" and func.attr in EXTRACT_FNS:
                pattern, is_const = _pattern_of(first, consts)
                if not is_const:
                    joined = _literal_join(first)
                    if joined is None:
                        undecided.append(f"{rel}::{where} (非常量 pattern，无字面量拼接可判)")
                        continue
                    pattern = joined
                if pattern is None:
                    continue
                if not _quote_delimited_group(pattern):
                    continue
                verdict = _bites_on_witness(pattern, _call_flags(node))
                if verdict is None:
                    undecided.append(f"{rel}::{where} (pattern 编译失败)")
                    continue
                if verdict:
                    hits.setdefault((rel, RULE_QUOTE), []).append(f"{where}  pattern={pattern!r}")

            # ── RULE_HASH：本地朴素 `#` 截断（`re.sub` 行尾注释 / `split('#')`）──
            elif owner == "re" and func.attr == "sub":
                pattern, is_const = _pattern_of(first, consts)
                if is_const and pattern is not None and _bare_hash(pattern) and _cuts_to_eol(pattern):
                    hits.setdefault((rel, RULE_HASH), []).append(f"{where}  re.sub(pattern={pattern!r})")
            elif func.attr in ("split", "partition"):
                if isinstance(first, ast.Constant) and first.value == "#":
                    hits.setdefault((rel, RULE_HASH), []).append(f"{where}  .{func.attr}('#')")

    return {
        "hits": {key: tuple(sorted(value)) for key, value in hits.items()},
        "undecided": tuple(sorted(undecided)),
        "face_sizes": face_sizes,
    }


def _hits(rule: str) -> dict[str, tuple[str, ...]]:
    """某条规则的现取命中：`{相对路径: (逐条描述, ...)}`。"""
    raw = _scan()["hits"]
    assert isinstance(raw, dict)
    return {path: lines for (path, hit_rule), lines in raw.items() if hit_rule == rule}


def _ledger() -> list[dict[str, object]]:
    data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    entries = data["entries"]
    assert isinstance(entries, list), "台账 `entries` 必须是数组"
    return entries


def _ledger_of(rule: str) -> dict[str, dict[str, object]]:
    return {str(e["path"]): e for e in _ledger() if e.get("rule") == rule}


def _anchor_line(rule: str) -> str:
    """燃尽锚点（**现取**，不写死）：台账条数 / 命中条数 / 未判定条数。"""
    hits = _hits(rule)
    ledger = _ledger_of(rule)
    total = sum(len(v) for v in hits.values())
    return (
        f"[燃尽锚点 {rule}] 台账文件数={len(ledger)} / 台账命中数={sum(int(e['hits']) for e in ledger.values())}"
        f" / 现取命中文件数={len(hits)} / 现取命中条数={total}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据
# ══════════════════════════════════════════════════════════════════════════════


def test_surface_is_complete_and_anchored() -> None:
    """判据面必须**四面齐全且可解释**（路径取不到 ⇒ fail-closed，不许静默空跑成绿）。"""
    scan = _scan()
    face_sizes = scan["face_sizes"]
    assert isinstance(face_sizes, dict)
    print(f"判据面（现取）：{face_sizes}")
    missing = [label for _base, _rec, label in SURFACE_SPECS if not face_sizes.get(label)]
    assert not missing, f"判据面取空（glob/路径失效）⇒ 本守卫会静默空跑成绿：缺 {missing}"
    surface = _surface()
    assert SELF_REL in {str(p.relative_to(REPO_ROOT)) for p in surface}, (
        f"本守卫自身不在判据面内（{SELF_REL}）—— 面取错了 ⇒ 一切判定都不可信"
    )


def test_quote_parsing_is_ledgered() -> None:
    """RULE_QUOTE：**未登记**的「按引号扫原文取值」⇒ 红（形态见模块 docstring）。"""
    hits = _hits(RULE_QUOTE)
    ledger = _ledger_of(RULE_QUOTE)
    print(_anchor_line(RULE_QUOTE))
    for path in sorted(hits):
        for line in hits[path]:
            print(f"  命中 {path}  {line}")
    unledgered = sorted(path for path in hits if path not in ledger)
    assert not unledgered, (
        "判据面出现**未登记**的原文口径解析（按引号扫原文取值，注释/docstring 即可喂中）：\n"
        + "\n".join(f"  {p}\n" + "\n".join(f"      {line}" for line in hits[p]) for p in unledgered)
        + "\n修法（二选一，**不要**往台账里加条目 —— 台账只许缩短）：\n"
        "  ① Python 源码 ⇒ 改用 `ast` / `tokenize` 取真语法单元（见 test_agent_permission_parity.py 的 `parse_agent_skills`）；\n"
        "  ② 其它语言 / SQL ⇒ 先剥注释与字符串再取值（顺序不许反；全仓唯一剥注释实现在 `.github/danger_scan.py::strip_comment`）。\n"
        f"复算：python3 -m pytest tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py -q -s"
    )


def test_naive_hash_cut_is_ledgered() -> None:
    """RULE_HASH：**未登记**的本地朴素 `#` 截断 ⇒ 红（`#5323` 第 7/8/9 条同族）。"""
    hits = _hits(RULE_HASH)
    ledger = _ledger_of(RULE_HASH)
    print(_anchor_line(RULE_HASH))
    for path in sorted(hits):
        for line in hits[path]:
            print(f"  命中 {path}  {line}")
    unledgered = sorted(path for path in hits if path not in ledger)
    assert not unledgered, (
        "判据面出现**未登记**的本地朴素 `#` 截断（未先清空字符串就按 `#` 截断 ⇒ 字符串里的 `#` 会吃掉行尾，属**假绿**）：\n"
        + "\n".join(f"  {p}\n" + "\n".join(f"      {line}" for line in hits[p]) for p in unledgered)
        + "\n修法：改用共享剥注释实现，或先清空字符串/文档字符串**再**剥 `#`（顺序不许反）。台账只许缩短。\n"
        f"复算：python3 -m pytest tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py -q -s"
    )


def test_every_ledger_entry_carries_reason_and_issue() -> None:
    """台账每条必须有 `reason` + 单号 `issue`；**缺任一项 ⇒ 红**（#5325 判据 2）。"""
    problems = []
    for entry in _ledger():
        path = str(entry.get("path") or "")
        reason = str(entry.get("reason") or "").strip()
        issue = str(entry.get("issue") or "").strip()
        if len(reason) < 8:
            problems.append(f"{path} [{entry.get('rule')}]：`reason` 缺失或过短（{reason!r}）")
        if not re.fullmatch(r"#\d{3,}", issue):
            problems.append(f"{path} [{entry.get('rule')}]：`issue` 缺失或不是单号（{issue!r}）")
        if str(entry.get("rule")) not in (RULE_QUOTE, RULE_HASH):
            problems.append(f"{path}：`rule` 非法（{entry.get('rule')!r}）")
        if not isinstance(entry.get("hits"), int) or int(entry["hits"]) < 1:
            problems.append(f"{path}：`hits` 必须是 ≥1 的整数（现取条数）")
    print(f"台账现取条数={len(_ledger())}")
    assert not problems, "台账条目不合规（豁免必须带理由 + 单号）：\n" + "\n".join(f"  {p}" for p in problems)


def test_every_ledger_entry_is_live_and_exact() -> None:
    """台账条目必须**对着现取命中**且条数**逐字相符** —— 只许缩短（陈旧/涨跌都被拦）。"""
    problems = []
    for rule in (RULE_QUOTE, RULE_HASH):
        hits = _hits(rule)
        for path, entry in sorted(_ledger_of(rule).items()):
            live = hits.get(path)
            if live is None:
                problems.append(f"{path} [{rule}]：台账条目**已陈旧** —— 该文件现取命中 0 ⇒ 必须删除该条目（只许缩短）")
                continue
            if len(live) != int(entry["hits"]):
                direction = "涨" if len(live) > int(entry["hits"]) else "跌"
                problems.append(
                    f"{path} [{rule}]：命中数{direction}了 —— 台账记 {entry['hits']}，现取 {len(live)}；"
                    f"现取清单：{list(live)}"
                )
    print(f"{_anchor_line(RULE_QUOTE)} | {_anchor_line(RULE_HASH)}")
    assert not problems, (
        "台账与现取命中不一致（**只许缩短**：修好一处就销账；新增债务不许靠加条目吸收）：\n"
        + "\n".join(f"  {p}" for p in problems)
    )


def test_guard_itself_is_clean() -> None:
    """本守卫自己不得出现在命中面里（不许给自己开豁免，也不许被自己的见证语料喂红）。"""
    for rule in (RULE_QUOTE, RULE_HASH):
        hits = _hits(rule)
        assert SELF_REL not in hits, (
            f"元守卫自身命中 {rule}：{hits.get(SELF_REL)} —— 守卫把**自己的文案**当判据了（本仓踩过多次）"
        )
        assert SELF_REL not in _ledger_of(rule), "元守卫不得给自己开台账条目"


def test_undecided_patterns_are_reported() -> None:
    """无法判定的 pattern 必须**打印**（照实登记，不许静默当成绿）。"""
    undecided = _scan()["undecided"]
    assert isinstance(undecided, tuple)
    print(f"无法判定（非常量 pattern / 编译失败）现取条数={len(undecided)}")
    for item in undecided:
        print(f"  未判定 {item}")