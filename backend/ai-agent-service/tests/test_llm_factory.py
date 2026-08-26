# case_ids: MC-008
"""LLM 工厂单元测试（app/llm/factory.py）

覆盖：_new_chat_model / create_skill_llm / create_vision_llm / create_intent_llm
     / create_summary_llm / create_suggestion_llm / invoke_text_safe。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langchain_deepseek import ChatDeepSeek

from app.llm.factory import LLMFactory, _new_chat_model


class TestNewChatModel:
    def test_ci_dummy_returns_chatopenai(self):
        with patch("app.llm.factory.MINIMAX_API_KEY", "ci-dummy"):
            model = _new_chat_model(model="m", api_key="ci-dummy", base_url="http://x")
        assert isinstance(model, ChatOpenAI)

    def test_real_key_returns_chatdeepseek(self):
        with patch("app.llm.factory.MINIMAX_API_KEY", "real-key"):
            model = _new_chat_model(model="m", api_key="real-key", base_url="http://x")
        assert isinstance(model, ChatDeepSeek)


class TestCreateSkillLLM:
    def test_defaults(self):
        with patch("app.llm.factory._new_chat_model") as mock_new, \
             patch("app.llm.factory.settings") as mock_settings:
            mock_settings.MINIMAX_MODEL = "m3"
            LLMFactory.create_skill_llm()
        kwargs = mock_new.call_args.kwargs
        assert kwargs["model"] == "m3"
        assert kwargs["temperature"] == 0.7
        assert kwargs["streaming"] is True
        assert kwargs["max_completion_tokens"] == 2048
        assert kwargs["request_timeout"] == 60
        assert "extra_body" not in kwargs

    def test_model_override(self):
        with patch("app.llm.factory._new_chat_model") as mock_new, \
             patch("app.llm.factory.settings") as mock_settings:
            mock_settings.MINIMAX_MODEL = "m3"
            LLMFactory.create_skill_llm(model_override="custom-model")
        assert mock_new.call_args.kwargs["model"] == "custom-model"

    def test_force_no_think_disables_thinking(self):
        with patch("app.llm.factory._new_chat_model") as mock_new, \
             patch("app.llm.factory.settings") as mock_settings:
            mock_settings.MINIMAX_MODEL = "m3"
            LLMFactory.create_skill_llm(force_no_think=True)
        kwargs = mock_new.call_args.kwargs
        assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
        assert kwargs["max_completion_tokens"] == 2048

    def test_enable_thinking_bumps_max_tokens(self):
        with patch("app.llm.factory._new_chat_model") as mock_new, \
             patch("app.llm.factory.settings") as mock_settings:
            mock_settings.MINIMAX_MODEL = "m3"
            LLMFactory.create_skill_llm(enable_thinking=True)
        kwargs = mock_new.call_args.kwargs
        assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
        assert kwargs["max_completion_tokens"] == 384000


class TestCreateVariants:
    def test_create_vision_llm(self):
        with patch("app.llm.factory.settings") as mock_settings, \
             patch("app.llm.factory.ChatOpenAI") as mock_co:
            mock_settings.VISION_MODEL = "vm"
            mock_settings.VISION_API_KEY = "vk"
            mock_settings.VISION_BASE_URL = "vb"
            LLMFactory.create_vision_llm()
        kwargs = mock_co.call_args.kwargs
        assert kwargs["model"] == "vm"
        assert kwargs["api_key"] == "vk"
        assert kwargs["base_url"] == "vb"
        # DeepSeek vision（OpenAI 兼容）不传 MiniMax 专属 thinking extra_body
        assert "extra_body" not in kwargs
        assert kwargs["max_completion_tokens"] == 16384

    def test_create_intent_llm(self):
        with patch("app.llm.factory._new_chat_model") as mock_new, \
             patch("app.llm.factory.settings") as mock_settings:
            mock_settings.INTENT_MODEL = "im"
            LLMFactory.create_intent_llm()
        kwargs = mock_new.call_args.kwargs
        assert kwargs["model"] == "im"
        assert kwargs["temperature"] == 0
        assert kwargs["max_completion_tokens"] == 200
        assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}

    def test_create_summary_llm_defaults(self):
        with patch("app.llm.factory._new_chat_model") as mock_new, \
             patch("app.llm.factory.settings") as mock_settings:
            mock_settings.INTENT_MODEL = "im"
            LLMFactory.create_summary_llm()
        kwargs = mock_new.call_args.kwargs
        assert kwargs["temperature"] == 0.3
        assert kwargs["max_completion_tokens"] == 512

    def test_create_summary_llm_parameterized(self):
        with patch("app.llm.factory._new_chat_model") as mock_new, \
             patch("app.llm.factory.settings") as mock_settings:
            mock_settings.INTENT_MODEL = "im"
            LLMFactory.create_summary_llm(temperature=0.1, max_tokens=100)
        kwargs = mock_new.call_args.kwargs
        assert kwargs["temperature"] == 0.1
        assert kwargs["max_completion_tokens"] == 100

    def test_create_suggestion_llm(self):
        with patch("app.llm.factory._new_chat_model") as mock_new, \
             patch("app.llm.factory.settings") as mock_settings:
            mock_settings.INTENT_MODEL = "im"
            LLMFactory.create_suggestion_llm()
        kwargs = mock_new.call_args.kwargs
        assert kwargs["temperature"] == 0.3
        assert kwargs["max_completion_tokens"] == 200
        assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


class TestInvokeTextSafe:
    def _mock_llm(self, content):
        mock_response = MagicMock()
        mock_response.content = content
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        return mock_llm

    @pytest.mark.asyncio
    async def test_cleans_multimodal_keeps_text_only(self):
        messages = [
            SystemMessage(content="你是客服"),
            HumanMessage(content=[
                {"type": "text", "text": "你好"},
                {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
            ]),
            AIMessage(content=[{"type": "text", "text": "您好"}]),
        ]
        mock_llm = self._mock_llm("  回复内容  ")
        with patch("app.llm.factory.LLMFactory.create_skill_llm", return_value=mock_llm):
            result = await LLMFactory.invoke_text_safe(messages)
        assert result == "回复内容"

        cleaned = mock_llm.ainvoke.call_args[0][0]
        assert cleaned[0].content == "你是客服"
        assert cleaned[1].content == "你好"
        assert cleaned[2].content == "您好"

    @pytest.mark.asyncio
    async def test_human_image_only_becomes_placeholder(self):
        messages = [
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
            ]),
        ]
        mock_llm = self._mock_llm("ok")
        with patch("app.llm.factory.LLMFactory.create_skill_llm", return_value=mock_llm):
            await LLMFactory.invoke_text_safe(messages)
        cleaned = mock_llm.ainvoke.call_args[0][0]
        assert cleaned[0].content == "[图片]"

    @pytest.mark.asyncio
    async def test_passes_skill_llm_options(self):
        messages = [HumanMessage(content="你好")]
        mock_llm = self._mock_llm("ok")
        with patch("app.llm.factory.LLMFactory.create_skill_llm", return_value=mock_llm) as mock_factory:
            await LLMFactory.invoke_text_safe(
                messages, enable_thinking=True, force_no_think=False, model_override="m"
            )
        kwargs = mock_factory.call_args.kwargs
        assert kwargs["enable_thinking"] is True
        assert kwargs["model_override"] == "m"
