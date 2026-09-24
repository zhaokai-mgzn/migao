"""
AI 智能客服系统 - 库存管理 Tool

查询和调整商品库存，支持库存预警查询。
"""

from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Union

from loguru import logger

from app.tools.base import (
    admin_api_failure,
    BaseTool,
    ToolContext,
    ToolResult,
    permission_denied,
)
from app.tools.stock_semantics import (
    LOW_STOCK_THRESHOLD,
    NO_SKU_SOURCE,
    low_stock_alert_threshold_schema,
    low_stock_phrase,
    no_sku_stock_note,
    product_stock_summary,
)
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"query", "low_stock_alert"}

#: 库存（米）的记数粒度 = 0.1（后端列 `NUMERIC(12,1)`，issue #5063；
#: 与算料口径「用料米数一律向上进位到 0.1」同源）。
STOCK_QUANTUM = Decimal("0.1")


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
        "【参数】action 必填：**只有 query（需 product_id）/ low_stock_alert（可选 threshold）两个只读 action**"
        "（B 端已只读化，issue #5247）。"
        "【反例】查商品详情（含库存字段）用 product_detail；查批次余量/剩料分布用 batch_stock_query。"
        "【反例】调库存**不在本工具能力内**——引导用户到后台「商品列表 → 编辑商品 → 库存」页调整。"
        "【标注】READONLY — 纯查询，不含任何写 action"
    )
    
    # 权限码（admin-api 目录）：ProductController / AgentProductController 的库存端点 ——
    # 读（query/low_stock_alert）= `product:list`、写（adjust）= `product:create`，与 controller 同码。
    # 声明了权限码 ⇒ **删除** allowed_roles：它含 C 端角色 `customer`（横向越权，issue #5246 判据 6），
    # 且权限码在场时角色白名单本就不生效＝第二份会漂的假门禁（#4106 F4）。
    required_permissions = ["product:list"]  # B 端只读化（#5247）：写码 product:create 已随 adjust 一并移除

    read_only = True
    read_only_actions = {"query", "low_stock_alert"}  # 只读 action 免确认
    destructive = False  # 库存调整可逆
    idempotent = False   # 调整操作非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：query（查询库存）/ low_stock_alert（低库存预警）—— 均为只读",
                "enum": ["query", "low_stock_alert"],
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
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )
        
        try:
            if action == "query":
                return await self._query_inventory(context, product_id)
            elif action == "low_stock_alert":
                return await self._low_stock_alert(context, threshold)
            else:
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
