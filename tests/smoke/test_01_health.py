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
        """admin-api 公网健康检查：/actuator/* 已被 nginx 屏蔽（安全加固），
        服务在线性通过公开认证端点验证"""
        # 1) 安全断言：/actuator/health 公网必须 404（nginx 屏蔽，Issue #2662）
        resp = admin_client.get("/actuator/health")
        assert resp.status_code == 404, (
            f"/actuator/health 应被 nginx 屏蔽返回 404（安全加固），实际 {resp.status_code}"
        )

        # 2) 在线性断言：公开端点 /api/auth/sms/login 空 body → 400/422（参数校验，服务在线）
        resp = admin_client.post("/api/auth/sms/login", json={})
        assert resp.status_code in (400, 422), (
            f"admin-api 应在线（登录端点参数校验响应），实际 {resp.status_code}: {resp.text[:200]}"
        )

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
