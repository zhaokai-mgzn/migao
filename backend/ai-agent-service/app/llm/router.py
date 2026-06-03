"""
LLM 模型路由

模型分工：
  - qwen3.7-max  — 复杂推理、多工具协同
  - qwen3.6-plus — 图片识别、意图识别、默认平衡档

启用条件：settings.LLM_ENABLE_MODEL_ROUTING=True
关闭时直接返回 settings.DASHSCOPE_MODEL（qwen3.7-max）。
"""

from __future__ import annotations

from typing import Any, List, Optional

from app.config import settings


# ---- 模型常量 ----
MODEL_MAX: str = "qwen3.7-max"      # 复杂推理 / 多工具协同
MODEL_PLUS: str = "qwen3.6-plus"    # 图片识别 / 意图识别 / 默认平衡档

# ---- 路由判定阈值 ----
_SIMPLE_INTENTS = {"greeting", "farewell", "capabilities"}
_TOOL_COUNT_MAX_THRESHOLD = 3
_TEXT_LENGTH_MAX_THRESHOLD = 8000


def has_images(messages: Optional[List[Any]]) -> bool:
    """检测消息列表中是否包含图片内容

    遍历 LangChain 消息列表，检查是否有 image_url 类型的 content。
    """
    if not messages:
        return False
    for msg in messages:
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    return True
    return False


def select_model(
    intent: str = "",
    tool_count: int = 0,
    text_length: int = 0,
    force_model: Optional[str] = None,
    has_vision: bool = False,
) -> str:
    """根据任务复杂度选择模型

    判定优先级：
        1. LLM_ENABLE_MODEL_ROUTING=False → 默认模型（关闭路由）
        2. force_model 显式覆盖
        3. 图片识别 (has_vision) → qwen3.6-plus
        4. 意图识别 / 简单意图 → qwen3.6-plus
        5. 工具数 >= 3 或文本长度 > 8000 → qwen3.7-max
        6. 其他 → qwen3.6-plus

    Args:
        intent: 意图名（与 IntentType 字符串保持一致）
        tool_count: 当前 Skill 绑定的 Tool 数量
        text_length: 输入消息+历史的总字符数
        force_model: 显式指定的模型名，跳过自动判定
        has_vision: 是否包含图片内容

    Returns:
        模型名（百炼可识别的 model 字段）
    """
    # 1. 路由开关关闭时直接走默认模型
    if not settings.LLM_ENABLE_MODEL_ROUTING:
        return settings.DASHSCOPE_MODEL

    # 2. 显式 force_model 优先
    if force_model:
        return force_model

    # 3. 图片识别 → qwen3.6-plus
    if has_vision:
        return MODEL_PLUS

    # 4. 意图识别 / 简单意图 → qwen3.6-plus
    if intent and intent.lower() in _SIMPLE_INTENTS:
        return MODEL_PLUS

    # 5. 复杂推理 → qwen3.7-max
    if tool_count >= _TOOL_COUNT_MAX_THRESHOLD or text_length > _TEXT_LENGTH_MAX_THRESHOLD:
        return MODEL_MAX

    # 6. 默认 → qwen3.6-plus
    return MODEL_PLUS
