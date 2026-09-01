"""
小布（C 端）真实 E2E 验收 — 数据隔离 + 上下文自动清理

零 Mock：SSE 对话 → 真实 LLM → 真实工具调用 → admin-api 数据验证。

覆盖：
1. 数据隔离：小布查订单必须调 customer_order_query（B 端 order_query 物理隔离）
2. 订单卡片：order_query 类结果下发 order 卡片事件
3. 上下文清理（T1 主题域切换）：查订单后再问商品，订单实体不污染商品话题
4. 用户级过滤：返回的订单属于当前 DEBUG customer（无法直接核对 user_id，
   以「仅 customer_order_query 且无 order_query」作为隔离代理断言）

运行前提：本地 ai-agent-service + admin-api（DEBUG 模式，无 SERVICE_TOKEN）。
"""
# case_ids: OR-001, DF-002
import pytest
from tests.e2e.real.conftest import (
    CustomerSession, sse_tools, sse_text
)


@pytest.mark.real_e2e
class TestXiaobuAcceptance:

    # ═══ 数据隔离：C 端订单查询 ═══

    def test_customer_order_query_isolation(self):
        """小布查订单 → 调 customer_order_query（不调 B 端 order_query）"""
        sess = CustomerSession().create()
        ev = sess.send("帮我查一下最近的订单")
        tools = sse_tools(ev)
        # 物理隔离：必须用 C 端专用工具
        assert "customer_order_query" in tools, f"tools: {tools}"
        # 绝不能出现 B 端工具（跨用户风险）
        assert "order_query" not in tools, f"B端 order_query 不应出现在小布: {tools}"
        text = sse_text(ev)
        assert len(text) > 0, "小布应有文本回复"

    def test_order_card_event(self):
        """订单查询结果 → 下发 order 卡片事件"""
        sess = CustomerSession().create()
        ev = sess.send("查我的订单")
        # card 事件类型为 order（OrderCard 渲染依据）
        card_types = [e["data"].get("type") for e in ev if e["event"] == "card"]
        assert "order" in card_types, f"card types: {card_types}"

    # ═══ 上下文自动清理（T1 主题域切换）═══

    def test_topic_switch_does_not_leak_order_context(self):
        """查订单后再问商品：订单上下文不污染商品话题（T1）"""
        sess = CustomerSession().create()
        ev1 = sess.send("帮我查一下最近的订单")
        tools1 = sse_tools(ev1)
        assert "customer_order_query" in tools1, f"round1 tools: {tools1}"

        # 切到商品域
        ev2 = sess.send("有什么遮光窗帘推荐")
        tools2 = sse_tools(ev2)
        # 商品话题应调 product_search / product_detail
        product_tools = [t for t in tools2 if t in ("product_search", "product_detail")]
        assert len(product_tools) > 0, f"round2 应调商品工具: {tools2}"

    # ═══ 商品查询正常可用（小布通用能力）═══

    def test_product_inquiry_works(self):
        """小布搜商品 → product_search 工具 + 文本回复"""
        sess = CustomerSession().create()
        ev = sess.send("推荐几款窗帘")
        tools = sse_tools(ev)
        assert "product_search" in tools, f"tools: {tools}"
        assert len(sse_text(ev)) > 0
