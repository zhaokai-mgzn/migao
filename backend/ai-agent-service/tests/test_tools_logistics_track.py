"""
物流查询 Tool 单元测试

测试 LogisticsTrackTool.execute() 的各种场景
"""

import pytest
from unittest.mock import patch, AsyncMock

from app.tools.logistics_track import LogisticsTrackTool
from app.tools.base import ToolContext, ToolResult


@pytest.fixture
def tool():
    return LogisticsTrackTool()


@pytest.fixture
def sample_order_with_logistics():
    """模拟包含物流信息的订单响应"""
    return {
        "success": True,
        "data": {
            "id": "order_001",
            "status": "shipped",
            "logistics": {
                "trackingNo": "SF1234567890",
                "company": "顺丰速运",
            },
        },
    }


@pytest.fixture
def sample_order_without_logistics():
    """模拟未发货订单响应"""
    return {
        "success": True,
        "data": {
            "id": "order_002",
            "status": "pending",
            "logistics": {},
        },
    }


class TestLogisticsTrackByOrder:
    """物流查询 - 通过订单号查询"""

    @patch("app.tools.logistics_track.get_admin_api_client")
    async def test_logistics_track_by_order_success(
        self, mock_get_client, tool, sample_tool_context, sample_order_with_logistics
    ):
        """通过订单号成功查询物流"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=sample_order_with_logistics)
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            order_id="order_001",
        )

        assert result.success is True
        assert result.data["tracking_number"] == "SF1234567890"
        assert result.data["company"] == "顺丰速运"
        assert "顺丰速运" in result.message

    @patch("app.tools.logistics_track.get_admin_api_client")
    async def test_logistics_track_order_not_found(
        self, mock_get_client, tool, sample_tool_context
    ):
        """订单不存在"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False,
            "error": {"message": "订单不存在"},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            order_id="order_nonexist",
        )

        assert result.success is False
        assert "未找到" in result.message or "订单" in result.message

    @patch("app.tools.logistics_track.get_admin_api_client")
    async def test_logistics_track_order_not_shipped(
        self, mock_get_client, tool, sample_tool_context, sample_order_without_logistics
    ):
        """订单未发货"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=sample_order_without_logistics)
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            order_id="order_002",
        )

        assert result.success is False
        assert "未发货" in result.error or "未发货" in result.message


class TestLogisticsTrackByNumber:
    """物流查询 - 通过快递单号查询"""

    @patch("app.tools.logistics_track.get_admin_api_client")
    async def test_logistics_track_by_tracking_number(
        self, mock_get_client, tool, sample_tool_context
    ):
        """通过快递单号查询（返回 mock 数据）"""
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            tracking_number="SF9876543210",
        )

        # 当前实现使用 mock 数据
        assert result.success is True
        assert result.data is not None
        assert "tracking_number" in result.data
        assert "traces" in result.data


class TestLogisticsTrackValidation:
    """物流查询 - 参数验证"""

    async def test_logistics_track_no_params(self, tool, sample_tool_context):
        """不提供任何参数"""
        result = await tool.execute(
            context=sample_tool_context,
        )

        assert result.success is False
        assert "缺少" in result.error or "请提供" in result.message

    async def test_logistics_track_permission_denied(self, tool, unauthorized_tool_context):
        """无权限角色查询被拒绝"""
        result = await tool.execute(
            context=unauthorized_tool_context,
            order_id="order_001",
        )

        assert result.success is False
        assert "权限" in result.error or "权限" in result.message


class TestLogisticsTrackError:
    """物流查询 - 异常处理"""

    @patch("app.tools.logistics_track.get_admin_api_client")
    async def test_logistics_track_network_error_fallback(
        self, mock_get_client, tool, sample_tool_context
    ):
        """网络异常时返回 mock 数据（优雅降级）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Connection timeout"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            order_id="order_001",
        )

        # execute 在异常时调用 _get_mock_result 优雅降级
        assert result.success is True
        assert result.data is not None
        assert "traces" in result.data


class TestLogisticsTrackMockResult:
    """物流查询 - _get_mock_result 方法"""

    def test_get_mock_result_with_tracking_number(self, tool):
        """Mock 结果包含快递单号"""
        result = tool._get_mock_result("SF111222333")

        assert result.success is True
        assert result.data["tracking_number"] == "SF111222333"
        assert result.data["status"] == "in_transit"
        assert len(result.data["traces"]) > 0

    def test_get_mock_result_with_company(self, tool):
        """Mock 结果包含快递公司"""
        result = tool._get_mock_result("SF111222333", company="中通快递")

        assert result.data["company"] == "中通快递"

    def test_get_mock_result_with_order_id(self, tool):
        """Mock 结果包含订单号"""
        result = tool._get_mock_result("SF111222333", order_id="order_999")

        assert result.data["order_id"] == "order_999"

    def test_get_mock_result_default_values(self, tool):
        """Mock 结果默认值"""
        result = tool._get_mock_result(None)

        assert result.data["tracking_number"] == "SF1234567890"
        assert result.data["company"] == "顺丰速运"


class TestLogisticsTrackStatusText:
    """物流查询 - STATUS_TEXT_MAP 状态映射"""

    def test_status_text_known_statuses(self, tool):
        """已知状态映射"""
        from app.tools.logistics_track import STATUS_TEXT_MAP

        assert STATUS_TEXT_MAP["pending"] == "待发货"
        assert STATUS_TEXT_MAP["in_transit"] == "运输中"
        assert STATUS_TEXT_MAP["delivered"] == "已签收"
        assert STATUS_TEXT_MAP["out_for_delivery"] == "派送中"

    def test_status_text_unknown_status(self, tool):
        """未知状态使用 dict.get 返回默认值"""
        from app.tools.logistics_track import STATUS_TEXT_MAP

        assert STATUS_TEXT_MAP.get("custom_status", "未知") == "未知"
