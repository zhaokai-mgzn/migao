"""
AI 智能客服系统 - AI Agent 服务入口

架构决策说明：
================
关于 Agent 框架的选择：
- 原计划使用 Hermes Agent（Nous Research 推出的自进化 Agent 框架）
- 经调研，Hermes Agent 目前主要通过 GitHub 源码安装，非 PyPI 标准包
- 考虑到项目稳定性和开发效率，当前采用 LangChain Agent 作为替代方案
- LangChain 提供成熟的 Tool calling、Memory 管理和 Streaming 支持
- 与 MiniMax M3（OpenAI 兼容接口）集成
- 未来如需迁移到 Hermes Agent，可基于当前 Tool 抽象层进行替换
================
"""

from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import settings
from app.log_config import setup_logging
from app.api.routes import router as api_router
from app.middleware.logging_middleware import RequestLoggingMiddleware
from app.utils.database import init_db, close_db
from app.utils.redis_client import init_redis, close_redis

# 会话空闲自动关闭配置
SESSION_AUTO_CLOSE_MINUTES = 240    # 空闲超时分钟数（4 小时）
SESSION_CLEANUP_INTERVAL = 300      # 后台扫描间隔（秒）
SESSION_RETENTION_DAYS = 90         # 已关闭会话保留天数


async def _session_auto_close_loop():
    """后台循环：定期扫描并关闭空闲会话 + 每日清理过期已关闭会话"""
    from datetime import datetime
    from app.memory.session_memory import SessionMemory

    session_memory = SessionMemory()
    last_cleanup_date = None

    while True:
        try:
            await asyncio.sleep(SESSION_CLEANUP_INTERVAL)

            # 1. 关闭空闲会话
            count = await session_memory.close_idle_sessions(
                idle_minutes=SESSION_AUTO_CLOSE_MINUTES
            )
            if count > 0:
                logger.info(
                    f"[auto-close] Background task closed {count} idle sessions "
                    f"(idle > {SESSION_AUTO_CLOSE_MINUTES}min)"
                )

            # 2. 每天清理一次过期已关闭会话
            today = datetime.utcnow().date()
            if last_cleanup_date != today:
                deleted = await session_memory.cleanup_closed_sessions(
                    older_than_days=SESSION_RETENTION_DAYS
                )
                if deleted > 0:
                    logger.info(
                        f"[auto-cleanup] Removed {deleted} expired closed sessions "
                        f"(older than {SESSION_RETENTION_DAYS}d)"
                    )
                last_cleanup_date = today

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[auto-close] Background scan error (non-fatal): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Environment: {'development' if settings.DEBUG else 'production'}")

    # 初始化数据库连接
    try:
        await init_db()
        logger.info("Database connection initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        if not settings.DEBUG:
            raise

    # 初始化 Redis 连接
    try:
        await init_redis()
        logger.info("Redis connection initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Redis: {e}")
        if not settings.DEBUG:
            raise

    # Agent 采用懒加载策略，首次请求时初始化
    logger.info("AI Agent Service started successfully")

    # 启动后台会话自动关闭任务
    cleanup_task = asyncio.create_task(_session_auto_close_loop())

    yield

    # 停止后台任务
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    # 关闭时执行
    logger.info("Shutting down AI Agent Service")

    # 关闭 Redis 连接
    try:
        await close_redis()
        logger.info("Redis connection closed")
    except Exception as e:
        logger.error(f"Error closing Redis connection: {e}")

    # 关闭数据库连接
    try:
        await close_db()
        logger.info("Database connection closed")
    except Exception as e:
        logger.error(f"Error closing database connection: {e}")


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""

    # 初始化日志系统
    setup_logging(debug=settings.DEBUG)

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="AI 智能客服系统 - AI Agent 服务",
        lifespan=lifespan,
    )

    # CORS 中间件
    cors_origins = [o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
    if settings.DEBUG:
        dev_origins = [
            "http://localhost:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
        for origin in dev_origins:
            if origin not in cors_origins:
                cors_origins.append(origin)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Tenant-ID", "Accept", "Origin"],
    )
    logger.info(f"CORS allowed origins: {cors_origins}")

    # 请求追踪中间件（在 CORS 之后添加，先于 CORS 执行）
    app.add_middleware(RequestLoggingMiddleware)

    # 注册路由
    app.include_router(api_router, prefix=settings.API_PREFIX)

    # 健康检查
    @app.get("/health")
    async def health_check():
        return {
            "status": "healthy",
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
    )
