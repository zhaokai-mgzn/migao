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

⇒ **「能校验」与「能执行」之间原本没有任何一层在比对**。skills 可以（也会）对**自己执行不了**
的写工具完成 `validate_input` 并落地「已校验待执行」状态（`base_skill` 在
`validate_input` 成功时落 `pending_validated_input`），随后模型调那个写工具 →
`Tool not found`。线上实证 **#3976**（sess_202d55d49a254a10）：B 端在 `product` skill 内
`validate_input(order_create)` + 发确认卡，点卡后 `[product] Tool not found: order_create`
→ 最终回复「已转到订单流程为您落单…请稍候，我这就提交」而 **orders 表无新订单**。

**本文件补的就是那层守卫**：`validate_input` 的每个目标必须是**当前 skill 执行得了**的写工具；
实测存量 **126** 处死角（8 个 skill），按 `A5_GAP_BASELINE` 登记为**存量账本**
（锚 `c0be8e35`，只许缩短、新增阻塞），机制修复跟踪 **#4017**。

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
| `test_no_skill_validates_a_write_tool_it_cannot_execute` | 把 `order_create` 从 `order_skill.ORDER_TOOLS` 注释掉 ⇒ `order` 的缺口集不再是账本里那 16 个 |
| `test_cross_skill_baseline_detects_growth_and_new_skills` | 注入式：账本外多一处死角 / 账本外的新 skill 带缺口 ⇒ 必报；存量原样 ⇒ 不报（负例） |
| `test_cross_skill_detector_fires_on_the_3976_shape` | 注入式：`product` skill 上下文 + 目标 `order_create` |
| `test_validate_targets_are_registered_tools` | 在 `_VALIDATION_RULES` 里加一个已下线工具名 |
| `test_customer_only_roles_has_exactly_one_definition` | 给 `chat.py` 的 set 加第三个角色（两个定义文件） |
| `test_customer_only_roles_branches_agree_at_runtime` | 把 `chat.py` 的 set 改成含第三个角色 |
| `test_customer_only_roles_import_direction_claim_is_true` | 保持两份独立定义（= 当前状态）⇒ 红 |

## 存量账本 vs 严格守卫（本文件的两类断言，别混）

| 判据 | 形态 | 当前 |
|---|---|---|
| A5 跨 skill 可达性（**静态矩阵**） | **存量账本**（`A5_GAP_BASELINE`，锚 `c0be8e35`，126 条 / 8 skill；**只许缩短 + 新增阻塞**） | 账本内**绿**（skill 仍未绑那些工具 ⇒ 矩阵条目不会因机制修复而消失） |
| A5 越界拦截（**运行时机制**） | **严格，无基线**（`test_every_registered_gap_is_rejected_at_runtime`：账本里每一处死角逐条断言被 `cross_skill_target` 拦下） | **绿**（#4017 机制修复落地后） |
| A10 单点化三条 | **严格，无基线**（命中的是必须修的真违规） | **绿**（#4018 合入后单点化已生效；落地当时为红 —— 见下方锚定记录） |

> ⚠️ **语义调整记录（issue #4079，2026-09-18）**：A5 原来只有**静态矩阵 + 账本放行** ——
> 账本里的 126 条是"**登记了但拦不住**"的存量债务。机制修复（`validate_input` 执行期比对
> 校验域与执行域，`target_tool ∉ 当前 skill 可执行集` ⇒ `success=False,
> error="cross_skill_target"`）+ 本文件新增的**运行时逐条断言**之后：
>   · 账本**不删不扩**（它是"这些 skill 还没绑那些工具"的**事实登记**，不是放行许可）；
>   · 每条登记的死角**必须被运行时拦下**（新用例逐条断言，含 injection 负例与域内负例）；
>   · 新 skill / 新写工具引入的死角**不在账本里 ⇒ 直接红**（原判据保留）。
> ⇒ 强度**只升不降**：改前=「记录并放行」，改后=「记录 + 逐条必须被拦」。
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


def cross_skill_gap_matrix(skills, tools, validation_targets) -> dict[str, frozenset[str]]:
    """`{skill: {它校验得了却执行不了的写工具}}` —— 账本比对用的**结构**形态。

    与 `cross_skill_validation_gaps` 的分工：那个给人读（字符串清单），
    这个给**账本**比对（精确到「缺哪一个工具」，才能判「新增」与「销账」）。
    两者共用同一份真值来源（skill 工具集 / 注册表 `read_only` / `_VALIDATION_RULES`）。
    """
    matrix: dict[str, frozenset[str]] = {}
    for cfg in skills:
        own = set(cfg.tool_names or [])
        if "validate_input" not in own:
            continue  # 适用域之外（反方向缺口只登记，见 scope declaration 用例）
        matrix[cfg.name] = frozenset(
            t for t in validation_targets
            if t not in own
            and tools.get_tool(t) is not None
            and not tools.get_tool(t).read_only
        )
    return matrix


# ──────────────────────────────────────────────────────────────────────────────
# A5 存量账本（**锚定 SHA + 逐条逐名**，只许缩短；新增阻塞）
# ──────────────────────────────────────────────────────────────────────────────
#
# ⚠️ 这不是「永久豁免」，是**已被登记的存量事实**：
#   · 锚定：`origin/main` @ **d5bca241**（2026-09-18 由 issue #4196 **重新锚定**：
#     126 条 → **140** 条，逐条可复算；原锚 c0be8e35 的 126 条为 #4012 落地时的真值）；
#   · 合计：**140** 条 / **8** 个绑了 `validate_input` 的 skill
#     （126 存量 + **14 条由 #4196 恢复加工单工具引入**，见下方「#4196 重新锚定」）；
#   · **语义（issue #4079 调整后）**：账本 = 「这些 skill 还没绑那些写工具」的**事实登记**，
#     **不是放行许可** —— 机制修复后每一处死角都由 `validate_input` 的域闸门在**运行时拦下**
#     （`test_every_registered_gap_is_rejected_at_runtime` 逐条断言）；
#   · 账本只许缩短 —— 条目在真值中不再命中时，守卫会打印 `SHOULD SHRINK` 要求移除；
#   · 新 skill / 新写工具引入的死角**不在账本里 ⇒ 直接红**（`test_no_skill_validates_…` 的 fail 分支）；
#   · 销账跟踪：**#4017**（机制修复 —— 已由 #4079 落地：域比对 + 越界拦截）。
#
# ⚠️ **#4196 重新锚定（126 → 140）——为什么这不是「新增债务靠登记销声」**：
#   · 事实链（每一环都有别的门禁兜着，不是自选动作）：
#     ① 产品裁定恢复加工单三工具（#4196）⇒ `registry` 重新注册 `processing_order_generate`
#        / `processing_order_update`（写工具）；
#     ② F6（`test_validation_rules_invariants::test_every_write_action_is_deterministically_gated`）
#        要求「已登记可写 ⇒ `_VALIDATION_RULES` 必须有规则」⇒ 两块规则恢复；
#     ③ 那张表是**域无关**的（A5 的前提，未变）⇒ 校验目标多了 2 个，而只有 `order` skill
#        绑了这两个工具 ⇒ 其余 7 个绑 `validate_input` 的 skill 各 +2 处死角。
#   · 判据面**没有放宽**：新增的 14 条与存量同族（「工具只被 1~2 个 skill 绑定」的架构事实），
#     且**逐条被运行时域闸门拦下** —— `test_every_registered_gap_is_rejected_at_runtime`
#     对**活真值**全量比对（skill × `_VALIDATION_RULES` 目标），不读账本、不因登记而跳过；
#   · 反向选择更坏：不注册工具 = 违背 #4196 的产品裁定；不恢复规则 = F6 红（fail-closed
#     会拦死合法调用）；把规则藏到 AST 读不到的位置 = 对守卫做**静默规避**（最坏形态）。
#   · **窄例外**（本账本**只许缩短**不因本次重新锚定而改变）：锚点前移**仅**允许在
#     「产品决策把既有工具恢复进某 skill」这一形态下发生，且必须同时满足 ——
#     ① 新增条目**逐条逐名**写进 `A5_REANCHOR_ADDITIONS`；
#     ② 逐条过 `test_reanchored_additions_trace_to_a_real_product_change`（目标**已注册** +
#        **写工具** + **至少被一个 skill 绑定** ⇒ 增量可追溯到真实产品变更）；
#     ③ 计数对账（账本总数 − 增量 == 旧锚条数）。其余一切「新增死角」仍**直接红**。
#   · 销账方向（这 14 条落在 **#4017** 的结构性修复范围内）：加工单写工具若被更多 skill
#     绑定、或 `validate_input` 的域闸门改为**前置**（目标不再进全局限定表），这 14 条随真值
#     消失 ⇒ 守卫打印 `SHOULD SHRINK` 要求移除。
#
# 复算命令（把下面的集合与真值 diff 出来）：
#   backend/ai-agent-service/.venv/bin/python -m pytest \
#     backend/ai-agent-service/tests/test_skill_tool_reachability.py -q -s -k shrink
A5_GAP_BASELINE: dict[str, frozenset[str]] = {
    # aftersales：自己工具集 7 个 → 死角 16 个
    "aftersales": frozenset({
        "aftersale_create", "category_manage", "customer_manage", "employee_manage",
        "finance_api", "inventory_manage", "notification_manage", "order_create",
        "processing_item_manage",
        "processing_order_generate", "processing_order_update",  # #4196 恢复接入
        "product_manage", "product_processing_item_manage",
        "product_update", "role_manage", "session_manage", "settings_manage", "sku_update",
    }),
    # customer：自己工具集 5 个 → 死角 17 个
    "customer": frozenset({
        "aftersale_create", "after_sales_manage", "category_manage", "employee_manage",
        "finance_api", "inventory_manage", "notification_manage", "order_create",
        "order_manage", "processing_item_manage",
        "processing_order_generate", "processing_order_update",  # #4196 恢复接入
        "product_manage",
        "product_processing_item_manage", "product_update", "role_manage",
        "session_manage", "settings_manage", "sku_update",
    }),
    # customer_aftersales：自己工具集 6 个 → 死角 17 个
    "customer_aftersales": frozenset({
        "after_sales_manage", "category_manage", "customer_manage", "employee_manage",
        "finance_api", "inventory_manage", "notification_manage", "order_create",
        "order_manage", "processing_item_manage",
        "processing_order_generate", "processing_order_update",  # #4196 恢复接入
        "product_manage",
        "product_processing_item_manage", "product_update", "role_manage",
        "session_manage", "settings_manage", "sku_update",
    }),
    # customer_order：自己工具集 10 个 → 死角 17 个
    "customer_order": frozenset({
        "aftersale_create", "after_sales_manage", "category_manage", "customer_manage",
        "employee_manage", "finance_api", "inventory_manage", "notification_manage",
        "order_manage", "processing_item_manage",
        "processing_order_generate", "processing_order_update",  # #4196 恢复接入
        "product_manage",
        "product_processing_item_manage", "product_update", "role_manage",
        "session_manage", "settings_manage", "sku_update",
    }),
    # order：自己工具集 9 个 → 死角 16 个
    "order": frozenset({
        "aftersale_create", "after_sales_manage", "category_manage", "customer_manage",
        "employee_manage", "finance_api", "inventory_manage", "notification_manage",
        "processing_item_manage", "product_manage", "product_processing_item_manage",
        "product_update", "role_manage", "session_manage", "settings_manage", "sku_update",
    }),
    # product：自己工具集 12 个 → 死角 11 个
    "product": frozenset({
        "aftersale_create", "after_sales_manage", "customer_manage", "employee_manage",
        "finance_api", "notification_manage", "order_create", "order_manage",
        "processing_order_generate", "processing_order_update",  # #4196 恢复接入
        "role_manage", "session_manage", "settings_manage",
    }),
    # settings：自己工具集 4 个 → 死角 16 个
    "settings": frozenset({
        "aftersale_create", "after_sales_manage", "category_manage", "customer_manage",
        "employee_manage", "finance_api", "inventory_manage", "order_create",
        "order_manage", "processing_item_manage",
        "processing_order_generate", "processing_order_update",  # #4196 恢复接入
        "product_manage",
        "product_processing_item_manage", "product_update", "role_manage",
        "session_manage", "sku_update",
    }),
    # staff：自己工具集 5 个 → 死角 16 个
    "staff": frozenset({
        "aftersale_create", "after_sales_manage", "category_manage", "customer_manage",
        "finance_api", "inventory_manage", "notification_manage", "order_create",
        "order_manage", "processing_item_manage",
        "processing_order_generate", "processing_order_update",  # #4196 恢复接入
        "product_manage",
        "product_processing_item_manage", "product_update", "settings_manage",
        "session_manage", "sku_update",
    }),
}

# ── #4196 锚点前移的**增量登记**（窄例外；逐条逐名，须过机器核验）───────────────
# 唯一允许锚点前移的形态：**产品决策把既有工具恢复进某 skill**（工具回到注册表 ⇒ F6 要求
# 恢复其 `_VALIDATION_RULES` ⇒ **域无关**的校验目标表新增目标 ⇒ 未绑该工具的 skill 各 +2）。
# 逐条逐名登记「skill → 新增的目标写工具」，并由
# `test_reanchored_additions_trace_to_a_real_product_change` 逐条核三条正当性
# （已注册 / 是写工具 / 至少被一个 skill 绑定）——**防这次成为以后「顺手 re-anchor」的口子**。
A5_REANCHOR_ADDITIONS: dict[str, frozenset[str]] = {
    "aftersales": frozenset({"processing_order_generate", "processing_order_update"}),
    "customer": frozenset({"processing_order_generate", "processing_order_update"}),
    "customer_aftersales": frozenset({"processing_order_generate", "processing_order_update"}),
    "customer_order": frozenset({"processing_order_generate", "processing_order_update"}),
    "product": frozenset({"processing_order_generate", "processing_order_update"}),
    "settings": frozenset({"processing_order_generate", "processing_order_update"}),
    "staff": frozenset({"processing_order_generate", "processing_order_update"}),
}

# 旧锚（#4012 落地时）的条数 —— 只作**计数对账**用（增量 = 总数 − 旧锚数），不复制整份旧集合
A5_BASELINE_COUNT_PRE_4196 = 126


def unjustified_reanchor_additions(additions, tools, skills) -> list[str]:
    """**判据内核**（纯函数）：锚点前移的每个新增条目必须可追溯到**真实产品变更**。

    三条（缺一即报出，逐条给理由）：
      ① `target` **已注册**（`tools.get_tool(target)` 非 None）——「既有工具」；
      ② `target` 是**写工具**（`read_only=False`）——只读目标不进 A5 矩阵，登记它没有意义；
      ③ `target` **至少被一个 skill 绑定**（`cfg.tool_names`）——「恢复**进**某个 skill」的判据；
         若一个工具谁都没绑，那就是真的新死角，**不许**靠登记销声。
    """
    bound = {t for cfg in skills for t in (cfg.tool_names or [])}
    bad: list[str] = []
    for skill, targets in sorted(additions.items()):
        for target in sorted(targets):
            tool = tools.get_tool(target)
            if tool is None:
                bad.append(f"{skill} → {target}：**未注册**（不是「既有工具」恢复，是凭空死角）")
            elif tool.read_only:
                bad.append(f"{skill} → {target}：**只读工具**（不进 A5 矩阵，登记无效）")
            elif target not in bound:
                bad.append(
                    f"{skill} → {target}：**没有任何 skill 绑定它**（不是「恢复进某 skill」"
                    f"⇒ 真新增死角，不许靠登记销声）"
                )
    return bad


# ──────────────────────────────────────────────────────────────────────────────
# A5 守卫
# ──────────────────────────────────────────────────────────────────────────────


def test_validate_targets_are_registered_tools():
    """`_VALIDATION_RULES` 的每个 key 必须是**已注册**工具（防陈旧表指向已下线工具）。

    反例输入（红证 ⑤）：把**未注册**的工具名（如已退场的 `human_handoff`）写回
    `_VALIDATION_RULES` ⇒ 红 —— 工具类文件仍在 `app/tools/`，但**不在注册表**里；
    所以「文件存在」不能当判据，必须比注册表。
    ⚠️ 本条与 #4196 的反转配套：`processing_order_generate` 曾是该红证的实例（#3917 下线期
    间「文件在、未注册」），#4196 恢复接入后它**已回到注册表** ⇒ 不再是红证实例，
    换成「类在但未注册」的通用形态（`human_handoff` 是当前实例）。
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
    """**A5 核心不变式（存量账本 + 新增阻塞）**：绑了 `validate_input` 的 skill，
    不得校验自己执行不了的写工具 —— **存量按 `A5_GAP_BASELINE` 放行，新增即红**。

    本用例只判**静态矩阵的增量**（"有没有新的死角"）。**死角逐条被拦**由下面
    `test_every_registered_gap_is_rejected_at_runtime` 断言（#4079 机制修复后新增）——
    两条分工：这条防**新增**，那条证**存量已被拦**。

    ## 为什么保留账本（而不是把 126 条判红）

    `ai-agent-service unit tests` 是**必需检查**（`branches/main/protection` 的 `contexts` 含它）。
    126 处死角的**根因**是"19 个写工具各只被 1~2 个 skill 绑定"的架构事实，不是个别 skill 漏绑；
    把它们判红只会挡住所有人的 PR，而**运行时早已被域闸门拦下**（#4079 之后）。
    ⇒ 账本保留为**事实登记**（防新增），拦截强度由运行时断言承担。

    ## 账本的语义（**不是永久豁免**，三条硬约束）

    1. **锚定 SHA**：`A5_GAP_BASELINE` 锚定 `origin/main` @ `c0be8e35`，逐条逐名登记（126 条 / 8 skill）；
    2. **只许缩短**：清单里的条目一旦在真值里**不再命中** ⇒ 打印 `SHOULD SHRINK` 要求移除
       （本 PR 不 fail 这一项：删条目属「收紧」，与「别人修好了却挡他的 PR」是两件事 ——
       同 `case_trust_gate.py` 对基线的既有口径）；
    3. **新增阻塞**：新 skill / 新写工具引入的死角**不在账本里 ⇒ 红**（本用例的 fail 分支）。

    ## 修复 issue（回填）

    **#4017**（机制修复，由 **#4079** 落地）—— `validate_input` 执行期读当前 skill 的可执行
    工具集，`target_tool ∉ 该集合` ⇒ `success=False, error="cross_skill_target"` + suggestion。
    账本的 126 条**不再靠"放行"活着**：`test_every_registered_gap_is_rejected_at_runtime`
    逐条断言它们被拦下（强度只升不降）。

    反例输入（红证 ①）：把 `order_create` 从 `order_skill.ORDER_TOOLS` 注释掉
    ⇒ `order` 的缺口集**不再是账本里的那 16 个**（多出 `order_create`）⇒ 必红。
    """
    from app.graph.skills.skill_registry import get_skill_registry
    from app.tools.registry import get_tool_registry

    tools = get_tool_registry()
    current = cross_skill_gap_matrix(list(get_skill_registry().get_all()), tools,
                                     validation_rule_targets())
    assert current, "缺口矩阵为空 —— 解析疑似失效（守卫会空转，账本就变成空气）"

    regressions: list[str] = []
    for skill, gaps in sorted(current.items()):
        allowed = A5_GAP_BASELINE.get(skill, frozenset())
        if skill not in A5_GAP_BASELINE:
            regressions.append(
                f"{skill} 是**新增**的 validate_input 绑定 skill，但账本里没有它 "
                f"⇒ 不许带缺口进入（现有缺口 {len(gaps)} 个：{sorted(gaps)[:4]}…）"
            )
            continue
        extra = sorted(gaps - allowed)
        if extra:
            regressions.append(
                f"{skill} 新增了 {len(extra)} 处死角（不在账本里）：{extra}\n"
                f"      → 修法：要么让这些工具在该 skill 内可达，要么走 #4017 的机制修复 —— "
                f"**不得**把它们加进账本（账本只许缩短）。"
                f"\n      唯一例外（窄例外）：**产品决策把既有工具恢复进某个 skill**（工具回到注册表 ⇒ "
                f"F6 要求恢复其规则 ⇒ 全局限定表新增目标）——那是真值变化，须在同一 PR 里"
                f"重新锚定账本（新 SHA + 新计数 + 逐条被运行时拦下的证据），且逐条登记进 "
                f"`A5_REANCHOR_ADDITIONS` 并过 `test_reanchored_additions_trace_to_a_real_"
                f"product_change`（已注册 + 写工具 + 至少被一个 skill 绑定）。"
            )

    shrunk = {
        skill: sorted(A5_GAP_BASELINE[skill] - current.get(skill, frozenset()))
        for skill in A5_GAP_BASELINE
        if A5_GAP_BASELINE[skill] - current.get(skill, frozenset())
    }
    if shrunk:
        print(
            "\n[A5 账本 SHOULD SHRINK] 以下条目已在真值中不再命中，请从 `A5_GAP_BASELINE` 移除"
            "（账本只许缩短；本守卫不因『未删』而红 —— 删条目属收紧，不属于本次回归）：\n  "
            + "\n  ".join(f"{s}: {v}" for s, v in sorted(shrunk.items()))
        )

    total_now = sum(len(g) for g in current.values())
    total_base = sum(len(v) for v in A5_GAP_BASELINE.values())
    assert not regressions, (
        f"A5 跨 skill 可达性**新增**缺口（存量 {total_base} 条按账本放行；当前 {total_now} 条）：\n  "
        + "\n  ".join(regressions)
        + "\n\n后果（#3976 线上实证 sess_202d55d49a254a10）：validate_input 成功 → 落"
          "「已校验待执行」→ 模型调那个写工具 → `Tool not found` → 空头承诺、订单永不落库。\n"
          "修法必须**机制级**（见 #4017），不得靠单点补工具。"
    )


def test_reanchored_additions_trace_to_a_real_product_change():
    """**锚点前移的窄例外必须可机器核**（#4196 立范式，防以后「顺手 re-anchor」）。

    三条硬条件（逐条对**活真值**算，见 `unjustified_reanchor_additions`）：新增条目的目标
    必须 ① 已注册 ② 写工具 ③ 至少被一个 skill 绑定 —— 即增量可追溯到**真实产品变更**
    （本次 = #4196 恢复加工单三工具进 order skill），不是凭空长出来的死角。

    另核两条一致性：
      · **逐条逐名**：增量登记里的每条都必须**确实在 `A5_GAP_BASELINE` 里**（登记与账本不得分叉）；
      · **计数对账**：增量条数 == 账本总数 − 旧锚条数（126）——只改数字不改逐条登记会被这条拦住。
    """
    from app.graph.skills.skill_registry import get_skill_registry
    from app.tools.registry import get_tool_registry

    tools = get_tool_registry()
    skills = list(get_skill_registry().get_all())
    assert skills, "skill registry 为空 —— 判据会空转（fail-closed）"

    bad = unjustified_reanchor_additions(A5_REANCHOR_ADDITIONS, tools, skills)
    assert bad == [], (
        "锚点前移的增量里有条目**追溯不到真实产品变更**（① 已注册 ② 写工具 ③ 至少一个 skill 绑定）：\n  "
        + "\n  ".join(bad)
        + "\n→ 账本只许缩短；锚点前移是**窄例外**（仅「产品决策把既有工具恢复进某 skill」），"
          "不得当成「新增死角可以顺手登记」的口子。"
    )

    not_in_ledger = sorted(
        f"{skill} → {target}"
        for skill, targets in A5_REANCHOR_ADDITIONS.items()
        for target in targets
        if target not in A5_GAP_BASELINE.get(skill, frozenset())
    )
    assert not_in_ledger == [], (
        "增量登记与账本分叉（这些条目登记了却不在 `A5_GAP_BASELINE` 里）：\n  "
        + "\n  ".join(not_in_ledger)
    )

    added = sum(len(v) for v in A5_REANCHOR_ADDITIONS.values())
    total = sum(len(v) for v in A5_GAP_BASELINE.values())
    assert total - added == A5_BASELINE_COUNT_PRE_4196, (
        f"计数对账失败：账本共 {total} 条 − 增量 {added} 条 = {total - added}，"
        f"而旧锚（#4012）记录为 {A5_BASELINE_COUNT_PRE_4196} 条 —— 说明账本被改动的部分"
        f"不止「逐条登记的增量」（只改数字/顺手加条目都会被这条拦住）"
    )


class TestReanchorJustificationIsNotVacuous:
    """**:red_circle: 红证 + 负例**：正当性判据必须能报，也必须能不误报。"""

    def _tools(self):
        from app.tools.registry import get_tool_registry

        return get_tool_registry()

    def _skills(self):
        from app.graph.skills.skill_registry import get_skill_registry

        return list(get_skill_registry().get_all())

    def test_negative_real_additions_are_not_reported(self):
        """负例：本次真实的 14 条 ⇒ **必须不报**（防恒红，同 R2）。"""
        assert unjustified_reanchor_additions(
            A5_REANCHOR_ADDITIONS, self._tools(), self._skills()
        ) == []

    def test_detector_reports_an_unbound_tool(self):
        """红证 ①：塞一个**没有任何 skill 绑定**的工具（真新增死角的形态）⇒ 必报。"""
        injected = {"order": frozenset({"human_handoff"})}
        bad = unjustified_reanchor_additions(injected, self._tools(), self._skills())
        assert bad, "「谁都没绑」的工具被当增量放行 ⇒ 窄例外变成任意口子"
        assert any("没有任何 skill 绑定" in b or "未注册" in b for b in bad), bad

    def test_detector_reports_a_read_only_and_a_nonexistent_tool(self):
        """红证 ②③：只读目标（登记无效）与不存在的工具名（凭空死角）⇒ 各必报。"""
        read_only = unjustified_reanchor_additions(
            {"order": frozenset({"processing_order_query"})}, self._tools(), self._skills()
        )
        assert any("只读工具" in b for b in read_only), read_only

        ghost = unjustified_reanchor_additions(
            {"order": frozenset({"ghost_tool_never_registered"})}, self._tools(), self._skills()
        )
        assert any("未注册" in b for b in ghost), ghost


def test_cross_skill_baseline_detects_growth_and_new_skills():
    """**注入式红证**：账本判据必须能报「增长」与「新 skill」，且不误报存量。

    三种夹具（与被测真值解耦，永远有效）：
      1. 存量**原样** ⇒ 不报（证明不是恒红）；
      2. `order` 多出一处死角（= 红证 ① 的抽象形态）⇒ **必须报**；
      3. 账本里没有的新 skill 带缺口 ⇒ **必须报**。
    """
    base = {"order": frozenset({"aftersale_create"}), "product": frozenset()}
    same = {"order": frozenset({"aftersale_create"}), "product": frozenset()}
    grown = {"order": frozenset({"aftersale_create", "order_create"}), "product": frozenset()}
    new_skill = {**same, "brand_new": frozenset({"order_create"})}

    def _regressions(current: dict) -> list[str]:
        out: list[str] = []
        for skill, gaps in sorted(current.items()):
            allowed = base.get(skill, frozenset())
            if skill not in base:
                out.append(f"new:{skill}")
            elif gaps - allowed:
                out.append(f"grown:{skill}:{sorted(gaps - allowed)}")
        return out

    assert _regressions(same) == [], "账本判据对**存量原样**误红"
    assert _regressions(grown) == ["grown:order:['order_create']"], "账本判据漏报增长"
    assert _regressions(new_skill) == ["new:brand_new"], "账本判据漏报新 skill"


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
# A5 机制（issue #4079 / #4017）：校验域 vs **执行域** —— 越界必须被拦
# ──────────────────────────────────────────────────────────────────────────────
#
# 事实链（三条，缺一条下面任何断言都可能是空跑）：
#   ① skill 回合的可执行工具集 = `create_skill_registry(cfg.tool_names)` 造出的 registry
#      （`prepare_turn` 用**同一个对象** `get_langchain_tools()` 绑定给模型）；
#   ② 该工厂把它登记进 `app.tools.registry` 的执行域（ContextVar，`get_tool_scope()`）；
#   ③ `ValidateInputTool.execute` 执行期读 ②，`target_tool ∉ 域` ⇒ `cross_skill_target`。


def validation_rule_actions() -> dict[str, str]:
    """`{target_tool: 一个**已登记**的 action}` —— 域比对的前置（action 无规则会走更早的分支）。

    AST 取真值（不是正则扫源码）：与 `validation_rule_targets()` 同一份解析口径。
    """
    rules = _find_assignment(_module_ast(VALIDATE_INPUT_PY), "_VALIDATION_RULES")
    assert isinstance(rules, ast.Dict), "_VALIDATION_RULES 不再是字典字面量 —— 请同步本守卫"
    out: dict[str, str] = {}
    for key, value in zip(rules.keys, rules.values):
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            continue
        assert isinstance(value, ast.Dict), f"{key.value} 的规则不是字典字面量 —— 解析失效"
        actions = [a.value for a in value.keys
                   if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        assert actions, f"{key.value} 没有解析出任何 action —— 守卫会空转（fail-closed）"
        out[key.value] = actions[0]
    assert out, "_VALIDATION_RULES 解析为空 —— 守卫会空转（fail-closed）"
    return out


#: 域外目标用的最小参数：非空即可（域比对在字段校验**之前**，见 `validate_input.execute`）
_PROBE_PARAMS = {"probe": 1}
#: 域内目标用**合法**参数（R2 负例要证明"没拦掉原本合法的调用"，必须能真通过校验）
_VALID_ORDER_PARAMS = {
    "customer_name": "张三",
    "customer_phone": "13800138000",
    "items": [{"product_id": "p1", "quantity": 1}],
}


def _admin_ctx():
    from app.tools.base import ToolContext
    return ToolContext(tenant_id=1, user_id="u_guard", session_id="sess_guard", role="admin")


async def test_every_registered_gap_is_rejected_at_runtime():
    """**A5 机制不变式（越界必须被拦）**：账本登记的每一处死角，运行时都必须被拒。

    判据（对**活真值**逐条算，不依赖账本的"放行"语义）：

      · 对每个绑了 `validate_input` 的 skill：用生产同一工厂
        `create_skill_registry(cfg.tool_names)` 登记执行域；
      · 对 `_VALIDATION_RULES` 的**每个**目标工具：
          - 目标 ∉ 该 skill 工具集 ⇒ `success is False` 且 `error == "cross_skill_target"` + suggestion；
          - 目标 ∈ 该 skill 工具集 ⇒ **不得**被域闸门拒（`error != "cross_skill_target"`）。

    强度（R4）：改前账本里的 126 条只是"**登记并放行**"（静态矩阵），现在**逐条断言被拦**。
    fail-closed（防"扫不到就通过"）：账本里的每个 skill 必须在活注册表里存在（幽灵即红）；
    且断言实际比对次数 == `绑 validate_input 的 skill 数 × 目标数`（**没有静默跳过**）。
    """
    from app.graph.skills.skill_registry import get_skill_registry
    from app.graph.skills.base_skill import create_skill_registry
    from app.tools.base import ToolContext  # noqa: F401  （保持与 `_admin_ctx` 同源）
    from app.tools.registry import get_tool_scope
    from app.tools.validate_input import ValidateInputTool

    skills = list(get_skill_registry().get_all())
    assert skills, "skill 注册表为空 —— 判据会空转（fail-closed）"
    live_names = {cfg.name for cfg in skills}
    ghosts = sorted(set(A5_GAP_BASELINE) - live_names)
    assert not ghosts, (
        f"账本里的 skill 在活注册表里不存在：{ghosts} —— 账本指向幽灵（判据会静默失去对象）"
    )

    targets = validation_rule_actions()
    tool = ValidateInputTool()
    ctx = _admin_ctx()

    checked = 0
    blocked = 0
    failures: list[str] = []
    for cfg in skills:
        own = set(cfg.tool_names or [])
        if "validate_input" not in own:
            continue  # 适用域之外（反方向缺口只登记，见 scope declaration 用例）
        create_skill_registry(list(cfg.tool_names))  # 生产同一工厂 → 登记执行域
        assert get_tool_scope() is not None, (
            f"{cfg.name}：工厂没有登记执行域 —— 域闸门会静默失效（#4079 的事实链断在第 ② 环）"
        )
        for target, action in sorted(targets.items()):
            checked += 1
            params = _VALID_ORDER_PARAMS if target == "order_create" else _PROBE_PARAMS
            res = await tool.execute(ctx, target_tool=target, target_action=action, params=params)
            if target in own:
                if res.error == "cross_skill_target":
                    failures.append(
                        f"{cfg.name} **域内**目标 {target} 被域闸门误拒（R2 误伤合法调用）"
                    )
                continue
            blocked += 1
            if res.success or res.error != "cross_skill_target":
                failures.append(
                    f"{cfg.name} 的域外目标 {target} 没被拦下：success={res.success} error={res.error!r}"
                    f" ⇒ 「能校验但执行不了」的死角又回来了（后果链见 #3976）"
                )
            elif not (res.suggestion or "").strip():
                failures.append(f"{cfg.name} 的域外目标 {target} 被拒但**没有 suggestion**（R5）")

    expect = sum(1 for cfg in skills if "validate_input" in set(cfg.tool_names or [])) * len(targets)
    assert checked == expect, (
        f"实际比对 {checked} 次，应为 {expect} 次 —— 有静默跳过（判据不得「扫不到就通过」）"
    )
    assert blocked > 0, (
        "活真值里一处域外死角都没有 ⇒ 本判据变成空跑；请确认账本/A5_GAP_BASELINE 是否已过期"
    )
    print(f"\n[A5 运行时域闸门] 比对 {checked} 对，其中域外 {blocked} 处（账本登记 "
          f"{sum(len(v) for v in A5_GAP_BASELINE.values())} 条）全部被拦下")
    assert not failures, "A5 域闸门未按预期工作：\n  " + "\n  ".join(failures)


async def test_cross_skill_gate_rejects_out_of_domain_and_passes_in_domain():
    """**注入式红证 + R2 阴性负例**（判据必须能红、也必须不误红）。

    夹具与被测真值解耦（用工厂造域，不依赖具体 skill 的绑定现状）：

      ① **#3976 形状**：`product` 域（工具集含 `product_manage`、不含 `order_create`）
         里校验 `order_create` ⇒ **必须** `cross_skill_target` + suggestion；
      ② **R2 域内**：`order` 域（含 `order_create`）里校验同一个目标 ⇒ **success=True**
         （参数是合法下单参数 ⇒ 校验路径一字不改）；
      ③ **空域 fail-closed**：`create_skill_registry([])`（登记了空域）⇒ 任何目标都拒；
      ④ **非 skill 回合**：`set_tool_scope(None)` ⇒ 无域可比对，行为回到改前
         （`validate_input(order_create)` 照常通过）—— `api/chat.py` / 内测直调的既有语义；
      ⑤ **红证（可执行形态）**：同一组参数，**仅域不同** ⇒ 判定翻转（③/① vs ④），
         证明"改前的 success=True"确实是被这道闸门改写的。

    改前必红：①③ 在 #4079 之前得到 `success=True`（机制缺失）⇒ 本用例当场红。
    """
    from app.graph.skills.base_skill import create_skill_registry
    from app.tools.registry import set_tool_scope
    from app.tools.validate_input import ValidateInputTool

    tool = ValidateInputTool()
    ctx = _admin_ctx()

    # ① #3976 形状：product 域内校验 order_create
    create_skill_registry(["validate_input", "product_manage", "product_detail"])
    r1 = await tool.execute(ctx, target_tool="order_create", target_action="create",
                            params=_VALID_ORDER_PARAMS)
    assert r1.success is False and r1.error == "cross_skill_target", (
        f"域外目标没被拦下（#3976 的空头承诺形态）：success={r1.success} error={r1.error!r}"
    )
    assert (r1.suggestion or "").strip(), "fail-closed 分支必须带 suggestion（R5：_self_correct_retry 靠它启动）"
    assert r1.data.get("cross_skill_target") == "order_create"

    # ② R2：域内目标照常通过（合法调用不得被误伤）
    create_skill_registry(["validate_input", "order_create", "order_manage"])
    r2 = await tool.execute(ctx, target_tool="order_create", target_action="create",
                            params=_VALID_ORDER_PARAMS)
    assert r2.success is True and r2.data.get("validated") is True, (
        f"域内目标的合法校验被误伤：success={r2.success} error={r2.error!r}"
    )

    # ③ 空域：登记了空集 ⇒ 任何目标都执行不了 ⇒ fail-closed 全拒
    create_skill_registry([])
    r3 = await tool.execute(ctx, target_tool="order_create", target_action="create",
                            params=_VALID_ORDER_PARAMS)
    assert r3.success is False and r3.error == "cross_skill_target", (
        f"空域未 fail-closed：success={r3.success} error={r3.error!r}"
    )

    # ④ 非 skill 回合（无域）：无"当前 skill 域"可比对 ⇒ 行为与改前一致
    set_tool_scope(None)
    r4 = await tool.execute(ctx, target_tool="order_create", target_action="create",
                            params=_VALID_ORDER_PARAMS)
    assert r4.success is True, (
        f"无域（直调全局注册表/单测直调）路径被误拦：success={r4.success} error={r4.error!r}"
    )
    # ⑤ 判定翻转由**域**决定：①/③ 与 ④ 的入参完全相同，结论相反
    assert (r1.success, r3.success, r4.success) == (False, False, True)


async def test_read_only_target_and_out_of_table_names_keep_old_semantics():
    """R2 阴性负例：只读目标 / 表外工具名**不进入**域闸门（既有错误语义一字不改）。

    `validate_input` 的域比对放在规则查表**之后**：表外工具名（拼错/未注册/只读工具）
    仍走「未知的工具」分支 —— 这是改前的语义，也是"只读目标不受影响"的判据。
    """
    from app.graph.skills.base_skill import create_skill_registry
    from app.tools.validate_input import ValidateInputTool

    tool = ValidateInputTool()
    ctx = _admin_ctx()
    # 域里只有 product_manage（不含只读的 product_search）
    create_skill_registry(["validate_input", "product_manage"])

    res = await tool.execute(ctx, target_tool="product_search", target_action="search",
                             params={"keyword": "窗帘"})
    assert res.success is False, "表外/只读目标本就不该通过（既有语义）"
    assert res.error != "cross_skill_target", (
        f"只读目标被域闸门接管：error={res.error!r} —— 适用域被越界（会给出误导性建议）"
    )
    assert "未知" in (res.error or "") or "未知" in (res.message or ""), (
        f"表外目标应保留「未知的工具」语义，实得 error={res.error!r} message={res.message!r}"
    )


def test_tool_scope_is_registered_by_the_skill_registry_factory():
    """**事实链判据（防整个域闸门静默失效）**：工厂登记的执行域 == 它造出的工具子集。

    没有这一条，上面两条运行时断言都可能在"域没被登记（`get_tool_scope() is None`）"时
    **静默变成空跑**（无域 ⇒ 不比对 ⇒ 全绿），正是本仓最忌讳的「判据自己选择沉默」。
    """
    from app.graph.skills.base_skill import create_skill_registry
    from app.tools.registry import get_tool_scope, set_tool_scope

    reg = create_skill_registry(["validate_input", "order_create", "tool_that_is_not_registered"])
    scope = get_tool_scope()
    assert scope is not None, "`create_skill_registry` 没有登记执行域 —— 域闸门会静默失效"
    assert scope == frozenset(reg.get_tool_names()), (
        f"登记的执行域 {sorted(scope)} != registry 实际工具集 {sorted(reg.get_tool_names())}"
    )
    assert scope == frozenset({"validate_input", "order_create"}), (
        "登记进域的名字必须与**实际注册成功**的工具一致（不存在于全局注册表的工具"
        "模型也调不到，不得算作域内可执行）"
    )
    # 复位（用例隔离另有 conftest autouse fixture 兜底；此处显式复位便于单独跑本文件）
    set_tool_scope(None)
    assert get_tool_scope() is None


# ──────────────────────────────────────────────────────────────────────────────
# A10：CUSTOMER_ONLY_ROLES 单点化不变式
# ──────────────────────────────────────────────────────────────────────────────


def _customer_only_roles_bindings() -> dict[str, dict]:
    """`{文件: {"defines": bool, "imports": bool}}` —— 每个文件对 `CUSTOMER_ONLY_ROLES` 的绑定形态。

    ⚠️ **必须按作用域 + 按文件分类**（否则会误红**正确**的单点化修法）：
    `api/chat.py` 的 `from app.tools.base import CUSTOMER_ONLY_ROLES` 与
    `tools/base.py` 的 `CUSTOMER_ONLY_ROLES = frozenset({...})` 是**同一件事的两端**，
    把它们一起数成「2 处定义」= 把正确修法判红（`migao-dev-flow` §19.1
    「基于错误的真相模型写出的护栏 = 永远红」）。

    判据（三类分开数）：
      · `defines`：模块顶层 `X = <字面量>` ⇒ **定义**（单一源只许有 1 个文件）；
      · `imports`：`from … import X` ⇒ **引用**（多文件引用是**期望**形态）；
      · 同文件既 `imports` 又在顶层 `defines` ⇒ **遮蔽单一源**（红，且有理由）。

    函数/类作用域内的同名赋值或形参（如 `_to_agent_role(role)` 的 `role`）**不算**任何一类。
    """
    bindings: dict[str, dict] = {}

    def _entry(label: str) -> dict:
        return bindings.setdefault(label, {"defines": False, "imports": False})

    def _scan(body: list[ast.stmt], label: str, *, top_level: bool) -> None:
        for node in body:
            if isinstance(node, ast.ImportFrom):
                if any(alias.name == "CUSTOMER_ONLY_ROLES" for alias in node.names):
                    _entry(label)["imports"] = True
                continue
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign) and node.value:
                targets = [node.target]
            else:
                targets = []
            if top_level and any(
                isinstance(t, ast.Name) and t.id == "CUSTOMER_ONLY_ROLES" for t in targets
            ):
                _entry(label)["defines"] = True
            # 进入子作用域：同名赋值只是局部变量/形参，**不算**定义或引用
            for sub in ast.iter_child_nodes(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    _scan(sub.body, label, top_level=False)

    for path in sorted(APP_DIR.rglob("*.py")):
        try:
            tree = _module_ast(path)
        except SyntaxError:  # pragma: no cover - 语法错的文件不属本守卫
            continue
        _scan(tree.body, str(path.relative_to(APP_DIR.parent)), top_level=True)
    return bindings


def _customer_only_roles_definitions() -> list[tuple[str, set[str]]]:
    """**单一源定义点**清单（= `defines=True` 的文件），供红证/报告使用。"""
    return [
        (label, set())
        for label, b in _customer_only_roles_bindings().items()
        if b["defines"]
    ]


def test_customer_only_roles_has_exactly_one_definition():
    """**A10 核心不变式**：`CUSTOMER_ONLY_ROLES` 全仓只许有**一处定义**（+ 若干 import）。

    `app/tools/base.py` 的注释声称「在此声明单一语义源，chat.py 复用本常量」——
    实测全仓零 import（两份独立定义）—— 落地时**红**（存量真违规：结构上已是两份）；
    #4018 合入后已单点化（`chat.py` 改为 import）⇒ 转绿。
    注释与实际不符本身也是缺陷：它让下一个改角色集的人**以为改一处就够**。

    判据口径（单点化后**必须转绿**，不得把正确修法判红）：
      · 恰好 **1** 处模块顶层 `CUSTOMER_ONLY_ROLES = <字面量>`（= 单一源）；
      · 其余引用一律是 `import`（多文件 import 是**期望**形态，不计数）；
      · 若某文件 import 之后又在**模块顶层**重新赋值 = 遮蔽单一源 ⇒ 计数 +1 ⇒ 红（有理由）。

    反例输入（红证 ④）：删掉/改掉任一侧定义，或新增第三处顶层赋值 ⇒ 定义数 ≠ 1 ⇒ 必红。
    """
    bindings = _customer_only_roles_bindings()
    assert bindings, "全仓找不到 CUSTOMER_ONLY_ROLES 绑定 —— 解析失效（守卫会空转）"

    definers = sorted(label for label, b in bindings.items() if b["defines"])
    shadowing = sorted(label for label, b in bindings.items() if b["defines"] and b["imports"])
    detail = "\n  ".join(
        f"{label}: defines={int(b['defines'])} imports={int(b['imports'])}"
        for label, b in sorted(bindings.items())
    )

    assert not shadowing, (
        f"以下文件**先 import 再在模块顶层重新赋值** = 遮蔽单一源：{shadowing}\n  {detail}\n"
        f"→ 导入被静默覆盖，单一源失效（这类遮蔽最难发现：读代码看到的是 import）。"
    )
    assert len(definers) == 1, (
        f"`CUSTOMER_ONLY_ROLES` 有 {len(definers)} 个**定义文件**（不变式：恰好 1 个；import 任意多）："
        f"\n  定义文件 = {definers}\n  全部绑定形态：\n  {detail}\n"
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

async def test_cached_validation_success_does_not_leak_across_domains():
    """R2/R4 邻接：只读工具缓存**不得跨域串味**（否则 A5 死角从缓存里被放回来）。

    形态（同租户、同参数、60s 内）：A 域（含 `order_create`）的 `validate_input` 成功结论
    若被 B 域（不含它）命中 ⇒ B 域拿到"校验通过" ⇒ 落 pending → 确认卡 → 点卡后
    `Tool not found`（就是 #3976 的后果链，只是经由缓存复活）。
    ⇒ 缓存键必须覆盖结果依赖的**全部事实**（含执行域）。
    """
    from app.graph.skills.base_skill import _execute_tool_safe, create_skill_registry
    from app.tools.registry import set_tool_scope
    from app.tools.validate_input import ValidateInputTool

    tool = ValidateInputTool()
    ctx = _admin_ctx()
    state = {"session_id": ctx.session_id, "tenant_id": ctx.tenant_id}
    args = {"target_tool": "order_create", "target_action": "create",
            "params": dict(_VALID_ORDER_PARAMS)}

    # 清模块级缓存（与 tests/test_tool_write_not_cached.py 同口径：防跨用例污染）
    cache = getattr(_execute_tool_safe, "_cache", None)
    if cache is not None:
        cache.clear()

    create_skill_registry(["validate_input", "order_create", "order_manage"])
    _s1, d1 = await _execute_tool_safe(tool, dict(args), ctx, state)
    assert d1["success"] is True, f"A 域（含目标工具）应当校验通过：{d1}"

    create_skill_registry(["validate_input", "product_manage", "product_search"])
    _s2, d2 = await _execute_tool_safe(tool, dict(args), ctx, state)
    assert d2.get("error") == "cross_skill_target", (
        f"B 域命中了 A 域的缓存结论 ⇒ 跨域串味，A5 死角复活（#3976 的后果链）：{d2}"
    )
    set_tool_scope(None)
