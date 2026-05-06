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
from app.router.rule_matcher import RuleMatcher, GREETING_REPLIES, FAREWELL_REPLIES, CAPABILITIES_REPLIES
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
        self, message: str, chat_history: list = None
    ) -> RouteDecision:
        """
        对用户消息进行意图路由
        
        Args:
            message: 用户消息文本
            chat_history: 对话历史
            
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

        # L2: 小模型分类
        intent_result = await self.intent_classifier.classify(message, chat_history)
        logger.info(
            f"[IntentRouter] L2 classifier result: intent={intent_result.intent.value}, "
            f"confidence={intent_result.confidence}"
        )
        return self._make_decision(intent_result)

    def _make_decision(self, intent_result: IntentResult) -> RouteDecision:
        """
        根据意图结果生成路由决策
        
        路由规则：
        - greeting → direct_reply（直接回复问候）
        - 高置信度(>0.7) → route_with_hint（附带 tool 提示）
        - 低置信度(<0.7) → full_agent（全量走大模型）
        """
        intent = intent_result.intent
        confidence = intent_result.confidence

        # Greeting 意图 → 直接回复
        if intent == IntentType.GREETING and confidence >= 0.9:
            return RouteDecision(
                intent_result=intent_result,
                action="direct_reply",
                direct_reply=GREETING_REPLIES[0],
            )

        # Farewell 意图 → 告别回复
        if intent == IntentType.FAREWELL and confidence >= 0.9:
            return RouteDecision(
                intent_result=intent_result,
                action="direct_reply",
                direct_reply=FAREWELL_REPLIES[0],
            )

        # Capabilities 意图 → 功能介绍回复
        if intent == IntentType.CAPABILITIES and confidence >= 0.9:
            return RouteDecision(
                intent_result=intent_result,
                action="direct_reply",
                direct_reply=CAPABILITIES_REPLIES[0],
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
