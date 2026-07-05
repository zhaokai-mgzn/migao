"""
LLM Factory - 唯一 LLM 配置入口 & 实例工厂

所有 LLM 相关配置（endpoint、api_key、model）只在此处从 settings 读取一次。
其他模块统一从本模块导入常量或调用工厂方法，禁止直接 import settings 读取 LLM 配置。
"""

from __future__ import annotations

from typing import Optional

from langchain_openai import ChatOpenAI

from app.config import settings

# ===== 唯一配置读取点（从 settings 读一次，全局共享）=====
MINIMAX_BASE_URL: str = settings.MINIMAX_BASE_URL
MINIMAX_API_KEY: str = settings.MINIMAX_API_KEY

# === 向后兼容别名（测试/旧代码）===
DASHSCOPE_BASE_URL = MINIMAX_BASE_URL


class LLMFactory:
    """统一 LLM 实例工厂"""

    @staticmethod
    def create_skill_llm(
        model_override: Optional[str] = None,
        enable_thinking: bool = False,
        force_no_think: bool = False,
    ) -> ChatOpenAI:
        """创建 Skill 专用 LLM

        - temperature=0.7
        - streaming=True
        - max_completion_tokens=2048
        - timeout=60

        Args:
            model_override: 显式指定模型名。
            enable_thinking: True → 显式 adaptive thinking。
            force_no_think: True → 显式 disabled thinking（轻量任务专用）。
                            不同于 enable_thinking=False（不传参，M3 默认仍开思考）。
        """
        model = model_override or settings.MINIMAX_MODEL
        kwargs: dict = dict(
            model=model,
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
            temperature=0.7,
            streaming=True,
            max_completion_tokens=2048,
            request_timeout=60,
        )
        if force_no_think:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            # 不思考时 2048 足够（仅格式化工具结果）
        elif enable_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            # DeepSeek V4 thinking 模式下思考+回复共享 token 预算，需增大
            kwargs["max_completion_tokens"] = 8192
        return ChatOpenAI(**kwargs)

    @staticmethod
    def create_vision_llm(model_override: Optional[str] = None, enable_thinking: bool = True) -> ChatOpenAI:
        """创建视觉多模态 LLM 实例（独立视觉模型配置）

        enable_thinking=True: 开启深度推理，更准确识别色号、材质、风格等细节。
        延迟增加 5-8s，但对商品创建场景质量提升显著。
        """
        model = model_override or settings.VISION_MODEL
        kwargs: dict = dict(
            model=model,
            api_key=settings.VISION_API_KEY,
            base_url=settings.VISION_BASE_URL,
            temperature=0.7,
            streaming=True,
            max_completion_tokens=16384,
            request_timeout=60,
        )
        if enable_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        return ChatOpenAI(**kwargs)

    @staticmethod
    def create_intent_llm() -> ChatOpenAI:
        """创建意图分类 LLM

        - temperature=0  确定性输出，便于 JSON 解析
        - max_completion_tokens=200 仅需返回 {"intent":..., "confidence":...}
        - thinking=disabled  关闭深度思考，节省 reasoning tokens，降低延迟
        """
        return ChatOpenAI(
            model=settings.INTENT_MODEL,
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
            temperature=0,
            max_completion_tokens=200,
            extra_body={"thinking": {"type": "disabled"}},
        )

    @staticmethod
    def create_summary_llm(
        temperature: float = 0.3,
        max_tokens: int = 512,
    ) -> ChatOpenAI:
        """创建摘要/压缩用 LLM

        用于对话历史压缩、上下文摘要等轻量任务。
        关闭深度思考以提升响应速度。

        Args:
            temperature: 温度参数，默认 0.3
            max_tokens: 最大输出 token，默认 512
        """
        return ChatOpenAI(
            model=settings.INTENT_MODEL,
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
            temperature=temperature,
            max_completion_tokens=max_tokens,
            extra_body={"thinking": {"type": "disabled"}},
        )

    @staticmethod
    async def invoke_text_safe(
        messages: list,
        enable_thinking: bool = False,
        force_no_think: bool = False,
        model_override: Optional[str] = None,
    ) -> str:
        """安全调用纯文本 LLM，自动清洗 image_url 多模态内容。

        所有文本 LLM 调用统一走此入口，避免 image_url 混合传入导致 API 错误。

        Args:
            messages: LangChain 消息列表（可能含多模态内容）
            enable_thinking: 是否启用深度思考
            force_no_think: 是否显式关闭思考（轻量任务）
            model_override: 模型覆盖

        Returns:
            str: LLM 响应文本
        """
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

        # 清洗 image_url，只保留纯文本
        cleaned = []
        for m in messages:
            content = getattr(m, 'content', None) or ""
            if isinstance(content, list):
                text_parts = [
                    c.get("text", "")
                    for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                text = " ".join(text_parts).strip()
                if isinstance(m, SystemMessage):
                    cleaned.append(SystemMessage(content=text))
                elif isinstance(m, HumanMessage):
                    cleaned.append(HumanMessage(content=text or "[图片]"))
                elif isinstance(m, AIMessage):
                    cleaned.append(AIMessage(content=text or ""))
                else:
                    cleaned.append(type(m)(content=text or ""))
            else:
                cleaned.append(m)

        llm = LLMFactory.create_skill_llm(
            model_override=model_override,
            enable_thinking=enable_thinking,
            force_no_think=force_no_think,
        )
        response = await llm.ainvoke(cleaned)
        return response.content.strip() if hasattr(response, 'content') else str(response)

    @staticmethod
    def create_suggestion_llm() -> ChatOpenAI:
        """创建建议/推荐生成 LLM

        - temperature=0.3 略带多样性，但避免发散
        - max_completion_tokens=200  建议文本通常较短
        - thinking=disabled  关闭思考模式以提升响应速度
        """
        return ChatOpenAI(
            model=settings.INTENT_MODEL,
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_BASE_URL,
            temperature=0.3,
            max_completion_tokens=200,
            extra_body={"thinking": {"type": "disabled"}},
        )
