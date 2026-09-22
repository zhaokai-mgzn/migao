# case_ids: PR-052
"""商品级 `stock_quantity` 放宽为 1 位小数（0.1 米粒度）—— AI 工具层判据（issue #5150）

真值口径（承接 #5063 用户裁定逐字：「**库存米数是小数，1 位小数，必须改造**」）：
  · `product_manage` 的 `stock_quantity` 入参 schema = `number`（改前 `integer`）；
  · 最多 1 位小数（0.1 米粒度）⇒ **原值下发**：`60.5` 就是 `60.5`，不是 `int()` 截出来的 `60`；
  · 超过 1 位小数（`2.755`）⇒ **显式拒绝**（fail-closed）+ 可行动文案
    （1 位小数 / 0.1 米粒度 / **不做静默取整**），且**零 API 调用**（不得先打后端再报错）；
  · 整数场景**逐值不变**：`30` 下发的仍是 `30`（不是 `30.0`）；
  · 精度判据**复用** #5063 落在 `inventory_manage` 的既有助手（同一对象），**不新造**第二套判据/常量。

红证（改前形态，本人实跑）：
  · schema `stock_quantity.type == "integer"` + 实现 `int(stock_quantity)` ⇒ `60.5` 被**截成 60**
    ⇒ `test_create_sends_60_5_unchanged` / `test_update_sends_60_5_unchanged` 红；
  · 无小数位判定 ⇒ `2.755` 静默取整后照常下发（POST / PATCH 被调用）⇒ PR-052 拒绝类判据红；
  · `validate_input` 的前置闸门把 `stock_quantity` 声明成 `int` ⇒ `60.5` 在闸门就被判「类型错误」，
    数字**根本到不了**工具层（工具层再对也无效）⇒ `test_gate_accepts_one_decimal` 红。

⚠️ 不写 `round(x, 1) == x` 这类浮点比较：`2.7` 的二进制表示不精确，会把**合法**的 `2.7`
判成「超过 1 位小数」而误拒（误拒 = 客户办不成事）。
"""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.tools import inventory_manage, product_manage
from app.tools.product_manage import ProductManageTool
from app.tools.validate_input import ValidateInputTool


@pytest.fixture
def tool():
    return ProductManageTool()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.post = AsyncMock(return_value={"success": True, "data": {"id": "p-1"}})
    client.patch = AsyncMock(return_value={"success": True, "data": {"id": "p-1"}})
    return client


def _sent_stock(mock_client, verb):
    """取工具真正下发给 admin-api 的 `stock` 字面量。"""
    return getattr(mock_client, verb).call_args[1]["json_data"]["stock"]


# ── 判据 4（最少代码）：复用 #5063 的助手，不是复制第二套判据 ──────────────────


class TestReusesIssue5063Helpers:
    def test_precision_helpers_are_the_same_objects_as_inventory_manage(self):
        """同一对象 ⇒ 同一口径：两处各写一份迟早漂移成「2.755 在库存调整被拒、在建品被静默取整」。"""
        assert product_manage._one_decimal_or_none is inventory_manage._one_decimal_or_none
        assert product_manage._stock_number is inventory_manage._stock_number
        assert product_manage.STOCK_QUANTUM is inventory_manage.STOCK_QUANTUM
        assert product_manage.STOCK_QUANTUM == Decimal("0.1")


# ── 判据 1：1 位小数原值下发（LLM 可见 schema + 落库字面量） ────────────────────


class TestSchemaDeclaresNumber:
    def test_schema_type_is_number(self):
        """schema 声明 `integer` 会诱导 LLM 把 60.5 说成 60（工具层再对也白搭）。"""
        schema = ProductManageTool.parameters["properties"]["stock_quantity"]
        assert schema["type"] == "number"

    def test_schema_description_states_meter_unit_and_one_decimal(self):
        """单位与精度必须写进 description（LLM 唯一的取值依据）。"""
        desc = ProductManageTool.parameters["properties"]["stock_quantity"]["description"]
        assert "米" in desc, f"未说明单位（米）：{desc!r}"
        assert "1 位小数" in desc, f"未说明「最多 1 位小数」：{desc!r}"
        assert "60.5" in desc, f"未给 LLM 可见的 1 位小数示例：{desc!r}"


class TestOneDecimalAccepted:
    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_create_sends_60_5_unchanged(
        self, mock_get_client, tool, admin_tool_context, mock_client
    ):
        """`60.5` 必须**原值**下发（改前 `int(60.5)` ⇒ 60，半米凭空消失且不报错）。"""
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create", name="窗帘-欧式",
            category_id="cat-1", price=100.0, stock_quantity=60.5,
        )

        assert result.success is True, result.message
        stock = _sent_stock(mock_client, "post")
        assert stock == 60.5, f"1 位小数值被静默取整/截断成 {stock!r}"
        assert isinstance(stock, float), f"下发字面量形态不对：{stock!r}"

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_update_sends_60_5_unchanged(
        self, mock_get_client, tool, admin_tool_context, mock_client
    ):
        """update 分支（PATCH 图）与 create 同口径 —— 只改一处必红。"""
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update", product_id="p-1",
            stock_quantity=60.5,
        )

        assert result.success is True, result.message
        assert mock_client.patch.call_args.args[0] == "/api/admin/agent/products/p-1"
        stock = _sent_stock(mock_client, "patch")
        assert stock == 60.5, f"1 位小数值被静默取整/截断成 {stock!r}"
        assert isinstance(stock, float), f"下发字面量形态不对：{stock!r}"

    @pytest.mark.parametrize(
        "stock_quantity, expected",
        [
            (2.7, 2.7),            # 浮点比较会误拒的那一个（十进制字面量判据必须放行）
            (Decimal("2.7"), 2.7),
            (0.1, 0.1),
            (60.5, 60.5),
        ],
    )
    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_boundary_values_are_accepted(
        self, mock_get_client, tool, admin_tool_context, mock_client, stock_quantity, expected
    ):
        """边界逐值：`2.7` / `0.1` / `60.5` 全部**接受**（判定写成「必须整数」必红）。"""
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create", name="窗帘",
            category_id="cat-1", price=100.0, stock_quantity=stock_quantity,
        )

        assert result.success is True, result.message
        assert _sent_stock(mock_client, "post") == expected


# ── 判据 2：超过 1 位小数 ⇒ 显式拒绝 + 零 API 调用 ─────────────────────────────


class TestOverPrecisionRejected:
    @pytest.mark.parametrize(
        "action, extra",
        [
            ("create", {"name": "窗帘", "category_id": "cat-1", "price": 100.0}),
            ("update", {"product_id": "p-1"}),
        ],
    )
    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_over_precision_is_rejected_before_any_api_call(
        self, mock_get_client, tool, admin_tool_context, mock_client, action, extra
    ):
        """`2.755` ⇒ `success=False` + 说清「0.1 米粒度 / 最多 1 位小数」+ 带原值 +
        **一个字节都不许下发给 admin-api**（连查询都不发）。"""
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action=action, stock_quantity=2.755, **extra
        )

        assert result.success is False, f"超精度输入被放行（静默取整）：{result.message}"
        combined = f"{result.error or ''}{result.message or ''}{result.suggestion or ''}"
        assert "1 位小数" in combined, f"文案未说清精度口径：{combined!r}"
        assert "0.1" in combined, f"文案未说清 0.1 米粒度：{combined!r}"
        assert "2.755" in (result.message or ""), f"文案未带越界的原值：{result.message!r}"
        assert "不会" in (result.suggestion or ""), "建议里未说明不做静默取整"
        assert mock_client.post.call_count == 0, "超精度输入仍下发了创建请求"
        assert mock_client.patch.call_count == 0, "超精度输入仍下发了更新请求"
        assert mock_client.get.call_count == 0, "拒绝必须发生在任何 API 调用之前"

    @pytest.mark.parametrize("stock_quantity", [2.755, 0.05, -1.23, 1.23456])
    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_over_precision_never_round_trips(
        self, mock_get_client, tool, admin_tool_context, mock_client, stock_quantity
    ):
        """逐值：超精度一律拒绝，**不**四舍五入成 `2.8`、**不**截断成 `2.7`。"""
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update", product_id="p-1",
            stock_quantity=stock_quantity,
        )

        assert result.success is False
        assert mock_client.patch.call_count == 0

    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_rejection_is_not_masked_by_empty_update(
        self, mock_get_client, tool, admin_tool_context, mock_client
    ):
        """只有超精度 stock 一个字段时也必须报精度错，不得被「没有需要更新的字段」遮蔽
        （否则用户拿到的是「没东西可改」，而真正越界的那一位无人告知）。"""
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update", product_id="p-1",
            stock_quantity=2.755,
        )

        assert result.success is False
        assert "1 位小数" in f"{result.message or ''}{result.suggestion or ''}"


# ── 判据 3：整数场景逐值不变 ──────────────────────────────────────────────────


class TestIntegerScenarioUnchanged:
    @pytest.mark.parametrize("verb, action, extra", [
        ("post", "create", {"name": "窗帘", "category_id": "cat-1", "price": 100.0}),
        ("patch", "update", {"product_id": "p-1"}),
    ])
    @patch("app.tools.product_manage.get_admin_api_client")
    async def test_integer_stock_is_sent_as_int(
        self, mock_get_client, tool, admin_tool_context, mock_client, verb, action, extra
    ):
        """`30` 下发的仍是 `30`（不是 `30.0`）—— 整数场景逐值不变。"""
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action=action, stock_quantity=30, **extra
        )

        assert result.success is True, result.message
        stock = _sent_stock(mock_client, verb)
        assert stock == 30
        assert isinstance(stock, int) and not isinstance(stock, bool), (
            f"整数场景下发形态变了：{stock!r}（Java DTO 收到 30.0 也是合法，但逐值不变是硬判据）"
        )


# ── 前置闸门（validate_input）：不得把合法的 1 位小数判成类型错 ────────────────


class TestValidateInputGateAcceptsOneDecimal:
    """红证：规则 `"stock_quantity": {"type": int, ...}` ⇒ `isinstance(60.5, int)` 为假
    ⇒ 闸门直接返回「类型错误: 库存数量 (stock_quantity) 应为 int」，数字**根本到不了**
    `product_manage`（与 #5063 给 `inventory_manage.adjustment` 放宽类型同因同法）。"""

    @pytest.fixture
    def gate(self):
        return ValidateInputTool()

    @pytest.mark.parametrize("stock_quantity", [60.5, 30, 2.7])
    async def test_gate_accepts_one_decimal(self, gate, admin_tool_context, stock_quantity):
        result = await gate.execute(
            context=admin_tool_context, target_tool="product_manage", target_action="create",
            params={
                "name": "窗帘", "price": 100.0, "category_id": "cat-1",
                "stock_quantity": stock_quantity, "specifications": {},
            },
        )
        assert result.success is True, f"{stock_quantity!r} 被前置闸门拦下：{result.message}"

    async def test_gate_still_blocks_negative(self, gate, admin_tool_context):
        """放宽类型不得连带放宽既有护栏：负数仍被拦（`min=0`）。"""
        result = await gate.execute(
            context=admin_tool_context, target_tool="product_manage", target_action="create",
            params={
                "name": "窗帘", "price": 100.0, "category_id": "cat-1",
                "stock_quantity": -1, "specifications": {},
            },
        )
        assert result.success is False
        assert "stock_quantity" in (result.message or "")
