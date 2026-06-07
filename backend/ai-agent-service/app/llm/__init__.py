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
)
# 模型路由常量已收敛到 config.py，此处从 settings 重新导出以保持向后兼容
# 后续新增代码请直接使用 settings.LLM_MODEL_*
from app.config import settings as _settings
MODEL_MAX = _settings.LLM_MODEL_MAX
MODEL_PLUS = _settings.LLM_MODEL_PLUS
MODEL_LITE = _settings.LLM_MODEL_LITE
MODEL_FLASH = _settings.LLM_MODEL_FLASH
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
    "MODEL_LITE",
    "MODEL_FLASH",
    "CostTracker",
    "CostRecord",
    "MODEL_PRICING",
    "call_with_retry",
    "cost_tracker",
]
