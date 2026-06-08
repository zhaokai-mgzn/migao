"""
AI 智能客服系统 - 用户记忆自动提取

每次对话结束后，异步调用轻量模型从对话中提取值得记住的信息。
写入 user_memories 表，下次对话时注入 System Prompt。
"""

import json
import re
from typing import Optional, List, Dict, Any

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger


EXTRACTION_PROMPT = """你是一个记忆提取器。从以下客服对话中提取值得记住的用户信息。

只提取**明确表达**的内容，不要编造或推测。

记忆类型：
- preference: 用户偏好（喜欢什么风格、预算范围、常用功能等）
- fact: 关键事实（订单号、手机号、地址、常用商品分类等）
- feedback: 用户对 AI 的纠正（"不对，那个订单号是..."）
- reference: 其他值得记住的信息

要求：
1. 每条记忆需要 key（简短英文标识）和 value（具体内容）
2. importance 评分 0-1：纠正类 1.0，偏好类 0.7-0.9，事实类 0.5-0.7
3. 如果对话中没有值得记住的信息，返回空数组
4. 不要重复已明确的信息
5. 直接返回 JSON 数组，不要其他内容

输出格式：
[{"type": "preference", "key": "style", "value": "喜欢简约风格", "importance": 0.8}]"""


def _parse_extraction_result(text: str) -> List[Dict[str, Any]]:
    """从 LLM 响应中解析记忆列表"""
    text = text.strip()

    # 尝试直接解析 JSON
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取 JSON 数组
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    return []


async def extract_memories_from_turn(
    user_message: str,
    assistant_reply: str,
    session_id: str = "",
) -> List[Dict[str, Any]]:
    """从一轮对话中提取用户记忆

    Args:
        user_message: 用户消息
        assistant_reply: AI 回复
        session_id: 会话 ID（用于日志）

    Returns:
        记忆列表 [{type, key, value, importance, context}]
    """
    # 跳过太短的对话（问候、感谢等）
    if len(user_message) < 4 and len(assistant_reply) < 20:
        return []

    prompt = (
        f"用户消息: {user_message[:500]}\n"
        f"AI 回复: {assistant_reply[:500]}\n\n"
        f"请提取值得记住的用户信息（纯 JSON 数组）。"
    )

    try:
        from app.llm import LLMFactory
        llm = LLMFactory.create_suggestion_llm()  # 复用 suggestion 的轻量模型
        response = await llm.ainvoke([
            SystemMessage(content=EXTRACTION_PROMPT),
            HumanMessage(content=prompt),
        ])
        content = response.content if isinstance(response.content, str) else ""
        items = _parse_extraction_result(content)

        if items:
            # 添加 context 字段
            for item in items:
                if "context" not in item:
                    item["context"] = f"session={session_id} | user: {user_message[:100]}"
            logger.info(
                f"[memory-extractor] Extracted {len(items)} memories | "
                f"session={session_id} keys={[i.get('key','?') for i in items]}"
            )
        return items

    except Exception as e:
        logger.warning(
            f"[memory-extractor] Extraction failed | session={session_id} error={e}"
        )
        return []


async def extract_and_save(
    tenant_id: int,
    user_id: str,
    user_message: str,
    assistant_reply: str,
    session_id: str = "",
) -> int:
    """提取记忆并保存到 user_memories 表

    这是 chat.py 的主要调用入口。

    Args:
        tenant_id: 租户 ID
        user_id: 用户 ID
        user_message: 用户消息
        assistant_reply: AI 回复
        session_id: 会话 ID

    Returns:
        成功保存的记忆条数
    """
    items = await extract_memories_from_turn(user_message, assistant_reply, session_id)
    if not items:
        return 0

    try:
        from app.memory.user_memory import UserMemoryManager
        manager = UserMemoryManager()
        count = await manager.batch_upsert(tenant_id, user_id, items)
        logger.info(
            f"[memory-extractor] Saved {count}/{len(items)} memories | "
            f"tenant={tenant_id} user={user_id}"
        )
        return count
    except Exception as e:
        logger.error(f"[memory-extractor] Save failed: {e}")
        return 0
