"""
AI 智能客服系统 - 库存汇总查询 Tool

查询商品的库存汇总，包含总库存、销量和销售额。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class ProductInventoryTool(BaseTool):
    """商品库存汇总查询 Tool
    
    查询商品的库存汇总信息，包含总库存、总销量、总销售额以及各SKU库存详情。
    
    使用场景：
    - 商家询问"这个商品卖了多少"
    - 商家想看某商品的总库存和销售情况
    - 商家想了解各SKU的销售数据
    """
    
    name = "query_inventory"
    description = (
        "查询商品的库存汇总，包含总库存、总销量、总销售额和各SKU库存详情。"
        "当需要了解商品销售情况、库存总览、各SKU库存明细时使用。"
    )
    
    parameters = {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "商品 ID（与 product_name 二选一）",
            },
            "product_name": {
                "type": "string",
                "description": "商品名称（模糊搜索获取ID，与 product_id 二选一）",
            },
        },
    }
    
    async def execute(
        self,
        context: ToolContext,
        product_id: Optional[str] = None,
        product_name: Optional[str] = None,
    ) -> ToolResult:
        """查询商品库存汇总
        
        Args:
            context: Tool 执行上下文
            product_id: 商品 ID
            product_name: 商品名称（用于搜索获取ID）
            
        Returns:
            ToolResult: 库存汇总结果
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询库存汇总信息",
            )
        
        try:
            # 如果没有product_id，尝试通过名称搜索
            if not product_id:
                if not product_name:
                    return ToolResult(
                        success=False,
                        error="缺少参数",
                        message="请提供商品ID（product_id）或商品名称（product_name）",
                    )
                product_id = await self._search_product_id(context, product_name)
                if not product_id:
                    return ToolResult(
                        success=False,
                        error="商品未找到",
                        message=f"未找到名称包含「{product_name}」的商品",
                    )
            
            logger.info(f"[inventory] Querying summary: product_id={product_id} | tenant={context.tenant_id}")
            
            # 调用 admin-api
            client = get_admin_api_client()
            response = await client.get(
                f"/api/admin/products/{product_id}/inventory-summary",
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
            
            if not response.get("success"):
                error_msg = response.get("error", {}).get("message", "查询失败")
                return ToolResult(
                    success=False,
                    error=error_msg,
                    message=f"查询库存汇总失败：{error_msg}",
                )
            
            data = response.get("data", {})
            
            # 格式化库存汇总信息
            formatted = self._format_inventory_data(data)
            
            logger.info(
                f"[inventory] Summary: product_id={product_id} "
                f"totalStock={formatted.get('total_stock')} "
                f"totalSales={formatted.get('total_sales_count')} | tenant={context.tenant_id}"
            )
            
            return ToolResult(
                success=True,
                data=formatted,
                message=(
                    f"库存汇总：总库存 {formatted.get('total_stock', 0)} 件，"
                    f"总销量 {formatted.get('total_sales_count', 0)} 件，"
                    f"总销售额 ¥{formatted.get('total_sales_amount', 0):.2f}"
                ),
            )
            
        except Exception as e:
            logger.error(f"[inventory] Query failed | tenant={context.tenant_id} error={type(e).__name__}: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                message="查询库存汇总时出错，请稍后重试",
            )
    
    async def _search_product_id(self, context: ToolContext, product_name: str) -> Optional[str]:
        """通过商品名称搜索获取product_id"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/products",
            params={"keyword": product_name, "size": 1},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        
        if response.get("success"):
            items = response.get("data", {}).get("items", [])
            if items:
                return str(items[0].get("id"))
        return None
    
    def _format_inventory_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """格式化库存汇总数据
        
        Args:
            data: API返回的库存汇总数据
            
        Returns:
            格式化后的库存信息
        """
        total_stock = data.get("totalStock") or data.get("total_stock", 0)
        total_sales_count = data.get("totalSalesCount") or data.get("total_sales_count", 0)
        total_sales_amount = data.get("totalSalesAmount") or data.get("total_sales_amount", 0)
        
        # 处理SKU详情
        sku_details_raw = data.get("skuDetails") or data.get("sku_details", [])
        sku_details = []
        for sku in sku_details_raw:
            sku_details.append({
                "sku_id": sku.get("id") or sku.get("skuId"),
                "sku_code": sku.get("skuCode") or sku.get("sku_code"),
                "color": sku.get("colorName") or sku.get("color"),
                "size": sku.get("sizeName") or sku.get("size"),
                "stock": sku.get("stock", 0),
                "sales_count": sku.get("salesCount") or sku.get("sales_count", 0),
                "sales_amount": sku.get("salesAmount") or sku.get("sales_amount", 0),
            })
        
        return {
            "total_stock": total_stock,
            "total_sales_count": total_sales_count,
            "total_sales_amount": total_sales_amount,
            "sku_count": len(sku_details),
            "sku_details": sku_details,
        }
