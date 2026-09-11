# case_ids: AS-003, CH-012, CH-010, OR-014, OR-017
"""
SkillConfig + SkillRegistry 单元测试

覆盖：
- SkillConfig 创建、Prompt 选择、人格检查
- SkillRegistry 注册、查询、意图聚合、路由映射
- 节点函数自动生成
- AgentConfig 注册、角色匹配、直接回复
- AgentRouter 路由逻辑
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.graph.skills.skill_config import SkillConfig, create_skill_config
from app.graph.skills.skill_registry import SkillRegistry
from app.agents.agent_config import (
    AgentConfig,
    register_agent,
    get_agent_config,
    get_all_agent_configs,
    find_agent_for_role,
    reset_agent_configs,
)
from app.agents.agent_router import AgentRouter


# ────────────── SkillConfig 测试 ──────────────


class TestSkillConfig:
    """SkillConfig 数据类测试"""

    def test_basic_creation(self):
        config = SkillConfig(
            name="test",
            domain="test",
            display_name="测试 Skill",
            tool_names=["tool_a", "tool_b"],
            route_keys=["test"],
            intents=["intent_a", "intent_b"],
            system_prompts={"mibao": "米宝 Prompt", "xiaobu": "小布 Prompt"},
            default_persona="mibao",
        )
        assert config.name == "test"
        assert config.tool_names == ["tool_a", "tool_b"]
        assert config.max_iterations == 8  # default

    def test_get_prompt_exact_match(self):
        config = SkillConfig(
            name="t", domain="t", display_name="T",
            system_prompts={"mibao": "MB", "xiaobu": "XB"},
            default_persona="mibao",
        )
        assert config.get_prompt("mibao") == "MB"
        assert config.get_prompt("xiaobu") == "XB"

    def test_get_prompt_fallback_to_default(self):
        config = SkillConfig(
            name="t", domain="t", display_name="T",
            system_prompts={"mibao": "MB"},
            default_persona="mibao",
        )
        # 请求不存在的 persona，fallback 到 default_persona
        assert config.get_prompt("unknown") == "MB"

    def test_get_prompt_fallback_to_any(self):
        config = SkillConfig(
            name="t", domain="t", display_name="T",
            system_prompts={"custom": "CP"},
            default_persona="nonexistent",
        )
        # default_persona 也不存在，fallback 到任意可用 prompt
        assert config.get_prompt("unknown") == "CP"

    def test_get_prompt_empty(self):
        config = SkillConfig(name="t", domain="t", display_name="T")
        assert config.get_prompt("any") == ""

    def test_has_persona(self):
        config = SkillConfig(
            name="t", domain="t", display_name="T",
            system_prompts={"mibao": "MB"},
            default_persona="mibao",
        )
        assert config.has_persona("mibao") is True
        assert config.has_persona("unknown") is True  # fallback to default
        # 如果 default_persona 不在 system_prompts 中
        config2 = SkillConfig(
            name="t2", domain="t2", display_name="T2",
            system_prompts={"custom": "CP"},
            default_persona="nonexistent",
        )
        assert config2.has_persona("custom") is True
        assert config2.has_persona("unknown") is False

    def test_get_all_intents(self):
        config = SkillConfig(
            name="t", domain="t", display_name="T",
            intents=["a", "b", "c"],
        )
        assert config.get_all_intents() == ["a", "b", "c"]

    def test_frozen(self):
        config = SkillConfig(name="t", domain="t", display_name="T")
        with pytest.raises(AttributeError):
            config.name = "changed"


class TestCreateSkillConfig:
    """工厂函数测试"""

    def test_basic_factory(self):
        config = create_skill_config(
            name="order",
            domain="order",
            display_name="订单",
            tool_names=["order_query"],
            mibao_prompt="米宝订单",
            xiaobu_prompt="小布订单",
        )
        assert config.system_prompts == {"mibao": "米宝订单", "xiaobu": "小布订单"}
        assert config.route_keys == ["order"]  # 默认用 domain

    def test_extra_prompts(self):
        config = create_skill_config(
            name="t", domain="t", display_name="T",
            tool_names=[],
            extra_prompts={"supply_chain": "SC Prompt"},
        )
        assert "supply_chain" in config.system_prompts


# ────────────── SkillRegistry 测试 ──────────────


class TestSkillRegistry:
    """SkillRegistry 注册表测试"""

    def _make_config(self, name="test", intents=None, route_keys=None):
        return SkillConfig(
            name=name,
            domain=name,
            display_name=name,
            tool_names=["tool_a"],
            route_keys=route_keys or [name],
            intents=intents or ["intent_a"],
            system_prompts={"mibao": f"{name} prompt"},
            default_persona="mibao",
        )

    def test_register_and_get(self):
        registry = SkillRegistry()
        config = self._make_config("order")
        registry.register(config)
        assert registry.get("order") == config
        assert registry.has("order")
        assert len(registry) == 1

    def test_get_or_raise(self):
        registry = SkillRegistry()
        config = self._make_config("order")
        registry.register(config)
        assert registry.get_or_raise("order") == config
        with pytest.raises(KeyError, match="not_exist"):
            registry.get_or_raise("not_exist")

    def test_get_all(self):
        registry = SkillRegistry()
        registry.register(self._make_config("a"))
        registry.register(self._make_config("b"))
        assert len(registry.get_all()) == 2

    def test_intent_to_route_map(self):
        registry = SkillRegistry()
        registry.register(SkillConfig(
            name="order", domain="order", display_name="订单",
            route_keys=["order"],
            intents=["order_query", "logistics_track"],
            system_prompts={"mibao": "p"},
        ))
        registry.register(SkillConfig(
            name="product", domain="product", display_name="商品",
            route_keys=["product"],
            intents=["product_inquiry"],
            system_prompts={"mibao": "p"},
        ))
        route_map = registry.get_intent_to_route_map()
        assert route_map == {
            "order_query": "order",
            "logistics_track": "order",
            "product_inquiry": "product",
        }

    def test_get_all_intents(self):
        registry = SkillRegistry()
        registry.register(self._make_config("a", intents=["i1", "i2"]))
        registry.register(self._make_config("b", intents=["i2", "i3"]))
        assert registry.get_all_intents() == {"i1", "i2", "i3"}

    def test_get_intents_for_skills(self):
        registry = SkillRegistry()
        registry.register(self._make_config("a", intents=["i1", "i2"]))
        registry.register(self._make_config("b", intents=["i3"]))
        assert registry.get_intents_for_skills(["a"]) == ["i1", "i2"]
        assert registry.get_intents_for_skills(["a", "b"]) == ["i1", "i2", "i3"]

    def test_get_skill_route_map(self):
        registry = SkillRegistry()
        registry.register(SkillConfig(
            name="order", domain="order", display_name="O",
            route_keys=["order"], intents=[], system_prompts={"mibao": "p"},
        ))
        registry.register(SkillConfig(
            name="general", domain="general", display_name="G",
            route_keys=["general"], intents=[], system_prompts={"mibao": "p"},
        ))
        route_map = registry.get_skill_route_map(["order"], "general")
        assert route_map == {
            "direct_reply": "direct_reply",
            "order": "order_skill",
            "general": "general_skill",
        }

    def test_create_node_function(self):
        registry = SkillRegistry()
        config = self._make_config("test")
        node_func = registry.create_node_function(config, "mibao")
        assert node_func.__name__ == "test_node"
        import asyncio
        assert asyncio.iscoroutinefunction(node_func)


# ────────────── AgentConfig 测试 ──────────────


class TestAgentConfig:
    """AgentConfig 配置测试"""

    def setup_method(self):
        reset_agent_configs()

    def test_basic_creation(self):
        config = AgentConfig(
            name="test",
            display_name="测试",
            persona="test_persona",
            skill_names=["order", "product"],
            fallback_skill="general",
            allowed_roles={"admin", "agent"},
            greeting="你好",
        )
        assert config.name == "test"
        assert config.get_all_skill_names() == ["order", "product", "general"]

    def test_all_skill_names_includes_fallback(self):
        config = AgentConfig(
            name="t", display_name="T", persona="p",
            skill_names=["a"], fallback_skill="b",
        )
        assert "a" in config.get_all_skill_names()
        assert "b" in config.get_all_skill_names()

    def test_all_skill_names_no_duplicate_fallback(self):
        config = AgentConfig(
            name="t", display_name="T", persona="p",
            skill_names=["a", "b"], fallback_skill="b",
        )
        names = config.get_all_skill_names()
        assert names.count("b") == 1

    def test_direct_reply(self):
        config = AgentConfig(
            name="t", display_name="T", persona="p",
            direct_replies={"greeting": "你好", "farewell": "再见"},
        )
        assert config.get_direct_reply("greeting") == "你好"
        assert config.get_direct_reply("farewell") == "再见"
        assert config.get_direct_reply("unknown") is None

    def test_allows_role(self):
        config = AgentConfig(
            name="t", display_name="T", persona="p",
            allowed_roles={"admin", "agent"},
        )
        assert config.allows_role("admin") is True
        assert config.allows_role("customer") is False

    def test_allows_role_empty_means_all(self):
        config = AgentConfig(name="t", display_name="T", persona="p")
        assert config.allows_role("anyone") is True

    def test_register_and_get(self):
        config = AgentConfig(name="mibao", display_name="米宝", persona="mibao")
        register_agent(config)
        assert get_agent_config("mibao") == config

    def test_get_nonexistent_raises(self):
        with pytest.raises(KeyError):
            get_agent_config("nonexistent")

    def test_find_agent_for_role(self):
        register_agent(AgentConfig(
            name="mibao", display_name="米宝", persona="mibao",
            allowed_roles={"admin", "agent"},
        ))
        register_agent(AgentConfig(
            name="xiaobu", display_name="小布", persona="xiaobu",
            allowed_roles={"customer"},
        ))
        assert find_agent_for_role("admin") == "mibao"
        assert find_agent_for_role("customer") == "xiaobu"
        assert find_agent_for_role("unknown") is None


# ────────────── AgentRouter 测试 ──────────────


class TestAgentRouter:
    """AgentRouter 路由测试"""

    def setup_method(self):
        reset_agent_configs()
        register_agent(AgentConfig(
            name="mibao", display_name="米宝", persona="mibao",
            allowed_roles={"admin", "agent"},
        ))
        register_agent(AgentConfig(
            name="xiaobu", display_name="小布", persona="xiaobu",
            allowed_roles={"customer"},
        ))

    def test_admin_routes_to_mibao(self):
        router = AgentRouter()
        user = MagicMock(role="admin")
        assert router.route(user) == "mibao"

    def test_agent_routes_to_mibao(self):
        router = AgentRouter()
        user = MagicMock(role="agent")
        assert router.route(user) == "mibao"

    def test_customer_routes_to_xiaobu(self):
        router = AgentRouter()
        user = MagicMock(role="customer")
        assert router.route(user) == "xiaobu"

    def test_unknown_role_fallback(self):
        router = AgentRouter()
        user = MagicMock(role="super_unknown")
        result = router.route(user)
        # 兜底到第一个注册的 Agent
        assert result in ("mibao", "xiaobu")

    def test_no_role_attribute_fallback(self):
        router = AgentRouter()
        user = object()  # 无 role 属性
        result = router.route(user)
        assert result in ("mibao", "xiaobu")


# ────────────── 小布 C 端售后 skill 引导（闭环回归） ──────────────


def test_customer_aftersales_prompt_not_handoff_on_aftersale_requests():
    """真实闭环回归：顾客换货/退货被误路由到 human_handoff。

    customer_aftersales 的 system prompt 必须明确「售后诉求 ≠ 转人工」——
    换货/退货/退款/色差/质量等是 aftersale_create 场景，转人工仅限明确要求/
    情绪激动/涉赔偿。
    """
    from app.graph.skills.customer_aftersales_skill import (
        CUSTOMER_AFTERSALES_TOOLS,
        CUSTOMER_AFTERSALES_SYSTEM_PROMPT,
        CUSTOMER_AFTERSALES_SKILL_CONFIG,
    )

    # 工具列表包含 aftersale_create（核心建单工具）
    assert "aftersale_create" in CUSTOMER_AFTERSALES_TOOLS
    assert "human_handoff" in CUSTOMER_AFTERSALES_TOOLS

    # prompt 明确售后诉求应走 aftersale_create
    assert "aftersale_create" in CUSTOMER_AFTERSALES_SYSTEM_PROMPT
    # 「售后诉求 ≠ 转人工」边界
    assert "售后诉求 ≠ 转人工" in CUSTOMER_AFTERSALES_SYSTEM_PROMPT
    # 换货/退货/色差/质量 = 创建场景，不是转人工理由
    assert "换货/退货/退款/维修/色差/质量问题" in CUSTOMER_AFTERSALES_SYSTEM_PROMPT
    # 已发货（shipped）等已确认及以上订单可正常创建退/换货工单（状态门禁允许）
    # —— 真实闭环回归：AI 看到"已发货"误判不能售后而转人工
    assert "已发货" in CUSTOMER_AFTERSALES_SYSTEM_PROMPT
    assert "shipped" in CUSTOMER_AFTERSALES_SYSTEM_PROMPT
    # 转人工触发边界仍保留
    assert "转人工" in CUSTOMER_AFTERSALES_SYSTEM_PROMPT

    # skill 配置正确挂载（供 registry 注册）
    assert CUSTOMER_AFTERSALES_SKILL_CONFIG.name == "customer_aftersales"
    assert CUSTOMER_AFTERSALES_SKILL_CONFIG.default_persona == "xiaobu"


# ────────────── 不变式：确认门禁可达性（CH-012 根因回归） ──────────────


def test_confirmed_write_tools_require_interact_in_same_skill():
    """不变式（C 端）：Skill 绑定了需确认的写工具时，必须同时暴露 `interact`。

    根因（CH-012 退换货实证 2026-09-11）：`base_skill._requires_confirmation` 在拦截
    未确认写操作时，返回 `confirmation_required` 并**要求 LLM 调用
    `interact(component=confirm)` 展示确认卡片**。而 `customer_aftersales` 的
    tool_names 里没有 `interact`（`aftersale_create` 却标了
    `requires_confirmation=True`）—— 门禁给出的补救路径在该 Skill 内**不可达**：
        ① 写工具 `aftersale_create` 只能依赖上一轮「口头确认」侥幸放行，弹卡确认路径不存在；
        ② 轮内 LLM 拿到「请调用 interact」的指引却无此工具 → 反复重试/放弃；
        ③ 唯一出口退化为 `human_handoff`（实测 CH-012 tools=['customer_order_query',
           'human_handoff', 'aftersale_query']，0/2 建单）。
    这是「prompt 写了、工具没给」型缺陷，单看 prompt 断言（本文件上一条用例）测不出来。

    作用域刻意限定为 **C 端（persona=xiaobu）**：C 端设计基线是「低学历点选友好」，
    写操作必须走卡片而非让顾客打字确认。B 端同类问题（staff/settings/data 共 6 处）
    另案跟踪，不在此用例内混同，避免把 B 端改动风险夹带进 C 端修复。
    """
    from app.graph.skills.skill_registry import get_skill_registry
    from app.tools.registry import get_tool_registry

    full_registry = get_tool_registry()
    violations: list[str] = []

    for config in get_skill_registry().get_all():
        if "xiaobu" not in (config.system_prompts or {}):
            continue
        tool_names = list(config.tool_names or [])
        if not tool_names:
            continue
        for name in tool_names:
            tool = full_registry.get_tool(name)
            if tool is None:
                continue
            needs_confirm = getattr(tool, "destructive", False) or getattr(
                tool, "requires_confirmation", False
            )
            if needs_confirm and "interact" not in tool_names:
                violations.append(f"{config.name} 绑定需确认写工具 {name} 但未暴露 interact")

    assert not violations, (
        "以下 C 端 Skill 的弹卡确认路径不可达（写工具只能靠口头确认侥幸放行）：\n  "
        + "\n  ".join(violations)
    )


def test_customer_aftersales_exposes_order_lookup_and_interact():
    """customer_aftersales 必须具备「定位订单 + 弹卡确认」的最小闭环工具。

    C 端顾客不会报订单号（说「第一笔订单」），且建单前必须弹 confirm 卡：
    - `customer_order_query`：把「第一笔订单」解析成 order_id（其 prompt 已假定可查）
    - `interact`：confirm 卡（门禁要求）+ choice 卡（售后类型/原因）
    """
    from app.graph.skills.customer_aftersales_skill import CUSTOMER_AFTERSALES_TOOLS

    assert "customer_order_query" in CUSTOMER_AFTERSALES_TOOLS
    assert "interact" in CUSTOMER_AFTERSALES_TOOLS
    # 既有能力不回归
    assert "aftersale_create" in CUSTOMER_AFTERSALES_TOOLS
    assert "aftersale_query" in CUSTOMER_AFTERSALES_TOOLS
    assert "human_handoff" in CUSTOMER_AFTERSALES_TOOLS


def test_customer_skills_only_bind_tools_customer_role_can_use():
    """不变式（C 端）：小布 Skill 绑定的工具，`customer` 角色必须都能用。

    根因（CH-012/OR-014/OR-017/CH-010 实测 2026-09-11，run 34620594324）：
    `ValidateInputTool.allowed_roles = ["admin","agent","tenant_admin"]` —— **不含 customer**
    → 小布的 `customer_order` / `customer_aftersales` 都绑了它，但顾客调用一律返回
    `权限不足`。而 `base_skill` 的「确认-执行链」依赖 `validate_input` **成功**才持久化
    「已校验待执行」状态：

        if tool_name == "validate_input" and result_dict.get("success"):  → 落 pending

    于是 C 端写流程的 confirm 永远换不来执行 —— `order_create` / `aftersale_create`
    在整轮评测里**一次都没成功调用过**（CI 轨迹：`failed=validate_input!权限不足`，
    随后 `human_handoff` 兜底）。

    与本文件上一条 `interact` 不变式同族：**「Skill 绑了，但角色用不了」= 死能力**。
    绑了却用不了的工具既浪费工具位（挤占 LLM 的注意力），又让流程在关键节点静默失败。
    本用例把「绑定的工具对本人可用」升级为全 C 端不变式。
    """
    from app.graph.skills.skill_registry import get_skill_registry
    from app.tools.base import ToolContext
    from app.tools.registry import get_tool_registry

    skill_registry = get_skill_registry()
    tool_registry = get_tool_registry()
    customer_ctx = ToolContext(
        tenant_id=1, user_id="debug_customer_1", session_id="s", role="customer",
    )

    violations: list = []
    checked = 0
    for config in skill_registry.get_all():
        if "xiaobu" not in (config.system_prompts or {}):
            continue
        for name in (config.tool_names or []):
            tool = tool_registry.get_tool(name)
            if tool is None:
                violations.append(f"{config.name} 绑定了未注册工具 {name}")
                continue
            checked += 1
            if not tool.check_permission(customer_ctx):
                violations.append(
                    f"{config.name} 绑定 {name}，但 allowed_roles={list(tool.allowed_roles)} "
                    f"不含 customer → 顾客调用必返回「权限不足」"
                )

    assert checked >= 10, f"仅检查了 {checked} 个工具绑定 —— 解析疑似失效（测试会空转）"
    assert not violations, (
        "以下 C 端 Skill 绑定了顾客**用不了**的工具（死能力，流程会在关键节点静默失败）：\n  "
        + "\n  ".join(violations)
    )


def test_customer_order_binds_validate_input_for_confirm_execute_chain():
    """C 端下单必须能走通「校验 → confirm → 执行」链（OR-014/OR-017/CH-010 实证）

    CI 轨迹（run 34622425044，OR-014）：
        R6 tools=interact data=interact(component=confirm title=请核对订单信息 …)
        R7 tools=-        ← 顾客已回「确认」，却**没有任何工具调用** → order_create 从未执行

    而 `customer_aftersales` 走通了同一条链（CH-012 本轮转 ✅：R1 卡片 → R3 validate_input
    → R4 aftersale_create 成功）。差别就在 **aftersales 绑了 `validate_input`、
    `customer_order` 没绑**：

        base_skill：if tool_name == "validate_input" and result_dict.get("success") → 落
        「已校验待执行」状态；下一轮顾客确认时直接执行写工具，不再从零重走。

    没有这一步，顾客回「确认」后 LLM 手上没有"待执行的动作与参数"，只能重新追问
    （实测回复要验证码/再问一遍），写操作永远不发生。
    """
    from app.graph.skills.customer_order_skill import CUSTOMER_ORDER_TOOLS

    assert "order_create" in CUSTOMER_ORDER_TOOLS, "回归：下单能力本体"
    assert "validate_input" in CUSTOMER_ORDER_TOOLS, (
        "customer_order 未绑定 validate_input —— confirm 后无法落地「已校验待执行」状态，"
        "顾客回「确认」时没有可执行动作，order_create 不会发生（OR-014 R7 实证）"
    )


def test_customer_order_prompt_requires_validate_before_confirm():
    """prompt 必须显式要求 confirm 卡片之前先 validate_input（否则 LLM 不会主动调）"""
    from app.graph.skills.customer_order_skill import CUSTOMER_ORDER_SYSTEM_PROMPT

    assert "validate_input" in CUSTOMER_ORDER_SYSTEM_PROMPT, (
        "prompt 未提及 validate_input —— 绑了工具但 LLM 不会用（「工具给了、话没说」）"
    )
    # 必须绑定到 confirm 之前这个时序语义，不能只是随口提一句
    assert "confirm" in CUSTOMER_ORDER_SYSTEM_PROMPT
