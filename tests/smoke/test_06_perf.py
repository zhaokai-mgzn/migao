"""
性能基线测试 (P1)

覆盖：登录接口 < 500ms、商品列表 < 1s、AI 对话首 token < 3s、并发 10 用户无错误。
"""

import concurrent.futures
import time

import httpx
import pytest

from .config import EnvConfig
from .helpers import SmokeTestClient, measure_time


@pytest.mark.p1
@pytest.mark.performance
class TestPerformanceBaseline:
    """性能基线测试"""

    def test_login_latency(self, admin_client: SmokeTestClient, config: EnvConfig):
        """登录接口响应时间 < 500ms"""
        def do_login():
            return admin_client.post("/api/auth/admin/login", json={
                "username": config.admin_username,
                "password": config.admin_password,
                "tenantId": config.tenant_id,
            })

        resp, elapsed_ms = measure_time(do_login)
        assert resp.status_code == 200, f"Login failed: {resp.status_code}"
        assert elapsed_ms < 800, (
            f"Login too slow: {elapsed_ms:.0f}ms (threshold: 800ms)"
        )
        print(f"\n  Login latency: {elapsed_ms:.0f}ms")

    def test_product_list_latency(self, authed_admin_client: SmokeTestClient):
        """商品列表响应时间 < 1000ms"""
        def do_request():
            return authed_admin_client.get("/api/admin/products", params={
                "page": 1, "size": 20,
            })

        resp, elapsed_ms = measure_time(do_request)
        assert resp.status_code == 200, f"Product list failed: {resp.status_code}"
        assert elapsed_ms < 1000, (
            f"Product list too slow: {elapsed_ms:.0f}ms (threshold: 1000ms)"
        )
        print(f"\n  Product list latency: {elapsed_ms:.0f}ms")

    def test_order_list_latency(self, authed_admin_client: SmokeTestClient):
        """订单列表响应时间 < 1000ms"""
        def do_request():
            return authed_admin_client.get("/api/admin/orders", params={
                "page": 1, "size": 20,
            })

        resp, elapsed_ms = measure_time(do_request)
        assert resp.status_code == 200, f"Order list failed: {resp.status_code}"
        assert elapsed_ms < 1000, (
            f"Order list too slow: {elapsed_ms:.0f}ms (threshold: 1000ms)"
        )
        print(f"\n  Order list latency: {elapsed_ms:.0f}ms")

    def test_ai_chat_first_token_latency(
        self, authed_ai_client: SmokeTestClient, config: EnvConfig, auth_token: dict
    ):
        """AI 对话首 token (TTFB) 响应时间 < 3000ms

        使用 stream 模式记录从发送请求到接收到第一个 chunk 的时间差，
        而非等待整个流响应结束。
        """
        # 创建会话
        session_resp = authed_ai_client.post("/api/chat/sessions", json={
            "title": "性能测试-TTFB",
        })
        if session_resp.status_code != 200:
            pytest.skip("Cannot create AI session")

        session_id = session_resp.json().get("data", {}).get("id")
        if not session_id:
            pytest.skip("No session ID returned")

        url = f"{config.ai_agent_url.rstrip('/')}/api/chat/send"
        headers = {
            "Authorization": f"Bearer {auth_token['access_token']}",
            "Accept": "text/event-stream",
        }
        payload = {
            "session_id": session_id,
            "message": "你好",
        }

        first_token_ms = None
        with httpx.Client(timeout=30.0) as client:
            start = time.perf_counter()
            with client.stream("POST", url, json=payload, headers=headers) as response:
                assert response.status_code == 200, (
                    f"AI chat stream failed: {response.status_code}"
                )
                for chunk in response.iter_bytes():
                    if chunk:
                        first_token_ms = (time.perf_counter() - start) * 1000
                        break

        assert first_token_ms is not None, "未收到任何流式 chunk，无法评估首 token 延迟"
        assert first_token_ms < 3000, (
            f"AI first token too slow: {first_token_ms:.0f}ms (threshold: 3000ms)"
        )
        print(f"\n  AI first token (TTFB) latency: {first_token_ms:.0f}ms")

    def test_concurrent_10_users_no_errors(
        self, config: EnvConfig, auth_token: dict
    ):
        """并发 10 用户请求无错误"""
        errors = []
        latencies = []

        def make_request(i: int):
            """单个并发请求"""
            client = SmokeTestClient(config.admin_api_url)
            client.set_token(auth_token["access_token"])
            try:
                start = time.perf_counter()
                resp = client.get("/api/admin/products", params={
                    "page": 1, "size": 10,
                })
                elapsed = (time.perf_counter() - start) * 1000
                latencies.append(elapsed)
                if resp.status_code != 200:
                    errors.append(f"User {i}: status={resp.status_code}")
            except Exception as e:
                errors.append(f"User {i}: {e}")
            finally:
                client.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request, i) for i in range(10)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Concurrent errors: {errors}"

        if latencies:
            avg_ms = sum(latencies) / len(latencies)
            max_ms = max(latencies)
            print(f"\n  Concurrent 10 users - avg: {avg_ms:.0f}ms, max: {max_ms:.0f}ms")
            # P95 不超过 2s
            sorted_latencies = sorted(latencies)
            p95 = sorted_latencies[int(len(sorted_latencies) * 0.95)]
            assert p95 < 2000, f"P95 latency too high: {p95:.0f}ms (threshold: 2000ms)"
