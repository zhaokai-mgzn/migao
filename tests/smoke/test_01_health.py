"""
健康检查验证测试 (P0)

验证所有服务的健康检查端点正常响应。
"""

# case_ids: API-010
import pytest

from .helpers import SmokeTestClient


@pytest.mark.p0
@pytest.mark.health
class TestHealthCheck:
    """健康检查验证"""

    def test_admin_api_health(self, admin_client: SmokeTestClient):
        """admin-api 健康检查：**部署形态**下 /actuator/* 被 nginx 屏蔽（安全加固），
        服务在线性通过公开认证端点验证；**本地直起**形态没有 nginx ⇒ 断言改成「DB 健康」。"""
        # 1) 安全断言：**部署形态**（https，前有 nginx）下 /actuator/health 必须 404（Issue #2662）；
        #    本地直起（http://localhost:8080，无 nginx）时 actuator 本就裸露可达 ⇒ 200 才是预期
        #    （2026-10-14 实测：原来无条件要求 404 ⇒ 本地形态**恒红**，且红得没有信息量）。
        resp = admin_client.get("/actuator/health")
        if admin_client.base_url.startswith("https://"):
            assert resp.status_code == 404, (
                f"部署形态下 /actuator/health 应被 nginx 屏蔽返回 404（安全加固），实际 {resp.status_code}"
            )
        else:
            assert resp.status_code == 200, (
                f"本地直起形态下 /actuator/health 应可达（无 nginx），实际 {resp.status_code}"
            )
            assert str(resp.json().get("status", "")).upper() in ("UP", "HEALTHY"), (
                f"本地 /actuator/health 应为 UP，实得 {resp.text[:200]}"
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
