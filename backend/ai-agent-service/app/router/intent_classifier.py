"""
L2 小模型意图分类 - 使用 qwen-turbo 进行意图识别
"""

import json
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.config import settings
from app.llm import LLMFactory, cost_tracker
from app.router.intent_config import IntentType, IntentResult


# DashScope OpenAI 兼容接口地址
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 意图分类 System Prompt
CLASSIFIER_SYSTEM_PROMPT = """你是一个意图分类器。根据用户消息，从以下意图列表中选择最匹配的一个，并给出置信度。

意图列表：
- order_query: 查询订单状态、订单信息
- logistics_track: 查询物流、快递进度
- product_inquiry: 商品咨询、价格查询、产品推荐
- after_sales: 退货、退款、换货、售后服务
- knowledge_faq: 面料知识、保养方法、安装指南等问答
- greeting: 打招呼、问候（如“你好”“在吗”）
- farewell: 告别、结束对话（如“再见”“谢谢再见”“拜拜”）
- capabilities: 询问助手能力、功能（如“你能做什么”“你有什么功能”）
- complaint: 投诉、举报、不满
- general: 以上都不匹配的其他问题

请严格以 JSON 格式输出，不要输出其他内容：
{"intent": "意图名称", "confidence": 0.xx}

注意：
- confidence 取值 0.0~1.0，表示你对分类结果的确信程度
- 如果用户消息含糊不清或可能属于多个意图，降低 confidence
- 优先考虑用户的核心诉求"""


class IntentClassifier:
    """
    L2 意图分类器
    
    使用 qwen-turbo 小模型进行意图分类，
    相比大模型调用成本更低、速度更快。
    """

    def __init__(self):
        self._llm: Optional[ChatOpenAI] = None

    @property
    def llm(self) -> ChatOpenAI:
        """懒加载 LLM 实例（统一走 LLMFactory）"""
        if self._llm is None:
            self._llm = LLMFactory.create_intent_llm()
        return self._llm

    async def classify(
        self, message: str, chat_history: list = None
    ) -> IntentResult:
        """
        使用小模型对用户消息进行意图分类
        
        Args:
            message: 用户消息文本
            chat_history: 对话历史（可选，用于上下文理解）
            
        Returns:
            IntentResult: 分类结果
        """
        try:
            messages = [SystemMessage(content=CLASSIFIER_SYSTEM_PROMPT)]

            # 如果有对话历史，提供最近几轮作为上下文
            if chat_history:
                recent = chat_history[-4:]  # 最近 2 轮对话
                context_text = "\n".join(
                    f"{'用户' if m.get('role') == 'user' else '客服'}: {m.get('content', '')}"
                    for m in recent
                )
                messages.append(
                    HumanMessage(content=f"对话上下文：\n{context_text}\n\n当前用户消息：{message}")
                )
            else:
                messages.append(HumanMessage(content=message))

            response = await self.llm.ainvoke(messages)
            # 成本追踪（失败仅 warning，不影响主流程）
            try:
                usage_meta = getattr(response, "usage_metadata", None) or {}
                input_tokens = int(usage_meta.get("input_tokens", 0) or 0)
                output_tokens = int(usage_meta.get("output_tokens", 0) or 0)
                if not (input_tokens or output_tokens):
                    resp_meta = getattr(response, "response_metadata", None) or {}
                    token_usage = resp_meta.get("token_usage") or resp_meta.get("usage") or {}
                    input_tokens = int(
                        token_usage.get("prompt_tokens")
                        or token_usage.get("input_tokens")
                        or 0
                    )
                    output_tokens = int(
                        token_usage.get("completion_tokens")
                        or token_usage.get("output_tokens")
                        or 0
                    )
                if input_tokens or output_tokens:
                    cost_tracker.track_call(
                        model=settings.INTENT_MODEL,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
            except Exception as track_exc:
                logger.warning(f"[intent_classifier] cost tracking failed: {track_exc}")

            result = self._parse_response(response.content)
            return result

        except Exception as e:
            logger.warning(f"Intent classifier error: {e}, falling back to general")
            return IntentResult(
                intent=IntentType.GENERAL,
                confidence=0.5,
                source="default",
                matched_keywords=[],
            )

    def _parse_response(self, content: str) -> IntentResult:
        """解析模型返回的 JSON 结果"""
        try:
            # 尝试提取 JSON（模型可能会包裹在 markdown 代码块中）
            text = content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            data = json.loads(text)
            intent_str = data.get("intent", "general")
            confidence = float(data.get("confidence", 0.5))

            # 验证 intent 是否在枚举中
            try:
                intent = IntentType(intent_str)
            except ValueError:
                intent = IntentType.GENERAL
                confidence = 0.5

            return IntentResult(
                intent=intent,
                confidence=min(max(confidence, 0.0), 1.0),
                source="classifier",
                matched_keywords=[],
            )

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to parse classifier response: {content}, error: {e}")
            return IntentResult(
                intent=IntentType.GENERAL,
                confidence=0.5,
                source="default",
                matched_keywords=[],
            )
