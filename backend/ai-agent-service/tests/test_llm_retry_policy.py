"""LLM 重试策略单元测试（app/llm/retry_policy.py）

覆盖：
- _extract_status_code：openai / httpx / requests 属性名兼容 + 无状态码
- _is_retryable：可重试（429/5xx/Timeout/ConnectionError/OSError）与不可重试（4xx/熔断/未知）
- call_with_retry：至少执行一次、成功不重试、重试后恢复、耗尽重试、不可重试立即抛出
"""
# case_ids: DF-011
import asyncio

import pytest

from app.llm.retry_policy import (
    _extract_status_code,
    _is_retryable,
    call_with_retry,
)


class TestExtractStatusCode:
    def test_direct_status_code(self):
        exc = Exception()
        exc.status_code = 429
        assert _extract_status_code(exc) == 429

    def test_http_status_attr(self):
        exc = Exception()
        exc.http_status = 500
        assert _extract_status_code(exc) == 500

    def test_response_status_code(self):
        exc = Exception()
        exc.response = type("Resp", (), {"status_code": 503})()
        assert _extract_status_code(exc) == 503

    def test_non_int_status_ignored(self):
        exc = Exception()
        exc.status_code = "429"
        assert _extract_status_code(exc) is None

    def test_no_status(self):
        assert _extract_status_code(Exception()) is None


class TestIsRetryable:
    @pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
    def test_retryable_status(self, code):
        exc = Exception()
        exc.status_code = code
        assert _is_retryable(exc) is True

    @pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
    def test_non_retryable_status(self, code):
        exc = Exception()
        exc.status_code = code
        assert _is_retryable(exc) is False

    def test_unknown_status_not_retryable(self):
        exc = Exception()
        exc.status_code = 418
        assert _is_retryable(exc) is False

    def test_timeout_retryable(self):
        assert _is_retryable(asyncio.TimeoutError()) is True

    def test_connection_error_retryable(self):
        assert _is_retryable(ConnectionError("reset")) is True

    def test_os_error_retryable(self):
        assert _is_retryable(OSError("socket")) is True

    def test_circuit_breaker_open_not_retryable(self):
        exc = type("CircuitBreakerOpenError", (Exception,), {})()
        assert _is_retryable(exc) is False

    def test_unknown_exception_not_retryable(self):
        assert _is_retryable(RuntimeError("boom")) is False


class TestCallWithRetry:
    @pytest.mark.asyncio
    async def test_success_runs_once(self):
        calls = [0]

        async def fn():
            calls[0] += 1
            return "ok"

        result = await call_with_retry(fn, max_retries=3, base_delay=0.001)
        assert result == "ok"
        assert calls[0] == 1

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        calls = [0]

        async def fn():
            calls[0] += 1
            if calls[0] < 3:
                exc = Exception("rate limit")
                exc.status_code = 429
                raise exc
            return "recovered"

        result = await call_with_retry(fn, max_retries=3, base_delay=0.001)
        assert result == "recovered"
        assert calls[0] == 3

    @pytest.mark.asyncio
    async def test_exhaust_retries_raises(self):
        calls = [0]

        async def fn():
            calls[0] += 1
            exc = Exception("timeout")
            exc.status_code = 504
            raise exc

        with pytest.raises(Exception) as exc_info:
            await call_with_retry(fn, max_retries=2, base_delay=0.001)
        assert exc_info.value.status_code == 504
        # 1 次初始 + 2 次重试 = 3 次
        assert calls[0] == 3

    @pytest.mark.asyncio
    async def test_non_retryable_raises_immediately(self):
        calls = [0]

        async def fn():
            calls[0] += 1
            exc = Exception("auth")
            exc.status_code = 401
            raise exc

        with pytest.raises(Exception) as exc_info:
            await call_with_retry(fn, max_retries=5, base_delay=0.001)
        assert exc_info.value.status_code == 401
        assert calls[0] == 1

    @pytest.mark.asyncio
    async def test_max_retries_zero_runs_once(self):
        calls = [0]

        async def fn():
            calls[0] += 1
            exc = Exception("timeout")
            exc.status_code = 504
            raise exc

        with pytest.raises(Exception):
            await call_with_retry(fn, max_retries=0, base_delay=0.001)
        assert calls[0] == 1

    @pytest.mark.asyncio
    async def test_timeout_error_retryable(self):
        calls = [0]

        async def fn():
            calls[0] += 1
            if calls[0] < 2:
                raise asyncio.TimeoutError()
            return "ok"

        result = await call_with_retry(fn, max_retries=1, base_delay=0.001)
        assert result == "ok"
        assert calls[0] == 2
