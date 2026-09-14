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

import re

import os as _os
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


@pytest.fixture(autouse=True)
def _isolate_global_agent_registry():
    """每个用例结束后把**全局 Agent 注册表**恢复成真实状态（issue #3569）。

    病灶（另一包实证 + 本包复核）：本文件的 `TestAgentConfig.setup_method`（:245）与
    `TestAgentRouter.setup_method`（:327）都会先 `reset_agent_configs()`（清空**真实**注册表），
    再注册两个**没有 skill_names** 的 stub，却**没有 teardown** → 泄漏到同文件后续类、
    以及后续测试文件。读全局注册表的代码（`app/graph/builder.py:42`、
    `app/graph/nodes.py:153/565`、`app/agents/customer_service_agent.py:127`）拿到 stub 后
    `skill_names=[]` → 遍历 skill 的循环体一次都不执行 → **静默空转**（用例照绿，什么都没测）。

    实证（修复前，同一份代码只换文件顺序）：
        pytest tests/test_skill_config_registry.py tests/test_dual_agent.py  → 4 failed
        pytest tests/test_dual_agent.py tests/test_skill_config_registry.py  → 64 passed

    恢复方式取"重新注册内置 Agent"（`app/agents/agents/__init__.py::register_all_agents`），
    而不是自造 stub —— 与模块导入时的真实注册路径同一份真值。
    """
    yield
    from app.agents.agents import register_all_agents

    reset_agent_configs()
    register_all_agents()


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
    写操作必须走卡片而非让顾客打字确认。

    B 端（staff/settings/data 共 6 处）**经证据评估后决定不补 `interact`**（issue #3317）：
    用例库里涉及这 6 个工具的 16 条用例**没有一条**断言 `interact`（含 smoke 的
    HR-001/HR-004，它们靠**口头确认**长期通过）→ 补工具等于改变 B 端交互形态，
    收益不明而回归面覆盖 105 条只能在面向生产的手动评测里验证。
    改为修真正的缺陷：确认门禁的话术**按本 Skill 是否有 `interact` 分流**
    （见 test_graph_skills.TestConfirmGateGuidance），不再给出不可执行指令。
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


def test_order_create_description_enforces_processing_item_ask():
    """`order_create` 的工具描述必须含「加工项先询问」铁律（OR-017 抖动治理）

    CI 实证（run 34622425044 ✅ / 34626024229 ❌，同代码同用例）：OR-017 断言
    `interact(component=choice, multiSelect=true)`，而 agent 时而直接跳到 confirm 卡
    ——「加工项主动询问」这条能力目前只写在 system prompt 里，**约 1/3 的轮次不生效**。

    工具描述是**每轮都随工具一起送进上下文**的，比长 system prompt 里的某一条更靠前、
    更稳定（LLM 选工具时必然读到）。故先在工具描述里落成"前置铁律 + 反例"。
    若仍抖动，下一步是**代码兜底**（选品含加工项却直接发 confirm 卡时，代码先补发
    choice 卡并抑制该 confirm），不在本提交内做。
    """
    from app.tools.order_create import OrderCreateTool

    desc = OrderCreateTool.description
    assert "多选" in desc or "multiSelect=true" in desc, "未要求用多选 choice 卡询问加工项"
    assert "加工项" in desc and "interact" in desc, "未把加工项询问写成交互卡动作"
    assert "漏收加工费" in desc or "金额错误" in desc, "未说明后果（LLM 需要后果才守规矩）"
    assert "product_search" in desc, "未提醒不得凭列表断言无加工项（历史误宣）"


class TestSkillPromptToolsetConsistency:
    """Skill 提示词不得指示**该 Skill 工具集里没有的工具**（issue #3361）。

    实证：`customer_quote` 的提示词写着「顾客确认下单后：用 interact(form) 下发收货信息
    表单…我帮您安排」，而它的工具集只有 `curtain_calc / product_detail / product_search /
    interact` —— **没有 order_create**。模型照提示词一路走到调用下单工具 → `tool_not_found`
    ×2 → 转人工，订单从未创建（CI run 34686905546 的 OR-017 R7/R8，顾客侧表现为"下单失败"）。

    这类缺陷的形态是「提示词承诺了做不到的事」，静态可查、后果严重（流程死路），
    所以在这里做成契约：提示词里出现的**下单动作**必须有对应工具，否则必须显式写明
    「本技能不做这件事，交回 X 流程」。
    """

    def _cfg(self, name):
        from app.graph.skills.skill_registry import get_skill_registry
        reg = get_skill_registry()
        return reg.get_or_raise(name)

    def test_quote_skill_does_not_promise_ordering(self):
        cfg = self._cfg("customer_quote")
        prompt = (cfg.system_prompts or {}).get("xiaobu") or ""
        tools = set(cfg.tool_names or [])
        assert "order_create" not in tools, "报价 skill 的工具集不含 order_create（前提变了要重写本测试）"
        # 不得指示"下发收货信息表单/自行安排下单"（做不到的承诺）
        assert "下发收货信息表单" not in prompt, (
            "报价 skill 提示词又在指示「下发收货信息表单」—— 本技能没有下单能力，"
            "模型会走到调用 order_create → tool_not_found → 转人工（订单永不创建）"
        )
        # 必须显式交回下单流程，并给出顾客可复制的切换话术
        assert "我要下单" in prompt and "没有下单能力" in prompt, (
            "报价 skill 未显式声明「本技能没有下单能力 + 交回下单流程」，"
            "顾客报价后下单会走进死路"
        )

    def test_quote_skill_tools_unchanged(self):
        """工具集是路由/提示词契约的依据，变更须有意识（本测试防顺手扩大）。"""
        cfg = self._cfg("customer_quote")
        assert set(cfg.tool_names or []) == {
            "curtain_calc", "product_detail", "product_search", "interact"
        }


class TestPromptToolPromiseInvariant:
    """提示词承诺的**工具**必须在技能工具集里（issue #3365，两次踩到的同一类缺陷）。

    实证（两次）：
      ① `customer_quote` 提示词写「顾客确认下单后用 interact(form) 收收货信息…我帮您安排」，
         但工具集**没有 order_create** → 模型走到调用下单工具 → `Tool not found: order_create`
         → 反复重试 → 转人工，订单永不创建（已修：提示词改为交回下单流程）。
      ② `customer_order` 提示词写「商品详情铁律：confirm 之前必须先调 product_detail」，
         但工具集**没有 product_search/product_detail** → 下单场景既查不了详情、接地自动驾驶
         也无从代跑 → 接地闸门拦了 17 次 order_create、流程死锁（已修：补工具）。

    判定必须**只看"指令句"**：提示词里提到工具名的场景有三类，只有第一类是"承诺"——
      1) 指令「必须先调 product_detail」「请调用 interact(...)」 → **承诺**（工具必须存在）；
      2) 否定「不可用的工具：order_create…不要声称能执行」 → 不是承诺（反而要求模型别用）；
      3) 描述「金额来自已确认的算料报价（curtain_calc 结果）」 → 不是承诺（是别处产出的结果）。
    不区分就会误报（首版实测：general 的否定清单、customer_order 的算料描述都被误判）。
    """

    KNOWN_TOOLS = (
        "product_search", "product_detail", "order_create", "aftersale_create",
        "customer_order_query", "customer_logistics_track", "customer_address_query",
        "aftersale_query", "validate_input", "interact", "human_handoff",
        "curtain_calc", "knowledge_search", "order_query", "product_manage",
        "order_manage", "inventory_manage", "employee_manage", "role_manage",
        "settings_manage",
    )
    _NEGATIVE = ("不可用", "不要", "不能", "无法", "禁止", "切勿", "不得")
    _DESCRIPTIVE = ("结果", "来自", "产出", "由其它技能", "由其他技能")
    _INSTRUCTION = ("调用", "先调", "再调", "必须", "请用", "使用", "执行", "走")

    @classmethod
    def promised_tools(cls, prompt: str) -> set:
        """从提示词里提取"被承诺的工具"（只看指令句）。"""
        out = set()
        for raw in re.split(r"[。；\n]", prompt or ""):
            seg = raw.strip()
            if not seg:
                continue
            if any(neg in seg for neg in cls._NEGATIVE):
                continue
            # 词边界匹配：`order_query` 不得因是 `customer_order_query` 的子串而命中
            # （首版用裸 `in` 实测误报：C 端技能被指"缺 order_query"）
            named = {t for t in cls.KNOWN_TOOLS
                     if re.search(rf"(?<![A-Za-z0-9_]){re.escape(t)}(?![A-Za-z0-9_])", seg)}
            if not named:
                continue
            if not any(ins in seg for ins in cls._INSTRUCTION):
                continue
            if any(des in seg for des in cls._DESCRIPTIVE) and not any(
                    ins in seg for ins in ("调用", "先调", "再调", "请用")):
                continue
            out |= named
        return out

    def _skills(self):
        from app.graph.skills.skill_registry import get_skill_registry
        return [c for c in get_skill_registry().get_all() if c.tool_names]

    def test_detector_classifies_promise_negative_and_description(self):
        """检测器自身的三分法（防误报/漏报）：指令=承诺；否定/描述=不算。"""
        assert self.promised_tools("confirm 之前必须先调 product_detail 取真实价格。") == {"product_detail"}
        assert self.promised_tools("不可用的工具：product_manage、order_create，不要声称能执行。") == set()
        assert self.promised_tools("金额来自已确认的算料报价（curtain_calc 结果）。") == set()
        # 描述性提及但**没有**"结果/来自"这类标记：靠"必须含指令动词"兜住（否则误报）
        assert self.promised_tools("报价口径：curtain_calc。") == set()
        assert self.promised_tools("参考字段：order_query。") == set()
        assert self.promised_tools("请调用 interact(component=confirm) 展示确认卡。") == {"interact"}

    def test_prompts_do_not_promise_missing_tools(self):
        bad = []
        for cfg in self._skills():
            prompt = " ".join((cfg.system_prompts or {}).values())
            if not prompt:
                continue
            tools = set(cfg.tool_names or [])
            missing = self.promised_tools(prompt) - tools
            if missing:
                bad.append(f"{cfg.name}: 提示词点名但工具集缺失 {sorted(missing)}")
        assert not bad, (
            "以下技能的提示词**指令**里点名了它没有的工具（模型会撞墙并陷入循环）：\n  "
            + "\n  ".join(bad)
        )

    def test_customer_order_has_grounding_tools(self):
        """具体锁定：C 端下单必须具备商品检索/详情（其提示词的"商品详情铁律"要求）。"""
        from app.graph.skills.skill_registry import get_skill_registry
        cfg = get_skill_registry().get_or_raise("customer_order")
        assert {"product_search", "product_detail"} <= set(cfg.tool_names or []), (
            "customer_order 缺商品工具 → 下单接地铁律无法执行（OR-014 死锁实证）"
        )


class TestLayerPromptToolWhitelist:
    """L3/L5 资产层的工具名也必须在技能工具集内（issue #3569）。

    缺口：上面的 `test_prompts_do_not_promise_missing_tools` 只扫
    `SkillConfig.system_prompts`（**L4 内联**），而**领域规则 L3**
    （`references/prompts/{skill}.md`）与 **few-shot L5**
    （`references/EXAMPLES-{skill}.md`，位置最末、行为影响最大）**从未被这条契约覆盖**。
    实证（issue #3569）：`EXAMPLES-customer_product.md` 写「先查看知识: knowledge_search」，
    而 customer_product 工具集只有 `product_search/product_detail/interact`；
    `EXAMPLES-customer_general.md` 写「order_query(action=list)」而该 skill 只绑
    `customer_order_query` —— 都是"提示词教模型调不存在的工具"，静态可查却长期无人拦。

    判定口径（沿用 `promised_tools` 的三分法：只认"指令"，不认否定与描述）：
    - L4 内联：交给 `promised_tools`（指令动词驱动）；
    - L3 领域规则：**`tool(` / `tool（` 调用形态**即指令；
    - L5 few-shot：`→ `/`✅ ` 开头的**动作轨迹行**（few-shot 里轨迹就是指令）或调用形态；
    - 显式 `❌ ` 反例行、以及句内出现否定词（不可用/不要/不能/无法/禁止/切勿/不得）的句子跳过
      —— 它们正是"教模型别这么干"，允许出现该技能没有的工具名。
    """

    # 已冻结的存量越界（不在本 issue 修复范围内）；每条都必须写明原因 + 归属 issue。
    # 目标：C 端（本 issue 负责的域）为 0；B 端这几条要改属于行为/产品裁定，另案处理。
    KNOWN_EXEMPTIONS = {
        # (skill, tool): 原因
        ("staff", "interact"):
            "issue #3317（OPEN）：staff L3/L5 承诺 interact(confirm) 确认卡，但工具集无 interact。"
            "补 interact vs 收紧 requires_confirmation 是**安全护栏取舍，须产品裁定**",
    }

    # tests/ -> ai-agent-service/ -> app/graph/skills/references
    _REF_DIR = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        "app", "graph", "skills", "references",
    )
    _CALL_FORM = re.compile(r"(?<![A-Za-z0-9_])[a-z_]+[\(（]")

    @classmethod
    def _universe(cls) -> set:
        """全部 skill 工具集的并集 = 真正存在的工具名全集（与 registry 注册集一致）。"""
        from app.graph.skills.skill_registry import get_skill_registry
        out = set()
        for cfg in get_skill_registry().get_all():
            out |= set(cfg.tool_names or [])
        return out

    @classmethod
    def _layer_tools(cls, text: str, *, fewshot: bool, universe: set) -> set:
        """抽取一组文本里"被指示调用"的工具名。"""
        out = set()
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("❌"):
                continue
            is_trace = fewshot and (line.startswith("→") or line.startswith("✅"))
            if not (is_trace or cls._CALL_FORM.search(line)):
                continue
            # 句级否定过滤：与 promised_tools 同口径（_NEGATIVE）
            for seg in re.split(r"[。；]", line):
                if any(neg in seg for neg in TestPromptToolPromiseInvariant._NEGATIVE):
                    continue
                for tool in universe:
                    if re.search(rf"(?<![A-Za-z0-9_]){re.escape(tool)}(?![A-Za-z0-9_])", seg):
                        out.add(tool)
        return out

    @classmethod
    def _read_l3(cls, skill: str) -> str:
        path = _os.path.join(cls._REF_DIR, "prompts", f"{skill}.md")
        if not _os.path.exists(path):
            return ""
        text = open(path, encoding="utf-8").read()
        # L3 首部 YAML frontmatter 由 base_skill 剥离（base_skill.py:562-566），不进 prompt → 不参与判定
        if text.startswith("---"):
            end = text.find("---", 3)
            text = text[end + 3:] if end > 0 else text
        return text

    @classmethod
    def _read_l5(cls, skill: str) -> str:
        path = _os.path.join(cls._REF_DIR, f"EXAMPLES-{skill}.md")
        return open(path, encoding="utf-8").read() if _os.path.exists(path) else ""

    def _violations(self) -> dict:
        from app.graph.skills.skill_registry import get_skill_registry
        universe = self._universe()
        bad = {}
        for cfg in get_skill_registry().get_all():
            if not cfg.tool_names:
                continue
            tools = set(cfg.tool_names)
            found = set()
            for label, text, fewshot in (
                ("L3", self._read_l3(cfg.name), False),
                ("L5", self._read_l5(cfg.name), True),
            ):
                for tool in self._layer_tools(text, fewshot=fewshot, universe=universe) - tools:
                    found.add((tool, label))
            if found:
                bad[cfg.name] = found
        return bad

    def test_l3_l5_do_not_name_missing_tools(self):
        bad = []
        for skill, found in sorted(self._violations().items()):
            unexpected = sorted(
                f"{tool}({label})" for tool, label in found
                if (skill, tool) not in self.KNOWN_EXEMPTIONS
            )
            if unexpected:
                bad.append(f"{skill}: L3/L5 指示了工具集里没有的工具 → {unexpected}")
        assert not bad, (
            "以下技能的**领域规则 L3 / few-shot L5**里指示了它没有的工具"
            "（模型会调用不存在的工具 → 反复重试/转人工，流程死路）：\n  "
            + "\n  ".join(bad)
            + "\n若确属「教模型别这么干」的反例，请把该行标 ❌ 或用否定词表述。"
        )

    def test_known_exemptions_are_still_needed(self):
        """豁免项不得腐烂：技能工具集若已补齐该工具，必须删掉对应豁免（防"永久白名单"）。"""
        violations = self._violations()
        stale = [
            f"{skill}/{tool}"
            for (skill, tool) in self.KNOWN_EXEMPTIONS
            if not any(t == tool for t, _ in violations.get(skill, set()))
        ]
        assert not stale, (
            "以下豁免已失效（该技能的 L3/L5 不再越界，或工具已补齐）—— 请删除 KNOWN_EXEMPTIONS 对应项："
            f"{stale}"
        )


class TestGlobalAgentRegistryNotPolluted:
    """金丝雀：本文件的 stub 注册用例不得把**全局** Agent 注册表留在 stub 状态（issue #3569）。

    放在文件**末尾** —— pytest 按文件内定义顺序执行，所以这里跑在
    `TestAgentConfig`（:245 reset + 注册 stub）与 `TestAgentRouter`（:327 同型）之后。
    一旦那两个类又变成「只 setup 无 teardown」，这里立刻红；此前它泄漏还会让**别的测试文件**
    静默空转（实证：`pytest test_skill_config_registry.py test_dual_agent.py` 4 failed）。
    """

    def test_real_agent_configs_survive(self):
        for name in ("mibao", "xiaobu"):
            cfg = get_agent_config(name)
            assert cfg.skill_names, (
                f"{name} 的全局注册被无 skill_names 的测试 stub 覆盖 → 后续测试文件里读全局"
                f"注册表的代码（builder.py:42 / nodes.py:153,565 / customer_service_agent.py:127）"
                f"会 skill_names=[] 静默空转。检查 test 级 teardown 恢复是否还在"
                f"（_isolate_global_agent_registry）。"
            )
        # stub 的 fallback 是默认值 "general"，真实小布是 "customer_general" —— 用它区分真值
        assert get_agent_config("xiaobu").fallback_skill == "customer_general", (
            "全局 xiaobu 配置不是真实声明（被测试 stub 覆盖）"
        )
