"""
测试 app.core.fallback — Tool 降级回复模板
"""
import pytest

from app.core.fallback import (
    FALLBACK_MESSAGES,
    DEFAULT_FALLBACK_MESSAGE,
    LLM_FALLBACK_MESSAGE,
    get_fallback_result,
    get_fallback_message,
)
from app.tools.base import ToolResult


class TestFallbackMessages:
    """降级消息表"""

    def test_known_tool_has_message(self):
        for tool_name in [
            "product_search", "order_query", "logistics_track",
            "dashboard_stats", "employee_manage", "role_manage",
            "after_sales_manage", "customer_manage",
        ]:
            assert tool_name in FALLBACK_MESSAGES, f"{tool_name} missing from FALLBACK_MESSAGES"
            assert len(FALLBACK_MESSAGES[tool_name]) > 0

    def test_all_messages_are_non_empty(self):
        for tool_name, msg in FALLBACK_MESSAGES.items():
            assert len(msg.strip()) > 0, f"Empty message for {tool_name}"


class TestGetFallbackResult:
    """get_fallback_result"""

    def test_known_tool_returns_toolresult_with_fallback_true(self):
        result = get_fallback_result("product_search")
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert result.data["fallback"] is True

    def test_known_tool_returns_correct_message(self):
        result = get_fallback_result("order_query")
        assert "订单查询" in result.message

    def test_returns_specific_reason_in_data(self):
        result = get_fallback_result("product_search", reason="circuit_breaker_open")
        assert result.data["reason"] == "circuit_breaker_open"

    def test_unknown_tool_returns_default_message(self):
        result = get_fallback_result("nonexistent_tool")
        assert result.message == DEFAULT_FALLBACK_MESSAGE

    def test_no_reason_defaults_to_service_unavailable(self):
        result = get_fallback_result("product_search")
        assert result.data["reason"] == "service_unavailable"


class TestGetFallbackMessage:
    """get_fallback_message"""

    def test_known_tool_returns_text(self):
        msg = get_fallback_message("dashboard_stats")
        assert isinstance(msg, str)
        assert "数据统计" in msg

    def test_unknown_tool_returns_default(self):
        msg = get_fallback_message("unknown_tool")
        assert msg == DEFAULT_FALLBACK_MESSAGE


class TestLLMFallbackMessage:
    """LLM 降级常量"""

    def test_llm_fallback_is_non_empty_string(self):
        assert len(LLM_FALLBACK_MESSAGE) > 0
