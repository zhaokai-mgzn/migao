# case_ids: OR-015, OR-016, OR-017, AS-003, PR-007
"""答卡轮域保持（#3557 G1 家族扩展）：本 skill 自己发的**任意卡型**的答卡轮不得被换域。

## 证据（run 34841029062 · SHA `1b3d2f2a` · job `103965821637`，原文）

| 轮 | 输入 | 工具 | agent 原文 |
|---|---|---|---|
| OR-015 R3 | （agent 发 `interact(choice, multiSelect, prefix=已选加工项：)` 卡） | … | 「是否需要加工项？（可多选…）」 |
| OR-015 R4 | `已选加工项：纳米圈打孔 · ¥9.5/米` | **`tools=-`** | 「**下单属于订单模块的操作，我当前这边承接的…**」 |
| OR-015 R5 | `确认` | **`tools=-`** | 「**我承接的是商品侧的工作**」 |
| OR-016 R2 | `不需要加工项` | **`tools=-`** | 「订单创建属于**订单模块**的活儿，我这边是…」（R3「确认下单」才恢复） |

同一 run、同一独立栈里 OR-010/OR-011/OR-009/OR-016/OR-028 **都成功调用了 `order_create`**
⇒ 能力事实可达，这里是**假能力否定**。

## 零 LLM 探针实测（本文件 `test_probe_*` 把它钉住）

```
RuleMatcher().match("已选加工项：纳米圈打孔 · ¥9.5/米")
  → product_inquiry  conf=0.95  kw=['加工项']            # rule_matcher.py:41 关键词表
RuleMatcher().match("不需要加工项")
  → product_inquiry  conf=0.95  kw=['加工项']
_intent_to_route_key("product_inquiry","mibao") → "product"
```

链路（改前）：R4 输入含「加工项」→ L1 判 `product_inquiry` → `source=="rule"` →
`route_by_intent` 的「L1 高置信域切换」逃逸（#3625 G3/T2）判定 `product != order`
→ **清掉 order 的会话锁** → 落到 `product_skill`（`PRODUCT_TOOLS` **没有** `order_create`）
→ 模型零工具可用，只能自称「我承接的是商品侧的工作」。R5 沿用被污染的锁 → 同签名。

## 为什么 #3625 / #3677 都没覆盖这条路径（本文件同时锁住这两个契约）

* **#3625**（`8fe99ee4`）引入的正是这条 L1 域逃逸（`nodes.py` 的 `_rule_domain` 分支）——
  它治的是「L1 已高置信判到商品动作、却被 order 锁困住」的反方向，**没有把"卡值/流程内措辞
  命中 L1 关键词"与"用户真的换话题"区分开**。
* **#3677**（`2e1c5094`）补了答卡轮豁免，但判据 `_is_card_confirm_round` 要求
  `last_confirm_skill == pending_interact_skill` **且逐字等于 `last_confirm_value`**，
  而这两个字段**只在 `component == "confirm"` 时落库**（`base_skill.py` interact 成功分支）
  ⇒ **choice / form 卡的答卡轮根本不在射程内**（OR-015 R4 答的是 multiSelect **choice** 卡）。
"""

import pytest
from langchain_core.messages import HumanMessage
from unittest.mock import patch

from app.graph.nodes import (
    _CARD_CONFIRM_INTENT_SOURCE,
    _is_card_answer_round,
    intent_router_node,
    route_by_intent,
)
from app.graph.skills.order_skill import ORDER_TOOLS
from app.graph.skills.product_skill import PRODUCT_TOOLS
from app.router.intent_config import IntentResult, RouteDecision
from app.router.rule_matcher import RuleMatcher

# ── 真实卡片载荷（形状照 `app/tools/interact.py` 的 interactive_data）──
# OR-015 R3 / OR-016 R1：订单 skill 发的加工项多选卡。
PROCESSING_ITEM_CARD = {
    "component": "choice",
    "title": "是否需要加工项？（可多选，不需要请点「不需要加工项」）",
    "options": [
        {"label": "纳米圈打孔 · ¥9.5/米", "value": "proc_item_pi_eval_punch"},
        {"label": "韩式波浪折边 · ¥12/米", "value": "proc_item_pi_eval_wave"},
    ],
    "multiSelect": True,
    "multiSelectSubmitPrefix": "已选加工项：",
    "multiSelectSubmitLabel": "完成选择",
    "multiSelectSkipLabel": "不需要加工项",
}
ORDER_ANSWER_R4 = "已选加工项：纳米圈打孔 · ¥9.5/米"
ORDER_ANSWER_R5 = "确认"


def _l1(msg: str) -> IntentResult:
    """真实 L1 结果（不 mock 规则表——探针数值就是要被钉住的被测事实）。

    未命中 = **本用例自己的前提写错了**（不是"跳过"）→ 显式前提失败 `pytest.fail`
    （不用 `assert is not None`：那是存在性弱断言，会被 QA Growth Gate 的
    `--check-weak` 判为凑数断言，见 `.github/growth_gate.py:_WEAK_PATTERNS`）。
    """
    result = RuleMatcher().match(msg)
    if result is None:
        pytest.fail(f"L1 未命中 {msg!r}，本用例的缺陷前提不成立")
    return result


def _state(msg: str, *, pending: str, card: dict | None, card_skill: str) -> dict:
    return {
        "messages": [HumanMessage(content=msg)],
        "pending_interact_skill": pending,
        "last_card_skill": card_skill,
        "last_card": card or {},
        "route_decision": {"action": "route_with_hint"},
        "intent_result": {"intent": "product_inquiry", "confidence": 0.95, "source": "rule"},
        "agent_type": "mibao",
        "tenant_id": 1,
        "session_id": "sess_b1_answer_round",
    }


class TestProbeL1Misfire:
    """缺陷前提探针：这两句中的「加工项」是 L1 的商品域关键词（rule_matcher.py:41）。"""

    @pytest.mark.parametrize("msg", [ORDER_ANSWER_R4, "不需要加工项"])
    def test_processing_item_answer_is_l1_product_inquiry(self, msg):
        result = _l1(msg)
        assert result.intent.value == "product_inquiry"
        assert result.confidence == 0.95
        assert "加工项" in result.matched_keywords
        assert result.source == "rule"

    def test_product_skill_has_no_order_create(self):
        """危害判据：落到 product skill = 无论怎么写都拿不到 order_create。"""
        assert "order_create" not in PRODUCT_TOOLS
        assert "order_create" in ORDER_TOOLS


class TestCardAnswerRoundStaysInOwnSkill:
    """正例：本 skill 自己发的 choice / form 卡的答卡轮 → 必须留在本 skill。"""

    def test_or015_r4_choice_answer_keeps_order_lock(self):
        """OR-015 R4（run 34841029062）：答 multiSelect choice 卡 → 不得落到 product。"""
        state = _state(ORDER_ANSWER_R4, pending="order", card=PROCESSING_ITEM_CARD,
                       card_skill="order")
        assert _is_card_answer_round(state) is True, "choice 卡答卡轮未被识别"
        route = route_by_intent(state)
        assert route == "order", (
            f"答卡轮被路由到 {route!r} —— 订单流程的上下文丢失，"
            "order_create 不可达（run 34841029062 OR-015 R4 零工具自称「商品侧」）"
        )
        assert state["pending_interact_skill"] == "order", "答卡轮不得清空本 skill 的会话锁"

    def test_or016_r2_skip_label_keeps_order_lock(self):
        """OR-016 R2：多选卡的「不需要加工项」（multiSelectSkipLabel）也是答卡。"""
        state = _state("不需要加工项", pending="order", card=PROCESSING_ITEM_CARD,
                       card_skill="order")
        assert route_by_intent(state) == "order"
        assert state["pending_interact_skill"] == "order"

    def test_choice_option_value_also_accepted(self):
        """前端点击协议发的是 label；个别卡发 value —— 两者都要认。"""
        state = _state("proc_item_pi_eval_punch", pending="order",
                       card=PROCESSING_ITEM_CARD, card_skill="order")
        assert route_by_intent(state) == "order"

    def test_form_card_answer_keeps_own_skill(self):
        """form 卡提交（`__FORM__|{json}`）同样是答卡轮（含跨域字段值时不得换域）。"""
        card = {
            "component": "form",
            "title": "订单 — 收货信息",
            "formFields": [{"key": "remark", "label": "备注"}],
            "submitLabel": "提交",
        }
        msg = '__FORM__|{"remark": "商品要加工项"}'
        assert _l1(msg).intent.value == "product_inquiry"      # 跨域词确实在
        state = _state(msg, pending="order", card=card, card_skill="order")
        assert route_by_intent(state) == "order"

    @pytest.mark.asyncio
    async def test_answer_round_skips_l1_at_intent_router(self):
        """第一判据点（#3677 同源）：答卡轮不得被 L1 规则表劫持重判意图。

        改前实测：`intent_router_node` 返回 `product_inquiry/rule` → 下游
        `route_by_intent` 的 L1 域逃逸清锁。改后必须短路成合成意图（本 skill 域）。
        """
        from unittest.mock import AsyncMock, patch

        msg = ORDER_ANSWER_R4
        decision = RouteDecision(intent_result=_l1(msg), action="route_with_hint")
        state = _state(msg, pending="order", card=PROCESSING_ITEM_CARD, card_skill="order")
        with patch("app.router.intent_router.IntentRouter") as router_cls:
            router_cls.return_value.route = AsyncMock(return_value=decision)
            result = await intent_router_node(state)
        assert result["intent_result"]["source"] == _CARD_CONFIRM_INTENT_SOURCE, (
            "答卡轮仍走了 L1/LLM 分类 —— 会话将被 L1 域逃逸甩到 product skill"
        )
        assert result["intent_result"]["intent"] == "order_query"


class TestReverseAnchors:
    """反向锚点：豁免只对「本 skill 自己那张卡的答卡」生效 —— 不得放宽成"答卡轮一律不切域"。"""

    def test_card_from_other_skill_does_not_exempt(self):
        """卡是**别的 skill** 发的 → 不豁免，照旧允许逃逸。"""
        state = _state(ORDER_ANSWER_R4, pending="order",
                       card=PROCESSING_ITEM_CARD, card_skill="product")
        assert _is_card_answer_round(state) is False
        assert route_by_intent(state) == "product"

    def test_unrelated_message_with_pending_card_still_escapes(self):
        """在办卡还在，但本轮说的不是它 → 逃逸必须照旧（不能把 escape hatch 关死）。"""
        state = _state("帮我查一下商品库存", pending="order",
                       card=PROCESSING_ITEM_CARD, card_skill="order")
        assert _is_card_answer_round(state) is False
        assert route_by_intent(state) == "product"

    def test_quote_skill_下单_still_escapes_with_its_own_card(self):
        """#3361 契约（不得踩）：报价 skill **自己发了报价卡**，顾客另起一句
        「确认下单」——该句不是那张卡的答卡 → 必须切到 `customer_order`。

        这是「答卡轮豁免扩到 choice/form 卡」的最大风险面：报价卡也是 choice 卡。
        判别式必须落在"本轮输入是否被那张卡接受"，而不是"有没有卡"。
        """
        quote_card = {
            "component": "choice",
            "title": "报价方案",
            "options": [
                {"label": "2 倍褶皱 · 用布 6.2 米", "value": "quote_2x"},
                {"label": "2.5 倍褶皱 · 用布 7.8 米", "value": "quote_25x"},
            ],
        }
        for msg in ("确认下单", "我要下单", "帮我下单"):
            state = _state(msg, pending="customer_quote", card=quote_card,
                           card_skill="customer_quote")
            state["intent_result"] = {"intent": "order_create", "confidence": 0.98,
                                      "source": "rule"}
            with patch.dict("app.graph.nodes._INTENT_TO_ROUTE",
                            {"mibao": {"order_create": "customer_order_skill",
                                       "general": "general_skill"}}):
                assert route_by_intent(state) == "customer_order_skill", (
                    f"{msg!r} 未切回下单流程 —— 报价 skill 没有 order_create，#3361 回归"
                )

    def test_no_pending_and_no_card_routes_by_intent(self):
        state = _state("已选加工项：纳米圈打孔", pending="", card=None, card_skill="")
        assert route_by_intent(state) == "product"


class TestConfirmCardContractUnchanged:
    """#3557（confirm 卡）原有契约不变：`last_confirm_*` 判据仍然生效。"""

    def test_confirm_round_still_exempt(self):
        value = "确认：商品名称=遮光窗帘；操作=下架（改为停售，买家不可下单）"
        state = _state(value, pending="product", card=None, card_skill="")
        state["last_confirm_skill"] = "product"
        state["last_confirm_value"] = value
        assert route_by_intent(state) == "product"
        assert state["pending_interact_skill"] == "product"
