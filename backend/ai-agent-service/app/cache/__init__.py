"""
AI 智能客服系统 - 语义缓存模块

提供基于 embedding 余弦相似度的语义级缓存，
对高频重复问题直接返回缓存答案，降低大模型调用成本。
"""

from app.cache.semantic_cache import (
    SemanticCache,
    CacheResult,
    semantic_cache,
    get_embedding,
    TTL_BY_INTENT,
    DEFAULT_TTL,
)

__all__ = [
    "SemanticCache",
    "CacheResult",
    "semantic_cache",
    "get_embedding",
    "TTL_BY_INTENT",
    "DEFAULT_TTL",
]
