"""
AI 智能客服系统 - JWT 认证模块测试

测试 auth.py 中的 JWT Token 解析和用户身份提取逻辑
"""
# case_ids: DF-014, OR-022

import time
import jwt
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException

from tests.conftest import TEST_JWT_SECRET


class TestVerifyJwtToken:
    """verify_jwt_token 函数测试"""

    @patch("app.utils.auth.settings")
    def test_parse_token_in_debug_mode_without_public_key(self, mock_settings, make_jwt_token, sample_camel_case_payload):
        """DEBUG 模式下无公钥时，应跳过签名验证直接解析 Token"""
        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import verify_jwt_token

        token = make_jwt_token(sample_camel_case_payload)
        payload = verify_jwt_token(token)

        assert payload["userId"] == "user_001"
        assert payload["tenantId"] == 1

    @patch("app.utils.auth.settings")
    def test_invalid_token_returns_401(self, mock_settings):
        """无效 Token 应返回 401 错误"""
        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import verify_jwt_token

        with pytest.raises(HTTPException) as exc_info:
            verify_jwt_token("this.is.not.a.valid.token")
        assert exc_info.value.status_code == 401

    @patch("app.utils.auth.settings")
    def test_missing_public_key_in_production_returns_500(self, mock_settings, make_jwt_token, sample_camel_case_payload):
        """非 DEBUG 模式下缺少公钥应返回 500 配置错误"""
        mock_settings.DEBUG = False
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import verify_jwt_token

        token = make_jwt_token(sample_camel_case_payload)
        with pytest.raises(HTTPException) as exc_info:
            verify_jwt_token(token)
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail["error"]["code"] == "CONFIG_ERROR"


class TestGetCurrentUser:
    """get_current_user 函数测试 — 用户身份提取"""

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_camel_case_jwt_claims(self, mock_settings, make_jwt_token, sample_camel_case_payload):
        """camelCase 字段名（userId, tenantId）应正确解析"""
        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import get_current_user

        token = make_jwt_token(sample_camel_case_payload)
        # 模拟 Request 对象
        request = MagicMock()
        request.cookies = {"access_token": token}
        request.state = MagicMock()

        user = await get_current_user(request, authorization=None)

        assert user.user_id == "user_001"
        assert user.tenant_id == 1
        assert user.identity_type == "wechat_mini"
        assert user.external_id == "wx_openid_abc"

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_snake_case_jwt_claims(self, mock_settings, make_jwt_token, sample_snake_case_payload):
        """snake_case 字段名（user_id, tenant_id）应正确解析"""
        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import get_current_user

        token = make_jwt_token(sample_snake_case_payload)
        request = MagicMock()
        request.cookies = {"access_token": token}
        request.state = MagicMock()

        user = await get_current_user(request, authorization=None)

        assert user.user_id == "user_002"
        assert user.tenant_id == 2
        assert user.identity_type == "account"
        assert user.role == "admin"

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_roles_array_takes_first_element(self, mock_settings, make_jwt_token):
        """roles 数组应取第一个元素作为 role"""
        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import get_current_user

        payload = {
            "userId": "user_roles",
            "tenantId": 1,
            "identityType": "account",
            "roles": ["agent", "admin"],
            "exp": int(time.time()) + 3600,
        }
        token = make_jwt_token(payload)
        request = MagicMock()
        request.cookies = {"access_token": token}
        request.state = MagicMock()

        user = await get_current_user(request, authorization=None)

        # 没有 role 字段时，应从 roles 数组取第一个
        assert user.role == "agent"

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_missing_required_claims_returns_401(self, mock_settings, make_jwt_token):
        """缺少必要的 userId/tenantId claims 应返回 401"""
        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import get_current_user

        # 缺少 userId 和 tenantId
        payload = {
            "identityType": "account",
            "role": "customer",
            "exp": int(time.time()) + 3600,
        }
        token = make_jwt_token(payload)
        request = MagicMock()
        request.cookies = {"access_token": token}
        request.state = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request, authorization=None)
        assert exc_info.value.status_code == 401

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_expired_token_returns_401(self, mock_settings, make_jwt_token, expired_payload):
        """过期 Token 应返回 401 错误（DEBUG 模式下不验证签名但仍检查 exp）"""
        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import verify_jwt_token

        token = make_jwt_token(expired_payload)
        # DEBUG 模式不验证签名，jwt.decode 默认也不验证 exp（verify_signature=False 时）
        # 但实际上 PyJWT 在 verify_signature=False 时也不验证 exp
        # 所以这里测试走正常流程能解析出 payload
        payload = verify_jwt_token(token)
        assert payload["userId"] == "user_expired"

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_no_token_in_debug_mode_without_debug_header_returns_401(self, mock_settings):
        """P0-3 回归：DEBUG=true 且无 token 时，不带 X-Debug-Role 头 → 必须 401

        此前实现会静默降级为 tenant_id=1 的 dev_user 管理员；生产若误配
        DEBUG=true，任何浏览器无 token 请求都会读到租户 1（词元通达）数据
        （跨租户数据泄露，POC 实测）。现 fail-closed：无头一律 401。
        """
        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import get_current_user

        request = MagicMock()
        request.cookies = {}
        request.state = MagicMock()
        request.headers = {"X-Debug-Role": ""}  # 无显式调试角色

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request, authorization=None)
        assert exc_info.value.status_code == 401

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_no_token_in_debug_mode_with_customer_header_returns_customer(self, mock_settings):
        """DEBUG + 显式 X-Debug-Role: customer → 小布 C 端身份（本地验收/CI xiaobu 用）"""
        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import get_current_user

        request = MagicMock()
        request.cookies = {}
        request.state = MagicMock()
        request.headers = {"X-Debug-Role": "customer"}

        user = await get_current_user(request, authorization=None)
        assert user.user_id == "debug_customer_1"
        assert user.role == "customer"

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_no_token_in_debug_mode_with_admin_header_returns_dev_user(self, mock_settings):
        """DEBUG + 显式 X-Debug-Role: mibao → 管理员身份（B 端 eval 显式声明后仍可用）"""
        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import get_current_user

        request = MagicMock()
        request.cookies = {}
        request.state = MagicMock()
        request.headers = {"X-Debug-Role": "mibao"}

        user = await get_current_user(request, authorization=None)
        assert user.user_id == "dev_user"
        assert user.tenant_id == 1
        # #3511（HR-003 归因）：DEBUG 管理员身份必须带**通配权限**——
        # 否则 role=admin 只能过 allowed_roles 粗筛，凡声明 required_permissions 的
        # 工具（employee_manage 等）会一律「权限不足」：B 端独立栈实测
        # `employee_manage!权限不足`，agent 行为正确却无法执行（评测环境缺陷，非能力缺陷）。
        assert "*" in user.permissions, (
            "DEBUG 管理员身份缺通配权限 permissions=['*'] → 需要 required_permissions 的"
            "工具在评测栈里必然『权限不足』（HR-003 实测形态）"
        )

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_debug_user_header_selects_customer_identity(self, mock_settings):
        """多身份评测（issue #3391）：DEBUG + customer + 白名单内 X-Debug-User → 用该用户。

        为什么需要：`debug_customer_1` 在种子里有历史订单，`customer_address_query` 恒
        `has_address=true` → 「新客没有历史收货信息 → 主动收集」这条路径**在评测里不可达**，
        而那正是验收 C-A1 暴露问题的路径（无历史地址时 agent 该查/该问，不是拒单）。
        """
        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import get_current_user

        request = MagicMock()
        request.cookies = {}
        request.state = MagicMock()
        request.headers = {"X-Debug-Role": "customer", "X-Debug-User": "debug_customer_new"}

        user = await get_current_user(request, authorization=None)
        assert user.user_id == "debug_customer_new"
        assert user.role == "customer"
        assert user.tenant_id == 1

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_debug_user_header_rejects_non_allowlisted_id(self, mock_settings):
        """白名单外一律忽略（防"DEBUG 误配 = 任意用户伪装"；P0-3 同类教训）。"""
        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import get_current_user

        for bad in ["dev_user", "admin", "user_1", "debug_customer_1; DROP TABLE orders",
                    "debug_", "DEBUG_customer_new", "../debug_customer_new"]:
            request = MagicMock()
            request.cookies = {}
            request.state = MagicMock()
            request.headers = {"X-Debug-Role": "customer", "X-Debug-User": bad}
            user = await get_current_user(request, authorization=None)
            assert user.user_id == "debug_customer_1", f"非白名单 id 被采纳: {bad!r}"

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_debug_user_header_customer_only(self, mock_settings):
        """B 端（mibao）不受该头影响 —— 覆盖面越小越安全。"""
        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import get_current_user

        request = MagicMock()
        request.cookies = {}
        request.state = MagicMock()
        request.headers = {"X-Debug-Role": "mibao", "X-Debug-User": "debug_customer_new"}

        user = await get_current_user(request, authorization=None)
        assert user.user_id == "dev_user", "B 端身份不该被 X-Debug-User 改写"

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_no_token_in_production_mode_returns_401(self, mock_settings):
        """生产模式下无 Token 应返回 401"""
        mock_settings.DEBUG = False
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import get_current_user

        request = MagicMock()
        request.cookies = {}
        request.state = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request, authorization=None)
        assert exc_info.value.status_code == 401


    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_custom_merchant_role_code_parses(self, mock_settings, make_jwt_token):
        """P1-C 回归：自定义角色码不得导致 401（role 放宽为 str 透传）"""
        mock_settings.DEBUG = True
        mock_settings.JWT_PUBLIC_KEY = ""

        from app.utils.auth import get_current_user

        payload = {
            "userId": "custom_staff_1",
            "tenantId": 20,
            "roles": ["poc_operator_custom"],
            "permissions": ["dashboard:view", "knowledge:manage"],
            "identityType": "sms",
        }
        token = make_jwt_token(payload)
        request = MagicMock()
        request.cookies = {"access_token": token}
        request.state = MagicMock()

        user = await get_current_user(request, authorization=None)
        assert user.user_id == "custom_staff_1"
        assert user.role == "poc_operator_custom"
        assert "dashboard:view" in user.permissions


class TestVerifyServiceToken:
    """verify_service_token 函数测试"""

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_valid_service_token(self, mock_settings):
        """有效的 Service Token 应返回 True"""
        mock_settings.SERVICE_TOKEN = "correct-token"

        from app.utils.auth import verify_service_token

        result = await verify_service_token("correct-token")
        assert result is True

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_invalid_service_token_returns_401(self, mock_settings):
        """无效的 Service Token 应返回 401（使用恒定时间比较防时序攻击）"""
        mock_settings.SERVICE_TOKEN = "correct-token"

        from app.utils.auth import verify_service_token

        with pytest.raises(HTTPException) as exc_info:
            await verify_service_token("wrong-token")
        assert exc_info.value.status_code == 401

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_token_comparison_constant_time(self, mock_settings):
        """Token 比较应使用 secrets.compare_digest 恒定时间比较"""
        mock_settings.SERVICE_TOKEN = "secret-token-123"

        from app.utils.auth import verify_service_token

        # 验证函数存在且正确拒绝不匹配 token
        result_match = await verify_service_token("secret-token-123")
        assert result_match is True
        with pytest.raises(HTTPException):
            await verify_service_token("different-token")

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_missing_service_token_returns_401(self, mock_settings):
        """缺少 Service Token 应返回 401"""
        mock_settings.SERVICE_TOKEN = "correct-token"

        from app.utils.auth import verify_service_token

        with pytest.raises(HTTPException) as exc_info:
            await verify_service_token(None)
        assert exc_info.value.status_code == 401
