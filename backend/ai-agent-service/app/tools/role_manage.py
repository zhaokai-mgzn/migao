"""
AI 智能客服系统 - 角色与权限管理 Tool

管理角色和权限，支持查询角色列表、详情、创建、更新、删除、查询所有权限。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"list", "all", "detail", "create", "update", "delete", "list_permissions"}


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
        "【触发】用户问'角色''权限''管理员''有哪些角色''创建角色''分配权限'时调用。【前置】list/all 可查询。create/update 需要 name + permission_ids。delete 需二次确认。【反例】管理员工账号用 employee_manage。查系统配置用 settings_manage。【标注】WRITE|DESTRUCTIVE — 删除角色/修改权限需二次确认"
    )
    allowed_roles = ["admin", "tenant_admin"]

    read_only = False
    destructive = True   # 可删除角色、修改权限
    idempotent = False   # 创建/删除非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：list（角色列表分页）/ all（所有角色）/ detail（角色详情）/ create（创建角色）/ update（更新角色）/ delete（删除角色）/ list_permissions（所有权限）",
                "enum": ["list", "all", "detail", "create", "update", "delete", "list_permissions"],
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
            "name": {
                "type": "string",
                "description": "角色名称（create/update 时使用）",
            },
            "code": {
                "type": "string",
                "description": "角色编码（create 时使用）",
            },
            "description": {
                "type": "string",
                "description": "角色描述（create/update 时可选）",
            },
            "permission_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "权限 ID 列表（create/update 时可选）",
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
            )

        try:
            if action == "list":
                return await self._list_roles(context, page, size, keyword)
            elif action == "all":
                return await self._all_roles(context)
            elif action == "detail":
                return await self._detail_role(context, role_id)
            elif action == "create":
                return await self._create_role(context, name, code, description, permission_ids)
            elif action == "update":
                return await self._update_role(context, role_id, name, description, permission_ids)
            elif action == "delete":
                return await self._delete_role(context, role_id)
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
            return ToolResult(
                success=False,
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
            return ToolResult(
                success=False,
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
            )

        client = get_admin_api_client()
        response = await client.get(
            f"/api/admin/roles/{role_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
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

    async def _create_role(
        self,
        context: ToolContext,
        name: Optional[str],
        code: Optional[str],
        description: Optional[str],
        permission_ids: Optional[List[str]],
    ) -> ToolResult:
        """创建角色"""
        if not name:
            return ToolResult(
                success=False,
                error="缺少角色名称",
                message="创建角色时必须提供角色名称（name）",
            )
        if not code:
            return ToolResult(
                success=False,
                error="缺少角色编码",
                message="创建角色时必须提供角色编码（code）",
            )

        json_data: Dict[str, Any] = {
            "name": name,
            "code": code,
        }
        if description:
            json_data["description"] = description
        if permission_ids:
            json_data["permissionIds"] = permission_ids

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/roles",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "创建失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"创建角色失败：{error_msg}",
            )

        data = response.get("data", {})
        logger.info(f"[role-manage] Created role: name={name}, code={code} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data=data,
            message=f"角色【{name}】已创建",
        )

    async def _update_role(
        self,
        context: ToolContext,
        role_id: Optional[str],
        name: Optional[str],
        description: Optional[str],
        permission_ids: Optional[List[str]],
    ) -> ToolResult:
        """更新角色"""
        if not role_id:
            return ToolResult(
                success=False,
                error="缺少角色 ID",
                message="更新角色时必须提供角色 ID（role_id）",
            )

        json_data: Dict[str, Any] = {}
        if name:
            json_data["name"] = name
        if description:
            json_data["description"] = description
        if permission_ids is not None:
            json_data["permissionIds"] = permission_ids

        if not json_data:
            return ToolResult(
                success=False,
                error="缺少更新内容",
                message="更新角色时必须提供至少一个字段（name/description/permission_ids）",
            )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/roles/{role_id}",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"更新角色失败：{error_msg}",
            )

        logger.info(f"[role-manage] Updated role_id={role_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"role_id": role_id},
            message="角色已更新",
        )

    async def _delete_role(
        self,
        context: ToolContext,
        role_id: Optional[str],
    ) -> ToolResult:
        """删除角色"""
        if not role_id:
            return ToolResult(
                success=False,
                error="缺少角色 ID",
                message="删除角色时必须提供角色 ID（role_id）",
            )

        client = get_admin_api_client()
        response = await client.delete(
            f"/api/admin/roles/{role_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "删除失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"删除角色失败：{error_msg}",
            )

        logger.info(f"[role-manage] Deleted role_id={role_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"role_id": role_id},
            message="角色已删除",
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
            return ToolResult(
                success=False,
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
