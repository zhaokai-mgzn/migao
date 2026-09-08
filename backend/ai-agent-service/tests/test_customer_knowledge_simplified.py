"""
测试 customer_knowledge — LLM WIKI 词条优先（issue #3051 P7）

两级策略：1) 优先 knowledge_search 检索本店已发布知识卡片（命中→基于卡片回答 + 来源标注）；
2) 未命中→LLM 内置领域知识兜底 + 通用建议免责。替代旧 RAG 检索（决策 D1）与旧纯 LLM 通用知识。
"""
# case_ids: API-022

from app.graph.skills.customer_knowledge_skill import (
    CUSTOMER_KNOWLEDGE_SKILL_CONFIG,
    CUSTOMER_KNOWLEDGE_TOOLS,
    CUSTOMER_KNOWLEDGE_SYSTEM_PROMPT,
)


class TestKnowledgeConfig:
    """knowledge skill 配置：词条优先"""

    def test_tool_list_has_knowledge_search(self):
        """tool_names 启用 knowledge_search（本店知识卡片检索）"""
        assert "knowledge_search" in CUSTOMER_KNOWLEDGE_TOOLS, (
            f"knowledge skill 应启用 knowledge_search，当前: {CUSTOMER_KNOWLEDGE_TOOLS}"
        )

    def test_config_tool_names_has_knowledge_search(self):
        assert "knowledge_search" in CUSTOMER_KNOWLEDGE_SKILL_CONFIG.tool_names

    def test_system_prompt_references_knowledge_search(self):
        """System Prompt 引用 knowledge_search（词条优先）"""
        assert "knowledge_search" in CUSTOMER_KNOWLEDGE_SYSTEM_PROMPT, (
            "System Prompt 应引用 knowledge_search 工具（词条优先策略）"
        )

    def test_system_prompt_has_card_source_note(self):
        """命中词条须注明「来自本店知识库」"""
        assert "来自本店知识库" in CUSTOMER_KNOWLEDGE_SYSTEM_PROMPT

    def test_system_prompt_has_fallback_disclaimer(self):
        """未命中兜底须注明通用行业建议"""
        assert "通用行业建议" in CUSTOMER_KNOWLEDGE_SYSTEM_PROMPT

    def test_system_prompt_mentions_built_in_knowledge(self):
        assert "知识" in CUSTOMER_KNOWLEDGE_SYSTEM_PROMPT

    def test_config_has_correct_domain(self):
        assert CUSTOMER_KNOWLEDGE_SKILL_CONFIG.name == "customer_knowledge"
        assert CUSTOMER_KNOWLEDGE_SKILL_CONFIG.domain == "knowledge"
        assert CUSTOMER_KNOWLEDGE_SKILL_CONFIG.default_persona == "xiaobu"

    def test_config_has_route_keys(self):
        assert "knowledge" in CUSTOMER_KNOWLEDGE_SKILL_CONFIG.route_keys
        assert "knowledge_faq" in CUSTOMER_KNOWLEDGE_SKILL_CONFIG.intents
