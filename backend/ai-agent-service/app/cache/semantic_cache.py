"""
AI 智能客服系统 - 语义缓存层

对语义相似的查询直接返回缓存答案，避免重复调用大模型链路。
使用 Redis 存储缓存条目，DashScope text-embedding-v3 生成向量，
纯 Python 余弦相似度匹配。
"""

import asyncio
import json
import math
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import redis.asyncio as redis
from loguru import logger

from app.config import settings
from app.llm import EMBEDDING_API_KEY, EMBEDDING_MODEL
from app.utils.redis_client import redis_pool


# ────────────────────────── 数据结构 ──────────────────────────

@dataclass
class CacheResult:
    """缓存命中结果"""
    answer: str
    intent_type: str
    confidence: float  # 余弦相似度分数
    cached_at: datetime


# ────────────────────── TTL 策略 ──────────────────────────

# 按意图类型设置不同 TTL（秒）
TTL_BY_INTENT: Dict[str, int] = {
    "greeting": 86400,          # 24h
    "knowledge_faq": 86400,     # 24h
    "product_inquiry": 3600,    # 1h
    "order_query": 300,         # 5min（动态数据）
    "logistics_track": 300,     # 5min（动态数据）
    "after_sales": 1800,        # 30min
    "complaint": 1800,          # 30min
    "general": 3600,            # 1h
}

DEFAULT_TTL = 3600  # 默认 1h


# ────────────────────── Embedding 工具函数 ──────────────────────

async def get_embedding(text: str) -> List[float]:
    """
    使用 DashScope text-embedding-v3 生成单条文本的 embedding 向量。

    Args:
        text: 输入文本

    Returns:
        embedding 向量 (list[float])
    """
    import dashscope

    dashscope.api_key = EMBEDDING_API_KEY
    model = EMBEDDING_MODEL

    def _call():
        return dashscope.TextEmbedding.call(
            model=model,
            input=[text],
            text_type="query",
        )

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, _call)

    if response.status_code == 200:
        return response.output["embeddings"][0]["embedding"]

    raise RuntimeError(
        f"Embedding API failed: status={response.status_code} "
        f"message={getattr(response, 'message', 'unknown')}"
    )


# ────────────────────── 余弦相似度（纯 Python）──────────────────

def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ────────────────────── 语义缓存核心类 ──────────────────────

class SemanticCache:
    """
    语义缓存层

    每个租户在 Redis 中维护一个缓存条目列表（JSON 序列化），
    对新查询生成 embedding 后，与缓存池中所有条目计算余弦相似度，
    命中阈值以上的直接返回缓存答案。

    Redis key 格式:  semantic_cache:{tenant_id}:entries
    """

    KEY_PREFIX = "semantic_cache"

    def __init__(
        self,
        similarity_threshold: Optional[float] = None,
        max_entries: Optional[int] = None,
    ):
        self.similarity_threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else settings.SEMANTIC_CACHE_SIMILARITY_THRESHOLD
        )
        self.max_entries = (
            max_entries
            if max_entries is not None
            else settings.SEMANTIC_CACHE_MAX_ENTRIES
        )

    # ─────────── 内部工具 ───────────

    def _cache_key(self, tenant_id: str) -> str:
        return f"{self.KEY_PREFIX}:{tenant_id}:entries"

    async def _get_redis(self) -> redis.Redis:
        if not redis_pool:
            raise RuntimeError("Redis connection pool is not initialized")
        return redis.Redis(connection_pool=redis_pool)

    async def _load_entries(self, client: redis.Redis, key: str) -> List[Dict[str, Any]]:
        """从 Redis 读取该租户的全部缓存条目"""
        raw = await client.get(key)
        if not raw:
            return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"[semantic-cache] Corrupt cache data, resetting | key={key}")
            await client.delete(key)
            return []

    async def _save_entries(
        self,
        client: redis.Redis,
        key: str,
        entries: List[Dict[str, Any]],
        ttl: Optional[int] = None,
    ) -> None:
        """将缓存条目列表写回 Redis"""
        data = json.dumps(entries, ensure_ascii=False)
        if ttl:
            await client.set(key, data, ex=ttl)
        else:
            await client.set(key, data)

    # ─────────── 公开接口 ───────────

    async def lookup(self, tenant_id: str, query: str) -> Optional[CacheResult]:
        """
        查找语义缓存。

        对 query 生成 embedding，在该租户的缓存池中寻找余弦相似度
        超过阈值的条目，命中则返回 CacheResult，否则返回 None。

        Args:
            tenant_id: 租户 ID
            query: 用户查询文本

        Returns:
            CacheResult 或 None
        """
        if not settings.SEMANTIC_CACHE_ENABLED:
            return None

        client = await self._get_redis()
        try:
            key = self._cache_key(tenant_id)
            entries = await self._load_entries(client, key)
            if not entries:
                return None

            # 生成查询 embedding
            query_embedding = await get_embedding(query)

            best_score = 0.0
            best_entry: Optional[Dict[str, Any]] = None

            for entry in entries:
                cached_embedding = entry.get("query_embedding")
                if not cached_embedding:
                    continue
                score = _cosine_similarity(query_embedding, cached_embedding)
                if score > best_score:
                    best_score = score
                    best_entry = entry

            if best_entry and best_score >= self.similarity_threshold:
                logger.info(
                    f"[semantic-cache] HIT | tenant={tenant_id} "
                    f"score={best_score:.4f} query={query[:50]}"
                )
                return CacheResult(
                    answer=best_entry["answer"],
                    intent_type=best_entry["intent_type"],
                    confidence=best_score,
                    cached_at=datetime.fromisoformat(best_entry["created_at"]),
                )

            logger.debug(
                f"[semantic-cache] MISS | tenant={tenant_id} "
                f"best_score={best_score:.4f} query={query[:50]}"
            )
            return None

        except Exception as e:
            # 缓存层失败不应阻塞主流程，降级为未命中
            logger.error(f"[semantic-cache] lookup error | tenant={tenant_id} error={e}")
            return None
        finally:
            await client.close()

    async def store(
        self,
        tenant_id: str,
        query: str,
        answer: str,
        intent_type: str,
        ttl: Optional[int] = None,
    ) -> None:
        """
        将问答对写入语义缓存。

        Args:
            tenant_id: 租户 ID
            query: 用户查询文本
            answer: 回答内容
            intent_type: 意图类型
            ttl: 自定义 TTL（秒），为 None 则按 intent_type 自动选择
        """
        if not settings.SEMANTIC_CACHE_ENABLED:
            return

        client = await self._get_redis()
        try:
            key = self._cache_key(tenant_id)
            entries = await self._load_entries(client, key)

            # 生成 embedding
            query_embedding = await get_embedding(query)

            now = datetime.now(timezone.utc).isoformat()
            new_entry: Dict[str, Any] = {
                "query_embedding": query_embedding,
                "query_text": query,
                "answer": answer,
                "intent_type": intent_type,
                "created_at": now,
            }

            # 检查是否已有高度相似的条目，有则更新而非新增
            replaced = False
            for i, entry in enumerate(entries):
                cached_emb = entry.get("query_embedding")
                if cached_emb and _cosine_similarity(query_embedding, cached_emb) >= self.similarity_threshold:
                    entries[i] = new_entry
                    replaced = True
                    break

            if not replaced:
                entries.append(new_entry)

            # 淘汰最旧条目（超出 max_entries 时）
            if len(entries) > self.max_entries:
                # 按 created_at 排序，保留最新的
                entries.sort(key=lambda e: e.get("created_at", ""), reverse=True)
                entries = entries[: self.max_entries]

            # 使用意图 TTL 或自定义 TTL
            effective_ttl = ttl if ttl is not None else TTL_BY_INTENT.get(intent_type, DEFAULT_TTL)
            await self._save_entries(client, key, entries, ttl=effective_ttl)

            logger.info(
                f"[semantic-cache] STORE | tenant={tenant_id} intent={intent_type} "
                f"ttl={effective_ttl}s entries={len(entries)} query={query[:50]}"
            )

        except Exception as e:
            logger.error(f"[semantic-cache] store error | tenant={tenant_id} error={e}")
        finally:
            await client.close()

    async def invalidate(self, tenant_id: str, pattern: Optional[str] = None) -> None:
        """
        清除指定租户的语义缓存。

        Args:
            tenant_id: 租户 ID
            pattern: 可选，按意图类型过滤清除（如 "order_query"）；
                     为 None 则清除该租户所有缓存。
        """
        client = await self._get_redis()
        try:
            key = self._cache_key(tenant_id)

            if pattern is None:
                # 清除所有
                await client.delete(key)
                logger.info(f"[semantic-cache] INVALIDATE ALL | tenant={tenant_id}")
            else:
                # 按 pattern 过滤
                entries = await self._load_entries(client, key)
                original_count = len(entries)
                entries = [
                    e for e in entries
                    if not (
                        pattern in e.get("intent_type", "")
                        or pattern in e.get("query_text", "")
                    )
                ]
                removed = original_count - len(entries)

                if entries:
                    await self._save_entries(client, key, entries)
                else:
                    await client.delete(key)

                logger.info(
                    f"[semantic-cache] INVALIDATE | tenant={tenant_id} "
                    f"pattern={pattern} removed={removed}"
                )

        except Exception as e:
            logger.error(f"[semantic-cache] invalidate error | tenant={tenant_id} error={e}")
        finally:
            await client.close()


# 模块级单例，供外部直接使用
semantic_cache = SemanticCache()
