# app/middleware/logging_middleware.py
import uuid
import time
import contextvars
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from loguru import logger

# 全局 request_id 上下文变量
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar('request_id', default='')


def get_request_id() -> str:
    """获取当前请求的 request_id"""
    return request_id_var.get('')


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """请求日志和追踪 ID 中间件"""

    # 不需要记录详细日志的路径
    SKIP_PATHS = frozenset({'/health', '/healthz', '/ready', '/favicon.ico'})

    async def dispatch(self, request: Request, call_next) -> Response:
        # 从请求头获取或生成 request_id
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        request_id_var.set(req_id)

        path = request.url.path
        method = request.method

        # 跳过健康检查等路径
        if path in self.SKIP_PATHS:
            return await call_next(request)

        client_host = request.client.host if request.client else "unknown"

        logger.info(
            f"[{req_id}] {method} {path} started | client={client_host}"
        )

        start_time = time.time()
        try:
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000

            logger.info(
                f"[{req_id}] {method} {path} completed | status={response.status_code} | duration={duration_ms:.1f}ms"
            )

            # 将 request_id 写入响应头
            response.headers["X-Request-ID"] = req_id
            return response
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                f"[{req_id}] {method} {path} failed | duration={duration_ms:.1f}ms | error={type(e).__name__}: {e}"
            )
            raise
