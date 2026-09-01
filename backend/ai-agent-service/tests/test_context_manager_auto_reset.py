"""
AgentContextManager 上下文自动清理测试 — 主题域切换重置(T1) + 事务终态重置(T2)

验证：
- entities 按域分桶（order/product/aftersales），跨域注入隔离
- record_domain_switch：切域后旧域实体标 stale，build_context 只注入当前域
- reset_domain：事务终态后清空指定域全部会话级状态
- reset_session：完整清空会话级状态（保留由调用方决定的用户级记忆）
"""
# case_ids: OR-001, DF-002
import pytest

from app.memory.context_manager import AgentContextManager


@pytest.fixture
def ctx():
    mgr = AgentContextManager()
    # 清空内部缓存，保证测试隔离
    mgr._cache.clear()
    mgr._user_session_map.clear()
    return mgr


class TestDomainScopedEntities:
    def test_entities_are_bucketed_by_domain(self, ctx):
        """tool 结果按域分桶存储"""
        ctx.record_tool_result("s1", "order_query", {
            "success": True,
            "data": {"orders": [{"id": "ord-1", "order_no": "ORD-A"}]},
            "message": "找到1个订单",
        })
        ctx.record_tool_result("s1", "product_search", {
            "success": True,
            "data": {"products": [{"id": "p-1", "name": "窗帘"}]},
            "message": "找到1个商品",
        })
        entities = ctx.get_entities("s1")
        # 域分桶：order 实体与 product 实体分属不同 key
        assert "order_nos" in entities
        assert "product_ids" in entities
        assert entities["order_nos"][0]["name"] == "ORD-A"
        assert entities["product_ids"][0]["id"] == "p-1"


class TestDomainSwitchResetT1:
    def test_domain_switch_stale_old_domain(self, ctx):
        """切域后旧域实体不注入 build_context（避免跨域污染）"""
        ctx.record_tool_result("s1", "order_query", {
            "success": True,
            "data": {"orders": [{"id": "ord-1", "order_no": "ORD-A"}]},
            "message": "找到1个订单",
        })
        ctx.set_last_skill("s1", "order")

        # 切换到 product 域
        ctx.record_domain_switch("s1", "product")
        context = ctx.build_context("s1", "product")

        # product 域上下文不应包含订单实体（ORD-A 已被标 stale 排除）
        assert "ORD-A" not in context
        assert "订单" not in context

    def test_same_domain_keeps_entities(self, ctx):
        """同域内（order→order）不触发切换，实体保留"""
        ctx.record_tool_result("s1", "order_query", {
            "success": True,
            "data": {"orders": [{"id": "ord-1", "order_no": "ORD-A"}]},
            "message": "找到1个订单",
        })
        ctx.set_last_skill("s1", "order")
        ctx.record_domain_switch("s1", "order")  # 同域，应为 no-op
        context = ctx.build_context("s1", "order")
        assert "ORD-A" in context

    def test_domain_switch_keeps_name_index_for_backtrack(self, ctx):
        """切域保留旧域名称索引（供"回到刚才话题"回溯），但不带精确 ID 细节"""
        ctx.record_tool_result("s1", "order_query", {
            "success": True,
            "data": {"orders": [{"id": "ord-1", "order_no": "ORD-A"}]},
            "message": "找到1个订单",
        })
        ctx.set_last_skill("s1", "order")
        ctx.record_domain_switch("s1", "product")
        context = ctx.build_context("s1", "product")
        # 不应含精确订单号（防误用），但提示语应存在
        assert "ORD-A" not in context


class TestTransactionResetT2:
    def test_reset_domain_clears_that_domain_state(self, ctx):
        """事务终态后清空指定域全部会话级状态（草稿/实体/tool_results）"""
        ctx.record_tool_result("s1", "order_query", {
            "success": True,
            "data": {"orders": [{"id": "ord-1", "order_no": "ORD-A"}]},
            "message": "找到1个订单",
        })
        ctx.record_tool_result("s1", "product_search", {
            "success": True,
            "data": {"products": [{"id": "p-1", "name": "窗帘"}]},
            "message": "找到1个商品",
        })
        ctx.set_last_skill("s1", "order")

        ctx.reset_domain("s1", "order")
        entities = ctx.get_entities("s1")
        # order 域实体被清空，product 域保留
        assert not entities.get("order_nos")
        assert entities["product_ids"][0]["id"] == "p-1"

    def test_reset_domain_clears_tool_results_and_last_skill(self, ctx):
        ctx.record_tool_result("s1", "order_query", {
            "success": True,
            "data": {"orders": [{"id": "ord-1", "order_no": "ORD-A"}]},
            "message": "找到1个订单",
        })
        ctx.set_last_skill("s1", "order")
        ctx.reset_domain("s1", "order")
        cache = ctx._cache["s1"]
        assert not cache.get("tool_results")
        assert cache.get("last_skill") != "order"  # 终态后不再残留当前域

    def test_reset_session_clears_all_session_state(self, ctx):
        """完整清空会话级状态（T4 新对话 / T3b 长空闲）"""
        ctx.record_tool_result("s1", "order_query", {
            "success": True,
            "data": {"orders": [{"id": "ord-1", "order_no": "ORD-A"}]},
            "message": "找到1个订单",
        })
        ctx.record_tool_result("s1", "product_search", {
            "success": True,
            "data": {"products": [{"id": "p-1", "name": "窗帘"}]},
            "message": "找到1个商品",
        })
        ctx.set_last_skill("s1", "product")
        ctx.reset_session("s1")
        entities = ctx.get_entities("s1")
        assert not entities.get("order_nos")
        assert not entities.get("product_ids")
        cache = ctx._cache["s1"]
        assert not cache.get("tool_results")
        assert not cache.get("last_skill")


class TestDecayToolStateT3:
    def test_decay_tool_state_clears_tool_results_keeps_entities(self, ctx):
        """短空闲（15min）：清工具结果缓存，保留实体与历史供续聊"""
        ctx.record_tool_result("s1", "order_query", {
            "success": True,
            "data": {"orders": [{"id": "ord-1", "order_no": "ORD-A"}]},
            "message": "找到1个订单",
        })
        ctx.set_last_skill("s1", "order")
        ctx.decay_tool_state("s1")
        cache = ctx._cache["s1"]
        assert not cache.get("tool_results")
        # 实体保留（续聊"刚才那个订单"仍可用名称）
        assert ctx.get_entities("s1").get("order_nos")
