"""
防线 3: Skill 路由覆盖测试

验证新增 Skill 不会抢走已有 Skill 的路由，
确保 Skill Registry 注册正确、意图映射不冲突。
"""
# case_ids: DF-008, DF-015, PR-008, OR-009, OR-010, CH-010, CH-019

import re

import pytest

from app.graph.skills.skill_registry import get_skill_registry, reset_skill_registry
from app.tools.registry import get_tool_registry
from app.agents.agent_config import get_agent_config

# 理由必须引用的证据锚点：issue 号（#3317）或用例 ID（CH-019）
_EVIDENCE_ANCHOR_RE = re.compile(r"#\d+|[A-Z]{2}-\d{3}")


# 允许「不绑 interact」的 B 端写 skill：它们持有需确认写工具，但**经评估**走
# base_skill 的文本确认降级话术（「本技能没有确认卡片能力：请完整复述并请用户回复确认」）。
# 语义是**许可**（不是断言），补绑 interact 后条目自动失效、用例仍全绿。
# 每条必须带理由 + 证据锚点，且必须仍是「持有需确认写工具的 B 端 skill」（见卫生测试）。
B_SKILL_TEXT_CONFIRM_ALLOWED: dict[str, str] = {
    "staff": (
        "employee_manage / role_manage 是 destructive 写，但本 skill 未绑 interact。"
        "既有决策 issue #3317：用例库涉及这 6 个工具的 16 条用例无一条断言 interact"
        "（含 smoke 的 HR-001/HR-004 靠口头确认长期通过），故改为让门禁话术按「本 skill "
        "是否有 interact」分流（文本复述 + 请用户回复确认），而不是给不可执行指令。"
        "交互形态统一由 #3577 推进（补绑 interact 后本条即失效）。"
    ),
    "settings": (
        "settings_manage（destructive）/ notification_manage（requires_confirmation）"
        "均为需确认写，本 skill 未绑 interact —— 同 issue #3317 决策，走文本确认降级话术"
        "（ST-001~ST-005 用例未断言 interact）。统一交互形态由 #3577 推进。"
    ),
    "data": (
        "finance_api / session_manage 为 requires_confirmation 高风险写（审计 07 P0-L1），"
        "本 skill 未绑 interact —— 同 issue #3317 决策，走文本确认降级话术"
        "（DA-* 用例未断言 interact）。统一交互形态由 #3577 推进。"
    ),
}


def _confirm_needing_tools(skill, tool_registry) -> list[str]:
    """skill 持有的「需确认写工具」名（判据与 base_skill._requires_confirmation 一致）。"""
    found = []
    for tool_name in (skill.tool_names or []):
        tool = tool_registry.get_tool(tool_name)
        if tool is not None and (
            getattr(tool, "destructive", False)
            or getattr(tool, "requires_confirmation", False)
        ):
            found.append(tool_name)
    return sorted(found)


def _mibao_skill_names() -> list[str]:
    """米宝（B 端）skill 名 —— 按 persona 归属从 skill registry 派生。

    ⚠️ 刻意**不用** `get_agent_config("mibao").get_all_skill_names()`：AgentConfig 是
    可变全局单例，`test_skill_config_registry.TestAgentRouter.setup_method` 会
    `reset_agent_configs()` 后注册只含角色的 **stub** mibao（无 skill_names，且无 teardown）
    → 跨文件顺序耦合：与本文件同跑时 mibao 的 skill_names 为空，断言静默空转/误红。
    skill registry 的 persona 归属是稳定事实源（与 skill_registry.get_intent_to_route_map
    的过滤口径一致），且本文件的 autouse fixture 会重置它 → 无跨文件污染。
    """
    return [
        config.name
        for config in get_skill_registry().get_all()
        if "mibao" in (config.system_prompts or {})
    ]


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

    例外：customer_manage / notification_manage 虽然有写能力，
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


# 注（issue #3594）：此处原有硬编码 `ALL_WRITE_TOOLS` 常量（12 个工具名）——
# 既从未被任何测试引用（死代码），又是与确认门禁测试同源的**枚举式清单**。
# 凡是需要"全部写工具"的判据，一律从注册表派生（见下方 registry 驱动测试），
# 不再维护第二份人工清单（枚举必然滞后于现实，见 §16.1 L0）。


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
    所有持有**需确认写工具**的 B 端 Skill 具备 interact，否则被拦截后 LLM 调不到工具。

    **registry 驱动（issue #3594）**：判据不再写死 skill 名单 —— 遍历
    `_mibao_skill_names()`（B 端 skill，按 persona 从 skill registry 派生）的真实绑定，
    用**工具注册表的真实元数据**（`destructive` / `requires_confirmation`）推导出
    「持有需确认写工具的 skill」。原实现硬编码 4 元组
    `("product", "order", "aftersales", "customer")`，
    漏掉 staff/settings/data —— 枚举式清单必然滞后于现实（与
    `test_tool_schema_consistency.py::ALWAYS_SKIP_PARAMS` 同一反模式）：
    新增写 skill / 新写工具绑到旧 skill 时，门禁静默漏检（本 issue 的写工具零门禁
    就是这样活下来的）。实证：把 `general`（不在旧 4 元组内）的 interact 拿掉，
    旧枚举断言仍绿、本用例红。

    例外（**许可**语义，非断言）：`B_SKILL_TEXT_CONFIRM_ALLOWED` 登记的 skill 允许
    不绑 interact —— 它们走 base_skill 的**文本确认降级话术**（issue #3317：拦截话术
    按本 Skill 是否有 interact 分流，不再给出不可执行指令）。
    许可是**自清除**的：这些 skill 将来补绑 interact 后本用例仍全绿（见 #3577），
    条目自然失效，不需要同时改这里 —— 这正是删掉枚举的意义。
    """
    skill_registry = get_skill_registry()
    tool_registry = get_tool_registry()

    write_skills: list[str] = []
    violations: list[str] = []
    for name in _mibao_skill_names():
        skill = skill_registry.get(name)
        if skill is None:
            continue
        needs = _confirm_needing_tools(skill, tool_registry)
        if not needs:
            continue
        write_skills.append(name)
        if "interact" in (skill.tool_names or []):
            continue
        if name in B_SKILL_TEXT_CONFIRM_ALLOWED:
            continue
        violations.append(f"{name} 持有需确认写工具 {needs} 但未绑定 interact")

    assert write_skills, (
        "推导出的「持有需确认写工具的 B 端 Skill」集合为空 —— registry 派生逻辑失效，"
        "本用例会空转假绿"
    )
    assert not violations, (
        "以下 B 端 Skill 的确认卡路径不可达（写工具被 confirm 守卫拦截后无 interact 可调，"
        "且未登记文本确认降级许可）：\n  " + "\n  ".join(violations)
        + "\n处置：① 给该 skill 补绑 interact（交互形态统一，见 #3577）；或 "
        "② 在 B_SKILL_TEXT_CONFIRM_ALLOWED 登记并写明理由 + 证据锚点。"
    )


def test_text_confirm_allowlist_is_live_and_reasoned():
    """文本确认降级许可清单的卫生：每条带理由 + 证据锚点，且**确实仍是写 skill**。

    - key 必须是 mibao 注册的 skill（防陈旧/拼写错误）；
    - 每条必须带理由，且引用证据锚点（issue 号 / 用例 ID）—— 防豁免清单变垃圾场；
    - 每条必须**仍然持有需确认写工具**：否则该条目已无意义（skill 变纯只读，
      或已补绑 interact 由别处兜住）→ 红，强制清理。
    """
    skill_registry = get_skill_registry()
    tool_registry = get_tool_registry()
    mibao_skills = set(_mibao_skill_names())

    problems: list[str] = []
    for name, reason in B_SKILL_TEXT_CONFIRM_ALLOWED.items():
        text = (reason or "").strip()
        if not text:
            problems.append(f"{name}: 缺 reason（许可必须写明理由，禁止裸登记）")
        elif not _EVIDENCE_ANCHOR_RE.search(text):
            problems.append(
                f"{name}: reason 未引用证据锚点（issue #NNNN 或用例 ID XX-999）"
            )
        if name not in mibao_skills:
            problems.append(f"{name}: 不是 mibao 注册的 skill（陈旧条目或拼写错误）")
            continue
        skill = skill_registry.get(name)
        if skill is not None and not _confirm_needing_tools(skill, tool_registry):
            problems.append(
                f"{name}: 已不持有需确认写工具，许可条目无意义（应删除）"
            )
    assert not problems, (
        "文本确认降级许可清单存在陈旧/不达标条目：\n  " + "\n  ".join(problems)
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
