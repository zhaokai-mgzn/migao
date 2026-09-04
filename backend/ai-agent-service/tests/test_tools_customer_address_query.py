# case_ids: CH-025
"""C 端下单地址自动填充 Tool 测试 — customer_address_query

验证：
- 仅 customer 角色可用（商户员工/admin 拒绝，不触发后端调用）
- 调用 C 端专用端点 /api/admin/agent/orders/mine 并强制按当前用户过滤
- 返回最近一笔有收货地址订单的收货信息（customerName/customerPhone/customerAddress）
- 无历史订单/无地址时返回空（不报错），供 LLM 走原表单询问流程
"""
import pytest
from unittest.mock import patch, AsyncMock

from app.tools.customer_address_query import CustomerAddressQueryTool
from app.tools.base import ToolContext


def make_tool():
    return CustomerAddressQueryTool()


def _order(id_, order_no, name, phone, address):
    return {
        "id": id_, "orderNo": order_no,
        "customerName": name, "customerPhone": phone,
        "customerAddress": address, "status": "completed",
        "createdAt": "2026-08-01T10:00:00Z",
    }


class TestCustomerAddressQuery:
    @pytest.mark.asyncio
    async def test_non_customer_role_rejected_without_api_call(self):
        tool = make_tool()
        ctx = ToolContext(tenant_id=1, user_id="emp_001", role="admin")
        with patch("app.tools.customer_address_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            result = await tool.execute(ctx)
            assert not result.success
            mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_user_id_rejected_without_api_call(self):
        tool = make_tool()
        ctx = ToolContext(tenant_id=1, user_id="internal-service", role="customer")
        with patch("app.tools.customer_address_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            result = await tool.execute(ctx)
            assert not result.success
            mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_latest_order_with_address(self, sample_tool_context):
        """有历史订单 → 返回最近一笔有地址订单的收货信息（用于 form 预填）"""
        tool = make_tool()
        with patch("app.tools.customer_address_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={
                "success": True,
                "data": {
                    "items": [
                        _order("o2", "ORD-2", "李四", "13900139000", "上海浦东新区", ),
                        _order("o1", "ORD-1", "张三", "13800138000", "杭州西湖区文三路1号"),
                    ],
                    "total": 2,
                },
            })
            mock_get_client.return_value = mock_client
            result = await tool.execute(sample_tool_context)
            assert result.success
            # 端点必须是 C 端专用 mine（强制用户过滤）
            assert mock_client.get.call_args.args[0] == "/api/admin/agent/orders/mine"
            call_kwargs = mock_client.get.call_args.kwargs
            assert call_kwargs["user_id"] == "user_001"
            # 返回最近订单的收货信息（预填数据源）
            data = result.data
            assert data["customer_name"] == "李四"
            assert data["customer_phone"] == "13900139000"
            assert data["customer_address"] == "上海浦东新区"
            assert data["order_no"] == "ORD-2"

    @pytest.mark.asyncio
    async def test_no_orders_returns_empty(self, sample_tool_context):
        """无历史订单 → 返回空地址（success=True，data 为空），LLM 走原询问流程"""
        tool = make_tool()
        with patch("app.tools.customer_address_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={
                "success": True,
                "data": {"items": [], "total": 0},
            })
            mock_get_client.return_value = mock_client
            result = await tool.execute(sample_tool_context)
            assert result.success
            assert result.data.get("has_address") is False
            assert result.data.get("customer_address") is None

    @pytest.mark.asyncio
    async def test_orders_without_address_returns_empty(self, sample_tool_context):
        """有订单但无地址 → 返回空地址（避免预填空值）"""
        tool = make_tool()
        with patch("app.tools.customer_address_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={
                "success": True,
                "data": {
                    "items": [_order("o1", "ORD-1", "张三", "13800138000", None)],
                    "total": 1,
                },
            })
            mock_get_client.return_value = mock_client
            result = await tool.execute(sample_tool_context)
            assert result.success
            assert result.data.get("has_address") is False

    @pytest.mark.asyncio
    async def test_api_failure_returns_error_with_suggestion(self, sample_tool_context):
        """后端查询失败 → 返回失败 + suggestion（LLM 走原表单询问流程）"""
        tool = make_tool()
        with patch("app.tools.customer_address_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={
                "success": False,
                "error": {"message": "查询失败"},
            })
            mock_get_client.return_value = mock_client
            result = await tool.execute(sample_tool_context)
            assert not result.success
            assert result.suggestion  # 失败必须给 suggestion（铁律）

    @pytest.mark.asyncio
    async def test_read_only_flagged(self):
        """只读工具标注（READONLY，无需 confirm 守卫）"""
        tool = make_tool()
        assert tool.read_only is True
        assert not tool.destructive
        assert "READONLY" in tool.get_schema()["function"]["description"]
