"""
AI 智能客服系统 - 核心稳定性基础设施

提供 Tool 调用层的可靠性保障：
- CircuitBreaker 熔断器：自动隔离故障下游
- Fallback 降级机制：在熔断/失败时返回友好回复
- AdminApiCache 缓存：admin-api 不可用时的兜底数据来源
"""

from app.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerState,
    circuit_breaker,
    get_breaker,
    reset_breakers,
)
from app.core.fallback import (
    FALLBACK_MESSAGES,
    LLM_FALLBACK_MESSAGE,
    get_fallback_result,
)
from app.core.admin_api_cache import (
    AdminApiCache,
    get_admin_api_cache,
)

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "CircuitBreakerState",
    "circuit_breaker",
    "get_breaker",
    "reset_breakers",
    "FALLBACK_MESSAGES",
    "LLM_FALLBACK_MESSAGE",
    "get_fallback_result",
    "AdminApiCache",
    "get_admin_api_cache",
]
