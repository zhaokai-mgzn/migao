"""
AI 智能客服系统 - 商品管理 Tool

创建、更新、上下架商品，支持管理商品基本信息和状态。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"create", "update", "toggle_status"}

# 商品状态
VALID_PRODUCT_STATUSES = {"on_sale", "off_sale"}


class ProductManageTool(BaseTool):
    """商品管理 Tool
    
    创建、更新、上下架商品，管理商品基本信息。
    
    使用场景：
    - 管理员创建新商品
    - 管理员更新商品信息（名称、价格、描述等）
    - 管理员上下架商品
    """
    
    name = "product_manage"
    description = (
        "创建、更新、上下架商品，管理商品基本信息。"
        "当需要新增商品、修改商品信息、上架或下架商品时使用。"
    )
    
    # admin、agent、tenant_admin 可使用
    allowed_roles = ["admin", "agent", "tenant_admin"]
    
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：create（创建）/ update（更新）/ toggle_status（上下架）",
                "enum": ["create", "update", "toggle_status"],
            },
            "product_id": {
                "type": "string",
                "description": "商品 ID（update/toggle_status 时必填）",
            },
            "name": {
                "type": "string",
                "description": "商品名称（create 时必填）",
            },
            "category_id": {
                "type": "string",
                "description": "分类 ID（可选）",
            },
            "price": {
                "type": "number",
                "description": "价格（可选）",
            },
            "description": {
                "type": "string",
                "description": "商品描述（可选）",
            },
            "stock_quantity": {
                "type": "integer",
                "description": "库存数量（可选）",
            },
            "processing_item_ids": {
                "type": "array",
                "description": "关联的加工项 ID 列表（可选，create/update 时用于绑定商品可用的加工项）",
                "items": {"type": "string"},
            },
            "status": {
                "type": "string",
                "description": "目标状态（toggle_status 时必填）：on_sale / off_sale",
                "enum": ["on_sale", "off_sale"],
            },
        },
        "required": ["action"],
    }
    
    async def execute(
        self,
        context: ToolContext,
        action: str,
        product_id: Optional[str] = None,
        name: Optional[str] = None,
        category_id: Optional[str] = None,
        price: Optional[float] = None,
        description: Optional[str] = None,
        stock_quantity: Optional[int] = None,
        processing_item_ids: Optional[list] = None,
        status: Optional[str] = None,
        brand: Optional[str] = None,
        images: Optional[list] = None,
        detail_images: Optional[list] = None,
        specifications: Optional[dict] = None,
        unit: Optional[str] = None,
        pricing_type: Optional[str] = None,
    ) -> ToolResult:
        """执行商品管理操作
        
        Args:
            context: Tool 执行上下文
            action: 操作类型
            product_id: 商品 ID
            name: 商品名称
            category_id: 分类 ID
            price: 价格
            description: 商品描述
            stock_quantity: 库存数量
            processing_item_ids: 关联加工项 ID 列表
            status: 目标状态
            
        Returns:
            ToolResult: 操作结果
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行商品管理操作",
            )
        
        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
            )
        
        try:
            if action == "create":
                return await self._create_product(
                    context, name, category_id, price, description, stock_quantity,
                    processing_item_ids, brand, images, detail_images,
                    specifications, unit, pricing_type
                )
            elif action == "update":
                return await self._update_product(
                    context, product_id, name, category_id, price, description, stock_quantity,
                    processing_item_ids, brand, images, detail_images, specifications, unit, pricing_type
                )
            elif action == "toggle_status":
                return await self._toggle_status(context, product_id, status)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                )
                
        except Exception as e:
            logger.error(f"Product manage error: action={action}, product_id={product_id}, error={e}")
            return ToolResult(
                success=False,
                error=str(e),
                message="商品操作失败，请稍后重试",
            )
    
    async def _create_product(
        self,
        context: ToolContext,
        name: Optional[str],
        category_id: Optional[str],
        price: Optional[float],
        description: Optional[str],
        stock_quantity: Optional[int],
        processing_item_ids: Optional[list] = None,
        brand: Optional[str] = None,
        images: Optional[list] = None,
        detail_images: Optional[list] = None,
        specifications: Optional[dict] = None,
        unit: Optional[str] = None,
        pricing_type: Optional[str] = None,
    ) -> ToolResult:
        """创建商品
        
        Args:
            context: Tool 执行上下文
            name: 商品名称
            category_id: 分类 ID
            price: 价格
            description: 商品描述
            stock_quantity: 库存数量
            
        Returns:
            ToolResult: 操作结果
        """
        if not name:
            return ToolResult(
                success=False,
                error="缺少商品名称",
                message="创建商品时必须提供商品名称（name）",
            )
        
        json_data: Dict[str, Any] = {"name": name}
        if category_id:
            json_data["categoryId"] = category_id
        if price is not None:
            json_data["basePrice"] = price
        if description:
            json_data["description"] = description
        if stock_quantity is not None:
            json_data["stock"] = stock_quantity
        if processing_item_ids:
            json_data["processingItems"] = processing_item_ids
        if brand:
            json_data["brand"] = brand
        if images:
            json_data["images"] = list(images)
            if images:
                json_data["mainImage"] = images[0]  # 首图作为封面
        if detail_images:
            json_data["detailImages"] = list(detail_images)
        if specifications:
            if isinstance(specifications, dict):
                json_data["specifications"] = specifications
            elif isinstance(specifications, str):
                # 逗号分隔的字符串转为 {key: key} 格式
                parts = [p.strip() for p in specifications.split(",") if p.strip()]
                json_data["specifications"] = {p: p for p in parts}
        if unit:
            json_data["unit"] = unit
        if pricing_type:
            json_data["pricingType"] = pricing_type
        
        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/products",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "创建失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"创建商品失败：{error_msg}",
            )
        
        product_data = response.get("data", {})
        product_id = product_data.get("id")
        
        logger.info(
            f"Product created: id={product_id}, name={name}, "
            f"tenant={context.tenant_id}, user={context.user_id}"
        )
        
        return ToolResult(
            success=True,
            data={"product_id": product_id, "name": name},
            message=f"商品【{name}】创建成功",
        )
    
    async def _update_product(
        self,
        context: ToolContext,
        product_id: Optional[str],
        name: Optional[str],
        category_id: Optional[str],
        price: Optional[float],
        description: Optional[str],
        stock_quantity: Optional[int],
        processing_item_ids: Optional[list] = None,
        brand: Optional[str] = None,
        images: Optional[list] = None,
        detail_images: Optional[list] = None,
        specifications: Optional[dict] = None,
        unit: Optional[str] = None,
        pricing_type: Optional[str] = None,
    ) -> ToolResult:
        """更新商品信息
        
        Args:
            context: Tool 执行上下文
            product_id: 商品 ID
            name: 商品名称
            category_id: 分类 ID
            price: 价格
            description: 商品描述
            stock_quantity: 库存数量
            
        Returns:
            ToolResult: 操作结果
        """
        if not product_id:
            return ToolResult(
                success=False,
                error="缺少商品 ID",
                message="更新商品时必须提供商品 ID（product_id）",
            )
        
        json_data: Dict[str, Any] = {}
        if name:
            json_data["name"] = name
        if category_id:
            json_data["categoryId"] = category_id
        if price is not None:
            json_data["basePrice"] = price
        if description:
            json_data["description"] = description
        if stock_quantity is not None:
            json_data["stock"] = stock_quantity
        if processing_item_ids is not None:
            json_data["processingItems"] = processing_item_ids
        
        if not json_data:
            return ToolResult(
                success=False,
                error="没有需要更新的字段",
                message="请至少提供一个需要更新的字段",
            )
        
        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/products/{product_id}",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"更新商品失败：{error_msg}",
            )
        
        logger.info(
            f"Product updated: id={product_id}, fields={list(json_data.keys())}, "
            f"tenant={context.tenant_id}, user={context.user_id}"
        )
        
        return ToolResult(
            success=True,
            data={"product_id": product_id, "updated_fields": list(json_data.keys())},
            message=f"商品信息已更新",
        )
    
    async def _toggle_status(
        self,
        context: ToolContext,
        product_id: Optional[str],
        status: Optional[str],
    ) -> ToolResult:
        """上下架商品
        
        Args:
            context: Tool 执行上下文
            product_id: 商品 ID
            status: 目标状态
            
        Returns:
            ToolResult: 操作结果
        """
        if not product_id:
            return ToolResult(
                success=False,
                error="缺少商品 ID",
                message="上下架操作时必须提供商品 ID（product_id）",
            )
        
        if not status or status not in VALID_PRODUCT_STATUSES:
            return ToolResult(
                success=False,
                error=f"无效的商品状态: {status}",
                message=f"请提供有效的状态值：{', '.join(VALID_PRODUCT_STATUSES)}",
            )
        
        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/products/{product_id}/status",
            json_data={"status": status},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "操作失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"商品状态更新失败：{error_msg}",
            )
        
        status_text = "上架" if status == "on_sale" else "下架"
        logger.info(
            f"Product status toggled: id={product_id}, status={status}, "
            f"tenant={context.tenant_id}, user={context.user_id}"
        )
        
        return ToolResult(
            success=True,
            data={"product_id": product_id, "status": status},
            message=f"商品已{status_text}",
        )
