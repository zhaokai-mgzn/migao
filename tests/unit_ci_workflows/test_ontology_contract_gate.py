# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   「CI/门禁结构由 pytest 单测验证」是 misc.yml 里已登记的形态）
"""L0 守卫：`scripts/check_ontology_contract.py`（contract-check.sh 第 6 项）不得恒红、且**不许放宽成空判据**。

为什么这个文件存在（issue #4058，唯一账本；#4062 已关闭并入本单）：
  ① **恒红**：schema 曾声明 `processing_order_*` 三个已下线 intent（#3917 产品决策
     从注册与绑定下线）"mibao 可达"，而双端映射里没有 ⇒ `contract-check.sh`
     （AGENTS.md 铁律 2「三把工具」之一）在 main 上**必然红**；
     ⚠️ **#4196 已恢复接入**（schema 与双端映射重新一致）⇒ 该具体实例消失，
     但判据面**不降级**：见 `test_schema_declared_reachability_has_a_live_mapping`
     （由 schema 现读真值，覆盖同一形态的**两个方向**）；
  ② **不可诊断**：包装脚本用 `grep -E "^❌" | head -3` 取详情，而明细行前缀是
     `   - intent …`（无 ❌ 前缀）⇒ 被整片过滤，红却指不出是谁；
  ③ **零接线**：`scripts/check_ontology_contract.py` 全仓 workflow 0 处引用 ⇒
     「文档说必跑 / CI 不跑 / 本地恒红」三重静默。

本文件按**证据层**分两段（口径不同、依赖不同，勿混）：
  * `TestContractGate`（**本文件的主门禁**）—— 走 pyyaml-only 的 `app.ontology`，
    在 pr-check 的 `ci-workflow-tests` job（只装 `pytest pyyaml`）里**真跑**：
    锁定「schema 归属表 vs 双端映射」= 违规清单必须为空（恒红即红）。
  * `TestLiveAuditEndToEnd` —— 端到端跑真实 CLI（需 ai-agent 全依赖）：
    本机/ai-agent-tests.yml 里有依赖 ⇒ 真跑；CI 最小环境（无 loguru）⇒ **显式 skip
    并记原因**（照实登记，不把"没跑"读成"通过"）。
  * `TestLiveLayerIsWiredInCi` —— **判别力前置**（issue #6514）：上一段的 skip 只在
    「活映射面在 CI 里**真有人跑**」时才允许成立 —— 替代判据 =
    `backend/ai-agent-service/tests/test_ontology_contract.py::test_live_registry_matches_schema_no_violations`
    （直接跑 `scripts/check_ontology_contract.py` 断言 exit 0，**无 skip**），
    执行面 = `ai-agent-tests.yml` 的 `ai-agent-service unit tests`（装全依赖）。
    这条接线被摘掉 ⇒ **判红**（不是静默跳过）；本文件也据此在台账
    `tests/unit_ci_workflows/wiring_claims_ledger.json` 登记了 `WIRING_UNDER_TEST`（§28.2）。

⚠️ issue #6514 的病灶（本文件改前即此形态）：#6499 加了活映射却没登记 schema，
`contract-check.sh` 第 6 项在 main 上恒红，而 **CI 结构性看不见** —— 因为
① 唯一验活映射的端到端判据（上一段）在最小环境里恒 skip；② skip 理由声称「同口径的
schema 层断言见兄弟判据」，而兄弟判据用的是**本文件里硬编码的快照**（不是活映射）
⇒ 制造了「有人守着」的假象。现在 skip 有前置、指向的替代判据是真的（上一段）。

反向证明（不把门禁放宽成空判据）：`test_false_declaration_is_still_detected`
用**注入式红证**——造一个真·声明可达却无映射的 intent ⇒ 必须报违规。
若有人把检查改成「什么都不查」，这条会红（`migao-acceptance`：不会红的断言=空断言）。
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
AIS_ROOT = REPO_ROOT / "backend" / "ai-agent-service"
SCHEMA = AIS_ROOT / "app" / "ontology" / "schema.yaml"
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "check_ontology_contract.py"
WRAPPER = REPO_ROOT / "contract-check.sh"

# 走 pyyaml-only 的包路径（`app.ontology` 只依赖 yaml/dataclasses/typing）。
# 注意：**不能** import `scripts/check_ontology_contract.py`——它在模块级就拉
# 双端 Agent 配置（loguru/langgraph/…），CI 最小环境必然 ImportError。
sys.path.insert(0, str(AIS_ROOT))

from app.ontology.contract import check_intent_ownership  # noqa: E402
from app.ontology.loader import load_ontology  # noqa: E402

# ── 活映射面的**接线声明**（`migao-dev-flow` §28.2；台账 = tests/unit_ci_workflows/wiring_claims_ledger.json）──
# 本判据守的接线 = 「活映射（真 registry ↔ schema）**在 CI 里真有人跑**」：全依赖 job
# `ai-agent-tests.yml` 的 `ai-agent-service unit tests` 跑 `backend/ai-agent-service/tests/`
# 整个套件，其中 `test_live_registry_matches_schema_no_violations` 直接跑
# `scripts/check_ontology_contract.py` 并断言 exit 0（**无 skip 分支**，issue #6514）。
# 本文件在最小环境里 skip 的**前置**就是这条接线活着 —— 摘掉它 ⇒ 判红，不是静默跳过
# （见 `_live_layer_wiring_problems` 与 `TestLiveLayerIsWiredInCi`）。
WIRING_UNDER_TEST = "backend/ai-agent-service/tests/test_ontology_contract.py::test_live_registry_matches_schema_no_violations"

AIS_LIVE_TESTS = AIS_ROOT / "tests" / "test_ontology_contract.py"
AIS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ai-agent-tests.yml"
LIVE_LAYER_SYMBOL = "test_live_registry_matches_schema_no_violations"


def _live_layer_wiring_problems(
    live_text: str | None = None, workflow_text: str | None = None
) -> list[str]:
    """「活映射面在 CI 里真有人跑」—— 最小环境 skip 的**前置**（判别力前置，issue #6514）。

    helper job 只装 pytest+pyyaml ⇒ 活映射端到端层**物理上跑不了**；但「跑不了」只有在
    **替代面确实存在、且被装了全依赖的 job 真的执行**时才允许 skip。两半都只读文本、零依赖：
      ① 全依赖 job 里必须有一条**不 skip** 的活映射判据（`LIVE_LAYER_SYMBOL` 在 AI 侧测试文件里）；
      ② 那条判据所在的套件必须由装了全依赖的 job 跑（装 `requirements.txt` + `pytest tests/`）。
    任一不成立 ⇒ 返回问题清单；调用方据此 **fail**（不是 skip）。
    两个参数仅供**注入式红证**用（缺省 = 现读仓内真值）。
    """
    if live_text is None:
        live_text = (
            AIS_LIVE_TESTS.read_text(encoding="utf-8") if AIS_LIVE_TESTS.is_file() else ""
        )
    if workflow_text is None:
        workflow_text = (
            AIS_WORKFLOW.read_text(encoding="utf-8") if AIS_WORKFLOW.is_file() else ""
        )
    problems: list[str] = []
    if LIVE_LAYER_SYMBOL not in live_text:
        problems.append(
            "全依赖 job 里没有**不 skip** 的活映射判据："
            f"{AIS_LIVE_TESTS.relative_to(REPO_ROOT)} 里找不到 `{LIVE_LAYER_SYMBOL}` "
            "⇒ 最小环境 skip 后，活映射面在 CI 里**无人覆盖**"
        )
    if "requirements.txt" not in workflow_text:
        problems.append(
            f"{AIS_WORKFLOW.relative_to(REPO_ROOT)} 里没有装全依赖（requirements.txt）"
            "⇒ 活映射判据跑不起来"
        )
    if not re.search(r"pytest\s+tests/", workflow_text):
        problems.append(
            f"{AIS_WORKFLOW.relative_to(REPO_ROOT)} 里没有跑 ai-agent 整套 `tests/` "
            "⇒ 活映射判据不在执行面内"
        )
    return problems


# 双端真实可达映射（真值来源：get_all_skill_names → skill.intents × route_keys）
REAL_AGENT_INTENT_MAPS = {
    "mibao": {
        "after_sales": "aftersales", "after_sales_create": "aftersales",
        "ai_config": "settings", "category_manage": "product",
        "complaint": "aftersales", "customer_manage": "customer",
        "customer_query": "customer", "dashboard": "data",
        "data_report": "data", "employee_manage": "staff",
        "finance": "data", "knowledge_faq": "knowledge",
        "logistics_track": "order", "notification": "settings",
        "order_create": "order", "order_query": "order",
        "permission_manage": "staff", "processing_manage": "product",
        "product_inquiry": "product", "role_manage": "staff",
        # 加工单域（#3340 登记 → #3917 下线 → **#4196 恢复接入**）：route_key=order，
        # 由 order skill 承载 ⇒ 重新出现在 mibao 真值映射里（仅 B 端；C 端不声明）。
        "processing_order_generate": "order", "processing_order_query": "order",
        "processing_order_update": "order",
        # 定时提醒域（issue #6486 包 2 引入，**#6514 补登记 schema**）：route_key 取 reminder
        # skill 的 `route_keys` 末位（registry last-wins）；仅 B 端（C 端不声明）。
        "scheduled_task_manage": "scheduled_task",
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
        "product_inquiry": "product", "quote": "quote",
        "role_manage": "data", "session_manage": "data",
        "staff_manage": "data", "statistics": "data",
        "system_settings": "data",
    },
}

REAL_AGENT_ROUTE_KEYS = {
    # mibao 侧含 reminder / schedule / scheduled_task（issue #6486 包 2 的 reminder skill
    # 声明的三个 route_key；#6514 补进本快照 —— 此前它们只活在活映射里）。
    "mibao": {"aftersales", "customer", "data", "general", "knowledge",
              "order", "product", "reminder", "schedule", "scheduled_task",
              "settings", "staff"},
    "xiaobu": {"aftersales", "customer", "data", "general", "knowledge",
               "order", "product", "quote", "settings", "staff"},
}

# #3917 下线、由 #4058 对齐 schema 的 3 个 intent —— **#4196 已恢复接入** ⇒ 本元组清空。
# 口径随之**换向**（不是删判据）：原先守「这 3 个不得声明可达性」，现在守「schema 声明的
# 可达性必须与活映射一致」（见 `test_schema_declared_reachability_has_a_live_mapping`）。
# ⚠️ 之所以保留这个空元组而不是连判据一起删：删掉就等于把「已下线 intent 不许假声明可达」
# 这条**判别力**也一起丢掉（migao-acceptance：不会红的断言 = 空断言）。当前无已下线 intent
# ⇒ 由下面的对称判据承接同一判别力，并额外覆盖「新 intent 只在 schema 里声明、忘了落 skill」
# 这个方向。
RETIRED_INTENTS: tuple[str, ...] = ()

# schema 里**声明了可达性**（`agents` 非空）的业务 intent —— 真值由 schema.yaml 现读，
# 不在本文件硬编码（硬编码会让这条判据变成「与自己的副本比对」）。
def _schema_declared_mappings(ontology) -> dict[str, dict[str, str]]:
    """`{intent: {agent: route_key}}` —— 只取 schema 里 `agents` 非空的条目。"""
    return {
        name: {agent: own.route_key for agent in own.agents}
        for name, own in ontology.intent_ownership.items()
        if own.agents
    }


def _violations(ontology) -> list:
    """跑一次归属契约审计（与 CLI 同一份 check_intent_ownership，同参数）"""
    return check_intent_ownership(
        ontology, REAL_AGENT_INTENT_MAPS, REAL_AGENT_ROUTE_KEYS, include_unregistered=True
    )


@pytest.fixture(scope="module")
def ontology():
    return load_ontology()


class TestContractGate:
    """主门禁：契约必须一致（恒红即红）+ 修订不得放宽判据。"""

    def test_live_schema_has_no_violations(self, ontology):
        """§4058 核心：schema 归属表 vs 双端映射 = 违规清单为空。

        改前（schema 仍声明 processing_order_* 的 `agents: [mibao]`）这里红 3 项，
        原文：intent 'processing_order_generate' schema 声明 agent 'mibao' 可达，
        但该 agent 映射缺失（route_key=order）—— 即「contract-check.sh 恒红」的真因。
        """
        violations = _violations(ontology)
        assert violations == [], (
            "contract-check.sh 第 6 项会因此恒红（改前即此形态，issue #4058）：\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_schema_declared_reachability_has_a_live_mapping(self, ontology):
        """**对称判据**（承接 `RETIRED_INTENTS` 清空后的判别力，不降级为空断言）。

        口径：#3917 下线期这条守「已下线的 3 个 intent 不得声明可达性」；#4196 恢复接入后
        已无已下线 intent，故换成守**声明侧 ↔ 活映射侧一致**，两条子判据（**逐条点名**，
        不靠 `test_live_schema_has_no_violations` 的整体清单兜底）：
          · ① **存在性**：schema 里声明了 `agents` 的每个 intent，在对应 agent 的真值映射里
               必须有条目（缺 = 「假声明」形态，正是 #4058 恒红的病根）；
          · ② **route_key 一致性（仅 mibao）**：B 端全局映射是路由约定的事实源 ⇒ mibao 的
               route_key 必须与 schema 逐字一致。**xiaobu 不比对** —— 按
               `app/ontology/contract.py` 的既有契约（v2 第 1b 条），C 端 customer_general
               兜底 skill 会把大量 intent 的 route_key 覆盖成 `data`，只要求可达、不要求逐字
               （对 xiaobu 严比 = 制造 20+ 条与产品契约相悖的假红）。
        ① 覆盖「只在 schema 声明可达、忘了落 skill」这个方向（`RETIRED_INTENTS` 那三条判据
        只覆盖「已下线却仍声明」的反方向）——两条方向合起来才是完整判据面。
        """
        declared = _schema_declared_mappings(ontology)
        assert declared, (
            "schema 里没有任何 `agents` 非空的 intent ⇒ 本判据会静默空转（fail-closed）"
        )
        problems: list[str] = []
        for intent, agent_map in sorted(declared.items()):
            for agent, route_key in sorted(agent_map.items()):
                live = REAL_AGENT_INTENT_MAPS.get(agent, {})
                if intent not in live:
                    problems.append(
                        f"{intent}：schema 声明 {agent} 可达（route_key={route_key}），"
                        f"但该 agent 的真值映射里没有它"
                    )
                elif agent == "mibao" and live[intent] != route_key:
                    problems.append(
                        f"{intent}：route_key 漂移（mibao）—— schema={route_key}，"
                        f"活映射={live[intent]}"
                    )
        assert problems == [], (
            "schema 声明的可达性与活映射不一致（contract-check.sh 第 6 项会因此恒红，"
            "issue #4058 的形态）：\n  " + "\n  ".join(problems)
        )

    def test_retired_intents_declare_no_reachability(self, ontology):
        """已下线 intent（当前**无**，`RETIRED_INTENTS` 为空）：保留留史但不得声明可达性。

        照 loader.py 既有语义（agents 缺省为空 = 未声明可达性），**不新增**
        status/deprecated 字段——本 schema 无此惯例。
        ⚠️ `RETIRED_INTENTS` 为空 ⇒ 循环体不执行。**这不是空断言**：它是一条**待命**判据
        （下次有人下线 intent 时把名字填进元组即生效），且同一判别力当前由
        `test_schema_declared_reachability_has_a_live_mapping` 的 ① 承担 —— 那里用的是
        schema 现读的真值而非本元组。两者分工：本元组管「显式登记的下线项」，那条管「全部声明项」。
        """
        owned = ontology.intent_ownership
        for intent in RETIRED_INTENTS:
            assert intent in owned, f"{intent} 的留史登记被误删（应保留 route_key/description）"
            assert owned[intent].agents == [], (
                f"{intent} 已下线，agents 必须为空（不得重新声明可达性）"
            )
            assert owned[intent].route_key == "order", f"{intent} 留史 route_key 应为 order"

    def test_retired_intents_absent_from_actual_maps(self):
        """守卫生效的前提：已下线 intent 确实**不在**双端真实映射里（现实未回退）。

        当前 `RETIRED_INTENTS` 为空 ⇒ 循环不执行；把名字填回元组即恢复判别力
        （#3917 期间它是活判据，**#4196 恢复接入后** 这 3 个 intent 重新出现在 mibao 映射里
        —— 见上方 `REAL_AGENT_INTENT_MAPS`，故不得再把它们列进 `RETIRED_INTENTS`）。
        """
        for intent in RETIRED_INTENTS:
            for agent, mapping in REAL_AGENT_INTENT_MAPS.items():
                assert intent not in mapping, (
                    f"{intent} 重新出现在 {agent} 映射里 ⇒ schema 的 agents: [] 已过期，"
                    "应恢复 agents: [mibao]（勿只改测试）"
                )

    def test_false_declaration_is_still_detected(self, ontology):
        """**反向证明（注入式红证）**：真·声明可达却无映射 ⇒ 必须报违规。

        注入一个 schema 里真声明 `agents: [mibao]`、但双端映射都没有的 intent。
        若检查被放宽成空判据（永远返回 []），这条立刻红。
        """
        mappings = {a: dict(m) for a, m in REAL_AGENT_INTENT_MAPS.items()}
        mappings["mibao"]["ghost_intent_without_mapping"] = "order"
        violations = check_intent_ownership(
            ontology, mappings, REAL_AGENT_ROUTE_KEYS, include_unregistered=True
        )
        # 该 intent 已登记 schema 且 schema 声明 xiaobu 可达但 xiaobu 无映射 ⇒ 真违规
        assert any("ghost_intent_without_mapping" in v for v in violations), (
            "schema 已登记但某端映射缺失必须被报出（空判据即失效）"
        )

    def test_unreachable_route_key_is_still_detected(self, ontology):
        """反向证明之二：route_key 不可达仍必须报出（可达性判据未被放宽）。"""
        keys = {
            "mibao": REAL_AGENT_ROUTE_KEYS["mibao"],
            "xiaobu": REAL_AGENT_ROUTE_KEYS["xiaobu"] - {"order"},
        }
        violations = check_intent_ownership(
            ontology, REAL_AGENT_INTENT_MAPS, keys, include_unregistered=True
        )
        assert any("xiaobu" in v and "order" in v for v in violations)


class TestWrapperForwardsFullDetail:
    """§4058 缺陷②：包装脚本必须**原文转发完整明细**，不得截断。"""

    def test_wrapper_no_longer_filters_detail_lines(self):
        """静态锁：**检查 6（intent 归属契约）那一段**不得再出现详情过滤/截断形态。

        只看 ① 非注释行 ② §6 段内——理由（两条都是实测踩过的假红/假绿形态）：
        * 「解释旧形态」的注释本身会把这条判据变成假红；
        * 检查 1 早就用 `| head -5` 做**它自己的**grep 限量（与详情转发无关），
          全文扫 `head -` 会误伤既存代码。
        """
        lines = WRAPPER.read_text(encoding="utf-8").splitlines()
        marker = "intent 归属契约（schema 单一事实源"
        assert any(marker in ln for ln in lines), (
            "contract-check.sh 找不到检查 6 的分节注释（结构变了请同步本断言）"
        )
        start = next(i for i, ln in enumerate(lines) if marker in ln)
        code = "\n".join(
            ln for ln in lines[start:] if not ln.lstrip().startswith("#")
        )
        assert not re.search(r'grep\s+-E\s+"\^', code), (
            "检查 6 代码区又用 ^ 前缀 grep 过滤详情 ⇒ 明细行 `   - intent …` 会再次丢失"
        )
        assert not re.search(r"\|\s*head\s+-\d", code), (
            "检查 6 代码区又截断详情（head -N）⇒ 门禁红却指不出是谁"
        )

    # 夹具 = 其余 5 项检查的最小满足集（让执行真的走到第 6 项；**少一个文件包装层就会
    # 在第 4/5 项崩掉**——本文件作者实测踩过：夹具不全 ⇒ 伪造的明细永远到不了断言）
    _FIXTURE_FILES = {
        "backend/ai-agent-service/app/tools/order_query.py": 'status = "producing"\n',
        "backend/ai-agent-service/app/tools/order_manage.py": 'status = "producing"\n',
        "backend/ai-agent-service/app/tools/order_create.py": 'status = "producing"\n',
        "backend/ai-agent-service/app/graph/skills/references/prompts/order.md": "status producing\n",
        "backend/ai-agent-service/app/tools/logistics_track.py": 'status = "producing"\n',
        "frontend/admin-web/src/types/index.ts": "refundAmount\n",
        "frontend/admin-web/src/lib/data-adapter.ts": (
            "refundAmount refund_amount refund_reason\n"
        ),
        "backend/admin-api/src/main/java/com/migao/admin/entity/Order.java": "refundAmount\n",
        "backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java": (
            "refundAmount\n"
        ),
        "backend/admin-api/src/main/java/com/migao/admin/controller/agent/AgentProductController.java": (
            "skus/{skuId}\n"
        ),
    }

    def test_wrapper_prints_audit_stdout_verbatim(self):
        """行为锁：伪造一份「多行违规明细」的审计输出 ⇒ 包装层必须**逐行原文**打印。

        改前实现对该输入只打印「❌ …违规 3 项: 」后面**什么都没有**（issue #4058 实测）——
        因为明细行前缀是 `   - intent …` 而无 ❌，被 `grep -E "^❌" | head -3` 整片滤掉。
        """
        fixture = (
            "ℹ️  schema 已登记业务 intent: 29 个\n"
            "❌ intent 归属契约违规 1 项:\n"
            "   - intent 'ghost_intent' schema 声明 agent 'mibao' 可达，"
            "但该 agent 映射缺失（route_key=order）\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts" / "check_ontology_contract.py").write_text("", encoding="utf-8")
            for rel, body in self._FIXTURE_FILES.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")

            # 明细由 **py 文件**承载（真实 GB 字符），再用真实解释器跑它：
            # 既避开 shell locale 转码（Bash 3.2 无 printf %b \u），也与真实脚本同形态
            stub = root / "audit_stub.py"
            stub.write_text(
                "import sys\n"
                "sys.stdout.buffer.write(" + repr(fixture.encode("utf-8")) + ")\n"
                "sys.exit(1)\n",
                encoding="utf-8",
            )
            fake_py = root / "backend" / "ai-agent-service" / ".venv" / "bin" / "python"
            fake_py.parent.mkdir(parents=True)
            fake_py.write_text(
                f'#!/usr/bin/env bash\nexec "{sys.executable}" "$(dirname "$0")/../../../../audit_stub.py"\n',
                encoding="utf-8",
            )
            fake_py.chmod(0o755)
            runner = root / "contract-check.sh"
            runner.write_text(WRAPPER.read_text(encoding="utf-8"), encoding="utf-8")
            runner.chmod(0o755)

            proc = subprocess.run(
                ["bash", str(runner)], cwd=tmp, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=120,
            )

        out = proc.stdout
        assert proc.returncode == 1, f"包装脚本必须把审计失败传播为 exit 1\n{out}"
        # 逐行原文：判据行 + 明细行（intent 名 / 声明方 / 缺失映射 / route_key）都必须到
        for line in fixture.splitlines():
            assert line in out, f"该行未被原文转发（详情被截断/过滤）：{line!r}\n--- 实得 ---\n{out}"


class TestLiveAuditEndToEnd:
    """证据层：真实 CLI 端到端（需 ai-agent 全依赖；最小环境**有前置地** skip 并记原因）。"""

    def test_audit_script_exits_zero(self):
        """`scripts/check_ontology_contract.py` 必须以 0 退出（issue #4058 验收标准）。"""
        probe = subprocess.run(
            [sys.executable, "-c", "import loguru, langgraph"],
            capture_output=True, text=True,
        )
        if probe.returncode != 0:
            problems = _live_layer_wiring_problems()
            assert problems == [], (
                "ai-agent 全依赖不可用（本 job 只装 pytest pyyaml）**且**活映射面在 CI 里"
                "没有承接判据 ⇒ 这条 skip 会让「映射加了、schema 没登记」结构性不可见"
                "（issue #6514 的病根）：\n  - " + "\n  - ".join(problems)
            )
            pytest.skip(
                "ai-agent 全依赖不可用（本 job 只装 pytest pyyaml）⇒ 端到端层未跑；"
                "**同口径的活映射判据在装了全依赖的 job 里真跑且不 skip** = "
                f"{WIRING_UNDER_TEST}（CI job = ai-agent-tests.yml / ai-agent-service unit tests）"
                "—— 本文件只做最小环境可跑的那一半，不替代它。"
                f" 探测输出：{probe.stderr.strip().splitlines()[-1:] }"
            )
        proc = subprocess.run(
            [sys.executable, str(AUDIT_SCRIPT)],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300,
        )
        assert proc.returncode == 0, (
            f"审计脚本应 exit 0，实得 {proc.returncode}\n--- stdout ---\n{proc.stdout}"
        )
        assert "✅ intent 归属契约一致" in proc.stdout

    def test_audit_script_reports_detail_on_violation(self):
        """审计脚本的违规明细必须**逐项成行**（非一行塞完），供包装层原文转发。"""
        src = AUDIT_SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(src)
        joined = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"extend", "append"}
            and "lines" in ast.unparse(node.func.value)
            and "violation" in ast.unparse(node).lower()
        ]
        assert joined, (
            "审计脚本未把 violations 逐项加入输出行 ⇒ 明细会再次丢失（看 run_audit 实现）"
        )


class TestLiveLayerIsWiredInCi:
    """**判别力前置**（issue #6514 判据 3）：`TestLiveAuditEndToEnd` 的 skip 只许在
    「活映射面在 CI 里真有人跑」时成立 —— 否则判红。

    这就是 issue 正文「假承诺必须消掉」的**更强形态**：改前 skip 理由里那句「同口径的…
    见兄弟判据」指向的是**硬编码快照**（`REAL_AGENT_INTENT_MAPS`，不是活映射）⇒ 制造
    「有人守着」的假象。现在它指向一条**真跑活映射**的判据（`WIRING_UNDER_TEST`），
    且这条指向本身有判据 —— 摘掉替代判据 / 摘掉它的执行面 ⇒ 本类当场红。

    helper job（只装 pytest+pyyaml）与全依赖 job 里**都跑**（零依赖、只读文本）。
    """

    def test_live_mapping_criterion_runs_in_a_full_dependency_job(self):
        problems = _live_layer_wiring_problems()
        assert problems == [], (
            "最小环境 skip 的替代面不成立（issue #6514）：\n  - " + "\n  - ".join(problems)
        )

    def test_precondition_has_discriminating_power(self):
        """注入式自证：三条接线各摘一处 ⇒ 前置必须判红（不会红的断言 = 空断言）。"""
        live = AIS_LIVE_TESTS.read_text(encoding="utf-8")
        workflow = AIS_WORKFLOW.read_text(encoding="utf-8")
        # 对照读数：真值 ⇒ 零问题
        assert _live_layer_wiring_problems(live, workflow) == []
        # 自证注入点真实存在（否则下面的注入是空动作、本判据是空断言）
        assert LIVE_LAYER_SYMBOL in live
        assert "requirements.txt" in workflow
        assert "pytest tests/" in workflow
        # ① 活映射判据被删 / 改名
        assert _live_layer_wiring_problems(
            live.replace(LIVE_LAYER_SYMBOL, "zzz_removed_live_check"), workflow
        ) != [], "活映射判据被摘掉却仍判绿 ⇒ 前置是空断言"
        # ② 全依赖 job 不再装依赖
        assert _live_layer_wiring_problems(
            live, workflow.replace("requirements.txt", "zzz_removed_requirements")
        ) != [], "全依赖 job 不装依赖却仍判绿 ⇒ 前置是空断言"
        # ③ 全依赖 job 不再跑该套件
        assert _live_layer_wiring_problems(
            live, workflow.replace("pytest tests/", "pytest zzz_nothing/")
        ) != [], "全依赖 job 不跑该套件却仍判绿 ⇒ 前置是空断言"