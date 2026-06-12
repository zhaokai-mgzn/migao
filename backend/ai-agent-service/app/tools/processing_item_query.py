"""
AI 智能客服系统 - 加工项查询 Tool

独立查询加工项模块（与商品关联的加工项不同，此处为店铺所有加工项目录）。
对应后端接口：
- GET /api/admin/processing-items（分页 + keyword/categoryId/status）
- GET /api/admin/processing-items/{id}

注意：本 Tool 与 query_processing_items 不同：
- query_processing_items：查询「某商品」关联的加工项及其自定义价格
- processing_item_query：查询「店铺加工项目录」，支持按名称、分类、状态搜索
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class ProcessingItemQueryTool(BaseTool):
    """加工项查询 Tool

    查询商家加工项目录（包含名称、分类、单价、单位、状态等）。

    使用场景：
    - 同事询问"查看加工项列表"
    - 同事搜索某个加工项（如"打孔"、"窗帘头"）
    - 查询加工项详情
    """

    name = "processing_item_query"
    description = (
        "查询店铺加工项目录列表或详情（包含加工项名称、分类、单价、单位、状态、加工天数等）。"
        "当同事询问'加工项列表'、'有哪些加工项'、'打孔/窗帘头多少钱'等加工项相关问题时使用。"
        "注意：本工具用于查询加工项目录本身，与查询订单（order_query）和查询商品（product_search）无关。"
    )

    parameters = {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "加工项 ID（可选）。提供时按 ID 查询单条详情。",
            },
            "keyword": {
                "type": "string",
                "description": "加工项名称关键词，模糊搜索（可选）。",
            },
            "category_id": {
                "type": "string",
                "description": "加工项分类 ID（可选）。",
            },
            "status": {
                "type": "string",
                "description": "状态筛选（可选）：active（启用）、inactive（禁用）。",
                "enum": ["active", "inactive"],
            },
            "page": {
                "type": "integer",
                "description": "页码，默认 1。",
                "default": 1,
            },
            "size": {
                "type": "integer",
                "description": "每页数量，默认 10。",
                "default": 10,
            },
        },
    }

    async def execute(
        self,
        context: ToolContext,
        id: Optional[str] = None,
        keyword: Optional[str] = None,
        category_id: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 10,
    ) -> ToolResult:
        """执行加工项查询

        Args:
            context: Tool 执行上下文
            id: 加工项 ID（提供时查询详情）
            keyword: 名称关键词
            category_id: 分类 ID
            status: 状态过滤
            page: 页码
            size: 每页数量

        Returns:
            ToolResult: 查询结果
        """
        # 强制转换分页参数为 int（LLM 可能传字符串）
        page = int(page) if page else 1
        size = int(size) if size else 10

        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询加工项信息",
            )

        try:
            client = get_admin_api_client()

            # 详情查询
            if id:
                logger.info(
                    f"[processing-item-query] Detail: id={id} | tenant={context.tenant_id}"
                )
                response = await client.get(
                    f"/api/admin/processing-items/{id}",
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
                if not response.get("success"):
                    error_msg = response.get("error", {}).get("message", "查询失败")
                    return ToolResult(
                        success=False,
                        error=error_msg,
                        message=f"查询加工项详情失败：{error_msg}",
                    )
                item = self._format_item(response.get("data") or {})
                item_name = item.get('name', '')
                price_text = f"{item.get('unit_price')}元/{item.get('unit', '件')}" if item.get('unit_price') is not None else ""
                return ToolResult(
                    success=True,
                    data={"item": item},
                    message=f"已找到加工项「{item_name}」",
                    summary=f"加工项详情: {item_name}, {price_text}".rstrip(", "),
                )

            # 列表查询
            params: Dict[str, Any] = {"page": page, "size": size}
            if keyword:
                params["keyword"] = keyword
            if category_id:
                params["categoryId"] = category_id
            if status:
                params["status"] = status

            logger.info(
                f"[processing-item-query] List: keyword='{keyword or ''}' "
                f"category_id={category_id} status={status} page={page} size={size} "
                f"| tenant={context.tenant_id}"
            )

            response = await client.get(
                "/api/admin/processing-items",
                params=params,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )

            if not response.get("success"):
                error_msg = response.get("error", {}).get("message", "查询失败")
                return ToolResult(
                    success=False,
                    error=error_msg,
                    message=f"查询加工项列表失败：{error_msg}",
                )

            data = response.get("data", {}) or {}
            records = data.get("items") or data.get("records") or []
            total = data.get("total", len(records))

            items = [self._format_item(r) for r in records]

            logger.info(
                f"[processing-item-query] Found {len(items)} items, total={total} "
                f"| tenant={context.tenant_id}"
            )

            if not items:
                empty_summary = (
                    f"未找到与'{keyword}'匹配的加工项"
                    if keyword
                    else "暂无加工项数据"
                )
                return ToolResult(
                    success=True,
                    data={"items": [], "total": 0, "page": page, "size": size},
                    message=(
                        f"暂无与「{keyword}」匹配的加工项"
                        if keyword
                        else "暂无加工项数据"
                    ),
                    summary=empty_summary,
                )

            # 构建摘要：取前3个加工项名
            top_names = [i["name"] for i in items[:3] if i.get("name")]
            names_str = "、".join(top_names)
            if len(items) > 3:
                names_str += "等"

            return ToolResult(
                success=True,
                data={
                    "items": items,
                    "total": total,
                    "page": page,
                    "size": size,
                    "total_pages": (total + size - 1) // size if size else 1,
                },
                message=f"共找到 {total} 个加工项",
                summary=f"找到{total}个加工项: {names_str}",
            )

        except Exception as e:
            logger.error(
                f"[processing-item-query] Failed | tenant={context.tenant_id} "
                f"error={type(e).__name__}: {e}"
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="查询加工项时出错，请稍后重试",
            )

    @staticmethod
    def _format_item(record: Dict[str, Any]) -> Dict[str, Any]:
        """格式化加工项记录，统一字段名"""
        if not record:
            return {}
        return {
            "id": record.get("id"),
            "name": record.get("name"),
            "category_id": record.get("categoryId") or record.get("category_id"),
            "category_name": record.get("categoryName") or record.get("category_name"),
            "pricing_method": record.get("pricingMethod") or record.get("pricing_method"),
            "unit_price": record.get("unitPrice") or record.get("unit_price"),
            "unit": record.get("unit"),
            "min_quantity": record.get("minQuantity") or record.get("min_quantity"),
            "max_quantity": record.get("maxQuantity") or record.get("max_quantity"),
            "description": record.get("description"),
            "options": record.get("options"),
            "processing_days": record.get("processingDays") or record.get("processing_days"),
            "ai_recommended": record.get("aiRecommended") or record.get("ai_recommended"),
            "status": record.get("status"),
        }
