"""
L1 规则匹配层 - 基于关键词和正则表达式的快速意图匹配
"""

import re
from typing import Optional

from app.router.intent_config import IntentType, IntentResult


# 关键词 → 意图映射表
KEYWORD_MAP: dict[IntentType, list[str]] = {
    IntentType.ORDER_QUERY: ["订单", "我的订单", "订单状态", "查订单"],
    IntentType.LOGISTICS_TRACK: ["物流", "快递", "到哪了", "发货"],
    IntentType.PRODUCT_INQUIRY: ["商品", "产品", "价格", "多少钱", "有没有", "加工项", "加工项目", "加工费"],
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
    # 订单号格式
    (re.compile(r"[A-Za-z]{0,3}\d{10,20}"), IntentType.ORDER_QUERY),
]

# Greeting 直接回复内容
GREETING_REPLIES = [
    "您好！我是米宝，您的智能工作助手。我可以帮您处理商品管理、订单处理、库存查询等工作事务，有什么需要帮忙的吗？",
]

# Farewell 告别回复
FAREWELL_REPLIES = [
    "好的，有需要随时找我~ 祝工作顺利！😊",
]

# Capabilities 功能介绍回复
CAPABILITIES_REPLIES = [
    """您好！我是米宝，您的智能工作助手。我可以帮您：
🔍 **商品管理** - 搜索商品、查看详情、管理库存
📦 **订单处理** - 查询订单状态、物流跟踪、订单管理
📚 **知识查询** - 面料知识、工艺流程、产品规格
🔧 **售后处理** - 退换货处理、客户投诉、安装指导
有什么需要帮忙的吗？""",
]


class RuleMatcher:
    """
    L1 规则匹配器
    
    通过关键词和正则表达式进行快速意图匹配，
    命中后返回高置信度结果，无需调用小模型。
    """

    def match(self, message: str) -> Optional[IntentResult]:
        """
        对用户消息进行规则匹配
        
        Args:
            message: 用户消息文本
            
        Returns:
            IntentResult 或 None（未命中）
        """
        if not message or not message.strip():
            return None

        msg_lower = message.strip().lower()

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
            if pattern.search(message):
                return IntentResult(
                    intent=intent,
                    confidence=0.9,
                    source="rule",
                    matched_keywords=[f"regex:{pattern.pattern}"],
                )

        return None
