"""
AI 智能客服系统 - 库存管理 Tool

查询和调整商品库存，支持库存预警查询。
"""

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Union

from loguru import logger

from app.tools.base import (
    admin_api_failure,
    BaseTool,
    ToolContext,
    ToolResult,
    permission_denied,
)
from app.briefing.delivery_risk import HAS_TRUTH
from app.briefing.proactive import NOT_WIRED
from app.tools.stock_semantics import (
    LOW_STOCK_THRESHOLD,
    NO_SKU_SOURCE,
    low_stock_alert_threshold_schema,
    low_stock_phrase,
    no_sku_stock_note,
    product_stock_summary,
)
from app.utils.http_client import get_admin_api_client


# 操作类型（issue #6280：`material_shortage` = 第三个只读 action，与 `low_stock_alert` 同族）
VALID_ACTIONS = {"query", "low_stock_alert", "material_shortage"}

#: 面向 LLM 的「可选 action」枚举顺序（**单点声明**）：`VALID_ACTIONS` 是集合，迭代顺序不保证
#: ⇒ 错误文案若直接 join 集合，加一个 action 就会**改写旧文案**（违反「旧行为逐字不变」）。
VALID_ACTION_ORDER = ("query", "low_stock_alert", "material_shortage")

#: 库存（米）的记数粒度 = 0.1（后端列 `NUMERIC(12,1)`，issue #5063；
#: 与算料口径「用料米数一律向上进位到 0.1」同源）。
STOCK_QUANTUM = Decimal("0.1")

#: 具名跨域视图 `material_shortage`（issue #6280 冻结契约 v1）的**取数面**：
#: 页面与 agent 共用同一份数字（预测内核单点在 admin-api 的 Java 纯函数，**Python 不重算预测**）。
#: 端点字面量按本仓风格留在**调用点**；常量与调用点字面量的一致性由单测机械钉住。
#: 权限码 = `product:list`（与库存台账 / 批次看板 / 低库存同码），只读。
MATERIAL_SHORTAGE_ENDPOINT = "/api/admin/materials/shortage"
#: 需求侧状态口径（与族 1 `UNSHIPPED_STATUSES` 同口径：不做 `pending`，避免未付款意向单放大缺口）
MATERIAL_SHORTAGE_STATUSES = "confirmed,producing"
#: 视图输出上限（有界是热路径的硬前提）
MATERIAL_SHORTAGE_LIMIT = 50

#: 风险分层（= 视图行序第一键，按紧急度降序）。`short` = **缺口确定、紧迫性未知**
#: —— 🔴 单列，**不得**并进 `critical`（并进去会把没填交期的商品排进最紧急一批）。
_RISK_BANDS = ("blocked", "critical", "soon", "short", "safe", "unknown")
_BAND_PHRASES = {
    "blocked": "缺口 + 交期已过",
    "critical": "缺口 + 交期≤3天",
    "soon": "缺口 + 交期≤7天",
    "short": "缺口确定、紧迫性未知",
    "safe": "无缺口（有余量）",
    "unknown": "单位不可比 ⇒ 未知",
}


def _one_decimal_or_none(value: Any) -> Optional[Decimal]:
    """库存类数值的小数位判定：最多 1 位小数 ⇒ `Decimal`，否则 `None`（fail-closed）。

    **为什么不用 `round(x, 1) == x`**：`2.7` 的二进制表示并不精确，浮点比较会把
    **合法**的 `2.7` 判成「超过 1 位小数」而误拒（误拒 = 客户办不成事）。
    判据取**十进制字面量**的小数位数（`Decimal("2.755").as_tuple().exponent == -3`），
    正是 LLM / 用户在界面上看到的那一位。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    exponent = parsed.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -1:
        return None
    return parsed


def _stock_number(value: Decimal) -> Union[int, float]:
    """`Decimal` → 整数保持 `int`（**整数场景逐值不变**），小数才落 `float`。

    保留 int 不是洁癖：Java DTO 若声明为整型，下发 `10.0` 会被 Jackson 判非法，
    白丢一次写操作（本单「不能损失客户」）。
    """
    return int(value) if value == value.to_integral_value() else float(value)


class InventoryManageTool(BaseTool):
    """库存管理 Tool
    
    查询和调整商品库存，支持库存预警查询。
    
    使用场景：
    - 查询某个商品的当前库存
    - 调整库存数量（入库、出库）
    - 查询低库存商品预警
    """
    
    name = "inventory_manage"
    description = (
        "【触发】用户问'库存''还有多少''缺货''低库存''出库''入库''调整库存'时调用。"
        "【触发】用户问'哪些商品缺料''缺口多大''按交期看哪些要先补''缺料风险'时，"
        "用 action=material_shortage 调本工具（跨域视图：未完成订单需求 vs SKU 权威库存）。"
        "【参数】action 必填：**只有 query（需 product_id）/ low_stock_alert（可选 threshold）/ "
        "material_shortage（缺料与缺口视图，无需参数）三个只读 action**"
        "（B 端已只读化，issue #5247）。"
        "【反例】查商品详情（含库存字段）用 product_detail；查批次余量/剩料分布用 batch_stock_query。"
        "【反例】调**单条**库存**不在本工具能力内**——引导用户到后台「商品管理 → 编辑商品 → 库存」页调整。"
        "【反例】只要**某个商品**的实时库存数 ⇒ 用 inventory_manage(action=query, product_id=…)，"
        "**不要**用 material_shortage（它只出「有缺口的商品」的跨域聚合，不答单商品库存）。"
        "【反例】只要**低于库存阈值**的 SKU 清单 ⇒ 用 inventory_manage(action=low_stock_alert)，"
        "**不要**用 material_shortage（后者按未完成订单的需求算缺口，不是按静态阈值）。"
        "【批量】多条商品一起调库存用 product_batch_update(action=preview, batch_type=inventory_stock)"
        "（两段确认 + 可撤销，issue #5950）—— 本工具自身不含任何写 action。"
        "【口径】material_shortage 的 `rate_per_week` / `exhaust_date` 在预测层未启用（历史台账深度不足）时"
        "一律为「未知」——**不是 0、不是当天**；单位不可比的行需求量为「未知」而非 0。"
        "【标注】READONLY — 纯查询，不含任何写 action"
    )
    
    # 权限码（admin-api 目录）：ProductController / AgentProductController 的库存端点 ——
    # 读（query/low_stock_alert）= `product:list`、写（adjust）= `product:create`，与 controller 同码。
    # 声明了权限码 ⇒ **删除** allowed_roles：它含 C 端角色 `customer`（横向越权，issue #5246 判据 6），
    # 且权限码在场时角色白名单本就不生效＝第二份会漂的假门禁（#4106 F4）。
    required_permissions = ["product:list"]  # B 端只读化（#5247）：写码 product:create 已随 adjust 一并移除

    read_only = True
    # 只读 action 免确认（issue #6280：material_shortage 是纯读跨域聚合，无写面）
    read_only_actions = {"query", "low_stock_alert", "material_shortage"}
    destructive = False  # 库存调整可逆
    idempotent = False   # 调整操作非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": ("操作类型：query（查询库存）/ low_stock_alert（低库存预警）/ "
                                "material_shortage（缺料与缺口视图，跨域聚合）—— 均为只读"),
                "enum": list(VALID_ACTION_ORDER),
            },
            "product_id": {
                "type": "string",
                "description": "商品 32 位 UUID。必须先通过 product_detail 或 product_search 查出真实 UUID 再传入，禁止传商品名称或序号",
            },
            "threshold": low_stock_alert_threshold_schema(),
        },
        "required": ["action"],
    }
    
    async def execute(
        self,
        context: ToolContext,
        action: str,
        product_id: Optional[str] = None,
        adjustment: Optional[float] = None,
        reason: Optional[str] = None,
        threshold: int = LOW_STOCK_THRESHOLD,
    ) -> ToolResult:
        """执行库存管理操作
        
        Args:
            context: Tool 执行上下文
            action: 操作类型
            product_id: 商品 ID
            adjustment: 调整数量
            reason: 调整原因
            threshold: 库存预警阈值
            
        Returns:
            ToolResult: 操作结果
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行库存管理操作",
                suggestion="请联系管理员获取执行库存管理操作权限",
            )
        
        # customer 角色仅允许 query 操作（动作级拒绝 ⇒ 走共享构造点带码，issue #4147 G2）
        if context.role == "customer" and action != "query":
            return permission_denied(
                message="抱歉，库存调整和低库存预警功能仅限管理员和客服使用。如需查询商品库存，请告诉我商品名称或 ID。",
                suggestion="顾客端只能查询库存，请改用 query 操作；如需调整库存请转人工或由管理员操作",
            )
        
        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTION_ORDER)}",
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )
        
        try:
            if action == "query":
                return await self._query_inventory(context, product_id)
            elif action == "low_stock_alert":
                return await self._low_stock_alert(context, threshold)
            elif action == "material_shortage":
                return await self._material_shortage(context)
            else:
                # 不可达（上方已按 `VALID_ACTIONS` 拦截）；保留为**响亮**的失败而非静默成功
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )
                
        except Exception as e:
            logger.error(f"Inventory manage error: action={action}, product_id={product_id}, error={e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="库存操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )
    
    async def _query_inventory(
        self,
        context: ToolContext,
        product_id: Optional[str],
    ) -> ToolResult:
        """查询商品库存
        
        Args:
            context: Tool 执行上下文
            product_id: 商品 ID
            
        Returns:
            ToolResult: 库存查询结果
        """
        if not product_id:
            return ToolResult(
                success=False,
                error="缺少商品 ID",
                message="查询库存时必须提供商品 ID（product_id）",
                suggestion="缺少 product_id，请先用 product_search 查到该商品后重试",
            )
        
        client = get_admin_api_client()
        response = await client.get(
            f"/api/admin/products/{product_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        
        if not response.get("success"):
            error_code = response.get("error", {}).get("code", "")
            error_msg = response.get("error", {}).get("message", "查询失败")
            
            if error_code == "NOT_FOUND" or "不存在" in error_msg:
                return admin_api_failure(response,
                    error="商品不存在",
                    message="未找到该商品，请检查商品 ID",
                    suggestion="请检查ID是否正确，或尝试其他搜索条件",
                )
            
            return admin_api_failure(response,
                error=error_msg,
                message="查询库存失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )
        
        data = response.get("data", {})
        
        # 验证响应数据的 tenant_id
        resp_tenant_id = data.get("tenantId") or data.get("tenant_id")
        if resp_tenant_id is not None and str(resp_tenant_id) != str(context.tenant_id):
            logger.error(
                f"Tenant data integrity violation in inventory_manage: "
                f"response tenant_id={resp_tenant_id}, expected={context.tenant_id}"
            )
            return ToolResult(
                success=False,
                error="商品不存在",
                message="未找到该商品",
                suggestion="请检查ID是否正确，或尝试其他搜索条件",
            )
        
        stock = product_stock_summary(data.get("skus"))
        product_name = data.get("name", "")
        
        logger.info(
            f"Inventory query: product_id={product_id}, stock={stock['stock']}, "
            f"source={stock['stock_source']}, tenant={context.tenant_id}"
        )

        if stock["stock_source"] == NO_SKU_SOURCE:
            # 无 SKU 记录 ⇒ 不谎报 0（issue #4038：0 会被读成「没货」）
            return ToolResult(
                success=True,
                data={
                    "product_id": product_id,
                    "product_name": product_name,
                    "stock": None,
                    "stock_source": NO_SKU_SOURCE,
                    "status": data.get("status"),
                },
                message=no_sku_stock_note(product_name),
                suggestion="请在商品详情维护 SKU（颜色/售卖方式/门幅）后重试",
            )
        
        # issue #5063：库存可为 1 位小数 ⇒ 展示与 data 都过一遍 Decimal 归一，
        # 免得整数库存（float 9599.0）显示成「9599.0」、小数带二进制毛刺。
        stock_display = _stock_number(Decimal(str(stock["stock"])))
        return ToolResult(
            success=True,
            data={
                "product_id": product_id,
                "product_name": product_name,
                "stock": stock_display,
                "stock_source": stock["stock_source"],
                "status": data.get("status"),
            },
            message=f"商品【{product_name}】当前库存：{stock_display}",
            summary=f"库存查询: {product_name}, 库存{stock_display}米",
        )
    async def _low_stock_alert(
        self,
        context: ToolContext,
        threshold: int = LOW_STOCK_THRESHOLD,
    ) -> ToolResult:
        """低库存预警查询（按颜色+规格维度）

        调用 admin-api 的 /api/admin/products/low-stock-by-color 接口，
        按 SKU 级别（颜色 × 门幅）返回低库存明细，而非商品总库存。

        Args:
            context: Tool 执行上下文
            threshold: 库存预警阈值，默认取单点来源
                `app/tools/stock_semantics.py::LOW_STOCK_THRESHOLD`（issue #3783；
                上界含：后端 SQL 为 `stock <= threshold`）

        Returns:
            ToolResult: 低库存 SKU 列表（含颜色、规格维度）
        """
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/products/low-stock-by-color",
            params={"threshold": threshold, "limit": 50},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="低库存预警查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        records = response.get("data", [])

        # 按颜色+规格维度格式化（含租户校验，纵深防御）
        low_stock_items = []
        for record in records:
            # 后端 SQL 已按 tenant 过滤，此处为纵深防御
            resp_tenant_id = record.get("tenantId")
            if resp_tenant_id is not None and str(resp_tenant_id) != str(context.tenant_id):
                continue
            low_stock_items.append({
                "product_id": record.get("productId"),
                "product_name": record.get("productName"),
                "sku_code": record.get("skuCode"),
                "color_name": record.get("colorName"),
                "door_width": record.get("doorWidth"),
                "stock": record.get("stock"),
                "price": record.get("price"),
            })

        logger.info(
            f"Low stock alert (color-dim): threshold={threshold}, found={len(low_stock_items)}, "
            f"tenant={context.tenant_id}"
        )

        if not low_stock_items:
            return ToolResult(
                success=True,
                data={"items": [], "threshold": threshold, "count": 0},
                message=f"没有 SKU {low_stock_phrase(threshold)} 的商品，库存状况良好",
            )

        return ToolResult(
            success=True,
            data={
                "items": low_stock_items,
                "threshold": threshold,
                "count": len(low_stock_items),
            },
            message=f"发现 {len(low_stock_items)} 个 SKU {low_stock_phrase(threshold)}，请按颜色+规格维度及时补货",
        )

    # ── 具名跨域视图 `material_shortage`（issue #6280 冻结契约 v1）──────────────
    #
    # Python 侧**不重算**任何预测：风险分层 / 缺口 / 历史深度判定都由 admin-api 的 Java 纯函数
    # 产出（页面与 agent 共用同一份数字）。本工具只做三件事：取数 · 形态校验（fail-closed）·
    # 把三态与「未知 ≠ 0」的纪律用人话披露出去。

    @staticmethod
    def _num_text(value: Any) -> str:
        """数值的人话形态（`18.0` ⇒ `18`；`None` ⇒ `未知`，**不是 0**）。"""
        if value is None or isinstance(value, bool):
            return "未知"
        parsed = _one_decimal_or_none(value)
        if parsed is None:
            return str(value)
        number = _stock_number(parsed)
        return str(number)

    def _shortage_bands_text(self, band_counts: Any) -> str:
        """六档人话（按固定序，逐档给可复算计数）—— 缺一档就少一个「能被人解释的分层」。"""
        counts = band_counts if isinstance(band_counts, dict) else {}
        parts = []
        for band in _RISK_BANDS:
            count = counts.get(band)
            if count is None:
                continue
            parts.append(f"{band}（{count} 个"
                         + (f"：{_BAND_PHRASES[band]}" if band in _BAND_PHRASES else "")
                         + "）")
        return "风险分层：" + "、".join(parts) if parts else ""

    def _shortage_message(self, view: Dict[str, Any]) -> str:
        """把视图快照拼成**面向 LLM 的披露文本**（判据 3/4/5/6 都落在这里）。"""
        fields = view.get("fields") if isinstance(view.get("fields"), dict) else {}
        rows = view.get("rows") or []
        count = view.get("count")
        count_text = count if isinstance(count, int) else len(rows)

        message = f"缺料与缺口视图（截至 {view.get('as_of')}）：{count_text} 个商品有需求侧关注点。"
        bands = self._shortage_bands_text(view.get("band_counts"))
        if bands:
            message += bands + "。"

        if not rows:
            message += "本次**没有**缺料风险商品（端点已明确返回空结果）——这是「查过了、没问题」。"
            message += "⚠️ 未完成订单未发生扣减台账（真实历史深度 2 周 < 要求 8 周）⇒ " \
                       "预测层未启用，`rate_per_week`（周耗用速率）与 `exhaust_date`（预计耗尽日）一律为「未知」" \
                       "——**不是 0**，请勿理解为「消耗很慢 / 不会耗尽」。"
            return message

        non_comparable = view.get("non_comparable") if isinstance(view.get("non_comparable"), dict) else {}
        nc_lines = non_comparable.get("lines")
        nc_products = non_comparable.get("products")
        if nc_lines or nc_products:
            message += (f"⚠️ 有 {nc_lines} 行 / {nc_products} 个商品**单位不可比**"
                        "（`products.unit` 不是「米」）⇒ 这些行的需求量 `demand_qty = null` 是「未知」，"
                        "**不是 0、也不是没有需求**；它们的风险分层为 unknown。")

        prediction_reason = ""
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("product_name"):
                prediction_reason = f"代表性商品：{row.get('product_name')}"
                break
        unwired_fields = [name for name, entry in fields.items()
                          if isinstance(entry, dict) and entry.get("status") == NOT_WIRED
                          and entry.get("truth") == HAS_TRUTH]
        if unwired_fields:
            depth = view.get("history_depth") if isinstance(view.get("history_depth"), dict) else {}
            weeks = depth.get("weeks")
            required = depth.get("required_weeks")
            message += (f"⚠️ 预测层未启用：真实历史深度 {self._num_text(weeks)} 周 < 要求 "
                        f"{self._num_text(required)} 周（数据年轻，不是数据脏）⇒ 以下字段一律「未知」，"
                        "**不是 0、不是当天**："
                        + "、".join(f"{fields[name].get('label') or name}（{name}）"
                                    for name in unwired_fields) + "。")

        no_truth = view.get("no_truth_fields") or []
        if no_truth:
            detail = "；".join(
                f"{name}：{fields[name].get('reason')}"
                for name in no_truth
                if isinstance(fields.get(name), dict) and fields[name].get("reason"))
            message += (f"⚠️ 其中 {len(no_truth)} 个字段**没有真值来源**"
                        f"⇒ 一律为「未知」，**不是 0**：{'、'.join(no_truth)}"
                        + (f"（逐条原因：{detail}）" if detail else "") + "。")

        short_rows = [row for row in rows
                      if isinstance(row, dict) and row.get("risk_band") == "short"]
        if short_rows:
            message += (f"⚠️ {len(short_rows)} 个商品落在 `short` 档 = **缺口确定、紧迫性未知**"
                        "（有缺口但交期未填或 >7 天）——**不得**读成 critical（临近交期）、"
                        "也**不得**读成 safe，需先补交期才能判紧急度。")

        if view.get("truncated"):
            message += (f"⚠️ 视图只列前 {view.get('count')} 个商品，共 {view.get('rows_total')} 个"
                        "（按风险分层取前段；聚合计数用的是全量行）。")

        message += "缺口为负 = 该商品有余量（照实返回）。"
        return message

    async def _material_shortage(self, context: ToolContext) -> ToolResult:
        """缺料与缺口视图（具名跨域视图 `material_shortage` 的按需消费，issue #6280）。

        取数面 = **一条只读端点** `/api/admin/materials/shortage`（权限 `product:list`）。
        fail-closed：端点失败 / 响应形态不认识 ⇒ 明确失败并点名权限码，
        **不得**把「没查到」伪装成「没有缺料」（空列表只在端点明确成功且形态完整时才算结论）。
        """
        client = get_admin_api_client()
        try:
            response = await client.get(
                "/api/admin/materials/shortage",
                params={"statuses": MATERIAL_SHORTAGE_STATUSES, "limit": MATERIAL_SHORTAGE_LIMIT},
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as exc:  # 网络 / 超时 / 熔断：归因到这一面
            logger.error("[inventory-manage] material_shortage 端点异常 {}: {}",
                         type(exc).__name__, exc)
            return ToolResult(
                success=False,
                error="material_shortage_fetch_failed",
                message=(f"缺料与缺口视图取数失败 —— 端点读不到（product:list）："
                         f"{type(exc).__name__}: {exc}"
                         "（fail-closed：没有需求/供给面就无法出结论，**不是**「没有缺料」）"),
                suggestion="请确认当前账号具备 product:list；若只是临时故障请稍后重试，"
                           "也可先用 inventory_manage(action=query, product_id=…) 查单个商品库存",
            )

        if not response.get("success"):
            error = response.get("error")
            detail = error.get("message", "查询失败") if isinstance(error, dict) else str(error or "查询失败")
            logger.warning("[inventory-manage] material_shortage 取数失败：{}", detail)
            return admin_api_failure(
                response,
                error="material_shortage_fetch_failed",
                message=(f"缺料与缺口视图取数失败（product:list）：{detail}"
                         "（fail-closed：取不到数就不能说「没有缺料」）"),
                suggestion="请确认当前账号具备 product:list；若只是临时故障请稍后重试，"
                           "也可先用 inventory_manage(action=low_stock_alert) 查低于阈值的 SKU 清单",
            )

        view = response.get("data")
        rows = view.get("rows") if isinstance(view, dict) else None
        band_counts = view.get("band_counts") if isinstance(view, dict) else None
        missing = [name for name, value in (("rows", rows), ("band_counts", band_counts))
                   if not isinstance(value, (list, dict))]
        if not isinstance(view, dict) or missing or view.get("view") != "material_shortage":
            logger.error("[inventory-manage] material_shortage 响应形态不可识别：keys={}",
                         sorted(view.keys()) if isinstance(view, dict) else type(view).__name__)
            return ToolResult(
                success=False,
                error="material_shortage_contract_mismatch",
                message=("缺料与缺口视图响应形态不可识别（缺少 " + "、".join(missing or ["view"])
                         + "）⇒ 无法判定有无缺料。**「没查到」不等于「没有缺料」**，"
                           "本结果不得当作「当前没有缺料」上报。"),
                suggestion="这是后端契约不一致（页面与 agent 共用同一端点）："
                           "请报告「material_shortage 端点响应形态与冻结契约 v1 不符」，不要重试同一调用",
            )

        logger.info("[inventory-manage] material_shortage rows={} total={} bands={}",
                    view.get("count"), view.get("rows_total"), band_counts)
        return ToolResult(
            success=True,
            data=dict(view),
            message=self._shortage_message(view),
            summary=f"缺料与缺口视图: {view.get('count')} 个商品",
        )
