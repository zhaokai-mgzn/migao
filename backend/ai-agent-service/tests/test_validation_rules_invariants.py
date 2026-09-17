# case_ids: OR-015, OR-014, PR-019, HR-005, ST-001, FN-001, AS-003, PP-006, PR-021
"""闸门规则表不变式族（F5 重复键 / F6 写 action 覆盖 / F8 schema 一致）。

> 本文件 = issue #4027（P9 守卫族扩建）的 F5/F6/F8 落点。**只读静态守卫**：
> 不改产品代码（`app/**`），把「一次性审计」变成「每次 CI 都会红」的不变式。
> 全部零 LLM、秒级、无网络、无 DB（唯一一次运行时调用是纯本地的 `validate_input`）。

## 病灶形状（三类**静默失效**，全部来自 P2 实测，不是推测）

真相源是 `app/tools/validate_input.py` 的 `_VALIDATION_RULES` —— 一张
**普通 dict 字面量**，它是写操作确认链的**唯一**确定性闸门（`base_skill` 靠它
`validated=True` 才落「已校验待执行」并放行写工具）。三类缺陷都**不会自己变红**：

| ID | 形态 | 后果（为什么静默） | 当前状态 |
|---|---|---|---|
| **F5** | dict 字面量**重复键**（P2 开发中亲自踩到：`employee_manage` 出现两个键，后者**吃掉**前者，**零报错**） | Python 语义就是「后者胜」⇒ 被吃掉的规则块**人间蒸发**，闸门对那批 action 退化成「无规则」（A4 前=假绿放行，A4 后=fail-closed 拒绝合法调用）。**运行时 dict 看不出来**（键只有一个），只有 **AST** 能看见。判据按 **AST 结构同一性**认键 ⇒ 字符串键（`"employee_manage"`）与枚举成员键（`INTENT_TOOL_MAP` 的 `IntentType.ORDER_QUERY`）一并覆盖 | 当前**无**重复键（已修）⇒ 守卫绿；注入重复键必红 |
| **F6** | 缺全域不变式「注册表里每个写 action 必须有规则」 | P2 把 A4 的写路径缺口补全后**没有留下任何门**：下次新增写工具/写 action 又忘补规则 ⇒ 要么假绿（旧语义）要么拦住合法调用，**没有任何测试会红** | 当前**绿**（P2 补齐 + issue #4047 把「无参写 action」也收进"必须有规则"） |
| **F8** | `required` 与**工具 schema** 之间无一致性检查 | 规则写错字段名（schema 里不存在）⇒ 闸门永远要求一个模型给不出的参数；规则**漏**掉工具 schema 的必填 ⇒ 闸门放行注定 422 的调用。两种都**照样返回 `validated=True`** | 当前**绿**（逐条核对过，见 `test_rule_fields_exist_in_tool_schema` / `test_tool_required_fields_are_gated`） |

**F5 为什么必须用 AST**：`_VALIDATION_RULES` 是模块级字面量，Python 在**编译期**就把
重复键折叠掉（后者胜），`import` 之后拿到的 dict 里**只剩一个键** —— 用运行时对象
永远查不出这件事（这正是它能静默到今天的原因）。

## 每条断言的反例输入（红证，逐条实测过）

| 用例 | 反例输入（改这一处即红） | 实测命令 |
|---|---|---|
| `test_no_duplicate_keys_in_validation_rules` | 在 `_VALIDATION_RULES` 顶层或任一工具块内复制一个键（如再加一个 `"employee_manage"`） | `pytest tests/test_validation_rules_invariants.py -q` |
| `test_no_duplicate_dict_keys_across_app` | 任意 `app/**/*.py` 的字典字面量里出现重复常量键 | 同上 |
| `test_every_write_action_is_deterministically_gated` | 从 `_VALIDATION_RULES` 删掉任一写 action 的条目（含**无参**的 `notification_manage.read_all` —— 见 `test_deleting_a_write_action_rule_turns_f6_red`，它在**真实注册表**上执行这次注入） | 同上 |
| `test_rule_less_action_fails_closed` | 把 `validate_input.execute` 的「无规则」分支改回 A4 前的 `success=True, skipped=True`（输入取工具自述的只读 action，该分支在运行期真实可达） | 同上 |
| `test_single_action_write_tools_are_gated` | 删掉 `sku_update` / `product_update` / `order_create` / `aftersale_create` 的整条规则 | 同上 |
| `test_registered_read_all_is_not_blocked` | 把 `read_all` 的规则改回缺条目（合法无参写调用被 fail-closed 拦）或把规则写成 `required: ["x"]` | 同上 |
| `test_rule_fields_exist_in_tool_schema` | 把某条规则的 `required` 改成 schema 里不存在的字段（如 `order_manage.cancel` 的 `order_id` → `order_idd`） | 同上 |
| `test_tool_required_fields_are_gated` | 从某条规则里删掉工具 schema 的必填（如 `sku_update.update` 的 `price`） | 同上 |

注入式夹具（`TestDuplicateKeyDetectorIsNotVacuous` / `TestWriteActionCoverageDetectorIsNotVacuous`
/ `TestSchemaConsistencyDetectorIsNotVacuous`）**与被测真值解耦**，每个判据都必须能报出，
也必须能不报（负例，R2）—— 防「恒真断言」与「恒红断言」两种坏判据。

## 适用域声明（对谁生效 / 对谁**不**生效）

| 维度 | 本文件覆盖 | 明确**不**覆盖（不写恒真判断凑数） |
|---|---|---|
| 工具 | 注册表中 `read_only=False` 的**全部**写工具 | 只读工具（`read_only=True`）：无写副作用 ⇒ 闸门不做要求 |
| action | 多动作写工具的 `action` 枚举 − `read_only_actions`（工具自述的只读 action） | 单动作写工具的「隐含 action 名」不做字符串猜测（见下） |
| 单动作写工具 | `schema.required` 非空者 ⇒ 规则表必须有条目（`order_create`/`aftersale_create`/`product_update`/`sku_update`） | `schema.required` 为空者（`human_handoff`：无参数契约、A4 已定为 fail-closed 拒绝）⇒ **登记打印**，不判红 |
| 无参写 action | **同样必须有规则**（issue #4047 收紧）：正确写法是显式 `{"required": []}`（`read_all` 已补，与 `settings_manage.update_settings` 同形）⇒ 运行期**真跑过**校验、合法调用不被拦（`test_registered_read_all_is_not_blocked`） | 不再有「无参 ⇒ 可以没有规则」这一档。**「没有规则」≠「无需校验」**：前者让 `validate_input` 走 fail-closed 分支（合法写路径被拦，即 #3566 把 `settings_manage.update_settings` 拦死的同型坏法） |
| 方向 | 规则 → 工具 schema（字段存在性）与工具 schema → 规则（必填覆盖） | 「规则比工具 schema **更严**是否有业务理由」不判（`settings_manage.update_settings` 的 `required: []` 是合法形态） |

## 为什么 F6 的域要按「可证明无参」而不是「名字像读操作」来划

`notification_manage` 的 `read_all`（全部标为已读）**名字**像读，实际是写
（`read_only_actions` 只声明了 `list`/`unread_count`）；反过来 `inventory_manage.adjust`
名字像写也确实是写。**按名字/中文措辞判读写 = 判据建在语料上**（R5 禁止，且宽正则实测会误伤：
`customer_manage` 同时有 `update`（写）与 `list`/`detail`（读））。
故本文件只用**代码真值**两类：① 工具自述的 `read_only_actions`；② `execute()` 里该 action
分派分支**实际接收的参数**（AST 读出）——两者都在类定义里，改名/加减 action 都会跟着动。

**fail-closed 方向**：分派分支找不到、调用带 `**kwargs` 透传、或工具源码不可解析
⇒ 一律视为**参数化**（必须有规则）。即「判不出来」永远不会退化成「无需规则」。

## `param_less` 字段现在的用途（issue #4047 之后，**不再是豁免**）

抽取「该 action 零业务参数」这件事仍然保留（`dispatch_params` 的 AST 读法），但它
**不再换豁免** —— 只用来把违规信息说准：无参写 action 缺规则时，出口是**显式补
`{"required": []}`**（声明"无参即合法"），而不是"因为无参所以可以没有规则"。这条区分是
F6 从 issue #4047 起唯一的口径（此前那一档「无参 ⇒ 可以没有规则 ⇒ 由运行时 fail-closed
兜底」已撤销：它把「闸门漏一格」写成了合法终态，而运行期后果是**合法写路径被拦**）。
"""

import ast
import collections
import inspect
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
VALIDATE_INPUT_PY = APP_DIR / "tools" / "validate_input.py"
RULES_NAME = "_VALIDATION_RULES"
EXECUTE_FUNC = "execute"


# ──────────────────────────────────────────────────────────────────────────────
# 源码解析工具（**读源真值**，fail-closed：解析不到 ≠ 无违规）
# ──────────────────────────────────────────────────────────────────────────────


def _module_ast(path: Path) -> ast.Module:
    """模块 AST。读不到/解析不了 ⇒ 抛错（守卫不得静默跳过）。"""
    return ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))


def _module_level_literal(tree: ast.Module, name: str) -> ast.expr:
    """模块级 `name = <expr>`（含 `name: T = <expr>`）的右值；找不到 ⇒ 抛错。"""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name and node.value:
                return node.value
    raise AssertionError(
        f"{VALIDATE_INPUT_PY} 里找不到模块级赋值 `{name}` —— 闸门真相源消失了。"
        f"请同步本守卫（**不得**静默跳过：解析不到 ≠ 无违规）"
    )


def validation_rules_literal() -> ast.Dict:
    """`_VALIDATION_RULES` 的**字面量**节点（AST，不是运行时 dict）。"""
    literal = _module_level_literal(_module_ast(VALIDATE_INPUT_PY), RULES_NAME)
    assert isinstance(literal, ast.Dict), (
        f"`{RULES_NAME}` 不再是字典字面量（{ast.dump(literal)[:80]}）—— 本守卫的解析前提变了，"
        f"请同步守卫（若改成由别处生成，请把判据挂到那个生成源上）"
    )
    assert literal.keys, f"`{RULES_NAME}` 解析出 0 个键 —— 守卫会空转（fail-closed）"
    return literal


# ──────────────────────────────────────────────────────────────────────────────
# F5：AST 级「无重复键」检测器
# ──────────────────────────────────────────────────────────────────────────────


def _key_label(key_node: ast.expr) -> str:
    """重复键的可读标签：常量字符串直接给值，其余给源码文本（如 `IntentType.ORDER_QUERY`）。"""
    if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
        return key_node.value
    return ast.unparse(key_node)


def duplicate_literal_keys(node: ast.AST) -> list[tuple[int, str]]:
    """递归找出字典**字面量**里的重复键 ⇒ `[(行号, key), …]`（按行号排序）。

    行号 = **重复出现的那一次**（第二次及以后）所在行 —— 直接指向要删/要合并的那一行，
    而不是字典字面量的起始行（后者在多行规则块里指不到地方）。

    键的「相同」按 **AST 结构同一性**判（`ast.dump`），因此覆盖三类字面量键：
    字符串常量（`"employee_manage"`）、枚举成员（`IntentType.ORDER_QUERY` —— `INTENT_TOOL_MAP`
    就是这么写的，同样会被 Python 静默折叠）、以及可辨识的表达式。
    **`**spread`（AST 里 key 为 `None`）不是键**，不参与判据（也不误报）。
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


def test_no_duplicate_keys_in_validation_rules():
    """**F5 核心不变式**：`_VALIDATION_RULES` 的字面量里不得有重复键（任何层级）。

    重复键的后果**不可见**：Python 编译期折叠 ⇒ `import` 之后只剩下最后一个键，
    被吃掉的那块规则（含 `required`/`enum`/`label`）**完全消失**，且没有任何报错。
    P2 开发中亲自踩到（`employee_manage` 两个键，后者吃掉前者）—— 这就是它必须
    由 AST 而不是运行时 dict 来判的原因。

    反例输入：在任一工具块内再写一次已有的 action 键（如 `"toggle_status"`）⇒ 必红。
    """
    dups = duplicate_literal_keys(validation_rules_literal())
    assert dups == [], (
        "`_VALIDATION_RULES` 出现**重复键**（Python 会静默让后者吃掉前者）：\n  "
        + "\n  ".join(f"第 {line} 行：`{key}`" for line, key in dups)
        + "\n→ 被吃掉的规则块在运行时**不存在**（闸门对该 action 退化成「无规则」）。"
        "\n→ 修法：合并两块（保留语义并集），**不得**靠调整顺序「让后者胜」。"
    )


def test_no_duplicate_dict_keys_across_app():
    """**同族机制扫描**（R1：同类实例 ≥2 就修机制）：`app/**` 全部字典字面量都不得有重复键。

    为什么扩到全 `app/**`：F5 的病灶是「**Python dict 字面量重复键静默丢配置**」这个语言级
    形状，不是 `validate_input` 独有 —— 任何放置配置/映射/别名表的字面量都会中同一刀
    （实证过的近亲：`role_manage` 的权限映射、`INTENT_TOOL_MAP` 一类表）。
    当前全仓 0 处（本用例绿）；新增即红。

    反例输入：在 `app/` 里任一 `{...}` 字面量中复制一个键 ⇒ 必红。
    """
    offenders: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        try:
            tree = _module_ast(path)
        except SyntaxError:  # pragma: no cover - 语法错的文件不属本守卫
            continue
        dups = duplicate_literal_keys(tree)
        if dups:
            offenders[str(path.relative_to(APP_DIR.parent))] = dups

    detail = "\n  ".join(
        f"{path}: " + "、".join(f"第 {line} 行 `{key}`" for line, key in dups)
        for path, dups in sorted(offenders.items())
    )
    assert offenders == {}, (
        f"`app/**` 有 {len(offenders)} 个文件出现**字典字面量重复键**（静默丢配置）：\n  "
        + detail
        + "\n→ 重复键只有最后一个生效，其余内容不可见（读代码/读运行时对象都看不出来）。"
    )


class TestDuplicateKeyDetectorIsNotVacuous:
    """**:red_circle: 红证（注入式）+ 负例**：F5 判据必须能报出，也必须能不报。"""

    def test_detector_catches_the_p2_employee_manage_shape(self):
        """P2 的真实踩坑形态（工具级重复键）⇒ **必须报出**。"""
        src = (
            f'{RULES_NAME} = {{\n'
            '    "employee_manage": {"create": {"required": ["name", "phone"]}},\n'
            '    "employee_manage": {"update": {"required": ["user_id"]}},\n'
            '}'
        )
        assert duplicate_literal_keys(ast.parse(src)) == [(3, "employee_manage")], (
            "检测器漏报工具级重复键 —— 这就是 P2 踩到的那个形态"
        )

    def test_detector_catches_a_nested_action_and_field_duplicate(self):
        """嵌套层级同样要报：action 级重复、字段级重复各一例（行号指向**重复那一次**）。"""
        src = (
            f'{RULES_NAME} = {{\n'                    # 1
            '    "order_manage": {\n'                  # 2
            '        "cancel": {"required": ["order_id"]},\n'          # 3
            '        "cancel": {"required": ["order_id"]},\n'          # 4 ← action 级重复
            '        "refund": {"required": ["order_id"],\n'           # 5
            '                   "refund_amount": {"min": 0.01},\n'     # 6
            '                   "refund_amount": {"min": 1.0}},\n'     # 7 ← 字段级重复
            '    },\n'
            '}'
        )
        assert duplicate_literal_keys(ast.parse(src)) == [(4, "cancel"), (7, "refund_amount")], (
            "嵌套层级（action 级 / 字段级）的重复键没有被报出"
        )

    def test_detector_stays_quiet_on_unique_keys_and_spreads(self):
        """负例：键唯一 + `**spread` + 计算键各自唯一 ⇒ **必须不报**（防恒红，R2）。"""
        src = (
            'BASE = {}\n'
            f'{RULES_NAME} = {{**BASE, "a": {{**BASE, "x": {{"type": str}}}}, f("k"): 1, f("j"): 2}}'
        )
        assert duplicate_literal_keys(ast.parse(src)) == [], (
            "检测器对**合法**字面量误红（展开/两个不同的计算键都不是重复键）"
        )

    def test_detector_catches_an_enum_member_key_duplicate(self):
        """枚举成员键（`INTENT_TOOL_MAP` 的形态）同样会被 Python 静默折叠 ⇒ 必须报出。

        这一类最容易被忽略：键不是字符串而是 `IntentType.X`，肉眼更像「不同写法」，
        但 AST 结构同一 ⇒ 同一键 ⇒ 后者胜。`app/router/intent_config.py` 的
        `INTENT_TOOL_MAP` 是现存实例（当前无重复，本用例把它纳入判据面）。
        """
        src = (
            'INTENT_TOOL_MAP = {\n'
            '    IntentType.ORDER_QUERY: ["order_query"],\n'
            '    IntentType.LOGISTICS_TRACK: ["logistics_track"],\n'
            '    IntentType.ORDER_QUERY: ["order_query", "order_manage"],\n'
            '}'
        )
        assert duplicate_literal_keys(ast.parse(src)) == [(4, "IntentType.ORDER_QUERY")]


# ──────────────────────────────────────────────────────────────────────────────
# F6：注册表里每个写 action 必须被闸门**确定性地**处理
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WriteActionView:
    """一个写 action 的**判定事实**（由注册表 + 源码 AST 派生，供纯函数判据消费）。

    Attributes:
        tool: 工具名。
        action: 多动作写工具的 action 名；`None` = 单动作写工具（schema 无 `action` 枚举）。
        gated: 规则表是否覆盖它（多动作看该 action 的键；单动作看该工具是否有条目）。
        param_less: `True` 仅当 **AST 证明**该 action 的分派只传 `context`；
                    `False`/`None` 一律按「参数化」处理（fail-closed）。
                    ⚠️ issue #4047 起它**不再是豁免**，只用来把违规信息说准
                    （无参 ⇒ 出口是补 `{"required": []}`）。
        schema_required: 工具 schema 的必填参数（原样）。
    """

    tool: str
    action: str | None
    gated: bool
    param_less: bool | None
    schema_required: tuple[str, ...]


def coverage_violations(views: list[WriteActionView]) -> list[str]:
    """**F6 判据内核**（纯函数）：返回「**已登记可写**却没有校验规则」的清单。

    判定（issue #4047 收紧后**只有一态**：有规则才算过）：

    * 多动作写工具（`action` 非空）：`_VALIDATION_RULES` 里**必须有**该 action 的条目。
      缺 ⇒ **违规**，**无论它是不是无参 action** —— 无参写 action 的正确写法是显式声明
      `{"required": []}`（与 `settings_manage.update_settings` / `update_ai_config` 同形），
      不是「没有规则」。两者在 `base_skill` 的确认-执行链上**后果相反**：
        - `{"required": []}` ⇒ 校验**真跑过**（`validated=True`）⇒ 合法写路径继续；
        - 「没有规则」⇒ 走「该操作无校验规则」fail-closed 分支 ⇒ **合法写路径被闸门拦死**
          （#3566 的 `settings_manage.update_settings` 就是这么坏掉的）。
      issue #4047 之前这里对无参 action 留了豁免（"交运行时 fail-closed 兜底"），
      那等于把「闸门漏一格」写成合法终态 —— 已撤销。
    * 单动作写工具（`action is None`）：`schema_required` 非空 ⇒ 规则表必须有条目，否则违规
      （隐含 action 名只存在于规则表自身，故不猜名字，见文件头）。
    """
    violations: list[str] = []
    for view in views:
        if view.action is not None:
            if view.gated:
                continue
            if view.param_less is True:
                violations.append(
                    f"{view.tool}.{view.action} 是**已登记可写的 action**（AST 已证明它零业务参数）"
                    f"但规则表里没有条目 —— 出口是显式声明 {{\"required\": []}}，"
                    f"不是「没有规则」（后者让合法写调用被 fail-closed 拦住）"
                )
            else:
                violations.append(
                    f"{view.tool}.{view.action} 是**参数化写 action**但没有校验规则"
                    f"（param_less={view.param_less!r} ⇒ 无法证明无需校验）"
                )
        elif view.schema_required and not view.gated:
            violations.append(
                f"{view.tool} 是参数化单动作写工具（schema.required={list(view.schema_required)}）"
                f"但规则表里没有任何条目"
            )
    return violations


def coverage_registrations(views: list[WriteActionView]) -> list[str]:
    """**登记（不判红）**清单 —— 让「域外/合法化」的写 action **可见**，不是静默丢弃。

    只剩一类：单动作写工具且 `schema.required` 为空（如 `human_handoff`：无参数契约，
    口径为「无必填 ⇒ 无规则可校验」，由运行期 fail-closed 兜底）。这一类之所以不判红：
    **单动作工具的隐含 action 名无从代码派生**（只存在于规则表自身），F6 不猜名字
    （见文件头），故它的域只能按「schema 有没有必填」划。

    issue #4047 之前这里还有一类「多动作工具的无参写 action 无规则」—— 已撤销：
    多动作工具的 action 名是**代码真值**（schema 的 `action` 枚举），没有"猜不出来"的问题，
    所以它必须判红。
    """
    notes: list[str] = []
    for view in views:
        if view.action is None and not view.schema_required:
            notes.append(f"{view.tool}：单动作写工具且无 schema 必填 ⇒ 无规则（登记，不判红）")
    return notes


def _tool_class_ast(tool) -> ast.Module | None:
    """工具类的源码 AST；源码不可解析 ⇒ `None`（调用方按「无法判定」处理）。"""
    try:
        src_file = inspect.getsourcefile(type(tool))
        if not src_file:
            return None
        return _module_ast(Path(src_file))
    except (OSError, TypeError, SyntaxError):  # pragma: no cover - 依赖运行环境
        return None


def _is_action_branch(test: ast.expr, action: str) -> bool:
    """该 `if` 的条件是不是 `action == "<action>"`（分派分支的判据形态）。"""
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "action"
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == action
    )


def dispatch_params(tool, action: str) -> list[str] | None:
    """AST 派生：`execute()` 里 `action == "<action>"` 分支**真正接收**的参数名。

    Returns:
        `[]`  = 证明该 action **无业务参数**（分派只传 `context`）；
        `[...]` = 参数名清单（非空即参数化）；
        `None`  = **无法判定**（类/方法/分支找不到、`**kwargs` 透传、源码不可解析）
                  ⇒ 调用方必须按「参数化」处理（fail-closed）。

    三个必须做对的细节（错了会**静默漏判**，实测踩过）：
      1. `execute` 必须取自**该工具的类**（一个文件里可能有多个类，取到别人的 `execute` = 读错真值）；
      2. 只看匹配分支自己的 `body`（`orelse` 是后续 `elif`，走进去会把别的 action 的参数算进来）；
      3. 只认 `self._handler(...)` 形态的调用（否则 `ToolResult(success=…, message=…)` 的
         关键字实参会被当成业务参数 —— 实测把无参的 `read_all` 误判成 9 个参数）。

    为什么按**分派分支的实参**取真值：`base.py` 的 schema 是**工具级** properties
    （多个 action 共用一张表），回答不了「这个 action 要哪些参数」；而分派分支是每个
    action 独有的，且 `**kwargs` 形态会被识别为「无法判定」而不是「无参」——
    这正是 `finance_api`（资金写、`**kwargs` 透传）不会被误判成无参的原因。
    """
    tree = _tool_class_ast(tool)
    if tree is None:
        return None
    cls = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.ClassDef) and n.name == type(tool).__name__),
        None,
    )
    if cls is None:
        return None  # 类不在源码里（动态构造/别名）⇒ 无法判定
    func = next(
        (f for f in cls.body
         if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name == EXECUTE_FUNC),
        None,
    )
    if func is None:
        return None  # `execute` 继承自父类 ⇒ 分派不在此处，无法判定

    params: list[str] = []
    found = False
    for node in ast.walk(func):
        if not isinstance(node, ast.If) or not _is_action_branch(node.test, action):
            continue
        for stmt in node.body:  # 只看本分支自己的 body（不含 orelse 里的后续 elif）
            for sub in ast.walk(stmt):
                if not isinstance(sub, ast.Return) or sub.value is None:
                    continue
                call = sub.value
                while isinstance(call, ast.Await):
                    call = call.value
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "self"
                ):
                    continue  # 非分派调用（ToolResult(...) 等）
                found = True
                for arg in call.args:
                    if isinstance(arg, ast.Name) and arg.id == "context":
                        continue  # ToolContext 不是业务参数
                    params.append(getattr(arg, "id", None) or ast.dump(arg)[:20])
                for kw in call.keywords:
                    if kw.arg is None:  # **kwargs 透传 ⇒ 无法判定
                        return None
                    params.append(kw.arg)
    if not found:
        return None
    return params


def _action_enum(tool) -> list[str] | None:
    """工具 schema 的 `action` 枚举；单动作工具（无该枚举）⇒ `None`。"""
    props = (tool.parameters or {}).get("properties") or {}
    enum = (props.get("action") or {}).get("enum")
    return list(enum) if enum else None


def write_action_views(tools: list, table: dict) -> list[WriteActionView]:
    """从**注册表**派生全部写 action 的判定事实（真值源 = 工具类 + 规则表）。"""
    views: list[WriteActionView] = []
    for tool in sorted(tools, key=lambda t: t.name):
        if tool.read_only:
            continue
        required = tuple((tool.parameters or {}).get("required") or ())
        enum = _action_enum(tool)
        if enum is None:
            views.append(WriteActionView(
                tool=tool.name, action=None, gated=tool.name in table,
                param_less=None, schema_required=required,
            ))
            continue
        read_only_actions = set(getattr(tool, "read_only_actions", None) or ())
        for action in sorted(set(enum) - read_only_actions):
            views.append(WriteActionView(
                tool=tool.name, action=action, gated=action in (table.get(tool.name) or {}),
                param_less=(dispatch_params(tool, action) == []), schema_required=required,
            ))
    assert views, "注册表里解析出 0 个写 action —— 解析失效（守卫会空转，fail-closed）"
    return views


def _registry_write_action_views() -> list[WriteActionView]:
    from app.tools.registry import get_tool_registry
    from app.tools.validate_input import _VALIDATION_RULES

    return write_action_views(list(get_tool_registry().get_all_tools()), _VALIDATION_RULES)


def test_every_write_action_is_deterministically_gated():
    """**F6 核心不变式**：注册表里**每个已登记可写的 action 都必须有校验规则**。

    只有一态（issue #4047 收紧，见 `coverage_violations`）：`_VALIDATION_RULES` 里有条目
    ⇒ 过；没有 ⇒ **判红**（无论参数化与否）。它防的是「下次新增写工具/写 action 又忘补规则」
    这个**静默重现**：旧语义下是 `skipped=True` 假绿，A4 之后是 fail-closed 拦死合法调用 ——
    两种都不会自己变红。

    反例输入（红证 F6）：删掉任一写 action 的规则（`employee_manage.update` /
    `finance_api.create_transaction` / `settings_manage.change_password` / **无参的
    `notification_manage.read_all`**）⇒ 必红。`read_all` 那次注入在**真实注册表**上
    由 `test_deleting_a_write_action_rule_turns_f6_red` 实际执行（不是手写样例）。
    """
    views = _registry_write_action_views()
    violations = coverage_violations(views)
    print(
        "\n[F6] 写 action 覆盖矩阵："
        f"共 {len(views)} 项、有规则 {sum(1 for v in views if v.gated)} 项；"
        f"登记（不判红）{coverage_registrations(views)}"
    )
    assert violations == [], (
        "以下**已登记可写的 action 没有校验规则**：\n  "
        + "\n  ".join(violations)
        + "\n→ 治理口径（issue #4047）：已登记可写 ⇒ 必须有规则。无参写 action 的出口是"
          "**显式声明 `{\"required\": []}`**（与 `settings_manage.update_settings` 同形），"
          "不是「没有规则」—— 后者会被 fail-closed 分支拦死合法调用。"
        "\n→ 修法：在 `_VALIDATION_RULES` 里补该 action 的规则（`required` 按**工具实现"
          "真实必填**声明；零业务参数就写 `[]`）。"
    )


def test_deleting_a_write_action_rule_turns_f6_red():
    """**:red_circle: 红证 ③**：把 `read_all` 的规则从**真实注册表 + 真实规则表**上删掉 ⇒ F6 必红。

    为什么不用手写样例：手写样例只能证明「判据对样例敏感」，证明不了「对**被测的那份
    真相源**敏感」。本用例拿真实工具集（`get_tool_registry()`）+ 真实规则表的**副本**
    （删掉一个键）跑同一条判据内核，注入的就是 issue #4047 的那个键。
    同时**负例 ④**：不删的真值 ⇒ 判据必须不报（防恒红）。

    （运行期那一半——「删掉规则 ⇒ 合法 read_all 被 fail-closed 拦住」——由
    `test_registered_read_all_is_not_blocked` 的反例方向覆盖：把规则删掉，它必红。
    此处**不再造第二套运行期注入机制**：红证要证明的是本判据对真值敏感，
    而 monkeypatch 式注入是另一个实现，留着就是第二份口径。）
    """
    import copy

    from app.tools.registry import get_tool_registry
    from app.tools.validate_input import _VALIDATION_RULES

    tools = list(get_tool_registry().get_all_tools())

    def _violations_for(table: dict) -> list[str]:
        return [
            v for v in coverage_violations(write_action_views(tools, table))
            if v.startswith("notification_manage.read_all ")
        ]

    assert _violations_for(_VALIDATION_RULES) == [], (
        "负例 ④：`read_all` **有规则**（真值）却被判红 —— 判据误伤合法输入（R2）"
    )

    injected = copy.deepcopy(_VALIDATION_RULES)
    del injected["notification_manage"]["read_all"]
    violations = _violations_for(injected)
    print(f"\n[#4047 红证 ③] 删掉 read_all 规则后的判据输出：{violations}")
    assert violations, (
        "红证 ③：删掉 `notification_manage.read_all` 的规则后 F6 **没有报** —— "
        "「已登记可写的 action 必须有规则」这条判据是空的（#4047 会静默复发）"
    )


async def test_registered_read_all_is_not_blocked(admin_tool_context):
    """**:white_check_mark: 负例 ④（运行期）**：合法的 `read_all` 调用**不得被闸门拦**。

    issue #4047 的验收要求就是这一条：补规则之前，`validate_input(target_tool=
    "notification_manage", target_action="read_all")` 落到「无规则」fail-closed 分支
    （`success=False` + 「校验**没有执行**」）⇒ 合法的「全部标为已读」写路径被拦。
    补上 `{"required": []}` 之后必须**真跑过**校验：`success=True` + `validated=True`
    + 无 `issues`/`skipped`（= 不是"跳过了"，是"没有必填可漏"）。
    """
    from app.tools.validate_input import ValidateInputTool

    tool = ValidateInputTool()
    result = await tool.execute(
        context=admin_tool_context, target_tool="notification_manage",
        target_action="read_all", params={"action": "read_all"},
    )
    print(f"\n[#4047] read_all 闸门真实返回：success={result.success}, data={result.data!r}")
    assert result.success is True, (
        f"合法的 read_all 调用被闸门拦住（#4047 要修的正是这个）："
        f"error={result.error!r}, message={result.message!r}, data={result.data!r}"
    )
    assert (result.data or {}).get("validated") is True, (
        f"read_all 没有真跑过校验（validated 不为 True）：{result.data!r}"
    )
    assert not (result.data or {}).get("skipped"), (
        f"read_all 走了「跳过」语义（= 假绿形态）：{result.data!r}"
    )
    assert not (result.data or {}).get("issues"), f"read_all 被报出校验问题：{result.data!r}"


async def test_rule_less_action_fails_closed(admin_tool_context):
    """**无规则分支的运行时验证**：闸门遇到规则表里没有的 action 必须**明确拒绝**，不得假绿。

    输入取**工具自述的只读 action**（`read_only_actions`，如 `notification_manage` 的
    `list`/`unread_count`）：它们在规则表里**本来就没有**条目（只读无需校验），
    所以这是该分支在运行期**真实可达**的路径 —— 不是为凑判据造的样例。
    （issue #4047 之前本用例的输入是「无规则的多动作写 action」；收紧后那种 action
    已被 F6 判红、注册表里**不存在**了，继续用它会让本用例空跑 —— §19.1「空判据」。）

    `success=False` + `data` 里没有 `skipped`/`validated` + `suggestion` 非空
    （R5：fail-closed 分支必须带可行动下一步，`_self_correct_retry` 靠它启动）。

    反例输入（红证）：把 `validate_input.execute` 的「无规则」分支改回 A4 前的
    `ToolResult(success=True, data={"validated": True, "skipped": True})` ⇒ 必红。
    """
    from app.tools.registry import get_tool_registry
    from app.tools.validate_input import ValidateInputTool

    tool = ValidateInputTool()
    probes: list[tuple[str, str]] = []
    for t in sorted(get_tool_registry().get_all_tools(), key=lambda x: x.name):
        for action in sorted(getattr(t, "read_only_actions", None) or ()):
            probes.append((t.name, action))
    assert probes, "注册表里解析出 0 个只读 action —— 探针来源消失（fail-closed，本用例会空跑）"

    checked: list[str] = []
    for tool_name, action in probes:
        result = await tool.execute(
            context=admin_tool_context, target_tool=tool_name,
            target_action=action, params={"action": action},
        )
        checked.append(f"{tool_name}.{action}")
        assert result.success is False, (
            f"{tool_name}.{action} 没有规则却返回 `success=True` —— 这就是 A4 的假绿形态"
            f"（模型会据此直接执行写工具）：{result.data!r}"
        )
        assert not (result.data or {}).get("validated"), (
            f"{tool_name}.{action} 校验**没有跑**却回了 validated=True：{result.data!r}"
        )
        assert result.suggestion, (
            f"{tool_name}.{action} 的 fail-closed 分支没有 suggestion —— "
            f"模型只能原地重试同一组参数（R5）"
        )
    print(f"\n[F6] 无规则 action 的 fail-closed 运行时验证：{checked}")


def test_single_action_write_tools_are_gated():
    """**F6 对单动作写工具的一半**（红证独立，便于逐条复现）。

    单动作写工具（schema 无 `action` 枚举）的**隐含 action 名**无从代码派生
    （`order_create` 的规则键 `create` 只存在于规则表自身）⇒ 不猜名字，**只要求
    「参数化 ⇒ 规则表里必须有条目」**：`schema.required` 非空 = 模型必须给出参数 =
    闸门有东西可校验。

    反例输入（红证 F6）：删掉 `sku_update` / `product_update` / `order_create` /
    `aftersale_create` 的整条规则 ⇒ 必红。
    """
    views = [v for v in _registry_write_action_views() if v.action is None]
    assert views, "注册表里解析出 0 个单动作写工具 —— 解析失效（fail-closed）"
    unguarded = [v.tool for v in views if v.schema_required and not v.gated]
    print(
        "\n[F6] 单动作写工具："
        + "；".join(
            f"{v.tool}(required={list(v.schema_required)}, gated={v.gated})" for v in views
        )
    )
    assert unguarded == [], (
        f"这些单动作写工具**要求参数却没有校验规则**：{unguarded}\n"
        f"→ 闸门拿不到规则 ⇒ 要么假绿放行、要么 fail-closed 拦住合法写路径（两种都坏）。"
    )


def test_write_action_coverage_matrix_is_visible():
    """**可见性断言**（§18.5「账本里看不出来的字段 = 缺陷的盲区」）：域外项必须被打印出来。

    本用例锁两件事：① 注册表里**每个**写工具都在矩阵里出现过（不得有工具静默缺席）；
    ② 登记清单（无 schema 必填的单动作写工具）每次 CI 都打印，
    让「为什么它没有规则」是**可读的事实**，而不是要靠人去反推的沉默。
    """
    from app.tools.registry import get_tool_registry

    views = _registry_write_action_views()
    registry_write_tools = sorted(t.name for t in get_tool_registry().get_all_tools() if not t.read_only)
    seen_tools = sorted({v.tool for v in views})
    assert seen_tools == registry_write_tools, (
        f"写 action 矩阵与注册表写工具集不一致（有工具静默缺席）：\n"
        f"  注册表 = {registry_write_tools}\n  矩阵   = {seen_tools}"
    )
    for note in coverage_registrations(views):
        print(f"[F6 登记·不判红] {note}")


class TestWriteActionCoverageDetectorIsNotVacuous:
    """**:red_circle: 红证（注入式）+ 负例**：F6 判据必须能报出，也必须能不报。"""

    @staticmethod
    def _view(tool: str, action: str | None, gated: bool, param_less=None,
              required=("a",)) -> WriteActionView:
        return WriteActionView(tool=tool, action=action, gated=gated,
                               param_less=param_less, schema_required=tuple(required))

    def test_detector_reports_an_ungated_parameterised_action(self):
        """注入：参数化写 action 无规则（A4 病灶面）⇒ **必须报出**。"""
        assert coverage_violations([
            self._view("brand_new_manage", "archive", gated=False, param_less=False),
        ]), "判据漏报「新增写 action 无规则」—— 这正是 F6 要防的静默重现"
        assert coverage_violations([
            self._view("brand_new_manage", "archive", gated=False, param_less=None),
        ]), "判据把**无法判定**当成「无需规则」（fail-closed 方向被破坏）"

    def test_detector_stays_quiet_when_gated(self):
        """**负例（R2）**：有规则 ⇒ 不报（防恒红）。

        为什么这条必须留着：收紧判据（#4047）最容易的过头是「把有规则的也报出来」——
        那样守卫会永远红，谁也不会再看它。
        """
        assert coverage_violations([
            self._view("order_manage", "cancel", gated=True, param_less=False),
            self._view("sku_update", None, gated=True, required=("product_id", "price")),
        ]) == []

    def test_detector_reports_an_ungated_param_less_action(self):
        """**红证（#4047 的形态）**：无参写 action 无规则 ⇒ **必须报出**（旧口径把它放行）。

        注入的是 `read_all` 的形状（`param_less=True` + 无规则）：issue #4047 之前这一格
        被当成合法终态，于是合法写调用被 fail-closed 拦住而没有任何测试会红。
        """
        violations = coverage_violations([
            self._view("notification_manage", "read_all", gated=False, param_less=True),
        ])
        assert violations, (
            "判据放行了「无参写 action 无规则」—— #4047 的缺口会静默复发"
        )
        assert "required" in violations[0], (
            f"违规信息没有指出出口（显式 `{{\"required\": []}}`）：{violations[0]!r}"
        )

    def test_detector_reports_a_parameterised_single_action_tool_without_rules(self):
        """单动作写工具：schema 要求参数却无规则 ⇒ 报出；无必填（human_handoff 形态）⇒ 登记不报。"""
        assert coverage_violations([self._view("sku_update", None, gated=False)]) == [
            "sku_update 是参数化单动作写工具（schema.required=['a']）但规则表里没有任何条目"
        ]
        assert coverage_violations([self._view("human_handoff", None, gated=False, required=())]) == []
        assert coverage_registrations(
            [self._view("human_handoff", None, gated=False, required=())]
        ) == ["human_handoff：单动作写工具且无 schema 必填 ⇒ 无规则（登记，不判红）"]

    def test_dispatch_params_reader_is_fail_closed(self):
        """`dispatch_params` 的 fail-closed 方向（判不出来 ⇒ `None` ⇒ 按参数化处理）。"""
        class KwargsTool:
            name = "kwargs_tool"

            async def execute(self, context, action, **kwargs):
                if action == "create":
                    return await self._create(context, **kwargs)
                return None

        class NoBranchTool:
            name = "no_branch_tool"

            async def execute(self, context, action):
                return None

        class ExplicitTool:
            name = "explicit_tool"

            async def execute(self, context, action, item_id=None):
                if action == "create":
                    return await self._create(context, item_id, reason="x")
                return None

        assert dispatch_params(KwargsTool(), "create") is None, "`**kwargs` 透传被误判成可判定"
        assert dispatch_params(NoBranchTool(), "create") is None, "分派分支缺失被误判成可判定"
        assert dispatch_params(ExplicitTool(), "create") == ["item_id", "reason"], (
            "显式实参没有被读全（会导致参数化写 action 被误判成无参 = 漏判）"
        )
        assert dispatch_params(KwargsTool(), "no_such_action") is None


# ──────────────────────────────────────────────────────────────────────────────
# F8：规则 `required` ↔ 工具 schema 必填的一致性
# ──────────────────────────────────────────────────────────────────────────────


def undeclared_rule_fields(table: dict, tools: dict) -> list[str]:
    """**F8 方向 A**：规则里出现的字段名必须在工具 schema 里真实存在。

    覆盖规则块的 `required` 列表**与**字段级规则键（`"status": {...}` 这种）——
    两者的作用一样：闸门会拿它去 `params` 里取值，名字错了就永远取不到。

    为什么这条能防住真缺陷：字段名写错（`order_idd`）时闸门**照样 `validated=True`**
    （模型给不出该字段 ⇒ 一律判缺必填 ⇒ 合法调用被拦），而错误信息指向一个
    工具根本不接收的参数名 —— 排查方向被带偏（#3566 的 `settings_manage.data` 就是这么坏掉的）。
    """
    problems: list[str] = []
    for tool_name, actions in table.items():
        tool = tools.get(tool_name)
        if tool is None:
            continue  # 未注册工具由既有的 L0 守卫（test_tools_validate_input）判红
        props = set(((tool.parameters or {}).get("properties") or {}).keys())
        for action, rule in actions.items():
            fields = list(rule.get("required") or []) + [k for k in rule if k != "required"]
            unknown = sorted({f for f in fields if f not in props})
            if unknown:
                problems.append(
                    f"{tool_name}.{action}: 规则声明了 schema 里**不存在**的字段 {unknown}"
                    f"（schema.properties = {sorted(props)}）"
                )
    return problems


def ungated_schema_required(table: dict, tools: dict) -> list[str]:
    """**F8 方向 B**：工具 schema 的**必填**必须被规则 `required` 覆盖（分派参数除外）。

    分派参数（承载 action 枚举的那个 property，通常是 `action`）不参与 —— 它是
    「调用哪个 action」的载体，不是业务参数（由 F6 的 action 枚举覆盖）。

    这条是 F8 证据里那句「规则写错仍 `validated=True`」的**直接**形态：规则漏了工具
    硬必填（如 `sku_update` 的 `price`）⇒ 闸门放行一个注定 422 / 白跑一轮的写调用。
    """
    problems: list[str] = []
    for tool_name, actions in table.items():
        tool = tools.get(tool_name)
        if tool is None:
            continue
        params = tool.parameters or {}
        props = params.get("properties") or {}
        required = list(params.get("required") or [])
        action_enum = (props.get("action") or {}).get("enum")
        # 分派参数 = 那个**枚举取值等于 action 枚举**的 property（通常是 `action`）；
        # 无 action 枚举（单动作工具）时退化为名字 `action`（正常不会出现在 required 里）。
        dispatch_props = {
            name for name, spec in props.items()
            if action_enum and isinstance(spec, dict) and spec.get("enum") == action_enum
        } or {"action"}
        business_required = [f for f in required if f not in dispatch_props]
        if not business_required:
            continue
        for action, rule in actions.items():
            missing = sorted(set(business_required) - set(rule.get("required") or []))
            if missing:
                problems.append(
                    f"{tool_name}.{action}: 工具 schema 必填 {missing} 没有被规则 required 覆盖"
                    f"（规则 = {list(rule.get('required') or [])}）"
                )
    return problems


def test_rule_fields_exist_in_tool_schema():
    """**F8 方向 A 不变式**：规则里的每个字段名必须是工具 schema 声明的参数。

    反例输入（红证 F8）：把某条规则的 `required` 改成 schema 里不存在的字段
    （如 `order_manage.cancel` 的 `order_id` → `order_idd`）⇒ 必红。
    """
    from app.tools.registry import get_tool_registry
    from app.tools.validate_input import _VALIDATION_RULES

    tools = {t.name: t for t in get_tool_registry().get_all_tools()}
    problems = undeclared_rule_fields(_VALIDATION_RULES, tools)
    assert problems == [], (
        "闸门规则声明了工具 schema 里**不存在**的字段（字段名写错 ⇒ 合法调用必被拦，"
        "且错误信息把排查引向不存在的参数）：\n  " + "\n  ".join(problems)
        + "\n→ 修法：字段名对齐工具 `parameters.properties`（`required` 与字段级规则键都要对）。"
    )


def test_tool_required_fields_are_gated():
    """**F8 方向 B 不变式**：工具 schema 的必填必须出现在规则 `required` 里。

    反例输入（红证 F8）：从 `sku_update.update` 的 `required` 里删掉 `price`
    （schema 硬必填）⇒ 必红。
    """
    from app.tools.registry import get_tool_registry
    from app.tools.validate_input import _VALIDATION_RULES

    tools = {t.name: t for t in get_tool_registry().get_all_tools()}
    problems = ungated_schema_required(_VALIDATION_RULES, tools)
    assert problems == [], (
        "闸门规则**漏掉**了工具 schema 的必填字段（闸门放行注定失败的写调用 = 白跑一轮 / 422）：\n  "
        + "\n  ".join(problems)
        + "\n→ 修法：把缺失字段补进该 action 的 `required`（口径：按工具实现真实必填声明）。"
    )


class TestSchemaConsistencyDetectorIsNotVacuous:
    """**:red_circle: 红证（注入式）+ 负例**：F8 两个方向的判据都必须能报出、也必须能不报。"""

    @staticmethod
    def _tool(name: str, props: dict, required: list, enum: list | None = None):
        from types import SimpleNamespace

        parameters = {"type": "object", "properties": dict(props)}
        if enum:
            properties = dict(props)
            properties["action"] = {"type": "string", "enum": list(enum)}
            parameters["properties"] = properties
        if required:
            parameters["required"] = list(required)
        return SimpleNamespace(name=name, parameters=parameters, read_only=False)

    def test_undeclared_field_is_reported(self):
        """注入：规则写了 schema 里不存在的字段 ⇒ **必须报出**（红证 F8 的形态）。"""
        tool = self._tool("order_manage", {"action": {}, "order_id": {}}, ["action"], enum=["cancel"])
        table = {"order_manage": {"cancel": {"required": ["order_idd"]}}}
        assert undeclared_rule_fields(table, {"order_manage": tool}) == [
            "order_manage.cancel: 规则声明了 schema 里**不存在**的字段 ['order_idd']"
            "（schema.properties = ['action', 'order_id']）"
        ]
        assert ungated_schema_required(table, {"order_manage": tool}) == [], "方向 B 对合法字段误红"

    def test_field_level_rule_keys_are_checked_too(self):
        """字段级规则键（非 `required`）同样要查 —— 它的作用与 required 一样。"""
        tool = self._tool("role_manage", {"action": {}, "role_id": {}}, ["action"], enum=["delete"])
        table = {"role_manage": {"delete": {"required": ["role_id"], "role_idd": {"type": str}}}}
        assert undeclared_rule_fields(table, {"role_manage": tool}) == [
            "role_manage.delete: 规则声明了 schema 里**不存在**的字段 ['role_idd']"
            "（schema.properties = ['action', 'role_id']）"
        ]

    def test_missing_schema_required_is_reported_and_dispatch_param_is_ignored(self):
        """注入：规则漏掉 schema 必填 ⇒ 报出；`action`（分派参数）不算业务必填 ⇒ 不误红。"""
        tool = self._tool("sku_update", {"product_id": {}, "price": {}}, ["product_id", "price"])
        table = {"sku_update": {"update": {"required": ["product_id"]}}}
        assert ungated_schema_required(table, {"sku_update": tool}) == [
            "sku_update.update: 工具 schema 必填 ['price'] 没有被规则 required 覆盖"
            "（规则 = ['product_id']）"
        ]

        multi = self._tool("order_manage", {"order_id": {}}, ["action", "order_id"], enum=["cancel"])
        ok_table = {"order_manage": {"cancel": {"required": ["order_id"]}}}
        assert ungated_schema_required(ok_table, {"order_manage": multi}) == [], (
            "分派参数 `action` 被当成业务必填 ⇒ 对正确规则误红（§19.1 假红）"
        )

    def test_detectors_stay_quiet_on_a_consistent_table(self):
        """负例：规则与 schema 一致 ⇒ 两个方向都必须不报（防恒红）。"""
        tool = self._tool("order_manage", {"order_id": {}}, ["action", "order_id"], enum=["cancel"])
        table = {"order_manage": {"cancel": {"required": ["order_id"],
                                            "order_id": {"type": str, "label": "订单ID"}}}}
        tools = {"order_manage": tool}
        assert undeclared_rule_fields(table, tools) == []
        assert ungated_schema_required(table, tools) == []