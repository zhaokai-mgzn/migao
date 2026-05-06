"""
AI 智能客服系统 - HTTP Client 封装

提供调用 admin-api 的异步 HTTP 客户端，支持 Service Token 认证。
"""

from typing import Optional, Dict, Any
import httpx
from loguru import logger

from app.config import settings


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
    
    async def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[int] = None,
        user_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """发送 GET 请求
        
        Args:
            path: API 路径（不含 base_url）
            params: URL 查询参数
            tenant_id: 租户 ID
            user_id: 用户 ID
            headers: 额外请求头
            
        Returns:
            Dict: 响应数据
            
        Raises:
            httpx.HTTPError: HTTP 请求错误
        """
        client = await self._get_client()
        request_headers = self._get_headers(tenant_id, user_id, headers)
        
        try:
            logger.debug(f"GET {path} params={params}")
            response = await client.get(
                path,
                params=params,
                headers=request_headers,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} for GET {path}: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error in GET {path}: {e}")
            raise
    
    async def post(
        self,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[int] = None,
        user_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """发送 POST 请求
        
        Args:
            path: API 路径
            data: Form 数据
            json_data: JSON 数据
            tenant_id: 租户 ID
            user_id: 用户 ID
            headers: 额外请求头
            
        Returns:
            Dict: 响应数据
        """
        client = await self._get_client()
        request_headers = self._get_headers(tenant_id, user_id, headers)
        
        try:
            logger.debug(f"POST {path} json={json_data}")
            response = await client.post(
                path,
                data=data,
                json=json_data,
                headers=request_headers,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} for POST {path}: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error in POST {path}: {e}")
            raise
    
    async def put(
        self,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[int] = None,
        user_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """发送 PUT 请求
        
        Args:
            path: API 路径
            json_data: JSON 数据
            tenant_id: 租户 ID
            user_id: 用户 ID
            headers: 额外请求头
            
        Returns:
            Dict: 响应数据
        """
        client = await self._get_client()
        request_headers = self._get_headers(tenant_id, user_id, headers)
        
        try:
            logger.debug(f"PUT {path} json={json_data}")
            response = await client.put(
                path,
                json=json_data,
                headers=request_headers,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} for PUT {path}: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error in PUT {path}: {e}")
            raise
    
    async def patch(
        self,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[int] = None,
        user_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """发送 PATCH 请求
        
        Args:
            path: API 路径
            json_data: JSON 数据
            tenant_id: 租户 ID
            user_id: 用户 ID
            headers: 额外请求头
            
        Returns:
            Dict: 响应数据
        """
        client = await self._get_client()
        request_headers = self._get_headers(tenant_id, user_id, headers)
        
        try:
            logger.debug(f"PATCH {path} json={json_data}")
            response = await client.patch(
                path,
                json=json_data,
                headers=request_headers,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} for PATCH {path}: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error in PATCH {path}: {e}")
            raise
    
    async def delete(
        self,
        path: str,
        tenant_id: Optional[int] = None,
        user_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """发送 DELETE 请求
        
        Args:
            path: API 路径
            tenant_id: 租户 ID
            user_id: 用户 ID
            headers: 额外请求头
            
        Returns:
            Dict: 响应数据
        """
        client = await self._get_client()
        request_headers = self._get_headers(tenant_id, user_id, headers)
        
        try:
            logger.debug(f"DELETE {path}")
            response = await client.delete(
                path,
                headers=request_headers,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} for DELETE {path}: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error in DELETE {path}: {e}")
            raise
    
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
