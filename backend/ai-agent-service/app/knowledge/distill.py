"""
客服会话知识提炼服务（LLM WIKI 板块 P5b，issue #3051）

把人工客服会话对话提炼为「顾客问题 → 客服回答」知识卡片候选，
写入 admin-api 的待确认队列（knowledge_candidates），由商家采纳后生效。

核心不变式：AI 只产生候选，发布权在商家。
"""

import json
import re
from typing import List, Optional

from loguru import logger

from app.llm import LLMFactory

MAX_CANDIDATES = 5
MAX_CONVERSATION_CHARS = 4000

DISTILL_SYSTEM_PROMPT = """你是电商客服经验萃取助手。给你一段「顾客与客服的真实对话」，请提炼出值得沉淀为店铺知识的内容。

提炼规则：
1. 只提炼「顾客提问 → 客服有效回答」的问答对；寒暄、无实质回答、未解决的内容不提炼
2. 每条候选 = 一个问题 + 一个标准回答，回答基于客服对话内容，不得编造对话中不存在的店铺事实
3. 回答保留关键事实（价格、周期、政策、参数等），删掉口语化废话，控制在 100 字以内
4. 置信度：0~1，对话中明确回答的事实给 0.9+，客服表达含糊或信息不全给 0.7 以下
5. evidence：用 1-2 句对话原文佐证（引用顾客原话或客服原话）
6. category 取值：faq / product / measure / aftersale / config

输出格式（严格 JSON 数组，不要输出其他文字）：
[{{"title": "问题标题", "answer": "标准回答", "category": "faq", "keywords": "关键词,逗号,分隔", "confidence": 0.9, "evidence": "对话原文佐证"}}]
最多输出 {max_candidates} 条。"""


def _extract_json_array(text: str) -> Optional[List[dict]]:
    """从 LLM 输出中容错抽取 JSON 数组。"""
    if not text:
        return None
    text = text.strip()
    # 直接是数组
    if text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    # 抽取 ```json ... ``` 块
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    # 抽取首个 [ ... ]
    bracket = re.search(r"(\[.*\])", text, re.S)
    if bracket:
        try:
            return json.loads(bracket.group(1))
        except json.JSONDecodeError:
            pass
    return None


def _sanitize_candidates(raw: List[dict]) -> List[dict]:
    """清洗候选：只保留 title/answer 非空的条目，字段归一化。"""
    result = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if not title or not answer:
            continue
        try:
            confidence = float(item.get("confidence") or 0.5)
        except (TypeError, ValueError):
            confidence = 0.5
        result.append({
            "title": title[:100],
            "answer": answer[:500],
            "category": str(item.get("category") or "faq")[:32],
            "keywords": str(item.get("keywords") or "")[:200],
            "confidence": round(min(max(confidence, 0.0), 1.0), 3),
            "evidence": str(item.get("evidence") or "")[:300],
        })
    return result[:MAX_CANDIDATES]


def _truncate_conversation(conversation_text: str) -> str:
    """截断超长会话（保留开头与结尾，中间省略）。"""
    if len(conversation_text) <= MAX_CONVERSATION_CHARS:
        return conversation_text
    ellipsis = "\n……（中间省略）……\n"
    budget = MAX_CONVERSATION_CHARS - len(ellipsis)
    head = conversation_text[: int(budget * 0.7)]
    tail = conversation_text[-int(budget * 0.3):]
    return head + "\n……（中间省略）……\n" + tail


async def distill(conversation_text: str, max_candidates: int = MAX_CANDIDATES) -> List[dict]:
    """提炼会话 → 候选知识卡片列表（异常降级返回空列表，不阻断调用方）。"""
    text = _truncate_conversation(conversation_text or "")
    if not text.strip():
        return []
    try:
        llm = LLMFactory.create_suggestion_llm()
        prompt = f"{DISTILL_SYSTEM_PROMPT.format(max_candidates=max_candidates)}\n\n<对话开始>\n{text}\n<对话结束>"
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content if isinstance(response.content, str) else ""
        raw = _extract_json_array(content)
        if raw is None:
            logger.warning("[knowledge:distill] LLM 输出无法解析为 JSON 数组，len={}", len(content))
            return []
        candidates = _sanitize_candidates(raw)
        logger.info("[knowledge:distill] 提炼完成 candidates={}", len(candidates))
        return candidates
    except Exception as e:
        logger.warning(f"[knowledge:distill] 提炼失败，降级返回空: {e}")
        return []
