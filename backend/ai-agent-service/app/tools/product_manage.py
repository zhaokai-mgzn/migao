"""
AI 智能客服系统 - 商品管理 Tool

创建、更新、上下架商品，管理加工项。
Agent BFF: create/update 走 /api/admin/agent/products, toggle_status 走原端点。
ID 解析、默认值填充、字段规范化由 Java Agent 端点负责。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


VALID_ACTIONS = {"create", "update", "toggle_status", "manage_processing_items"}
VALID_PRODUCT_STATUSES = {"on_sale", "off_sale"}


class ProductManageTool(BaseTool):
    """商品管理 Tool"""

    name = "product_manage"
    description = (
        "【触发】创建/修改/上下架商品。create 必填 name+price，收集→确认→执行。update 需 product_id。"
        "toggle_status 需 product_id+status。manage_processing_items 用于增删加工项。"
        "【标注】WRITE|DESTRUCTIVE"
    )

    allowed_roles = ["admin", "agent", "tenant_admin"]
    read_only = False
    destructive = True
    idempotent = False

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "update", "toggle_status", "manage_processing_items"],
                "description": "操作类型",
            },
            "product_id": {
                "type": "string",
                "description": "商品ID。update / toggle_status / manage_processing_items 时必填",
            },
            "name": {"type": "string", "description": "商品名称。create 时必填"},
            "category_id": {
                "type": "string",
                "description": "分类ID。支持 UUID / 分类名称 / UUID 前缀，服务端自动解析",
            },
            "price": {"type": "number", "description": "价格（元）", "examples": [100.0, 23.8]},
            "stock_quantity": {"type": "integer", "description": "库存数量", "examples": [500]},
            "description": {"type": "string", "description": "商品描述文本"},
            "brand": {"type": "string", "description": "品牌名称"},
            "unit": {"type": "string", "description": "计价单位，空则按品类默认"},
            "pricing_type": {"type": "string", "description": "计价方式，空则按品类默认"},
            "sku_code": {"type": "string", "description": "商品货号/SKU编码，空则自动生成"},
            "status": {
                "type": "string",
                "enum": ["on_sale", "off_sale"],
                "description": "商品状态",
            },
            "colors": {
                "type": "array", "items": {"type": "string"},
                "description": "颜色数组。传颜色名列表，服务端自动构建颜色对象",
            },
            "selling_methods": {
                "type": "array", "items": {"type": "string"},
                "description": "售卖方式数组。支持中文（散剪/整卷）或英文（bulk_cut/full_roll）",
            },
            "door_widths": {
                "type": "array", "items": {"type": "string"},
                "description": "门幅数组。例：['2.8米','3.2米']",
            },
            "images": {"type": "array", "items": {"type": "string"}, "description": "商品主图URL数组"},
            "detail_images": {"type": "array", "items": {"type": "string"}, "description": "商品详情图URL数组"},
            "processing_item_ids": {
                "type": "array", "items": {"type": "string"},
                "description": "加工项ID数组。支持 UUID / 加工项名称 / 序号，服务端自动解析",
            },
            "processing_item_configs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "processingItemId": {"type": "string", "description": "加工项ID（支持名称/序号）"},
                        "customPrice": {"type": "number", "description": "自定义价格"},
                    },
                },
                "description": "加工项配置数组（含自定义价格）",
            },
            "specifications": {
                "type": "object",
                "description": "规格对象。可含 weight(克重) material(材质) craft(工艺) style(风格) pattern(图案) function(功能)",
            },
            # manage_processing_items 专用参数
            "processing_item_action": {
                "type": "string", "enum": ["add", "remove"],
                "description": "加工项操作类型。manage_processing_items 时必填",
            },
            "skus": {
                "type": "array", "items": {"type": "object"},
                "description": "SKU数组。系统自动生成，一般不需要手动传",
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
        colors: Optional[list] = None,
        selling_methods: Optional[list] = None,
        door_widths: Optional[list] = None,
        sku_code: Optional[str] = None,
        skus: Optional[list] = None,
        processing_item_configs: Optional[list] = None,
        pricing_type: Optional[str] = None,
        processing_item_action: Optional[str] = None,
    ) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(
                success=False, error="权限不足",
                message="您没有权限执行商品管理操作",
                suggestion="请联系管理员获取权限",
            )

        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False, error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
            )

        try:
            if action == "create":
                return await self._create_product(context, name, category_id, price,
                    description, stock_quantity, processing_item_ids, brand, images,
                    detail_images, specifications, unit, colors, selling_methods,
                    door_widths, sku_code, skus, processing_item_configs, pricing_type, status)
            elif action == "update":
                return await self._update_product(context, product_id, name, category_id,
                    price, description, stock_quantity, brand, images, detail_images,
                    specifications, unit, colors, pricing_type, selling_methods,
                    door_widths, sku_code)
            elif action == "toggle_status":
                return await self._toggle_status(context, product_id, status)
            elif action == "manage_processing_items":
                return await self._manage_processing_items(
                    context, product_id, processing_item_action, processing_item_ids)
            else:
                return ToolResult(success=False, error=f"未知操作: {action}")

        except Exception as e:
            logger.error(f"Product manage error: action={action}, error={e}")
            return ToolResult(
                success=False, error="tool_execution_failed",
                message="商品操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    # ── Agent BFF: CREATE ──

    async def _create_product(self, context, name, category_id, price, description,
                               stock_quantity, processing_item_ids, brand, images,
                               detail_images, specifications, unit, colors,
                               selling_methods, door_widths, sku_code, skus,
                               processing_item_configs, pricing_type, status) -> ToolResult:
        if not name:
            return ToolResult(
                success=False, error="缺少商品名称",
                message="创建商品时必须提供商品名称（name）",
            )

        json_data: Dict[str, Any] = {"name": name}
        if category_id: json_data["categoryId"] = category_id
        if price is not None: json_data["basePrice"] = price
        if description: json_data["description"] = description
        if stock_quantity is not None: json_data["stock"] = int(stock_quantity)
        if processing_item_ids: json_data["processingItemIds"] = processing_item_ids
        if processing_item_configs: json_data["processingItemConfigs"] = processing_item_configs
        if brand: json_data["brand"] = brand
        if images: json_data["images"] = images
        if detail_images: json_data["detailImages"] = detail_images
        if colors: json_data["colors"] = colors
        if selling_methods: json_data["sellingMethods"] = selling_methods
        if door_widths: json_data["doorWidths"] = door_widths
        if skus: json_data["skus"] = skus
        if sku_code: json_data["skuCode"] = sku_code
        if specifications: json_data["specifications"] = specifications
        if unit: json_data["unit"] = unit
        if pricing_type: json_data["pricingType"] = pricing_type
        if status: json_data["status"] = status

        logger.info(f"[product_manage] Agent create: name={name}")
        client = get_admin_api_client()
        response = await client.post("/api/admin/agent/products",
            json_data=json_data, tenant_id=context.tenant_id, user_id=context.user_id)

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = error_info.get("message", "创建失败") if isinstance(error_info, dict) else str(error_info)
            suggestion = response.get("suggestion", "")
            return ToolResult(
                success=False, error=error_msg,
                message=f"创建商品失败：{error_msg}",
                suggestion=suggestion or "请检查必填字段是否完整",
            )

        product_data = response.get("data", {})
        product_id = product_data.get("id")
        warnings = response.get("warnings", [])

        success_msg = f"商品【{name}】创建成功"
        if warnings:
            success_msg += "\n\n⚠️ 提示：" + "\n".join(warnings)

        logger.info(f"Product created via Agent: id={product_id}, name={name}")
        return ToolResult(
            success=True,
            data={"product_id": product_id, "name": name},
            message=success_msg,
        )

    # ── Agent BFF: UPDATE (PATCH, partial) ──

    async def _update_product(self, context, product_id, name, category_id, price,
                               description, stock_quantity, brand, images, detail_images,
                               specifications, unit, colors, pricing_type, selling_methods,
                               door_widths, sku_code) -> ToolResult:
        if not product_id:
            return ToolResult(
                success=False, error="缺少商品 ID",
                message="更新商品时必须提供商品 ID（product_id）",
            )

        # 只传非 None 字段（null = 不修改，Java Agent PATCH 端点自动处理）
        json_data: Dict[str, Any] = {}
        if name is not None: json_data["name"] = name
        if category_id is not None: json_data["categoryId"] = category_id
        if price is not None: json_data["basePrice"] = price
        if description is not None: json_data["description"] = description
        if stock_quantity is not None: json_data["stock"] = int(stock_quantity)
        if brand is not None: json_data["brand"] = brand
        if images is not None: json_data["images"] = images
        if detail_images is not None: json_data["detailImages"] = detail_images
        if specifications is not None: json_data["specifications"] = specifications
        if unit is not None: json_data["unit"] = unit
        if pricing_type is not None: json_data["pricingType"] = pricing_type
        if colors is not None: json_data["colors"] = colors
        if selling_methods is not None: json_data["sellingMethods"] = selling_methods
        if door_widths is not None: json_data["doorWidths"] = door_widths
        if sku_code is not None: json_data["skuCode"] = sku_code

        if not json_data:
            return ToolResult(
                success=False, error="没有需要更新的字段",
                message="请至少提供一个需要更新的字段",
            )

        logger.info(f"[product_manage] Agent PATCH update: id={product_id}, fields={list(json_data.keys())}")
        client = get_admin_api_client()
        response = await client.patch(f"/api/admin/agent/products/{product_id}",
            json_data=json_data, tenant_id=context.tenant_id, user_id=context.user_id)

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = error_info.get("message", "更新失败") if isinstance(error_info, dict) else str(error_info)
            return ToolResult(
                success=False, error=error_msg,
                message=f"更新商品失败：{error_msg}",
            )

        logger.info(f"Product updated via Agent: id={product_id}, fields={list(json_data.keys())}")
        return ToolResult(
            success=True,
            data={"product_id": product_id, "updated_fields": list(json_data.keys())},
            message="商品信息已更新",
        )

    # ── Agent BFF: PROCESSING ITEMS (add/remove) ──

    async def _manage_processing_items(self, context, product_id, processing_item_action,
                                        processing_item_ids) -> ToolResult:
        if not product_id:
            return ToolResult(success=False, error="缺少商品 ID", message="请提供商品 ID")
        if processing_item_action not in ("add", "remove"):
            return ToolResult(
                success=False, error="无效的加工项操作",
                message="processing_item_action 必须为 add 或 remove",
            )
        if not processing_item_ids:
            return ToolResult(success=False, error="缺少加工项 ID", message="请提供加工项 ID 列表")

        logger.info(f"[product_manage] Agent processing items: {processing_item_action} on {product_id}")
        client = get_admin_api_client()
        response = await client.patch(
            f"/api/admin/agent/products/{product_id}/processing-items",
            json_data={"action": processing_item_action, "itemIds": processing_item_ids},
            tenant_id=context.tenant_id, user_id=context.user_id)

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = error_info.get("message", "操作失败") if isinstance(error_info, dict) else str(error_info)
            return ToolResult(success=False, error=error_msg, message=f"加工项操作失败：{error_msg}")

        items = response.get("data", [])
        warnings = response.get("warnings", [])
        action_text = "添加" if processing_item_action == "add" else "删除"
        msg = f"加工项已{action_text}，当前共 {len(items) if isinstance(items, list) else 0} 个加工项"
        if warnings:
            msg += "\n\n⚠️ 提示：" + "\n".join(warnings)

        return ToolResult(success=True, data={"processing_items": items}, message=msg)

    # ── TOGGLE STATUS (原端点，无变化) ──

    async def _toggle_status(self, context, product_id, status) -> ToolResult:
        if not product_id:
            return ToolResult(success=False, error="缺少商品 ID", message="请提供商品 ID（product_id）")
        if not status or status not in VALID_PRODUCT_STATUSES:
            return ToolResult(
                success=False, error=f"无效的商品状态: {status}",
                message=f"请提供有效的状态值：{', '.join(VALID_PRODUCT_STATUSES)}",
            )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/products/{product_id}/status",
            json_data={"status": status},
            tenant_id=context.tenant_id, user_id=context.user_id)

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "操作失败")
            return ToolResult(success=False, error=error_msg, message=f"商品状态更新失败：{error_msg}")

        status_text = "上架" if status == "on_sale" else "下架"
        logger.info(f"Product status toggled: id={product_id}, status={status}")
        return ToolResult(
            success=True,
            data={"product_id": product_id, "status": status},
            message=f"商品已{status_text}",
        )
