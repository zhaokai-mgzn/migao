# case_ids: HR-009, DF-003, HR-002, AG-008
"""B 端能力边界的**投影判据**（issue #7291；#7334 二次审计收口）。

为什么需要它：能力边界原先靠人工抄写在 10 个 prompt 文件里，其中 9 处与工具真值相反
（`非单据对象创建 ✅ 支持`，而 `employee_manage` / `customer_manage` 的 action enum
里根本没有 create）—— 模型在同一个 system prompt 里同时看到互斥的两句话。

#7334 追加的四类判据（都带判别力自证）：
- **字段级真值**：`product_update` / `sku_update` 没有 action 维度 ⇒ 用 `required_props`
  探针（price / name / status），不再「工具可达就整条能力可用」；
- **全覆盖**：所有 B 端可达写工具都必须被某个单元探到（`sku_update` 曾漏网）；
- **反向真值**：`decided_off` 单元对应的工具字段/枚举值若仍暴露 ⇒
  `forbidden_exposures()` 具名报红（上下架曾是「快照绿、工具还能做」）；
- **话术一致**：手写 prompt（含 `SkillConfig.system_prompts` 的 Python 内联 prompt）
  的支持/拒绝话术必须与当前真值一致（单元 ✅ 时不得说「不在能力内」，❌ 时不得说「支持」）。

红证（判别力自证）：
- `test_probe_flips_when_tool_gains_action`（create+update 都在 ⇒ 可用）
- `test_partial_action_does_not_flip`（只加 create ⇒ 仍不可用，防「半条能力」）
- `test_field_probe_distinguishes_price_and_name`
- `test_write_tool_completeness_has_red_power`
- `test_forbidden_exposure_has_red_power`
- `test_prose_guard_has_red_power`

#8119（按本轮 skill 投影）追加：`render_capability_boundary(skill_name=...)` 必须把**本域不可达**
的写能力从「✅ 可直接办理」移到「➡️ 本域不直接办」，而本域可办的不得降格。注入式红证 =
把投影里的 skill 过滤摘掉（退回 persona 全局）⇒ 7 个零写 skill 的判据立刻红（读数见 PR body）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.agents.capability_boundary import (
    DIRECT_PREFIX,
    ELSEWHERE_PREFIX,
    UNITS,
    _compute_mibao_reachable_tool_names,
    declared_tool_names,
    forbidden_exposures,
    mibao_reachable_tool_names,
    render_capability_boundary,
    resolve_units,
)

_REFERENCES_DIR = (
    Path(__file__).resolve().parent.parent / "app" / "graph" / "skills" / "references"
)

#: 现实快照。**变了就更新这里** —— 它同时是 #7050 接线 / 工具收窄的提醒装置。
AVAILABILITY_SNAPSHOT = {
    "price_update": True,
    "product_rename": True,
    "sku_price_update": True,
    "batch_update": True,
    "batch_revert": True,
    "notification_read": True,
    "notification_read_all": True,
    "reminder": True,
    "craft_calc_config_update": True,  # issue #7514：A 档可逆写（product 域）
    "employee_write": False,
    "role_write": False,
    "customer_write": False,
    "category_write": False,
    "processing_item_write": False,
    "supplier_write": False,
    "document_create": False,
    "delete_object": False,
    "single_status_toggle": False,
    "batch_status_toggle": False,
}


def _registered_tools() -> dict:
    from app.tools.registry import get_tool_registry

    return {t.name: t for t in get_tool_registry().get_all_tools()}


def _independent_reachable() -> frozenset:
    """独立复算 B 端可达工具（不复用被测模块的函数）。"""
    from app.agents.agents.mibao import MIBAO_CONFIG
    from app.graph.skills.skill_registry import get_skill_registry

    from app.graph.skills.base_skill import _all_skill_configs, _read_only_tool_names

    registry = get_skill_registry()
    names: set[str] = set()
    for skill_name in (*MIBAO_CONFIG.skill_names, MIBAO_CONFIG.fallback_skill):
        cfg = registry.get(skill_name)
        if cfg is not None:
            names.update(cfg.tool_names or ())
    # #4125：同 persona 家族的**只读**工具也并入（独立复算，不复用 create_skill_registry）
    read_only = _read_only_tool_names()
    for cfg in _all_skill_configs():
        if "mibao" in (cfg.system_prompts or {}):
            names.update(t for t in (cfg.tool_names or ()) if t in read_only)
    return frozenset(names)


def _independent_available(unit, tools: dict, reachable: frozenset) -> bool:
    """独立复算单条可用性（字段 / 枚举值 / action 真值，不调用被测模块）。"""
    if unit.decided_off or not unit.tool or unit.tool not in reachable:
        return False
    tool = tools.get(unit.tool)
    if tool is None or getattr(tool, "read_only", False):
        return False
    props = ((getattr(tool, "parameters", None) or {}).get("properties") or {})
    if not set(unit.required_props).issubset(props):
        return False
    for prop, values in unit.required_prop_values:
        enum = set(((props.get(prop) or {}).get("enum") or []))
        if not set(values).issubset(enum):
            return False
    if unit.actions:
        enum = set(((props.get("action") or {}).get("enum") or []))
        read_only_actions = set(getattr(tool, "read_only_actions", ()) or ())
        writable = enum - read_only_actions
        if not set(unit.actions).issubset(writable):
            return False
    return True


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
        "B 端能力真值已变化（工具增删了写 action / 字段 / 批量类型或绑定面变了）。\n"
        f"现真值：{actual}\n"
        f"快照：  {AVAILABILITY_SNAPSHOT}\n"
        "处理：核对 app/agents/capability_boundary.py 的 UNITS 后更新本快照；"
        "渲染文案与字段级探针由投影自动跟随，无需手改 prompt。"
    )


def test_probe_flips_when_tool_gains_action():
    """判别力自证：给 employee_manage 内存注入 create+update ⇒ 同一套逻辑判为可用。"""

    class _FakeTool:
        name = "employee_manage"
        read_only = False
        read_only_actions = {"list", "detail"}
        parameters = {
            "properties": {"action": {"enum": ["list", "detail", "create", "update"]}}
        }

    tools = _registered_tools()
    tools["employee_manage"] = _FakeTool()
    states = resolve_units(tools=tools, reachable=_independent_reachable())
    assert states["employee_write"] is True


def test_partial_action_does_not_flip():
    """只加 create、没有 update ⇒「员工账号的创建与变更」仍不可用（不宣称半条能力）。"""

    class _FakeTool:
        name = "employee_manage"
        read_only = False
        read_only_actions = {"list", "detail"}
        parameters = {"properties": {"action": {"enum": ["list", "detail", "create"]}}}

    tools = _registered_tools()
    tools["employee_manage"] = _FakeTool()
    states = resolve_units(tools=tools, reachable=_independent_reachable())
    assert states["employee_write"] is False


def test_field_probe_distinguishes_price_and_name():
    """字段级真值：同名工具只留 price 时改价 ✅、改名 ❌（旧模型只看工具可达，两者同真）。"""

    class _FakeTool:
        name = "product_update"
        read_only = False
        parameters = {"properties": {"price": {"type": "number"}}}

    tools = _registered_tools()
    tools["product_update"] = _FakeTool()
    states = resolve_units(tools=tools, reachable=_independent_reachable())
    assert states["price_update"] is True
    assert states["product_rename"] is False


def _uncovered_write_tools(tools: dict, reachable: frozenset, units=UNITS) -> list[str]:
    """B 端可达写工具里，没有被任何非 decided_off 单元探到的工具。"""
    covered = {u.tool for u in units if u.tool and not u.decided_off}
    return sorted(
        name for name in reachable
        if (tool := tools.get(name)) is not None
        and not getattr(tool, "read_only", False)
        and name not in covered
    )


def test_every_reachable_write_tool_is_probed():
    """写工具全覆盖：新增一把 B 端写工具却没有能力单元 ⇒ 红（`sku_update` 曾漏网）。"""
    uncovered = _uncovered_write_tools(_registered_tools(), _independent_reachable())
    assert not uncovered, (
        "以下 B 端可达写工具没有被任何能力单元探到 ⇒ 能力边界会静默漏掉它："
        f"{uncovered}。修法：给 UNITS 加探针（字段级用 required_props），"
        "或在测试里登记显式豁免（带理由）。"
    )


def test_write_tool_completeness_has_red_power():
    """判别力自证：注入一把未登记的写工具 ⇒ 完备性检查必须点名它。"""

    class _FakeTool:
        name = "fake_write_capability"
        read_only = False
        read_only_actions = set()
        parameters = {"properties": {}}

    tools = _registered_tools()
    tools["fake_write_capability"] = _FakeTool()
    reachable = frozenset(set(_independent_reachable()) | {"fake_write_capability"})
    assert _uncovered_write_tools(tools, reachable) == ["fake_write_capability"]


def test_decided_off_status_is_not_exposed_by_tools():
    """反向真值：上下架按裁定 A 不做 ⇒ 两把工具都不得再暴露 status / product_status。"""
    problems = forbidden_exposures()
    assert not problems, "产品裁定 ❌ 的上下架仍能从工具面执行：\n" + "\n".join(problems)


def test_forbidden_exposure_has_red_power():
    """判别力自证：把 status / product_status 注回去 ⇒ 两个单元都具名报红。"""

    class _ProductUpdate:
        name = "product_update"
        read_only = False
        parameters = {"properties": {"price": {"type": "number"},
                                     "status": {"enum": ["on_sale", "off_sale"]}}}

    class _Batch:
        name = "product_batch_update"
        read_only = False
        read_only_actions = {"preview"}
        parameters = {
            "properties": {
                "action": {"enum": ["preview", "execute", "revert"]},
                "batch_type": {"enum": ["product_price", "product_status", "inventory_stock"]},
            }
        }

    tools = _registered_tools()
    tools["product_update"] = _ProductUpdate()
    tools["product_batch_update"] = _Batch()
    problems = forbidden_exposures(tools, _independent_reachable())
    assert any("single_status_toggle" in p and "status" in p for p in problems), problems
    assert any("batch_status_toggle" in p and "product_status" in p for p in problems), problems


#: 单元 → 手写话术（只在**当前真值**下判）：
#: · 单元 ✅ ⇒ 不得出现 deny 话术（「改名不在能力内」）
#: · 单元 ❌ ⇒ 不得出现 support 话术（「支持创建员工」）
#: 只收具名短语，不做 NLU —— 它抓的是「文案写死了一个与真值相反的事实」这类回归。
UNIT_PROSE = {
    "price_update": {"deny": ("改价不在能力内", "不支持改价", "不能改价", "改不了价")},
    "product_rename": {
        "deny": ("改名不在能力内", "不支持改名", "不能改名", "改不了名", "没有改名能力"),
    },
    "sku_price_update": {
        "deny": ("SKU 改价不在能力内", "单规格调价不在能力内", "不支持 SKU 改价"),
    },
    "batch_update": {
        "deny": ("批量改价不在能力内", "批量库存调整不在能力内", "不支持批量改价"),
    },
    "batch_revert": {"deny": ("批量撤销不在能力内", "不支持撤销", "不能撤销")},
    "notification_read": {"deny": ("标记已读不在能力内", "不支持标记已读")},
    "notification_read_all": {"deny": ("全部已读不在能力内", "不支持全部已读")},
    "reminder": {"deny": ("定时提醒不在能力内", "不支持定时提醒")},
    "employee_write": {
        "support": ("可以创建员工", "支持创建员工", "能创建员工", "可以建员工", "能建员工"),
        "deny": ("写能力未接线", "创建员工账号不在黄金策能力内", "创建/更新/删除员工"),
    },
    "role_write": {
        "support": ("可以创建岗位", "支持创建岗位", "可以创建角色", "支持创建角色"),
        "deny": ("写能力未接线", "建角色/改权限不在能力内", "创建/更新/删除岗位"),
    },
    "customer_write": {
        "support": ("可以创建客户", "支持创建客户", "可以给客户打标签", "支持给客户打标签"),
        "deny": ("打标签不在能力内", "修改资料不在能力内",
                 "打标签、移除标签、创建/删除标签都不在能力内"),
    },
    "category_write": {
        "support": ("可以创建分类", "支持创建分类", "能创建分类", "可以新增分类"),
        "deny": ("分类增删改",),
    },
    "processing_item_write": {
        "support": ("可以创建加工项", "支持创建加工项", "可以新增加工项", "可以修改加工项"),
        "deny": ("加工项增删改",),
    },
    "supplier_write": {
        "support": ("可以创建供应商", "支持创建供应商", "可以新增供应商"),
    },
    "document_create": {
        "support": ("可以创建商品", "支持创建商品", "可以创建订单", "支持创建订单"),
    },
    "delete_object": {
        "support": ("可以删除商品", "支持删除商品", "可以删除员工", "支持删除员工"),
    },
    "single_status_toggle": {
        "support": ("支持上下架", "可以上下架", "能上架", "能下架", "可以上架", "可以下架"),
    },
    "batch_status_toggle": {
        "support": ("支持批量上下架", "可以批量上下架", "批量上架", "批量下架"),
    },
}


def _mibao_prompt_texts() -> dict[str, str]:
    """B 端**实际进模型**的 prompt 文本：markdown 层 + SkillConfig 内联层。

    只收 mibao persona：C 端元元的能力（如创建订单）不在本投影射程内，
    混进来会把「C 端合法能力」误判成 B 端越界。
    """
    from app.agents.agents.mibao import MIBAO_CONFIG
    from app.graph.skills.base_skill import _all_skill_configs

    skill_names = list(MIBAO_CONFIG.skill_names)
    if MIBAO_CONFIG.fallback_skill:
        skill_names.append(MIBAO_CONFIG.fallback_skill)
    texts: dict[str, str] = {}
    for name in skill_names:
        for rel in (f"prompts/{name}.md", f"EXAMPLES-{name}.md"):
            path = _REFERENCES_DIR / rel
            if path.is_file():
                texts[str(path.relative_to(_REFERENCES_DIR))] = path.read_text(encoding="utf-8")
    shared = _REFERENCES_DIR / "PROMPT-rules.md"
    if shared.is_file():
        texts["PROMPT-rules.md"] = shared.read_text(encoding="utf-8")
    for cfg in _all_skill_configs():
        text = (cfg.system_prompts or {}).get("mibao")
        if text:
            texts[f"SkillConfig[{cfg.name}::mibao]"] = text
    return texts


def _asserted_phrase(text: str, phrase: str) -> bool:
    """短语是否被**肯定地**写出来（跳过「不得答/不要写/禁止说…」的否定语境）。

    为什么需要：示例里会有「❌ 不得答『改名不在能力内』」这种**反向示范**，
    以及「不能创建员工」这种拒绝话术。纯 `in` 会把它们当成能力声明（假红）。
    """
    start = 0
    while True:
        idx = text.find(phrase, start)
        if idx < 0:
            return False
        prefix = text[max(0, idx - 8):idx]
        if not any(neg in prefix for neg in ("不", "无法", "没", "别", "勿", "禁止", "不要", "不应")):
            return True
        start = idx + len(phrase)


def _prose_offenders(texts: dict[str, str]) -> list[str]:
    states = resolve_units()
    offenders: list[str] = []
    for where, text in texts.items():
        for key, rules in UNIT_PROSE.items():
            phrases = rules.get("deny") if states.get(key) else rules.get("support")
            for phrase in phrases or ():
                if _asserted_phrase(text, phrase):
                    kind = "拒绝" if states.get(key) else "支持"
                    offenders.append(f"{where}: {key} 当前为 {states.get(key)}，却出现{kind}话术「{phrase}」")
    return offenders


def test_capability_prose_matches_registry_state():
    """类级防回流：手写 prompt（含 Python 内联 prompt）不得与当前真值相反。"""
    offenders = _prose_offenders(_mibao_prompt_texts())
    assert not offenders, (
        "以下 prompt 的手写能力话术与注册表真值相反（单元 ✅ 说不能 / 单元 ❌ 说能）：\n"
        + "\n".join(offenders)
        + "\n修法：改成由【能力边界】段表述，或按当前真值改写；不要新增第二份能力矩阵。"
    )


def test_prose_guard_has_red_power():
    """判别力自证：注入「支持创建员工」（当前 ❌）/「改名不在能力内」（当前 ✅）都红。"""
    assert any("employee_write" in x for x in _prose_offenders({"fake.md": "支持创建员工"}))
    assert any("product_rename" in x for x in _prose_offenders({"fake.md": "改名不在能力内"}))
    assert not _prose_offenders({"fake.md": "改名可以做；上下架不在能力内；不能创建员工"})


#: 完整 next_step 快照。叶子是**页面级标签**（不在侧边栏树里），这里冻结完整文案；
#: 首级必须是真实侧边栏节点。改任一条都必须人工核对真实后台页面（#7334 的
#: 「商品管理 → 加工项」就是只校验首级时漏掉的死链）。
NEXT_STEP_SNAPSHOT = {
    "employee_write": "后台「组织管理 → 员工管理」",
    "role_write": "后台「组织管理 → 岗位权限」",
    "customer_write": "后台「客户列表」",
    "category_write": "后台「商品管理 → 商品分类管理」",
    "processing_item_write": "后台「企业基础设置 → 加工项与加工费」",
    "supplier_write": "后台「入库单」新增时填写供应商（暂无独立供应商管理页）",
    "document_create": "对应业务页面（提交永远在页面）",
    "delete_object": "对应业务页面",
    "single_status_toggle": "后台「商品管理」页",
    "batch_status_toggle": "后台「商品管理」页",
}

#: 真实侧边栏一级节点（含一级独立项）。改菜单时同步这里。
REAL_SIDEBAR_ROOTS = frozenset({
    "组织管理", "客户列表", "商品管理", "企业基础设置", "入库单",
})


def test_next_steps_match_frozen_navigation_snapshot():
    actual = {u.key: u.next_step for u in UNITS if u.next_step}
    assert actual == NEXT_STEP_SNAPSHOT, (
        "next_step 文案变了：请人工核对真实后台页面后同步本快照。\n"
        f"现取：{actual}\n快照：{NEXT_STEP_SNAPSHOT}"
    )
    for key, step in NEXT_STEP_SNAPSHOT.items():
        match = re.search(r"「([^」]+)」", step)
        if not match:
            continue
        first = match.group(1).split("→")[0].strip()
        assert first in REAL_SIDEBAR_ROOTS, (
            f"{key} 的后台路径首级「{first}」不是真实侧边栏节点"
            f"（允许：{sorted(REAL_SIDEBAR_ROOTS)}）"
        )


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


def test_reachability_probe_does_not_leak_tool_scope():
    """探测不得有副作用：未缓存的探测跑完必须还原执行域。

    病灶（2026-10-19 实证）：`create_skill_registry` 会把本轮工具集写进全局 `tool_scope`
    （A5 设计）—— 探测函数若直接调它而不还原，执行域就停在最后一个 skill 上，
    后续流程把域内目标（如 `order_create`）判成越域，红在第一个人想不到的地方。

    #7334：公开函数加了进程级缓存，泄漏红证必须打**未缓存**的 `_compute_...`，
    否则缓存命中时它根本不调 `create_skill_registry`，测试会变成空转。
    """
    from app.tools.registry import get_tool_scope, set_tool_scope

    set_tool_scope(["order_query", "validate_input"])
    before = get_tool_scope()
    _compute_mibao_reachable_tool_names()
    assert get_tool_scope() == before, "可达性探测泄漏了 tool_scope（执行域被改写）"
    set_tool_scope(None)


# ────────────────────── 按本轮 skill 投影（issue #8119）──────────────────────
# 病灶：投影按 **persona 全局**给 ⇒ 每个 mibao 回合都注入「✅ 商品改名可直接办理（以本段为准）」，
# 而 order / customer / staff / data / knowledge / aftersales / general 这 7 个 skill **零写工具**
# （现取）⇒ 模型只能空头承诺或误拒（同族真实缺陷 #7347 边界问句触发工具调用 / #7758 守卫误判锁死会话）。


def _mibao_skill_names() -> list[str]:
    """现取：所有 mibao persona 的 skill（**不写死清单** —— 新增域自动进判据）。"""
    from app.graph.skills.base_skill import _all_skill_configs

    return sorted(
        cfg.name for cfg in _all_skill_configs()
        if "mibao" in set(cfg.system_prompts or {})
    )


def _declared_write_tool_names(skill_name: str) -> list[str]:
    """独立复算：本 skill **声明面**里的写工具（不经过被判的渲染函数）。"""
    from app.graph.skills.skill_registry import get_skill_registry
    from app.tools.registry import get_tool_registry

    tools = {t.name: t for t in get_tool_registry().get_all_tools()}
    cfg = get_skill_registry().get(skill_name)
    return sorted(
        name for name in (cfg.tool_names or ())
        if (tool := tools.get(name)) is not None and not getattr(tool, "read_only", False)
    )


def _segment(text: str, prefix: str) -> list[str]:
    """取某一段的单元清单（行首标记；该段不存在 ⇒ 空列表）。

    单元标签里不含中文顿号（`、`）—— 段落里唯一的 `、` 只做分隔符（下方判据自证）。
    """
    line = next((ln for ln in text.splitlines() if ln.startswith(prefix)), "")
    if not line:
        return []
    return [s for s in line.rsplit("：", 1)[-1].split("、") if s]


def test_unit_labels_carry_no_delimiter():
    """解析前提自证：单元标签不含顿号（`_segment` 用它做分隔符）。"""
    offenders = [u.label for u in UNITS if "、" in u.label]
    assert not offenders, f"单元标签含顿号，`_segment` 会切错：{offenders}"


def test_available_units_probe_are_write_tools():
    """判域前提（issue #8119）：**可办**单元的探针必须是**写工具**。

    为什么必须钉住：按本轮 skill 的 `tool_names`（声明面）判域，成立的前提是
    「写能力只来自声明面」—— `create_skill_registry` 的 #4125 家族合并**只并只读工具**。
    若某个 ✅ 单元的探针是只读工具，它会经家族合并出现在**别的** skill 回合，
    只看声明面就会把**能办**的说成「本域不直接办」（把能力弄丢，比空头承诺更隐蔽）。
    本判据把这个前提从注释里的假设变成会红的事实；真出现时，修法是给该单元换写探针，
    或把判域改成「声明面 ∪ 家族只读可达」——**不要**默默放宽这里的断言。
    """
    tools = _registered_tools()
    states = resolve_units()
    offenders = sorted(
        (u.key, str(u.tool), "未注册" if tools.get(u.tool) is None else "read_only=True")
        for u in UNITS
        if states.get(u.key) and not u.decided_off and u.tool
        and (tools.get(u.tool) is None or getattr(tools.get(u.tool), "read_only", False))
    )
    assert offenders == [], (
        f"可办单元的探针不是写工具 ⇒「按声明面判域」的前提被破坏：{offenders}"
    )


def test_unscoped_render_stays_persona_wide():
    """向后兼容契约：不传 skill_name ⇒ 保持全局投影，且**不出现**「本域不直接办」段。

    既有判据 / 其它调用方按全局口径读（`test_render_contains_every_unit_label`，
    `tests/agent_projection_ledger.json` 登记的就是这个缝）。
    """
    text = render_capability_boundary()
    assert "商品改名" in _segment(text, DIRECT_PREFIX)
    assert ELSEWHERE_PREFIX not in text


def test_zero_write_skills_never_claim_direct_capability():
    """本域不可达的写能力不得出现在「✅ 可直接办理」段（issue #8119）。

    红证（注入式）：把 `render_capability_boundary` 的 skill 过滤摘掉（`scope` 恒 None，
    = 退回 persona 全局投影）⇒ 下面 7 个零写 skill 的 ✅ 段立刻出现商品改价 / 改名 ⇒ 红。

    正向对照（防「干脆不渲染」的假绿）：同一批能力必须出现在「本域不直接办」段，
    既不在 ✅ 也不在该段 ⇒ 红（能力被弄丢同样是错）。
    """
    # 判别力自证：解析器必须**看得见** ✅ 段，否则「✅ 段为空」就是空断言。
    assert "商品改名" in _segment(render_capability_boundary(), DIRECT_PREFIX)

    zero_write = [s for s in _mibao_skill_names() if not _declared_write_tool_names(s)]
    assert len(zero_write) >= 7, f"零写 skill 现取集合异常（应含 order 等 7 个）：{zero_write}"

    states = resolve_units()
    available = [u.label for u in UNITS if states[u.key] and not u.decided_off]
    for skill_name in zero_write:
        text = render_capability_boundary(skill_name=skill_name)
        direct = _segment(text, DIRECT_PREFIX)
        assert not direct, (
            f"{skill_name} 回合的「✅ 可直接办理」仍含本域不可达的能力：{direct} —— "
            f"本轮工具集里没有对应写工具（零写 skill），模型只能空头承诺（#7347 / #7758）"
        )
        elsewhere = _segment(text, ELSEWHERE_PREFIX)
        missing = [label for label in available if label not in elsewhere]
        assert not missing, (
            f"{skill_name} 回合把可办能力弄丢了（既不在 ✅ 也不在「本域不直接办」）：{missing}"
        )
        for label in ("商品改价", "商品改名"):
            assert label in elsewhere, (
                f"{skill_name} 回合未把「{label}」登记为「本域不直接办」（本店已支持、本域不可达）"
            )


def test_product_turn_keeps_own_writes_direct():
    """不得把可办的说成不可办：product 自己的写能力必须留在 ✅ 段（issue #8119）。"""
    text = render_capability_boundary(skill_name="product")
    direct = _segment(text, DIRECT_PREFIX)
    elsewhere = _segment(text, ELSEWHERE_PREFIX)
    for label in ("商品改价", "商品改名", "单规格改价", "批量撤销", "算料口径变更"):
        assert label in direct, f"product 回合把本域可办的「{label}」降格了：{direct}"
        assert label not in elsewhere, f"product 回合把可办的「{label}」列进了「本域不直接办」"
    # 反向对照：别的域的写能力不得混进 product 的 ✅ 段。
    for label in ("通知标记已读", "定时提醒的建与取消"):
        assert label not in direct, f"product 回合的 ✅ 段混进了非本域能力「{label}」"
        assert label in elsewhere, f"product 回合未把非本域能力「{label}」登记为「本域不直接办」"


@pytest.mark.parametrize(
    ("skill_name", "own", "other"),
    [
        ("reminder", "定时提醒的建与取消", "通知标记已读"),
        ("notification", "通知标记已读", "定时提醒的建与取消"),
    ],
)
def test_single_write_skills_scope_their_own_writes(skill_name, own, other):
    """reminder / notification 各只有一把写工具（现取）⇒ ✅ 段只该有自家那条。"""
    text = render_capability_boundary(skill_name=skill_name)
    direct = _segment(text, DIRECT_PREFIX)
    elsewhere = _segment(text, ELSEWHERE_PREFIX)
    assert own in direct, f"{skill_name} 回合丢了本域能力「{own}」：{direct}"
    assert own not in elsewhere
    assert other in elsewhere, f"{skill_name} 回合未把非本域能力「{other}」移到「本域不直接办」"
    assert other not in direct
    assert "商品改名" in elsewhere


#: 交接话术（2026-10-29 用户裁定）：只写「不要承诺代办」不够 —— 商家听到的仍是「我这里办不了」。
#: 该段必须给模型**可执行的下一步** + 一句可直接说的话（示例随单元清单变化，故只钉形态不钉清单）。
HANDOFF_GUIDE = "引导换场景"
HANDOFF_EXAMPLE = "把遮光窗帘改成 199 元"


def test_elsewhere_segment_carries_handoff_wording():
    """➡️ 段必须给出**可执行的下一步**，不能只有「不要在本域承诺代办」这半句。

    红证（注入式）：把 `capability_boundary.py` 里 `ELSEWHERE_PREFIX` 的后缀退回旧形态
    「（对应场景能办；不要在本域承诺代办）：」⇒ 本判据红（逐 skill 报缺哪半句）。

    为什么必须钉住：这一段的存在意义是「本域办不了 → 去对应场景能办，可以这么说」；
    只剩禁令时模型只会复述「我这边办不了」，商家得到的仍是否定答复（2026-10-29 用户裁定
    「说的是别承诺，但没给下一步」）。
    """
    targets = []
    for skill_name in _mibao_skill_names():
        text = render_capability_boundary(skill_name=skill_name)
        line = next((ln for ln in text.splitlines() if ln.startswith(ELSEWHERE_PREFIX)), "")
        if line:
            # 抬头 = 段落前缀 + 括注（单元清单在最后一个「：」之后，`_segment` 的口径）
            targets.append((skill_name, line.rsplit("：", 1)[0]))
    assert targets, (
        "没有任何 mibao skill 渲染出「➡️ 本域不直接办」段 —— 判据面为空（fail-closed："
        "先确认不是整段渲染坏了，再谈交接话术）"
    )
    for skill_name, head in targets:
        missing = [s for s in (HANDOFF_GUIDE, HANDOFF_EXAMPLE) if s not in head]
        assert not missing, (
            f"{skill_name} 回合的「➡️ 本域不直接办」缺交接话术 {missing} —— 只剩「别承诺」时"
            f"商家听到的仍是「我这里办不了」；该段抬头现为：{head[:90]}…"
        )


def test_every_mibao_skill_projects_its_own_scope():
    """类级元守卫：**每个** mibao skill 的边界段都必须按本 skill 的声明面投影（#8119）。

    为什么需要：只要有人把 `base_skill._capability_boundary(skill)` 里的 `skill_name` 漏掉
    （退回 persona 全局投影），所有 skill 都渲染成同一段，而**上面每条实例判据都在自己那一侧
    绿**（= 判据绿、接线没了）。这里从注册表**现取** mibao skill 清单并独立复算 ✅ 段
    ⇒ 以后新增 skill 忘传 skill_name 也当场红。
    """
    from app.graph.skills.base_skill import _capability_boundary

    states = resolve_units()
    for skill_name in _mibao_skill_names():
        declared = declared_tool_names(skill_name) or frozenset()
        expected = [
            u.label for u in UNITS
            if states[u.key] and not u.decided_off and (not u.tool or u.tool in declared)
        ]
        got = _segment(_capability_boundary(skill_name), DIRECT_PREFIX)
        assert got == expected, (
            f"{skill_name}: 能力边界段没有按本 skill 的声明面投影\n"
            f"现取：{got}\n应得：{expected}\n"
            "修法：`_capability_boundary` 必须把 skill_name 传给 render_capability_boundary"
            "（issue #8119）"
        )
    # 反向对照：写面不同的两个域必须渲染不同 —— 漏传 skill_name 时两者逐字相同，本行先红。
    assert _capability_boundary("order") != _capability_boundary("product")
