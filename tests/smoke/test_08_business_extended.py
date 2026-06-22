"""
业务扩展冒烟测试 (P1) - 第二波

覆盖：
- 商品完整 CRUD（含分类、搜索、更新、删除）
- 加工项 CRUD（含价格计算）
- 客户完整管理（创建、搜索、详情、更新）
- 用户/员工管理（列表、创建、状态切换、密码重置）

依赖：第一波测试创建的分类、加工分类数据。如缺失会自动尝试创建或跳过。
"""

import time
import uuid

import pytest

from .helpers import SmokeTestClient, assert_success_response


def _ts_suffix() -> str:
    """生成测试数据唯一后缀（毫秒级 + 短随机串）"""
    return f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"


def _extract_records(resp_json: dict) -> list:
    """从响应中提取列表数据，兼容 records / items / 直接列表 三种格式"""
    payload = resp_json.get("data", resp_json) if isinstance(resp_json, dict) else resp_json
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("records", payload.get("items", []))
    return []


def _extract_data(resp_json: dict) -> dict:
    """提取响应 data 体"""
    if not isinstance(resp_json, dict):
        return {}
    return resp_json.get("data", resp_json) or {}


def _get_or_create_category(client: SmokeTestClient) -> str:
    """获取或创建一个商品分类，返回 categoryId（不存在/失败返回空串）"""
    resp = client.get("/api/admin/categories")
    if resp.status_code == 200:
        tree = _extract_data(resp.json())
        nodes = tree if isinstance(tree, list) else _extract_records(resp.json())
        if nodes:
            return str(nodes[0].get("id", ""))

    # 尝试创建
    create_resp = client.post("/api/admin/categories", json={
        "name": f"测试分类-{_ts_suffix()}",
        "sortOrder": 999,
    })
    if create_resp.status_code == 200:
        return str(_extract_data(create_resp.json()).get("id", ""))
    return ""


def _get_or_create_processing_category(client: SmokeTestClient) -> str:
    """获取或创建一个加工分类，返回 id"""
    resp = client.get("/api/admin/processing-categories")
    if resp.status_code == 200:
        nodes = _extract_data(resp.json())
        if isinstance(nodes, list) and nodes:
            return str(nodes[0].get("id", ""))

    create_resp = client.post("/api/admin/processing-categories", json={
        "name": f"测试加工分类-{_ts_suffix()}",
        "sortOrder": 999,
    })
    if create_resp.status_code == 200:
        return str(_extract_data(create_resp.json()).get("id", ""))
    return ""


# ========================================================
# 商品完整 CRUD
# ========================================================
@pytest.mark.p1
@pytest.mark.business
class TestProductCRUD:
    """商品完整 CRUD 流程"""

    def test_create_product(self, authed_admin_client: SmokeTestClient):
        """POST 创建商品（含名称、价格、描述）"""
        category_id = _get_or_create_category(authed_admin_client)
        if not category_id:
            pytest.skip("无可用商品分类，跳过商品创建测试")

        suffix = _ts_suffix()
        payload = {
            "name": f"冒烟测试商品-{suffix}",
            "categoryId": category_id,
            "basePrice": 199.99,
            "description": "smoke test product description",
            "status": "off_sale",
            "stock": 100,
            "stockWarningThreshold": 10,
        }
        resp = authed_admin_client.post("/api/admin/products", json=payload)
        if resp.status_code == 404:
            pytest.skip("商品创建接口不存在")
        assert resp.status_code == 200, f"Create product failed: {resp.status_code} {resp.text[:300]}"
        data = assert_success_response(resp)
        product = _extract_data(data)
        product_id = product.get("id")
        assert product_id, f"创建后无商品ID: {product}"
        assert product.get("name") == payload["name"]

        # 立即清理
        authed_admin_client.delete(f"/api/admin/products/{product_id}")

    def test_search_products(self, authed_admin_client: SmokeTestClient):
        """GET /search?keyword=xxx 搜索商品（不存在则尝试 keyword 参数过滤）"""
        # 优先尝试 /search 子路径
        resp = authed_admin_client.get(
            "/api/admin/products/search", params={"keyword": "测试"}
        )
        if resp.status_code == 404:
            # 回退到主路径 keyword 过滤
            resp = authed_admin_client.get(
                "/api/admin/products",
                params={"page": 1, "size": 10, "keyword": "测试"},
            )
        assert resp.status_code == 200, f"Search products failed: {resp.status_code} {resp.text[:300]}"
        records = _extract_records(resp.json())
        assert isinstance(records, list), f"搜索返回非列表: {type(records)}"

    def test_update_product(self, authed_admin_client: SmokeTestClient):
        """PUT 更新商品信息"""
        category_id = _get_or_create_category(authed_admin_client)
        if not category_id:
            pytest.skip("无可用商品分类")

        suffix = _ts_suffix()
        create_resp = authed_admin_client.post("/api/admin/products", json={
            "name": f"待更新商品-{suffix}",
            "categoryId": category_id,
            "basePrice": 99.0,
            "description": "before update",
            "status": "off_sale",
        })
        if create_resp.status_code == 404:
            pytest.skip("商品创建接口不存在")
        assert create_resp.status_code == 200, f"前置创建失败: {create_resp.text[:300]}"
        product_id = _extract_data(create_resp.json()).get("id")
        assert product_id, "前置创建未返回ID"

        try:
            update_payload = {
                "name": f"已更新商品-{suffix}",
                "categoryId": category_id,
                "basePrice": 299.0,
                "description": "after update",
                "status": "off_sale",
            }
            update_resp = authed_admin_client.put(
                f"/api/admin/products/{product_id}", json=update_payload
            )
            assert update_resp.status_code == 200, (
                f"Update product failed: {update_resp.status_code} {update_resp.text[:300]}"
            )
            updated = _extract_data(update_resp.json())
            assert updated.get("name") == update_payload["name"], "名称未更新"
        finally:
            authed_admin_client.delete(f"/api/admin/products/{product_id}")

    def test_delete_product(self, authed_admin_client: SmokeTestClient):
        """DELETE 删除商品"""
        category_id = _get_or_create_category(authed_admin_client)
        if not category_id:
            pytest.skip("无可用商品分类")

        create_resp = authed_admin_client.post("/api/admin/products", json={
            "name": f"待删除商品-{_ts_suffix()}",
            "categoryId": category_id,
            "basePrice": 1.0,
            "description": "to be deleted",
        })
        if create_resp.status_code == 404:
            pytest.skip("商品创建接口不存在")
        assert create_resp.status_code == 200, f"前置创建失败: {create_resp.text[:300]}"
        product_id = _extract_data(create_resp.json()).get("id")
        assert product_id, "前置创建未返回ID"

        del_resp = authed_admin_client.delete(f"/api/admin/products/{product_id}")
        assert del_resp.status_code == 200, (
            f"Delete product failed: {del_resp.status_code} {del_resp.text[:300]}"
        )

        # 验证已删除（再次 GET 应返回非 200 或 data 为空）
        check_resp = authed_admin_client.get(f"/api/admin/products/{product_id}")
        if check_resp.status_code == 200:
            body = check_resp.json()
            # 软删除时 data 应为空或 success 为 false
            data = _extract_data(body)
            assert not data or body.get("success") is False, (
                f"删除后仍能查询到商品: {body}"
            )

    def test_product_with_category(self, authed_admin_client: SmokeTestClient):
        """创建含分类ID的商品并验证 categoryId 持久化"""
        category_id = _get_or_create_category(authed_admin_client)
        if not category_id:
            pytest.skip("无可用商品分类")

        suffix = _ts_suffix()
        payload = {
            "name": f"含分类商品-{suffix}",
            "categoryId": category_id,
            "basePrice": 50.0,
            "description": "with category",
        }
        resp = authed_admin_client.post("/api/admin/products", json=payload)
        if resp.status_code == 404:
            pytest.skip("商品创建接口不存在")
        assert resp.status_code == 200, f"Create with category failed: {resp.text[:300]}"
        product = _extract_data(resp.json())
        product_id = product.get("id")
        assert product_id, "创建未返回ID"

        try:
            # 拉详情核对 categoryId
            detail_resp = authed_admin_client.get(f"/api/admin/products/{product_id}")
            assert detail_resp.status_code == 200
            detail = _extract_data(detail_resp.json())
            returned_cat = str(detail.get("categoryId") or detail.get("category_id") or "")
            assert returned_cat == str(category_id), (
                f"分类未关联: expected={category_id}, got={returned_cat}"
            )
        finally:
            authed_admin_client.delete(f"/api/admin/products/{product_id}")


# ========================================================
# 加工项管理
# ========================================================
@pytest.mark.p1
@pytest.mark.business
class TestProcessingItemAPI:
    """加工项 API 测试"""

    def test_create_processing_item(self, authed_admin_client: SmokeTestClient):
        """POST 创建加工项"""
        category_id = _get_or_create_processing_category(authed_admin_client)
        if not category_id:
            pytest.skip("无可用加工分类")

        suffix = _ts_suffix()
        payload = {
            "name": f"加工项-{suffix[:12]}",
            "categoryId": category_id,
            "pricingMethod": "per_meter",
            "unitPrice": 25.0,
            "unit": "元/米",
            "minQuantity": 1,
            "maxQuantity": 999,
            "description": "smoke test processing item",
            "processingDays": 1,
            "status": "active",
        }
        resp = authed_admin_client.post("/api/admin/processing-items", json=payload)
        if resp.status_code == 404:
            pytest.skip("加工项创建接口不存在")
        assert resp.status_code == 200, (
            f"Create processing item failed: {resp.status_code} {resp.text[:300]}"
        )
        item = _extract_data(resp.json())
        item_id = item.get("id")
        assert item_id, f"创建后无加工项ID: {item}"

        # 清理
        authed_admin_client.delete(f"/api/admin/processing-items/{item_id}")

    def test_list_processing_items(self, authed_admin_client: SmokeTestClient):
        """GET 加工项列表"""
        resp = authed_admin_client.get(
            "/api/admin/processing-items", params={"page": 1, "size": 10}
        )
        if resp.status_code == 404:
            pytest.skip("加工项列表接口不存在")
        assert resp.status_code == 200, (
            f"List processing items failed: {resp.status_code} {resp.text[:300]}"
        )
        records = _extract_records(resp.json())
        assert isinstance(records, list), f"加工项列表返回非列表: {type(records)}"

    def test_calculate_price(self, authed_admin_client: SmokeTestClient):
        """POST /calculate 价格计算"""
        category_id = _get_or_create_processing_category(authed_admin_client)
        if not category_id:
            pytest.skip("无可用加工分类")

        # 先创建一个加工项以提供可计算的 ID
        create_resp = authed_admin_client.post("/api/admin/processing-items", json={
            "name": f"计价-{_ts_suffix()[:12]}",
            "categoryId": category_id,
            "pricingMethod": "per_meter",
            "unitPrice": 10.0,
            "unit": "元/米",
        })
        if create_resp.status_code == 404:
            pytest.skip("加工项创建接口不存在")
        assert create_resp.status_code == 200, f"前置创建失败: {create_resp.text[:300]}"
        item_id = _extract_data(create_resp.json()).get("id")
        assert item_id

        try:
            calc_resp = authed_admin_client.post(
                "/api/admin/processing-items/calculate",
                json={
                    "processingItemId": item_id,
                    "quantity": 5,
                },
            )
            if calc_resp.status_code == 404:
                pytest.skip("价格计算接口不存在")
            assert calc_resp.status_code == 200, (
                f"Calculate price failed: {calc_resp.status_code} {calc_resp.text[:300]}"
            )
            result = _extract_data(calc_resp.json())
            # 价格字段名兼容 totalPrice / total / price
            price_value = (
                result.get("totalPrice")
                or result.get("total")
                or result.get("price")
                or result.get("amount")
            )
            assert price_value is not None, f"计算结果无价格字段: {result}"
        finally:
            authed_admin_client.delete(f"/api/admin/processing-items/{item_id}")

    def test_delete_processing_item(self, authed_admin_client: SmokeTestClient):
        """DELETE 删除加工项"""
        category_id = _get_or_create_processing_category(authed_admin_client)
        if not category_id:
            pytest.skip("无可用加工分类")

        create_resp = authed_admin_client.post("/api/admin/processing-items", json={
            "name": f"删除-{_ts_suffix()[:12]}",
            "categoryId": category_id,
            "pricingMethod": "fixed",
            "unitPrice": 1.0,
        })
        if create_resp.status_code == 404:
            pytest.skip("加工项创建接口不存在")
        assert create_resp.status_code == 200
        item_id = _extract_data(create_resp.json()).get("id")
        assert item_id

        del_resp = authed_admin_client.delete(f"/api/admin/processing-items/{item_id}")
        assert del_resp.status_code == 200, (
            f"Delete processing item failed: {del_resp.status_code} {del_resp.text[:300]}"
        )


# ========================================================
# 客户完整管理
# ========================================================
@pytest.mark.p1
@pytest.mark.business
class TestCustomerCRUD:
    """客户 API 完整管理"""

    def test_create_customer(self, authed_admin_client: SmokeTestClient):
        """POST 创建客户（接口可能不开放，404/405 时跳过）"""
        suffix = _ts_suffix()
        payload = {
            "name": f"测试客户-{suffix}",
            "phone": f"139{suffix[-8:]}",
            "sourceChannel": "manual",
            "vipLevel": "normal",
            "remark": "smoke test",
        }
        resp = authed_admin_client.post("/api/admin/customers", json=payload)
        if resp.status_code in (404, 405):
            pytest.skip(f"客户创建接口不存在: status={resp.status_code}")
        assert resp.status_code == 200, (
            f"Create customer failed: {resp.status_code} {resp.text[:300]}"
        )
        customer = _extract_data(resp.json())
        customer_id = customer.get("id")
        assert customer_id, f"创建后无客户ID: {customer}"

    def test_search_customers(self, authed_admin_client: SmokeTestClient):
        """GET /search?keyword=xxx 搜索（不存在则回退到 keyword 过滤）"""
        resp = authed_admin_client.get(
            "/api/admin/customers/search", params={"keyword": "test"}
        )
        if resp.status_code == 404:
            resp = authed_admin_client.get(
                "/api/admin/customers",
                params={"page": 1, "size": 10, "keyword": "test"},
            )
        assert resp.status_code == 200, (
            f"Search customers failed: {resp.status_code} {resp.text[:300]}"
        )
        records = _extract_records(resp.json())
        assert isinstance(records, list)

    def test_customer_detail(self, authed_admin_client: SmokeTestClient):
        """GET /{id} 详情"""
        list_resp = authed_admin_client.get(
            "/api/admin/customers", params={"page": 1, "size": 1}
        )
        if list_resp.status_code != 200:
            pytest.skip(f"无法获取客户列表: {list_resp.status_code}")
        records = _extract_records(list_resp.json())
        if not records:
            pytest.skip("数据库中无客户数据")

        customer_id = records[0].get("id")
        assert customer_id, "客户记录缺少 id 字段"

        detail_resp = authed_admin_client.get(f"/api/admin/customers/{customer_id}")
        assert detail_resp.status_code == 200, (
            f"Customer detail failed: {detail_resp.status_code} {detail_resp.text[:300]}"
        )
        detail = _extract_data(detail_resp.json())
        # 详情可能返回扁平 customer 或嵌套结构
        returned_id = detail.get("id") or (detail.get("customer") or {}).get("id")
        assert str(returned_id) == str(customer_id), (
            f"详情ID不匹配: expected={customer_id}, got={returned_id}"
        )

    def test_update_customer(self, authed_admin_client: SmokeTestClient):
        """PUT 更新客户信息"""
        list_resp = authed_admin_client.get(
            "/api/admin/customers", params={"page": 1, "size": 1}
        )
        if list_resp.status_code != 200:
            pytest.skip("无法获取客户列表")
        records = _extract_records(list_resp.json())
        if not records:
            pytest.skip("数据库中无客户数据")

        customer = records[0]
        customer_id = customer.get("id")
        new_remark = f"smoke-updated-{_ts_suffix()}"
        payload = dict(customer)
        payload["remark"] = new_remark

        resp = authed_admin_client.put(
            f"/api/admin/customers/{customer_id}", json=payload
        )
        assert resp.status_code == 200, (
            f"Update customer failed: {resp.status_code} {resp.text[:300]}"
        )


# ========================================================
# 用户/员工管理
# ========================================================
@pytest.mark.p1
@pytest.mark.business
class TestUserManagement:
    """用户/员工管理 API"""

    def test_list_users(self, authed_admin_client: SmokeTestClient):
        """GET 用户列表"""
        resp = authed_admin_client.get(
            "/api/admin/users", params={"page": 1, "size": 10}
        )
        if resp.status_code == 404:
            pytest.skip("用户列表接口不存在")
        assert resp.status_code == 200, (
            f"List users failed: {resp.status_code} {resp.text[:300]}"
        )
        records = _extract_records(resp.json())
        assert isinstance(records, list), f"用户列表返回非列表: {type(records)}"

    def test_create_user(self, authed_admin_client: SmokeTestClient):
        """POST 创建新用户"""
        suffix = _ts_suffix()
        phone = f"138{suffix[-8:]}"
        payload = {
            "username": phone,
            "phone": phone,
            "password": "Smoke@2024",
            "name": f"测试员工-{suffix}",
            "role": "operator",
        }
        resp = authed_admin_client.post("/api/admin/users", json=payload)
        if resp.status_code == 404:
            pytest.skip("用户创建接口不存在")
        assert resp.status_code == 200, (
            f"Create user failed: {resp.status_code} {resp.text[:300]}"
        )
        user = _extract_data(resp.json())
        user_id = user.get("id")
        assert user_id, f"创建后无用户ID: {user}"

        # 清理
        authed_admin_client.delete(f"/api/admin/users/{user_id}")

    def test_toggle_user_status(self, authed_admin_client: SmokeTestClient):
        """PUT /{id}/status 状态变更"""
        # 先创建一个用户用于切换状态，避免影响现有账号
        suffix = _ts_suffix()
        phone = f"137{suffix[-8:]}"
        create_resp = authed_admin_client.post("/api/admin/users", json={
            "username": phone,
            "phone": phone,
            "password": "Smoke@2024",
            "name": f"状态切换测试-{suffix}",
            "role": "operator",
        })
        if create_resp.status_code == 404:
            pytest.skip("用户创建接口不存在")
        if create_resp.status_code != 200:
            pytest.skip(f"前置创建用户失败，跳过状态切换测试: {create_resp.status_code}")
        user_id = _extract_data(create_resp.json()).get("id")
        assert user_id

        try:
            # 禁用
            disable_resp = authed_admin_client.put(
                f"/api/admin/users/{user_id}/status", json={"status": "disabled"}
            )
            if disable_resp.status_code == 404:
                pytest.skip("用户状态切换接口不存在")
            assert disable_resp.status_code == 200, (
                f"Disable user failed: {disable_resp.status_code} {disable_resp.text[:300]}"
            )
            # 启用
            enable_resp = authed_admin_client.put(
                f"/api/admin/users/{user_id}/status", json={"status": "active"}
            )
            assert enable_resp.status_code == 200, (
                f"Enable user failed: {enable_resp.status_code} {enable_resp.text[:300]}"
            )
        finally:
            authed_admin_client.delete(f"/api/admin/users/{user_id}")

    def test_reset_password(self, authed_admin_client: SmokeTestClient):
        """PUT /{id}/reset-password 密码重置"""
        suffix = _ts_suffix()
        phone = f"136{suffix[-8:]}"
        create_resp = authed_admin_client.post("/api/admin/users", json={
            "username": phone,
            "phone": phone,
            "password": "Smoke@2024",
            "name": f"密码重置测试-{suffix}",
            "role": "operator",
        })
        if create_resp.status_code == 404:
            pytest.skip("用户创建接口不存在")
        if create_resp.status_code != 200:
            pytest.skip(f"前置创建用户失败: {create_resp.status_code}")
        user_id = _extract_data(create_resp.json()).get("id")
        assert user_id

        try:
            # 优先尝试 PUT /reset-password
            reset_resp = authed_admin_client.put(
                f"/api/admin/users/{user_id}/reset-password",
                json={"newPassword": "Reset@2024"},
            )
            if reset_resp.status_code == 404:
                # 回退到 POST
                reset_resp = authed_admin_client.post(
                    f"/api/admin/users/{user_id}/reset-password",
                    json={"newPassword": "Reset@2024"},
                )
            if reset_resp.status_code == 404:
                pytest.skip("密码重置接口不存在")
            assert reset_resp.status_code == 200, (
                f"Reset password failed: {reset_resp.status_code} {reset_resp.text[:300]}"
            )
        finally:
            authed_admin_client.delete(f"/api/admin/users/{user_id}")
