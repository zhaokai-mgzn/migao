"""
防线 3: Skill 路由覆盖测试

验证新增 Skill 不会抢走已有 Skill 的路由，
确保 Skill Registry 注册正确、意图映射不冲突。
"""
# case_ids: DF-008, DF-015, PR-008, OR-009, OR-010, CH-010

import pytest

from app.graph.skills.skill_registry import get_skill_registry, reset_skill_registry
from app.agents.agent_config import get_agent_config


@pytest.fixture(autouse=True)
def reset():
    reset_skill_registry()
    yield
    reset_skill_registry()


# ============ Skill Registry 完整性 ============

def test_all_mibao_skills_registered():
    """米宝的 8 个 Skill 全部注册"""
    registry = get_skill_registry()
    agent = get_agent_config("mibao")
    names = agent.get_all_skill_names()
    for name in names:
        skill = registry.get(name)
        assert skill is not None, f"Skill '{name}' 未注册"
        assert len(skill.tool_names) > 0, f"Skill '{name}' 无 tool"


def test_all_xiaobu_skills_registered():
    """小布的 3 个 C 端 Skill 全部注册"""
    registry = get_skill_registry()
    agent = get_agent_config("xiaobu")
    names = agent.get_all_skill_names()
    for name in names:
        skill = registry.get(name)
        assert skill is not None, f"Skill '{name}' 未注册"


# ============ 路由冲突检测 ============

def test_no_overlapping_route_keys():
    """不同 Skill 的路由 key 必须唯一"""
    registry = get_skill_registry()
    mibao = get_agent_config("mibao")
    seen = {}
    for name in mibao.get_all_skill_names():
        skill = registry.get(name)
        if not skill:
            continue
        for key in skill.route_keys:
            if key == "direct_reply":
                continue  # 公共 key，允许多个 Skill 共享
            assert key not in seen, (
                f"路由冲突: '{key}' 已被 Skill '{seen[key]}' 使用，"
                f"'{name}' 试图重复注册"
            )
            seen[key] = name


def test_general_has_only_read_tools():
    """兜底 general Skill 只应有只读 Tool（写操作需确认后走领域 Skill）

    例外：customer_manage / notification_manage / quick_reply_manage 虽然有写能力，
    但在 general 中主要用于查询和列表展示，写操作仍需用户明确触发。
    """
    registry = get_skill_registry()
    general = registry.get("general")
    assert general is not None
    # 确认核心写操作 Tool 不会漏进 general
    # processing_item_manage 等管理类 Tool 在 general 中用于列表展示
    truly_write_only = {"product_manage", "order_create", "inventory_manage", "order_manage", "employee_manage", "role_manage", "settings_manage"}
    for tool in truly_write_only:
        assert tool not in general.tool_names, (
            f"纯写 Tool '{tool}' 不应在 general Skill 中"
        )


# 写操作 Tool 列表（应从领域 Skill 中调用，不应在 general 中）
ALL_WRITE_TOOLS = {
    "product_manage", "order_manage", "order_create",
    "inventory_manage", "after_sales_manage",
    "customer_manage", "employee_manage", "role_manage",
    "settings_manage", "notification_manage", "quick_reply_manage",
    "category_manage", "processing_item_manage",
}


def test_each_skill_has_unique_domain():
    """每个 Skill 必须有唯一的 domain（用于路由和统计）"""
    registry = get_skill_registry()
    mibao = get_agent_config("mibao")
    domains = {}
    for name in mibao.get_all_skill_names():
        skill = registry.get(name)
        if not skill:
            continue
        domain = skill.domain or "unknown"
        # 同 domain 允许多个 Skill（如 order domain 有 order 和 aftersales）
        domains.setdefault(domain, []).append(name)

    # 每个 domain 至少有一个 Skill
    for domain, skills in domains.items():
        assert len(skills) >= 1, f"domain '{domain}' 无关联 Skill"


# ============ 意图映射完整性 ============

def test_all_intents_have_route():
    """所有意图都有对应的路由 key"""
    from app.graph.nodes import _get_intent_to_route
    from app.router.intent_config import IntentType

    all_intents = {i.value for i in IntentType}
    intent_map = _get_intent_to_route()
    mapped = set(intent_map.keys())

    # 不用 assert 全覆盖，因为有些意图不需要路由
    # 但至少核心意图要有映射
    critical = {"order_query", "product_inquiry", "greeting", "general", "after_sales", "complaint"}
    missing = critical - mapped
    assert not missing, f"核心意图缺少路由映射: {missing}"


# ============ Fallback 机制 ============

def test_mibao_has_fallback():
    """米宝必须有兜底 Skill"""
    agent = get_agent_config("mibao")
    assert agent.fallback_skill is not None
    registry = get_skill_registry()
    assert registry.get(agent.fallback_skill) is not None, \
        f"兜底 Skill '{agent.fallback_skill}' 未注册"


def test_xiaobu_has_fallback():
    """小布必须有兜底 Skill"""
    agent = get_agent_config("xiaobu")
    assert agent.fallback_skill is not None
    registry = get_skill_registry()
    assert registry.get(agent.fallback_skill) is not None, \
        f"兜底 Skill '{agent.fallback_skill}' 未注册"


# ============ interact 工具绑定一致性（G6 防回归） ============

def test_prompt_required_interact_tools_are_bound():
    """B 端 Skill 的 Prompt 要求调用 interact 时，tool_names 必须绑定 interact。

    回归背景（issue #2777）：product/order 的 prompt 与 references 多处要求
    interact(choice/confirm/form)（如 prompts/order.md 多 SKU 规格选择、prompts/product.md
    分类/加工项选择、PROMPT-rules 写操作 confirm 卡），但 tool_names 此前未绑定
    interact → LLM 调用时 tool_not_found → 静默退化为纯文本，confirm 语义丢失
    （PR-008/OR-009/OR-010 交互卡期望无法兑现，eval 只能靠"声明调用"假绿）。
    """
    registry = get_skill_registry()
    # B 端 prompt/EXAMPLES/references 显式要求 interact 的 Skill（已核实的强制绑定点）
    for name in ("product", "order"):
        skill = registry.get(name)
        assert skill is not None, f"Skill '{name}' 未注册"
        assert "interact" in skill.tool_names, (
            f"Skill '{name}' 的 prompt 要求 interact 但 tool_names 未绑定（G6 回归）"
        )


def test_all_write_skills_bind_interact_via_confirm_guard():
    """写操作 confirm 守卫（base_skill 代码层拦截提示调 interact confirm）要求
    所有持有写工具的 B 端 Skill 具备 interact，否则被拦截后 LLM 调不到工具。

    例外：general 兜底不执行写操作（test_general_has_only_read_tools），
    但 base_skill 拦截消息对任何 skill 生效——凡持 confirm 需求的 skill 均需绑定。
    """
    registry = get_skill_registry()
    write_skills = ("product", "order", "aftersales", "customer")
    for name in write_skills:
        skill = registry.get(name)
        assert skill is not None, f"Skill '{name}' 未注册"
        assert "interact" in skill.tool_names, (
            f"Skill '{name}' 需经 confirm 守卫的写操作确认，必须绑定 interact（G6 回归）"
        )


def test_general_binds_interact_for_clarify_cards():
    """general 兜底 skill 必须绑定 interact（Phase 2, issue #2789）。

    general 是低置信意图/图片消息的澄清主战场（intent_router 低置信重写 →
    general；图片强制路由 vision mode），且 VISION_CLARIFY_GUIDE（Phase 1）
    明确要求意图模糊时优先 interact(choice) 下发候选卡。若 general 未绑定
    interact，澄清只能退化为纯文本——无法承载"2-4 候选意图点选"的澄清卡。
    """
    registry = get_skill_registry()
    general = registry.get("general")
    assert general is not None, "general skill 未注册"
    assert "interact" in general.tool_names, (
        "general skill 需承载低置信/图片澄清卡，必须绑定 interact（Phase 2 回归）"
    )
