# case_ids: PR-047, PR-048
"""库存小数化（1 位小数 = 0.1 米粒度）—— AI 工具层判据（issue #5063）

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
from app.tools.validate_input import ValidateInputTool

STOCK_ENDPOINT = "/api/admin/agent/products/prod-1/stock"


@pytest.fixture
def tool():
    return InventoryManageTool()


def _mock_client(sku_stocks, new_stock):
    """构造 admin-api mock：GET 商品详情（SKU 明细 → 当前库存）、PATCH 库存端点（读回值）。"""
    client = AsyncMock()
    client.get = AsyncMock(return_value={
        "success": True,
        "data": {
            "name": "窗帘-欧式",
            "stock": 0,  # 商品级（非权威，故意误导）
            "skus": [{"stock": s} for s in sku_stocks],
        },
    })
    client.patch = AsyncMock(return_value={"success": True, "data": {"stock": new_stock}})
    return client


# ── PR-046：库存调整接受 1 位小数 ──────────────────────────────────────────────


class TestOneDecimalInputAccepted:
    def test_adjustment_schema_type_is_number(self):
        """LLM 可见 schema 必须声明为 number —— 声明 integer 时 LLM 不会传小数。

        红证：改前是 `"integer"`（`int` 类型声明会诱导 LLM 把 60.5 说成 60）。
        """
        schema = InventoryManageTool.parameters["properties"]["adjustment"]
        assert schema["type"] == "number"

    def test_schema_description_states_meter_unit_and_one_decimal(self):
        """单位与精度必须写进 description（LLM 唯一的取值依据）。"""
        desc = InventoryManageTool.parameters["properties"]["adjustment"]["description"]
        assert "米" in desc, f"未说明单位（米）：{desc!r}"
        assert "1 位小数" in desc, f"未说明「最多 1 位小数」：{desc!r}"
        assert "60.5" in desc, f"未给 LLM 可见的 1 位小数示例：{desc!r}"

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_adjustment_60_5_reaches_admin_api_as_float(
        self, mock_get_client, tool, admin_tool_context
    ):
        """`60.5` 必须**原值**下发（不是 60）——静默取整会让库存与实物不符。"""
        mock_client = _mock_client([60.5], new_stock=121.0)
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="adjust",
            product_id="prod-1", adjustment=60.5, reason="入库半卷",
        )

        assert result.success is True, result.message
        assert mock_client.patch.call_args.args[0] == STOCK_ENDPOINT
        body = mock_client.patch.call_args.kwargs["json_data"]
        assert body["adjustment"] == 60.5
        assert isinstance(body["adjustment"], float), (
            f"1 位小数值被改成 {body['adjustment']!r}（静默取整 / 截断）"
        )

    @pytest.mark.parametrize(
        "adjustment, expected_new",
        [
            (Decimal("2.7"), Decimal("102.7")),
            (Decimal("-2.7"), Decimal("97.3")),
            (Decimal("10"), Decimal("110")),
            (Decimal("60.5"), Decimal("160.5")),
        ],
    )
    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_one_decimal_boundaries_are_accepted(
        self, mock_get_client, tool, admin_tool_context, adjustment, expected_new
    ):
        """边界逐值：`2.7` / `-2.7` / `10` / `60.5` 全部**接受**（判定写成「必须整数」必红）。"""
        mock_client = _mock_client([100], new_stock=float(expected_new))
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="adjust",
            product_id="prod-1", adjustment=adjustment, reason="盘点",
        )

        assert result.success is True, result.message
        assert Decimal(str(result.data["new_stock"])) == expected_new
        body = mock_client.patch.call_args.kwargs["json_data"]
        assert Decimal(str(body["adjustment"])) == adjustment

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_integer_input_still_sent_as_int(
        self, mock_get_client, tool, admin_tool_context
    ):
        """整数场景**逐值不变**：下发 `10`（不是 `10.0`）—— Java DTO 若为整型，
        `10.0` 会被 Jackson 判非法，白丢一次写操作。"""
        mock_client = _mock_client([100], new_stock=110)
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="adjust",
            product_id="prod-1", adjustment=10, reason="盘点",
        )

        assert result.success is True, result.message
        body = mock_client.patch.call_args.kwargs["json_data"]
        assert body["adjustment"] == 10
        assert isinstance(body["adjustment"], int) and not isinstance(body["adjustment"], bool)
        assert result.data["new_stock"] == 110
        assert "110" in result.message

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_decimal_sum_and_message_have_no_float_fuzz(
        self, mock_get_client, tool, admin_tool_context
    ):
        """SKU 求和 `60.1 + 0.2 = 60.3`，再 `+0.4` ⇒ `60.7`。

        朴素浮点会得到 `60.70000000000001`：读回校验会误判「未生效」、
        文案会吐给用户一串毛刺数字。故求和与展示都必须走 `Decimal`。
        """
        mock_client = _mock_client([60.1, 0.2], new_stock=60.7)
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="adjust",
            product_id="prod-1", adjustment=0.4, reason="补料",
        )

        assert result.success is True, result.message
        assert result.data["previous_stock"] == 60.3, result.data
        assert result.data["new_stock"] == 60.7, result.data
        assert "60.7" in result.message
        assert "60.70000000000001" not in result.message and "60.300000000000004" not in result.message

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

    @pytest.mark.parametrize("adjustment", [2.755, 0.05, -1.23])
    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_over_precision_is_rejected_with_actionable_text(
        self, mock_get_client, tool, admin_tool_context, adjustment
    ):
        """>1 位小数 ⇒ `success=False` + 说清「库存按 0.1 粒度记，最多 1 位小数」+
        告诉用户改成 1 位小数后重试；**且一个字节都不许下发给 admin-api**。"""
        mock_client = _mock_client([100], new_stock=102.7)
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="adjust",
            product_id="prod-1", adjustment=adjustment, reason="盘点",
        )

        assert result.success is False
        combined = f"{result.error or ''}{result.message or ''}{result.suggestion or ''}"
        assert "1 位小数" in combined, f"文案未说清精度口径：{combined!r}"
        assert "0.1" in combined, f"文案未说清 0.1 粒度：{combined!r}"
        assert result.suggestion, "失败必须给出可行动建议（ToolResult 契约）"
        assert mock_client.patch.call_count == 0, "超精度输入被静默执行（未 fail-closed）"

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_over_precision_message_keeps_original_value(
        self, mock_get_client, tool, admin_tool_context
    ):
        """文案要带原始值（`2.755`），否则用户不知道哪一位越界。"""
        mock_get_client.return_value = _mock_client([100], new_stock=102.7)

        result = await tool.execute(
            context=admin_tool_context, action="adjust",
            product_id="prod-1", adjustment=2.755, reason="盘点",
        )

        assert result.success is False
        assert "2.755" in (result.message or ""), result.message

    @patch("app.tools.inventory_manage.get_admin_api_client")
    async def test_over_precision_rejection_does_not_touch_api(
        self, mock_get_client, tool, admin_tool_context
    ):
        """拒绝必须发生在**任何** API 调用之前（连查询都不必发）。"""
        mock_client = _mock_client([100], new_stock=102.7)
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="adjust",
            product_id="prod-1", adjustment=2.755, reason="盘点",
        )

        assert result.success is False
        assert mock_client.get.call_count == 0
        assert mock_client.patch.call_count == 0


class TestValidateInputGateAcceptsDecimal:
    """前置闸门（`validate_input`）不得把合法的 1 位小数判成类型错。

    红证（改前）：规则 `"adjustment": {"type": int, ...}` ⇒ `isinstance(60.5, int)` 为假
    ⇒ 闸门直接返回「类型错误: 调整数量 (adjustment) 应为 int」，数字**根本到不了**
    `inventory_manage`（工具层再对也无效）。
    """

    @pytest.fixture
    def gate(self):
        return ValidateInputTool()

    @pytest.mark.parametrize("adjustment", [60.5, 2.7, -2.7, 10])
    async def test_validate_input_gate_accepts_one_decimal(
        self, gate, admin_tool_context, adjustment
    ):
        result = await gate.execute(
            context=admin_tool_context, target_tool="inventory_manage", target_action="adjust",
            params={"product_id": "prod-001", "adjustment": adjustment, "reason": "盘点"},
        )
        assert result.success is True, f"{adjustment!r} 被前置闸门拦下：{result.message}"

    async def test_validate_input_gate_still_blocks_zero(self, gate, admin_tool_context):
        """放宽类型不得连带放宽既有护栏：`0` 仍被拦（Service 侧拒绝 0）。"""
        result = await gate.execute(
            context=admin_tool_context, target_tool="inventory_manage", target_action="adjust",
            params={"product_id": "prod-001", "adjustment": 0, "reason": "盘点"},
        )
        assert result.success is False
        assert "adjustment" in (result.message or "")
