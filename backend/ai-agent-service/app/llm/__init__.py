"""
LLM 基础设施层

统一封装 LLM 实例创建、模型路由、成本追踪、智能重试等横切能力。
对上层 Skill / Router / Suggestion 节点屏蔽 ChatOpenAI 构造细节。
"""

from app.llm.factory import (
    LLMFactory,
    DASHSCOPE_BASE_URL,
    DASHSCOPE_API_KEY,
    DASHSCOPE_EMBEDDING_MODEL,
)
from app.llm.router import (
    select_model,
    has_images,
    MODEL_MAX,
    MODEL_PLUS,
    MODEL_TURBO,
    MODEL_FLASH,
    MODEL_VL_PLUS,
    MODEL_VL_MAX,
)
from app.llm.cost_tracker import CostTracker, CostRecord, MODEL_PRICING
from app.llm.retry_policy import call_with_retry

# 进程内单例：所有 LLM 调用点统一使用此实例累计成本
cost_tracker = CostTracker()

__all__ = [
    "LLMFactory",
    "DASHSCOPE_BASE_URL",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_EMBEDDING_MODEL",
    "select_model",
    "has_images",
    "MODEL_MAX",
    "MODEL_PLUS",
    "MODEL_TURBO",
    "MODEL_FLASH",
    "MODEL_VL_PLUS",
    "MODEL_VL_MAX",
    "CostTracker",
    "CostRecord",
    "MODEL_PRICING",
    "call_with_retry",
    "cost_tracker",
]
