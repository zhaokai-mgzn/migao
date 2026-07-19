"""SKU 价格更新 Tool — 按颜色/售卖方式/门幅精确匹配"""

from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class SkuUpdateTool(BaseTool):
    """单独更新某个 SKU 的价格"""

    name = "sku_update"
    description = (
        "【触发】用户说'白色改成XX元''散剪太贵了''XX颜色的调成XX'时直接调用。"
        "【前置】product_detail 返回的 SKU 列表中有颜色/售卖方式/门幅，选一个填入。"
        "color/selling_method/door_width 都是可选的，至少填一个来定位 SKU。"
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
            "color": {
                "type": "string",
                "description": "颜色名称，如'10# 复古墨绿'、'白色'。从 product_detail skus[].color_name 获取",
            },
            "selling_method": {
                "type": "string",
                "description": "售卖方式：散剪(bulk_cut) 或 整卷(full_roll)。可选",
            },
            "door_width": {
                "type": "string",
                "description": "门幅，如'2.8米'。可选",
            },
            "price": {"type": "number", "description": "新价格（元）"},
        },
        "required": ["product_id", "price"],
    }

    async def execute(
        self,
        context: ToolContext,
        product_id: str,
        price: float,
        color: str = "",
        selling_method: str = "",
        door_width: str = "",
    ) -> ToolResult:
        if not product_id or ".." in str(product_id):
            return ToolResult(success=False, error="Invalid product_id")

        client = get_admin_api_client()
        body = {"price": price}
        if color: body["color"] = color
        if selling_method: body["selling_method"] = selling_method
        if door_width: body["door_width"] = door_width

        logger.info(f"[sku_update] product={product_id} color={color} method={selling_method} width={door_width} price={price}")

        response = await client.patch(
            f"/api/admin/agent/products/{product_id}/skus/price",
            json_data=body,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            err = response.get("error", {})
            msg = err.get("message", "更新失败") if isinstance(err, dict) else str(err)
            return ToolResult(success=False, error=msg, message=f"SKU 调价失败: {msg}",
                            suggestion="请先调 product_detail 查看 SKU 列表，确认颜色/售卖方式/门幅正确")

        desc_parts = [p for p in [color, selling_method, door_width] if p]
        desc = " ".join(desc_parts) if desc_parts else product_id

        return ToolResult(
            success=True,
            data={"color": color, "selling_method": selling_method, "door_width": door_width, "new_price": price},
            message=f"SKU「{desc}」价格已更新为 ¥{price}",
        )
