"""
测试 app.tools.finance_api — 财务对账工具（登记收支/汇总/流水/对账）

B 端只读化（issue #5247）：finance_api（财务对账） 的写 action 已删除 ⇒ 本次退休写路径用例（产品裁定，非放宽门禁）。

对齐行为契约：migao/.github/cases/finance.yml FN-001~003
- FN-001 登记一笔线下收款 → finance_api(action=create_transaction)
- FN-002 本月收入退款净额 → finance_api(action=get_summary)
- FN-003 哪些订单没对平 → finance_api(action=get_reconciliation)
"""
# case_ids: FN-001, FN-002, FN-003

import inspect

import pytest
from unittest.mock import patch, AsyncMock

from app.tools.finance_api import FinanceApiTool
from app.utils.http_client import AdminApiClient


class TestFinanceApiPermission:
    """权限校验"""

    async def test_customer_role_denied(self, unauthorized_tool_context):
        tool = FinanceApiTool()
        result = await tool.execute(context=unauthorized_tool_context, action="get_summary")
        assert result.success is False


class TestFinanceApiClientKwargsContract:
    """issue #3548：自研客户端 post() 只接受 json_data（httpx 风格的 json= 必 TypeError）"""

    def test_admin_api_client_post_has_no_json_kwarg(self):
        """契约锚点：自研客户端签名就是 json_data，且无 **kwargs 兜底"""
        params = inspect.signature(AdminApiClient.post).parameters
        assert "json_data" in params, f"客户端 post 签名变更: {list(params)}"
        assert "json" not in params, "客户端 post 不应接受 httpx 风格的 json= 关键字"
        assert not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()), \
            "客户端 post 不得有 **kwargs（否则调用方拼错关键字不会被拦截）"

    # [RETIRED #5247] test_create_transaction_success_with_strict_client 已退休：登记收支（create_transaction）已从 B 端移除（B 端只读化）：写请求不再存在，json_data 透传断言无对象。

    # [RETIRED #5247] test_client_error_surfaces_as_failure_not_success 已退休：登记收支（create_transaction）已从 B 端移除（B 端只读化）：写请求不再存在，断言无对象。

    # [RETIRED #5247] test_business_failure_returns_success_false 已退休：登记收支（create_transaction）已从 B 端移除（B 端只读化）：写请求不再存在，断言无对象。


class TestFinanceApiActions:
    """各 action 测试"""

    # [RETIRED #5247] test_create_transaction_success 已退休：登记收支（create_transaction）已从 B 端移除（B 端只读化）：写能力不再存在，断言无对象。

    # [RETIRED #5247] test_create_transaction_missing_amount 已退休：登记收支（create_transaction）已从 B 端移除（B 端只读化）：金额必填契约随之消失，断言无对象。

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_get_summary_success(self, mock_get_client, admin_tool_context):
        """FN-002 契约：收支汇总 netIncome = totalIncome - totalRefund"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {
                "totalIncome": 10000.0,
                "totalRefund": 2000.0,
                "netIncome": 8000.0,
                "pendingReceivable": 500.0,
            },
        })
        mock_get_client.return_value = mock_client

        tool = FinanceApiTool()
        result = await tool.execute(context=admin_tool_context, action="get_summary")

        assert result.success is True
        assert result.data["netIncome"] == result.data["totalIncome"] - result.data["totalRefund"]

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_get_transactions_success(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [{"transactionNo": "FIN-001", "type": "income", "amount": 500.0}], "total": 1},
        })
        mock_get_client.return_value = mock_client

        tool = FinanceApiTool()
        result = await tool.execute(context=admin_tool_context, action="get_transactions")

        assert result.success is True
        assert len(result.data["items"]) == 1

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_get_reconciliation_success(self, mock_get_client, admin_tool_context):
        """FN-003 契约：应收对账 difference = receivedAmount - receivableAmount"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"items": [{"orderNo": "ORD001", "receivableAmount": 100.0, "receivedAmount": 80.0, "difference": -20.0}], "total": 1},
        })
        mock_get_client.return_value = mock_client

        tool = FinanceApiTool()
        result = await tool.execute(context=admin_tool_context, action="get_reconciliation")

        assert result.success is True
        item = result.data["items"][0]
        assert item["difference"] == item["receivedAmount"] - item["receivableAmount"]

    async def test_invalid_action(self, admin_tool_context):
        tool = FinanceApiTool()
        result = await tool.execute(context=admin_tool_context, action="not_a_real_action")
        assert result.success is False


class TestFinancePeriodDefaults:
    """FN-004 参数契约回归：get_summary/get_transactions/get_reconciliation
    缺时间参数时自动补本期默认（本月1号~今天）——agent 偶发不传时间参数，
    服务端默认避免「无时间范围查询」与 case 断言冲突。"""

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_get_summary_defaults_to_current_period(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"netIncome": 1.0}})
        mock_get_client.return_value = mock_client

        tool = FinanceApiTool()
        result = await tool.execute(context=admin_tool_context, action="get_summary")
        assert result.success is True
        # 校验请求参数含本期默认 startDate/endDate
        call_kwargs = mock_client.get.call_args.kwargs
        params = call_kwargs.get("params") or {}
        assert params.get("startDate") is not None, f"缺默认 startDate: {params}"
        assert params.get("endDate") is not None, f"缺默认 endDate: {params}"
        import datetime as dt
        assert params["endDate"] == dt.date.today().isoformat()

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_get_transactions_defaults_to_current_period(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": []}})
        mock_get_client.return_value = mock_client

        tool = FinanceApiTool()
        result = await tool.execute(context=admin_tool_context, action="get_transactions")
        assert result.success is True
        params = mock_client.get.call_args.kwargs.get("params") or {}
        assert params.get("startDate") is not None
        assert params.get("endDate") is not None

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_get_reconciliation_defaults_to_current_period(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": []}})
        mock_get_client.return_value = mock_client

        tool = FinanceApiTool()
        result = await tool.execute(context=admin_tool_context, action="get_reconciliation")
        assert result.success is True
        params = mock_client.get.call_args.kwargs.get("params") or {}
        assert params.get("startDate") is not None
        assert params.get("endDate") is not None
