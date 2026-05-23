"""
冒烟测试共享 Fixtures
"""

from typing import Dict

import pytest

from .config import EnvConfig, get_config
from .helpers import SmokeTestClient


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
    resp = admin_client.post("/api/auth/admin/login", json={
        "username": config.admin_username,
        "password": config.admin_password,
        "tenantId": config.tenant_id,
    })
    if resp.status_code != 200:
        pytest.fail(
            f"登录失败: status={resp.status_code}, body={resp.text[:300]} - "
            f"P0 冒烟测试要求登录链路必须可用，禁止静默跳过"
        )

    data = resp.json()
    token_data = data.get("data", data)
    access_token = token_data.get("accessToken", token_data.get("access_token", ""))
    refresh_token = token_data.get("refreshToken", token_data.get("refresh_token", ""))

    if not access_token:
        pytest.fail("登录响应缺少 access token，认证链路异常")

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
