"""
AI 智能客服系统 - 商品分类管理 Tool

管理商品分类，包括获取分类树、创建分类、更新分类、删除分类。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import (
    admin_api_failure,
    BaseTool,
    permission_denied,
    ToolContext,
    ToolResult,
)
from app.utils.http_client import get_admin_api_client


# 操作类型（`create` = 建商品分类，issue #8618 接回；`tree` 一字未动）
VALID_ACTIONS = {"tree", "create"}

#: 只读 action —— 免确认拦截（`base_skill._requires_confirmation` 直接读这个字段）。
READ_ONLY_ACTIONS = frozenset({"tree"})

#: 写 action（走确认门禁）。改名 / 删除**有意不在此列**（issue #8618 边界）。
WRITE_ACTIONS = frozenset(VALID_ACTIONS - READ_ONLY_ACTIONS)


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
        "【参数】action 必填：tree（扁平分类列表，无父子概念，只读）/ create（建商品分类，写，需确认）。"
        "tree 返回的分类 id（长字符串如 88b6c50fbc...）用于按分类筛选商品。"
        "【反例】查商品/库存用 product_search / product_detail；分类 id ≠ 商品 id，不要混用。"
        "【确认】create 属写操作：调 interact(component=\"confirm\") 发确认卡，**卡面必须逐字带出分类名**；"
        "用户点卡后才调用，未确认的调用会被门禁拦下。分类是扁平结构（无父子概念），新建的分类直接出现在列表里。"
        "【反例】改分类名 / 删分类**不在本工具能力内**——如实说明并引导用户到后台"
        "「商品管理 → 分类管理」页面操作，不要承诺代为修改。"
        "【标注】WRITE — create 需确认；tree 免确认"
    )
    # 权限码（admin-api 目录，issue #5291）：分类**读**端点挂分类读码 `product:category:view`
    # （`CategoryController.getCategoryTree` 的方法级注解）；写面（`POST /api/admin/categories`）
    # 是类级 `product:category`。
    # 粗筛取两码并集（任一命中即可进入工具），**action 级复检**在 execute 内按端点注解收严
    # （防止仅持读码的岗位借黄金策建分类）。此前写死 ["admin","tenant_admin"] ⇒ operator /
    # product_manager 持码却被判「权限不足」（#4106 F4）。
    required_permissions = ["product:category:view", "product:category"]

    read_only = False
    read_only_actions = READ_ONLY_ACTIONS  # tree 免确认拦截
    requires_confirmation = True           # 写操作走既有确认门禁（#8618；不自建第二套）
    destructive = False                    # 不含改名/删除（那两类不在能力内）
    idempotent = False   # create 非幂等：重放会建出第二个同名分类

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：tree（获取分类列表，只读）/ create（新建商品分类，写，需确认）",
                "enum": ["tree", "create"],
            },
            "category_id": {
                "type": "string",
                "description": "分类 ID（update/delete 时必填）",
            },
            "name": {
                "type": "string",
                "description": "分类名称（create 时必填）",
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
        # 权限检查（粗粒度：required_permissions 任一命中即可进入工具）
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行分类管理操作",
                suggestion="请联系管理员获取执行分类管理操作权限",
            )

        # 细粒度权限（与 `CategoryController` 的 `@RequirePermission` 逐端点对齐）：
        # tree 要 product:category:view，create（POST /api/admin/categories）要 product:category。
        # 防的是「只持分类读码的岗位」借黄金策建分类。
        required = "product:category:view" if action in self.read_only_actions else "product:category"
        if "*" not in (context.permissions or []) and required not in (context.permissions or []):
            return permission_denied(
                message=f"您没有权限执行该分类操作（缺少权限：{required}）",
                suggestion=(
                    "请联系管理员在「岗位权限」中为您开通商品分类的相应权限"
                    f"（{'查看' if required == 'product:category:view' else '管理'}分类）"
                ),
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
            elif action == "create":
                return await self._create_category(context, name)
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
    async def _create_category(self, context: ToolContext, name: Optional[str]) -> ToolResult:
        """创建分类（扁平结构，无父子概念，issue #2905）

        端点 `POST /api/admin/categories`（类级 `@RequirePermission("product:category")`）。
        本地先拦缺名（§31 P4：说清缺哪个字段、该做什么），不把服务端 422 直接甩给模型。
        """
        if not name:
            return ToolResult(
                success=False,
                error="缺少分类名称",
                message="创建分类时必须提供 name",
                suggestion="缺少分类名称 name，请向用户询问分类名称后重试",
            )

        json_data: Dict[str, Any] = {"name": name}

        logger.info(
            f"[category-manage] Create: name={name} | tenant={context.tenant_id}"
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
            return admin_api_failure(response,
                error=error_msg,
                message=f"创建分类失败：{error_msg}",
                suggestion="请先用 category_manage 的 tree 操作确认是否已有同名分类，再换一个名称后重试",
            )

        data = response.get("data", {}) or {}
        return ToolResult(
            success=True,
            data=data,
            message=f"分类「{name}」创建成功",
        )
