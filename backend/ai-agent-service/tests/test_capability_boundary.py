# case_ids: HR-009, DF-003, HR-002
"""B 端能力边界的**投影判据**（issue #7291）。

为什么需要它：能力边界原先靠人工抄写在 10 个 prompt 文件里，其中 9 处与工具真值相反
（`非单据对象创建 ✅ 支持`，而 `employee_manage` / `customer_manage` 的 action enum 里
根本没有 create）—— 模型在同一个 system prompt 里同时看到互斥的两句话
（Layer 2/3 手抄声明 vs Layer 2.6 能力索引）。

本判据把「说的」钉在「能做的」上：
- 探针必须指向**已注册**工具（拼错即红）
- 渲染状态必须等于**独立复算**的注册表真值（不走被测模块的内部函数）
- 真值变化即红：快照 `AVAILABILITY_SNAPSHOT` 是「现实变了」的闹钟 ——
  例如 #7050 把 `employee_manage(create)` 接回来时，本判据会红，提示更新 UNITS 与渲染
- `references/**` 不得再出现手写的能力声明（类级：防回流）
- 只注入 mibao（C 端 prompt 逐字节不受影响）

红证（判别力自证）：`test_probe_flips_when_tool_gains_action` 用内存替身给
`employee_manage` 加 create action ⇒ 同一套解析逻辑把它判为可用。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.capability_boundary import (
    UNITS,
    mibao_reachable_tool_names,
    render_capability_boundary,
    resolve_units,
)

_REFERENCES_DIR = (
    Path(__file__).resolve().parent.parent / "app" / "graph" / "skills" / "references"
)

#: 现实快照。**变了就更新这里** —— 它同时是 #7050 接线时的提醒装置。
AVAILABILITY_SNAPSHOT = {
    "price_update": True,
    "batch_update": True,
    "notification_read": True,
    "reminder": True,
    "employee_write": False,
    "role_write": False,
    "customer_write": False,
    "category_write": False,
    "processing_item_write": False,
    "supplier_write": False,
    "document_create": False,
    "delete_object": False,
    "status_toggle": False,
}


def _registered_tools() -> dict:
    from app.tools.registry import get_tool_registry

    return {t.name: t for t in get_tool_registry().get_all_tools()}


def _independent_reachable() -> frozenset:
    """独立复算 B 端可达工具（不复用被测模块的函数）。"""
    from app.agents.agents.mibao import MIBAO_CONFIG
    from app.graph.skills.skill_registry import get_skill_registry

    registry = get_skill_registry()
    names: set[str] = set()
    for skill_name in MIBAO_CONFIG.skill_names:
        cfg = registry.get(skill_name)
        if cfg is not None:
            names.update(cfg.tool_names or ())
    return frozenset(names)


def _independent_available(unit, tools: dict, reachable: frozenset) -> bool:
    """独立复算单条可用性（枚举 action 真值，不调用被测模块）。"""
    if unit.decided_off or not unit.tool or unit.tool not in reachable:
        return False
    tool = tools.get(unit.tool)
    if tool is None or getattr(tool, "read_only", False):
        return False
    if not unit.actions:
        return True
    props = ((getattr(tool, "parameters", None) or {}).get("properties") or {})
    enum = set(((props.get("action") or {}).get("enum") or []))
    read_only_actions = set(getattr(tool, "read_only_actions", ()) or ())
    writable = enum - read_only_actions
    return set(unit.actions).issubset(writable)


def test_probe_tools_are_registered():
    """探针拼错工具名 ⇒ 红（否则「暂未接线」会因拼写错误而永远成立）。"""
    tools = _registered_tools()
    for unit in UNITS:
        if unit.tool:
            assert unit.tool in tools, f"能力单元 {unit.key} 的探针指向未注册工具 {unit.tool}"


def test_production_reachable_matches_independent_recount():
    assert mibao_reachable_tool_names() == _independent_reachable()


def test_availability_matches_registry_truth():
    """渲染状态 == 独立复算真值（不是自证：复算路径不经过被测模块）。"""
    tools = _registered_tools()
    reachable = _independent_reachable()
    actual = resolve_units(tools=tools, reachable=reachable)
    expected = {u.key: _independent_available(u, tools, reachable) for u in UNITS}
    assert actual == expected


def test_availability_snapshot_is_current():
    """现实快照：工具真值一变就红，逼更新 UNITS/渲染（#7050 落地时的提醒装置）。"""
    actual = resolve_units()
    assert actual == AVAILABILITY_SNAPSHOT, (
        "B 端能力真值已变化（工具增删了写 action 或绑定面变了）。\n"
        f"现真值：{actual}\n"
        f"快照：  {AVAILABILITY_SNAPSHOT}\n"
        "处理：核对 app/agents/capability_boundary.py 的 UNITS 后更新本快照；"
        "渲染文案由投影自动跟随，无需手改 prompt。"
    )


def test_probe_flips_when_tool_gains_action():
    """判别力自证：给 employee_manage 内存注入 create action ⇒ 同一套逻辑判为可用。"""

    class _FakeTool:
        name = "employee_manage"
        read_only = False
        read_only_actions = {"list", "detail"}
        parameters = {
            "properties": {"action": {"enum": ["list", "detail", "create"]}}
        }

    tools = _registered_tools()
    tools["employee_manage"] = _FakeTool()
    states = resolve_units(tools=tools, reachable=_independent_reachable())
    assert states["employee_write"] is True


def test_no_handwritten_capability_claims_in_prompts():
    """类级守卫：手写的「非单据对象创建」声明不得回流（边界只许由投影渲染）。"""
    offenders = [
        str(path.relative_to(_REFERENCES_DIR.parent))
        for path in _REFERENCES_DIR.rglob("*.md")
        if "非单据对象创建" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        "以下 prompt 仍在手写能力边界声明（应删除，由 capability_boundary 投影接管）："
        f"{offenders}"
    )


def test_render_contains_every_unit_label():
    """渲染不漏项：每条单元都必须出现在渲染文本里（漏项 = 模型看不到这条边界）。"""
    text = render_capability_boundary()
    missing = [u.label for u in UNITS if u.label not in text]
    assert not missing, f"渲染缺少能力单元：{missing}"


def test_boundary_injected_for_mibao_only():
    """只注入 mibao：C 端（customer_general）prompt 不含该段。"""
    from app.graph.skills.base_skill import (
        _CAPABILITY_BOUNDARY_MARKER,
        _PROMPT_CACHE,
        _build_system_prompt,
    )

    _PROMPT_CACHE.clear()
    assert _CAPABILITY_BOUNDARY_MARKER in _build_system_prompt("staff")
    assert _CAPABILITY_BOUNDARY_MARKER not in _build_system_prompt("customer_general")
