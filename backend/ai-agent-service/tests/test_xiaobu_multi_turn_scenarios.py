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

# ============ 日志配置 ============

logger = logging.getLogger("xiaobu_test")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("[%(levelname)s] %(message)s")
    )
    logger.addHandler(handler)


# ============ 问题追踪 ============

@dataclass
class Issue:
    """发现的问题"""
    turn: int
    category: str
    description: str


@dataclass
class ScenarioReport:
    """场景测试报告"""
    name: str
    issues: List[Issue] = field(default_factory=list)
    turns_executed: int = 0

    def record_issue(self, turn: int, category: str, description: str):
        issue = Issue(turn=turn, category=category, description=description)
        self.issues.append(issue)
        logger.warning(f"  ⚠ 问题[{category}] Turn#{turn}: {description}")

    def summary(self):
        if not self.issues:
            logger.info(f"✅ {self.name}: {self.turns_executed} 轮对话全部通过，未发现问题")
        else:
            logger.warning(
                f"⚠ {self.name}: {self.turns_executed} 轮对话，发现 {len(self.issues)} 个问题："
            )
            for i in self.issues:
                logger.warning(f"   - [Turn#{i.turn}][{i.category}] {i.description}")


def assert_no_issues(report: ScenarioReport):
    """断言场景无问题，否则测试失败"""
    assert not report.issues, (
        f"{report.name} 发现 {len(report.issues)} 个问题：" +
        "; ".join(f"[Turn#{i.turn}][{i.category}] {i.description}" for i in report.issues)
    )


# ============ 辅助函数 ============

def _extract_tool_calls_from_messages(messages) -> List[Dict[str, Any]]:
    """从消息列表中提取 Tool 调用详情"""
    tool_calls = []
    tool_results = {}

    # 先收集所有 ToolMessage 的结果
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_results[msg.tool_call_id] = msg.content

    # 再从 AIMessage 中提取 tool_calls
    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tc in msg.tool_calls:
                call_info = {
                    'name': tc.get('name', '?'),
                    'args': tc.get('args', {}),
                    'id': tc.get('id', ''),
                    'result': tool_results.get(tc.get('id', ''), None),
                }
                tool_calls.append(call_info)

    return tool_calls


def log_turn(
    turn_num: int,
    user_msg: str,
    intent_result: Optional[dict],
    skill_name: str,
    tool_calls: List[Dict[str, Any]],
    reply: str,
    suggestions: Optional[List[str]] = None,
    entities: Optional[dict] = None,
):
    """记录每轮对话的详细日志 - 增强版"""
    logger.info(f"\n  ╔{'═'*56}╗")
    logger.info(f"  ║  Turn #{turn_num}")
    logger.info(f"  ╠{'═'*56}╣")
    logger.info(f"  ║ 📥 用户输入: {user_msg}")
    logger.info(f"  ╠{'─'*56}╣")
    if intent_result:
        intent = intent_result.get('intent', '?')
        conf = intent_result.get('confidence', '?')
        source = intent_result.get('source', '?')
        logger.info(f"  ║ 🎯 意图识别: {intent} (置信度={conf}, 来源={source})")
    else:
        logger.info(f"  ║ 🎯 意图识别: (未捕获)")
    logger.info(f"  ║ 🔀 Skill路由: {skill_name or '(无)'}")
    if tool_calls:
        for tc in tool_calls:
            logger.info(f"  ║ 🔧 Tool调用: {tc['name']} | 参数={tc.get('args', {})}")
            if tc.get('result'):
                result_preview = str(tc['result'])[:100]
                logger.info(f"  ║    └─ 结果: {result_preview}...")
    else:
        logger.info(f"  ║ 🔧 Tool调用: (无)")
    logger.info(f"  ╠{'─'*56}╣")
    # 完整输出回复内容，不截断
    logger.info(f"  ║ 📤 小布回复:")
    for line in reply.split('\n'):
        logger.info(f"  ║    {line}")
    if suggestions:
        logger.info(f"  ║ 💡 建议问题: {suggestions}")
    if entities:
        logger.info(f"  ║ 📋 提取实体: {entities}")
    logger.info(f"  ╚{'═'*56}╝")


# ============ Mock 数据 ============

MOCK_PRODUCTS = [
    {"id": "prod_001", "name": "雪尼尔遮光窗帘", "price": 299.0, "status": "active",
     "stock": 100, "images": ["img1.jpg"], "tenantId": 1},
    {"id": "prod_002", "name": "棉麻透光纱帘", "price": 159.0, "status": "active",
     "stock": 50, "images": ["img2.jpg"], "tenantId": 1},
    {"id": "prod_003", "name": "电动遮光帘", "price": 599.0, "status": "active",
     "stock": 30, "images": ["img3.jpg"], "tenantId": 1},
]

MOCK_PRODUCT_DETAIL = {
    "id": "prod_001", "name": "雪尼尔遮光窗帘", "price": 299.0,
    "originalPrice": 399.0, "stock": 100, "status": "active",
    "description": "高档雪尼尔面料，遮光率95%，适合卧室使用",
    "categoryName": "遮光窗帘", "images": ["img1.jpg", "img2.jpg"],
    "skus": [
        {"id": "sku_001", "skuCode": "XNE-WH-270",
         "specifications": {"颜色": "白色", "尺寸": "2.0m×2.7m"},
         "price": 299.0, "stock": 50, "status": "active"},
    ],
    "specifications": {"面料": "雪尼尔", "遮光率": "95%", "工艺": "打孔"},
    "tenantId": 1,
}

MOCK_ORDER = {
    "id": "ORD20250501001",
    "status": "shipped",
    "totalAmount": 299.0,
    "items": [{"productName": "雪尼尔遮光窗帘", "quantity": 1, "price": 299.0}],
    "logistics": {
        "trackingNo": "SF1234567890",
        "company": "顺丰速运",
        "receiverPhone": "13800138000",
    },
    "tenantId": 1,
}

MOCK_ORDER_PENDING = {
    "id": "ORD20250501002",
    "status": "pending",
    "totalAmount": 159.0,
    "items": [{"productName": "棉麻透光纱帘", "quantity": 1, "price": 159.0}],
    "logistics": {},
    "tenantId": 1,
}

MOCK_KNOWLEDGE_RESULTS = {
    "面料": "雪尼尔面料具有绒面质感，手感柔软，不易起球，遮光效果好。",
    "清洗": "建议干洗或手洗，水温不超过30度，不可使用漂白剂。",
    "安装": "打孔窗帘安装步骤：1.确认窗帘杆位置 2.标记打孔点 3.使用电钻打孔 4.安装膨胀螺丝 5.放上窗帘杆 6.挂上窗帘",
    "尺寸": "测量窗帘尺寸：宽度=窗口宽度×1.5-2倍，高度=从杆到地面的距离-2cm",
}


# ============ Mock 工具函数 ============

def _make_llm_response(content: str, tool_calls=None) -> AIMessage:
    """构造 AIMessage 响应"""
    msg = AIMessage(content=content)
    if tool_calls:
        msg.tool_calls = tool_calls
    return msg


def _make_tool_result(success: bool, data: Any = None, error: str = None, message: str = None) -> str:
    return json.dumps(
        {"success": success, "data": data, "error": error, "message": message},
        ensure_ascii=False, default=str,
    )


# ============ 公共 Fixtures ============

@pytest.fixture(autouse=True)
def _reset_singletons():
    """每个测试重置全局单例"""
    reset_agent()
    reset_tool_registry()
    yield
    reset_agent()
    reset_tool_registry()


@pytest.fixture
def agent_context():
    """标准测试用 AgentContext"""
    return AgentContext(
        user_id="user_test_001",
        tenant_id=1,
        session_id="sess_multi_turn_001",
        role="customer",
        identity_type="wechat_mini",
    )


@pytest.fixture
def agent_context_b():
    """另一个用户的 AgentContext"""
    return AgentContext(
        user_id="user_test_002",
        tenant_id=1,
        session_id="sess_multi_turn_002",
        role="customer",
        identity_type="wechat_mini",
    )


def _build_mock_patches():
    """构建所有 Mock patch 列表"""
    return {
        "semantic_cache": patch(
            "app.graph.nodes.semantic_cache",
            new_callable=lambda: lambda: MagicMock(
                lookup=AsyncMock(return_value=None),
                store=AsyncMock(),
            ),
            create=True,
        ),
        "cache_settings": patch("app.graph.nodes.settings", create=True),
        "suggestions": patch(
            "app.graph.nodes.FollowUpSuggestionGenerator", create=True,
        ),
        "skill_llm": patch("app.graph.skills.base_skill.get_skill_llm"),
        "admin_api": patch("app.utils.http_client.AdminApiClient._get_client"),
        "tracker": patch("app.graph.skills.base_skill.get_tracker"),
        "classifier": patch("app.router.intent_classifier.IntentClassifier.classify"),
    }


class MultiTurnRunner:
    """
    多轮对话执行器

    封装 Agent 的多轮调用，维护 chat_history，记录详细日志和问题。
    """

    def __init__(self, agent: CustomerServiceAgent, context: AgentContext, report: ScenarioReport):
        self.agent = agent
        self.context = context
        self.chat_history: List[Dict[str, Any]] = []
        self.report = report
        self.turn = 0
        # 跟踪每轮的 intent 和 skill
        self.intent_chain: List[str] = []
        self.skill_chain: List[str] = []

    async def send(self, message: str) -> AgentResponse:
        """发送一条消息并获取回复，通过 graph.ainvoke 获取完整 AgentState"""
        self.turn += 1

        try:
            # 像 achat 一样构建消息列表和初始 state
            messages = self.agent._convert_history(self.chat_history)
            messages.append(HumanMessage(content=message))

            set_tool_context(self.context.to_tool_context())

            initial_state = self.agent._build_initial_state(messages, self.context)
            result = await self.agent.graph.ainvoke(initial_state)

            # 从完整 AgentState 中提取各项信息
            final_answer = result.get("final_answer", "")
            intent_result = result.get("intent_result", None)
            skill_used = result.get("skill_used", "")
            suggestions = result.get("suggestions", [])
            entities = result.get("entities", {})
            result_messages = result.get("messages", [])

            # 从 messages 中提取 tool 调用详情
            tool_calls = _extract_tool_calls_from_messages(result_messages)

            # 构建 AgentResponse（保持与 achat 兼容的返回值）
            resp = AgentResponse(
                content=final_answer,
                type="text",
                metadata={
                    "skill_used": skill_used,
                    "intent_result": intent_result,
                    "suggestions": suggestions,
                    "entities": entities,
                },
            )
        except Exception as e:
            logger.error(f"Agent error in send(): {e}", exc_info=True)
            resp = AgentResponse(
                content="抱歉，我遇到了一些问题，请稍后重试或联系人工客服。",
                type="error",
                metadata={"error": str(e)},
            )
            intent_result = None
            skill_used = ""
            tool_calls = []
            suggestions = []
            entities = {}

        # 记录到 history
        self.chat_history.append({"role": "user", "content": message})
        self.chat_history.append({"role": "assistant", "content": resp.content})

        # 增强日志输出
        log_turn(
            turn_num=self.turn,
            user_msg=message,
            intent_result=intent_result,
            skill_name=skill_used,
            tool_calls=tool_calls,
            reply=resp.content,
            suggestions=suggestions if suggestions else None,
            entities=entities if entities else None,
        )
        self.report.turns_executed = self.turn
        return resp


# ============ 10 个测试场景 ============

class TestXiaobuMultiTurnScenarios:
    """小布多轮对话场景测试集"""

    # ── Case 1：完整购物咨询旅程 ──

    @pytest.mark.asyncio
    async def test_case01_full_shopping_journey(self, agent_context):
        """
        Case 1：完整购物咨询旅程
        ========================
        场景：顾客从问候开始，搜索商品，查看详情，询问下单方式，最后告别。
        意图切换：greeting → product_inquiry → product_inquiry → general → farewell
        验证：
        - 问候回复包含小布自我介绍
        - 商品搜索通过 product_search 工具返回结果
        - 商品详情通过 product_detail 工具返回
        - 下单引导到小程序或转人工
        - 告别语友好自然
        """
        report = ScenarioReport(name="Case1-完整购物咨询旅程")
        logger.info(f"\n{'='*60}\n开始 {report.name}\n{'='*60}")

        llm_call_count = 0

        async def mock_llm_ainvoke(messages, **kwargs):
            nonlocal llm_call_count
            llm_call_count += 1
            last_human = next(
                (m for m in reversed(messages) if isinstance(m, HumanMessage)), None
            )
            user_text = last_human.content if last_human else ""

            # Turn 2: 搜索窗帘 → 调 product_search
            if "窗帘" in user_text and "详情" not in user_text and "详细" not in user_text:
                last_tool = next(
                    (m for m in reversed(messages) if isinstance(m, ToolMessage)), None
                )
                if last_tool:
                    return _make_llm_response(
                        "亲，为您找到以下窗帘产品：\n"
                        "1. 雪尼尔遮光窗帘 ¥299\n"
                        "2. 棉麻透光纱帘 ¥159\n"
                        "3. 电动遮光帘 ¥599\n"
                        "您对哪款感兴趣呢？"
                    )
                return _make_llm_response(
                    "",
                    tool_calls=[{
                        "name": "product_search",
                        "args": {"keyword": "窗帘"},
                        "id": f"tc_{llm_call_count}",
                    }],
                )

            # Turn 3: 第一款详情 → 调 product_detail
            if "第一款" in user_text or "雪尼尔" in user_text or "详情" in user_text:
                last_tool = next(
                    (m for m in reversed(messages) if isinstance(m, ToolMessage)), None
                )
                if last_tool:
                    return _make_llm_response(
                        "这款雪尼尔遮光窗帘非常受欢迎呢！\n"
                        "💰 价格：¥299（原价¥399）\n"
                        "🌟 面料：雪尼尔，手感柔软\n"
                        "🌙 遮光率：95%，非常适合卧室\n"
                        "📐 可选尺寸：2.0m×2.7m\n"
                        "目前有货哦，需要下单的话可以在小程序直接购买~"
                    )
                return _make_llm_response(
                    "",
                    tool_calls=[{
                        "name": "product_detail",
                        "args": {"product_id": "prod_001"},
                        "id": f"tc_{llm_call_count}",
                    }],
                )

            # Turn 4: 怎么下单
            if "下单" in user_text or "购买" in user_text:
                return _make_llm_response(
                    "您可以直接在微信小程序「米高窗帘」中下单购买哦~\n"
                    "如果需要定制尺寸，建议联系人工客服帮您处理，我可以帮您转接。"
                )

            return _make_llm_response("您好，有什么可以帮您的吗？")

        # 构建 mock admin-api 响应
        async def mock_admin_get(*args, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            path = args[0] if args else ""
            if "products/" in str(path) and not str(path).endswith("/products"):
                resp.json.return_value = {"success": True, "data": {**MOCK_PRODUCT_DETAIL}}
            else:
                resp.json.return_value = {
                    "success": True,
                    "data": {"records": MOCK_PRODUCTS, "total": len(MOCK_PRODUCTS)},
                }
            return resp

        with patch("app.graph.skills.base_skill.get_skill_llm") as mock_llm_factory, \
             patch("app.utils.http_client.AdminApiClient._get_client") as mock_client, \
             patch("app.graph.skills.base_skill.get_tracker") as mock_tracker, \
             patch("app.config.settings") as mock_settings, \
             patch("app.router.intent_classifier.IntentClassifier.classify") as mock_classify:

            mock_settings.SEMANTIC_CACHE_ENABLED = False
            mock_settings.DASHSCOPE_API_KEY = ""  # 关键：清空以禁用动态建议生成
            mock_settings.DASHSCOPE_MODEL = "qwen-test"

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.ainvoke = AsyncMock(side_effect=mock_llm_ainvoke)
            mock_llm_factory.return_value = mock_llm

            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=mock_admin_get)
            mock_client.return_value = mock_http

            mock_tracker_inst = MagicMock()
            mock_tracker_inst.extract_entities_from_tool_result = MagicMock()
            mock_tracker_inst.get_entities = MagicMock(return_value=MagicMock(
                order_nos=[], phone_numbers=[], product_names=[], product_ids=[], amounts=[],
            ))
            mock_tracker.return_value = mock_tracker_inst

            mock_classify.return_value = IntentResult(
                intent=IntentType.GENERAL, confidence=0.6, source="classifier",
            )

            agent = CustomerServiceAgent()
            runner = MultiTurnRunner(agent, agent_context, report)

            # Turn 1: 问候
            resp1 = await runner.send("你好")
            assert resp1.content, "Turn 1: 回复不应为空"
            # greeting 走 direct_reply，不经过 LLM

            # Turn 2: 搜索商品
            resp2 = await runner.send("我想看看你们的窗帘")
            assert resp2.content, "Turn 2: 回复不应为空"
            if "窗帘" not in resp2.content and "产品" not in resp2.content:
                report.record_issue(2, "内容缺失", "商品搜索回复中未提及窗帘/产品")

            # Turn 3: 查看详情
            resp3 = await runner.send("第一款雪尼尔的详细介绍一下")
            assert resp3.content, "Turn 3: 回复不应为空"
            if "299" not in resp3.content and "雪尼尔" not in resp3.content:
                report.record_issue(3, "内容缺失", "商品详情回复缺少价格或名称")

            # Turn 4: 下单咨询
            resp4 = await runner.send("怎么下单购买呢")
            assert resp4.content, "Turn 4: 回复不应为空"

            # Turn 5: 告别
            resp5 = await runner.send("好的谢谢，再见")
            assert resp5.content, "Turn 5: 回复不应为空"

        report.summary()
        assert_no_issues(report)

    # ── Case 2：订单全流程追踪 ──

    @pytest.mark.asyncio
    async def test_case02_order_tracking_full_flow(self, agent_context):
        """
        Case 2：订单全流程追踪
        ====================
        场景：顾客查询订单状态 → 追踪物流 → 催发货 → 要求修改订单 → 转人工
        意图切换：order_query → logistics_track → after_sales → human_handoff
        验证：
        - 订单查询通过 order_query 工具返回正确状态
        - 物流追踪通过 logistics_track 工具返回物流信息
        - 修改订单操作正确引导转人工
        """
        report = ScenarioReport(name="Case2-订单全流程追踪")
        logger.info(f"\n{'='*60}\n开始 {report.name}\n{'='*60}")

        async def mock_llm_ainvoke(messages, **kwargs):
            last_human = next(
                (m for m in reversed(messages) if isinstance(m, HumanMessage)), None
            )
            user_text = last_human.content if last_human else ""
            last_tool = next(
                (m for m in reversed(messages) if isinstance(m, ToolMessage)), None
            )

            if "订单" in user_text and "修改" not in user_text and "取消" not in user_text:
                if last_tool:
                    return _make_llm_response(
                        "您的订单 ORD20250501001 当前状态为【已发货】\n"
                        "商品：雪尼尔遮光窗帘 × 1\n"
                        "金额：¥299.00\n"
                        "如需查看物流详情，请告诉我~"
                    )
                return _make_llm_response(
                    "",
                    tool_calls=[{"name": "order_query", "args": {"order_id": "ORD20250501001"}, "id": "tc_oq1"}],
                )

            if "物流" in user_text or "快递" in user_text or "到哪" in user_text:
                if last_tool:
                    return _make_llm_response(
                        "物流信息如下：\n"
                        "📦 快递公司：顺丰速运\n"
                        "📋 运单号：SF1234567890\n"
                        "📍 最新状态：包裹已到达杭州转运中心\n"
                        "预计明天送达，请保持电话畅通~"
                    )
                return _make_llm_response(
                    "",
                    tool_calls=[{
                        "name": "logistics_track",
                        "args": {"order_id": "ORD20250501001"},
                        "id": "tc_lt1",
                    }],
                )

            if "催" in user_text or "快点" in user_text:
                return _make_llm_response(
                    "理解您着急的心情呢~ 根据物流信息，您的包裹已在运输途中，"
                    "预计明天就能到达。如果超时未到，请随时联系我们，我帮您跟进处理哦~"
                )

            if "修改" in user_text or "取消" in user_text:
                return _make_llm_response(
                    "非常抱歉，修改/取消订单需要人工客服为您处理。\n"
                    "我现在帮您转接人工客服，请稍等~ 🙏"
                )

            return _make_llm_response("请问您需要查询哪个订单呢？")

        async def mock_admin_get(*args, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"success": True, "data": {**MOCK_ORDER}}
            return resp

        with patch("app.graph.skills.base_skill.get_skill_llm") as mock_llm_factory, \
             patch("app.utils.http_client.AdminApiClient._get_client") as mock_client, \
             patch("app.graph.skills.base_skill.get_tracker") as mock_tracker, \
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

            mock_tracker_inst = MagicMock()
            mock_tracker_inst.extract_entities_from_tool_result = MagicMock()
            mock_tracker_inst.get_entities = MagicMock(return_value=MagicMock(
                order_nos=["ORD20250501001"], phone_numbers=[], product_names=[], product_ids=[], amounts=[],
            ))
            mock_tracker.return_value = mock_tracker_inst
            mock_classify.return_value = IntentResult(
                intent=IntentType.GENERAL, confidence=0.5, source="classifier",
            )

            agent = CustomerServiceAgent()
            runner = MultiTurnRunner(agent, agent_context, report)

            # Turn 1: 查订单
            resp1 = await runner.send("帮我查一下订单 ORD20250501001")
            assert "ORD20250501001" in resp1.content or "订单" in resp1.content, \
                "Turn 1: 应返回订单信息"

            # Turn 2: 查物流
            resp2 = await runner.send("物流到哪了")
            assert resp2.content, "Turn 2: 物流回复不应为空"

            # Turn 3: 催发货
            resp3 = await runner.send("能不能催一下快点到")
            assert resp3.content, "Turn 3: 催发货回复不应为空"

            # Turn 4: 修改订单 → 应引导转人工
            resp4 = await runner.send("我想修改一下收货地址")
            assert resp4.content, "Turn 4: 回复不应为空"
            has_human_handoff = any(
                kw in resp4.content for kw in ["人工", "转接", "客服处理"]
            )
            if not has_human_handoff:
                report.record_issue(4, "转人工缺失", "修改订单操作未引导转人工客服")

        report.summary()
        assert_no_issues(report)

    # ── Case 3：知识库深度咨询 ──

    @pytest.mark.asyncio
    async def test_case03_knowledge_deep_consultation(self, agent_context):
        """
        Case 3：知识库深度咨询
        ====================
        场景：顾客连续咨询面料 → 清洗保养 → 安装方法 → 尺寸测量
        同一 Skill（customer_knowledge_skill）内的上下文延续
        验证：knowledge_search 连续调用，回答基于检索结果
        """
        report = ScenarioReport(name="Case3-知识库深度咨询")
        logger.info(f"\n{'='*60}\n开始 {report.name}\n{'='*60}")

        knowledge_query_count = 0

        async def mock_llm_ainvoke(messages, **kwargs):
            nonlocal knowledge_query_count
            last_human = next(
                (m for m in reversed(messages) if isinstance(m, HumanMessage)), None
            )
            user_text = last_human.content if last_human else ""
            last_tool = next(
                (m for m in reversed(messages) if isinstance(m, ToolMessage)), None
            )

            if last_tool:
                knowledge_query_count += 1
                try:
                    tool_data = json.loads(last_tool.content)
                except Exception:
                    tool_data = {}
                answer = tool_data.get("data", {}).get("answer", "")
                return _make_llm_response(
                    f"根据我们的知识库，{answer}\n还有其他问题吗？"
                )

            # 首次发问 → 调知识库
            query = ""
            if "面料" in user_text or "材质" in user_text:
                query = "雪尼尔面料特性"
            elif "清洗" in user_text or "保养" in user_text:
                query = "窗帘清洗方法"
            elif "安装" in user_text:
                query = "窗帘安装步骤"
            elif "尺寸" in user_text or "测量" in user_text:
                query = "窗帘尺寸测量"
            else:
                query = user_text

            return _make_llm_response(
                "",
                tool_calls=[{
                    "name": "knowledge_search",
                    "args": {"query": query},
                    "id": f"tc_ks_{knowledge_query_count + 1}",
                }],
            )

        with patch("app.graph.skills.base_skill.get_skill_llm") as mock_llm_factory, \
             patch("app.utils.http_client.AdminApiClient._get_client") as mock_client, \
             patch("app.graph.skills.base_skill.get_tracker") as mock_tracker, \
             patch("app.config.settings") as mock_settings, \
             patch("app.router.intent_classifier.IntentClassifier.classify") as mock_classify, \
             patch("app.tools.knowledge_search._RAG_AVAILABLE", False):

            mock_settings.SEMANTIC_CACHE_ENABLED = False
            mock_settings.DASHSCOPE_API_KEY = ""
            mock_settings.DASHSCOPE_MODEL = "qwen-test"

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.ainvoke = AsyncMock(side_effect=mock_llm_ainvoke)
            mock_llm_factory.return_value = mock_llm

            mock_http = AsyncMock()
            mock_client.return_value = mock_http

            mock_tracker_inst = MagicMock()
            mock_tracker_inst.extract_entities_from_tool_result = MagicMock()
            mock_tracker_inst.get_entities = MagicMock(return_value=MagicMock(
                order_nos=[], phone_numbers=[], product_names=[], product_ids=[], amounts=[],
            ))
            mock_tracker.return_value = mock_tracker_inst
            mock_classify.return_value = IntentResult(
                intent=IntentType.KNOWLEDGE_FAQ, confidence=0.85, source="classifier",
            )

            agent = CustomerServiceAgent()
            runner = MultiTurnRunner(agent, agent_context, report)

            # Turn 1: 面料咨询
            resp1 = await runner.send("雪尼尔面料有什么特点")
            assert resp1.content, "Turn 1: 回复不应为空"

            # Turn 2: 清洗保养
            resp2 = await runner.send("这种面料怎么清洗保养")
            assert resp2.content, "Turn 2: 回复不应为空"

            # Turn 3: 安装方法
            resp3 = await runner.send("打孔窗帘怎么安装")
            assert resp3.content, "Turn 3: 回复不应为空"

            # Turn 4: 尺寸测量
            resp4 = await runner.send("窗帘尺寸怎么测量")
            assert resp4.content, "Turn 4: 回复不应为空"

            # 增强断言：验证知识库被调用 4 次
            if knowledge_query_count < 4:
                report.record_issue(4, "Tool调用不足", f"期望 knowledge_search 至少调用 4 次，实际: {knowledge_query_count}")

        report.summary()
        assert_no_issues(report)

    # ── Case 4：跨 Skill 复杂场景 ──

    @pytest.mark.asyncio
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
                return _make_llm_response(
                    "",
                    tool_calls=[{"name": "knowledge_search", "args": {"query": "窗帘保养"}, "id": f"tc_{call_idx}"}],
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
             patch("app.graph.skills.base_skill.get_tracker") as mock_tracker, \
             patch("app.config.settings") as mock_settings, \
             patch("app.router.intent_classifier.IntentClassifier.classify") as mock_classify, \
             patch("app.tools.knowledge_search._RAG_AVAILABLE", False), \
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

            mock_tracker_inst = MagicMock()
            mock_tracker_inst.extract_entities_from_tool_result = MagicMock()
            mock_tracker_inst.get_entities = MagicMock(return_value=MagicMock(
                order_nos=[], phone_numbers=[], product_names=[], product_ids=[], amounts=[],
            ))
            mock_tracker.return_value = mock_tracker_inst
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
             patch("app.graph.skills.base_skill.get_tracker") as mock_tracker, \
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

            mock_tracker_inst = MagicMock()
            mock_tracker_inst.extract_entities_from_tool_result = MagicMock()
            mock_tracker_inst.get_entities = MagicMock(return_value=MagicMock(
                order_nos=[], phone_numbers=[], product_names=[], product_ids=[], amounts=[],
            ))
            mock_tracker.return_value = mock_tracker_inst
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
             patch("app.graph.skills.base_skill.get_tracker") as mock_tracker, \
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

            mock_tracker_inst = MagicMock()
            mock_tracker_inst.extract_entities_from_tool_result = MagicMock()
            mock_tracker_inst.get_entities = MagicMock(return_value=MagicMock(
                order_nos=[], phone_numbers=[], product_names=[], product_ids=[], amounts=[],
            ))
            mock_tracker.return_value = mock_tracker_inst
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

    @pytest.mark.asyncio
    async def test_case07_permission_boundary_security(self, agent_context):
        """
        Case 7：边界安全测试
        ==================
        场景：尝试修改订单 → 尝试查看他人订单 → 尝试管理商品
        验证：
        - 小布只有查询权限
        - 修改操作正确拒绝并引导转人工
        - 不泄露其他用户数据
        """
        report = ScenarioReport(name="Case7-边界安全测试")
        logger.info(f"\n{'='*60}\n开始 {report.name}\n{'='*60}")

        async def mock_llm_ainvoke(messages, **kwargs):
            last_human = next(
                (m for m in reversed(messages) if isinstance(m, HumanMessage)), None
            )
            user_text = last_human.content if last_human else ""
            last_tool = next(
                (m for m in reversed(messages) if isinstance(m, ToolMessage)), None
            )

            if last_tool:
                return _make_llm_response("已为您查询到相关信息。")

            if any(kw in user_text for kw in ["取消", "修改", "删除"]):
                return _make_llm_response(
                    "抱歉，我暂时无法帮您执行修改/取消操作。\n"
                    "如需修改订单，我帮您转接人工客服处理哦~ 🙏"
                )
            if "上架" in user_text or "下架" in user_text or "管理" in user_text:
                return _make_llm_response(
                    "抱歉，商品管理操作需要通过管理后台进行，我作为客服无法帮您处理。\n"
                    "如有需要，请联系您的商家管理员~"
                )
            if "别人" in user_text or "他人" in user_text:
                return _make_llm_response(
                    "抱歉，为保护用户隐私，我只能查询您自己的订单信息。\n"
                    "如您有其他问题，请随时告诉我~"
                )
            if "库存" in user_text and "调整" in user_text:
                return _make_llm_response(
                    "库存调整需要管理员权限，我无法帮您处理。\n"
                    "如果您是想了解某商品是否有货，我可以帮您查询~"
                )

            return _make_llm_response("请问有什么可以帮您的？")

        with patch("app.graph.skills.base_skill.get_skill_llm") as mock_llm_factory, \
             patch("app.utils.http_client.AdminApiClient._get_client") as mock_client, \
             patch("app.graph.skills.base_skill.get_tracker") as mock_tracker, \
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

            mock_tracker_inst = MagicMock()
            mock_tracker_inst.extract_entities_from_tool_result = MagicMock()
            mock_tracker_inst.get_entities = MagicMock(return_value=MagicMock(
                order_nos=[], phone_numbers=[], product_names=[], product_ids=[], amounts=[],
            ))
            mock_tracker.return_value = mock_tracker_inst
            mock_classify.return_value = IntentResult(
                intent=IntentType.AFTER_SALES, confidence=0.8, source="classifier",
            )

            agent = CustomerServiceAgent()
            runner = MultiTurnRunner(agent, agent_context, report)

            # Turn 1: 尝试取消订单
            resp1 = await runner.send("帮我取消订单 ORD20250501001")
            assert resp1.content, "Turn 1"
            if "人工" not in resp1.content and "无法" not in resp1.content:
                report.record_issue(1, "权限边界", "取消订单操作未正确拒绝")

            # Turn 2: 尝试查看他人订单
            resp2 = await runner.send("帮我查查别人的订单")
            assert resp2.content, "Turn 2"
            if "隐私" not in resp2.content and "无法" not in resp2.content:
                report.record_issue(2, "权限边界", "查看他人订单未正确拒绝")

            # Turn 3: 尝试管理商品
            mock_classify.return_value = IntentResult(
                intent=IntentType.GENERAL, confidence=0.6, source="classifier",
            )
            resp3 = await runner.send("帮我把那款窗帘下架")
            assert resp3.content, "Turn 3"
            if "管理" not in resp3.content and "无法" not in resp3.content:
                report.record_issue(3, "权限边界", "商品管理操作未正确拒绝")

            # Turn 4: 尝试调整库存
            resp4 = await runner.send("调整一下雪尼尔窗帘的库存")
            assert resp4.content, "Turn 4"

        report.summary()
        assert_no_issues(report)

    # ── Case 8：工具链故障降级 ──

    @pytest.mark.asyncio
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
             patch("app.graph.skills.base_skill.get_tracker") as mock_tracker, \
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

            mock_tracker_inst = MagicMock()
            mock_tracker_inst.extract_entities_from_tool_result = MagicMock()
            mock_tracker_inst.get_entities = MagicMock(return_value=MagicMock(
                order_nos=[], phone_numbers=[], product_names=[], product_ids=[], amounts=[],
            ))
            mock_tracker.return_value = mock_tracker_inst
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

    # ── Case 9：语义缓存验证 ──

    @pytest.mark.asyncio
    async def test_case09_semantic_cache_validation(self, agent_context):
        """
        Case 9：语义缓存验证
        ==================
        场景：首次提问 → 相同问题再问 → 语义相似问题
        测试缓存命中和语义相似度匹配
        验证：第二次回复来自缓存（skill_used == 'cache'）
        """
        report = ScenarioReport(name="Case9-语义缓存验证")
        logger.info(f"\n{'='*60}\n开始 {report.name}\n{'='*60}")

        cache_store: Dict[str, str] = {}
        lookup_count = 0

        async def mock_cache_lookup(tenant_id, query, **kwargs):
            nonlocal lookup_count
            lookup_count += 1
            logger.info(f"  [Cache] lookup #{lookup_count}: '{query}'")
            # 精确匹配
            if query in cache_store:
                logger.info(f"  [Cache] HIT (exact)")
                result = MagicMock()
                result.answer = cache_store[query]
                result.confidence = 0.98
                return result
            # 模糊匹配（简单包含关系模拟语义相似）
            for key, value in cache_store.items():
                if len(set(key) & set(query)) / max(len(set(key)), 1) > 0.6:
                    logger.info(f"  [Cache] HIT (similar) key='{key}'")
                    result = MagicMock()
                    result.answer = value
                    result.confidence = 0.85
                    return result
            logger.info(f"  [Cache] MISS")
            return None

        async def mock_cache_store(tenant_id, query, answer, **kwargs):
            cache_store[query] = answer
            logger.info(f"  [Cache] stored: '{query}' → '{answer[:50]}...'")

        async def mock_llm_ainvoke(messages, **kwargs):
            last_tool = next(
                (m for m in reversed(messages) if isinstance(m, ToolMessage)), None
            )
            if last_tool:
                return _make_llm_response("根据查询结果，雪尼尔面料不容易起球，非常耐用。")
            return _make_llm_response(
                "",
                tool_calls=[{"name": "knowledge_search", "args": {"query": "雪尼尔面料起球"}, "id": "tc_c1"}],
            )

        from app.cache.semantic_cache import semantic_cache as _sc_instance

        with patch("app.graph.skills.base_skill.get_skill_llm") as mock_llm_factory, \
             patch("app.utils.http_client.AdminApiClient._get_client") as mock_client, \
             patch("app.graph.skills.base_skill.get_tracker") as mock_tracker, \
             patch("app.config.settings") as mock_settings, \
             patch("app.router.intent_classifier.IntentClassifier.classify") as mock_classify, \
             patch.object(_sc_instance, "lookup", new_callable=AsyncMock, side_effect=mock_cache_lookup), \
             patch.object(_sc_instance, "store", new_callable=AsyncMock, side_effect=mock_cache_store), \
             patch("app.tools.knowledge_search._RAG_AVAILABLE", False):

            mock_settings.SEMANTIC_CACHE_ENABLED = True
            mock_settings.DASHSCOPE_API_KEY = ""
            mock_settings.DASHSCOPE_MODEL = "qwen-test"

            mock_llm = MagicMock()
            mock_llm.bind_tools.return_value = mock_llm
            mock_llm.ainvoke = AsyncMock(side_effect=mock_llm_ainvoke)
            mock_llm_factory.return_value = mock_llm

            mock_http = AsyncMock()
            mock_client.return_value = mock_http

            mock_tracker_inst = MagicMock()
            mock_tracker_inst.extract_entities_from_tool_result = MagicMock()
            mock_tracker_inst.get_entities = MagicMock(return_value=MagicMock(
                order_nos=[], phone_numbers=[], product_names=[], product_ids=[], amounts=[],
            ))
            mock_tracker.return_value = mock_tracker_inst
            mock_classify.return_value = IntentResult(
                intent=IntentType.KNOWLEDGE_FAQ, confidence=0.85, source="classifier",
            )

            agent = CustomerServiceAgent()
            runner = MultiTurnRunner(agent, agent_context, report)

            # Turn 1: 首次提问（缓存 MISS → 走 LLM → 写入缓存）
            resp1 = await runner.send("雪尼尔面料会不会起球")
            assert resp1.content, "Turn 1: 回复不应为空"
            logger.info(f"  缓存状态: {len(cache_store)} 条记录")

            # Turn 2: 完全相同的问题（应该缓存命中）
            resp2 = await runner.send("雪尼尔面料会不会起球")
            assert resp2.content, "Turn 2: 回复不应为空"
            # 增强断言：验证缓存命中（skill_used 应为 cache）
            skill2 = resp2.metadata.get("skill_used", "") if resp2.metadata else ""
            if skill2 and skill2 != "cache":
                report.record_issue(2, "缓存未命中", f"相同问题第二次查询期望走缓存，实际 skill_used={skill2}")

            # Turn 3: 语义相似问题
            resp3 = await runner.send("雪尼尔面料容易起球吗")
            assert resp3.content, "Turn 3: 回复不应为空"

        report.summary()
        assert_no_issues(report)

    # ── Case 10：复杂混合场景压力测试 ──

    @pytest.mark.asyncio
    async def test_case10_complex_stress_test(self, agent_context):
        """
        Case 10：复杂混合场景压力测试
        ============================
        场景：连续 10 轮+不同意图+上下文引用+错误恢复
        验证：长对话稳定性，上下文不退化
        """
        report = ScenarioReport(name="Case10-复杂混合压力测试")
        logger.info(f"\n{'='*60}\n开始 {report.name}\n{'='*60}")

        async def mock_llm_ainvoke(messages, **kwargs):
            last_human = next(
                (m for m in reversed(messages) if isinstance(m, HumanMessage)), None
            )
            user_text = last_human.content if last_human else ""
            last_tool = next(
                (m for m in reversed(messages) if isinstance(m, ToolMessage)), None
            )

            if last_tool:
                return _make_llm_response("已为您查询到相关信息。")

            if "窗帘" in user_text and ("搜索" in user_text or "看看" in user_text):
                return _make_llm_response(
                    "",
                    tool_calls=[{"name": "product_search", "args": {"keyword": "窗帘"}, "id": "tc_s1"}],
                )
            if "订单" in user_text:
                return _make_llm_response(
                    "",
                    tool_calls=[{"name": "order_query", "args": {"order_id": "ORD20250501001"}, "id": "tc_s2"}],
                )
            if "物流" in user_text:
                return _make_llm_response(
                    "",
                    tool_calls=[{"name": "logistics_track", "args": {"order_id": "ORD20250501001"}, "id": "tc_s3"}],
                )
            if "清洗" in user_text or "保养" in user_text:
                return _make_llm_response(
                    "",
                    tool_calls=[{"name": "knowledge_search", "args": {"query": "窗帘清洗"}, "id": "tc_s4"}],
                )
            if "退货" in user_text or "投诉" in user_text:
                return _make_llm_response(
                    "我理解您的情况，这需要人工客服为您处理。我帮您转接，请稍等~ 🙏"
                )
            if "刚才" in user_text or "之前" in user_text or "前面" in user_text:
                # 测试上下文引用
                return _make_llm_response(
                    "好的，根据我们之前的对话，您查询的是订单 ORD20250501001，"
                    "目前状态为已发货，物流正在运输中~"
                )
            if "详情" in user_text or "详细" in user_text:
                return _make_llm_response(
                    "",
                    tool_calls=[{"name": "product_detail", "args": {"product_id": "prod_001"}, "id": "tc_s5"}],
                )

            return _make_llm_response("好的，还有什么需要帮忙的吗？")

        async def mock_admin_get(*args, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            path = str(args[0]) if args else ""
            if "orders" in path:
                resp.json.return_value = {"success": True, "data": {**MOCK_ORDER}}
            elif "products/" in path and not path.endswith("/products"):
                resp.json.return_value = {"success": True, "data": {**MOCK_PRODUCT_DETAIL}}
            else:
                resp.json.return_value = {
                    "success": True, "data": {"records": MOCK_PRODUCTS, "total": 3},
                }
            return resp

        with patch("app.graph.skills.base_skill.get_skill_llm") as mock_llm_factory, \
             patch("app.utils.http_client.AdminApiClient._get_client") as mock_client, \
             patch("app.graph.skills.base_skill.get_tracker") as mock_tracker, \
             patch("app.config.settings") as mock_settings, \
             patch("app.router.intent_classifier.IntentClassifier.classify") as mock_classify, \
             patch("app.tools.knowledge_search._RAG_AVAILABLE", False), \
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

            mock_tracker_inst = MagicMock()
            mock_tracker_inst.extract_entities_from_tool_result = MagicMock()
            mock_tracker_inst.get_entities = MagicMock(return_value=MagicMock(
                order_nos=[], phone_numbers=[], product_names=[], product_ids=[], amounts=[],
            ))
            mock_tracker.return_value = mock_tracker_inst
            mock_classify.return_value = IntentResult(
                intent=IntentType.GENERAL, confidence=0.5, source="classifier",
            )

            agent = CustomerServiceAgent()
            runner = MultiTurnRunner(agent, agent_context, report)

            # 10+ 轮对话
            messages = [
                ("你好", "greeting"),
                ("帮我看看你们的窗帘", "product_inquiry"),
                ("第一款详情介绍一下", "product_inquiry"),
                ("我有个订单想查一下 ORD20250501001", "order_query"),
                ("这个订单的物流到哪了", "logistics_track"),
                ("窗帘收到后怎么清洗保养", "knowledge_faq"),
                ("帮我回顾一下刚才查的订单状态", "context_reference"),
                ("这个窗帘质量不好我想退货", "after_sales"),
                ("你们有没有电动窗帘", "product_inquiry"),
                ("好的谢谢，再见", "farewell"),
            ]

            for i, (msg, expected_intent) in enumerate(messages, 1):
                # 动态设置 mock_classify 的返回值
                intent_map = {
                    "greeting": IntentType.GREETING,
                    "product_inquiry": IntentType.PRODUCT_INQUIRY,
                    "order_query": IntentType.ORDER_QUERY,
                    "logistics_track": IntentType.LOGISTICS_TRACK,
                    "knowledge_faq": IntentType.KNOWLEDGE_FAQ,
                    "after_sales": IntentType.AFTER_SALES,
                    "farewell": IntentType.FAREWELL,
                    "context_reference": IntentType.GENERAL,
                }
                intent_type = intent_map.get(expected_intent, IntentType.GENERAL)
                mock_classify.return_value = IntentResult(
                    intent=intent_type, confidence=0.85, source="classifier",
                )

                resp = await runner.send(msg)
                assert resp.content, f"Turn {i} ({expected_intent}): 回复不应为空"

                if resp.type == "error":
                    report.record_issue(i, "运行时错误", f"Turn {i} 返回了错误: {resp.content[:100]}")

            # 验证长对话稳定性
            assert runner.turn >= 10, f"应完成至少10轮对话，实际 {runner.turn} 轮"
            assert len(runner.chat_history) == runner.turn * 2, \
                f"chat_history 应有 {runner.turn * 2} 条，实际 {len(runner.chat_history)}"

        report.summary()
        assert_no_issues(report)


# ============ 全局测试报告 ============

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
