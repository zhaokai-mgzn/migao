"""SKU 价格更新 Tool — 单独调整某个 SKU 的价格"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class SkuUpdateTool(BaseTool):
    """单独更新某个 SKU 的价格"""

    name = "sku_update"
    description = (
        "【触发】用户说'把XX颜色的改成XX元''散剪的价格太高了''白色调成XX'时调用。"
        "【前置】需先调 product_detail 查看 SKU 列表，让用户选择具体要改哪个 SKU。"
        "sku_id 从 product_detail 返回的 skus[].id 获取。"
        "【标注】WRITE"
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
            "sku_id": {
                "type": "string",
                "description": "SKU 标识。支持 SKU UUID，也支持'颜色 售卖方式 门幅'格式（如'白色 散剪 2.8米'），服务端自动匹配",
            },
            "price": {"type": "number", "description": "新价格（元）"},
        },
        "required": ["product_id", "sku_id", "price"],
    }

    async def execute(
        self,
        context: ToolContext,
        product_id: str,
        sku_id: str,
        price: float,
    ) -> ToolResult:
        # 基本校验：拒绝路径穿越字符
        if not product_id or ".." in str(product_id) or "/" in str(product_id):
            return ToolResult(success=False, error="Invalid product_id", message="商品 ID 格式不正确")
        if not sku_id or ".." in str(sku_id) or "/" in str(sku_id):
            return ToolResult(success=False, error="Invalid sku_id", message="SKU ID 格式不正确")

        client = get_admin_api_client()
        logger.info(f"[sku_update] product={product_id} sku={sku_id} price={price}")

        response = await client.patch(
            f"/api/admin/agent/products/{product_id}/skus/{sku_id}",
            json_data={"price": price},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            err = response.get("error", {})
            msg = err.get("message", "更新失败") if isinstance(err, dict) else str(err)
            return ToolResult(success=False, error=msg, message=f"SKU 价格更新失败: {msg}",
                            suggestion="请先调 product_detail 查看 SKU 列表，确认 SKU ID 正确")

        data = response.get("data", {})
        skus = data.get("skus", [])
        updated = next((s for s in skus if s.get("id") == sku_id), {})
        color = updated.get("color_name", "")
        method = updated.get("selling_method", "")
        width = updated.get("door_width", "")
        desc = f"{color} {method} {width}".strip()

        return ToolResult(
            success=True,
            data={"sku_id": sku_id, "new_price": price, "product": data},
            message=f"SKU「{desc}」价格已更新为 ¥{price}",
        )
