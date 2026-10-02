# case_ids: MC-069
"""**路由目的地必须真的在图上**（issue #6044 缺陷 C）—— `KeyError: 'settings'` 的类级固化。

## 病（2026-10-02 B 端真实 LLM 评测，ST-002/ST-004/ST-005 四个会话各崩一次）

```
[astream_chat] Error session=sess_51af8f1f02b34dc9 error=KeyError: 'settings' | agent=mibao
用户输入「看看通知」
  …
  File "…/langgraph/graph/_branch.py", line 203, in <listcomp>
    r if isinstance(r, Send) else self.ends[r] for r in result
KeyError: 'settings'
```

根因：`route_by_intent` 返回 `'settings'`，而米宝图的条件边 `ends` 里**没有**这个目的地 —
`settings` skill 已按 issue #5247 从 `MIBAO_CONFIG.skill_names` **解绑**（系统设置/通知配置不进 B 端
对话面），但 `settings_skill.py` 的文件仍在 SkillRegistry 里（**保留它是有意的**：删掉会让路由/账本
口径漂移）⇒ `SkillRegistry.get_intent_to_route_map()` 的 **persona 过滤**（`settings_skill` 有
`mibao` persona）**不等于绑定过滤**，`notification` / `system_settings` / `ai_config` 三个意图
照样映射到 `'settings'` ⇒ 条件边解析目的地时抛 `KeyError` ⇒ 整轮 SSE 崩。

## 本文件锁什么

| # | 判据 | 会怎么红 |
|---|---|---|
| 1 | **映射表的目的地都在图上**：`_get_intent_to_route(agent)` 的每个值 ∈ 该 agent 图上真实存在的节点 | 有人再让一个未绑定 skill 的 route_key 进映射表 ⇒ 红并具名 |
| 2 | **`route_by_intent` 的返回值都在图上**（边界输入：未绑定的 pending skill / `action=handoff_offer` 在米宝上 / notification 意图） | 崩溃点本身复现 ⇒ 红 |
| 3 | **未绑定 route_key 改判到 fallback**：注册表里、但不在该 agent `skill_names` 里的 skill 的 route_key ⇒ 落 `fallback_skill`，且**打进日志**（可归因） | 静默丢弃 / 仍返回未绑定 key ⇒ 红 |
| 4 | **对照组**：绑定得上的 route_key 照旧原样返回（不许"一刀切全兜底"把路由打死） | 修法过度 ⇒ 红 |

判据 3 用的是**真注册表 + patch 一个不在任何 agent 里的 skill**，不依赖「settings 永远不绑定」这个
一次性事实 —— 下一个被解绑的 skill 同样会红。

## 边界（照实登记，§19.1）

- 判据 1/2 只覆盖 `mibao` / `xiaobu` 两个**已登记** agent（`agents/agents/**` 里新增 agent 时需一起加，
  `build_agent_graph` 的节点集合是判据的来源，不是硬编码清单）。
- `route_by_intent` 的 `pending_skill` 分支**有意保留**「回到上一轮 skill」的既有语义；本判据只保证
  **图上存在的** pending skill 能回去 —— `pending_skill` 若含图上没有的名字，那是会话状态面的事
  （不在本判据射程，见 PR body 的未覆盖项）。
- 本判据**不改**任何门禁的通过条件、不新增豁免。
"""

from unittest.mock import patch

import pytest

#: 逐个 agent 过；新增 agent 时在这里加一行（图节点集合由 builder 现取，不硬编码）。
AGENTS = ("mibao", "xiaobu")


def _route_map(agent_type: str) -> dict:
    """复刻 `build_agent_graph` 的 `skill_route_map`（route_key / skill name ⇒ 节点名）。

    与 builder 的差别只有一处：builder 在 for 循环里"后注册的覆盖先注册的"，这里同样按
    `get_all_skill_names()` 的顺序覆盖 —— 结果与 `graph.add_conditional_edges` 的 `ends` 一致。
    """
    from app.agents.agent_config import get_agent_config
    from app.graph.skills.skill_registry import get_skill_registry

    agent_config = get_agent_config(agent_type)
    registry = get_skill_registry()
    route_map = {"direct_reply": "direct_reply"}
    if agent_type == "xiaobu":
        route_map["handoff_offer"] = "handoff_offer"
    for skill_name in agent_config.get_all_skill_names():
        config = registry.get(skill_name)
        if not config:
            continue
        node_id = f"{skill_name}_skill"
        for route_key in config.route_keys:
            route_map[route_key] = node_id
        route_map[skill_name] = node_id
    return route_map


def _destinations(agent_type: str) -> set:
    """条件边**接受**的目的地全集 = `skill_route_map` 的 key ∪ value。

    - key = route_key（意图映射返回的形态）/ skill name（`pending_interact_skill` 返回的形态）；
    - value = 节点名（两者最终都映射到它）。
    """
    route_map = _route_map(agent_type)
    return set(route_map) | set(route_map.values())


def _nodes(agent_type: str) -> set:
    """图上**真实存在**的节点名（`_route_map` 的 value 必须全部落在这里）。"""
    from app.graph.builder import build_agent_graph

    return set(build_agent_graph(agent_type).get_graph().nodes.keys())


class TestIntentMapDestinationsExistOnTheGraph:
    """判据 1：映射表（意图 → 路由 key）的每个目的地都在该 agent 的图上。"""

    @pytest.mark.parametrize("agent_type", AGENTS)
    def test_every_mapped_destination_is_a_node(self, agent_type):
        from app.graph.nodes import _get_intent_to_route

        destinations = _destinations(agent_type)
        dangling = {intent: key for intent, key in _get_intent_to_route(agent_type).items()
                    if key not in destinations}
        assert dangling == {}, (
            f"agent={agent_type} 的意图映射里有**图上不存在**的目的地：{dangling} —— "
            "条件边解析目的地时会抛 KeyError（issue #6044 缺陷 C）"
        )


class TestRouteMapMatchesTheCompiledGraph:
    """判据 0（自证坐标）：`_route_map` 复刻的节点名必须与**真图**一致 —— 否则上面两条会被架空。"""

    @pytest.mark.parametrize("agent_type", AGENTS)
    def test_route_map_values_are_real_nodes(self, agent_type):
        route_map = _route_map(agent_type)
        nodes = _nodes(agent_type)
        assert set(route_map.values()) <= nodes, (
            f"agent={agent_type} 的 route_map 指向图上不存在的节点："
            f"{sorted(set(route_map.values()) - nodes)}（复刻口径漂移 ⇒ 判据失效）"
        )


class TestRouteByIntentNeverReturnsADanglingDestination:
    """判据 2：`route_by_intent` 的返回值恒在图上（含边界输入）。"""

    @staticmethod
    def _state(agent_type: str, **overrides) -> dict:
        state = {
            "agent_type": agent_type,
            "messages": [],
            "intent_result": {"intent": "general", "confidence": 0.9, "source": "rule"},
            "route_decision": {"action": "full_agent"},
            "pending_interact_skill": "",
            "session_id": "sess_route_dest_test",
        }
        state.update(overrides)
        return state

    @pytest.mark.parametrize("agent_type", AGENTS)
    @pytest.mark.parametrize("intent", ["notification", "system_settings", "ai_config",
                                        "dashboard", "order_query", "general"])
    def test_known_intents_land_on_a_node(self, agent_type, intent):
        from app.graph.nodes import route_by_intent

        route_map = _route_map(agent_type)
        state = self._state(agent_type, intent_result={"intent": intent, "confidence": 0.95,
                                                      "source": "rule"})
        destination = route_by_intent(state)
        assert destination in _destinations(agent_type), (
            f"agent={agent_type} intent={intent} ⇒ route_by_intent 返回 {destination!r}"
            "（图上没有该目的地 ⇒ LangGraph 必抛 KeyError）"
        )

    @pytest.mark.parametrize("agent_type", AGENTS)
    def test_unbound_pending_skill_is_not_propagated(self, agent_type):
        """未绑定的 pending skill（按 #5247，`settings` 是现成的一例）不许被原样返回。"""
        from app.graph.nodes import route_by_intent

        state = self._state(agent_type, pending_interact_skill="settings")
        destination = route_by_intent(state)
        assert destination in _destinations(agent_type), (
            f"agent={agent_type} 的 pending_skill='settings' ⇒ route_by_intent 返回 {destination!r}"
            "（图上没有该目的地 ⇒ 与 2026-10-02 实测的 KeyError 同型）"
        )

    @pytest.mark.parametrize("agent_type", AGENTS)
    @pytest.mark.parametrize("pending", ["settings", "order", "general", "order_skill", "ghost"])
    def test_any_pending_skill_lands_on_a_node(self, agent_type, pending):
        """pending skill 的**任何**取值（绑定的 / 解绑的 / 图节点名 / 不存在的）都不许越出目的地集。"""
        from app.graph.nodes import route_by_intent

        state = self._state(agent_type, pending_interact_skill=pending,
                            route_decision={"action": "route_with_llm"},
                            intent_result={"intent": "general", "confidence": 0.5, "source": "default"})
        destination = route_by_intent(state)
        assert destination in _destinations(agent_type), (
            f"agent={agent_type} pending_skill={pending!r} ⇒ route_by_intent 返回 {destination!r}"
            "（图上没有该目的地 ⇒ LangGraph 必抛 KeyError）"
        )

    @pytest.mark.parametrize("agent_type", AGENTS)
    def test_handoff_offer_only_where_the_node_exists(self, agent_type):
        """`action=handoff_offer` 只在有该节点的 agent 上返回它（米宝图上没有 ⇒ 不许返回）。"""
        from app.graph.nodes import route_by_intent

        state = self._state(agent_type, route_decision={"action": "handoff_offer"})
        destination = route_by_intent(state)
        assert destination in _destinations(agent_type), (
            f"agent={agent_type} action=handoff_offer ⇒ route_by_intent 返回 {destination!r}"
            "（图上没有该目的地）"
        )


class TestUnboundRouteKeysFallBackToTheFallbackSkill:
    """判据 3/4：未绑定 ⇒ fallback（可归因）；绑定得上 ⇒ 原样（不许一刀切）。"""

    @staticmethod
    def _ghost_config():
        from app.graph.skills.skill_config import SkillConfig

        return SkillConfig(
            name="ghost",
            domain="ghost",
            display_name="幽灵域",
            tool_names=[],
            route_keys=["ghost"],
            intents=["ghost_intent"],
            system_prompts={"mibao": "ghost"},
            default_persona="mibao",
        )

    def test_unbound_route_key_is_remapped_to_fallback_and_logged(self):
        """注册表里有、但不在本 agent `skill_names` 里的 skill ⇒ 落 fallback，且日志里看得出来。"""
        from app.agents.agent_config import get_agent_config
        from app.graph import nodes as nodes_mod

        agent_config = get_agent_config("mibao")
        assert "ghost" not in agent_config.skill_names, "本判据要的是**未绑定**的 skill"
        nodes_mod._INTENT_TO_ROUTE.clear()
        try:
            # `_get_intent_to_route` 是**函数内 import** ⇒ 要 patch 定义处
            # （`app.agents.agent_config.get_agent_config`），patch `nodes.xxx` 无效。
            with patch("app.agents.agent_config.get_agent_config", return_value=agent_config), \
                    patch("app.graph.skills.skill_registry.get_skill_registry") as registry:
                registry.return_value.get_intent_to_route_map.return_value = {"ghost_intent": "ghost"}
                # `agent_config` 得用**真**那份（`get_all_skill_names()` 要有真绑定面），
                # 注册表替身只为 `ghost` 这个未绑定 skill 存在。
                registry.return_value.get.side_effect = (
                    lambda name: self._ghost_config() if name == "ghost" else None)
                mapping = nodes_mod._get_intent_to_route("mibao")
        finally:
            nodes_mod._INTENT_TO_ROUTE.clear()

        assert mapping["ghost_intent"] == agent_config.fallback_skill, (
            "未绑定的 route_key 必须改判到 fallback skill（builder 一定会建那个节点）"
            f"，实际 = {mapping['ghost_intent']!r}"
        )

    def test_bound_route_keys_are_untouched(self):
        """对照组：`order` 绑定在米宝上 ⇒ `order_query` 必须照旧回到 `order`。"""
        from app.graph.nodes import _get_intent_to_route

        mapping = _get_intent_to_route("mibao")
        assert mapping["order_query"] == "order", (
            "绑定得上的 route_key 不许被一刀切兜底掉（那会把路由打死）"
        )
        assert mapping["greeting"] == "direct_reply"
        assert mapping["general"] == "general"
