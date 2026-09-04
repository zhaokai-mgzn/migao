# case_ids: MC-001, MC-002, MC-013, MC-014
"""记忆提取器单元测试（app/memory/extractor.py）

覆盖：_parse_extraction_result / extract_memories_from_turn / extract_and_save /
C 端受控词表 / PII 变体过滤 / agent_type 分流 / context 去 PII /
会话末聚合（extract_and_accumulate / flush_memories，issue #2815）。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.memory.extractor import (
    _parse_extraction_result,
    extract_memories_from_turn,
    extract_and_save,
    extract_and_accumulate,
    flush_memories,
)


class TestParseExtractionResult:
    """_parse_extraction_result：纯 JSON / 内嵌数组 / 非法输入"""

    def test_pure_json_array(self):
        result = _parse_extraction_result(
            '[{"type": "preference", "key": "style", "value": "简约", "importance": 0.8}]'
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["type"] == "preference"
        assert result[0]["key"] == "style"

    def test_json_array_embedded_in_text(self):
        result = _parse_extraction_result(
            '好的，提取结果如下：[{"type": "fact", "key": "order", "value": "ORD123"}] 以上'
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["type"] == "fact"

    def test_non_json_returns_empty(self):
        assert _parse_extraction_result("这里没有 JSON") == []

    def test_dict_not_list_returns_empty(self):
        assert _parse_extraction_result('{"type": "preference"}') == []

    def test_blank_returns_empty(self):
        assert _parse_extraction_result("   ") == []


class TestExtractMemoriesFromTurn:
    """extract_memories_from_turn：短对话跳过 / LLM 流程 / 异常兜底"""

    @pytest.mark.asyncio
    async def test_short_turn_skips_without_llm(self):
        with patch("app.llm.LLMFactory") as mock_factory:
            result = await extract_memories_from_turn(
                user_message="你好",
                assistant_reply="您好",
                session_id="s1",
            )
        assert result == []
        mock_factory.create_suggestion_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_result_gets_context_appended(self):
        mock_response = MagicMock()
        mock_response.content = '[{"type": "preference", "key": "curtain_style", "value": "奶油风"}]'
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch(
            "app.llm.LLMFactory.create_suggestion_llm",
            return_value=mock_llm,
        ):
            result = await extract_memories_from_turn(
                user_message="我的订单号是ORD-123",
                assistant_reply="好的，已记录您的订单号。",
                session_id="sess-1",
                agent_type="xiaobu",
            )

        assert len(result) == 1
        # context 去 PII：仅存会话标识与 agent，不再写原始 user_message（issue #2815）
        assert result[0]["context"] == "session=sess-1 | agent=xiaobu"

    @pytest.mark.asyncio
    async def test_existing_context_not_overwritten(self):
        mock_response = MagicMock()
        mock_response.content = (
            '[{"type": "preference", "key": "curtain_style", "value": "奶油风", "context": "已有"}]'
        )
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch(
            "app.llm.LLMFactory.create_suggestion_llm",
            return_value=mock_llm,
        ):
            result = await extract_memories_from_turn(
                user_message="我喜欢奶油风的窗帘",
                assistant_reply="好的，已为您记下。",
                session_id="sess-2",
                agent_type="xiaobu",
            )

        assert result[0]["context"] == "已有"

    @pytest.mark.asyncio
    async def test_llm_exception_returns_empty(self):
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("llm down"))

        with patch(
            "app.llm.LLMFactory.create_suggestion_llm",
            return_value=mock_llm,
        ):
            result = await extract_memories_from_turn(
                user_message="帮我查一下订单状态好吗",
                assistant_reply="您的订单已经发货，请注意查收物流信息。",
                session_id="sess-3",
            )

        assert result == []


class TestExtractAndSave:
    """extract_and_save：无记忆 / 保存成功 / 保存异常"""

    @pytest.mark.asyncio
    async def test_no_memories_returns_zero(self):
        with patch(
            "app.memory.extractor.extract_memories_from_turn",
            new_callable=AsyncMock,
            return_value=[],
        ):
            count = await extract_and_save(
                tenant_id=1, user_id="u1",
                user_message="你好", assistant_reply="您好",
                session_id="s1",
            )
        assert count == 0

    @pytest.mark.asyncio
    async def test_batch_upsert_returns_count(self):
        items = [{"type": "fact", "key": "curtain_style", "value": "奶油风"}]
        mock_manager = MagicMock()
        mock_manager.batch_upsert = AsyncMock(return_value=1)

        with patch(
            "app.memory.extractor.extract_memories_from_turn",
            new_callable=AsyncMock,
            return_value=items,
        ), patch(
            "app.memory.extractor.UserMemoryManager",
            return_value=mock_manager,
        ):
            count = await extract_and_save(
                tenant_id=1, user_id="u1",
                user_message="我喜欢奶油风窗帘", assistant_reply="好的，已记录。",
                session_id="s1",
                agent_type="xiaobu",
            )
        assert count == 1
        mock_manager.batch_upsert.assert_awaited_once_with(
            1, "u1", items, agent_type="xiaobu"
        )

    @pytest.mark.asyncio
    async def test_batch_upsert_exception_returns_zero(self):
        items = [{"type": "preference", "key": "curtain_style", "value": "奶油风"}]
        mock_manager = MagicMock()
        mock_manager.batch_upsert = AsyncMock(side_effect=RuntimeError("db down"))

        with patch(
            "app.memory.extractor.extract_memories_from_turn",
            new_callable=AsyncMock,
            return_value=items,
        ), patch(
            "app.memory.extractor.UserMemoryManager",
            return_value=mock_manager,
        ):
            count = await extract_and_save(
                tenant_id=1, user_id="u1",
                user_message="我喜欢奶油风窗帘", assistant_reply="好的，已记录。",
                session_id="s1",
                agent_type="xiaobu",
            )
        assert count == 0


class TestFilterPii:
    """_filter_pii：PII 记忆过滤（手机号/地址/邮箱不落库）"""

    def test_phone_in_value_dropped(self):
        from app.memory.extractor import _filter_pii
        result = _filter_pii([{"type": "fact", "key": "contact", "value": "手机 13812345678"}])
        assert result == []

    def test_phone_key_dropped(self):
        from app.memory.extractor import _filter_pii
        result = _filter_pii([{"type": "fact", "key": "phone", "value": "13812345678"}])
        assert result == []

    def test_address_key_dropped(self):
        from app.memory.extractor import _filter_pii
        result = _filter_pii([{"type": "fact", "key": "address", "value": "文一西路100号"}])
        assert result == []

    def test_email_key_dropped(self):
        from app.memory.extractor import _filter_pii
        result = _filter_pii([{"type": "fact", "key": "email", "value": "a@b.com"}])
        assert result == []

    def test_normal_memories_kept(self):
        from app.memory.extractor import _filter_pii
        result = _filter_pii([{"type": "preference", "key": "style", "value": "简约风格"}])
        assert len(result) == 1
        assert result[0]["key"] == "style"

    def test_mixed_list_filters_only_pii(self):
        from app.memory.extractor import _filter_pii
        result = _filter_pii([
            {"type": "fact", "key": "order", "value": "ORD-123"},
            {"type": "fact", "key": "phone", "value": "13812345678"},
        ])
        assert len(result) == 1
        assert result[0]["key"] == "order"


class TestPiiVariantFiltering:
    """_filter_pii 变体拦截：LLM 自由生成 key 的 40+ 变体（issue #2815 数据实证）"""

    def test_variant_key_phone(self):
        from app.memory.extractor import _filter_pii
        for key in ("phone", "phone_numbers", "customer_phone", "order_phone",
                    "recipient_phone", "phone_tail", "new_employee_phone",
                    "phone_13812345678", "alternate_phone"):
            assert _filter_pii([{"type": "fact", "key": key, "value": "x"}]) == [], key

    def test_variant_key_address(self):
        from app.memory.extractor import _filter_pii
        for key in ("address", "shipping_address", "delivery_address",
                    "customer_address", "recipient_address", "order_address"):
            assert _filter_pii([{"type": "fact", "key": key, "value": "杭州"}]) == [], key

    def test_variant_key_name(self):
        from app.memory.extractor import _filter_pii
        for key in ("name", "customer_name", "recipient_name", "user_name",
                    "order_customer_name", "new_staff_name"):
            assert _filter_pii([{"type": "fact", "key": key, "value": "张三"}]) == [], key

    def test_phone_in_value_still_dropped(self):
        from app.memory.extractor import _filter_pii
        result = _filter_pii([{"type": "fact", "key": "contact_info", "value": "电话 13812345678"}])
        assert result == []


class TestControlledVocabulary:
    """C 端受控词表：LLM 返回的词表外 key 一律丢弃（消灭语义漂移/去重失效）"""

    def test_out_of_vocabulary_key_dropped(self):
        from app.memory.extractor import _filter_vocabulary
        result = _filter_vocabulary([
            {"type": "preference", "key": "curtain_style", "value": "奶油风"},   # 词表内
            {"type": "fact", "key": "order_count", "value": "160个订单"},          # 会话态错配
            {"type": "fact", "key": "order_id", "value": "ORD-1"},                 # 一次性事实
            {"type": "preference", "key": "random_invented", "value": "xyz"},      # 乱造 key
        ])
        assert len(result) == 1
        assert result[0]["key"] == "curtain_style"

    def test_all_vocabulary_keys_kept(self):
        from app.memory.extractor import _filter_vocabulary, CEND_MEMORY_KEYS
        items = [{"type": "preference", "key": k, "value": "v"} for k in CEND_MEMORY_KEYS]
        result = _filter_vocabulary(items)
        assert len(result) == len(CEND_MEMORY_KEYS)


class TestAgentTypeSplit:
    """agent_type 分流：B 端（mibao）不提取不落库（issue #2815）"""

    @pytest.mark.asyncio
    async def test_mibao_skips_extraction_without_llm(self):
        with patch("app.llm.LLMFactory") as mock_factory:
            result = await extract_memories_from_turn(
                user_message="帮我查一下最近的订单",
                assistant_reply="好的，为您查询到 3 个订单",
                session_id="s1",
                agent_type="mibao",
            )
        assert result == []
        mock_factory.create_suggestion_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_mibao_skips_save_returns_zero(self):
        with patch(
            "app.memory.extractor.extract_memories_from_turn",
            new_callable=AsyncMock,
            return_value=[{"type": "fact", "key": "k", "value": "v"}],
        ), patch(
            "app.memory.extractor.UserMemoryManager",
        ) as mock_mgr_cls:
            count = await extract_and_save(
                tenant_id=1, user_id="u1",
                user_message="msg", assistant_reply="reply",
                session_id="s1", agent_type="mibao",
            )
        assert count == 0
        mock_mgr_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_xiaobu_extracts_and_saves(self):
        items = [{"type": "preference", "key": "curtain_style", "value": "奶油风"}]
        mock_manager = MagicMock()
        mock_manager.batch_upsert = AsyncMock(return_value=1)
        with patch(
            "app.memory.extractor.extract_memories_from_turn",
            new_callable=AsyncMock,
            return_value=items,
        ), patch(
            "app.memory.extractor.UserMemoryManager",
            return_value=mock_manager,
        ):
            count = await extract_and_save(
                tenant_id=1, user_id="u1",
                user_message="我喜欢奶油风的窗帘",
                assistant_reply="好的，已为您记下",
                session_id="s1",
                agent_type="xiaobu",
            )
        assert count == 1
        mock_manager.batch_upsert.assert_awaited_once_with(
            1, "u1", items, agent_type="xiaobu"
        )


class TestContextDePii:
    """context 字段去 PII：不再写原始 user_message 明文（数据实证：context 含手机号/地址）"""

    @pytest.mark.asyncio
    async def test_context_does_not_contain_raw_user_message(self):
        mock_response = MagicMock()
        mock_response.content = '[{"type": "preference", "key": "curtain_style", "value": "奶油风"}]'
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        with patch(
            "app.llm.LLMFactory.create_suggestion_llm",
            return_value=mock_llm,
        ):
            result = await extract_memories_from_turn(
                user_message="我叫张三，电话13800138000，喜欢奶油风的窗帘",
                assistant_reply="好的，已为您记下偏好",
                session_id="sess-1",
                agent_type="xiaobu",
            )
        assert len(result) == 1
        ctx = result[0].get("context", "")
        assert "13800138000" not in ctx
        assert "张三" not in ctx
        assert "sess-1" in ctx


class TestSessionEndAggregation:
    """会话末聚合（issue #2815）：每轮提取累积到 session_states，会话关闭时 flush 落库。

    - extract_and_accumulate：提取 → 合并进 state.memory_candidates（按 key 去重、高 importance 胜出）
    - flush_memories：从 state 读候选 → batch_upsert(user_memories) → 清空候选
    - B 端（mibao）不累积不落库
    """

    @pytest.mark.asyncio
    async def test_mibao_accumulate_skips_without_store(self):
        with patch("app.memory.extractor.extract_memories_from_turn") as mock_extract, \
             patch("app.memory.extractor.SessionStateStore") as mock_store_cls:
            mock_extract.assert_not_called()
            count = await extract_and_accumulate(
                tenant_id=1, user_id="u1", agent_type="mibao",
                session_id="s1", user_message="m", assistant_reply="r",
            )
            assert count == 0
            mock_store_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_accumulate_merges_by_key_keeps_highest_importance(self):
        """同 key 候选按 importance 去重合并（去重失效修复：key 受控后同义不再堆积）"""
        items1 = [{"type": "preference", "key": "curtain_style", "value": "奶油风", "importance": 0.7}]
        items2 = [{"type": "preference", "key": "curtain_style", "value": "简约风", "importance": 0.9}]
        mock_store = MagicMock()
        mock_store.load = AsyncMock(return_value={})
        mock_store.commit = AsyncMock(return_value=True)

        with patch("app.memory.extractor.extract_memories_from_turn",
                   new_callable=AsyncMock, side_effect=[items1, items2]), \
             patch("app.memory.extractor.SessionStateStore", return_value=mock_store):
            await extract_and_accumulate(1, "u1", "xiaobu", "s1", "msg1", "r1")
            await extract_and_accumulate(1, "u1", "xiaobu", "s1", "msg2", "r2")

        payload = mock_store.commit.call_args.args[1]["memory_candidates"]
        assert payload["tenant_id"] == 1
        assert payload["user_id"] == "u1"
        assert payload["agent_type"] == "xiaobu"
        assert len(payload["items"]) == 1
        assert payload["items"][0]["value"] == "简约风"
        assert payload["items"][0]["importance"] == 0.9

    @pytest.mark.asyncio
    async def test_flush_writes_candidates_and_clears(self):
        """flush：读候选载荷 → batch_upsert（带 agent_type）→ 清空 memory_candidates"""
        mock_store = MagicMock()
        mock_store.load = AsyncMock(return_value={
            "memory_candidates": {
                "tenant_id": 1, "user_id": "u1", "agent_type": "xiaobu",
                "items": [
                    {"type": "preference", "key": "curtain_style", "value": "奶油风", "importance": 0.8},
                ],
            },
        })
        mock_store.commit = AsyncMock(return_value=True)
        mock_mgr = MagicMock()
        mock_mgr.batch_upsert = AsyncMock(return_value=1)

        with patch("app.memory.extractor.SessionStateStore", return_value=mock_store), \
             patch("app.memory.extractor.UserMemoryManager", return_value=mock_mgr):
            count = await flush_memories("s1")

        assert count == 1
        mock_mgr.batch_upsert.assert_awaited_once_with(1, "u1", [
            {"type": "preference", "key": "curtain_style", "value": "奶油风", "importance": 0.8},
        ], agent_type="xiaobu")
        # 清空候选后提交
        final_state = mock_store.commit.call_args.args[1]
        assert "memory_candidates" not in final_state

    @pytest.mark.asyncio
    async def test_flush_no_candidates_returns_zero(self):
        mock_store = MagicMock()
        mock_store.load = AsyncMock(return_value={})
        with patch("app.memory.extractor.SessionStateStore", return_value=mock_store), \
             patch("app.memory.extractor.UserMemoryManager") as mock_mgr_cls:
            count = await flush_memories("s1")
        assert count == 0
        mock_mgr_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_exception_returns_zero(self):
        mock_store = MagicMock()
        mock_store.load = AsyncMock(side_effect=RuntimeError("db down"))
        with patch("app.memory.extractor.SessionStateStore", return_value=mock_store):
            count = await flush_memories("s1")
        assert count == 0
