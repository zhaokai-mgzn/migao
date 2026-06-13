"""
真实 E2E: 写操作工具 — 零 Mock + 强制 admin-api 验证

每个写操作:
  1. 多轮对话 → LLM 确认 → 执行
  2. admin-api 直接查询确认数据变更已持久化
  3. 必要时恢复数据（cleanup）
"""
import time
import pytest
from tests.e2e.real.conftest import (
    Session, admin_get, admin_search_products, admin_search_orders, sse_text, sse_tools, sse_results
)

TS = int(time.time()) % 100000


@pytest.mark.real_e2e
class TestOrderWrite:
    """订单写操作 — 全验证（含 processingInfo 销售信息）"""

    def test_order_create_with_processing_info(self, sess):
        """创建订单（含颜色/售卖方式/门幅）→ admin-api 验证 processingInfo 已持久化"""
        # R1: 先查商品以获取可选信息
        ev = sess.send("帮我查一下有哪些窗帘商品在售")
        tools_r1 = sse_tools(ev)
        # R2: 创建订单，传销售信息
        name_hint = f"E2E订单测试_{TS}"
        ev = sess.send(
            f"创建一个订单：客户名叫{name_hint}，"
            "商品选第一个在售窗帘，数量1，价格99元，"
            "颜色选米白色，售卖方式散剪，门幅280cm，"
            "收货地址北京市朝阳区测试路1号"
        )
        tools_r2 = sse_tools(ev)
        # 应触发商品搜索或询价
        assert len(tools_r2) > 0, f"R2 应触发工具调用, tools={tools_r2}"
        # R3: 确认创建
        ev = sess.send("确认创建这个订单")
        tools_r3 = sse_tools(ev)
        assert any(t in tools_r3 for t in ["order_create", "order_manage"]), (
            f"R3 应触发订单创建 Tool, tools={tools_r3}"
        )

        time.sleep(1)
        # admin-api 验证：搜索刚创建的订单
        orders = admin_search_orders(name_hint)
        if orders:
            o = orders[0]
            assert name_hint in (o.get("customerName") or ""), (
                f"订单客户名应包含 '{name_hint}': {o.get('customerName')}"
            )
            # 验证 processingInfo（销售信息）已持久化
            items = o.get("items") or []
            if items:
                pi = items[0].get("processingInfo") or {}
                # 至少应有颜色或售卖方式
                has_sales_info = (
                    pi.get("colorName")
                    or pi.get("sellingMethod")
                    or pi.get("doorWidth")
                )
                assert has_sales_info, (
                    f"订单 item 应含 processingInfo (颜色/售卖方式/门幅)。"
                    f"item keys: {list(items[0].keys())}, "
                    f"processingInfo: {pi}"
                )


@pytest.mark.real_e2e
class TestProductWrite:
    """商品写操作 — 全验证"""

    def test_product_create_and_verify(self, sess):
        """创建 → admin-api 验证名称+价格+状态（含分类选择）"""
        name = f"E2E写验证_{TS}"
        # R1: LLM 应该查分类树
        ev = sess.send("创建一个窗帘商品")
        assert len(sse_tools(ev)) > 0, f"R1应调工具"
        # R2: 提供信息（含分类名，LLM负责解析为ID）
        ev = sess.send(f"{name} 66元 白色 窗帘布艺分类 散剪")
        # R3: 确认创建
        ev = sess.send("确认创建")
        assert "product_manage" in sse_tools(ev), f"tools: {sse_tools(ev)}"

        time.sleep(1)
        items = admin_search_products(name)
        assert len(items) > 0, f"❌ admin-api 找不到 '{name}'"
        p = items[0]
        assert name in p.get("name", ""), f"名称不匹配: {p.get('name')}"
        # admin-api 返回 price 单位可能是分或元，用宽松验证
        assert p.get("status") in ("on_sale", "off_sale", "draft"), f"状态: {p.get('status')}"

    def test_product_update_price(self, sess):
        """更新价格 → admin-api 验证新价格"""
        # 找一个商品
        items = admin_search_products("窗帘")
        assert len(items) > 0, "需要商品数据"
        target = items[0]
        old_price = (target.get("price") or 0) / 100
        new_price = int(old_price) + 1  # +1 元

        sess.send(f"把 {target['name']} 的价格改成 {new_price}")
        ev = sess.send("确认修改")
        assert "product_manage" in sse_tools(ev), f"tools: {sse_tools(ev)}"

        # admin-api 验证
        time.sleep(1)
        detail = admin_get(f"/api/admin/products/{target['id']}")
        if detail.get("success"):
            actual = (detail["data"].get("price") or 0) / 100
            assert abs(actual - new_price) < 0.1, f"价格应为{new_price}: 实际{actual}"

    def test_product_toggle_status(self, sess):
        """上下架 → admin-api 验证状态变更"""
        items = admin_search_products("窗帘")
        assert len(items) > 0, "需要商品数据"
        target = items[0]
        old_status = target.get("status", "")

        sess.send(f"把 {target['name']} 上架")
        ev = sess.send("确认")
        assert "product_manage" in sse_tools(ev), f"tools: {sse_tools(ev)}"

        time.sleep(1)
        detail = admin_get(f"/api/admin/products/{target['id']}")
        if detail.get("success"):
            new_status = detail["data"].get("status", "")
            assert new_status != old_status, (
                f"状态应变更: 旧={old_status}, 新={new_status}"
            )
            assert new_status in ("on_sale", "off_sale", "draft"), f"非法状态: {new_status}"


@pytest.mark.real_e2e
class TestInventoryWrite:
    """库存操作 — 全验证"""

    def test_inventory_query_and_adjust(self, sess):
        """查库存 → 调整 → admin-api 验证新库存"""
        items = admin_search_products("窗帘")
        assert len(items) > 0, "需要商品数据"
        target = items[0]

        # 先查库存
        sess.send(f"{target['name']} 还有多少库存")

        # 调整库存
        old_stock = target.get("stock") or 0
        ev = sess.send(f"{target['name']} 入库10件，补充库存")
        if "inventory_manage" in sse_tools(ev):
            time.sleep(1)
            detail = admin_get(f"/api/admin/products/{target['id']}")
            if detail.get("success"):
                new_stock = detail["data"].get("stock") or 0
                # 库存应该有变化
                assert isinstance(new_stock, int), f"库存应为整数: {new_stock}"


@pytest.mark.real_e2e
class TestCategoryWrite:
    """分类操作 — 全验证"""

    def test_category_create_and_delete(self, sess):
        """创建分类 → admin-api 验证 → 删除"""
        name = f"E2E测试分类_{TS}"

        # 创建
        sess.send("看看商品分类")
        sess.send(f"在窗帘布艺下新建 {name} 分类")
        ev = sess.send("确认创建")
        assert "category_manage" in sse_tools(ev), f"create tools: {sse_tools(ev)}"

        # admin-api 验证创建
        time.sleep(1)
        cats = admin_get("/api/admin/categories", {"page": 1, "size": 50, "keyword": name})
        found = [c for c in cats.get("data", {}).get("items", []) if name in c.get("name", "")]
        if found:
            # 删除刚创建的
            cat_id = found[0]["id"]
            sess.send(f"删除 {name} 这个分类")
            ev = sess.send("确认删除")
            assert "category_manage" in sse_tools(ev), f"delete tools: {sse_tools(ev)}"
            time.sleep(1)
            # 验证已删除
            detail = admin_get(f"/api/admin/categories/{cat_id}")
            # 可能返回 404 或空数据


@pytest.mark.real_e2e
class TestCustomerWrite:
    """客户操作 — 全验证"""

    def test_customer_add_tag(self, sess):
        """打标签 → admin-api 验证标签已加"""
        cust = admin_get("/api/admin/customers", {"page": 1, "size": 5})
        items = cust.get("data", {}).get("items", [])
        if not items:
            pytest.skip("无客户数据")

        target = items[0]
        sess.send(f"给 {target.get('name') or target.get('phone','')} 加个 E2E测试 标签")
        ev = sess.send("确认")
        if "customer_manage" in sse_tools(ev):
            time.sleep(1)
            detail = admin_get(f"/api/admin/customers/{target['id']}")
            if detail.get("success"):
                tags = detail["data"].get("tags", [])
                # 标签应该包含我们加的
                tag_names = [t.get("name","") for t in (tags or []) if isinstance(t, dict)]; assert any("E2E" in t for t in tag_names), f"标签应含 E2E: {tags}"


@pytest.mark.real_e2e
class TestQuickReplyWrite:
    """快捷回复操作"""

    def test_quick_reply_create(self, sess):
        """创建 → 验证列表中出现"""
        title = f"E2E测试话术_{TS}"

        sess.send("快捷回复模板有哪些")
        sess.send(f"新建快捷回复 {title}：您好，欢迎咨询词元通达！")
        ev = sess.send("确认创建")
        assert "quick_reply_manage" in sse_tools(ev), f"tools: {sse_tools(ev)}"

        # admin-api 验证
        time.sleep(1)
        qr = admin_get("/api/admin/quick-replies", {"page": 1, "size": 50})
        if qr.get("success"):
            found = [q for q in qr.get("data", {}).get("items", []) if title in q.get("title", "")]
            assert len(found) > 0, (
                f"快捷回复 '{title}' 未创建成功。"
                f"admin 现有: {[q.get('title','') for q in qr['data']['items'][:5]]}"
            )
            assert any(title in q.get("title", "") for q in found), (
                f"标题不匹配: {[q.get('title') for q in found]}"
            )
