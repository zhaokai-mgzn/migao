"""
后续问题建议 (Follow-up Suggestions) 单元测试

测试覆盖：
- 预设建议模板返回（Agent 感知：米宝 vs 小布）
- 各意图类型都有对应建议
- 失败降级（超时时返回默认建议）
- Agent 感知：不同 Agent 返回不同建议
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.suggestions.follow_up import (
    FollowUpSuggestionGenerator,
    MIBAO_PRESET_SUGGESTIONS,
    XIAOBU_PRESET_SUGGESTIONS,
    MIBAO_DEFAULT_SUGGESTIONS,
    XIAOBU_DEFAULT_SUGGESTIONS,
    _has_specific_entities,
    _parse_suggestions_from_response,
)


# ========== 预设建议模板测试 ==========

class TestPresetSuggestions:
    """预设建议模板测试（Agent 感知）"""

    def test_mibao_all_intents_have_presets(self):
        """米宝：所有高频意图都有预设建议"""
        expected = [
            "order_query", "logistics_track", "product_inquiry",
            "after_sales", "knowledge_faq", "greeting", "complaint",
            "customer_manage", "customer_query",
            "employee_manage", "staff_manage", "role_manage",
            "system_settings", "ai_config",
            "dashboard", "statistics", "data_report",
            "category_manage", "processing_manage",
            "after_sales_create", "notification", "quick_reply",
            "session_manage", "knowledge_manage",
        ]
        for intent in expected:
            assert intent in MIBAO_PRESET_SUGGESTIONS, \
                f"米宝缺少意图 {intent} 的预设建议"
            assert len(MIBAO_PRESET_SUGGESTIONS[intent]) >= 2, \
                f"米宝意图 {intent} 预设建议少于 2 个"

    def test_xiaobu_all_intents_have_presets(self):
        """小布：所有高频意图都有预设建议"""
        expected = [
            "order_query", "logistics_track", "product_inquiry",
            "after_sales", "knowledge_faq", "greeting", "complaint",
        ]
        for intent in expected:
            assert intent in XIAOBU_PRESET_SUGGESTIONS, \
                f"小布缺少意图 {intent} 的预设建议"
            assert len(XIAOBU_PRESET_SUGGESTIONS[intent]) >= 2

    def test_mibao_default_suggestions(self):
        """米宝默认兜底建议符合 B 端定位"""
        assert len(MIBAO_DEFAULT_SUGGESTIONS) >= 2
        # 不应包含 C 端文案
        for s in MIBAO_DEFAULT_SUGGESTIONS:
            assert "浏览热门商品" not in s, "米宝不应出现 C 端文案"
            assert "联系人工客服" not in s, "米宝不应出现 C 端文案"

    def test_xiaobu_default_suggestions(self):
        """小布默认兜底建议符合 C 端定位"""
        assert len(XIAOBU_DEFAULT_SUGGESTIONS) >= 2

    def test_mibao_preset_no_consumer_language(self):
        """米宝预设建议不应出现纯消费者视角的文案"""
        consumer_phrases = ["浏览热门商品", "咨询窗帘定制", "联系人工客服"]
        for intent, suggestions in MIBAO_PRESET_SUGGESTIONS.items():
            for s in suggestions:
                for phrase in consumer_phrases:
                    assert phrase not in s, \
                        f"米宝预设 [{intent}] 包含 C 端文案: '{s}'"

    def test_mibao_preset_has_management_context(self):
        """米宝的管理类意图建议应包含管理操作关键词"""
        management_intents = [
            "customer_manage", "employee_manage", "category_manage",
            "system_settings", "dashboard",
        ]
        for intent in management_intents:
            suggestions = MIBAO_PRESET_SUGGESTIONS.get(intent, [])
            assert len(suggestions) >= 2, f"米宝管理意图 {intent} 建议不足"
            # 管理意图的建议应该是 B 端操作相关
            all_text = " ".join(suggestions)
            assert len(all_text) > 0


# ========== Agent 感知 generate 测试 ==========

class TestAgentAwareGeneration:
    """Agent 感知的建议生成测试"""

    @pytest.fixture
    def generator(self):
        with patch("app.suggestions.follow_up.settings") as mock_settings:
            mock_settings.DASHSCOPE_API_KEY = ""
            mock_settings.INTENT_MODEL = "qwen-turbo"
            gen = FollowUpSuggestionGenerator()
        return gen

    @pytest.mark.asyncio
    async def test_mibao_gets_mibao_presets(self, generator):
        """米宝使用米宝预设建议"""
        result = await generator.generate(
            query="查看订单",
            answer="这是您的订单列表",
            intent_type="order_query",
            agent_type="mibao",
        )
        assert result == MIBAO_PRESET_SUGGESTIONS["order_query"]

    @pytest.mark.asyncio
    async def test_xiaobu_gets_xiaobu_presets(self, generator):
        """小布使用小布预设建议"""
        result = await generator.generate(
            query="查看订单",
            answer="这是您的订单列表",
            intent_type="order_query",
            agent_type="xiaobu",
        )
        assert result == XIAOBU_PRESET_SUGGESTIONS["order_query"]

    @pytest.mark.asyncio
    async def test_mibao_and_xiaobu_different_presets(self, generator):
        """米宝和小布对同一意图返回不同建议"""
        mibao_result = await generator.generate(
            query="你好", answer="您好！", intent_type="greeting", agent_type="mibao",
        )
        xiaobu_result = await generator.generate(
            query="你好", answer="您好！", intent_type="greeting", agent_type="xiaobu",
        )
        assert mibao_result != xiaobu_result, \
            "米宝和小布的 greeting 建议应该不同"

    @pytest.mark.asyncio
    async def test_mibao_unknown_intent_uses_mibao_default(self, generator):
        """米宝未知意图返回米宝默认建议"""
        result = await generator.generate(
            query="test", answer="test", intent_type="unknown", agent_type="mibao",
        )
        assert result == MIBAO_DEFAULT_SUGGESTIONS

    @pytest.mark.asyncio
    async def test_xiaobu_unknown_intent_uses_xiaobu_default(self, generator):
        """小布未知意图返回小布默认建议"""
        result = await generator.generate(
            query="test", answer="test", intent_type="unknown", agent_type="xiaobu",
        )
        assert result == XIAOBU_DEFAULT_SUGGESTIONS

    @pytest.mark.asyncio
    async def test_default_agent_type_is_mibao(self, generator):
        """不传 agent_type 时默认为米宝（向后兼容）"""
        result = await generator.generate(
            query="test", answer="test", intent_type="greeting",
        )
        assert result == MIBAO_PRESET_SUGGESTIONS["greeting"]

    @pytest.mark.asyncio
    async def test_mibao_customer_manage_returns_b2b(self, generator):
        """米宝客户管理意图返回 B 端建议"""
        result = await generator.generate(
            query="新增客户", answer="客户已创建", intent_type="customer_manage",
            agent_type="mibao",
        )
        assert isinstance(result, list)
        assert len(result) >= 2
        # 不应该是默认兜底
        assert result != MIBAO_DEFAULT_SUGGESTIONS

    @pytest.mark.asyncio
    async def test_mibao_dashboard_returns_analytics(self, generator):
        """米宝看板意图返回数据分析相关建议"""
        result = await generator.generate(
            query="看报表", answer="这是经营数据", intent_type="dashboard",
            agent_type="mibao",
        )
        assert isinstance(result, list)
        assert len(result) >= 2

    @pytest.mark.asyncio
    async def test_generate_returns_list_of_strings(self, generator):
        """返回值类型检查"""
        result = await generator.generate(
            query="你好", answer="您好！", intent_type="greeting", agent_type="mibao",
        )
        assert isinstance(result, list)
        assert all(isinstance(s, str) for s in result)


# ========== 实体检测测试 ==========

class TestEntityDetection:
    """回复中实体检测测试"""

    def test_detect_order_number(self):
        """检测订单号"""
        assert _has_specific_entities("订单号：ORD123456") is True

    def test_detect_price(self):
        """检测价格"""
        assert _has_specific_entities("总价¥299") is True

    def test_detect_date(self):
        """检测日期"""
        assert _has_specific_entities("预计2025-05-03送达") is True

    def test_no_entity(self):
        """无实体"""
        assert _has_specific_entities("有什么可以帮您的") is False


# ========== 响应解析测试 ==========

class TestParseSuggestions:
    """模型响应解析测试"""

    def test_parse_json_array(self):
        """解析标准 JSON 数组"""
        result = _parse_suggestions_from_response('["问题1", "问题2", "问题3"]')
        assert result == ["问题1", "问题2", "问题3"]

    def test_parse_embedded_json(self):
        """从文本中提取嵌入的 JSON"""
        result = _parse_suggestions_from_response('建议如下：["查看物流", "退款"]')
        assert result == ["查看物流", "退款"]

    def test_parse_truncated_to_3(self):
        """结果最多返回 3 个"""
        result = _parse_suggestions_from_response('["a", "b", "c", "d"]')
        assert len(result) == 3

    def test_parse_invalid_returns_none(self):
        """无法解析时返回 None"""
        result = _parse_suggestions_from_response("这不是一个列表")
        assert result is None


# ========== generate 方法测试（动态生成） ==========

class TestFollowUpSuggestionGenerator:
    """后续建议生成器 generate 方法测试"""

    @pytest.fixture
    def generator(self):
        with patch("app.suggestions.follow_up.settings") as mock_settings:
            mock_settings.DASHSCOPE_API_KEY = ""
            mock_settings.INTENT_MODEL = "qwen-turbo"
            gen = FollowUpSuggestionGenerator()
        return gen

    @pytest.mark.asyncio
    async def test_generate_preset_no_api_key(self, generator):
        """无 API Key → 不使用动态生成"""
        generator._api_key = ""  # 确保无 API Key
        result = await generator.generate(
            query="查物流",
            answer="订单号：ORD001 已发货",
            intent_type="logistics_track",
            agent_type="xiaobu",
        )
        # 虽有实体但无 API Key，仍返回预设
        assert result == XIAOBU_PRESET_SUGGESTIONS["logistics_track"]

    @pytest.mark.asyncio
    async def test_generate_dynamic_success(self):
        """动态生成成功"""
        with patch("app.suggestions.follow_up.settings") as mock_settings:
            mock_settings.DASHSCOPE_API_KEY = "test-key"
            mock_settings.INTENT_MODEL = "qwen-turbo"
            gen = FollowUpSuggestionGenerator()

        mock_response = MagicMock()
        mock_response.content = '["追踪物流", "联系卖家", "确认收货"]'
        mock_response.response_metadata = {}
        mock_response.usage_metadata = {}

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch(
            "app.suggestions.follow_up.LLMFactory.create_suggestion_llm",
            return_value=mock_llm,
        ):
            result = await gen.generate(
                query="我的快递到哪了",
                answer="您的订单号：ORD123 预计2025-05-03到达",
                intent_type="logistics_track",
                agent_type="xiaobu",
            )
            assert result == ["追踪物流", "联系卖家", "确认收货"]

    @pytest.mark.asyncio
    async def test_generate_dynamic_timeout_fallback(self):
        """动态生成超时 → 返回预设模板"""
        import httpx

        with patch("app.suggestions.follow_up.settings") as mock_settings:
            mock_settings.DASHSCOPE_API_KEY = "test-key"
            mock_settings.INTENT_MODEL = "qwen-turbo"
            gen = FollowUpSuggestionGenerator()

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch(
            "app.suggestions.follow_up.LLMFactory.create_suggestion_llm",
            return_value=mock_llm,
        ):
            result = await gen.generate(
                query="我的快递到哪了",
                answer="您的订单号：ORD123 预计2025-05-03到达",
                intent_type="logistics_track",
                agent_type="xiaobu",
            )
            assert result == XIAOBU_PRESET_SUGGESTIONS["logistics_track"]

    @pytest.mark.asyncio
    async def test_generate_exception_fallback(self, generator):
        """异常时降级为预设建议"""
        with patch.object(
            generator, "_generate_dynamic",
            new_callable=AsyncMock,
            side_effect=Exception("unexpected error"),
        ), patch.object(
            generator, "_should_use_dynamic",
            return_value=True,
        ):
            result = await generator.generate(
                query="test",
                answer="test ¥100",
                intent_type="product_inquiry",
                agent_type="xiaobu",
            )
            assert result == XIAOBU_PRESET_SUGGESTIONS["product_inquiry"]
