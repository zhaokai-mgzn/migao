"""
意图配置 - 定义意图类型、结果数据类、路由决策
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class IntentType(str, Enum):
    """意图类型枚举（8类）"""
    ORDER_QUERY = "order_query"
    LOGISTICS_TRACK = "logistics_track"
    PRODUCT_INQUIRY = "product_inquiry"
    AFTER_SALES = "after_sales"
    KNOWLEDGE_FAQ = "knowledge_faq"
    GREETING = "greeting"
    FAREWELL = "farewell"
    CAPABILITIES = "capabilities"
    COMPLAINT = "complaint"
    GENERAL = "general"


@dataclass
class IntentResult:
    """意图识别结果"""
    intent: IntentType
    confidence: float
    source: str  # "rule" / "classifier" / "default"
    matched_keywords: list = field(default_factory=list)


@dataclass
class RouteDecision:
    """路由决策结果"""
    intent_result: IntentResult
    action: str  # "direct_reply" / "route_with_hint" / "full_agent" / "human_handoff"
    direct_reply: Optional[str] = None
    tool_hint: Optional[str] = None


# 意图 → 推荐 Tool 映射
INTENT_TOOL_MAP: dict[IntentType, list[str]] = {
    IntentType.ORDER_QUERY: ["order_query", "order_manage"],
    IntentType.LOGISTICS_TRACK: ["logistics_track"],
    IntentType.PRODUCT_INQUIRY: ["product_search", "product_detail"],
    IntentType.AFTER_SALES: ["order_query", "human_handoff"],
    IntentType.KNOWLEDGE_FAQ: ["knowledge_search"],
    IntentType.GREETING: [],
    IntentType.FAREWELL: [],
    IntentType.CAPABILITIES: [],
    IntentType.COMPLAINT: ["human_handoff"],
    IntentType.GENERAL: [],
}
