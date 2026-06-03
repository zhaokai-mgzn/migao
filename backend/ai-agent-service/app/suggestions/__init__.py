"""
后续问题建议模块

在 AI 回复结束后自动推荐后续问题，引导用户继续对话。
Agent 感知：米宝（B 端）和小布（C 端）使用不同的预设建议。
"""

from app.suggestions.follow_up import (
    FollowUpSuggestionGenerator,
    MIBAO_PRESET_SUGGESTIONS,
    MIBAO_DEFAULT_SUGGESTIONS,
    XIAOBU_PRESET_SUGGESTIONS,
    XIAOBU_DEFAULT_SUGGESTIONS,
)

__all__ = [
    "FollowUpSuggestionGenerator",
    "MIBAO_PRESET_SUGGESTIONS",
    "MIBAO_DEFAULT_SUGGESTIONS",
    "XIAOBU_PRESET_SUGGESTIONS",
    "XIAOBU_DEFAULT_SUGGESTIONS",
]
