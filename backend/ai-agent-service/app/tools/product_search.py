"""
AI 智能客服系统 - 商品搜索 Tool

搜索商品列表，根据关键词、分类等条件查询商品。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client
from app.utils.field_mapper import FieldMapper


class ProductSearchTool(BaseTool):
    """商品搜索 Tool
    
    搜索商品列表，支持关键词、分类、价格区间筛选。
    
    使用场景：
    - 用户询问"有什么窗帘"
    - 用户搜索"遮光窗帘"
    - 用户询问某个分类的商品
    """
    
    name = "product_search"
    description = (
        "搜索商品列表，根据关键词、分类等条件查询商品。"
        "当用户询问有什么产品、想找某种商品、或需要推荐时使用。"
    )
    
    parameters = {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "搜索关键词，如'遮光窗帘'、'雪尼尔'",
            },
            "category_id": {
                "type": "string",
                "description": "商品分类 ID（可选）",
            },
            "min_price": {
                "type": "number",
                "description": "最低价格（可选）",
            },
            "max_price": {
                "type": "number",
                "description": "最高价格（可选）",
            },
            "page": {
                "type": "integer",
                "description": "页码，默认 1",
                "default": 1,
            },
            "size": {
                "type": "integer",
                "description": "每页数量，默认 5",
                "default": 5,
            },
            "stock_status": {
                "type": "string",
                "description": "库存状态筛选（可选）：in_stock（有库存）/ low_stock（低库存）/ out_of_stock（缺货）",
                "enum": ["in_stock", "low_stock", "out_of_stock"],
            },
        },
    }
    
    async def execute(
        self,
        context: ToolContext,
        keyword: str = "",
        category_id: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        page: int = 1,
        size: int = 5,
        stock_status: Optional[str] = None,
    ) -> ToolResult:
        """执行商品搜索
        
        Args:
            context: Tool 执行上下文
            keyword: 搜索关键词
            category_id: 分类 ID
            min_price: 最低价格
            max_price: 最高价格
            page: 页码
            size: 每页数量
            stock_status: 库存状态筛选（in_stock/low_stock/out_of_stock）
            
        Returns:
            ToolResult: 搜索结果
        """
        # 强制转换分页参数为 int（LLM 可能传字符串）
        page = int(page) if page else 1
        size = int(size) if size else 5
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限搜索商品",
            )
        
        try:
            # 搜索请求日志
            logger.info(f"[product-search] Searching: keyword='{keyword}' category={category_id} | tenant={context.tenant_id}")
            
            # 构建查询参数
            params: Dict[str, Any] = {
                "page": page,
                "size": size,
            }
            
            if keyword:
                params["keyword"] = keyword
            if category_id:
                params["categoryId"] = category_id
            if min_price is not None:
                params["minPrice"] = min_price
            if max_price is not None:
                params["maxPrice"] = max_price
            if stock_status:
                params["stockStatus"] = stock_status
            
            # 调用 admin-api
            client = get_admin_api_client()
            response = await client.get(
                "/api/admin/products",
                params=params,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
            
            # 解析响应
            if not response.get("success"):
                error_msg = response.get("error", {}).get("message", "搜索失败")
                return ToolResult(
                    success=False,
                    error=error_msg,
                    message="商品搜索失败，请稍后重试",
                )
            
            data = response.get("data", {})
            records = data.get("items", [])
            total = data.get("total", 0)
            
            # 验证响应数据的 tenant_id，过滤不属于当前租户的记录
            verified_records = []
            filtered_count = 0
            for record in records:
                resp_tenant_id = record.get("tenantId") or record.get("tenant_id")
                if resp_tenant_id is not None and str(resp_tenant_id) != str(context.tenant_id):
                    logger.error(
                        f"Tenant data integrity violation in product_search: "
                        f"response tenant_id={resp_tenant_id}, expected={context.tenant_id}"
                    )
                    filtered_count += 1
                    continue
                verified_records.append(record)
            
            if filtered_count > 0:
                logger.warning(
                    f"Product search filtered {filtered_count} records due to tenant_id mismatch, "
                    f"tenant={context.tenant_id}"
                )
                total = max(0, total - filtered_count)
            
            # 格式化商品列表
            products = self._format_products(verified_records)
            
            logger.info(
                f"[product-search] Found {len(products)} products, total={total} | tenant={context.tenant_id}"
            )
            
            if not products:
                return ToolResult(
                    success=True,
                    data={"products": [], "total": 0, "page": page, "size": size},
                    message=f"抱歉，没有找到与'{keyword}'相关的商品，换个关键词试试？",
                    summary=f"未找到与'{keyword}'相关的商品",
                )

            # 构建摘要：取前3个商品名
            top_names = [p["name"] for p in products[:3] if p.get("name")]
            names_str = "、".join(top_names)
            if len(products) > 3:
                names_str += "等"

            return ToolResult(
                success=True,
                data={
                    "products": products,
                    "total": total,
                    "page": page,
                    "size": size,
                    "total_pages": (total + size - 1) // size,
                },
                message=f"找到 {total} 件相关商品",
                summary=f"找到{total}件商品: {names_str}",
            )
            
        except Exception as e:
            logger.error(f"[product-search] Search failed | tenant={context.tenant_id} error={type(e).__name__}: {e}")
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="搜索商品时出错，请稍后重试",
            )
    
    def _format_products(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """格式化商品列表
        
        Args:
            records: 原始商品记录
            
        Returns:
            List: 格式化后的商品列表
        """
        products = []
        for record in records:
            product = {
                "id": record.get("id"),
                "name": record.get("name"),
                "price": FieldMapper.get_price(record),
                "description": record.get("description", ""),
                "images": record.get("images", []),
                "main_image": FieldMapper.get_main_image(record),
                "stock": record.get("stock"),
                "status": record.get("status"),
                "category_id": FieldMapper.get_category_id(record),
                "specifications": record.get("specifications", {}),
            }
            products.append(product)
        
        return products
