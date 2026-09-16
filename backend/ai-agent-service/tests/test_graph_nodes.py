"""图辅助节点单元测试（app/graph/nodes.py）

覆盖：
- _extract_text_from_content：str / None / list / 非文本兜底
- _get_last_human_text / _last_human_has_image：多模态检测
- direct_reply_node：greeting/farewell/capabilities 兜底
- intent_router_node：pending_skill 短消息合成意图快捷路由
- intent_router_node：plan_rewrite 路径澄清轮护栏（连续模糊意图触发兜底）
- route_by_intent：direct_reply + 多模态重定向 general、escape hatch 切换、会话连续性
"""
# case_ids: CH-002, CH-003, CH-018, CH-021, CH-022, OR-017, PR-007
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.graph.nodes import (
    _extract_text_from_content,
    _get_last_human_text,
    _last_human_has_image,
    direct_reply_node,
    intent_router_node,
    route_by_intent,
)

# PR-007（#3557）R2 实发原文：商品上下架确认卡的 confirmValue，逐字回传。
# 卡值里的「（改为停售，买家不可下单）」含「下单」—— 缺陷链的触发器。
PR007_CONFIRM_VALUE = (
    "确认：商品名称=遮光窗帘；当前价格=¥168.00；当前状态=在售；"
    "操作=下架（改为停售，买家不可下单）"
)


class TestExtractTextFromContent:
    def test_string_passthrough(self):
        assert _extract_text_from_content("你好") == "你好"

    def test_none_returns_empty(self):
        assert _extract_text_from_content(None) == ""

    def test_list_text_blocks_joined(self):
        content = [
            {"type": "text", "text": "你好"},
            {"type": "image_url", "image_url": {"url": "x"}},
            {"type": "text", "text": "世界"},
        ]
        assert _extract_text_from_content(content) == "你好 世界"

    def test_non_dict_list_ignored(self):
        content = [{"type": "text", "text": "a"}, "raw", 123]
        assert _extract_text_from_content(content) == "a"

    def test_non_string_fallback(self):
        assert _extract_text_from_content(42) == "42"


class TestGetLastHumanText:
    def test_string_content(self):
        messages = [HumanMessage(content="hello")]
        assert _get_last_human_text(messages) == "hello"

    def test_list_content(self):
        messages = [HumanMessage(content=[{"type": "text", "text": "hi"}])]
        assert _get_last_human_text(messages) == "hi"

    def test_no_human_message(self):
        assert (_get_last_human_text([AIMessage(content="assistant")]) is None)

    def test_image_only_returns_none(self):
        messages = [HumanMessage(content=[{"type": "image_url", "image_url": {"url": "x"}}])]
        assert (_get_last_human_text(messages) is None)


class TestLastHumanHasImage:
    def test_image_detected(self):
        messages = [HumanMessage(content=[{"type": "image_url", "image_url": {"url": "x"}}])]
        assert _last_human_has_image(messages) is True

    def test_no_image(self):
        messages = [HumanMessage(content="纯文本")]
        assert _last_human_has_image(messages) is False

    def test_no_human(self):
        assert _last_human_has_image([AIMessage(content="a")]) is False


class TestDirectReplyNode:
    @pytest.mark.asyncio
    async def test_greeting_fallback(self):
        with patch("app.agents.agent_config.get_agent_config", side_effect=ImportError):
            state = {
                "intent_result": {"intent": "greeting"},
                "route_decision": {"action": "direct_reply", "direct_reply": ""},
            }
            result = await direct_reply_node(state)
        assert result["skill_used"] == "direct_reply"
        assert "帮您" in result["final_answer"]

    @pytest.mark.asyncio
    async def test_farewell_fallback(self):
        with patch("app.agents.agent_config.get_agent_config", side_effect=ImportError):
            state = {
                "intent_result": {"intent": "farewell"},
                "route_decision": {"action": "direct_reply", "direct_reply": ""},
            }
            result = await direct_reply_node(state)
        assert "随时找我" in result["final_answer"]

    @pytest.mark.asyncio
    async def test_config_reply_preferred(self):
        fake_config = MagicMock()
        fake_config.get_direct_reply.return_value = "自定义问候"
        with patch("app.agents.agent_config.get_agent_config", return_value=fake_config):
            state = {
                "intent_result": {"intent": "greeting"},
                "route_decision": {"action": "direct_reply", "direct_reply": ""},
            }
            result = await direct_reply_node(state)
        assert result["final_answer"] == "自定义问候"


class TestIntentRouterNode:
    @pytest.mark.asyncio
    async def test_pending_skill_short_msg_rewrites_intent(self):
        state = {
            "pending_interact_skill": "product",
            "session_id": "s1",
            "messages": [HumanMessage(content="确认")],
        }
        result = await intent_router_node(state)
        assert result["intent_result"]["intent"] == "product_inquiry"
        assert result["intent_result"]["confidence"] == 0.99
        assert result["intent_result"]["source"] == "plan_rewrite"
        assert result["route_decision"]["action"] == "full_agent"

    @pytest.mark.asyncio
    async def test_short_order_signal_uses_l1_not_synthetic(self):
        """短消息带**下单**信号（「确认下单」4 字）→ 必须按 L1 给 order_create（#3476 根因）。

        C-A1 P1 实证（run 34791767013）：pending=customer_product 时「确认下单」走短消息路径，
        而 `_SKILL_TO_INTENT` 的键是**域**名（product/order…），C 端 pending 值是
        customer_product/customer_order → **全部 miss → 一律 general** →
        escape 命中 order 域关键词却路由到 customer_general（没有 order_create）
        → 模型只能说"我下不了单"并转人工（C-A1 L1 违规 3 条）。
        """
        state = {
            "pending_interact_skill": "customer_product",
            "session_id": "s1",
            "agent_type": "xiaobu",
            "messages": [HumanMessage(content="确认下单")],
        }
        result = await intent_router_node(state)
        assert result["intent_result"]["intent"] == "order_create", (
            f"「确认下单」必须按 L1 给 order_create，实得 {result['intent_result']['intent']}")

    @pytest.mark.asyncio
    async def test_card_confirm_round_keeps_own_skill_intent(self):
        """#3557 G1：答卡轮（逐字回传**本 skill** 卡的 confirmValue）不重判意图。

        这是缺陷链的**第一个判据点**（`intent_router_node` → `IntentRouter.route()`
        → L1 规则表先于 LLM 分类器）：卡值里的「（改为停售，买家不可下单）」含「下单」
        → L1 判 `order_create` 0.98 → 路由到 order skill（无 product_manage）
        → 零工具调用 + 「订单模块」口径拒绝（CI run 34808115143，PR-007 50%）。
        答卡轮保持本 skill 的合成意图后，后续 route_by_intent 的 G1 豁免才能生效。
        """
        from app.graph.nodes import _CARD_CONFIRM_INTENT_SOURCE
        confirm = PR007_CONFIRM_VALUE
        state = {
            "pending_interact_skill": "product",
            "last_confirm_skill": "product",
            "last_confirm_value": confirm,
            "session_id": "s1",
            "agent_type": "mibao",
            "messages": [HumanMessage(content=confirm)],
        }
        result = await intent_router_node(state)
        assert result["intent_result"]["source"] == _CARD_CONFIRM_INTENT_SOURCE
        assert result["intent_result"]["intent"] != "order_create", (
            "答卡轮仍被判成 order_create —— 会话将被路由到 order skill（#3557 第一判据点）"
        )

    @pytest.mark.asyncio
    async def test_card_confirm_round_long_msg_skips_llm_classifier(self):
        """答卡轮不得进入 LLM 分类（msg_len > 5 的"长消息允许话题切换"分支）。

        L1 在此之前已判出 order_create；若不短路，长消息分支会真的调分类器
        ——修复必须在此拦下（零 LLM 可复现，不依赖模型采样）。
        """
        from app.graph.nodes import _CARD_CONFIRM_INTENT_SOURCE
        confirm = PR007_CONFIRM_VALUE
        state = {
            "pending_interact_skill": "product",
            "last_confirm_skill": "product",
            "last_confirm_value": confirm,
            "session_id": "s1",
            "agent_type": "mibao",
            "messages": [HumanMessage(content=confirm)],
        }
        with patch("app.router.intent_router.IntentRouter") as mock_router:
            result = await intent_router_node(state)
        mock_router.assert_not_called()
        assert result["intent_result"]["source"] == _CARD_CONFIRM_INTENT_SOURCE

    @pytest.mark.asyncio
    async def test_bare_confirm_keeps_synthetic(self):
        """回归：无领域信号的短消息（「确认」）仍走合成意图（pending 域），不得被 L1 抢走。"""
        state = {
            "pending_interact_skill": "customer_product",
            "session_id": "s1",
            "agent_type": "xiaobu",
            "messages": [HumanMessage(content="确认")],
        }
        result = await intent_router_node(state)
        assert result["intent_result"]["intent"] == "product_inquiry", result

    @pytest.mark.asyncio
    async def test_short_order_signal_any_c_pending_skill(self):
        """不只 customer_product：customer_knowledge / customer_general 同样要能被下单信号拉回。"""
        for pending in ("customer_knowledge", "customer_general", "customer_product"):
            state = {
                "pending_interact_skill": pending,
                "session_id": "s1",
                "agent_type": "xiaobu",
                "messages": [HumanMessage(content="确认下单")],
            }
            result = await intent_router_node(state)
            assert result["intent_result"]["intent"] == "order_create", (
                f"pending={pending} 时「确认下单」未按 L1 给 order_create")

    @pytest.mark.asyncio
    async def test_pending_skill_order_maps_to_order_query(self):
        state = {
            "pending_interact_skill": "order",
            "session_id": "s1",
            "messages": [HumanMessage(content="1")],
        }
        result = await intent_router_node(state)
        assert result["intent_result"]["intent"] == "order_query"

    @pytest.mark.asyncio
    async def test_pending_skill_multimodal_image_msg_no_crash(self):
        """缺陷锁定（线上 sess_* 会话真实报错）：pending_skill 存在时用户发图，
        最后一条 HumanMessage content 为多模态 list（text + image_url），
        intent_router_node 对 raw content 调 .strip() 抛
        ``AttributeError: 'list' object has no attribute 'strip'``。

        修复后应走短消息 plan_rewrite 路径（图片消息的文本通常很短），
        正常路由回 pending skill，不崩溃、不弹交互卡。
        """
        from app.graph.clarify_guard import CLARIFY_STATE_KEY

        store = self._mock_clarify_store(
            {CLARIFY_STATE_KEY: {"count": 1, "force_example": False}}
        )
        state = {
            "pending_interact_skill": "general",
            "session_id": "s1",
            "messages": [HumanMessage(content=[
                {"type": "text", "text": "你懂的"},
                {"type": "image_url", "image_url": {"url": "https://picsum.photos/seed/curtain-fabric/800/600"}},
            ])],
        }
        with patch("app.memory.session_state_store.SessionStateStore", return_value=store):
            result = await intent_router_node(state)
        assert result["intent_result"]["source"] == "plan_rewrite"
        assert result["route_decision"]["action"] == "full_agent"
        assert result["intent_result"]["intent"] == "general"

    @pytest.mark.asyncio
    async def test_no_pending_skill_runs_llm(self):
        mock_route_decision = MagicMock()
        mock_route_decision.intent_result.intent.value = "greeting"
        mock_route_decision.intent_result.confidence = 0.9
        mock_route_decision.intent_result.source = "llm"
        mock_route_decision.action = "direct_reply"
        mock_route_decision.direct_reply = "您好"
        mock_route_decision.tool_hint = None

        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_route_decision)

        state = {
            "session_id": "s1",
            "agent_type": "xiaobu",
            "messages": [HumanMessage(content="你好")],
        }
        with patch("app.router.intent_router.IntentRouter", return_value=mock_router), \
             patch("app.graph.nodes._get_agent_intents", return_value=["greeting", "general"]), \
             patch("app.graph.nodes._build_entity_hint", new=AsyncMock(return_value="")):
            result = await intent_router_node(state)
        assert result["intent_result"]["intent"] == "greeting"
        assert result["route_decision"]["action"] == "direct_reply"

    # ── 澄清轮护栏：plan_rewrite 路径（pending_skill 短消息）也必须接入护栏 ──
    # 真实验收发现（#2801）：连续模糊意图（"帮我看看"→"就是那个"→"你懂的"）
    # 澄清卡下发后 pending_skill 已设置，后续模糊轮走 plan_rewrite 提前 return，
    # 完全绕过护栏挂点 → 兜底话术永不触发。本组测试锁定该缺陷。

    @staticmethod
    def _mock_clarify_store(state_dict):
        """内存版 SessionStateStore（与 test_clarify_guard 同构）。"""
        store = MagicMock()
        store.load = AsyncMock(return_value=dict(state_dict))
        store.commit = AsyncMock(side_effect=lambda sid, st: (state_dict.clear(), state_dict.update(st)))
        return store

    @pytest.mark.asyncio
    async def test_pending_skill_vague_short_msg_reaches_clarify_limit_returns_fallback(self):
        """缺陷锁定：plan_rewrite 短消息（如"就是那个"）连续模糊已达上限 → 应返回兜底话术。"""
        from app.graph.clarify_guard import (
            CLARIFY_STATE_KEY,
            CLARIFY_FORCE_EXAMPLE_TEXT,
            MAX_CLARIFY_ROUNDS,
        )

        store = self._mock_clarify_store(
            {CLARIFY_STATE_KEY: {"count": MAX_CLARIFY_ROUNDS, "force_example": True}}
        )
        state = {
            "pending_interact_skill": "general",
            "session_id": "s1",
            "messages": [HumanMessage(content="就是那个")],
        }
        with patch("app.memory.session_state_store.SessionStateStore", return_value=store):
            result = await intent_router_node(state)
        # 护栏改写为 direct_reply 兜底话术（而非继续 plan_rewrite 弹卡）
        assert result["route_decision"]["action"] == "direct_reply"
        assert result["route_decision"]["direct_reply"] == CLARIFY_FORCE_EXAMPLE_TEXT

    @pytest.mark.asyncio
    async def test_pending_skill_vague_short_msg_increments_clarify_count(self):
        """plan_rewrite 模糊短消息应计澄清轮（count +1 写回），未达上限继续 plan_rewrite。"""
        from app.graph.clarify_guard import CLARIFY_STATE_KEY

        store = self._mock_clarify_store({CLARIFY_STATE_KEY: {"count": 1, "force_example": False}})
        state = {
            "pending_interact_skill": "general",
            "session_id": "s1",
            "messages": [HumanMessage(content="你懂的")],
        }
        with patch("app.memory.session_state_store.SessionStateStore", return_value=store):
            result = await intent_router_node(state)
        assert result["intent_result"]["source"] == "plan_rewrite"
        assert result["route_decision"]["action"] == "full_agent"
        assert store.commit.called
        assert store.commit.call_args[0][1][CLARIFY_STATE_KEY]["count"] == 2

    @pytest.mark.asyncio
    async def test_pending_skill_domain_keyword_resets_clarify(self):
        """plan_rewrite 短消息含领域关键词（如"查订单"）→ 实质意图，清零计数。"""
        from app.graph.clarify_guard import CLARIFY_STATE_KEY

        store = self._mock_clarify_store(
            {CLARIFY_STATE_KEY: {"count": 2, "force_example": True}}
        )
        state = {
            "pending_interact_skill": "general",
            "session_id": "s1",
            "messages": [HumanMessage(content="查订单")],
        }
        with patch("app.memory.session_state_store.SessionStateStore", return_value=store):
            result = await intent_router_node(state)
        assert result["route_decision"]["action"] == "full_agent"
        assert store.commit.called
        assert store.commit.call_args[0][1][CLARIFY_STATE_KEY]["count"] == 0

    @pytest.mark.asyncio
    async def test_pending_customer_general_vague_short_msg_counts_clarify(self):
        """C 端澄清卡由 customer_general skill 下发：pending_skill=customer_general
        的模糊短消息也应计澄清轮（真实验收 #2801 发现：只认 general 导致 C 端
        护栏永不计数、兜底不触发）。"""
        from app.graph.clarify_guard import CLARIFY_STATE_KEY

        store = self._mock_clarify_store({CLARIFY_STATE_KEY: {"count": 1, "force_example": False}})
        state = {
            "pending_interact_skill": "customer_general",
            "session_id": "s1",
            "messages": [HumanMessage(content="你懂的")],
        }
        with patch("app.memory.session_state_store.SessionStateStore", return_value=store):
            result = await intent_router_node(state)
        assert result["intent_result"]["source"] == "plan_rewrite"
        assert result["route_decision"]["action"] == "full_agent"
        assert store.commit.called
        assert store.commit.call_args[0][1][CLARIFY_STATE_KEY]["count"] == 2

    @pytest.mark.asyncio
    async def test_general_intent_classifier_source_counts_clarify_round(self):
        """主挂点：classifier 直接判 general（非 low_confidence 重写）也计澄清轮。

        真实验收 #2801 发现：R1"帮我看看"confidence=0.30 被 classifier 判 general
        （GENERAL 在低置信重写豁免清单内，source 非 low_confidence），旧判定
        source=="low_confidence" 不成立 → 首轮未计数 → 兜底推迟一轮。
        """
        from app.graph.clarify_guard import CLARIFY_STATE_KEY

        store = self._mock_clarify_store({CLARIFY_STATE_KEY: {"count": 0, "force_example": False}})

        mock_route_decision = MagicMock()
        mock_route_decision.intent_result.intent.value = "general"
        mock_route_decision.intent_result.confidence = 0.30
        mock_route_decision.intent_result.source = "classifier"
        mock_route_decision.action = "full_agent"
        mock_route_decision.direct_reply = None
        mock_route_decision.tool_hint = None

        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_route_decision)

        state = {
            "session_id": "s1",
            "agent_type": "mibao",
            "messages": [HumanMessage(content="帮我看看")],
        }
        with patch("app.router.intent_router.IntentRouter", return_value=mock_router), \
             patch("app.graph.nodes._get_agent_intents", return_value=["general"]), \
             patch("app.graph.nodes._build_entity_hint", new=AsyncMock(return_value="")), \
             patch("app.memory.session_state_store.SessionStateStore", return_value=store):
            result = await intent_router_node(state)
        assert result["route_decision"]["action"] == "full_agent"
        assert store.commit.called
        assert store.commit.call_args[0][1][CLARIFY_STATE_KEY]["count"] == 1


class TestRouteByIntent:
    def test_direct_reply_no_pending(self):
        state = {
            "route_decision": {"action": "direct_reply"},
            "messages": [HumanMessage(content="你好")],
        }
        assert route_by_intent(state) == "direct_reply"

    def test_direct_reply_multimodal_redirects_to_general(self):
        state = {
            "route_decision": {"action": "direct_reply"},
            "messages": [HumanMessage(content=[{"type": "image_url", "image_url": {"url": "x"}}])],
        }
        assert route_by_intent(state) == "general"

    def test_pending_skill_stays_on_same_skill(self):
        state = {
            "pending_interact_skill": "product",
            "route_decision": {"action": "full_agent"},
            "intent_result": {"intent": "product_inquiry"},
            "messages": [HumanMessage(content="好的，继续")],
        }
        assert route_by_intent(state) == "product"

    def test_pending_skill_guard_forced_bypasses_pending(self):
        """护栏强制兜底（guard_forced=True）不被 pending_skill 覆盖。

        真实验收 #2801 发现：澄清护栏改写为 direct_reply 兜底话术后，
        route_by_intent 因 pending_skill 存在又覆盖回 general skill →
        兜底永不触达用户。guard_forced 标记必须穿透 pending_skill。
        """
        state = {
            "pending_interact_skill": "general",
            "route_decision": {"action": "direct_reply", "guard_forced": True},
            "intent_result": {"intent": "general"},
            "messages": [HumanMessage(content="你懂的")],
        }
        assert route_by_intent(state) == "direct_reply"

    def test_pending_skill_escape_hatch_switches_domain(self):
        state = {
            "pending_interact_skill": "product",
            "route_decision": {"action": "full_agent"},
            "intent_result": {"intent": "order_query"},
            "messages": [HumanMessage(content="帮我查一下订单")],
        }
        with patch.dict("app.graph.nodes._INTENT_TO_ROUTE",
                        {"": {"order_query": "order_skill", "general": "general"}}):
            result = route_by_intent(state)
        assert result == "order_skill"

    def test_quote_skill_下单_escapes_to_order_skill(self):
        """报价 skill 锁住会话时，「确认下单/我要下单」必须能切回下单流程（issue #3361）。

        为什么必须有这条：`customer_quote` 会下发报价卡并锁住 `pending_interact_skill`，
        但它**没有 order_create 工具**。若「下单」不算 order 域信号，escape hatch 不触发
        → 会话锁死在报价 skill → 模型照样调 order_create → `tool_not_found` ×2 → 转人工，
        订单从未创建（CI run 34686905546 实证：OR-017 R7/R8，顾客侧表现为"下单失败"）。
        """
        from app.graph.nodes import _SKILL_DOMAIN_KEYWORDS
        assert "下单" in _SKILL_DOMAIN_KEYWORDS["order"], (
            "order 领域关键词缺「下单」—— 报价后顾客说『确认下单』将无法切回下单流程"
        )
        for msg in ("确认下单", "我要下单", "帮我下单"):
            state = {
                "pending_interact_skill": "customer_quote",
                "route_decision": {"action": "full_agent"},
                "intent_result": {"intent": "order_create"},
                "messages": [HumanMessage(content=msg)],
            }
            with patch.dict("app.graph.nodes._INTENT_TO_ROUTE",
                            {"": {"order_create": "customer_order_skill", "general": "general"}}):
                result = route_by_intent(state)
            assert result == "customer_order_skill", f"{msg!r} 未切回下单流程（route={result}）"
            assert state["pending_interact_skill"] == "", f"{msg!r} 未释放报价 skill 的会话锁"

    def test_processing_order_signal_escapes_product_lock(self):
        """#3921：在办商品锁里用户说「查看加工单数据」→ 必须逃逸到订单域。

        商品域把「加工单」当「加工项」查（PG-017 首跑 0 分 + 证据会话
        sess_f3c0ee0d2cc342a0）；「加工单」是 order 域信号，会话锁在 product 时
        提加工单必须切走（到订单域走概念区分口径），不能留在商品域误查加工项目录。
        """
        from app.graph.nodes import _SKILL_DOMAIN_KEYWORDS
        assert "加工单" in _SKILL_DOMAIN_KEYWORDS["order"], (
            "order 领域关键词缺「加工单」—— 商品锁中提加工单会被当加工项处理"
        )
        state = {
            "pending_interact_skill": "product_skill",
            "route_decision": {"action": "full_agent"},
            "intent_result": {"intent": "order_query"},
            "messages": [HumanMessage(content="查看加工单数据")],
        }
        with patch.dict("app.graph.nodes._INTENT_TO_ROUTE",
                        {"": {"order_query": "order_skill", "general": "general"}}):
            result = route_by_intent(state)
        assert result == "order_skill", f"加工单话题未逃逸到订单域（route={result}）"
        assert state["pending_interact_skill"] == "", "加工单话题未释放商品锁"

    def test_own_domain_keyword_does_not_escape_customer_skill(self):
        """C 端 skill 名带 `customer_` 前缀，**自己的领域关键词不得触发 escape hatch**。

        回归实证（CI run 34688038261）：在 `customer_order` 里顾客点确认卡回传
        「确认下单：遮光窗帘3米+打孔加工，合计¥95.4」→ 因消息含「下单」（order 域），
        而 escape hatch 用 `skill_domain == pending_skill` 比较 `order` vs `customer_order`
        **永不相等** → 连本领域也被当成"其他领域" → 误判话题切换、清空会话锁 →
        intent 分类为 quote → 路由到 customer_quote（无 order_create）→
        `Tool not found: order_create` → 订单永不创建、最终转人工。
        """
        from app.graph.nodes import _skill_keyword_domain
        assert _skill_keyword_domain("customer_order") == "order"
        assert _skill_keyword_domain("customer_aftersales") == "aftersales"
        assert _skill_keyword_domain("order") == "order"      # B 端风格名不变
        assert _skill_keyword_domain("") == ""

        for msg in ("确认下单：遮光窗帘3米+打孔加工，合计¥95.4", "帮我查一下订单"):
            state = {
                "pending_interact_skill": "customer_order",
                "route_decision": {"action": "full_agent"},
                "intent_result": {"intent": "quote"},
                "messages": [HumanMessage(content=msg)],
            }
            with patch.dict("app.graph.nodes._INTENT_TO_ROUTE",
                            {"": {"quote": "customer_quote_skill", "general": "general"}}):
                result = route_by_intent(state)
            assert result == "customer_order", (
                f"{msg!r} 在 customer_order 里被误判为话题切换（route={result}）—— "
                "会话被甩到报价 skill，order_create 将不可用"
            )
            assert state["pending_interact_skill"] == "customer_order"

    def test_quote_skill_stays_without_order_intent(self):
        """反向：顾客只是在报价流程里闲聊，不得被误切走（escape hatch 不能过宽）。"""
        state = {
            "pending_interact_skill": "customer_quote",
            "route_decision": {"action": "full_agent"},
            "intent_result": {"intent": "quote"},
            "messages": [HumanMessage(content="这个报价挺合适，再帮我看看褶皱倍数")],
        }
        with patch.dict("app.graph.nodes._INTENT_TO_ROUTE",
                        {"": {"quote": "customer_quote_skill", "general": "general"}}):
            result = route_by_intent(state)
        # 会话连续性返回的是 pending skill 的**节点名**（原样），不走 intent 映射
        assert result == "customer_quote"
        assert state["pending_interact_skill"] == "customer_quote"

    # ── #3557（G1）：确认卡「答卡轮」必须留在发卡 skill 里 ──────────────────────
    # 判据不是"答卡轮一律不切域"（那会踩 #3361：报价卡后顾客另起一句「确认下单」
    # 必须切到 customer_order），而是**本轮输入逐字等于本 skill 自己那张卡的
    # confirmValue** —— 只有点击卡片回传系统自产值才会逐字相等。
    def test_pr007_confirm_card_round_stays_in_product_skill(self):
        """PR-007 R2：逐字回传商品上下架卡的 confirmValue → 必须留在 product。

        缺陷（issue #3557 / CI run 34808115143，PR-007 score 50%）：卡值里那句
        「（改为停售，买家不可下单）」含「下单」→ L1 规则表判 `order_create`
        （`rule_matcher.py`）→ 本领域词表 `{"查商品","搜商品","创建商品","商品管理"}`
        全不命中 → escape hatch 命中 order 域词 → **清空会话锁** → intent 兜底
        `order_create → 'order'` → 进 `order` skill（`ORDER_TOOLS` 里**没有**
        `product_manage`）→ 零工具调用，模型只能以「订单模块」口径拒执行。
        确定性：零 LLM 可复现（同一句去掉「（改为停售，买家不可下单）」即不复现）。
        """
        state = {
            "pending_interact_skill": "product",
            "last_confirm_skill": "product",
            "last_confirm_value": PR007_CONFIRM_VALUE,
            "route_decision": {"action": "full_agent"},
            "intent_result": {"intent": "order_create", "confidence": 0.98, "source": "rule"},
            "messages": [HumanMessage(content=PR007_CONFIRM_VALUE)],
            "session_id": "sess_pr007",
            "agent_type": "mibao",
        }
        result = route_by_intent(state)
        assert result == "product", (
            f"答卡轮被路由到 {result!r}——发卡 skill 的上下文丢失，"
            "写工具 product_manage 不可达（#3557）"
        )
        assert state["pending_interact_skill"] == "product", "答卡轮不得清空本 skill 的会话锁"

    def test_pr007_counterfactual_card_value_without_cross_domain_word(self):
        """反事实对照：同一句**去掉**「（改为停售，买家不可下单）」→ 仍留 product。

        这条修复前就该绿 —— 它证明缺陷的判据是「卡值文本是否命中跨域关键词」，
        与答卡机制本身无关（PR-016 形态的无跨域词卡值同样留得住）。
        """
        value = "确认：商品名称=遮光窗帘；当前价格=¥168.00；当前状态=在售；操作=下架"
        state = {
            "pending_interact_skill": "product",
            "last_confirm_skill": "product",
            "last_confirm_value": value,
            "route_decision": {"action": "full_agent"},
            "intent_result": {"intent": "product_inquiry", "confidence": 0.95, "source": "rule"},
            "messages": [HumanMessage(content=value)],
            "session_id": "sess_pr007_cf",
            "agent_type": "mibao",
        }
        assert route_by_intent(state) == "product"
        assert state["pending_interact_skill"] == "product"

    def test_card_value_from_other_skill_does_not_block_escape(self):
        """反向契约：卡是**别的 skill** 发的 → 答卡轮豁免不生效，照旧允许话题切换。

        这条与原 `test_pending_skill_escape_hatch_switches_domain` 同源，补上
        `last_confirm_skill` 区分度：只有"本 skill 自己那张卡"才配豁免。
        """
        state = {
            "pending_interact_skill": "product",
            "last_confirm_skill": "order",          # 卡由 order skill 下发
            "last_confirm_value": "确认：订单号=EVAL-ORD-0001；操作=发货",
            "route_decision": {"action": "full_agent"},
            "intent_result": {"intent": "order_query"},
            "messages": [HumanMessage(content="帮我查一下订单")],
            "agent_type": "mibao",
        }
        with patch.dict("app.graph.nodes._INTENT_TO_ROUTE",
                        {"mibao": {"order_query": "order_skill", "general": "general"}}):
            result = route_by_intent(state)
        assert result == "order_skill"

    def test_no_pending_routes_by_intent(self):
        state = {
            "route_decision": {"action": "full_agent"},
            "intent_result": {"intent": "product_inquiry"},
            "messages": [HumanMessage(content="搜窗帘")],
            "agent_type": "",
        }
        with patch.dict("app.graph.nodes._INTENT_TO_ROUTE",
                        {"": {"product_inquiry": "product_skill", "general": "general"}}):
            result = route_by_intent(state)
        assert result == "product_skill"


class TestCurrentDomainSignalPriority:
    """本领域信号优先于话题切换（issue #3361，CH-012 复现型红灯的真因）。

    CH-012 实证（CI run 34703192730 / 34704068475）：
      R1 在 `customer_aftersales` 下发「请选择要退货的订单」choice 卡；
      R2 顾客回「我要退上次买的那单，订单号 EVAL-ORD-0002」——同一句里既有
      **本领域**信号（「退」）又有 **order 域**词（「订单号」）；
      旧逻辑只问"有没有别的领域词" → 判为话题切换 → 甩到 `customer_order`
      （**没有 aftersale_create**）→ 模型只能尝试转人工 → 被在办兜底拦住 →
      三轮原地打转、售后单永不创建。

    语义：顾客在退货流程里提订单号，是**流程内指代**，不是换话题。
    """

    def _route(self, msg, pending, intent, mapping):
        from langchain_core.messages import HumanMessage
        state = {
            "messages": [HumanMessage(content=msg)],
            "pending_interact_skill": pending,
            "route_decision": {"action": "full_agent"},
            "intent_result": {"intent": intent},
            "agent_type": "xiaobu",
            "tenant_id": 1,
        }
        with patch.dict("app.graph.nodes._INTENT_TO_ROUTE", {"xiaobu": mapping}):
            return route_by_intent(state)

    def test_return_flow_message_with_order_no_stays(self):
        mapping = {"order_query": "customer_order_skill", "after_sales": "customer_aftersales_skill",
                   "general": "customer_general_skill"}
        assert self._route("我要退上次买的那单，订单号 EVAL-ORD-0002",
                           "customer_aftersales", "order_query", mapping) == "customer_aftersales"

    def test_bare_tui_is_aftersales_signal(self):
        """C 端口语「我要退…」不含「退货」三字，也必须算 aftersales 信号。"""
        from app.graph.nodes import _SKILL_DOMAIN_KEYWORDS
        assert "退" in _SKILL_DOMAIN_KEYWORDS["aftersales"]

    def test_genuine_topic_switch_still_works(self):
        """无反退域信号时，话题切换必须照旧生效（不能把 escape hatch 关死）。"""
        mapping = {"order_query": "customer_order_skill", "general": "customer_general_skill"}
        assert self._route("帮我查一下我的订单", "customer_product", "order_query",
                           mapping) == "customer_order_skill"

    def test_order_signal_escapes_product_lock(self):
        """在办商品锁里顾客说「确认下单」（intent=order_create）→ 必须逃逸到下单技能。

        C-A1 P1 的完整链条（#3476）：pending=customer_product 时「确认下单」被
        短消息合成意图打成 general → escape 命中 order 域关键词却路由到 general skill
        （无 order_create）→ 模型只能"我下不了单"并转人工。本测试锁"escape + 正确意图
        → 落到下单技能"这一半。
        """
        mapping = {"order_create": "customer_order_skill", "general": "customer_general_skill"}
        assert self._route("确认下单", "customer_product", "order_create",
                           mapping) == "customer_order_skill", (
            "下单信号必须从商品锁逃逸到下单技能（C-A1 P1）")

    def test_customer_product_inquiry_switches_to_product(self):
        """C 端口语型商品询问必须能切到商品域（issue #3364，E2E 实测红）。

        `_SKILL_DOMAIN_KEYWORDS["product"]` 是管理端说法（查商品/搜商品/创建商品/商品管理），
        E2E `test_topic_switch_does_not_leak_order_context` 的顾客说的是
        「有什么遮光窗帘推荐」——一个都不命中 → 会话被订单卡锁住 → round2 调不出商品工具。
        修法用**句式**（询问/求推荐）而非裸词，见 `_SKILL_DOMAIN_PATTERNS`。
        """
        mapping = {"product_inquiry": "customer_product_skill", "general": "customer_general_skill"}
        for msg in ("有什么遮光窗帘推荐", "看看这款面料", "有没有雪尼尔面料"):
            assert self._route(msg, "customer_order", "product_inquiry",
                               mapping) == "customer_product_skill", f"{msg!r} 未切到商品域"

    def test_order_instruction_with_product_noun_stays_in_order(self):
        """反向保护：下单指令里提到商品名**不得**被当成切到商品域（否则下单流程被甩走）。

        「遮光窗帘 3 米，要打孔加工」含商品名词但无询问句式 → 必须留在 customer_order
        （OR-014/OR-017 依赖该行为）。
        """
        mapping = {"product_inquiry": "customer_product_skill", "order_create": "customer_order_skill"}
        # 会话连续性返回的是 pending skill 名本身（不走 intent 映射）
        assert self._route("遮光窗帘 3 米，要打孔加工", "customer_order", "order_create",
                           mapping) == "customer_order"

    def test_switch_to_order_from_quote_still_works(self):
        """报价 skill 无 order 域关键词 → 「我要下单」仍可切回下单流程。"""
        mapping = {"order_create": "customer_order_skill", "general": "customer_general_skill"}
        assert self._route("我要下单", "customer_quote", "order_create",
                           mapping) == "customer_order_skill"


class TestEscapeHatchHonoursRuleIntent:
    """#3557 G3/T2：escape hatch 丢弃 L1 已算出的高置信 intent（独立根因，非答卡轮）。

    `_SKILL_DOMAIN_KEYWORDS["product"]` 只有**查询**口径（查商品/搜商品/创建商品/商品管理），
    没有任何商品**动作**词；且 `route_by_intent` 完全不参考 L1 高置信判定 ⇒ 会话锁在非商品域
    时，商品动作全部被困：

    | 前置         | 输入                | L1 判定            | 旧行为（探针实测） |
    |---|---|---|---|
    | pending=order | 再把它上架           | product_inquiry 0.95 | order（拒绝）|
    | pending=order | 改一下遮光窗帘的价格   | product_inquiry      | order（拒绝）|
    | pending=order | 查一下库存           | product_inquiry      | order（拒绝）|
    | pending=order | 把遮光窗帘下架        | 无 L1（动作词不在表内）| order（拒绝）|

    修法两层（最小）：① product 词表补**商品专属动作词**「上架/下架」（裸名词会坏事，
    见 `_SKILL_DOMAIN_PATTERNS` 注释；动词不会——C 端下单/报价/售后话术里不出现）；
    ② L1 高置信（`route_decision.source == "rule"`）判到**可路由**的域 → 放行逃逸，
    不再要求消息逐字命中词表。
    """

    @staticmethod
    def _route(msg, pending, intent, source="rule", mapping=None):
        state = {
            "messages": [HumanMessage(content=msg)],
            "pending_interact_skill": pending,
            "route_decision": {"action": "full_agent", "source": source},
            "intent_result": {"intent": intent, "confidence": 0.95, "source": source},
            "agent_type": "mibao",
            "session_id": "sess_g3",
        }
        with patch.dict("app.graph.nodes._INTENT_TO_ROUTE",
                        {"mibao": mapping or {"product_inquiry": "product_skill",
                                              "order_query": "order_skill",
                                              "general": "general_skill"}}):
            return route_by_intent(state)

    @pytest.mark.parametrize("msg,intent", [
        ("再把它上架", "product_inquiry"),          # 动作词 + L1 高置信
        ("把遮光窗帘下架", "product_inquiry"),        # 动作词（L1 不认，靠词表补）→ 补词后 L1 亦命中
        ("改一下遮光窗帘的价格", "product_inquiry"),  # 查询口径词表不含，靠 L1 放行
        ("查一下库存", "product_inquiry"),           # 同上
    ])
    def test_product_action_escapes_non_product_lock(self, msg, intent):
        result = self._route(msg, "order", intent)
        assert result == "product_skill", (
            f"pending=order 时 {msg!r} 仍被困在 {result!r} —— "
            "order skill 没有 product_manage，模型只能以「模块越界」口径拒绝（G3/T2）"
        )

    def test_low_confidence_intent_does_not_escape(self):
        """反向保护：LLM 分类器（source=classifier）判出的意图**不**放行逃逸。

        放宽口子必须只对 L1 规则命中开（高置信、确定性）；否则短信/答卡值被
        分类器误判成别的域时会重演"会话锁被甩走"的老问题。
        """
        assert self._route("好的", "order", "product_inquiry",
                           source="classifier") == "order"

    def test_rule_intent_without_target_skill_stays(self):
        """反向保护：L1 判到**不可路由**的意图（无对应 skill 映射）→ 不逃逸。"""
        assert self._route("你好", "order", "greeting", source="rule",
                           mapping={"greeting": "direct_reply"}) == "order"

    def test_product_action_words_are_minimal_set(self):
        """词表只补商品**专属动作**词（防贪多引入跨域误切换）。"""
        from app.graph.nodes import _SKILL_DOMAIN_KEYWORDS
        product_kw = _SKILL_DOMAIN_KEYWORDS["product"]
        assert {"上架", "下架"} <= product_kw
        # 「价格」「库存」**故意不加**：C 端报价/下单话术高频出现（「这个价格帮我下单」
        # 「库存还有吗」），入表会让 customer_quote/customer_order 的会话锁被误逃逸；
        # 这两条由上面的 L1 高置信放行覆盖（不需要进词表）。
        assert "价格" not in product_kw and "库存" not in product_kw

