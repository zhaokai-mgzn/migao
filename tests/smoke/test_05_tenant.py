"""
多租户隔离测试 (P1)

覆盖：租户 A 无法查到租户 B 的数据、Service Token 认证正确性。
"""

import pytest

from .config import EnvConfig
from .helpers import SmokeTestClient, assert_success_response


@pytest.mark.p1
@pytest.mark.tenant
class TestTenantIsolation:
    """多租户数据隔离测试"""

    def test_tenant_a_cannot_see_tenant_b_products(
        self, authed_admin_client: SmokeTestClient, config: EnvConfig
    ):
        """租户 A 无法查到租户 B 的商品数据

        验证逻辑：
        1. 用当前租户登录查询商品
        2. 验证返回的所有商品都属于当前租户（通过 tenant_id 字段）
        """
        resp = authed_admin_client.get("/api/admin/products", params={
            "page": 1,
            "size": 50,
        })
        if resp.status_code != 200:
            pytest.skip("Cannot get product list")

        data = resp.json()
        page_data = data.get("data", data)
        records = page_data.get("records", page_data.get("items", []))

        # 如果有数据，验证所有记录属于当前租户
        for record in records:
            tenant_id = record.get("tenantId", record.get("tenant_id"))
            if tenant_id is not None:
                assert str(tenant_id) == str(config.tenant_id), (
                    f"Data leak! Found product with tenant_id={tenant_id}, "
                    f"expected {config.tenant_id}. Product ID: {record.get('id')}"
                )

    def test_tenant_a_cannot_see_tenant_b_orders(
        self, authed_admin_client: SmokeTestClient, config: EnvConfig
    ):
        """租户 A 无法查到租户 B 的订单数据"""
        resp = authed_admin_client.get("/api/admin/orders", params={
            "page": 1,
            "size": 50,
        })
        if resp.status_code != 200:
            pytest.skip("Cannot get order list")

        data = resp.json()
        page_data = data.get("data", data)
        records = page_data.get("records", page_data.get("items", []))

        for record in records:
            tenant_id = record.get("tenantId", record.get("tenant_id"))
            if tenant_id is not None:
                assert str(tenant_id) == str(config.tenant_id), (
                    f"Data leak! Found order with tenant_id={tenant_id}, "
                    f"expected {config.tenant_id}. Order ID: {record.get('id')}"
                )

    def test_tenant_a_cannot_see_tenant_b_customers(
        self, authed_admin_client: SmokeTestClient, config: EnvConfig
    ):
        """租户 A 无法查到租户 B 的客户数据"""
        resp = authed_admin_client.get("/api/admin/customers", params={
            "page": 1,
            "size": 50,
        })
        if resp.status_code != 200:
            pytest.skip("Cannot get customer list")

        data = resp.json()
        page_data = data.get("data", data)
        records = page_data.get("records", page_data.get("items", []))

        for record in records:
            tenant_id = record.get("tenantId", record.get("tenant_id"))
            if tenant_id is not None:
                assert str(tenant_id) == str(config.tenant_id), (
                    f"Data leak! Found customer with tenant_id={tenant_id}, "
                    f"expected {config.tenant_id}. Customer ID: {record.get('id')}"
                )


@pytest.mark.p1
@pytest.mark.tenant
class TestServiceTokenAuth:
    """Service Token 认证测试"""

    def test_service_token_access_internal_api(
        self, ai_client: SmokeTestClient, service_token_headers: dict
    ):
        """有效 Service Token 可访问内部 API"""
        resp = ai_client.get(
            "/api/internal/tools",
            headers=service_token_headers,
        )
        # 内部 API 需要 Service Token
        assert resp.status_code == 200, (
            f"Service token auth failed: {resp.status_code} {resp.text[:200]}"
        )

    def test_invalid_service_token_rejected(self, ai_client: SmokeTestClient):
        """无效 Service Token 被拒绝"""
        resp = ai_client.get(
            "/api/internal/tools",
            headers={"X-Service-Token": "invalid-token-12345"},
        )
        assert resp.status_code in (401, 403), (
            f"Expected 401/403 for invalid service token, got {resp.status_code}"
        )

    def test_no_service_token_rejected(self, ai_client: SmokeTestClient):
        """无 Service Token 访问内部 API 被拒绝"""
        resp = ai_client.get("/api/internal/tools")
        assert resp.status_code in (401, 403), (
            f"Expected 401/403 for missing service token, got {resp.status_code}"
        )
