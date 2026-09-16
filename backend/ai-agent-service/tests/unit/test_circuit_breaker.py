"""
测试 app.core.circuit_breaker — 三态熔断器

DF-011（`defense.breaker-threshold` / `defense.breaker-no-retry`）的**契约面**在这里锁死：
这两条 truths 是 `CircuitBreaker` 纯逻辑性质，**无法**由 agent-eval 的端到端用例证明
（理由与证据见下面两个用例的 docstring）。端到端只保留"可观测的防御行为"。
"""
# case_ids: DF-011, DF-012, DF-013
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

class TestCircuitBreaker4xxExclusion:
    """4xx HTTP status codes are handled at http_client layer, not at circuit breaker"""

    async def test_excluded_exceptions_skip_failure_count(self):
        """excluded_exceptions 类型的异常不计入 failure（用于排除业务异常）"""
        class BusinessValidationError(Exception):
            pass

        breaker = CircuitBreaker(
            name="test_exclude",
            failure_threshold=1,
            excluded_exceptions=(BusinessValidationError,)
        )

        async def raise_business_error():
            raise BusinessValidationError("业务校验失败")

        # 被排除的异常不计入 failure
        for _ in range(3):
            try:
                await breaker.call(raise_business_error)
            except BusinessValidationError:
                pass
        assert breaker.failure_count == 0
        assert breaker.state == CircuitBreakerState.CLOSED

    async def test_non_excluded_exception_still_counted(self):
        """未被排除的异常正常计入 failure"""
        class BusinessValidationError(Exception):
            pass

        breaker = CircuitBreaker(
            name="test_mixed",
            failure_threshold=1,
            excluded_exceptions=(BusinessValidationError,)
        )

        async def raise_runtime_error():
            raise RuntimeError("真正的系统错误")

        try:
            await breaker.call(raise_runtime_error)
        except RuntimeError:
            pass
        assert breaker.failure_count == 1

    async def test_excluded_exceptions_is_tuple(self):
        """excluded_exceptions 接受 Tuple[Type[BaseException]]"""
        breaker = CircuitBreaker(
            name="test_tuple",
            failure_threshold=1,
            excluded_exceptions=(ValueError, TypeError)
        )


class TestOpenBreakerBlocksTheCallEntirely:
    """开路 = **函数体根本不被执行**（DF-011 的「开路后不再发起 LLM 调用」的可执行判据）。

    为什么必须锁这条：`base_skill` 里 LLM 调用的形状是
    `call_with_retry(lambda: llm_breaker.call(_llm_invoke))` —— 若 `CircuitBreakerOpenError`
    是在**调用之后**才抛出（例如被包在 try/except 里返回兜底值），模型仍会被真实调用一次，
    「不再发起 LLM 调用」就是空话。断言必须落在"被执行次数"上，而不是"抛了什么异常"。
    """

    async def test_open_breaker_never_invokes_the_callable(self):
        breaker = CircuitBreaker(name="block_counted", failure_threshold=3)
        invocations = {"n": 0}

        async def counted_probe():
            invocations["n"] += 1
            return "probe-result"

        async def failing_probe():
            raise RuntimeError("downstream 503")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await breaker.call(failing_probe)
        assert breaker.state == CircuitBreakerState.OPEN, "连续 3 次失败后必须开路"

        with pytest.raises(CircuitBreakerOpenError):
            await breaker.call(counted_probe)
        assert invocations["n"] == 0, (
            f"开路后底层函数仍被调用了 {invocations['n']} 次 —— "
            "「开路后不再发起 LLM 调用」不成立（DF-011）"
        )

    async def test_open_breaker_error_propagates_through_call_with_retry(self):
        """开路异常穿过重试层**不重试**（DF-011「直接向上传播」）。

        为什么必须锁：`base_skill` 用 `call_with_retry(...)` 包住 breaker 调用。
        若重试策略把 `CircuitBreakerOpenError` 当瞬时错误，开路后仍会重试 N 次
        → 每次都真实打下游 → 熔断失去意义。
        """
        from app.llm.retry_policy import call_with_retry

        attempts = {"n": 0}

        async def factory():
            attempts["n"] += 1
            raise CircuitBreakerOpenError("blocked")

        with pytest.raises(CircuitBreakerOpenError):
            await call_with_retry(factory, max_retries=3, base_delay=0.001)
        assert attempts["n"] == 1, (
            f"CircuitBreakerOpenError 被重试了 {attempts['n']} 次 —— 开路不再立即向上传播"
        )


class TestHttpClient4xxDoesNotTripBreaker:
    """HTTP 熔断器**不把 4xx 算作失败**（DF-011 前提「连续 3 次失败」为何不成立的根因）。

    为什么必须锁这条：`http_client._do_call` 对 400≤status<500 直接
    `return {"success": False, ...}`（**不抛异常** → breaker 的 `_on_failure` 不会被调用），
    这是**有意设计**（4xx = 客户端/业务错误，不是服务故障）。

    实测（CI run 34838080233，DF-011）：输入是 5 条「查不存在的ID-00X」→ 商品不存在是 **404**
    ⇒ 无论查多少次，`admin_api:GET:/api/admin/products/{id}` 的 `failure_count` 恒为 0、
    breaker 永不 OPEN。因此任何以「连续 3 次失败后 breaker 打开」为前提的**端到端**断言
    都建立在不存在的前提上 —— 这条把它钉成机器断言，防止下次再用 4xx 输入去测熔断。
    """

    @staticmethod
    def _client_with(json_body: dict, status: int = 404):
        from app.utils.http_client import AdminApiClient

        client = AdminApiClient(base_url="http://admin-api:8080", service_token="t")
        fake = AsyncMock()
        resp = MagicMock()
        resp.status_code = status
        resp.json.return_value = json_body
        resp.text = str(json_body)
        resp.raise_for_status = MagicMock()
        fake.request = AsyncMock(return_value=resp)
        fake.is_closed = False
        client._client = fake
        return client

    async def test_repeated_404_leaves_breaker_closed(self):
        """连续 4 次 404 → breaker 仍 CLOSED、failure_count=0（服务故障 vs 客户端错误的边界）。"""
        client = self._client_with(
            {"error": {"code": "NOT_FOUND", "message": "商品不存在"}}
        )
        path = "/api/admin/products/ID-001"
        breaker = get_breaker(f"admin_api:GET:{path}")

        for _ in range(4):
            result = await client.get(path)
            assert result["success"] is False

        assert breaker.failure_count == 0, (
            "404 被计入了熔断失败数 —— 客户端错误被当成服务故障（会误熔断）"
        )
        assert breaker.state == CircuitBreakerState.CLOSED

    @staticmethod
    def _client_raising_5xx(status: int = 503):
        """真实的 5xx 形状：`raise_for_status()` 抛 httpx.HTTPStatusError（http_client 会 re-raise）。"""
        import httpx
        from app.utils.http_client import AdminApiClient

        client = AdminApiClient(base_url="http://admin-api:8080", service_token="t")
        fake = AsyncMock()
        response = httpx.Response(
            status_code=status,
            request=httpx.Request("GET", "http://admin-api:8080/api/admin/products/ID-002"),
        )
        resp = MagicMock()
        resp.status_code = status
        resp.text = "boom"
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("503", request=response.request, response=response)
        )
        fake.request = AsyncMock(return_value=resp)
        fake.is_closed = False
        client._client = fake
        return client

    async def test_5xx_does_trip_breaker(self):
        """反向：服务端故障（5xx）**必须**计入失败并最终开路（防上一条把熔断整体关死）。"""
        import httpx

        client = self._client_raising_5xx(503)
        path = "/api/admin/products/ID-002"
        breaker = get_breaker(f"admin_api:GET:{path}")

        for _ in range(3):
            with pytest.raises(httpx.HTTPStatusError):
                await client.get(path)

        assert breaker.failure_count >= 3, "5xx 未被计入熔断失败数 —— 熔断永不触发"
        assert breaker.state == CircuitBreakerState.OPEN


class TestExcludedExceptionsTupleShape:
    """`excluded_exceptions` 接受 Tuple[Type[BaseException]] 并被原样保存。"""

    def test_excluded_exceptions_is_tuple(self):
        breaker = CircuitBreaker(
            name="test_tuple",
            failure_threshold=1,
            excluded_exceptions=(ValueError, TypeError),
        )
        assert breaker.excluded_exceptions == (ValueError, TypeError)
