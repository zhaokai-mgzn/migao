"""
跨服务租户信息传递测试

验证 ai-agent-service 调用 admin-api 时租户信息正确传递，包括：
1. HTTP 客户端层：请求头中包含正确的 tenant_id / service token
2. Tool 执行层：Tool 从 ToolContext 取出 tenant_id 传递给 HTTP 客户端
3. Service Token 认证与租户 header 传播
"""

import time
import pytest
from unittest.mock import patch, AsyncMock, MagicMock, call

import httpx

from app.tools.base import ToolContext, ToolResult
from app.tools.product_search import ProductSearchTool
from app.tools.product_detail import ProductDetailTool
from app.utils.http_client import AdminApiClient


# ========== 公用常量 ==========

TENANT_A = 1
TENANT_B = 2
USER_A = "user_tenant_a"
USER_B = "user_tenant_b"
SERVICE_TOKEN = "test-service-token"


@pytest.fixture
def ctx_tenant_a():
    return ToolContext(tenant_id=TENANT_A, user_id=USER_A, session_id="sess_a", role="customer")


@pytest.fixture
def ctx_tenant_b():
    return ToolContext(tenant_id=TENANT_B, user_id=USER_B, session_id="sess_b", role="customer")


# ============================================================
# 第一部分：HTTP 客户端租户信息传递
# ============================================================


class TestHttpClientTenantHeaders:
    """验证 AdminApiClient 在请求中正确携带租户信息"""

    @pytest.mark.unit
    def test_get_headers_includes_tenant_id(self):
        """_get_headers 返回的 headers 中包含 X-Tenant-Id"""
        client = AdminApiClient(
            base_url="http://localhost:8080",
            service_token=SERVICE_TOKEN,
        )
        headers = client._get_headers(tenant_id=TENANT_A, user_id=USER_A)

        assert headers["X-Tenant-Id"] == str(TENANT_A)
        assert headers["X-User-Id"] == USER_A
        assert headers["X-Service-Token"] == SERVICE_TOKEN

    @pytest.mark.unit
    def test_get_headers_without_tenant_id(self):
        """未传 tenant_id 时 headers 中不包含 X-Tenant-Id"""
        client = AdminApiClient(
            base_url="http://localhost:8080",
            service_token=SERVICE_TOKEN,
        )
        headers = client._get_headers(tenant_id=None, user_id=None)

        assert "X-Tenant-Id" not in headers
        assert "X-User-Id" not in headers
        # Service Token 始终存在
        assert headers["X-Service-Token"] == SERVICE_TOKEN

    @pytest.mark.unit
    def test_get_headers_with_different_tenants(self):
        """不同租户的请求携带各自的 tenant_id"""
        client = AdminApiClient(
            base_url="http://localhost:8080",
            service_token=SERVICE_TOKEN,
        )
        headers_a = client._get_headers(tenant_id=TENANT_A, user_id=USER_A)
        headers_b = client._get_headers(tenant_id=TENANT_B, user_id=USER_B)

        assert headers_a["X-Tenant-Id"] == str(TENANT_A)
        assert headers_b["X-Tenant-Id"] == str(TENANT_B)
        assert headers_a["X-Tenant-Id"] != headers_b["X-Tenant-Id"]

    @pytest.mark.unit
    async def test_http_client_includes_tenant_id_in_request(self):
        """GET 请求实际发出时包含正确的 tenant_id header"""
        client = AdminApiClient(
            base_url="http://localhost:8080",
            service_token=SERVICE_TOKEN,
        )

        # Mock 底层 httpx.AsyncClient
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True, "data": {}}
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client = AsyncMock()
        mock_httpx_client.request = AsyncMock(return_value=mock_response)
        mock_httpx_client.is_closed = False
        client._client = mock_httpx_client

        await client.get("/api/admin/products", tenant_id=TENANT_A, user_id=USER_A)

        # 验证请求 headers 包含租户信息
        call_kwargs = mock_httpx_client.request.call_args
        sent_headers = call_kwargs.kwargs.get("headers", {})
        assert sent_headers["X-Tenant-Id"] == str(TENANT_A)
        assert sent_headers["X-Service-Token"] == SERVICE_TOKEN

    @pytest.mark.unit
    async def test_http_client_with_different_tenants(self):
        """不同租户的 HTTP 请求携带各自正确的 tenant_id"""
        client = AdminApiClient(
            base_url="http://localhost:8080",
            service_token=SERVICE_TOKEN,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True, "data": {}}
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client = AsyncMock()
        mock_httpx_client.request = AsyncMock(return_value=mock_response)
        mock_httpx_client.is_closed = False
        client._client = mock_httpx_client

        # 租户 A 请求
        await client.get("/api/admin/products", tenant_id=TENANT_A)
        headers_a = mock_httpx_client.request.call_args_list[0].kwargs["headers"]

        # 租户 B 请求
        await client.get("/api/admin/products", tenant_id=TENANT_B)
        headers_b = mock_httpx_client.request.call_args_list[1].kwargs["headers"]

        assert headers_a["X-Tenant-Id"] == str(TENANT_A)
        assert headers_b["X-Tenant-Id"] == str(TENANT_B)

    @pytest.mark.unit
    async def test_http_client_post_includes_tenant_id(self):
        """POST 请求中同样包含 tenant_id header"""
        client = AdminApiClient(
            base_url="http://localhost:8080",
            service_token=SERVICE_TOKEN,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True, "data": {}}
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client = AsyncMock()
        mock_httpx_client.request = AsyncMock(return_value=mock_response)
        mock_httpx_client.is_closed = False
        client._client = mock_httpx_client

        await client.post(
            "/api/admin/orders",
            json_data={"item": "test"},
            tenant_id=TENANT_A,
            user_id=USER_A,
        )

        sent_headers = mock_httpx_client.request.call_args.kwargs["headers"]
        assert sent_headers["X-Tenant-Id"] == str(TENANT_A)
        assert sent_headers["X-User-Id"] == USER_A


# ============================================================
# 第二部分：Tool 执行租户隔离
# ============================================================


class TestProductSearchToolTenantContext:
    """ProductSearch Tool 正确传递租户上下文"""

    @pytest.fixture
    def tool(self):
        return ProductSearchTool()

    @pytest.mark.integration
    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_tool_passes_tenant_context(
        self, mock_get_client, tool, ctx_tenant_a
    ):
        """ProductSearch 调用 HTTP 客户端时传递了正确的 tenant_id"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "records": [
                    {"id": "p1", "name": "窗帘A", "tenantId": TENANT_A, "price": 100},
                ],
                "total": 1,
            },
        })
        mock_get_client.return_value = mock_client

        await tool.execute(context=ctx_tenant_a, keyword="窗帘")

        # 验证 HTTP 客户端被调用时传递了正确的 tenant_id
        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args
        assert call_kwargs.kwargs.get("tenant_id") == TENANT_A
        assert call_kwargs.kwargs.get("user_id") == USER_A

    @pytest.mark.integration
    @patch("app.tools.product_search.get_admin_api_client")
    async def test_product_search_different_tenants_pass_own_id(
        self, mock_get_client, tool, ctx_tenant_a, ctx_tenant_b
    ):
        """不同租户调用 ProductSearch 时各自传递自己的 tenant_id"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"records": [], "total": 0},
        })
        mock_get_client.return_value = mock_client

        await tool.execute(context=ctx_tenant_a, keyword="窗帘")
        await tool.execute(context=ctx_tenant_b, keyword="窗帘")

        calls = mock_client.get.call_args_list
        assert calls[0].kwargs["tenant_id"] == TENANT_A
        assert calls[1].kwargs["tenant_id"] == TENANT_B

    @pytest.mark.integration
    @patch("app.tools.product_search.get_admin_api_client")
    async def test_tool_execution_with_wrong_tenant_returns_empty(
        self, mock_get_client, tool, ctx_tenant_a
    ):
        """admin-api 返回的数据全属于其他租户时，过滤后结果为空"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "records": [
                    {"id": "p1", "name": "其他租户商品", "tenantId": TENANT_B, "price": 200},
                    {"id": "p2", "name": "另一个租户商品", "tenantId": 999, "price": 300},
                ],
                "total": 2,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=ctx_tenant_a, keyword="商品")

        assert result.success is True
        assert result.data["products"] == []
        assert result.data["total"] == 0


class TestProductDetailToolTenantContext:
    """ProductDetail Tool 正确传递租户上下文"""

    @pytest.fixture
    def tool(self):
        return ProductDetailTool()

    @pytest.mark.integration
    @patch("app.tools.product_detail.get_admin_api_client")
    async def test_product_detail_tool_passes_tenant_context(
        self, mock_get_client, tool, ctx_tenant_a
    ):
        """ProductDetail 调用 HTTP 客户端时传递了正确的 tenant_id"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "p1",
                "name": "测试商品",
                "tenantId": TENANT_A,
                "price": 299,
            },
        })
        mock_get_client.return_value = mock_client

        await tool.execute(context=ctx_tenant_a, product_id="p1")

        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args
        assert call_kwargs.kwargs.get("tenant_id") == TENANT_A
        assert call_kwargs.kwargs.get("user_id") == USER_A

    @pytest.mark.integration
    @patch("app.tools.product_detail.get_admin_api_client")
    async def test_product_detail_cross_tenant_data_rejected(
        self, mock_get_client, tool, ctx_tenant_a
    ):
        """ProductDetail 返回其他租户数据时被拒绝"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "p_other",
                "name": "他人商品",
                "tenantId": TENANT_B,
                "price": 999,
            },
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=ctx_tenant_a, product_id="p_other")

        assert result.success is False
        assert result.error == "商品不存在"


class TestToolContextTenantIdConsistency:
    """ToolContext 的 tenant_id 与 JWT claims 一致性"""

    @pytest.mark.unit
    def test_tool_context_tenant_id_matches_jwt_claim(self):
        """ToolContext 的 tenant_id 应与构造时传入的值一致（模拟 JWT 提取后传递）"""
        jwt_tenant_id = 42
        jwt_user_id = "user_from_jwt"

        # 模拟 chat.py 中从 UserIdentity 构建 ToolContext 的过程
        context = ToolContext(
            tenant_id=jwt_tenant_id,
            user_id=jwt_user_id,
            session_id="sess_jwt",
            role="customer",
        )

        assert context.tenant_id == jwt_tenant_id
        assert context.user_id == jwt_user_id

    @pytest.mark.unit
    def test_tool_context_tenant_id_is_int(self):
        """ToolContext 的 tenant_id 必须为 int 类型"""
        context = ToolContext(
            tenant_id=1,
            user_id="u1",
            session_id="s1",
            role="customer",
        )
        assert isinstance(context.tenant_id, int)


# ============================================================
# 第三部分：Service Token 认证与租户传递
# ============================================================


class TestInternalApiServiceToken:
    """内部 API 需要 Service Token 认证"""

    @pytest.mark.integration
    async def test_internal_api_requires_service_token(self):
        """未携带 Service Token 调用内部 API 应被拒绝"""
        from fastapi import HTTPException
        from app.utils.auth import verify_service_token

        with pytest.raises(HTTPException) as exc_info:
            await verify_service_token(x_service_token=None)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["error"]["code"] == "AUTH_REQUIRED"

    @pytest.mark.integration
    @patch("app.utils.auth.settings")
    async def test_invalid_service_token_rejected(self, mock_settings):
        """无效的 Service Token 应被拒绝"""
        from fastapi import HTTPException
        from app.utils.auth import verify_service_token

        mock_settings.SERVICE_TOKEN = "correct-token"

        with pytest.raises(HTTPException) as exc_info:
            await verify_service_token(x_service_token="wrong-token")

        assert exc_info.value.status_code == 401

    @pytest.mark.integration
    @patch("app.utils.auth.settings")
    async def test_valid_service_token_accepted(self, mock_settings):
        """正确的 Service Token 应通过验证"""
        from app.utils.auth import verify_service_token

        mock_settings.SERVICE_TOKEN = SERVICE_TOKEN

        result = await verify_service_token(x_service_token=SERVICE_TOKEN)
        assert result is True


class TestInternalApiTenantHeaderPropagation:
    """内部 API 调用时租户 header 传播"""

    @pytest.mark.integration
    async def test_internal_api_tenant_header_propagation(self):
        """Tool 执行请求中的 tenant_id 正确传递到 ToolContext"""
        from app.api.internal import ToolExecuteRequest

        request = ToolExecuteRequest(
            tool_name="product_search",
            params={"keyword": "窗帘"},
            tenant_id=TENANT_A,
            user_id=USER_A,
        )

        # 验证请求模型正确携带 tenant_id
        assert request.tenant_id == TENANT_A
        assert request.user_id == USER_A

    @pytest.mark.integration
    @patch("app.api.internal.get_tool_registry")
    @patch("app.api.internal.verify_service_token", return_value=True)
    async def test_execute_tool_builds_correct_context(
        self, mock_auth, mock_registry_fn
    ):
        """execute_tool 端点从请求中正确构建 ToolContext"""
        from app.api.internal import execute_tool, ToolExecuteRequest

        mock_registry = MagicMock()
        mock_registry.has_tool.return_value = True

        mock_result = ToolResult(success=True, data={"products": []}, message="ok")
        mock_registry.execute_tool = AsyncMock(return_value=mock_result)
        mock_registry_fn.return_value = mock_registry

        request = ToolExecuteRequest(
            tool_name="product_search",
            params={"keyword": "窗帘"},
            tenant_id=TENANT_A,
            user_id=USER_A,
            session_id="sess_internal",
        )

        result = await execute_tool(request=request, authorized=True)

        # 验证 registry.execute_tool 被调用时传入了正确的 ToolContext
        mock_registry.execute_tool.assert_called_once()
        call_args = mock_registry.execute_tool.call_args
        context_arg = call_args.args[1]  # 第二个位置参数是 context
        assert isinstance(context_arg, ToolContext)
        assert context_arg.tenant_id == TENANT_A
        assert context_arg.user_id == USER_A
        assert context_arg.session_id == "sess_internal"
        assert context_arg.role == "admin"  # 内部调用使用 admin 角色

    @pytest.mark.integration
    @patch("app.api.internal.get_tool_registry")
    @patch("app.api.internal.verify_service_token", return_value=True)
    async def test_internal_api_cross_tenant_context_isolation(
        self, mock_auth, mock_registry_fn
    ):
        """不同租户的内部 API 调用构建不同的 ToolContext"""
        from app.api.internal import execute_tool, ToolExecuteRequest

        mock_registry = MagicMock()
        mock_registry.has_tool.return_value = True
        mock_result = ToolResult(success=True, data={}, message="ok")
        mock_registry.execute_tool = AsyncMock(return_value=mock_result)
        mock_registry_fn.return_value = mock_registry

        # 租户 A 的请求
        req_a = ToolExecuteRequest(
            tool_name="product_search",
            params={},
            tenant_id=TENANT_A,
            user_id=USER_A,
        )
        await execute_tool(request=req_a, authorized=True)

        # 租户 B 的请求
        req_b = ToolExecuteRequest(
            tool_name="product_search",
            params={},
            tenant_id=TENANT_B,
            user_id=USER_B,
        )
        await execute_tool(request=req_b, authorized=True)

        calls = mock_registry.execute_tool.call_args_list
        ctx_a = calls[0].args[1]
        ctx_b = calls[1].args[1]

        assert ctx_a.tenant_id == TENANT_A
        assert ctx_b.tenant_id == TENANT_B
        assert ctx_a.tenant_id != ctx_b.tenant_id


class TestHttpClientServiceTokenAlwaysPresent:
    """HTTP 客户端始终附带 Service Token"""

    @pytest.mark.unit
    def test_service_token_always_in_headers(self):
        """无论是否传 tenant_id，Service Token 都应包含在 headers 中"""
        client = AdminApiClient(
            base_url="http://localhost:8080",
            service_token=SERVICE_TOKEN,
        )

        # 不传任何上下文
        headers_no_ctx = client._get_headers()
        assert headers_no_ctx["X-Service-Token"] == SERVICE_TOKEN

        # 传了租户上下文
        headers_with_ctx = client._get_headers(tenant_id=TENANT_A, user_id=USER_A)
        assert headers_with_ctx["X-Service-Token"] == SERVICE_TOKEN

    @pytest.mark.unit
    @patch("app.utils.http_client.settings")
    def test_no_service_token_configured(self, mock_settings):
        """未配置 Service Token 时 headers 中不包含 X-Service-Token"""
        mock_settings.ADMIN_API_BASE_URL = "http://localhost:8080"
        mock_settings.SERVICE_TOKEN = None
        client = AdminApiClient(
            base_url="http://localhost:8080",
            service_token=None,
        )
        # 强制置空，因为构造函数 fallback 到 settings.SERVICE_TOKEN
        client.service_token = None
        headers = client._get_headers(tenant_id=TENANT_A)
        assert "X-Service-Token" not in headers
