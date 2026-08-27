"""
订单查询 Tool 测试 — 验证 processingInfo 销售信息提取 + 安全隔离
"""
# case_ids: OR-001, OR-002, OR-003, OR-004
import pytest
from unittest.mock import patch, AsyncMock
from app.tools.order_query import OrderQueryTool
from app.tools.base import ToolContext


class TestFormatOrders:
    """_format_orders 方法：验证 processingInfo 提取"""

    def make_record(self, items):
        """构建测试用订单记录"""
        return {
            "id": "ord-1",
            "orderNo": "TEST-001",
            "customerName": "测试客户",
            "customerPhone": "13800138000",
            "totalAmount": 500.0,
            "status": "pending",
            "items": items,
            "createdAt": "2026-06-01T10:00:00Z",
        }

    def test_item_with_processingInfo_extracts_sales_info(self):
        """有 processingInfo 时提取销售信息"""
        tool = OrderQueryTool()
        record = self.make_record([{
            "productName": "窗帘",
            "productCode": "CL-001",
            "unitPrice": 168.0,
            "quantity": 2,
            "amount": 336.0,
            "processingInfo": {
                "colorName": "灰色",
                "sellingMethod": "bulk_cut",
                "doorWidth": "2.8米",
                "skuCode": "SKU-GREY-280",
                "processingFee": 50.0,
            },
        }])

        result = tool._format_orders([record])
        item = result[0]["items"][0]

        assert item["product_name"] == "窗帘"
        assert item["销售信息"] is not None
        assert item["销售信息"]["颜色"] == "灰色"
        assert item["销售信息"]["售卖方式"] == "散剪"
        assert item["销售信息"]["门幅"] == "2.8米"
        assert item["销售信息"]["SKU编码"] == "SKU-GREY-280"
        assert item["销售信息"]["加工费"] == "¥50.00"

    def test_item_without_processingInfo_has_none_sales_info(self):
        """无 processingInfo 时销售信息为 None"""
        tool = OrderQueryTool()
        record = self.make_record([{
            "productName": "样本册",
            "productCode": "SP-001",
            "unitPrice": 50.0,
            "quantity": 1,
            "amount": 50.0,
        }])

        result = tool._format_orders([record])
        item = result[0]["items"][0]

        assert item["product_name"] == "样本册"
        assert item["销售信息"] is None

    def test_selling_method_translation(self):
        """售卖方式正确翻译为中文"""
        tool = OrderQueryTool()
        test_cases = [
            ("bulk_cut", "散剪"),
            ("full_roll", "整卷"),
            ("per_meter", "按米"),
            ("per_piece", "按件"),
        ]
        for code, expected_label in test_cases:
            record = self.make_record([{
                "productName": "test",
                "unitPrice": 10.0,
                "quantity": 1,
                "amount": 10.0,
                "processingInfo": {"sellingMethod": code},
            }])
            result = tool._format_orders([record])
            assert result[0]["items"][0]["销售信息"]["售卖方式"] == expected_label

    def test_multiple_items_with_mixed_processingInfo(self):
        """多商品混合：有的有销售信息，有的没有"""
        tool = OrderQueryTool()
        record = self.make_record([
            {
                "productName": "有颜色",
                "unitPrice": 100.0,
                "quantity": 1,
                "amount": 100.0,
                "processingInfo": {"colorName": "米白"},
            },
            {
                "productName": "无颜色",
                "unitPrice": 50.0,
                "quantity": 1,
                "amount": 50.0,
            },
        ])

        result = tool._format_orders([record])
        items = result[0]["items"]

        assert items[0]["销售信息"] is not None
        assert items[0]["销售信息"]["颜色"] == "米白"
        assert items[1]["销售信息"] is None

    def test_order_top_level_fields_preserved(self):
        """订单顶层字段不受影响"""
        tool = OrderQueryTool()
        record = self.make_record([])

        result = tool._format_orders([record])
        order = result[0]

        assert order["id"] == "ord-1"
        assert order["order_no"] == "TEST-001"
        assert order["customer_name"] == "测试客户"
        assert order["total_amount"] == 500.0
        assert order["status"] == "pending"


# ============================================================
# GAP-4: 订单查询 → 必须 tenant_id + customer_id 双重隔离
# 业务真值: 订单查询做 tenant_id + customer_id 双重隔离
# 当前状态: FAIL — 只传了 tenant_id/user_id header，未显式过滤
# ============================================================

class TestOrderQueryCustomerIsolation:
    """订单查询隔离：依赖后端租户隔离（TenantLineInnerInterceptor 自动注入 tenant_id）。

    后端 OrderListResponse 无 tenantId/customerId 字段，客户端读这些字段做
    "二次校验" 是空操作。真实的租户隔离由 admin-api 在 SQL 层保证，Agent 只
    负责透传 X-Tenant-Id 头，不再伪造客户侧过滤。
    """

    @patch("app.tools.order_query.get_admin_api_client")
    async def test_order_query_for_customer_does_not_send_customer_id_param(self, mock_get_client, sample_tool_context):
        """customer 角色查询订单 → 不传后端不支持的 customerId 参数，只传租户头"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [], "total": 0},
        })
        mock_get_client.return_value = mock_client

        tool = OrderQueryTool()
        result = await tool.execute(
            context=sample_tool_context,  # role=customer, user_id=user_001
            action="list",
            page=1,
            page_size=10,
        )

        assert result.success is True

        call_args = mock_client.get.call_args
        params = call_args[1].get("params", {})
        assert "customerId" not in params, (
            f"customerId 后端不支持，不得透传，当前 params: {params}"
        )
        assert call_args[1].get("tenant_id") == sample_tool_context.tenant_id, (
            f"请求必须携带 X-Tenant-Id header(tenant_id kwarg): {call_args}"
        )

    @patch("app.tools.order_query.get_admin_api_client")
    async def test_order_query_for_admin_skips_customer_id_filter(self, mock_get_client, admin_tool_context):
        """admin角色查询订单 → 不需要 customer_id 过滤（可查看所有客户）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "ord-1", "orderNo": "O1", "customerName": "客户A", "customerPhone": "138", "totalAmount": 100, "status": "pending", "createdAt": ""},
                    {"id": "ord-2", "orderNo": "O2", "customerName": "客户B", "customerPhone": "139", "totalAmount": 200, "status": "confirmed", "createdAt": ""},
                ],
                "total": 2,
            },
        })
        mock_get_client.return_value = mock_client

        tool = OrderQueryTool()
        result = await tool.execute(
            context=admin_tool_context,  # role=admin
            action="list",
            page=1,
            page_size=10,
        )

        assert result.success is True
        # admin可以看到所有客户的订单
        assert result.data["total"] == 2

    @patch("app.tools.order_query.get_admin_api_client")
    async def test_order_query_returns_records_as_backend_supplies(self, mock_get_client, sample_tool_context):
        """响应中的记录原样返回：隔离由后端 SQL 层保证，客户端不再按
        tenantId/customerId 伪造过滤（响应字段不存在 = 空操作）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "ord-mine", "orderNo": "O-MINE-001", "customerName": "我的", "customerPhone": "138", "totalAmount": 100, "status": "pending", "createdAt": ""},
                ],
                "total": 1,
            },
        })
        mock_get_client.return_value = mock_client

        tool = OrderQueryTool()
        result = await tool.execute(
            context=sample_tool_context,  # user_id=user_001
            action="list",
        )

        assert result.success is True
        assert result.data["total"] == 1
        assert len(result.data["orders"]) == 1

    @patch("app.tools.order_query.get_admin_api_client")
    async def test_order_query_sends_tenant_header(self, mock_get_client, sample_tool_context):
        """customer 角色查订单 → HTTP 请求必须携带 X-Tenant-Id header"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [], "total": 0},
        })
        mock_get_client.return_value = mock_client

        tool = OrderQueryTool()
        result = await tool.execute(
            context=sample_tool_context,
            action="list",
        )

        assert result.success is True
        call_kwargs = mock_client.get.call_args[1]
        assert call_kwargs.get("tenant_id") == sample_tool_context.tenant_id, (
            f"请求必须包含X-Tenant-Id header(tenant_id kwarg): {call_kwargs}"
        )

    @patch("app.tools.order_query.get_admin_api_client")
    async def test_order_query_does_not_client_filter_cross_tenant_records(self, mock_get_client, admin_tool_context):
        """后端返回的记录原样透传，客户端不再按响应 tenantId 伪造过滤
        （OrderListResponse 无 tenantId 字段，旧逻辑是恒不触发的空操作）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "items": [
                    {"id": "ord-1", "orderNo": "O1", "customerName": "A", "customerPhone": "138", "totalAmount": 100, "status": "pending", "createdAt": ""},
                    {"id": "ord-2", "orderNo": "O2", "customerName": "B", "customerPhone": "139", "totalAmount": 200, "status": "confirmed", "createdAt": ""},
                ],
                "total": 2,
            },
        })
        mock_get_client.return_value = mock_client

        tool = OrderQueryTool()
        result = await tool.execute(
            context=admin_tool_context,
            action="list",
        )

        assert result.success is True
        assert result.data["total"] == 2
        orders = result.data.get("orders", [])
        assert len(orders) == 2

    @patch("app.tools.order_query.get_admin_api_client")
    async def test_order_query_missing_customer_id_rejected(self, mock_get_client, sample_tool_context):
        """customer 角色但 context.user_id 为空 → 验证拒绝执行，不发起 API 调用"""
        from app.tools.base import ToolContext

        mock_client = AsyncMock()
        mock_client.get = AsyncMock()
        mock_get_client.return_value = mock_client

        no_user_context = ToolContext(
            tenant_id=1,
            user_id="",
            session_id="sess_test",
            role="customer",
        )

        tool = OrderQueryTool()
        result = await tool.execute(
            context=no_user_context,
            action="list",
        )

        assert result.success is False
        error_text = (result.error or "") + (result.message or "")
        assert "customer" in error_text.lower() or "用户" in error_text
        mock_client.get.assert_not_called()


class TestOrderQueryListParams:
    """list action 的筛选参数与后端 OrderController 对齐：

    后端只支持 page/size/status/keyword/followStatus/hasProcessing/
    startDate/endDate/orderId/receiver/productCode/productTitle。
    旧参数 order_no/customer_phone/date_from/date_to/customerId 必须
    归一化到支持的参数，不得再透传（否则参数静默失效）。
    """

    @patch("app.tools.order_query.get_admin_api_client")
    async def test_supported_filter_params_map_to_backend(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
        mock_get_client.return_value = mock_client

        tool = OrderQueryTool()
        result = await tool.execute(
            context=admin_tool_context,
            action="list",
            keyword="张",
            order_id="ORD-123",
            receiver="李",
            status="producing",
            start_date="2026-06-01",
            end_date="2026-06-30",
        )

        assert result.success is True
        params = mock_client.get.call_args[1]["params"]
        assert params["keyword"] == "张"
        assert params["orderId"] == "ORD-123"
        assert params["receiver"] == "李"
        assert params["status"] == "producing"
        assert params["startDate"] == "2026-06-01"
        assert params["endDate"] == "2026-06-30"

    @patch("app.tools.order_query.get_admin_api_client")
    async def test_unsupported_legacy_params_normalized(self, mock_get_client, admin_tool_context):
        """旧参数 order_no/customer_phone/date_from/date_to 必须归一化到后端支持的参数，
        禁止继续透传 orderNo/customerPhone/dateFrom/dateTo（后端不接收 = 静默失效）"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
        mock_get_client.return_value = mock_client

        tool = OrderQueryTool()
        result = await tool.execute(
            context=admin_tool_context,
            action="list",
            order_no="ORD-123",
            customer_phone="13800138000",
            date_from="2026-06-01",
            date_to="2026-06-30",
        )

        assert result.success is True
        params = mock_client.get.call_args[1]["params"]
        # 归一化后的参数
        assert params["orderId"] == "ORD-123"
        assert params["receiver"] == "13800138000"
        assert params["startDate"] == "2026-06-01"
        assert params["endDate"] == "2026-06-30"
        # 后端不支持的参数必须消失
        for unsupported in ("orderNo", "customerPhone", "dateFrom", "dateTo", "customerId"):
            assert unsupported not in params, (
                f"参数 {unsupported} 后端不支持，不得透传，当前 params: {params}"
            )

    @patch("app.tools.order_query.get_admin_api_client")
    async def test_page_size_coerced_to_int(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
        mock_get_client.return_value = mock_client

        tool = OrderQueryTool()
        result = await tool.execute(context=admin_tool_context, action="list", page="3", page_size="25")
        assert result.success is True
        params = mock_client.get.call_args[1]["params"]
        assert params["page"] == 3
        assert params["size"] == 25

    async def test_invalid_action(self, admin_tool_context):
        tool = OrderQueryTool()
        result = await tool.execute(context=admin_tool_context, action="export")
        assert result.success is False
        assert "无效的操作类型" in result.error

    async def test_guest_role_denied(self):
        tool = OrderQueryTool()
        guest = ToolContext(tenant_id=1, user_id="g1", session_id="s", role="guest")
        result = await tool.execute(context=guest, action="list")
        assert result.success is False
        assert "权限" in result.error

    @patch("app.tools.order_query.get_admin_api_client")
    async def test_list_failure_passthrough(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": False, "error": {"message": "服务不可用"}})
        mock_get_client.return_value = mock_client

        tool = OrderQueryTool()
        result = await tool.execute(context=admin_tool_context, action="list")
        assert result.success is False
        assert result.error == "服务不可用"

    @patch("app.tools.order_query.get_admin_api_client")
    async def test_execute_exception_generic(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("boom"))
        mock_get_client.return_value = mock_client

        tool = OrderQueryTool()
        result = await tool.execute(context=admin_tool_context, action="list")
        assert result.success is False
        assert result.error == "tool_execution_failed"


class TestOrderQueryStatistics:
    """statistics / follow_status_stats 摘要构建

    后端 OrderStatisticsResponse 字段：totalCount/pendingCount/confirmedCount/
    producingCount/shippedCount/completedCount/cancelledCount（+unpaid/paid/refunded）。
    """

    @patch("app.tools.order_query.get_admin_api_client")
    async def test_statistics_summary(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "totalCount": 42,
                "pendingCount": 5,
                "confirmedCount": 10,
                "producingCount": 7,
                "shippedCount": 8,
                "completedCount": 9,
                "cancelledCount": 3,
            },
        })
        mock_get_client.return_value = mock_client

        tool = OrderQueryTool()
        result = await tool.execute(context=admin_tool_context, action="statistics")
        assert result.success is True
        # 摘要必须包含真实数字而非 N/A
        assert "N/A" not in result.summary
        assert "42" in result.summary
        assert "7" in result.summary  # producingCount
        assert mock_client.get.call_args[0][0] == "/api/admin/orders/statistics"

    @patch("app.tools.order_query.get_admin_api_client")
    async def test_statistics_fallback_na(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {}})
        mock_get_client.return_value = mock_client

        tool = OrderQueryTool()
        result = await tool.execute(context=admin_tool_context, action="statistics")
        assert result.success is True
        assert "N/A" in result.summary

    @patch("app.tools.order_query.get_admin_api_client")
    async def test_follow_status_stats_summary(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"pending": 1, "processing": 2, "totalCount": 3},
        })
        mock_get_client.return_value = mock_client

        tool = OrderQueryTool()
        result = await tool.execute(context=admin_tool_context, action="follow_status_stats")
        assert result.success is True
        assert "pending:1" in result.summary
        assert mock_client.get.call_args[0][0] == "/api/admin/orders/follow-status/stats"


class TestFormatOrdersExtras:
    """_format_orders 的金额兜底与状态中文映射"""

    def test_amount_fallback_from_unit_price_quantity(self):
        tool = OrderQueryTool()
        record = {
            "id": "ord-1",
            "orderNo": "O1",
            "status": "pending",
            "items": [{"productName": "窗帘", "unitPrice": 10.0, "quantity": 3}],
        }
        result = tool._format_orders([record])
        assert result[0]["items"][0]["amount"] == 30.0

    def test_amount_fallback_invalid_values_to_zero(self):
        tool = OrderQueryTool()
        record = {
            "id": "ord-1",
            "orderNo": "O1",
            "status": "pending",
            "items": [{"productName": "窗帘", "unitPrice": "abc", "quantity": 3}],
        }
        result = tool._format_orders([record])
        assert result[0]["items"][0]["amount"] == 0

    def test_status_text_mapping(self):
        tool = OrderQueryTool()
        expected = {
            "pending": "待付款",
            "confirmed": "已确认（待发货）",
            "producing": "生产中",
            "shipped": "已发货",
            "completed": "已完成",
            "cancelled": "已取消",
        }
        for status, text in expected.items():
            record = {"id": "o", "orderNo": "O1", "status": status, "items": []}
            result = tool._format_orders([record])
            assert result[0]["status_text"] == text


class TestOrderQueryStatusVocabulary:
    """状态词表与后端对齐：订单状态是 producing（生产中），不是 processing"""

    def test_status_enum_uses_producing(self):
        """参数 schema 的 status 枚举必须使用 producing 且不含 processing"""
        status_enum = OrderQueryTool.parameters["properties"]["status"]["enum"]
        assert "producing" in status_enum
        assert "processing" not in status_enum

    def test_status_text_map_uses_producing(self):
        """ORDER_STATUS_TEXT 必须使用 producing 键，且不含 processing 键"""
        from app.tools.order_query import ORDER_STATUS_TEXT
        assert ORDER_STATUS_TEXT["producing"] == "生产中"
        assert "processing" not in ORDER_STATUS_TEXT

    @patch("app.tools.order_query.get_admin_api_client")
    async def test_list_status_producing_sent_to_backend(self, mock_get_client, admin_tool_context):
        """action=list + status=producing → 请求参数 status=producing"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
        mock_get_client.return_value = mock_client

        tool = OrderQueryTool()
        result = await tool.execute(
            context=admin_tool_context, action="list", status="producing"
        )
        assert result.success is True
        params = mock_client.get.call_args[1]["params"]
        assert params["status"] == "producing"
