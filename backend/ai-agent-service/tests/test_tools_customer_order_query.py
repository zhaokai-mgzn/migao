"""
C 端"我的订单"查询 Tool 测试 — 数据隔离核心验证

验证 customer_order_query 与 B 端 order_query 物理隔离：
- 仅 customer 角色可用（商户员工/admin 一律拒绝）
- 强制调用 C 端专用端点 /api/admin/agent/orders/mine
- 无 user_id 时拒绝，不透传任何可跨用户搜索的参数（keyword/receiver 等被 schema 排除）
"""
# case_ids: OR-001, DF-002
import pytest
from unittest.mock import patch, AsyncMock

from app.tools.customer_order_query import CustomerOrderQueryTool
from app.tools.base import ToolContext


def make_tool():
    return CustomerOrderQueryTool()


class TestCustomerOrderQueryIsolation:
    """物理隔离：角色限制 + 用户强制过滤"""

    @pytest.mark.asyncio
    async def test_non_customer_role_rejected_without_api_call(self):
        """商户员工/admin 角色直接拒绝，且不触发后端调用"""
        tool = make_tool()
        ctx = ToolContext(tenant_id=1, user_id="emp_001", role="admin")
        with patch("app.tools.customer_order_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            result = await tool.execute(ctx)
            assert not result.success
            assert "权限" in (result.error or "") or "权限" in (result.message or "")
            mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_user_id_rejected_without_api_call(self):
        """无 user_id（或内部服务占位）时拒绝，不触发后端调用"""
        tool = make_tool()
        ctx = ToolContext(tenant_id=1, user_id="internal-service", role="customer")
        with patch("app.tools.customer_order_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            result = await tool.execute(ctx)
            assert not result.success
            mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_c_endpoint_with_user_header(self, sample_tool_context):
        """customer 角色调用 C 端专用端点，且请求带 user_id（后端据此强制过滤）"""
        tool = make_tool()
        with patch("app.tools.customer_order_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={
                "success": True,
                "data": {"items": [], "total": 0, "page": 1, "size": 10},
            })
            mock_get_client.return_value = mock_client
            result = await tool.execute(sample_tool_context)
            assert result.success
            # 必须调用 C 端专用端点（B 端 order_query 的 /api/admin/orders 不能出现在这里）
            call_args = mock_client.get.call_args
            assert call_args.args[0] == "/api/admin/agent/orders/mine"
            call_kwargs = call_args.kwargs
            assert call_kwargs["user_id"] == "user_001"
            assert call_kwargs["tenant_id"] == 1

    @pytest.mark.asyncio
    async def test_status_filter_passed_but_no_cross_user_params(self, sample_tool_context):
        """仅支持 status/page/page_size；keyword/receiver 等跨用户参数被 schema 排除"""
        tool = make_tool()
        schema = tool.parameters
        props = schema["properties"]
        assert "keyword" not in props
        assert "receiver" not in props
        assert "order_id" not in props
        assert "start_date" not in props
        assert "end_date" not in props

        with patch("app.tools.customer_order_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={
                "success": True,
                "data": {"items": [], "total": 0},
            })
            mock_get_client.return_value = mock_client
            result = await tool.execute(sample_tool_context, status="shipped", page=2, page_size=5)
            assert result.success
            params = mock_client.get.call_args.kwargs["params"]
            assert params["status"] == "shipped"
            assert params["page"] == 2
            assert params["size"] == 5


class TestCustomerOrderQueryFormat:
    """格式化：与 B 端 order_query 一致的订单摘要输出"""

    def test_formats_orders_with_items(self):
        tool = make_tool()
        records = [{
            "id": "ord-1",
            "orderNo": "ORD-MY-001",
            "customerName": "张三",
            "customerPhone": "13800138000",
            "totalAmount": 199.0,
            "status": "shipped",
            "items": [{
                "productName": "窗帘",
                "unitPrice": 99.5,
                "quantity": 2,
                "amount": 199.0,
            }],
            "createdAt": "2026-06-01T10:00:00Z",
        }]
        orders = tool._format_orders(records)
        assert orders[0]["order_no"] == "ORD-MY-001"
        assert orders[0]["status_text"] == "已发货"
        assert orders[0]["items"][0]["product_name"] == "窗帘"
        assert orders[0]["items"][0]["quantity"] == 2

    def test_status_text_fallback_to_raw_status(self):
        tool = make_tool()
        orders = tool._format_orders([{"status": "unknown_status", "items": []}])
        assert orders[0]["status_text"] == "unknown_status"
