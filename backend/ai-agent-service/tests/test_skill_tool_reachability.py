# case_ids: OR-029, OR-014
"""跨 skill 工具可达性守卫（A5）+ `CUSTOMER_ONLY_ROLES` 单点化不变式（A10）。

> 本文件 = issue #4012（P3「常驻 L0 守卫」包）的 A5 / A10 落点。**只读静态守卫**：
> 不修改产品代码（`app/**`），只把「一次性审计」变成「每次 CI 都会红」的不变式。
> 全部零 LLM、秒级、无网络、无 DB。

## A5：`validate_input` 是**域无关**的，执行是**域相关**的，中间没有任何守卫

两个事实（都是**读源**得到，不是推断）：

1. **校验侧域无关** —— `app/tools/validate_input.py` 的
   `_VALIDATION_RULES.get(target_tool)` 只查一张**全局**表：只要 `target_tool` 在表里
   （= 任意一个已注册写工具），校验就照常跑，**完全不看当前 skill 的工具集**
   （按 `_VALIDATION_RULES.get(target_tool)` 文本检索）。
2. **执行侧域相关** —— 每个 skill 只会拿到 `SkillConfig.tool_names` 里那十几个工具的
   LangChain 绑定；skill 外的工具名一律 `Tool not found`。

⇒ **「能校验」与「能执行」之间没有任何一层在比对**。skills 可以（也会）对**自己执行不了**
的写工具完成 `validate_input` 并落地「已校验待执行」状态（`base_skill` 在
`validate_input` 成功时落 `pending_validated_input`），随后模型调那个写工具 →
`Tool not found`。线上实证 **#3976**（sess_202d55d49a254a10）：B 端在 `product` skill 内
`validate_input(order_create)` + 发确认卡，点卡后 `[product] Tool not found: order_create`
→ 最终回复「已转到订单流程为您落单…请稍候，我这就提交」而 **orders 表无新订单**。

### 适用域声明（本守卫对谁生效 / 对谁不生效）

| 维度 | 本守卫覆盖 | 明确**不**覆盖（不做恒真判断凑数） |
|---|---|---|
| skill | `SkillRegistry` 里**全部**已注册 skill | 未注册到全局 registry 的动态子集（`create_skill_registry(tool_names)` 的临时注册表） |
| 工具 | `validate_input` 的校验目标里**已注册且 `read_only=False`** 的写工具 | 只读工具的自校验（无写副作用死角，见 `test_cross_skill_gap_scope_declaration`） |
| 方向 | 「绑了 `validate_input` 却执行不了目标写工具」 | 「有写工具但**没绑** `validate_input`」（反方向缺口，**登记不判红**） |

**为什么只判写工具**：只读工具「假绿」的代价是模型空跑一轮后如实说查不到；
写工具的代价是**订单永不落库**（#3976 原文）。两类业务后果不同量级，
把只读一起判红会把正确修法堵死（`migao-dev-flow` §19.1「误红即坏断言」）。

## A10：`CUSTOMER_ONLY_ROLES` 是**两份**定义，`tools/base.py` 的注释却声称单一源

- `app/tools/base.py` 的模块注释原文：「在此声明单一语义源，**chat.py 复用本常量**」；
- 实测：全仓 **0 处** `from app.tools.base import … CUSTOMER_ONLY_ROLES`
  （按 `CUSTOMER_ONLY_ROLES` 文本检索，仅 `tools/base.py` 与 `api/chat.py` 两处定义 + 各自使用）。

⇒ 两份 `{"customer","agent"}` 今天**恰好相等**，所以没有任何东西会红；
明天任一侧加一个角色就**静默分叉**，而分叉的后果是
「工具层认它是顾客、API 层认它是员工」—— 权限口径分裂（审计 07 那一类，间接提示注入面）。
本守卫锁「**单点定义**」这个**结构**，不只锁「今天相等」这个**巧合**。

## 每条断言都有反例输入（红证）

| 用例 | 反例输入（改这一处即红） |
|---|---|
| `test_no_skill_validates_a_write_tool_it_cannot_execute` | 把 `order_create` 从 `order_skill.ORDER_TOOLS` 注释掉 |
| `test_cross_skill_detector_fires_on_the_3976_shape` | 注入式：`product` skill 上下文 + 目标 `order_create` |
| `test_validate_targets_are_registered_tools` | 在 `_VALIDATION_RULES` 里加一个已下线工具名 |
| `test_customer_only_roles_has_exactly_one_definition` | 给 `chat.py` 的 set 加第三个角色 / 新增第三处定义 |
| `test_customer_only_roles_branches_agree_at_runtime` | 把 `chat.py` 的 set 改成含第三个角色 |
| `test_customer_only_roles_import_direction_claim_is_true` | 保持两份独立定义（= 当前状态）⇒ 红 |

> 本文件**不建存量基线**（issue #4012 硬约束）：A5/A10 命中的是**必须修的真违规**，
> 直接红是**预期行为**。机制级修法与依赖见 PR body 关联的独立 issue。
"""

import ast
from pathlib import Path

from app.graph.skills.skill_config import SkillConfig

APP_DIR = Path(__file__).resolve().parents[1] / "app"
CHAT_PY = APP_DIR / "api" / "chat.py"
VALIDATE_INPUT_PY = APP_DIR / "tools" / "validate_input.py"


# ──────────────────────────────────────────────────────────────────────────────
# 源码解析工具（**读源真值**，不靠字符串匹配猜）
# ──────────────────────────────────────────────────────────────────────────────


def _module_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _find_assignment(tree: ast.Module, name: str) -> ast.expr:
    """模块级 `name = <expr>`（含 `name: T = <expr>`）的右值。

    找不到 ⇒ 抛错（**fail-closed**）：解析不到真值绝不允许退化成「没问题」。
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name and node.value:
                return node.value
    raise AssertionError(
        f"{path} 里找不到模块级赋值 `{name}` —— 守卫的真相源消失了，"
        f"请同步本守卫（不得静默跳过：解析不到 ≠ 无违规）"
    )


def _literal_str_set(node: ast.expr | None) -> set[str]:
    """`{"a","b"}` / `frozenset({"a","b"})` 的**字面量**元素集合。"""
    if isinstance(node, ast.Call):
        for arg in node.args:
            if isinstance(arg, (ast.Set, ast.List, ast.Tuple)):
                return {e.value for e in arg.elts if isinstance(e, ast.Constant)}
        return set()
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return {e.value for e in node.elts if isinstance(e, ast.Constant)}
    raise AssertionError(f"不认识的集合字面量形态：{ast.dump(node)[:120]}")


def validation_rule_targets() -> set[str]:
    """`validate_input._VALIDATION_RULES` 的**校验目标工具名**集合（域无关的那张表）。

    用 AST 取字典字面量的 key（不是正则扫文件）：正则会把注释里提到的工具名算进来，
    而「判据建立在注释语料上」正是 R5 禁止的形态（判据必须建立在**已有事实**上）。
    """
    rules = _find_assignment(_module_ast(VALIDATE_INPUT_PY), "_VALIDATION_RULES")
    assert isinstance(rules, ast.Dict), "_VALIDATION_RULES 不再是字典字面量 —— 请同步本守卫"
    targets = {k.value for k in rules.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    assert targets, "_VALIDATION_RULES 解析为空 —— 守卫会空转（fail-closed）"
    return targets


# ──────────────────────────────────────────────────────────────────────────────
# A5 判据本体（纯函数，可被注入式夹具驱动）
# ──────────────────────────────────────────────────────────────────────────────


def cross_skill_validation_gaps(skills, tools, validation_targets) -> list[str]:
    """返回「能校验但执行不了」的**写**工具死角清单。

    参数取「最小形状」而不是全局单例 —— 这样判据自身可被注入式夹具驱动
    （`test_cross_skill_detector_fires_on_the_3976_shape`），而不是只能靠改真代码才红。

    Returns:
        list[str]：每条形如 `"<skill> 可 validate_input(<tool>) 但执行不了它"`；
                   `tools` 里查不到的校验目标（未注册/已下线）单独标注。
    """
    gaps: list[str] = []
    for cfg in skills:
        own = set(cfg.tool_names or [])
        if "validate_input" not in own:
            # 没绑 validate_input 的 skill 根本走不到「校验成功 → 待执行」这条链，
            # 它的缺口是**反方向**的（见 test_cross_skill_gap_scope_declaration）。
            continue
        for target in sorted(validation_targets):
            if target in own:
                continue
            tool = tools.get_tool(target)
            if tool is None:
                gaps.append(
                    f"{cfg.name} 校验 {target}（**未注册/已下线**，但 _VALIDATION_RULES 仍声明它可校验）"
                )
                continue
            if tool.read_only:
                continue  # 只读目标：空跑一轮后如实回答，无写副作用死角（适用域见文件头）
            gaps.append(
                f"{cfg.name} 可 validate_input({target}) 但该 skill 执行不了它"
                f"（Tool not found ⇒「已校验待执行」的写动作永不可达）"
            )
    return gaps


# ──────────────────────────────────────────────────────────────────────────────
# A5 守卫
# ──────────────────────────────────────────────────────────────────────────────


def test_validate_targets_are_registered_tools():
    """`_VALIDATION_RULES` 的每个 key 必须是**已注册**工具（防陈旧表指向已下线工具）。

    反例输入（红证 ⑤）：把已下线的 `processing_order_generate` 写回 `_VALIDATION_RULES` ⇒ 红。
    该工具类**仍在** `app/tools/processing_order_generate.py`，只是**不再注册**
    （issue #3917 产品决策）—— 所以「文件存在」不能当判据，必须比注册表。
    """
    from app.tools.registry import get_tool_registry

    registered = set(get_tool_registry().get_tool_names())
    assert len(registered) >= 30, f"注册表只解析出 {len(registered)} 个工具 —— 疑似解析失效（守卫会空转）"

    unregistered = sorted(t for t in validation_rule_targets() if t not in registered)
    assert not unregistered, (
        "`validate_input._VALIDATION_RULES` 声明了**已下线/未注册**的工具可校验：\n  "
        + "\n  ".join(unregistered)
        + "\n→ 校验会通过、执行必然 Tool not found（#3976 的形态）"
    )


def test_no_skill_validates_a_write_tool_it_cannot_execute():
    """**A5 核心不变式**：绑了 `validate_input` 的 skill，不得校验自己执行不了的写工具。

    这是「能校验 ≠ 能执行」之间缺失的那层守卫。**当前红**（存量真违规，见 PR body）。

    反例输入（红证 ①）：把 `order_create` 从 `order_skill.ORDER_TOOLS` 注释掉
    ⇒ `order` 变成「校验得了 order_create 却执行不了」⇒ 本用例必红。
    """
    from app.graph.skills.skill_registry import get_skill_registry
    from app.tools.registry import get_tool_registry

    skills = list(get_skill_registry().get_all())
    tools = get_tool_registry()

    binding_skills = [c for c in skills if "validate_input" in (c.tool_names or [])]
    assert len(binding_skills) >= 5, (
        f"只有 {len(binding_skills)} 个 skill 绑了 validate_input —— 绑定解析疑似失效（守卫会空转）"
    )

    gaps = cross_skill_validation_gaps(skills, tools, validation_rule_targets())
    assert not gaps, (
        f"A5 跨 skill 可达性缺口 {len(gaps)} 处 —— 「能校验但执行不了」的写工具死角：\n  "
        + "\n  ".join(gaps[:8])
        + (f"\n  …（共 {len(gaps)} 条，逐条缺口矩阵见 PR body 的证据表）" if len(gaps) > 8 else "")
        + "\n\n后果（#3976 线上实证 sess_202d55d49a254a10）：validate_input 成功 → 落"
          "「已校验待执行」→ 模型调那个写工具 → `Tool not found` → 空头承诺、订单永不落库。\n"
          "修法必须**机制级**（在 validate_input 或 skill 绑定层比对工具集），"
          "不得靠单点补工具（同类实例上百个，见 PR body 的独立 issue）。"
    )


def test_cross_skill_detector_fires_on_the_3976_shape():
    """**注入式红证**（红证 ②）：判据本身必须能红，且不得恒真。

    三种夹具（**与被测真值解耦**，永远有效）：

    1. `#3976` 的真实形状 —— `product` skill 上下文里校验 `order_create` ⇒ **必须报出**；
    2. 目标写工具**在**本 skill 工具集里（`order` 校验 `order_create`）⇒ **必须不报**
       （负例：证明判据不是恒红，R2）；
    3. 没绑 `validate_input` 的 skill（`data`）⇒ **必须不报**（适用域之外）。
    """
    from app.tools.registry import get_tool_registry

    tools = get_tool_registry()
    targets = {"order_create"}  # 只留一个目标，夹具最小化

    def _cfg(name: str, tool_names: list[str]) -> SkillConfig:
        return SkillConfig(name=name, domain=name, display_name=name, tool_names=tool_names)

    # ① #3976 形状：product skill 里校验 order_create
    gap_3976 = cross_skill_validation_gaps(
        [_cfg("product", ["validate_input", "product_manage"])], tools, targets)
    assert len(gap_3976) == 1 and "product" in gap_3976[0] and "order_create" in gap_3976[0], (
        f"判据对 #3976 的真实形状**没有报出**缺口 —— 这是一条恒绿断言（夹具结果：{gap_3976}）"
    )

    # ② 负例：目标在本 skill 工具集里 ⇒ 不报
    ok = cross_skill_validation_gaps(
        [_cfg("order", ["validate_input", "order_create"])], tools, targets)
    assert ok == [], f"判据对**合法**输入误红（目标已在本 skill 内）：{ok}"

    # ③ 适用域外：没绑 validate_input ⇒ 不报
    out_of_scope = cross_skill_validation_gaps(
        [_cfg("data", ["finance_api", "session_manage"])], tools, targets)
    assert out_of_scope == [], f"判据越出适用域（未绑 validate_input 的 skill 不应判红）：{out_of_scope}"


def test_cross_skill_gap_scope_declaration():
    """**适用域声明 + 反方向缺口登记**（R1：加一道门必须写清适用域 + 不适用域的负例）。

    本守卫**只**判「绑了 `validate_input` 却执行不了目标写工具」。两类**不适用域**各有负例：

    - **只读目标不判红**（无写副作用死角）；
    - **未绑 `validate_input` 的 skill 不判红** —— 反方向缺口（「有写工具但整个 skill 不走
      校验前置」）是**产品判断**（该 skill 该不该走确认链），不是可达性问题；
      把它混进同一判据会让本守卫变成永远红（§19.1），故只**登记打印**。

    反例输入：把判据放宽到全工具/全 skill ⇒ 本用例的两条负例立刻红（指出适用域被越界）。
    """
    from app.graph.skills.skill_registry import get_skill_registry
    from app.tools.registry import get_tool_registry

    skills = list(get_skill_registry().get_all())
    tools = get_tool_registry()

    # 负例 A：只读目标不在判红范围内
    read_only_names = sorted({t.name for t in tools.get_all_tools() if t.read_only})
    assert read_only_names, "注册表里没有只读工具 —— 解析失效"
    assert cross_skill_validation_gaps(
        [SkillConfig(name="x", domain="x", display_name="x", tool_names=["validate_input"])],
        tools, {read_only_names[0]},
    ) == [], f"只读目标 {read_only_names[0]} 被误判成写死角 —— 适用域被越界"

    # 负例 B：未绑 validate_input 的 skill 不在判红范围内（即使它执行不了那个写工具）
    assert cross_skill_validation_gaps(
        [SkillConfig(name="data", domain="data", display_name="data",
                     tool_names=["finance_api", "session_manage"])],
        tools, {"order_create"},
    ) == [], "未绑 validate_input 的 skill 被误判 —— 反方向缺口不得并入本判据（永远红风险）"

    # 反方向缺口的**登记**（不判红，只打印供后续登记 issue）
    unbounded: list[str] = []
    for cfg in skills:
        own = set(cfg.tool_names or [])
        if "validate_input" in own:
            continue
        writes = sorted(
            t for t in own
            if tools.get_tool(t) is not None and not tools.get_tool(t).read_only
        )
        if writes:
            unbounded.append(f"{cfg.name} 有写工具但未绑 validate_input：{'/'.join(writes)}")
    print("\n[A5 适用域外·登记不判红] 反方向缺口：\n  " + "\n  ".join(unbounded or ["（无）"]))


# ──────────────────────────────────────────────────────────────────────────────
# A10：CUSTOMER_ONLY_ROLES 单点化不变式
# ──────────────────────────────────────────────────────────────────────────────


def _customer_only_roles_definitions() -> list[tuple[str, set[str]]]:
    """全仓 `CUSTOMER_ONLY_ROLES = <字面量集合>` 的**定义点**（AST，不扫注释/字符串）。"""
    found: list[tuple[str, set[str]]] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        try:
            tree = _module_ast(path)
        except SyntaxError:  # pragma: no cover - 语法错的文件不属本守卫
            continue
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value:
                targets, value = [node.target], node.value
            if any(isinstance(t, ast.Name) and t.id == "CUSTOMER_ONLY_ROLES" for t in targets):
                found.append((str(path.relative_to(APP_DIR.parent)), _literal_str_set(value)))
    return found


def test_customer_only_roles_has_exactly_one_definition():
    """**A10 核心不变式**：`CUSTOMER_ONLY_ROLES` 全仓只许有**一处**定义。

    `app/tools/base.py` 的注释声称「在此声明单一语义源，chat.py 复用本常量」——
    实测全仓零 import（两份独立定义）。**当前红**（存量真违规：结构上已是两份）。
    注释与实际不符本身也是缺陷：它让下一个改角色集的人**以为改一处就够**。

    反例输入（红证 ④）：删掉/改掉任一侧定义，或新增第三处 ⇒ 定义数 ≠ 1 ⇒ 必红。
    """
    defs = _customer_only_roles_definitions()
    assert defs, "全仓找不到 CUSTOMER_ONLY_ROLES 定义 —— 解析失效（守卫会空转）"
    detail = "\n  ".join(f"{path} = {sorted(vals)}" for path, vals in defs)

    assert len(defs) == 1, (
        f"`CUSTOMER_ONLY_ROLES` 有 {len(defs)} 处定义（不变式：恰好 1 处）：\n  {detail}\n"
        f"→ 两份定义今天恰好相等，明天任一侧加一个角色就**静默分叉**："
        f"「工具层认它是顾客、API 层认它是员工」的权限口径分裂。\n"
        f"→ 修法：`api/chat.py` 反向 import `tools/base.py` 的常量（`app/tools/**` 不得反向 import "
        f"`app/api/**`，故单一源必须落在 tools 层 —— 与既有注释声明的方向一致），"
        f"并删掉 `base.py` 那句与事实不符的「chat.py 复用本常量」。"
    )


def test_customer_only_roles_branches_agree_at_runtime():
    """A10 附带判据：两份定义**今天**的取值也必须相等（锁「分叉的后果」这一面）。

    与上一条的分工：上一条锁**结构**（只许一处），本条锁**取值**（两处是否等价）。
    若有人只删注释、没真单点化，本条挡住「两份不等」这一半风险。

    反例输入（红证 ④）：把 `chat.py` 的 set 改成含第三个角色 ⇒ 两侧不等 ⇒ 必红。
    """
    from app.api.chat import CUSTOMER_ONLY_ROLES as chat_roles
    from app.tools.base import CUSTOMER_ONLY_ROLES as tools_roles

    assert set(tools_roles) == set(chat_roles), (
        f"C 端角色集两份定义**取值已分叉**：\n"
        f"  app/tools/base.py = {sorted(tools_roles)}\n"
        f"  app/api/chat.py   = {sorted(chat_roles)}\n"
        f"→ 工具层与 API 层的顾客身份判定不一致 = 权限口径分裂。"
    )


def test_customer_only_roles_import_direction_claim_is_true():
    """A10 附带判据：`base.py` 那句「chat.py 复用本常量」的**声明必须为真**。

    声明的形态判据（不靠中文措辞）：`api/chat.py` 里必须**真的**有从
    `app.tools.base` 取 `CUSTOMER_ONLY_ROLES` 的 import；否则注释是**假真值**
    （`migao-dev-flow` §19.1「注释漂移 = 假绿来源」）—— 要么让它为真、要么撤回 claim。

    反例输入：保持两份独立定义（= 当前状态）⇒ 本用例必红。
    """
    imports: list[str] = []
    for node in ast.walk(_module_ast(CHAT_PY)):
        if isinstance(node, ast.ImportFrom) and node.module == "app.tools.base":
            imports.extend(alias.name for alias in node.names)

    assert "CUSTOMER_ONLY_ROLES" in imports, (
        "`app/api/chat.py` 没有从 `app.tools.base` 导入 `CUSTOMER_ONLY_ROLES` —— "
        "而 `base.py` 的注释声称「chat.py 复用本常量」（假真值）。\n"
        "→ 二选一：① 真单点化（chat.py import tools 层常量）；"
        "② 撤回 `base.py` 那句 claim，并如实登记两份定义的同步责任。"
    )