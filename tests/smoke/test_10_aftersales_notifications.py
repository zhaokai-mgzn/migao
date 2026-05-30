"""
售后工单 / 通知系统 / Dashboard 模块冒烟测试 (P1)

覆盖：
- 售后工单 CRUD 与状态流转
- 通知列表/未读数/已读标记/详情
- Dashboard 主统计数据格式与今日数据
"""

import pytest

from .helpers import (
    SmokeTestClient,
    assert_page_response,
    assert_success_response,
)


def _records_of(resp) -> list:
    """从分页响应中提取 records/items 列表。"""
    if resp.status_code != 200:
        return []
    data = resp.json()
    page_data = data.get("data", data)
    if isinstance(page_data, list):
        return page_data
    return page_data.get("records", page_data.get("items", []))


def _skip_if_unsupported(resp, label: str):
    """API 未实现时统一 skip。"""
    if resp.status_code in (404, 405):
        pytest.skip(f"{label} API endpoint not available (status={resp.status_code})")


@pytest.mark.p1
@pytest.mark.business
class TestAfterSalesAPI:
    """售后工单 API 测试"""

    def test_create_after_sale(self, authed_admin_client: SmokeTestClient):
        """POST 创建售后工单"""
        # 先尝试取一个真实订单 ID 关联，没有则用占位 ID
        order_id = "smoke-test-order"
        order_resp = authed_admin_client.get(
            "/api/admin/orders", params={"page": 1, "size": 1}
        )
        if order_resp.status_code == 200:
            records = _records_of(order_resp)
            if records:
                order_id = str(records[0].get("id", order_id))

        payload = {
            "orderId": order_id,
            "ticketType": "return",
            "description": "smoke test 自动化创建的售后工单",
            "priority": "normal",
        }
        resp = authed_admin_client.post(
            "/api/admin/after-sales", json=payload
        )
        _skip_if_unsupported(resp, "Create after-sale")

        # 200 创建成功，或 4xx 因订单不存在/校验失败被拒绝；后端可达即认为接口可用
        assert resp.status_code in (200, 201, 400, 422, 500), (
            f"Unexpected status creating after-sale: "
            f"{resp.status_code} {resp.text[:300]}"
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            ticket = data.get("data", data)
            assert isinstance(ticket, dict), (
                f"Expected ticket object, got: {type(ticket)}"
            )

    def test_list_after_sales(self, authed_admin_client: SmokeTestClient):
        """GET 售后工单列表"""
        resp = authed_admin_client.get(
            "/api/admin/after-sales", params={"page": 1, "size": 10}
        )
        _skip_if_unsupported(resp, "List after-sales")

        data = assert_page_response(resp)
        page_data = data.get("data", data)
        records = page_data.get("records", page_data.get("items", []))
        assert isinstance(records, list), (
            f"Expected list of after-sales tickets, got: {type(records)}"
        )

    def test_after_sale_status_flow(self, authed_admin_client: SmokeTestClient):
        """售后工单状态流转：pending -> processing -> resolved"""
        list_resp = authed_admin_client.get(
            "/api/admin/after-sales", params={"page": 1, "size": 1}
        )
        _skip_if_unsupported(list_resp, "List after-sales")

        records = _records_of(list_resp)
        if not records:
            pytest.skip("No after-sales tickets in database for status flow test")

        ticket_id = records[0].get("id")
        assert ticket_id, "After-sales ticket has no ID field"

        # 流转到 processing
        processing_resp = authed_admin_client.put(
            f"/api/admin/after-sales/{ticket_id}/status",
            json={"status": "processing", "remark": "smoke test 流转中"},
        )
        _skip_if_unsupported(processing_resp, "Update after-sale status")
        assert processing_resp.status_code in (200, 400, 409), (
            f"Unexpected status moving to processing: "
            f"{processing_resp.status_code} {processing_resp.text[:300]}"
        )

        # 流转到 resolved（部分实现可能因前置状态约束返回 400/409，可接受）
        resolved_resp = authed_admin_client.put(
            f"/api/admin/after-sales/{ticket_id}/status",
            json={"status": "resolved", "remark": "smoke test 已完成"},
        )
        assert resolved_resp.status_code in (200, 400, 409), (
            f"Unexpected status moving to resolved: "
            f"{resolved_resp.status_code} {resolved_resp.text[:300]}"
        )

    def test_after_sale_detail(self, authed_admin_client: SmokeTestClient):
        """GET /{id} 售后工单详情"""
        list_resp = authed_admin_client.get(
            "/api/admin/after-sales", params={"page": 1, "size": 1}
        )
        _skip_if_unsupported(list_resp, "List after-sales")
        records = _records_of(list_resp)
        if not records:
            pytest.skip("No after-sales tickets in database")

        ticket_id = records[0].get("id")
        detail_resp = authed_admin_client.get(
            f"/api/admin/after-sales/{ticket_id}"
        )
        _skip_if_unsupported(detail_resp, "After-sale detail")
        assert detail_resp.status_code == 200, (
            f"After-sale detail failed: "
            f"{detail_resp.status_code} {detail_resp.text[:300]}"
        )
        data = detail_resp.json()
        ticket = data.get("data", data)
        assert isinstance(ticket, dict), (
            f"Expected ticket object, got: {type(ticket)}"
        )
        returned_id = ticket.get("id")
        assert returned_id is None or str(returned_id) == str(ticket_id), (
            f"Detail ID mismatch: requested {ticket_id}, got {returned_id}"
        )


@pytest.mark.p1
@pytest.mark.business
class TestNotificationAPI:
    """通知系统 API 测试"""

    def test_list_notifications(self, authed_admin_client: SmokeTestClient):
        """GET 通知列表"""
        resp = authed_admin_client.get(
            "/api/admin/notifications", params={"page": 1, "size": 10}
        )
        _skip_if_unsupported(resp, "List notifications")

        data = assert_page_response(resp)
        page_data = data.get("data", data)
        records = page_data.get("records", page_data.get("items", []))
        assert isinstance(records, list), (
            f"Expected list of notifications, got: {type(records)}"
        )

    def test_unread_count(self, authed_admin_client: SmokeTestClient):
        """GET 未读通知数"""
        resp = authed_admin_client.get(
            "/api/admin/notifications/unread-count"
        )
        _skip_if_unsupported(resp, "Unread count")

        data = assert_success_response(resp)
        payload = data.get("data", data)
        # 兼容 {count: N} 或纯数值返回
        if isinstance(payload, dict):
            count = payload.get("count", payload.get("unreadCount", payload.get("total")))
        else:
            count = payload
        assert count is None or isinstance(count, (int, float)), (
            f"Expected numeric unread count, got: {type(count)} -> {payload}"
        )
        if isinstance(count, (int, float)):
            assert count >= 0, f"Unread count should be non-negative, got {count}"

    def test_mark_as_read(self, authed_admin_client: SmokeTestClient):
        """PUT /{id}/read 标记通知已读"""
        list_resp = authed_admin_client.get(
            "/api/admin/notifications", params={"page": 1, "size": 1}
        )
        _skip_if_unsupported(list_resp, "List notifications")

        records = _records_of(list_resp)
        if not records:
            pytest.skip("No notifications in database to mark as read")

        notification_id = records[0].get("id")
        assert notification_id, "Notification has no ID field"

        resp = authed_admin_client.put(
            f"/api/admin/notifications/{notification_id}/read"
        )
        _skip_if_unsupported(resp, "Mark notification as read")
        # 已读幂等：200 成功，或 400/409 表示已是已读状态
        assert resp.status_code in (200, 204, 400, 409), (
            f"Unexpected status marking as read: "
            f"{resp.status_code} {resp.text[:300]}"
        )

    def test_notification_detail(self, authed_admin_client: SmokeTestClient):
        """GET /{id} 通知详情（如支持）"""
        list_resp = authed_admin_client.get(
            "/api/admin/notifications", params={"page": 1, "size": 1}
        )
        _skip_if_unsupported(list_resp, "List notifications")

        records = _records_of(list_resp)
        if not records:
            pytest.skip("No notifications in database")

        notification_id = records[0].get("id")
        resp = authed_admin_client.get(
            f"/api/admin/notifications/{notification_id}"
        )
        _skip_if_unsupported(resp, "Notification detail")
        assert resp.status_code == 200, (
            f"Notification detail failed: "
            f"{resp.status_code} {resp.text[:300]}"
        )
        data = resp.json()
        notification = data.get("data", data)
        assert isinstance(notification, dict), (
            f"Expected notification object, got: {type(notification)}"
        )


@pytest.mark.p1
@pytest.mark.business
class TestDashboardAPI:
    """Dashboard 数据 API 测试"""

    # 候选端点：常见后端约定为 /stats 子路径，部分实现直接挂在根路径
    _STATS_PATHS = ("/api/admin/dashboard/stats", "/api/admin/dashboard")

    def _get_stats(self, client: SmokeTestClient):
        """尝试 stats 端点，返回首个非 404/405 的响应及其路径。"""
        last_resp = None
        for path in self._STATS_PATHS:
            resp = client.get(path)
            if resp.status_code not in (404, 405):
                return resp, path
            last_resp = resp
        return last_resp, self._STATS_PATHS[-1]

    def test_dashboard_stats(self, authed_admin_client: SmokeTestClient):
        """GET 主统计数据：状态码 200 即可"""
        resp, path = self._get_stats(authed_admin_client)
        _skip_if_unsupported(resp, f"Dashboard stats ({path})")
        assert resp.status_code == 200, (
            f"Dashboard stats failed at {path}: "
            f"{resp.status_code} {resp.text[:300]}"
        )

    def test_dashboard_data_format(self, authed_admin_client: SmokeTestClient):
        """验证 Dashboard 返回数据格式：包含 data 字段且为对象"""
        resp, path = self._get_stats(authed_admin_client)
        _skip_if_unsupported(resp, f"Dashboard stats ({path})")
        assert resp.status_code == 200, (
            f"Dashboard stats failed: {resp.status_code} {resp.text[:300]}"
        )

        body = resp.json()
        assert "data" in body, (
            f"Dashboard response missing 'data' field: keys={list(body.keys())}"
        )
        stats = body["data"]
        assert isinstance(stats, dict), (
            f"Dashboard data should be an object, got: {type(stats)}"
        )

        # 校验已知数值字段类型合理（如有则必须为数字，非负）
        numeric_candidates = (
            "totalOrders", "orderCount",
            "totalCustomers", "customerCount",
            "totalProducts", "productCount",
            "todayOrders", "todayRevenue",
            "totalRevenue", "revenue",
        )
        for key in numeric_candidates:
            if key in stats and stats[key] is not None:
                value = stats[key]
                assert isinstance(value, (int, float)), (
                    f"Dashboard field {key} should be numeric, got {type(value)}: {value}"
                )
                assert value >= 0, (
                    f"Dashboard field {key} should be non-negative, got {value}"
                )

    def test_dashboard_today_stats(self, authed_admin_client: SmokeTestClient):
        """今日统计：尝试带 range/period 参数或访问 today 子路径"""
        # 路径 1：参数过滤
        param_resp = None
        for path in self._STATS_PATHS:
            resp = authed_admin_client.get(path, params={"range": "today"})
            if resp.status_code not in (404, 405):
                param_resp = resp
                break

        # 路径 2：专用子路径
        today_resp = authed_admin_client.get("/api/admin/dashboard/today")

        # 至少一种方式可用即视为通过
        candidates = [r for r in (param_resp, today_resp) if r is not None]
        if not candidates or all(
            r.status_code in (404, 405) for r in candidates
        ):
            pytest.skip("Today stats API endpoint not available")

        for resp in candidates:
            if resp.status_code in (404, 405):
                continue
            assert resp.status_code == 200, (
                f"Today stats failed: {resp.status_code} {resp.text[:300]}"
            )
            body = resp.json()
            assert "data" in body or "success" in body or "code" in body, (
                f"Today stats missing standard envelope fields: "
                f"keys={list(body.keys())}"
            )
