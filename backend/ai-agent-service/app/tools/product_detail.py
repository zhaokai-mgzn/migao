"""
AI 智能客服系统 - 商品详情 Tool

查询商品详细信息，包括价格、规格、描述等。
"""

from typing import Any, Dict
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class ProductDetailTool(BaseTool):
    """商品详情 Tool
    
    查询商品的详细信息，包括价格、规格、SKU、库存等。
    
    使用场景：
    - 用户询问某个商品的详细信息
    - 用户询问价格、规格、库存
    - 需要展示商品详情卡片
    """
    
    name = "product_detail"
    description = (
        "【触发】用户问'XX商品详情''XX多少钱''XX什么颜色''XX的规格'或指定商品ID时调用。【前置】需要 product_id，如果用户只说了商品名，先调 product_search 获取ID。【反例】搜商品列表用 product_search，查库存用 inventory_manage。【标注】READONLY"
    )
    
    parameters = {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "商品 ID",
            },
        },
        "required": ["product_id"],
    }
    
    async def execute(
        self,
        context: ToolContext,
        product_id: str,
    ) -> ToolResult:
        """执行商品详情查询
        
        Args:
            context: Tool 执行上下文
            product_id: 商品 ID
            
        Returns:
            ToolResult: 商品详情
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查看商品详情",
                suggestion="请联系管理员获取查看商品详情权限",
            )
        
        if not product_id:
            return ToolResult(
                success=False,
                error="缺少商品 ID",
                message="请提供商品 ID",
            )
        
        try:
            # 调用 admin-api
            client = get_admin_api_client()
            response = await client.get(
                f"/api/admin/products/{product_id}",
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
            
            # 解析响应
            if not response.get("success"):
                error_code = response.get("error", {}).get("code", "")
                error_msg = response.get("error", {}).get("message", "查询失败")
                
                if error_code == "NOT_FOUND" or "不存在" in error_msg:
                    return ToolResult(
                        success=False,
                        error="商品不存在",
                        message="抱歉，未找到该商品，请检查商品 ID 是否正确",
                    )
                
                return ToolResult(
                    success=False,
                    error=error_msg,
                    message="查询商品详情失败，请稍后重试",
                    suggestion="请稍后重试，如持续失败请联系技术支持",
                )
            
            data = response.get("data", {})
            
            if not data:
                return ToolResult(
                    success=False,
                    error="商品不存在",
                    message="抱歉，未找到该商品",
                )
            
            # 验证响应数据的 tenant_id
            resp_tenant_id = data.get("tenantId") or data.get("tenant_id")
            if resp_tenant_id is not None and str(resp_tenant_id) != str(context.tenant_id):
                logger.error(
                    f"Tenant data integrity violation in product_detail: "
                    f"response tenant_id={resp_tenant_id}, expected={context.tenant_id}"
                )
                return ToolResult(
                    success=False,
                    error="商品不存在",
                    message="抱歉，未找到该商品",
                )
            
            # 格式化商品详情
            product = self._format_product(data)
            
            logger.info(
                f"Product detail: id={product_id}, name={product.get('name')}, "
                f"tenant={context.tenant_id}"
            )
            
            price_text = f"{product.get('price')}元" if product.get('price') is not None else "暂无标价"
            return ToolResult(
                success=True,
                data=product,
                message=f"已获取商品【{product.get('name')}】的详细信息",
                summary=f"商品详情: {product.get('name')}, {price_text}",
            )
            
        except Exception as e:
            logger.error(f"Product detail error: {e}")
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="查询商品详情时出错，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )
    
    def _format_product(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """格式化商品详情
        
        Args:
            data: 原始商品数据
            
        Returns:
            Dict: 格式化后的商品详情
        """
        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "description": data.get("description", ""),
            "price": data.get("price") or data.get("basePrice"),
            "original_price": data.get("originalPrice"),
            "stock": data.get("stock"),
            "status": data.get("status"),
            "category_id": data.get("categoryId"),
            "category_name": data.get("categoryName"),
            "images": data.get("images", []),
            "main_image": data.get("mainImage") or (
                data.get("images", [None])[0] if data.get("images") else None
            ),
            "skus": self._format_skus(data.get("skus", [])),
            "specifications": data.get("specifications", {}),
            "processing_items": data.get("processingItems", []),
            "sales_count": data.get("salesCount", 0),
            "created_at": data.get("createdAt"),
        }
    
    def _format_skus(self, skus: list) -> list:
        """格式化 SKU 列表
        
        Args:
            skus: 原始 SKU 列表
            
        Returns:
            list: 格式化后的 SKU 列表
        """
        if not skus:
            return []
        
        formatted = []
        for sku in skus:
            formatted.append({
                "id": sku.get("id"),
                "sku_code": sku.get("skuCode"),
                "specifications": sku.get("specifications", {}),
                "price": sku.get("price"),
                "stock": sku.get("stock"),
                "status": sku.get("status"),
            })
        
        return formatted
