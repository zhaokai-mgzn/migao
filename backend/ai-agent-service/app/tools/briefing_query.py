"""
AI 智能客服系统 - 经营日报（每日简报）查询 Tool（issue #5247 模块覆盖：看板与分析）

只读：`BriefingController` → `GET /api/admin/briefing/today`（方法级 `dashboard:view`）。
"""

from typing import Any, Dict
from loguru import logger

from app.briefing.proactive import (
    INCOMPLETE,
    NOT_WIRED,
    daily_findings,
    daily_findings_total,
    proactive_status,
)
from app.briefing.product_health import FIELD_LABELS, product_health
from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


#: 具名跨域视图（族 3 · 包 2，issue #5369）：白名单 —— 值不在表内一律拒绝，不猜
VALUED_VIEWS = ("product_health",)

#: 当日简报端点（依赖 LLM 生成链路；未生成 ⇒ 空态）
TODAY_ENDPOINT = "/api/admin/briefing/today"

#: 确定性快照端点（按需视图的数据面：同一份内核快照，零 LLM）—— 端点字面量与
#: `BriefingController` 的 `@GetMapping("/snapshot")` 由单测机械钉住（不许凭语义推测，§17.3）
SNAPSHOT_ENDPOINT = "/api/admin/briefing/snapshot"


class BriefingQueryTool(BaseTool):
    """经营日报查询 Tool（只读；含具名跨域视图的**按需**下钻）"""

    name = "briefing_query"
    description = (
        "【触发】用户问'今天经营怎么样''每日简报''今日日报''今天出了多少单/收了多少'时调用；"
        "问「商品健康度 / 哪些商品卖得好但退货高 / 某个商品毛利怎么样」时带 view=product_health。"
        "【参数】view 可选（具名跨域视图）：缺省 = 当日经营日报；"
        "product_health = 商品健康度（SKU 级的销量 / 库存 / 退货率 / 成本毛利，按需实时取同一份内核快照）。"
        "【反例】跨时段趋势/订单状态分布/活跃会话用 dashboard_stats；应收对账与资金流水用 finance_api。"
        "【标注】READONLY — 只读查询"
    )

    # 权限码（admin-api 目录）：`BriefingController.GET /api/admin/briefing/today` 方法级
    # `@RequirePermission("dashboard:view")` —— 与侧边栏「每日简报」节点同码。
    required_permissions = ["dashboard:view"]
    read_only = True
    destructive = False
    idempotent = True

    parameters = {
        "type": "object",
        "properties": {
            "view": {
                "type": "string",
                "enum": list(VALUED_VIEWS),
                "description": (
                    "具名跨域视图（按需下钻，与日报**同一份内核快照** ⇒ 口径一致）："
                    "product_health = 商品健康度 —— 逐 SKU 的销量 / 库存 / 退货率 / 成本毛利；"
                    "成本未知的行如实标「未知」（不是毛利 0），未接线 / 不完整的字段会点名说明。"
                    "不传 = 当日经营日报。"
                ),
            },
        },
        "required": [],
    }

    async def execute(self, context: ToolContext, view: str = "", **kwargs) -> ToolResult:
        view = (view or "").strip()
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查看经营日报",
                suggestion="请联系管理员为您开通「每日简报」查看权限后重试",
            )
        if view and view not in VALUED_VIEWS:
            # 白名单之外一律拒绝（不猜、不降级）：具名视图的契约就是「一个高频问题一个视图」
            return ToolResult(
                success=False,
                error=f"无效的视图: {view}",
                message=f"不支持的视图，可选：{'、'.join(VALUED_VIEWS)}",
                suggestion="请从工具说明里的可选视图里选一个后重试，不要自行改用其它 view",
            )

        try:
            client = get_admin_api_client()
            # 🔴 端点字面量必须留在**调用点**：静态归属机具（`tests/tool_http_attribution.py`
            # 的 `_path_template`）只认调用点的字符串字面量 / f-string / 拼接 —— 写成模块常量
            # 会让本工具被判成「无 admin-api 调用点」⇒ 权限对账（`ci workflow helper unit tests`）
            # 两条判据一起红。常量与调用点字面量的一致性由单测机械钉住
            #（`tests/test_tools_briefing_query.py` 的 `test_call_site_literals_match_the_declared_endpoints`）。
            if view:
                response = await client.get(
                    "/api/admin/briefing/snapshot",
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
            else:
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
        if view:
            return _view_result(view, data, context)
        if not data:
            return ToolResult(
                success=True,
                data={},
                message="今日暂无经营日报数据（简报按当日数据生成，数据为空时即为暂无）",
            )
        # 主动发现（族 1 · 包 1，issue #5322）：对**同源聚合快照**做确定性规则扫描，
        # 只把「当天异常」并进日报（全量视图留给按需查询，族 3）；无快照 ⇒ 空集合，不猜。
        # 🔴 没有处置入口的条目在引擎装配期就被丢弃（`app/briefing/proactive.py::_assemble`）。
        snapshot = data.get("sourceSnapshot")
        findings = daily_findings(snapshot, as_of=data.get("bizDate"))
        # 逐规则接线状态（issue #5358）：**没接线 / 本次不完整** ≠ **已接线且本次完整但当天无命中**
        # —— 空命中不得被读成「今天一切正常」。状态进 `data`（调用方自己可分），
        # 未接线 / 不完整的规则在消息里**如实点名**。
        status = proactive_status(snapshot)
        unwired = [entry["rule_name"] for entry in status.values() if entry["status"] == NOT_WIRED]
        incomplete = [entry for entry in status.values() if entry["status"] == INCOMPLETE]
        total_today = daily_findings_total(snapshot, as_of=data.get("bizDate"))
        logger.info("[briefing_query] done proactive={} total_today={} not_wired={} incomplete={}",
                    len(findings), total_today, len(unwired), len(incomplete))
        message = "今日经营日报如下"
        if findings:
            message = f"今日经营日报如下，另有 {len(findings)} 项当天异常待处理"
            if total_today > len(findings):
                # 「日报要窄」不许变成静默少报：条数被 max_findings 截断时点出真实条数
                message += f"（日报只列前 {len(findings)} 项，当天共 {total_today} 项）"
        if unwired:
            # 禁用措辞（「今日无异常」「一切正常」…）一律不出现：本次根本**没有检查**这些方面。
            message += (
                f"。⚠️ 以下能力尚未接入本次扫描：{'、'.join(unwired)}"
                " —— 这些方面本次没有检查数据，请勿理解为均已检查"
            )
        if incomplete:
            # 同上：本次**检查了但不完整**（行数被上限截断 / 维度缺值）⇒ 也不得读成「没问题」。
            detail = "；".join(entry["reason"] for entry in incomplete)
            message += (
                f"。⚠️ 以下能力本次数据不完整，空命中不代表没有问题："
                f"{'、'.join(entry['rule_name'] for entry in incomplete)} —— {detail}"
            )
        return ToolResult(
            success=True,
            data=dict(data, proactive=findings, proactive_status=status),
            message=message,
        )


def _view_result(view: str, snapshot: Dict[str, Any], context: ToolContext) -> ToolResult:
    """具名跨域视图的按需结果（族 3 · 包 2，issue #5369）。

    三条口径逐字落在这里（消息是模型的**唯一**输入源，消息里没有的兜底模型编不出来）：

    1. **未接线 / 不完整必须点名**（不要出现「一切正常」这类会覆盖未检查面的措辞）——
       与 `proactive_status` 的披露同一纪律（issue #5358）；
    2. 🔴 **「未知」与「0」不混**：成本未知的行如实说「毛利无法给出（不是 0）」；
    3. **有界不静默**：输出被上限截断时点出「只列前 N 行，共 M 行」。
    """
    result = product_health(snapshot, tenant_id=context.tenant_id)
    fields = result["fields"]
    unwired = [FIELD_LABELS.get(name, name) for name, entry in fields.items()
               if entry["status"] == NOT_WIRED]
    incomplete = [(FIELD_LABELS.get(name, name), entry["reason"]) for name, entry in fields.items()
                  if entry["status"] == INCOMPLETE]

    message = f"商品健康度视图：{result['count']} 个 SKU"
    if result["truncated"]:
        message += f"（视图只列前 {result['count']} 行，共 {result['rows_total']} 行）"
    unknown_cost = result["unknown_cost_rows"]
    if unknown_cost:
        # 关键口径：成本未知**不是**毛利 0 —— 不许让模型把「读不到」说成「成本为零」
        message += (f"；其中 {unknown_cost} 个 SKU 的成本未知（未维护移动加权成本）"
                    "⇒ 这些行的毛利**无法给出**（「未知」不是「0」）")
    if result["unattributed_returns"]:
        message += (f"；另有 {result['unattributed_returns']} 笔退货无法归属到商品"
                    "（多商品订单），受影响的商品退货率会偏低")
    if unwired:
        message += (f"。⚠️ 以下字段本次未接线：{'、'.join(unwired)}"
                    " —— 这些方面本次没有数据，请勿理解为均为 0")
    if incomplete:
        detail = "；".join(f"{label}：{reason}" for label, reason in incomplete if reason)
        message += (f"。⚠️ 以下字段本次数据不完整，其结论不可当作「没问题」："
                    f"{'、'.join(label for label, _ in incomplete)} —— {detail}")
    # data 就是**视图本体**（`view` 键 = 视图标识字符串）—— 不再包一层，也不回灌原始快照：
    # 工具结果是有界的（≤ MAX_VIEW_ROWS 行），原始快照（每个数组 ≤500 行）不进这里。
    return ToolResult(success=True, data=dict(result), message=message)
