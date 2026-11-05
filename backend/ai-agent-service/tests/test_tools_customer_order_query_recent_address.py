# case_ids: CH-025
"""C 端下单地址自动填充 —— 已收敛为 `customer_order_query(action="recent_address")`（issue #8726）

这是**等价变换**的逐字段证明（收敛前 = 独立工具 `customer_address_query`，收敛后 = 同一工具的第二个 action）：

- 同一端点 `/api/admin/agent/orders/mine` + 同一强制用户过滤（`user_id` 透传，无任何跨用户参数）；
- **命中**：`data` 六键逐字相同（has_address / customer_name / customer_phone /
  customer_address / order_no / source），`message` / `summary` 文案逐字相同；
- **未命中**：`data` 四键（含 None）逐字相同；`message` / `summary` 文案逐字相同；
- 仅 customer 角色可用；缺失用户标识时**不触发**后端调用；
- `action=list` 的返回形状不受影响（orders/total/page/page_size[/total_pages]）。

下面的 `FROZEN_*` 常量 = 收敛前对外可观测面的**唯一 durable 载体**：旧实现文件已删
（工具名必须零残留），所以"收敛前返回什么"只能冻结在测试里，供逐字段对照。
"""
import pytest
from unittest.mock import patch, AsyncMock

from app.tools.base import ToolContext
from app.tools.customer_order_query import RECENT_ADDRESS_ACTION, CustomerOrderQueryTool


def make_tool():
    return CustomerOrderQueryTool()


def _order(id_, order_no, name, phone, address):
    return {
        "id": id_, "orderNo": order_no,
        "customerName": name, "customerPhone": phone,
        "customerAddress": address, "status": "completed",
        "createdAt": "2026-08-01T10:00:00Z",
    }


#: 收敛前命中路径的 data（逐字冻结）
FROZEN_HIT = {
    "has_address": True,
    "customer_name": "李四",
    "customer_phone": "13900139000",
    "customer_address": "上海浦东新区",
    "order_no": "ORD-2",
    "source": "last_order",
}
#: 收敛前命中路径的 message / summary（逐字冻结）
FROZEN_HIT_MESSAGE = "已找到您上次的收货信息（来自订单 ORD-2），可直接确认或修改"
FROZEN_HIT_SUMMARY = "命中上次收货信息: 李四 139****9000 上海浦东新区"
#: 收敛前未命中路径的 data（逐字冻结；**没有** order_no / source 两键）
FROZEN_MISS = {
    "has_address": False,
    "customer_name": None,
    "customer_phone": None,
    "customer_address": None,
}
FROZEN_MISS_MESSAGE = "暂未找到您之前保存的收货信息"
FROZEN_MISS_SUMMARY = "无历史收货地址，按原流程询问顾客收货人/手机号/地址"


class TestRecentAddressAction:
    """收敛后的 recent_address action（= 收敛前 customer_address_query 的全部行为）"""

    @pytest.mark.asyncio
    async def test_non_customer_role_rejected_without_api_call(self):
        tool = make_tool()
        ctx = ToolContext(tenant_id=1, user_id="emp_001", role="admin")
        with patch("app.tools.customer_order_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            result = await tool.execute(ctx, action=RECENT_ADDRESS_ACTION)
            assert result.success is False
            assert result.error == "权限不足"
            mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_user_id_rejected_without_api_call(self):
        tool = make_tool()
        ctx = ToolContext(tenant_id=1, user_id="internal-service", role="customer")
        with patch("app.tools.customer_order_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            result = await tool.execute(ctx, action=RECENT_ADDRESS_ACTION)
            assert result.success is False
            assert result.error == "缺少用户标识"
            mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_latest_order_with_address_field_for_field(self, sample_tool_context):
        """有历史订单 → 返回最近一笔有地址订单的收货信息（**逐字段**等同收敛前）"""
        tool = make_tool()
        with patch("app.tools.customer_order_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={
                "success": True,
                "data": {
                    "items": [
                        _order("o2", "ORD-2", "李四", "13900139000", "上海浦东新区"),
                        _order("o1", "ORD-1", "张三", "13800138000", "杭州西湖区文三路1号"),
                    ],
                    "total": 2,
                },
            })
            mock_get_client.return_value = mock_client
            result = await tool.execute(sample_tool_context, action=RECENT_ADDRESS_ACTION)

            assert result.success is True
            # ① 端点与强制用户过滤（与 list 同一面，无法越权）
            assert mock_client.get.call_args.args[0] == "/api/admin/agent/orders/mine"
            assert mock_client.get.call_args.kwargs["params"] == {"page": 1, "size": 10}
            assert mock_client.get.call_args.kwargs["user_id"] == "user_001"
            # ② 返回形状逐字段相同（键集合 + 值，**不是**"键存在"）
            assert result.data == FROZEN_HIT
            assert result.message == FROZEN_HIT_MESSAGE
            assert result.summary == FROZEN_HIT_SUMMARY

    @pytest.mark.asyncio
    async def test_no_orders_returns_empty_field_for_field(self, sample_tool_context):
        """无历史订单 → 空地址（success=True），逐字段等同收敛前（LLM 走原询问流程）"""
        tool = make_tool()
        with patch("app.tools.customer_order_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={
                "success": True,
                "data": {"items": [], "total": 0},
            })
            mock_get_client.return_value = mock_client
            result = await tool.execute(sample_tool_context, action=RECENT_ADDRESS_ACTION)
            assert result.success is True
            assert result.data == FROZEN_MISS
            assert result.message == FROZEN_MISS_MESSAGE
            assert result.summary == FROZEN_MISS_SUMMARY

    @pytest.mark.asyncio
    async def test_orders_without_address_returns_empty(self, sample_tool_context):
        """有订单但无地址 → 空地址（避免预填空值），形状与"无订单"一致"""
        tool = make_tool()
        with patch("app.tools.customer_order_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={
                "success": True,
                "data": {
                    "items": [_order("o1", "ORD-1", "张三", "13800138000", None)],
                    "total": 1,
                },
            })
            mock_get_client.return_value = mock_client
            result = await tool.execute(sample_tool_context, action=RECENT_ADDRESS_ACTION)
            assert result.success is True
            assert result.data == FROZEN_MISS

    @pytest.mark.asyncio
    async def test_snake_case_payload_accepted(self, sample_tool_context):
        """后端若给 snake_case（customer_address）也必须命中（收敛前同一回退口径）"""
        tool = make_tool()
        with patch("app.tools.customer_order_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={
                "success": True,
                "data": {"items": [{
                    "order_no": "ORD-9", "customer_name": "王五",
                    "customer_phone": "13700137000", "customer_address": "北京朝阳区",
                }], "total": 1},
            })
            mock_get_client.return_value = mock_client
            result = await tool.execute(sample_tool_context, action=RECENT_ADDRESS_ACTION)
            assert result.data["customer_address"] == "北京朝阳区"
            assert result.data["order_no"] == "ORD-9"

    @pytest.mark.asyncio
    async def test_api_failure_returns_error_with_suggestion(self, sample_tool_context):
        """后端查询失败 → 失败 + suggestion（LLM 走原表单询问流程）"""
        tool = make_tool()
        with patch("app.tools.customer_order_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={
                "success": False,
                "error": {"message": "查询失败"},
            })
            mock_get_client.return_value = mock_client
            result = await tool.execute(sample_tool_context, action=RECENT_ADDRESS_ACTION)
            assert result.success is False
            assert result.suggestion == "直接询问顾客收货人/手机号/地址后继续下单流程"
            assert result.message == "收货地址查询失败，请直接告诉我您的收货信息"

    @pytest.mark.asyncio
    async def test_pagination_args_are_ignored(self, sample_tool_context):
        """收敛前该能力**没有**分页入参 ⇒ 收敛后传了也必须被忽略（结果不得改变）"""
        tool = make_tool()
        with patch("app.tools.customer_order_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={
                "success": True,
                "data": {"items": [_order("o1", "ORD-1", "张三", "13800138000", "杭州")], "total": 1},
            })
            mock_get_client.return_value = mock_client
            await tool.execute(sample_tool_context, action=RECENT_ADDRESS_ACTION,
                               page=7, page_size=50, status="shipped")
            assert mock_client.get.call_args.kwargs["params"] == {"page": 1, "size": 10}


class TestToolContract:
    """工具契约面：action 枚举 / 只读标注 / list 形状不变"""

    def test_action_enum_has_exactly_two_actions(self):
        props = make_tool().parameters["properties"]
        assert props["action"]["enum"] == ["list", RECENT_ADDRESS_ACTION]
        assert props["action"]["default"] == "list"

    def test_old_params_are_still_present(self):
        """收敛前的 list 入参一个都不能少（status 枚举也不能变）"""
        props = make_tool().parameters["properties"]
        assert {"action", "status", "page", "page_size"} <= set(props)
        assert props["status"]["enum"] == [
            "pending", "confirmed", "producing", "shipped", "completed", "cancelled",
        ]

    def test_read_only_flagged(self):
        """只读工具标注（READONLY，无需 confirm 守卫）"""
        tool = make_tool()
        assert tool.read_only is True
        assert not tool.destructive
        assert "READONLY" in tool.get_schema()["function"]["description"]

    def test_description_covers_both_triggers(self):
        """两个语义都必须在工具描述里（否则模型选不到 recent_address）"""
        desc = make_tool().get_schema()["function"]["description"]
        assert "recent_address" in desc
        assert "我的订单" in desc
        assert "has_address" in desc

    @pytest.mark.asyncio
    async def test_list_action_shape_unchanged(self, sample_tool_context):
        """list action 的返回形状与收敛前逐字相同（orders/total/page/page_size/total_pages）"""
        tool = make_tool()
        with patch("app.tools.customer_order_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={
                "success": True,
                "data": {"items": [_order("o1", "ORD-1", "张三", "13800138000", "杭州")], "total": 1},
            })
            mock_get_client.return_value = mock_client
            result = await tool.execute(sample_tool_context, action="list")
            assert set(result.data) == {"orders", "total", "page", "page_size", "total_pages"}
            assert result.data["total_pages"] == 1
            assert result.message == "为您找到 1 个订单"
            assert result.data["orders"][0]["order_no"] == "ORD-1"
            assert mock_client.get.call_args.kwargs["params"] == {"page": 1, "size": 10}

    @pytest.mark.asyncio
    async def test_list_empty_shape_unchanged(self, sample_tool_context):
        """list 空结果形状不变（无 total_pages 键，收敛前如此）"""
        tool = make_tool()
        with patch("app.tools.customer_order_query.get_admin_api_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value={
                "success": True, "data": {"items": [], "total": 0}})
            mock_get_client.return_value = mock_client
            result = await tool.execute(sample_tool_context, action="list")
            assert set(result.data) == {"orders", "total", "page", "page_size"}
            assert result.message == "您暂时没有相关订单"
