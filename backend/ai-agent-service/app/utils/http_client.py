"""
AI 智能客服系统 - HTTP Client 封装

提供调用 admin-api 的异步 HTTP 客户端，支持 Service Token 认证。
集成了 CircuitBreaker 熔断保护，用于防止下游服务雪崩。
"""

from typing import Optional, Dict, Any
import httpx
from loguru import logger

from app.config import settings


class _ApiBusinessError(Exception):
    """Internal: raised when admin API returns success=False in the response body.

    Carries the original response data so callers can still inspect the error details.
    """
    __slots__ = ("data",)

    def __init__(self, data: Dict[str, Any]) -> None:
        self.data = data
        error_info = data.get("error", {}) if isinstance(data, dict) else {}
        super().__init__(f"Admin API error: {error_info.get('message', 'Unknown')}")


class AdminApiClient:
    """调用 admin-api 的 HTTP 客户端
    
    封装了与 admin-api 的 HTTP 通信，自动添加认证头。
    
    使用示例：
        client = AdminApiClient()
        result = await client.get("/api/admin/products", params={"keyword": "窗帘"})
    """
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        service_token: Optional[str] = None,
        timeout: float = 25.0,
    ):
        """初始化 HTTP 客户端
        
        Args:
            base_url: admin-api 基础 URL，默认从配置读取
            service_token: Service Token，默认从配置读取
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url or settings.ADMIN_API_BASE_URL
        self.service_token = service_token or settings.SERVICE_TOKEN
        self.timeout = timeout
        
        # 创建异步 HTTP 客户端
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
            )
        return self._client
    
    def _get_headers(
        self,
        tenant_id: Optional[int] = None,
        user_id: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """构建请求头
        
        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            extra_headers: 额外的请求头
            
        Returns:
            Dict: 完整的请求头
        """
        headers = {}
        
        # Service Token 认证
        if self.service_token:
            headers["X-Service-Token"] = self.service_token
        
        # 多租户上下文
        if tenant_id:
            headers["X-Tenant-Id"] = str(tenant_id)
        if user_id:
            headers["X-User-Id"] = user_id
        
        # 合并额外请求头
        if extra_headers:
            headers.update(extra_headers)
        
        return headers
    
    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[int] = None,
        user_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Send an HTTP request with circuit breaker protection.

        All public HTTP methods (get/post/put/patch/delete) delegate to this method.
        The circuit breaker wraps the actual httpx call so that:

        - HTTP 2xx + JSON body ``success=True`` → breaker.on_success()
        - HTTP error OR body ``success=False`` → breaker.on_failure()
        - Network/timeout errors → breaker.on_failure()
        - Circuit OPEN / HALF_OPEN probe limit reached → returns a fallback dict

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE).
            path: API path (without base_url).
            params: URL query parameters (GET only).
            data: Form data (POST only).
            json_data: JSON body (POST/PUT/PATCH).
            tenant_id: Tenant ID for X-Tenant-Id header.
            user_id: User ID for X-User-Id header.
            headers: Extra request headers.

        Returns:
            Dict with ``success``, ``error``, and ``data`` keys.

        Raises:
            httpx.HTTPStatusError: Non-2xx HTTP responses (after breaker counts failure).
            Exception: Network / timeout / unexpected errors (after breaker counts failure).
        """
        # Lazy import to avoid circular dependency:
        # http_client → app.core.circuit_breaker → app.core.__init__ → app.tools → http_client
        from app.core.circuit_breaker import get_breaker, CircuitBreakerOpenError  # noqa: E402

        breaker = get_breaker(f"admin_api:{method}:{path}")

        async def _do_call() -> Dict[str, Any]:
            client = await self._get_client()
            request_headers = self._get_headers(tenant_id, user_id, headers)

            logger.debug(f"{method} {path}")
            response = await client.request(
                method=method,
                url=path,
                params=params,
                data=data,
                json=json_data,
                headers=request_headers,
            )
            # 4xx = 客户端/业务错误（404/422/400等），不是服务故障，不应触发熔断
            if 400 <= response.status_code < 500:
                result: Dict[str, Any] = response.json()
                return {
                    "success": False,
                    "error": result.get("error", {}),
                    "data": None,
                }
            response.raise_for_status()
            result: Dict[str, Any] = response.json()

            # Business-level failure → raise so the breaker counts it as a failure.
            if isinstance(result, dict) and result.get("success") is False:
                raise _ApiBusinessError(result)

            return result

        try:
            return await breaker.call(_do_call)
        except CircuitBreakerOpenError:
            logger.warning(
                f"[CircuitBreaker] OPEN for {method} {path}, "
                f"state={breaker.state.value} failures={breaker.failure_count}"
            )
            return {
                "success": False,
                "error": {"code": "CIRCUIT_OPEN", "message": "服务暂时不可用"},
                "data": None,
            }
        except _ApiBusinessError as e:
            # Return the original error response so callers can inspect it.
            return e.data
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error {e.response.status_code} for {method} {path}: {e.response.text}"
            )
            raise
        except Exception as e:
            logger.error(f"Error in {method} {path}: {e}")
            raise

    async def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[int] = None,
        user_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """发送 GET 请求"""
        return await self._request(
            "GET", path, params=params,
            tenant_id=tenant_id, user_id=user_id, headers=headers,
        )

    async def post(
        self,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[int] = None,
        user_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """发送 POST 请求"""
        return await self._request(
            "POST", path, data=data, json_data=json_data,
            tenant_id=tenant_id, user_id=user_id, headers=headers,
        )

    async def put(
        self,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[int] = None,
        user_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """发送 PUT 请求"""
        return await self._request(
            "PUT", path, json_data=json_data,
            tenant_id=tenant_id, user_id=user_id, headers=headers,
        )

    async def patch(
        self,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[int] = None,
        user_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """发送 PATCH 请求"""
        return await self._request(
            "PATCH", path, json_data=json_data,
            tenant_id=tenant_id, user_id=user_id, headers=headers,
        )

    async def delete(
        self,
        path: str,
        tenant_id: Optional[int] = None,
        user_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """发送 DELETE 请求"""
        return await self._request(
            "DELETE", path,
            tenant_id=tenant_id, user_id=user_id, headers=headers,
        )
    
    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.debug("AdminApiClient closed")
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()


# 全局客户端实例（单例模式）
_admin_api_client: Optional[AdminApiClient] = None


def get_admin_api_client() -> AdminApiClient:
    """获取全局 AdminApiClient 实例
    
    Returns:
        AdminApiClient: HTTP 客户端实例
    """
    global _admin_api_client
    if _admin_api_client is None:
        _admin_api_client = AdminApiClient()
    return _admin_api_client


def reset_admin_api_client():
    """重置全局客户端实例（用于测试）"""
    global _admin_api_client
    _admin_api_client = None
