"""
AI 智能客服系统 - 经营日报（每日简报）查询 Tool（issue #5247 模块覆盖：看板与分析）

只读：`BriefingController` → `GET /api/admin/briefing/today`（方法级 `dashboard:view`）。
"""

import json
from typing import Any, Dict, List
from loguru import logger

from app.briefing.proactive import (
    INCOMPLETE,
    NOT_ENABLED,
    NOT_WIRED,
    WIRED,
    daily_findings,
    daily_findings_total,
    proactive_status,
)
from app.briefing.product_health import (
    FIELD_LABELS,
    NOT_ON_SALE,
    VERDICT_BAD,
    VERDICT_WATCH,
    product_health,
)
from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


#: 具名跨域视图（族 3 · 包 2，issue #5369）：白名单 —— 值不在表内一律拒绝，不猜
VALUED_VIEWS = ("product_health",)

#: 当日简报端点（依赖 LLM 生成链路；未生成 ⇒ 空态）
TODAY_ENDPOINT = "/api/admin/briefing/today"

#: 历史简报端点（issue #8253）：复盘的第一块原料 —— 过去 N 天 AI 提醒过什么。
#: 🔴 它是**独立端点**，不是 `VALUED_VIEWS` 里的一个 view（那个白名单走的是 `/snapshot`，
#: 拿回来的是「今天的快照」—— 名字像、东西完全不是）。
HISTORY_ENDPOINT = "/api/admin/briefing/history"

#: `view="history"` 的默认回看天数（上限 90 由 Java 侧 `HISTORY_MAX_DAYS` 钳制，此处不重复实现）
HISTORY_DEFAULT_DAYS = 30

#: 确定性快照端点（按需视图的数据面：同一份内核快照，零 LLM）—— 端点字面量与
#: `BriefingController` 的 `@GetMapping("/snapshot")` 由单测机械钉住（不许凭语义推测，§17.3）
SNAPSHOT_ENDPOINT = "/api/admin/briefing/snapshot"


def _merchant_display(entry: Dict[str, Any]) -> str:
    """商家话术（引擎 `display`，issue #7195 产出 / #7201 在消息侧消费）。

    🔴 缺省时**不退回 `reason`** —— 那里是诊断面（快照键 / 字段名 / 截断上限 / 文件路径），
    而消息是模型的**唯一摘要**：给它 reason 等于给它一份「照着念给商家」的稿子。
    """
    return str(entry.get("display") or "这项检查本次没有数据")


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
    # `@RequirePermission("dashboard:view")` —— 与侧边栏**「经营概览」节点**同码
    #（2026-10-17 issue #7087：原「每日简报」菜单项已撤，该码现只由「经营概览」节点承载）。
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

    async def execute(self, context: ToolContext, view: str = "", days: int = HISTORY_DEFAULT_DAYS,
                      **kwargs) -> ToolResult:
        view = (view or "").strip()
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查看经营日报",
                suggestion="请联系管理员为您开通「经营概览」查看权限后重试",
            )
        if view and view != "history" and view not in VALUED_VIEWS:
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
            if view == "history":
                response = await client.get(
                    "/api/admin/briefing/history",
                    params={"days": days},
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
            elif view:
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
        if view == "history":
            return render_history_result(data, days, context)
        if view:
            return render_view_result(view, data, context)
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
        # 🔴 #5348：**系统有、该租户没开**（如未做成本核算）—— 与「尚未接入」**并列、不可合并**：
        # 前者**可行动**（用户能去开启），后者不可行动（系统没做）。混成一句，用户就不知道
        # 「没这个功能」还是「我没开」。`reason` 非 None 且就是那句引导（不变式不给本态开例外）。
        not_enabled = [entry for entry in status.values() if entry["status"] == NOT_ENABLED]
        incomplete = [entry for entry in status.values() if entry["status"] == INCOMPLETE]
        total_today = daily_findings_total(snapshot, as_of=data.get("bizDate"))
        logger.info("[briefing_query] done proactive={} total_today={} not_wired={} not_enabled={} incomplete={}",
                    len(findings), total_today, len(unwired), len(not_enabled), len(incomplete))
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
            # 本次**检查了但不完整**（行数被上限截断 / 维度缺值 / 有行未判定）⇒ 也不得读成「没问题」。
            # 🔴 只点名 + 一句商家话术（issue #7201）：reason 里的行数 / 字段名 / 截断上限是**诊断面**，
            # 拼进来模型就会照着念（商家的原话：「这里很多信息我都看不懂」）。
            message += (
                "。⚠️ 以下能力本次数据不完整（可能有遗漏，空命中不代表没有问题）："
                f"{'、'.join(entry['rule_name'] for entry in incomplete)}"
            )
        if not_enabled:
            # 🔴 与「尚未接入」那句**分开说**（#5348）：本态是**可行动**的 —— 说清「是**你**没开」，
            # 并给**商家指引**（`display`）。不抛 `reason`：那里有快照键 / 「成本核算」这类内部口径（#7201）。
            detail = "；".join(
                f"{entry['rule_name']}（{_merchant_display(entry)}）" for entry in not_enabled)
            message += f"。⚠️ 以下能力本次没有检查 —— 你还没开启，开启后就能查：{detail}"
        # 数据源**固有边界**（issue #5388）：只对**本次真的检查过**的规则说（`wired`）——
        # 未接线 / 没开启 / 不完整各自已有专句，再叠一句边界只是噪音（#7201）。
        # 🔴 只说**人话**：披露「可能漏报 / 空结果不等于绝对没有」，
        # 不抛 fail-open / #5303 / 表名这些工程口径（它们仍留在 `data` 供按需下钻）。
        caveated = [entry["rule_name"] for entry in status.values()
                    if entry["caveats"] and entry["status"] == WIRED]
        if caveated:
            message += ("。⚠️ 以下检查只覆盖系统记录到的范围（可能漏报，空结果不等于绝对没有）："
                        + "、".join(caveated))
        return ToolResult(
            success=True,
            data=dict(data, proactive=findings, proactive_status=status),
            message=message,
        )


def render_history_result(rows: Any, days: int, context: ToolContext) -> ToolResult:
    """历史简报 → 给模型的摘要（issue #8253）。

    **空历史必须自己说「没有」**：`data=[]` 不等于「一切正常」。让模型对着空列表说
    「近期经营无异常」是这类工具最典型的假绿（对齐 P0 的「未知 ≠ 0」）——
    所以空态 message 里明写「这不是『一切正常』，是『没有记录』」。
    """
    items: List[Dict[str, Any]] = [row for row in (rows or []) if isinstance(row, dict)]
    if not items:
        return ToolResult(
            success=True,
            data={"days": days, "count": 0, "rows": []},
            message=(
                f"过去 {days} 天没有历史简报。**这不是「一切正常」，是「没有记录」** —— "
                "可能简报功能刚启用、或这段时间没有生成。别据此下「经营没问题」的结论。"
            ),
        )

    dates = [str(row.get("bizDate")) for row in items if row.get("bizDate")]
    earliest, latest = (min(dates), max(dates)) if dates else ("未知", "未知")
    lines = [f"过去 {days} 天共 {len(items)} 条历史简报（{earliest} ~ {latest}）。"]

    shown = 0
    for row in items:
        if shown >= 12:
            break
        content = row.get("content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (ValueError, TypeError):
                content = {}
        if not isinstance(content, dict):
            content = {}
        titles: List[str] = []
        for key in ("suggestions", "todos", "risks"):
            for entry in (content.get(key) or [])[:3]:
                if isinstance(entry, dict):
                    text = str(entry.get("title") or entry.get("text") or entry.get("summary") or "")[:40]
                elif isinstance(entry, str):
                    text = entry[:40]
                else:
                    text = ""
                if text:
                    titles.append(text)
        if titles:
            lines.append(f"- {row.get('bizDate')}：{'；'.join(titles)}")
            shown += 1
    if len(items) > 12:
        lines.append(f"（只列最近 12 条有内容的，共 {len(items)} 条）")
    lines.append(
        "以上是当时的**原文**；要判断「后来有没有被处理 / 有没有效」，"
        "请再查对应的当前视图做对比（例如 view=product_health 看退货率现在是中位还是高于上四分位）。"
    )
    return ToolResult(
        success=True,
        data={"days": days, "count": len(items), "earliest": earliest, "latest": latest, "rows": items},
        message="\n".join(lines),
    )


def render_view_result(view: str, snapshot: Dict[str, Any], context: ToolContext) -> ToolResult:
    """具名跨域视图的按需结果（族 3 · 包 2，issue #5369）。

    三条口径逐字落在这里（消息是模型的**唯一**输入源，消息里没有的兜底模型编不出来）：

    1. **未接线 / 不完整必须点名**（不要出现「一切正常」这类会覆盖未检查面的措辞）——
       与 `proactive_status` 的披露同一纪律（issue #5358）；
    2. 🔴 **「未知」与「0」不混**：成本未知的行如实说「毛利无法给出（不是 0）」；
    3. **有界不静默**：输出被上限截断时点出「只列前 N 行，共 M 行」。

    第四条口径（issue #6347 Part B，与「未接线」同一纪律的另一半）：

    4. 🔴 **「有 SKU 但被在售口径过滤掉」与「表里没有 SKU」不可合并** —— 前者要说清「有 N 个 SKU
       （M 个商品）因未上架未纳入」+ 出路（商品状态非法时先改回 off_sale/draft 再上架）；**禁止**
       说成「SKU 记录数 = 0 / SKU 层是空的 / 建议检查商品规格是否已录入」（那是**归因错误**，
       会把用户引向徒劳返工）。原文由引擎侧 `_filtered_reason` **单点**产出（本文件不另写一份）。
    """
    result = product_health(snapshot, tenant_id=context.tenant_id)
    fields = result["fields"]
    unwired = [FIELD_LABELS.get(name, name) for name, entry in fields.items()
               if entry["status"] == NOT_WIRED]
    incomplete = [FIELD_LABELS.get(name, name) for name, entry in fields.items()
                  if entry["status"] == INCOMPLETE]

    count = result["count"]
    filtered = result["not_on_sale"]
    message = f"商品健康度视图：{count} 个 SKU"
    if count == 0 and any(entry["status"] == NOT_ON_SALE for entry in fields.values()):
        # 🔴 空数组**不许**被静默读成「这个租户没有 SKU」（issue #6347 Part B）：过滤事实在，
        # 就把「有几个 / 为什么没进来 / 怎么让它们进来」原样说出来（模型只看得见这条消息）。
        message = f"商品健康度视图：本次 **0** 个 SKU —— {filtered['message']}"
    elif filtered["filtered_count"]:
        # 部分被过滤：视图本身照旧可用，但过滤事实也得说出来（否则条数偏低会被读成「就这些」）
        message += f"（另有 {filtered['filtered_count']} 个 SKU 因商品未上架未纳入 —— {filtered['message']}）"
    if result["truncated"]:
        message += f"（视图只列前 {result['count']} 行，共 {result['rows_total']} 行）"
    # 同行基线 + 判断摘要（issue #8234）：message 是模型的唯一摘要 —— 基线不写进来，
    # 模型只会照念「8 个 SKU」，verdict 等于不存在。
    rate_baseline = result["baselines"]["return_rate"]
    if rate_baseline:
        bad = sum(1 for row in result["rows"] if row["return_rate_verdict"] == VERDICT_BAD)
        watch = sum(1 for row in result["rows"] if row["return_rate_verdict"] == VERDICT_WATCH)
        message += (
            f"。退货率同行基线：中位 {rate_baseline['peer_median']:.1%}、"
            f"上四分位 {rate_baseline['peer_p75']:.1%}"
            f"（{rate_baseline['sample_size']} 个样本）—— "
            f"{bad} 个 SKU 高于上四分位、{watch} 个居中（这是相对基线，不是绝对标准）"
        )
    else:
        message += "。退货率样本不足（少于 5 个有效 SKU），本次不给出好坏判断"
    # 权衡的刻度（issue #8276）：钱不进 message，模型只会念「8 个 SKU」——
    # 「这批货压了多少钱」是老板看第一眼就想知道的数，必须自己说出来。
    stocked = [row for row in result["rows"]
               if row.get("money", {}).get("stock_value") is not None]
    if stocked:
        total_value = sum(row["money"]["stock_value"] for row in stocked)
        no_value = sum(1 for row in result["rows"]
                       if row.get("money", {}).get("stock_value") is None)
        message += f"。这些 SKU 压着的库存成本合计约 {total_value:,.2f} 元（stock × 成本价）"
        if no_value:
            # 🔴 「算不出来」不是「不占钱」—— 必须说清哪部分是盲区
            message += f"；另有 {no_value} 个 SKU 成本未知 ⇒ 这部分的资金占用**算不出来**（不是 0）"

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
        # 🔴 只点名（issue #7201）：`reason` 里是「快照未提供 xxx 行数组（装配层未接线）」
        # 「上限 N 行」这类工程口径 —— 消息是模型的唯一摘要，它会照着念给商家。
        message += (f"。⚠️ 以下字段本次数据不完整，其结论不可当作「没问题」："
                    f"{'、'.join(incomplete)}")
    # data 就是**视图本体**（`view` 键 = 视图标识字符串）—— 不再包一层，也不回灌原始快照：
    # 工具结果是有界的（≤ MAX_VIEW_ROWS 行），原始快照（每个数组 ≤500 行）不进这里。
    return ToolResult(success=True, data=dict(result), message=message)
