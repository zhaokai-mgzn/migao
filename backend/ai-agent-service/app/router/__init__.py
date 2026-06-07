"""
意图路由引擎 (Intent Router)

三级路由架构：
- L1: 规则匹配（关键词 + 正则）
- L2: 轻量模型意图分类
- L3: 路由决策（直接回复 / 带提示路由 / 全量 Agent）
"""

from app.router.intent_config import IntentType, IntentResult, RouteDecision
from app.router.rule_matcher import RuleMatcher
from app.router.intent_classifier import IntentClassifier
from app.router.intent_router import IntentRouter

__all__ = [
    "IntentType",
    "IntentResult",
    "RouteDecision",
    "RuleMatcher",
    "IntentClassifier",
    "IntentRouter",
]
