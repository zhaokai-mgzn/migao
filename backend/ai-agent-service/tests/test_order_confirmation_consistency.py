# case_ids: OR-016, OR-014
"""F22 确认卡↔落库一致性守护（issue #4037）—— 断言红证先行。

## 缺陷（今日线上实证）
顾客点确认卡看到的是 **¥498（10 米 / 2.8 米 / 3 个加工项）**，落库却是
**¥133.80（1 米 / 3.2 米 / 2 个加工项 + 优惠 ¥5）** —— **全系统无一处校验两者一致**。
卡上的事实与写工具真实参数是**两份独立产物**：
`interact(component=confirm, fields=[…])` 的 fields 由模型自由书写，
`order_create` 的 items 也由模型自由书写，两处之间只有 prompt 里的口头约定。

## 修法（确定性层，零 LLM）
1. 顾客**确认那一刻**把「被确认的金额事实」快照进会话状态
   （`confirmed_order_facts`，与既有 `confirmed_write_tool` 同处落库）；
2. `order_create` **真正执行之前**重算事实并与快照比对，不一致 ⇒ 拦截并给可行动下一步。

「金额事实」只取**驱动金额与库存的规范值**（服务端就是按这些重算的）：
客户手机号 + 每行 `product_name/quantity/unit_price/加工费`。
**金额字段刻意让服务端重算**（L1 正确性由服务端负责），本守护只保证
「顾客确认的那份明细 = 真正要执行的那份明细」。

## 红证形态（本文件先红后绿）
- `test_card_facts_have_no_money`：`confirm_card_fields` 的投影**必须**含数量/单价/小计/合计
  —— 改前没有 ⇒ 卡片事实无从核对（这就是"全系统无一处校验"的机制）。
- `test_consistency_blocks_amount_drift` / `test_consistency_blocks_dropped_item` /
  `test_consistency_blocks_phone_drift`：线上实证那笔单的形态（价格/行数/手机号漂移）必须被拦。
- `test_consistency_allows_identical` / `test_consistency_allows_added_optional_field`：
  **R2 负例** —— 完全一致、以及"确认后只补非金额信息（收货地址/验证码）"不得被拦。
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage

from app.graph.skills.base_skill import confirm_card_fields
from app.tools.order_create import order_confirmation_mismatch, order_facts_of


def _facts(items, phone="13800138000"):
    return order_facts_of({"customer_phone": phone, "items": items})


def _item(name="遮光窗帘", qty=1, price=133.8, subtotal=133.8, **extra):
    it = {"product_name": name, "quantity": qty, "unit_price": price, "subtotal": subtotal}
    it.update(extra)
    return it


class TestConfirmCardCarriesMoneyFacts:
    """卡片投影必须带上金额事实（否则"卡上写了多少钱"根本没有机器可读的那一份）。"""

    def test_card_fields_have_no_money(self):
        fields = confirm_card_fields({
            "customer_phone": "13800138000",
            "items": [_item(qty=10, price=49.8, subtotal=498.0)],
        })
        labels = [f["label"] for f in fields]
        assert "单价" in labels, f"确认卡投影缺单价：{labels}"
        assert "小计" in labels, f"确认卡投影缺小计：{labels}"
        assert "合计" in labels, f"确认卡投影缺合计：{labels}"

    def test_card_fields_keep_existing_labels(self):
        """R2 负例：既有标签（商品/数量/收货人/手机号/地址）一个都不能丢。"""
        fields = confirm_card_fields({
            "customer_name": "张三",
            "customer_phone": "13800138000",
            "customer_address": "杭州市西湖区",
            "items": [_item()],
        })
        labels = [f["label"] for f in fields]
        for keep in ("商品", "数量", "收货人", "手机号", "地址"):
            assert keep in labels, f"既有卡片标签被改坏：{labels}"


class TestFactsSnapshot:
    """事实快照的取值口径（驱动金额/库存的规范值）。"""

    def test_facts_include_canonical_money_values(self):
        facts = _facts([_item(name="遮光窗帘", qty=3, price=168, subtotal=528.0)])
        assert "13800138000" in facts
        assert "遮光窗帘" in facts
        assert "3" in facts and "168" in facts

    def test_facts_ignore_non_money_fields(self):
        """非金额字段（地址/备注/验证码）不进事实 —— 确认后补这些信息不应导致不一致。"""
        base = _facts([_item()])
        enriched = order_facts_of({
            "customer_phone": "13800138000",
            "customer_address": "杭州市西湖区",
            "sms_code": "123456",
            "remark": "周五送到",
            "items": [_item(width=2.8, height=3.2)],
        })
        assert base == enriched, "非金额字段（地址/验证码/备注/尺寸）不该进入一致性事实"

    def test_facts_include_processing_fee(self):
        """加工费是金额的一部分（服务端按 unitPrice×quantity 重算），必须进事实。"""
        no_fee = _facts([_item()])
        with_fee = _facts([_item(processing_info={
            "processingItems": [{"name": "打孔", "unitPrice": 8, "quantity": 3}]})])
        assert no_fee != with_fee, "加工费变化未进入一致性事实（= 漏收/多收加工费无人发现）"

    def test_facts_empty_when_no_items(self):
        assert order_facts_of({"customer_phone": "13800138000"}) == ""
        assert order_facts_of(None) == ""


class TestConsistencyGuard:
    """落库前核对：确认的事实 vs 真正要执行的事实。"""

    def test_consistency_blocks_amount_drift(self):
        """线上实证形态：确认卡 ¥498（10 米 @49.8），落库 ¥133.80（1 米 @133.8）。"""
        confirmed = _facts([_item(qty=10, price=49.8, subtotal=498.0)])
        actual = {"customer_phone": "13800138000",
                  "items": [_item(qty=1, price=133.8, subtotal=133.8)]}
        err = order_confirmation_mismatch(actual, confirmed)
        assert err, "确认卡金额与落库金额不一致却放行（= F22 原缺陷）"

    def test_consistency_blocks_dropped_item(self):
        """确认卡 3 个加工项/多行，落库变少行。"""
        confirmed = _facts([_item(name="遮光窗帘"), _item(name="纱帘")])
        actual = {"customer_phone": "13800138000", "items": [_item(name="遮光窗帘")]}
        assert order_confirmation_mismatch(actual, confirmed), "少了一行却放行"

    def test_consistency_blocks_phone_drift(self):
        confirmed = _facts([_item()], phone="13800138000")
        actual = {"customer_phone": "13900139000", "items": [_item()]}
        err = order_confirmation_mismatch(actual, confirmed)
        assert err, "客户手机号与确认时不符却放行（订单会挂到别人名下）"

    def test_consistency_blocks_processing_fee_drift(self):
        confirmed = _facts([_item(processing_info={
            "processingItems": [{"name": "打孔", "unitPrice": 8, "quantity": 3}]})])
        actual = {"customer_phone": "13800138000",
                  "items": [_item()]}  # 加工项被静默丢掉 = 漏收加工费
        assert order_confirmation_mismatch(actual, confirmed), "加工项被丢弃却放行"

    # ── R2 负例：合法输入不得被拦 ──────────────────────────────────────────

    def test_consistency_allows_identical(self):
        confirmed = _facts([_item(qty=3, price=168, subtotal=528.0)])
        actual = {"customer_phone": "13800138000",
                  "items": [_item(qty=3, price=168, subtotal=528.0)]}
        assert order_confirmation_mismatch(actual, confirmed) == ""

    def test_consistency_allows_added_optional_field(self):
        """确认后补收货地址/验证码/尺寸（非金额信息）⇒ 不得被拦。"""
        confirmed = _facts([_item(qty=3, price=168, subtotal=528.0)])
        actual = {
            "customer_phone": "13800138000",
            "customer_address": "杭州市西湖区文三路 1 号",
            "sms_code": "123456",
            "remark": "周五送到",
            "items": [_item(qty=3, price=168, subtotal=528.0, width=2.8, height=3.2)],
        }
        assert order_confirmation_mismatch(actual, confirmed) == ""

    def test_consistency_allows_formatted_number_drift(self):
        """同一金额的不同写法（"168" / "168.00" / 168.0）不得被判不一致。"""
        confirmed = _facts([_item(qty="3", price="168.00", subtotal="528.00")])
        actual = {"customer_phone": "13800138000",
                  "items": [_item(qty=3, price=168.0, subtotal=528)]}
        assert order_confirmation_mismatch(actual, confirmed) == ""

    def test_consistency_skipped_when_nothing_confirmed(self):
        """没记过确认事实 ⇒ 不拦（本守护只比对"确认过什么"，不替代确认门禁）。"""
        assert order_confirmation_mismatch({"items": [_item()]}, "") == ""
        assert order_confirmation_mismatch({"items": [_item()]}, None) == ""

    def test_consistency_skipped_when_confirmed_has_no_items(self):
        """确认快照没有金额事实（老会话/无 items 的写）⇒ 无从核对，不拦。"""
        assert order_confirmation_mismatch({"items": [_item()]}, "手机号=13800138000") == ""

    def test_mismatch_message_is_actionable(self):
        """R5：fail-closed 必须带可行动下一步（否则模型原地重试烧轮数）。"""
        confirmed = _facts([_item(qty=10, price=49.8, subtotal=498.0)])
        actual = {"customer_phone": "13800138000",
                  "items": [_item(qty=1, price=133.8, subtotal=133.8)]}
        err = order_confirmation_mismatch(actual, confirmed)
        assert "确认" in err, f"拦截话术未说明「要重新确认」：{err}"
        assert "order_create" in err or "下单" in err, f"拦截话术未点名下一步：{err}"

# ══ 门禁级集成（走真实 `execute_skill` 确认门禁，不是只测纯函数）════════════
# 纯函数绿 ≠ 落库路径被守住：判据必须**真的挂在门禁上并被行使**，
# 否则就是「声明无消费」（写进代码但无人调用）。
class TestGateBlocksPostConfirmDrift:
    """确认后明细被改写 ⇒ 写调用必须被门禁拦下（F22 线上实证形态）。"""

    LONG_CONFIRM = "确认下单：遮光窗帘 10米 ¥49.8 合计¥498，收货人张三 13800138000"

    @staticmethod
    def _run_gate(store_state, items, phone="13800138000"):
        """跑一次真实 `execute_skill`，返回被执行的工具名列表。"""
        import asyncio

        from langchain_core.messages import AIMessage as _AI
        from app.graph.skills.base_skill import execute_skill
        from app.tools.order_create import OrderCreateTool
        from tests.test_graph_skills import _make_state

        executed = []

        async def fake_execute(tool, args, ctx, state):
            executed.append(tool.name)
            return (json.dumps({"success": True, "data": {}}), {"success": True, "data": {}})

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
             patch("app.memory.session_state_store.SessionStateStore") as store_cls:
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.side_effect = lambda n: (
                OrderCreateTool() if n == "order_create" else None)
            create_reg.return_value = registry

            breaker = MagicMock()

            async def _passthrough(fn):
                return await fn()

            breaker.call = _passthrough
            get_breaker.return_value = breaker

            call = MagicMock(spec=_AI)
            call.content = ""
            call.tool_calls = [{"name": "order_create",
                                "args": {"customer_name": "张三", "customer_phone": phone,
                                         "items": items}, "id": "t1"}]
            final = MagicMock(spec=_AI)
            final.content = "订单已提交"
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[call, final])
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            inst = MagicMock()
            inst.load = AsyncMock(side_effect=lambda sid: dict(store_state))
            inst.commit = AsyncMock(side_effect=lambda sid, full: store_state.update(full))
            store_cls.return_value = inst

            asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content="123456")]),
                skill_name="customer_order",
                tool_names=["order_create"], system_prompt="你是小布",
            ))
        return executed

    def _confirmed_state(self, confirmed_items):
        return {
            "last_confirm_value": self.LONG_CONFIRM,
            "confirmed_write_tool": "order_create",
            "confirmed_order_facts": order_facts_of(
                {"customer_phone": "13800138000", "items": confirmed_items}),
            "grounded_product_detail": {"product_id": "prod_eval_blackout"},
        }

    def test_gate_blocks_amount_drift(self):
        """确认卡 ¥498（10 米 @49.8）→ 落库 ¥133.80（1 米 @133.8）必须被拦。"""
        state = self._confirmed_state([_item(qty=10, price=49.8, subtotal=498.0)])
        executed = self._run_gate(state, [_item(qty=1, price=133.8, subtotal=133.8)])
        assert "order_create" not in executed, (
            "确认后金额被改写仍落库（= F22 原缺陷：卡上 ¥498、落库 ¥133.80）")

    def test_gate_blocks_phone_drift(self):
        state = self._confirmed_state([_item()])
        executed = self._run_gate(state, [_item()], phone="13900139000")
        assert "order_create" not in executed, "确认后手机号被改写仍落库"

    # ── R2 负例：合法输入不得被拦 ──────────────────────────────────────────

    def test_gate_allows_identical_items(self):
        state = self._confirmed_state([_item(qty=3, price=168, subtotal=528.0)])
        executed = self._run_gate(state, [_item(qty=3, price=168, subtotal=528.0)])
        assert executed == ["order_create"], (
            f"明细与确认一致却被拦（R2 反例：合法下单被卡住）：{executed}")

    def test_gate_allows_added_optional_field_after_confirm(self):
        """确认后补收货地址/尺寸（非金额信息）⇒ 照旧放行。"""
        state = self._confirmed_state([_item(qty=3, price=168, subtotal=528.0)])
        executed = self._run_gate(
            state, [_item(qty=3, price=168, subtotal=528.0, width=2.8, height=3.2)])
        assert executed == ["order_create"], f"补非金额信息被误拦：{executed}"

    def test_gate_untouched_without_facts_snapshot(self):
        """没记过金额事实（老会话/非下单写）⇒ 门禁行为一字不变（照旧放行）。"""
        state = {"last_confirm_value": self.LONG_CONFIRM,
                 "confirmed_write_tool": "order_create",
                 "grounded_product_detail": {"product_id": "prod_eval_blackout"}}
        executed = self._run_gate(state, [_item(qty=1, price=133.8, subtotal=133.8)])
        assert executed == ["order_create"], f"无快照时误拦：{executed}"
