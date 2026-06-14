"""
LLM 基础设施层

统一封装 LLM 实例创建、模型路由、成本追踪、智能重试等横切能力。
对上层 Skill / Router / Suggestion 节点屏蔽 ChatOpenAI 构造细节。
"""

from app.llm.factory import (
    LLMFactory,
    MINIMAX_BASE_URL,
    MINIMAX_API_KEY,
)
from app.llm.router import (
    select_model,
    has_images,
)
# 模型路由常量已收敛到 config.py，此处从 settings 重新导出以保持向后兼容
# 后续新增代码请直接使用 settings.LLM_MODEL_*
from app.config import settings as _settings
MODEL_PRIMARY = _settings.LLM_MODEL_PRIMARY
MODEL_FAST = _settings.LLM_MODEL_FAST
from app.llm.cost_tracker import CostTracker, CostRecord, MODEL_PRICING
from app.llm.retry_policy import call_with_retry

# 进程内单例：所有 LLM 调用点统一使用此实例累计成本
cost_tracker = CostTracker()

# 向后兼容别名（测试/旧代码引用旧常量名时自动映射到新名）
MODEL_MAX = MODEL_PRIMARY
MODEL_PLUS = MODEL_PRIMARY
MODEL_LITE = MODEL_FAST
MODEL_FLASH = MODEL_FAST
DASHSCOPE_BASE_URL = MINIMAX_BASE_URL
DASHSCOPE_MODEL = _settings.MINIMAX_MODEL

__all__ = [
    "LLMFactory",
    "MINIMAX_BASE_URL",
    "MINIMAX_API_KEY",
    "select_model",
    "has_images",
    "MODEL_PRIMARY",
    "MODEL_FAST",
    "CostTracker",
    "CostRecord",
    "MODEL_PRICING",
    "call_with_retry",
    "cost_tracker",
]
