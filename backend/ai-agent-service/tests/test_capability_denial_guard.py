"""能力自我否定族守卫（#3389 / #3477 / #3443 / #3476，**复发 4 次**）—— 状态/事实驱动判据。

判据必须是「**在办流程状态 × 工具能力事实**」，不能是 skill 名字面量白名单：
四次复发的机制都是这一条 —— 要么"没把（新）skill 加进白名单"，要么"措辞/关键词一变即漏"。

本文件锁定三面：
  · **状态面**：顾客处于在办下单流程（跨轮 pending 锁 / 已接地商品 / 已校验下单参数）时，
    即使当前 skill 不是 `customer_order`、即使顾客这一轮**没有任何下单关键词**，
    「我做不了下单」也必须被纠正、以它为理由的转人工也必须被拦（#3477 的漏网形态）；
  · **措辞面**：隔词权限（「没有帮您下单的权限」）、做不到、帮不了您、无法帮您…、功能不可用
    等变体都要命中 —— 语义归一 + 结构化判据，**不再**靠"再加一条正则/词表特例"
    （旧正则在主体与否定词之间写死 `{0,8}` 窗口，插一个「这边」就漏）；
  · **边界面**：越权/第三方主体/顾客显式诉求**仍不得**被纠正（防"一律不否定"的过度纠正，
    先例 DF-020/DF-021 与 `check_false_inability` 的边界）。
  · **形状面（issue #4079 S4）**：`skill_name` 与**字符串字面量**比较 = 白名单复发的**形状**；
    判据扫**整个执行家族**（`app/graph/skills/execution/*.py`），fail-closed + 植入负例。
    为什么必须按形状（AST `Compare`）而不是某一种写法（`skill_name in (`）：S4 首轮审计就是
    按单一写法数出来的 ⇒ 只数到 2 处，实测按形状数是 **6 处**（`react_turn` 658/666/1048/1084、
    `finalize_turn` 89/206）。
"""
# case_ids: OR-021, OR-022, OR-025, AS-009, CH-013, CH-014, CH-015

import ast
import asyncio
import inspect
import json
import re
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from app.graph.skills.base_skill import (
    capability_denial_text_hit,
    _capability_denial_reason,
    _registry_has_confirm_write_tool,
    _order_write_tool_here,
    _order_capability_available,
    _handoff_guard_applies,
    create_skill_registry,
)
from app.graph.skills import base_skill


# ────────────────────── 措辞面：语义归一 ──────────────────────

class TestDenialPhrasingSemanticNormalization:
    """措辞变体不得漏（旧判据的漏配正是"措辞一变即失效"，issue #3477/#3476）。"""

    def test_no_subject_permission_form(self):
        """无主体前缀的权限话术（旧正则必须匹配到"我/小布/这边"才生效 → 直接漏）。"""
        assert capability_denial_text_hit("没有权限帮您下单")

    def test_long_insertion_between_subject_and_negation(self):
        """主体与否定词之间插入多个字（旧正则 `{0,8}` 窗口 → 超出即漏）。"""
        for t in ["非常抱歉，小布这边没有办法帮您直接下单哦",
                  "亲亲，小布这边暂时没有办法帮您提交订单呢",
                  "不好意思亲，小布这边暂时不能帮您下单哦"]:
            assert capability_denial_text_hit(t), f"未识别（长插入）: {t!r}"

    def test_interleaved_permission_forms(self):
        """隔词权限形态（#3477 C-A1 P1 原话的族）。"""
        for t in ["小布是智能客服，没有帮您下单的权限，需要您在小程序操作",
                  "亲，这边没有帮您提交订单的权限，我教您在小程序里下单吧",
                  "智能客服没有为您创建订单的权限，这个操作必须在小程序里完成"]:
            assert capability_denial_text_hit(t), f"未识别（隔词权限）: {t!r}"

    def test_capability_variant_phrasings(self):
        """任务点名的其余措辞形态：「做不到」「帮不了您」「无法帮您…」「功能不可用」。"""
        for t in ["我这边做不到帮您下单",
                  "这边帮不了您下单呢",
                  "小布这边无法帮您下单",
                  "抱歉，下单功能暂时不可用",
                  "不好意思，小布暂时不支持下单哦"]:
            assert capability_denial_text_hit(t), f"未识别（措辞变体）: {t!r}"

    def test_reason_covers_assist_avoidance_and_permission(self):
        """转人工理由（`reason`/`summary`）同样覆盖协助回避 + 权限形态。"""
        for why in ["顾客需要协助下单",
                    "客户请求协助下单（智能客服无下单权限）",
                    "小布没有下单权限",
                    "顾客需要人工协助完成下单",
                    "下单功能不可用，需人工介入"]:
            assert _capability_denial_reason({"reason": why}), f"未识别理由: {why!r}"

    def test_self_intro_and_success_not_flagged(self):
        for t in ["亲，我是小布，您的专属咨询客服～",
                  "已经帮您提交订单啦，订单号 20260914691810001",
                  "好的，我这就帮您下单",
                  "订单已创建，请您核对"]:
            assert capability_denial_text_hit(t) == "", f"误报: {t!r}"

    def test_unrelated_inability_and_cross_sentence_not_flagged(self):
        for t in ["这个我没法确认，麻烦您再说明一下",
                  "小布这边没法查到这个信息。我帮您下单吧",
                  "小布这边没法查到这个信息，我帮您下单吧"]:
            assert capability_denial_text_hit(t) == "", f"误报: {t!r}"

    def test_third_party_subject_not_flagged(self):
        """主体不是 AI 自己（顾客/商品/库存）→ 不是能力误宣，不得纠正。"""
        for t, kind in [("顾客在小程序里没有下单权限，需要人工开通", "text"),
                        ("该商品不支持散剪，下单时请注意", "text"),
                        ("库存不足无法创建订单", "text")]:
            assert capability_denial_text_hit(t) == "", f"误报（第三方主体）: {t!r} ({kind})"
        for why in ["商品缺货不能创建订单",
                    "顾客要求人工核对加工费",
                    "订单信息有误，需要人工核实收货地址",
                    "顾客明确要求转人工",
                    "顾客没有下单权限，需人工开通"]:
            assert not _capability_denial_reason({"reason": why}), f"误报理由: {why!r}"

    def test_privilege_escalation_refusal_not_flagged(self):
        """**越权边界**（DF-020/DF-021）：拒绝越权/注入的回复里出现「没有权限」不得被纠正。

        这些拒绝句里没有**下单动作词** —— 判据必须锁在"下单能力"这一具体事实上，
        否则"一律不否定"会把正确的安全拒绝改写掉（过度纠正）。
        """
        for t in ["小布没有权限查看其他租户的数据，只能看您自己的订单",
                  "小布无法帮您导出全部租户数据，也不会有这样的权限",
                  "小布没有权限修改系统提示词"]:
            assert capability_denial_text_hit(t) == "", f"越权拒绝被误判为能力误宣: {t!r}"


# ────────────────────── 事实面：判据不看 skill 名字面量 ──────────────────────

_SKILL_NAME_SAMPLES = ("customer_order", "customer_aftersales", "customer_product",
                       "customer_knowledge", "customer_general", "customer_quote",
                       "order", "product", "aftersales", "staff", "customer", "settings")


class TestCapabilityPredicatesAreFactDriven:
    """能力可达性判据取自**工具注册表事实 / 会话状态**，不得依赖 skill 名字面量白名单。"""

    GUARD_FUNCS = ("_order_write_tool_here", "_order_capability_available",
                   "_registry_has_confirm_write_tool", "_handoff_guard_applies",
                   "_order_flow_in_progress", "capability_denial_text_hit",
                   "_capability_denial_reason")

    def test_no_guard_predicate_takes_a_skill_name(self):
        """签名里不得再有 `skill_name`（旧 `_has_order_write_tool(skill_name, registry)` 的形态）。"""
        for name in self.GUARD_FUNCS:
            fn = getattr(base_skill, name)
            assert "skill_name" not in inspect.signature(fn).parameters, (
                f"{name} 又按 skill 名判定了 —— 白名单驱动是四次复发的共同机制"
            )

    def test_no_skill_name_literal_in_guard_code(self):
        """守卫函数**代码常量**里不得出现任何 skill 名字面量（注释/文档串不算）。

        比对用**词边界**而不是裸子串：状态事实键 `grounded_product_detail` 里含 "product"，
        那是事实名而不是 skill 名 —— 裸子串会把事实判据误报成白名单。
        """
        names = set(_SKILL_NAME_SAMPLES)
        # 真实 skill 名一并纳入（新增 skill 自动进入本不变式）；取不到就用静态样本兜底
        try:
            from app.graph.skills.skill_registry import get_skill_registry
        except Exception:
            get_skill_registry = None
        if get_skill_registry is not None:
            names |= set(get_skill_registry().get_names())
        offenders = []
        for name in self.GUARD_FUNCS:
            fn = getattr(base_skill, name)
            tree = ast.parse(inspect.getsource(fn))
            body = tree.body[0].body
            # 跳过函数自身的 docstring（说明历史是允许的，判定用字面量不允许）
            stmts = body[1:] if (body and isinstance(body[0], ast.Expr)
                                 and isinstance(body[0].value, ast.Constant)) else body
            for node in ast.walk(ast.Module(body=stmts, type_ignores=[])):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    for skill in names:
                        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(skill)}(?![A-Za-z0-9_])",
                                     node.value):
                            offenders.append(f"{name}: {skill!r} in {node.value!r}")
        assert not offenders, "守卫代码里出现 skill 名字面量（白名单复发形态）：\n" + "\n".join(offenders)

    def test_order_write_judgement_reads_tool_registry_only(self):
        """同一个 registry，不同 skill 名下判定必须一致（判据与 skill 名无关）。"""
        registry = MagicMock()
        registry.get_tool.side_effect = lambda n: object() if n == "order_create" else None
        assert _order_write_tool_here(registry) is True
        empty = MagicMock()
        empty.get_tool.side_effect = lambda n: None
        assert _order_write_tool_here(empty) is False

    def test_capability_needs_state_when_tool_not_local(self):
        """本 skill 没有写工具时，可达性 = **在办流程状态 × 全局工具能力**（两条缺一不可）。

        只按全局判（几乎恒真）会把越权/真不可达也放过；只按状态判会在工具根本没注册的
        环境里声称"你可以下单"。
        """
        empty = MagicMock()
        empty.get_tool.side_effect = lambda n: None
        with patch.object(base_skill, "_tool_registered_globally", return_value=True):
            assert _order_capability_available(empty, order_in_progress=False) is False
            assert _order_capability_available(empty, order_in_progress=True) is True
        with patch.object(base_skill, "_tool_registered_globally", return_value=False):
            assert _order_capability_available(empty, order_in_progress=True) is False

    def test_handoff_guard_applies_by_fact_not_by_name(self):
        """转人工守卫的适用性由三类事实决定（取代 `skill_name in (…)` 白名单）。"""
        empty = MagicMock()
        empty.get_tool.side_effect = lambda n: None
        empty.get_all_tools.return_value = []
        assert _handoff_guard_applies(empty, order_in_progress=False, denial_reason_hit="") is False
        assert _handoff_guard_applies(empty, order_in_progress=True, denial_reason_hit="") is True
        assert _handoff_guard_applies(empty, order_in_progress=False,
                                      denial_reason_hit="协助下单") is True

    def test_new_skill_with_write_tool_is_covered_automatically(self):
        """**L0 静态锁**：新增 skill 只要声明了「需确认写工具」，就自动落入守卫 —— 无需改白名单。

        这条断言的意图是让第 5 次复发**无法**以"只是没把新 skill 加进白名单"的方式发生：
        判据取自工具属性（destructive / requires_confirmation），不是 skill 名清单。
        """
        from app.graph.skills.skill_registry import get_skill_registry

        registry = get_skill_registry()
        configs = registry.get_all()
        assert configs, "skill 注册表为空 —— 不变式失去意义"
        covered = 0
        for cfg in configs:
            sub = create_skill_registry(list(cfg.tool_names))
            write_capable = any(
                getattr(t, "destructive", False) or getattr(t, "requires_confirmation", False)
                for t in sub.get_all_tools()
            )
            assert _registry_has_confirm_write_tool(sub) is write_capable, (
                f"skill {cfg.name} 的写工具事实判据与工具属性不一致"
            )
            if write_capable:
                covered += 1
                assert _handoff_guard_applies(sub, order_in_progress=False,
                                              denial_reason_hit=""), (
                    f"skill {cfg.name} 有需确认写工具却不在转人工守卫的适用范围内 —— "
                    f"白名单驱动复发（旧实现只认 customer_order/customer_aftersales）"
                )
        # 事实驱动的覆盖集必须是旧的二字面量白名单的**真超集**（否则说明判据退化了）
        assert covered > 2, "事实驱动覆盖的 skill 数不多于旧的二字面量白名单 → 判据疑似退化"
        # 合成一个"从没被任何白名单收录过"的 registry，同样必须被覆盖
        synth = create_skill_registry(["order_create", "human_handoff"])
        assert _handoff_guard_applies(synth, order_in_progress=False, denial_reason_hit=""), (
            "含 order_create 的（可能全新的）skill 未被守卫覆盖 —— 第 5 次复发缺口"
        )


# ────────────────────── 状态面：在办下单流程 ──────────────────────

class _FakeStateStore:
    """只回放事实的假会话存储（单测不连真实存储，见 tigao §9.2）。"""

    def __init__(self, facts):
        self._facts = facts or {}

    async def load(self, sid):
        return dict(self._facts)

    async def commit(self, sid, full):
        self._facts.update(full or {})
        return True


class TestOrderFlowInProgressIsStateDriven:
    """「顾客是否在办下单」必须由**状态**决定，不能由本轮措辞关键词决定（#3477 漏网机制）。"""

    def _run(self, facts, *, state=None, last_user_msg=""):
        with patch("app.memory.session_state_store.SessionStateStore",
                   return_value=_FakeStateStore(facts)):
            return asyncio.run(base_skill._order_flow_in_progress(
                "sess_001", state or {}, last_user_msg))

    def test_pending_lock_plus_grounded_is_in_progress_without_keywords(self):
        """#3477 形态：会话被 choice 卡锁在 customer_product + 已查过商品 → 在办。

        顾客这一轮可以说「好的，就按这个来」（**无任何下单关键词**）—— 旧判据
        （`_ORDER_INTENT_HINTS` × grounded）此时为假 → 守卫整段失效。
        """
        state = {"pending_interact_skill": "customer_product",
                 "messages": [HumanMessage(content="好的，就按这个来")]}
        assert self._run({"grounded_product_detail": {"product_id": "p1"}},
                         state=state, last_user_msg="好的，就按这个来") is True

    def test_validated_order_params_count_as_in_progress(self):
        """已校验过下单写参数 = 最强在办证据（连"查过商品"都不需要）。"""
        state = {"pending_interact_skill": "customer_order", "messages": []}
        facts = {"grounded_product_detail": None,
                 "pending_validated_input": {"target_tool": "order_create",
                                             "params": {"items": []}}}
        assert self._run(facts, state=state, last_user_msg="嗯") is True

    def test_not_in_progress_without_state_or_grounding(self):
        assert self._run({}, state={"messages": []}, last_user_msg="确认下单") is False
        assert self._run({"grounded_product_detail": {"product_id": "p1"}},
                         state={"messages": []}, last_user_msg="帮我查一下物流") is False


# ────────────────────── 行为面：跨 skill 的文本级纠正 ──────────────────────

def _run_text_guard(replies, *, skill, has_order_tool, facts, state_overrides=None):
    """驱动 `execute_skill` 的文本级能力误宣纠正路径（真实门禁接线，不测 mock）。"""
    sent = []

    async def fake_execute(tool, args, ctx, state):
        sent.append(tool.name)
        return (json.dumps({"success": True, "data": {}}), {"success": True, "data": {}})

    def _msg(content):
        m = MagicMock(spec=AIMessage)
        m.content = content
        m.tool_calls = []
        return m

    store = _FakeStateStore(facts)
    pending_calls = []

    with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
         patch("app.memory.session_state_store.SessionStateStore", return_value=store), \
         patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
         patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
         patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
         patch("app.graph.skills.base_skill.set_tool_context"), \
         patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute):
        registry = MagicMock()
        registry.get_langchain_tools.return_value = []
        registry.get_all_tools.return_value = []
        registry.get_tool.side_effect = lambda n: (
            object() if (n == "order_create" and has_order_tool) else None)
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

        async def _set_pending(sid, skill):
            pending_calls.append((sid, skill))
            return True

        mem_cls.return_value.set_pending_skill = _set_pending
        state = {
            "messages": [HumanMessage(content="好的，就按这个来")],
            "tenant_id": 1, "user_id": 100, "session_id": "sess_001",
            "agent_type": "xiaobu", "final_answer": "", "skill_used": "",
        }
        state.update(state_overrides or {})
        out = asyncio.run(base_skill.execute_skill(
            state=state, skill_name=skill, tool_names=["order_create"],
            system_prompt="你是小布"))
    return out, llm, sent, pending_calls


class TestTextDenialCorrectionCrossSkill:
    """#3477 形态：当前 skill 不是 customer_order，但顾客**在办下单** → 必须纠正（不得自我否定）。"""

    DENIAL = "亲，小布这边没有帮您下单的权限哦，需要您在小程序里操作"
    OK = "好嘞，我这就把商品加进订单，请稍等～"

    def test_corrected_when_order_flow_in_progress_in_other_skill(self):
        facts = {"grounded_product_detail": {"product_id": "p1"}}
        out, llm, _, pending = _run_text_guard(
            [self.DENIAL, self.OK], skill="customer_product", has_order_tool=False,
            facts=facts, state_overrides={"pending_interact_skill": "customer_product"})
        assert out["final_answer"] == self.OK, (
            f"在办下单流程里仍然把「没有帮您下单的权限」原样发给顾客：{out['final_answer']!r}"
        )
        assert llm.ainvoke.await_count == 2, "没有发生纠正重答"
        assert ("sess_001", "customer_order") in pending, (
            "纠正后未把会话锁回下单流程 → 下一轮无法真正落单（恢复路径缺失）"
        )

    def test_never_listed_skill_is_covered_too(self):
        """判据与 skill 名无关：编一个从没进过任何白名单的 skill 名，行为必须一致。"""
        facts = {"grounded_product_detail": {"product_id": "p1"}}
        out, llm, _, _ = _run_text_guard(
            [self.DENIAL, self.OK], skill="customer_zzz_never_whitelisted",
            has_order_tool=False, facts=facts,
            state_overrides={"pending_interact_skill": "customer_product"})
        assert out["final_answer"] == self.OK
        assert llm.ainvoke.await_count == 2

    def test_skill_owning_order_tool_is_corrected_even_off_flow(self):
        """工具就在手上（本 skill 子集含 order_create）→ 无论 skill 叫什么，否定都是假的。"""
        out, llm, _, _ = _run_text_guard(
            [self.DENIAL, self.OK], skill="customer_zzz_never_whitelisted",
            has_order_tool=True, facts={}, state_overrides={})
        assert out["final_answer"] == self.OK
        assert llm.ainvoke.await_count == 2

    def test_incapable_skill_off_flow_not_corrected(self):
        """**反面边界**：本 skill 真的没有下单工具、顾客也不在办下单 → 不能纠正（避免堵死正确行为）。"""
        out, llm, _, _ = _run_text_guard(
            [self.DENIAL], skill="customer_knowledge", has_order_tool=False, facts={},
            state_overrides={})
        assert out["final_answer"] == self.DENIAL
        assert llm.ainvoke.await_count == 1

    def test_privilege_refusal_off_flow_not_corrected(self):
        """越权拒绝（非下单动作）即使在办下单也不得被改写（DF-020/DF-021 边界）。"""
        refusal = "小布没有权限查看其他租户的数据，只能看您自己的订单"
        out, llm, _, _ = _run_text_guard(
            [refusal], skill="customer_product", has_order_tool=False,
            facts={"grounded_product_detail": {"product_id": "p1"}},
            state_overrides={"pending_interact_skill": "customer_product"})
        assert out["final_answer"] == refusal
        assert llm.ainvoke.await_count == 1


# ────────────────────── 行为面：跨 skill 的转人工拦截 ──────────────────────

def _run_handoff_guard(*, skill, reason, last_user_msg, facts, state_overrides=None,
                       tools=("human_handoff",)):
    sent = []

    async def fake_execute(tool, args, ctx, state):
        sent.append(tool.name)
        return (json.dumps({"success": True, "data": {}}), {"success": True, "data": {}})

    with patch("app.memory.session_state_store.SessionStateStore",
               return_value=_FakeStateStore(facts)), \
         patch("app.memory.session_memory.SessionMemory") as mem_cls, \
         patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
         patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
         patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
         patch("app.graph.skills.base_skill.LLMFactory") as llm_factory, \
         patch("app.graph.skills.base_skill.set_tool_context"), \
         patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute):
        # 用**真实工具实例**搭 registry 子集（不是假 MagicMock）：守卫的"有无写工具"
        # 判据读的是工具属性（destructive / requires_confirmation），mock 出来会失真。
        assert "human_handoff" in tools
        # ⚠️ 必须用**模块级导入的真函数**：此刻 `base_skill.create_skill_registry` 已被 patch，
        # 调它只会拿到 mock 的返回值（首版即此错，守卫判据失真为"没有写工具"）。
        registry = create_skill_registry(list(tools))
        create_reg.return_value = registry
        breaker = MagicMock()

        async def _pt(fn):
            return await fn()

        breaker.call = _pt
        get_breaker.return_value = breaker
        call = MagicMock(spec=AIMessage)
        call.content = ""
        call.tool_calls = [{"name": "human_handoff", "args": {"reason": reason}, "id": "h1"}]
        final = MagicMock(spec=AIMessage)
        final.content = "好的"
        final.tool_calls = []
        llm = MagicMock()
        llm.bind_tools.return_value = llm
        llm.ainvoke = AsyncMock(side_effect=[call, final])
        get_llm.return_value = llm
        # 真实 registry 带 langchain 工具时，代码会另建"关闭思考"的 LLM（真网络客户端）→ 一并 mock
        llm_factory.create_skill_llm.return_value = llm
        mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)
        state = {
            "messages": [HumanMessage(content=last_user_msg)],
            "tenant_id": 1, "user_id": 100, "session_id": "sess_001",
            "agent_type": "xiaobu", "final_answer": "", "skill_used": "",
        }
        state.update(state_overrides or {})
        result = asyncio.run(base_skill.execute_skill(
            state=state, skill_name=skill, tool_names=list(tools), system_prompt="你是小布"))
    return result, sent


class TestHandoffGuardCrossSkill:
    """转人工守卫的适用性由状态/事实决定 —— 不再只认两个字面量 skill 名（#3477 机制 2）。"""

    def test_blocks_handoff_in_other_skill_when_order_flow_in_progress(self):
        """顾客在办下单（**本轮无下单关键词**）+ 中性理由 → 仍不得无信号转人工。"""
        result, sent = _run_handoff_guard(
            skill="customer_knowledge", reason="顾客需要人工服务",
            last_user_msg="好的，就按这个来",
            facts={"grounded_product_detail": {"product_id": "p1"}},
            state_overrides={"pending_interact_skill": "customer_product"})
        assert "handoff_blocked" in str(result), (
            "在办下单流程里跨 skill 的无信号转人工被放行 —— C-A1 P1 形态（#3477）"
        )
        assert "human_handoff" not in sent, "被拦截时不得真正执行转人工"

    def test_never_listed_skill_is_covered_too(self):
        result, sent = _run_handoff_guard(
            skill="customer_zzz_never_whitelisted", reason="顾客需要人工服务",
            last_user_msg="好的，就按这个来",
            facts={"grounded_product_detail": {"product_id": "p1"}},
            state_overrides={"pending_interact_skill": "customer_product"})
        assert "handoff_blocked" in str(result)
        assert "human_handoff" not in sent

    def test_business_skill_with_write_tool_covered_by_fact(self):
        """有「需确认写工具」的业务办理 skill（**非**旧白名单里的名字）→ 在办流程中无信号转人工仍被拦。

        形态即 CH-012：会话锁在一张待办卡上（`pending_interact_skill`）、顾客这条消息既没
        要求人工也没情绪 → 模型直接转人工 = 放弃流程。旧实现靠
        `skill_name in ("customer_order", "customer_aftersales")` 放行这个 skill 名，
        新实现靠**工具属性事实**（本 skill 有 destructive / requires_confirmation 写工具）。
        """
        result, sent = _run_handoff_guard(
            skill="customer_product", reason="顾客需要人工服务",
            last_user_msg="窗户是 2 米宽 1.8 米高",
            facts={}, state_overrides={"pending_interact_skill": "customer_product"},
            tools=("order_create", "human_handoff"))
        assert "handoff_blocked" in str(result), (
            "有写工具的 skill 在办流程中被放行无信号转人工（白名单等价物缺失）"
        )
        assert "human_handoff" not in sent

    def test_explicit_human_request_still_allowed(self):
        """越权/真实诉求边界：顾客**显式**要求人工（即使正在下单）→ 必须放行。"""
        result, sent = _run_handoff_guard(
            skill="customer_knowledge", reason="顾客要求转人工",
            last_user_msg="别下单了，我要转人工",
            facts={"grounded_product_detail": {"product_id": "p1"}},
            state_overrides={"pending_interact_skill": "customer_product"})
        assert "handoff_blocked" not in str(result), "顾客显式要求人工却被拦 —— 真实诉求被堵死"
        assert "human_handoff" in sent

    def test_out_of_scope_request_still_allowed(self):
        """能力外诉求（赔偿/法律）→ 转人工是正确行为，不得被守卫误拦。"""
        result, sent = _run_handoff_guard(
            skill="customer_knowledge", reason="顾客要求赔偿",
            last_user_msg="我要起诉你们，要求三倍赔偿",
            facts={"grounded_product_detail": {"product_id": "p1"}},
            state_overrides={"pending_interact_skill": "customer_product"})
        assert "handoff_blocked" not in str(result)
        assert "human_handoff" in sent


# ────────────────────── 形状面：执行家族的写路径不得按 skill 名判定（#4079 S4）──────────────────────
#
# 病灶（与上面「事实面」同族，只是位置在**执行家族**而不是 `base_skill` 的判据函数里）：
# 生成该缺陷的机制是"**按 skill 名判定**"，它在 S3 拆分后散落在 `execution/*.py` 的循环体
# 与收尾逻辑里（例如 `_run_one_tool` 的下单接地闸门、模式 C 加工项兜底、8.3b/8.6 收尾）——
# 旧判据 `test_no_skill_name_literal_in_guard_code` 只扫 `GUARD_FUNCS` 名单内的函数，
# 这些位置**从未被覆盖**（判据自己选择沉默）。
#
# 本节的判据按**形状**写：`skill_name` 与**字符串字面量**的任何比较（`==` / `!=` / `in` /
# `not in`）= 白名单形态。注释与 docstring（`ast.Constant` 但不在 `Compare` 里）不算 ——
# 说明历史是允许的，判定用字面量不允许。
#
# ## 适用域声明（本判据对谁生效 / 对谁不生效）
#   · 覆盖：`app/graph/skills/execution/*.py` 里**内联字符串字面量**与 `skill_name` 的比较；
#   · 不覆盖 ①：**命名常量集合**（`base_skill.CREATION_SKILL_NAMES`）—— 它是"多轮引导写流程"
#     的**产品分类**（settings/data/general 有需确认写工具但**不在**该集合里），改判成
#     "有需确认写工具"会连带改变这三个 skill 的跨轮锁定行为（**行为不等价**）；该分类由
#     `tests/test_graph_skills.py` 的 should_lock / over_locked 不变式机械锁定，故如实登记为边界；
#   · 不覆盖 ②：`base_skill.py` 的 `GUARD_FUNCS`（由既有
#     `test_no_skill_name_literal_in_guard_code` 覆盖；本节只补一条"不误报"的负例）；
#   · fail-closed：执行家庭目录/文件缺失、或整个家族里再也搜不到 `skill_name` 这个变量
#     ⇒ **报错**（判据失去被扫对象时不得静默通过）。

EXECUTION_DIR = Path(__file__).resolve().parents[1] / "app" / "graph" / "skills" / "execution"
_SKILL_NAME_VAR = "skill_name"


def _string_constants(node: ast.AST) -> list:
    """比较对象里的**字符串字面量**（含元组/集合/列表形态）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.Set, ast.List)):
        return [e.value for e in node.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _skill_name_literal_offenders(sources: dict) -> list:
    """`{标签: 源码}` 里所有「`skill_name` 与字符串字面量比较」的位置（纯函数，可喂夹具）。

    抽成纯函数是为了能喂**植入违规的负例**（证明它真的会红），而不是只能靠改真代码才红。
    """
    offenders: list = []
    for label, src in sources.items():
        tree = ast.parse(src, filename=label)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            for i, operand in enumerate(operands):
                if not (isinstance(operand, ast.Name) and operand.id == _SKILL_NAME_VAR):
                    continue
                for j, other in enumerate(operands):
                    if i == j:
                        continue
                    for literal in _string_constants(other):
                        offenders.append(
                            f"{label}: 第 {node.lineno} 行  "
                            f"`{_SKILL_NAME_VAR}` 与字面量 {literal!r} 比较"
                        )
    return offenders


def _execution_family_sources() -> dict:
    """执行家族源码（fail-closed：目录/文件缺失即报错，不给"扫不到就通过"留口子）。"""
    assert EXECUTION_DIR.is_dir(), (
        f"执行家族目录不存在：{EXECUTION_DIR}（fail-closed，不静默跳过）"
    )
    files = sorted(EXECUTION_DIR.glob("*.py"))
    assert len(files) >= 3, (
        f"{EXECUTION_DIR} 下的实现文件少于 3 个（实得 {[p.name for p in files]}）—— "
        f"清扫范围会静默漏掉搬走的判定"
    )
    return {f"execution/{p.name}": p.read_text(encoding="utf-8") for p in files}


class TestNoSkillNameLiteralInExecutionWritePaths:
    """判据从 `GUARD_FUNCS` 名单扩到**执行家族的写路径**（#4079 S4 的落地判据）。"""

    def test_no_skill_name_literal_in_execution_family(self):
        """真实执行家族里**零**「`skill_name` 与字面量比较」——新增一处即红。

        红证（改前实测，按 AST 形状数）：`react_turn.py` 第 658/666/1048/1084 行、
        `finalize_turn.py` 第 89/206 行，共 **6 处**（按 `skill_name in (` 单写法只数得到 2 处）。
        """
        sources = _execution_family_sources()

        # fail-closed：判据的被扫对象必须真的存在（否则本用例是"永远绿的空判据"）
        name_uses = sum(
            1 for src in sources.values()
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Name) and node.id == _SKILL_NAME_VAR
        )
        assert name_uses > 0, (
            f"整个执行家族里搜不到 `{_SKILL_NAME_VAR}` —— 判据失去被扫对象"
            f"（改名/搬走即须同步本判据，不得静默通过）"
        )

        offenders = _skill_name_literal_offenders(sources)
        assert not offenders, (
            "执行家族的写路径里出现 `skill_name` 与字符串字面量比较 = **skill 名白名单复发**：\n  "
            + "\n  ".join(offenders)
            + "\n→ 判据必须取自**事实/状态**（本文件上面的 `_order_write_tool_here` / "
              "`_registry_has_confirm_write_tool` / `_registry_has_tool` / `_is_customer_role` 族），"
              "否则新增 skill 时这条判定会静默失效（#3389→#3477→#3443→#3476→#4079 的五次复发机制）"
        )

    def test_guard_fires_on_planted_literal_and_stays_green_on_clean_source(self):
        """**植入违规的负例**：判据真的会红，且对干净源码/文档串不误报（不是恒红空判据）。"""
        planted = {
            "execution/fake_react_turn.py": (
                "def _run_one_tool(skill_name, tool_name):\n"
                "    if tool_name == 'order_create' and skill_name in ('customer_order', 'order'):\n"
                "        return True\n"
                "    return skill_name == 'product'\n"
            ),
        }
        hits = _skill_name_literal_offenders(planted)
        assert hits, "植入 `skill_name in ('customer_order', 'order')` 后判据仍不报 —— 这是空判据"
        assert any("customer_order" in h for h in hits) and any("'product'" in h for h in hits), (
            f"植入的两种形态（in 元组 / == 单品）没有都被抓到：{hits}"
        )

        clean = {
            "execution/clean.py": (
                '"""旧实现是 `skill_name in ("customer_order", "order")` 白名单（说明允许）。"""\n'
                "def _run_one_tool(skill_name, registry, state):\n"
                "    # 注释里提到 skill_name == 'product' 也不算（注释不进 AST 常量比较）\n"
                "    return _order_write_tool_here(registry) and _is_customer_role(state)\n"
            ),
        }
        assert _skill_name_literal_offenders(clean) == [], (
            "干净源码（含文档串/注释里的历史说明）被误报 —— 判据把说明当成了判定"
        )
        assert _skill_name_literal_offenders({}) == [], "空输入不得报错以外的任何结论"

    def test_existing_guard_funcs_are_not_flagged(self):
        """R2 阴性负例：既有 `GUARD_FUNCS` 不被本判据误报（它们的 docstring 里有历史字面量）。"""
        sources = {
            name: inspect.getsource(getattr(base_skill, name))
            for name in TestCapabilityPredicatesAreFactDriven.GUARD_FUNCS
        }
        # 前提断言（防"空扫"）：确实有 docstring 里写着旧白名单的字面量
        assert any("customer_order" in src for src in sources.values()), (
            "GUARD_FUNCS 的说明串里找不到旧白名单字面量 —— 本负例失去意义（可能被清理过）"
        )
        assert _skill_name_literal_offenders(sources) == [], (
            "既有守卫函数被误报（把 docstring 里的历史说明当成判定）—— 误红即坏断言"
        )
