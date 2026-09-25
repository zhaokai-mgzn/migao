# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 `_source_parsing.py` / `test_stale_report_reaper.py` 的同款声明。本 PR 不新建用例族。）
"""闸门规则表 `_VALIDATION_RULES` 的三条 L0 不变式（#4025 台账 F5 / F6 / F8）—— **源码级**。

## 为什么要有这一份（和 app 侧那一份的关系）

真相源是 `backend/ai-agent-service/app/tools/validate_input.py` 的 `_VALIDATION_RULES` ——
一张**普通 dict 字面量**，它是写操作确认链的唯一确定性闸门（`base_skill` 靠它
`validated=True` 才落「已校验待执行」并放行写工具）。三类缺陷都**不会自己变红**：

| ID | 形态 | 后果（为什么静默） |
|---|---|---|
| **F5** | dict 字面量**重复键**（P2 开发中亲自踩到 `employee_manage` 两个键） | Python 编译期折叠成「后者胜」、**零报错** ⇒ 被吃掉的规则块运行时不存在，闸门对那批 action 退化成「无规则」。**运行时 dict 看不出来**（键只有一个），只有 AST 能看见 |
| **F6** | 新增写工具/写 action **忘了补规则** | 闸门落「该操作无校验规则」分支（`validate_input.execute`）⇒ A4 前是假绿放行、A4 后是 fail-closed 拦死合法调用。两种都不变红 |
| **F8** | 规则 `required` 里**写错字段名**（工具根本不接收） | 闸门照样返回 `validated=True`，但模型永远给不出该字段 ⇒ 合法调用被拦，且错误信息把人指向不存在的参数（#3566 的 `settings_manage.data` 就是这么坏掉的） |

**这一份为什么是源码级**：`tests/unit_ci_workflows/**` 所在的 CI 腿
（`pr-check.yml` 的 `ci workflow helper unit tests` job）**只装 `pytest pyyaml`**（无 pydantic
⇒ `import app.*` 必炸），且该 job **不带路径门控**（每个 PR 都跑）⇒ 把这三条不变式放在这里，
它们才会在每个 PR 上被判，而不是只在 ai-agent 腿装得上依赖时才判。

**边界（照实登记，别把「这边绿」读成「全治住了」）**：本文件**只做源码级的部分** ——

* F6 只判到**工具级**（写工具的规则块存在与否）：action 级覆盖需要 `schema.action` 枚举
  （要 import 注册表 ⇒ 要 pydantic），那一半由
  `backend/ai-agent-service/tests/test_validation_rules_invariants.py`
  （`::test_every_write_action_is_deterministically_gated` 等）承担 —— 两边是**分工**，
  不是同一判据抄两遍；本文件不复制它的口径，也不替它下结论。
* 运行期语义（无规则分支真的 fail-closed、`read_all` 这类无参写调用不被拦）同样只在 app 侧那份里判。

## 三条判据（读数一律**现取**，判据里不写死条数）

1. **F5** `test_no_duplicate_keys_in_validation_rules`：`_VALIDATION_RULES` 字面量**任何层级**
   （工具名层 / action 层 / 字段层）都不得有重复键；
2. **F6** `test_every_write_tool_has_validation_rules`：源码标记 `read_only = False` 的**每个**写工具
   都必须有规则块。白名单 `RULE_LESS_WRITE_TOOLS`（键=工具名、值=理由）**只许缩短**
   （`test_rule_less_write_tool_ledger_is_not_stale` 双向对账）；
3. **F8** `test_required_fields_exist_in_tool_source`：每条规则 `required` 里的字段必须在
   **该工具源码（去注释）**里真实出现。白名单 `UNKNOWN_REQUIRED_KEYS`
   （键 `<工具>.<action>.<字段>`）**只许缩短**，且**只许豁免单一台账已记的死键**
   （`test_unknown_required_key_ledger_is_not_stale_and_within_the_single_ledger`）。

## 红证（每条都**实跑过**注入并逐字节还原；三个检测器另有常驻的注入式自证）

| 注入（改真源码这一处即红） | 变红的用例 |
|---|---|
| 在 `_VALIDATION_RULES` 顶层再写一次已有的工具键 | `test_no_duplicate_keys_in_validation_rules` |
| 把某个写工具的规则块键改名（如 `"order_create"` → 别的名字）⇒ 该工具变成「无规则写工具」 | `test_every_write_tool_has_validation_rules` |
| 把某条规则 `required` 里的字段换成一个源码中不存在的名字 | `test_required_fields_exist_in_tool_source` |

`TestDetectorsAreNotVacuous` 把这三条**在现取真值上**再证一遍（不落盘、每个 PR 都跑；
红证要证明的是「判据对真值敏感」，靠人工注入证不了第二次），并各带一条负例（防恒红）。

## 适用域声明（对谁生效 / 对谁**不**生效）

| 维度 | 覆盖 | 明确**不**覆盖 |
|---|---|---|
| 工具 | `app/tools/*.py` 里类体显式写 `read_only = False` 的全部工具 | 只读工具（`BaseTool.read_only` 默认 `True`）：无写副作用 ⇒ 不做要求 |
| 规则面 | 整个 `_VALIDATION_RULES`（**不缩域**：20 个工具键一个不漏） | 规则值与工具实现的**语义**是否等价（如 `min`/`enum` 取值）—— 那要靠契约/业务判据 |
| F8 字段 | 字段名在源码里作为**独立标识符或字符串**出现 | 「该字段是否真的必填」不判（`required` 与实现严格度的口径属 app 侧那份） |
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "tools"
VALIDATE_INPUT_PY = TOOLS_DIR / "validate_input.py"
RULES_SYMBOL = "_VALIDATION_RULES"

# 单一台账：「规则块对应的 action 已被工具删除」的**唯一**登记处（它自己钉「只许缩短 + 陈旧即红」）。
# 本文件只**读**它、不复制它 —— F8 的豁免必须是它的派生面，不是第二本账。
RETIRED_LEDGER_PY = (REPO_ROOT / "backend" / "ai-agent-service" / "tests"
                     / "test_tools_validate_input.py")
RETIRED_LEDGER_SYMBOL = "RETIRED_RULE_KEYS_B_END_READONLY"

# append（**不是** insert）：只作兜底解析路径，避免遮蔽同名模块（与 conftest 同款理由）。
sys.path.append(str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import code_without_comments  # noqa: E402

# ── 白名单：只许缩短（由下面两条 `*_ledger_is_not_stale*` 判据双向对账）────────────────────

# F6：已登记可写却**没有规则块**的工具。值 = 理由（会被打印出来，让「为什么它没有规则」是可读事实）。
RULE_LESS_WRITE_TOOLS: dict[str, str] = {
    "human_handoff": (
        "工具本身正在退场（用户裁定 2026-09-19「不应该存在 human_handoff 这种东西」，"
        "`tests/unit_ci_workflows/test_human_handoff_retired.py` 锁它不可达）⇒ 不为一个"
        "正在被删除的工具补规则；工具源码删除后本条必须同批销账"
    ),
}

# F8：`required` 里在工具源码中找不到的字段。值 = 理由。
# **已清空（空 dict = 该白名单的合法终态，不是「判据关掉了」）**：曾经的 3 条**全部**是
# 「规则块对应的 action 已被工具删除」的死键，其规则块已随 #4025 的 F8 销账包从 app 侧删除
# （`finance_api.create_transaction` / `settings_manage.change_password`）⇒ 豁免项归零。
# 本白名单**只许缩短**：再新增一条 = 给一个活规则开豁免，判据会红；
# 由 `test_unknown_required_key_ledger_is_not_stale_and_within_the_single_ledger` 钉住。
UNKNOWN_REQUIRED_KEYS: dict[str, str] = {}


# ══════════════════════════════════════════════════════════════════════════════
# 一、读源码（**一律 fail-closed**：解析不出来 ≠ 没有违规）
# ══════════════════════════════════════════════════════════════════════════════


def _module_level_value(tree: ast.Module, symbol: str, where: str) -> ast.expr:
    """模块级 `symbol = <expr>`（含 `symbol: T = <expr>`）的右值；找不到 ⇒ 抛错。"""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == symbol for t in targets):
            continue
        if node.value is None:
            raise AssertionError(f"{where} 的模块级声明 `{symbol}` 没有右值（拿不到真相源）")
        return node.value
    raise AssertionError(
        f"{where} 里找不到模块级声明 `{symbol}` —— 判据的真相源消失了。"
        f"请同步本守卫（**不得**静默跳过：扫不到 ≠ 没有违规）"
    )


def _as_dict_literal(node: ast.expr, where: str) -> ast.Dict:
    """该节点的现取形状必须是 dict 字面量；否则抛错（判据的解析前提变了）。"""
    if not isinstance(node, ast.Dict):
        raise AssertionError(
            f"{where} 不再是字典字面量（现取 {type(node).__name__}）⇒ 本判据的解析前提变了，"
            f"请把判据挂到新的真相源上（**不得**静默跳过）"
        )
    return node


def validation_rules_literal(path: Path = VALIDATE_INPUT_PY) -> ast.Dict:
    """`_VALIDATION_RULES` 的**字面量**节点（AST，不是运行时 dict）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    literal = _as_dict_literal(
        _module_level_value(tree, RULES_SYMBOL, str(path)), f"{path} 的 `{RULES_SYMBOL}`"
    )
    if not literal.keys:
        raise AssertionError(
            f"`{RULES_SYMBOL}` 解析出 0 个键 —— 判据会在空集上恒真（fail-closed）"
        )
    return literal


def _key_label(key_node: ast.expr) -> str:
    """键的可读标签：字符串常量给值，其余给源码文本。"""
    if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
        return key_node.value
    return ast.unparse(key_node)


def duplicate_literal_keys(node: ast.AST) -> list[tuple[int, str]]:
    """递归找出字典**字面量**里的重复键 ⇒ `[(行号, 键), …]`（按行号排序）。

    行号 = **重复出现的那一次**（第二次及以后）所在行 —— 直接指向该删/该合并的那一行，
    而不是字典的起始行（后者在多行规则块里指不到地方）。

    键的「相同」按 **AST 结构同一性**（`ast.dump`）判 ⇒ 覆盖字符串常量键与枚举成员键
    （`IntentType.X` 那类同样会被 Python 静默折叠）。`**spread`（AST 里 key 为 `None`）
    不是键，不参与判据（也不误报）。
    """
    dups: list[tuple[int, str]] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Dict):
            continue
        seen: set[str] = set()
        for key_node in sub.keys:
            if key_node is None:  # `**spread`：不是键
                continue
            identity = ast.dump(key_node)
            if identity in seen:
                dups.append((key_node.lineno, _key_label(key_node)))
            seen.add(identity)
    return sorted(dups)


def _required_fields(body: ast.Dict, where: str) -> tuple[str, ...]:
    """规则体的 `required` 字段元组；没有 `required` 键 ⇒ 空元组（= 该 action 无必填）。"""
    for key_node, value_node in zip(body.keys, body.values):
        if not (isinstance(key_node, ast.Constant) and key_node.value == "required"):
            continue
        if not isinstance(value_node, ast.List):
            raise AssertionError(
                f"`{where}` 的 `required` 不再是列表字面量（现取 {type(value_node).__name__}）"
                f"⇒ F8 读不到必填集（fail-closed）"
            )
        fields: list[str] = []
        for elt in value_node.elts:
            if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
                raise AssertionError(
                    f"`{where}` 的 `required` 含非字符串字面量元素（现取 {ast.unparse(elt)}）"
                    f"⇒ F8 判不了它是否存在（fail-closed）"
                )
            fields.append(elt.value)
        return tuple(fields)
    return ()


def rule_table(literal: ast.Dict, where: str = RULES_SYMBOL) -> dict[str, dict[str, tuple[str, ...]]]:
    """AST 字面量 → 纯数据：工具 → action → `required` 字段元组。

    fail-closed：顶层/工具层/action 层出现 `**spread`（键为 `None`）、或某层不是 dict 字面量
    ⇒ 抛错。「展开」意味着工具集/action 集无法从字面量确定 —— 那时判据只能空转，必须红。
    """
    table: dict[str, dict[str, tuple[str, ...]]] = {}
    for tool_key, tool_value in zip(literal.keys, literal.values):
        if tool_key is None:
            raise AssertionError(f"`{where}` 顶层出现 `**spread` ⇒ 工具集无法从字面量确定（fail-closed）")
        tool = _key_label(tool_key)
        actions = _as_dict_literal(tool_value, f"`{where}[\"{tool}\"]`")
        per_action: dict[str, tuple[str, ...]] = {}
        for action_key, action_value in zip(actions.keys, actions.values):
            if action_key is None:
                raise AssertionError(
                    f"`{where}[\"{tool}\"]` 里出现 `**spread` ⇒ action 集无法确定（fail-closed）"
                )
            action = _key_label(action_key)
            body = _as_dict_literal(action_value, f"`{where}[\"{tool}\"][\"{action}\"]`")
            per_action[action] = _required_fields(body, f"{tool}.{action}")
        table[tool] = per_action
    return table


def write_tool_modules(tools_dir: Path = TOOLS_DIR) -> dict[str, str]:
    """源码标记 `read_only = False` 的工具 ⇒ `{模块名: 类名}`。

    读的是**类体里显式写 `read_only = False`**：`BaseTool.read_only` 的默认值是 `True`（只读），
    故「没写」= 只读 —— 方向是 fail-safe（顶多漏掉一个没显式声明的写工具，
    而 `read_only = False` 正是本判据要抓的那个声明）。
    """
    found: dict[str, str] = {}
    for path in sorted(tools_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    targets = stmt.targets
                elif isinstance(stmt, ast.AnnAssign):
                    targets = [stmt.target]
                else:
                    continue
                if not any(isinstance(t, ast.Name) and t.id == "read_only" for t in targets):
                    continue
                if isinstance(stmt.value, ast.Constant) and stmt.value.value is False:
                    found[path.stem] = node.name
    return found


def _tool_code_by_module(modules) -> dict[str, str]:
    """每个模块的**去注释代码面**（`code_without_comments` = 仓内剥注释的唯一实现）。

    为什么先剥注释：字段名只出现在注释里 ⇒ 判据会把「拼错的字段」当成存在（漏检方向，
    `#5323` 第 7 条同族）。缺源码文件 ⇒ 抛错（规则守着一个不存在的工具 = 闸门永远不命中）。
    """
    code: dict[str, str] = {}
    for module in sorted(set(modules)):
        path = TOOLS_DIR / f"{module}.py"
        if not path.is_file():
            raise AssertionError(
                f"规则表里的 `{module}` 在 {TOOLS_DIR} 下**没有源码文件** ⇒ 这条规则永远不会命中"
                f"（闸门守着一个不存在的工具）。修法：删规则块或补回工具源码。"
            )
        code[module] = code_without_comments(path.read_text(encoding="utf-8"), str(path))
    return code


def _mentions_field(code: str, field: str) -> bool:
    """字段名在代码面里作为**独立标识符或字符串**出现（前后不得再接标识符字符）。"""
    return re.search(rf"(?<![A-Za-z0-9_.]){re.escape(field)}(?![A-Za-z0-9_])", code) is not None


def unknown_required_fields(rules: dict, code_by_module: dict) -> list[str]:
    """**F8 内核**（纯函数）：`required` 里在**该工具源码（去注释）**中找不到的字段。

    返回 `["<工具>.<action>.<字段>", …]`。豁免不在这里做（内核只管报，白名单在判据层对账）。
    """
    unknown: list[str] = []
    for tool, actions in sorted(rules.items()):
        code = code_by_module.get(tool)
        if code is None:
            continue  # 缺源码文件由 `_tool_code_by_module` 判红（单一出口，不在这里重复报）
        for action, required in sorted(actions.items()):
            for field in required:
                if not _mentions_field(code, field):
                    unknown.append(f"{tool}.{action}.{field}")
    return unknown


def rule_less_write_tools(rules: dict, write_modules) -> list[str]:
    """**F6 内核**（纯函数）：已登记可写却**没有规则块**的写工具（按名字排序）。"""
    return sorted(module for module in set(write_modules) if module not in rules)


def retired_rule_actions(path: Path = RETIRED_LEDGER_PY) -> set[tuple[str, str]]:
    """单一台账 `RETIRED_RULE_KEYS_B_END_READONLY` 的 `(tool, action)` 集合（源码级 AST 读）。

    读不到 ⇒ 抛错（fail-closed）：那时要么改挂新台账、要么把 F8 白名单同批清空 ——
    **不得**让豁免失去出处（否则就是第二本没人对账的账）。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    value = _module_level_value(tree, RETIRED_LEDGER_SYMBOL, f"{path}")
    if isinstance(value, ast.Call):
        if len(value.args) != 1:
            raise AssertionError(
                f"`{RETIRED_LEDGER_SYMBOL}` 是多参调用 ⇒ 本判据读不到条目（fail-closed）"
            )
        value = value.args[0]
    if not isinstance(value, (ast.Set, ast.List, ast.Tuple)):
        raise AssertionError(
            f"`{RETIRED_LEDGER_SYMBOL}` 的现取形状是 {type(value).__name__} ⇒ 本判据读不到条目"
            f"（fail-closed；请同步本守卫）"
        )
    pairs: set[tuple[str, str]] = set()
    for elt in value.elts:
        if not (isinstance(elt, ast.Tuple) and len(elt.elts) == 2):
            raise AssertionError(
                f"`{RETIRED_LEDGER_SYMBOL}` 的条目不是二元组（现取 {ast.unparse(elt)[:60]}）"
                f"⇒ 读不到 (tool, action)"
            )
        tool_node, action_node = elt.elts
        if not (isinstance(tool_node, ast.Constant) and isinstance(action_node, ast.Constant)):
            raise AssertionError(
                f"`{RETIRED_LEDGER_SYMBOL}` 的条目含非常量（现取 {ast.unparse(elt)[:60]}）"
            )
        pairs.add((str(tool_node.value), str(action_node.value)))
    return pairs


def _live_rules() -> tuple[dict[str, dict[str, tuple[str, ...]]], dict[str, str]]:
    """现取「规则表 + 写工具集」（F5 / F6 侧需要的全部读法）。"""
    rules = rule_table(validation_rules_literal())
    return rules, write_tool_modules()


def _live_unknown(rules: dict) -> list[str]:
    """现取 F8 侧读数：`required` 里在**对应工具源码**中找不到的字段。

    ⚠️ 与 `_live_rules()` **分开**：本读法会 fail-closed 判「规则指向一个不存在的工具」，
    合在一起会让 F6 的判据因为 F8 侧的前提问题而红 —— 判红必须**可归因**（红在谁身上要说清）。
    """
    return unknown_required_fields(rules, _tool_code_by_module(rules.keys()))


# ══════════════════════════════════════════════════════════════════════════════
# 二、三条判据（F5 / F6 / F8）
# ══════════════════════════════════════════════════════════════════════════════


def test_no_duplicate_keys_in_validation_rules() -> None:
    """**F5**：`_VALIDATION_RULES` 字面量**任何层级**都不得有重复键。

    重复键的后果**不可见**：Python 在编译期折叠成「后者胜」、零报错 ⇒ 被吃掉的那块规则
    （含 `required`/`enum`/`label`）在运行时**完全不存在**，闸门对那批 action 退化成「无规则」。
    这就是它必须由 AST 而不是运行时 dict 来判的原因。

    反例输入（红证）：在顶层或任一工具块内再写一次已有的键 ⇒ 必红。
    """
    dups = duplicate_literal_keys(validation_rules_literal())
    assert dups == [], (
        "`_VALIDATION_RULES` 出现**重复键**（Python 会静默让后者吃掉前者，被吃掉的规则块"
        "在运行时不存在）：\n  "
        + "\n  ".join(f"第 {line} 行：`{key}`" for line, key in dups)
        + "\n→ 修法：合并两块（保留语义并集），**不得**靠调整顺序「让后者胜」。"
    )


def test_every_write_tool_has_validation_rules() -> None:
    """**F6**：源码标记 `read_only = False` 的**每个**写工具都必须有规则块。

    「没有规则块」不等于「无需校验」：`validate_input.execute` 对没有规则的 action 走
    「该操作无校验规则」分支 ⇒ A4 之前是 `success=True, skipped=True` 的**假绿**
    （模型据此直接执行写工具），A4 之后是 fail-closed **拦死合法调用**。两种都不会自己变红。

    反例输入（红证）：把任一写工具的规则块键改名（工具名不再出现在表里）⇒ 必红。
    """
    rules, writes = _live_rules()
    violations = rule_less_write_tools(rules, writes)
    unregistered = [tool for tool in violations if tool not in RULE_LESS_WRITE_TOOLS]
    print(
        f"\n[F6] 现取读数：写工具 {len(writes)} 个 / 规则表顶层 {len(rules)} 个工具 / "
        f"无规则写工具 {violations or '（无）'}；已登记（不判红）{sorted(RULE_LESS_WRITE_TOOLS) or '（无）'}"
    )
    assert unregistered == [], (
        "以下**已登记可写**的工具在 `_VALIDATION_RULES` 里没有任何规则块"
        "（闸门对它的每个 action 都会落「该操作无校验规则」分支）：\n  "
        + "\n  ".join(unregistered)
        + "\n→ 修法：补规则块（`required` 按工具实现的真实必填声明；零业务参数写 `{\"required\": []}`）。"
    )


def test_required_fields_exist_in_tool_source() -> None:
    """**F8**：每条规则 `required` 里的字段必须在**该工具源码（去注释）**里真实出现。

    字段名写错时闸门**照样**返回 `validated=True`，但模型永远给不出那个参数 ⇒ 合法调用
    被拦，且报错指向一个工具根本不接收的字段（排查方向被带偏）。

    反例输入（红证）：把某条规则 `required` 里的字段换成一个源码中不存在的名字 ⇒ 必红。
    """
    rules, _ = _live_rules()
    unknown = _live_unknown(rules)
    unregistered = [key for key in unknown if key not in UNKNOWN_REQUIRED_KEYS]
    print(
        f"\n[F8] 现取读数：规则块 {sum(len(a) for a in rules.values())} 条 / "
        f"未知必填字段 {unknown or '（无）'}；已登记（不判红）{sorted(UNKNOWN_REQUIRED_KEYS) or '（无）'}"
    )
    assert unregistered == [], (
        "以下规则的 `required` 字段在**对应工具源码**里找不到"
        "（闸门会要求一个模型给不出的参数 ⇒ 合法调用被拦）：\n  "
        + "\n  ".join(unregistered)
        + "\n→ 修法：改成工具真正接收的字段名（按工具源码），或删掉该必填项。"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 三、两张白名单的「只许缩短」对账（陈旧即红 / 不许无据新增）
# ══════════════════════════════════════════════════════════════════════════════


def test_rule_less_write_tool_ledger_is_not_stale() -> None:
    """**F6 白名单只许缩短**：登记的「无规则写工具」必须**仍然真的无规则、且仍然是写工具**。

    没有这条，白名单就退化成永久后门（工具补了规则或工具已删除，登记还挂着 ⇒ 下一个
    真缺口只要"长得像这一条"就免检）。理由一并打印出来 —— 让「为什么它没有规则」是**可读的事实**。
    """
    rules, writes = _live_rules()
    violations = set(rule_less_write_tools(rules, writes))
    problems: list[str] = []
    for tool in sorted(RULE_LESS_WRITE_TOOLS):
        if tool not in violations:
            problems.append(
                f"{tool}：已不再是「无规则写工具」（规则表里已有它的规则块，或它已不再标记 "
                f"`read_only = False`）⇒ 陈旧登记必须销账（台账只许缩短）"
            )
        print(f"[F6 登记·不判红] {tool}：{RULE_LESS_WRITE_TOOLS[tool]}")
    assert problems == [], (
        "F6 白名单里的条目**已陈旧**：\n  " + "\n  ".join(problems)
    )


def test_unknown_required_key_ledger_is_not_stale_and_within_the_single_ledger() -> None:
    """**F8 白名单只许缩短 + 不许脱离单一台账**。

    ① **只许缩短**：登记的键必须**仍然真的**是「未知必填字段」（app 侧把死规则块清理掉后，
       登记必须同批销账）；
    ② **不许另开账本**：每条豁免的 `(工具, action)` 必须出现在单一台账
       `RETIRED_RULE_KEYS_B_END_READONLY` 里 —— 也就是说，本白名单只允许豁免**已被登记为
       死键**的规则块，不允许拿它给一个**活的**写规则开豁免。
    """
    rules, _ = _live_rules()
    unknown = set(_live_unknown(rules))
    retired = retired_rule_actions()
    problems: list[str] = []
    for key in sorted(UNKNOWN_REQUIRED_KEYS):
        tool, _, rest = key.partition(".")
        action, _, field = rest.partition(".")
        if not (tool and action and field):
            problems.append(f"{key}：键必须写成 `<工具>.<action>.<字段>` 三段式")
            continue
        if key not in unknown:
            problems.append(f"{key}：已不再是「未知必填字段」⇒ 陈旧登记必须销账（台账只许缩短）")
            continue
        if (tool, action) not in retired:
            problems.append(
                f"{key}：豁免的规则块 `{tool}.{action}` **不在**单一台账 "
                f"`{RETIRED_LEDGER_SYMBOL}` 里 ⇒ 不允许拿本白名单给活的规则开豁免"
                f"（要开就得先把它登记进单一台账，在 diff 里看得见）"
            )
        print(f"[F8 登记·不判红] {key}：{UNKNOWN_REQUIRED_KEYS[key]}")
    print(f"\n[F8] 单一台账 `{RETIRED_LEDGER_SYMBOL}` 现取 {len(retired)} 条死键")
    assert problems == [], (
        "F8 白名单与现取读数 / 单一台账不符：\n  " + "\n  ".join(problems)
    )


def test_guard_surfaces_are_not_empty() -> None:
    """**反空跑**：三个判据面都必须取得到（面取错 ⇒ 上面几条判据全在空集上恒真）。

    ⚠️ 这里只判「面非空」，**不写死条数** —— 条数一律现取并打印（本文件的所有读数都是现取的）。
    """
    rules, writes = _live_rules()
    with_required = [f"{tool}.{action}" for tool, actions in rules.items()
                     for action, required in actions.items() if required]
    retired = retired_rule_actions()
    print(
        f"\n[面自检] 规则表工具 {len(rules)} 个 / 带必填的规则块 {len(with_required)} 条 / "
        f"写工具 {len(writes)} 个 / 单一台账 {len(retired)} 条"
    )
    assert rules, "`_VALIDATION_RULES` 读出 0 个工具 ⇒ F6/F8 会在空集上恒真"
    assert with_required, "没有一条规则带 `required` ⇒ F8 判据空转（fail-closed）"
    assert writes, f"{TOOLS_DIR} 下扫不到标记 `read_only = False` 的工具 ⇒ F6 判据空转（fail-closed）"
    assert retired, f"单一台账 `{RETIRED_LEDGER_SYMBOL}` 读出 0 条 ⇒ F8 白名单对账判据空转"


# ══════════════════════════════════════════════════════════════════════════════
# 四、注入式自证（**在现取真值上**再证一遍：判据必须能报出，也必须能不报）
# ══════════════════════════════════════════════════════════════════════════════


class TestDetectorsAreNotVacuous:
    """:red_circle: 三个检测器各带正例（合成载荷）与负例（防恒红），外加**在真源码/真表上**的注入。"""

    def test_duplicate_detector_reports_a_tool_level_duplicate(self) -> None:
        """P2 的真实踩坑形态（工具级重复键）⇒ 必须报出，且行号指向**重复那一次**。"""
        src = (
            f"{RULES_SYMBOL} = {{\n"
            '    "employee_manage": {"create": {"required": ["name"]}},\n'
            '    "employee_manage": {"update": {"required": ["user_id"]}},\n'
            "}"
        )
        assert duplicate_literal_keys(ast.parse(src)) == [(3, "employee_manage")], (
            "检测器漏报工具级重复键 —— 这正是 P2 踩到的那个形态"
        )

    def test_duplicate_detector_reports_nested_action_and_field_duplicates(self) -> None:
        """嵌套层级同样要报：action 级、字段级各一例。"""
        src = (
            f"{RULES_SYMBOL} = {{\n"                                     # 1
            '    "order_manage": {\n'                                    # 2
            '        "cancel": {"required": ["order_id"]},\n'            # 3
            '        "cancel": {"required": ["order_id"]},\n'            # 4 ← action 级
            '        "refund": {"required": ["order_id"],\n'             # 5
            '                   "refund_amount": {"min": 0.01},\n'       # 6
            '                   "refund_amount": {"min": 1.0}},\n'       # 7 ← 字段级
            "    },\n"
            "}"
        )
        assert duplicate_literal_keys(ast.parse(src)) == [(4, "cancel"), (7, "refund_amount")], (
            "嵌套层级（action 级 / 字段级）的重复键没有被报出"
        )

    def test_duplicate_detector_stays_quiet_on_spreads_and_unique_keys(self) -> None:
        """负例：键唯一 + `**spread` + 两个不同的计算键 ⇒ **必须不报**（防恒红）。"""
        src = (
            "BASE = {}\n"
            f'{RULES_SYMBOL} = {{**BASE, "a": {{**BASE, "x": {{"type": str}}}}, f("k"): 1, f("j"): 2}}'
        )
        assert duplicate_literal_keys(ast.parse(src)) == [], (
            "检测器对**合法**字面量误红（展开/两个不同的计算键都不是重复键）"
        )

    def test_duplicating_a_tool_key_in_the_live_source_turns_f5_red(self) -> None:
        """**红证 ① 的形态（在真源码上、不落盘）**：复制一个顶层工具键 ⇒ F5 必报出它。"""
        source = VALIDATE_INPUT_PY.read_text(encoding="utf-8")
        literal = validation_rules_literal()
        name = _key_label(literal.keys[0])
        line = literal.keys[0].lineno
        lines = source.splitlines(keepends=True)
        injected = "".join(lines[: line - 1] + [f'    "{name}": {{}},\n'] + lines[line - 1:])
        reported = [key for _, key in duplicate_literal_keys(ast.parse(injected))]
        assert reported == [name], (
            f"在真源码里复制顶层键 `{name}` 后 F5 没报出它（现取 {reported}）"
            f"⇒ 判据对真源码不敏感"
        )

    def test_rule_less_detector_reports_and_stays_quiet(self) -> None:
        """F6 内核：未登记的写工具 ⇒ 报出；全部有规则 ⇒ 不报。"""
        assert rule_less_write_tools({"order_manage": {}}, ["order_manage", "brand_new_manage"]) == [
            "brand_new_manage"
        ], "F6 内核漏报「新增写工具没有规则」—— 这正是 F6 要防的静默重现"
        assert rule_less_write_tools({"a": {}, "b": {}}, ["a", "b"]) == [], (
            "F6 内核把**有规则**的写工具也报出来（恒红方向）"
        )

    def test_removing_a_write_tool_rule_block_turns_f6_red_on_the_live_table(self) -> None:
        """**红证 ② 的形态（在现取真值上）**：删掉一个写工具的规则块 ⇒ F6 必报出该工具。"""
        rules, writes = _live_rules()
        gated = sorted(set(rules) & set(writes))
        assert gated, "现取表里没有一个「有规则块的写工具」—— 本自证无从成立（fail-closed）"
        target = gated[0]
        mutated = {tool: acts for tool, acts in rules.items() if tool != target}
        assert target in rule_less_write_tools(mutated, writes), (
            f"从现取表里删掉 `{target}` 的规则块后 F6 没有报出它 ⇒ 判据对真值不敏感"
        )

    def test_unknown_field_detector_reports_a_typo_and_stays_quiet(self) -> None:
        """F8 内核：拼错的字段 ⇒ 报出；真实存在的字段 ⇒ 不报。"""
        code = {"order_manage": "params.get('order_id')"}
        assert unknown_required_fields({"order_manage": {"cancel": ("order_id",)}}, code) == [], (
            "F8 内核把源码里真实存在的字段报成未知（恒红方向）"
        )
        assert unknown_required_fields({"order_manage": {"cancel": ("order_idd",)}}, code) == [
            "order_manage.cancel.order_idd"
        ], "F8 内核漏报拼错的字段名 —— 这正是 F8 要防的形态"

    def test_mentions_field_is_not_a_substring_match(self) -> None:
        """F8 内核的字段匹配是**独立标识符/字符串**，不是子串（`amount` 不该被 `refund_amount` 顶替）。"""
        assert _mentions_field("x = refund_amount", "amount") is False, (
            "字段匹配退化成了子串匹配（`refund_amount` 会把 `amount` 顶替掉 ⇒ 漏检）"
        )
        assert _mentions_field('{"amount": 1}', "amount") is True, "字符串键形态没有被认出来"

    def test_injecting_an_unknown_field_turns_f8_red_on_the_live_table(self) -> None:
        """**红证 ③ 的形态（在现取真值上）**：把一条真规则的 `required` 换成不存在的字段 ⇒ F8 必报出。"""
        rules, _ = _live_rules()
        gated = sorted((tool, action) for tool, actions in rules.items()
                       for action, required in actions.items() if required)
        assert gated, "现取表里没有一条带必填字段的规则 —— 本自证无从成立（fail-closed）"
        tool, action = gated[0]
        mutated = {t: {a: tuple(r) for a, r in acts.items()} for t, acts in rules.items()}
        mutated[tool][action] = ("no_such_field_xyz",)
        reported = unknown_required_fields(mutated, _tool_code_by_module(rules.keys()))
        assert f"{tool}.{action}.no_such_field_xyz" in reported, (
            f"把现取规则 `{tool}.{action}` 的 `required` 换成不存在的字段后 F8 没有报出"
            f"（现取 {reported}）⇒ 判据对真值不敏感"
        )

    def test_malformed_literals_are_fail_closed(self) -> None:
        """解析前提被破坏时**必须抛错**（不是静默跳过）：`**spread` 让工具集无法确定 ⇒ 红。"""
        spread = f'{RULES_SYMBOL} = {{**BASE, "order_manage": {{"cancel": {{"required": ["order_id"]}}}}}}'
        with pytest.raises(AssertionError, match="spread"):
            rule_table(_as_dict_literal(ast.parse(spread).body[0].value, RULES_SYMBOL))
        not_a_list = f'{RULES_SYMBOL} = {{"order_manage": {{"cancel": {{"required": "order_id"}}}}}}'
        with pytest.raises(AssertionError, match="required"):
            rule_table(_as_dict_literal(ast.parse(not_a_list).body[0].value, RULES_SYMBOL))
