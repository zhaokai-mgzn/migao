"""
测试 app.tools.finance_api — 财务对账工具（登记收支/汇总/流水/对账）

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


class _StrictAdminApiClient:
    """自研 admin-api 客户端的「严格替身」——签名与 AdminApiClient.post 逐字一致。

    为什么不用 AsyncMock：AsyncMock 接受任意 kwargs，会把调用方「关键字拼错」这类
    错误一并吞掉（issue #3548 的 bug 正是因此逃过单测）。严格签名复现真实运行期行为：
    传 `json=` → TypeError → 登记收支必然失败。
    """

    def __init__(self, response=None):
        self.response = response if response is not None else {"success": True, "data": {}}
        self.calls = []

    async def post(self, path, data=None, json_data=None, tenant_id=None, user_id=None, headers=None):
        self.calls.append({
            "path": path,
            "data": data,
            "json_data": json_data,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "headers": headers,
        })
        return self.response


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

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_create_transaction_success_with_strict_client(self, mock_get_client, admin_tool_context):
        """FN-001 核心：严格签名客户端下登记收支必须成功，且透传 json_data=payload"""
        client = _StrictAdminApiClient({
            "success": True,
            "data": {"id": "fin-001", "transactionNo": "FIN-202609150001",
                     "type": "income", "amount": 88.0, "status": "success"},
        })
        mock_get_client.return_value = client

        tool = FinanceApiTool()
        result = await tool.execute(
            context=admin_tool_context,
            action="create_transaction",
            type="income",
            amount=88,
            payment_method="wechat",
        )

        assert result.success is True, (
            f"登记收支未成功: error={result.error!r} message={result.message!r} "
            f"（严格签名客户端下传错关键字会 TypeError）"
        )
        assert len(client.calls) == 1, "应恰好调用一次客户端 post"
        call = client.calls[0]
        assert call["path"] == "/api/admin/finance/transactions"
        assert call["json_data"] == {"type": "income", "amount": 88.0, "paymentMethod": "wechat"}
        assert call["data"] is None, "payload 必须走 json_data，不得误走 data（form 编码）"
        assert call["tenant_id"] == admin_tool_context.tenant_id
        assert call["user_id"] == admin_tool_context.user_id
        assert "FIN-202609150001" in result.message

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_client_error_surfaces_as_failure_not_success(self, mock_get_client, admin_tool_context):
        """失败不得被静默降级为成功：客户端抛错时必须 success=False 且带 error"""
        class _BrokenClient:
            async def post(self, path, data=None, json_data=None, tenant_id=None, user_id=None, headers=None):
                raise TypeError("post() got an unexpected keyword argument 'json'")

        mock_get_client.return_value = _BrokenClient()

        tool = FinanceApiTool()
        result = await tool.execute(
            context=admin_tool_context, action="create_transaction", type="income", amount=88,
        )

        assert result.success is False, "工具异常必须以失败暴露给上层，不能伪装成功"
        assert result.error == "tool_execution_failed"
        assert result.message, "失败必须给出用户可读消息"

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_business_failure_returns_success_false(self, mock_get_client, admin_tool_context):
        """admin-api 业务失败（success=False）同样不得被当成登记成功"""
        client = _StrictAdminApiClient({
            "success": False,
            "error": {"code": "INVALID_PARAM", "message": "金额非法"},
            "data": None,
        })
        mock_get_client.return_value = client

        tool = FinanceApiTool()
        result = await tool.execute(
            context=admin_tool_context, action="create_transaction", type="income", amount=88,
        )

        assert result.success is False
        assert result.error == "金额非法"


class TestFinanceApiActions:
    """各 action 测试"""

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_create_transaction_success(self, mock_get_client, admin_tool_context):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={
            "success": True,
            "data": {"id": "fin-001", "transactionNo": "FIN-202608270001", "type": "income", "amount": 500.0},
        })
        mock_get_client.return_value = mock_client

        tool = FinanceApiTool()
        result = await tool.execute(
            context=admin_tool_context,
            action="create_transaction",
            type="income",
            amount=500,
            payment_method="wechat",
            remark="线下收款",
        )

        assert result.success is True
        assert result.summary is not None
        # 校验透传参数（issue #3548：自研客户端关键字是 json_data，旧断言 json 把 bug 固化成"期望"）
        call_kwargs = mock_client.post.call_args.kwargs
        assert "json" not in call_kwargs
        assert call_kwargs["json_data"]["type"] == "income"
        assert call_kwargs["json_data"]["amount"] == 500

    @patch("app.tools.finance_api.get_admin_api_client")
    async def test_create_transaction_missing_amount(self, mock_get_client, admin_tool_context):
        """FN-001 契约：登记收支必须携带金额，缺失时应给出可修复建议"""
        mock_get_client.return_value = AsyncMock()

        tool = FinanceApiTool()
        result = await tool.execute(context=admin_tool_context, action="create_transaction")

        assert result.success is False
        assert result.suggestion is not None and len(result.suggestion) > 0

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
