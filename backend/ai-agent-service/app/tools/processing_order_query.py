"""
AI 智能客服系统 - 加工单查询 Tool（issue #3340）

按加工单号/订单号/关键词查询加工单列表，或查单个加工单详情。

`delivery_risk` action（issue #6217 / V2）是**具名跨域视图** `delivery_risk` 的按需消费入口：
跨**加工单列表**与**逐单工序进度**两条既有只读端点做确定性聚合（哪些单快到交期还卡着工序 /
卡在哪个工序最多）—— 生产页是单任务视图，结构上答不出这两个问题。
"""

import asyncio
import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.briefing.delivery_risk import (
    FIELD_LABELS as RISK_LABELS,
    HAS_TRUTH,
    MAX_VIEW_ROWS as RISK_MAX_VIEW_ROWS,
    NO_TRUTH_REASONS as RISK_NO_TRUTH_REASONS,
    delivery_risk,
)
from app.briefing.proactive import INCOMPLETE, NOT_WIRED, WIRED
from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型（issue #6217：`query` = 旧的加工单查询；`delivery_risk` = 新增的具名跨域视图）
VALID_ACTIONS = {"query", "delivery_risk"}

# 加工单状态中文映射（与后端 ProcessingOrderService 状态机对齐）
PO_STATUS_TEXT = {
    "generated": "已生成",
    "issued": "已发加工",
    "in_processing": "加工中",
    "completed": "加工完成",
    "cancelled": "已取消",
}

#: 具名跨域视图 `delivery_risk`（族 3 · 包 4 / V2，issue #6217）的**取数面**：两条**既有**只读端点。
#: 端点字面量按本仓风格留在**调用点**；常量与调用点字面量的一致性由单测机械钉住。
#: 权限码逐条对齐（`ProcessingOrderController` 与 `AgentProductionController` 的方法级
#: `@RequirePermission`）：两者同为生产域读码 `production:view`。
DELIVERY_RISK_ORDERS_ENDPOINT = "/api/admin/processing-orders"
DELIVERY_RISK_PROGRESS_ENDPOINT = "/api/admin/agent/production/progress"

#: 逐单工序进度的**取数上限**（有界是硬前提：一条 progress 调用对应一张加工单，
#: 不设上限会把一个对话回合变成 N 次串行 HTTP）。超出的加工单落「进度未知」并被**点名**，
#: 不静默少报。
DELIVERY_RISK_PROGRESS_LIMIT = 50
#: 逐单进度取数的并发上限（同一 SDK 客户端 + 熔断器：并发太高会把熔断器打开）
DELIVERY_RISK_PROGRESS_CONCURRENCY = 8


class ProcessingOrderQueryTool(BaseTool):
    """加工单查询 Tool"""

    name = "processing_order_query"
    description = (
        "【触发】用户问'加工单到哪了''JG-xxx 什么状态''这个订单的加工单'时调用；"
        "问'哪些单快到交期还卡着工序''卡在哪个工序最多''生产交付风险'时用 action=delivery_risk 调本工具。"
        "【参数】action 可选：query（默认，查加工单列表）/ delivery_risk（生产交付风险视图，"
        "跨单聚合：交期 + 工序进度 + 卡点，按风险排序）。"
        "query 可选 keyword（加工单号 JG-xxx / 订单号 ORD-xxx）或 status 筛选。"
        "【反例】生成加工单 / 改加工单状态**不在能力内**——如实说明并引导商家到后台「生产看板」页操作。"
        "【口径】delivery_risk 依赖两条既有只读端点（加工单列表 + 逐单工序进度），均需 production:view；"
        "其中「排产交期 / 承诺发货日」在既有端点里**没有来源** ⇒ 一律为「未知」，**不是当天、不是 0**；"
        "没填交期的加工单落「风险未知」（**不是**「不紧急」）。"
        "【标注】READONLY — 只读查询"
    )

    # 权限码（admin-api 目录，issue #5291）：加工单**查看**取生产域读码 `production:view`
    # （`ProcessingOrderController` 的查询端点 `GET /api/admin/processing-orders` 同码；
    # `AgentProductionController` 的 `GET /agent/production/progress` 亦为 `production:view`）。
    # 沿革：#5246 曾把工具码对齐节点码 `processing:manage`（当时生产域无读码）⇒ 本单读出读码后回到只读语义。
    # 旧白名单里的 knowledge_editor 在目录里只有 dashboard:view + product:list ⇒ 不再放行（收窄）。
    required_permissions = ["production:view"]
    read_only = True
    # 已恢复接入（issue #4196：反转 #3917 的下线决策）：registry 注册 + order skill 工具绑定
    # + prompts/order.md 操作指引三处齐备；概念区分口径仍在（防混淆守则）。
    destructive = False
    idempotent = True
    # 只读 action 免确认拦截（issue #6217：delivery_risk 是纯读聚合，无写面）
    read_only_actions = {"query", "delivery_risk"}

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：query（默认，按关键词/状态查加工单列表）/ delivery_risk（生产交付风险视图：跨单聚合交期 + 工序进度 + 卡点，按风险排序）—— 均为只读",
                "enum": ["query", "delivery_risk"],
                "default": "query",
            },
            "keyword": {
                "type": "string",
                "description": "加工单号（JG-xxx）/ 订单号（ORD-xxx）或订单 UUID，可选（action=query）",
            },
            "status": {
                "type": "string",
                "enum": ["generated", "issued", "in_processing", "completed", "cancelled"],
                "description": "按加工单状态筛选（可选，action=query）",
            },
        },
        "required": [],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str = "query",
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(success=False,
                error="权限不足",
                message="您没有权限查询加工单",
                suggestion="请改用订单查询（order_query）向用户提供订单信息；如需查看加工单请先确认当前账号权限",
            )

        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(sorted(VALID_ACTIONS))}",
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )

        if action == "delivery_risk":
            return await self._delivery_risk(context)

        try:
            client = get_admin_api_client()
            params: Dict[str, str] = {}
            if keyword:
                params["keyword"] = keyword.strip()
            if status:
                params["status"] = status
            response = await client.get(
                "/api/admin/processing-orders",
                params=params,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(f"Processing order query error: {e}", exc_info=True)
            return ToolResult(
                success=False, error="tool_execution_failed",
                message="加工单查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = error_info.get("message", "查询失败") if isinstance(error_info, dict) else str(error_info)
            return admin_api_failure(response, error=error_msg,
                message=f"加工单查询失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请改为不带状态筛选查询，或请用户联系管理员核对加工单数据",
            )

        data = response.get("data") or []
        if not data:
            return ToolResult(
                success=True, data={"list": []},
                message="未找到加工单" + (f"（关键词：{keyword}）" if keyword else ""),
            )

        # 组装人类可读列表
        rows = []
        for po in data:
            rows.append({
                "id": po.get("id"),
                "processingOrderNo": po.get("processingOrderNo"),
                "orderNo": po.get("orderNo"),
                "customerName": po.get("customerName"),
                "processor": po.get("processor"),
                "expectedDeliveryDate": po.get("expectedDeliveryDate"),
                "status": po.get("status"),
                "statusText": PO_STATUS_TEXT.get(po.get("status"), po.get("status")),
                "printCount": po.get("printCount"),
            })
        logger.info(f"[processing_order_query] done: count={len(rows)}")
        return ToolResult(
            success=True,
            data={"list": rows},
            message=f"共找到 {len(rows)} 个加工单",
        )

    # ── 具名跨域视图 `delivery_risk`（族 3 · 包 4 / V2，issue #6217）────────────────

    @staticmethod
    def _rows_of(data: Any) -> Optional[List[Dict[str, Any]]]:
        """容错取列表（裸列表 / `PageResponse` 信封）；形态不认识 ⇒ `None`（**不是 `[]`**）。"""
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if isinstance(data, dict):
            for key in ("items", "records", "list", "rows"):
                value = data.get(key)
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, dict)]
            return []
        return None

    async def _fetch(self, context: ToolContext, endpoint: str, order_no: Optional[str] = None,
                     ) -> Tuple[Optional[List[Dict[str, Any]]], str]:
        """取一条**既有只读端点**的行数组 ⇒ `(rows | None, 失败原因)`（失败**不**返回 `[]`）。

        🔴 两条端点的路径在 `client.get(...)` 的实参位置**逐条写成字面量** ——
        静态归属门禁（`tests/test_tool_payload_backend_contract.py::
        test_payload_calls_are_attributable_to_an_endpoint`）只认调用点的字面量；
        用变量拼路径会让这个调用点静默脱离门禁射程。
        """
        client = get_admin_api_client()
        try:
            if endpoint == DELIVERY_RISK_ORDERS_ENDPOINT:
                response = await client.get("/api/admin/processing-orders", params={},
                                            tenant_id=context.tenant_id,
                                            user_id=context.user_id)
            elif endpoint == DELIVERY_RISK_PROGRESS_ENDPOINT:
                response = await client.get("/api/admin/agent/production/progress",
                                            params={"order_no": order_no},
                                            tenant_id=context.tenant_id,
                                            user_id=context.user_id)
            else:  # fail-closed：不认识的端点**不猜路径**
                return None, f"未登记的端点（不在本视图的两条取数面内）：{endpoint}"
        except Exception as exc:  # 网络 / 超时 / 熔断：归因到这一面
            logger.error("[processing-order-query] delivery_risk 端点异常 endpoint={}: {}: {}",
                         endpoint, type(exc).__name__, exc)
            return None, f"{type(exc).__name__}: {exc}"
        if not response.get("success"):
            error = response.get("error")
            message = error.get("message", "查询失败") if isinstance(error, dict) else str(error or "查询失败")
            return None, message
        rows = self._rows_of(response.get("data"))
        if rows is None:
            return None, "响应形态不可识别（data 既不是列表也不是对象）"
        return rows, ""

    def _assemble(self, orders: List[Dict[str, Any]],
                  progress: List[Optional[Dict[str, Any]]]) -> Dict[str, Any]:
        """把两条端点的行**归一化**成视图消费的快照（列名归一化是**装配层**的口径）。

        `progress` 与 `orders` **按下标对齐**（`None` = 那一张的单据进度没取到 ⇒ 该单卡点未知）。
        归一化只改键名、不改语义；金额 / 日期为空一律保持为空（**不折 0、不折当天**）。
        """
        order_rows = orders[:RISK_MAX_VIEW_ROWS]
        progress_rows = [row for row in progress[:RISK_MAX_VIEW_ROWS] if isinstance(row, dict)]

        def meta(count: int, limit: int, truncated: bool) -> Dict[str, Any]:
            return {"limit": limit, "count": count, "truncated": truncated}

        return {
            "row_fields": {
                "processing_orders": ["processing_order_no", "order_no", "customer_name",
                                      "processor", "expected_delivery_date", "status"],
                "production_progress": ["order_no", "expected_delivery_date", "current_operation",
                                        "pending_operations", "total_operations",
                                        "done_operations"],
            },
            "row_meta": {
                "processing_orders": meta(len(order_rows), RISK_MAX_VIEW_ROWS,
                                          len(orders) > RISK_MAX_VIEW_ROWS),
                "production_progress": meta(len(progress_rows), DELIVERY_RISK_PROGRESS_LIMIT,
                                            len(orders) > DELIVERY_RISK_PROGRESS_LIMIT),
            },
            "processing_orders": [{
                "processing_order_no": row.get("processingOrderNo"),
                "order_no": row.get("orderNo"),
                "customer_name": row.get("customerName"),
                "processor": row.get("processor"),
                "expected_delivery_date": row.get("expectedDeliveryDate"),
                "status": row.get("status"),
            } for row in order_rows],
            "production_progress": [{
                "order_no": row.get("order_no"),
                "expected_delivery_date": row.get("expected_delivery_date"),
                "current_operation": row.get("current_operation"),
                "pending_operations": row.get("pending_operations"),
                "total_operations": row.get("total_operations"),
                "done_operations": row.get("done_operations"),
                "progress_percent": row.get("progress_percent"),
            } for row in progress_rows],
        }

    async def _delivery_risk(self, context: ToolContext) -> ToolResult:
        """生产交付风险视图（具名跨域视图 `delivery_risk` 的按需消费，issue #6217 / V2）。

        取数面 = **两条既有只读端点**：加工单列表（有界 100）→ 逐单工序进度（**上限** 50 张、
        并发 8）。列表面失败 ⇒ fail-closed；**单张**进度取不到 ⇒ 只把该张的卡点/进度落「未知」
        （由视图逐字段三态 + 消息点名，**不静默少报**）。
        """
        orders, reason = await self._fetch(context, DELIVERY_RISK_ORDERS_ENDPOINT)
        if orders is None:
            logger.warning("[processing-order-query] delivery_risk 加工单列表取数失败：{}", reason)
            return ToolResult(
                success=False,
                error="cross_domain_fetch_failed",
                message=(f"生产交付风险视图取数失败 —— 加工单列表读不到（production:view）：{reason}"
                         "（fail-closed：没有加工单面就无法出结论）"),
                suggestion="请确认当前账号具备 production:view；若只是临时故障请稍后重试，"
                           "也可先用 production_progress_query(order_no=…) 查单张订单的进度",
            )

        # 逐单进度：只对**要展示的那批**取（有界 + 并发），失败的单**不进数组**（= 该单进度未知）
        targets = [row for row in orders[:DELIVERY_RISK_PROGRESS_LIMIT]
                   if str(row.get("orderNo") or "").strip()]
        semaphore = asyncio.Semaphore(DELIVERY_RISK_PROGRESS_CONCURRENCY)

        async def one(order_no: str) -> Optional[Dict[str, Any]]:
            async with semaphore:
                rows, _why = await self._fetch(context, DELIVERY_RISK_PROGRESS_ENDPOINT,
                                               order_no)
            return rows[0] if rows else None

        fetched = await asyncio.gather(*(one(str(row.get("orderNo")).strip()) for row in targets))
        by_order = {str(row.get("orderNo")).strip(): item
                    for row, item in zip(targets, fetched) if isinstance(item, dict)}
        progress = [by_order.get(str(row.get("orderNo") or "").strip()) for row in orders]

        snapshot = self._assemble(orders, progress)
        result = delivery_risk(snapshot, tenant_id=context.tenant_id, as_of=_dt.date.today())
        fields = result["fields"]
        no_truth = result["no_truth_fields"]
        unwired = [name for name, entry in fields.items()
                   if entry["status"] == NOT_WIRED and entry["truth"] == HAS_TRUTH]
        incomplete = [(name, entry["reason"]) for name, entry in fields.items()
                      if entry["status"] == INCOMPLETE]
        bands = result["band_counts"]
        logger.info("[processing-order-query] delivery_risk rows={} total={} overdue={} stuck={}",
                    result["count"], result["rows_total"], bands.get("overdue"),
                    len(result["stuck_top"]))

        message = (f"生产交付风险视图（截至 {result['as_of']}）：{result['count']} 张加工单 —— "
                   f"已逾期 {bands.get('overdue', 0)} / 临近交期 {bands.get('critical', 0)} / "
                   f"接近交期 {bands.get('soon', 0)} / 宽裕 {bands.get('safe', 0)} / "
                   f"交期未知 {bands.get('unknown', 0)}"
                   "（交期未知 = 该单没填交期，是「不知道」，**不是**「不紧急」）")
        if result["stuck_top"]:
            message += "。卡点工序 Top：" + "、".join(
                f"{item['operation']}（{item['order_count']} 单）" for item in result["stuck_top"][:5])
        if result["truncated"]:
            message += (f"。⚠️ 视图只列前 {result['count']} 张，共 {result['rows_total']} 张"
                        "（按交付风险排序取前段）")
        if result["missing_progress"]:
            message += (f"。⚠️ {result['missing_progress']} 张加工单**没取到逐单工序进度**"
                        "（逐单取数有上限 / 该单取数失败）⇒ 这些单的卡点与进度是「未知」，"
                        "**不是**「没有卡着的工序」")
        if no_truth:
            message += (f"。⚠️ 其中 {len(no_truth)} 个字段**没有真值来源**（既有只读端点里没有这个列）"
                        f"⇒ 这些字段一律为「未知」，**不是 0、不是当天、不是默认值**："
                        + "、".join(f"{RISK_LABELS.get(name, name)}（{name}）" for name in no_truth)
                        + "。逐条原因："
                        + "；".join(f"{name}：{RISK_NO_TRUTH_REASONS[name]}"
                                    for name in no_truth if name in RISK_NO_TRUTH_REASONS))
        if unwired:
            message += (f"。⚠️ 以下字段本次未接线：{'、'.join(unwired)}"
                        " —— 这些方面本次没有数据，请勿理解为均为 0")
        if incomplete:
            detail = "；".join(f"{RISK_LABELS.get(name, name)}：{reason}"
                               for name, reason in incomplete if reason)
            message += (f"。⚠️ 以下字段本次数据不完整，其结论不可当作「没问题」："
                        f"{'、'.join(RISK_LABELS.get(name, name) for name, _ in incomplete)} —— {detail}")
        return ToolResult(success=True, data=dict(result), message=message)
