"""
AI 智能客服系统 - 财务对账 Tool

面向商家运营的财务能力：登记线下收支、收支汇总、资金流水、应收对账。
对齐行为契约 finance.yml（FN-001~003）：
- FN-001 登记一笔线下收款 → action=create_transaction
- FN-002 本月收入退款净额 → action=get_summary
- FN-003 哪些订单没对平 → action=get_reconciliation
"""

import datetime as _dt
import math
from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"get_summary", "get_transactions", "get_reconciliation"}

# issue #8120：收支汇总对比的四项口径（与 get_summary 的 data 键逐字一致）。
COMPARE_FIELDS = ("totalIncome", "totalRefund", "netIncome", "pendingReceivable")


def _is_true(value: Any) -> bool:
    """工具入参布尔归一（模型可能给 True / "true" / 1）。"""
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return value is True or value == 1


def _previous_period(start: _dt.date, end: _dt.date) -> tuple:
    """与本期**等长**且**紧邻其前**的区间（上一期 end = 本期 start 的前一天）。"""
    length = (end - start).days + 1
    previous_end = start - _dt.timedelta(days=1)
    previous_start = previous_end - _dt.timedelta(days=length - 1)
    return previous_start, previous_end


def _summary_metrics(payload: Dict[str, Any]) -> Dict[str, float]:
    """四项的**数值**口径（缺 netIncome 时按 income - refund 推导，与 get_summary 一致）。"""

    def _num(raw: Any, default: float = 0.0) -> float:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return default
        number = float(raw)
        return number if math.isfinite(number) else default

    income = _num(payload.get("totalIncome"))
    refund = _num(payload.get("totalRefund"))
    net = payload.get("netIncome")
    return {
        "totalIncome": income,
        "totalRefund": refund,
        "netIncome": _num(net, round(income - refund, 2)),
        "pendingReceivable": _num(payload.get("pendingReceivable")),
    }


def _build_summary_compare(
    current: Dict[str, Any],
    previous: Dict[str, Any],
    current_span: tuple,
    previous_span: tuple,
) -> Dict[str, Any]:
    """上一期四项 + 逐项 delta / delta_pct（上期为 0 ⇒ delta_pct=None，绝不 Infinity/NaN）。"""
    current_metrics = _summary_metrics(current)
    previous_metrics = _summary_metrics(previous)
    delta: Dict[str, float] = {}
    delta_pct: Dict[str, Optional[float]] = {}
    previous_is_zero: Dict[str, bool] = {}
    for field in COMPARE_FIELDS:
        current_value = current_metrics[field]
        previous_value = previous_metrics[field]
        change = round(current_value - previous_value, 2)
        zero = previous_value == 0
        delta[field] = change
        previous_is_zero[field] = zero
        delta_pct[field] = None if zero else round(change / previous_value * 100, 2)
    return {
        "period": {
            "startDate": current_span[0].isoformat(),
            "endDate": current_span[1].isoformat(),
        },
        "previous_period": {
            "startDate": previous_span[0].isoformat(),
            "endDate": previous_span[1].isoformat(),
        },
        "previous": previous_metrics,
        "delta": delta,
        "delta_pct": delta_pct,
        "previous_is_zero": previous_is_zero,
    }


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
        "【触发】用户说'登记收款''登记退款''记一笔账''资金流水''收支''对账''净额''收入''进账'"
        "'收了多少''赚了多少'时调用（任何资金/财务/对账类查询或登记）。"
        "【参数】action 必填：**只有 get_summary(收支汇总, 可选 compare=true 给等长上一期对比) / "
        "get_transactions(资金流水) / "
        "get_reconciliation(应收对账) 三个只读 action**（B 端已只读化，issue #5247）。"
        "【反例】查订单金额/明细用 order_query；看经营看板/趋势用 dashboard_stats。"
        "【反例】登记收支**不在本工具能力内**——引导用户到后台「财务对账」页登记。"
        "【标注】READONLY — 纯查询，不含任何写 action"
        "【不要用于】工人计件工资/人工成本（用 piecework_query）；售后工单的退款进度（用 after_sales_manage）"
    )
    # 权限码（admin-api 目录）：读面 `finance:view`；issue #5246 起 `POST /finance/transactions`
    # （登记收支）走写码 `finance:create`（此前挂在读码上）。旧白名单里的 `operation_manager`
    # 在 admin-api 里根本不存在（角色码漂移）。
    required_permissions = ["finance:view"]  # B 端只读化（#5247）：写码 finance:create 已随 create_transaction 移除

    read_only = True
    destructive = False
    read_only_actions = frozenset({"get_summary", "get_transactions", "get_reconciliation"})
    idempotent = False

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：get_summary（收支汇总）/ get_transactions（资金流水）/ get_reconciliation（应收对账）—— 均为只读",
                "enum": ["get_summary", "get_transactions", "get_reconciliation"],
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
            "compare": {
                "type": "boolean",
                "description": (
                    "仅在 action=get_summary 时生效：true ⇒ 再查**等长上一期**（本期 start 前推一个周期），"
                    "返回上一期四项 + 逐项 delta / delta_pct。问“这个月比上个月呢”时传 true，"
                    "不要自己口算，也不要拆成两次不同区间的查询。默认 false。"
                ),
                "default": False,
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
            if action == "get_summary":
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
    async def _get_summary(self, context: ToolContext, **kwargs) -> ToolResult:
        """收支汇总（FN-002）"""
        params: Dict[str, Any] = {}
        # FN-004 参数契约：缺时间参数自动补本期默认（本月1号~今天）
        import datetime as _dt
        _today = _dt.date.today()
        params["startDate"] = kwargs.get("start_date") or _today.replace(day=1).isoformat()
        params["endDate"] = kwargs.get("end_date") or _today.isoformat()

        # issue #8120：compare=true ⇒ 上一期 = 与本期**等长**且**紧邻其前**的区间。
        # 日期不可解析时**先失败、不发任何查询**（不拿半段数据算对比）。
        compare = _is_true(kwargs.get("compare"))
        current_span: Optional[tuple] = None
        previous_span: Optional[tuple] = None
        if compare:
            try:
                current_span = (
                    _dt.date.fromisoformat(str(params["startDate"])),
                    _dt.date.fromisoformat(str(params["endDate"])),
                )
            except ValueError:
                return ToolResult(
                    success=False,
                    error="invalid_date_range",
                    message="时间范围格式不正确（需 YYYY-MM-DD），无法计算上一期对比",
                    suggestion="请按 YYYY-MM-DD 提供 start_date / end_date 后重试",
                )
            if current_span[1] < current_span[0]:
                return ToolResult(
                    success=False,
                    error="invalid_date_range",
                    message="开始日期晚于结束日期，无法计算上一期对比",
                    suggestion="请确认 start_date 早于或等于 end_date 后重试",
                )
            previous_span = _previous_period(*current_span)

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
            return admin_api_failure(response,
                error=error_msg,
                message="收支汇总查询失败",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
        if compare and not isinstance(data, dict):
            return admin_api_failure(response,
                error="unexpected_summary_payload",
                message="收支汇总数据格式异常，无法给出对比",
                suggestion="请稍后重试；本次不返回估算值",
            )
        message = "收支汇总数据已获取"
        if compare:
            previous_params = {
                "startDate": previous_span[0].isoformat(),
                "endDate": previous_span[1].isoformat(),
            }
            previous_response = await client.get(
                "/api/admin/finance/summary",
                params=previous_params,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
            if not isinstance(previous_response, dict):
                previous_response = (
                    {"data": previous_response} if isinstance(previous_response, list) else {}
                )
            if not previous_response.get("success"):
                previous_error = previous_response.get("error", {}).get("message", "查询失败")
                return admin_api_failure(previous_response,
                    error=previous_error,
                    message=(
                        f"上一期（{previous_params['startDate']}~{previous_params['endDate']}）"
                        "收支汇总查询失败，无法给出对比"
                    ),
                    suggestion="请稍后重试；本次不返回估算的上一期数字",
                )
            previous_data = previous_response.get("data", {})
            if not isinstance(previous_data, dict):
                return admin_api_failure(previous_response,
                    error="unexpected_summary_payload",
                    message="上一期收支汇总数据格式异常，无法给出对比",
                    suggestion="请稍后重试；本次不返回估算值",
                )
            data = dict(data)
            data["compare"] = _build_summary_compare(
                data, previous_data, current_span, previous_span
            )
            message += (
                f"（含上一期对比：本期 {current_span[0]}~{current_span[1]}，"
                f"上期 {previous_span[0]}~{previous_span[1]}）"
            )
        total_income = data.get("totalIncome", 0)
        total_refund = data.get("totalRefund", 0)
        net_income = data.get("netIncome", total_income - total_refund)
        pending = data.get("pendingReceivable", 0)
        logger.info(f"[finance-api] Summary fetched | tenant={context.tenant_id}")
        return ToolResult(
            success=True,
            data=data,
            message=message,
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
        # FN-004 参数契约：缺时间参数自动补本期默认（本月1号~今天）
        import datetime as _dt
        _today = _dt.date.today()
        params["startDate"] = kwargs.get("start_date") or _today.replace(day=1).isoformat()
        params["endDate"] = kwargs.get("end_date") or _today.isoformat()

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
            return admin_api_failure(response,
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
        # FN-004 参数契约：缺时间参数自动补本期默认（本月1号~今天）
        import datetime as _dt
        _today = _dt.date.today()
        params["startDate"] = kwargs.get("start_date") or _today.replace(day=1).isoformat()
        params["endDate"] = kwargs.get("end_date") or _today.isoformat()

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
            return admin_api_failure(response,
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
