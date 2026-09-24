# case_ids: MC-005, MC-006, CH-003, MC-010
"""模糊输入 → **可点击的猜测**（issue #5329，提问引导「类型 2」）。

判据来源：`docs/agent-feature-design.md` §九「提问引导」的类型 2（P0：对话层「猜测式追问」）。

## 问题（本文件守什么）

B 端用户「不知道自己想要什么」是三个不同的问题，本单只治**第 2 类：知道自己要什么，
但说不出来**。改前：低置信度的模糊输入被 `IntentRouter` 重写成 `general` 后全交给模型，
模型最常见的产出是一句**开放式反问**（「请问您想查什么」）—— 用户本来就说不出，
再把问题原样丢回去，等于零帮助。

改后：模糊输入 ⇒ **理解后的猜测 + 可点击的选项**（「我理解你想看「经营看板」，
是这个吗？也可以直接点下面的方向」），把「提不出问题」变成「点一下就行」。

## 判据必须**从事实 derive**（本文件的核心，同 `test_capability_index_prompt.py` 的路子）

引导条目 = `SkillConfig.tool_names`（当前 skill 的**绑定集**）× 工具 `description` 的
`【触发】` 段里**用户原话**的机械投影 ——
**不写死任何 skill 名 / 工具名 / 引导文案**（引导了却做不到，比不引导更伤）。

术语桥是**反着用**的：`prompts/*.md` 的「术语映射」拿用户口语去**理解**用户；
这里拿工具自己声明的触发原话去**生成用户看得懂**的引导。

## 每条断言的红证（改这一处即红）

| 用例 | 反例输入（改这一处即红） |
|---|---|
| `test_vague_input_yields_clickable_guess` | 回到开放式反问（无 `component=choice` / 选项 < 2）⇒ 红 |
| `test_injected_open_question_is_not_a_clickable_guess` | 负控：「请问您想查什么」被判定成可点击猜测 ⇒ 红（证明上面那条有判别力） |
| `test_wiring_regression_to_open_question_turns_red` | 把投影关掉（= 改回开放式反问）⇒ 路由产物里没有可点击猜测 ⇒ 断言必红 |
| `test_every_guess_is_answerable_by_bound_tool_set` | 投影出「当前绑定集答不出来」的条目 ⇒ 红 |
| `test_unbound_guess_is_flagged` | 负控：塞一条指向未绑定能力（`order_create` 绑在 order、不在 general）⇒ 必须被点名 |
| `test_foreign_bound_readonly_tool_is_not_projected` | 负控（**合成事实**）：拆掉投影里的绑定集过滤 ⇒ 只读但没绑在当前 skill 上的工具会溜进来 ⇒ 红 |
| `test_guidance_text_carries_no_tool_or_field_name` | 引导文案里出现工具名 / 字段名 ⇒ 红 |
| `test_internal_name_detector_has_discriminating_power` | 负控：检测器对「调 order_query」不报 ⇒ 红 |
| `test_clicked_guess_routes_to_the_answering_skill` | 点击值走上正常路径却落不到「能回答它的 skill」⇒ 红（判据 4） |
| `test_direct_reply_node_emits_interact_choice_card` | 卡片没进 `messages`（用户没得点）⇒ 红 |

## ⚠️ 边界（照实登记）

- 触发面 = **米宝（B 端）× 低置信模糊轮 × 本会话第一次需要澄清**。后续模糊轮交还既有的
  澄清护栏升级链（`app/graph/clarify_guard.py`：上限后给示例兜底），本文件不重复实现；
- 类型 1（空白态上下文引导）/ 类型 3（主动发现）**不在本单**，本文件不涉及；
- 引导条目只取**只读**方向：模糊输入先要「查得出来」（写操作不在本单范围）。
"""
import json
import re
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from app.router.intent_config import IntentType, IntentResult, RouteDecision
from app.router.rule_matcher import RuleMatcher
from app.suggestions.vague_guess import (
    bound_tool_names,
    build_guess_card,
    named_internal,
    project_guesses,
    unanswerable,
)

#: 被引导的模糊输入（issue 原文的例子）。
_VAGUE_INPUT = "我想看看最近的情况"


# ────────────────────── 判据 1 的断言体（可被负控复用） ──────────────────────

def _is_clickable_guess(artifact) -> bool:
    """「可点击的猜测」= `choice` 组件 + ≥2 个带 label/value 的选项。

    开放式反问（纯文案、没有可点的东西）在本判据下一律为 False —— 这正是
    「改回『请问您想查什么』⇒ 必须变红」的那条线。
    """
    if not isinstance(artifact, dict):
        return False
    if artifact.get("component") != "choice":
        return False
    options = artifact.get("options")
    if not isinstance(options, list) or len(options) < 2:
        return False
    return all(
        isinstance(o, dict) and str(o.get("label") or "").strip()
        and str(o.get("value") or "").strip()
        for o in options
    )


# ────────────────────── fixtures ──────────────────────

def _reset_caches():
    from app.graph.nodes import reset_agent_intents_cache

    reset_agent_intents_cache()
    yield
    reset_agent_intents_cache()


@pytest.fixture(autouse=True)
def _clean_caches():
    yield from _reset_caches()


def _make_state(messages, session_id="sess-vague-1", agent_type="mibao"):
    """构造 AgentState（字段与 `app/graph/state.py` 对齐）。"""
    return {
        "messages": messages,
        "agent_type": agent_type,
        "tenant_id": 1,
        "user_id": "staff-1",
        "user_name": "测试同事",
        "tenant_name": None,
        "session_id": session_id,
        "role": "admin",
        "permissions": ["*"],
        "intent_result": None,
        "route_decision": None,
        "final_answer": "",
        "skill_used": "",
        "suggestions": [],
        "pending_interact_skill": "",
    }


def _low_confidence_decision(guessed: str = "dashboard") -> RouteDecision:
    """模拟 L2 分类器「听不太明白，但隐约觉得是 dashboard」的那一轮。

    与 `IntentRouter._make_decision` 的低置信改写同形：intent 被重写成 general，
    原猜测留在 `guessed_intent`（不丢弃 —— 它就是要拿去当「猜测」的材料）。
    """
    return RouteDecision(
        intent_result=IntentResult(
            intent=IntentType.GENERAL,
            confidence=0.30,
            source="low_confidence",
            guessed_intent=guessed,
        ),
        action="full_agent",
    )


def _patch_store(state=None):
    """mock SessionStateStore（内存 state）——与 `test_clarify_guard.py` 同形。"""
    store = AsyncMock()
    store.load = AsyncMock(return_value=dict(state or {}))
    store.commit = AsyncMock(return_value=True)
    return patch("app.memory.session_state_store.SessionStateStore", return_value=store)


# ────────────────────── 判据 1：模糊输入 ⇒ 可点击的猜测 ──────────────────────

class TestVagueInputYieldsClickableGuess:
    def test_vague_input_yields_clickable_guess(self):
        """模糊输入下投影出的产物必须是**可点击的猜测**，不是开放式反问。"""
        card = build_guess_card("general")
        assert card, "模糊输入没有产出任何引导产物（用户仍然只能自己想办法）"
        assert _is_clickable_guess(card), (
            f"引导产物不可点击（= 开放式反问形态）：{card!r}")
        assert card.get("title"), "猜测卡应有「我理解你想…」的引导句"
        # 引导句是**用户语言**，不是能力名 / 内部用语
        assert not re.search(r"跨域|批量操作|skill|tool", card["title"], re.I), (
            f"引导句用了能力名/内部用语：{card['title']!r}")

    def test_guessed_intent_leads_the_options(self):
        """「我理解你想看 X，是这个吗」：分类器**猜到的那个方向**必须排在第一位。

        改前 `IntentRouter` 把低置信猜测**丢掉**（只留 general）；这里要求它被用起来，
        否则引导退化成一张与用户输入无关的菜单。
        """
        card = build_guess_card("general", guessed_intent="dashboard")
        first = card["options"][0]
        guess = next(g for g in project_guesses("general") if g["value"] == first["value"])
        assert guess["intent"] == "dashboard", (
            f"首位选项应来自猜中的方向 dashboard，实际 {guess['intent']}")
        assert guess["value"] in card["title"], (
            f"引导句应点名猜到的方向：title={card['title']!r} value={guess['value']!r}")

    def test_injected_open_question_is_not_a_clickable_guess(self):
        """负控（红证）：改回开放式反问 ⇒ 判据 1 的断言体必须判否。"""
        open_question = {"component": "", "title": "请问您想查什么？"}
        assert not _is_clickable_guess(open_question), (
            "「请问您想查什么」被判定成可点击猜测 —— 判据 1 是空判据")
        # 只有 1 个选项也不叫「给猜测」（用户没得选，等同反问）
        assert not _is_clickable_guess(
            {"component": "choice", "title": "t", "options": [{"label": "a", "value": "a"}]})

    async def test_wiring_regression_to_open_question_turns_red(self):
        """注入式红证（判据 1 的**接线**面）：把投影关掉 = 改回开放式反问 ⇒ 必红。

        上面两条断言的是「投影函数」；这条断言的是「接线」—— 没有它，投影写得再好
        也可能根本没接进模糊输入那条路（本仓最忌讳的「判据自己选择沉默」）。
        """
        from app.graph.nodes import intent_router_node

        state = _make_state([HumanMessage(content=_VAGUE_INPUT)])
        with patch("app.router.intent_router.IntentRouter.route",
                   AsyncMock(return_value=_low_confidence_decision())), \
                patch("app.graph.nodes.build_guess_card", return_value=None), \
                _patch_store():
            result = await intent_router_node(state)

        # 关掉投影后：路由产物里**没有**可点击猜测（= 改前的开放式反问形态）
        assert not _is_clickable_guess(result["route_decision"].get("guess_card")), (
            "投影被关掉却仍产出可点击猜测 —— 说明判据读的不是被测对象")

    async def test_vague_input_turn_carries_clickable_card(self):
        """接线正面：模糊轮的路由产物里带着可点击的猜测卡（判据 1 的生产路径）。"""
        from app.graph.nodes import intent_router_node

        state = _make_state([HumanMessage(content=_VAGUE_INPUT)])
        with patch("app.router.intent_router.IntentRouter.route",
                   AsyncMock(return_value=_low_confidence_decision())), _patch_store():
            result = await intent_router_node(state)

        route = result["route_decision"]
        assert _is_clickable_guess(route.get("guess_card")), (
            f"模糊轮没有带上可点击的猜测卡：{route!r}")
        assert route.get("action") == "direct_reply", (
            "猜测卡应由确定性节点直发（不走大模型自由发挥），action 应为 direct_reply")
        assert route.get("direct_reply") == route["guess_card"]["title"]

    async def test_second_vague_round_falls_back_to_existing_escalation(self):
        """本会话**已经**澄清过 ⇒ 不再发卡（交还既有护栏的升级链，不反复追问）。"""
        from app.graph.nodes import intent_router_node

        state = _make_state([HumanMessage(content=_VAGUE_INPUT)])
        with patch("app.router.intent_router.IntentRouter.route",
                   AsyncMock(return_value=_low_confidence_decision())), \
                _patch_store({"clarify": {"count": 1, "force_example": False}}):
            result = await intent_router_node(state)

        assert not _is_clickable_guess(result["route_decision"].get("guess_card")), (
            "第二轮模糊输入又发一张猜测卡 —— 会变成反复追问（护栏预算被绕过）")


# ────────────────────── 判据 2：每条引导可追溯到一条真实能力 ──────────────────────

class TestGuessIsTraceableToRealCapability:
    def test_every_guess_is_answerable_by_bound_tool_set(self):
        """**硬闸**：每条引导点名的事情，都必须能被**当前 skill 的绑定集**回答。

        「引导了却做不到，比不引导更伤」—— 这条断言就是防它。
        """
        guesses = project_guesses("general")
        assert guesses, "一条引导都投影不出来 —— 本判据会恒真（空判据）"
        flagged = unanswerable("general", guesses)
        assert not flagged, (
            "以下引导指向了当前 skill 答不出来的能力（推荐答不出来的问题）："
            f"{flagged}")

    def test_guess_tools_are_registered_and_bound(self):
        """引导条目的能力来源必须是**已注册**且**真的绑在当前 skill 上**的工具。"""
        bound = bound_tool_names("general")
        assert bound, "绑定集为空 —— 判据会恒真（空判据）"
        checked = 0
        for guess in project_guesses("general"):
            checked += 1
            assert guess["tool"] in bound, (
                f"{guess['label']!r} 点名了未绑定工具 {guess['tool']!r}")
        assert checked >= 2, f"只扫到 {checked} 条引导 —— 判据疑似空跑"

    def test_unbound_guess_is_flagged(self):
        """负控（红证）：塞一条指向**未绑定**能力的引导 ⇒ 必须被点名。

        `order_create` 是**真实存在**的能力，但绑在 `order` 而不在 `general`
        （B 端只读化后 general 只有只读工具）⇒ 正是「引导用户做一件本流程做不到的事」的形态。
        """
        bad = {
            "label": "帮我下单", "value": "帮我下单",
            "intent": "order_create", "skill": "order", "tool": "order_create",
        }
        assert unanswerable("general", [bad]) == [bad], (
            "指向未绑定能力的引导没有被点名 —— 判据 2 的硬闸是空的")

    def test_real_capability_still_passes_the_gate(self):
        """负控的另一半：绑定集**内**的条目不许被误杀（否则闸门只会恒红）。"""
        good = project_guesses("general")[0]
        assert unanswerable("general", [good]) == []

    def test_foreign_bound_readonly_tool_is_not_projected(self):
        """负控（红证，**合成事实**）：只读但**没绑在当前 skill 上**的工具不许被引导。

        为什么要合成（本仓 `test_index_is_derived_from_registry_not_hardcoded` 同款理由）：
        真实注册表下，"未绑定的只读工具"恰好都不满足 L1 路由 ⇒ 绑不绑这道闸**看起来都能过**
        —— 那它是一道"看起来绿"的空闸，将来注册表一变就漏。合成事实把它逼出来：
        去掉投影里的绑定集过滤，`synth_foreign`（只读、绑在**别的** skill）立刻溜进候选 ⇒ 红。
        """
        from app.graph.skills.skill_config import SkillConfig

        class _FakeTool:
            def __init__(self, name, description, read_only=True):
                self.name = name
                self.description = description
                self.read_only = read_only
                self.parameters = {"type": "object", "properties": {}}

        class _FakeToolRegistry:
            def __init__(self, tools):
                self._tools = tools

            def get_all_tools(self):
                return list(self._tools)

        class _FakeSkillRegistry:
            def __init__(self, configs):
                self._configs = configs

            def get_all(self):
                return list(self._configs)

            def get(self, name):
                return next((c for c in self._configs if c.name == name), None)

            def get_intent_to_route_map(self, persona="mibao"):
                mapping = {}
                for cfg in self._configs:
                    if persona and persona not in cfg.system_prompts:
                        continue
                    for route_key in cfg.route_keys:
                        for intent in cfg.intents:
                            mapping[intent] = route_key
                return mapping

        current = SkillConfig(
            name="synth_cur", domain="synth", display_name="当前流程",
            tool_names=["synth_own"], route_keys=["synth_cur"], intents=["general"],
            system_prompts={"synth_persona": "p"},
        )
        foreign = SkillConfig(
            name="synth_other", domain="synth", display_name="别的流程",
            tool_names=["synth_foreign"], route_keys=["synth_other"],
            intents=["order_query"], system_prompts={"synth_persona": "p"},
        )
        # 两个工具的触发原话都能被 L1 判到 order_query；它只路由回 `synth_other`
        tools = [
            _FakeTool("synth_own", "【触发】用户说'查订单'时调用"),
            _FakeTool("synth_foreign", "【触发】用户说'查订单'时调用"),
        ]
        with patch("app.tools.registry.get_tool_registry",
                   return_value=_FakeToolRegistry(tools)), \
                patch("app.graph.skills.skill_registry.get_skill_registry",
                      return_value=_FakeSkillRegistry([current, foreign])):
            guesses = project_guesses("synth_cur")

        assert guesses == [], (
            f"投影出了当前 skill **没有绑定**的工具（引导了却做不到）：{guesses}")


# ────────────────────── 判据 3：引导文本不含工具名 / 字段名 ──────────────────────

class TestGuidanceTextIsUserLanguage:
    def test_guidance_text_carries_no_tool_or_field_name(self):
        """`principles.md` 的「回复中禁止出现工具名/字段名」延伸到**引导面**。

        卡片是用户**直接看到并点击**的东西 —— 文案里出现 `dashboard_stats` /
        `status` 之类，等于把内部实现摆到用户面前。
        """
        card = build_guess_card("general")
        texts = [card["title"]]
        for opt in card["options"]:
            texts += [opt["label"], opt["value"]]
        offenders = {t: named_internal(t) for t in texts if named_internal(t)}
        assert not offenders, f"引导文案里出现了工具名/字段名：{offenders}"

    def test_user_language_has_no_ascii_placeholders(self):
        """用户语言里不该出现 `XX` / 英文占位（那是 schema 话术，不是人话）。"""
        for guess in project_guesses("general"):
            assert not re.search(r"[A-Za-z]", guess["label"]), (
                f"引导文案含英文/占位符（不是用户语言）：{guess['label']!r}")

    def test_internal_name_detector_has_discriminating_power(self):
        """负控（红证）：检测器对内部名不报 ⇒ 上面那条是永远绿的空判据。"""
        assert named_internal("调 order_query 看一下") == ["order_query"], (
            "检测器认不出工具名 —— 判据 3 是空判据")
        assert named_internal("查一下 status 字段") == ["status"], (
            "检测器认不出字段名 —— 判据 3 是空判据")
        assert named_internal("看看最近的经营情况") == []


# ────────────────────── 判据 4：点选后进入正常处理路径 ──────────────────────

class TestClickedGuessEntersNormalPath:
    def test_clicked_guess_routes_to_the_answering_skill(self):
        """点选猜测 = 发一条真实用户消息 ⇒ 下一轮必须走**正常路径**落到能回答它的 skill。

        判据 4「不是又一轮澄清」的机械形态：L1 规则（确定性、无 LLM）就能把它判到
        一个**真实意图**，且该意图路由到的正是**投影时点名的那个 skill**。
        """
        matcher = RuleMatcher()
        from app.graph.nodes import _intent_to_route_key

        checked = 0
        for guess in project_guesses("general"):
            # 「L1 认不认识」与「认成了什么」合成一条**业务事实**断言：
            # 认不出来（None）与认成兜底意图是同一个失败形态 —— 都会掉回澄清。
            hit = matcher.match(guess["value"])
            got_intent = hit.intent.value if hit is not None else "<未命中>"
            assert got_intent != "<未命中>", (
                f"点选 {guess['value']!r} 后 L1 认不出来 —— 会掉回澄清（判据 4 不成立）")
            assert got_intent != "general", (
                f"点选 {guess['value']!r} 被归到兜底意图 —— 等于又一轮澄清")
            assert _intent_to_route_key(got_intent, "mibao") == guess["skill"], (
                f"{guess['value']!r} 路由到了 "
                f"{_intent_to_route_key(got_intent, 'mibao')!r}，"
                f"而能回答它的是 {guess['skill']!r}")
            checked += 1
        assert checked >= 2, f"只验证了 {checked} 条 —— 判据疑似空跑"

    async def test_direct_reply_node_emits_interact_choice_card(self):
        """`direct_reply` 节点必须把猜测落成 `interact` 卡片消息（用户点得到）。

        与 `handoff_offer` 同协议：`AIMessage(tool_calls=[interact])` +
        `ToolMessage(name="interact")` ⇒ SSE 出 `interactive` 事件 ⇒ 前端渲染 ChoiceCard。
        """
        from app.graph.nodes import direct_reply_node

        card = build_guess_card("general")
        state = _make_state([HumanMessage(content=_VAGUE_INPUT)])
        state["intent_result"] = {"intent": "general", "confidence": 0.30,
                                  "source": "low_confidence"}
        state["route_decision"] = {
            "action": "direct_reply", "direct_reply": card["title"], "guess_card": card,
        }
        out = await direct_reply_node(state)

        tool_msgs = [m for m in out.get("messages", [])
                     if isinstance(m, ToolMessage) and m.name == "interact"]
        assert tool_msgs, "direct_reply 没把猜测卡发出去 —— 用户无卡可点"
        payload = json.loads(tool_msgs[0].content)
        assert payload.get("success") is True
        assert payload["data"]["component"] == "choice"
        assert len(payload["data"]["options"]) >= 2
        # 卡片文案即引导句：用户看到的是「我理解你想…」而不是内部话术
        assert out["final_answer"] == card["title"], (
            f"回复文案被别的直复模板覆盖了：{out['final_answer']!r}")