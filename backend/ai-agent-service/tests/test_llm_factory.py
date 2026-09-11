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
        with patch("app.llm.factory.LLM_API_KEY", "ci-dummy"):
            model = _new_chat_model(model="m", api_key="ci-dummy", base_url="http://x")
        assert isinstance(model, ChatOpenAI)

    def test_real_key_returns_chatdeepseek(self):
        with patch("app.llm.factory.LLM_API_KEY", "real-key"):
            model = _new_chat_model(model="m", api_key="real-key", base_url="http://x")
        assert isinstance(model, ChatDeepSeek)


class TestCreateSkillLLM:
    def test_defaults(self):
        with patch("app.llm.factory._new_chat_model") as mock_new, \
             patch("app.llm.factory.settings") as mock_settings:
            mock_settings.LLM_MODEL = "m3"
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
            mock_settings.LLM_MODEL = "m3"
            LLMFactory.create_skill_llm(model_override="custom-model")
        assert mock_new.call_args.kwargs["model"] == "custom-model"

    def test_force_no_think_disables_thinking(self):
        with patch("app.llm.factory._new_chat_model") as mock_new, \
             patch("app.llm.factory.settings") as mock_settings:
            mock_settings.LLM_MODEL = "m3"
            LLMFactory.create_skill_llm(force_no_think=True)
        kwargs = mock_new.call_args.kwargs
        assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
        assert kwargs["max_completion_tokens"] == 2048

    def test_enable_thinking_bumps_max_tokens(self):
        with patch("app.llm.factory._new_chat_model") as mock_new, \
             patch("app.llm.factory.settings") as mock_settings:
            mock_settings.LLM_MODEL = "m3"
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


class TestVisionLlmApiKeyFallback:
    """视觉 LLM 的 API key 兜底（issue #3270）。

    契约（见 create_vision_llm docstring 与 config.py 注释）：
      「DeepSeek vision … 与主模型共用 DeepSeek API key（推理/视觉同 key）」
    且 `Settings.LLM_API_KEY` 属性明确实现「PRIMARY 优先，VISION 兜底」。
    但 `create_vision_llm` 此前**直接取 settings.VISION_API_KEY**，绕过了该兜底 →
    只配 PRIMARY_API_KEY 的环境（compose/生产常态、CI 实测）视觉链路报
    `OpenAIError: Missing credentials` → 图片能力（拍照找同款/识别面料）不可用。

    实测（CI normal 档）：CH-026「澄清卡后发图」以
    `OpenAIError: Missing credentials. Please pass an api_key` 失败。
    """

    def test_falls_back_to_primary_key_when_vision_key_empty(self):
        with patch("app.llm.factory.settings") as ms, \
             patch("app.llm.factory.ChatOpenAI") as mock_co:
            ms.VISION_MODEL = "vm"
            ms.VISION_API_KEY = ""            # 未单独配置视觉 key（常态）
            ms.PRIMARY_API_KEY = "pk"         # 只有主模型 key
            LLMFactory.create_vision_llm()
        assert mock_co.call_args.kwargs["api_key"] == "pk", (
            "VISION_API_KEY 为空时必须兜底用 PRIMARY_API_KEY —— "
            "否则只配主 key 的环境视觉链路不可用（issue #3270 实测 CH-026）"
        )

    def test_explicit_vision_key_takes_priority(self):
        """显式配置了独立视觉 key → 优先用它（不覆盖用户意图）"""
        with patch("app.llm.factory.settings") as ms, \
             patch("app.llm.factory.ChatOpenAI") as mock_co:
            ms.VISION_MODEL = "vm"
            ms.VISION_API_KEY = "vk"
            ms.PRIMARY_API_KEY = "pk"
            LLMFactory.create_vision_llm()
        assert mock_co.call_args.kwargs["api_key"] == "vk"

    def test_base_url_falls_back_to_primary(self):
        with patch("app.llm.factory.settings") as ms, \
             patch("app.llm.factory.ChatOpenAI") as mock_co:
            ms.VISION_MODEL = "vm"
            ms.VISION_API_KEY = ""
            ms.PRIMARY_API_KEY = "pk"
            ms.VISION_BASE_URL = ""
            ms.PRIMARY_BASE_URL = "https://api.deepseek.com/v1"
            LLMFactory.create_vision_llm()
        assert mock_co.call_args.kwargs["base_url"] == "https://api.deepseek.com/v1"
