"""
对话上下文追踪器 (Context Tracker) 单元测试

测试覆盖：
- 实体提取（订单号、手机号、金额等正则匹配）
- 对话状态转换
- 意图链记录
- 指代消解
- 上下文摘要生成
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.context.tracker import (
    ConversationTracker,
    ConversationStage,
    ExtractedEntities,
)


# ========== ExtractedEntities 测试 ==========

class TestExtractedEntities:
    """实体数据类测试"""

    def test_is_empty_initial(self):
        """初始状态为空"""
        entities = ExtractedEntities()
        assert entities.is_empty() is True

    def test_is_empty_after_add(self):
        """添加数据后非空"""
        entities = ExtractedEntities()
        entities.add_order_no("ORD001")
        assert entities.is_empty() is False

    def test_add_unique_deduplication(self):
        """去重添加"""
        entities = ExtractedEntities()
        entities.add_order_no("ORD001")
        entities.add_order_no("ORD001")
        assert len(entities.order_nos) == 1

    def test_to_summary_str(self):
        """摘要字符串生成"""
        entities = ExtractedEntities()
        entities.add_order_no("ORD001")
        entities.add_phone("13800138000")
        summary = entities.to_summary_str()
        assert "ORD001" in summary
        assert "13800138000" in summary

    def test_to_summary_str_empty(self):
        """空实体的摘要"""
        entities = ExtractedEntities()
        assert entities.to_summary_str() == "无"

    def test_get_latest_entity_for_pronoun_order(self):
        """指代消解：优先返回订单号"""
        entities = ExtractedEntities()
        entities.add_order_no("ORD001")
        entities.add_product_name("遮光窗帘")
        ref = entities.get_latest_entity_for_pronoun()
        assert "ORD001" in ref

    def test_get_latest_entity_for_pronoun_product(self):
        """指代消解：无订单号时返回商品名"""
        entities = ExtractedEntities()
        entities.add_product_name("遮光窗帘")
        ref = entities.get_latest_entity_for_pronoun()
        assert "遮光窗帘" in ref

    def test_get_latest_entity_for_pronoun_none(self):
        """指代消解：无实体时返回 None"""
        entities = ExtractedEntities()
        assert entities.get_latest_entity_for_pronoun() is None


# ========== 实体提取测试 ==========

class TestEntityExtraction:
    """实体提取测试"""

    @pytest.fixture
    def tracker(self):
        return ConversationTracker()

    def test_extract_order_no_with_label(self, tracker):
        """提取带标签的订单号"""
        tracker.extract_entities_from_text("s1", "订单号：ORD-123456")
        entities = tracker.get_entities("s1")
        assert "ORD-123456" in entities.order_nos

    def test_extract_order_no_pattern_ORD(self, tracker):
        """提取 ORD 前缀订单号"""
        tracker.extract_entities_from_text("s1", "我的订单 ORD123456789 状态怎样")
        entities = tracker.get_entities("s1")
        assert any("ORD123456789" in no for no in entities.order_nos)

    def test_extract_order_no_pattern_SO(self, tracker):
        """提取 SO 前缀订单号"""
        tracker.extract_entities_from_text("s1", "SO20250503123456 已发货了吗")
        entities = tracker.get_entities("s1")
        assert any("SO20250503123456" in no for no in entities.order_nos)

    def test_extract_phone_with_label(self, tracker):
        """提取带标签的手机号"""
        tracker.extract_entities_from_text("s1", "手机号：13812345678")
        entities = tracker.get_entities("s1")
        assert "13812345678" in entities.phone_numbers

    def test_extract_phone_standalone(self, tracker):
        """提取独立的手机号"""
        tracker.extract_entities_from_text("s1", "请联系我 13912345678")
        entities = tracker.get_entities("s1")
        assert "13912345678" in entities.phone_numbers

    def test_extract_amount(self, tracker):
        """提取金额"""
        tracker.extract_entities_from_text("s1", "价格是299.99元")
        entities = tracker.get_entities("s1")
        assert any("299.99" in a for a in entities.amounts)

    def test_extract_product_id(self, tracker):
        """提取商品 ID"""
        tracker.extract_entities_from_text("s1", "商品ID：12345")
        entities = tracker.get_entities("s1")
        assert "12345" in entities.product_ids

    def test_extract_multiple_entities(self, tracker):
        """一条消息提取多个实体"""
        tracker.extract_entities_from_text(
            "s1", "订单号ORD-999888 手机号13800138000 金额199元"
        )
        entities = tracker.get_entities("s1")
        assert len(entities.order_nos) >= 1
        assert len(entities.phone_numbers) >= 1
        assert len(entities.amounts) >= 1

    def test_accumulate_entities_across_messages(self, tracker):
        """跨消息累积实体"""
        tracker.extract_entities_from_text("s1", "订单号ORD-001")
        tracker.extract_entities_from_text("s1", "手机号13800138000")
        entities = tracker.get_entities("s1")
        assert len(entities.order_nos) >= 1
        assert len(entities.phone_numbers) >= 1

    def test_extract_from_tool_result_order(self, tracker):
        """从 Tool 结果提取订单实体"""
        result = {
            "data": {
                "order_no": "ORD-TOOL-001",
                "phone": "13900139000",
                "total_amount": 599,
                "items": [{"product_name": "高遮光窗帘"}],
            }
        }
        tracker.extract_entities_from_tool_result("s1", "order_query", result)
        entities = tracker.get_entities("s1")
        assert "ORD-TOOL-001" in entities.order_nos
        assert "13900139000" in entities.phone_numbers
        assert "高遮光窗帘" in entities.product_names

    def test_extract_from_tool_result_product(self, tracker):
        """从 Tool 结果提取商品实体"""
        result = {"data": {"name": "雪尼尔窗帘", "id": 42, "price": 299}}
        tracker.extract_entities_from_tool_result("s1", "product_detail", result)
        entities = tracker.get_entities("s1")
        assert "雪尼尔窗帘" in entities.product_names
        assert "42" in entities.product_ids


# ========== 对话状态转换测试 ==========

class TestConversationStage:
    """对话阶段管理测试"""

    @pytest.fixture
    def tracker(self):
        return ConversationTracker()

    def test_initial_stage(self, tracker):
        """初始阶段为 INITIAL"""
        assert tracker.get_stage("s1") == ConversationStage.INITIAL

    def test_update_stage(self, tracker):
        """手动更新阶段"""
        tracker.update_stage("s1", ConversationStage.QUERYING)
        assert tracker.get_stage("s1") == ConversationStage.QUERYING

    def test_infer_stage_from_intent_greeting(self, tracker):
        """greeting → INITIAL"""
        stage = tracker.infer_stage_from_intent("s1", "greeting")
        assert stage == ConversationStage.INITIAL

    def test_infer_stage_from_intent_order_query(self, tracker):
        """order_query → QUERYING"""
        stage = tracker.infer_stage_from_intent("s1", "order_query")
        assert stage == ConversationStage.QUERYING

    def test_infer_stage_from_intent_after_sales(self, tracker):
        """after_sales → CONFIRMING"""
        stage = tracker.infer_stage_from_intent("s1", "after_sales")
        assert stage == ConversationStage.CONFIRMING

    def test_infer_stage_from_intent_complaint(self, tracker):
        """complaint → CONFIRMING"""
        stage = tracker.infer_stage_from_intent("s1", "complaint")
        assert stage == ConversationStage.CONFIRMING


# ========== 意图链测试 ==========

class TestIntentChain:
    """意图链记录测试"""

    @pytest.fixture
    def tracker(self):
        return ConversationTracker()

    def test_append_intent(self, tracker):
        """追加意图"""
        tracker.append_intent("s1", "greeting")
        tracker.append_intent("s1", "order_query")
        chain = tracker.get_intent_chain("s1")
        assert chain == ["greeting", "order_query"]

    def test_deduplicate_consecutive(self, tracker):
        """连续重复意图去重"""
        tracker.append_intent("s1", "order_query")
        tracker.append_intent("s1", "order_query")
        chain = tracker.get_intent_chain("s1")
        assert len(chain) == 1

    def test_non_consecutive_duplicates_kept(self, tracker):
        """非连续重复意图保留"""
        tracker.append_intent("s1", "order_query")
        tracker.append_intent("s1", "logistics_track")
        tracker.append_intent("s1", "order_query")
        chain = tracker.get_intent_chain("s1")
        assert chain == ["order_query", "logistics_track", "order_query"]

    def test_max_chain_length(self, tracker):
        """意图链最多 20 个"""
        for i in range(25):
            tracker.append_intent("s1", f"intent_{i}")
        chain = tracker.get_intent_chain("s1")
        assert len(chain) <= 20


# ========== 指代消解测试 ==========

class TestPronounResolution:
    """指代消解测试"""

    @pytest.fixture
    def tracker(self):
        t = ConversationTracker()
        t.extract_entities_from_text("s1", "订单号ORD-999")
        return t

    def test_resolve_pronoun_hit(self, tracker):
        """检测到指代词且有实体 → 返回提示"""
        hint = tracker.resolve_pronouns("s1", "那个订单怎么还没到")
        assert hint is not None
        assert "ORD-999" in hint

    def test_resolve_pronoun_no_pronoun(self, tracker):
        """无指代词 → 返回 None"""
        hint = tracker.resolve_pronouns("s1", "订单状态是什么")
        assert hint is None

    def test_resolve_pronoun_no_entity(self):
        """有指代词但无实体 → 返回 None"""
        tracker = ConversationTracker()
        hint = tracker.resolve_pronouns("s2", "那个怎么回事")
        assert hint is None


# ========== 上下文摘要测试 ==========

class TestContextSummary:
    """上下文摘要生成测试"""

    @pytest.fixture
    def tracker(self):
        return ConversationTracker()

    def test_empty_summary(self, tracker):
        """空状态 → 空摘要"""
        summary = tracker.generate_context_summary("s_new")
        assert summary == ""

    def test_summary_with_entities(self, tracker):
        """有实体时生成 XML 格式摘要"""
        tracker.extract_entities_from_text("s1", "订单号ORD-001")
        tracker.append_intent("s1", "order_query")
        summary = tracker.generate_context_summary("s1")
        assert "<context_summary>" in summary
        assert "ORD-001" in summary
        assert "order_query" in summary

    def test_summary_with_intent_chain_only(self, tracker):
        """只有意图链也生成摘要"""
        tracker.append_intent("s1", "greeting")
        summary = tracker.generate_context_summary("s1")
        assert "<intent_chain>" in summary


# ========== 对话历史压缩测试 ==========

class TestHistoryCompression:
    """对话历史压缩测试"""

    @pytest.fixture
    def tracker(self):
        return ConversationTracker()

    @pytest.mark.asyncio
    async def test_no_compression_short_history(self, tracker):
        """短历史不压缩"""
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "您好"},
        ]
        result = await tracker.compress_history(history, "s1", max_turns=10)
        assert result == history

    @pytest.mark.asyncio
    async def test_compression_triggered(self, tracker):
        """超长历史触发压缩"""
        # 构造 12 轮对话
        history = []
        for i in range(12):
            history.append({"role": "user", "content": f"问题{i}"})
            history.append({"role": "assistant", "content": f"回答{i}"})

        with patch.object(
            tracker, "_summarize_history",
            new_callable=AsyncMock,
            return_value="对话摘要内容",
        ):
            result = await tracker.compress_history(
                history, "s1", max_turns=10, keep_recent=5
            )

        # 压缩后第一条应该是摘要
        assert result[0]["role"] == "system"
        assert "摘要" in result[0]["content"]
        # 总长度应小于原始历史
        assert len(result) < len(history)

    @pytest.mark.asyncio
    async def test_empty_history(self, tracker):
        """空历史不压缩"""
        result = await tracker.compress_history([], "s1")
        assert result == []


# ========== 会话清理测试 ==========

class TestSessionCleanup:
    """会话清理测试"""

    def test_clear_session(self):
        """清理会话状态"""
        tracker = ConversationTracker()
        tracker.extract_entities_from_text("s1", "订单号ORD-001")
        tracker.clear_session("s1")
        # 清理后获取的是全新状态
        entities = tracker.get_entities("s1")
        assert entities.is_empty()

    def test_clear_nonexistent_session(self):
        """清理不存在的会话不报错"""
        tracker = ConversationTracker()
        tracker.clear_session("nonexistent")
