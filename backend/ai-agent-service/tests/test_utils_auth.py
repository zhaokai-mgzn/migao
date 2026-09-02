"""app/utils/auth.py 单元测试（issue #2430，defense 域 JWT/Service Token 认证）

覆盖（补 test_auth.py 未覆盖的 RS256 真实验签路径 + 鉴权依赖）：
- verify_service_token：未配置 SERVICE_TOKEN → 503 CONFIG_ERROR（fail-closed）
- verify_jwt_token：RS256 公钥验签 + audience=migao 手动校验；
  合法 token → payload / 过期 → 401 TOKEN_EXPIRED / 签名无效 → 401 TOKEN_INVALID /
  audience 不匹配 → 401 TOKEN_INVALID
- get_current_user：Authorization Header（非 Cookie）取 token + permissions list/JSON 解析
- get_optional_user：认证失败返回 None / DEBUG 默认用户
- require_roles：允许角色放行 / 越权 → 403 PERMISSION_DENIED
"""
# case_ids: DF-007, DF-009, DF-014, DF-017

import time
import jwt
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from app.utils.auth import (
    UserRole,
    UserIdentity,
    verify_service_token,
    verify_jwt_token,
    get_current_user,
    get_optional_user,
    require_roles,
)


def _gen_rsa():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


_PRIVATE_PEM, _PUBLIC_PEM = _gen_rsa()


def _sign(payload, private_pem=_PRIVATE_PEM):
    return jwt.encode(payload, private_pem, algorithm="RS256")


def _future_payload(**extra):
    payload = {
        "userId": "u1",
        "tenantId": 1,
        "identityType": "account",
        "role": "customer",
        "aud": "migao",
        "exp": int(time.time()) + 3600,
    }
    payload.update(extra)
    return payload


class TestVerifyServiceToken:
    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_not_configured_returns_503(self, mock_settings):
        mock_settings.SERVICE_TOKEN = ""

        with pytest.raises(HTTPException) as exc:
            await verify_service_token("any-token")

        assert exc.value.status_code == 503
        assert exc.value.detail["error"]["code"] == "CONFIG_ERROR"


class TestVerifyJwtTokenRS256:
    @patch("app.utils.auth.settings")
    def test_valid_token_returns_payload(self, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = _PUBLIC_PEM
        mock_settings.DEBUG = False

        result = verify_jwt_token(_sign(_future_payload()))

        assert result["userId"] == "u1"
        assert result["aud"] == "migao"

    @patch("app.utils.auth.settings")
    def test_expired_token_returns_401(self, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = _PUBLIC_PEM
        mock_settings.DEBUG = False
        payload = _future_payload(exp=int(time.time()) - 3600)

        with pytest.raises(HTTPException) as exc:
            verify_jwt_token(_sign(payload))

        assert exc.value.status_code == 401
        assert exc.value.detail["error"]["code"] == "TOKEN_EXPIRED"

    @patch("app.utils.auth.settings")
    def test_invalid_signature_returns_401(self, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = _PUBLIC_PEM
        mock_settings.DEBUG = False
        other_private, _ = _gen_rsa()

        with pytest.raises(HTTPException) as exc:
            verify_jwt_token(_sign(_future_payload(), private_pem=other_private))

        assert exc.value.status_code == 401
        assert exc.value.detail["error"]["code"] == "TOKEN_INVALID"

    @patch("app.utils.auth.settings")
    def test_wrong_audience_returns_401(self, mock_settings):
        mock_settings.JWT_PUBLIC_KEY = _PUBLIC_PEM
        mock_settings.DEBUG = False
        payload = _future_payload(aud="other-audience")

        with pytest.raises(HTTPException) as exc:
            verify_jwt_token(_sign(payload))

        assert exc.value.status_code == 401
        assert exc.value.detail["error"]["code"] == "TOKEN_INVALID"


class TestGetCurrentUser:
    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_header_based_auth(self, mock_settings):
        mock_settings.DEBUG = False
        mock_settings.JWT_PUBLIC_KEY = _PUBLIC_PEM

        creds = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=_sign(_future_payload())
        )
        request = MagicMock()
        request.cookies = {}
        request.state = MagicMock()

        user = await get_current_user(request, authorization=creds)

        assert user.user_id == "u1"
        assert user.tenant_id == 1
        assert user.role == "customer"

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_permissions_from_list(self, mock_settings):
        mock_settings.DEBUG = False
        mock_settings.JWT_PUBLIC_KEY = _PUBLIC_PEM

        creds = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=_sign(_future_payload(permissions=["a", "b"])),
        )
        request = MagicMock()
        request.cookies = {}
        request.state = MagicMock()

        user = await get_current_user(request, authorization=creds)

        assert user.permissions == ["a", "b"]

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_permissions_from_json_string(self, mock_settings):
        mock_settings.DEBUG = False
        mock_settings.JWT_PUBLIC_KEY = _PUBLIC_PEM

        creds = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=_sign(_future_payload(perm='["x", "y"]')),
        )
        request = MagicMock()
        request.cookies = {}
        request.state = MagicMock()

        user = await get_current_user(request, authorization=creds)

        assert user.permissions == ["x", "y"]


class TestGetOptionalUser:
    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_returns_none_on_auth_failure(self, mock_settings):
        mock_settings.DEBUG = False
        mock_settings.JWT_PUBLIC_KEY = ""

        request = MagicMock()
        request.cookies = {}
        request.client = MagicMock(host="1.2.3.4")

        result = await get_optional_user(request, authorization=None)

        # 认证失败（401）应被吞掉并返回 None，而非向调用方抛出
        assert not result

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_returns_user_when_authenticated(self, mock_settings):
        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        request = MagicMock()
        request.cookies = {}
        request.state = MagicMock()

        result = await get_optional_user(request, authorization=None)

        assert result.user_id == "dev_user"


class TestMerchantStaffRoles:
    """admin-api 商户员工角色码必须能通过认证（角色码漂移修复，POC 审查 D 项）。

    此前 UserRole 枚举仅 customer/agent/admin 三值，admin-api 签发的
    operator/product_manager/customer_service 等员工角色 JWT 全部 401，
    商户员工无法使用米宝 B 端对话。
    """

    @pytest.mark.parametrize(
        "role_code",
        ["operator", "product_manager", "customer_service", "knowledge_editor", "super_admin"],
    )
    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_merchant_staff_role_passes_auth(self, mock_settings, role_code):
        mock_settings.DEBUG = False
        mock_settings.JWT_PUBLIC_KEY = _PUBLIC_PEM

        creds = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=_sign(_future_payload(role=role_code)),
        )
        request = MagicMock()
        request.cookies = {}
        request.state = MagicMock()

        user = await get_current_user(request, authorization=creds)

        assert user.user_id == "u1"
        assert user.tenant_id == 1
        assert user.role == role_code  # 原角色保留，供 allowed_roles 细粒度判断


class TestRequireRoles:
    @pytest.mark.asyncio
    async def test_allowed_role_passes(self):
        checker = require_roles([UserRole.ADMIN, UserRole.AGENT])
        user = UserIdentity(
            user_id="u1",
            tenant_id=1,
            identity_type="account",
            role=UserRole.AGENT,
        )

        result = await checker(user)

        assert result.user_id == "u1"
        assert result.role == "agent"

    @pytest.mark.asyncio
    async def test_denied_role_returns_403(self):
        checker = require_roles([UserRole.ADMIN])
        user = UserIdentity(
            user_id="u1",
            tenant_id=1,
            identity_type="account",
            role=UserRole.CUSTOMER,
        )

        with pytest.raises(HTTPException) as exc:
            await checker(user)

        assert exc.value.status_code == 403
        assert exc.value.detail["error"]["code"] == "PERMISSION_DENIED"
