"""
测试 app.tools.aftersale_create — C端售后创建工具

业务真值 #2: 客户可以创建售后工单→必须关联已有订单号，只能创建自己的工单
"""
import pytest
from unittest.mock import patch, AsyncMock


class TestAftersaleCreatePermission:
    """权限校验 — customer角色可创建售后工单"""

    async def test_customer_role_allowed(self, sample_tool_context):
        """customer角色可以创建售后工单"""
        from app.tools.aftersale_create import AftersaleCreateTool
        tool = AftersaleCreateTool()
        assert tool.check_permission(sample_tool_context) is True

    async def test_guest_role_denied(self, unauthorized_tool_context):
        """guest不能创建售后工单"""
        from app.tools.aftersale_create import AftersaleCreateTool
        tool = AftersaleCreateTool()
        assert tool.check_permission(unauthorized_tool_context) is False


class TestAftersaleCreateSuccess:
    """成功创建售后工单"""

    @patch("app.tools.aftersale_create.get_admin_api_client")
    async def test_customer_creates_aftersale_with_order_id(self, mock_get_client, sample_tool_context):
        """客户关联已有订单号创建售后工单"""
        from app.tools.aftersale_create import AftersaleCreateTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {
                "id": "as-cust-001",
                "ticketNo": "AS-2024-C001",
                "orderId": "order-123",
                "ticketType": "refund",
                "status": "pending",
            },
        })
        mock_get_client.return_value = mock_client

        tool = AftersaleCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            order_id="order-123",
            ticket_type="refund",
            reason="商品与描述不符",
        )

        assert result.success is True
        assert "as-cust-001" in str(result.data)
        mock_client.post.assert_called_once()

        # 验证传入了正确的参数
        call_args = mock_client.post.call_args
        json_data = call_args[1]["json_data"]
        assert json_data["orderId"] == "order-123"
        assert json_data["ticketType"] == "refund"
        assert json_data["source"] == "customer"


class TestAftersaleCreateValidation:
    """参数校验"""

    async def test_missing_order_id_returns_error(self, sample_tool_context):
        """缺少order_id返回错误+suggestion"""
        from app.tools.aftersale_create import AftersaleCreateTool

        tool = AftersaleCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            order_id="",
            ticket_type="refund",
            reason="商品有问题",
        )

        assert result.success is False
        assert result.suggestion is not None

    async def test_missing_ticket_type_returns_error(self, sample_tool_context):
        """缺少ticket_type返回错误+suggestion"""
        from app.tools.aftersale_create import AftersaleCreateTool

        tool = AftersaleCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            order_id="order-123",
            reason="商品有问题",
        )

        assert result.success is False
        assert result.suggestion is not None

    async def test_missing_reason_returns_error(self, sample_tool_context):
        """缺少reason返回错误+suggestion"""
        from app.tools.aftersale_create import AftersaleCreateTool

        tool = AftersaleCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            order_id="order-123",
            ticket_type="exchange",
        )

        assert result.success is False
        assert result.suggestion is not None

    async def test_invalid_ticket_type_rejected(self, sample_tool_context):
        """无效ticket_type被拒绝"""
        from app.tools.aftersale_create import AftersaleCreateTool

        tool = AftersaleCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            order_id="order-123",
            ticket_type="delete_order",  # 无效类型
            reason="test",
        )

        assert result.success is False


class TestAftersaleCreateFailure:
    """错误处理"""

    @patch("app.tools.aftersale_create.get_admin_api_client")
    async def test_admin_api_returns_failure_with_suggestion(self, mock_get_client, sample_tool_context):
        """admin-api失败时返回suggestion"""
        from app.tools.aftersale_create import AftersaleCreateTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": False,
            "error": {"message": "订单不存在"},
        })
        mock_get_client.return_value = mock_client

        tool = AftersaleCreateTool()
        result = await tool.execute(
            context=sample_tool_context,
            order_id="order-999",
            ticket_type="refund",
            reason="test",
        )

        assert result.success is False
        assert result.suggestion is not None
