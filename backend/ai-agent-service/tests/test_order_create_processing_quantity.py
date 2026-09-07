"""
下单加工项数量规则（OR-014，issue #3005 回滚 #2986）

行业加工费按米计价、辅料（罗马圈/四爪钩等）含在加工费中 → 回滚 per_piece 与「每米数量」：
- per_meter → 数量 = 面料米数
- per_set / fixed → 数量 = 1
- per_area → 数量 = 宽×高
- 禁止「每米几个」的密度推导（per_piece 已移除）

本测试断言两层：
1. 工具层：order_create 完整透传 processing_info.processingItems（含 quantity/unitPrice/subtotal），processingFee = 各项单价×数量之和
2. Prompt 层：order prompt 固化按米规则、不含密度推导（perMeterQuantity 已从 prompt 移除）
"""
# case_ids: OR-014
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


@pytest.fixture
def tool():
    return OrderCreateTool()


@pytest.fixture
def agent_ctx():
    return ToolContext(tenant_id=1, user_id="agent_001", session_id="s", role="agent")


class TestOrderCreateProcessingPassthrough:
    """工具层：processing_info 含加工项，完整透传"""

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_per_meter_processing_item_passthrough(
        self, mock_get_client, tool, agent_ctx
    ):
        """per_meter 加工项（打孔 8 元/米 × 3 米）随 processing_info 透传，加工费计入"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value={"success": True, "data": {"id": "ORD-014", "orderNo": "ORD-014"}}
        )
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
                    "processingFee": 24.0,  # 8 元/米 × 3 米
                    "processingItems": [
                        {
                            "id": "pi-punch",
                            "name": "打孔（罗马圈）",
                            "unitPrice": 8.0,
                            "quantity": 3,
                            "unit": "米",
                            "pricingMethod": "per_meter",
                            "subtotal": 24.0,
                        }
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
        # per_meter 数量 = 面料米数 3
        assert item["quantity"] == 3
        assert item["unitPrice"] == 8.0
        assert item["pricingMethod"] == "per_meter"
        assert item["subtotal"] == 24.0
        # 加工费 = 单价 × 数量
        assert item["unitPrice"] * item["quantity"] == pi["processingFee"]

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_per_set_processing_item_passthrough(
        self, mock_get_client, tool, agent_ctx
    ):
        """per_set 加工项（帘头加工 50 元/套）数量 = 1"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value={"success": True, "data": {"id": "ORD-014b", "orderNo": "ORD-014b"}}
        )
        mock_get_client.return_value = mock_client

        items = [
            {
                "product_name": "遮光窗帘",
                "quantity": 3,
                "unit_price": 88.0,
                "subtotal": 314.0,
                "processing_info": {
                    "processingFee": 50.0,
                    "processingItems": [
                        {
                            "id": "pi-trim",
                            "name": "帘头加工",
                            "unitPrice": 50.0,
                            "quantity": 1,
                            "unit": "套",
                            "pricingMethod": "per_set",
                            "subtotal": 50.0,
                        }
                    ],
                },
            }
        ]

        result = await tool.execute(
            context=agent_ctx,
            customer_name="李女士",
            customer_phone="13800138000",
            items=items,
        )

        assert result.success is True
        sent = mock_client.post.call_args[1]["json_data"]
        pi = sent["items"][0]["processingInfo"]
        assert pi["processingItems"][0]["quantity"] == 1
        assert pi["processingItems"][0]["subtotal"] == 50.0
        assert pi["processingFee"] == 50.0


class TestOrderPromptQuantityRules:
    """Prompt 层：order prompt 固化按米规则、无密度推导"""

    def test_prompt_has_per_meter_rule(self):
        """prompt 明确 per_meter 数量=面料米数，禁止密度推导"""
        with open(PROMPT_PATH) as f:
            content = f.read()
        assert "per_meter" in content
        assert "面料米数" in content
        assert "每米几个" in content  # 明确禁止虚构密度的表述
        assert "perMeterQuantity" not in content

    def test_prompt_has_unit_price_per_meter_example(self):
        """prompt 含按米计价示例（打孔 8 元/米 × 3 米 = 24 元）"""
        with open(PROMPT_PATH) as f:
            content = f.read()
        assert "8 元/米" in content
        assert "24 元" in content

    def test_examples_show_per_meter_example(self):
        """EXAMPLES 例5b 改为 per_meter 按米示例，不含密度推导"""
        with open(EXAMPLES_PATH) as f:
            content = f.read()
        assert "每米几个" in content or "密度推导" in content
        assert "pricingMethod:\"per_meter\"" in content or "pricingMethod: \"per_meter\"" in content
        assert "perMeterQuantity" not in content