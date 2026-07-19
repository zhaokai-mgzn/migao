"""
应用级 RLS（租户隔离）行为测试

验证应用自身的隔离机制（非 PostgreSQL 内置 RLS）：
1. AdminApiClient 正确注入 X-Tenant-Id header
2. JWT tenant_id 正确解析为 UserIdentity
3. 跨租户 session 访问被拒绝（send_message 中 session.tenant_id ≠ user.tenant_id → 403）
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


# ═══════════════════════════════════════════════════════════════════
# 1. HTTP Client — X-Tenant-Id 注入
# ═══════════════════════════════════════════════════════════════════

class TestTenantHeaderInjection:
    """AdminApiClient._get_headers 在每个请求中注入 X-Tenant-Id"""

    def test_get_headers_injects_tenant_id(self):
        from app.utils.http_client import AdminApiClient
        client = AdminApiClient(base_url="http://test")
        headers = client._get_headers(tenant_id=42)
        assert headers["X-Tenant-Id"] == "42"

    def test_get_headers_no_tenant_id_skips_header(self):
        from app.utils.http_client import AdminApiClient
        client = AdminApiClient(base_url="http://test")
        headers = client._get_headers(tenant_id=None)
        assert "X-Tenant-Id" not in headers

    def test_get_headers_injects_user_id(self):
        from app.utils.http_client import AdminApiClient
        client = AdminApiClient(base_url="http://test")
        headers = client._get_headers(tenant_id=1, user_id="user_123")
        assert headers["X-User-Id"] == "user_123"

    @pytest.mark.asyncio
    async def test_get_passes_tenant_header(self):
        """GET 请求通过 _request 注入 X-Tenant-Id"""
        from app.utils.http_client import AdminApiClient
        client = AdminApiClient(base_url="http://test")

        captured_headers = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "data": {}}

        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_client", AsyncMock(return_value=mock_http)):
            await client.get("/api/products", params={"page": 1}, tenant_id=99)

        call_kwargs = mock_http.request.call_args[1]
        assert call_kwargs["headers"]["X-Tenant-Id"] == "99"

    @pytest.mark.asyncio
    async def test_post_passes_tenant_header(self):
        """POST 请求通过 _request 注入 X-Tenant-Id"""
        from app.utils.http_client import AdminApiClient
        client = AdminApiClient(base_url="http://test")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "data": {}}

        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_client", AsyncMock(return_value=mock_http)):
            await client.post("/api/products", json_data={"name": "test"}, tenant_id=88)

        call_kwargs = mock_http.request.call_args[1]
        assert call_kwargs["headers"]["X-Tenant-Id"] == "88"


# ═══════════════════════════════════════════════════════════════════
# 2. JWT → Tenant 提取
# ═══════════════════════════════════════════════════════════════════

class TestJwtTenantExtraction:
    """verify_jwt_token + get_current_user 正确提取 tenant_id"""

    @patch("app.utils.auth.settings")
    def test_camel_case_tenant_id(self, mock_settings):
        """camelCase: tenantId → UserIdentity.tenant_id"""
        from app.utils.auth import verify_jwt_token
        import jwt as pyjwt

        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        token = pyjwt.encode(
            {"userId": "u1", "tenantId": 5, "identityType": "account", "role": "admin"},
            "secret", algorithm="HS256",
        )
        payload = verify_jwt_token(token)
        assert payload["tenantId"] == 5

    @patch("app.utils.auth.settings")
    def test_snake_case_tenant_id(self, mock_settings):
        """snake_case: tenant_id 也正确解析"""
        from app.utils.auth import verify_jwt_token
        import jwt as pyjwt

        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        token = pyjwt.encode(
            {"user_id": "u1", "tenant_id": 8, "identity_type": "account", "role": "customer"},
            "secret", algorithm="HS256",
        )
        payload = verify_jwt_token(token)
        assert payload["tenant_id"] == 8

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_user_identity_carries_tenant(self, mock_settings):
        """get_current_user 返回的 UserIdentity 包含正确 tenant_id"""
        from app.utils.auth import get_current_user
        import jwt as pyjwt

        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        token = pyjwt.encode(
            {"userId": "u_test", "tenantId": 42, "identityType": "account", "role": "customer"},
            "secret", algorithm="HS256",
        )
        from fastapi.security import HTTPAuthorizationCredentials
        auth = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        request = MagicMock()
        request.cookies = {}
        request.state = MagicMock()

        user = await get_current_user(request, auth)
        assert user.tenant_id == 42
        assert user.user_id == "u_test"

    @patch("app.utils.auth.settings")
    def test_empty_tenant_id_allowed(self, mock_settings):
        """tenantId 缺失时不阻止解析（get_current_user 中默认 tenant_id=1）"""
        from app.utils.auth import verify_jwt_token
        import jwt as pyjwt

        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        token = pyjwt.encode(
            {"userId": "u1", "identityType": "account", "role": "customer"},
            "secret", algorithm="HS256",
        )
        payload = verify_jwt_token(token)
        assert "tenantId" not in payload
        assert payload["userId"] == "u1"


# ═══════════════════════════════════════════════════════════════════
# 3. 跨租户 Session 访问拒绝
# ═══════════════════════════════════════════════════════════════════

class TestCrossTenantSessionRejection:
    """send_message 内 session.tenant_id ≠ user.tenant_id → 403"""

    @pytest.mark.asyncio
    async def test_cross_tenant_session_blocked(self):
        """用 tenant_id=2 的 JWT 访问 tenant_id=1 的 session → 403"""
        import jwt as pyjwt
        from fastapi import HTTPException

        # Mock SessionMemory 和 settings 来绕过中间件依赖
        with patch("app.api.chat.SessionMemory") as MockSM, \
             patch("app.api.chat.settings") as mock_settings:

            mock_settings.DEBUG = True
            mock_settings.JWT_PUBLIC_KEY = ""
            mock_settings.SERVICE_TOKEN = ""

            # session 属于 tenant 1
            mock_sm = AsyncMock()
            mock_sm.get_session = AsyncMock(return_value={
                "session_id": "sess_cross",
                "tenant_id": 1,
                "customer_id": "user_a",
                "status": "active",
                "agent_type": "mibao",
            })
            MockSM.return_value = mock_sm

            # JWT 声明租户 2
            token = pyjwt.encode(
                {"userId": "user_b", "tenantId": 2,
                 "identityType": "account", "role": "admin"},
                "secret", algorithm="HS256",
            )

            from app.api.chat import ChatSendRequest, send_message
            request = ChatSendRequest(
                session_id="sess_cross",
                message="hello",
            )

            # 用 get_current_user 模拟当前用户为租户 2
            with patch("app.api.chat.get_current_user") as mock_get_user:
                from app.utils.auth import UserIdentity
                mock_get_user.return_value = UserIdentity(
                    user_id="user_b", tenant_id=2,
                    identity_type="account", role="admin",
                )

                # 直接传 current_user 绕过 FastAPI Depends
                with pytest.raises(HTTPException) as exc_info:
                    await send_message(
                        request,
                        current_user=UserIdentity(
                            user_id="user_b", tenant_id=2,
                            identity_type="account", role="admin",
                        ),
                    )
                assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_same_tenant_session_allowed(self):
        """同租户同用户访问 session → 不抛异常（继续后续流程）"""
        import jwt as pyjwt
        from fastapi import HTTPException

        with patch("app.api.chat.SessionMemory") as MockSM, \
             patch("app.api.chat.settings") as mock_settings:

            mock_settings.DEBUG = True
            mock_settings.JWT_PUBLIC_KEY = ""
            mock_settings.SERVICE_TOKEN = ""

            mock_sm = AsyncMock()
            mock_sm.get_session = AsyncMock(return_value={
                "session_id": "sess_ok",
                "tenant_id": 1,
                "customer_id": "user_a",
                "status": "active",
                "agent_type": "mibao",
            })
            MockSM.return_value = mock_sm

            from app.api.chat import ChatSendRequest, send_message
            request = ChatSendRequest(
                session_id="sess_ok",
                message="hello",
            )

            with patch("app.api.chat.get_current_user") as mock_get_user:
                from app.utils.auth import UserIdentity
                mock_get_user.return_value = UserIdentity(
                    user_id="user_a", tenant_id=1,  # same tenant
                    identity_type="account", role="admin",
                )

                # 不会抛 403（会继续到 _agent_stream_to_sse 但被 SSE 相关 mock 卡住，
                # 但关键验证是它通过了 session 租户检查）
                try:
                    await send_message(
                        request,
                        current_user=UserIdentity(
                            user_id="user_a", tenant_id=1,
                            identity_type="account", role="admin",
                        ),
                    )
                except HTTPException as e:
                    # 不应该因为租户不匹配而 403
                    assert e.status_code != 403, (
                        f"相同租户不应被拒绝，实际 {e.status_code}: {e.detail}"
                    )
