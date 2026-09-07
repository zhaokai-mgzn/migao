"""
下单加工项数量自动推导（OR-014，issue #2986）

数量由系统按计价方式推导（LLM 依据 order prompt 规则计算后随 processing_info 透传给后端）：
- per_meter → 数量 = 面料米数
- per_piece + perMeterQuantity > 0 → 数量 = ceil(面料米数 × 每米数量)（如打孔 3 米 × 6 个/米 = 18 个）
- per_piece 无密度 / per_set / fixed / per_area → 数量 = 1

本测试断言两层：
1. 工具层：order_create 完整透传 processing_info.processingItems（含推导后的 quantity/unitPrice/subtotal），processingFee = 各项单价×数量之和
2. Prompt 层：order prompt 固化「数量自动推导」与「用户零感知数量（确认只展示名称+金额）」规则
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
    """工具层：processing_info 含推导后的加工项，完整透传"""

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_processing_items_passthrough(
        self, mock_get_client, tool, agent_ctx
    ):
        """per_piece 加工项（打孔 1.5 元/个 × 18 个）随 processing_info 透传，加工费计入"""
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
                "subtotal": 291.0,  # 面料 264 + 打孔加工 27
                "processing_info": {
                    "colorId": "c1",
                    "colorName": "米白",
                    "sellingMethod": "bulk_cut",
                    "doorWidth": "2.8米",
                    "processingFee": 27.0,  # 1.5 × 18（3 米 × 6 个/米 = 18 个）
                    "processingItems": [
                        {
                            "id": "pi-punch-pc",
                            "name": "打孔（罗马圈，按个）",
                            "unitPrice": 1.5,
                            "quantity": 18,
                            "unit": "个",
                            "pricingMethod": "per_piece",
                            "subtotal": 27.0,
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
        assert pi["processingFee"] == 27.0
        assert len(pi["processingItems"]) == 1
        item = pi["processingItems"][0]
        # 推导数量 18 个随结构透传（用户不感知，仅内部携带）
        assert item["quantity"] == 18
        assert item["unitPrice"] == 1.5
        assert item["pricingMethod"] == "per_piece"
        assert item["subtotal"] == 27.0
        # 加工费 = 单价 × 推导数量
        assert item["unitPrice"] * item["quantity"] == pi["processingFee"]

    @patch("app.tools.order_create.get_admin_api_client")
    async def test_per_meter_quantity_is_fabric_meters(
        self, mock_get_client, tool, agent_ctx
    ):
        """per_meter 加工项（高温定型 ¥20/米）数量 = 面料米数"""
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
                "subtotal": 324.0,
                "processing_info": {
                    "processingFee": 60.0,
                    "processingItems": [
                        {
                            "id": "pi_shape_high",
                            "name": "高温定型",
                            "unitPrice": 20.0,
                            "quantity": 3,  # = 面料米数
                            "unit": "米",
                            "pricingMethod": "per_meter",
                            "subtotal": 60.0,
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
        assert pi["processingItems"][0]["quantity"] == 3
        assert pi["processingItems"][0]["subtotal"] == 60.0
        assert pi["processingFee"] == 60.0


class TestOrderPromptQuantityRules:
    """Prompt 层：order prompt 固化数量推导与数量隐藏规则"""

    def test_prompt_has_server_side_derivation_rule(self):
        """prompt 明确「数量自动推导 + 禁止询问需要几个」"""
        with open(PROMPT_PATH) as f:
            content = f.read()
        assert "数量自动推导" in content
        assert "禁止问" in content
        assert "ceil(面料米数" in content
        assert "per_meter" in content and "perMeterQuantity" in content

    def test_prompt_hides_quantity_from_user(self):
        """prompt 明确「确认卡与回复只展示名称+金额，不出现数量字眼」"""
        with open(PROMPT_PATH) as f:
            content = f.read()
        assert "加工项+金额" in content
        assert "不出现数量" in content

    def test_examples_show_derived_quantity_example(self):
        """EXAMPLES 有 per_piece+密度 推导示例（3 米×6 个/米=18 个）"""
        with open(EXAMPLES_PATH) as f:
            content = f.read()
        assert "每米数量" in content or "perMeterQuantity" in content
        assert "打孔" in content