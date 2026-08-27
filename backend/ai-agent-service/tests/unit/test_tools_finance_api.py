"""
测试 app.tools.finance_api — 财务对账工具（登记收支/汇总/流水/对账）

对齐行为契约：migao/.github/cases/finance.yml FN-001~003
- FN-001 登记一笔线下收款 → finance_api(action=create_transaction)
- FN-002 本月收入退款净额 → finance_api(action=get_summary)
- FN-003 哪些订单没对平 → finance_api(action=get_reconciliation)
"""
import pytest
from unittest.mock import patch, AsyncMock

from app.tools.finance_api import FinanceApiTool


class TestFinanceApiPermission:
    """权限校验"""

    async def test_customer_role_denied(self, unauthorized_tool_context):
        tool = FinanceApiTool()
        result = await tool.execute(context=unauthorized_tool_context, action="get_summary")
        assert result.success is False


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
        # 校验透传参数
        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs["json"]["type"] == "income"
        assert call_kwargs["json"]["amount"] == 500

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
