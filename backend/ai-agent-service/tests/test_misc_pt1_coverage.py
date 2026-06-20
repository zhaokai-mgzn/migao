"""Tests for misc-part1 — coverage gap issue #576"""
import pytest
from unittest.mock import MagicMock

class TestExtractStatusCode:
    def test_openai_status_code(self):
        from app.llm.retry_policy import _extract_status_code
        exc = Exception(); exc.status_code = 429
        assert _extract_status_code(exc) == 429

    def test_httpx_response(self):
        from app.llm.retry_policy import _extract_status_code
        exc = Exception(); exc.response = MagicMock(status_code=500)
        assert _extract_status_code(exc) == 500

    def test_no_status_code(self):
        from app.llm.retry_policy import _extract_status_code
        assert _extract_status_code(Exception()) is None

class TestIsRetryable:
    def test_retryable_429(self):
        from app.llm.retry_policy import _is_retryable
        exc = Exception(); exc.status_code = 429
        assert _is_retryable(exc) is True

    def test_non_retryable_401(self):
        from app.llm.retry_policy import _is_retryable
        exc = Exception(); exc.status_code = 401
        assert _is_retryable(exc) is False

    def test_non_retryable_400(self):
        from app.llm.retry_policy import _is_retryable
        exc = Exception(); exc.status_code = 400
        assert _is_retryable(exc) is False

class TestCallWithRetry:
    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        from app.llm.retry_policy import call_with_retry
        count = [0]
        async def fn():
            count[0] += 1
            return "ok"
        result = await call_with_retry(fn, max_retries=2)
        assert result == "ok" and count[0] == 1

    @pytest.mark.asyncio
    async def test_retry_on_429(self):
        from app.llm.retry_policy import call_with_retry
        count = [0]
        async def fn():
            count[0] += 1
            if count[0] < 3:
                exc = Exception("rate limit"); exc.status_code = 429; raise exc
            return "recovered"
        result = await call_with_retry(fn, max_retries=3, base_delay=0.001)
        assert result == "recovered" and count[0] == 3

class TestConversationStage:
    def test_enum_values(self):
        from app.context.tracker import ConversationStage
        assert len(list(ConversationStage)) >= 4
        assert ConversationStage.INITIAL.value == "initial"

class TestCostTrackerFunctions:
    def test_calc_cost(self):
        from app.llm.cost_tracker import _calc_cost_cny
        cost = _calc_cost_cny("test-model", 1000, 500)
        assert cost >= 0
