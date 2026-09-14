# case_ids: CH-010, OR-014, OR-017
"""`amount_verify` 的加工费口径必须与系统真值一致（issue #3521）。

> ⚠️ 本文件放 ai-agent 测试根（不放 `tests/unit_ci_workflows/`）：那里是**零依赖** job
> （CI 故意不 pip install），而 `local_runner` 模块级 import httpx → 会
> `ModuleNotFoundError`（本 PR 首轮 CI 实证）。同 #3517 的 `test_amount_verify_variants.py`。

## 为什么必须有（实证）

CH-010 首跑红了一条金额断言：

```
amount_verify[order_create](R8): 总额 311.4 ≠ Σ小计71.4+加工费252.0=323.4
```

数字反推即定位真因（不是"模型算错总额"，是**模型的 args 自相矛盾**）：

- 小计 71.4 = 3 × 23.8（`prod_eval_2699` 系列雪尼尔窗帘面料，23.8/米）；
- 订单落库总额 **311.4 = 71.4 + 240**；
- 而模型在 `processing_info.processingFee` 里声明的是 **252**（= 刺绣工艺 30/㎡ × 8.4㎡）。

240 是哪来的？服务端 `OrderService.sumProcessingFee()` 的权威口径是
**Σ processingItems[].unitPrice × quantity**（`extractProcessingItems` 里 `amount` 就是
这两个字段相乘，`processingFee` 字段**根本不参与**总额计算）。即模型写了
`processingItems[{unitPrice: 30, quantity: 8}]`（→240）却又声明 `processingFee: 252`
（按面积 8.4 算的另一份）——**同一份 args 里两个加工费数字**。

后果比"断言红"严重：确认卡上给顾客看的是 323.4，落库/收款却是 311.4（差 12 元），
而旧断言把这件事报成"总额不平"，既指错了因、也指错了修的地方。

## 本组守卫

1. 加工费用**服务端口径**（Σ unitPrice × quantity）核对，而不是信 `processingFee` 字段；
2. `processingFee` 与 Σ加工项不一致时，给**点名该矛盾**的可执行断言（`processing_fee` 检查项），
   总额核对也用服务端口径（否则会用一个模型自造的数字去判系统真值，制造假红）。
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]   # tests/ → ai-agent-service/ → backend/ → 仓根
RUNNER = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("lr_amount", RUNNER)
    m = importlib.util.module_from_spec(spec)
    sys.modules["lr_amount"] = m
    spec.loader.exec_module(m)
    return m


def _round(rnd, items, total, fee_declared=None, proc_items=None):
    """造一轮 order_create 成功调用的 results（只含金额断言用得到的字段）。"""
    pinfo = {"processingFee": fee_declared} if fee_declared is not None else {}
    if proc_items is not None:
        pinfo["processingItems"] = proc_items
    args = {
        "customer_name": "张三",
        "customer_phone": "13800138000",
        "items": [
            {
                "product_name": "2699系列雪尼尔窗帘面料",
                "quantity": 3,
                "unit_price": 23.8,
                "subtotal": 71.4,
                "processing_info": pinfo,
            }
        ],
    }
    return {
        "__round": rnd,
        "tool_calls": [{"name": "order_create", "args": args}],
        "tool_results": [
            {"tool": "order_create",
             "result": {"success": True, "data": {"totalAmount": total, "orderNo": "X"}}}
        ],
    }


def _run(m, results, checks):
    return asyncio.run(m.check_amount_verify(
        token="t", results=results,
        amount_verify=[{"tool": "order_create", "checks": checks}],
    ))


class TestProcessingFeeCanonicalSource:
    """加工费必须按**服务端口径**（Σ processingItems unitPrice×quantity）核算。"""

    def test_3521_signature_reports_fee_mismatch_not_total_mismatch(self):
        """#3521 实况：声明 252（面积 8.4）而 items 是 30×8=240 → 服务端落库 311.4。

        旧实现的报错是「总额 311.4 ≠ Σ小计71.4+加工费252.0=323.4」——把一个
        **args 内部矛盾**报成"总额不平"。新实现必须：
          · 点名 `processingFee` 与 Σ加工项不一致（可执行、指向修的地方）；
          · 总额核对用服务端口径（71.4+240=311.4）→ 不再产生那条误导性红。
        """
        m = _load_runner()
        results = [_round(9, None, total=311.4, fee_declared=252.0,
                          proc_items=[{"name": "刺绣工艺", "unitPrice": 30, "quantity": 8}])]
        issues = _run(m, results, ["subtotal", "processing_fee", "total"])
        joined = "\n".join(issues)
        assert any("processingFee" in i and "加工项" in i for i in issues), (
            f"应点名 processingFee 与 Σ加工项 的矛盾，实际: {joined!r}")
        assert "252" in joined and "240" in joined, f"矛盾的两个数字都要出现: {joined!r}"
        assert not any("≠ Σ小计" in i for i in issues), (
            f"服务端口径 71.4+240=311.4 与落库总额一致 → 不该再报总额不平: {joined!r}")

    def test_consistent_fee_is_clean(self):
        """声明值与 Σ加工项一致（24 = 8×3）→ 无任何违规。"""
        m = _load_runner()
        results = [_round(8, None, total=95.4, fee_declared=24.0,
                          proc_items=[{"name": "纳米圈打孔", "unitPrice": 8, "quantity": 3}])]
        assert _run(m, results, ["subtotal", "processing_fee", "total"]) == []

    def test_fee_folded_subtotal_variant_still_clean(self):
        """#3517 的「小计已含加工费」变体不受本次改动影响（防回归）。"""
        m = _load_runner()
        # 服务端口径：71.4（面料）+ 24（加工）= 95.4，两种小计约定下总额都是 95.4
        r = _round(8, None, total=95.4, fee_declared=24.0,
                   proc_items=[{"name": "纳米圈打孔", "unitPrice": 8, "quantity": 3}])
        item = r["tool_calls"][0]["args"]["items"][0]
        item["subtotal"] = 95.4      # 变体②：小计 71.4 + 加工费 24
        assert _run(m, [r], ["subtotal", "processing_fee", "total"]) == []

    def test_no_processing_items_falls_back_to_declared_fee(self):
        """没有 processingItems 的老形态（只写 processingFee）→ 沿用声明值，不误报。"""
        m = _load_runner()
        results = [_round(8, None, total=95.4, fee_declared=24.0)]
        assert _run(m, results, ["subtotal", "processing_fee", "total"]) == []

    def test_total_still_checked_when_no_processing_items(self):
        """回退路径也要真的核对总额（不能因为缺 processingItems 就静默放过）。"""
        m = _load_runner()
        results = [_round(8, None, total=999.0, fee_declared=24.0)]
        issues = _run(m, results, ["subtotal", "processing_fee", "total"])
        assert any("总额" in i for i in issues), f"应报总额不平: {issues!r}"


class TestAmountChecksVocabulary:
    def test_processing_fee_is_a_known_check(self):
        """`processing_fee` 必须进已知检查项词汇表（否则 _normalize 之外的路径会漂）。"""
        m = _load_runner()
        assert "processing_fee" in m._KNOWN_AMOUNT_CHECKS

    def test_ch010_declares_processing_fee_check(self):
        """CH-010 的 amount_verify 必须真的开启加工费一致性检查（配置层可见）。"""
        import importlib.util as iu
        spec = iu.spec_from_file_location("ec_ch010", REPO_ROOT / "tests/agent_eval/eval_cases.py")
        mod = iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        case = next(c for c in mod.ALL_CASES if c.id == "CH-010")
        specs = [s for s in (case.amount_verify or []) if isinstance(s, dict)]
        assert specs, "CH-010 必须保留 amount_verify"
        assert any("processing_fee" in (s.get("checks") or []) for s in specs), (
            f"CH-010 需开启 processing_fee 检查，实际: {[s.get('checks') for s in specs]!r}")
