"""
LLM Factory - 唯一 DashScope 配置入口 & LLM 实例工厂

所有 DashScope 相关配置（endpoint、api_key、model）只在此处从 settings 读取一次。
其他模块统一从本模块导入常量或调用工厂方法，禁止直接 import settings 读取 DashScope 配置。
"""

from __future__ import annotations

from typing import Optional

from langchain_openai import ChatOpenAI

from app.config import settings

# ===== 唯一配置读取点（从 settings 读一次，全局共享）=====
DASHSCOPE_BASE_URL: str = settings.DASHSCOPE_BASE_URL
DASHSCOPE_API_KEY: str = settings.DASHSCOPE_API_KEY
DASHSCOPE_EMBEDDING_MODEL: str = settings.DASHSCOPE_EMBEDDING_MODEL


class LLMFactory:
    """统一 LLM 实例工厂"""

    @staticmethod
    def create_skill_llm(
        model_override: Optional[str] = None,
        enable_thinking: bool = False,
    ) -> ChatOpenAI:
        """创建 Skill 专用 LLM

        - temperature=0.7
        - streaming=True
        - max_tokens=2048
        - request_timeout=60

        Args:
            model_override: 显式指定模型名（来自 router.select_model 的返回值）。
                            为空则使用 settings.DASHSCOPE_MODEL。
            enable_thinking: 是否启用 Qwen3 深度思考模式。
                             开启后模型先推理再回复，质量更高但首次响应慢 5-15s。
                             默认关闭（客服场景优先速度），复杂意图由调用方显式开启。
        """
        model = model_override or settings.DASHSCOPE_MODEL
        kwargs: dict = dict(
            model=model,
            api_key=DASHSCOPE_API_KEY,
            base_url=DASHSCOPE_BASE_URL,
            temperature=0.7,
            streaming=True,
            max_tokens=2048,
            request_timeout=60,
        )
        if enable_thinking:
            kwargs["extra_body"] = {"enable_thinking": True}
        return ChatOpenAI(**kwargs)

    @staticmethod
    def create_vision_llm(model_override: Optional[str] = None) -> ChatOpenAI:
        """创建视觉多模态 LLM 实例

        - 使用同一个 DashScope OpenAI 兼容接口
        - 不启用 thinking 模式（视觉模型不支持）
        """
        model = model_override or settings.DASHSCOPE_VISION_MODEL
        return ChatOpenAI(
            model=model,
            api_key=DASHSCOPE_API_KEY,
            base_url=DASHSCOPE_BASE_URL,
            temperature=0.7,
            streaming=True,
            max_tokens=2048,
            request_timeout=60,
        )

    @staticmethod
    def create_intent_llm() -> ChatOpenAI:
        """创建意图分类 LLM

        - temperature=0  确定性输出，便于 JSON 解析
        - max_tokens=100 仅需返回 {"intent":..., "confidence":...}
        """
        return ChatOpenAI(
            model=settings.INTENT_MODEL,
            api_key=DASHSCOPE_API_KEY,
            base_url=DASHSCOPE_BASE_URL,
            temperature=0,
            max_tokens=100,
        )

    @staticmethod
    def create_summary_llm(
        temperature: float = 0.3,
        max_tokens: int = 512,
    ) -> ChatOpenAI:
        """创建摘要/压缩用 LLM

        用于对话历史压缩、上下文摘要等轻量任务。

        Args:
            temperature: 温度参数，默认 0.3
            max_tokens: 最大输出 token，默认 512
        """
        return ChatOpenAI(
            model=settings.INTENT_MODEL,
            api_key=DASHSCOPE_API_KEY,
            base_url=DASHSCOPE_BASE_URL,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    @staticmethod
    def create_suggestion_llm() -> ChatOpenAI:
        """创建建议/推荐生成 LLM

        - temperature=0.3 略带多样性，但避免发散
        - max_tokens=200  建议文本通常较短
        """
        return ChatOpenAI(
            model=settings.INTENT_MODEL,
            api_key=DASHSCOPE_API_KEY,
            base_url=DASHSCOPE_BASE_URL,
            temperature=0.3,
            max_tokens=200,
        )
