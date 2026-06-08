"""
AI 智能客服系统 - Memory 模块

提供四层记忆系统：
1. Short-term Memory: 当前对话上下文（PostgreSQL session_messages + Redis ConversationTracker）
2. Long-term Memory: 用户画像/历史偏好（PostgreSQL user_memories 表）
3. Semantic Memory: 领域知识（DashVector 向量数据库，当前禁用）
4. Procedural Memory: Tool 执行经验（PostgreSQL）

详见文档：docs/architecture.md §4.4
"""

from app.memory.session_memory import SessionMemory
from app.memory.user_memory import UserMemoryManager

__all__ = [
    "SessionMemory",
    "UserMemoryManager",
]
