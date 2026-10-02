# case_ids: DA-021
"""日报卡片面「proactive 四态」可视化（issue #5955）—— 让「今天为什么没有提示」逐规则可见。

本文件钉住的是**挂载点**而不是引擎（引擎判据在 `test_briefing_proactive*.py`，本单不改引擎）：

1. 四态挂在 `sanitize_briefing` **之后** —— 前者的白名单只返回五个键，字段从 LLM 出口进不来
   （塞进去 ⇒ **被丢弃是预期**，这是判据本身，不是 bug）；
2. 挂上去的值 = `proactive_status(snapshot)` 的**原样**（零重算、零改写、不改快照）；
3. 「没数据 / 没开启 / 不完整」与「已接线、本次完整但无命中」在**输出上可分** ——
   前者带 `reason`，后者 `reason is None` 且边界只在 `caveats` 里（不许因为「绿」就不显示边界）。
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.briefing.generator import (
    PROACTIVE_STATUS_KEY,
    attach_proactive_status,
    generate_briefing,
    sanitize_briefing,
)
from app.briefing.proactive import proactive_status

CARD_KEYS = ("summary", "review", "todo", "risks", "suggestions")


def _snapshot(orders=None, skus=None, audit_tool_logging=True):
    """带装配层自描述的**真**快照形状（`row_fields` 是引擎判接线的唯一依据，不给就不算接线）。"""
    return {
        "biz_date": "2026-10-02",
        "row_fields": {
            "orders": ["order_no", "status", "customer_id", "created_at", "shipped_at",
                       "sale_amount", "cost_amount"],
            "skus": ["sku_id", "product_id", "product_name", "stock"],
        },
        "row_meta": {
            "orders": {"limit": 500, "count": len(orders or []), "truncated": False},
            "skus": {"limit": 500, "count": len(skus or []), "truncated": False},
        },
        "cost_accounting": False,
        "audit_tool_logging": audit_tool_logging,
        "orders": list(orders or []),
        "skus": list(skus or []),
    }


#: 规则齐全且**无命中**：orders/skus 已接线，另外四条规则的数组本快照没有（= 未接线）。
ALL_WIRED_NO_HIT = _snapshot()

LLM_JSON = json.dumps({
    "summary": "昨日订单 0 单",
    "review": [],
    "todo": [{
        "priority": "high",
        "title": "1 个订单待发货",
        "reason": "超过发货时效",
        "metrics": [{"key": "pending_ship_orders", "value": 1}],
    }],
    "risks": [],
    "suggestions": [],
})


def _fake_llm(content=LLM_JSON):
    llm = AsyncMock()
    llm.ainvoke.return_value.content = content
    return llm


async def _run(snapshot, llm_content=LLM_JSON):
    """真的跑一遍 `generate_briefing`（LLM 出站被替身，其余全是真实现）。"""
    with patch("app.briefing.generator.LLMFactory.create_briefing_llm", return_value=_fake_llm(llm_content)):
        return await generate_briefing(snapshot)


class TestStatusNotFromLlmExit:
    """判据 4：钉住「状态字段不来自 LLM 出口」—— 塞进去被丢弃是预期，挂载点之后必须成功。"""

    def test_llm_supplied_status_is_silently_dropped_by_whitelist(self):
        raw = json.loads(LLM_JSON)
        raw[PROACTIVE_STATUS_KEY] = {"low_stock": {"status": "wired", "reason": None}}
        cleaned = sanitize_briefing(raw)
        # 白名单的**行为**判据：五个键之外一律没有（不是「值被改」，是「键不存在」）
        assert set(cleaned) == set(CARD_KEYS)

    @pytest.mark.asyncio
    async def test_status_from_llm_exit_is_dropped_end_to_end(self):
        poisoned = json.loads(LLM_JSON)
        poisoned[PROACTIVE_STATUS_KEY] = {"伪造": {"status": "wired", "reason": None}}
        briefing = await _run(ALL_WIRED_NO_HIT, llm_content=json.dumps(poisoned))
        # 模型编的状态**进不来**：挂上去的那个是引擎的逐规则结果（六条规则，不是一条）
        assert "伪造" not in briefing[PROACTIVE_STATUS_KEY]
        assert set(briefing[PROACTIVE_STATUS_KEY]) == set(proactive_status(ALL_WIRED_NO_HIT))

    @pytest.mark.asyncio
    async def test_status_injected_after_the_mount_point(self):
        briefing = await _run(ALL_WIRED_NO_HIT)
        assert briefing[PROACTIVE_STATUS_KEY] == proactive_status(ALL_WIRED_NO_HIT)

    @pytest.mark.asyncio
    async def test_injected_status_is_the_engine_object_untouched(self):
        briefing = await _run(ALL_WIRED_NO_HIT)
        entry = briefing[PROACTIVE_STATUS_KEY]["low_stock"]
        # 原样透传：键集与引擎逐字相同（少一个键 = 消费方读不到原因/边界）
        assert set(entry) == {"rule_id", "rule_name", "status", "reason", "missing", "gaps", "caveats"}
        assert entry["status"] == "wired"
        assert entry["reason"] is None

    @pytest.mark.asyncio
    async def test_snapshot_is_not_mutated(self):
        snapshot = _snapshot()
        before = json.dumps(snapshot, sort_keys=True, default=str)
        await _run(snapshot)
        assert json.dumps(snapshot, sort_keys=True, default=str) == before


class TestNotWiredIsNamedNotSilent:
    """判据 1：未接线的规则必须**具名**报出 + 给出原因（不是「今天没问题」）。"""

    @pytest.mark.asyncio
    async def test_unwired_rule_is_named_with_reason(self):
        briefing = await _run(ALL_WIRED_NO_HIT)
        status = briefing[PROACTIVE_STATUS_KEY]
        # 快照没有 returns 数组 ⇒ 连续退货**本次没有检查**（而不是「没命中」）
        assert status["repeat_returns"]["status"] == "not_wired"
        assert status["repeat_returns"]["rule_name"] == "连续退货"
        assert "returns" in status["repeat_returns"]["reason"]
        assert status["repeat_returns"]["missing"] == ["returns"]

    @pytest.mark.asyncio
    async def test_unwired_and_clean_empty_are_distinguishable(self):
        briefing = await _run(ALL_WIRED_NO_HIT)
        status = briefing[PROACTIVE_STATUS_KEY]
        # 互斥红的一半：同一次输出里，「没检查」有原因、「查了没问题」没原因 —— 两者不可混。
        # 🔴 只用 `is None` / 文本在场两种判据（不写 `is not None` 这类弱断言）。
        assert status["repeat_returns"]["reason"] != status["low_stock"]["reason"]
        assert status["low_stock"]["reason"] is None
        assert "returns" in status["repeat_returns"]["reason"]
        assert status["low_stock"]["status"] == "wired"
        assert status["repeat_returns"]["status"] == "not_wired"


class TestWiredCaveatsStayVisible:
    """判据 3：`wired` 的规则其 `caveats`（数据源固有边界）也必须在场。"""

    @pytest.mark.asyncio
    async def test_wired_rule_caveats_are_present(self):
        briefing = await _run(ALL_WIRED_NO_HIT)
        entry = briefing[PROACTIVE_STATUS_KEY]["low_stock"]
        # `caveats` 恒在（可为空列表）：消费方不必先判 wired 再决定读不读边界
        assert isinstance(entry["caveats"], list)
        # 改价那条即使在 `not_wired` 态也带着 fail-open 边界（wired 时同理，见下）
        assert briefing[PROACTIVE_STATUS_KEY]["price_change_over"]["caveats"]
        assert any("fail-open" in c for c in briefing[PROACTIVE_STATUS_KEY]["price_change_over"]["caveats"])

    def test_wired_rule_keeps_reason_none_while_caveats_present(self):
        status = proactive_status(ALL_WIRED_NO_HIT)
        # 不变式：`reason is None` ⟺ `wired`（caveats 不借用 reason 通道 —— 它有自己的键）
        for entry in status.values():
            assert (entry["reason"] is None) == (entry["status"] == "wired")


class TestUnknownIsNotNoProblem:
    """「未知 ≠ 没问题」：状态算不出来时**不挂键**（消费方须按未知处理），而不是挂个空壳。"""

    def test_blank_snapshot_is_reported_unknown_not_clean(self):
        # 空快照（没有任何自描述）⇒ 引擎**六条规则全部** `not_wired` 且各自带原因：
        # 「不知道」必须是能被显示出来的东西，不许退化成空壳被消费方读成「已检查」。
        status = proactive_status({})
        assert len(status) == 6
        for entry in status.values():
            assert entry["status"] == "not_wired"
            assert entry["reason"]

    def test_degenerate_snapshot_still_mounts_the_unknown_verdict(self):
        mounted = attach_proactive_status({"summary": "x"}, {})
        assert set(mounted) == {"summary", "proactive_status"}
        assert {e["status"] for e in mounted[PROACTIVE_STATUS_KEY].values()} == {"not_wired"}

    def test_status_can_be_read_off_the_wire_shape(self):
        """跨端契约（判据 5 的窄测试面）：字段名/枚举值三端一致 —— 键名逐字，枚举值只有这四个。"""
        status = proactive_status(ALL_WIRED_NO_HIT)
        assert set(status) == {
            "below_cost_price", "unshipped_overdue", "low_stock",
            "repeat_returns", "price_change_over", "discount_over",
        }
        for entry in status.values():
            assert entry["status"] in {"wired", "not_wired", "not_enabled", "incomplete"}
        # 挂载键本身也是契约的一部分（admin-api / admin-web 按这个键取）
        assert PROACTIVE_STATUS_KEY == "proactive_status"

    def test_not_enabled_is_separate_from_not_wired(self):
        """`not_enabled`（系统有、该租户没开 ⇒ **可行动**）与 `not_wired`（系统没做）不可合并。"""
        snapshot = _snapshot(audit_tool_logging=False)
        snapshot["row_fields"]["price_changes"] = [
            "change_no", "tool_name", "product_id", "before_price", "new_price", "changed_at",
        ]
        snapshot["price_changes"] = []
        status = proactive_status(snapshot)
        assert status["price_change_over"]["status"] == "not_enabled"
        assert "审计" in status["price_change_over"]["reason"]
        assert status["repeat_returns"]["status"] == "not_wired"
