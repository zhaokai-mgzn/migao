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
        assert config.max_iterations == 5  # default

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
