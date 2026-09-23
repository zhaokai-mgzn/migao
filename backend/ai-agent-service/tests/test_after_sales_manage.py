"""AfterSalesManageTool 单元测试 — 售后工单查询（只读）。

B 端只读化（issue #5247）：after_sales_manage（售后工单） 的写 action 已删除 ⇒ 本次退休写路径用例（产品裁定，非放宽门禁）。
覆盖 list/detail 的正常路径与参数校验，
以及 destructive 工具只读 action 的确认豁免（DF-008）。
"""
# case_ids: AS-001, AS-002, AS-004, AS-007, DF-008
# ⚠️ 声明**只能有一处**（issue #4239：`extract_case_ids()` 取首个声明行即停）——
# 旧写法在 docstring 里另写了一份（AS-001/002/004/007），新口径下它会遮蔽本行、丢掉 DF-008。
import pytest
from unittest.mock import AsyncMock, patch

from app.graph.skills.base_skill import _requires_confirmation
from app.tools.after_sales_manage import AfterSalesManageTool, VALID_ACTIONS


@pytest.fixture
def tool():
    return AfterSalesManageTool()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    return client


class TestAfterSalesReadOnlyConfirmation:
    """destructive 工具只读 action 的确认豁免（DF-008）"""

    def test_read_only_actions_declared(self, tool):
        assert tool.read_only_actions == {"list", "detail"}

    def test_read_only_actions_subset_of_valid_actions(self, tool):
        assert tool.read_only_actions <= VALID_ACTIONS

    def test_list_query_exempt_from_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "list"}, "查售后工单") is False

    def test_detail_query_exempt_from_confirm(self, tool):
        assert _requires_confirmation(tool, {"action": "detail", "ticket_id": "x"}, "查工单详情") is False

    # [RETIRED #5247] test_write_actions_still_require_confirm 已退休：售后写 action（create/update_status）已从 B 端移除（B 端只读化）：写 action 不再存在，确认拦截断言无对象。


class TestAfterSalesPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="list")
        assert result.success is False
        assert "权限" in result.error

    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="close")
        assert result.success is False
        assert "无效的操作类型" in result.error


class TestAfterSalesList:
    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_list_passthrough(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [{"id": "t1", "status": "pending"}], "total": 1},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context,
            action="list",
            page="2",
            size="5",
            status="pending",
            ticket_type="refund",
            keyword="尺寸",
        )

        assert result.success is True
        assert result.data["items"][0]["id"] == "t1"
        assert result.data["total"] == 1
        # 结果数据必须附带中文业务术语标签（禁止英文枚举流入 LLM 回复）
        assert result.data["items"][0]["status_label"] == "待处理"
        params = mock_client.get.call_args[1]["params"]
        assert params["page"] == 2
        assert params["size"] == 5
        assert params["status"] == "pending"
        assert params["ticketType"] == "refund"
        assert params["keyword"] == "尺寸"

    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_list_failure(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": False, "error": {"message": "服务不可用"}})
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="list")
        assert result.success is False
        assert result.error == "服务不可用"

    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_list_enriches_chinese_labels(self, mock_get_client, tool, admin_tool_context, mock_client):
        """列表数据必须附带中文业务术语标签（状态/优先级/类型），
        避免 LLM 把 normal/urgent/critical 等英文枚举原样输出给用户"""
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [
                {"id": "t1", "status": "pending", "priority": "normal", "ticketType": "refund"},
                {"id": "t2", "status": "processing", "priority": "urgent", "ticketType": "complaint"},
            ], "total": 2},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list")

        assert result.success is True
        items = result.data["items"]
        assert items[0]["status_label"] == "待处理"
        assert items[0]["priority_label"] == "普通"
        assert items[0]["ticket_type_label"] == "退款"
        assert items[1]["status_label"] == "处理中"
        assert items[1]["priority_label"] == "紧急"
        assert items[1]["ticket_type_label"] == "投诉"
        # 原始枚举值必须保留（内部推理/API 契约需要）
        assert items[0]["priority"] == "normal"


class TestAfterSalesDetail:
    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_detail_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="detail")
        assert result.success is False
        assert "缺少工单 ID" in result.error
        mock_client.get.assert_not_called()

    @patch("app.tools.after_sales_manage.get_admin_api_client")
    async def test_detail_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        payload = {"id": "t1", "ticketNo": "AS-1", "status": "pending"}
        mock_client.get = AsyncMock(return_value={"success": True, "data": payload})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="detail", ticket_id="t1")
        assert result.success is True
        # 原始字段保留
        assert result.data["id"] == payload["id"]
        assert result.data["ticketNo"] == payload["ticketNo"]
        assert result.data["status"] == payload["status"]
        # 详情数据附带中文状态标签
        assert result.data["status_label"] == "待处理"
        assert mock_client.get.call_args[0][0] == "/api/admin/after-sales/t1"


# [RETIRED #5247] TestAfterSalesCreate（4 例） 已退休：建售后工单（create）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。


# [RETIRED #5247] TestAfterSalesUpdateStatus（5 例） 已退休：工单状态流转（update_status）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。
