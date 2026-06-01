"""
意图路由主逻辑 - 三级路由决策引擎
"""

from typing import Optional

from loguru import logger

from app.router.intent_config import (
    IntentType,
    IntentResult,
    RouteDecision,
    INTENT_TOOL_MAP,
)
from app.router.rule_matcher import RuleMatcher
from app.router.intent_classifier import IntentClassifier


class IntentRouter:
    """
    意图路由引擎
    
    三级路由决策流程：
    1. L1 规则匹配（关键词 + 正则）→ 高置信度快速命中
    2. L2 小模型分类（qwen-turbo）→ 语义理解
    3. 路由决策 → 确定 action 和附加信息
    """

    def __init__(self):
        self.rule_matcher = RuleMatcher()
        self.intent_classifier = IntentClassifier()

    async def route(
        self,
        message: str,
        chat_history: list = None,
        agent_intents: list[str] | None = None,
    ) -> RouteDecision:
        """
        对用户消息进行意图路由

        Args:
            message: 用户消息文本
            chat_history: 对话历史
            agent_intents: 该 Agent 可处理的意图列表（可选）。
                           传入后分类器只考虑这些意图，提升准确率。

        Returns:
            RouteDecision: 路由决策结果
        """
        # L1: 规则匹配
        intent_result = self.rule_matcher.match(message)
        if intent_result:
            logger.info(
                f"[IntentRouter] L1 rule matched: intent={intent_result.intent.value}, "
                f"confidence={intent_result.confidence}, keywords={intent_result.matched_keywords}"
            )
            return self._make_decision(intent_result)

        # L2: 小模型分类（Agent 感知）
        intent_result = await self.intent_classifier.classify(
            message, chat_history, agent_intents=agent_intents
        )
        logger.info(
            f"[IntentRouter] L2 classifier result: intent={intent_result.intent.value}, "
            f"confidence={intent_result.confidence}"
        )
        return self._make_decision(intent_result)

    def _make_decision(self, intent_result: IntentResult) -> RouteDecision:
        """
        根据意图结果生成路由决策

        路由规则：
        - greeting/farewell/capabilities → direct_reply（回复文本由 direct_reply_node 从 AgentConfig 获取）
        - 高置信度(>=0.7) → route_with_hint（附带 tool 提示）
        - 低置信度(<0.7) → full_agent（全量走大模型）
        """
        intent = intent_result.intent
        confidence = intent_result.confidence

        # 直接回复意图 → action="direct_reply"
        # 回复文本由 direct_reply_node 从 AgentConfig.direct_replies 获取
        # 这里不再硬编码回复内容，实现 Agent 级别的个性化
        if intent in (IntentType.GREETING, IntentType.FAREWELL, IntentType.CAPABILITIES):
            if confidence >= 0.9:
                return RouteDecision(
                    intent_result=intent_result,
                    action="direct_reply",
                    direct_reply=None,  # 由 direct_reply_node 填充
                )

        # 高置信度 → 带 tool 提示路由
        if confidence >= 0.7:
            tools = INTENT_TOOL_MAP.get(intent, [])
            tool_hint = ", ".join(tools) if tools else None
            return RouteDecision(
                intent_result=intent_result,
                action="route_with_hint",
                tool_hint=tool_hint,
            )

        # 低置信度 → 全量 Agent
        return RouteDecision(
            intent_result=intent_result,
            action="full_agent",
        )
