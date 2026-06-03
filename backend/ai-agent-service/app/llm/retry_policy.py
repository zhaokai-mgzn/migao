"""
LLM 智能重试策略

收敛式重试：仅对瞬时错误（超时、429、5xx）重试，
鉴权/参数错误（401/400/422）直接抛出，避免无谓消耗配额。

与 CircuitBreaker 协同：
- retry 应包在 breaker 调用外层（在 breaker 之前重试）
- breaker 抛 CircuitBreakerOpenError 时不重试，立刻向上传播
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Awaitable, Callable, Optional, TypeVar

from app.config import settings


logger = logging.getLogger(__name__)

T = TypeVar("T")

# 可重试的 HTTP 状态码（瞬时错误）
_RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# 不可重试的 HTTP 状态码（鉴权 / 参数错误）
_NON_RETRYABLE_STATUS: frozenset[int] = frozenset({400, 401, 403, 404, 422})


def _extract_status_code(exc: BaseException) -> Optional[int]:
    """尽力从异常对象中抽取 HTTP 状态码

    兼容 openai / httpx / requests 的常见属性命名：
    - exc.status_code
    - exc.response.status_code
    - exc.http_status
    """
    for attr in ("status_code", "http_status"):
        code = getattr(exc, attr, None)
        if isinstance(code, int):
            return code
    response = getattr(exc, "response", None)
    if response is not None:
        code = getattr(response, "status_code", None)
        if isinstance(code, int):
            return code
    return None


def _is_retryable(exc: BaseException) -> bool:
    """判断异常是否值得重试

    可重试：
        - asyncio.TimeoutError
        - HTTP 状态码 ∈ {429, 500, 502, 503, 504}
        - 网络层瞬时错误（ConnectionError / OSError）

    不可重试：
        - HTTP 状态码 ∈ {400, 401, 403, 404, 422}
        - CircuitBreakerOpenError（避免与熔断器冲突）
        - 其余未知异常默认不重试，遵循“收敛式”原则
    """
    # 熔断器开路：立即向上传播，不重试
    # 这里用字符串判断避免循环依赖
    if type(exc).__name__ == "CircuitBreakerOpenError":
        return False

    if isinstance(exc, asyncio.TimeoutError):
        return True

    status = _extract_status_code(exc)
    if status is not None:
        if status in _NON_RETRYABLE_STATUS:
            return False
        if status in _RETRYABLE_STATUS:
            return True
        return False

    # 网络瞬时错误：连接 / DNS / socket
    if isinstance(exc, (ConnectionError, OSError)):
        return True

    return False


async def call_with_retry(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    max_retries: Optional[int] = None,
    base_delay: Optional[float] = None,
) -> T:
    """以收敛式重试执行异步调用

    Args:
        coro_factory: 无参 async 工厂，每次重试都重新创建协程对象
                      （协程是一次性的，不能复用）
        max_retries: 最大重试次数，默认读 settings.LLM_RETRY_MAX_ATTEMPTS
        base_delay: 重试基础延迟（秒），默认读 settings.LLM_RETRY_BASE_DELAY_S

    Returns:
        coro_factory() 的返回值

    Raises:
        最后一次尝试的异常（包括不可重试异常立即抛出）
    """
    if max_retries is None:
        max_retries = settings.LLM_RETRY_MAX_ATTEMPTS
    if base_delay is None:
        base_delay = settings.LLM_RETRY_BASE_DELAY_S

    # 至少执行 1 次（attempt=0），上限为 1 + max_retries 次
    total_attempts = max(1, max_retries + 1)
    last_exc: Optional[BaseException] = None

    for attempt in range(total_attempts):
        try:
            return await coro_factory()
        except BaseException as exc:
            last_exc = exc
            if not _is_retryable(exc):
                logger.debug(
                    "[llm_retry] non-retryable error, raising | attempt=%d type=%s",
                    attempt + 1,
                    type(exc).__name__,
                )
                raise

            # 已是最后一次尝试，不再重试
            if attempt >= total_attempts - 1:
                logger.warning(
                    "[llm_retry] retries exhausted | attempts=%d type=%s err=%s",
                    attempt + 1,
                    type(exc).__name__,
                    str(exc)[:200],
                )
                raise

            # 指数退避 + jitter
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
            logger.info(
                "[llm_retry] retry %d/%d after %.2fs | type=%s err=%s",
                attempt + 1,
                total_attempts - 1,
                delay,
                type(exc).__name__,
                str(exc)[:200],
            )
            await asyncio.sleep(delay)

    # 理论不可达：循环要么 return 要么 raise
    assert last_exc is not None
    raise last_exc
