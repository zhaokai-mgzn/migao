"""
AI 智能客服系统 - 商品搜索 Tool

搜索商品列表，根据关键词、分类等条件查询商品。

⚠️ 后端契约（admin-api `dto/ProductQueryRequest.java`）：查询参数只有
keyword/name/productId/categoryId/status/recommended/page/size/stockBelow/skuCode/
createdFrom/createdTo/startDate/endDate/sortBy/sortOrder —— **没有** minPrice/maxPrice/
stockStatus。Spring 默认忽略未知字段（FAIL_ON_UNKNOWN_PROPERTIES=false）→ 下发这三个键
等于没筛：后端返回全量，工具却报「找到 N 件相关商品」，LLM 再把全量叙述成「已筛选出
100-200 元的商品」＝**幻觉式筛选**（工具接口审计 A1）。
因此：价格区间在本工具内做**本地过滤**（total 取过滤后真实条数）；库存筛选下发后端
真实字段 `stockBelow`（语义：stock ≤ 阈值，见 ProductService）。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.tools.stock_semantics import LOW_STOCK_THRESHOLD, low_stock_phrase
from app.utils.http_client import get_admin_api_client
from app.utils.field_mapper import FieldMapper


# 库存筛选词表 → 后端 stockBelow 值（ProductQueryRequest.stockBelow；语义 stock ≤ 阈值）
# LOW_STOCK 阈值不在此处定义 —— 单点来源 app/tools/stock_semantics.py（issue #3783：
# 本文件与 inventory_manage 曾各持一套口径，同一句「低库存」会给出 100 / 10 两个数字）
OUT_OF_STOCK_THRESHOLD = 0
STOCK_STATUS_TO_STOCK_BELOW: Dict[str, int] = {
    "low_stock": LOW_STOCK_THRESHOLD,
    "out_of_stock": OUT_OF_STOCK_THRESHOLD,
}


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
        "【触发】用户问'有什么XX''搜XX''找XX商品''有没有XX''XX元左右的商品'或提到商品关键词/分类时调用。"
        "【前置】keyword 可选，缺关键词时列出全部。"
        "stock_status 支持 low_stock（" + low_stock_phrase() + "）/out_of_stock（库存≤0）；"
        "min_price/max_price（元）为本地过滤（后端不支持价格筛选），只作用于本次返回的 size 条，"
        "需更大范围请调大 size。"
        "【反例】查单个商品详情用 product_detail，查分类用 category_manage(tree)。"
        "【标注】READONLY — 放心调用，无需确认"
    )

    # 含 operator：admin-api 员工角色（RoleService operator 有 product:list 权限码，
    # 角色码漂移修复 POC-2761 D 项）。customer 保留（C 端商品搜索）。
    allowed_roles = ["customer", "admin", "agent", "tenant_admin", "operator"]
    
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
                "description": "最低价格（元，可选）。后端不支持价格筛选 → 本工具对返回结果做本地过滤，只作用于本次返回的 size 条",
            },
            "max_price": {
                "type": "number",
                "description": "最高价格（元，可选）。后端不支持价格筛选 → 本工具对返回结果做本地过滤，只作用于本次返回的 size 条",
            },
            "page": {
                "type": "integer",
                "description": "页码，默认 1",
                "default": 1,
            },
            "size": {
                "type": "integer",
                "description": "每页数量，默认 5。价格区间为本地过滤，调大 size 可扩大筛选范围",
                "default": 5,
            },
            "stock_status": {
                "type": "string",
                "description": (
                    f"库存状态筛选（可选）：low_stock={low_stock_phrase()}"
                    "（与后台低库存口径一致）/ "
                    "out_of_stock=库存≤0。对应后端 stockBelow 字段；"
                    "「有货」后端无法表达（stockBelow 只有「≤」语义），请在结果里按 stock 判断"
                ),
                "enum": ["low_stock", "out_of_stock"],
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
            min_price: 最低价格（本地过滤）
            max_price: 最高价格（本地过滤）
            page: 页码
            size: 每页数量
            stock_status: 库存状态筛选（low_stock/out_of_stock，映射后端 stockBelow）
            
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
                suggestion="请联系管理员获取商品查看权限",
            )

        # 库存筛选值校验：词表外的取值（如历史 in_stock）必须显式拒绝，
        # 绝不下发后端不认的词（静默返回全量 → 又变成幻觉式筛选）
        if stock_status and stock_status not in STOCK_STATUS_TO_STOCK_BELOW:
            return ToolResult(
                success=False,
                error=f"不支持的库存筛选: {stock_status}",
                message=f"库存状态仅支持：{', '.join(sorted(STOCK_STATUS_TO_STOCK_BELOW))}",
                suggestion=f"请用 low_stock（{low_stock_phrase()}）或 out_of_stock（库存≤0）；「有货」请在结果里按 stock 判断",
            )
        
        try:
            # 搜索请求日志
            logger.info(f"[product-search] Searching: keyword='{keyword}' category={category_id} | tenant={context.tenant_id}")
            
            # 构建查询参数（键必须 ∈ ProductQueryRequest 字段，否则 Spring 静默忽略）
            params: Dict[str, Any] = {
                "page": page,
                "size": size,
            }
            
            if keyword:
                params["keyword"] = keyword
            if category_id:
                params["categoryId"] = category_id
            # 库存筛选：只下发后端真实字段 stockBelow（绝不发 stockStatus）
            if stock_status:
                params["stockBelow"] = STOCK_STATUS_TO_STOCK_BELOW[stock_status]
            # 价格区间：后端无价格字段 → 绝不下发 minPrice/maxPrice，改在下方本地过滤
            # C 端（顾客）只展示已上架商品（issue #3932）：强制下发后端真实字段 status=on_sale
            #（ProductQueryRequest.status），由后端先行过滤；下方再做本地纵深过滤
            #（防后端口径漂移 / 历史数据缺 status 字段）。B 端商户需要看到自己店铺全状态商品 → 不加。
            if context.role == "customer":
                params["status"] = "on_sale"
            
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
                    suggestion="请稍后重试，或尝试更精确的关键词",
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
                # total 取「本工具实际验证通过的条数」：既不沿用含越权记录的后端 total，
                # 也不用 max(0, total - filtered_count) 这类按丢弃数估算的错语义
                total = len(verified_records)

            # C 端（顾客）上架过滤（issue #3932，纵深防御）：仅保留 status == "on_sale" 的记录，
            # 非上架（off_sale 下架等）与缺 status 字段的历史数据一律不展示、不计数。
            # total 语义：后端已按 status=on_sale 过滤（真实字段）→ 零命中时不覆盖后端 total
            #（保分页口径）；本地确有过滤时取过滤后真实条数（与价格本地过滤同一语义，
            # 审计 A1 同款口径——本地过滤无法获知全库真实条数）。
            if context.role == "customer":
                on_sale_records = [
                    r for r in verified_records if r.get("status") == "on_sale"
                ]
                status_filtered = len(verified_records) - len(on_sale_records)
                if status_filtered > 0:
                    logger.warning(
                        f"[product-search] Customer on_sale filter removed {status_filtered} "
                        f"records not in on_sale status (tenant={context.tenant_id})"
                    )
                    total = len(on_sale_records)
                verified_records = on_sale_records

            # 价格区间本地过滤（后端 ProductQueryRequest 无价格字段）：
            # total 必须是过滤后的真实条数（审计 A1 —— 错语义 total 会让 LLM 报出全量件数）
            price_range_desc = ""
            scanned_count = len(verified_records)
            if min_price is not None or max_price is not None:
                verified_records = [
                    r for r in verified_records
                    if self._price_in_range(FieldMapper.get_price(r), min_price, max_price)
                ]
                total = len(verified_records)
                price_range_desc = self._price_range_desc(min_price, max_price)
                logger.info(
                    f"[product-search] Local price filter {price_range_desc}: "
                    f"{scanned_count} -> {total}（后端不支持价格筛选）"
                )
            
            # 格式化商品列表
            products = self._format_products(verified_records)
            
            logger.info(
                f"[product-search] Found {len(products)} products, total={total} | tenant={context.tenant_id}"
            )
            
            if not products:
                if price_range_desc:
                    # 商品是存在的，只是不在价格区间 → 措辞必须说清，不能报「没找到相关商品」
                    message = (
                        f"在检索到的 {scanned_count} 件商品中，没有价格{price_range_desc}的商品；"
                        f"可放宽价格区间、换关键词，或调大 size 扩大检索范围"
                    )
                else:
                    message = f"抱歉，没有找到与'{keyword}'相关的商品，换个关键词试试？"
                return ToolResult(
                    success=True,
                    data={"products": [], "total": 0, "page": page, "size": size},
                    message=message,
                )

            # 构建摘要：取前3个商品名 + ID 前缀，LLM 写操作时直接用 UUID
            top_items = []
            for p in products[:3]:
                name = p.get("name", "")
                pid = p.get("id", "")
                top_items.append(f"{name}({pid[:8]}...)")
            names_str = "、".join(top_items)
            if len(products) > 3:
                names_str += f" 等{len(products)}件"

            if price_range_desc:
                # 本地过滤后的口径必须披露「扫描范围」（后端分页 → 只筛了本次返回的 size 条），
                # 否则 LLM 会把「本次筛出 M 件」叙述成「全店共 M 件」
                message = (
                    f"在检索到的 {scanned_count} 件商品中，筛出 {total} 件价格{price_range_desc}的商品: "
                    f"{names_str}"
                )
            else:
                message = f"找到 {total} 件相关商品: {names_str}"

            return ToolResult(
                success=True,
                data={
                    "products": products,
                    "total": total,
                    "page": page,
                    "size": size,
                    "total_pages": (total + size - 1) // size,
                },
                message=message,
            )
            
        except Exception as e:
            logger.error(f"[product-search] Search failed | tenant={context.tenant_id} error={type(e).__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="搜索商品时出错，请稍后重试",
                suggestion="请稍后重试，或尝试更精确的关键词",
            )

    @staticmethod
    def _price_in_range(price: Optional[float], min_price: Optional[float], max_price: Optional[float]) -> bool:
        """价格是否落在区间内（价格缺失的记录无法证明命中 → 排除）"""
        if price is None:
            return False
        if min_price is not None and price < min_price:
            return False
        if max_price is not None and price > max_price:
            return False
        return True

    @staticmethod
    def _price_range_desc(min_price: Optional[float], max_price: Optional[float]) -> str:
        """价格区间的中文描述（用于向用户/LLM 说明过滤口径）"""
        if min_price is not None and max_price is not None:
            return f"在 {min_price}-{max_price} 元之间"
        if min_price is not None:
            return f"不低于 {min_price} 元"
        return f"不高于 {max_price} 元"
    
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
