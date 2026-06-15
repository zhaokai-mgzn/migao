"""
测试 app.core.circuit_breaker — 三态熔断器
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerState,
    circuit_breaker as cb_decorator,
    get_breaker,
    reset_breakers,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    """每个测试前清空全局注册表"""
    reset_breakers()
    yield
    reset_breakers()


class TestCircuitBreakerInit:
    """初始化和属性"""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0
        assert cb.is_open() is False

    def test_is_open_returns_false_when_closed(self):
        cb = CircuitBreaker("test")
        assert cb.is_open() is False

    def test_snapshot_contains_expected_keys(self):
        cb = CircuitBreaker("test")
        snap = cb.snapshot()
        assert snap["name"] == "test"
        assert snap["state"] == "CLOSED"
        assert snap["failure_count"] == 0


class TestClosedState:
    """CLOSED 状态行为"""

    async def test_success_keeps_closed(self):
        cb = CircuitBreaker("test")
        mock_func = AsyncMock(return_value="ok")
        result = await cb.call(mock_func, "arg1", kw="val")
        assert result == "ok"
        assert cb.failure_count == 0
        assert cb.state == CircuitBreakerState.CLOSED

    async def test_failure_increments_count(self):
        cb = CircuitBreaker("test")
        mock_func = AsyncMock(side_effect=ValueError("boom"))
        with pytest.raises(ValueError, match="boom"):
            await cb.call(mock_func)
        assert cb.failure_count == 1
        assert cb.state == CircuitBreakerState.CLOSED

    async def test_consecutive_failures_trip_to_open(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        for i in range(3):
            with pytest.raises(ValueError):
                await cb.call(AsyncMock(side_effect=ValueError(f"fail_{i}")))
        assert cb.state == CircuitBreakerState.OPEN
        assert cb.is_open() is True


class TestOpenState:
    """OPEN 状态行为"""

    async def test_rejects_calls_when_open(self):
        cb = CircuitBreaker("test")
        # 先让熔断器打开
        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(AsyncMock(side_effect=ValueError("boom")))
        assert cb.state == CircuitBreakerState.OPEN
        # 再调用应直接拒绝
        with pytest.raises(CircuitBreakerOpenError, match="OPEN"):
            await cb.call(AsyncMock(return_value="ok"))

    async def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)
        # trip
        with pytest.raises(ValueError):
            await cb.call(AsyncMock(side_effect=ValueError("boom")))
        assert cb.state == CircuitBreakerState.OPEN
        # wait
        await asyncio.sleep(0.02)
        # next call should transition to HALF_OPEN
        mock_func = AsyncMock(return_value="ok")
        await cb.call(mock_func)
        assert cb.state == CircuitBreakerState.CLOSED  # probe success → CLOSED


class TestHalfOpenState:
    """HALF_OPEN 状态行为"""

    async def test_success_in_half_open_transitions_to_closed(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)
        with pytest.raises(ValueError):
            await cb.call(AsyncMock(side_effect=ValueError("boom")))
        await asyncio.sleep(0.02)
        result = await cb.call(AsyncMock(return_value="ok"))
        assert result == "ok"
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0

    async def test_failure_in_half_open_transitions_back_to_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)
        with pytest.raises(ValueError):
            await cb.call(AsyncMock(side_effect=ValueError("boom")))
        await asyncio.sleep(0.02)
        with pytest.raises(ValueError):
            await cb.call(AsyncMock(side_effect=ValueError("boom2")))
        assert cb.state == CircuitBreakerState.OPEN

    async def test_half_open_probe_limit(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01, half_open_max_calls=1)
        with pytest.raises(ValueError):
            await cb.call(AsyncMock(side_effect=ValueError("boom")))
        await asyncio.sleep(0.02)

        # 启动两个并发探测，一个应被拒绝
        async def probe():
            await cb.call(AsyncMock(return_value="ok"))

        t1 = asyncio.create_task(probe())
        t2 = asyncio.create_task(probe())

        # 一个成功，一个可能被拒绝
        results = await asyncio.gather(t1, t2, return_exceptions=True)
        assert any(not isinstance(r, Exception) for r in results)


class TestExcludedExceptions:
    """排除异常不计入失败"""

    async def test_excluded_exception_not_counted(self):
        cb = CircuitBreaker("test", excluded_exceptions=(ValueError,))
        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(AsyncMock(side_effect=ValueError("ignore")))
        assert cb.failure_count == 0
        assert cb.state == CircuitBreakerState.CLOSED

    async def test_non_excluded_exception_counted(self):
        cb = CircuitBreaker("test", excluded_exceptions=(ValueError,))
        with pytest.raises(TypeError):
            await cb.call(AsyncMock(side_effect=TypeError("count me")))
        assert cb.failure_count == 1


class TestReset:
    """手动重置"""

    def test_reset_clears_all(self):
        cb = CircuitBreaker("test")
        cb._state = CircuitBreakerState.OPEN
        cb._failure_count = 5
        cb._opened_at = time.monotonic()
        cb._half_open_in_flight = 3
        cb.reset()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0
        assert cb.is_open() is False


class TestRegistry:
    """全局注册表"""

    def test_get_breaker_lazy_creates_singleton(self):
        b1 = get_breaker("my_api")
        b2 = get_breaker("my_api")
        assert b1 is b2

    def test_get_breaker_different_names(self):
        b1 = get_breaker("a")
        b2 = get_breaker("b")
        assert b1 is not b2

    def test_reset_breakers_clears_all(self):
        b1 = get_breaker("x")
        b2 = get_breaker("y")
        b1._state = CircuitBreakerState.OPEN
        b2._state = CircuitBreakerState.OPEN
        reset_breakers()
        assert b1.state == CircuitBreakerState.CLOSED
        assert b2.state == CircuitBreakerState.CLOSED


class TestDecorator:
    """circuit_breaker 装饰器"""

    async def test_decorator_passes_through_result(self):
        @cb_decorator(name="deco_test")
        async def my_func(x):
            return x * 2

        result = await my_func(5)
        assert result == 10

    async def test_decorator_trips_breaker_on_failure(self):
        call_count = 0

        @cb_decorator(name="deco_fail", failure_threshold=2)
        async def failing_func():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        for _ in range(2):
            with pytest.raises(ValueError):
                await failing_func()

        # 第三次应直接拒绝（熔断器 OPEN）
        with pytest.raises(CircuitBreakerOpenError):
            await failing_func()

    async def test_decorator_has_circuit_breaker_attr(self):
        @cb_decorator(name="deco_attr")
        async def my_func():
            return 1

        assert hasattr(my_func, "__circuit_breaker__")
        assert isinstance(my_func.__circuit_breaker__, CircuitBreaker)
