"""
后续问题建议生成器

在 AI 回复结束后，自动推荐 2-3 个后续问题建议，引导用户继续对话。

策略：
- 高频意图使用预设模板（<5ms）
- 涉及具体实体时使用 qwen3.6-plus 动态生成（100-200ms）
- 超时或失败时返回预设模板兜底
"""

import json
import re
from typing import Optional

import httpx
from langchain_core.messages import HumanMessage
from loguru import logger

from app.config import settings
from app.llm import LLMFactory, cost_tracker


# 预定义建议模板（高频意图直接返回，无需调用模型）
PRESET_SUGGESTIONS: dict[str, list[str]] = {
    "order_query": ["查看物流信息", "申请退货退款", "修改收货地址"],
    "logistics_track": ["确认收货", "联系快递客服", "查看其他订单物流"],
    "product_inquiry": ["查看商品详情", "了解促销活动", "咨询定制服务"],
    "after_sales": ["查看售后进度", "了解退款政策", "联系人工客服"],
    "knowledge_faq": ["查看更多常见问题", "咨询具体产品问题", "联系专业顾问"],
    "greeting": ["查看我的订单", "浏览热门商品", "咨询窗帘定制"],
    "complaint": ["查看投诉处理进度", "联系主管", "了解赔偿政策"],
}

# 默认兜底建议
DEFAULT_SUGGESTIONS: list[str] = ["查看我的订单", "浏览热门商品", "联系人工客服"]

# 用于检测回复中是否包含具体实体的正则
_ENTITY_PATTERNS = [
    re.compile(r"订单号[：:\s]*\w+"),
    re.compile(r"[A-Z]{2}\d{9,}[A-Z]{2}"),  # 物流单号
    re.compile(r"商品[：:\s]*[「「【]?.+?[」」】]?"),
    re.compile(r"¥\d+"),  # 价格
    re.compile(r"\d{4}-\d{2}-\d{2}"),  # 日期
]

DYNAMIC_PROMPT = """你是一个智能客服助手。根据以下对话内容，生成3个用户最可能继续询问的后续问题。

用户问题：{query}
AI回复：{answer}

要求：
1. 问题要简短自然，像用户会说的话
2. 问题要与当前对话主题相关
3. 问题之间不要重复
4. 直接返回 JSON 数组格式，不要其他内容

输出格式示例：["问题1", "问题2", "问题3"]"""


def _has_specific_entities(answer: str) -> bool:
    """检测回复中是否包含具体实体（订单号、商品名、价格等）"""
    for pattern in _ENTITY_PATTERNS:
        if pattern.search(answer):
            return True
    return False


def _parse_suggestions_from_response(text: str) -> Optional[list[str]]:
    """从模型响应中解析建议列表"""
    text = text.strip()
    # 尝试直接解析 JSON 数组
    try:
        result = json.loads(text)
        if isinstance(result, list) and all(isinstance(s, str) for s in result):
            return result[:3]
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取 JSON 数组
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list) and all(isinstance(s, str) for s in result):
                return result[:3]
        except json.JSONDecodeError:
            pass

    return None


class FollowUpSuggestionGenerator:
    """后续问题建议生成器"""

    def __init__(self):
        self._api_key = settings.DASHSCOPE_API_KEY
        self._model = settings.INTENT_MODEL  # qwen3.6-plus
        self._llm = None  # 懒加载 LangChain LLM 实例

    async def generate(
        self,
        query: str,
        answer: str,
        intent_type: str,
        chat_history: Optional[list] = None,
    ) -> list[str]:
        """
        生成 2-3 个后续问题建议

        Args:
            query: 用户原始问题
            answer: AI 回复内容
            intent_type: 意图类型
            chat_history: 对话历史（可选）

        Returns:
            2-3 个后续问题建议字符串列表
        """
        try:
            # 智能选择策略
            if self._should_use_dynamic(answer, intent_type):
                suggestions = await self._generate_dynamic(query, answer)
                if suggestions:
                    return suggestions[:3]

            # 使用预设模板
            return self._get_preset(intent_type)

        except Exception as e:
            logger.warning(f"Failed to generate follow-up suggestions: {e}")
            return self._get_preset(intent_type)

    def _should_use_dynamic(self, answer: str, intent_type: str) -> bool:
        """判断是否应该使用动态生成"""
        # 没有 API Key 时不使用动态生成
        if not self._api_key:
            return False
        # 回复涉及具体实体时使用动态生成
        return _has_specific_entities(answer)

    def _get_preset(self, intent_type: str) -> list[str]:
        """获取预设建议模板"""
        return PRESET_SUGGESTIONS.get(intent_type, DEFAULT_SUGGESTIONS)

    async def _generate_dynamic(
        self, query: str, answer: str
    ) -> Optional[list[str]]:
        """使用 qwen3.6-plus 动态生成后续问题建议（走 LangChain 统一接口）"""
        prompt = DYNAMIC_PROMPT.format(
            query=query[:200],  # 截断避免过长
            answer=answer[:500],
        )

        try:
            if self._llm is None:
                self._llm = LLMFactory.create_suggestion_llm()

            response = await self._llm.ainvoke([HumanMessage(content=prompt)])

            # 成本追踪（失败仅 warning）
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
                        model=self._model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
            except Exception as track_exc:
                logger.warning(f"[follow_up] cost tracking failed: {track_exc}")

            content = response.content if isinstance(response.content, str) else ""
            return _parse_suggestions_from_response(content)

        except httpx.TimeoutException:
            logger.debug("Dynamic suggestion generation timed out, falling back to preset")
            return None
        except Exception as e:
            logger.warning(f"Dynamic suggestion generation failed: {e}")
            return None
