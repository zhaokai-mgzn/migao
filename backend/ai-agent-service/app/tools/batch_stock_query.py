"""批次 / 省料**只读**查询 Tool（issue #5188；数据面 #5145 / #5158 / #5159）。

## 与 `inventory_manage` 的分工（为什么是**新工具**而不是扩它的 `query`）

母单 #5188 的首选是「能扩 `inventory_manage.query` 就扩」。核过之后**不能扩**，三条都是硬理由：

1. **权限层直接冲突**：批次读面（`StockBatchController`）全部挂 `@RequirePermission("product:list")`，
   而 `inventory_manage` 是**双端工具**（`allowed_roles` 含 `customer`）——按 `docs/wiki/CONTRACT-LEDGER.md`
   §10.1 与 `tests/test_tool_permission_codes.py` 的登记清单，双端工具**不得**声明权限码
   （C 端 JWT 没有权限码，加码会让 C 端 `query` 全量失效 = 判据 6「不损失客户」红）。
   「加码」与「C 端可用」在同一类上不可兼得。
2. **成本口径不得进对客链路**：批次行含 `unitCost`、省料含 `savedAmount`（金额）——都是内部成本口径；
   `inventory_manage.query` 是 C 端顾客可调用的 action，扩进去等于把成本/金额参数与语义
   放进对客的 tool schema。
3. **schema 会变糊**：`query` 现在是「单一商品 SKU 库存」且 `product_id` **必填**；
   批次读面要求 `productId` **可空**（全租户批次 / 分布 / 看板），且需要 batchNo / dyeLot / granularity
   —— 同一个 action 会长出两种必填形态 + 两种返回体（SKU 库存 vs 批次/分布/看板）。

## 🔴 两条铁律（本仓）

- **AI 不编数**：四个 action 全部**原样透传服务端读面**（`/api/admin/batch-stock/*`）——
  agent 侧**不算**米数、金额、占比、也不重算余量。判据：
  `tests/test_batch_stock_query.py::TestSavingSameSource`（逐值相等 + 「重算会漂」的红证）。
- **空数据不冒充 0**：`null` 一律留 `null`（同 #5159 口径），文案回「无数据」，不回 `0`。

只读（`read_only=True`）：不含任何写调用（不调库存、不派工单、不改批次）。
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult, admin_api_failure, permission_denied
from app.tools.stock_semantics import BATCH_NEARLY_USED_UP_METERS, batch_is_nearly_used_up
from app.utils.http_client import get_admin_api_client

#: 操作类型：一个 action 对一个端点（端点与权限码都**逐字**取自 `StockBatchController`）
VALID_ACTIONS = ("batches", "distribution", "saving_board", "saving_trend")

#: 单次回给模型的批次行上限（只影响**展示条数**，不影响读面口径；
#: 截断时 `matched_count` 仍回真实匹配数，并显式告知被截断）。
MAX_BATCH_ROWS = 50

#: admin-api 失败时的兜底建议（
#: 授权类失败的**可执行**建议由共享映射点 `admin_api_failure` 按码顶掉，不在这里写）。
_FAIL_SUGGESTION = (
    "先确认筛选条件（商品/批次号/缸号/时间粒度）是否有效；"
    "仍查不到时如实告知用户暂时查不到，不要自行估算米数或金额"
)


def _fmt(value: Any) -> str:
    """服务端数值 → 文案：`None` 交给调用方说「无数据」（**不回落 0**）。

    数值可能是 JSON 数字或字符串（Java `BigDecimal` 两种下发形态都见过）⇒ 统一
    走 `str` 再规整尾部零，避免把 `24.68` 显示成 `24.680000000000003`。
    """
    text = str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _matches(value: Any, needle: str) -> bool:
    """批次号 / 缸号的匹配：**大小写不敏感的子串**（用户常只报一段号或缸号前缀）。"""
    return needle in str(value or "").lower()


class BatchStockQueryTool(BaseTool):
    """批次账 / 省料度量的只读查询（米宝 B 端；数据面 #5145 / #5159）"""

    name = "batch_stock_query"

    description = (
        "【触发】商家问'哪些批次快用尽了''这批还剩多少米''某个批次/缸号还有多少''剩料分布/有多少料剩着'"
        "'这个月省了多少料/省了多少钱''省料趋势/单位产出用多少料'时调用。"
        "【前置】action 四选一：batches（批次余量，可按 product_id / batch_no / dye_lot 查，"
        "nearly_used_up=true 只看快用尽的批次）/ distribution（剩余量四档分布）/ "
        "saving_board（省料度量汇总：逐单省料 + 剩余量分档，按来源组分开）/ "
        "saving_trend（入库/消耗/单位产出消耗的趋势）。查具体商品时先 product_search 取真实 UUID。"
        "【反例】查商品 SKU 库存/调整库存用 inventory_manage；查订单/生产进度用 order_query / "
        "production_progress_query；查加工单用 processing_order_query。"
        "【标注】READONLY — 只读服务端批次账与省料读面，不改动任何数据、不算米数与金额"
    )

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型：batches（批次余量）/ distribution（剩余量四档分布）/ "
                    "saving_board（省料度量汇总）/ saving_trend（采购与消耗趋势）"
                ),
                "enum": list(VALID_ACTIONS),
            },
            "product_id": {
                "type": "string",
                "description": (
                    "商品 32 位 UUID（可选）。先通过 product_search / product_detail 查到真实 UUID 再传入，"
                    "禁止传商品名称；不传 = 全店范围（分布/省料汇总允许，批次明细建议传）"
                ),
            },
            "batch_no": {
                "type": "string",
                "description": "批次号（如 PC-20260901-0001，可只给一段），仅 batches 用；大小写不敏感的子串匹配",
            },
            "dye_lot": {
                "type": "string",
                "description": "供应商缸号（如 A12，可只给一段），仅 batches 用；大小写不敏感的子串匹配",
            },
            "nearly_used_up": {
                "type": "boolean",
                "description": (
                    "仅 batches 用：true ⇒ 只回剩余量已落到服务端最小档（快用尽）的批次。"
                    "该档位由服务端定义，工具不自定阈值"
                ),
            },
            "granularity": {
                "type": "string",
                "description": "时间粒度：month（按月，YYYY-MM，缺省）/ week（按 ISO 周）；仅 saving_board / saving_trend 用",
                "enum": ["month", "week"],
            },
        },
        "required": ["action"],
    }

    # 权限码 = 批次读面各端点的 `@RequirePermission`（**逐字一致**，逐字判据见
    # `tests/test_batch_stock_query.py::TestPermissionAlignment`）。
    # 声明了权限码 ⇒ 不得再声明 `allowed_roles`（第二份会漂的假门禁）。
    required_permissions = ["product:list"]

    read_only = True
    destructive = False
    idempotent = True

    async def execute(
        self,
        context: ToolContext,
        action: str,
        product_id: Optional[str] = None,
        batch_no: Optional[str] = None,
        dye_lot: Optional[str] = None,
        nearly_used_up: bool = False,
        granularity: Optional[str] = None,
    ) -> ToolResult:
        """按 action 查批次账 / 省料读面（纯只读，无任何写操作）"""
        if not self.check_permission(context):
            return permission_denied(
                message="您没有权限查询批次账与省料数据",
                suggestion=(
                    "批次/省料读面需要商品查看权限（product:list）；"
                    "请联系管理员为当前岗位开通后重试"
                ),
            )

        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )

        try:
            if action == "batches":
                return await self._batches(context, product_id, batch_no, dye_lot, nearly_used_up)
            if action == "distribution":
                return await self._distribution(context, product_id)
            if action == "saving_board":
                return await self._saving_board(context, product_id, granularity)
            return await self._saving_trend(context, granularity)
        except Exception as e:
            logger.error(
                f"[batch-stock] Failed | tenant={context.tenant_id} action={action} "
                f"error={type(e).__name__}: {e}",
                exc_info=True,
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="批次/省料数据查询失败，请稍后重试",
                suggestion=(
                    "请稍后重试；仍失败时如实告知用户暂时查不到，不要自行估算米数或金额"
                ),
            )

    # ── 读面 ────────────────────────────────────────────────────────────────

    async def _batches(
        self,
        context: ToolContext,
        product_id: Optional[str],
        batch_no: Optional[str],
        dye_lot: Optional[str],
        nearly_used_up: bool,
    ) -> ToolResult:
        """批次余量（派生值原样透传，agent 侧不重算 `入库量 − 消耗`）

        「快用尽」= 服务端第一档（`batch_is_nearly_used_up`）——
        **刻意不传 `onlyAvailable`**：负余量（超扣）也在第一档，剔掉就是第二份口径。
        """
        params: Dict[str, Any] = {}
        if product_id:
            params["productId"] = product_id

        client = get_admin_api_client()
        response = await client.get(
            # 路径用**字面量**：跨模块 payload 契约门禁要求调用点能静态归属到端点
            "/api/admin/batch-stock/batches",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not response.get("success"):
            return admin_api_failure(response, message="批次余量查询失败", suggestion=_FAIL_SUGGESTION)

        rows = response.get("data") or []
        if not isinstance(rows, list):
            rows = []

        needle_batch = (batch_no or "").strip().lower()
        needle_lot = (dye_lot or "").strip().lower()
        matched = [
            r for r in rows
            if (not needle_batch or _matches(r.get("batchNo"), needle_batch))
            and (not needle_lot or _matches(r.get("dyeLot"), needle_lot))
            and (not nearly_used_up or batch_is_nearly_used_up(r.get("remainingMeters")))
        ]
        shown = matched[:MAX_BATCH_ROWS]
        truncated = len(matched) > len(shown)

        logger.info(
            f"[batch-stock] batches | tenant={context.tenant_id} product_id={product_id} "
            f"batch_no={batch_no} dye_lot={dye_lot} nearly_used_up={nearly_used_up} "
            f"matched={len(matched)} shown={len(shown)}"
        )

        data = {
            "action": "batches",
            "batches": shown,
            "batch_count": len(shown),
            "matched_count": len(matched),
            "truncated": truncated,
            "filters": {
                "product_id": product_id,
                "batch_no": batch_no,
                "dye_lot": dye_lot,
                "nearly_used_up": bool(nearly_used_up),
                "nearly_used_up_threshold_meters": (
                    str(BATCH_NEARLY_USED_UP_METERS) if nearly_used_up else None
                ),
            },
        }

        if not matched:
            return ToolResult(
                success=True,
                data=data,
                message=(
                    "无数据：当前条件下没有批次记录"
                    "（可确认商品、批次号或缸号是否正确，或去掉「快用尽」筛选再看全部批次）"
                ),
                summary="批次余量：无数据",
            )

        head = f"共 {len(matched)} 个批次"
        if nearly_used_up:
            head += f"已用到快用尽（剩余 ≤ {_fmt(BATCH_NEARLY_USED_UP_METERS)} 米）"
        if truncated:
            head += f"，仅展示前 {len(shown)} 个"
        return ToolResult(
            success=True,
            data=data,
            message=f"{head}，余量明细见卡片",
            summary=f"批次余量：{head}",
        )

    async def _distribution(self, context: ToolContext, product_id: Optional[str]) -> ToolResult:
        """剩余量分布（**四档恒由服务端给**：档位 key / label / 计数 / 占比全部透传）"""
        params: Dict[str, Any] = {}
        if product_id:
            params["productId"] = product_id

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/batch-stock/distribution",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not response.get("success"):
            return admin_api_failure(response, message="剩余量分布查询失败", suggestion=_FAIL_SUGGESTION)

        data = response.get("data") or {}
        if not isinstance(data, dict):
            return admin_api_failure(response, message="剩余量分布查询失败", suggestion=_FAIL_SUGGESTION)

        total = data.get("totalBatches") or 0
        buckets = data.get("buckets") or []
        payload = {**data, "action": "distribution"}

        if not total:
            return ToolResult(
                success=True,
                data=payload,
                message="无数据：没有批次记录（可确认商品筛选是否正确）",
                summary="剩余量分布：无数据",
            )

        parts = [
            f"{b.get('label')} {b.get('batchCount')} 个"
            for b in buckets
        ]
        logger.info(
            f"[batch-stock] distribution | tenant={context.tenant_id} "
            f"product_id={product_id} total={total}"
        )
        return ToolResult(
            success=True,
            data=payload,
            message=f"共 {total} 个批次的剩余量分布：" + "；".join(parts),
            summary=f"剩余量分布：共 {total} 个批次",
        )

    async def _saving_board(
        self, context: ToolContext, product_id: Optional[str], granularity: Optional[str]
    ) -> ToolResult:
        """省料度量汇总（L2 分档 + L1 逐单省料；**逐值透传**，来源组标签取服务端）"""
        params: Dict[str, Any] = {}
        if product_id:
            params["productId"] = product_id
        if granularity:
            params["granularity"] = granularity

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/batch-stock/saving-board",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not response.get("success"):
            return admin_api_failure(response, message="省料度量查询失败", suggestion=_FAIL_SUGGESTION)

        data = response.get("data") or {}
        if not isinstance(data, dict):
            return admin_api_failure(response, message="省料度量查询失败", suggestion=_FAIL_SUGGESTION)

        payload = {**data, "action": "saving_board"}
        total = data.get("total") or {}
        cohorts = data.get("cohorts") or []

        logger.info(
            f"[batch-stock] saving-board | tenant={context.tenant_id} "
            f"product_id={product_id} saved_meters={total.get('savedMeters')}"
        )

        if total.get("savedMeters") is None and not total.get("batchCount"):
            return ToolResult(
                success=True,
                data=payload,
                message=(
                    "无数据：该范围内没有批次与省料记录"
                    "（可按商品或时间粒度缩小范围后再试；金额与占比读不出时一律回「无数据」，不回落 0）"
                ),
                summary="省料度量：无数据",
            )

        segments: List[str] = []
        for cohort in cohorts:
            label = cohort.get("cohortLabel") or cohort.get("cohort") or ""
            saved, amount = cohort.get("savedMeters"), cohort.get("savedAmount")
            if saved is None and cohort.get("remainingMeters") is None:
                segments.append(f"{label}：无数据")
                continue
            seg = f"{label}："
            if saved is None:
                seg += "省料无数据"
            else:
                seg += f"省 {_fmt(saved)} 米"
                if amount is None:
                    seg += "（金额无数据：部分行没有均价）"
                else:
                    seg += f" / {_fmt(amount)} 元"
            if cohort.get("lineCount"):
                seg += f"，{cohort['lineCount']} 行"
            segments.append(seg)

        head = f"省料度量（{data.get('granularity')}，{data.get('timezone')}）："
        return ToolResult(
            success=True,
            data=payload,
            message=head + "；".join(segments),
            summary=(
                f"省料度量：省 {_fmt(total.get('savedMeters'))} 米 / "
                f"{_fmt(total.get('savedAmount'))} 元（合计）"
                if total.get("savedMeters") is not None
                else "省料度量：无数据"
            ),
        )

    async def _saving_trend(self, context: ToolContext, granularity: Optional[str]) -> ToolResult:
        """省料趋势（L3：采购/消耗/单位产出消耗；合计与单点全部透传）"""
        params: Dict[str, Any] = {}
        if granularity:
            params["granularity"] = granularity

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/batch-stock/saving-trend",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not response.get("success"):
            return admin_api_failure(response, message="省料趋势查询失败", suggestion=_FAIL_SUGGESTION)

        data = response.get("data") or {}
        if not isinstance(data, dict):
            return admin_api_failure(response, message="省料趋势查询失败", suggestion=_FAIL_SUGGESTION)

        payload = {**data, "action": "saving_trend"}
        points = data.get("points") or []
        purchased = data.get("purchasedTotalMeters")
        consumed = data.get("consumedTotalMeters")
        opening = data.get("openingTotalMeters")

        logger.info(
            f"[batch-stock] saving-trend | tenant={context.tenant_id} "
            f"granularity={granularity} points={len(points)}"
        )

        if not points and purchased is None and consumed is None and opening is None:
            return ToolResult(
                success=True,
                data=payload,
                message="无数据：该范围内没有入库/消耗记录（读不出时一律回「无数据」，不回落 0）",
                summary="省料趋势：无数据",
            )

        return ToolResult(
            success=True,
            data=payload,
            message=(
                f"共 {len(points)} 个时间点：采购入库 "
                + ("无数据" if purchased is None else f"{_fmt(purchased)} 米")
                + "；消耗 "
                + ("无数据" if consumed is None else f"{_fmt(consumed)} 米")
                + "；存量导入入库 "
                + ("无数据" if opening is None else f"{_fmt(opening)} 米（单列，不计入采购）")
            ),
            summary="省料趋势已获取",
        )
