"""
AI 智能客服系统 - 生产进度查询 Tool（issue #3996 / M4-I）

按**冻结契约**（并行包 #3995 提供端点）调用：

    GET /api/admin/agent/production/progress?order_no={订单号}

返回：进度百分比 / 当前工序 / 待完工序 / 预计交期。
双端可用：C 端顾客查自己的订单进度（小布），B 端商户员工查任意单（米宝）。
纯只读（read_only=True），无写操作、无破坏性。
"""

from typing import Any, Dict, Optional

from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client

# 冻结契约端点（#3995）
PROGRESS_ENDPOINT = "/api/admin/agent/production/progress"


def _fmt_percent(value: Any) -> str:
    """进度百分比展示：60.0 → '60'、60.5 → '60.5'、缺失 → '未知'（不编造 0%）"""
    if value is None:
        return "未知"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(num)) if num.is_integer() else f"{num:g}"


class ProductionProgressQueryTool(BaseTool):
    """生产进度查询 Tool（双端只读）

    调 admin-api 冻结契约端点，把「订单做到哪道工序/还剩哪些工序/预计何时交付」
    转成 LLM 与顾客都能读懂的摘要；查询失败一律给 suggestion（禁止编造进度）。
    """

    name = "production_progress_query"

    description = (
        "【触发】用户问'订单做到哪了''生产进度''还要多久能好''卡在哪道工序''排产了吗/什么时候发货'时调用。"
        "【前置】需要订单号 order_no；用户没给订单号时**先查订单拿号**"
        "（商户端用 order_query，顾客本人订单用 customer_order_query），不要猜号。"
        "【反例】查物流/快递用 logistics_track（顾客本人用 customer_logistics_track）；"
        "查订单金额/状态/明细用 order_query（C 端 customer_order_query）；"
        "查经营汇总用 dashboard_stats。"
        "【标注】READONLY — 只读查询生产进度，不改动任何数据"
    )

    parameters = {
        "type": "object",
        "properties": {
            "order_no": {
                "type": "string",
                "description": (
                    "订单号（如 ORD-20260917-0001），必填。"
                    "用户未提供时先用订单查询工具取号（order_query / customer_order_query），"
                    "禁止编造或猜测订单号。"
                ),
            },
        },
        "required": ["order_no"],
    }

    # 双端：顾客查自己的单（C 端），商户员工/管理员查任意单（B 端）
    allowed_roles = ["customer", "admin", "agent", "tenant_admin"]
    read_only = True
    destructive = False
    idempotent = True

    async def execute(
        self,
        context: ToolContext,
        order_no: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """查询订单的生产进度"""
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询生产进度",
                suggestion="请联系管理员开通生产进度查询权限",
            )

        order_no = str(order_no or "").strip()
        if not order_no:
            return ToolResult(
                success=False,
                error="缺少订单号",
                message="请先告诉我订单号，我才能帮您查生产进度",
                suggestion=(
                    "用订单查询工具拿到订单号后再调用本工具：商户端 order_query、"
                    "顾客本人订单 customer_order_query（可列出在途订单让用户选择）；"
                    "禁止编造订单号"
                ),
            )

        try:
            client = get_admin_api_client()
            response = await client.get(
                PROGRESS_ENDPOINT,
                params={"order_no": order_no},
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(
                f"[production-progress] Failed | tenant={context.tenant_id} "
                f"order_no={order_no} error={type(e).__name__}: {e}",
                exc_info=True,
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="查询生产进度失败，请稍后重试",
                suggestion="请稍后重试；仍失败时如实告知用户暂时查不到，可转人工核实，禁止编造生产进度",
            )

        if not isinstance(response, dict) or not response.get("success"):
            error_info = response.get("error", {}) if isinstance(response, dict) else {}
            error_msg = (
                error_info.get("message", "查询失败")
                if isinstance(error_info, dict) else str(error_info)
            )
            logger.info(
                f"[production-progress] Rejected | tenant={context.tenant_id} "
                f"order_no={order_no} error={error_msg}"
            )
            return ToolResult(
                success=False,
                error=error_msg,
                message="查询生产进度失败，请稍后重试",
                suggestion=(
                    "先核对订单号是否正确（可用 order_query / customer_order_query 复核）；"
                    "仍查不到时如实告知用户，可转人工核实，禁止编造生产进度"
                ),
            )

        data = response.get("data")
        if not isinstance(data, dict) or not data:
            return ToolResult(
                success=False,
                error="NOT_FOUND",
                message=f"未查到订单 {order_no} 的生产进度",
                suggestion=(
                    "该订单可能尚未进入生产或订单号有误：先用 order_query / "
                    "customer_order_query 复核订单号与状态，不要编造进度或交期"
                ),
            )

        logger.info(
            f"[production-progress] Fetched | tenant={context.tenant_id} order_no={order_no} "
            f"percent={data.get('progress_percent')}"
        )

        current = data.get("current_operation") or ""
        eta = data.get("expected_delivery_date") or ""

        # LLM 友好摘要：生产进度 60%（当前：韩褶-布），预计交付 2026-09-25
        summary = f"生产进度 {_fmt_percent(data.get('progress_percent'))}%"
        if current:
            summary += f"（当前：{current}）"
        if eta:
            summary += f"，预计交付 {eta}"

        return ToolResult(
            success=True,
            data=data,
            message=f"订单 {order_no} 的生产进度已获取",
            summary=summary,
        )
