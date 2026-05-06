"""
后续问题建议模块

在 AI 回复结束后自动推荐后续问题，引导用户继续对话。
"""

from app.suggestions.follow_up import (
    FollowUpSuggestionGenerator,
    PRESET_SUGGESTIONS,
    DEFAULT_SUGGESTIONS,
)

__all__ = [
    "FollowUpSuggestionGenerator",
    "PRESET_SUGGESTIONS",
    "DEFAULT_SUGGESTIONS",
]
