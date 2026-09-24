"""
AI 智能客服系统 - 商品分类管理 Tool

管理商品分类，包括获取分类树、创建分类、更新分类、删除分类。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"tree"}


class CategoryManageTool(BaseTool):
    """商品分类管理 Tool

    管理商品分类：获取分类列表、创建/更新/删除分类。

    使用场景：
    - 查看商品分类列表（扁平结构，无父子概念，issue #2905）
    - 创建新的商品分类（顶级，无子分类）
    - 更新分类名称
    - 删除不需要的分类
    """

    name = "category_manage"
    description = (
        "【触发】用户问'有哪些分类''分类列表''这个商品是哪个分类'时调用；"
        "建品/查商品需要分类 id 时也用 tree。"
        "【参数】action 必填，**本工具只有 tree 一个只读 action**（返回扁平分类列表，无父子概念）。"
        "tree 返回的分类 id（长字符串如 88b6c50fbc...）用于按分类筛选商品。"
        "【反例】查商品/库存用 product_search / product_detail；分类 id ≠ 商品 id，不要混用。"
        "【反例】新建/改名/删除分类**不在本工具能力内**（B 端已只读化，issue #5247）——"
        "引导用户到后台「商品列表 → 分类管理」页面自行操作，不要承诺代为修改。"
        "【标注】READONLY — 纯查询，不含任何写 action"
    )
    # 权限码（admin-api 目录）：CategoryController 类级 `@RequirePermission("product:category")`。
    # 此前写死 ["admin","tenant_admin"] ⇒ operator / product_manager 持码却被判「权限不足」（#4106 F4）。
    required_permissions = ["product:category"]

    read_only = True
    read_only_actions = {"tree"}  # 只读 action 免确认拦截
    idempotent = False   # 创建/删除非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：tree（获取分类列表）—— 本工具只有这一个只读 action",
                "enum": ["tree"],
            },
            "category_id": {
                "type": "string",
                "description": "分类 ID（update/delete 时必填）",
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
    ) -> ToolResult:
        """执行商品分类管理操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行分类管理操作",
                suggestion="请联系管理员获取执行分类管理操作权限",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )

        try:
            if action == "tree":
                return await self._get_tree(context)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )

        except Exception as e:
            logger.error(f"[category-manage] Failed: action={action}, error={type(e).__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="分类管理操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
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
            return admin_api_failure(response,
                error=error_msg,
                message=f"获取分类树失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请让用户联系管理员核对分类数据",
            )

        tree = response.get("data", [])
        names = [c.get("name", "") for c in tree[:5] if isinstance(c, dict)]
        summary = f"共{len(tree)}个分类: {', '.join(names)}" if names else "暂无分类"
        return ToolResult(
            success=True,
            data={"tree": tree},
            message="已获取商品分类树形结构",
            summary=summary,
        )