#!/usr/bin/env python3
"""
ontology 契约校验脚本（issue #2821 切片 3）— contract-check.sh 第 6 项

以 schema.intent_ownership 为单一事实源，与真实 skill_registry 映射对比：
- 试点范围（schema 已声明 intent）：防假声明 / route_key 漂移 / 双端（mibao/xiaobu）视图不可达
- include_unregistered=False：未登记 intent 仅提示不阻断（留待全量登记迭代）

用法：python3 scripts/check_ontology_contract.py
退出码：0=一致；1=发现违规
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


def main() -> int:
    try:
        ontology = load_ontology()
    except OntologySchemaError as e:
        print(f"❌ 本体 schema 加载失败: {e}")
        return 1

    from app.agents.agents.mibao import MIBAO_CONFIG  # noqa: E402
    from app.agents.agents.xiaobu import XIAOBU_CONFIG  # noqa: E402
    from app.graph.skills.skill_registry import get_skill_registry  # noqa: E402

    registry = get_skill_registry()
    intent_to_route = registry.get_intent_to_route_map(persona="mibao")

    def agent_route_keys(config) -> dict:
        keys = set()
        for skill_name in config.skill_names:
            sc = registry.get(skill_name)
            if sc:
                keys.update(sc.route_keys)
        return keys

    agent_keys = {
        "mibao": agent_route_keys(MIBAO_CONFIG),
        "xiaobu": agent_route_keys(XIAOBU_CONFIG),
    }

    violations = check_intent_ownership(
        ontology, intent_to_route, agent_keys, include_unregistered=False
    )

    registered = sorted(ontology.intent_ownership or {})
    unregistered = sorted(
        k for k in intent_to_route if k not in ontology.intent_ownership
    )
    print(f"ℹ️  schema 已登记 intent（试点范围）: {registered}")
    print(f"ℹ️  skill 已映射未登记（留待全量登记）: {unregistered}")
    if violations:
        print(f"❌ intent 归属契约违规 {len(violations)} 项:")
        for v in violations:
            print(f"   - {v}")
        return 1
    print("✅ intent 归属契约一致（schema 已声明范围）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
