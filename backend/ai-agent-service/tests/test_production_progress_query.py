"""ProductionProgressQueryTool 单测 — 生产进度查询（issue #3996 / M4-I）。

契约（由并行包 #3995 冻结）：
  GET /api/admin/agent/production/progress?order_no={订单号}
  → {"success": true, "data": {"order_no", "status", "status_text", "progress_percent",
       "current_operation", "pending_operations": [...], "total_operations",
       "done_operations", "expected_delivery_date"}}

零真实网络：`get_admin_api_client` 全部 mock。
"""
# case_ids: CH-039, CH-040
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.production_progress_query import ProductionProgressQueryTool

PROGRESS_PATH = "/api/admin/agent/production/progress"

# 冻结契约样例（与后端端点 data 结构逐字段一致）
PROGRESS_DATA = {
    "order_no": "ORD-20260917-0001",
    "status": "in_production",
    "status_text": "生产中",
    "progress_percent": 60,
    "current_operation": "韩褶-布",
    "pending_operations": ["韩褶-布", "打孔", "质检"],
    "total_operations": 5,
    "done_operations": 2,
    "expected_delivery_date": "2026-09-25",
}


@pytest.fixture
def tool():
    return ProductionProgressQueryTool()


@pytest.fixture
def customer_context():
    """C 端顾客（小布）上下文 —— 查自己的订单进度"""
    return ToolContext(tenant_id=1, user_id="customer_001", session_id="sess_pp_1", role="customer")


@pytest.fixture
def seller_context():
    """B 端商户员工（米宝）上下文 —— 查任意单"""
    return ToolContext(tenant_id=1, user_id="agent_001", session_id="sess_pp_2", role="agent")


class TestMetadataContract:
    """Tool 元数据：LLM 选择工具时只读 description，触发/前置/反例/标注必须自带"""

    def test_read_only_and_role_metadata(self, tool):
        assert tool.name == "production_progress_query"
        assert tool.read_only is True
        assert tool.destructive is False
        assert tool.idempotent is True
        # 两端可用：顾客查自己的单、商户员工查任意单
        for role in ("customer", "admin", "agent", "tenant_admin"):
            assert role in tool.allowed_roles, f"{role} 应可查生产进度"

    def test_description_carries_trigger_prereq_counterexample(self, tool):
        desc = tool.description
        assert "【触发】" in desc and "生产进度" in desc
        assert "【前置】" in desc and "order_no" in desc
        assert "【反例】" in desc and "logistics_track" in desc
        assert "READONLY" in desc

    def test_parameters_require_order_no(self, tool):
        params = tool.parameters
        assert params["properties"]["order_no"]["type"] == "string"
        assert params["required"] == ["order_no"]


class TestExecuteSuccess:
    """成功路径：字段透传 + LLM 友好摘要 + 调用冻结契约端点"""

    @patch("app.tools.production_progress_query.get_admin_api_client")
    async def test_customer_queries_progress(self, mock_get_client, tool, customer_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": dict(PROGRESS_DATA)})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=customer_context, order_no="ORD-20260917-0001")

        assert result.success is True
        # 端点与参数（冻结契约）
        args, kwargs = mock_client.get.call_args
        assert args[0] == PROGRESS_PATH
        assert kwargs["params"] == {"order_no": "ORD-20260917-0001"}
        assert kwargs["tenant_id"] == 1
        assert kwargs["user_id"] == "customer_001"
        # 进度/当前工序/待完工序/交期 全部透传
        data = result.data
        assert data["progress_percent"] == 60
        assert data["current_operation"] == "韩褶-布"
        assert data["pending_operations"] == ["韩褶-布", "打孔", "质检"]
        assert data["expected_delivery_date"] == "2026-09-25"
        assert data["status_text"] == "生产中"
        # LLM 摘要文案
        assert result.summary == "生产进度 60%（当前：韩褶-布），预计交付 2026-09-25"

    @patch("app.tools.production_progress_query.get_admin_api_client")
    async def test_seller_queries_any_order(self, mock_get_client, tool, seller_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": dict(PROGRESS_DATA)})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=seller_context, order_no="ORD-20260917-0001")

        assert result.success is True
        assert mock_client.get.call_args.kwargs["user_id"] == "agent_001"

    @patch("app.tools.production_progress_query.get_admin_api_client")
    async def test_order_no_is_trimmed(self, mock_get_client, tool, seller_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": dict(PROGRESS_DATA)})
        mock_get_client.return_value = mock_client

        await tool.execute(context=seller_context, order_no="  ORD-20260917-0001  ")

        assert mock_client.get.call_args.kwargs["params"] == {"order_no": "ORD-20260917-0001"}

    @patch("app.tools.production_progress_query.get_admin_api_client")
    async def test_summary_without_expected_delivery(self, mock_get_client, tool, seller_context):
        """交期缺失时不编造日期，摘要只说进度与当前工序"""
        data = dict(PROGRESS_DATA)
        data["expected_delivery_date"] = None
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": data})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=seller_context, order_no="ORD-20260917-0001")

        assert result.success is True
        assert result.summary == "生产进度 60%（当前：韩褶-布）"


class TestExecuteFailure:
    """失败路径：不抛异常、success=False、必须给 suggestion（反幻觉引导）"""

    @patch("app.tools.production_progress_query.get_admin_api_client")
    async def test_api_business_failure(self, mock_get_client, tool, seller_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False,
            "error": {"code": "ORDER_NOT_FOUND", "message": "订单不存在"},
            "data": None,
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=seller_context, order_no="ORD-不存在")

        assert result.success is False
        assert result.message == "查询生产进度失败，请稍后重试"
        assert result.suggestion, "失败必须给 suggestion 引导 LLM 修复"

    @patch("app.tools.production_progress_query.get_admin_api_client")
    async def test_http_exception_is_caught(self, mock_get_client, tool, seller_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("connection reset"))
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=seller_context, order_no="ORD-20260917-0001")

        assert result.success is False
        assert result.message == "查询生产进度失败，请稍后重试"
        assert result.suggestion

    @patch("app.tools.production_progress_query.get_admin_api_client")
    async def test_non_dict_response_does_not_crash(self, mock_get_client, tool, seller_context):
        """admin-api 异常返回形态（list/None）不得抛异常"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=seller_context, order_no="ORD-20260917-0001")

        assert result.success is False
        assert result.suggestion

    @patch("app.tools.production_progress_query.get_admin_api_client")
    async def test_success_flag_with_empty_data(self, mock_get_client, tool, seller_context):
        """success=true 但 data 为空：如实告知未查到，不得编造进度"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": None})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=seller_context, order_no="ORD-20260917-0001")

        assert result.success is False
        assert "未查到" in result.message
        assert result.suggestion

    @pytest.mark.parametrize("missing", [None, "", "   "])
    async def test_missing_order_no_guides_to_order_query(self, tool, seller_context, missing):
        """订单号缺失：明确提示先查订单号（不得猜号、不得直接查）"""
        result = await tool.execute(context=seller_context, order_no=missing)

        assert result.success is False
        assert result.error == "缺少订单号"
        assert "订单号" in result.message
        assert "order_query" in result.suggestion

    async def test_permission_denied(self, tool):
        """未知角色（guest）不可查生产进度"""
        guest = ToolContext(tenant_id=1, user_id="guest_001", session_id="sess_pp_3", role="guest")

        result = await tool.execute(context=guest, order_no="ORD-20260917-0001")

        assert result.success is False
        assert result.message == "您没有权限查询生产进度"
        assert tool.check_permission(guest) is False
