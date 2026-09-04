"""
intent 归属契约校验测试（issue #2821 切片 3）

覆盖 app.ontology.contract.check_intent_ownership 公共契约：
- schema.intent_ownership 声明 intent→route_key→agents 归属表
- 与 skill_registry 实际映射对比：schema 声明缺失 / 实际 intent 未登记 / route_key 漂移 / 双端视图不可达
- 返回违规清单（不抛异常，由调用方决定是否阻断）

Seam: app.ontology.contract.check_intent_ownership()（纯函数，输入 schema + 实际映射，
输出违规清单；不触碰 skill_registry 内部实现）。
"""
# case_ids: OB-003

import pytest

from app.ontology.contract import check_intent_ownership
from app.ontology.loader import load_ontology


@pytest.fixture
def ontology():
    """加载默认 schema.yaml（含 intent_ownership 段）"""
    return load_ontology()


# 实际 skill 映射（真值来源：skill_registry.get_intent_to_route_map 语义 + B/C 端 skill 声明）
REAL_INTENT_TO_ROUTE = {
    "order_query": "order",
    "order_create": "order",
    "logistics_track": "order",
    "after_sales": "aftersales",
    "after_sales_create": "aftersales",
    "complaint": "aftersales",
}

# 双端可达 route_key（真值来源：mibao.py/xiaobu.py skill_names → skill_config.route_keys）
REAL_AGENT_ROUTE_KEYS = {
    "mibao": {"order", "product", "aftersales", "customer", "staff", "settings", "data", "general"},
    "xiaobu": {"order", "product", "quote", "aftersales", "knowledge", "general"},
}


class TestSchemaIntentOwnership:
    def test_schema_declares_order_domain_intents(self, ontology):
        """schema 必须声明订单/售后域 intent 归属（试点范围）"""
        owned = ontology.intent_ownership
        assert owned is not None and len(owned) >= 6
        for intent in ("order_query", "order_create", "logistics_track",
                       "after_sales", "after_sales_create", "complaint"):
            assert intent in owned, f"schema 未登记 intent {intent}"
        assert owned["order_query"].route_key == "order"
        assert owned["after_sales"].route_key == "aftersales"

    def test_dual_agent_declared(self, ontology):
        """订单/售后域 intent 必须两端（mibao+xiaobu）都声明可达"""
        for intent in ("order_query", "order_create", "after_sales_create"):
            agents = ontology.intent_ownership[intent].agents
            assert {"mibao", "xiaobu"} <= set(agents), f"{intent} 缺双端声明"


class TestContractValidation:
    def test_consistent_mapping_returns_no_violations(self, ontology):
        """schema 与真实映射一致 → 违规清单为空"""
        violations = check_intent_ownership(
            ontology, REAL_INTENT_TO_ROUTE, REAL_AGENT_ROUTE_KEYS
        )
        assert violations == []

    def test_schema_intent_missing_from_skill_map(self, ontology):
        """schema 声明了但 skill 映射缺失 → 违规（B 端新增 intent 未实现）"""
        skill_map = dict(REAL_INTENT_TO_ROUTE)
        del skill_map["order_create"]
        violations = check_intent_ownership(ontology, skill_map, REAL_AGENT_ROUTE_KEYS)
        assert any("order_create" in v and "缺失" in v for v in violations)

    def test_actual_intent_not_registered_in_schema(self, ontology):
        """skill 映射有但 schema 未登记 → 违规（新 intent 漂移，无机制强制的洞）"""
        skill_map = dict(REAL_INTENT_TO_ROUTE)
        skill_map["new_intent_no_schema"] = "order"
        violations = check_intent_ownership(ontology, skill_map, REAL_AGENT_ROUTE_KEYS)
        assert any("new_intent_no_schema" in v and "未登记" in v for v in violations)

    def test_route_key_drift_detected(self, ontology):
        """schema 的 route_key 与实际映射不一致 → 违规"""
        skill_map = dict(REAL_INTENT_TO_ROUTE)
        skill_map["order_query"] = "product"  # 漂移
        violations = check_intent_ownership(ontology, skill_map, REAL_AGENT_ROUTE_KEYS)
        assert any("order_query" in v and "route_key" in v for v in violations)

    def test_xiaobu_route_unreachable_detected(self, ontology):
        """schema 声明 xiaobu 可达，但 xiaobu 实际无该 route_key → 违规
        （正是 skill_registry.py:163-166 注释『修改 B 端 intent 必须验证 xiaobu』
        要强制化的场景：改 B 端映射后 xiaobu 视图没跟上）"""
        agent_keys = {
            "mibao": REAL_AGENT_ROUTE_KEYS["mibao"],
            "xiaobu": {"order", "product", "quote", "knowledge", "general"},  # 缺 aftersales
        }
        violations = check_intent_ownership(ontology, REAL_INTENT_TO_ROUTE, agent_keys)
        assert any("xiaobu" in v and "aftersales" in v for v in violations)

    def test_returns_list_not_raise(self, ontology):
        """缺失时返回违规清单而非抛异常（调用方决定阻断）"""
        violations = check_intent_ownership(ontology, {}, {})
        assert isinstance(violations, list)
        assert len(violations) >= 6

    def test_include_unregistered_false_ignores_unregistered(self, ontology):
        """试点模式（include_unregistered=False）：未登记 intent 不算违规，
        只严查 schema 已声明范围（防假声明/漂移/双端不可达）"""
        skill_map = dict(REAL_INTENT_TO_ROUTE)
        skill_map["unregistered_intent"] = "order"  # 未登记
        violations = check_intent_ownership(
            ontology, skill_map, REAL_AGENT_ROUTE_KEYS, include_unregistered=False
        )
        assert not any("unregistered_intent" in v for v in violations)

    def test_include_unregistered_false_still_catches_drift(self, ontology):
        """试点模式仍必须拦截 schema 已声明范围的 route_key 漂移"""
        skill_map = dict(REAL_INTENT_TO_ROUTE)
        skill_map["order_query"] = "product"  # 已登记 intent 漂移
        violations = check_intent_ownership(
            ontology, skill_map, REAL_AGENT_ROUTE_KEYS, include_unregistered=False
        )
        assert any("order_query" in v and "route_key" in v for v in violations)
