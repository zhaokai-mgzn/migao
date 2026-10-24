"""ProcessingOrderGenerateTool 单元测试 — 加工单生成（issue #3340）"""
# case_ids: PG-001, PG-002, PG-003, PG-004, UI-115
import pytest
from unittest.mock import AsyncMock, patch
from app.tools.processing_order_generate import ProcessingOrderGenerateTool


@pytest.fixture
def tool():
    return ProcessingOrderGenerateTool()


class TestGenerate:
    @patch("app.tools.processing_order_generate.get_admin_api_client")
    async def test_generate_success(self, mock_get_client, tool, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": [{"orderRef": "order-1", "success": True, "processingOrderNo": "JG-20260912-0001"}],
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, order_ids=["order-1", "ORD-xxx"])

        assert result.success is True
        assert "已生成 1 个加工单" in result.message
        call_args = mock_client.post.call_args
        assert "processing-orders/generate" in call_args[0][0]
        assert call_args.kwargs["json_data"] == {"orderIds": ["order-1", "ORD-xxx"]}

    @patch("app.tools.processing_order_generate.get_admin_api_client")
    async def test_generate_partial_failure(self, mock_get_client, tool, admin_tool_context):
        """部分失败：已存在加工单/无加工项 → 结果列表带失败原因（幂等/条件化联动）"""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": [
                {"orderRef": "order-1", "success": True, "processingOrderNo": "JG-1"},
                {"orderRef": "order-2", "success": False, "message": "订单已有加工单 JG-2，请勿重复生成"},
                {"orderRef": "order-3", "success": False, "message": "订单无加工项，无需生成加工单"},
            ],
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, order_ids=["order-1", "order-2", "order-3"])

        assert result.success is True  # 至少一个成功
        assert "1/3" in result.message
        assert "已有加工单" in result.message
        assert "无加工项" in result.message

    async def test_generate_empty_list(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, order_ids=[])
        assert result.success is False
        assert "请提供" in result.message

    async def test_generate_too_many(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, order_ids=[f"o{i}" for i in range(101)])
        assert result.success is False
        assert "100" in result.message

    async def test_permission_denied(self, tool, unauthorized_tool_context):
        result = await tool.execute(context=unauthorized_tool_context, order_ids=["order-1"])
        assert result.success is False
        assert "没有权限" in result.message


class TestSelfDescriptionIsPerKind:
    """工具**自述**必须按型正确（issue #7079 第 5 包；用例 UI-115 判据 7）。

    病根：工具本体**不做自过滤**（直接把 order_ids 打给后端，而后端 `ProcessingOrderService.prepare`
    的门是 `snapshot.isEmpty()`、`buildSnapshot` 对 `saleForm=布料` 的行**保留** ⇒ 卖布单**能**生成
    出库作业单），但它的 description / 失败 suggestion 写着「仅已确认且**含加工项**的订单可生成」
    ⇒ 模型据此可能**拒调**，而发货守卫的文案恰恰让商家「让黄金策生成出库作业单」——两个面互相矛盾。

    红证（实跑）：把 description 那句改回「仅已确认且含加工项的订单可生成」⇒ 判据 1 红；
    把失败 suggestion 改回「请确认订单已确认且含加工项」⇒ 判据 2 红。
    """

    def test_description_says_fabric_sale_orders_are_supported(self, tool):
        desc = ProcessingOrderGenerateTool.description
        # 判据 1：说明里必须出现卖布单/出库作业单这一型（否则模型会以为只支持含加工项）
        assert "卖布" in desc or "出库作业单" in desc, desc
        # 且**不再**留下「只有含加工项才可生成」的单侧措辞
        assert "仅已确认且含加工项" not in desc, desc

    async def test_failure_suggestion_is_per_kind_and_actionable(self, tool, admin_tool_context, monkeypatch):
        """判据 2：后端整体失败时的 suggestion 必须按型说清「哪种单可生成」，可行动。"""
        from app.tools import processing_order_generate as mod

        class _Client:
            async def post(self, *a, **kw):
                return {"success": False, "error": {"message": "boom"}}

        monkeypatch.setattr(mod, "get_admin_api_client", lambda: _Client())
        result = await tool.execute(context=admin_tool_context, order_ids=["order-1"])
        assert result.success is False
        assert "卖布" in (result.suggestion or ""), result.suggestion
        assert "含加工项" in (result.suggestion or ""), result.suggestion
