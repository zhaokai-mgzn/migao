"""
LLM 模型路由

根据任务复杂度（意图、工具数、文本长度）选择合适的模型，平衡成本与效果。

启用条件：settings.LLM_ENABLE_MODEL_ROUTING=True
默认关闭：在关闭时直接返回 settings.DASHSCOPE_MODEL，保持原有行为。
"""

from __future__ import annotations

from typing import Any, List, Optional

from app.config import settings


# ---- 模型路由常量已收敛到 settings（app/config.py），禁止在此硬编码 ----
#     settings.LLM_MODEL_MAX   — 复杂推理 / 多工具协同
#     settings.LLM_MODEL_PLUS  — 默认平衡档
#     settings.LLM_MODEL_LITE — 轻量快速
#     settings.LLM_MODEL_FLASH — 极简任务
#     settings.DASHSCOPE_VISION_MODEL — 视觉模型

# ---- 路由判定阈值 ----
_SIMPLE_INTENTS = {"greeting", "farewell", "capabilities"}
_TOOL_COUNT_MAX_THRESHOLD = 3
_TEXT_LENGTH_MAX_THRESHOLD = 8000


def has_images(messages: Optional[List[Any]]) -> bool:
    """检测最后一条 HumanMessage 是否包含图片内容

    只检查最后一条 HumanMessage，而非全量扫描。
    避免历史图片污染后续纯文本消息的 LLM 路由决策 (Issue #204)。
    """
    if not messages:
        return False
    from langchain_core.messages import HumanMessage
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, list):
                return any(
                    isinstance(item, dict) and item.get("type") == "image_url"
                    for item in content
                )
            return False
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
        3. has_vision=True 且启用视觉 → DASHSCOPE_VISION_MODEL
        4. 简单意图（greeting/farewell/capabilities）→ lite
        5. 工具数 >= 3 或文本长度 > 8000 → max
        6. 其他 → plus

    Args:
        intent: 意图名（与 IntentType 字符串保持一致）
        tool_count: 当前 Skill 绑定的 Tool 数量
        text_length: 输入消息+历史的总字符数
        force_model: 显式指定的模型名，跳过自动判定
        has_vision: 是否包含图片内容，需要路由到视觉模型

    Returns:
        模型名（百炼可识别的 model 字段）
    """
    # 1. 路由开关关闭时直接走默认模型
    if not settings.LLM_ENABLE_MODEL_ROUTING:
        return settings.DASHSCOPE_MODEL

    # 2. 显式 force_model 优先
    if force_model:
        return force_model

    # 3. 多模态视觉请求优先路由到视觉模型
    if has_vision and settings.DASHSCOPE_VISION_ENABLED:
        return settings.DASHSCOPE_VISION_MODEL

    # 4. 简单意图 → lite
    if intent and intent.lower() in _SIMPLE_INTENTS:
        return settings.LLM_MODEL_LITE

    # 5. 复杂任务 → max
    if tool_count >= _TOOL_COUNT_MAX_THRESHOLD or text_length > _TEXT_LENGTH_MAX_THRESHOLD:
        return settings.LLM_MODEL_MAX

    # 6. 默认平衡档
    return settings.LLM_MODEL_PLUS
