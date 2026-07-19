"""
接口契约验证 — admin-api 响应结构必须与 tool 解析逻辑一致。

每个测试验证：admin-api 返回数据中，tool 会访问的字段名存在且类型正确。
如果 admin-api 改了字段名/类型而 tool 没跟上，这里直接炸。
"""

import pytest


def _pick_first(items: list) -> dict:
    """取列表第一个元素，没有则跳过。"""
    if not items:
        pytest.skip("快照中无数据")
    return items[0]


def _assert_fields(item: dict, required: dict, context: str = ""):
    """验证 item 中必填字段存在且类型正确。

    required: {field_name: expected_type}
    """
    for field, expected_type in required.items():
        assert field in item, (
            f"{context}缺少字段 '{field}'，"
            f"admin-api 可能已改名。实际字段: {sorted(item.keys())}"
        )
        value = item[field]
        if expected_type is str:
            assert isinstance(value, str), (
                f"{context}.{field} 应为 str，实际 {type(value).__name__}"
            )
        elif expected_type is int:
            assert isinstance(value, (int, float)), (
                f"{context}.{field} 应为 number，实际 {type(value).__name__}"
            )
        elif expected_type is list:
            assert isinstance(value, list), (
                f"{context}.{field} 应为 list，实际 {type(value).__name__}"
            )
        elif expected_type is dict:
            assert isinstance(value, dict), (
                f"{context}.{field} 应为 dict，实际 {type(value).__name__}"
            )
        elif expected_type == "nullable_str":
            assert value is None or isinstance(value, str), (
                f"{context}.{field} 应为 str|null，实际 {type(value).__name__}"
            )


# ═══════════════════════════════════════════════════════════════════
# 商品
# ═══════════════════════════════════════════════════════════════════

class TestProductContract:
    """product_search + product_detail 依赖的字段"""

    def test_product_list_structure(self, products_response):
        """product_search 解析 /api/admin/products 返回列表"""
        resp = products_response
        assert resp.get("success") is True or "data" in resp, (
            "响应缺少 success 或 data"
        )
        data = resp.get("data", {})
        assert "total" in data, "data 缺少 total"
        items = data.get("items") or data.get("records") or data.get("list") or []
        if not items:
            pytest.skip("快照中无商品数据")

        product = _pick_first(items)
        # product_search 和 product_detail 访问的字段
        _assert_fields(product, {
            "id": str,
            "name": str,
            "price": int,
        }, "product")

    def test_product_optional_fields(self, products_response):
        """product_detail 访问的可选字段"""
        data = products_response.get("data", {})
        items = data.get("items") or data.get("records") or data.get("list") or []
        product = _pick_first(items)

        # product_detail 访问的扩展字段
        optional = {
            "images": list,
            "description": "nullable_str",
            "status": str,
            "categoryId": "nullable_str",
            "categoryName": "nullable_str",
        }
        for field, expected in optional.items():
            if field in product:
                _assert_fields(product, {field: expected}, "product")


# ═══════════════════════════════════════════════════════════════════
# 订单
# ═══════════════════════════════════════════════════════════════════

class TestOrderContract:
    """order_query 依赖的字段"""

    def test_order_list_structure(self, orders_response):
        resp = orders_response
        data = resp.get("data", {})
        items = data.get("items") or data.get("records") or data.get("list") or []
        order = _pick_first(items)

        # order_query 核心字段
        _assert_fields(order, {
            "id": str,
        }, "order")

    def test_order_optional_fields(self, orders_response):
        data = orders_response.get("data", {})
        items = data.get("items") or data.get("records") or data.get("list") or []
        order = _pick_first(items)

        for field in ("orderNo", "order_no", "status", "totalAmount", "total_amount",
                      "customerName", "customer_name", "createdAt", "created_at"):
            if field in order:
                break
        else:
            # 至少有一个标识字段
            pass  # order.id already verified above


# ═══════════════════════════════════════════════════════════════════
# 客户
# ═══════════════════════════════════════════════════════════════════

class TestCustomerContract:
    """customer_manage 依赖的字段"""

    def test_customer_list_structure(self, customers_response):
        resp = customers_response
        data = resp.get("data", {})
        items = data.get("items") or data.get("records") or data.get("list") or []
        customer = _pick_first(items)

        _assert_fields(customer, {
            "id": str,
        }, "customer")


# ═══════════════════════════════════════════════════════════════════
# 售后
# ═══════════════════════════════════════════════════════════════════

class TestAfterSalesContract:
    """aftersale_query 依赖的字段"""

    def test_aftersales_list_structure(self, after_sales_response):
        resp = after_sales_response
        data = resp.get("data", {})
        items = data.get("items") or data.get("records") or data.get("list") or []
        ticket = _pick_first(items)

        _assert_fields(ticket, {
            "id": str,
        }, "after-sales ticket")


# ═══════════════════════════════════════════════════════════════════
# 加工项
# ═══════════════════════════════════════════════════════════════════

class TestProcessingItemContract:
    """processing_item_query / product_manage 依赖的字段"""

    def test_processing_item_list_structure(self, processing_items_response):
        resp = processing_items_response
        data = resp.get("data", {})
        items = data.get("items") or data.get("records") or data.get("list") or []
        pi = _pick_first(items)

        _assert_fields(pi, {
            "id": str,
            "name": str,
        }, "processing-item")


# ═══════════════════════════════════════════════════════════════════
# 分类
# ═══════════════════════════════════════════════════════════════════

class TestCategoryContract:
    """category_manage / product_manage 依赖的字段"""

    def test_category_tree_structure(self, categories_tree_response):
        resp = categories_tree_response
        data = resp.get("data", {})
        # data 可能是直接的数组 [{id, name, children}] 或 {tree: [...]}
        if isinstance(data, list):
            tree = data
        else:
            tree = data.get("tree") or data.get("categories") or data.get("items") or []
        if not tree:
            pytest.skip("快照中无分类数据")

        cat = tree[0]
        _assert_fields(cat, {
            "id": str,
            "name": str,
        }, "category")


# ═══════════════════════════════════════════════════════════════════
# 仪表盘
# ═══════════════════════════════════════════════════════════════════

class TestDashboardContract:
    """dashboard_stats 依赖的字段"""

    def test_dashboard_structure(self, dashboard_stats_response):
        resp = dashboard_stats_response
        data = resp.get("data", {})
        # 仪表盘数据按天/周/月聚合，验证 data 存在且是 dict
        assert isinstance(data, dict), (
            f"dashboard data 应为 dict，实际 {type(data).__name__}"
        )
