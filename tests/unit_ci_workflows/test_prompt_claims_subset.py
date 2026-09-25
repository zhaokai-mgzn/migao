# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""Prompt 声称 ⊆ 代码事实（issue #4025 台账 F20）。

## 病根（台账原文）

> **F20**：prompt 是行为主要载体却只有长度守卫：`test_prompt_snapshots.py` 只断言
> `200 < len(prompt) < 13000` ⇒ **改语义不改长度 = 零信号**。

实测（`backend/ai-agent-service/tests/test_prompt_snapshots.py` 的
`test_skill_prompt_length_reasonable`）：唯一对**整段** prompt 的机械断言就是长度区间
（上限已滚到 14800）。把「库存按 0.1 米粒度记录」改成「0.3 米」、把订单状态机的
`cancelled` 换成 `refunded`、把算料必填字段改成 `no_such_field_xyz` —— **长度一字不变
⇒ 全仓零信号**（这正是一次等长注入红证要证明的事）。

## 处置方向（泛化 #4125「能力索引」的范式）

`tests/test_capability_index_prompt.py` 的范式是「判据**从事实 derive**：现算期望值 vs
prompt 实际内容逐项比对，不写死任何名字」。本文件把它推广到 F20 的四类声称：

| 类别 | 声称点（prompt 现取） | 事实源（代码现取） |
|---|---|---|
| **阈值数字** | `references/prompts/product.md` 的「库存粒度 0.1 米、最多 1 位小数」 | `backend/ai-agent-service/app/tools/inventory_manage.py::STOCK_QUANTUM` |
| **阈值数字** | `references/prompts/customer_quote.md` 的「≤2.2m 单开 / >5m 四开」 | `backend/ai-agent-service/app/clarification/curtain_checklist.py::WIDTH_SINGLE_MAX` / `::WIDTH_FOUR_MIN` |
| **枚举值** | `references/prompts/order.md` §订单状态机 的 `中文(值)` 状态图 | `app/tools/validate_input.py::_VALIDATION_RULES["order_manage"]["update_status"]["status"]["enum"]` |
| **枚举值** | `references/prompts/customer_quote.md` 的「可选 eyelet(打孔)/…」 | `app/tools/curtain_calc.py::CurtainCalcTool.parameters["mounting"]["enum"]` |
| **必填字段名** | `references/prompts/customer_quote.md` §算料参数 表格（字段列 + 必填列） | `app/tools/curtain_calc.py::CurtainCalcTool.parameters["properties"]` / `["required"]` |
| **白名单/词表** | 术语映射表（口语说法 → 内部值） | **已覆盖，不重写**：`backend/ai-agent-service/tests/test_issue_4454_craft_glossary.py`（真值源 `docs/curtain-production-rules.md` §8，双向包含 + 注入式自证） |

判不动、也没硬凑成假判据的类别**显式登记**（见 `_CLAIM_GAPS`，由
`test_claim_gaps_are_registered_and_printed` 打印 + 逐条校验 reason/issue/owner）——
**不许静默跳过**。

## 为什么是**纯静态**（不 import 后端 app 包）

本文件跑在 CI 的 `ci workflow helper unit tests` job 里，该 job 只 `pip install pytest pyyaml`
（没有 pydantic/langchain 等后端依赖，见 `tests/unit_ci_workflows/test_ai_agent_prompt_reference_guard.py`
的同款说明）。故两侧都由**文本 + AST** 取：prompt 侧读 `.md` 原文，事实侧从**源码字面量**反解
（`_VALIDATION_RULES` / `CurtainCalcTool.parameters` / 模块级常量）。每个事实源都 **fail-closed**：
常量改名、结构变成非字面量、要取的键消失 ⇒ 抛错（不给「扫不到就通过」留口子）。

## 每条断言的红证（改这一处即红，实测读数见 PR body）

| 用例 | 反例输入（改这一处即红） |
|---|---|
| `test_stock_granularity_claim_matches_code_constant` | `product.md` 的「0.1 米」改「0.2 米」（**等长**）⇒ 点名 声称 0.2 / 事实 0.1 |
| `test_open_count_width_thresholds_match_clarification_constants` | `customer_quote.md` 的「≤2.2m 单开」改 2.3（等长）⇒ 点名两侧 |
| `test_order_state_machine_claim_matches_validation_enum` | 状态图里 `(cancelled)` 改 `(refunded)`（不存在的枚举值）⇒ 点名 `refunded` |
| `test_mounting_enum_claim_matches_tool_schema_enum` | 「可选」串里塞一个 schema 没有的 `(no_such_mounting)` ⇒ 点名它 |
| `test_quote_field_names_are_declared_parameters` | 算料参数表字段列塞 `no_such_field_xyz` ⇒ 点名它 |
| `test_quote_required_fields_are_declared_required` | 把某「否」行改成「是」⇒ 点名该字段未被代码声明必填 |
| `TestClaimCheckerIsNotVacuous` | 注入式夹具：杜撰的声称必须被报出、真声称必须不被报 |

## 边界（照实登记，别把「登记了」读成「治住了」）

* 只覆盖**能从源码字面量取到事实**的声称点 —— 判不了的见 `_CLAIM_GAPS`（打印 + 逐条理由）；
* **工具名**类声称已有守卫（`tests/test_capability_index_prompt.py` 能力索引、
  `tests/unit_ci_workflows/test_ai_agent_prompt_reference_guard.py` 必需文件），本文件**不重复造**；
* 「**新增一个 prompt 文件/声称点，而没有任何东西变红**」这条**没有机械锁**：
  登记点是人加的（`_CLAIM_SITES`）；本文件只保证**已登记的站点**不会静默失效（fail-closed）。
"""
from __future__ import annotations

import ast
import re
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = REPO_ROOT / "backend" / "ai-agent-service"
REF_DIR = SERVICE_ROOT / "app" / "graph" / "skills" / "references"
TOOLS_DIR = SERVICE_ROOT / "app" / "tools"
CLARIFICATION_DIR = SERVICE_ROOT / "app" / "clarification"

PRODUCT_PROMPT = REF_DIR / "prompts" / "product.md"
ORDER_PROMPT = REF_DIR / "prompts" / "order.md"
QUOTE_PROMPT = REF_DIR / "prompts" / "customer_quote.md"

VALIDATE_INPUT_PY = TOOLS_DIR / "validate_input.py"
CURTAIN_CALC_PY = TOOLS_DIR / "curtain_calc.py"
INVENTORY_MANAGE_PY = TOOLS_DIR / "inventory_manage.py"
CURTAIN_CHECKLIST_PY = CLARIFICATION_DIR / "curtain_checklist.py"

#: 判不动 / 本包未固化的声称类别登记表（**未登记即红**：新增/删除都必须在
#: `test_claim_gaps_are_registered_and_printed` 里逐条给出理由与去向；不许静默跳过）。
_CLAIM_GAPS = (
    {
        "kind": "undecidable",
        "site": "references/**（全体）",
        "claim": "自然语言行为规则（「必须发确认卡」「不得甩锅权限」「面向用户一律中文」「不编造数据」…）",
        "reason": "真值 = LLM 的**行为**，代码侧没有可逐项比对的字面量 ⇒ 静态判不了；"
                  "只能由行为评测（.github/cases/** 的 data_checks / order_before）承担",
        "issue": "#4025",
        "owner": "行为评测 owner（.github/cases 面）",
    },
    {
        "kind": "undecidable",
        "site": "references/EXAMPLES-customer_knowledge.md",
        "claim": "行业/店铺知识数值（「棉麻水温不超过30°C」「雪尼尔/高精密建议干洗」）",
        "reason": "真值在商户知识库条目（knowledge-templates/** 与 DB 行），不在代码里；"
                  "同一条文案按租户可不同 ⇒ 代码侧无单一事实源可比",
        "issue": "#4025",
        "owner": "知识库 owner（knowledge-templates 面）",
    },
    {
        "kind": "unfixed",
        "site": "references/prompts/order.md §加工单",
        "claim": "加工单状态机 generated→issued→in_processing→completed｜cancelled",
        "reason": "真值在 Java 侧（ProcessingOrderService 的状态机），ai-agent-service 内**没有**对应字面量；"
                  "本文件的事实源刻意限定为「Python 源码字面量」⇒ 跨语言解析登记为未固化",
        "issue": "#4025",
        "owner": "该守卫 owner（tests/unit_ci_workflows/test_prompt_claims_subset.py）",
    },
    {
        "kind": "unfixed",
        "site": "references/prompts/order.md §订单状态机 第 3 条",
        "claim": "散文里的枚举提及（「只有 shipped 才能确认收货、只有 producing 才能发货、pending/confirmed 才能关闭」）",
        "reason": "句子形态不固定，机械抽取会假红（本仓踩过多次「判据被自己的文案喂红」）；"
                  "同一枚举集已由状态图（fenced block）那一站覆盖 ⇒ 只登记不另判",
        "issue": "#4025",
        "owner": "该守卫 owner（tests/unit_ci_workflows/test_prompt_claims_subset.py）",
    },
    {
        "kind": "unfixed",
        "site": "references/prompts/customer_quote.md 智能默认值表",
        "claim": "款式→褶皱倍数散文映射（「打孔帘 2 倍、韩式褶 2 倍、四爪钩 2 倍、罗马帘 1 倍」）",
        "reason": "真值 DEFAULT_FULLNESS 可得，缺的是**无白名单的定位方式**："
                  "要把「打孔帘/韩式褶/四爪钩/罗马帘」映到 DEFAULT_FULLNESS 的键，就得人写一张中文→枚举表"
                  "（本仓对白名单复发有专门守卫）⇒ 登记为未固化，不硬凑",
        "issue": "#4025",
        "owner": "该守卫 owner（tests/unit_ci_workflows/test_prompt_claims_subset.py）",
    },
)

_ABSENT = object()


# ══════════════════════════════════════════════════════════════════════════════
# 一、取事实：源码字面量（纯 AST，fail-closed）
# ══════════════════════════════════════════════════════════════════════════════


def _module_ast(path: Path) -> ast.Module:
    """读源码 AST；文件缺失/语法错即**报错**（fail-closed，不静默跳过）。"""
    assert path.is_file(), f"守卫的被扫目标不存在：{path}（fail-closed，不静默跳过）"
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _literal(node: ast.AST):
    """把「字面量」AST 节点转成 Python 值；遇到解释不了的形态 ⇒ 报错（fail-closed）。

    支持：常量 / dict / list / tuple / `Decimal("…")`。**不支持**的东西宁可红，
    也不返回半个结构（返回残缺结构会让下游判据静默空跑）。
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Dict):
        out = {}
        for key, value in zip(node.keys, node.values):
            if key is None:                      # `{**other}` 展开
                raise AssertionError(
                    f"事实源里出现 dict 展开（`**`）⇒ 守卫无法反解，宁可红：{ast.dump(node)[:120]}")
            out[_literal(key)] = _literal(value)
        return out
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_literal(element) for element in node.elts]
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "Decimal" and len(node.args) == 1):
        return Decimal(_literal(node.args[0]))
    raise AssertionError(
        f"事实源不再是字面量（{type(node).__name__}）⇒ 守卫无法反解，宁可红：{ast.dump(node)[:120]}")


def _assigned_to(node: ast.AST, name: str):
    """`name = …` 与 `name: T = …` 两种形态统一取右值（取不到 ⇒ `None`）。"""
    if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets):
        return node.value
    if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
            and node.target.id == name):
        return node.value
    return None


def _module_assign_node(tree: ast.Module, name: str, where: str) -> ast.AST:
    """模块级 `name = <节点>`（含带类型注解的 `name: T = …`）的右值**节点**；缺失 ⇒ 报错。"""
    for node in tree.body:
        value = _assigned_to(node, name)
        if value is not None:
            return value
    raise AssertionError(
        f"{where} 里找不到模块级赋值 `{name} = …` —— 事实源消失了（fail-closed："
        f"「常量没了」必须比「声称对不上」更早红）")


def _module_assign_value(tree: ast.Module, name: str, where: str):
    """模块级 `name = <字面量>` 的值（整份都是字面量时用这个）。"""
    return _literal(_module_assign_node(tree, name, where))


def _class_attr_node(tree: ast.Module, class_name: str, attr: str, where: str) -> ast.AST:
    """类属性 `class_name.attr = <节点>` 的右值节点（类/属性缺失 ⇒ 报错）。"""
    for node in tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        for stmt in node.body:
            value = _assigned_to(stmt, attr)
            if value is not None:
                return value
        raise AssertionError(f"{where} 的 `{class_name}` 里找不到类属性 `{attr}` —— 事实源消失了")
    raise AssertionError(f"{where} 里找不到类 `{class_name}` —— 事实源消失了（fail-closed）")


def _dig_ast(node: ast.AST, keys, where: str) -> ast.AST:
    """在 **AST 层**按 `keys` 逐层下钻（缺键/结构变形 ⇒ 报错）。

    ⚠️ 为什么在 AST 层走而不是先整体转成 dict：事实源里混着**只读不取**的非字面量
    （如 `_VALIDATION_RULES` 的 `{"type": str}` —— `str` 是 `Name` 不是字面量）。
    整体转换会因这些**与判据无关**的节点而红；**只转换真正读到的那一条路径**，
    才既严格（读到的必须能解释）又不误伤。
    """
    current = node
    walked: list = []
    for key in keys:
        if not isinstance(current, ast.Dict):
            raise AssertionError(
                f"{where} 里取 `{'/'.join(str(k) for k in keys)}` 时在 `{walked}` 处断了 —— "
                f"事实源的结构变了（fail-closed）")
        found = None
        for key_node, value_node in zip(current.keys, current.values):
            if key_node is not None and _literal(key_node) == key:
                found = value_node
                break
        if found is None:
            raise AssertionError(
                f"{where} 里取 `{'/'.join(str(k) for k in keys)}` 时在 `{walked}` 处缺键 {key!r} —— "
                f"事实源的结构变了（fail-closed）")
        current = found
        walked.append(key)
    return current


def _dig(node: ast.AST, keys, where: str):
    """`_dig_ast` + 把最终节点转成 Python 值（读到的这一条路径必须全是字面量）。"""
    return _literal(_dig_ast(node, keys, where))


def validation_enum(tool: str, action: str, field: str) -> list:
    """`_VALIDATION_RULES[tool][action][field]["enum"]`（现取，不抄清单）。"""
    tree = _module_ast(VALIDATE_INPUT_PY)
    rules = _module_assign_node(tree, "_VALIDATION_RULES", "app/tools/validate_input.py")
    values = _dig(rules, [tool, action, field, "enum"], f"_VALIDATION_RULES[{tool}][{action}]")
    assert values and all(isinstance(v, str) for v in values), (
        f"_VALIDATION_RULES[{tool}][{action}][{field}][enum] 不是非空字符串表：{values!r}")
    return list(values)


def tool_parameters_node() -> ast.AST:
    """`CurtainCalcTool.parameters` 的右值**节点**（现取，不抄字段名）。"""
    tree = _module_ast(CURTAIN_CALC_PY)
    return _class_attr_node(tree, "CurtainCalcTool", "parameters", "app/tools/curtain_calc.py")


def stock_quantum() -> Decimal:
    """库存记数粒度常量（定义点 = `inventory_manage.py`；`product_manage` 从它导入）。"""
    tree = _module_ast(INVENTORY_MANAGE_PY)
    value = _module_assign_value(tree, "STOCK_QUANTUM", "app/tools/inventory_manage.py")
    assert isinstance(value, Decimal), f"STOCK_QUANTUM 不再是 Decimal：{value!r}"
    return value


def checklist_constant(name: str) -> Decimal:
    """`curtain_checklist.py` 的模块级数值常量（现取）。"""
    tree = _module_ast(CURTAIN_CHECKLIST_PY)
    value = _module_assign_value(tree, name, "app/clarification/curtain_checklist.py")
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{name} 不再是数值字面量：{value!r}")
    return Decimal(str(value))


def decimal_places(value: Decimal) -> int:
    """十进制字面量的小数位数（`Decimal(\"0.1\")` ⇒ 1）。"""
    exponent = value.as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


# ══════════════════════════════════════════════════════════════════════════════
# 二、取声称：prompt 原文（文本解析，fail-closed）
# ══════════════════════════════════════════════════════════════════════════════

_SECTION_END_RE = re.compile(r"^## ", re.M)
_FENCE_RE = re.compile(r"^```.*?$(.*?)^```", re.M | re.S)
_ENUM_IN_PARENS_RE = re.compile(r"\(([a-z_][a-z0-9_]*)\)")
_LATIN_TOKEN_RE = re.compile(r"[a-z_][a-z0-9_]*")


def _prompt_text(path: Path) -> str:
    assert path.is_file(), f"prompt 文件不存在：{path}（fail-closed，不静默跳过）"
    return path.read_text(encoding="utf-8")


def _section(text: str, head: str) -> str:
    """`head` 开头的段（到下一个 `## ` 为止）；缺失 ⇒ 报错（红，不静默跳过）。"""
    index = text.find(head)
    assert index >= 0, (
        f"找不到段落 {head!r} —— 段落被删/改名 ⇒ 该判据失效（fail-closed："
        f"「声称点消失」必须比「声称对不上」更早红）")
    match = _SECTION_END_RE.search(text, index + len(head))
    return text[index:(match.start() if match else len(text))]


def _unique(pattern: str, text: str, label: str) -> str:
    """`pattern` 在 `text` 里**恰好**命中一次 ⇒ 返回捕获组；0 次或多次 ⇒ 报错。"""
    hits = re.findall(pattern, text)
    assert len(hits) == 1, (
        f"{label}：期望恰好 1 处，实测 {len(hits)} 处 {hits!r} —— "
        f"要么声称被删（判据变空跑），要么出现多份口径（真值分叉）")
    return hits[0]


# ── 站点 ①：库存粒度（product.md）────────────────────────────────────────────

_GRANULARITY_RE = r"库存粒度\s*([0-9]+(?:\.[0-9]+)?)\s*米"
_DECIMALS_RE = r"最多\s*([0-9]+)\s*位小数"


def stock_granularity_claims(text: str) -> dict:
    """{`granularity_meters`, `max_decimal_places`} —— product.md 声称的库存记数口径。"""
    return {
        "granularity_meters": Decimal(_unique(_GRANULARITY_RE, text, "库存粒度声称")),
        "max_decimal_places": int(_unique(_DECIMALS_RE, text, "小数位声称")),
    }


def stock_granularity_facts() -> dict:
    """同一份口径的**代码事实**（常量 + 由它算出的小数位数）。"""
    quantum = stock_quantum()
    return {"granularity_meters": quantum, "max_decimal_places": decimal_places(quantum)}


# ── 站点 ②：开数宽度阈值（customer_quote.md）────────────────────────────────

_SINGLE_MAX_RE = r"≤\s*([0-9]+(?:\.[0-9]+)?)\s*m\s*单开"
_FOUR_MIN_RE = r">\s*([0-9]+(?:\.[0-9]+)?)\s*m\s*四开"


def open_count_threshold_claims(text: str) -> dict:
    """{`single_open_max_m`, `four_open_min_m`} —— customer_quote.md 声称的开数分界。"""
    return {
        "single_open_max_m": Decimal(_unique(_SINGLE_MAX_RE, text, "单开上限声称")),
        "four_open_min_m": Decimal(_unique(_FOUR_MIN_RE, text, "四开下限声称")),
    }


def open_count_threshold_facts() -> dict:
    return {
        "single_open_max_m": checklist_constant("WIDTH_SINGLE_MAX"),
        "four_open_min_m": checklist_constant("WIDTH_FOUR_MIN"),
    }


# ── 站点 ③：订单状态机（order.md）──────────────────────────────────────────

_ORDER_SM_RE = re.compile(r"^## 订单状态机", re.M)


def order_state_machine_claims(text: str) -> set:
    """订单状态机状态图里 `中文(值)` 的**值**集合（只取 fenced block，不取散文）。"""
    section = None
    match = _ORDER_SM_RE.search(text)
    assert match, "order.md 里找不到 `## 订单状态机` 段 —— 声称点消失（fail-closed）"
    section = _section(text[match.start():], "## 订单状态机")
    fence = _FENCE_RE.search(section)
    assert fence, "`## 订单状态机` 段里没有 fenced 状态图 —— 声称点消失（fail-closed）"
    claims = set(_ENUM_IN_PARENS_RE.findall(fence.group(1)))
    assert claims, "状态图里一个 `中文(值)` 都没解析到 —— 判据会空跑（fail-closed）"
    return claims


def order_state_machine_facts() -> set:
    return set(validation_enum("order_manage", "update_status", "status"))


# ── 站点 ④：悬挂方式枚举（customer_quote.md）────────────────────────────────

_OPTIONAL_ENUM_LINE_RE = re.compile(r"^.*mounting.*可选(.*)$", re.M)


def mounting_enum_claims(text: str) -> set:
    """「可选 eyelet(打孔)/s_hook(韩式褶)/…」里的枚举值集合。"""
    match = _OPTIONAL_ENUM_LINE_RE.search(text)
    assert match, (
        "customer_quote.md 里找不到含 `mounting` 与「可选」的那一行 —— 声称点消失（fail-closed）")
    claims = set()
    for option in match.group(1).split("/"):
        token = re.match(r"\s*([a-z_][a-z0-9_]*)\s*\(", option)
        assert token, (
            f"「可选」串里的一项不是 `值(中文)` 形态：{option!r} —— 解析不了 ⇒ 宁可红"
            f"（不静默漏掉一项声称）")
        claims.add(token.group(1))
    assert claims, "「可选」串里一个枚举值都没解析到 —— 判据会空跑（fail-closed）"
    return claims


def mounting_enum_facts() -> set:
    values = _dig(tool_parameters_node(), ["properties", "mounting", "enum"],
                  "CurtainCalcTool.parameters")
    assert values and all(isinstance(v, str) for v in values), f"mounting.enum 不是字符串表：{values!r}"
    return set(values)


# ── 站点 ⑤：算料参数表（customer_quote.md）────────────────────────────────

def quote_param_rows(text: str) -> list:
    """§算料参数 表格的 `(字段名表, 必填?)` 行（表头/分隔行不算；空表 ⇒ 报错）。"""
    section = _section(text, "## 算料参数")
    rows = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or set(cells[0]) <= set("-: "):
            continue                                  # 分隔行
        if cells[0] == "字段":                         # 表头
            continue
        rows.append((_LATIN_TOKEN_RE.findall(cells[0]), cells[1]))
    assert rows, "§算料参数 表格解析出 0 行 —— 判据会空跑（fail-closed）"
    for names, flag in rows:
        assert names, f"算料参数表有一行的字段列没有可解析的字段名：{flag!r} 行"
        assert flag in ("是", "否"), f"算料参数表的必填列出现非 是/否 取值：{flag!r}"
    return rows


def quote_param_claims(text: str) -> dict:
    """{`declared_fields`, `required_fields`} —— 算料参数表声称的字段名与必填项。"""
    rows = quote_param_rows(text)
    return {
        "declared_fields": {name for names, _ in rows for name in names},
        "required_fields": {name for names, flag in rows if flag == "是" for name in names},
    }


def quote_param_facts() -> dict:
    """工具 schema 的事实：已声明属性 + 代码声明必填（`required` 数组 ∪ 描述里写「必填」的字段）。"""
    parameters = tool_parameters_node()
    properties = _dig(parameters, ["properties"], "CurtainCalcTool.parameters")
    required = _dig(parameters, ["required"], "CurtainCalcTool.parameters")
    assert isinstance(properties, dict) and properties, f"parameters.properties 为空：{properties!r}"
    assert isinstance(required, list) and required, f"parameters.required 为空：{required!r}"
    declared_required = {name for name in required if isinstance(name, str)}
    for name, spec in properties.items():
        if isinstance(spec, dict) and "必填" in str(spec.get("description", "")):
            declared_required.add(name)
    return {"declared_fields": set(properties), "required_fields": declared_required}


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据本体（纯函数，供注入式红证驱动 —— 判据能红才不是空断言）
# ══════════════════════════════════════════════════════════════════════════════


def subset_violations(claims, facts) -> list:
    """`claims` 里**不**属于 `facts` 的元素（保序）—— 「声称 ⊄ 事实」。"""
    return [claim for claim in sorted(claims) if claim not in facts]


def missing_from_claims(claims, facts) -> list:
    """`facts` 里**没有**任何声称覆盖的元素（保序）—— 「事实 ⊄ 声称」（全图声称用）。"""
    return [fact for fact in sorted(facts) if fact not in claims]


def value_mismatches(claims: dict, facts: dict) -> list:
    """逐键比对**数值/取值是否相等**，返回「声称值 vs 事实值」的差异描述。"""
    problems = []
    for key in sorted(set(claims) | set(facts)):
        claimed = claims.get(key, _ABSENT)
        fact = facts.get(key, _ABSENT)
        if claimed != fact:
            problems.append(f"{key}: 声称 {claimed} vs 事实 {fact}")
    return problems


def format_violations(label: str, problems: list, hint: str) -> str:
    return (f"{label}：\n  " + "\n  ".join(problems) + f"\n→ {hint}")


# ══════════════════════════════════════════════════════════════════════════════
# 四、判据
# ══════════════════════════════════════════════════════════════════════════════


def test_claim_census_is_visible_and_non_vacuous():
    """现取条数打印（每类声称 ≥1 条）—— 「扫不到」不许长得像「通过」。"""
    quote = quote_param_claims(_prompt_text(QUOTE_PROMPT))
    census = {
        "库存粒度/小数位声称（product.md）": len(stock_granularity_claims(_prompt_text(PRODUCT_PROMPT))),
        "开数宽度阈值声称（customer_quote.md）": len(open_count_threshold_claims(_prompt_text(QUOTE_PROMPT))),
        "订单状态机枚举声称（order.md）": len(order_state_machine_claims(_prompt_text(ORDER_PROMPT))),
        "悬挂方式枚举声称（customer_quote.md）": len(mounting_enum_claims(_prompt_text(QUOTE_PROMPT))),
        "算料参数表字段行（customer_quote.md）": len(quote_param_rows(_prompt_text(QUOTE_PROMPT))),
    }
    for label, count in census.items():
        print(f"[prompt-claims] 现取 {label} = {count} 条")
    assert all(count > 0 for count in census.values()), f"有站点现取 0 条（判据会空跑）：{census}"
    assert quote["required_fields"] <= quote["declared_fields"], (
        f"算料参数表的必填项不是字段列的子集：{sorted(quote['required_fields'] - quote['declared_fields'])}")


def test_stock_granularity_claim_matches_code_constant():
    """product.md 声称的库存记数口径必须**等于** `STOCK_QUANTUM` 与它的小数位数。

    反例输入：把「0.1 米」改成「0.2 米」（**字符数不变**）⇒ 必红，点名 声称 0.2 / 事实 0.1。
    """
    claims = stock_granularity_claims(_prompt_text(PRODUCT_PROMPT))
    facts = stock_granularity_facts()
    problems = value_mismatches(claims, facts)
    assert not problems, format_violations(
        "product.md 的库存记数口径与代码常量不一致（issue #4025 F20）", problems,
        f"事实源 = {INVENTORY_MANAGE_PY.relative_to(REPO_ROOT)}::STOCK_QUANTUM（`product_manage` 从它导入）；"
        f"改口径必须改代码常量，或把 prompt 的声称改成与它一致")


def test_open_count_width_thresholds_match_clarification_constants():
    """customer_quote.md 声称的开数宽度分界必须**等于**追问清单里的两个常量。

    反例输入：把「≤2.2m 单开」改成「≤2.3m 单开」（**等长**）⇒ 必红，点名两侧读数。
    """
    claims = open_count_threshold_claims(_prompt_text(QUOTE_PROMPT))
    facts = open_count_threshold_facts()
    problems = value_mismatches(claims, facts)
    assert not problems, format_violations(
        "customer_quote.md 的开数宽度分界与追问清单常量不一致（issue #4025 F20）", problems,
        f"事实源 = {CURTAIN_CHECKLIST_PY.relative_to(REPO_ROOT)}::WIDTH_SINGLE_MAX / ::WIDTH_FOUR_MIN；"
        f"「默认值」与「prompt 教给模型的默认值」必须是同一个数")


def test_order_state_machine_claim_matches_validation_enum():
    """订单状态图的每个值都必须是代码闸门枚举里的值，且枚举每个值都要在图上。

    反例输入：把 `(cancelled)` 改成 `(refunded)`（代码里不存在的枚举值）⇒ 必红并点名 `refunded`。
    """
    short = subset_violations(order_state_machine_claims(_prompt_text(ORDER_PROMPT)),
                              order_state_machine_facts())
    assert not short, format_violations(
        "order.md 的状态图声称了代码里不存在的订单状态（issue #4025 F20）", short,
        "事实源 = app/tools/validate_input.py::_VALIDATION_RULES[order_manage][update_status]"
        "[status][enum]；模型会照着图把不存在的状态说给商家 ⇒ 要么删这个声称，要么补进闸门枚举")

    absent = missing_from_claims(order_state_machine_claims(_prompt_text(ORDER_PROMPT)),
                                 order_state_machine_facts())
    assert not absent, format_violations(
        "order.md 的状态图漏掉了代码支持的订单状态（状态图声称的是**全图**）", absent,
        "事实源同上；漏一个状态 ⇒ 模型答不出那条流转（声称不完整与声称错误同害）")


def test_mounting_enum_claim_matches_tool_schema_enum():
    """「可选 eyelet(打孔)/…」的每个值都必须在工具 schema 的 `mounting.enum` 里，且反向不漏。

    反例输入：串里塞一个 schema 没有的 `no_such_mounting` ⇒ 必红并点名该符号。
    """
    claims = mounting_enum_claims(_prompt_text(QUOTE_PROMPT))
    facts = mounting_enum_facts()
    problems = [f"声称了 schema 没有的悬挂方式：{v}" for v in subset_violations(claims, facts)]
    problems += [f"schema 支持却未告知模型：{v}" for v in missing_from_claims(claims, facts)]
    assert not problems, format_violations(
        "customer_quote.md 的悬挂方式枚举与工具 schema 不一致（issue #4025 F20）", problems,
        "事实源 = app/tools/curtain_calc.py::CurtainCalcTool.parameters[properties][mounting][enum]")


def test_quote_field_names_are_declared_parameters():
    """算料参数表的每个字段名都必须是 `curtain_calc` 已声明的入参（防杜撰字段名）。

    反例输入：字段列塞 `no_such_field_xyz` ⇒ 必红并点名该符号（模型会照着一个传不进去的键采集）。
    """
    claims = quote_param_claims(_prompt_text(QUOTE_PROMPT))["declared_fields"]
    facts = quote_param_facts()["declared_fields"]
    problems = subset_violations(claims, facts)
    assert not problems, format_violations(
        "customer_quote.md 的算料参数表列了工具入参里没有的字段（issue #4025 F20）", problems,
        "事实源 = app/tools/curtain_calc.py::CurtainCalcTool.parameters[properties]；"
        "prompt 是模型采集参数的唯一依据 ⇒ 杜撰字段名会让采集结果进不了工具")


def test_quote_required_fields_are_declared_required():
    """算料参数表标「必填=是」的字段，代码侧必须也把它声明为必填。

    反例输入：把某个「否」行改成「是」⇒ 必红，点名该字段未被代码声明必填。
    """
    claims = quote_param_claims(_prompt_text(QUOTE_PROMPT))["required_fields"]
    facts = quote_param_facts()["required_fields"]
    problems = subset_violations(claims, facts)
    assert not problems, format_violations(
        "customer_quote.md 声称必填、而代码没声明必填的字段（issue #4025 F20）", problems,
        "事实源 = CurtainCalcTool.parameters[required] ∪ {描述里写「必填」的字段}；"
        "「prompt 说必填、代码不强制」= 模型少采一个参数也不会被拦（静默出坏报价）")


def test_claim_gaps_are_registered_and_printed():
    """判不动 / 未固化的声称类别**显式登记**（打印 + 逐条 reason/issue/owner），不静默跳过。"""
    for gap in _CLAIM_GAPS:
        missing = [key for key in ("kind", "site", "claim", "reason", "issue", "owner")
                   if not str(gap.get(key) or "").strip()]
        assert not missing, f"声称缺口登记条目不完整（缺 {missing}）：{gap}"
        assert gap["kind"] in ("undecidable", "unfixed"), (
            f"缺口类别必须是 undecidable（无机械真值）或 unfixed（有真值但本包未固化）：{gap['kind']}")
    kinds = {gap["kind"] for gap in _CLAIM_GAPS}
    assert kinds == {"undecidable", "unfixed"}, (
        f"两类缺口都要有（否则「判不了」与「没做」会被混为一谈）：实测 {sorted(kinds)}")
    for gap in _CLAIM_GAPS:
        print(f"[prompt-claims-gap/{gap['kind']}] {gap['site']} :: {gap['claim']} —— "
              f"{gap['reason']}（{gap['issue']} / {gap['owner']}）")


# ══════════════════════════════════════════════════════════════════════════════
# 五、判据自身不恒真（注入式自证 + 负例）
# ══════════════════════════════════════════════════════════════════════════════


class TestClaimCheckerIsNotVacuous:
    """判据必须**能报出**杜撰的声称，也必须**不报**真的声称（两侧都测，防恒真/恒红）。"""

    def test_subset_checker_reports_a_planted_claim(self):
        """杜撰的声称 ⇒ 必须被报出（否则判据是空的）。"""
        facts = order_state_machine_facts()
        assert subset_violations({"refunded"} | facts, facts) == ["refunded"]

    def test_subset_checker_stays_quiet_on_real_claims(self):
        """负例：真声称（现取的事实本身）⇒ 必须不报（防恒红）。"""
        facts = order_state_machine_facts()
        assert subset_violations(facts, facts) == []
        assert missing_from_claims(facts, facts) == []

    def test_value_mismatch_names_both_sides(self):
        """数值判据必须点名**两侧读数**（只报「不一致」无法定位）。"""
        problems = value_mismatches({"granularity_meters": Decimal("0.2")},
                                    {"granularity_meters": Decimal("0.1")})
        assert len(problems) == 1 and "0.2" in problems[0] and "0.1" in problems[0], problems

    def test_value_mismatch_stays_quiet_when_equal(self):
        """负例：两侧相等（含 `5` vs `5.0` 这种同值异写法）⇒ 必须不报。"""
        assert value_mismatches({"four_open_min_m": Decimal("5.0")},
                                {"four_open_min_m": Decimal("5")}) == []

    def test_literal_reader_refuses_a_non_literal_fact(self, tmp_path):
        """事实源在**读到的那条路径上**变成非字面量 ⇒ **报错**，不返回半个结构。"""
        planted = tmp_path / "planted.py"
        planted.write_text(
            "_VALIDATION_RULES = {'t': {'a': {'f': {'enum': SOME_CONSTANT}}}}\n",
            encoding="utf-8")
        tree = _module_ast(planted)
        rules = _module_assign_node(tree, "_VALIDATION_RULES", str(planted))
        try:
            _dig(rules, ["t", "a", "f", "enum"], str(planted))
        except AssertionError as exc:
            assert "不再是字面量" in str(exc), str(exc)
        else:
            raise AssertionError("非字面量事实源没有被拒绝 —— 守卫会在运行时静默空跑")

    def test_path_navigation_refuses_a_missing_key(self, tmp_path):
        """下钻路径上缺键 ⇒ **报错**（结构变了不许静默返回空）。"""
        planted = tmp_path / "planted.py"
        planted.write_text("_VALIDATION_RULES = {'t': {'a': {}}}\n", encoding="utf-8")
        tree = _module_ast(planted)
        rules = _module_assign_node(tree, "_VALIDATION_RULES", str(planted))
        try:
            _dig(rules, ["t", "a", "f", "enum"], str(planted))
        except AssertionError as exc:
            assert "缺键" in str(exc), str(exc)
        else:
            raise AssertionError("缺键没有被拒绝 —— 事实源被改结构后判据会静默空跑")

    def test_section_reader_refuses_a_missing_section(self, tmp_path):
        """声称点段落消失 ⇒ **报错**（fail-closed），不许「找不到就通过」。"""
        planted = tmp_path / "planted.md"
        planted.write_text("# 只有一个标题\n没有状态机段\n", encoding="utf-8")
        try:
            order_state_machine_claims(planted.read_text(encoding="utf-8"))
        except AssertionError as exc:
            assert "订单状态机" in str(exc), str(exc)
        else:
            raise AssertionError("段落缺失没有被拒绝 —— 「声称点被删」会静默变绿")

    def test_numeric_claims_reader_reports_both_readings(self):
        """站点 ① 的解析本身可红：把 prompt 原文换成另一组数 ⇒ 解析结果跟着变。"""
        planted = "（库存粒度 0.2 米、最多 3 位小数），禁止四舍五入或改写。"
        assert stock_granularity_claims(planted) == {
            "granularity_meters": Decimal("0.2"), "max_decimal_places": 3}

    def test_quote_param_rows_refuses_an_unparseable_required_flag(self):
        """必填列出现非法取值（不是 是/否）⇒ 报错（否则新形态会被静默漏判）。"""
        planted = ("## 算料参数\n\n| 字段 | 必填 | 如何获取 |\n|---|---|---|\n"
                   "| window_width 窗宽 | 必须 | 顾客提供 |\n")
        try:
            quote_param_rows(planted)
        except AssertionError as exc:
            assert "必填列" in str(exc), str(exc)
        else:
            raise AssertionError("非法必填取值没有被拒绝 —— 判据会静默漏掉这类行")
