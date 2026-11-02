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
import time
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
SESSION_AUTO_CLOSE_MINUTES = 720    # 空闲超时分钟数（12 小时；用户裁定 2026-10-30，issue #8182）
SESSION_CLEANUP_INTERVAL = 300      # 后台扫描间隔（秒）
SESSION_RETENTION_DAYS = 90         # 已关闭会话保留天数
SESSION_STARTUP_GRACE_S = 600       # 启动宽限期（秒）：进程启动后 N 秒内不执行关闭扫描（issue #2915）


async def _session_auto_close_loop():
    """后台循环：定期扫描并关闭空闲会话 + 每日清理过期已关闭会话（经 SessionService）

    启动宽限期（issue #2915）：进程刚启动（部署/重启）时不立即扫描关闭——
    避免部署过渡期把积压/时间戳未修正的会话一次性批量误杀（线上 89 会话
    在 #2904 部署后首次扫描被一批关闭的教训）。
    """
    from datetime import datetime, timezone
    from app.memory.session_service import SessionService

    session_service = SessionService()
    last_cleanup_date = None
    started_at = time.monotonic()

    while True:
        try:
            await asyncio.sleep(SESSION_CLEANUP_INTERVAL)

            if time.monotonic() - started_at < SESSION_STARTUP_GRACE_S:
                continue

            # 1. 关闭空闲会话（active → closed/expired 语义由状态机约束）
            count = await session_service.expire_idle(
                idle_minutes=SESSION_AUTO_CLOSE_MINUTES
            )
            if count > 0:
                logger.info(
                    f"[auto-close] Background task closed {count} idle sessions "
                    f"(idle > {SESSION_AUTO_CLOSE_MINUTES}min)"
                )

            # 2. 每天清理一次过期已关闭会话
            today = datetime.now(timezone.utc).date()
            if last_cleanup_date != today:
                deleted = await session_service.purge(
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
        # ⚠️ 逐项白名单，与 admin-api `SecurityConfig.setAllowedHeaders` 同口径（issue #6479）：
        # 两个 H5 端（bmini `utils/request.ts`、mini-app `utils/request.ts`）**每个**请求都带
        # `X-Client-Type`，缺它 ⇒ 跨域形态下 `/api/chat/**` 与 `/api/chat/quick-actions` 等
        # 全部请求被预检拦掉（本地联调实测 `net::ERR_FAILED`）。
        # 判据 = tests/unit_ci_workflows/test_cors_custom_headers_contract.py（漏一个当场具名红）。
        allow_headers=[
            "Authorization", "Content-Type", "X-Request-ID", "X-Tenant-ID", "Accept", "Origin",
            "X-Client-Type", "X-Client-Request-Id", "X-Worker-Session-Id",
        ],
    )
    logger.info(f"CORS allowed origins: {cors_origins}")

    # 请求追踪中间件（在 CORS 之后添加，先于 CORS 执行）
    app.add_middleware(RequestLoggingMiddleware)

    # 注册路由
    app.include_router(api_router, prefix=settings.API_PREFIX)

    # 生图失败（503）：响应体 `{"code", "detail"}` 并存（issue #7552）。
    # 为什么不直接 raise HTTPException：默认处理器只透传 detail，会把机器可读失败码丢掉，
    # admin-api 就只能从中文 detail 里拆字符串猜成因（「模型不支持」被劝「稍后重试」）。
    from app.api.internal import ImageGenerationFailure

    @app.exception_handler(ImageGenerationFailure)
    async def _image_generation_failure(request, exc: ImageGenerationFailure):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "detail": exc.detail},
        )

    # 健康检查
    @app.get("/health")
    async def health_check():
        return {
            "status": "healthy",
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
        }

    # Readiness：探活 Redis + DB（供 compose healthcheck / 编排使用，fail-closed）
    @app.get("/ready")
    async def ready_check():
        from fastapi.responses import JSONResponse
        from app.utils.health import check_readiness
        if not await check_readiness():
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "service": settings.APP_NAME},
            )
        return {"status": "ready", "service": settings.APP_NAME}

    # 构建身份探针（issue #8203；审计 P1-01：改前 `ai-api.migaozn.com/api/version|/version|/build-info`
    # **全 404** ⇒ ai-agent 线上「跑的是哪个 commit」不可判定、发布漂移不可发现）。
    #
    # 与 admin-api `GET /api/version` **同口径**（三个字段：app / sha / builtAt），
    # 值全部来自**构建期注入**（`Settings.MIGAO_BUILD_SHA` / `MIGAO_BUILT_AT` ← Dockerfile 的
    # `ARG`+`ENV` ← `deploy.sh` 的 `--build-arg`）。
    #
    # 三态语义（消费方必须照此判，「取不到」不得当「一致」）：
    #   · sha 非空且与期望一致 ⇒ 线上就是这次构建；
    #   · sha 非空但不一致     ⇒ 判红（这正是本端点存在的理由）；
    #   · sha 为空             ⇒ **探不到**（老镜像 / 非部署形态启动），不得判绿也不得判红。
    #
    # ⚠️ 挂在**两个路径**上有意：`/version`（本服务原有 `/health` `/ready` 的邻居，直连容器/回环用）
    #   与 `/api/version`（与 admin-api **同名**，运维/探针只有一条命名口径）。
    @app.get("/version")
    @app.get("/api/version")
    async def version_probe():
        return {
            "app": settings.APP_NAME,
            "sha": (settings.MIGAO_BUILD_SHA or "").strip(),
            "builtAt": (settings.MIGAO_BUILT_AT or "").strip(),
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
