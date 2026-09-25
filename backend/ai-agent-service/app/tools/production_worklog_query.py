"""
AI 智能客服系统 - 加工单「过程明细」查询 Tool（issue #4201，仅 B 端）

按**冻结契约**（同族先例 #3995 的 progress / piecework）调用：

    GET /api/admin/agent/production/worklog?order_no={订单号}

返回：**工序实例**（做到哪一步：应做/合格/返工/报废、状态、分组）+ **报工明细**
（谁报的、报了多少、正常/返工/报废、日期）+ 数量与计件金额合计。

口径（**与端点同源，工具层不重算**）：
  · 「下料」= 工序库**裁剪组**（`group_name=裁剪`）—— 不是另一个模型；
  · 合格 = `work_type=normal` 的合格数；返工/报废各取该笔报工数量（返工/报废**不计件**）；
  · 计件金额由服务端按**同一份**聚合给出（rework/scrap 排除）⇒ 本工具禁止自行心算。

权限码 `order:list` 只可能来自商户员工 JWT —— 报文明细含**报工人与计件金额**（车间/工资面），
**不对 C 端顾客开放**（C 端无权限码，天然被挡）。纯只读（read_only=True），无写操作。
"""

from typing import Any, Dict, Optional

from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult, admin_api_failure
from app.utils.http_client import get_admin_api_client


def _fmt_num(value: Any) -> str:
    """数量展示：12.0 → '12'、12.5 → '12.5'、缺失 → '未知'（不编造 0）"""
    if value is None:
        return "未知"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(num)) if num.is_integer() else f"{num:g}"


def _fmt_amount(value: Any) -> str:
    """金额展示：4.0 → '¥4.00'（非数值时原样带符号，不编造 0）"""
    try:
        return f"¥{float(value):,.2f}"
    except (TypeError, ValueError):
        return f"¥{value}"


class ProductionWorklogQueryTool(BaseTool):
    """加工单过程明细查询 Tool（仅 B 端）

    商家问「这单下料（裁剪）做到哪了 / 谁报的 / 合格多少 / 返工报废多少 / 过程明细」时调用；
    逐工序为 `operations`，逐笔报工为 `work_logs`，合计为 `totals`。
    """

    name = "production_worklog_query"

    description = (
        "【触发】商家问'这单下料/裁剪做到哪了''谁报的''合格多少''返工报废多少''过程明细'"
        "'每道工序谁在做''报工记录'时调用。"
        "【参数】需要订单号 order_no；用户没给时**先查订单拿号**"
        "（商户端用 order_query），不要猜号。"
        "【反例】只问'做到哪道工序/还要多久'用 production_progress_query（订单级进度，不发明细）；"
        "问'某师傅这个月计件多少钱'用 piecework_query（按人×月）；"
        "查订单金额/状态用 order_query。"
        "【标注】READONLY — 只读查询工序报工明细（仅商户员工/管理员可用，不对顾客开放）；"
        "禁止编造报工人/数量/计件金额，数字一律以本工具返回为准"
    )

    parameters = {
        "type": "object",
        "properties": {
            "order_no": {
                "type": "string",
                "description": (
                    "订单号（如 ORD-20260917-0001），必填。也接受加工单号/加工单二维码内容"
                    "（服务端按订单四形态解析）。用户未提供时先用 order_query 取号，"
                    "禁止编造或猜测订单号。"
                ),
            },
        },
        "required": ["order_no"],
    }

    # 仅 B 端：报工明细含报工人与计件金额（工资面）⇒ 不对 C 端顾客开放。
    # 权限码（admin-api 目录，issue #5291）：报工明细取生产域读码 `production:view`
    # （`AgentProductionController` 的 `GET .../worklog` 方法级注解同码）。
    # 沿革：原取 order:list（订单读码），#5246 曾改判为 `processing:manage`。
    required_permissions = ["production:view"]
    read_only = True
    destructive = False
    idempotent = True

    async def execute(
        self,
        context: ToolContext,
        order_no: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """查询加工单的工序过程明细与报工记录"""
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询工序报工明细",
                suggestion="工序报工明细仅对商户员工/管理员开放，请引导顾客联系商家核实",
            )

        order_no = str(order_no or "").strip()
        if not order_no:
            return ToolResult(
                success=False,
                error="缺少订单号",
                message="请先告诉我订单号，我才能帮您查这道工序做到哪了",
                suggestion=(
                    "用订单查询工具拿到订单号后再调用本工具（商户端 order_query，"
                    "可列出在途订单让用户选择）；禁止编造订单号"
                ),
            )

        try:
            client = get_admin_api_client()
            response = await client.get(
                # 冻结契约端点（#4201）；**路径用字面量**：跨模块 payload 契约门禁
                # （tests/test_tool_payload_backend_contract.py）要求 admin-api 调用点
                # 能静态归属到端点（模块常量会判「静默脱离射程」）。
                "/api/admin/agent/production/worklog",
                params={"order_no": order_no},
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(
                f"[production-worklog] Failed | tenant={context.tenant_id} "
                f"order_no={order_no} error={type(e).__name__}: {e}",
                exc_info=True,
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="查询工序报工明细失败，请稍后重试",
                suggestion=(
                    "请稍后重试；仍失败时如实告知用户暂时查不到，可转人工核实，"
                    "禁止编造报工人/数量/计件金额"
                ),
            )

        if not isinstance(response, dict) or not response.get("success"):
            # **必须走共享映射点**（issue #4149 G4）：就地降级成「请稍后重试」会丢 `error_code`
            # ⇒ 授权失败还会被自修复重试再来一遍（拿同一身份调一次永远不可能成功的接口）。
            error_info = response.get("error", {}) if isinstance(response, dict) else {}
            error_msg = (
                error_info.get("message", "查询失败")
                if isinstance(error_info, dict) else str(error_info)
            )
            logger.info(
                f"[production-worklog] Rejected | tenant={context.tenant_id} "
                f"order_no={order_no} error={error_msg}"
            )
            return admin_api_failure(
                response,
                error=error_msg,
                message="查询工序报工明细失败，请稍后重试",
                suggestion=(
                    "先核对订单号是否正确（可用 order_query 复核）；仍查不到时如实告知用户，"
                    "可转人工核实，禁止编造工序进度/报工人/数量"
                ),
            )

        data = response.get("data")
        if not isinstance(data, dict) or not data:
            return ToolResult(
                success=False,
                error="NOT_FOUND",
                message=f"未查到订单 {order_no} 的工序报工明细",
                suggestion=(
                    "该订单可能尚未进入生产或订单号有误：先用 order_query 复核订单号与状态，"
                    "不要编造工序、报工人或数量"
                ),
            )

        logger.info(
            f"[production-worklog] Fetched | tenant={context.tenant_id} order_no={order_no} "
            f"operations={len(data.get('operations') or [])}"
        )

        return ToolResult(
            success=True,
            data=data,
            message=f"订单 {order_no} 的工序报工明细已获取",
            summary=self._summary(order_no, data),
        )

    @staticmethod
    def _summary(order_no: str, data: Dict[str, Any]) -> str:
        """LLM 友好摘要：数字**逐字来自端点返回**（工具层不重算、不心算计价）。"""
        operations = data.get("operations") or []
        if not operations:
            # 「未开始」态（无加工单 / 零报工）不是错误：如实说无记录，禁止编造进度
            return f"订单 {order_no} 暂无工序/报工记录（尚未开始生产）"
        done = sum(1 for op in operations if isinstance(op, dict) and op.get("status") == "done")
        totals = data.get("totals") or {}
        return (
            f"订单 {order_no} 过程明细：共 {len(operations)} 道工序（已完 {done} 道）；"
            f"合格 {_fmt_num(totals.get('qualified_qty'))} / "
            f"返工 {_fmt_num(totals.get('rework_qty'))} / "
            f"报废 {_fmt_num(totals.get('scrap_qty'))}，"
            f"计件 {_fmt_amount(totals.get('piecework_amount'))}"
        )
