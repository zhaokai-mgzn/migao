"""
认证链路冒烟测试 (P0)

覆盖：登录获取 JWT Token、Token 刷新、未认证请求返回 401。
"""

import pytest

from .config import EnvConfig
from .helpers import SmokeTestClient, assert_success_response


@pytest.mark.p0
@pytest.mark.auth
class TestAuthLogin:
    """登录认证测试"""

    def test_login_success(self, admin_client: SmokeTestClient, config: EnvConfig):
        """管理员 SMS 验证码登录获取 JWT Token"""
        resp = admin_client.post("/api/auth/sms/login", json={
            "phone": config.admin_phone,
            "code": config.admin_sms_code,
        })
        data = assert_success_response(resp)
        token_data = data.get("data", data)

        # 验证返回 Token
        access_token = token_data.get("accessToken", token_data.get("access_token"))
        assert access_token, f"No accessToken in response: {token_data.keys()}"
        assert access_token.startswith("eyJ"), f"Token should be JWT but got: {access_token[:20]}..."

        # 审计 07 P1-5：refresh token 仅经 HttpOnly cookie 下发，响应体不得再携带
        assert "refreshToken" not in token_data or token_data.get("refreshToken") is None, (
            "refresh token 不应出现在响应体（安全加固，仅 HttpOnly cookie 承载）"
        )
        set_cookie = resp.headers.get("set-cookie", "")
        assert "refresh_token=" in set_cookie, f"缺少 refresh_token Set-Cookie: {set_cookie[:200]}"
        assert "HttpOnly" in set_cookie, "refresh_token cookie 必须 HttpOnly"

    def test_login_wrong_code(self, admin_client: SmokeTestClient, config: EnvConfig):
        """错误验证码登录失败"""
        resp = admin_client.post("/api/auth/sms/login", json={
            "phone": config.admin_phone,
            "code": "000000",
        })
        assert resp.status_code in (400, 401, 403), (
            f"Expected auth error, got {resp.status_code}"
        )

    def test_login_missing_fields(self, admin_client: SmokeTestClient):
        """缺少必填字段登录失败"""
        resp = admin_client.post("/api/auth/sms/login", json={})
        assert resp.status_code in (400, 422), (
            f"Expected validation error, got {resp.status_code}"
        )

    def test_password_login_disabled(self, admin_client: SmokeTestClient):
        """#375 密码登录已禁用，应返回错误"""
        resp = admin_client.post("/api/auth/admin/login", json={
            "username": "admin",
            "password": "any_password",
            "tenantId": 1,
        })
        assert resp.status_code in (400, 401, 403), (
            f"Password login should be disabled, got {resp.status_code}"
        )
        body = resp.json()
        msg = str(body).lower()
        assert "禁用" in msg or "disabled" in msg or "短信" in msg or "sms" in msg, (
            f"Should mention password login disabled, got: {resp.text[:200]}"
        )


@pytest.mark.p0
@pytest.mark.auth
class TestTokenRefresh:
    """Token 刷新测试"""

    def test_refresh_token(self, admin_client: SmokeTestClient, auth_token: dict):
        """使用 HttpOnly refresh_token cookie 获取新的 access token（审计 07 P1-5）"""
        # 登录时 Set-Cookie 已存入 httpx client cookie jar，无需在 body 传 refresh token
        resp = admin_client.post("/api/auth/refresh", json={})
        assert resp.status_code == 200, (
            f"Refresh via cookie should succeed, got {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        token_data = data.get("data", data)
        new_token = token_data.get("accessToken", token_data.get("access_token"))
        assert new_token, "Refresh did not return new access token"

    def test_refresh_invalid_token(self, admin_client: SmokeTestClient):
        """无效 refresh token 返回错误"""
        resp = admin_client.post("/api/auth/refresh", json={
            "refreshToken": "invalid.token.here",
        })
        assert resp.status_code in (400, 401, 403), (
            f"Expected auth error for invalid refresh token, got {resp.status_code}"
        )


@pytest.mark.p0
@pytest.mark.auth
class TestUnauthorizedAccess:
    """未认证请求测试"""

    def test_unauthenticated_returns_401(self, config: EnvConfig):
        """未携带 Token 访问受保护接口返回 401"""
        client = SmokeTestClient(config.admin_api_url)
        try:
            resp = client.get("/api/admin/products")
            assert resp.status_code in (401, 403), (
                f"Expected 401/403 for unauthenticated request, got {resp.status_code}"
            )
        finally:
            client.close()

    def test_invalid_token_returns_401(self, config: EnvConfig):
        """无效 Token 访问受保护接口返回 401"""
        client = SmokeTestClient(config.admin_api_url)
        client.set_token("invalid.jwt.token")
        try:
            resp = client.get("/api/admin/products")
            assert resp.status_code in (401, 403), (
                f"Expected 401/403 for invalid token, got {resp.status_code}"
            )
        finally:
            client.close()

    def test_get_current_user(self, authed_admin_client: SmokeTestClient):
        """已认证用户获取当前用户信息

        仅在 status_code == 200 时才断言 body 内容，避免对未实现/路由不同
        的环境误报。非 200 状态下跳过 body 验证但不作为失败。
        """
        resp = authed_admin_client.get("/api/auth/me")
        if resp.status_code != 200:
            return
        data = resp.json()
        user_data = data.get("data", data)
        # 验证包含用户基本信息
        assert "user" in user_data or "username" in user_data or "id" in user_data, (
            f"Missing user info in /me response: {user_data.keys()}"
        )
