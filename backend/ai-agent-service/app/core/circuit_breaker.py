"""
AI 智能客服系统 - 熔断器（CircuitBreaker）

实现经典三态熔断器，用于保护下游服务（admin-api、LLM 等）：

状态机：
    CLOSED  → 正常放行；连续失败达到 failure_threshold 后切到 OPEN
    OPEN    → 直接拒绝调用，抛出 CircuitBreakerOpenError；
              recovery_timeout 后允许有限次数 HALF_OPEN 探测
    HALF_OPEN → 仅放行 half_open_max_calls 次探测；
                探测成功 → CLOSED；探测失败 → OPEN

线程/协程安全：
- CircuitBreaker 自身的状态变更通过 asyncio.Lock 串行化
- 全局 _breakers 注册表通过 _registry_lock 串行化（同步锁，
  因为 get_breaker 通常在同步上下文中调用）

典型用法：
    breaker = get_breaker("admin_api", failure_threshold=3, recovery_timeout=30)
    result = await breaker.call(some_async_func, arg1, kw=val)

    # 或装饰器形式
    @circuit_breaker(name="admin_api")
    async def call_admin_api(...):
        ...
"""
from __future__ import annotations

import asyncio
import functools
import time
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, Type

from loguru import logger


class CircuitBreakerState(str, Enum):
    """熔断器状态"""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenError(Exception):
    """熔断器处于 OPEN（或 HALF_OPEN 已达探测上限）时抛出"""

    def __init__(self, name: str, message: Optional[str] = None) -> None:
        self.name = name
        super().__init__(message or f"CircuitBreaker '{name}' is OPEN")


class CircuitBreaker:
    """异步熔断器实现

    Args:
        name: 熔断器名（用于日志、注册表 key）
        failure_threshold: CLOSED 状态下连续失败多少次后切到 OPEN
        recovery_timeout: OPEN 状态保持多少秒后允许 HALF_OPEN 探测
        half_open_max_calls: HALF_OPEN 状态下并发探测调用上限
        excluded_exceptions: 这些异常不计入失败统计（如业务校验错误）
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
        excluded_exceptions: Tuple[Type[BaseException], ...] = (),
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.excluded_exceptions = excluded_exceptions

        self._state: CircuitBreakerState = CircuitBreakerState.CLOSED
        self._failure_count: int = 0
        self._opened_at: float = 0.0
        self._half_open_in_flight: int = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitBreakerState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def is_open(self) -> bool:
        """快速判断是否处于 OPEN 状态（不带探测时序检查，仅给调用方快速兜底用）"""
        if self._state != CircuitBreakerState.OPEN:
            return False
        # 已超过 recovery_timeout 表示即将进入 HALF_OPEN，不再视为完全 OPEN
        if time.monotonic() - self._opened_at >= self.recovery_timeout:
            return False
        return True

    def snapshot(self) -> Dict[str, Any]:
        """返回快照，主要用于日志/监控"""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "opened_at": self._opened_at,
            "half_open_in_flight": self._half_open_in_flight,
        }

    def _transition(self, new_state: CircuitBreakerState, reason: str = "") -> None:
        """切换状态并记录日志（必须在持有 _lock 时调用）"""
        old_state = self._state
        if old_state == new_state:
            return
        logger.warning(
            f"[circuit-breaker:{self.name}] state transition: "
            f"{old_state.value} → {new_state.value} | reason={reason} "
            f"failures={self._failure_count}"
        )
        self._state = new_state
        if new_state == CircuitBreakerState.OPEN:
            self._opened_at = time.monotonic()
            self._half_open_in_flight = 0
        elif new_state == CircuitBreakerState.HALF_OPEN:
            self._half_open_in_flight = 0
        elif new_state == CircuitBreakerState.CLOSED:
            self._failure_count = 0
            self._opened_at = 0.0
            self._half_open_in_flight = 0

    async def _before_call(self) -> None:
        """调用前置检查：决定放行 / 拒绝 / 切到 HALF_OPEN"""
        async with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                if time.monotonic() - self._opened_at >= self.recovery_timeout:
                    self._transition(
                        CircuitBreakerState.HALF_OPEN,
                        reason=f"recovery_timeout({self.recovery_timeout}s) elapsed",
                    )
                else:
                    raise CircuitBreakerOpenError(self.name)

            if self._state == CircuitBreakerState.HALF_OPEN:
                if self._half_open_in_flight >= self.half_open_max_calls:
                    raise CircuitBreakerOpenError(
                        self.name,
                        f"CircuitBreaker '{self.name}' HALF_OPEN probe limit reached",
                    )
                self._half_open_in_flight += 1

    async def _on_success(self) -> None:
        async with self._lock:
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._transition(
                    CircuitBreakerState.CLOSED,
                    reason="probe success in HALF_OPEN",
                )
            self._failure_count = 0

    async def _on_failure(self, exc: BaseException) -> None:
        # 排除指定异常（不计入失败）
        if self.excluded_exceptions and isinstance(exc, self.excluded_exceptions):
            return
        async with self._lock:
            self._failure_count += 1
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._transition(
                    CircuitBreakerState.OPEN,
                    reason=f"probe failed: {type(exc).__name__}",
                )
            elif self._state == CircuitBreakerState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._transition(
                        CircuitBreakerState.OPEN,
                        reason=(
                            f"failure_threshold reached "
                            f"({self._failure_count}/{self.failure_threshold})"
                        ),
                    )

    async def call(self, func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        """以熔断器保护的方式执行异步函数。

        Raises:
            CircuitBreakerOpenError: 熔断器处于 OPEN（或 HALF_OPEN 已达探测上限）。
            Exception: 业务函数本身抛出的异常（已计入失败统计）。
        """
        await self._before_call()
        try:
            result = await func(*args, **kwargs)
        except CircuitBreakerOpenError:
            # 来自下层的熔断异常直接透传，不重复计入失败
            raise
        except BaseException as exc:
            await self._on_failure(exc)
            raise
        else:
            await self._on_success()
            return result

    def reset(self) -> None:
        """手动重置熔断器（用于测试 / 运维）"""
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._opened_at = 0.0
        self._half_open_in_flight = 0


# ==================== 全局注册表 ====================

_breakers: Dict[str, CircuitBreaker] = {}

# 同步锁：get_breaker 通常被同步代码调用
import threading as _threading  # noqa: E402

_registry_lock = _threading.Lock()


def get_breaker(
    name: str,
    failure_threshold: int = 3,
    recovery_timeout: float = 30.0,
    half_open_max_calls: int = 1,
    excluded_exceptions: Tuple[Type[BaseException], ...] = (),
) -> CircuitBreaker:
    """获取（或惰性创建）指定名字的熔断器单例。

    后续相同 name 的调用直接复用首次创建时的配置。
    """
    breaker = _breakers.get(name)
    if breaker is not None:
        return breaker
    with _registry_lock:
        breaker = _breakers.get(name)
        if breaker is None:
            breaker = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                half_open_max_calls=half_open_max_calls,
                excluded_exceptions=excluded_exceptions,
            )
            _breakers[name] = breaker
        return breaker


def reset_breakers() -> None:
    """重置所有已注册熔断器（主要用于测试）"""
    with _registry_lock:
        for breaker in _breakers.values():
            breaker.reset()


def circuit_breaker(
    name: str,
    failure_threshold: int = 3,
    recovery_timeout: float = 30.0,
    half_open_max_calls: int = 1,
    excluded_exceptions: Tuple[Type[BaseException], ...] = (),
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """装饰器形式的熔断器，仅适用于 async 函数。

    示例：
        @circuit_breaker(name="admin_api", failure_threshold=3, recovery_timeout=30)
        async def fetch(...):
            ...
    """

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        breaker = get_breaker(
            name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            half_open_max_calls=half_open_max_calls,
            excluded_exceptions=excluded_exceptions,
        )

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await breaker.call(func, *args, **kwargs)

        wrapper.__circuit_breaker__ = breaker  # type: ignore[attr-defined]
        return wrapper

    return decorator
