"""商品快速更新 Tool — 改价格/名称等单个字段，轻量无负担"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class ProductUpdateTool(BaseTool):
    """商品快速更新 — 传什么改什么，null 字段不修改"""

    name = "product_update"
    description = (
        "【触发】用户说'改价格''改名称''价格改成XX''改名'时**直接调用**，无需 validate_input。"
        "只传要改的字段，其他字段保持不变。product_id 支持名称/序号/UUID。"
        "【注意】改的是商品统一定价，影响所有 SKU。单独调某个 SKU 价格请引导去商品管理页。"
        "【反例】增删加工项用 product_processing_item_manage，单独 SKU 调价本工具不支持。"
        "【标注】WRITE|IDEMPOTENT"
    )
    allowed_roles = ["admin", "tenant_admin"]
    read_only = False
    destructive = False
    idempotent = True

    parameters = {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "商品标识。支持名称/序号/UUID，服务端自动解析",
            },
            "price": {"type": "number", "description": "新价格（可选）"},
            "name": {"type": "string", "description": "新名称（可选）"},
            "description": {"type": "string", "description": "新描述（可选）"},
            "status": {"type": "string", "enum": ["on_sale", "off_sale"], "description": "上下架（可选）"},
        },
        "required": ["product_id"],
    }

    async def execute(
        self,
        context: ToolContext,
        product_id: str,
        price: Optional[float] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
    ) -> ToolResult:
        # Build only the fields that were actually provided
        json_data: Dict[str, Any] = {}
        if price is not None: json_data["price"] = price
        if name: json_data["name"] = name
        if description: json_data["description"] = description
        if status: json_data["status"] = status

        if not json_data:
            return ToolResult(success=False, error="没有要修改的字段", message="请提供至少一个要修改的字段")

        logger.info(f"[product_update] {product_id}: {list(json_data.keys())}")
        client = get_admin_api_client()
        response = await client.patch(
            f"/api/admin/agent/products/{product_id}",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            err = response.get("error", {})
            msg = err.get("message", "更新失败") if isinstance(err, dict) else str(err)
            return ToolResult(success=False, error=msg, message=f"更新失败: {msg}",
                            suggestion="请确认商品名称或ID正确，或先调用 product_search 查询")

        return ToolResult(success=True, data=response.get("data", {}),
                         message=f"商品已更新: {', '.join(json_data.keys())}")
