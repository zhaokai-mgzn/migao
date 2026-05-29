"""
AI 智能客服系统 - 加工项价格查询 Tool

查询商品关联的加工项及其价格（含自定义价格）。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class ProcessingItemsTool(BaseTool):
    """加工项价格查询 Tool
    
    查询商品关联的加工项配置，包含默认价格、自定义价格和最终价格。
    
    使用场景：
    - 商家询问"这个商品有哪些加工项"
    - 商家想知道某个商品的加工费用
    - 商家想了解自定义价格与默认价格的区别
    """
    
    name = "query_processing_items"
    description = (
        "查询商品关联的加工项及其价格（含自定义价格和最终价格）。"
        "当需要了解商品的加工项配置、加工费用明细、自定义定价时使用。"
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
        """查询商品加工项
        
        Args:
            context: Tool 执行上下文
            product_id: 商品 ID
            product_name: 商品名称（用于搜索获取ID）
            
        Returns:
            ToolResult: 加工项查询结果
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询加工项信息",
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
            
            logger.info(f"[processing-items] Querying: product_id={product_id} | tenant={context.tenant_id}")
            
            # 调用 admin-api
            client = get_admin_api_client()
            response = await client.get(
                f"/api/admin/products/{product_id}/processing-items",
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
            
            if not response.get("success"):
                error_msg = response.get("error", {}).get("message", "查询失败")
                return ToolResult(
                    success=False,
                    error=error_msg,
                    message=f"查询加工项失败：{error_msg}",
                )
            
            data = response.get("data", {})
            
            # 格式化加工项信息
            formatted = self._format_processing_items(data)
            
            logger.info(
                f"[processing-items] Found {formatted.get('item_count', 0)} items "
                f"for product_id={product_id} | tenant={context.tenant_id}"
            )
            
            if formatted["item_count"] == 0:
                return ToolResult(
                    success=True,
                    data=formatted,
                    message="该商品暂无关联的加工项",
                )
            
            return ToolResult(
                success=True,
                data=formatted,
                message=f"该商品共有 {formatted['item_count']} 个加工项",
            )
            
        except Exception as e:
            logger.error(f"[processing-items] Query failed | tenant={context.tenant_id} error={type(e).__name__}: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                message="查询加工项时出错，请稍后重试",
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
    
    def _format_processing_items(self, data: Any) -> Dict[str, Any]:
        """格式化加工项数据
        
        Args:
            data: API返回的加工项数据
            
        Returns:
            格式化后的加工项信息
        """
        if isinstance(data, list):
            items_raw = data
        else:
            items_raw = data.get("items") or data.get("processingItems", [])
        
        items = []
        for item in items_raw:
            default_price = item.get("defaultPrice") or item.get("default_price")
            custom_price = item.get("customPrice") or item.get("custom_price")
            final_price = item.get("finalPrice") or item.get("final_price")
            
            # 如果没有final_price，使用custom_price或default_price
            if final_price is None:
                final_price = custom_price if custom_price is not None else default_price
            
            items.append({
                "id": item.get("id") or item.get("processingItemId"),
                "name": item.get("name") or item.get("itemName"),
                "category": item.get("category") or item.get("categoryName"),
                "unit": item.get("unit", ""),
                "default_price": default_price,
                "custom_price": custom_price,
                "final_price": final_price,
                "has_custom_price": custom_price is not None,
            })
        
        return {
            "item_count": len(items),
            "items": items,
        }
