# case_ids: AG-008, PR-026, PR-027
"""下单域守卫 × 图片/海报域的**域隔离** + 「用户显式撤回」解锁（issue #7758）。

## 生产实证（sess_cf885dc3ef40435a，2026-10-25 15:41–15:50 +08，tenant 46）

会话在做**营销海报**，第 5 轮起连续 3 轮改口成下单话术（问配色/门幅/米数/收货人），
用户 15:48:24 明确说「我不是要下单，我要更新商品」后仍在订单流里打转。落库状态：
`session_states.pending_skill = order`、`_current_domain = order`、`_stale_domains = [product]`。

用库中原文跑真实判据（零 LLM）复现出**一条误锁链**：

  15:43:34 的回复（**海报卡**能力边界，当时是正确回复）：
      「**海报卡的能力是固定的**…一张商品档案里的**主图** + 商品名 + 价格…我这边**改不了排版**…」
  修前 `capability_denial_text_hit(...)` -> '我这边**改不了排版'（= 下单域守卫命中）
  修前 `_product_image_denial_hit(...)`   -> '我这边**改不了排版'（= 图片域守卫命中）

⇒ `react_turn` 的下单域块把它当成「下单能力误宣」：`_order_flow_in_progress` 为真（已查过商品详情 +
流程仍锁定）⇒ `_relock_order_skill` 把会话锁到 `order` + 注入
`_TEXT_DENIAL_CORRECTIVE_MIDORDER`（"缺信息就问缺的那一项"）⇒ 下一轮直接问下单规格。

三段缺陷各自可独立判红（本文件逐段锁住）：

  · **D1 域串味**：下单域判据不得吞掉图片/海报域的能力边界陈述（两个域各有自己的守卫与纠正方向）；
  · **D2 跨小句过宽**：图片域的「整段锚点 + 任意 `V不了`」会把**排版/版式/模板/字体/配色**这类
    非图片对象算成图片能力否定；
  · **D3/D4 撤回不生效、误锁无出口**：`_has_ordering_intent('我不是要下单…')` 因**子串**命中返回真
    ⇒ 守卫继续上膛；且误锁的 `pending_skill` 每轮被 `finalize_turn` 写回 ⇒ 会话**一直**粘在订单流。

判据一律**零 LLM、零真库**（假 store 回放事实），红/绿只由判据本身决定。
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import HumanMessage

from app.graph.skills import base_skill
from app.graph.skills.base_skill import (
    _is_ordering_withdrawal,
    _order_flow_in_progress,
    _product_image_denial_hit,
    capability_denial_text_hit,
)

# 15:43:34 生产原文（**逐字**取自 session_messages；海报卡能力边界 + 图片上传边界，都不是能力误宣）
POSTER_BOUNDARY = (
    "这得先跟您说清楚边界，免得来回折腾 🙏\n\n**海报卡的能力是固定的**：一张商品档案里的**主图** + "
    "商品名 + 价格 + 单位 + 您确认的文案，版式由系统模板渲染，我这边**改不了排版、加不了多图拼贴、"
    "调不了配色和字体**。所以「更精美」「多放几张商品图」这类设计向的要求，我做不到，也不会假装能做。"
    "\n\n能帮您补的是**图源**，两件事：\n\n1. **我可以按这个商品逐张生成商品图**：主图 / 材质细节 / "
    "工艺细节 / 场景效果（每次出 1 张，1440×1440，您可下载或长按保存），拿去设计工具里拼版正好；\n"
    "2. **商品档案里补更多实拍图**：这个得在后台「商品管理」页编辑商品时上传，我这边没有上传/改图能力。"
    "\n\n精美排版建议走专业设计工具（Canva、稿定之类），把文案和商品图拖进去做，比系统模板自由得多。"
    "\n\n您想先出哪张图？刚才这轮没成功，请您再说一次，我继续为您办理。"
)

# #5318 的四条图片域拒绝原文（**真话**：图片写能力确实不在黄金策手上 ⇒ 图片域守卫必须照旧命中）
IMAGE_DENIALS = [
    "我这个商品管理入口只能改价格、名称、描述、状态、回补库存开关这些字段，不包含图片上传",
    "您上传的这张色卡图我这边拿不到可写入的地址，所以没法代劳",
    "抱歉，这个入口不能设置主图，图片上传功能不在我的能力范围内",
    "抱歉，我这边没法设置主图，只能请您去后台操作",
]

# OR-014 的 5 句下单域能力误宣（**假话**：order_create 就在全局工具表里 ⇒ 必须照旧命中）
ORDER_DENIALS = [
    "非常抱歉，元元这边没有办法帮您直接下单哦",
    "没有权限帮您下单",
    "抱歉，下单功能暂时不可用",
    "元宝这边帮不了您下单呢",
    "元宝暂时不支持下单哦",
]


class TestDenialDomainIsolation:
    """D1：两个域的能力判据**互不吞并**（下单域守卫不得把图片/海报边界当自己的命中）。"""

    def test_production_poster_boundary_is_not_an_order_denial(self):
        hit = capability_denial_text_hit(POSTER_BOUNDARY)
        assert hit == "", (
            f"海报卡的能力边界被下单域守卫当成了「下单能力误宣」：{hit!r}\n"
            f"⇒ react_turn 会把会话 relock 到 order（sess_cf885dc3ef40435a 的真实成因）"
        )

    def test_layout_clause_is_not_read_as_an_image_denial(self):
        """整段有「主图」锚点，但**排版**那一句不得被算成图片能力否定（15:43:34 生产原文）。

        修前命中的是「我这边**改不了排版」（= 跨小句裸 `V不了` + 整段锚点）；
        修后命中的只能是真正的图片能力句（「我这边没有上传/改图能力」）。
        """
        hit = _product_image_denial_hit(POSTER_BOUNDARY)
        assert "排版" not in hit, (
            f"「改不了排版」（海报模板排版，与图片上传无关）被图片域判据命中：{hit!r}")

    def test_image_denials_belong_to_image_domain_only(self):
        for text in IMAGE_DENIALS:
            assert _product_image_denial_hit(text), f"图片域判据漏配（回归）: {text!r}"
            assert capability_denial_text_hit(text) == "", (
                f"图片域拒绝被下单域守卫吞并 → 会把会话锁到 order 并改写成下单话术: {text!r}"
            )

    def test_order_denials_still_hit(self):
        """正对照：真·下单能力误宣一条都不许因为域隔离而漏（OR-014 族）。"""
        for text in ORDER_DENIALS:
            assert capability_denial_text_hit(text), f"下单域判据回归: {text!r}"

    @pytest.mark.parametrize("text", [
        # 整段有图片锚点（主图），但「做不了」的宾语是**排版/版式/模板/字体/配色**
        "海报里放的是商品主图，我这边改不了排版",
        "商品主图是有的，但版式我这边调不了，只能按模板出",
        "主图已经用上了，字体和配色我这边改不了",
        "商品图我给你换成主图，海报的拼图我这边加不了",
        # 文案面（#7512 已裁定：文案必须用户给，AI 不代写）
        "海报主图我能出，文案我不能替您写",
    ])
    def test_layout_and_copy_boundaries_are_not_image_denials(self, text):
        assert _product_image_denial_hit(text) == "", (
            f"非图片对象（排版/版式/字体/配色/拼图/文案）被算成图片能力否定: {text!r}"
        )

    def test_cross_clause_capability_negation_still_hit(self):
        """正对照：跨小句的**能力资源否定**形态（没有…能力/工具/通道）继续命中（#3938 不许回退）。"""
        for text in [
            "改商品图片属于商品编辑操作，我这边没有这个能力",
            "更换商品主图属于商品管理模块的写操作，我这边没有对应的执行工具，没法直接帮您",
            "改图这块属于商品编辑，我这边没有图片上传的通道",
        ]:
            assert _product_image_denial_hit(text), f"跨小句能力否定漏配（回归）: {text!r}"


class TestOrderingWithdrawal:
    """D3：用户**显式撤回**下单 —— 否定词 × 下单动作锚点（不是子串命中）。"""

    @pytest.mark.parametrize("text", [
        "我不是要下单，我要更新商品",   # 本单的生产原文（15:48:24）
        "先不下单了",
        "别落单了，我只是问问",
        "不用结算了，先看看别的",
    ])
    def test_withdrawal_detected(self, text):
        assert _is_ordering_withdrawal(text), f"显式撤回未识别: {text!r}"

    @pytest.mark.parametrize("text", [
        "确认下单", "我要下单", "帮我下单吧", "下单", "就按这个来",
        "帮我把这单下一下", "付款方式有哪些",
    ])
    def test_normal_ordering_is_not_withdrawal(self, text):
        assert not _is_ordering_withdrawal(text), f"正向下单措辞被误判成撤回: {text!r}"


class _FakeStateStore:
    """只回放事实的假会话存储（单测不连真实存储）。"""

    def __init__(self, facts):
        self._facts = facts or {}

    async def load(self, sid):
        return dict(self._facts)

    async def commit(self, sid, full):
        self._facts.update(full or {})
        return True


class TestOrderFlowInProgressRespectsWithdrawal:
    """D4a：撤回是**比状态更高优先级**的用户信号（不削弱 #3477 的「状态优先」）。"""

    def _run(self, facts, *, state=None, last_user_msg=""):
        with patch("app.memory.session_state_store.SessionStateStore",
                   return_value=_FakeStateStore(facts)):
            return asyncio.run(base_skill._order_flow_in_progress(
                "sess_001", state or {}, last_user_msg))

    def test_withdrawal_beats_in_progress_state(self):
        state = {"pending_interact_skill": "order",
                 "messages": [HumanMessage(content="我不是要下单，我要更新商品")]}
        facts = {"grounded_product_detail": {"product_id": "p1"}}
        assert self._run(facts, state=state,
                         last_user_msg="我不是要下单，我要更新商品") is False, (
            "用户已经撤回下单，判据仍为真 ⇒ 下单守卫继续上膛、会话锁不回"

        )

    def test_positive_rephrase_still_in_progress(self):
        """#3477 正对照：正向改述（无下单关键词）仍由**状态**兜底为在办。"""
        state = {"pending_interact_skill": "customer_product",
                 "messages": [HumanMessage(content="好的，就按这个来")]}
        facts = {"grounded_product_detail": {"product_id": "p1"}}
        assert self._run(facts, state=state, last_user_msg="好的，就按这个来") is True


def _routing_state(message, *, pending="order", intent="product_inquiry"):
    return {
        "messages": [HumanMessage(content=message)],
        "tenant_id": 1, "user_id": 100, "session_id": "sess_001",
        "agent_type": "mibao",
        "route_decision": {"action": "full_agent"},
        "intent_result": {"intent": intent, "source": "rule"},
        "pending_interact_skill": pending,
        "final_answer": "", "skill_used": "",
    }


class TestRoutingUnlocksOnWithdrawal:
    """D4b：撤回必须能**离开**下单 skill（否则路由每轮都回 order）。"""

    def test_withdrawal_leaves_order_skill(self):
        from app.graph.nodes import route_by_intent
        state = _routing_state("我不是要下单，我要更新商品")
        route = route_by_intent(state)
        assert route != "order", (
            f"pending=order + 用户显式撤回，路由仍回 order ⇒ 会话永远出不来（拿到 {route!r}）"
        )
        assert state.get("pending_interact_skill") == "", "撤回轮没有清掉会话锁"

    def test_positive_confirmation_stays_in_order_skill(self):
        """既有契约（#3361/#3557）：正向确认轮必须原样回到 pending skill。"""
        from app.graph.nodes import route_by_intent
        state = _routing_state("确认下单")
        assert route_by_intent(state) == "order"


class TestPendingLockReleasedOnWithdrawal:
    """D4c：`finalize_turn` 每轮会把 pending 写回当前 skill ⇒ 撤回轮必须清锁。"""

    def _run_release(self, state):
        calls = []

        async def _set(sid, skill):
            calls.append((sid, skill))
            return True

        with patch("app.memory.session_memory.SessionMemory") as mem_cls:
            mem_cls.return_value.set_pending_skill = _set
            ok = asyncio.run(
                base_skill._release_order_lock_on_withdrawal("sess_001", state))
        return ok, calls

    def test_release_clears_pending(self):
        ok, calls = self._run_release({"ordering_withdrawn": True,
                                       "pending_interact_skill": "order"})
        assert ok is True
        assert calls == [("sess_001", None)], f"没有清除跨轮下单锁：{calls}"

    def test_release_is_noop_without_withdrawal(self):
        ok, calls = self._run_release({"pending_interact_skill": "order"})
        assert ok is False
        assert calls == [], "非撤回轮不得动 pending 锁"

    def test_finalize_turn_is_wired_to_release(self):
        """接线判据：解锁必须真的挂在 `finalize_turn` 的跨轮持久化段（不是只写了个函数）。"""
        src = Path(base_skill.__file__).with_name("execution").joinpath(
            "finalize_turn.py").read_text(encoding="utf-8")
        assert "_release_order_lock_on_withdrawal" in src, (
            "finalize_turn 没有调用解锁函数 ⇒ pending_skill 每轮照旧写回 order，会话仍会「一直」乱回复"
        )
        assert re.search(r"ordering_withdrawn", src), (
            "finalize_turn 没有读 `ordering_withdrawn` 标志"
        )
