"""
LLM Factory - 统一 LLM 实例工厂

集中管理所有 ChatOpenAI 实例的构造逻辑：
- Skill LLM: Tool Calling 主力，启用 streaming + Qwen3 thinking
- Intent LLM: 意图分类小模型，确定性输出
- Suggestion LLM: 推荐/建议生成，低 temperature

后续若需对接其他 Provider（OpenAI/Anthropic 等），仅需在此处扩展。
"""

from __future__ import annotations

from typing import Optional

from langchain_openai import ChatOpenAI

from app.config import settings


# DashScope OpenAI 兼容接口地址
DASHSCOPE_BASE_URL = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"


class LLMFactory:
    """统一 LLM 实例工厂"""

    @staticmethod
    def create_skill_llm(model_override: Optional[str] = None) -> ChatOpenAI:
        """创建 Skill 专用 LLM

        参数与现有 base_skill.get_skill_llm() 一致，并支持 model_override：
        - temperature=0.7
        - streaming=True
        - max_tokens=2048
        - request_timeout=60
        - extra_body={"enable_thinking": True}  # Qwen3 思考模式

        Args:
            model_override: 显式指定模型名（来自 router.select_model 的返回值）。
                            为空则使用 settings.DASHSCOPE_MODEL。
        """
        model = model_override or settings.DASHSCOPE_MODEL
        return ChatOpenAI(
            model=model,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=DASHSCOPE_BASE_URL,
            temperature=0.7,
            streaming=True,
            max_tokens=2048,
            request_timeout=60,
            extra_body={"enable_thinking": True},
        )

    @staticmethod
    def create_vision_llm(model_override: Optional[str] = None) -> ChatOpenAI:
        """创建视觉多模态 LLM 实例

        用于处理包含图片的多模态请求。
        - 使用同一个 DashScope OpenAI 兼容接口
        - 不启用 thinking 模式（视觉模型不支持）

        Args:
            model_override: 显式指定模型名（来自 router.select_model 的返回值）。
                            为空则使用 settings.DASHSCOPE_VISION_MODEL。
        """
        model = model_override or settings.DASHSCOPE_VISION_MODEL
        return ChatOpenAI(
            model=model,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=DASHSCOPE_BASE_URL,
            temperature=0.7,
            streaming=True,
            max_tokens=2048,
            request_timeout=60,
            # 注意：视觉模型不启用 thinking 模式
        )

    @staticmethod
    def create_intent_llm() -> ChatOpenAI:
        """创建意图分类 LLM

        - temperature=0  确定性输出，便于 JSON 解析
        - max_tokens=100 仅需返回 {"intent":..., "confidence":...}
        """
        return ChatOpenAI(
            model=settings.INTENT_MODEL,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=DASHSCOPE_BASE_URL,
            temperature=0,
            max_tokens=100,
        )

    @staticmethod
    def create_suggestion_llm() -> ChatOpenAI:
        """创建建议/推荐生成 LLM

        - temperature=0.3 略带多样性，但避免发散
        - max_tokens=200  建议文本通常较短
        """
        return ChatOpenAI(
            model=settings.INTENT_MODEL,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=DASHSCOPE_BASE_URL,
            temperature=0.3,
            max_tokens=200,
        )
