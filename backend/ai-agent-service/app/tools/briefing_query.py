"""
AI 智能客服系统 - 经营日报（每日简报）查询 Tool（issue #5247 模块覆盖：看板与分析）

只读：`BriefingController` → `GET /api/admin/briefing/today`（方法级 `dashboard:view`）。
"""

from typing import Any, Dict
from loguru import logger

from app.briefing.proactive import daily_findings
from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class BriefingQueryTool(BaseTool):
    """经营日报查询 Tool（只读）"""

    name = "briefing_query"
    description = (
        "【触发】用户问'今天经营怎么样''每日简报''今日日报''今天出了多少单/收了多少'时调用。"
        "【参数】无参数（固定取当日简报）。"
        "【反例】跨时段趋势/订单状态分布/活跃会话用 dashboard_stats；应收对账与资金流水用 finance_api。"
        "【标注】READONLY — 只读查询"
    )

    # 权限码（admin-api 目录）：`BriefingController.GET /api/admin/briefing/today` 方法级
    # `@RequirePermission("dashboard:view")` —— 与侧边栏「每日简报」节点同码。
    required_permissions = ["dashboard:view"]
    read_only = True
    destructive = False
    idempotent = True

    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, context: ToolContext) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查看经营日报",
                suggestion="请联系管理员为您开通「每日简报」查看权限后重试",
            )

        try:
            client = get_admin_api_client()
            response = await client.get(
                "/api/admin/briefing/today",
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(f"Briefing query error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="经营日报查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = (
                error_info.get("message", "查询失败")
                if isinstance(error_info, dict)
                else str(error_info)
            )
            return admin_api_failure(
                response,
                error=error_msg,
                message=f"经营日报查询失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请改用 dashboard_stats 取看板指标",
            )

        data: Dict[str, Any] = response.get("data") or {}
        if not data:
            return ToolResult(
                success=True,
                data={},
                message="今日暂无经营日报数据（简报按当日数据生成，数据为空时即为暂无）",
            )
        # 主动发现（族 1 · 包 1，issue #5322）：对**同源聚合快照**做确定性规则扫描，
        # 只把「当天异常」并进日报（全量视图留给按需查询，族 3）；无快照 ⇒ 空集合，不猜。
        # 🔴 没有处置入口的条目在引擎装配期就被丢弃（`app/briefing/proactive.py::_assemble`）。
        findings = daily_findings(data.get("sourceSnapshot"), as_of=data.get("bizDate"))
        logger.info("[briefing_query] done proactive={}", len(findings))
        message = "今日经营日报如下"
        if findings:
            message = f"今日经营日报如下，另有 {len(findings)} 项当天异常待处理"
        return ToolResult(success=True, data=dict(data, proactive=findings), message=message)
