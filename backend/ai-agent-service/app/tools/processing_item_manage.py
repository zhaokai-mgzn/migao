"""
AI 智能客服系统 - 加工项管理 Tool

管理加工项写入操作，包括创建/更新/删除加工项、加工分类 CRUD、价格计算。
与 processing_item_query（查询）互补，本工具负责写入操作。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {
    "create_item", "update_item", "delete_item", "toggle_item_status",
    "list_categories", "create_category", "update_category", "delete_category",
    "calculate_price",
}


class ProcessingItemManageTool(BaseTool):
    """加工项管理 Tool

    管理加工项写入操作：创建/更新/删除加工项、加工分类 CRUD、价格计算。

    使用场景：
    - 创建新的加工项（如打孔、窗帘头加工等）
    - 更新加工项信息（价格、名称、描述等）
    - 删除加工项
    - 管理加工分类（查看/创建/更新/删除）
    - 计算加工项价格
    """

    name = "processing_item_manage"
    description = (
        "加工项管理工具，支持创建/更新/删除加工项、加工分类增删改查、价格计算。"
        "与 processing_item_query（查询工具）互补，本工具负责写入和管理操作。"
        "当需要新增加工项、修改加工项信息、管理加工分类或计算加工价格时使用。"
    )

    allowed_roles = ["admin", "tenant_admin"]

    read_only = False
    destructive = True   # 可删除加工项/分类
    idempotent = False   # 创建/删除非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型：create_item（创建加工项）/ update_item（更新加工项）/ delete_item（删除加工项）"
                    "/ toggle_item_status（启用/停用加工项）"
                    "/ list_categories（分类列表）/ create_category（创建分类）/ update_category（更新分类）"
                    "/ delete_category（删除分类）/ calculate_price（计算价格）"
                ),
                "enum": [
                    "create_item", "update_item", "delete_item", "toggle_item_status",
                    "list_categories", "create_category", "update_category", "delete_category",
                    "calculate_price",
                ],
            },
            "item_id": {
                "type": "string",
                "description": "加工项 ID（update_item/delete_item 时必填）",
            },
            "category_id": {
                "type": "string",
                "description": "加工分类 ID（create_item 时必填，update_item/update_category/delete_category 时必填）",
            },
            "name": {
                "type": "string",
                "description": "名称（create_item/create_category 时必填，update_item/update_category 时可选）",
            },
            "price": {
                "type": "number",
                "description": "单价（create_item 时必填，update_item 时可选）",
            },
            "description": {
                "type": "string",
                "description": "描述信息（可选）",
            },
            "unit": {
                "type": "string",
                "description": "计量单位（create_item 时可选）",
            },
            "processing_item_id": {
                "type": "string",
                "description": "加工项 ID（calculate_price 时必填）",
            },
            "quantity": {
                "type": "number",
                "description": "数量（calculate_price 时必填）",
            },
            "status": {
                "type": "string",
                "description": "目标状态（toggle_item_status 时必填）：active（启用）/ inactive（停用）",
                "enum": ["active", "inactive"],
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        item_id: Optional[str] = None,
        category_id: Optional[str] = None,
        name: Optional[str] = None,
        price: Optional[float] = None,
        description: Optional[str] = None,
        unit: Optional[str] = None,
        processing_item_id: Optional[str] = None,
        quantity: Optional[float] = None,
        status: Optional[str] = None,
    ) -> ToolResult:
        """执行加工项管理操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行加工项管理操作",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
            )

        try:
            if action == "create_item":
                return await self._create_item(context, name, category_id, price, description, unit)
            elif action == "update_item":
                return await self._update_item(context, item_id, name, category_id, price, description)
            elif action == "delete_item":
                return await self._delete_item(context, item_id)
            elif action == "toggle_item_status":
                return await self._toggle_item_status(context, item_id, status)
            elif action == "list_categories":
                return await self._list_categories(context)
            elif action == "create_category":
                return await self._create_category(context, name, description)
            elif action == "update_category":
                return await self._update_category(context, category_id, name, description)
            elif action == "delete_category":
                return await self._delete_category(context, category_id)
            elif action == "calculate_price":
                return await self._calculate_price(context, processing_item_id, quantity)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                )

        except Exception as e:
            logger.error(f"[processing-item-manage] Failed: action={action}, error={type(e).__name__}: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                message="加工项管理操作失败，请稍后重试",
            )

    async def _create_item(
        self,
        context: ToolContext,
        name: Optional[str],
        category_id: Optional[str],
        price: Optional[float],
        description: Optional[str],
        unit: Optional[str],
    ) -> ToolResult:
        """创建加工项"""
        if not name:
            return ToolResult(
                success=False,
                error="缺少加工项名称",
                message="创建加工项时必须提供 name",
            )
        if not category_id:
            return ToolResult(
                success=False,
                error="缺少分类 ID",
                message="创建加工项时必须提供 category_id",
            )
        if price is None:
            return ToolResult(
                success=False,
                error="缺少价格",
                message="创建加工项时必须提供 price",
            )

        json_data: Dict[str, Any] = {
            "name": name,
            "categoryId": category_id,
            "price": price,
        }
        if description:
            json_data["description"] = description
        if unit:
            json_data["unit"] = unit

        logger.info(
            f"[processing-item-manage] CreateItem: name={name}, category_id={category_id}, "
            f"price={price} | tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/processing-items",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "创建失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"创建加工项失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data=response.get("data", {}),
            message=f"加工项「{name}」创建成功",
        )

    async def _update_item(
        self,
        context: ToolContext,
        item_id: Optional[str],
        name: Optional[str],
        category_id: Optional[str],
        price: Optional[float],
        description: Optional[str],
    ) -> ToolResult:
        """更新加工项"""
        if not item_id:
            return ToolResult(
                success=False,
                error="缺少加工项 ID",
                message="更新加工项时必须提供 item_id",
            )

        json_data: Dict[str, Any] = {}
        if name:
            json_data["name"] = name
        if category_id:
            json_data["categoryId"] = category_id
        if price is not None:
            json_data["price"] = price
        if description:
            json_data["description"] = description

        if not json_data:
            return ToolResult(
                success=False,
                error="缺少更新内容",
                message="更新加工项时至少提供 name、category_id、price 或 description 之一",
            )

        logger.info(
            f"[processing-item-manage] UpdateItem: item_id={item_id}, fields={list(json_data.keys())} "
            f"| tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/processing-items/{item_id}",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"更新加工项失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"item_id": item_id, **json_data},
            message="加工项已更新",
        )

    async def _delete_item(self, context: ToolContext, item_id: Optional[str]) -> ToolResult:
        """删除加工项"""
        if not item_id:
            return ToolResult(
                success=False,
                error="缺少加工项 ID",
                message="删除加工项时必须提供 item_id",
            )

        logger.info(f"[processing-item-manage] DeleteItem: item_id={item_id} | tenant={context.tenant_id}")

        client = get_admin_api_client()
        response = await client.delete(
            f"/api/admin/processing-items/{item_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "删除失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"删除加工项失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"item_id": item_id},
            message="加工项已删除",
        )

    async def _toggle_item_status(
        self,
        context: ToolContext,
        item_id: Optional[str],
        status: Optional[str],
    ) -> ToolResult:
        """启用/停用加工项"""
        if not item_id:
            return ToolResult(
                success=False,
                error="缺少加工项 ID",
                message="启用/停用加工项时必须提供 item_id",
            )
        if not status or status not in ("active", "inactive"):
            return ToolResult(
                success=False,
                error=f"无效的状态值: {status}",
                message="请提供有效的状态值：active（启用）或 inactive（停用）",
            )

        logger.info(
            f"[processing-item-manage] ToggleItemStatus: item_id={item_id}, status={status} "
            f"| tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/processing-items/{item_id}/status",
            json_data={"status": status},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "操作失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"加工项状态更新失败：{error_msg}",
            )

        status_text = "启用" if status == "active" else "停用"
        return ToolResult(
            success=True,
            data={"item_id": item_id, "status": status},
            message=f"加工项已{status_text}",
        )

    async def _list_categories(self, context: ToolContext) -> ToolResult:
        """获取加工分类列表"""
        logger.info(f"[processing-item-manage] ListCategories | tenant={context.tenant_id}")

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/processing-categories",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"获取加工分类列表失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"categories": response.get("data", [])},
            message="已获取加工分类列表",
        )

    async def _create_category(
        self,
        context: ToolContext,
        name: Optional[str],
        description: Optional[str],
    ) -> ToolResult:
        """创建加工分类"""
        if not name:
            return ToolResult(
                success=False,
                error="缺少分类名称",
                message="创建加工分类时必须提供 name",
            )

        json_data: Dict[str, Any] = {"name": name}
        if description:
            json_data["description"] = description

        logger.info(
            f"[processing-item-manage] CreateCategory: name={name} | tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/processing-categories",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "创建失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"创建加工分类失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data=response.get("data", {}),
            message=f"加工分类「{name}」创建成功",
        )

    async def _update_category(
        self,
        context: ToolContext,
        category_id: Optional[str],
        name: Optional[str],
        description: Optional[str],
    ) -> ToolResult:
        """更新加工分类"""
        if not category_id:
            return ToolResult(
                success=False,
                error="缺少分类 ID",
                message="更新加工分类时必须提供 category_id",
            )
        if not name:
            return ToolResult(
                success=False,
                error="缺少分类名称",
                message="更新加工分类时必须提供 name",
            )

        json_data: Dict[str, Any] = {"name": name}
        if description:
            json_data["description"] = description

        logger.info(
            f"[processing-item-manage] UpdateCategory: category_id={category_id}, name={name} "
            f"| tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/processing-categories/{category_id}",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"更新加工分类失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"category_id": category_id, **json_data},
            message=f"加工分类已更新为「{name}」",
        )

    async def _delete_category(self, context: ToolContext, category_id: Optional[str]) -> ToolResult:
        """删除加工分类"""
        if not category_id:
            return ToolResult(
                success=False,
                error="缺少分类 ID",
                message="删除加工分类时必须提供 category_id",
            )

        logger.info(
            f"[processing-item-manage] DeleteCategory: category_id={category_id} "
            f"| tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.delete(
            f"/api/admin/processing-categories/{category_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "删除失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"删除加工分类失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"category_id": category_id},
            message="加工分类已删除",
        )

    async def _calculate_price(
        self,
        context: ToolContext,
        processing_item_id: Optional[str],
        quantity: Optional[float],
    ) -> ToolResult:
        """计算加工项价格"""
        if not processing_item_id:
            return ToolResult(
                success=False,
                error="缺少加工项 ID",
                message="计算价格时必须提供 processing_item_id",
            )
        if quantity is None:
            return ToolResult(
                success=False,
                error="缺少数量",
                message="计算价格时必须提供 quantity",
            )

        logger.info(
            f"[processing-item-manage] CalculatePrice: item_id={processing_item_id}, "
            f"quantity={quantity} | tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/processing-items/calculate",
            json_data={
                "processingItemId": processing_item_id,
                "quantity": quantity,
            },
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "计算失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"计算加工价格失败：{error_msg}",
            )

        data = response.get("data", {})
        total_price = data.get("totalPrice") or data.get("total_price", "")

        return ToolResult(
            success=True,
            data=data,
            message=f"加工价格计算结果：{total_price}",
        )
