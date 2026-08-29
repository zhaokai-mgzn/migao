"""
共享基础设施（拆分自 test_xiaobu_multi_turn_scenarios.py，2026-08-29）
"""
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
        # [RAG 禁用] semantic_cache 已移除
        "cache_settings": patch("app.graph.nodes.settings", create=True),
        "suggestions": patch(
            "app.graph.nodes.FollowUpSuggestionGenerator", create=True,
        ),
        "skill_llm": patch("app.graph.skills.base_skill.get_skill_llm"),
        "admin_api": patch("app.utils.http_client.AdminApiClient._get_client"),
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

