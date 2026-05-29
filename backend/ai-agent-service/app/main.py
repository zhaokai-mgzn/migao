"""
AI 智能客服系统 - AI Agent 服务入口

架构决策说明：
================
关于 Agent 框架的选择：
- 原计划使用 Hermes Agent（Nous Research 推出的自进化 Agent 框架）
- 经调研，Hermes Agent 目前主要通过 GitHub 源码安装，非 PyPI 标准包
- 考虑到项目稳定性和开发效率，当前采用 LangChain Agent 作为替代方案
- LangChain 提供成熟的 Tool calling、Memory 管理和 Streaming 支持
- 与阿里云百炼（DashScope）集成良好
- 未来如需迁移到 Hermes Agent，可基于当前 Tool 抽象层进行替换
================
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import settings
from app.log_config import setup_logging
from app.api.routes import router as api_router
from app.middleware.logging_middleware import RequestLoggingMiddleware
from app.utils.database import init_db, close_db
from app.utils.redis_client import init_redis, close_redis


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
        # 开发环境下允许继续启动，方便调试
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
    
    # 初始化 RAG 组件（DashVector + Embedding）
    rag_pipeline = None
    try:
        from app.rag.vector_store import get_vector_store
        from app.rag.pipeline import get_rag_pipeline
        
        vector_store = await get_vector_store()
        health = await vector_store.health_check()
        if health.get("available"):
            logger.info(f"DashVector initialized: {health}")
        else:
            logger.warning(f"DashVector not fully available: {health}")
        
        rag_pipeline = await get_rag_pipeline()
        logger.info("RAG pipeline initialized")
    except Exception as e:
        logger.warning(f"RAG initialization failed (non-fatal, graceful degradation): {e}")
    
    # Agent 采用懒加载策略，首次请求时初始化
    logger.info("AI Agent Service started successfully")
    
    yield
    
    # 关闭时执行
    logger.info("Shutting down AI Agent Service")
    
    # 关闭 RAG 连接
    try:
        from app.rag.vector_store import get_vector_store, reset_vector_store
        from app.rag.pipeline import reset_rag_pipeline
        from app.rag.retriever import reset_hybrid_retriever
        from app.rag.bm25_retriever import reset_bm25_retriever
        
        vs = await get_vector_store()
        await vs.close()
        reset_vector_store()
        reset_hybrid_retriever()
        reset_bm25_retriever()
        reset_rag_pipeline()
        logger.info("RAG connections closed")
    except Exception as e:
        logger.error(f"Error closing RAG connections: {e}")
    
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
        # 开发模式下额外允许常见本地开发端口（Next.js: 3000/3001，Vite: 5173）
        # 即便 .env 中 CORS_ALLOWED_ORIGINS 配置不全，也保证本地前端可访问
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
