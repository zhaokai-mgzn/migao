"""
B 端能力边界投影（issue #7291；#7334 收口）。

**单一事实源 = 工具注册表 × mibao 绑定面**，渲染成 system prompt 的一段，
替代原先人工抄写在 10 个 prompt 文件里的边界声明（其中 9 处与真值相反：
`非单据对象创建 ✅ 支持`，而 `employee_manage` / `customer_manage` 的 action enum
里根本没有 create —— 模型在同一个 prompt 里同时看到互斥的两句话）。

与 `_capability_index` 的分工（同族、不同问题）：
- 能力索引回答「哪个域有哪些写工具」——给模型的**地图**
- 本模块回答「用户能让我办什么、不能办什么、不能办时去哪」——给模型的**口径**

## 真值粒度（#7334）
不只 `action.enum`：字段级工具（`product_update` / `sku_update` 没有 action 维度）
用 `required_props` 探针，具名批量用 `required_prop_values` 探 batch_type 的枚举值。
产品裁定 ❌ 的单元用 `forbidden_props` / `forbidden_prop_values` 反向钉住：
工具若仍暴露该字段/枚举值，`forbidden_exposures()` 会具名报出（不再靠快照静默冻结）。

Seam: `render_capability_boundary()` → str（只给 mibao；调用方按 persona 门控）。

判据：`tests/test_capability_boundary.py`（探针已注册 / 独立复算一致 / 现实快照 /
字段级与批量枚举值 / 写工具全覆盖 / 手写声明不得回流 / 只注入 mibao / 内存注入判别力自证）。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

#: 渲染段首标记（调用方据此判断「这一段在不在」，测试也用它做断言）。
MARKER = "【能力边界】"


@dataclass(frozen=True)
class CapabilityUnit:
    """一条用户语言的能力单元。

    Attributes:
        key: 稳定标识（用例 / 台账引用，不渲染给模型）
        label: 用户语言（渲染进 prompt）
        tool: 探针工具名（空串 = 全仓无此工具，如供应商）
        actions: 需要的**全部**写 action（空 = 只要工具可达且不是只读即算可用；
            多动作标签必须列全 —— 少一个就判不可用，避免「加了一个 action 却宣称整条能力」）
        required_props: 工具 schema 必须存在的字段（字段级能力的真值；如改价的 price）
        required_prop_values: 字段枚举值必须全含（如 batch_type 必须含两种批量类型）
        forbidden_props: **产品裁定不做**时，工具若仍暴露该字段 ⇒ `forbidden_exposures()` 报红
        forbidden_prop_values: 同上，按字段枚举值反向钉住（如 batch_type 的 product_status）
        decided_off: 产品裁定不做（不随工具真值变化，如创建单据类 / 删除 / 上下架）
        next_step: 不能办时的后台路径（渲染时逐条给出，避免「只说不行」）
    """

    key: str
    label: str
    tool: str = ""
    actions: Tuple[str, ...] = ()
    required_props: Tuple[str, ...] = ()
    required_prop_values: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    forbidden_props: Tuple[str, ...] = ()
    forbidden_prop_values: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    decided_off: bool = False
    next_step: str = ""


#: 能力单元清单（**唯一手写面**：标签 + 探针 + 后台路径）。
#: 真值不在这里 —— 在 `resolve_units()` 从注册表现取。
#: ⚠️ 多动作标签必须把动作**列全**（如「创建与变更」= create + update）；
#: 只接一半时宁可先拆成两条单元，也不要让一条单元代表整条标签。
UNITS: Tuple[CapabilityUnit, ...] = (
    # ── A 档：可逆变更（当前可达）────────────────────────────────────────
    CapabilityUnit(
        "price_update", "商品改价",
        tool="product_update", required_props=("price",),
    ),
    CapabilityUnit(
        "product_rename", "商品改名",
        tool="product_update", required_props=("name",),
    ),
    CapabilityUnit(
        "sku_price_update", "单规格改价",
        tool="sku_update", required_props=("price",),
    ),
    CapabilityUnit(
        "batch_update", "批量改价 / 批量库存调整",
        tool="product_batch_update", actions=("execute",),
        required_prop_values=(("batch_type", ("product_price", "inventory_stock")),),
    ),
    CapabilityUnit(
        "batch_revert", "批量撤销",
        tool="product_batch_update", actions=("revert",),
    ),
    CapabilityUnit(
        "notification_read", "通知标记已读",
        tool="notification_manage", actions=("mark_read",),
    ),
    CapabilityUnit(
        "notification_read_all", "通知全部标记已读",
        tool="notification_manage", actions=("read_all",),
    ),
    CapabilityUnit(
        "reminder", "定时提醒的建与取消",
        tool="scheduled_task_manage", actions=("create", "cancel"),
    ),
    # ── B 档：非单据对象创建（#7050 裁定要接、当前未接线）──────────────
    # 标签含两个动作 ⇒ 两个动作都在才算可用（只接 create 时拆成两条，别宣称「变更」）。
    CapabilityUnit(
        "employee_write", "员工账号的创建与变更",
        tool="employee_manage", actions=("create", "update"),
        next_step="后台「组织管理 → 员工管理」",
    ),
    CapabilityUnit(
        "role_write", "岗位（角色）的创建与变更",
        tool="role_manage", actions=("create", "update"),
        next_step="后台「组织管理 → 岗位权限」",
    ),
    CapabilityUnit(
        "customer_write", "客户建档 / 改资料 / 打标签",
        tool="customer_manage", actions=("create", "update", "add_tag"),
        next_step="后台「客户列表」",
    ),
    CapabilityUnit(
        "category_write", "商品分类的创建与变更",
        tool="category_manage", actions=("create", "update"),
        next_step="后台「商品管理 → 商品分类管理」",
    ),
    CapabilityUnit(
        "processing_item_write", "加工项的创建与变更",
        tool="processing_item_manage", actions=("create", "update"),
        next_step="后台「企业基础设置 → 加工项与加工费」",
    ),
    CapabilityUnit(
        "supplier_write", "供应商档案的创建与变更",
        next_step="后台「入库单」新增时填写供应商（暂无独立供应商管理页）",
    ),
    # ── C 档：产品裁定不做（不随工具变化）──────────────────────────────
    CapabilityUnit(
        "document_create",
        "创建商品 / 订单 / 各类单据",
        decided_off=True,
        next_step="对应业务页面（提交永远在页面）",
    ),
    CapabilityUnit(
        "delete_object", "删除 / 停用 / 作废",
        decided_off=True,
        next_step="对应业务页面",
    ),
    # 用户 2026-10-16 裁定「上下架都 ❌」（#7054/#7334 裁定 A）：单件与批量分开探针，
    # 工具若仍暴露 status / product_status，`forbidden_exposures()` 具名报红。
    CapabilityUnit(
        "single_status_toggle", "商品单件上架 / 下架",
        tool="product_update", forbidden_props=("status",),
        decided_off=True, next_step="后台「商品管理」页",
    ),
    CapabilityUnit(
        "batch_status_toggle", "商品批量上架 / 下架",
        tool="product_batch_update",
        forbidden_prop_values=(("batch_type", ("product_status",)),),
        decided_off=True, next_step="后台「商品管理」页",
    ),
)


def _properties(tool: Any) -> Mapping[str, Any]:
    return ((getattr(tool, "parameters", None) or {}).get("properties") or {})


def _writable_actions(tool: Any) -> FrozenSet[str]:
    """工具的**可写** action 集合 = schema enum − `read_only_actions`（注册表事实）。"""
    enum = ((_properties(tool).get("action") or {}).get("enum") or ())
    read_only_actions = set(getattr(tool, "read_only_actions", ()) or ())
    return frozenset(a for a in enum if a not in read_only_actions)


def _has_props(tool: Any, props: Tuple[str, ...]) -> bool:
    available = set(_properties(tool))
    return set(props).issubset(available)


def _has_prop_values(tool: Any, pairs: Tuple[Tuple[str, Tuple[str, ...]], ...]) -> bool:
    properties = _properties(tool)
    for prop, values in pairs:
        enum = ((properties.get(prop) or {}).get("enum") or ())
        if not set(values).issubset(enum):
            return False
    return True


def _unit_available(unit: CapabilityUnit, tools: Mapping[str, Any],
                    reachable: FrozenSet[str]) -> bool:
    if unit.decided_off or not unit.tool or unit.tool not in reachable:
        return False
    tool = tools.get(unit.tool)
    if tool is None or getattr(tool, "read_only", False):
        return False
    if not _has_props(tool, unit.required_props):
        return False
    if not _has_prop_values(tool, unit.required_prop_values):
        return False
    if unit.actions and not set(unit.actions).issubset(_writable_actions(tool)):
        return False
    return True


def resolve_units(
    tools: Optional[Mapping[str, Any]] = None,
    reachable: Optional[FrozenSet[str]] = None,
) -> Dict[str, bool]:
    """逐单元解析可用性。`tools` / `reachable` 可注入（测试判别力自证用）。"""
    if tools is None:
        tools = _registered_tools()
    if reachable is None:
        reachable = mibao_reachable_tool_names()
    return {u.key: _unit_available(u, tools, reachable) for u in UNITS}


def _registered_tools() -> Dict[str, Any]:
    from app.tools.registry import get_tool_registry

    return {t.name: t for t in get_tool_registry().get_all_tools()}


def _compute_mibao_reachable_tool_names() -> FrozenSet[str]:
    """**未缓存**的可达性计算（测试的泄漏红证只许走这里，见 `test_reachability...`）。

    ⚠️ 必须走 `create_skill_registry` 这条真实现：它按 #4125 把「同一 persona 家族的
    **只读**工具」并入每个 skill（`settings_skill` 的 `default_persona=mibao` ⇒
    `validate_input` / `settings_manage` / `notification_manage` 对黄金策可达）。
    手搓「skill_names 的 tool_names 并集」会漏掉这条通道 —— 2026-10-19 实证：据此把三条
    用例误判成「空断言」，方向整个反了（见 docs/wiki/agent-capability-paradigm.md §五）。

    副作用：`create_skill_registry` 会把本轮工具集写进全局 `tool_scope`（A5 设计）——
    本函数是**只读探测**，必须原样还原，否则会把执行域留在最后一个 skill 上，
    让后续流程把域内目标判成越域（2026-10-19 实证：order_create 被误拒）。
    """
    from app.agents.agents.mibao import MIBAO_CONFIG
    from app.graph.skills.base_skill import create_skill_registry
    from app.graph.skills.skill_registry import get_skill_registry
    from app.tools.registry import get_tool_scope, set_tool_scope

    registry = get_skill_registry()
    skill_names = list(MIBAO_CONFIG.skill_names)
    if MIBAO_CONFIG.fallback_skill:
        skill_names.append(MIBAO_CONFIG.fallback_skill)
    names: set[str] = set()
    previous_scope = get_tool_scope()
    try:
        for skill_name in skill_names:
            cfg = registry.get(skill_name)
            if cfg is None:
                continue
            names.update(create_skill_registry(list(cfg.tool_names or ())).get_tool_names())
    finally:
        set_tool_scope(previous_scope)
    return frozenset(names)


@lru_cache(maxsize=1)
def mibao_reachable_tool_names() -> FrozenSet[str]:
    """mibao 真实可达的工具名 = 每个绑定 skill（∪ 兜底）**实际注册后**的工具名并集。

    进程级缓存（#7334）：绑定面是静态代码事实，而 `create_skill_registry` 每调一次都会
    打一批 `Tool registered` 日志（实测单次渲染 345 行）。缓存后每进程只算一次；
    测试要重新探测请调 `_compute_mibao_reachable_tool_names()` 或 `cache_clear()`。
    """
    return _compute_mibao_reachable_tool_names()


def forbidden_exposures(
    tools: Optional[Mapping[str, Any]] = None,
    reachable: Optional[FrozenSet[str]] = None,
) -> List[str]:
    """产品裁定 ❌ 的单元，若工具仍暴露对应字段/枚举值 ⇒ 具名报出（空列表 = 干净）。

    这是 `decided_off` 的**反向真值判据**：只渲染 ❌ 不够 —— 工具还能做，模型就可能
    被工具 schema / 能力索引引去做，而快照又会把一个恒 False 的产品裁定冻结成绿。
    """
    if tools is None:
        tools = _registered_tools()
    if reachable is None:
        reachable = mibao_reachable_tool_names()
    problems: List[str] = []
    for unit in UNITS:
        if not unit.decided_off or not unit.tool or unit.tool not in reachable:
            continue
        tool = tools.get(unit.tool)
        if tool is None:
            continue
        for prop in unit.forbidden_props:
            if prop in _properties(tool):
                problems.append(
                    f"{unit.key}: 工具 {unit.tool} 仍暴露字段 {prop}（产品裁定 ❌ 但工具面还能做）"
                )
        for prop, values in unit.forbidden_prop_values:
            enum = ((_properties(tool).get(prop) or {}).get("enum") or ())
            still = [v for v in values if v in enum]
            if still:
                problems.append(
                    f"{unit.key}: 工具 {unit.tool} 的 {prop} 仍含 {still}（产品裁定 ❌ 但工具面还能做）"
                )
    return problems


def render_capability_boundary(states: Optional[Mapping[str, bool]] = None) -> str:
    """渲染 prompt 段。分组顺序固定（可直接办理 → 暂未接线 → 按裁定不做）。"""
    states = resolve_units() if states is None else states

    ok = [u.label for u in UNITS if states.get(u.key)]
    pending = [u for u in UNITS if not states.get(u.key) and not u.decided_off]
    decided = [u.label for u in UNITS if u.decided_off]

    lines = [
        MARKER + "以下能力状态由工具注册表推导（issue #7291；含字段 / 枚举值级）；"
        "与其它段落的能力口径冲突时**以本段为准**：",
        "- ✅ 可直接办理：" + "、".join(ok),
    ]
    if pending:
        lines.append(
            "- ❌ 暂未接线（如实说「现在做不了」+ 给后台路径，**不得**承诺代办）："
            + "；".join(f"{u.label} → {u.next_step}" for u in pending)
        )
    if decided:
        lines.append(
            "- ❌ 按产品裁定不做（提交永远在页面）：" + "、".join(decided)
        )
    # 空清单守卫：宁可整段不渲染，也不产出「✅ 可直接办理：」这种空话。
    if not ok:
        lines.pop(1)
    lines.append(
        "- ⚠️ 以上是能力面；当前账号能不能执行，以【权限范围】与工具返回为准"
        "（无权限时如实说明，不要重试）。"
    )
    return "\n".join(lines)
