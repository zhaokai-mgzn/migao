"""
AI 智能客服系统 - 库存管理 Tool

查询和调整商品库存，支持库存预警查询。
"""

from typing import Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"query", "adjust", "low_stock_alert"}


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
        "【触发】用户问'库存''还有多少''缺货''低库存''出库''入库''调整库存'时调用。【前置】query: 需要 product_id。adjust: product_id+adjustment+reason。low_stock_alert: 可选 threshold。customer 角色仅允许 query，adjust 和 low_stock_alert 仅限管理员/客服。【反例】查商品详情(含库存字段)用 product_detail，不要混淆。【标注】WRITE(adjust) — query是安全的，adjust需确认"
    )
    
    # admin、agent、customer、tenant_admin 可使用（customer 仅限 query 操作）
    allowed_roles = ["admin", "agent", "customer", "tenant_admin"]

    read_only = False
    destructive = False  # 库存调整可逆
    idempotent = False   # 调整操作非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：query（查询库存）/ adjust（调整库存）/ low_stock_alert（低库存预警）",
                "enum": ["query", "adjust", "low_stock_alert"],
            },
            "product_id": {
                "type": "string",
                "description": "商品 32 位 UUID。必须先通过 product_detail 或 product_search 查出真实 UUID 再传入，禁止传商品名称或序号",
            },
            "adjustment": {
                "type": "integer",
                "description": "调整数量（adjust 时必填），正数增加，负数减少",
            },
            "reason": {
                "type": "string",
                "description": "调整原因（adjust 时必填）",
            },
            "threshold": {
                "type": "integer",
                "description": "库存预警阈值（low_stock_alert 时可选，默认 10）",
                "default": 10,
            },
        },
        "required": ["action"],
    }
    
    async def execute(
        self,
        context: ToolContext,
        action: str,
        product_id: Optional[str] = None,
        adjustment: Optional[int] = None,
        reason: Optional[str] = None,
        threshold: int = 10,
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
        
        # customer 角色仅允许 query 操作
        if context.role == "customer" and action != "query":
            return ToolResult(
                success=False,
                error="权限不足",
                message="抱歉，库存调整和低库存预警功能仅限管理员和客服使用。如需查询商品库存，请告诉我商品名称或 ID。",
            )
        
        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
            )
        
        try:
            if action == "query":
                return await self._query_inventory(context, product_id)
            elif action == "adjust":
                return await self._adjust_inventory(context, product_id, adjustment, reason)
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
            logger.error(f"Inventory manage error: action={action}, product_id={product_id}, error={e}")
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
                return ToolResult(
                    success=False,
                    error="商品不存在",
                    message="未找到该商品，请检查商品 ID",
                    suggestion="请检查ID是否正确，或尝试其他搜索条件",
                )
            
            return ToolResult(
                success=False,
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
        
        stock = data.get("stock", 0)
        product_name = data.get("name", "")
        
        logger.info(
            f"Inventory query: product_id={product_id}, stock={stock}, "
            f"tenant={context.tenant_id}"
        )
        
        return ToolResult(
            success=True,
            data={
                "product_id": product_id,
                "product_name": product_name,
                "stock": stock,
                "status": data.get("status"),
            },
            message=f"商品【{product_name}】当前库存：{stock}",
            summary=f"库存查询: {product_name}, 库存{stock}件",
        )
    
    async def _adjust_inventory(
        self,
        context: ToolContext,
        product_id: Optional[str],
        adjustment: Optional[int],
        reason: Optional[str],
    ) -> ToolResult:
        """调整库存数量
        
        Args:
            context: Tool 执行上下文
            product_id: 商品 ID
            adjustment: 调整数量
            reason: 调整原因
            
        Returns:
            ToolResult: 操作结果
        """
        if not product_id:
            return ToolResult(
                success=False,
                error="缺少商品 ID",
                message="调整库存时必须提供商品 ID（product_id）",
            )
        
        if adjustment is None:
            return ToolResult(
                success=False,
                error="缺少调整数量",
                message="调整库存时必须提供调整数量（adjustment）",
            )
        
        if not reason:
            return ToolResult(
                success=False,
                error="缺少调整原因",
                message="调整库存时必须提供调整原因（reason）",
            )
        
        # 先查询当前库存
        client = get_admin_api_client()
        query_response = await client.get(
            f"/api/admin/products/{product_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        
        if not query_response.get("success"):
            error_msg = query_response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message="无法获取当前库存信息",
            )
        
        product_data = query_response.get("data", {})
        current_stock = product_data.get("stock", 0)
        product_name = product_data.get("name", "")
        new_stock = current_stock + adjustment
        
        if new_stock < 0:
            return ToolResult(
                success=False,
                error="库存不足",
                message=f"当前库存 {current_stock}，无法减少 {abs(adjustment)}",
            )
        
        # 更新库存（对抗编程：透传 reason，防止丢失调整原因）
        update_payload: dict = {"name": product_name, "stock": new_stock}
        if reason:
            update_payload["reason"] = reason
        response = await client.put(
            f"/api/admin/products/{product_id}",
            json_data=update_payload,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"库存调整失败：{error_msg}",
            )
        
        adjust_text = f"增加 {adjustment}" if adjustment > 0 else f"减少 {abs(adjustment)}"
        logger.info(
            f"Inventory adjusted: product_id={product_id}, "
            f"adjustment={adjustment}, {current_stock} -> {new_stock}, "
            f"reason={reason}, tenant={context.tenant_id}, user={context.user_id}"
        )
        
        return ToolResult(
            success=True,
            data={
                "product_id": product_id,
                "previous_stock": current_stock,
                "adjustment": adjustment,
                "new_stock": new_stock,
                "reason": reason,
            },
            message=f"库存已{adjust_text}，{current_stock} → {new_stock}",
        )
    
    async def _low_stock_alert(
        self,
        context: ToolContext,
        threshold: int = 100,
    ) -> ToolResult:
        """低库存预警查询（按颜色+规格维度）

        调用 admin-api 的 /api/admin/products/low-stock-by-color 接口，
        按 SKU 级别（颜色 × 门幅）返回低库存明细，而非商品总库存。

        Args:
            context: Tool 执行上下文
            threshold: 库存预警阈值，默认 100

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
            return ToolResult(
                success=False,
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
                message=f"没有 SKU 库存低于 {threshold} 的商品，库存状况良好",
            )

        return ToolResult(
            success=True,
            data={
                "items": low_stock_items,
                "threshold": threshold,
                "count": len(low_stock_items),
            },
            message=f"发现 {len(low_stock_items)} 个 SKU 库存低于 {threshold}，请按颜色+规格维度及时补货",
        )
