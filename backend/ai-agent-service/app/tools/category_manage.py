"""
AI 智能客服系统 - 商品分类管理 Tool

管理商品分类，包括获取分类树、创建分类、更新分类、删除分类。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"tree", "create", "update", "delete"}


class CategoryManageTool(BaseTool):
    """商品分类管理 Tool

    管理商品分类：获取分类树、创建/更新/删除分类。

    使用场景：
    - 查看商品分类树形结构
    - 创建新的商品分类（顶级或子分类）
    - 更新分类名称
    - 删除不需要的分类
    """

    name = "category_manage"
    description = (
        "商品分类管理工具，支持获取分类树形结构、创建新分类、更新分类名称、删除分类。"
        "当需要管理商品分类（如查看分类结构、添加/修改/删除分类）时使用。"
    )

    allowed_roles = ["admin", "super_admin", "tenant_admin"]

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：tree（获取分类树）/ create（创建分类）/ update（更新分类）/ delete（删除分类）",
                "enum": ["tree", "create", "update", "delete"],
            },
            "category_id": {
                "type": "string",
                "description": "分类 ID（update/delete 时必填）",
            },
            "name": {
                "type": "string",
                "description": "分类名称（create 时必填，update 时可选）",
            },
            "parent_id": {
                "type": "string",
                "description": "父分类 ID（create 时可选，不传则为顶级分类）",
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        category_id: Optional[str] = None,
        name: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> ToolResult:
        """执行商品分类管理操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行分类管理操作",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
            )

        try:
            if action == "tree":
                return await self._get_tree(context)
            elif action == "create":
                return await self._create_category(context, name, parent_id)
            elif action == "update":
                return await self._update_category(context, category_id, name)
            elif action == "delete":
                return await self._delete_category(context, category_id)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                )

        except Exception as e:
            logger.error(f"[category-manage] Failed: action={action}, error={type(e).__name__}: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                message="分类管理操作失败，请稍后重试",
            )

    async def _get_tree(self, context: ToolContext) -> ToolResult:
        """获取分类树形结构"""
        logger.info(f"[category-manage] Tree | tenant={context.tenant_id}")

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/categories/tree",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"获取分类树失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"tree": response.get("data", [])},
            message="已获取商品分类树形结构",
        )

    async def _create_category(
        self,
        context: ToolContext,
        name: Optional[str],
        parent_id: Optional[str],
    ) -> ToolResult:
        """创建分类"""
        if not name:
            return ToolResult(
                success=False,
                error="缺少分类名称",
                message="创建分类时必须提供 name",
            )

        json_data: Dict[str, Any] = {"name": name}
        if parent_id:
            json_data["parentId"] = parent_id

        logger.info(
            f"[category-manage] Create: name={name}, parent_id={parent_id} "
            f"| tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/categories",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "创建失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"创建分类失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data=response.get("data", {}),
            message=f"分类「{name}」创建成功",
        )

    async def _update_category(
        self,
        context: ToolContext,
        category_id: Optional[str],
        name: Optional[str],
    ) -> ToolResult:
        """更新分类"""
        if not category_id:
            return ToolResult(
                success=False,
                error="缺少分类 ID",
                message="更新分类时必须提供 category_id",
            )
        if not name:
            return ToolResult(
                success=False,
                error="缺少分类名称",
                message="更新分类时必须提供 name",
            )

        logger.info(
            f"[category-manage] Update: category_id={category_id}, name={name} "
            f"| tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/categories/{category_id}",
            json_data={"name": name},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"更新分类失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"category_id": category_id, "name": name},
            message=f"分类已更新为「{name}」",
        )

    async def _delete_category(self, context: ToolContext, category_id: Optional[str]) -> ToolResult:
        """删除分类"""
        if not category_id:
            return ToolResult(
                success=False,
                error="缺少分类 ID",
                message="删除分类时必须提供 category_id",
            )

        logger.info(f"[category-manage] Delete: category_id={category_id} | tenant={context.tenant_id}")

        client = get_admin_api_client()
        response = await client.delete(
            f"/api/admin/categories/{category_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "删除失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"删除分类失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"category_id": category_id},
            message="分类已删除",
        )
