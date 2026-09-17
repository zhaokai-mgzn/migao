# case_ids: MC-003, MC-004, DA-002
"""意图分类器单元测试（app/router/intent_classifier.py）

覆盖：_extract_text / _build_classifier_prompt / IntentClassifier._parse_response / classify。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.router.intent_classifier import (
    _extract_text,
    _build_classifier_prompt,
    _INTENT_DESCRIPTIONS,
    IntentClassifier,
)
from app.router.intent_config import IntentType


class TestExtractText:
    def test_none_returns_empty(self):
        assert _extract_text(None) == ""

    def test_str_returns_same(self):
        assert _extract_text("你好") == "你好"

    def test_list_joins_text_blocks(self):
        content = [
            {"type": "text", "text": "你好"},
            {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
            {"type": "text", "text": "查订单"},
        ]
        assert _extract_text(content) == "你好 查订单"

    def test_list_skips_empty_text(self):
        content = [{"type": "text", "text": ""}, {"type": "text", "text": "ok"}]
        assert _extract_text(content) == "ok"

    def test_other_type_stringified(self):
        assert _extract_text(123) == "123"


class TestBuildClassifierPrompt:
    def test_none_uses_all_intents(self):
        prompt = _build_classifier_prompt(None)
        assert "greeting" in prompt
        assert "order_query" in prompt
        assert "general" in prompt

    def test_missing_general_gets_appended(self):
        prompt = _build_classifier_prompt(["order_query", "product_inquiry"])
        assert "- general:" in prompt

    def test_general_not_duplicated(self):
        prompt = _build_classifier_prompt(["general", "order_query"])
        assert prompt.count("- general:") == 1

    def test_unknown_intent_desc_falls_back_to_name(self):
        prompt = _build_classifier_prompt(["no_such_intent"])
        assert "- no_such_intent: no_such_intent" in prompt

    def test_disambiguation_only_shows_relevant(self):
        prompt = _build_classifier_prompt(["order_query"])
        assert "订单统计" in prompt  # order_query 的消歧规则
        assert "看板/总览" not in prompt  # dashboard 的消歧规则不应出现

    def test_order_trend_disambiguation_to_data_domain(self):
        """DA-002 消歧规则（issue #2854）：'订单趋势/走势/环比/涨跌'须归数据域而非 order_query。

        8-29 基线 DA-002 通过 → 本体论后反复 order_query（12 次）的根因之一是
        L2 分类器把「最近7天订单趋势」误判为订单域查询。此处验证 prompt 消歧规则
        明确指向 dashboard_stats 对应意图。
        """
        prompt = _build_classifier_prompt(["statistics", "dashboard", "order_query", "data_report"])
        assert "订单趋势" in prompt
        assert "走势" in prompt
        assert "环比" in prompt
        assert "涨跌" in prompt
        # 规则必须把趋势类词引向数据域（dashboard_stats），不得引向 order_query
        trend_rule_lines = [ln for ln in prompt.splitlines() if "趋势" in ln and "订单" in ln]
        assert trend_rule_lines, "缺少「订单趋势归数据域」消歧规则"
        joined = " ".join(trend_rule_lines)
        assert "dashboard_stats" in joined or "数据域" in joined or "统计" in joined


class TestIntentDescriptionSync:
    """**不变式**：`_INTENT_DESCRIPTIONS` 必须与 `IntentType` 枚举同步（issue #4010 / A8）。

    为什么是机制层而不是补三条描述：分类器提示的两条构建路径都以描述表为准 ——
    `agent_intents=None` 时 `intents_to_show = list(_INTENT_DESCRIPTIONS.keys())`（**没有
    描述的意图根本不出现在提示里**，分类器永远选不中它），`agent_intents` 给定时
    `_INTENT_DESCRIPTIONS.get(intent, intent)` 退化成裸英文 token（`- quote: quote`）。
    两种退化都**不会报错**、也不会让任何既有测试变红 —— 只能靠不变式守住。

    适用域：`_INTENT_DESCRIPTIONS` 的键集 ↔ `IntentType` 的值集。
    不适用域（**有意保留**）：`agent_intents` 运行时传入 skill 声明的枚举外意图
    （如 order_skill 曾声明的 `processing_order_generate`）仍走 `get(intent, intent)`
    兜底 —— 见 `TestBuildClassifierPrompt.test_unknown_intent_desc_falls_back_to_name`。
    """

    def test_every_enum_value_has_description(self):
        missing = sorted({i.value for i in IntentType} - set(_INTENT_DESCRIPTIONS))
        assert not missing, (
            f"这些 IntentType 取值没有描述（分类器提示会退化成裸英文 token / 整条不出现）：{missing}"
        )

    def test_no_description_outlives_its_enum_value(self):
        """反向同步：枚举删了成员却留下描述 = 提示里出现模型永远返回不了的死意图。"""
        dead = sorted(set(_INTENT_DESCRIPTIONS) - {i.value for i in IntentType})
        assert not dead, f"这些描述键已不在 IntentType 中（死意图，必须一并删除）：{dead}"

    def test_prompt_never_renders_bare_token_for_enum_intents(self):
        """用户可见症状的回归锚点：提示里不得出现 `- <intent>: <intent>` 这种裸 token。

        按**每个**枚举值单独构建提示（模拟各 skill 声明的意图子集，如
        customer_quote_skill 的 `["quote"]`、data_skill 的 `finance`）。
        枚举外意图（本测试不覆盖）的兜底形态见 TestBuildClassifierPrompt。
        """
        bare = []
        for intent in IntentType:
            prompt = _build_classifier_prompt([intent.value])
            if f"- {intent.value}: {intent.value}" in prompt:
                bare.append(intent.value)
        assert not bare, f"分类器提示里这些意图退化成裸英文 token：{bare}"


class TestParseResponse:
    def _cls(self):
        return IntentClassifier()

    def test_empty_content_falls_back_general(self):
        result = self._cls()._parse_response("")
        assert result.intent == IntentType.GENERAL
        assert result.confidence == 0.5
        assert result.source == "default"

    def test_pure_json(self):
        result = self._cls()._parse_response('{"intent": "order_query", "confidence": 0.9}')
        assert result.intent == IntentType.ORDER_QUERY
        assert result.confidence == 0.9
        assert result.source == "classifier"

    def test_markdown_code_block(self):
        result = self._cls()._parse_response(
            '```json\n{"intent": "product_inquiry", "confidence": 0.8}\n```'
        )
        assert result.intent == IntentType.PRODUCT_INQUIRY
        assert result.confidence == 0.8

    def test_embedded_json_object(self):
        result = self._cls()._parse_response('结果是 {"intent": "greeting", "confidence": 0.7}')
        assert result.intent == IntentType.GREETING

    def test_invalid_intent_falls_back_general(self):
        result = self._cls()._parse_response('{"intent": "not_an_intent", "confidence": 0.9}')
        assert result.intent == IntentType.GENERAL
        assert result.confidence == 0.5

    def test_confidence_clamped(self):
        result = self._cls()._parse_response('{"intent": "order_query", "confidence": 3.0}')
        assert result.confidence == 1.0
        result2 = self._cls()._parse_response('{"intent": "order_query", "confidence": -1.0}')
        assert result2.confidence == 0.0

    def test_parse_exception_falls_back_default(self):
        result = self._cls()._parse_response("这不是 JSON")
        assert result.intent == IntentType.GENERAL
        assert result.confidence == 0.5
        assert result.source == "default"


class TestClassify:
    def _classifier(self, response_content):
        cls = IntentClassifier()
        mock_response = MagicMock()
        mock_response.content = response_content
        mock_response.usage_metadata = {"input_tokens": 10, "output_tokens": 5}
        mock_response.response_metadata = {}
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        cls._llm = mock_llm
        return cls

    @pytest.mark.asyncio
    async def test_normal_returns_classifier_source(self):
        cls = self._classifier('{"intent": "order_query", "confidence": 0.95}')
        result = await cls.classify("查订单")
        assert result.intent == IntentType.ORDER_QUERY
        assert result.source == "classifier"

    @pytest.mark.asyncio
    async def test_chat_history_injects_context(self):
        cls = self._classifier('{"intent": "general", "confidence": 0.5}')
        history = [{"role": "user", "content": "历史消息"}] * 10
        await cls.classify("在吗", chat_history=history)
        call = cls._llm.ainvoke.call_args[0][0]
        assert len(call) == 2  # System + Human
        assert "对话上下文" in call[1].content

    @pytest.mark.asyncio
    async def test_cost_tracking_usage_metadata(self):
        cls = self._classifier('{"intent": "general", "confidence": 0.5}')
        with patch("app.router.intent_classifier.cost_tracker") as mock_tracker:
            await cls.classify("你好")
            mock_tracker.track_call.assert_called_once()
            kwargs = mock_tracker.track_call.call_args.kwargs
            assert kwargs["input_tokens"] == 10
            assert kwargs["output_tokens"] == 5

    @pytest.mark.asyncio
    async def test_cost_tracking_fallback_response_metadata(self):
        cls = IntentClassifier()
        mock_response = MagicMock()
        mock_response.content = '{"intent": "general", "confidence": 0.5}'
        mock_response.usage_metadata = {}
        mock_response.response_metadata = {
            "token_usage": {"prompt_tokens": 3, "completion_tokens": 2}
        }
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        cls._llm = mock_llm

        with patch("app.router.intent_classifier.cost_tracker") as mock_tracker:
            await cls.classify("你好")
            kwargs = mock_tracker.track_call.call_args.kwargs
            assert kwargs["input_tokens"] == 3
            assert kwargs["output_tokens"] == 2

    @pytest.mark.asyncio
    async def test_classify_exception_falls_back_default(self):
        cls = IntentClassifier()
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
        cls._llm = mock_llm
        result = await cls.classify("你好")
        assert result.intent == IntentType.GENERAL
        assert result.confidence == 0.5
        assert result.source == "default"
        assert result.matched_keywords == []
