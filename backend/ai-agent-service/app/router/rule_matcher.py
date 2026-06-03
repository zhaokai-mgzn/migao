"""
L1 规则匹配层 - 基于关键词和正则表达式的快速意图匹配
"""

import re
from typing import Optional, Union

from app.router.intent_config import IntentType, IntentResult


def _extract_text(content: Union[str, list, None]) -> str:
    """从消息内容中提取纯文本

    支持 str 和多模态 list 格式：
    [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                if text:
                    parts.append(text)
        return " ".join(parts)
    return str(content)


# 关键词 → 意图映射表
KEYWORD_MAP: dict[IntentType, list[str]] = {
    IntentType.ORDER_QUERY: ["订单", "我的订单", "订单状态", "查订单", "待发货"],
    IntentType.ORDER_CREATE: ["创建订单", "新建订单", "下单", "开个单", "录单"],
    IntentType.LOGISTICS_TRACK: ["物流", "快递", "到哪了"],
    IntentType.PRODUCT_INQUIRY: ["商品", "产品", "价格", "多少钱", "加工项", "加工项目", "加工费"],
    IntentType.AFTER_SALES: ["退货", "退款", "换货", "售后", "维修"],
    IntentType.KNOWLEDGE_FAQ: ["怎么清洗", "怎么安装", "怎么保养", "怎么测量", "怎么选", "如何", "什么是", "为什么", "教程"],
    IntentType.FAREWELL: ["再见", "拜拜", "bye", "goodbye", "下次见", "回见"],
    IntentType.CAPABILITIES: [
        "你能做什么", "你会什么", "你有什么功能", "能帮我做什么",
        "有什么功能", "你能干什么", "你可以做什么", "你能帮我什么",
        "能做什么", "什么功能",
    ],
    IntentType.GREETING: ["你好", "在吗", "嗨", "hello", "hi"],
    IntentType.COMPLAINT: ["投诉", "举报", "不满", "差评"],
}

# 正则规则
REGEX_RULES: list[tuple[re.Pattern, IntentType]] = [
    # 订单号格式（要求 ORD 前缀，避免误匹配手机号）
    (re.compile(r"ORD[-\s]?\d{10,20}"), IntentType.ORDER_QUERY),
]

# 直接回复内容已迁移到 AgentConfig.direct_replies
# 参见 agents/mibao.py 和 agents/xiaobu.py 中的配置
# GREETING_REPLIES / FAREWELL_REPLIES / CAPABILITIES_REPLIES 已删除，
# 现在由 AgentConfig.get_direct_reply(intent) 统一提供


class RuleMatcher:
    """
    L1 规则匹配器
    
    通过关键词和正则表达式进行快速意图匹配，
    命中后返回高置信度结果，无需调用小模型。
    """

    def match(self, message: Union[str, list, None]) -> Optional[IntentResult]:
        """
        对用户消息进行规则匹配

        Args:
            message: 用户消息文本（str 或多模态 list）

        Returns:
            IntentResult 或 None（未命中）
        """
        text = _extract_text(message)
        if not text or not text.strip():
            return None

        msg_lower = text.strip().lower()

        # 1. 关键词匹配
        # --- 优先匹配 capabilities（长短语，避免被其他意图抢占） ---
        cap_keywords = KEYWORD_MAP.get(IntentType.CAPABILITIES, [])
        cap_matched = [kw for kw in cap_keywords if kw.lower() in msg_lower]
        if cap_matched:
            return IntentResult(
                intent=IntentType.CAPABILITIES,
                confidence=1.0,
                source="rule",
                matched_keywords=cap_matched,
            )

        # --- 优先匹配 farewell（"谢谢，再见" 等组合也应被识别） ---
        farewell_keywords = KEYWORD_MAP.get(IntentType.FAREWELL, [])
        farewell_matched = [kw for kw in farewell_keywords if kw.lower() in msg_lower]
        if farewell_matched:
            return IntentResult(
                intent=IntentType.FAREWELL,
                confidence=1.0,
                source="rule",
                matched_keywords=farewell_matched,
            )

        for intent, keywords in KEYWORD_MAP.items():
            # capabilities 和 farewell 已在上面处理
            if intent in (IntentType.CAPABILITIES, IntentType.FAREWELL):
                continue

            matched = [kw for kw in keywords if kw.lower() in msg_lower]
            if matched:
                # Greeting 意图：消息非常短且完全匹配时才高置信度
                if intent == IntentType.GREETING:
                    # 仅当消息较短时（≤10字符）才视为纯问候
                    if len(msg_lower) <= 10:
                        return IntentResult(
                            intent=intent,
                            confidence=1.0,
                            source="rule",
                            matched_keywords=matched,
                        )
                    # 较长消息中包含问候词，不单独识别为 greeting
                    continue
                
                return IntentResult(
                    intent=intent,
                    confidence=0.95,
                    source="rule",
                    matched_keywords=matched,
                )

        # 2. 正则规则匹配
        for pattern, intent in REGEX_RULES:
            if pattern.search(text):
                return IntentResult(
                    intent=intent,
                    confidence=0.9,
                    source="rule",
                    matched_keywords=[f"regex:{pattern.pattern}"],
                )

        return None
