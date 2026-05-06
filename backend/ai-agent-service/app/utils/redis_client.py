"""
AI 智能客服系统 - Redis 连接模块

使用 redis.asyncio 实现异步 Redis 操作
用于：
- 会话状态缓存
- 消息队列
- 限流计数
- JWT 黑名单
"""

from typing import Optional, AsyncGenerator
import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool
from loguru import logger

from app.config import settings

# Redis 连接池（全局单例）
redis_pool: Optional[ConnectionPool] = None


async def init_redis() -> None:
    """
    初始化 Redis 连接池
    
    在应用启动时调用
    """
    global redis_pool
    
    try:
        redis_pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,  # 自动解码响应为字符串
            max_connections=50,     # 最大连接数
        )
        
        # 测试连接
        client = redis.Redis(connection_pool=redis_pool)
        await client.ping()
        await client.close()
        
        # 从 URL 中提取 host/port 用于日志
        redis_url = settings.REDIS_URL
        logger.info(f"[redis] Connected to Redis | url={redis_url}")
    except Exception as e:
        logger.error(f"[redis] Connection failed | error={e}", exc_info=True)
        raise


async def close_redis() -> None:
    """
    关闭 Redis 连接池
    
    在应用关闭时调用
    """
    global redis_pool
    
    if redis_pool:
        await redis_pool.disconnect()
        redis_pool = None
        logger.info("Redis connection pool closed")


async def get_redis() -> AsyncGenerator[redis.Redis, None]:
    """
    获取 Redis 客户端的依赖注入函数
    
    使用方式：
        @router.get("/cache")
        async def get_cache(redis_client: redis.Redis = Depends(get_redis)):
            value = await redis_client.get("key")
            return {"value": value}
    
    Yields:
        redis.Redis: Redis 异步客户端
    """
    if not redis_pool:
        raise RuntimeError("Redis connection pool is not initialized")
    
    client = redis.Redis(connection_pool=redis_pool)
    try:
        yield client
    finally:
        await client.close()


class RedisClient:
    """
    Redis 客户端封装类
    
    提供常用的 Redis 操作方法，支持异步上下文管理
    """
    
    def __init__(self):
        self._client: Optional[redis.Redis] = None
    
    async def __aenter__(self) -> redis.Redis:
        if not redis_pool:
            raise RuntimeError("Redis connection pool is not initialized")
        self._client = redis.Redis(connection_pool=redis_pool)
        return self._client
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.close()
            self._client = None
    
    # 常用键前缀（用于命名空间隔离）
    KEY_PREFIX = {
        "session": "session:",
        "message": "msg:",
        "rate_limit": "ratelimit:",
        "jwt_blacklist": "jwt:blacklist:",
        "user_status": "user:status:",
        "cache": "cache:",
    }
    
    async def get(self, key: str) -> Optional[str]:
        """GET 操作封装"""
        if not redis_pool:
            raise RuntimeError("Redis connection pool is not initialized")
        client = redis.Redis(connection_pool=redis_pool)
        try:
            logger.debug(f"[redis] GET key={key}")
            value = await client.get(key)
            return value
        except Exception as e:
            logger.error(f"[redis] Operation failed | op=GET key={key} error={e}")
            raise
        finally:
            await client.close()
    
    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """SET 操作封装"""
        if not redis_pool:
            raise RuntimeError("Redis connection pool is not initialized")
        client = redis.Redis(connection_pool=redis_pool)
        try:
            logger.debug(f"[redis] SET key={key} ttl={ttl}")
            if ttl:
                await client.set(key, value, ex=ttl)
            else:
                await client.set(key, value)
            return True
        except Exception as e:
            logger.error(f"[redis] Operation failed | op=SET key={key} error={e}")
            raise
        finally:
            await client.close()
    
    async def delete(self, key: str) -> bool:
        """DELETE 操作封装"""
        if not redis_pool:
            raise RuntimeError("Redis connection pool is not initialized")
        client = redis.Redis(connection_pool=redis_pool)
        try:
            logger.debug(f"[redis] DEL key={key}")
            await client.delete(key)
            return True
        except Exception as e:
            logger.error(f"[redis] Operation failed | op=DEL key={key} error={e}")
            raise
        finally:
            await client.close()
    
    @classmethod
    def make_key(cls, prefix: str, *parts: str) -> str:
        """
        生成带前缀的 Redis 键
        
        Args:
            prefix: 键前缀类型
            *parts: 键的组成部分
        
        Returns:
            完整的 Redis 键
        
        Example:
            >>> RedisClient.make_key("session", "tenant1", "user123")
            "session:tenant1:user123"
        """
        prefix_value = cls.KEY_PREFIX.get(prefix, prefix)
        return ":".join([prefix_value] + list(parts))
