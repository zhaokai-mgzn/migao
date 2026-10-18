"""
B 端能力边界投影（issue #7291）。

**单一事实源 = 工具注册表 × mibao 绑定面**，渲染成 system prompt 的一段，
替代原先人工抄写在 10 个 prompt 文件里的边界声明（其中 9 处与真值相反：
`非单据对象创建 ✅ 支持`，而 `employee_manage` / `customer_manage` 的 action enum
里根本没有 create —— 模型在同一个 prompt 里同时看到互斥的两句话）。

与 `_capability_index` 的分工（同族、不同问题）：
- 能力索引回答「哪个域有哪些写工具」——给模型的**地图**
- 本模块回答「用户能让我办什么、不能办什么、不能办时去哪」——给模型的**口径**

Seam: `render_capability_boundary()` → str（只给 mibao；调用方按 persona 门控）。

判据：`tests/test_capability_boundary.py`（探针已注册 / 独立复算一致 / 现实快照 /
手写声明不得回流 / 只注入 mibao / 内存注入判别力自证）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

#: 渲染段首标记（调用方据此判断「这一段在不在」，测试也用它做断言）。
MARKER = "【能力边界】"


@dataclass(frozen=True)
class CapabilityUnit:
    """一条用户语言的能力单元。

    Attributes:
        key: 稳定标识（用例 / 台账引用，不渲染给模型）
        label: 用户语言（渲染进 prompt）
        tool: 探针工具名（空串 = 全仓无此工具，如供应商）
        actions: 需要的写 action（空 = 只要工具可达且不是只读即算可用）
        decided_off: 产品裁定不做（不随工具真值变化，如创建单据类 / 删除）
        next_step: 不能办时的后台路径（渲染时逐条给出，避免「只说不行」）
    """

    key: str
    label: str
    tool: str = ""
    actions: Tuple[str, ...] = ()
    decided_off: bool = False
    next_step: str = ""


#: 能力单元清单（**唯一手写面**：标签 + 探针）。
#: 真值不在这里 —— 在 `resolve_units()` 从注册表现取。
UNITS: Tuple[CapabilityUnit, ...] = (
    # ── A 档：可逆变更（当前可达）────────────────────────────────────────
    CapabilityUnit("price_update", "商品改价", tool="product_update"),
    CapabilityUnit(
        "batch_update", "批量改价 / 批量库存调整",
        tool="product_batch_update", actions=("execute",),
    ),
    CapabilityUnit(
        "notification_read", "通知标记已读",
        tool="notification_manage", actions=("mark_read",),
    ),
    CapabilityUnit(
        "reminder", "定时提醒的建与取消",
        tool="scheduled_task_manage", actions=("create", "cancel"),
    ),
    # ── B 档：非单据对象创建（#7050 裁定要接、当前未接线）──────────────
    CapabilityUnit(
        "employee_write", "员工账号的创建与变更",
        tool="employee_manage", actions=("create",),
        next_step="后台「组织管理 → 员工管理」",
    ),
    CapabilityUnit(
        "role_write", "岗位（角色）与权限的创建与变更",
        tool="role_manage", actions=("create",),
        next_step="后台「组织管理 → 岗位权限」",
    ),
    CapabilityUnit(
        "customer_write", "客户建档 / 改资料 / 打标签",
        tool="customer_manage", actions=("update",),
        next_step="后台「客户列表」",
    ),
    CapabilityUnit(
        "category_write", "商品分类的创建与变更",
        tool="category_manage", actions=("create",),
        next_step="后台「商品 → 分类」",
    ),
    CapabilityUnit(
        "processing_item_write", "加工项的创建与变更",
        tool="processing_item_manage", actions=("create",),
        next_step="后台「商品 → 加工项」",
    ),
    CapabilityUnit(
        "supplier_write", "供应商的创建与变更",
        next_step="后台对应页面",
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
    # #7054：用户 2026-10-16 裁定「上下架都 ❌」，而 product_batch_update 仍提供
    # product_status ——工具侧缺口由 #7054 收口；本处按**产品裁定**渲染 ❌。
    CapabilityUnit(
        "status_toggle", "商品上架 / 下架",
        decided_off=True,
        next_step="后台「商品」页",
    ),
)


def _writable_actions(tool: Any) -> FrozenSet[str]:
    """工具的**可写** action 集合 = schema enum − `read_only_actions`（注册表事实）。"""
    props = ((getattr(tool, "parameters", None) or {}).get("properties") or {})
    enum = ((props.get("action") or {}).get("enum") or ())
    read_only_actions = set(getattr(tool, "read_only_actions", ()) or ())
    return frozenset(a for a in enum if a not in read_only_actions)


def _unit_available(unit: CapabilityUnit, tools: Mapping[str, Any],
                    reachable: FrozenSet[str]) -> bool:
    if unit.decided_off or not unit.tool or unit.tool not in reachable:
        return False
    tool = tools.get(unit.tool)
    if tool is None or getattr(tool, "read_only", False):
        return False
    if not unit.actions:
        return True
    return set(unit.actions).issubset(_writable_actions(tool))


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


def mibao_reachable_tool_names() -> FrozenSet[str]:
    """mibao 真实可达的工具名 = 其绑定 skill 的 `tool_names` 并集。"""
    from app.agents.agents.mibao import MIBAO_CONFIG
    from app.graph.skills.skill_registry import get_skill_registry

    registry = get_skill_registry()
    names = set()
    for skill_name in MIBAO_CONFIG.skill_names:
        cfg = registry.get(skill_name)
        if cfg is not None:
            names.update(cfg.tool_names or ())
    return frozenset(names)


def render_capability_boundary(states: Optional[Mapping[str, bool]] = None) -> str:
    """渲染 prompt 段。分组顺序固定（可直接办理 → 暂未接线 → 按裁定不做）。"""
    states = resolve_units() if states is None else states
    by_key = {u.key: u for u in UNITS}

    ok = [u.label for u in UNITS if states.get(u.key)]
    pending = [u for u in UNITS if not states.get(u.key) and not u.decided_off]
    decided = [u.label for u in UNITS if u.decided_off]

    lines = [
        MARKER + "以下由工具注册表实时推导（issue #7291）；与其它段落冲突时**以本段为准**：",
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
    return "\n".join(lines)
