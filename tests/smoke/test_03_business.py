"""
核心业务 API 冒烟测试 (P0)

覆盖：商品列表/详情、订单列表、客户列表查询。
"""

import pytest

from .helpers import SmokeTestClient, assert_success_response, assert_page_response


@pytest.mark.p0
@pytest.mark.business
class TestProductAPI:
    """商品 API 测试"""

    def test_product_list(self, authed_admin_client: SmokeTestClient):
        """商品列表查询"""
        resp = authed_admin_client.get("/api/admin/products", params={
            "page": 1,
            "size": 10,
        })
        data = assert_page_response(resp)
        page_data = data.get("data", data)
        # 验证返回数据结构
        records = page_data.get("records", page_data.get("items", []))
        assert isinstance(records, list), f"Expected list of products, got: {type(records)}"

    def test_product_list_with_keyword(self, authed_admin_client: SmokeTestClient):
        """商品列表关键字搜索"""
        resp = authed_admin_client.get("/api/admin/products", params={
            "page": 1,
            "size": 10,
            "keyword": "窗帘",
        })
        assert resp.status_code == 200, f"Product search failed: {resp.status_code}"

    def test_product_detail(self, authed_admin_client: SmokeTestClient):
        """商品详情查询"""
        # 先获取列表取第一个商品
        list_resp = authed_admin_client.get("/api/admin/products", params={
            "page": 1, "size": 1,
        })
        if list_resp.status_code != 200:
            pytest.skip("Cannot get product list")

        data = list_resp.json()
        page_data = data.get("data", data)
        records = page_data.get("records", page_data.get("items", []))
        if not records:
            pytest.skip("No products in database")

        product_id = records[0].get("id")
        assert product_id, "Product has no ID field"

        # 查询详情
        detail_resp = authed_admin_client.get(f"/api/admin/products/{product_id}")
        assert detail_resp.status_code == 200, (
            f"Product detail failed: {detail_resp.status_code}"
        )
        detail_data = detail_resp.json()
        product = detail_data.get("data", detail_data)
        assert product.get("id") == product_id or str(product.get("id")) == str(product_id)


@pytest.mark.p0
@pytest.mark.business
class TestOrderAPI:
    """订单 API 测试"""

    def test_order_list(self, authed_admin_client: SmokeTestClient):
        """订单列表查询"""
        resp = authed_admin_client.get("/api/admin/orders", params={
            "page": 1,
            "size": 10,
        })
        data = assert_page_response(resp)
        page_data = data.get("data", data)
        records = page_data.get("records", page_data.get("items", []))
        assert isinstance(records, list), f"Expected list of orders, got: {type(records)}"

    def test_order_list_filter_by_status(self, authed_admin_client: SmokeTestClient):
        """订单按状态过滤"""
        resp = authed_admin_client.get("/api/admin/orders", params={
            "page": 1,
            "size": 10,
            "status": "pending",
        })
        assert resp.status_code == 200, f"Order filter failed: {resp.status_code}"

    def test_order_detail(self, authed_admin_client: SmokeTestClient):
        """订单详情查询"""
        list_resp = authed_admin_client.get("/api/admin/orders", params={
            "page": 1, "size": 1,
        })
        if list_resp.status_code != 200:
            pytest.skip("Cannot get order list")

        data = list_resp.json()
        page_data = data.get("data", data)
        records = page_data.get("records", page_data.get("items", []))
        if not records:
            pytest.skip("No orders in database")

        order_id = records[0].get("id")
        detail_resp = authed_admin_client.get(f"/api/admin/orders/{order_id}")
        assert detail_resp.status_code == 200, (
            f"Order detail failed: {detail_resp.status_code}"
        )


@pytest.mark.p0
@pytest.mark.business
class TestCustomerAPI:
    """客户 API 测试"""

    def test_customer_list(self, authed_admin_client: SmokeTestClient):
        """客户列表查询"""
        resp = authed_admin_client.get("/api/admin/customers", params={
            "page": 1,
            "size": 10,
        })
        data = assert_page_response(resp)
        page_data = data.get("data", data)
        records = page_data.get("records", page_data.get("items", []))
        assert isinstance(records, list), f"Expected list of customers, got: {type(records)}"

    def test_customer_list_with_filter(self, authed_admin_client: SmokeTestClient):
        """客户列表带过滤条件"""
        resp = authed_admin_client.get("/api/admin/customers", params={
            "page": 1,
            "size": 10,
            "keyword": "test",
        })
        assert resp.status_code == 200, f"Customer filter failed: {resp.status_code}"
