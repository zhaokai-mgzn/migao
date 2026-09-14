# case_ids: OR-014
"""OR-014 能力自我否定族守卫（B 端「商品线上下文」自称无提交订单能力）—— 事实驱动面。

## 缺陷与根因（run `34856561459` · SHA `97668011` · mibao 腿，两次同指纹失败）

`OR-014` 期望 `must_succeed: order_create`，实际是 `order_create → unmatched expectation`，
agent 连续 7 轮自称没能力落单（R5「落单（提交订单）属于订单环节的操作，我这条线负责的是商品」/
R7「这单我不具备提交能力」/R8「这单在商品线确实落不了」/R11「这单要落单，请回「转人工」」）。
**反证**：同 run 的 OR-008/OR-010 真调成功了 `order_create` ⇒ 能力/权限可达，是 agent 自己
把业务边界画错。

根因链（零 LLM 复算，`RuleMatcher` + `_rule_intent_domain` + `_card_accepts_answer` 真实函数）：

| 轮 | 输入 | L1 | 路由 |
|---|---|---|---|
| R1 | 帮我下单，遮光窗帘 3 米，要打孔加工 | `order_create`(rule) | `order` skill，发「规格」choice 卡 |
| R2 | 米白 · 散剪 · 门幅2.8米 · ¥150/米 | — | 答卡轮（`_card_accepts_answer=True`）→ 留 `order` |
| R3 | 不需要其他加工项 | **`product_inquiry`(rule)**（关键词「加工项」） | **L1 域逃逸清锁 → `product` skill** |
| R4 | `__FORM__\|{…}` | — | R3 的 form 卡答卡轮 → 留 `product` |
| R5+ | 确认 / 123456 … | — | 短消息沿用 pending=`product`（容器日志 `[product] … has_tools=False`） |

`PRODUCT_TOOLS` 里没有 `order_create` ⇒ 模型"实话实说"自己这条线落不了单。两处必须一起修：
① 文本级能力误宣判据认不出**归属错位/`V不了`/「不具备…能力」/「落单」**这些**形态**（改前
实测 5 句全部返回空）；② `_relock_order_skill` 把回锁目标写死 C 端节点名 `customer_order`，
米宝图里没有该节点。本文件把两处的修法钉在**事实**上（注册表声明 + persona 可达集 +
会话状态），并额外钉住**合法换域不得被牺牲**（`#3625 G3/T2` 契约）。

判据与结构不变式见 `tests/unit_ci_workflows/test_denial_guard_or014_invariants.py`。
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from app.agents.agent_config import get_agent_config
from app.graph.nodes import route_by_intent
from app.graph.skills import base_skill
from app.graph.skills.base_skill import (
    ORDER_WRITE_TOOL,
    _flow_owner_skill,
    capability_denial_text_hit,
    create_skill_registry as _real_create_skill_registry,
)
from app.graph.skills.product_skill import PRODUCT_TOOLS
from app.router.rule_matcher import RuleMatcher
from app.tools.registry import get_tool_registry

# ── OR-014 真实否定原文（仅用于**验证判据覆盖**；判据本身不得含整句，见 L0 不变式）──
OR014_DENIALS = [
    "收到您的确认 ✅ **落单（提交订单）属于订单环节的操作，我这条线负责的是商品**，订单落单要走订单工作台。",
    "**这单我不具备提交能力**：我负责的是商品线，订单落单要走订单工作台。",
    "这单在**商品线**确实落不了，您再确认几次结果也一样，**请回「转人工」**",
    "**这单我确实下不了** —— 我负责商品线，订单落单",
    "一句话收口：**这单要落单，请回「转人工」**；或您自己到订单工作台提交。",
]

# 同 run 的邻近用例原文（OR-015/OR-016，run 34841029062 的「商品侧」形态）
OR015_DENIALS = [
    "下单属于订单模块的操作，我当前这边承接的是商品侧的工作。",
    "订单创建属于**订单模块**的活儿，我这边是商品模块。",
]

# **不得被误判**的边界（DF-020/021 越权拒绝、第三方主体客观说明、正常成功/开场白）
CLEAN_TEXTS = [
    "小布没有权限查看其他租户的数据，只能看您自己的订单",
    "小布无法帮您导出全部租户数据，也不会有这样的权限",
    "顾客在小程序里没有下单权限，需要人工开通",
    "该商品不支持散剪，下单时请注意",
    "库存不足无法创建订单",
    "亲，我是小布，您的专属咨询客服～",
    "已经帮您提交订单啦，订单号 20260914691810001",
    "好的，我这就帮您下单",
    "订单已创建，请您核对",
]

CONFIRM_CARD = {
    "component": "confirm",
    "title": "请确认订单信息",
    "confirmValue": "确认：商品=遮光窗帘（米白｜散剪｜2.8米）× 3；客户=张三 13800138000",
    "fields": [{"label": "商品", "value": "遮光窗帘"}],
}
GROUNDED_FACTS = {"grounded_product_detail": {"product_id": "prod_eval_blackout"}}


# ────────────────────── 措辞面：形态判据（不是句子白名单）──────────────────────

class TestDenialMorphologyCoverage:
    """归属错位 / `V不了` / 「不具备…能力」/ B 端动作词「落单」都是**形态**，不得整句入表。"""

    @pytest.mark.parametrize("text", OR014_DENIALS + OR015_DENIALS)
    def test_or014_denial_forms_are_caught(self, text):
        hit = capability_denial_text_hit(text)
        assert hit, f"能力误宣未被识别（OR-014 复发形态）：{text!r}"

    @pytest.mark.parametrize("text", CLEAN_TEXTS)
    def test_boundaries_stay_clean(self, text):
        assert capability_denial_text_hit(text) == "", f"越权/第三方/成功话术被误判：{text!r}"


# ────────────────────── 事实面：回锁目标由注册表 + persona 派生 ──────────────────────

class TestFlowOwnerIsFactDerived:
    """回锁目标 = 声明了 `order_create` 的 skill ∩ 当前 persona 可达集（**两个都是事实**）。"""

    @pytest.mark.parametrize("persona", ["mibao", "xiaobu"])
    def test_owner_is_reachable_in_persona_graph(self, persona):
        """不变式：回锁目标**必须真的存在于该 persona 的 skill_names**。

        实证（OR-014）：旧实现写死 `customer_order` → 米宝（B 端）图里没有该节点，
        `route_by_intent` 把 pending 名原样返回、条件边映射缺失 ⇒ 回锁自己把会话打坏。
        """
        owner = _flow_owner_skill({"agent_type": persona})
        assert owner, f"{persona} 解析不出下单流程归属 skill"
        cfg = get_agent_config(persona)
        assert owner in cfg.get_all_skill_names(), (
            f"回锁目标 {owner!r} 不在 {persona} 的 skill_names 里 → 图里没有该节点"
        )
        from app.graph.skills.skill_registry import get_skill_registry
        declared = get_skill_registry().get(owner)
        assert declared is not None, f"回锁目标 {owner!r} 不在 skill 注册表里"
        assert ORDER_WRITE_TOOL in declared.tool_names, (
            f"回锁目标 {owner!r} 并未声明 {ORDER_WRITE_TOOL} —— 回锁后仍然落不了单"
        )

    def test_owner_differs_per_persona(self):
        """两个 persona 各有自己的下单 skill（不得跨图互相指）。"""
        assert _flow_owner_skill({"agent_type": "mibao"}) != \
            _flow_owner_skill({"agent_type": "xiaobu"})

    def test_unknown_persona_does_not_guess(self):
        """认不出 persona 时不得瞎猜（只有唯一候选才允许回锁）—— 防指向不存在的节点。"""
        assert _flow_owner_skill({}) == ""
        assert _flow_owner_skill({"agent_type": "no_such_persona"}) == ""


# ────────────────────── 行为面：纠正 + 回锁 + 在办卡归属迁移 ──────────────────────

class _FakeStateStore:
    """只回放/记录事实的假会话存储（单测不连真实存储，`migao-dev-flow` §9.2）。"""

    def __init__(self, facts):
        self._facts = dict(facts or {})

    async def load(self, sid):
        return dict(self._facts)

    async def commit(self, sid, full):
        self._facts.update(full or {})
        return True


def _run_denied_order_turn(replies, *, skill, tool_names, facts, state_overrides=None):
    """驱动真实 `execute_skill` 的能力误宣纠正路径（真实工具注册表子集，不 mock 工具属性）。"""
    store = _FakeStateStore(facts)
    pending_calls = []

    def _msg(content):
        m = MagicMock(spec=None)  # AIMessage 语义只用到 content/tool_calls
        m.content = content
        m.tool_calls = []
        return m

    with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
         patch("app.memory.session_state_store.SessionStateStore", return_value=store), \
         patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
         patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
         patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
         patch("app.graph.skills.base_skill.LLMFactory") as llm_factory, \
         patch("app.graph.skills.base_skill.set_tool_context"), \
         patch("app.graph.skills.base_skill._execute_tool_safe") as exec_tool:
        # ⚠️ 用**真实** registry 子集（不是 MagicMock）：「有没有写工具」读的是工具注册表事实，
        # mock 出来会让判据失真（既有 `test_capability_denial_guard.py` 同一教训）。
        registry = _real_create_skill_registry(list(tool_names))
        create_reg.return_value = registry
        breaker = MagicMock()

        async def _pt(fn):
            return await fn()

        breaker.call = _pt
        get_breaker.return_value = breaker
        llm = MagicMock()
        llm.bind_tools.return_value = llm
        llm.ainvoke = AsyncMock(side_effect=[_msg(c) for c in replies])
        get_llm.return_value = llm
        llm_factory.create_skill_llm.return_value = llm
        exec_tool.return_value = (json.dumps({"success": True, "data": {}}),
                                  {"success": True, "data": {}})

        async def _set_pending(sid, name):
            pending_calls.append((sid, name))
            return True

        mem_cls.return_value.set_pending_skill = _set_pending
        state = {
            "messages": [HumanMessage(content="确认")],
            "tenant_id": 1, "user_id": 100, "session_id": "sess_or014",
            "role": "admin", "agent_type": "mibao",
            "pending_interact_skill": skill,
            "final_answer": "", "skill_used": "",
        }
        state.update(state_overrides or {})
        out = asyncio.run(base_skill.execute_skill(
            state=state, skill_name=skill, tool_names=list(tool_names),
            system_prompt="你是米宝"))
    return out, llm, pending_calls, store


class TestBEndDenialIsCorrectedAndRelocked:
    """商品线上自称"落不了单"：必须被纠正 → 回锁到**本 persona 的**下单 skill。"""

    DENIAL = OR014_DENIALS[0]
    OK = "好的，已为您转到订单流程落单，请稍候。"

    def test_denial_is_corrected_and_session_relocked_to_order(self):
        out, llm, pending, _ = _run_denied_order_turn(
            [self.DENIAL, self.OK], skill="product", tool_names=PRODUCT_TOOLS,
            facts=dict(GROUNDED_FACTS, last_card=CONFIRM_CARD, last_card_skill="product"))
        assert out["final_answer"] == self.OK, (
            f"B 端「落单属于订单环节」被原样发给用户：{out['final_answer']!r}")
        assert llm.ainvoke.await_count == 2, "没有发生纠正重答"
        owner = _flow_owner_skill({"agent_type": "mibao"})
        assert ("sess_or014", owner) in pending, (
            f"纠正后未把会话锁回 {owner!r} → 下一轮仍落不了单（恢复路径缺失）")

    def test_inflight_confirm_card_ownership_follows_the_flow(self):
        """**单独红证**：在办确认卡的归属标记必须随流程迁移。

        为什么必须（OR-014 乒乓形态）：下一轮的"答卡轮豁免"要求
        `last_card_skill == pending_interact_skill`。卡是在**漂错的那个 skill**（product）里发的，
        只回锁流程而不迁移卡归属 ⇒ 用户点这张卡时被判成"别的 skill 的卡" → L1 域逃逸再次
        把会话甩回 product → 回锁等于没修。
        """
        _, _, _, store = _run_denied_order_turn(
            [self.DENIAL, self.OK], skill="product", tool_names=PRODUCT_TOOLS,
            facts=dict(GROUNDED_FACTS, last_card=CONFIRM_CARD, last_card_skill="product"))
        owner = _flow_owner_skill({"agent_type": "mibao"})
        assert store._facts.get("last_card_skill") == owner, (
            "在办确认卡的归属未随流程迁移（下一轮答卡轮不豁免 → 被 L1 甩回 product）")
        assert store._facts.get("last_confirm_skill") == owner

    def test_choice_card_ownership_is_not_migrated(self):
        """反向锚点：choice/form 卡（商品上下架等选择器）语义上属于发卡 skill，不跟着迁。"""
        choice_card = {"component": "choice", "title": "请选择要下架的商品",
                       "options": [{"label": "遮光窗帘"}]}
        _, _, _, store = _run_denied_order_turn(
            [self.DENIAL, self.OK], skill="product", tool_names=PRODUCT_TOOLS,
            facts=dict(GROUNDED_FACTS, last_card=choice_card, last_card_skill="product"))
        assert store._facts.get("last_card_skill") == "product", (
            "非 confirm 卡的归属被误迁移 → 该卡自己的流程会被路由到别的 skill")

    def test_off_flow_denial_in_product_skill_is_not_corrected(self):
        """反面边界：不在办下单 → 商品线说"落不了单"**不得**被纠正（避免过度纠正）。"""
        out, llm, pending, _ = _run_denied_order_turn(
            [self.DENIAL], skill="product", tool_names=PRODUCT_TOOLS,
            facts={}, state_overrides={"pending_interact_skill": ""})
        assert out["final_answer"] == self.DENIAL
        assert llm.ainvoke.await_count == 1
        assert ("sess_or014", _flow_owner_skill({"agent_type": "mibao"})) not in pending, \
            "不在办下单却回锁了下单流程"


class TestCEndContractUnbroken:
    """C 端既有契约（#3477）：同一形态下回锁目标仍是 C 端下单 skill（换 derive 不换行为）。"""

    DENIAL = "亲，小布这边没有帮您下单的权限哦，需要您在小程序里操作"
    OK = "好嘞，我这就把商品加进订单，请稍等～"

    def test_customer_session_relocks_to_customer_owner(self):
        out, llm, pending, _ = _run_denied_order_turn(
            [self.DENIAL, self.OK], skill="customer_product", tool_names=PRODUCT_TOOLS,
            facts=dict(GROUNDED_FACTS), state_overrides={"role": "customer",
                                                         "agent_type": "xiaobu"})
        assert out["final_answer"] == self.OK
        assert llm.ainvoke.await_count == 2
        assert ("sess_or014", _flow_owner_skill({"agent_type": "xiaobu"})) in pending


# ────────────────────── 合法换域不得被牺牲（#3625 G3/T2 契约）──────────────────────

class TestLegitimateDomainSwitchStillWorks:
    """**红证**：在办订单流程 + 已接地商品 + 明确的新域诉求 → L1 域逃逸必须照旧生效。

    这一条是为了防止"为了让 OR-014 变绿而把逃逸一刀切关掉"（该族反复复发的根因）。
    退化演示：把 `route_by_intent` 的 L1 域逃逸分支删掉/全局禁用 → 本测试必红。
    """

    def _state(self, msg, **over):
        card = {"component": "choice", "title": "是否需要加工项？",
                "options": [{"label": "纳米圈打孔 · ¥9.5/米"}],
                "multiSelect": True, "multiSelectSkipLabel": "不需要加工项"}
        state = {
            "messages": [HumanMessage(content=msg)],
            "pending_interact_skill": "order",
            "last_card": card,
            "last_card_skill": "order",
            "route_decision": {"action": "route_with_hint"},
            "intent_result": {"intent": "product_inquiry", "confidence": 0.95,
                              "source": "rule"},
            "agent_type": "mibao",
            "tenant_id": 1,
            "session_id": "sess_or014_switch",
        }
        state.update(over)
        return state

    def test_explicit_product_action_still_switches_domain(self):
        msg = "改一下遮光窗帘的价格"
        l1 = RuleMatcher().match(msg)
        assert l1 is not None and l1.source == "rule" and l1.intent.value == "product_inquiry"
        state = self._state(msg, intent_result={"intent": l1.intent.value,
                                                "confidence": 0.95, "source": "rule"})
        assert route_by_intent(state) == "product", (
            "在办订单流程里明确的商品诉求被锁死在 order → #3625 G3/T2 契约回归")
        assert state["pending_interact_skill"] == "", "逃逸未释放会话锁"
