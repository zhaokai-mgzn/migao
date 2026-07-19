"""
AI 智能客服系统 — 商品加工项关联管理 Tool（从 product_manage 拆分）

单一职责：为已存在的商品增删加工项。
与 product_manage（商品 CRUD）和 processing_item_manage（加工项 CRUD）分离。
"""

from typing import Any, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class ProductProcessingItemManageTool(BaseTool):
    """商品加工项关联管理 Tool

    为已存在的商品添加或移除加工项。商品 ID 支持名称/序号/UUID 自动解析。
    """

    name = "product_processing_item_manage"
    description = (
        "【触发】用户说'添加加工项''加上XX''关联XX'时**直接调用**，无需 validate_input 和确认。"
        "【前置】product_id/item_ids 支持名称/UUID/序号自动解析。不要先调 processing_item_query。"
        "【标注】WRITE|IDEMPOTENT — 幂等操作，重复执行不会出错"
    )
    allowed_roles = ["admin", "tenant_admin"]

    read_only = False
    destructive = False  # add/remove 本身不具破坏性，可回滚
    idempotent = True    # 重复 add 幂等（已存在跳过）

    parameters = {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "商品标识。支持商品名称、序号（1-based）、UUID 或 UUID 前缀。服务端自动解析，无需 LLM 手动查 UUID",
            },
            "action": {
                "type": "string",
                "enum": ["add", "remove"],
                "description": "操作类型：add（添加加工项）/ remove（移除加工项）",
            },
            "item_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "加工项 ID 列表。支持商品名称、序号（1-based）、UUID 或 UUID 前缀。服务端自动解析",
            },
        },
        "required": ["product_id", "action", "item_ids"],
    }

    async def execute(
        self,
        context: ToolContext,
        product_id: str,
        action: str,
        item_ids: list,
    ) -> ToolResult:
        """执行商品加工项关联操作"""

        if action not in ("add", "remove"):
            return ToolResult(
                success=False, error="无效的加工项操作",
                message="action 必须为 add 或 remove",
            )
        if not item_ids:
            return ToolResult(
                success=False, error="缺少加工项 ID",
                message="请提供加工项 ID 列表",
            )

        # ── ID 自动解析：LLM 传名称/序号/UUID 都接受 ──
        from app.utils.id_resolver import resolve_product_id, resolve_processing_item_ids
        client = get_admin_api_client()

        resolved_product_id = await resolve_product_id(
            str(product_id).strip(), context.tenant_id, client,
        )
        if not resolved_product_id:
            return ToolResult(
                success=False, error="商品不存在",
                message=f"找不到商品「{product_id}」，请确认商品名称或 ID",
            )

        resolved_item_ids = await resolve_processing_item_ids(
            item_ids, context.tenant_id, client,
        )
        if not resolved_item_ids:
            return ToolResult(
                success=False, error="加工项不存在",
                message="找不到指定的加工项，请检查加工项名称或 ID",
            )

        logger.info(
            f"[product-pi-manage] {action} | "
            f"raw_product={product_id}→{resolved_product_id} "
            f"raw_items={item_ids}→{resolved_item_ids} "
            f"| tenant={context.tenant_id}"
        )

        response = await client.patch(
            f"/api/admin/agent/products/{resolved_product_id}/processing-items",
            json_data={"action": action, "itemIds": resolved_item_ids},
            tenant_id=context.tenant_id, user_id=context.user_id,
        )

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = error_info.get("message", "操作失败") if isinstance(error_info, dict) else str(error_info)
            return ToolResult(
                success=False, error=error_msg,
                message=f"加工项{action}失败：{error_msg}",
            )

        items = response.get("data", [])
        warnings = response.get("warnings", [])
        action_text = "添加" if action == "add" else "删除"
        msg = f"加工项已{action_text}，当前共 {len(items) if isinstance(items, list) else 0} 个加工项"
        if warnings:
            msg += "\n\n⚠️ 提示：" + "\n".join(warnings)

        return ToolResult(
            success=True,
            data={"processing_items": items, "warnings": warnings},
            message=msg,
        )
