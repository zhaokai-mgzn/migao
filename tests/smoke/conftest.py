"""
冒烟测试共享 Fixtures
"""

# case_ids: API-010
from typing import Dict

import pytest

from .config import EnvConfig, get_config
from .helpers import SmokeTestClient
from .retry_policy import SESSION_LEDGER


def pytest_sessionfinish(session, exitstatus):
    """瞬态重试读数（issue #4182）：**有重试**与**零重试**都要出声。

    只在"有重试"时打印的话，「本轮零瞬态」与「读数机制坏了」长得一模一样
    （本仓最贵的形态：绿了但没跑）。这行会随 tee 进 run summary 与 artifact
    ⇒ "这次为什么绿 / 为什么红"事后可判。
    """
    if SESSION_LEDGER.retries:
        print(f"\n⚠️ P0 冒烟本轮遇瞬态签名 {SESSION_LEDGER.transient_events} 次，"
              f"重试 {SESSION_LEDGER.retries} 次，累计等待 {SESSION_LEDGER.waited:.0f}s"
              f"（会话上限 {SESSION_LEDGER.budget_s:.0f}s）"
              f"—— 部署滚动重启窗口，非回归（issue #4182）")
    else:
        print("\n✅ P0 冒烟本轮零瞬态重试（无 502/503/504，也无连接断开）")


@pytest.fixture(scope="session")
def config() -> EnvConfig:
    """获取测试环境配置"""
    return get_config()


@pytest.fixture(scope="session")
def admin_client(config: EnvConfig) -> SmokeTestClient:
    """admin-api 测试客户端"""
    client = SmokeTestClient(config.admin_api_url)
    yield client
    client.close()


@pytest.fixture(scope="session")
def ai_client(config: EnvConfig) -> SmokeTestClient:
    """ai-agent-service 测试客户端"""
    client = SmokeTestClient(config.ai_agent_url)
    yield client
    client.close()


@pytest.fixture(scope="session")
def auth_token(admin_client: SmokeTestClient, config: EnvConfig) -> Dict[str, str]:
    """获取认证 Token（session 级别复用）"""
    resp = admin_client.post("/api/auth/sms/login", json={
        "phone": config.admin_phone,
        "code": config.admin_sms_code,
    })
    if resp.status_code != 200:
        pytest.fail(
            f"SMS 登录失败: status={resp.status_code}, body={resp.text[:300]} - "
            f"P0 冒烟测试要求登录链路必须可用，禁止静默跳过"
        )

    data = resp.json()
    token_data = data.get("data", data)
    access_token = token_data.get("accessToken", token_data.get("access_token", ""))
    # 审计 07 P1-5：refresh token 不再由响应体下发（仅 HttpOnly cookie 承载）。
    # httpx.Client 会自动管理 Set-Cookie，后续 refresh 请求无需手动传 refresh token。
    refresh_token = token_data.get("refreshToken", token_data.get("refresh_token", "")) or ""

    if not access_token:
        pytest.fail("SMS 登录响应缺少 access token，认证链路异常")

    admin_client.set_token(access_token, refresh_token)
    return {"access_token": access_token, "refresh_token": refresh_token}


@pytest.fixture(scope="session")
def authed_admin_client(admin_client: SmokeTestClient, auth_token: dict) -> SmokeTestClient:
    """已认证的 admin-api 客户端"""
    return admin_client


@pytest.fixture(scope="session")
def authed_ai_client(ai_client: SmokeTestClient, auth_token: dict) -> SmokeTestClient:
    """已认证的 ai-agent-service 客户端（使用相同 token）"""
    ai_client.set_token(auth_token["access_token"])
    return ai_client


@pytest.fixture(scope="session")
def service_token_headers(config: EnvConfig) -> Dict[str, str]:
    """服务间通信 Token 头"""
    return {"X-Service-Token": config.service_token}
