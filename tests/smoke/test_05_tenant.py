"""
多租户隔离测试 (P1)

覆盖：租户 A 无法查到租户 B 的数据、Service Token 认证正确性。

隔离验证策略：
1. 主查询：验证当前租户 token 查询返回的记录均属于本租户（过滤验证）
2. 对照组：用租户 A 的 token 带上不存在/另一租户的 tenantId 查询 header/参数，
   验证后端不会信任客户端传入的 tenantId（仅能看到本租户数据）
"""

import pytest

from .config import EnvConfig
from .helpers import SmokeTestClient, assert_success_response


# 用于对照组的“另一租户”ID：远离当前租户且不可能存在的值。
_FOREIGN_TENANT_ID = 999_999_999


def _records_of(resp) -> list:
    """从分页响应中提取 records/items 列表。"""
    if resp.status_code != 200:
        return []
    data = resp.json()
    page_data = data.get("data", data)
    return page_data.get("records", page_data.get("items", []))


@pytest.mark.p1
@pytest.mark.tenant
class TestTenantIsolation:
    """多租户数据隔离测试"""

    def test_tenant_a_cannot_see_tenant_b_products(
        self, authed_admin_client: SmokeTestClient, config: EnvConfig
    ):
        """租户 A 无法查到租户 B 的商品数据

        验证逻辑：
        1. 用当前租户登录查询商品，验证返回记录均属于当前租户。
        2. 对照组：用同一 token 携带另一租户的 tenantId 查询商品，
           验证后端不会信任请求传入的 tenantId 参数。期望：
           - 403/404 被拒绝，或
           - 200 但记录仍全部属于当前租户（严格隔离）
        """
        # 1) 主查询：返回记录必须全部属于当前租户
        resp = authed_admin_client.get("/api/admin/products", params={
            "page": 1,
            "size": 50,
        })
        if resp.status_code != 200:
            pytest.skip("Cannot get product list")

        for record in _records_of(resp):
            tenant_id = record.get("tenantId", record.get("tenant_id"))
            if tenant_id is not None:
                assert str(tenant_id) == str(config.tenant_id), (
                    f"Data leak! Found product with tenant_id={tenant_id}, "
                    f"expected {config.tenant_id}. Product ID: {record.get('id')}"
                )

        # 2) 对照组：伪装另一租户的 tenantId/header 请求同一接口
        foreign_resp = authed_admin_client.get(
            "/api/admin/products",
            params={"page": 1, "size": 50, "tenantId": _FOREIGN_TENANT_ID},
            headers={"X-Tenant-Id": str(_FOREIGN_TENANT_ID)},
        )
        # 隔离生效的几种合法表现：被拒绝，或返回仅本租户数据
        assert foreign_resp.status_code in (200, 400, 401, 403, 404), (
            f"Unexpected status when querying foreign tenant: "
            f"{foreign_resp.status_code} {foreign_resp.text[:200]}"
        )
        if foreign_resp.status_code == 200:
            for record in _records_of(foreign_resp):
                tenant_id = record.get("tenantId", record.get("tenant_id"))
                if tenant_id is not None:
                    assert str(tenant_id) != str(_FOREIGN_TENANT_ID), (
                        f"跨租户隔离失效！请求 tenantId={_FOREIGN_TENANT_ID} 返回了外部租户记录: "
                        f"product_id={record.get('id')}, tenant_id={tenant_id}"
                    )
                    assert str(tenant_id) == str(config.tenant_id), (
                        f"跨租户数据泄露！预期仅返回本租户 {config.tenant_id} 数据，"
                        f"实际返回 tenant_id={tenant_id}"
                    )

    def test_tenant_a_cannot_see_tenant_b_orders(
        self, authed_admin_client: SmokeTestClient, config: EnvConfig
    ):
        """租户 A 无法查到租户 B 的订单数据（包含对照组）"""
        resp = authed_admin_client.get("/api/admin/orders", params={
            "page": 1,
            "size": 50,
        })
        if resp.status_code != 200:
            pytest.skip("Cannot get order list")

        for record in _records_of(resp):
            tenant_id = record.get("tenantId", record.get("tenant_id"))
            if tenant_id is not None:
                assert str(tenant_id) == str(config.tenant_id), (
                    f"Data leak! Found order with tenant_id={tenant_id}, "
                    f"expected {config.tenant_id}. Order ID: {record.get('id')}"
                )

        # 对照组：伪装外部租户 ID 请求
        foreign_resp = authed_admin_client.get(
            "/api/admin/orders",
            params={"page": 1, "size": 50, "tenantId": _FOREIGN_TENANT_ID},
            headers={"X-Tenant-Id": str(_FOREIGN_TENANT_ID)},
        )
        assert foreign_resp.status_code in (200, 400, 401, 403, 404), (
            f"Unexpected status: {foreign_resp.status_code}"
        )
        if foreign_resp.status_code == 200:
            for record in _records_of(foreign_resp):
                tenant_id = record.get("tenantId", record.get("tenant_id"))
                if tenant_id is not None:
                    assert str(tenant_id) == str(config.tenant_id), (
                        f"跨租户订单泄露！tenant_id={tenant_id}, order_id={record.get('id')}"
                    )

    def test_tenant_a_cannot_see_tenant_b_customers(
        self, authed_admin_client: SmokeTestClient, config: EnvConfig
    ):
        """租户 A 无法查到租户 B 的客户数据（包含对照组）"""
        resp = authed_admin_client.get("/api/admin/customers", params={
            "page": 1,
            "size": 50,
        })
        if resp.status_code != 200:
            pytest.skip("Cannot get customer list")

        for record in _records_of(resp):
            tenant_id = record.get("tenantId", record.get("tenant_id"))
            if tenant_id is not None:
                assert str(tenant_id) == str(config.tenant_id), (
                    f"Data leak! Found customer with tenant_id={tenant_id}, "
                    f"expected {config.tenant_id}. Customer ID: {record.get('id')}"
                )

        # 对照组：伪装外部租户 ID 请求
        foreign_resp = authed_admin_client.get(
            "/api/admin/customers",
            params={"page": 1, "size": 50, "tenantId": _FOREIGN_TENANT_ID},
            headers={"X-Tenant-Id": str(_FOREIGN_TENANT_ID)},
        )
        assert foreign_resp.status_code in (200, 400, 401, 403, 404), (
            f"Unexpected status: {foreign_resp.status_code}"
        )
        if foreign_resp.status_code == 200:
            for record in _records_of(foreign_resp):
                tenant_id = record.get("tenantId", record.get("tenant_id"))
                if tenant_id is not None:
                    assert str(tenant_id) == str(config.tenant_id), (
                        f"跨租户客户泄露！tenant_id={tenant_id}, customer_id={record.get('id')}"
                    )

    def test_foreign_tenant_resource_direct_access_denied(
        self, authed_admin_client: SmokeTestClient, config: EnvConfig
    ):
        """直接访问伪造的外部租户资源 ID 应被拒绝或 404

        使用足够大且不可能属于当前租户的 ID，期望返回 403/404；
        若返回 200，资源 tenant_id 必须为本租户才不算泄露。
        """
        foreign_id = 9_999_999_999
        resp = authed_admin_client.get(f"/api/admin/products/{foreign_id}")
        assert resp.status_code in (200, 400, 401, 403, 404), (
            f"期望跨租户资源访问被拒绝或 404，实际返回 {resp.status_code}: "
            f"{resp.text[:200]}"
        )
        if resp.status_code == 200:
            data = resp.json()
            product = data.get("data", data)
            tenant_id = product.get("tenantId", product.get("tenant_id"))
            assert tenant_id is None or str(tenant_id) == str(config.tenant_id), (
                f"跨租户资源泄露！tenant_id={tenant_id}"
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
