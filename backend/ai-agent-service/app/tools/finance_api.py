"""
AI 智能客服系统 - 财务对账 Tool

面向商家运营的财务能力：登记线下收支、收支汇总、资金流水、应收对账。
对齐行为契约 finance.yml（FN-001~003）：
- FN-001 登记一笔线下收款 → action=create_transaction
- FN-002 本月收入退款净额 → action=get_summary
- FN-003 哪些订单没对平 → action=get_reconciliation
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"create_transaction", "get_summary", "get_transactions", "get_reconciliation"}


class FinanceApiTool(BaseTool):
    """财务对账 Tool

    提供资金流水登记/查询、收支汇总、应收对账能力。

    使用场景：
    - 登记一笔线下收款或退款（create_transaction）
    - 查看收入/退款/净额汇总（get_summary）
    - 查看资金流水列表（get_transactions）
    - 查看应收对账（订单应收 vs 实收差额，get_reconciliation）
    """

    name = "finance_api"
    description = (
        "【触发】用户说'登记收款''登记退款''记一笔账''资金流水''收支''对账''净额''收入''进账''收了多少''赚了多少'时调用。【何时用】任何资金/财务/对账类查询或登记。【何时不用】查订单金额（用 order_query）、看经营看板（用 dashboard_stats）。【前置】action: create_transaction(登记收支,需type+amount)/get_summary(收支汇总)/get_transactions(资金流水)/get_reconciliation(应收对账)。【标注】create_transaction 为 WRITE — 登记前需确认"
    )
    allowed_roles = ["admin", "tenant_admin", "operation_manager"]

    read_only = False
    requires_confirmation = True  # 审计 07 P0-L1: 高风险非 destructive 写操作需用户确认
    destructive = False
    read_only_actions = frozenset({"get_summary", "get_transactions", "get_reconciliation"})
    idempotent = False

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型：create_transaction（登记收支，需 type+amount）/ "
                    "get_summary（收支汇总）/ get_transactions（资金流水）/ "
                    "get_reconciliation（应收对账）"
                ),
                "enum": ["create_transaction", "get_summary", "get_transactions", "get_reconciliation"],
            },
            "type": {
                "type": "string",
                "description": "收支类型，仅 create_transaction 时必填：income（收款）/ refund（退款）",
                "enum": ["income", "refund"],
            },
            "amount": {
                "type": "number",
                "description": "金额（元），仅 create_transaction 时必填，必须大于 0",
                "minimum": 0.01,
            },
            "payment_method": {
                "type": "string",
                "description": "支付方式（create_transaction 可选）：wechat / alipay / cash / bank_transfer",
                "enum": ["wechat", "alipay", "cash", "bank_transfer"],
            },
            "order_id": {
                "type": "string",
                "description": "关联订单号或订单 UUID（create_transaction 可选）",
            },
            "remark": {
                "type": "string",
                "description": "备注（create_transaction 可选）",
            },
            "keyword": {
                "type": "string",
                "description": "关键词搜索（get_transactions / get_reconciliation 可选）：流水号或订单号",
            },
            "start_date": {
                "type": "string",
                "description": "开始日期 YYYY-MM-DD（可选）",
            },
            "end_date": {
                "type": "string",
                "description": "结束日期 YYYY-MM-DD（可选）",
            },
            "page": {
                "type": "integer",
                "description": "页码，默认 1",
                "default": 1,
            },
            "size": {
                "type": "integer",
                "description": "每页条数，默认 10",
                "default": 10,
            },
        },
        "required": ["action"],
    }

    async def execute(self, context: ToolContext, action: str, **kwargs) -> ToolResult:
        """执行财务操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限操作财务数据",
                suggestion="请联系管理员开通财务权限",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(sorted(VALID_ACTIONS))}",
                suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
            )

        try:
            if action == "create_transaction":
                return await self._create_transaction(context, **kwargs)
            elif action == "get_summary":
                return await self._get_summary(context, **kwargs)
            elif action == "get_transactions":
                return await self._get_transactions(context, **kwargs)
            elif action == "get_reconciliation":
                return await self._get_reconciliation(context, **kwargs)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型",
                )
        except Exception as e:
            logger.error(f"[finance-api] Error: action={action}, error={type(e).__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="财务操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    async def _create_transaction(self, context: ToolContext, **kwargs) -> ToolResult:
        """登记一笔线下收支（FN-001）"""
        # 校验必填：type + amount
        txn_type = kwargs.get("type")
        amount = kwargs.get("amount")
        if not txn_type or txn_type not in ("income", "refund"):
            return ToolResult(
                success=False,
                error="参数不完整",
                message="登记收支需要提供收支类型（income 收款 / refund 退款）",
                suggestion="请说明是收款还是退款，以及具体金额，例如：登记一笔线下收款 500 元",
            )
        if amount is None:
            return ToolResult(
                success=False,
                error="参数不完整",
                message="登记收支需要提供金额",
                suggestion="请提供具体金额，例如：登记一笔线下收款 500 元",
            )
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return ToolResult(
                success=False,
                error="参数无效",
                message="金额格式不正确",
                suggestion="请输入数字金额，例如：500 或 500.00",
            )
        if amount <= 0:
            return ToolResult(
                success=False,
                error="参数无效",
                message="金额必须大于 0",
                suggestion="请输入大于 0 的金额",
            )

        payload: Dict[str, Any] = {
            "type": txn_type,
            "amount": amount,
        }
        if kwargs.get("payment_method"):
            payload["paymentMethod"] = kwargs["payment_method"]
        if kwargs.get("order_id"):
            payload["orderId"] = kwargs["order_id"]
        if kwargs.get("remark"):
            payload["remark"] = kwargs["remark"]

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/finance/transactions",
            json=payload,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not isinstance(response, dict):
            response = {"data": response} if isinstance(response, list) else {}

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "登记失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message="收支登记失败",
                suggestion="请检查参数后重试，或联系技术支持",
            )

        data = response.get("data", {})
        txn_no = data.get("transactionNo") or data.get("transaction_no") or "已生成"
        type_label = "收款" if txn_type == "income" else "退款"
        logger.info(f"[finance-api] Transaction created | tenant={context.tenant_id} type={txn_type} amount={amount}")
        return ToolResult(
            success=True,
            data=data,
            message=f"{type_label}登记成功，流水号：{txn_no}",
            summary=f"已登记{type_label}{amount}元，流水号{txn_no}",
        )

    async def _get_summary(self, context: ToolContext, **kwargs) -> ToolResult:
        """收支汇总（FN-002）"""
        params: Dict[str, Any] = {}
        if kwargs.get("start_date"):
            params["startDate"] = kwargs["start_date"]
        if kwargs.get("end_date"):
            params["endDate"] = kwargs["end_date"]

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/finance/summary",
            params=params or None,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not isinstance(response, dict):
            response = {"data": response} if isinstance(response, list) else {}

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message="收支汇总查询失败",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
        total_income = data.get("totalIncome", 0)
        total_refund = data.get("totalRefund", 0)
        net_income = data.get("netIncome", total_income - total_refund)
        pending = data.get("pendingReceivable", 0)
        logger.info(f"[finance-api] Summary fetched | tenant={context.tenant_id}")
        return ToolResult(
            success=True,
            data=data,
            message="收支汇总数据已获取",
            summary=f"收入{total_income}元, 退款{total_refund}元, 净收入{net_income}元, 待收款{pending}元",
        )

    async def _get_transactions(self, context: ToolContext, **kwargs) -> ToolResult:
        """资金流水查询"""
        params: Dict[str, Any] = {
            "page": kwargs.get("page", 1),
            "size": kwargs.get("size", 10),
        }
        if kwargs.get("keyword"):
            params["keyword"] = kwargs["keyword"]
        if kwargs.get("start_date"):
            params["startDate"] = kwargs["start_date"]
        if kwargs.get("end_date"):
            params["endDate"] = kwargs["end_date"]

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/finance/transactions",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not isinstance(response, dict):
            response = {"data": response} if isinstance(response, list) else {}

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message="资金流水查询失败",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
        items = data.get("items") if isinstance(data, dict) else data
        total = data.get("total", len(items)) if isinstance(data, dict) else len(items)
        logger.info(f"[finance-api] Transactions fetched | tenant={context.tenant_id} total={total}")
        return ToolResult(
            success=True,
            data={"items": items, "total": total},
            message=f"共 {total} 条资金流水",
            summary=f"查询到 {total} 条资金流水",
        )

    async def _get_reconciliation(self, context: ToolContext, **kwargs) -> ToolResult:
        """应收对账（FN-003）"""
        params: Dict[str, Any] = {
            "page": kwargs.get("page", 1),
            "size": kwargs.get("size", 10),
        }
        if kwargs.get("keyword"):
            params["keyword"] = kwargs["keyword"]
        if kwargs.get("start_date"):
            params["startDate"] = kwargs["start_date"]
        if kwargs.get("end_date"):
            params["endDate"] = kwargs["end_date"]

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/finance/reconciliation",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not isinstance(response, dict):
            response = {"data": response} if isinstance(response, list) else {}

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message="应收对账查询失败",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
        items = data.get("items") if isinstance(data, dict) else data
        total = data.get("total", len(items)) if isinstance(data, dict) else len(items)
        # 标注差额异常项
        anomalies = [it for it in (items or []) if it.get("difference") != 0]
        logger.info(f"[finance-api] Reconciliation fetched | tenant={context.tenant_id} total={total} anomalies={len(anomalies)}")
        return ToolResult(
            success=True,
            data={"items": items, "total": total},
            message=f"共 {total} 条对账记录，其中 {len(anomalies)} 条存在差额",
            summary=f"对账记录 {total} 条，未对平 {len(anomalies)} 条",
        )
