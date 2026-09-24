# case_ids: PR-047, PR-048
"""库存小数化（1 位小数 = 0.1 米粒度）—— AI 工具层判据（issue #5063）

B 端只读化（issue #5247）：inventory_manage（库存） 的写 action 已删除 ⇒ 本次退休写路径用例（产品裁定，非放宽门禁）。
真值口径（issue #5063 用户裁定「库存米数是小数，1 位小数，必须改造」+「不能损失客户」）：

  · 库存 / 数量列由 `INT` 升级为 `NUMERIC(12,1)` ⇒ **0.1 米**粒度；
  · 库存类**输入**超过 1 位小数 ⇒ **显式拒绝**（fail-closed），文案必须可行动；
    **禁止**四舍五入 / 截断后照常执行 —— 静默取整 = 与实物不符的账；
  · 整数场景**逐值不变**（`10` 下发的仍是 `10`，不是 `10.0`）；
  · 工具给 LLM / 用户看的数字必须干净（`62.5`，不是 `62.50000000001`）。

红证（改前 @ origin/main @9b4e3a1bd，本人实跑）：
  · schema `adjustment.type == "integer"` ⇒ `test_adjustment_schema_type_is_number` 红；
  · `_adjust_inventory` 无小数位判定，`2.755` 被**静默**透传给后端 ⇒ PR-047 三条红；
  · `stock_semantics.product_stock_summary` 用 `int(...)` 累加 ⇒ `60.5 + 1.5` 得 `61`
    ⇒ `test_product_stock_summary_sums_decimals_without_precision_loss` 红；
  · `validate_input` 闸门 `adjustment` 规则声明 `int` ⇒ `60.5` 在**前置闸门**就被判类型错，
    工具层再对也到不了后端 ⇒ `test_validate_input_gate_accepts_one_decimal` 红。

⚠️ 不写 `round(x, 1) == x` 这类浮点比较：`2.7` 的二进制表示不精确，会把合法的 `2.7`
判成「超过 1 位小数」而**误拒**（本文件 `test_one_decimal_helper_accepts` 正是该形态的判据）。
"""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.inventory_manage import InventoryManageTool, _one_decimal_or_none
from app.tools.stock_semantics import product_stock_summary



@pytest.fixture
def tool():
    return InventoryManageTool()


# ── PR-046：库存调整接受 1 位小数 ──────────────────────────────────────────────


class TestOneDecimalInputAccepted:
    # [RETIRED #5247] test_adjustment_schema_type_is_number 已退休：库存调整（adjust）已从 B 端移除（B 端只读化）：adjustment 的 schema 声明随之消失，断言无对象。

    # [RETIRED #5247] test_schema_description_states_meter_unit_and_one_decimal 已退休：库存调整（adjust）已从 B 端移除（B 端只读化）：adjustment 的 description 随之消失，断言无对象。

    # [RETIRED #5247] test_adjustment_60_5_reaches_admin_api_as_float 已退休：库存调整（adjust）已从 B 端移除（B 端只读化）：小数调整量下发路径不再存在，断言无对象。

    # [RETIRED #5247] TestOneDecimalInputAccepted（4 例） 已退休：库存调整（adjust）已从 B 端移除（B 端只读化）：小数边界下发路径不再存在，断言无对象。

    # [RETIRED #5247] test_integer_input_still_sent_as_int 已退休：库存调整（adjust）已从 B 端移除（B 端只读化）：整数下发的 int 保留判据随写路径消失。

    # [RETIRED #5247] test_decimal_sum_and_message_have_no_float_fuzz 已退休：库存调整（adjust）已从 B 端移除（B 端只读化）：读回校验/文案路径不再存在；SKU 求和的 Decimal 判据由 TestSkuSumKeepsDecimalPrecision 与 query 展示用例继续守着。

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_query_message_shows_decimal_stock_cleanly(
        self, mock_get_client, tool, admin_tool_context
    ):
        """查询展示：`60.5 + 2 = 62.5` 报「62.5」，不得出现 `62.50000000001` /
        也不得把 `62.0` 展示成 `62.0`（整数场景观感不变）。"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"name": "窗帘-欧式", "stock": 0, "skus": [{"stock": 60.5}, {"stock": 2}]},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="query", product_id="prod-1")

        assert result.success is True
        assert result.data["stock"] == 62.5
        assert "62.5" in result.message
        assert "62.50000000001" not in result.message


class TestSkuSumKeepsDecimalPrecision:
    """`product_stock_summary`（工具层商品库存唯一入口）不得再静默截断（issue #4038 + #5063）。"""

    def test_product_stock_summary_sums_decimals_without_precision_loss(self):
        """红证（改前）：`int(60.5) + int(1.5)` ⇒ **61**（半米凭空消失）。"""
        summary = product_stock_summary([{"stock": 60.5}, {"stock": 1.5}])
        assert summary["stock"] == 62.0, f"得 {summary['stock']!r}（静默截断）"
        assert summary["stock_source"] == "sku_sum"

    def test_product_stock_summary_avoids_binary_float_fuzz(self):
        """`0.1 + 0.2` 必须是 `0.3`（朴素 float 求和会得 `0.30000000000000004`）。"""
        assert product_stock_summary([{"stock": 0.1}, {"stock": 0.2}])["stock"] == 0.3

    def test_product_stock_summary_still_tolerates_dirty_value(self):
        """护栏（改前也绿，防重构引入崩溃）：单条脏值按「不计入」处理，不炸整商品。
        注意 `Decimal("abc")` 抛的是 `InvalidOperation`（**不是** ValueError）。"""
        assert product_stock_summary([{"stock": "abc"}, {"stock": 7}])["stock"] == 7
        assert product_stock_summary([{"id": "s1"}, {"stock": 7}])["stock"] == 7

    def test_product_stock_summary_no_sku_is_still_unknown(self):
        """不得因本次改造把「无 SKU」从 None 退回 0（会被读成「没货」）。"""
        for empty in ([], None):
            assert product_stock_summary(empty)["stock"] is None


# ── PR-047：超过 1 位小数 ⇒ 显式拒绝（fail-closed，可行动） ────────────────────


class TestOverOneDecimalRejected:
    def test_one_decimal_helper_accepts(self):
        """纯函数判据：≤1 位小数放行。**含 2.7 / -2.7**（浮点比较会误拒的那两个）。"""
        for value in (2.7, -2.7, 10, 60.5, "3.5", Decimal("0.1"), Decimal("-9")):
            parsed = _one_decimal_or_none(value)
            # 单一强断言（既有「不是 None」又有「值相等」——弱断言门禁要求触业务数据，
            # 且「None 也算过」的空断言不许留在新增文件里）
            assert parsed == Decimal(str(value)), f"{value!r} 被误拒或被改值（得 {parsed!r}）"

    def test_one_decimal_helper_rejects_over_precision(self):
        """纯函数判据：>1 位小数 ⇒ None（**不**四舍五入、**不**截断）。"""
        for value in (2.755, 0.05, -1.23, 1.23456, "2.755", Decimal("2.755")):
            assert _one_decimal_or_none(value) is None, f"{value!r} 未被判为超过 1 位小数"

    def test_one_decimal_helper_rejects_non_numeric(self):
        """非数值 / 非有限值 ⇒ None（走既有「缺少调整数量」或本单拒绝分支，不得当 0 执行）。"""
        for value in (None, "abc", True, float("nan"), float("inf")):
            assert _one_decimal_or_none(value) is None, f"{value!r} 未被判为非法"

    # [RETIRED #5247] TestOverOneDecimalRejected（3 例） 已退休：库存调整（adjust）已从 B 端移除（B 端只读化）：超精度拒绝路径不再存在，断言无对象。

    # [RETIRED #5247] test_over_precision_message_keeps_original_value 已退休：库存调整（adjust）已从 B 端移除（B 端只读化）：超精度拒绝文案不再存在，断言无对象。

    # [RETIRED #5247] test_over_precision_rejection_does_not_touch_api 已退休：库存调整（adjust）已从 B 端移除（B 端只读化）：写前拒绝路径不再存在，断言无对象。


# [RETIRED #5247] TestValidateInputGateAcceptsDecimal（2 例） 已退休：库存调整（adjust）已从 B 端移除（B 端只读化）：前置闸门只对该 action 生效，写 action 不存在则闸门规则无消费方，断言无对象。
