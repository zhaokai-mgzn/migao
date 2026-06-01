"""
意图配置 - 定义意图类型、结果数据类、路由决策
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class IntentType(str, Enum):
    """意图类型枚举

    按领域分组，与 INTENT_DOMAINS 配合使用。
    新增意图时请归入对应的领域分组。
    """
    # ── 公共（所有 Agent 共享）──
    GREETING = "greeting"
    FAREWELL = "farewell"
    CAPABILITIES = "capabilities"
    GENERAL = "general"
    # ── 订单域 (order) ──
    ORDER_QUERY = "order_query"
    LOGISTICS_TRACK = "logistics_track"
    AFTER_SALES = "after_sales"
    AFTER_SALES_CREATE = "after_sales_create"
    COMPLAINT = "complaint"
    # ── 商品域 (product) ──
    PRODUCT_INQUIRY = "product_inquiry"
    CATEGORY_MANAGE = "category_manage"
    PROCESSING_MANAGE = "processing_manage"
    # ── 客户关系域 (crm) ──
    CUSTOMER_MANAGE = "customer_manage"
    CUSTOMER_QUERY = "customer_query"
    # ── 人事域 (hr) ──
    EMPLOYEE_MANAGE = "employee_manage"
    STAFF_MANAGE = "staff_manage"
    ROLE_MANAGE = "role_manage"
    PERMISSION_MANAGE = "permission_manage"
    # ── 系统配置域 (settings) ──
    SYSTEM_SETTINGS = "system_settings"
    AI_CONFIG = "ai_config"
    NOTIFICATION = "notification"
    QUICK_REPLY = "quick_reply"
    # ── 数据分析域 (analytics) ──
    DASHBOARD = "dashboard"
    STATISTICS = "statistics"
    DATA_REPORT = "data_report"
    SESSION_MANAGE = "session_manage"
    # ── 知识库域 (knowledge) ──
    KNOWLEDGE_FAQ = "knowledge_faq"
    KNOWLEDGE_MANAGE = "knowledge_manage"
    # ── 未来扩展域（示例）──
    # SUPPLIER_QUERY = "supplier_query"       # 供应链域
    # PURCHASE_ORDER = "purchase_order"        # 供应链域
    # PRODUCTION_SCHEDULE = "production_schedule"  # 生产域


# 意图→领域分组映射
# 用于意图命名空间化：Agent 只关注自己领域的意图子集
INTENT_DOMAINS: dict[str, set[str]] = {
    "common": {"greeting", "farewell", "capabilities", "general"},
    "order": {"order_query", "logistics_track", "after_sales", "after_sales_create", "complaint"},
    "product": {"product_inquiry", "category_manage", "processing_manage"},
    "crm": {"customer_manage", "customer_query"},
    "hr": {"employee_manage", "staff_manage", "role_manage", "permission_manage"},
    "settings": {"system_settings", "ai_config", "notification", "quick_reply"},
    "analytics": {"dashboard", "statistics", "data_report", "session_manage"},
    "knowledge": {"knowledge_faq", "knowledge_manage"},
    # 未来扩展：
    # "supply_chain": {"supplier_query", "purchase_order", ...},
    # "production": {"production_schedule", "material_requisition", ...},
}


def get_intents_by_domains(domains: set[str]) -> set[str]:
    """获取指定领域集合的所有意图

    Args:
        domains: 领域名称集合，如 {"order", "product", "common"}

    Returns:
        set[str]: 意图值集合
    """
    intents: set[str] = set()
    for domain in domains:
        domain_intents = INTENT_DOMAINS.get(domain)
        if domain_intents:
            intents.update(domain_intents)
    return intents


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
