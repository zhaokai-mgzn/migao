"""Readiness 探活 — Redis + DB 可用性检查（供 compose healthcheck / 编排使用，fail-closed）

- 成功：Redis ping 通过 + DB SELECT 1 通过 → True
- 任一失败（含 Redis 连接池未初始化）→ False
"""
import redis.asyncio as redis
from loguru import logger
from sqlalchemy import text

from app.utils.database import AsyncSessionLocal
from app.utils.redis_client import redis_pool


async def check_readiness() -> bool:
    """探活 DB 与 Redis。全部可用返回 True，否则 False（不抛异常）。"""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        if redis_pool is None:
            logger.warning("[ready] redis pool not initialized")
            return False
        client = redis.Redis(connection_pool=redis_pool)
        try:
            await client.ping()
        finally:
            await client.close()
        return True
    except Exception as e:
        logger.warning(f"[ready] dependency check failed: {e}")
        return False
