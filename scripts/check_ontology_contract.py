#!/usr/bin/env python3
"""
ontology 契约校验脚本（issue #2821 延续切片 A）— contract-check.sh 第 6 项

以 schema.intent_ownership 为单一事实源，与双端（mibao/xiaobu）真实可达映射对比：
- 全量严查（include_unregistered=True）：schema 声明缺失 / 未登记 / route_key 漂移
  （mibao 严格一致）/ 双端视图不可达，任一违规即退出 1
- 双端视图构建口径：registry 的 persona 过滤映射 ∩ 该 agent 实际启用的 skill
  （get_all_skill_names 含 fallback）→ 排除 RAG 禁用（mibao 无 knowledge）与
  兜底 general 的失真，只留真实可达业务 intent

用法：python3 scripts/check_ontology_contract.py
退出码：0=一致；1=发现违规

CI 接线（issue #4058）：workflow 侧未显式接线（`.github/workflows/**` 需 workflow scope），
改由既有 CI 会跑的 `tests/unit_ci_workflows/` 守卫测试覆盖同一份逻辑
（`test_ontology_contract_gate.py` 直接调本脚本并断言 exit 0）。
"""
import os
import sys
from pathlib import Path

# ── 与 tests/conftest.py 一致的环境注入（Settings 部分字段无默认值）──
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("ADMIN_API_BASE_URL", "http://admin-api:8080")
os.environ.setdefault("SERVICE_TOKEN", "test-service-token")
os.environ.setdefault(
    "JWT_PUBLIC_KEY",
    "-----BEGIN PUBLIC KEY-----\nTESTKEY\n-----END PUBLIC KEY-----",
)
os.environ.setdefault("LOGISTICS_API_URL", "https://wuliu.market.alicloudapi.com/kdi")
os.environ.setdefault("LOGISTICS_APPCODE", "test-appcode")
os.environ.setdefault("SSE_TIMEOUT", "300")
os.environ.setdefault("SSE_PING_INTERVAL", "30")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:3000")

# ai-agent-service 加入 sys.path（脚本从仓库根调用，路径为 backend/ai-agent-service）
AIS_ROOT = Path(__file__).resolve().parent.parent / "backend" / "ai-agent-service"
sys.path.insert(0, str(AIS_ROOT))

from app.ontology.contract import check_intent_ownership  # noqa: E402
from app.ontology.loader import OntologySchemaError, load_ontology  # noqa: E402

# 兜底 intent 不属于业务归属表（路由机制，非业务意图）
_BUSINESS_EXCLUDE = {"general"}


def _agent_intent_map(registry, config) -> dict:
    """该 agent 真实可达的 intent→route_key 映射。

    口径：registry.get_intent_to_route_map(persona=agent)（保持注册顺序的
    last-wins 语义）∩ 该 agent 实际启用 skill（get_all_skill_names 含 fallback）
    声明的 intent 集合，排除 general 兜底——避免 RAG 禁用（mibao 的 knowledge）
    与兜底 skill 造成的失真。
    """
    persona_map = registry.get_intent_to_route_map(persona=config.persona)
    allowed = set()
    for skill_name in config.get_all_skill_names():
        sc = registry.get(skill_name)
        if sc:
            allowed.update(sc.intents)
    return {k: v for k, v in persona_map.items() if k in allowed and k not in _BUSINESS_EXCLUDE}


def _agent_route_keys(registry, config) -> set:
    """该 agent 真实可达 route_key 集合（get_all_skill_names 含 fallback 的 route_keys 并集）"""
    keys = set()
    for skill_name in config.get_all_skill_names():
        sc = registry.get(skill_name)
        if sc:
            keys.update(sc.route_keys)
    return keys


def run_audit() -> tuple:
    """跑一次归属契约审计（单一口径，供 CLI 与守卫测试共用）。

    Returns:
        (exit_code, lines)：exit_code 0=一致 / 1=违规或 schema 加载失败；
        lines = 完整输出行（含每项违规明细，**不截断**——issue #4058：
        contract-check.sh 曾把明细行过滤掉 ⇒ 门禁红却指不出是谁）。
    """
    try:
        ontology = load_ontology()
    except OntologySchemaError as e:
        return 1, [f"❌ 本体 schema 加载失败: {e}"]

    from app.agents.agents.mibao import MIBAO_CONFIG  # noqa: E402
    from app.agents.agents.xiaobu import XIAOBU_CONFIG  # noqa: E402
    from app.graph.skills.skill_registry import get_skill_registry  # noqa: E402

    registry = get_skill_registry()

    agent_intent_maps = {
        "mibao": _agent_intent_map(registry, MIBAO_CONFIG),
        "xiaobu": _agent_intent_map(registry, XIAOBU_CONFIG),
    }
    agent_route_keys = {
        "mibao": _agent_route_keys(registry, MIBAO_CONFIG),
        "xiaobu": _agent_route_keys(registry, XIAOBU_CONFIG),
    }

    violations = check_intent_ownership(
        ontology, agent_intent_maps, agent_route_keys, include_unregistered=True
    )

    registered = sorted(ontology.intent_ownership or {})
    lines = [f"ℹ️  schema 已登记业务 intent: {len(registered)} 个"]
    for agent, mapping in agent_intent_maps.items():
        lines.append(
            f"ℹ️  {agent} 真实可达 intent: {len(mapping)} 个 "
            f"| route_keys: {sorted(agent_route_keys[agent])}"
        )
    if violations:
        lines.append(f"❌ intent 归属契约违规 {len(violations)} 项:")
        lines.extend(f"   - {v}" for v in violations)  # 每项完整明细
        return 1, lines
    lines.append("✅ intent 归属契约一致（全量严查：双端视图对齐 schema）")
    return 0, lines


def main() -> int:
    code, lines = run_audit()
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
