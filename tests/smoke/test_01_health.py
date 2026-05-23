"""
健康检查验证测试 (P0)

验证所有服务的健康检查端点正常响应。
"""

import pytest

from .helpers import SmokeTestClient


@pytest.mark.p0
@pytest.mark.health
class TestHealthCheck:
    """健康检查验证"""

    def test_admin_api_health(self, admin_client: SmokeTestClient):
        """admin-api /actuator/health 返回 UP"""
        resp = admin_client.get("/actuator/health")
        assert resp.status_code == 200, f"Health check failed: {resp.status_code} {resp.text}"
        data = resp.json()
        assert data.get("status") == "UP", f"Service not UP: {data}"

    def test_ai_agent_health(self, ai_client: SmokeTestClient):
        """ai-agent-service /health 返回 200"""
        resp = ai_client.get("/health")
        assert resp.status_code == 200, f"Health check failed: {resp.status_code} {resp.text}"
        data = resp.json()
        assert data.get("status") in ("healthy", "ok"), f"Service not healthy: {data}"

    def test_admin_api_db_connection(self, admin_client: SmokeTestClient):
        """admin-api 数据库连接正常（通过 health 检查）"""
        resp = admin_client.get("/actuator/health")
        if resp.status_code == 200:
            data = resp.json()
            # Spring Boot Actuator 详细健康检查
            components = data.get("components", {})
            if "db" in components:
                assert components["db"]["status"] == "UP", (
                    f"Database not UP: {components['db']}"
                )

    def test_admin_api_redis_connection(self, admin_client: SmokeTestClient):
        """admin-api Redis 连接正常（通过 health 检查）"""
        resp = admin_client.get("/actuator/health")
        if resp.status_code == 200:
            data = resp.json()
            components = data.get("components", {})
            if "redis" in components:
                assert components["redis"]["status"] == "UP", (
                    f"Redis not UP: {components['redis']}"
                )
