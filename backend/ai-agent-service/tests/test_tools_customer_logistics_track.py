"""
C 端"查物流" Tool 单元测试（小布专用 customer_logistics_track）

铁律覆盖（OR-012）：
1. 仅查当前用户已发货(在途)订单的物流（/orders/mine?status=shipped 后端强制按用户过滤）
2. 拒绝用户直接提供快递单号查询（无 tracking_number 参数，传了也拒绝）
3. 指定订单号必须在本人已发货订单中，否则拒绝
4. 详情 ownership 防御（customerId 不符跳过）；无运单号跳过不编造
5. 非 customer 角色 / 缺用户标识一律拒绝
"""
# case_ids: OR-012

import pytest
from unittest.mock import patch, AsyncMock

from app.tools.customer_logistics_track import CustomerLogisticsTrackTool


@pytest.fixture
def tool():
    return CustomerLogisticsTrackTool()


@pytest.fixture
def mock_settings():
    """物流 API 未配置 → 轨迹查询走 Mock 降级（不依赖外网）"""
    with patch("app.tools.logistics_track.settings") as mock_settings:
        mock_settings.LOGISTICS_APPCODE = ""
        mock_settings.LOGISTICS_API_URL = "https://fake.api/kdi"
        yield mock_settings


def _mine_response(*orders):
    """构造 /orders/mine?status=shipped 的响应"""
    return {"success": True, "data": {"items": list(orders), "total": len(orders)}}


def _detail_response(order_id, tracking_no="SF1234567890", company="顺丰速运", customer_id=None, status="shipped"):
    """构造 /orders/{id} 详情响应"""
    data = {
        "id": order_id,
        "status": status,
        "logistics": {"trackingNo": tracking_no, "logisticsCompany": company},
    }
    if customer_id is not None:
        data["customerId"] = customer_id
    return {"success": True, "data": data}


def _shipped_order(order_id="order_001", order_no="ORD-20260901-0001"):
    return {"id": order_id, "orderNo": order_no, "status": "shipped"}


class TestCustomerLogisticsTrack:
    """查物流 - 核心铁律"""

    @patch("app.tools.customer_logistics_track.get_admin_api_client")
    async def test_list_own_in_transit_orders(
        self, mock_get_client, tool, sample_tool_context, mock_settings
    ):
        """列出本人已发货订单的物流（列表 → 详情 → 轨迹 mock 降级）"""
        mock_client = AsyncMock()

        async def mock_get(url, **kwargs):
            if "orders/mine" in url:
                return _mine_response(_shipped_order())
            if "/api/admin/orders/" in url:
                return _detail_response("order_001")
            return {"success": False}

        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=sample_tool_context, action="list")

        assert result.success is True
        assert result.data["total"] == 1
        item = result.data["logistics_list"][0]
        assert item["order_no"] == "ORD-20260901-0001"
        assert item["tracking_number"] == "SF1234567890"
        assert item["company"] == "顺丰速运"
        assert item["status"] == "in_transit"
        # 卡片数据与列表首项一致
        assert result.data["logistics"] == item
        # /mine 必须带 status=shipped 筛选
        mine_call = [c for c in mock_client.get.call_args_list if "orders/mine" in str(c.args[0])]
        assert mine_call, "应调用 /orders/mine"
        assert mine_call[0].kwargs["params"]["status"] == "shipped"

    @patch("app.tools.customer_logistics_track.get_admin_api_client")
    async def test_no_in_transit_orders(
        self, mock_get_client, tool, sample_tool_context, mock_settings
    ):
        """无在途订单 → 空结果友好提示"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mine_response())
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=sample_tool_context)

        assert result.success is True
        assert result.data["logistics_list"] == []
        assert "在途" in (result.message or "")

    @patch("app.tools.customer_logistics_track.get_admin_api_client")
    async def test_narrow_to_own_order(
        self, mock_get_client, tool, sample_tool_context, mock_settings
    ):
        """指定订单号（本人已发货）→ 只返回该订单物流"""
        mock_client = AsyncMock()

        async def mock_get(url, **kwargs):
            if "orders/mine" in url:
                return _mine_response(
                    _shipped_order("order_001", "ORD-20260901-0001"),
                    _shipped_order("order_002", "ORD-20260901-0002"),
                )
            if "/api/admin/orders/" in url:
                return _detail_response("order_002", tracking_no="YT9876543210", company="圆通速递")
            return {"success": False}

        mock_client.get = mock_get
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context, order_id="ORD-20260901-0002"
        )

        assert result.success is True
        assert result.data["total"] == 1
        assert result.data["logistics_list"][0]["order_no"] == "ORD-20260901-0002"
        assert result.data["logistics_list"][0]["tracking_number"] == "YT9876543210"

    @patch("app.tools.customer_logistics_track.get_admin_api_client")
    async def test_reject_order_not_in_transit(
        self, mock_get_client, tool, sample_tool_context, mock_settings
    ):
        """指定订单不在本人已发货订单中 → 拒绝"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mine_response(_shipped_order()))
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context, order_id="ORD-OTHER-0001"
        )

        assert result.success is False
        assert "在途" in (result.error or "") or "在途" in (result.message or "")

    async def test_reject_direct_tracking_number(
        self, tool, sample_tool_context, mock_settings
    ):
        """铁律：用户提供快递单号 → 必须拒绝（不支持物流号直查）"""
        result = await tool.execute(
            context=sample_tool_context,
            tracking_number="SF1234567890",
        )

        assert result.success is False
        assert "快递单号" in (result.error or "") or "快递单号" in (result.message or "")

    async def test_permission_denied_for_non_customer(
        self, tool, admin_tool_context, mock_settings
    ):
        """非 customer 角色（商家员工/管理员）→ 拒绝（用 B 端 logistics_track）"""
        result = await tool.execute(context=admin_tool_context)

        assert result.success is False
        assert "仅限顾客" in (result.message or "")

    async def test_missing_user_id_rejected(self, tool, mock_settings):
        """缺真实用户标识 → 拒绝（防跨用户数据泄露）"""
        from app.tools.base import ToolContext

        ctx = ToolContext(
            tenant_id=1, user_id="internal-service", session_id="s", role="customer"
        )
        result = await tool.execute(context=ctx)

        assert result.success is False
        assert "用户" in (result.message or "")


class TestCustomerLogisticsTrackDefense:
    """查物流 - 防御纵深"""

    @patch("app.tools.customer_logistics_track.get_admin_api_client")
    async def test_skip_order_with_ownership_mismatch(
        self, mock_get_client, tool, sample_tool_context, mock_settings
    ):
        """详情 customerId 与当前用户不符 → 跳过该订单（防御，不应发生）"""
        mock_client = AsyncMock()

        async def mock_get(url, **kwargs):
            if "orders/mine" in url:
                return _mine_response(_shipped_order())
            if "/api/admin/orders/" in url:
                # 列表是用户自己的，但详情返回了别人的 customerId → 视为异常，跳过
                return _detail_response("order_001", customer_id="other_user_999")
            return {"success": False}

        mock_client.get = mock_get
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=sample_tool_context)

        assert result.success is True
        assert result.data["logistics_list"] == []

    @patch("app.tools.customer_logistics_track.get_admin_api_client")
    async def test_skip_order_without_tracking_no(
        self, mock_get_client, tool, sample_tool_context, mock_settings
    ):
        """已发货但无运单号（异常数据）→ 跳过，不编造物流"""
        mock_client = AsyncMock()

        async def mock_get(url, **kwargs):
            if "orders/mine" in url:
                return _mine_response(_shipped_order())
            if "/api/admin/orders/" in url:
                return {
                    "success": True,
                    "data": {"id": "order_001", "status": "shipped", "logistics": {}},
                }
            return {"success": False}

        mock_client.get = mock_get
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=sample_tool_context)

        assert result.success is True
        assert result.data["logistics_list"] == []

    @patch("app.tools.customer_logistics_track.get_admin_api_client")
    async def test_mine_list_rejected(
        self, mock_get_client, tool, sample_tool_context, mock_settings
    ):
        """/orders/mine 失败 → 返回失败并给引导"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            return_value={"success": False, "error": {"message": "缺少用户标识"}}
        )
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=sample_tool_context)

        assert result.success is False
        assert result.suggestion
