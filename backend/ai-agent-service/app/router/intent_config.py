"""
意图配置 - 定义意图类型、结果数据类、路由决策
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class IntentType(str, Enum):
    """意图类型枚举"""
    # 备货 / C 端客服场景
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
    # 商家后台（米宝）管理类场景
    CUSTOMER_MANAGE = "customer_manage"
    CUSTOMER_QUERY = "customer_query"
    EMPLOYEE_MANAGE = "employee_manage"
    STAFF_MANAGE = "staff_manage"
    ROLE_MANAGE = "role_manage"
    PERMISSION_MANAGE = "permission_manage"
    SYSTEM_SETTINGS = "system_settings"
    AI_CONFIG = "ai_config"
    NOTIFICATION = "notification"
    QUICK_REPLY = "quick_reply"
    DASHBOARD = "dashboard"
    STATISTICS = "statistics"
    DATA_REPORT = "data_report"
    SESSION_MANAGE = "session_manage"
    AFTER_SALES_CREATE = "after_sales_create"
    KNOWLEDGE_MANAGE = "knowledge_manage"
    CATEGORY_MANAGE = "category_manage"
    PROCESSING_MANAGE = "processing_manage"


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
    IntentType.ORDER_QUERY: ["order_query"],
    IntentType.LOGISTICS_TRACK: ["logistics_track"],
    IntentType.PRODUCT_INQUIRY: ["product_search", "product_detail"],
    IntentType.AFTER_SALES: ["order_query", "after_sales_manage"],
    IntentType.KNOWLEDGE_FAQ: ["knowledge_search"],
    IntentType.GREETING: [],
    IntentType.FAREWELL: [],
    IntentType.CAPABILITIES: [],
    IntentType.COMPLAINT: ["human_handoff"],
    IntentType.GENERAL: [],
    # 商家后台管理类意图
    IntentType.CUSTOMER_MANAGE: ["customer_manage"],
    IntentType.CUSTOMER_QUERY: ["customer_manage"],
    IntentType.EMPLOYEE_MANAGE: ["employee_manage"],
    IntentType.STAFF_MANAGE: ["employee_manage", "role_manage"],
    IntentType.ROLE_MANAGE: ["role_manage"],
    IntentType.PERMISSION_MANAGE: ["role_manage"],
    IntentType.SYSTEM_SETTINGS: ["settings_manage"],
    IntentType.AI_CONFIG: ["settings_manage"],
    IntentType.NOTIFICATION: ["notification_manage"],
    IntentType.QUICK_REPLY: ["quick_reply_manage"],
    IntentType.DASHBOARD: ["dashboard_stats"],
    IntentType.STATISTICS: ["dashboard_stats"],
    IntentType.DATA_REPORT: ["dashboard_stats"],
    IntentType.SESSION_MANAGE: ["session_manage"],
    IntentType.AFTER_SALES_CREATE: ["after_sales_manage"],
    IntentType.KNOWLEDGE_MANAGE: ["knowledge_manage"],
    IntentType.CATEGORY_MANAGE: ["category_manage"],
    IntentType.PROCESSING_MANAGE: ["processing_item_manage"],
}
