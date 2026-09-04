"""
vision 候选实体 → 上下文实体槽 grounding 测试（issue #2821 切片 2，G10 修复）

覆盖 AgentContextManager.record_vision_candidates 公共契约：
- vision 分析识别出的候选商品/订单/客户写入实体槽（source=vision）
- build_context 注入包含 vision 候选实体（图片关联对象有召回保障）
- 重复写入去重；非法 entity_type 拒绝
- 与 _extract_entities 的工具结果提取共存，互不覆盖

Seam: AgentContextManager.record_vision_candidates()（公共接口，
不触碰 _extract_entities 内部实现）。
"""
# case_ids: OB-002

import pytest

from app.memory.context_manager import AgentContextManager


@pytest.fixture
def mgr():
    """独立实例（不走全局单例，避免测试间污染）"""
    return AgentContextManager()


class TestRecordVisionCandidates:
    def test_writes_candidates_with_vision_source(self, mgr):
        """写入后 get_entities 返回带 source=vision 的候选"""
        mgr.record_vision_candidates(
            "sess_v1",
            "product_ids",
            [{"id": "sku-1", "name": "雪尼尔遮光窗帘"}],
        )
        entities = mgr.get_entities("sess_v1")
        assert entities["product_ids"] == [
            {"id": "sku-1", "name": "雪尼尔遮光窗帘", "source": "vision"}
        ]

    def test_build_context_injects_vision_candidates(self, mgr):
        """build_context 注入包含 vision 候选实体（跨轮召回保障）"""
        mgr.record_vision_candidates(
            "sess_v2",
            "product_ids",
            [{"id": "sku-9", "name": "米白雪尼尔"}],
        )
        context = mgr.build_context("sess_v2", "product")
        assert "sku-9" in context
        assert "米白雪尼尔" in context

    def test_duplicate_candidates_deduplicated(self, mgr):
        """重复写入同一候选去重（同 id 或同 name 均不重复）"""
        mgr.record_vision_candidates(
            "sess_v3", "order_nos", [{"id": "o-1", "name": "单号123"}]
        )
        mgr.record_vision_candidates(
            "sess_v3", "order_nos", [{"id": "o-1", "name": "单号123"}]
        )
        mgr.record_vision_candidates(
            "sess_v3", "order_nos", [{"id": "o-1", "name": "单号123改"}]
        )
        entities = mgr.get_entities("sess_v3")
        assert len(entities["order_nos"]) == 1

    def test_invalid_entity_type_rejected(self, mgr):
        """非法 entity_type（不在 ENTITY_DOMAIN）必须拒绝"""
        with pytest.raises(ValueError):
            mgr.record_vision_candidates(
                "sess_v4", "unknown_type", [{"id": "x", "name": "y"}]
            )

    def test_coexists_with_tool_extraction(self, mgr):
        """vision 候选与工具结果提取共存：同类型追加，互不覆盖"""
        # 先通过工具结果提取一个商品实体（模拟 _extract_entities 路径）
        mgr.record_tool_result(
            "sess_v5",
            "product_search",
            {"data": {"products": [{"id": "sku-a", "name": "布艺窗帘"}]}},
        )
        # 再写入 vision 候选
        mgr.record_vision_candidates(
            "sess_v5",
            "product_ids",
            [{"id": "sku-b", "name": "雪尼尔"}],
        )
        entities = mgr.get_entities("sess_v5")
        ids = [e["id"] for e in entities["product_ids"]]
        assert ids == ["sku-a", "sku-b"]
        # 工具提取的 source 保留 tool 名，不被 vision 覆盖
        assert {e["source"] for e in entities["product_ids"]} == {
            "product_search",
            "vision",
        }
