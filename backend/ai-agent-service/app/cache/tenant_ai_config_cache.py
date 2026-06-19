"""
TenantAiConfig 缓存层

为 get_greeting() 提供低延迟的租户 AI 配置读取。
两层缓存：内存（进程级，0ms）+ Redis（跨进程，5min TTL）。

若 admin-api 不可用，返回 None，调用方使用 channel_config.py 的默认值。
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Optional

from loguru import logger
import redis.asyncio as redis_async

from app.utils import redis_client as redis_module
from app.utils.http_client import get_admin_api_client

CACHE_KEY_PREFIX = "cache:tenant_ai_config:"
MEMORY_TTL = 60          # 内存缓存 TTL（秒）
REDIS_TTL = 300          # Redis 缓存 TTL（秒）


class TenantAiConfigCache:
    """租户 AI 配置缓存。

    两层缓存策略：
    1. 内存缓存（进程内 dict）— 最快，适合高频 greeting 调用
    2. Redis 缓存（跨进程）— 多个 worker 共享

    读取流程：内存 → Redis → admin-api HTTP → 写入两层缓存
    任何一层失败都不抛异常，优雅降级。
    """

    def __init__(self):
        self._memory: Dict[int, tuple[dict, float]] = {}  # tenant_id -> (config, expiry)
        self._lock = asyncio.Lock()

    def _get_redis(self) -> Optional[redis_async.Redis]:
        """从全局连接池获取 Redis 客户端。"""
        pool = redis_module.redis_pool
        if pool is None:
            return None
        return redis_async.Redis(connection_pool=pool)

    def _redis_key(self, tenant_id: int) -> str:
        return f"{CACHE_KEY_PREFIX}{tenant_id}"

    async def get_config(self, tenant_id: int) -> Optional[dict]:
        """获取租户 AI 配置。

        Returns:
            TenantAiConfig dict，或 None（admin-api 不可用时）
        """
        # 1. 内存缓存
        if tenant_id in self._memory:
            config, expiry = self._memory[tenant_id]
            if time.time() < expiry:
                return config
            del self._memory[tenant_id]

        # 2. Redis 缓存
        try:
            r = self._get_redis()
            if r:
                raw = await r.get(self._redis_key(tenant_id))
                if raw:
                    config = json.loads(raw)
                    self._memory[tenant_id] = (config, time.time() + MEMORY_TTL)
                    return config
        except Exception:
            pass  # Redis 不可用，继续走 admin-api

        # 3. admin-api HTTP
        config = await self._fetch_from_admin_api(tenant_id)
        if config is None:
            return None

        # 4. 写入两层缓存
        self._memory[tenant_id] = (config, time.time() + MEMORY_TTL)
        try:
            r = self._get_redis()
            if r:
                await r.setex(
                    self._redis_key(tenant_id),
                    REDIS_TTL,
                    json.dumps(config, ensure_ascii=False, default=str),
                )
        except Exception:
            pass

        return config

    async def _fetch_from_admin_api(self, tenant_id: int) -> Optional[dict]:
        """从 admin-api 拉取 TenantAiConfig。"""
        try:
            client = get_admin_api_client()
            response = await client.get(
                "/api/admin/tenant/ai-config",
                tenant_id=tenant_id,
                user_id="0",  # 系统内部调用，无具体用户
            )
            if response.get("success") and response.get("data"):
                logger.debug(f"TenantAiConfig fetched: tenant={tenant_id}")
                return response["data"]
            logger.warning(
                f"TenantAiConfig fetch failed: tenant={tenant_id} "
                f"error={response.get('error', {}).get('message', 'unknown')}"
            )
            return None
        except Exception as e:
            logger.warning(f"TenantAiConfig fetch error: tenant={tenant_id} {e}")
            return None

    async def invalidate(self, tenant_id: int) -> None:
        """清除指定租户的缓存（配置更新后调用）。"""
        self._memory.pop(tenant_id, None)
        try:
            r = self._get_redis()
            if r:
                await r.delete(self._redis_key(tenant_id))
        except Exception:
            pass
        logger.info(f"TenantAiConfig cache invalidated: tenant={tenant_id}")
