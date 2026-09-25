"""
AI 智能客服系统 - 角色与权限管理 Tool

管理角色和权限，支持查询角色列表、详情、创建、更新、删除、查询所有权限。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"list", "all", "detail", "list_permissions"}


class RoleManageTool(BaseTool):
    """角色与权限管理 Tool

    管理角色和权限，支持查询角色列表、详情、创建、更新、删除、查询所有权限。

    使用场景：
    - 查询角色列表（支持分页和关键词搜索）
    - 获取所有角色（适合下拉选择）
    - 查看角色详情及其权限
    - 创建新角色并分配权限
    - 更新角色信息和权限
    - 删除角色
    - 查询系统所有可用权限
    """

    name = "role_manage"
    description = (
        "【触发】用户问'角色''权限''管理员''有哪些角色''创建角色''分配权限'时调用。"
        "【参数】action 必填：**只有 list / all / detail / list_permissions 四个只读 action**"
        "（B 端已只读化，issue #5247）。detail 需 role_id（来自 list/all）。"
        "【反例】管理员工账号用 employee_manage；查系统配置请引导用户到后台页面。"
        "【反例】建/改/删岗位**不在本工具能力内**——引导用户到后台「组织管理 → 岗位权限」页操作。"
        "【标注】READONLY — 纯查询，不含任何写 action"
    )
    # 权限码（admin-api 目录，issue #5291）：权限目录读端点 `AdminPermissionController` 已改挂
    # 岗位权限**读**码 `system:view`（写面 `PUT/DELETE /api/admin/roles` 仍是 `system:manage`）。
    # 该码在目录里只有 admin（RoleService 第 301 行「不含 system:manage —— 归 admin 专属（越权守卫）」）
    # ⇒ 实际放行面不变，只是不再靠角色名硬编码。
    required_permissions = ["system:view"]

    read_only = True
    read_only_actions = {"list", "all", "detail", "list_permissions"}  # 只读 action 免确认拦截

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：list（角色列表分页）/ all（所有角色）/ detail（角色详情）/ list_permissions（所有权限）—— 均为只读",
                "enum": ["list", "all", "detail", "list_permissions"],
            },
            "role_id": {
                "type": "string",
                "description": "角色 ID（detail/update/delete 时必填）",
            },
            "page": {
                "type": "integer",
                "description": "页码，默认 1（list 时可选）",
                "default": 1,
            },
            "size": {
                "type": "integer",
                "description": "每页数量，默认 10（list 时可选）",
                "default": 10,
            },
            "keyword": {
                "type": "string",
                "description": "搜索关键词（list 时可选）",
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        role_id: Optional[str] = None,
        page: int = 1,
        size: int = 10,
        keyword: Optional[str] = None,
        name: Optional[str] = None,
        code: Optional[str] = None,
        description: Optional[str] = None,
        permission_ids: Optional[List[str]] = None,
        **kwargs,
    ) -> ToolResult:
        """执行角色与权限管理操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行角色管理操作",
                suggestion="请联系管理员获取执行角色管理操作权限",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(sorted(VALID_ACTIONS))}",
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )

        try:
            if action == "list":
                return await self._list_roles(context, page, size, keyword)
            elif action == "all":
                return await self._all_roles(context)
            elif action == "detail":
                return await self._detail_role(context, role_id)
            elif action == "list_permissions":
                return await self._list_permissions(context)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )

        except Exception as e:
            logger.error(f"[role-manage] Error: action={action}, error={type(e).__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="角色管理操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    async def _list_roles(
        self,
        context: ToolContext,
        page: int,
        size: int,
        keyword: Optional[str],
    ) -> ToolResult:
        """查询角色列表（分页）"""
        page = int(page) if page else 1
        size = int(size) if size else 10

        params: Dict[str, Any] = {"page": page, "size": size}
        if keyword:
            params["keyword"] = keyword

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/roles",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="角色列表查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
        records = data.get("items", [])
        total = data.get("total", 0)

        roles = []
        for record in records:
            roles.append({
                "id": record.get("id"),
                "name": record.get("name"),
                "code": record.get("code"),
                "description": record.get("description"),
                "user_count": record.get("userCount"),
                "created_at": record.get("createdAt"),
            })

        logger.info(f"[role-manage] Listed {len(roles)} roles, total={total} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={
                "roles": roles,
                "total": total,
                "page": page,
                "size": size,
            },
            message=f"找到 {total} 个角色" if total > 0 else "未找到符合条件的角色",
        )

    async def _all_roles(self, context: ToolContext) -> ToolResult:
        """获取所有角色（适合下拉选择）"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/roles/all",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="获取角色列表失败",
                suggestion="请检查输入参数是否正确，或稍后重试",
            )

        data = response.get("data", [])
        logger.info(f"[role-manage] Got all {len(data)} roles | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"roles": data, "count": len(data)},
            message=f"共 {len(data)} 个角色",
        )

    async def _detail_role(
        self,
        context: ToolContext,
        role_id: Optional[str],
    ) -> ToolResult:
        """查询角色详情"""
        if not role_id:
            return ToolResult(
                success=False,
                error="缺少角色 ID",
                message="查询角色详情时必须提供角色 ID（role_id）",
                suggestion="缺少 role_id，请先用 role_manage 的 list 操作取到角色 ID 后重试",
            )

        client = get_admin_api_client()
        response = await client.get(
            f"/api/admin/roles/{role_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="角色详情查询失败",
                suggestion="请检查输入参数是否正确，或稍后重试",
            )

        data = response.get("data", {})
        logger.info(f"[role-manage] Detail role_id={role_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data=data,
            message=f"角色【{data.get('name', '')}】的详细信息",
        )
    async def _list_permissions(self, context: ToolContext) -> ToolResult:
        """查询所有可用权限"""

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/permissions",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="权限列表查询失败",
                suggestion="请检查输入参数是否正确，或稍后重试",
            )

        data = response.get("data", [])
        logger.info(f"[role-manage] Listed {len(data)} permissions | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"permissions": data, "count": len(data)},
            message=f"共 {len(data)} 个可用权限",
        )
