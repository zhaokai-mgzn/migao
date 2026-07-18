"""
AgentContextManager 单元测试

覆盖 context_manager.py 所有核心路径：
- 单例模式、缓存 CRUD、实体提取、上下文构建、对话压缩
"""

import pytest
from collections import OrderedDict
from unittest.mock import patch, MagicMock, AsyncMock


class TestGetContextManager:
    """get_context_manager 单例工厂"""

    def test_returns_singleton(self):
        """多次调用返回同一实例"""
        from app.memory.context_manager import get_context_manager, AgentContextManager
        a = get_context_manager()
        b = get_context_manager()
        assert a is b
        assert isinstance(a, AgentContextManager)

    def test_reset_after_global_clear(self):
        """手动清除全局变量后重新创建"""
        import app.memory.context_manager as mod
        mod._context_manager = None
        mgr = mod.get_context_manager()
        assert mgr is not None
        assert mgr is mod._context_manager


class TestGetOrCreate:
    """_get_or_create 缓存管理"""

    def test_creates_new_cache_entry(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        cache = mgr._get_or_create("sess_1")
        assert isinstance(cache, OrderedDict)
        assert len(cache) == 0
        assert "sess_1" in mgr._cache

    def test_reuses_existing_cache(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        cache1 = mgr._get_or_create("sess_1")
        cache1["foo"] = "bar"
        cache2 = mgr._get_or_create("sess_1")
        assert cache2 is cache1
        assert cache2["foo"] == "bar"

    def test_evicts_oldest_when_over_100_sessions(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        # Fill to 101 sessions
        for i in range(101):
            mgr._get_or_create(f"sess_{i}")
        assert len(mgr._cache) <= 100
        # sess_0 should be evicted (oldest)
        assert "sess_0" not in mgr._cache
        assert "sess_100" in mgr._cache


class TestRecordToolResult:
    """record_tool_result — 记录 tool 调用结果"""

    def test_records_result_and_creates_summary(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        mgr.record_tool_result("sess_1", "product_search", {
            "success": True,
            "message": "找到 3 个商品",
            "data": {"total": 3, "products": [{"id": "p1", "name": "窗帘A"}]}
        })
        cache = mgr._cache["sess_1"]
        assert len(cache["tool_results"]) == 1
        assert cache["tool_results"][0]["tool"] == "product_search"
        assert cache["tool_results"][0]["total"] == 3
        assert "找到 3 个商品" in cache["tool_results"][0]["summary"]

    def test_auto_extracts_entities_from_product_search(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        mgr.record_tool_result("sess_1", "product_search", {
            "success": True,
            "data": {"products": [{"id": "uuid-1", "name": "遮光帘"}]}
        })
        entities = mgr._cache["sess_1"]["entities"]
        assert "product_ids" in entities
        assert entities["product_ids"][0]["id"] == "uuid-1"
        assert entities["product_ids"][0]["name"] == "遮光帘"

    def test_respects_max_tool_results(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        for i in range(12):
            mgr.record_tool_result("sess_1", f"tool_{i}", {
                "success": True, "message": f"result {i}"
            })
        cache = mgr._cache["sess_1"]
        assert len(cache["tool_results"]) == 8  # MAX_TOOL_RESULTS
        # Oldest should be evicted
        tools = [r["tool"] for r in cache["tool_results"]]
        assert "tool_0" not in tools
        assert "tool_11" in tools


class TestSetLastSkill:
    """set_last_skill"""

    def test_sets_and_reads_last_skill(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        mgr.set_last_skill("sess_1", "product")
        assert mgr._cache["sess_1"]["last_skill"] == "product"

        mgr.set_last_skill("sess_1", "order")
        assert mgr._cache["sess_1"]["last_skill"] == "order"


class TestSummarizeResult:
    """_summarize_result — 从 tool result 提取摘要"""

    def test_extracts_key_stats(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        summary = mgr._summarize_result("order_query", {
            "success": True,
            "message": "找到订单",
            "data": {"total": 5, "page": 1, "size": 10, "total_pages": 1}
        })
        assert summary["tool"] == "order_query"
        assert summary["total"] == 5
        assert summary["page"] == 1
        assert summary["size"] == 10
        assert summary["total_pages"] == 1

    def test_truncates_long_message(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        long_msg = "x" * 300
        summary = mgr._summarize_result("test", {
            "success": True, "message": long_msg
        })
        assert len(summary["summary"]) == 200

    def test_handles_missing_data(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        summary = mgr._summarize_result("test", {"success": False, "message": "失败"})
        assert summary["tool"] == "test"
        assert summary["summary"] == "失败"
        assert "total" not in summary


class TestExtractEntities:
    """_extract_entities — 自动提取实体"""

    def test_extracts_product_entities(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        cache = OrderedDict()
        mgr._extract_entities(cache, "product_search", {
            "data": {"products": [
                {"id": "p1", "name": "商品A"},
                {"id": "p2", "name": "商品B"},
            ]}
        })
        assert len(cache["entities"]["product_ids"]) == 2

    def test_dedup_entities_by_id(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        cache = OrderedDict()
        mgr._extract_entities(cache, "product_search", {
            "data": {"products": [{"id": "p1", "name": "商品A"}]}
        })
        mgr._extract_entities(cache, "product_detail", {
            "data": {"products": [{"id": "p1", "name": "商品A"}]}
        })
        assert len(cache["entities"]["product_ids"]) == 1  # dedup

    def test_extracts_order_entities(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        cache = OrderedDict()
        mgr._extract_entities(cache, "order_query", {
            "data": {"orders": [{"id": "uuid-1", "order_no": "ORD-001"}]}
        })
        entities = cache["entities"]["order_nos"]
        assert len(entities) == 1
        assert entities[0]["id"] == "uuid-1"
        assert entities[0]["name"] == "ORD-001"

    def test_extracts_customer_entities(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        cache = OrderedDict()
        mgr._extract_entities(cache, "customer_manage", {
            "data": {"customers": [{"id": "c1", "name": "客户A"}]}
        })
        assert len(cache["entities"]["customer_ids"]) == 1

    def test_extracts_processing_item_entities(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        cache = OrderedDict()
        mgr._extract_entities(cache, "processing_item_query", {
            "data": {"items": [{"id": "pi_1", "name": "S钩安装"}]}
        })
        assert len(cache["entities"]["processing_item_ids"]) == 1

    def test_handles_single_dict_as_list(self):
        """data 中 items 是 dict 而非 list 时自动包装为 list"""
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        cache = OrderedDict()
        mgr._extract_entities(cache, "processing_item_query", {
            "data": {"items": {"id": "pi_solo", "name": "单项"}}
        })
        assert len(cache["entities"]["processing_item_ids"]) == 1

    def test_extracts_vision_fields_from_product_manage(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        cache = OrderedDict()
        mgr._extract_entities(cache, "product_manage", {
            "success": True,
            "data": {"product": {
                "name": "星夜帘",
                "colors": ["蓝", "灰"],
                "price": 268,
                "specifications": "280cm"
            }}
        })
        assert cache["vision_fields"]["name"] == "星夜帘"
        assert cache["vision_fields"]["colors"] == ["蓝", "灰"]
        assert cache["vision_fields"]["price"] == 268

    def test_entity_limit_is_enforced(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        mgr.MAX_ENTITIES = 3
        cache = OrderedDict()
        items = [{"id": f"p{i}", "name": f"商品{i}"} for i in range(10)]
        mgr._extract_entities(cache, "product_search", {"data": {"products": items}})
        assert len(cache["entities"]["product_ids"]) == 3

    def test_skips_items_without_id(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        cache = OrderedDict()
        mgr._extract_entities(cache, "product_search", {
            "data": {"products": [
                {"name": "无ID商品"},
                {"id": "p1", "name": "有ID商品"},
            ]}
        })
        assert len(cache["entities"]["product_ids"]) == 1
        assert cache["entities"]["product_ids"][0]["id"] == "p1"


class TestBuildContext:
    """build_context — 构建注入 LLM 的上下文"""

    def test_builds_basic_context_with_tool_hint(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        ctx = mgr.build_context("sess_new", "product")
        assert "工具链" in ctx
        assert "product_search" in ctx

    def test_builds_context_with_entities(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        mgr.record_tool_result("sess_1", "product_search", {
            "data": {"products": [{"id": "uuid-1", "name": "遮光帘"}]}
        })
        ctx = mgr.build_context("sess_1", "product")
        assert "遮光帘" in ctx
        assert "uuid-1" in ctx
        assert "已知实体" in ctx

    def test_skill_switch_hint(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        mgr.set_last_skill("sess_1", "product")
        ctx = mgr.build_context("sess_1", "order")
        assert "product" in ctx
        assert "复用" in ctx or "刚离开" in ctx

    def test_no_switch_hint_for_same_skill(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        mgr.set_last_skill("sess_1", "product")
        ctx = mgr.build_context("sess_1", "product")
        assert "刚离开" not in ctx

    def test_includes_recent_tool_results(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        mgr.record_tool_result("sess_1", "product_search", {
            "message": "找到遮光窗帘", "data": {}
        })
        ctx = mgr.build_context("sess_1", "product")
        assert "遮光窗帘" in ctx

    def test_respects_max_context_length(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        mgr.MAX_CONTEXT_LENGTH = 50
        # Fill with lots of data
        for i in range(10):
            mgr.record_tool_result("sess_1", f"tool_{i}", {
                "message": f"很长的结果消息文本 {i} " * 5, "data": {}
            })
        ctx = mgr.build_context("sess_1", "product")
        assert len(ctx) <= 50


class TestCompressConversation:
    """compress_conversation — 长对话压缩"""

    def test_short_conversation_no_compress(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        messages = [MagicMock(type='human', content='hi')] * 5
        result = mgr._cache["sess_1"] = OrderedDict()
        import asyncio
        summary = asyncio.run(mgr.compress_conversation("sess_1", messages, max_recent=12))
        assert summary == ""

    def test_long_conversation_compresses(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()

        msgs = []
        for i in range(20):
            cls = type('HumanMessage', (), {'type': 'human', 'content': f'问题{i}'}) if i % 2 == 0 else \
                  type('AIMessage', (), {'type': 'ai', 'content': f'回答{i}'})
            msgs.append(cls())

        cache = mgr._get_or_create("sess_1")
        import asyncio
        summary = asyncio.run(mgr.compress_conversation("sess_1", msgs, max_recent=12))
        assert "对话历史摘要" in summary
        assert "用户意图" in summary

    def test_compress_includes_entities(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        mgr.record_tool_result("sess_1", "product_search", {
            "data": {"products": [{"id": "uuid-1", "name": "窗帘"}]}
        })

        msgs = []
        for i in range(20):
            cls = type('HumanMessage', (), {'type': 'human', 'content': f'问题{i}'}) if i % 2 == 0 else \
                  type('AIMessage', (), {'type': 'ai', 'content': f'回答{i}'})
            msgs.append(cls())

        import asyncio
        summary = asyncio.run(mgr.compress_conversation("sess_1", msgs, max_recent=12))
        assert "窗帘" in summary

    def test_truncates_long_human_messages(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()

        msgs = [type('HumanMessage', (), {'type': 'human', 'content': 'x' * 100})() for _ in range(5)]
        msgs += [type('HumanMessage', (), {'type': 'human', 'content': 'recent'})()] * 10

        import asyncio
        summary = asyncio.run(mgr.compress_conversation("sess_1", msgs, max_recent=12))
        # Truncated: content > 60 should be cut
        assert "..." in summary


class TestRedisPersistence:
    """save / load — Redis 持久化"""

    @pytest.mark.asyncio
    async def test_save_without_redis(self):
        """Redis 不可用时 save 不抛异常"""
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        mgr._cache["sess_1"] = OrderedDict({"entities": {"product_ids": []}})
        # Should not raise
        await mgr.save("sess_1")

    @pytest.mark.asyncio
    async def test_load_without_redis(self):
        """Redis 不可用时 load 不抛异常"""
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        await mgr.load("sess_1")  # Should not raise

    @pytest.mark.asyncio
    @patch("app.utils.redis_client.get_redis")
    async def test_save_to_redis(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        mgr._cache["sess_1"] = OrderedDict({"foo": "bar"})
        await mgr.save("sess_1")
        mock_redis.set.assert_called_once()
        # Key should be ctx:sess_1
        args = mock_redis.set.call_args[0]
        assert args[0] == "ctx:sess_1"

    @pytest.mark.asyncio
    @patch("app.utils.redis_client.get_redis")
    async def test_load_from_redis(self, mock_get_redis):
        import json
        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps({"foo": "loaded"})
        mock_get_redis.return_value = mock_redis
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        await mgr.load("sess_1")
        assert mgr._cache["sess_1"]["foo"] == "loaded"


class TestToolHints:
    """SKILL_TOOL_HINTS 覆盖所有 skill"""

    def test_all_skills_have_hints(self):
        from app.memory.context_manager import AgentContextManager
        expected = {"product", "order", "aftersales", "customer",
                    "staff", "settings", "data", "general"}
        assert set(AgentContextManager.SKILL_TOOL_HINTS.keys()) == expected

    def test_unknown_skill_no_hint(self):
        from app.memory.context_manager import AgentContextManager
        mgr = AgentContextManager()
        ctx = mgr.build_context("sess_1", "nonexistent_skill")
        assert "工具链" not in ctx
