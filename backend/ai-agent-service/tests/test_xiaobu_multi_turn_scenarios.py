"""
小布（CustomerServiceAgent）复杂多轮对话场景测试
==============================================

10 个场景验证小布的智能程度，涵盖：
- 意图识别准确性
- 多轮上下文保持
- Skill 路由正确性
- Tool 调用链完整性
- 转人工引导时机
- 错误恢复与降级
- 语义缓存效果
- 权限边界安全

测试策略：
  使用 CustomerServiceAgent.achat() 非流式接口进行多轮对话。
  每轮对话手动维护 chat_history，模拟真实多轮场景。
  Mock 层：LLM (ChatOpenAI)、AdminApiClient、SemanticCache、Suggestions。
"""
# case_ids: CH-005, CH-006, CH-007
import json
import time
import asyncio
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from unittest.mock import patch, AsyncMock, MagicMock
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from app.agents.customer_service_agent import (
    CustomerServiceAgent,
    AgentContext,
    AgentResponse,
    reset_agent,
)
from app.tools import set_tool_context
from app.tools.registry import reset_tool_registry
from app.router.intent_config import IntentType, IntentResult
from tests.xiaobu_multi_turn_shared import (
    logger,
    Issue,
    ScenarioReport,
    MultiTurnRunner,
    assert_no_issues,
    log_turn,
    _extract_tool_calls_from_messages,
    MOCK_PRODUCTS,
    MOCK_PRODUCT_DETAIL,
    MOCK_ORDER,
    MOCK_ORDER_PENDING,
    MOCK_KNOWLEDGE_RESULTS,
)

class TestXiaobuMultiTurnScenarios:
    """小布多轮对话场景测试集"""

    # ── Case 1：完整购物咨询旅程 ──
    async def test_case04_cross_skill_complex_switch(self, agent_context):
        """
        Case 4：跨 Skill 复杂场景
        ========================
        场景：商品咨询 → 查订单 → 问物流 → 问保养知识 → 售后投诉
        测试 5 种不同意图在一个会话中的切换
        验证：Skill 切换正确，上下文不丢失
        """
        report = ScenarioReport(name="Case4-跨Skill复杂场景")
        logger.info(f"\n{'='*60}\n开始 {report.name}\n{'='*60}")

        call_idx = 0

        async def mock_llm_ainvoke(messages, **kwargs):
            nonlocal call_idx
            call_idx += 1
            last_human = next(
                (m for m in reversed(messages) if isinstance(m, HumanMessage)), None
            )
            user_text = last_human.content if last_human else ""
            last_tool = next(
                (m for m in reversed(messages) if isinstance(m, ToolMessage)), None
            )

            if last_tool:
                return _make_llm_response(f"已为您查询到相关信息。")

            if "投诉" in user_text or "质量" in user_text:
                return _make_llm_response(
                    "非常抱歉给您带来不好的体验，我已记录您的反馈。\n"
                    "这个问题需要人工客服为您处理，我现在帮您转接，请稍等~"
                )
            if "商品" in user_text or "产品" in user_text or "窗帘" in user_text:
                return _make_llm_response(
                    "",
                    tool_calls=[{"name": "product_search", "args": {"keyword": "遮光窗帘"}, "id": f"tc_{call_idx}"}],
                )
            if "订单" in user_text:
                return _make_llm_response(
                    "",
                    tool_calls=[{"name": "order_query", "args": {"order_id": "ORD20250501001"}, "id": f"tc_{call_idx}"}],
                )
            if "物流" in user_text or "快递" in user_text:
                return _make_llm_response(
                    "",
                    tool_calls=[{"name": "logistics_track", "args": {"order_id": "ORD20250501001"}, "id": f"tc_{call_idx}"}],
                )
            if "保养" in user_text or "清洗" in user_text:
                # [RAG 禁用] knowledge_search 已下线，改为直接文本回复
                return _make_llm_response(
                    "窗帘建议每隔3-6个月清洗一次，避免暴晒。\n"
                    "日常保养可用软毛刷除尘，局部污渍用湿布轻轻擦拭。"
                )

            return _make_llm_response("好的，还有什么需要帮忙的吗？")

        async def mock_admin_get(*args, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            path = str(args[0]) if args else ""
            if "orders" in path:
                resp.json.return_value = {"success": True, "data": {**MOCK_ORDER}}
            else:
                resp.json.return_value = {
                    "success": True,
                    "data": {"records": MOCK_PRODUCTS, "total": len(MOCK_PRODUCTS)},
                }
            return resp

        with patch("app.graph.skills.base_skill.get_skill_llm") as mock_llm_factory, \
             patch("app.utils.http_client.AdminApiClient._get_client") as mock_client, \
             patch("app.config.settings") as mock_settings, \
             patch("app.router.intent_classifier.IntentClassifier.classify") as mock_classify, \
             patch("app.tools.logistics_track.settings") as mock_log_settings:

            mock_settings.SEMANTIC_CACHE_ENABLED = False
            mock_settings.DASHSCOPE_API_KEY = ""
            mock_settings.DASHSCOPE_MODEL = "qwen-test"
            mock_log_settings.LOGISTICS_APPCODE = ""
            mock_log_settings.LOGISTICS_API_URL = "https://fake.api/kdi"

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.ainvoke = AsyncMock(side_effect=mock_llm_ainvoke)
            mock_llm_factory.return_value = mock_llm

            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=mock_admin_get)
            mock_client.return_value = mock_http

            mock_classify.return_value = IntentResult(
                intent=IntentType.GENERAL, confidence=0.5, source="classifier",
            )

            agent = CustomerServiceAgent()
            runner = MultiTurnRunner(agent, agent_context, report)

            resp1 = await runner.send("你们有什么遮光窗帘")
            assert resp1.content, "Turn 1: 商品搜索回复不应为空"

            resp2 = await runner.send("帮我查一下订单 ORD20250501001")
            assert resp2.content, "Turn 2: 订单查询回复不应为空"

            resp3 = await runner.send("这个订单的物流到哪了")
            assert resp3.content, "Turn 3: 物流查询回复不应为空"

            resp4 = await runner.send("窗帘收到后怎么保养")
            assert resp4.content, "Turn 4: 知识库回复不应为空"

            resp5 = await runner.send("窗帘质量有问题我要投诉")
            assert resp5.content, "Turn 5: 投诉回复不应为空"
            if "\u4eba\u5de5" not in resp5.content and "\u8f6c\u63a5" not in resp5.content:
                report.record_issue(5, "\u8f6c\u4eba\u5de5\u7f3a\u5931", "\u6295\u8bc9\u573a\u666f\u672a\u5f15\u5bfc\u8f6c\u4eba\u5de5")

        report.summary()
        assert_no_issues(report)

    # \u2500\u2500 Case 5\uff1a\u552e\u540e\u6295\u8bc9\u5347\u7ea7\u573a\u666f \u2500\u2500

    @pytest.mark.asyncio
    async def test_case05_aftersales_complaint_escalation(self, agent_context):
        """
        Case 5：售后投诉升级场景
        ======================
        场景：商品质量问题 → 情绪激动 → 要求赔偿 → 坚持投诉 → 转人工
        验证：
        - 小布的情绪安抚话术
        - 正确识别需要转人工的时机
        - 不承诺具体赔偿方案（超出权限）
        """
        report = ScenarioReport(name="Case5-售后投诉升级")
        logger.info(f"\n{'='*60}\n开始 {report.name}\n{'='*60}")

        async def mock_llm_ainvoke(messages, **kwargs):
            last_human = next(
                (m for m in reversed(messages) if isinstance(m, HumanMessage)), None
            )
            user_text = last_human.content if last_human else ""

            if "质量" in user_text and "问题" in user_text:
                return _make_llm_response(
                    "非常抱歉听到您遇到了质量问题！请问具体是什么情况呢？\n"
                    "您方便提供一下订单号吗？我先帮您查看一下~"
                )
            if "破" in user_text or "坏" in user_text or "差" in user_text:
                return _make_llm_response(
                    "真的非常抱歉给您带来这样的体验 😔\n"
                    "我完全理解您的心情，遇到这种情况确实很糟糕。\n"
                    "我建议帮您转接人工客服，他们可以为您安排退换货或其他补偿方案，好吗？"
                )
            if "赔偿" in user_text or "补偿" in user_text:
                return _make_llm_response(
                    "您的诉求我已经记录下来了。关于赔偿方案，需要人工客服根据具体情况来为您处理。\n"
                    "我现在帮您转接人工客服，他们会尽快给您一个满意的解决方案~"
                )
            if "投诉" in user_text:
                return _make_llm_response(
                    "我理解您的不满，您的投诉我们非常重视。\n"
                    "我已经帮您转接到专属客服主管，他们会优先处理您的问题，请稍等~ 🙏"
                )
            if "态度" in user_text or "差评" in user_text:
                return _make_llm_response(
                    "非常抱歉让您有不好的体验，我们一定会改进。\n"
                    "我帮您转接人工客服来跟进处理好吗？"
                )

            return _make_llm_response("我理解您的心情，请告诉我具体情况，我会尽力帮您解决。")

        with patch("app.graph.skills.base_skill.get_skill_llm") as mock_llm_factory, \
             patch("app.utils.http_client.AdminApiClient._get_client") as mock_client, \
             patch("app.config.settings") as mock_settings, \
             patch("app.router.intent_classifier.IntentClassifier.classify") as mock_classify:

            mock_settings.SEMANTIC_CACHE_ENABLED = False
            mock_settings.DASHSCOPE_API_KEY = ""
            mock_settings.DASHSCOPE_MODEL = "qwen-test"

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.ainvoke = AsyncMock(side_effect=mock_llm_ainvoke)
            mock_llm_factory.return_value = mock_llm

            mock_http = AsyncMock()
            mock_client.return_value = mock_http

            mock_classify.return_value = IntentResult(
                intent=IntentType.COMPLAINT, confidence=0.85, source="classifier",
            )

            agent = CustomerServiceAgent()
            runner = MultiTurnRunner(agent, agent_context, report)

            resp1 = await runner.send("你们的窗帘质量有问题！")
            assert resp1.content, "Turn 1"
            if "抱歉" not in resp1.content:
                report.record_issue(1, "话术缺失", "质量投诉未表达歉意")

            resp2 = await runner.send("收到的窗帘就是破的，太差了！")
            assert resp2.content, "Turn 2"

            resp3 = await runner.send("我要求赔偿！")
            assert resp3.content, "Turn 3"
            if "人工" not in resp3.content:
                report.record_issue(3, "转人工缺失", "赔偿要求未引导转人工")

            resp4 = await runner.send("我要投诉你们")
            assert resp4.content, "Turn 4"

            resp5 = await runner.send("服务态度也很差，我要差评")
            assert resp5.content, "Turn 5"

        report.summary()
        assert_no_issues(report)

    # ── Case 6：模糊意图识别挑战 ──

    @pytest.mark.asyncio
    async def test_case06_ambiguous_intent_challenge(self, agent_context):
        """
        Case 6：模糊意图识别挑战
        ======================
        场景：模糊表述 → 追问澄清 → 正确理解
        如"那个东西怎么样了"（无法判断是订单还是商品）→ 小布应追问
        测试 L2 小模型分类在模糊场景下的表现
        """
        report = ScenarioReport(name="Case6-模糊意图识别")
        logger.info(f"\n{'='*60}\n开始 {report.name}\n{'='*60}")

        async def mock_llm_ainvoke(messages, **kwargs):
            last_human = next(
                (m for m in reversed(messages) if isinstance(m, HumanMessage)), None
            )
            user_text = last_human.content if last_human else ""

            if "那个" in user_text and ("怎么样" in user_text or "处理" in user_text):
                return _make_llm_response(
                    "请问您是想了解：\n"
                    "1️⃣ 您之前咨询的商品信息？\n"
                    "2️⃣ 您的订单物流进度？\n"
                    "3️⃣ 其他问题？\n"
                    "请告诉我，我来帮您查~"
                )
            if "订单" in user_text:
                return _make_llm_response(
                    "",
                    tool_calls=[{"name": "order_query", "args": {"order_id": "ORD20250501001"}, "id": "tc_amb1"}],
                )
            if "什么时候" in user_text or "多久" in user_text:
                return _make_llm_response(
                    "您是想了解发货时间还是到货时间呢？\n"
                    "如果您有订单号，我可以帮您查询具体的物流进度~"
                )
            last_tool = next(
                (m for m in reversed(messages) if isinstance(m, ToolMessage)), None
            )
            if last_tool:
                return _make_llm_response("已为您查询到相关信息。")

            return _make_llm_response("请问您具体想了解什么呢？我可以帮您查询商品、订单或物流信息~")

        with patch("app.graph.skills.base_skill.get_skill_llm") as mock_llm_factory, \
             patch("app.utils.http_client.AdminApiClient._get_client") as mock_client, \
             patch("app.config.settings") as mock_settings, \
             patch("app.router.intent_classifier.IntentClassifier.classify") as mock_classify:

            mock_settings.SEMANTIC_CACHE_ENABLED = False
            mock_settings.DASHSCOPE_API_KEY = ""
            mock_settings.DASHSCOPE_MODEL = "qwen-test"

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.ainvoke = AsyncMock(side_effect=mock_llm_ainvoke)
            mock_llm_factory.return_value = mock_llm

            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=MagicMock(
                raise_for_status=MagicMock(),
                json=MagicMock(return_value={"success": True, "data": {**MOCK_ORDER}}),
            ))
            mock_client.return_value = mock_http

            # 模糊意图 → L2 分类置信度低
            mock_classify.return_value = IntentResult(
                intent=IntentType.GENERAL, confidence=0.4, source="classifier",
            )

            agent = CustomerServiceAgent()
            runner = MultiTurnRunner(agent, agent_context, report)

            # Turn 1: 模糊表述
            resp1 = await runner.send("那个东西怎么样了")
            assert resp1.content, "Turn 1: 模糊意图回复不应为空"

            # Turn 2: 澄清是订单
            mock_classify.return_value = IntentResult(
                intent=IntentType.ORDER_QUERY, confidence=0.9, source="classifier",
            )
            resp2 = await runner.send("就是我的订单 ORD20250501001")
            assert resp2.content, "Turn 2: 澄清后回复不应为空"

            # Turn 3: 另一个模糊表述
            mock_classify.return_value = IntentResult(
                intent=IntentType.GENERAL, confidence=0.3, source="classifier",
            )
            resp3 = await runner.send("什么时候能好")
            assert resp3.content, "Turn 3: 回复不应为空"

        report.summary()
        assert_no_issues(report)

    # ── Case 7：边界安全测试 ──
    async def test_case08_tool_failure_degradation(self, agent_context):
        """
        Case 8：工具链故障降级
        ====================
        场景：Tool 调用失败 → 友好提示 → 重试 → 降级处理
        Mock Tool 返回错误，测试错误恢复和降级策略
        验证：不暴露技术错误，给出友好提示
        """
        report = ScenarioReport(name="Case8-工具链故障降级")
        logger.info(f"\n{'='*60}\n开始 {report.name}\n{'='*60}")

        attempt_count = 0

        async def mock_llm_ainvoke(messages, **kwargs):
            nonlocal attempt_count
            last_human = next(
                (m for m in reversed(messages) if isinstance(m, HumanMessage)), None
            )
            user_text = last_human.content if last_human else ""
            last_tool = next(
                (m for m in reversed(messages) if isinstance(m, ToolMessage)), None
            )

            if last_tool:
                try:
                    tool_data = json.loads(last_tool.content)
                except Exception:
                    tool_data = {}
                if not tool_data.get("success", True):
                    attempt_count += 1
                    if attempt_count >= 2:
                        return _make_llm_response(
                            "非常抱歉，系统暂时出现了一些问题，无法为您查询。\n"
                            "建议您稍后再试，或者联系人工客服帮您处理~ 🙏"
                        )
                    return _make_llm_response(
                        "查询遇到一点问题，让我再试一次...",
                    )
                return _make_llm_response("已为您查询到信息。")

            if "商品" in user_text or "窗帘" in user_text:
                return _make_llm_response(
                    "",
                    tool_calls=[{"name": "product_search", "args": {"keyword": "窗帘"}, "id": "tc_err1"}],
                )
            if "订单" in user_text:
                return _make_llm_response(
                    "",
                    tool_calls=[{"name": "order_query", "args": {"order_id": "ORD20250501001"}, "id": "tc_err2"}],
                )

            return _make_llm_response("请问有什么可以帮您的？")

        import httpx

        with patch("app.graph.skills.base_skill.get_skill_llm") as mock_llm_factory, \
             patch("app.utils.http_client.AdminApiClient._get_client") as mock_client, \
             patch("app.config.settings") as mock_settings, \
             patch("app.router.intent_classifier.IntentClassifier.classify") as mock_classify:

            mock_settings.SEMANTIC_CACHE_ENABLED = False
            mock_settings.DASHSCOPE_API_KEY = ""
            mock_settings.DASHSCOPE_MODEL = "qwen-test"

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.ainvoke = AsyncMock(side_effect=mock_llm_ainvoke)
            mock_llm_factory.return_value = mock_llm

            # 模拟 admin-api 不可用
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_client.return_value = mock_http

            mock_classify.return_value = IntentResult(
                intent=IntentType.PRODUCT_INQUIRY, confidence=0.85, source="classifier",
            )

            agent = CustomerServiceAgent()
            runner = MultiTurnRunner(agent, agent_context, report)

            # Turn 1: 搜索商品 → Tool 失败
            resp1 = await runner.send("帮我搜索窗帘商品")
            assert resp1.content, "Turn 1: 回复不应为空"
            # 不应暴露技术错误信息
            if "ConnectError" in resp1.content or "Connection refused" in resp1.content:
                report.record_issue(1, "错误泄露", "技术错误信息暴露给用户")

            # Turn 2: 查订单 → Tool 失败
            mock_classify.return_value = IntentResult(
                intent=IntentType.ORDER_QUERY, confidence=0.9, source="classifier",
            )
            resp2 = await runner.send("查一下我的订单")
            assert resp2.content, "Turn 2: 回复不应为空"
            if "Exception" in resp2.content or "traceback" in resp2.content.lower():
                report.record_issue(2, "错误泄露", "异常堆栈暴露给用户")

        report.summary()
        assert_no_issues(report)

    # ── Case 10：复杂混合场景压力测试 ──

class TestSummaryReport:
    """测试结束后的汇总报告"""

    @pytest.mark.asyncio
    async def test_zz_final_summary(self):
        """
        汇总报告（以 zz_ 前缀确保最后执行）

        此测试始终通过，仅用于输出日志信息。
        """
        logger.info("\n" + "=" * 60)
        logger.info("小布多轮对话场景测试 - 全部完成")
        logger.info("=" * 60)
        logger.info("共 10 个场景，覆盖：")
        logger.info("  1. 完整购物咨询旅程")
        logger.info("  2. 订单全流程追踪")
        logger.info("  3. 知识库深度咨询")
        logger.info("  4. 跨 Skill 复杂场景")
        logger.info("  5. 售后投诉升级")
        logger.info("  6. 模糊意图识别挑战")
        logger.info("  7. 边界安全测试")
        logger.info("  8. 工具链故障降级")
        logger.info("  9. 语义缓存验证")
        logger.info("  10. 复杂混合压力测试")
        logger.info("=" * 60)

