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
        """admin-api 数据库连接正常（通过 health 检查）

        ⚠️ issue #8994 ④：**部署形态**下 `/actuator/health` 被 nginx 屏蔽返回 404
        （= `test_admin_api_health` 里那条安全断言），此时 DB 健康**不可判定** ⇒
        显式 `pytest.skip`。此前的写法 `if resp.status_code == 200:` 没有 else 分支
        ⇒ 404 时**零断言 PASSED**（SDQS DQ-4 假绿）。
        """
        resp = admin_client.get("/actuator/health")
        if resp.status_code != 200:
            pytest.skip(
                f"/actuator/health 在部署形态不可达（status={resp.status_code}，"
                f"nginx 屏蔽）⇒ DB 健康不可判定（issue #8994 ④）"
            )
        components = resp.json().get("components", {})
        db = components.get("db")
        if not isinstance(db, dict):
            pytest.skip("health 未暴露 db 组件明细 ⇒ DB 健康不可判定（issue #8994 ④）")
        assert db.get("status") == "UP", f"Database not UP: {db}"

    def test_admin_api_redis_connection(self, admin_client: SmokeTestClient):
        """admin-api Redis 连接正常（通过 health 检查）

        同 `test_admin_api_db_connection`：404 / 无组件明细 ⇒ 显式 skip（issue #8994 ④），
        不许零断言 PASSED。
        """
        resp = admin_client.get("/actuator/health")
        if resp.status_code != 200:
            pytest.skip(
                f"/actuator/health 在部署形态不可达（status={resp.status_code}，"
                f"nginx 屏蔽）⇒ Redis 健康不可判定（issue #8994 ④）"
            )
        components = resp.json().get("components", {})
        redis = components.get("redis")
        if not isinstance(redis, dict):
            pytest.skip("health 未暴露 redis 组件明细 ⇒ Redis 健康不可判定（issue #8994 ④）")
        assert redis.get("status") == "UP", f"Redis not UP: {redis}"
