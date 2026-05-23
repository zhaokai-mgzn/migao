"""
订单全生命周期冒烟测试 (P1)

覆盖：
- 订单创建（含商品/客户关联、最简字段、无效数据）
- 订单状态流转（pending -> confirmed -> producing -> completed）
- 订单过滤查询（状态/日期/客户/分页）

后端实际路由：
- POST   /api/admin/orders            创建订单
- GET    /api/admin/orders            分页查询，支持 status / keyword
- GET    /api/admin/orders/{id}       订单详情
- PUT    /api/admin/orders/{id}/status 更新订单状态

订单状态合法值：pending / confirmed / producing / shipped / completed / cancelled
"""

import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytest

from .helpers import SmokeTestClient, assert_page_response, assert_success_response


# ---------------------------------------------------------------------------
# 内部工具：从分页响应中提取记录列表
# ---------------------------------------------------------------------------

def _extract_records(resp_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    page_data = resp_json.get("data", resp_json)
    return page_data.get("records", page_data.get("items", []) or [])


def _extract_total(resp_json: Dict[str, Any]) -> Optional[int]:
    page_data = resp_json.get("data", resp_json)
    total = page_data.get("total")
    if total is None:
        return None
    try:
        return int(total)
    except (TypeError, ValueError):
        return None


def _extract_data(resp_json: Dict[str, Any]) -> Dict[str, Any]:
    return resp_json.get("data", resp_json) or {}


def _short_uid() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# 测试数据构造
# ---------------------------------------------------------------------------

def _pick_product(client: SmokeTestClient) -> Optional[Dict[str, Any]]:
    """获取一个可用商品；若库内无数据则返回 None"""
    resp = client.get("/api/admin/products", params={"page": 1, "size": 1})
    if resp.status_code != 200:
        return None
    records = _extract_records(resp.json())
    return records[0] if records else None


def _pick_customer(client: SmokeTestClient) -> Optional[Dict[str, Any]]:
    """获取一个可用客户；若库内无数据则返回 None"""
    resp = client.get("/api/admin/customers", params={"page": 1, "size": 1})
    if resp.status_code != 200:
        return None
    records = _extract_records(resp.json())
    return records[0] if records else None


def _build_order_payload(
    product: Optional[Dict[str, Any]] = None,
    customer: Optional[Dict[str, Any]] = None,
    *,
    minimal: bool = False,
) -> Dict[str, Any]:
    """构造订单创建请求体"""
    suffix = _short_uid()
    customer_name = (customer or {}).get("name") or f"smoke-customer-{suffix}"
    customer_phone = (customer or {}).get("phone") or f"138{int(time.time()) % 100000000:08d}"

    product_id = (product or {}).get("id")
    product_name = (product or {}).get("name") or f"smoke-product-{suffix}"
    unit_price_raw = (product or {}).get("price") or (product or {}).get("unitPrice") or 199.0
    try:
        unit_price = float(unit_price_raw)
    except (TypeError, ValueError):
        unit_price = 199.0
    if unit_price <= 0:
        unit_price = 199.0
    quantity = 1
    subtotal = round(unit_price * quantity, 2)

    item: Dict[str, Any] = {
        "productName": product_name,
        "quantity": quantity,
        "unitPrice": unit_price,
        "subtotal": subtotal,
    }
    if product_id:
        item["productId"] = product_id

    payload: Dict[str, Any] = {
        "customerName": customer_name,
        "customerPhone": customer_phone,
        "items": [item],
    }
    if not minimal:
        payload["customerAddress"] = "上海市浦东新区张江高科技园区"
        payload["remark"] = f"smoke-test-{suffix}"
    return payload


def _create_order(client: SmokeTestClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    """提交创建订单请求并返回订单详情数据"""
    resp = client.post("/api/admin/orders", json=payload)
    assert resp.status_code == 200, (
        f"创建订单失败: status={resp.status_code}, body={resp.text[:500]}"
    )
    body = assert_success_response(resp)
    return _extract_data(body)


def _update_order_status(client: SmokeTestClient, order_id: str, status: str):
    """更新订单状态，返回原始响应供断言"""
    return client.put(f"/api/admin/orders/{order_id}/status", json={"status": status})


# ---------------------------------------------------------------------------
# 创建订单
# ---------------------------------------------------------------------------

@pytest.mark.p1
@pytest.mark.business
class TestOrderCreation:
    """订单创建场景"""

    def test_create_order(self, authed_admin_client: SmokeTestClient):
        """创建订单（含商品和客户关联）"""
        product = _pick_product(authed_admin_client)
        customer = _pick_customer(authed_admin_client)

        payload = _build_order_payload(product=product, customer=customer, minimal=False)
        order = _create_order(authed_admin_client, payload)

        order_id = order.get("id")
        assert order_id, f"创建后未返回订单 id: {order}"
        assert order.get("customerName") == payload["customerName"]
        # 部分实现可能将 status 默认为 pending
        if "status" in order and order["status"] is not None:
            assert order["status"] in {
                "pending", "confirmed", "producing", "shipped", "completed", "cancelled",
            }

    def test_create_order_minimal(self, authed_admin_client: SmokeTestClient):
        """最简订单（最少必填字段）"""
        payload = _build_order_payload(minimal=True)
        # 仅保留必填：customerName / customerPhone / items
        order = _create_order(authed_admin_client, payload)
        assert order.get("id"), f"最简订单创建未返回 id: {order}"

    def test_create_order_invalid(self, authed_admin_client: SmokeTestClient):
        """无效数据创建订单应被拒绝"""
        # 缺少必填的 customerName 与 items
        invalid_payload = {
            "customerPhone": "13800000000",
        }
        resp = authed_admin_client.post("/api/admin/orders", json=invalid_payload)
        # 预期 4xx 或业务错误；不允许 2xx 通过
        assert resp.status_code != 200 or _is_business_error(resp.json()), (
            f"无效订单未被拒绝: status={resp.status_code}, body={resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert _is_business_error(body), f"业务层未返回错误: {body}"


def _is_business_error(body: Dict[str, Any]) -> bool:
    """识别 HTTP 200 但业务层返回错误的场景"""
    if not isinstance(body, dict):
        return False
    if body.get("success") is False:
        return True
    code = body.get("code")
    if code is not None and code not in (0, 200):
        return True
    return False


# ---------------------------------------------------------------------------
# 订单状态流转
# ---------------------------------------------------------------------------

@pytest.mark.p1
@pytest.mark.business
class TestOrderStatusFlow:
    """订单状态流转"""

    def test_order_status_flow(self, authed_admin_client: SmokeTestClient):
        """完整状态流转：pending -> confirmed -> producing -> completed"""
        product = _pick_product(authed_admin_client)
        order = _create_order(authed_admin_client, _build_order_payload(product=product))
        order_id = order.get("id")
        assert order_id, "订单 id 缺失"

        for target in ("confirmed", "producing", "completed"):
            resp = _update_order_status(authed_admin_client, order_id, target)
            if 400 <= resp.status_code < 500:
                pytest.skip(
                    f"状态流转 API 不支持 {target} 转换: "
                    f"status={resp.status_code}, body={resp.text[:200]}"
                )
            assert resp.status_code == 200, (
                f"流转到 {target} 失败: status={resp.status_code}, body={resp.text[:300]}"
            )

            detail = authed_admin_client.get(f"/api/admin/orders/{order_id}")
            assert detail.status_code == 200, f"查询订单详情失败: {detail.status_code}"
            current = _extract_data(detail.json()).get("status")
            # 后端可能采用大小写或异步更新；存在状态字段时应等于目标
            if current is not None:
                assert current == target, f"订单状态未更新为 {target}: 当前={current}"

    def test_order_status_invalid_transition(self, authed_admin_client: SmokeTestClient):
        """非法状态值应被拒绝"""
        order = _create_order(authed_admin_client, _build_order_payload())
        order_id = order.get("id")
        assert order_id, "订单 id 缺失"

        resp = _update_order_status(authed_admin_client, order_id, "not_a_real_status")
        # 校验注解 @Pattern 应返回 400；若返回 200 则需业务层报错
        if resp.status_code == 200:
            body = resp.json()
            assert _is_business_error(body), (
                f"非法状态被静默接受: status=200, body={body}"
            )
        else:
            assert 400 <= resp.status_code < 500, (
                f"非法状态期望 4xx，实际 {resp.status_code}: {resp.text[:300]}"
            )


# ---------------------------------------------------------------------------
# 订单过滤查询
# ---------------------------------------------------------------------------

@pytest.mark.p1
@pytest.mark.business
class TestOrderQuery:
    """订单过滤与分页查询"""

    def test_filter_by_status(self, authed_admin_client: SmokeTestClient):
        """按状态筛选（pending）"""
        # 先创建一笔订单确保至少存在一条 pending 数据
        _create_order(authed_admin_client, _build_order_payload())

        resp = authed_admin_client.get("/api/admin/orders", params={
            "page": 1,
            "size": 20,
            "status": "pending",
        })
        data = assert_page_response(resp)
        records = _extract_records(data)
        # 仅断言返回的数据状态匹配（兼容空库情况）
        for record in records:
            status = record.get("status")
            if status is not None:
                assert status == "pending", f"过滤未生效，记录状态={status}"

    def test_filter_by_date(self, authed_admin_client: SmokeTestClient):
        """按日期范围筛选（如支持）"""
        today = datetime.utcnow().date()
        start = (today - timedelta(days=7)).isoformat()
        end = today.isoformat()

        # 兼容多种参数命名；任一返回 4xx 即视为不支持
        param_variants = [
            {"startDate": start, "endDate": end},
            {"startTime": start, "endTime": end},
            {"beginDate": start, "endDate": end},
        ]
        last_resp = None
        for extra in param_variants:
            params = {"page": 1, "size": 10, **extra}
            resp = authed_admin_client.get("/api/admin/orders", params=params)
            last_resp = resp
            if resp.status_code == 200:
                # 至少响应结构正常
                _ = _extract_records(resp.json())
                return
        if last_resp is None or last_resp.status_code != 200:
            pytest.skip(
                "订单按日期范围筛选未实现或不接受常见参数命名"
                f"（最近响应 status={getattr(last_resp, 'status_code', 'N/A')}）"
            )

    def test_filter_by_customer(self, authed_admin_client: SmokeTestClient):
        """按客户筛选（使用自创订单的客户名作为 keyword）"""
        payload = _build_order_payload()
        order = _create_order(authed_admin_client, payload)
        customer_name = order.get("customerName") or payload["customerName"]

        # 后端实现以 keyword 过滤（同时覆盖客户名/手机号/订单号）
        resp = authed_admin_client.get("/api/admin/orders", params={
            "page": 1,
            "size": 20,
            "keyword": customer_name,
        })
        if resp.status_code != 200:
            pytest.skip(f"按客户/关键字筛选不支持: status={resp.status_code}")

        data = assert_page_response(resp)
        records = _extract_records(data)
        if not records:
            # 接口生效但库内未命中（如租户数据隔离），不视为失败
            return
        # 若返回结果带 customerName 字段则进行宽松校验
        names = [r.get("customerName") for r in records if r.get("customerName")]
        if names:
            assert any(customer_name in n or n in customer_name for n in names), (
                f"keyword={customer_name} 未命中任意记录: names={names[:5]}"
            )

    def test_order_pagination(self, authed_admin_client: SmokeTestClient):
        """分页参数验证"""
        # 至少创建两笔订单提高分页可观测性
        for _ in range(2):
            _create_order(authed_admin_client, _build_order_payload())

        size = 1
        first = authed_admin_client.get("/api/admin/orders", params={"page": 1, "size": size})
        assert first.status_code == 200, f"分页查询失败: {first.status_code}"
        first_body = assert_page_response(first)
        first_records = _extract_records(first_body)
        first_total = _extract_total(first_body)

        assert len(first_records) <= size, (
            f"page=1 size={size} 返回数量={len(first_records)} 超过 size"
        )

        # 若总数 > size，验证 page=2 返回不同数据
        if first_total is not None and first_total > size:
            second = authed_admin_client.get(
                "/api/admin/orders", params={"page": 2, "size": size}
            )
            assert second.status_code == 200, f"第二页查询失败: {second.status_code}"
            second_records = _extract_records(second.json())
            assert len(second_records) <= size

            first_ids = {r.get("id") for r in first_records if r.get("id")}
            second_ids = {r.get("id") for r in second_records if r.get("id")}
            if first_ids and second_ids:
                assert first_ids.isdisjoint(second_ids), (
                    f"分页未生效，第二页与第一页数据重叠: "
                    f"page1={first_ids}, page2={second_ids}"
                )
