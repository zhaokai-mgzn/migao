"""
AI 智能客服系统 - admin-api 调用缓存层

为高频只读接口（商品搜索 / 分类树）提供 Redis 缓存：
- product_search: TTL 5 分钟
- category_tree:  TTL 30 分钟

缓存策略：
1. 正常成功：写入缓存（覆盖旧值）
2. admin-api 不可用 / 熔断 OPEN：作为兜底返回最近一次缓存
3. 多租户隔离：所有 key 均带 tenant_id 前缀

设计原则：
- 任何 Redis 异常都不抛给上游，缓存层不能拖垮主流程
- 命中即返回；未命中由调用方决定是否走 admin-api
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

from loguru import logger

import redis.asyncio as redis_async

from app.utils import redis_client as redis_module


KEY_PREFIX = "cache:admin_api:"
TTL_PRODUCT_SEARCH = 300       # 5 分钟
TTL_CATEGORY_TREE = 1800       # 30 分钟


def _hash_params(params: Optional[Dict[str, Any]]) -> str:
    """将查询参数稳定哈希为短字符串，作为缓存 key 的一部分。"""
    if not params:
        return "empty"
    payload = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()[:16]


class AdminApiCache:
    """admin-api 数据缓存（基于 Redis）

    设计原则：
    - 任何 Redis 异常都不抛给上游（缓存层不能拖垮主流程）
    - 命中即返回；未命中由调用方决定是否走 admin-api
    """

    def _get_client(self) -> Optional[redis_async.Redis]:
        """从全局连接池借一个 Redis 客户端；未初始化时返回 None。"""
        pool = redis_module.redis_pool
        if pool is None:
            return None
        return redis_async.Redis(connection_pool=pool)

    @staticmethod
    def make_product_search_key(tenant_id: int, params: Optional[Dict[str, Any]]) -> str:
        return f"{KEY_PREFIX}product_search:{tenant_id}:{_hash_params(params)}"

    @staticmethod
    def make_category_tree_key(tenant_id: int) -> str:
        return f"{KEY_PREFIX}category_tree:{tenant_id}"

    async def _get_json(self, key: str) -> Optional[Dict[str, Any]]:
        client = self._get_client()
        if client is None:
            return None
        try:
            raw = await client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            logger.warning(f"[admin-api-cache] GET failed | key={key} error={e}")
            return None
        finally:
            try:
                await client.close()
            except Exception:
                pass

    async def _set_json(self, key: str, value: Dict[str, Any], ttl: int) -> bool:
        client = self._get_client()
        if client is None:
            return False
        try:
            payload = json.dumps(value, ensure_ascii=False, default=str)
            await client.set(key, payload, ex=ttl)
            return True
        except Exception as e:
            logger.warning(f"[admin-api-cache] SET failed | key={key} error={e}")
            return False
        finally:
            try:
                await client.close()
            except Exception:
                pass

    # ---------- product_search ----------

    async def get_product_search(
        self, tenant_id: int, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        key = self.make_product_search_key(tenant_id, params)
        cached = await self._get_json(key)
        if cached is not None:
            logger.info(f"[admin-api-cache] HIT product_search | tenant={tenant_id} key={key}")
        return cached

    async def set_product_search(
        self,
        tenant_id: int,
        params: Optional[Dict[str, Any]],
        response: Dict[str, Any],
    ) -> bool:
        key = self.make_product_search_key(tenant_id, params)
        return await self._set_json(key, response, TTL_PRODUCT_SEARCH)

    # ---------- category_tree ----------

    async def get_category_tree(self, tenant_id: int) -> Optional[Dict[str, Any]]:
        key = self.make_category_tree_key(tenant_id)
        cached = await self._get_json(key)
        if cached is not None:
            logger.info(f"[admin-api-cache] HIT category_tree | tenant={tenant_id} key={key}")
        return cached

    async def set_category_tree(self, tenant_id: int, response: Dict[str, Any]) -> bool:
        key = self.make_category_tree_key(tenant_id)
        return await self._set_json(key, response, TTL_CATEGORY_TREE)


_singleton: Optional[AdminApiCache] = None


def get_admin_api_cache() -> AdminApiCache:
    """获取全局 AdminApiCache 单例"""
    global _singleton
    if _singleton is None:
        _singleton = AdminApiCache()
    return _singleton
