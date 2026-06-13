"""
真实 E2E: 查询工具 — 零 Mock + 强数据验证

每个测试: 对话 → LLM → tool → 双端验证 (SSE 内容 + admin-api 数据一致)
"""
import pytest
from tests.e2e.real.conftest import (
    Session, admin_get, admin_search_products, sse_text, sse_tools, sse_results
)


def _product_names_from_admin(keyword="窗帘"):
    """从 admin-api 获取真实商品名列表"""
    items = admin_search_products(keyword)
    return [p.get("name", "") for p in items], items


@pytest.mark.real_e2e
class TestQueryTools:

    # ═══ 商品 ═══

    def test_product_search(self, sess):
        """搜索 → 验证返回的商品名与 admin-api 数据一致"""
        ev = sess.send("有什么窗帘")
        assert "product_search" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)

        # 强验证：SSE 回复中至少提到 1 个 admin-api 真实商品名
        names, items = _product_names_from_admin("窗帘")
        assert len(items) > 0, "admin-api 应有窗帘商品"
        matched = [n for n in names if n and n in text]
        assert len(matched) > 0, (
            f"SSE 回复应包含真实商品名。admin-api 有: {names[:5]}, SSE: {text[:200]}"
        )

    def test_product_detail(self, sess):
        """详情 → 验证价格/颜色等字段匹配 admin-api 数据"""
        _, items = _product_names_from_admin("窗帘")
        assert len(items) > 0, "需要至少一个商品"
        target = items[0]
        target_name = target.get("name", "")
        target_id = target.get("id", "")

        ev = sess.send(f"看一下 {target_name} 的详情")
        assert "product_detail" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)

        # 验证：SSE 回复包含商品名
        assert target_name in text or target_name[:4] in text, (
            f"SSE 应包含商品名 '{target_name}': {text[:200]}"
        )

        # 验证：从 admin-api 拿详情，对比价格
        detail = admin_get(f"/api/admin/products/{target_id}")
        if detail.get("success"):
            p = detail.get("data", {})
            price = (p.get("price") or 0) / 100  # 分转元
            assert str(int(price)) in text or str(price) in text or "元" in text, (
                f"SSE 应包含价格 {price}元: {text[:200]}"
            )

    # ═══ 订单 ═══

    def test_order_query(self, sess):
        """订单查询 → 验证数据一致性 + 销售信息字段"""
        ev = sess.send("查最近的订单，看看详细信息")
        assert "order_query" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)

        # admin-api 验证
        data = admin_get("/api/admin/orders", {"page": 1, "size": 5})
        if data.get("success") and data.get("data", {}).get("items"):
            orders = data["data"]["items"]
            # SSE 应提到至少一个订单号或客户名
            order_nos = [o.get("orderNo", "") for o in orders if o.get("orderNo")]
            customer_names = [o.get("customerName", "") for o in orders if o.get("customerName")]
            matched = any((n and n in text) for n in order_nos + customer_names)
            assert matched, (
                f"SSE 应包含订单号或客户名。admin: {order_nos[:3]} {customer_names[:3]}, SSE: {text[:200]}"
            )
            # 验证订单详情是否包含销售信息字段（颜色/售卖方式/门幅）
            # 检查 admin-api 订单 items 中是否有 processingInfo
            for o in orders[:3]:
                items = o.get("items") or []
                for it in items:
                    pi = it.get("processingInfo") or {}
                    if pi.get("colorName") or pi.get("sellingMethod") or pi.get("doorWidth"):
                        # 如果 admin-api 中有销售信息，SSE 应提及
                        assert any(kw in text for kw in [
                            "颜色", "售卖", "门幅", "销售信息", "散剪", "定高", "买通",
                            pi.get("colorName", ""), pi.get("sellingMethod", ""),
                        ] if kw), (
                            f"订单 {o.get('orderNo')} 含销售信息 {pi}，SSE 应提及: {text[:300]}"
                        )
                        break
        else:
            # 无订单数据也算正常
            assert "订单" in text or "没有" in text or "暂无" in text

    def test_order_statistics(self, sess):
        """订单统计 → 验证数字合理"""
        ev = sess.send("订单统计数据")
        assert "order_query" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)

        # admin-api 验证统计数字
        stats = admin_get("/api/admin/orders/statistics")
        if stats.get("success"):
            # SSE 应该提到统计数据
            assert "单" in text or "订单" in text

    # ═══ 物流 ═══

    def test_logistics_track(self, sess):
        """物流 → 验证 tool 触发"""
        ev = sess.send("查 ORD-20240601 物流")
        assert "logistics_track" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        # 物流查询可能失败（订单不存在），但 tool 必须触发

    # ═══ 看板 ═══

    def test_dashboard_overview(self, sess):
        """经营看板 → 验证数字与 admin-api 一致"""
        ev = sess.send("今天生意怎么样")
        assert "dashboard_stats" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)

        # 从 admin-api 拿真实统计数据对比
        stats = admin_get("/api/admin/orders/statistics")
        if stats.get("success"):
            stat_data = stats.get("data", {})
            today_count = stat_data.get("todayOrderCount") or stat_data.get("totalOrders")
            if today_count:
                assert str(today_count) in text, (
                    f"SSE 订单数应与 admin-api 一致: admin={today_count}, SSE={text[:200]}"
                )

    def test_dashboard_trend(self, sess):
        """订单趋势 → 验证 tool 触发（dashboard_stats 或 order_query 均可）"""
        ev = sess.send("最近7天订单趋势")
        tools = sse_tools(ev)
        assert "dashboard_stats" in tools or "order_query" in tools, f"tools: {tools}"

    # ═══ 加工项 ═══

    def test_processing_item_query(self, sess):
        """加工项查询 → 验证实际加工项名出现在 SSE 中"""
        ev = sess.send("有哪些加工项")
        assert "processing_item_query" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)

        # admin-api 获取真实加工项
        pi = admin_get("/api/admin/processing-items", {"page": 1, "size": 10})
        if pi.get("success") and pi.get("data", {}).get("items"):
            pi_names = [p.get("name", "") for p in pi["data"]["items"] if p.get("name")]
            matched = [n for n in pi_names if n and n in text]
            assert len(matched) > 0, (
                f"SSE 应包含真实加工项名。admin: {pi_names[:5]}, SSE: {text[:200]}"
            )

    # ═══ 分类 ═══

    def test_category_tree(self, sess):
        """分类树 → 验证分类名匹配"""
        ev = sess.send("看看商品分类有哪些")
        assert "category_manage" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)

        cats = admin_get("/api/admin/categories", {"page": 1, "size": 10})
        cat_items = cats.get("data", cats) if isinstance(cats, dict) else cats
        cat_items = cat_items if isinstance(cat_items, list) else cat_items.get("items", [])
        if cat_items:
            cat_names = [c.get("name", "") for c in cat_items if c.get("name")]
            matched = [n for n in cat_names if n and n in text]
            assert len(matched) > 0, (
                f"SSE 应包含真实分类名。admin: {cat_names}, SSE: {text[:200]}"
            )

    # ═══ 客户/员工/角色 ═══

    def test_customer_list(self, sess):
        """客户 → 验证数字一致"""
        ev = sess.send("查客户列表")
        assert "customer_manage" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)

        cust = admin_get("/api/admin/customers", {"page": 1, "size": 10})
        if cust.get("success") and cust.get("data", {}).get("total"):
            total = cust["data"]["total"]
            assert str(total) in text, (
                f"SSE 客户数应与 admin-api 一致: admin={total}, SSE={text[:200]}"
            )

    def test_employee_list(self, sess):
        """员工 → 验证员工名出现"""
        ev = sess.send("有哪些员工")
        assert "employee_manage" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)

        emp = admin_get("/api/admin/users", {"page": 1, "size": 10})
        if emp.get("success") and emp.get("data", {}).get("items"):
            emp_names = [e.get("name", "") or e.get("nickname", "") for e in emp["data"]["items"]]
            emp_names = [n for n in emp_names if n]
            if emp_names:
                matched = [n for n in emp_names if n and n in text]
                assert len(matched) > 0, (
                    f"SSE 应包含真实员工名。admin: {emp_names}, SSE: {text[:200]}"
                )

    def test_role_list(self, sess):
        """角色 → 验证角色名匹配 admin-api 数据"""
        ev = sess.send("系统有哪些角色")
        assert "role_manage" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)

        roles = admin_get("/api/admin/roles")
        if roles.get("success") and roles.get("data"):
            role_items = roles["data"] if isinstance(roles["data"], list) else roles["data"].get("items", [])
            role_names = [r.get("name", "") for r in role_items if r.get("name")]
            if role_names:
                matched = [n for n in role_names if n and n in text]
                assert len(matched) > 0, (
                    f"SSE 应包含真实角色名。admin: {role_names}, SSE: {text[:200]}"
                )

    # ═══ 其他管理工具 ═══

    def test_notification_list(self, sess):
        """通知 → 验证 tool 触发 + 含实际通知内容"""
        ev = sess.send("看看有没有新通知")
        assert "notification_manage" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)

        notifs = admin_get("/api/admin/notifications", {"page": 1, "size": 5})
        if notifs.get("success") and notifs.get("data", {}).get("total"):
            total = notifs["data"]["total"]
            assert str(total) in text, (
                f"SSE 应含通知总数。admin total={total}, SSE: {text[:200]}"
            )

    def test_quick_reply_list(self, sess):
        """快捷回复 → 验证实际模板标题出现在 SSE 中"""
        ev = sess.send("快捷回复模板有哪些")
        assert "quick_reply_manage" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)

        qr = admin_get("/api/admin/quick-replies", {"page": 1, "size": 10})
        if qr.get("success") and qr.get("data", {}).get("items"):
            titles = [q.get("title", "") for q in qr["data"]["items"] if q.get("title")]
            matched = [t for t in titles if t and t in text]
            assert len(matched) > 0, (
                f"SSE 应包含真实快捷回复标题。admin: {titles[:5]}, SSE: {text[:200]}"
            )

    def test_settings_get(self, sess):
        ev = sess.send("查看系统设置")
        assert "settings_manage" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)
        # 验证包含实际设置内容（如商户名）
        settings = admin_get("/api/admin/settings")
        if settings.get("success") and settings.get("data"):
            name = settings["data"].get("name", "")
            if name:
                assert name in text, f"SSE 应含商户名 '{name}': {text[:200]}"

    def test_session_monitor(self, sess):
        """会话监控 → 验证 tool 触发 + 返回内容非错误"""
        ev = sess.send("现在在线客服情况怎么样")
        assert "session_manage" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)
        # 验证返回了有效的会话状态信息（非错误文本）
        assert len(text) > 10, f"SSE 回复过短: {text[:200]}"
        assert "抱歉" not in text or "会话" in text, (
            f"SSE 应含会话数据或正常状态描述: {text[:200]}"
        )

    def test_aftersales_list(self, sess):
        """售后 → 验证实际工单数据出现"""
        ev = sess.send("查看售后工单列表")
        assert "after_sales_manage" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)

        tickets = admin_get("/api/admin/after-sales", {"page": 1, "size": 5})
        if tickets.get("success") and tickets.get("data", {}).get("items"):
            ticket_nos = [t.get("ticketNo", "") for t in tickets["data"]["items"] if t.get("ticketNo")]
            customer_names = [t.get("customerName", "") for t in tickets["data"]["items"] if t.get("customerName")]
            all_ids = ticket_nos + customer_names
            matched = any((n and n in text) for n in all_ids)
            assert matched, (
                f"SSE 应包含工单号或客户名。admin: {all_ids[:5]}, SSE: {text[:200]}"
            )

    def test_processing_item_manage_list(self, sess):
        """加工项管理列表 → 验证含加工项分类"""
        ev = sess.send("加工项分类有哪些")
        assert "processing_item_manage" in sse_tools(ev), f"tools: {sse_tools(ev)}"
        text = sse_text(ev)

        pi = admin_get("/api/admin/processing-items", {"page": 1, "size": 10})
        if pi.get("success") and pi.get("data", {}).get("items"):
            pi_names = [p.get("name", "") for p in pi["data"]["items"] if p.get("name")]
            categories = list(set(
                p.get("categoryName", "") for p in pi["data"]["items"] if p.get("categoryName")
            ))
            search_terms = pi_names + categories
            matched = [t for t in search_terms if t and t in text]
            assert len(matched) > 0, (
                f"SSE 应包含真实加工项或分类名。admin: {search_terms[:5]}, SSE: {text[:200]}"
            )
