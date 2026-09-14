"""amount_verify subtotal/total 断言的口径兼容单测（#3511 T3.2 归因）

背景（B 端独立栈首跑 run 34804430769，OR-014 失败）：
    amount_verify[order_create](R7): 「遮光窗帘」小计 528.0 ≠ 数量3.0×单价168.0

但 528 = 504（3×168）+ 24（打孔 8×3）—— **两种约定都合法**：
  ① 面料小计：subtotal = 数量 × 单价（服务端 canonical：
     `AgentOrderCreateRequest`「subtotal 可选 → 服务端按 quantity × unitPrice 重算」；
     C 端 seed 的历史订单明细也是 504 = 3×168）
  ② 含加工费：subtotal = 面料小计 + 本行 processingFee（工具描述
     「合计写入 processingFee 并**计入金额**」的自然读法）

两种在服务端都会被规范化，**用户可见结果一致**（订单总额/落库金额正确）→
按 acceptance-protocol §14.2「有效性漂移：真实重放 fail 但行为合理（LLM 合法变体）
→ 校准断言」，断言应兼容两式，不得对合法变体判红（假失败会污染完成判定）。

同时：total 检查**不得双计** —— 若 Σ小计已含加工费，expected 不应再加 ΣprocessingFee。
"""
# case_ids: OR-014, OR-016, OR-021
import asyncio
import importlib.util
import unittest.mock as mock
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("migao_eval_runner_amt", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lr = _load_runner()

PRICE = 168.0          # 遮光窗帘商品库单价
FEE = 24.0             # 纳米圈打孔 8 元/米 × 3 米
QTY = 3.0


def _results(subtotal, total=None, fee=FEE):
    """构造一轮 order_create 成功调用：args.items[0] 带 subtotal；可选结果带总额。"""
    item = {"product_name": "遮光窗帘", "quantity": QTY, "unit_price": PRICE,
            "subtotal": subtotal,
            "processing_info": {"processingFee": fee}}
    data = {"orderNo": "20260914348780002"}
    if total is not None:
        data["totalAmount"] = total
    return [{
        "__round": 1,
        "tool_calls": [{"name": "order_create", "args": {"items": [item]}}],
        "tool_results": [{"tool": "order_create", "result": {"success": True, "data": data}}],
        "final_text": "订单已创建",
    }]


SPEC = [{"tool": "order_create", "product_name": "遮光窗帘",
         "checks": ["unit_price", "subtotal", "total"]}]


def _run(results):
    async def _fake_price(token, name):
        return PRICE
    with mock.patch.object(lr, "_fetch_product_price", new=_fake_price):
        return asyncio.run(lr.check_amount_verify("tok", results, SPEC))


class TestSubtotalVariants:
    """subtotal 两种合法约定都必须通过（否则合法变体被判红 = 假失败）"""

    def test_canonical_subtotal_passes(self):
        """变体① 面料小计：subtotal = 3×168 = 504"""
        assert _run(_results(504.0, total=528.0)) == []

    def test_subtotal_including_processing_fee_passes(self):
        """变体② 含加工费：subtotal = 504 + 24 = 528（B 端首跑实测形态）"""
        assert _run(_results(528.0, total=528.0)) == []

    def test_wrong_subtotal_still_fails(self):
        """真错仍必须判红：¥95.4 是 OR-014 的历史真实缺陷（没查商品凭记忆报价）"""
        issues = _run(_results(95.4, total=95.4))
        assert issues, "明显错误的小计必须判红（放宽不得丢信号）"


class TestTotalNoDoubleCounting:
    """total 检查不得双计：Σ小计已含加工费时，expected 不再加 processingFee"""

    def test_total_ok_when_fee_folded_in_subtotal(self):
        """变体② + 服务端总额 528 → 通过（旧实现算 expected=528+24=552 → 假红）"""
        assert _run(_results(528.0, total=528.0)) == []

    def test_total_ok_when_fee_separate(self):
        """变体① + 服务端总额 528 = 504 + 24 → 通过（原行为不变）"""
        assert _run(_results(504.0, total=528.0)) == []

    def test_total_wrong_still_fails(self):
        """总额真错（528 vs 552）仍判红"""
        issues = _run(_results(504.0, total=552.0))
        assert any("总额" in i for i in issues), f"总额错误必须判红: {issues}"
