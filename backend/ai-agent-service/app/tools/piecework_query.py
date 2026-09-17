"""
AI 智能客服系统 - 计件工资查询 Tool（issue #3996 / M4-I，仅 B 端）

按**冻结契约**（并行包 #3995 提供端点）调用：

    GET /api/admin/agent/production/piecework?worker_name={姓名}&period=YYYY-MM

返回：计件合计 + 明细（工序 / 数量 / 金额）。
权限码 `order:list` 只可能来自商户员工 JWT —— **工人工资不对 C 端顾客开放**（C 端无权限码）。
纯只读（read_only=True），无写操作、无破坏性。
"""

import re
from typing import Any, Dict, Optional

from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult, admin_api_failure
from app.utils.http_client import get_admin_api_client

# 统计月份形态：YYYY-MM（脏参数不发起调用，避免后端 500 与错误归因）
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _fmt_amount(value: Any) -> str:
    """金额展示：1234.0 → '¥1,234.00'（非数值时原样带符号，不编造 0）"""
    try:
        return f"¥{float(value):,.2f}"
    except (TypeError, ValueError):
        return f"¥{value}"


class PieceworkQueryTool(BaseTool):
    """计件工资查询 Tool（仅 B 端商户侧）

    商家问「某工人这个月计件多少 / 某单人工成本 / 计件明细」时调用；
    汇总为 `total`，逐工序明细为 `details`。
    """

    name = "piecework_query"

    description = (
        "【触发】商家问'某工人这个月计件多少''XX 师傅的计件工资''计件明细''某单人工成本'时调用。"
        "【前置】需要 worker_name（工人/师傅姓名）；period 为统计月份（YYYY-MM，如 2026-09），"
        "用户没说月份时不传，由服务端按当月统计（不要自己编月份）。"
        "【反例】查订单金额/货款用 order_query；查经营汇总（营收/看板）用 dashboard_stats；"
        "查员工账号用 employee_manage。"
        "【标注】READONLY — 只读查询计件（工人工资，仅商户员工/管理员可用，不对顾客开放）"
    )

    parameters = {
        "type": "object",
        "properties": {
            "worker_name": {
                "type": "string",
                "description": "工人/师傅姓名（必填，如'王师傅'）",
            },
            "period": {
                "type": "string",
                "description": (
                    "统计月份，格式 YYYY-MM（如 2026-09）。"
                    "用户未指定月份时**不要传**（服务端按当月统计）。"
                ),
            },
        },
        "required": ["worker_name"],
    }

    # 仅 B 端：工人工资/人工成本不对 C 端顾客开放 —— C 端 JWT 没有权限码，天然被挡。
    # 权限码（admin-api 目录）：AgentProductionController / ProductionController 类级
    # `@RequirePermission("order:list")`。
    required_permissions = ["order:list"]
    read_only = True
    destructive = False
    idempotent = True

    async def execute(
        self,
        context: ToolContext,
        worker_name: Optional[str] = None,
        period: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """查询计件工资汇总与明细"""
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询计件",
                suggestion="计件工资仅对商户员工/管理员开放，请引导顾客联系商家核实",
            )

        worker_name = str(worker_name or "").strip()
        if not worker_name:
            return ToolResult(
                success=False,
                error="缺少工人姓名",
                message="请告诉我要查哪位师傅的计件（姓名）",
                suggestion=(
                    "先确认工人姓名（可用 employee_manage 查员工列表核对）再调用本工具；"
                    "禁止编造姓名或工资数据"
                ),
            )

        params: Dict[str, str] = {"worker_name": worker_name}
        period = str(period or "").strip()
        if period:
            if not PERIOD_RE.match(period):
                return ToolResult(
                    success=False,
                    error="月份格式错误",
                    message=f"月份格式应为 YYYY-MM（如 2026-09），收到：{period}",
                    suggestion="按 YYYY-MM 重新传月份；用户未指定月份时不要传 period（默认当月）",
                )
            params["period"] = period

        try:
            client = get_admin_api_client()
            response = await client.get(
                # 冻结契约端点（#3995）；**路径用字面量**：跨模块 payload 契约门禁
                # （tests/test_tool_payload_backend_contract.py）要求调用点可静态归属端点。
                "/api/admin/agent/production/piecework",
                params=params,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(
                f"[piecework-query] Failed | tenant={context.tenant_id} "
                f"error={type(e).__name__}: {e}",
                exc_info=True,
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="查询计件失败，请稍后重试",
                suggestion="请稍后重试；仍失败时如实告知暂时查不到，禁止编造计件金额",
            )

        if not isinstance(response, dict) or not response.get("success"):
            # **必须走共享映射点**（issue #4149 G4）：这一支的 `Or` 形态曾被 L0 锁漏掉
            # （旧判据只认 `not X.get("success")` / `is False`），于是 403 响应在这里被
            # 就地降级成「请稍后重试」——`error_code` 丢失 ⇒ 授权失败还会被自修复重试
            # 再来一遍（拿同一身份调一次永远不可能成功的接口）。
            error_info = response.get("error", {}) if isinstance(response, dict) else {}
            error_msg = (
                error_info.get("message", "查询失败")
                if isinstance(error_info, dict) else str(error_info)
            )
            logger.info(
                f"[piecework-query] Rejected | tenant={context.tenant_id} error={error_msg}"
            )
            return admin_api_failure(
                response,
                error=error_msg,
                message="查询计件失败，请稍后重试",
                suggestion=(
                    "先核对工人姓名与月份（可用 employee_manage 查员工）；"
                    "仍查不到时如实告知，禁止编造计件金额"
                ),
            )

        data = response.get("data")
        if not isinstance(data, dict) or not data:
            return ToolResult(
                success=False,
                error="NOT_FOUND",
                message=f"未查到 {worker_name} 的计件记录",
                suggestion=(
                    "该工人在此月份可能没有报工记录：先核对姓名与月份"
                    "（可用 employee_manage 查员工），不要编造计件金额"
                ),
            )

        period_label = data.get("period") or period
        worker_label = data.get("worker_name") or worker_name
        logger.info(
            f"[piecework-query] Fetched | tenant={context.tenant_id} worker={worker_label} "
            f"period={period_label}"
        )

        # LLM 友好摘要：王师傅 2026-09 计件合计 ¥1,234.00
        summary = f"{worker_label} {period_label} 计件合计 {_fmt_amount(data.get('total'))}"

        return ToolResult(
            success=True,
            data=data,
            message=f"{worker_label} 的计件数据已获取",
            summary=summary,
        )
