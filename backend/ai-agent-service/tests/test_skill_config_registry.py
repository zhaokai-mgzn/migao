# case_ids: AS-003, CH-012, CH-010, OR-014, OR-017, HR-005, ST-003, ST-005, FN-001, DA-004
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


# ────────────── 不变式：确认门禁可达性（CH-012 根因回归；#3317 全 Skill 放开） ──────────────

# 显式豁免清单（键 = Skill 名，值 = 豁免理由）——**禁止用宽泛 skip 让不变式形同虚设**
# （先例教训：`test_tool_schema_consistency.py` 的 ALWAYS_SKIP_PARAMS 恰好排除了缺陷字段）。
# 豁免只允许一种形态：**纯只读 Skill**（0 个需确认写工具 → 永远走不到门禁的补救话术）。
# 两条测试都会机械校验豁免的"诚实性"：① 理由必须非空；② 被豁免 Skill 当前**确实**用不上
# 该豁免（它若后来绑上写工具/在 prompt 里承诺确认卡，豁免立即失效 → 测试转红），
# 防"陈旧豁免"退化成永久后门。
_CONFIRM_GATE_INTERACT_EXEMPT: dict = {}
_CONFIRM_CARD_PROMISE_INTERACT_EXEMPT: dict = {}

# 「prompt 承诺确认卡」的措辞标记（发确认卡的唯一手段就是 interact(component=confirm)）
_CONFIRM_CARD_MARKERS = ("确认卡", "确认卡片", "component=confirm")

# #3317 的 6 处工具绑定（B 端）——逐一锁定为回归锚点
_ISSUE_3317_BINDINGS = {
    "staff": ("employee_manage", "role_manage"),
    "settings": ("settings_manage", "notification_manage"),
    "data": ("finance_api", "session_manage"),
}

# 显式豁免台账（键 = Skill 名，值 = 不绑 `interact` 的理由）：**没绑 `interact` 的 Skill 必须
# 在这里逐条记录在案**，且理由必须成立（只读、prompt 不承诺确认卡）。台账由
# `test_interact_absent_only_for_recorded_read_only_skills` 机械校验——新 Skill 若漏绑
# `interact`，测试立刻红并要求"要么补绑、要么在此写理由"，不允许静默漏改。
_READ_ONLY_INTERACT_SKILLS = {
    "knowledge": (
        "B 端知识库：只绑 knowledge_search / processing_item_query（均为只读），"
        "tool_names 里 0 个需确认写工具，自身 prompt（prompts/knowledge.md 不存在、"
        "EXAMPLES-knowledge.md）也不承诺确认卡 → 结构上走不到确认门禁的补救话术"
    ),
    "customer_knowledge": (
        "C 端知识库：只绑 knowledge_search（只读），0 个需确认写工具，"
        "EXAMPLES-customer_knowledge.md 不承诺确认卡 → 同上"
    ),
}


def _skill_prompt_surface(config) -> str:
    """Skill **自身**的 prompt 表面（内联 system_prompts + base_skill 按 Skill 注入的文件）。

    `base_skill._build_system_prompt` 的组装层次：`base/identity.md` + `base/principles.md` +
    共享 `PROMPT-rules.md` + `prompts/{skill}.md` + inline + `EXAMPLES-{skill}.md`。
    共享层（尤其 PROMPT-rules「破坏性写必须先展示确认卡片」）是**每个 Skill 都注入**的公共
    铁律，计进来会让只读 Skill 也"承诺"确认卡 → 不变式恒真、形同虚设（本包要防的假绿形态）。
    故这里只取"按 Skill 区分"的那几层，与 base_skill 的解析保持同一目录来源。
    """
    import pathlib

    from app.graph.skills.base_skill import _ref_dir

    ref = pathlib.Path(_ref_dir)
    parts = list((config.system_prompts or {}).values())
    for path in (ref / "prompts" / f"{config.name}.md", ref / f"EXAMPLES-{config.name}.md"):
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _confirm_gated_tools(config, tool_registry) -> list:
    """该 Skill 绑定的「需确认写工具」名称（destructive 或 requires_confirmation）。"""
    gated = []
    for name in (config.tool_names or []):
        tool = tool_registry.get_tool(name)
        if tool is None:
            continue
        if getattr(tool, "destructive", False) or getattr(tool, "requires_confirmation", False):
            gated.append(name)
    return gated


def _assert_exemptions_are_honest(exempt: dict, granted: list) -> None:
    """豁免必须带非空理由，且只对"当前确实用不上"的 Skill 生效（防陈旧豁免/宽泛 skip）。"""
    for name, reason in exempt.items():
        assert isinstance(reason, str) and reason.strip(), (
            f"豁免清单里的 {name} 没有写理由 —— 无理由的豁免等于宽泛 skip"
        )
        assert name in granted, (
            f"豁免清单里的 {name} 已不成立（它当前并不需要该豁免）—— 请从清单移除"
        )


def test_confirmed_write_tools_require_interact_in_same_skill():
    """不变式（**全 Skill**，2026-09-14 起）：绑定需确认写工具的 Skill 必须暴露 `interact`。

    根因（CH-012 退换货实证 2026-09-11）：`base_skill._requires_confirmation` 在拦截
    未确认写操作时，返回 `confirmation_required` 并**要求 LLM 调用
    `interact(component=confirm)` 展示确认卡片**。若该 Skill 的 tool_names 里没有
    `interact`（而它绑了 `requires_confirmation`/`destructive` 写工具），门禁给出的补救
    路径在该 Skill 内**不可达**：
        ① 写工具只能依赖上一轮「口头确认」侥幸放行，弹卡确认路径不存在；
        ② 轮内 LLM 拿到「请调用 interact」的指引却无此工具 → 反复重试/放弃；
        ③ 唯一出口退化为 `human_handoff`（实测 CH-012 tools=['customer_order_query',
           'human_handoff', 'aftersale_query']，0/2 建单）。
    这是「prompt 写了、工具没给」型缺陷，单看 prompt 断言（本文件上一条用例）测不出来。

    📌 决策记录（2026-09-14 产品裁定，**推翻**下列历史决定）：
      本用例原作用域刻意限定 C 端（`if "xiaobu" not in config.system_prompts: continue`），
      并在注释里记下「B 端 staff/settings/data 共 6 处经证据评估后决定**不补** `interact`」
      （issue #3317：相关 16 条用例无一条断言 interact，补工具会改变 B 端交互形态）。
      **该决定已被产品裁定推翻**，裁定原话：
        「我的要求是**写操作应该是安全的**，我们在 **admin-api 层面做了限制**，
          我希望**交互形态是统一的**。」
      ⇒ ① **采用 A 路径**：给缺 `interact` 的写入型 Skill 补绑（staff/settings/data，
            覆盖 #3317 的 6 处工具绑定）；② **禁止 B 路径**（收紧/移除
            `requires_confirmation`）—— 那会降低写操作安全性，与铁律冲突；写操作的安全边界
            由 **admin-api 层**承担，agent 侧确认卡属**交互一致性**，不是唯一安全网；
            ③ B 端与 C 端走**同一套**确认卡机制。
      故作用域放开到**全 Skill**；豁免只剩"纯只读 Skill"（见 `_CONFIRM_GATE_INTERACT_EXEMPT`，
      必须逐条写理由）。

    与门禁话术分支的关系：`base_skill` 的补救话术按「本 Skill 是否绑 `interact`」分流
    （无 interact → 退化为文本复述，见 test_graph_skills.TestConfirmGateGuidance）。
    配置层统一后，**该分支的"无 interact"支路对所有已注册 Skill 不可达** —— 本用例即其
    常量/断言驱动的守护（分支本体在 base_skill.py，属其它包所有权，本包不改；保留它是对
    "非注册 tool_names 动态子集"的防御性兜底，不再承担已注册 Skill 的话术分流）。
    """
    from app.graph.skills.skill_registry import get_skill_registry
    from app.tools.registry import get_tool_registry

    full_registry = get_tool_registry()
    skills = [c for c in get_skill_registry().get_all() if c.tool_names]
    exempt_granted: list[str] = []
    violations: list[str] = []
    checked = 0

    for config in skills:
        gated = _confirm_gated_tools(config, full_registry)
        if config.name in _CONFIRM_GATE_INTERACT_EXEMPT:
            if not gated:
                exempt_granted.append(config.name)
            continue
        if not gated:
            continue
        checked += 1
        if "interact" not in (config.tool_names or []):
            violations.append(
                f"{config.name} 绑定需确认写工具 {'/'.join(gated)} 但未暴露 interact"
            )

    _assert_exemptions_are_honest(_CONFIRM_GATE_INTERACT_EXEMPT, exempt_granted)
    # 厚度守卫：防 registry/工具注册解析失效导致不变式空转（假绿）
    assert checked >= 10, (
        f"仅检查了 {checked} 个绑定需确认写工具的 Skill —— 解析疑似失效（不变式空转）"
    )
    assert not violations, (
        "以下 Skill 的弹卡确认路径不可达（写工具只能靠口头确认侥幸放行）：\n  "
        + "\n  ".join(violations)
    )


def test_issue_3317_six_bindings_now_expose_interact():
    """#3317 的 6 处（staff×2 / settings×2 / data×2）逐一锁定：补绑后交互形态统一。

    同时锁住**禁止的 B 路径**：这 6 个工具的 `requires_confirmation`/`destructive` 安全
    语义不得被下调（写操作安全由 admin-api 层承担，但 agent 侧门禁本身也是安全网，
    不得为"话术好写"而摘除）。
    """
    from app.graph.skills.skill_registry import get_skill_registry
    from app.tools.registry import get_tool_registry

    reg = get_skill_registry()
    tools = get_tool_registry()

    for skill_name, gated_names in _ISSUE_3317_BINDINGS.items():
        cfg = reg.get_or_raise(skill_name)
        tool_names = set(cfg.tool_names or [])
        assert "interact" in tool_names, (
            f"{skill_name} 未绑 interact —— 门禁「请调用 interact(component=confirm)」"
            f"对该 Skill 是不可执行指令（#3317）"
        )
        for name in gated_names:
            assert name in tool_names, f"{skill_name} 的既有写工具 {name} 被移除（回归）"
            tool = tools.get_tool(name)
            assert tool is not None and (
                getattr(tool, "destructive", False)
                or getattr(tool, "requires_confirmation", False)
            ), (
                f"{skill_name}.{name} 的需确认标记被下调 —— 禁止 B 路径"
                f"（安全语义不得为交互话术让路）"
            )


def test_confirm_gate_guidance_takes_card_branch_for_unified_skills():
    """交互形态统一的**直接**断言：门禁话术对全 Skill 落在「卡片支路」而非「文本兜底」。

    `base_skill` 的补救话术按「本 Skill 的工具子集里有没有 `interact`」分流
    （`skill_registry.get_tool("interact") is not None`）：
      绑 → 「请调用 interact(component=confirm) 发确认卡」（可执行，本包统一后的形态）
      未绑 → 「完整复述 + 口头确认」（文本兜底，交互形态不统一的旧形态）
    这里用**与 base_skill 完全相同的判据**（`create_skill_registry(cfg.tool_names)`）断言：
    所有绑了需确认写工具的 Skill 都落在卡片支路 —— 即"分流"不再由运行时探测决定交互形态，
    而由配置 + 本文件的不变式锁定（分支本体在 base_skill.py，属其它包所有权，本包不改）。
    """
    from app.graph.skills.base_skill import create_skill_registry
    from app.graph.skills.skill_registry import get_skill_registry
    from app.tools.registry import get_tool_registry

    tools = get_tool_registry()
    fallback: list[str] = []
    for config in get_skill_registry().get_all():
        if not config.tool_names or not _confirm_gated_tools(config, tools):
            continue
        subset = create_skill_registry(list(config.tool_names))
        if subset.get_tool("interact") is None:
            fallback.append(config.name)

    assert not fallback, (
        f"以下 Skill 的门禁话术会落到「文本复述 + 口头确认」兜底支路（交互形态不统一）："
        f"{fallback} —— 补绑 interact 或登记豁免理由"
    )


def test_prompt_promising_confirm_card_requires_interact():
    """不变式（全 Skill）：Skill 自身 prompt 承诺「确认卡」→ 必须绑 `interact`（承诺=能力）。

    这是 `TestPromptToolPromiseInvariant` 的姊妹条：那条只扫**内联** prompt 里点名的工具，
    而 B 端的确认卡承诺写在 `references/prompts/{skill}.md`（staff.md「立即调
    interact(component=confirm) 发确认卡片」/ settings.md「先校验参数 + 确认卡 + 用户确认后
    执行」/ data.md「结束会话需确认卡」）—— 只查内联 prompt 查不到，**#3317 的 6 处正是从
    这道缝里漏出去的**（prompt 承诺了、工具集里没有）。故本用例按 Skill 聚合"自身 prompt
    表面"（内联 + base_skill 注入的 prompts/EXAMPLES 文件）做承诺 ↔ 能力一致性断言。
    """
    from app.graph.skills.skill_registry import get_skill_registry

    skills = [c for c in get_skill_registry().get_all() if c.tool_names]
    promising: list[str] = []
    exempt_granted: list[str] = []
    violations: list[str] = []

    for config in skills:
        surface = _skill_prompt_surface(config)
        if not any(marker in surface for marker in _CONFIRM_CARD_MARKERS):
            continue
        promising.append(config.name)
        if config.name in _CONFIRM_CARD_PROMISE_INTERACT_EXEMPT:
            exempt_granted.append(config.name)
            continue
        if "interact" not in (config.tool_names or []):
            violations.append(
                f"{config.name} 的 prompt 承诺「确认卡」但工具集没有 interact（承诺不可执行）"
            )

    _assert_exemptions_are_honest(_CONFIRM_CARD_PROMISE_INTERACT_EXEMPT, exempt_granted)
    # 厚度守卫：检测标记必须真的扫到承诺，否则不变式空转（假绿）
    assert len(promising) >= 8, (
        f"只扫到 {promising} 个承诺确认卡的 Skill —— 检测标记疑似失效（不变式空转）"
    )
    assert not violations, (
        "以下 Skill 的 prompt 承诺了确认卡，却给不出下发卡片的工具：\n  "
        + "\n  ".join(violations)
    )


def test_interact_absent_only_for_recorded_read_only_skills():
    """显式豁免台账：没绑 `interact` 的 Skill 必须逐条记录在案，且理由必须成立。

    作用：把「交互形态统一」落成**可复核的清单**，而不是靠"没人提就没问题"。
    ① 未记录在 `_READ_ONLY_INTERACT_SKILLS` 却缺 `interact` 的 Skill → 红（要么补绑，要么写理由）；
    ② 台账里的 Skill 若其实有需确认写工具 / prompt 承诺确认卡 → 红（理由不成立，豁免无效）；
    ③ 理由为空 → 红（无理由的豁免 = 宽泛 skip，本仓库已有先例教训）。
    """
    from app.graph.skills.skill_registry import get_skill_registry
    from app.tools.registry import get_tool_registry

    tools = get_tool_registry()
    skills = [c for c in get_skill_registry().get_all() if c.tool_names]

    for name, reason in _READ_ONLY_INTERACT_SKILLS.items():
        assert isinstance(reason, str) and reason.strip(), f"{name} 的豁免没有写理由"
        cfg = get_skill_registry().get_or_raise(name)
        assert "interact" not in (cfg.tool_names or []), (
            f"{name} 已绑 interact —— 请把它从只读豁免台账移除（豁免已过时）"
        )
        assert not _confirm_gated_tools(cfg, tools), (
            f"{name} 现在绑了需确认写工具 —— 只读豁免不成立，必须补绑 interact"
        )
        assert not any(m in _skill_prompt_surface(cfg) for m in _CONFIRM_CARD_MARKERS), (
            f"{name} 的 prompt 现在承诺确认卡 —— 只读豁免不成立，必须补绑 interact"
        )

    unrecorded = sorted(
        c.name for c in skills
        if "interact" not in (c.tool_names or []) and c.name not in _READ_ONLY_INTERACT_SKILLS
    )
    assert not unrecorded, (
        f"以下 Skill 没绑 interact 却没记录豁免理由：{unrecorded}\n"
        f"交互形态统一（#3577）：要么补绑 interact，要么在 _READ_ONLY_INTERACT_SKILLS "
        f"写清「结构上不需要」的理由"
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
