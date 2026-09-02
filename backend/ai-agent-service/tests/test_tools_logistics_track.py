"""
物流查询 Tool 单元测试

测试 LogisticsTrackTool.execute() 的各种场景
"""
# case_ids: OR-005, OR-013

import pytest
from unittest.mock import patch, AsyncMock

from app.tools.logistics_track import LogisticsTrackTool
from app.tools.base import ToolContext, ToolResult


@pytest.fixture
def tool():
    return LogisticsTrackTool()


@pytest.fixture
def sample_order_with_logistics():
    """模拟包含物流信息的订单响应（与后端 OrderDetailResponse.LogisticsInfo 对齐：
    快递公司字段是 logisticsCompany，无 receiverPhone）"""
    return {
        "success": True,
        "data": {
            "id": "order_001",
            "status": "shipped",
            "logistics": {
                "trackingNo": "SF1234567890",
                "logisticsCompany": "顺丰速运",
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
        # 两次 HTTP 调用：① 列表搜索 ② 详情查询，需返回不同格式
        async def mock_get(url, **kwargs):
            if "/api/admin/orders" == url and kwargs.get("params", {}).get("keyword"):
                # 列表搜索：admin-api 实际返回 items 数组（生产回归：旧实现读 records 永远空）
                return {"success": True, "data": {"items": [{"id": "order_001"}]}}
            # 详情查询
            return sample_order_with_logistics
        mock_client.get = mock_get
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
    async def test_logistics_track_parses_logistics_company(
        self, mock_get_client, tool, sample_tool_context
    ):
        """后端响应物流字段是 logisticsCompany（非 company）→ 工具必须正确解析"""
        mock_client = AsyncMock()
        async def mock_get(url, **kwargs):
            if "/api/admin/orders" == url and kwargs.get("params", {}).get("keyword"):
                return {"success": True, "data": {"items": [{"id": "order_001"}]}}
            return {
                "success": True,
                "data": {
                    "id": "order_001",
                    "status": "shipped",
                    "logistics": {
                        "trackingNo": "SF1234567890",
                        "logisticsCompany": "中通快递",
                    },
                },
            }
        mock_client.get = mock_get
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            order_id="order_001",
        )

        assert result.success is True
        assert result.data["tracking_number"] == "SF1234567890"
        # company 来自 logisticsCompany 字段
        assert result.data["company"] == "中通快递"
        # receiverPhone 后端不存在，工具不应报错也不应展示
        assert "receiverPhone" not in result.data

    @patch("app.tools.logistics_track.get_admin_api_client")
    async def test_logistics_track_by_order_legacy_records_shape(
        self, mock_get_client, tool, sample_tool_context, sample_order_with_logistics
    ):
        """兼容旧 records 数组格式（历史契约，防止回归）"""
        mock_client = AsyncMock()

        async def mock_get(url, **kwargs):
            if "/api/admin/orders" == url and kwargs.get("params", {}).get("keyword"):
                return {"success": True, "data": {"records": [{"id": "order_001"}]}}
            return sample_order_with_logistics
        mock_client.get = mock_get
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=sample_tool_context, order_id="order_001")
        assert result.success is True
        assert result.data["tracking_number"] == "SF1234567890"

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
        async def mock_get(url, **kwargs):
            if "/api/admin/orders" == url and kwargs.get("params", {}).get("keyword"):
                return {"success": True, "data": {"records": [{"id": "order_002"}]}}
            return sample_order_without_logistics
        mock_client.get = mock_get
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=sample_tool_context,
            order_id="order_002",
        )

        assert result.success is False
        assert "未发货" in result.error or "未发货" in result.message


class TestLogisticsTrackRejectsTrackingNumber:
    """物流查询 - 禁止直接通过快递单号查询（安全铁律）"""

    async def test_logistics_track_by_tracking_number_rejected(
        self, tool, sample_tool_context
    ):
        """通过快递单号查询 → 必须被拒绝（只能通过真实订单号查）"""
        result = await tool.execute(
            context=sample_tool_context,
            tracking_number="SF9876543210",
        )

        assert result.success is False
        assert "快递单号" in result.error or "订单号" in result.message


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
        assert isinstance(result.data["traces"], list)
        assert len(result.data["traces"]) > 0


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


class TestLogisticsTrackInferStatus:
    """物流查询 - _infer_status_from_traces 关键词推断"""

    def test_empty_traces_fallback(self, tool):
        assert tool._infer_status_from_traces([]) == "in_transit"

    def test_keyword_delivered(self, tool):
        assert tool._infer_status_from_traces([{"content": "快件已签收"}]) == "delivered"

    def test_keyword_out_for_delivery(self, tool):
        assert tool._infer_status_from_traces([{"content": "正在派送"}]) == "out_for_delivery"

    def test_keyword_picked(self, tool):
        assert tool._infer_status_from_traces([{"content": "已揽收"}]) == "picked"

    def test_keyword_returned(self, tool):
        assert tool._infer_status_from_traces([{"content": "快件已退回"}]) == "returned"

    def test_keyword_exception(self, tool):
        assert tool._infer_status_from_traces([{"content": "问题件"}]) == "exception"

    def test_keyword_in_transit(self, tool):
        assert tool._infer_status_from_traces([{"content": "快件发往转运中心"}]) == "in_transit"

    def test_latest_three_only(self, tool):
        traces = [
            {"content": "已签收"},
            {"content": "正在派送"},
            {"content": "无关键词轨迹"},
        ]
        # 最新一条（索引 0）命中签收
        assert tool._infer_status_from_traces(traces) == "delivered"

    def test_no_match_fallback(self, tool):
        assert tool._infer_status_from_traces([{"content": "已收取快件"}]) == "in_transit"


class TestLogisticsTrackCompanyCode:
    """物流查询 - _get_company_code 编码转换"""

    def test_ascii_code_uppercase(self, tool):
        assert tool._get_company_code("sf") == "SF"

    def test_chinese_name_mapping(self, tool):
        assert tool._get_company_code("顺丰速运") == "SFEXPRESS"
        assert tool._get_company_code("中通快递") == "ZTO"
        assert tool._get_company_code("韵达") == "YUNDA"

    def test_unknown_company_none(self, tool):
        assert tool._get_company_code("未知快递") is None


class TestLogisticsTrackTransform:
    """物流查询 - _transform_api_response 标准格式转换"""

    def test_transform_with_api_type_and_traces(self, tool):
        api_result = {
            "status": "0",
            "result": {
                "type": "SFEXPRESS",
                "number": "SF123",
                "list": [
                    {"time": "2026-01-01", "context": "已签收"},
                    {"time": "2025-12-31", "status": "发往杭州"},
                ],
            },
        }
        data = tool._transform_api_response(api_result, "SF123", "顺丰速运", "order-1")
        assert data["company"] == "顺丰速运"
        assert data["tracking_number"] == "SF123"
        assert data["status"] == "delivered"
        assert data["status_text"] == "已签收"
        assert len(data["traces"]) == 2
        assert data["traces"][1]["content"] == "发往杭州"

    def test_transform_company_fallback(self, tool):
        api_result = {"status": "0", "result": {"list": []}}
        data = tool._transform_api_response(api_result, "SF123", "中通快递", None)
        assert data["company"] == "中通快递"


class TestLogisticsTrackOrderEdge:
    """物流查询 - _track_by_order 隔离/分支"""

    @patch("app.tools.logistics_track.get_admin_api_client")
    async def test_uuid_direct_branch(self, mock_get_client, tool, admin_tool_context):
        """UUID 订单号跳过 keyword 搜索，直接查详情"""
        mock_client = AsyncMock()
        async def mock_get(url, **kwargs):
            return {"success": True, "data": {
                "logistics": {"trackingNo": "SF1", "logisticsCompany": "顺丰速运"}}}
        mock_client.get = mock_get
        mock_get_client.return_value = mock_client

        uuid = "12345678-1234-1234-1234-123456789012"
        result = await tool._track_by_order(admin_tool_context, uuid)
        # 直接走详情 → trackingNo → _track_by_number → mock 降级成功
        assert result.success is True

    @patch("app.tools.logistics_track.get_admin_api_client")
    async def test_tenant_mismatch_rejected(self, mock_get_client, tool, admin_tool_context):
        """响应 tenant_id 与上下文不一致 → 订单不存在（数据完整性）"""
        mock_client = AsyncMock()
        async def mock_get(url, **kwargs):
            if kwargs.get("params", {}).get("keyword"):
                return {"success": True, "data": {"records": [{"id": "uuid-x"}]}}
            return {"success": True, "data": {"tenantId": 999, "logistics": {"trackingNo": "SF1"}}}
        mock_client.get = mock_get
        mock_get_client.return_value = mock_client

        result = await tool._track_by_order(admin_tool_context, "ORD-1")
        assert result.success is False
        assert "订单不存在" in result.error


class TestLogisticsApiAutoDetectRetry:
    """阿里云市场 API：显式公司 code 被拒(203) → 去 type 自动识别重试（真实数据回归）"""

    @patch("app.tools.logistics_track.httpx.AsyncClient")
    async def test_203_retry_without_type(self, mock_http_client, tool, admin_tool_context):
        """type=JT 返回 203（快递公司不存在）→ 去掉 type 重试成功"""
        calls = []

        class _FakeResp:
            def raise_for_status(self):
                pass
            def json(self):
                pass

        async def fake_get(url, headers=None, params=None):
            calls.append(dict(url=url, params=dict(params) if params else None))  # 拷贝，避免重试 pop 污染记录
            r = _FakeResp()
            if len(calls) == 1:
                r.json = lambda: {"status": "203", "msg": "快递公司不存在:JT"}
            else:
                r.json = lambda: {"status": "0", "result": {
                    "type": "JITU", "number": "JT3175138582857",
                    "list": [{"time": "2026-08-28 20:33", "context": "【义乌转运中心】快件已发出"}]}}
            return r

        mock_client = AsyncMock()
        mock_client.get = fake_get
        mock_http_client.return_value.__aenter__.return_value = mock_client

        with patch("app.tools.logistics_track.settings") as mock_settings:
            mock_settings.LOGISTICS_APPCODE = "test-appcode"
            mock_settings.LOGISTICS_API_URL = "https://fake.api/kdi"
            result = await tool._call_logistics_api("JT3175138582857", "极兔速递")

        assert result is not None
        assert result["status"] == "0"
        # 第一次带 type=JT，第二次去掉 type（自动识别）
        assert calls[0]["params"].get("type") == "JITU"
        assert "type" not in calls[1]["params"]

    def test_company_code_jitu(self, tool):
        """极兔中文名 → JITU（阿里云市场 kdi API 实际 code，JT 会被 203 拒绝）"""
        assert tool._get_company_code("极兔速递") == "JITU"
        assert tool._get_company_code("极兔") == "JITU"


class TestLogisticsStatusInferenceRealWording:
    """真实快递轨迹措辞的状态推断（圆通/中通/顺丰 实测文案）"""

    @pytest.mark.parametrize("content,expected", [
        ("快件已由菜鸟驿站杭州西溪蝶园店送达（上门服务）", "delivered"),
        ("已于 09-02 送货上门，签收人：家门口", "delivered"),
        ("您的快件已派送成功（家门口）", "delivered"),
        ("快件正在派送中，请保持电话畅通", "out_for_delivery"),
        ("快件已到达【杭州转运中心】", "in_transit"),
    ])
    def test_infer_from_real_wording(self, tool, content, expected):
        assert tool._infer_status_from_traces([{"content": content}]) == expected
