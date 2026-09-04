"""
intent 归属契约校验测试（issue #2821 延续切片 A：全量登记 + 按 agent 核对）

覆盖 app.ontology.contract.check_intent_ownership 公共契约（v2 签名）：
- agent_intent_maps: {agent: {intent: route_key}} 每个 agent 实际注册 skill 的意图→路由映射
  （真实可达，由 get_all_skill_names 含 fallback 构建，而非 persona 过滤——后者会
  包含被 RAG 禁用/未启用的 skill）
- agent_route_keys: {agent: set(route_keys)} 每个 agent 真实可达的路由集合
- schema.intent_ownership 全量登记 27 个业务 intent（双端 23 + finance 仅 mibao +
  knowledge_faq/knowledge_manage/quote 仅 xiaobu；general 兜底不属业务表）
- 四类违规：agent 映射缺失（假声明）/ 未登记 / route_key 漂移 / 双端不可达

Seam: app.ontology.contract.check_intent_ownership()（纯函数，输入 schema + 双端映射，
输出违规清单；不触碰 skill_registry 内部实现）。
"""
# case_ids: ON-003

import pytest

from app.ontology.contract import check_intent_ownership
from app.ontology.loader import load_ontology


@pytest.fixture
def ontology():
    """加载默认 schema.yaml（含全量 intent_ownership 段）"""
    return load_ontology()


# ── 双端真实可达映射（真值来源：get_all_skill_names → skill.intents × route_keys）──
# 2026-09-04 实测：mibao 25 intent / xiaobu 27 intent（含 fallback 兜底 skill）
REAL_AGENT_INTENT_MAPS = {
    "mibao": {
        "after_sales": "aftersales", "after_sales_create": "aftersales",
        "ai_config": "settings", "category_manage": "product",
        "complaint": "aftersales", "customer_manage": "customer",
        "customer_query": "customer", "dashboard": "data",
        "data_report": "data", "employee_manage": "staff",
        "finance": "data", "logistics_track": "order",
        "notification": "settings", "order_create": "order",
        "order_query": "order", "permission_manage": "staff",
        "processing_manage": "product", "product_inquiry": "product",
        "quick_reply": "settings", "role_manage": "staff",
        "session_manage": "data", "staff_manage": "staff",
        "statistics": "data", "system_settings": "settings",
    },
    "xiaobu": {
        "after_sales": "aftersales", "after_sales_create": "aftersales",
        "ai_config": "data", "category_manage": "data",
        "complaint": "aftersales", "customer_manage": "data",
        "customer_query": "data", "dashboard": "data",
        "data_report": "data", "employee_manage": "data",
        "knowledge_faq": "knowledge", "knowledge_manage": "data",
        "logistics_track": "order", "notification": "data",
        "order_create": "order", "order_query": "order",
        "permission_manage": "data", "processing_manage": "data",
        "product_inquiry": "product", "quick_reply": "data",
        "quote": "quote", "role_manage": "data",
        "session_manage": "data", "staff_manage": "data",
        "statistics": "data", "system_settings": "data",
    },
}

# 真实可达 route_keys（含 fallback 兜底 skill 的 route_keys）
REAL_AGENT_ROUTE_KEYS = {
    "mibao": {"aftersales", "customer", "data", "general", "order", "product", "settings", "staff"},
    "xiaobu": {"aftersales", "customer", "data", "general", "knowledge", "order", "product", "quote", "settings", "staff"},
}


class TestSchemaIntentOwnership:
    def test_schema_registers_all_27_business_intents(self, ontology):
        """schema 必须全量登记 27 个业务 intent（排除 general 兜底）"""
        owned = ontology.intent_ownership
        assert set(owned) == {
            # 双端 23
            "after_sales", "after_sales_create", "ai_config", "category_manage",
            "complaint", "customer_manage", "customer_query", "dashboard",
            "data_report", "employee_manage", "logistics_track", "notification",
            "order_create", "order_query", "permission_manage", "processing_manage",
            "product_inquiry", "quick_reply", "role_manage", "session_manage",
            "staff_manage", "statistics", "system_settings",
            # 仅 mibao
            "finance",
            # 仅 xiaobu
            "knowledge_faq", "knowledge_manage", "quote",
        }

    def test_agent_declarations_reflect_reality(self, ontology):
        """agents 声明与真实可达一致：finance 仅 mibao；knowledge/quote 仅 xiaobu"""
        owned = ontology.intent_ownership
        assert owned["finance"].agents == ["mibao"]
        assert owned["quote"].agents == ["xiaobu"]
        assert owned["knowledge_faq"].agents == ["xiaobu"]
        assert set(owned["order_query"].agents) == {"mibao", "xiaobu"}

    def test_route_keys_match_mibao_global_map(self, ontology):
        """route_key 与 mibao 全局映射一致（B 端是路由约定事实源）"""
        owned = ontology.intent_ownership
        for intent, expected in {
            "order_query": "order", "order_create": "order",
            "after_sales": "aftersales", "complaint": "aftersales",
            "product_inquiry": "product", "customer_manage": "customer",
            "employee_manage": "staff", "system_settings": "settings",
            "dashboard": "data", "knowledge_faq": "knowledge",
            "quote": "quote",
        }.items():
            assert owned[intent].route_key == expected, f"{intent} route_key 漂移"


class TestContractValidation:
    def test_consistent_mapping_returns_no_violations(self, ontology):
        """schema 与双端真实映射一致 → 违规清单为空（全量严查）"""
        violations = check_intent_ownership(
            ontology, REAL_AGENT_INTENT_MAPS, REAL_AGENT_ROUTE_KEYS
        )
        assert violations == []

    def test_agent_mapping_missing_detected(self, ontology):
        """schema 声明某 agent 可达，但该 agent 映射缺失 → 违规（假声明）"""
        maps = {
            "mibao": {k: v for k, v in REAL_AGENT_INTENT_MAPS["mibao"].items()},
            "xiaobu": {k: v for k, v in REAL_AGENT_INTENT_MAPS["xiaobu"].items()},
        }
        del maps["mibao"]["order_create"]  # mibao 映射缺失
        violations = check_intent_ownership(ontology, maps, REAL_AGENT_ROUTE_KEYS)
        assert any("order_create" in v and "mibao" in v and "缺失" in v for v in violations)

    def test_agent_specific_quote_handled(self, ontology):
        """xiaobu 专属 quote：mibao 映射没有是正常的，不得误报"""
        violations = check_intent_ownership(
            ontology, REAL_AGENT_INTENT_MAPS, REAL_AGENT_ROUTE_KEYS
        )
        assert not any("quote" in v for v in violations)

    def test_unregistered_intent_detected(self, ontology):
        """agent 映射有但 schema 未登记 → 违规（新 intent 漂移）"""
        maps = {
            "mibao": dict(REAL_AGENT_INTENT_MAPS["mibao"]),
            "xiaobu": dict(REAL_AGENT_INTENT_MAPS["xiaobu"]),
        }
        maps["mibao"]["new_intent_no_schema"] = "order"
        violations = check_intent_ownership(ontology, maps, REAL_AGENT_ROUTE_KEYS)
        assert any("new_intent_no_schema" in v and "未登记" in v for v in violations)

    def test_route_key_drift_detected(self, ontology):
        """schema 的 route_key 与该 agent 实际映射不一致 → 违规"""
        maps = {
            "mibao": dict(REAL_AGENT_INTENT_MAPS["mibao"]),
            "xiaobu": dict(REAL_AGENT_INTENT_MAPS["xiaobu"]),
        }
        maps["mibao"]["order_query"] = "product"  # 漂移
        violations = check_intent_ownership(ontology, maps, REAL_AGENT_ROUTE_KEYS)
        assert any("order_query" in v and "route_key" in v for v in violations)

    def test_xiaobu_route_unreachable_detected(self, ontology):
        """schema 声明 xiaobu 可达的 intent，xiaobu 实际 route_key 缺失 → 违规"""
        agent_keys = {
            "mibao": REAL_AGENT_ROUTE_KEYS["mibao"],
            "xiaobu": REAL_AGENT_ROUTE_KEYS["xiaobu"] - {"aftersales"},  # 缺 aftersales
        }
        violations = check_intent_ownership(
            ontology, REAL_AGENT_INTENT_MAPS, agent_keys
        )
        assert any("xiaobu" in v and "aftersales" in v for v in violations)

    def test_returns_list_not_raise(self, ontology):
        """缺失时返回违规清单而非抛异常（调用方决定阻断）"""
        violations = check_intent_ownership(ontology, {}, {})
        assert isinstance(violations, list)
        assert len(violations) >= 27

    def test_include_unregistered_false_ignores_unregistered(self, ontology):
        """include_unregistered=False：未登记 intent 不算违规（兼容/降级模式）"""
        maps = {
            "mibao": dict(REAL_AGENT_INTENT_MAPS["mibao"]),
            "xiaobu": dict(REAL_AGENT_INTENT_MAPS["xiaobu"]),
        }
        maps["mibao"]["unregistered_intent"] = "order"
        violations = check_intent_ownership(
            ontology, maps, REAL_AGENT_ROUTE_KEYS, include_unregistered=False
        )
        assert not any("unregistered_intent" in v for v in violations)

    def test_include_unregistered_false_still_catches_drift(self, ontology):
        """降级模式仍必须拦截已登记范围的 route_key 漂移"""
        maps = {
            "mibao": dict(REAL_AGENT_INTENT_MAPS["mibao"]),
            "xiaobu": dict(REAL_AGENT_INTENT_MAPS["xiaobu"]),
        }
        maps["mibao"]["order_query"] = "product"  # 已登记 intent 漂移
        violations = check_intent_ownership(
            ontology, maps, REAL_AGENT_ROUTE_KEYS, include_unregistered=False
        )
        assert any("order_query" in v and "route_key" in v for v in violations)
