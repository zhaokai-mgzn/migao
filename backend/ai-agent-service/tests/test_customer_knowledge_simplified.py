"""
测试 customer_knowledge 简化 — 用LLM内置知识替代RAG

业务真值的一部分: knowledge简化 (AI用LLM内置领域知识回答，不依赖RAG)
"""
import pytest
from app.graph.skills.customer_knowledge_skill import (
    CUSTOMER_KNOWLEDGE_SKILL_CONFIG,
    CUSTOMER_KNOWLEDGE_TOOLS,
    CUSTOMER_KNOWLEDGE_SYSTEM_PROMPT,
)


class TestKnowledgeSimplifiedConfig:
    """knowledge skill 配置已简化"""

    def test_tool_list_is_empty(self):
        """简化后 tool_names 为空列表，不使用knowledge_search RAG工具"""
        assert CUSTOMER_KNOWLEDGE_TOOLS == [], (
            f"knowledge skill 应无 tools，当前: {CUSTOMER_KNOWLEDGE_TOOLS}"
        )

    def test_config_tool_names_is_empty(self):
        """SkillConfig.tool_names 为空"""
        assert CUSTOMER_KNOWLEDGE_SKILL_CONFIG.tool_names == []

    def test_system_prompt_does_not_reference_knowledge_search(self):
        """System Prompt 不再引用 knowledge_search 工具"""
        assert "knowledge_search" not in CUSTOMER_KNOWLEDGE_SYSTEM_PROMPT, (
            "System Prompt 不应再引用已禁用的 knowledge_search 工具"
        )

    def test_system_prompt_mentions_built_in_knowledge(self):
        """System Prompt 提及使用LLM内置知识"""
        assert "知识" in CUSTOMER_KNOWLEDGE_SYSTEM_PROMPT, (
            "System Prompt 应提及LLM知识能力"
        )

    def test_config_has_correct_domain(self):
        """Skill 配置的基础字段正确"""
        assert CUSTOMER_KNOWLEDGE_SKILL_CONFIG.name == "customer_knowledge"
        assert CUSTOMER_KNOWLEDGE_SKILL_CONFIG.domain == "knowledge"
        assert CUSTOMER_KNOWLEDGE_SKILL_CONFIG.default_persona == "xiaobu"

    def test_config_has_route_keys(self):
        """路由配置保留"""
        assert "knowledge" in CUSTOMER_KNOWLEDGE_SKILL_CONFIG.route_keys
        assert "knowledge_faq" in CUSTOMER_KNOWLEDGE_SKILL_CONFIG.intents
