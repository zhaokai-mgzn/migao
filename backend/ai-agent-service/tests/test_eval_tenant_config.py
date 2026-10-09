# case_ids: DA-024
"""DEBUG 降级身份的**目标租户**可配，且生产路径不接受外部租户（issue #6288）。

## 为什么这个文件必须有（不是「多写一层测试」）

`app/utils/auth.py` 的 DEBUG 降级身份里，`tenant_id` 曾经写死 `1`。2026-10-04 云测试环境
重建后 tenant 1「词元通达」连同全部数据已清空 ⇒ 写死 1 会让「**唯一打已部署环境**的评测
入口」（`agent-eval.yml` → `tests/agent_eval/local_runner.py`，借本分支拿管理员身份）
落到一个**不存在的租户**，而该入口的唯一触发是 `workflow_dispatch` ⇒ **不会报警**。

修法 = 收敛到 `settings.EVAL_TENANT_ID`（环境变量 `EVAL_TENANT_ID`）。本文件钉住**两侧**：

| # | 侧 | 断言 |
|---|---|---|
| ① | **正向** | DEBUG 档下按配置取租户 ⇒ 生效（管理员身份 / C 端 customer 身份各一条，**逐值**） |
| ② | **🔴 反向（缺一不可）** | **生产路径**（`DEBUG=False`）下即使有人注入了 tenant（头 / 配置） ⇒ **不生效**（401，永不降级） |
| ③ | 配置面 | 逐值注入（如 7 / 12345）⇒ 走到身份里的就是注入值；`DEBUG_FALLBACK_TENANT_ID` ≡ `settings.EVAL_TENANT_ID`；默认值 = 云测试租户 25 |

只有 ① 会「把一个越权通道当成特性交付」：`tenant_id=1` 是 P0-3（2026-09-03）刚钉住的
越权面（注释逐字写着「降级为 tenant_id=1 的 dev_user 管理员，导致跨租户数据泄露」）
⇒ 租户可配**只能**发生在「DEBUG + 显式 `X-Debug-Role`」这条既有关闭的通道内。

零 LLM、零网络、零 DB（`settings` 被打桩；真实请求对象由 `MagicMock` 提供）。
"""
import pytest
from unittest.mock import MagicMock, patch

from app.utils import auth as auth_mod
from app.utils.auth import get_current_user
from fastapi import HTTPException

# 云测试租户的真值（2026-10-04 云测试环境重建；依据见 PR body）
CLOUD_TEST_TENANT_ID = 25


def _request(headers: dict | None = None) -> MagicMock:
    req = MagicMock()
    req.cookies = {}
    req.state = MagicMock()
    req.headers = headers or {}
    req.client = MagicMock(host="127.0.0.1")
    return req


class TestDebugFallbackTenantIsConfigurable:
    """① 正向：DEBUG 档下按配置取租户 ⇒ 生效（逐值）。"""

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_admin_identity_uses_configured_tenant(self, mock_settings):
        mock_settings.DEBUG = True
        user = await get_current_user(_request({"X-Debug-Role": "mibao"}), authorization=None)
        assert user.role == "admin"
        assert user.tenant_id == auth_mod.DEBUG_FALLBACK_TENANT_ID
        assert user.tenant_id == CLOUD_TEST_TENANT_ID  # 默认 = 云测试租户

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_customer_identity_uses_configured_tenant(self, mock_settings):
        """C 端 customer 身份（多身份评测）同样走配置，不是各写一份字面量。"""
        mock_settings.DEBUG = True
        user = await get_current_user(_request({"X-Debug-Role": "customer"}), authorization=None)
        assert user.role == "customer"
        assert user.tenant_id == CLOUD_TEST_TENANT_ID

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_customer_identity_with_debug_user_override_keeps_configured_tenant(
            self, mock_settings):
        mock_settings.DEBUG = True
        user = await get_current_user(
            _request({"X-Debug-Role": "customer", "X-Debug-User": "debug_customer_2"}),
            authorization=None)
        assert user.user_id == "debug_customer_2"
        assert user.tenant_id == CLOUD_TEST_TENANT_ID

    @pytest.mark.parametrize("injected", [7, 25, 12345])
    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_injected_value_reaches_the_identity(self, mock_settings, monkeypatch,
                                                       injected):
        """① 逐值：**注入一个租户号 ⇒ 走到身份里用的就是注入值**（不是「非空」）。"""
        mock_settings.DEBUG = True
        monkeypatch.setattr(auth_mod, "DEBUG_FALLBACK_TENANT_ID", injected, raising=True)
        admin = await get_current_user(_request({"X-Debug-Role": "mibao"}), authorization=None)
        customer = await get_current_user(_request({"X-Debug-Role": "customer"}), authorization=None)
        assert admin.tenant_id == injected
        assert customer.tenant_id == injected


class TestConfiguredTenantIsTheSingleSource:
    """③ 配置面：字段默认值 / 解析件 / 身份三处必须是同一个值。"""

    def test_fallback_constant_comes_from_settings_field(self):
        from app.config import settings
        assert auth_mod.DEBUG_FALLBACK_TENANT_ID == settings.EVAL_TENANT_ID, (
            "auth 的降级租户不是读 settings.EVAL_TENANT_ID —— 又出现了第二份真值"
        )

    def test_default_points_to_the_cloud_test_tenant(self):
        from app.config import settings
        assert settings.EVAL_TENANT_ID == CLOUD_TEST_TENANT_ID, (
            f"EVAL_TENANT_ID 默认 {settings.EVAL_TENANT_ID} ≠ 云测试租户 {CLOUD_TEST_TENANT_ID}"
        )

    def test_env_var_injection_is_honoured(self, monkeypatch):
        """逐值：环境变量 `EVAL_TENANT_ID` 真能改到 `Settings` 的取值（注入面存在且正确）。"""
        from app.config import Settings
        assert Settings(EVAL_TENANT_ID=12345, DEBUG=True).EVAL_TENANT_ID == 12345  # noqa: ERA001
        monkeypatch.setenv("EVAL_TENANT_ID", "777")
        assert Settings(DEBUG=True).EVAL_TENANT_ID == 777


class TestNonDebugPathRejectsExternalTenant:
    """② 🔴 反向护栏（缺一不可）：生产路径注入 tenant ⇒ **不生效**。"""

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_debug_role_header_is_inert_when_debug_off(self, mock_settings):
        """`DEBUG=False` + 注入的调试头（含调试身份）⇒ 401 fail-closed，永不降级。"""
        mock_settings.DEBUG = False
        mock_settings.JWT_PUBLIC_KEY = ""
        with pytest.raises(HTTPException) as exc:
            await get_current_user(_request({"X-Debug-Role": "mibao"}), authorization=None)
        assert exc.value.status_code == 401

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_debug_role_header_is_inert_without_the_debug_flag(self, mock_settings):
        """只带 `X-Debug-Role: customer` 也 401（无 token 一律 fail-closed）。"""
        mock_settings.DEBUG = False
        mock_settings.JWT_PUBLIC_KEY = ""
        with pytest.raises(HTTPException) as exc:
            await get_current_user(_request({"X-Debug-Role": "customer"}), authorization=None)
        assert exc.value.status_code == 401

    @patch("app.utils.auth.settings")
    @pytest.mark.asyncio
    async def test_configured_tenant_is_not_a_fallback_on_production_path(
            self, mock_settings, monkeypatch):
        """🔴 反向护栏本体：把「配置的租户」换成哨兵值 ⇒ 生产路径**绝不**产生该租户的身份。"""
        sentinel = 987_654_321
        mock_settings.DEBUG = False
        mock_settings.JWT_PUBLIC_KEY = ""
        monkeypatch.setattr(auth_mod, "DEBUG_FALLBACK_TENANT_ID", sentinel, raising=True)
        # 无 token：必须 401（不是"降级成哨兵租户的管理员"）
        with pytest.raises(HTTPException):
            await get_current_user(_request({"X-Debug-Role": "mibao"}), authorization=None)
        # 带 token：租户只来自 JWT（tenantId=1 的测试载荷），与配置值无关
        from tests.test_utils_auth import _PUBLIC_PEM, _future_payload, _sign
        from fastapi.security import HTTPAuthorizationCredentials
        mock_settings.JWT_PUBLIC_KEY = _PUBLIC_PEM
        creds = HTTPAuthorizationCredentials(scheme="Bearer",
                                            credentials=_sign(_future_payload(tenantId=1)))
        user = await get_current_user(_request(), authorization=creds)
        assert user.tenant_id == 1
        assert user.tenant_id != sentinel
