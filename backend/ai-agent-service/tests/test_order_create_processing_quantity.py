"""
下单加工项数量口径（OR-014 / OR-028；issue #3005 回滚 + issue #4882 收口）

行业加工费按米计价、辅料（罗马圈/四爪钩等）含在加工费中 ⇒ **数量口径只有一个**：
`processingItems[i].quantity` = **该订单行的面料米数**（= items[i].quantity），
禁止「每米几个」的密度推导。

issue #4882：加工项**不再有单价与计价方式** ⇒ `processingItems[]` 每项只剩
`{id, name, quantity}`（`unit` 可选）；`unitPrice` / `pricingMethod` / `subtotal`
以及按计价方式（per_meter/per_set/per_area/fixed）分支推导数量的规则**全部退场**。

本测试断言两层：
1. 工具层：order_create 透传 processing_info.processingItems（quantity = 面料米数），
   且**不**凭空造出 unitPrice/pricingMethod/subtotal（红证：造出来即断言失败）。
2. Prompt 层：order prompt 固化「= 面料米数」+ 保留「禁止每米几个的密度推导」，
   且不再有计价方式枚举推导。
"""
# case_ids: OR-014, OR-028
import os
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.order_create import OrderCreateTool
from app.tools.base import ToolContext

PROMPT_PATH = os.path.join(
    os.path.dirname(__file__),
    "../app/graph/skills/references/prompts/order.md",
)
EXAMPLES_PATH = os.path.join(
    os.path.dirname(__file__),
    "../app/graph/skills/references/EXAMPLES-order.md",
)

# issue #4882：加工项明细里**不得**再出现的键（下发已删键 = 契约漂移/伪造金额）
_REMOVED_ITEM_KEYS = ("unitPrice", "pricingMethod", "subtotal")


@pytest.fixture
def tool():
    return OrderCreateTool()


@pytest.fixture
def agent_ctx():
    return ToolContext(tenant_id=1, user_id="agent_001", session_id="s", role="agent")


def _with_library(client, price, name="遮光窗帘", pid="p1"):
    """给 mock client 装上商品库 GET（order_create 单价接地校验用）。"""
    async def _get(path, params=None, **kwargs):
        if path.rstrip("/").endswith("/products"):
            return {"success": True, "data": {"items": [{"id": pid, "name": name}], "total": 1}}
        return {"success": True, "data": {
            "id": pid, "name": name, "price": price, "basePrice": price,
            "skus": [{"id": f"{pid}-1", "skuCode": "SKU-1", "colorName": "米白",
                      "price": price, "stock": 1}],
        }}
    client.get = AsyncMock(side_effect=_get)
    return client


class TestOrderCreateProcessingPassthrough:
    """工具层：processing_info 含加工项，按 #4882 后的新契约透传"""

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_processing_item_quantity_is_fabric_meters(
        self, mock_get_client, tool, agent_ctx
    ):
        """打孔加工项：数量 = 面料米数 3；明细里不得出现单价/计价方式/小计。

        红证：改前 `processingItems[]` 每项会被要求带 unitPrice/pricingMethod/subtotal
        （本用例逐个断言它们**不存在**）；若有人照旧 prompt 把单价塞回来，本用例红。
        """
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value={"success": True, "data": {"id": "ORD-014", "orderNo": "ORD-014"}}
        )
        _with_library(mock_client, 88.0)
        mock_get_client.return_value = mock_client

        items = [
            {
                "product_name": "遮光窗帘",
                "quantity": 3,
                "unit_price": 88.0,
                "subtotal": 288.0,  # 面料 264 + 打孔加工 24
                "processing_info": {
                    "colorId": "c1",
                    "colorName": "米白",
                    "sellingMethod": "bulk_cut",
                    "doorWidth": "2.8米",
                    "processingFee": 24.0,
                    "processingItems": [
                        {"id": "pi-punch", "name": "打孔（罗马圈）", "quantity": 3, "unit": "米"}
                    ],
                },
            }
        ]

        result = await tool.execute(
            context=agent_ctx,
            customer_name="王先生",
            customer_phone="13900139000",
            items=items,
        )

        assert result.success is True
        sent = mock_client.post.call_args[1]["json_data"]
        pi = sent["items"][0]["processingInfo"]
        assert pi["processingFee"] == 24.0
        assert len(pi["processingItems"]) == 1
        item = pi["processingItems"][0]
        # 数量口径：= 该订单行的面料米数（唯一口径，issue #4882 后不再按计价方式推导）
        assert item["quantity"] == 3
        assert item["quantity"] == sent["items"][0]["quantity"], (
            "加工数量必须 = 该订单行面料米数（items[i].quantity）")
        assert item["unit"] == "米"
        for key in _REMOVED_ITEM_KEYS:
            assert key not in item, f"加工项明细不得出现已删键 {key}（issue #4882）"

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_decimal_fabric_meters_preserved(
        self, mock_get_client, tool, agent_ctx
    ):
        """小数面料米数（2.5 米）必须保真落到加工数量（issue #3666 的小数口径仍成立）。

        改前：数量按计价方式推导，per_area 的面积才是小数；现在口径统一 = 面料米数，
        2.5 米就是 2.5 —— 任何截断都会让加工数量与订单行不一致。
        """
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value={"success": True, "data": {"id": "ORD-3666", "orderNo": "ORD-3666"}}
        )
        _with_library(mock_client, 88.0)
        mock_get_client.return_value = mock_client

        items = [
            {
                "product_name": "遮光窗帘",
                "quantity": 2.5,
                "unit_price": 88.0,
                "subtotal": 240.0,  # 面料 220 + 定型加工 20
                "processing_info": {
                    "sellingMethod": "bulk_cut",
                    "doorWidth": "2.8米",
                    "processingFee": 20.0,
                    "processingItems": [
                        {"id": "pi-shape", "name": "定型", "quantity": 2.5, "unit": "米"}
                    ],
                },
            }
        ]

        result = await tool.execute(
            context=agent_ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=items,
        )

        assert result.success is True, f"小数米数被误拦：{result.error} {(result.message or '')}"
        sent = mock_client.post.call_args[1]["json_data"]
        entry = sent["items"][0]
        assert entry["quantity"] == pytest.approx(2.5), "明细数量 2.5 米必须保真透传"
        pi = entry["processingInfo"]
        assert pi["processingItems"][0]["quantity"] == pytest.approx(2.5), (
            "加工数量 = 面料米数 2.5（不得截断成 2）")


class TestOrderPromptQuantityRules:
    """Prompt 层：order prompt 固化「= 面料米数」、保留禁密度推导、无计价方式"""

    def test_prompt_states_quantity_is_fabric_meters(self):
        """prompt 明确 processingItems.quantity = 该行面料米数，且禁止密度推导。"""
        with open(PROMPT_PATH) as f:
            content = f.read()
        assert "面料米数" in content
        assert "每米几个" in content  # 明确禁止虚构密度的表述
        assert "perMeterQuantity" not in content

    def test_prompt_has_no_pricing_method_breakdown(self):
        """#4882：prompt 不得再按计价方式分支推导数量（该字段已删除）。

        注意：提示词里**可以**出现「禁止写 pricingMethod」这种**禁令**表述
        （把已删键显式点名比含糊更安全）；不得出现的是**计价方式取值**
        （per_meter/per_set/per_area/per_piece）与「按 pricingMethod 推导」的分支口径。
        """
        with open(PROMPT_PATH) as f:
            content = f.read()
        for token in ("per_meter", "per_set", "per_area", "per_piece"):
            assert token not in content, (
                f"order prompt 仍出现计价方式取值 {token!r}（issue #4882 已删该字段）")
        assert "按 pricingMethod 推导" not in content

    def test_examples_show_fabric_meters_rule(self):
        """EXAMPLES 例5b 用「面料米数」口径，且加工项明细无单价/计价方式。"""
        with open(EXAMPLES_PATH) as f:
            content = f.read()
        assert "面料米数" in content
        assert "每米几个" in content or "密度推导" in content
        assert "pricingMethod" not in content
        assert "perMeterQuantity" not in content
