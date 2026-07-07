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
def _split_str(val):
    import re
    return [p.strip() for p in re.split(r"[,，、\s]+|和|与", val) if p.strip()]

# 中文售卖方式 → admin-api 期望值
_SELLING_TRANSLATE = {"散剪": "bulk_cut", "整卷": "full_roll", "按片": "per_piece", "定高": "fixed_height", "买通": "buy_through"}

def _normalize_array(val):
    """LLM 可能传 JSON字符串/对象/单项 → 统一为 list"""
    if val is None: return None
    if isinstance(val, str):
        import json as _json
        try: return _json.loads(val) if val.strip().startswith("[") else [val]
        except (ValueError, _json.JSONDecodeError): return [v.strip() for v in val.replace("，",",").split(",") if v.strip()]
    if isinstance(val, dict):
        if "item" in val: return [val["item"]]
        return list(val.values())
    if isinstance(val, list): return val
    return [val]

def _normalize_number(val):
    """LLM 可能传字符串 "66" → 转为数字"""
    if val is None: return None
    if isinstance(val, (int, float)): return val
    if isinstance(val, str):
        try: return float(val) if "." in val else int(val)
        except (ValueError, TypeError): return val
    return val


def _auto_generate_sku_code(name: str) -> str:
    """LLM 没传货号时自动生成，对抗编程——不依赖 LLM 记得传 sku_code

    策略：
    1. 提取名称中的英文/数字（如 "YUUR 2699" → "YUUR2699"）
    2. 都没有 → 用名称 MD5 前 8 位
    """
    import re, hashlib
    # 提取名称中的英文和数字
    alnum = ''.join(re.findall(r'[A-Za-z0-9]', name))
    if len(alnum) >= 3:
        return alnum[:12].upper()
    # 拼音首字母需要第三方库，这里用 MD5 兜底
    return hashlib.md5(name.encode()).hexdigest()[:8].upper()

async def _resolve_category_id(category_id, context):
    """从分类树按名称匹配解析为真实UUID。不信任LLM直接传的值（可能被截断/编造）。"""
    if not category_id: return category_id
    try:
        from app.utils.http_client import get_admin_api_client
        client = get_admin_api_client()
        resp = await client.get("/api/admin/categories", tenant_id=context.tenant_id, user_id=context.user_id)
        cats = resp.get("data", resp) if isinstance(resp, dict) else resp
        cat_list = cats if isinstance(cats, list) else cats.get("items", []) if isinstance(cats, dict) else []

        # 精确匹配UUID
        for c in cat_list:
            if isinstance(c, dict) and c.get("id") == category_id:
                return category_id
            for child in c.get("children", []) if isinstance(c, dict) else []:
                if isinstance(child, dict) and child.get("id") == category_id:
                    return category_id

        # UUID不匹配 → 按名称匹配 → 按UUID前缀匹配（LLM可能截断UUID）
        for c in cat_list:
            if isinstance(c, dict) and c.get("name") == category_id:
                return c["id"]
            for child in c.get("children", []) if isinstance(c, dict) else []:
                if isinstance(child, dict) and child.get("name") == category_id:
                    return child["id"]
        # 前缀匹配：LLM传的截断UUID "88b6c50fbcb2..." 匹配真实 "88b6c50fbc269..."
        if len(category_id) >= 8:
            for c in cat_list:
                if isinstance(c, dict) and c.get("id","").startswith(category_id[:16]):
                    logger.info(f"[product_manage] Resolved truncated UUID {category_id[:20]}... → {c['id']}")
                    return c["id"]
                for child in c.get("children", []) if isinstance(c, dict) else []:
                    if isinstance(child, dict) and child.get("id","").startswith(category_id[:16]):
                        logger.info(f"[product_manage] Resolved truncated UUID {category_id[:20]}... → {child['id']}")
                        return child["id"]

        # 全部匹配失败 → 返回 None，由调用方决定如何处理
        available_names = []
        for c in cat_list:
            if isinstance(c, dict):
                available_names.append(f"{c.get('name', '?')} (id={c.get('id', '?')[:8]}...)")
        logger.warning(
            f"[product_manage] Could not resolve category_id: {category_id}. "
            f"Available categories: {available_names[:5]}"
        )
        return None
    except Exception as e:
        logger.warning(f"[product_manage] Category resolution failed: {e}")
    return None


async def _resolve_processing_item_ids(ids, context) -> list:
    """解析加工项 ID：将 LLM 可能传的名称/UUID 前缀转为真实 UUID。

    加工项名称如"罗马杆环安装"会被解析为 "pi_xxxxx"。
    序号如 "1" "4" "7" 会被解析为列表中对应位置的记录（1-based）。

    返回 (resolved, unresolved) 元组 — 让调用方知道哪些 ID 未解析。
    """
    if not ids:
        return ids, []
    ids = _normalize_array(ids)
    try:
        from app.utils.http_client import get_admin_api_client
        client = get_admin_api_client()
        resp = await client.get("/api/admin/processing-items",
            params={"page": 1, "size": 200},
            tenant_id=context.tenant_id,
            user_id=context.user_id)
        items = []
        if isinstance(resp, dict):
            data = resp.get("data", resp)
            items = data.get("items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

        resolved = []
        unresolved = []
        for pid in ids:
            pid_str = str(pid).strip()
            # 兼容 auto-interact 格式: "pi_1234|加工项名" → 提取 UUID 部分
            if "|" in pid_str:
                pid_str = pid_str.split("|")[0].strip()
            found = None

            # 1. 纯数字 → 按列表位置匹配（1-based 序号）
            if pid_str.isdigit():
                idx = int(pid_str) - 1  # 用户看到的 1-based 序号
                if 0 <= idx < len(items) and isinstance(items[idx], dict):
                    found = items[idx].get("id")
                    if found:
                        logger.info(
                            f"[product_manage] Resolved row number {pid_str} → "
                            f"{items[idx].get('name', '?')} ({found[:20]}...)"
                        )

            # 2. 精确 UUID 匹配
            if not found:
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if item.get("id") == pid_str:
                        found = item["id"]
                        break
                    # 名称匹配
                    if item.get("name") == pid_str:
                        found = item["id"]
                        break
                    # UUID 前缀匹配（LLM 可能截断）
                    if len(pid_str) >= 8 and item.get("id", "").startswith(pid_str[:16]):
                        found = item["id"]
                        break

            if found:
                resolved.append(found)
            else:
                logger.warning(f"[product_manage] Could not resolve processing_item_id: {pid_str!r}")
                unresolved.append(pid_str)
                # 如果看起来像 UUID，仍然尝试使用（可能是正确的但不在此 tenant 的列表中）
                if len(pid_str) >= 20:
                    resolved.append(pid_str)
                    unresolved.remove(pid_str)

        if resolved:
            logger.info(f"[product_manage] Resolved processing_item_ids: {ids} → {resolved}")
        if unresolved:
            logger.warning(f"[product_manage] UNRESOLVED processing_item_ids: {unresolved}")
        return resolved, unresolved
    except Exception as e:
        logger.warning(f"[product_manage] Processing item resolution failed: {e}")
        return ids, []

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
        "【触发】创建/修改/上下架商品。create 必填 name+price，收集→确认→执行。update 需 product_id。toggle_status 需 product_id+status。【标注】WRITE|DESTRUCTIVE"
    )
    
    # admin、agent、tenant_admin 可使用
    required_permissions = ["product:create"]
    allowed_roles = ["admin", "agent", "tenant_admin"]

    read_only = False
    destructive = True   # 可删除商品、上下架
    idempotent = False   # 创建/删除非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string", "enum": ["create", "update", "toggle_status"],
                "description": "操作类型",
            },
            "product_id": {
                "type": "string",
                "description": "商品ID。update 或 toggle_status 时必填",
            },
            "name": {
                "type": "string",
                "description": "商品名称。create 时必填。如'遮光窗帘'",
            },
            "category_id": {
                "type": "string",
                "description": "分类ID。从 category_manage(tree) 返回数据中取对应分类的 id 字段值",
                "examples": ["88b6c50fbc2695fd0fca51705e957d17"],
            },
            "price": {
                "type": "number",
                "description": "价格（元），纯数字",
                "examples": [100.0, 23.8],
            },
            "stock_quantity": {
                "type": "integer",
                "description": "库存数量，纯整数",
                "examples": [500],
            },
            "description": {
                "type": "string",
                "description": "商品描述文本",
            },
            "brand": {
                "type": "string",
                "description": "品牌名称",
            },
            "unit": {
                "type": "string",
                "enum": ["米", "件", "套", "个", "卷", "片", "平方米"],
                "description": "计价单位",
            },
            "pricing_type": {
                "type": "string",
                "enum": ["per_meter", "per_piece", "per_area", "fixed"],
                "description": "计价方式",
            },
            "sku_code": {
                "type": "string",
                "description": "商品货号/SKU编码",
            },
            "status": {
                "type": "string",
                "enum": ["on_sale", "off_sale"],
                "description": "商品状态。create 时传入控制初始状态，默认 on_sale；toggle_status 时必填",
            },
            "colors": {
                "type": "array",
                "items": {"type": "string"},
                "description": "颜色数组。传颜色名列表",
                "examples": [["米白色", "浅灰色", "深蓝色"]],
            },
            "selling_methods": {
                "type": "array",
                "items": {"type": "string", "enum": ["散剪", "整卷", "按片", "定高", "买通"]},
                "description": "售卖方式数组",
                "examples": [["散剪", "整卷"]],
            },
            "door_widths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "门幅数组。例：['2.8米','3.2米']",
            },
            "images": {
                "type": "array",
                "items": {"type": "string"},
                "description": "商品主图URL数组",
            },
            "detail_images": {
                "type": "array",
                "items": {"type": "string"},
                "description": "商品详情图URL数组",
            },
            "processing_item_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "加工项ID数组。先调 processing_item_query 获取可用列表让用户选，收集选中的ID后传入",
            },
            "specifications": {
                "type": "object",
                "description": "规格对象。可含 weight(克重) material(材质) craft(工艺) style(风格) pattern(图案) function(功能)",
            },
            "skus": {
                "type": "array",
                "items": {"type": "object"},
                "description": "SKU数组。系统根据颜色×售卖方式×门幅自动生成，不需要手动传",
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
                suggestion="请联系管理员获取执行商品管理操作权限",
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
                    specifications, unit, colors, selling_methods, door_widths, sku_code, skus, processing_item_configs, pricing_type, status
                )
            elif action == "update":
                return await self._update_product(
                    context, product_id, name, category_id, price, description, stock_quantity,
                    processing_item_ids, brand, images, detail_images, specifications, unit,
                    colors, pricing_type, selling_methods, door_widths, sku_code, skus, processing_item_configs
                )
            elif action == "toggle_status":
                return await self._toggle_status(context, product_id, status)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )
                
        except Exception as e:
            logger.error(f"Product manage error: action={action}, product_id={product_id}, error={e}")
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="商品操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
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
        colors: Optional[list] = None,
        selling_methods: Optional[list] = None,
        door_widths: Optional[list] = None,
        sku_code: Optional[str] = None,
        skus: Optional[list] = None,
        processing_item_configs: Optional[list] = None,
        pricing_type: Optional[str] = None,
        status: Optional[str] = None,
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
        
        # AI 友好：自动规范化 LLM 可能传错的参数
        original_category_id = category_id
        category_id = await _resolve_category_id(category_id, context) if category_id else None
        # 如果 LLM 传了 category_id 但解析失败，立即返回错误引导 LLM 重新查询分类树
        if original_category_id and not category_id:
            return ToolResult(
                success=False,
                error=f"分类ID无效: {original_category_id}",
                message=f"无法找到匹配的分类（ID: {original_category_id}），请使用 category_manage tree 查询正确的分类ID",
                suggestion="请先调用 category_manage(action='tree') 获取分类树，然后用正确的分类ID重试",
            )
        price = _normalize_number(price)
        stock_quantity = _normalize_number(stock_quantity)
        colors = _normalize_array(colors) if colors is not None else None
        selling_methods = _normalize_array(selling_methods) if selling_methods is not None else None

        json_data: Dict[str, Any] = {"name": name}
        if category_id:
            json_data["categoryId"] = category_id
        if price is not None:
            json_data["basePrice"] = float(price)  # admin-api 直接用元
        if description:
            json_data["description"] = description
        if stock_quantity is not None:
            json_data["stock"] = int(stock_quantity)
        processing_warnings = []
        if processing_item_ids:
            processing_item_ids, unresolved_ids = await _resolve_processing_item_ids(processing_item_ids, context)
            if unresolved_ids:
                processing_warnings.append(
                    f"以下加工项ID无法解析: {unresolved_ids}。"
                    f"请使用 processing_item_query 查询真实ID后重试"
                )
        if processing_item_ids:
            if processing_item_configs:
                json_data["processingItemConfigs"] = processing_item_configs
            elif processing_item_ids:
                json_data["processingItemConfigs"] = [{"processingItemId": pid} for pid in processing_item_ids]
        if brand:
            json_data["brand"] = brand
        if images:
            json_data["images"] = list(images)
        if "stockDeductionMode" not in json_data:
            json_data["stockDeductionMode"] = "on_order"
        if detail_images:
            json_data["detailImages"] = list(detail_images)
        if colors:
            normalized = []
            for c in colors:
                if isinstance(c, str):
                    normalized.append({"colorName": c})
                elif isinstance(c, dict):
                    nc = {"colorName": c.get("colorName", c.get("name", ""))}
                    if c.get("id") is not None: nc["id"] = c["id"]
                    if c.get("remark") is not None: nc["remark"] = c["remark"]
                    if c.get("mainColorHex") is not None: nc["mainColorHex"] = c["mainColorHex"]
                    normalized.append(nc)
            if normalized:
                json_data["colors"] = normalized
        if selling_methods:
            json_data["sellingMethods"] = [_SELLING_TRANSLATE.get(m, m) for m in selling_methods]
        if door_widths:
            json_data["doorWidths"] = _split_str(door_widths) if isinstance(door_widths, str) else list(door_widths)
        if skus:
            json_data["skus"] = skus
        if sku_code:
            json_data["skuCode"] = sku_code
        elif name:
            # 对抗编程：LLM 没传货号时自动生成，不依赖 prompt 约束
            auto_code = _auto_generate_sku_code(name)
            json_data["skuCode"] = auto_code
            logger.info(f"[product_manage] Auto-generated sku_code: {auto_code} for product: {name}")
        if specifications:
            if isinstance(specifications, dict):
                json_data["specifications"] = {str(k): str(v) for k, v in specifications.items()}
            elif isinstance(specifications, str):
                parts = [p.strip() for p in specifications.split(",") if p.strip()]
                json_data["specifications"] = {p: p for p in parts}
        if unit:
            json_data["unit"] = unit
        elif category_id:
            # 默认计价单位：窗帘布艺 → 米
            json_data["unit"] = "米"
        if pricing_type:
            json_data["pricingType"] = pricing_type
        elif category_id:
            # 默认计价方式：窗帘布艺 → per_meter
            json_data["pricingType"] = "per_meter"
        if status:
            if status not in VALID_PRODUCT_STATUSES:
                return ToolResult(
                    success=False,
                    error=f"无效的商品状态: {status}",
                    message=f"请提供有效的状态值：{', '.join(VALID_PRODUCT_STATUSES)}",
                )
            json_data["status"] = status

        logger.info(f"[product_manage] Creating product with json_data keys={list(json_data.keys())} name={name}")
        logger.info(f"[product_manage] Creating product keys={list(json_data.keys())} name={name}")
        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/products",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "创建失败")
            error_code = response.get("error", {}).get("code", "")
            suggestion = ""
            if "分类" in error_msg or "CATEGORY" in str(error_code).upper():
                suggestion = "请使用 category_manage(action='tree') 获取分类树，确认正确的分类ID后重试"
            elif "VALIDATION" in str(error_code).upper():
                suggestion = "参数校验失败，请检查必填字段是否完整，确认后重试"
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"创建商品失败：{error_msg}",
                suggestion=suggestion,
            )

        product_data = response.get("data", {})
        product_id = product_data.get("id")

        logger.info(
            f"Product created: id={product_id}, name={name}, "
            f"tenant={context.tenant_id}, user={context.user_id}"
        )

        # 后创建验证：如果传了 processing_item_ids，确认是否已关联
        success_message = f"商品【{name}】创建成功"
        if processing_warnings:
            success_message += "\n\n⚠️ 警告：" + "\n".join(processing_warnings)

        return ToolResult(
            success=True,
            data={"product_id": product_id, "name": name},
            message=success_message,
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
        colors: Optional[list] = None,
        pricing_type: Optional[str] = None,
        selling_methods: Optional[list] = None,
        door_widths: Optional[list] = None,
        sku_code: Optional[str] = None,
        skus: Optional[list] = None,
        processing_item_configs: Optional[list] = None,
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
        
        # AI 友好：自动规范化 LLM 可能传错的参数（与 _create_product 保持一致）
        category_id = await _resolve_category_id(category_id, context) if category_id else None
        price = _normalize_number(price)
        stock_quantity = _normalize_number(stock_quantity)
        colors = _normalize_array(colors) if colors is not None else None
        selling_methods = _normalize_array(selling_methods) if selling_methods is not None else None

        json_data: Dict[str, Any] = {}
        if name:
            json_data["name"] = name
        if category_id:
            json_data["categoryId"] = category_id
        if price is not None:
            json_data["basePrice"] = float(price)
        if description:
            json_data["description"] = description
        if stock_quantity is not None:
            json_data["stock"] = int(stock_quantity)
        update_warnings = []
        if processing_item_ids:
            processing_item_ids, unresolved_ids = await _resolve_processing_item_ids(processing_item_ids, context)
            if unresolved_ids:
                update_warnings.append(
                    f"以下加工项ID无法解析: {unresolved_ids}。"
                    f"请使用 processing_item_query 查询真实ID后重试"
                )
        if processing_item_ids:
            if processing_item_configs:
                json_data["processingItemConfigs"] = processing_item_configs
            elif processing_item_ids:
                json_data["processingItemConfigs"] = [{"processingItemId": pid} for pid in processing_item_ids]
        if brand:
            json_data["brand"] = brand
        if images:
            json_data["images"] = list(images)
        if detail_images:
            json_data["detailImages"] = list(detail_images)
        if colors:
            normalized = []
            for c in colors:
                if isinstance(c, str):
                    normalized.append({"colorName": c})
                elif isinstance(c, dict):
                    nc = {"colorName": c.get("colorName", c.get("name", ""))}
                    if c.get("id") is not None: nc["id"] = c["id"]
                    if c.get("remark") is not None: nc["remark"] = c["remark"]
                    if c.get("mainColorHex") is not None: nc["mainColorHex"] = c["mainColorHex"]
                    normalized.append(nc)
            if normalized:
                json_data["colors"] = normalized
        if selling_methods:
            json_data["sellingMethods"] = [_SELLING_TRANSLATE.get(m, m) for m in selling_methods]
        if door_widths:
            json_data["doorWidths"] = _split_str(door_widths) if isinstance(door_widths, str) else list(door_widths)
        if skus:
            json_data["skus"] = skus
        if sku_code:
            json_data["skuCode"] = sku_code
        if specifications:
            if isinstance(specifications, dict):
                json_data["specifications"] = {str(k): str(v) for k, v in specifications.items()}
            elif isinstance(specifications, str):
                parts = [p.strip() for p in specifications.split(",") if p.strip()]
                json_data["specifications"] = {p: p for p in parts}
        if unit:
            json_data["unit"] = unit
        if pricing_type:
            json_data["pricingType"] = pricing_type

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
