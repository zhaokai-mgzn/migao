"""
AI 智能客服系统 - 商品管理 Tool

创建、更新、上下架商品。
Agent BFF: create/update 走 /api/admin/agent/products, toggle_status 走原端点。
ID 解析、默认值填充、字段规范化由 Java Agent 端点负责。

⚠️ 后端契约：create 的 payload 键必须 ∈ `dto/agent/AgentProductCreateRequest` 字段
（name/categoryId/basePrice/skuCode/description/brand/unit/pricingType/stock/status/
images/detailImages/colors/sellingMethods/doorWidths/specifications/stockDeductionMode/
allowReturnRestock）—— Spring 静默忽略未知字段，下发 DTO 没有的键 = 无声丢数据 +
工具报成功（工具审计 A4：`skus` 因此被删）。
⚠️ issue #4371：`processingItemIds`/`processingItemConfigs` 已随「商品↔加工项解耦」从
DTO 与本工具一并移除 —— 加工项是**店铺级目录**（`processing_item_query`），不再挂在商品上。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


VALID_ACTIONS = {"create", "update", "toggle_status"}
VALID_PRODUCT_STATUSES = {"on_sale", "off_sale"}


class ProductManageTool(BaseTool):
    """商品管理 Tool"""

    name = "product_manage"
    description = (
        "【触发】创建/修改/上下架商品。create 必填 name+price，收集→确认→执行。"
        "update 需 product_id（支持名称/序号/UUID，服务端自动解析），只传要改的字段。"
        "toggle_status 需 product_id+status(on_sale/off_sale)。"
        "【标注】WRITE|DESTRUCTIVE"
        "【铁律】用户明确要求写操作（禁用/调整/删除/上下架/重置等**单步写**）时：先查必要信息拿真实 ID → 展示操作预览 + 确认卡 → 用户确认后立即调用写工具执行，禁止只查询/展示列表就停（HR-003/PP-006/PR-005 实拍：agent 只 list/query 不执行写工具判失败）。"
        "【铁律】写工具返回 success 后复查若显示旧值：优先按写结果向用户如实说明「已写入，查询显示旧值可能为读取延迟」，禁止断言「未落库」、禁止建议用户去后台手动操作（#3899）。"
        "【铁律】状态变更（上/下架）必须用 action=toggle_status 单独调用：update 不处理 status（状态走状态机端点，Java updateProduct 刻意恢复原状态），把 status 放进 update 会被显式拒绝（#3899）。"
        "【create 流程】action=create 是**多步引导流程**（收集 → 分类确认 → 货号 → 汇总确认卡 → 用户确认后才执行 create），"
        "**禁止抢跑**：基本信息未收齐或未发确认卡就执行 create 属禁止行为。"
        "**加工项与商品无关**（issue #4371）：加工项是店铺级目录，建品**不需要**询问/关联加工项，"
        "也不要把加工项写进本工具的 create 参数（本工具没有该参数）。"
    )

    # 权限码（admin-api 目录）：商品写（create/update/toggle_status）取写码 `product:create`
    # （ProductController 的 POST/PUT/DELETE 都是 product:create）。
    required_permissions = ["product:create"]
    read_only = False
    destructive = True
    idempotent = False

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                # enum 必须 ⊆ VALID_ACTIONS：留在 enum 里的值必须是运行时真能跑的分支
                # （工具审计 B1）
                "enum": ["create", "update", "toggle_status"],
                "description": "操作类型：create（创建商品，必填 name+price）/ update（修改已有商品字段，必传 product_id 且只传要改的字段）/ toggle_status（上架或下架，必传 product_id+status(on_sale/off_sale)）",
            },
            "product_id": {
                "type": "string",
                "description": "商品UUID（必填且必须传 32 位 UUID）。create 不需要。其他 action 必须先通过 product_query 查出真实 UUID 再传入，禁止传商品名称",
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
                # ⚠️ 这是**有意的权限边界，不是缺口**（issue #3686，有意为之请勿"补齐"）：
                # 后端 ProductService.STATUS_TRANSITIONS 有 4 值（draft/under_review/on_sale/off_sale），
                # 但 Agent 只负责**上下架**；草稿创建与送审（draft → under_review → on_sale）
                # 是 admin-web 后台的商品运营流程，需人工编辑资料并承担审核语义。
                # 给 Agent 放开这两值 = 让对话直接跳过审核门禁（越权），违反最小权限。
                # 若确实需要 Agent 送审，须先补权限设计 + 审核责任归属，再改本枚举。
                "description": "商品状态：仅 on_sale(上架) / off_sale(下架)。"
                               "草稿(draft)与送审(under_review)是后台人工流程，Agent 无权限——这是有意的权限边界",
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
            "specifications": {
                "type": "object",
                "description": "规格对象。可含 weight(克重) material(材质) craft(工艺) style(风格) pattern(图案) function(功能)",
            },
            "allow_return_restock": {
                "type": "boolean",
                "description": "退货后是否回补库存（可选，create 时使用，issue #2991）：true=退货回补/可再售，false=定制商品退货不回补。缺省 false",
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
        pricing_type: Optional[str] = None,
        allow_return_restock: Optional[bool] = None,
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
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )

        try:
            if action == "create":
                return await self._create_product(context, name, category_id, price,
                    description, stock_quantity, brand, images,
                    detail_images, specifications, unit, colors, selling_methods,
                    door_widths, sku_code, pricing_type,
                    status, allow_return_restock)
            elif action == "update":
                return await self._update_product(context, product_id, name, category_id,
                    price, description, stock_quantity, brand, images, detail_images,
                    specifications, unit, colors, pricing_type, selling_methods,
                    door_widths, sku_code, status)
            elif action == "toggle_status":
                return await self._toggle_status(context, product_id, status)
            else:
                return ToolResult(success=False,
                    error=f"未知操作: {action}",
                    suggestion="操作类型不在支持范围内，请从工具说明的可选 action 中重新选择一个后重试",
                )

        except Exception as e:
            logger.error(f"Product manage error: action={action}, error={e}", exc_info=True)
            return ToolResult(
                success=False, error="tool_execution_failed",
                message="商品操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    # ── Agent BFF: CREATE ──

    async def _create_product(self, context, name, category_id, price, description,
                               stock_quantity, brand, images,
                               detail_images, specifications, unit, colors,
                               selling_methods, door_widths, sku_code,
                               pricing_type, status,
                               allow_return_restock=None) -> ToolResult:
        if not name:
            return ToolResult(
                success=False, error="缺少商品名称",
                message="创建商品时必须提供商品名称（name）",
                suggestion="缺少商品名称 name，请向用户询问商品名称后重试",
            )

        json_data: Dict[str, Any] = {"name": name}
        # 空分类不下发（#3665 冒烟 B1）：'' 会让后端 category_id 违 FK；用 strip 兼容纯空白
        if category_id and category_id.strip(): json_data["categoryId"] = category_id
        if price is not None: json_data["basePrice"] = price
        if description: json_data["description"] = description
        if stock_quantity is not None: json_data["stock"] = int(stock_quantity)
        if brand: json_data["brand"] = brand
        if images: json_data["images"] = images
        if detail_images: json_data["detailImages"] = detail_images
        if colors: json_data["colors"] = colors
        if selling_methods: json_data["sellingMethods"] = selling_methods
        if door_widths: json_data["doorWidths"] = door_widths
        if sku_code: json_data["skuCode"] = sku_code
        if specifications: json_data["specifications"] = specifications
        if unit: json_data["unit"] = unit
        if pricing_type: json_data["pricingType"] = pricing_type
        if status: json_data["status"] = status
        # allow_return_restock 透传（issue #2991，建品时设置退货回补开关）
        if allow_return_restock is not None:
            json_data["allowReturnRestock"] = allow_return_restock

        logger.info(f"[product_manage] Agent create: name={name}")
        client = get_admin_api_client()
        response = await client.post("/api/admin/agent/products",
            json_data=json_data, tenant_id=context.tenant_id, user_id=context.user_id)

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = error_info.get("message", "创建失败") if isinstance(error_info, dict) else str(error_info)
            suggestion = response.get("suggestion", "")
            return admin_api_failure(response,
                error=error_msg,
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
                               door_widths, sku_code, status=None) -> ToolResult:
        if not product_id:
            return ToolResult(
                success=False, error="缺少商品 ID",
                message="更新商品时必须提供商品 ID（product_id）",
                suggestion="缺少 product_id，请先用 product_search 查到该商品后重试",
            )

        # issue #3899：update 不处理 status——Java updateProduct 刻意恢复原状态，状态只能走
        # PUT /api/admin/products/{id}/status（updateProductStatus 状态机端点，见 _toggle_status）。
        # 静默忽略会让 LLM 收到 success 但 status 没变 → 复查对不上 → 误报「未生效，去后台手动操作」。
        # 显式拒绝并引导走 toggle_status，禁止半成功写入。
        if status is not None:
            return ToolResult(
                success=False,
                error="status 请用 action=toggle_status 单独调用（状态变更走状态机端点，update 不处理 status）",
                message="商品状态变更未执行：update 不处理 status，请改用 action=toggle_status 单独调用（商品其他字段未受影响）",
                suggestion="product_manage(action=toggle_status, product_id=<id>, status=on_sale/off_sale)",
            )

        # 只传非 None 字段（null = 不修改，Java Agent PATCH 端点自动处理）
        json_data: Dict[str, Any] = {}
        if name is not None: json_data["name"] = name
        # 空分类不下发（#3665 冒烟 B1）：与 create 真值判断同口径——'' 会被后端
        # resolveCategoryId('') → null → 422「无法找到匹配的分类」，纯空白同理
        if category_id is not None and category_id.strip(): json_data["categoryId"] = category_id
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
                suggestion="没有需要更新的字段，请向用户确认要修改哪一项（价格/库存/名称/状态等）后重试",
            )

        logger.info(f"[product_manage] Agent PATCH update: id={product_id}, fields={list(json_data.keys())}")
        client = get_admin_api_client()
        response = await client.patch(f"/api/admin/agent/products/{product_id}",
            json_data=json_data, tenant_id=context.tenant_id, user_id=context.user_id)

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = error_info.get("message", "更新失败") if isinstance(error_info, dict) else str(error_info)
            return admin_api_failure(response,
                error=error_msg,
                message=f"更新商品失败：{error_msg}",
                suggestion="请先用 product_detail 读取该商品当前信息，核对字段后重新提交更新",
            )

        logger.info(f"Product updated via Agent: id={product_id}, fields={list(json_data.keys())}")
        return ToolResult(
            success=True,
            data={"product_id": product_id, "updated_fields": list(json_data.keys())},
            message="商品信息已更新",
        )

    # ── TOGGLE STATUS (原端点，无变化) ──

    async def _toggle_status(self, context, product_id, status) -> ToolResult:
        if not product_id:
            return ToolResult(success=False,
                error="缺少商品 ID",
                message="请提供商品 ID（product_id）",
                suggestion="商品状态只支持错误提示中列出的取值，请按用户意图改传其中之一后重试",
            )
        if not status or status not in VALID_PRODUCT_STATUSES:
            return ToolResult(
                success=False, error=f"无效的商品状态: {status}",
                message=f"请提供有效的状态值：{', '.join(VALID_PRODUCT_STATUSES)}",
                suggestion="缺少 product_id，请先用 product_search 查到该商品后重试",
            )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/products/{product_id}/status",
            json_data={"status": status},
            tenant_id=context.tenant_id, user_id=context.user_id)

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "操作失败")
            return admin_api_failure(response, error=error_msg,
                message=f"商品状态更新失败：{error_msg}",
                suggestion="请先用 product_detail 确认该商品当前状态（下架商品不可直接改状态），再重新提交",
            )

        status_text = "上架" if status == "on_sale" else "下架"
        logger.info(f"Product status toggled: id={product_id}, status={status}")
        return ToolResult(
            success=True,
            data={"product_id": product_id, "status": status},
            message=f"商品已{status_text}",
        )
