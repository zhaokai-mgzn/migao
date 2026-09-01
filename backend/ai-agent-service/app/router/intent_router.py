"""
意图路由主逻辑 - 三级路由决策引擎
"""

from typing import Optional, Union

from loguru import logger

from app.router.intent_config import (
    IntentType,
    IntentResult,
    RouteDecision,
    INTENT_TOOL_MAP,
)
from app.router.rule_matcher import RuleMatcher
from app.router.intent_classifier import IntentClassifier

# 低置信度阈值：低于此值时，具体业务意图会被重写为 general 兜底澄清（不硬猜 skill）
LOW_CONFIDENCE_THRESHOLD = 0.55

# 这些意图不参与低置信度重写：general 本身已是兜底，greeting/farewell/capabilities 有独立逻辑
_CLARIFY_EXEMPT_INTENTS = (
    IntentType.GREETING,
    IntentType.FAREWELL,
    IntentType.CAPABILITIES,
    IntentType.GENERAL,
)


class IntentRouter:
    """
    意图路由引擎
    
    三级路由决策流程：
    1. L1 规则匹配（关键词 + 正则）→ 高置信度快速命中
    2. L2 轻量模型分类 → 语义理解
    3. 路由决策 → 确定 action 和附加信息
    """

    def __init__(self):
        self.rule_matcher = RuleMatcher()
        self.intent_classifier = IntentClassifier()

    async def route(
        self,
        message: Union[str, list],
        chat_history: list = None,
        agent_intents: list[str] | None = None,
        entity_hint: str = "",
    ) -> RouteDecision:
        """
        对用户消息进行意图路由

        Args:
            message: 用户消息文本（str 或多模态 list）
            chat_history: 对话历史
            agent_intents: 该 Agent 可处理的意图列表（可选）。
                           传入后分类器只考虑这些意图，提升准确率。
            entity_hint: 跨轮实体提示（如"[上下文实体] 之前对话已涉及：订单「ORD123」"）。
                         仅注入 L2 分类器做指代消解；L1 规则匹配只看原始用户消息，
                         防止 hint 中的领域词（如"加工项"）污染关键词匹配误路由。

        Returns:
            RouteDecision: 路由决策结果
        """
        # L1: 规则匹配（只看原始用户消息，实体提示不得参与关键词匹配）
        intent_result = self.rule_matcher.match(message)
        if intent_result:
            logger.info(
                f"[IntentRouter] L1 rule matched: intent={intent_result.intent.value}, "
                f"confidence={intent_result.confidence}, keywords={intent_result.matched_keywords}"
            )
            return self._make_decision(intent_result)

        # L2: 小模型分类（Agent 感知，注入实体提示做指代消解）
        classify_message = message
        if entity_hint:
            classify_message = f"{entity_hint}\n用户消息：{message}"
        intent_result = await self.intent_classifier.classify(
            classify_message, chat_history, agent_intents=agent_intents
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

        # 极低置信度（LLM 自己都不确定）且是具体业务意图 → 重写为 general 兜底澄清。
        # 猜错一个 skill 比让用户澄清更伤信任；general skill 拥有全工具集 + 澄清引导 prompt。
        if (
            confidence < LOW_CONFIDENCE_THRESHOLD
            and intent not in _CLARIFY_EXEMPT_INTENTS
        ):
            logger.info(
                f"[IntentRouter] Low confidence ({confidence:.2f}) on '{intent.value}', "
                f"rewriting to general for clarification"
            )
            return RouteDecision(
                intent_result=IntentResult(
                    intent=IntentType.GENERAL,
                    confidence=confidence,
                    source="low_confidence",
                ),
                action="full_agent",
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
