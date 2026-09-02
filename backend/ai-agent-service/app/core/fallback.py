"""
AI 智能客服系统 - Tool 降级回复模板

当熔断器处于 OPEN 状态、或下游连续失败时，
直接返回预定义的友好回复，避免把错误抛回给用户。
"""
from typing import Optional

from app.tools.base import ToolResult


# 各 Tool 的降级回复文案（key 必须与 Tool 名一致）
FALLBACK_MESSAGES = {
    # ---------- 商品域 ----------
    "product_search": "抱歉，商品搜索服务暂时繁忙，请稍后再试或直接告诉我您想了解的商品名称，我会人工为您介绍。",
    "product_detail": "抱歉，商品详情服务暂时不可用，请稍后再试，或留下您想了解的商品名称，我们的客服会尽快与您联系。",
    "query_product_skus": "抱歉，商品规格查询暂时不可用，请稍后再试。",
    "query_inventory": "抱歉，库存查询服务暂时不可用，请稍后再试。",
    # ---------- 订单域 ----------
    "order_query": "订单查询服务暂时不可用,请稍后重试或联系人工客服为您查询订单状态。",
    "order_manage": "订单操作暂时无法完成,请稍后再试或联系人工客服。",
    "manage_order_follow_status": "订单跟进状态服务暂时不可用,请稍后再试。",
    # ---------- 物流 / 售后 ----------
    "logistics_track": "物流查询暂时无法使用,请稍后再试,或在订单详情中查看物流单号自行追踪。",
    "after_sales_manage": "售后服务暂时不可用,请稍后再试或联系人工客服处理您的售后请求。",
    "customer_manage": "客户管理服务暂时不可用,请稍后再试。",
    # ---------- 后台管理域 ----------
    "category_manage": "商品分类服务暂时不可用,请稍后再试。",
    "product_manage": "商品管理服务暂时不可用,请稍后再试。",
    "inventory_manage": "库存管理服务暂时不可用,请稍后再试。",
    "dashboard_stats": "数据统计暂时不可用,请稍后再试。",
    "processing_item_query": "加工项查询暂时不可用,请稍后再试。",
    "processing_item_manage": "加工项管理暂时不可用,请稍后再试。",
    "query_processing_items": "加工项查询暂时不可用,请稍后再试。",
    # ---------- 员工 / 角色 / 设置 / 会话 / 通知 / 快捷回复 ----------
    "employee_manage": "员工管理服务暂时不可用,请稍后再试。",
    "role_manage": "角色管理服务暂时不可用,请稍后再试。",
    "settings_manage": "系统设置服务暂时不可用,请稍后再试。",
    "session_manage": "会话管理服务暂时不可用,请稍后再试。",
    "notification_manage": "通知管理服务暂时不可用,请稍后再试。",
    "quick_reply_manage": "快捷回复服务暂时不可用,请稍后再试。",
}

# 未在表中找到对应 Tool 时使用的兜底文案
DEFAULT_FALLBACK_MESSAGE = "该服务暂时不可用，请稍后再试，或联系人工客服为您处理。"

# LLM 调用失败 / 熔断时使用的友好回复
LLM_FALLBACK_MESSAGE = "AI 助手暂时离线维护中，您可以联系人工客服获取帮助。"


def get_fallback_result(tool_name: str, reason: Optional[str] = None) -> ToolResult:
    """获取指定 Tool 的降级 ToolResult。

    Args:
        tool_name: Tool 名称
        reason: 降级原因，用于追溯（如 "circuit_breaker_open"、"timeout" 等）

    Returns:
        ToolResult: success=False，包含友好提示文案
    """
    message = FALLBACK_MESSAGES.get(tool_name, DEFAULT_FALLBACK_MESSAGE)
    return ToolResult(
        success=False,
        error=reason if reason else "service_unavailable",
        message=message,
        data={
            "fallback": True,
            "reason": reason if reason else "service_unavailable",
        },
    )


def get_fallback_message(tool_name: str) -> str:
    """获取指定 Tool 的降级文本（不构造 ToolResult）"""
    return FALLBACK_MESSAGES.get(tool_name, DEFAULT_FALLBACK_MESSAGE)
