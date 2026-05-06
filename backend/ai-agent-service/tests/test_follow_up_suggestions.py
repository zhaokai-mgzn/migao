"""
后续问题建议 (Follow-up Suggestions) 单元测试

测试覆盖：
- 预设建议模板返回
- 各意图类型都有对应建议
- 失败降级（超时时返回默认建议）
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.suggestions.follow_up import (
    FollowUpSuggestionGenerator,
    PRESET_SUGGESTIONS,
    DEFAULT_SUGGESTIONS,
    _has_specific_entities,
    _parse_suggestions_from_response,
)


# ========== 预设建议模板测试 ==========

class TestPresetSuggestions:
    """预设建议模板测试"""

    def test_all_intents_have_presets(self):
        """所有高频意图都有预设建议"""
        expected = [
            "order_query", "logistics_track", "product_inquiry",
            "after_sales", "knowledge_faq", "greeting", "complaint",
        ]
        for intent in expected:
            assert intent in PRESET_SUGGESTIONS
            assert len(PRESET_SUGGESTIONS[intent]) >= 2

    def test_default_suggestions_exist(self):
        """默认兜底建议存在且至少 2 个"""
        assert len(DEFAULT_SUGGESTIONS) >= 2

    def test_preset_returns_correct_intent(self):
        """预设模板按意图返回正确建议"""
        gen = FollowUpSuggestionGenerator()
        result = gen._get_preset("order_query")
        assert result == PRESET_SUGGESTIONS["order_query"]

    def test_preset_unknown_intent_returns_default(self):
        """未知意图返回默认建议"""
        gen = FollowUpSuggestionGenerator()
        result = gen._get_preset("unknown_intent_type")
        assert result == DEFAULT_SUGGESTIONS


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


# ========== generate 方法测试 ==========

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
    async def test_generate_preset_no_entities(self, generator):
        """回复无实体 → 返回预设模板"""
        result = await generator.generate(
            query="我的订单在哪",
            answer="您好，请问您的订单号是多少？",
            intent_type="order_query",
        )
        assert result == PRESET_SUGGESTIONS["order_query"]

    @pytest.mark.asyncio
    async def test_generate_preset_no_api_key(self, generator):
        """无 API Key → 不使用动态生成"""
        result = await generator.generate(
            query="查物流",
            answer="订单号：ORD001 已发货",
            intent_type="logistics_track",
        )
        # 虽有实体但无 API Key，仍返回预设
        assert result == PRESET_SUGGESTIONS["logistics_track"]

    @pytest.mark.asyncio
    async def test_generate_dynamic_success(self):
        """动态生成成功"""
        with patch("app.suggestions.follow_up.settings") as mock_settings:
            mock_settings.DASHSCOPE_API_KEY = "test-key"
            mock_settings.INTENT_MODEL = "qwen-turbo"
            gen = FollowUpSuggestionGenerator()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '["追踪物流", "联系卖家", "确认收货"]'}}]
        }

        with patch("app.suggestions.follow_up.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            MockClient.return_value = mock_client

            result = await gen.generate(
                query="我的快递到哪了",
                answer="您的订单号：ORD123 预计2025-05-03到达",
                intent_type="logistics_track",
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

        with patch("app.suggestions.follow_up.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            MockClient.return_value = mock_client

            result = await gen.generate(
                query="我的快递到哪了",
                answer="您的订单号：ORD123 预计2025-05-03到达",
                intent_type="logistics_track",
            )
            assert result == PRESET_SUGGESTIONS["logistics_track"]

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
            )
            assert result == PRESET_SUGGESTIONS["product_inquiry"]

    @pytest.mark.asyncio
    async def test_generate_returns_list_of_strings(self, generator):
        """返回值类型检查"""
        result = await generator.generate(
            query="你好",
            answer="您好！",
            intent_type="greeting",
        )
        assert isinstance(result, list)
        assert all(isinstance(s, str) for s in result)
