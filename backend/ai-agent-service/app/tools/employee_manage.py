"""
AI 智能客服系统 - 员工管理 Tool

管理员工账号，支持查询员工列表、详情、创建、更新、删除、重置密码、启用/禁用。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"list", "detail", "create", "update", "delete", "reset_password", "toggle_status"}


class EmployeeManageTool(BaseTool):
    """员工管理 Tool

    管理员工账号，支持查询员工列表、详情、创建、更新、删除、重置密码、启用/禁用。

    使用场景：
    - 查询员工列表（按关键词、状态、角色筛选）
    - 查看员工详细信息
    - 创建新员工账号
    - 更新员工信息
    - 删除员工
    - 重置员工密码
    - 启用或禁用员工账号
    """

    name = "employee_manage"
    description = (
        "员工管理工具，支持查询员工列表、详情、创建、更新、删除、重置密码、启用/禁用。"
        "当需要管理员工账号、查看员工信息、调整员工状态时使用。"
    )

    # 仅 admin、tenant_admin 可使用
    allowed_roles = ["admin", "tenant_admin"]

    read_only = False
    destructive = True   # 可删除员工、重置密码、禁用账号
    idempotent = False   # 创建/删除非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：list（员工列表）/ detail（员工详情）/ create（创建员工）/ update（更新员工）/ delete（删除员工）/ reset_password（重置密码）/ toggle_status（启用/禁用）",
                "enum": ["list", "detail", "create", "update", "delete", "reset_password", "toggle_status"],
            },
            "user_id": {
                "type": "string",
                "description": "员工用户 ID（detail/update/delete/reset_password/toggle_status 时必填）",
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
                "description": "搜索关键词，支持姓名、手机号（list 时可选）",
            },
            "status": {
                "type": "string",
                "description": "状态筛选：active/disabled（list/toggle_status 时可选）",
                "enum": ["active", "disabled"],
            },
            "role": {
                "type": "string",
                "description": "角色筛选（list 时可选）",
            },
            "phone": {
                "type": "string",
                "description": "手机号（create/update 时使用）",
            },
            "password": {
                "type": "string",
                "description": "密码（create/update 时使用）",
            },
            "name": {
                "type": "string",
                "description": "姓名（create/update 时使用）",
            },
            "role_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "角色 ID 列表（create 时使用）",
            },
            "avatar": {
                "type": "string",
                "description": "头像 URL（update 时可选）",
            },
            "new_password": {
                "type": "string",
                "description": "新密码（reset_password 时可选，不填则随机生成）",
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        user_id: Optional[str] = None,
        page: int = 1,
        size: int = 10,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        role: Optional[str] = None,
        phone: Optional[str] = None,
        password: Optional[str] = None,
        name: Optional[str] = None,
        role_ids: Optional[List[str]] = None,
        avatar: Optional[str] = None,
        new_password: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """执行员工管理操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行员工管理操作",
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
                return await self._list_users(context, page, size, keyword, status, role)
            elif action == "detail":
                return await self._detail_user(context, user_id)
            elif action == "create":
                return await self._create_user(context, phone, password, name, role_ids)
            elif action == "update":
                return await self._update_user(context, user_id, name, phone, password, avatar, role)
            elif action == "delete":
                return await self._delete_user(context, user_id)
            elif action == "reset_password":
                return await self._reset_password(context, user_id, new_password)
            elif action == "toggle_status":
                return await self._toggle_status(context, user_id, status)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                )

        except Exception as e:
            logger.error(f"[employee-manage] Error: action={action}, error={type(e).__name__}: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                message="员工管理操作失败，请稍后重试",
            )

    async def _list_users(
        self,
        context: ToolContext,
        page: int,
        size: int,
        keyword: Optional[str],
        status: Optional[str],
        role: Optional[str],
    ) -> ToolResult:
        """查询员工列表"""
        page = int(page) if page else 1
        size = int(size) if size else 10

        params: Dict[str, Any] = {"page": page, "size": size}
        if keyword:
            params["keyword"] = keyword
        if status:
            params["status"] = status
        if role:
            params["role"] = role

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/users",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message="员工列表查询失败，请稍后重试",
            )

        data = response.get("data", {})
        records = data.get("items", [])
        total = data.get("total", 0)

        users = []
        for record in records:
            users.append({
                "id": record.get("id"),
                "name": record.get("name"),
                "phone": record.get("phone"),
                "status": record.get("status"),
                "roles": record.get("roles", []),
                "created_at": record.get("createdAt"),
            })

        logger.info(f"[employee-manage] Listed {len(users)} users, total={total} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={
                "users": users,
                "total": total,
                "page": page,
                "size": size,
            },
            message=f"找到 {total} 个员工" if total > 0 else "未找到符合条件的员工",
        )

    async def _detail_user(
        self,
        context: ToolContext,
        user_id: Optional[str],
    ) -> ToolResult:
        """查询员工详情"""
        if not user_id:
            return ToolResult(
                success=False,
                error="缺少员工 ID",
                message="查询员工详情时必须提供员工 ID（user_id）",
            )

        client = get_admin_api_client()
        response = await client.get(
            f"/api/admin/users/{user_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message="员工详情查询失败",
            )

        data = response.get("data", {})
        logger.info(f"[employee-manage] Detail user_id={user_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data=data,
            message=f"员工【{data.get('name', '')}】的详细信息",
        )

    async def _create_user(
        self,
        context: ToolContext,
        phone: Optional[str],
        password: Optional[str],
        name: Optional[str],
        role_ids: Optional[List[str]],
    ) -> ToolResult:
        """创建员工"""
        if not phone:
            return ToolResult(
                success=False,
                error="缺少手机号",
                message="创建员工时必须提供手机号（phone）",
            )
        if not password:
            return ToolResult(
                success=False,
                error="缺少密码",
                message="创建员工时必须提供密码（password）",
            )
        if not name:
            return ToolResult(
                success=False,
                error="缺少姓名",
                message="创建员工时必须提供姓名（name）",
            )

        json_data: Dict[str, Any] = {
            "phone": phone,
            "password": password,
            "name": name,
        }
        if role_ids:
            json_data["roleIds"] = role_ids

        client = get_admin_api_client()
        response = await client.post(
            "/api/admin/users",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "创建失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"创建员工失败：{error_msg}",
            )

        data = response.get("data", {})
        logger.info(f"[employee-manage] Created user: name={name}, phone={phone} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data=data,
            message=f"员工【{name}】已创建",
        )

    async def _update_user(
        self,
        context: ToolContext,
        user_id: Optional[str],
        name: Optional[str],
        phone: Optional[str],
        password: Optional[str],
        avatar: Optional[str],
        role: Optional[str],
    ) -> ToolResult:
        """更新员工信息"""
        if not user_id:
            return ToolResult(
                success=False,
                error="缺少员工 ID",
                message="更新员工时必须提供员工 ID（user_id）",
            )

        json_data: Dict[str, Any] = {}
        if name:
            json_data["name"] = name
        if phone:
            json_data["phone"] = phone
        if password:
            json_data["password"] = password
        if avatar:
            json_data["avatar"] = avatar
        if role:
            json_data["role"] = role

        if not json_data:
            return ToolResult(
                success=False,
                error="缺少更新内容",
                message="更新员工时必须提供至少一个字段（name/phone/password/avatar/role）",
            )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/users/{user_id}",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"更新员工失败：{error_msg}",
            )

        logger.info(f"[employee-manage] Updated user_id={user_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"user_id": user_id},
            message="员工信息已更新",
        )

    async def _delete_user(
        self,
        context: ToolContext,
        user_id: Optional[str],
    ) -> ToolResult:
        """删除员工"""
        if not user_id:
            return ToolResult(
                success=False,
                error="缺少员工 ID",
                message="删除员工时必须提供员工 ID（user_id）",
            )

        client = get_admin_api_client()
        response = await client.delete(
            f"/api/admin/users/{user_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "删除失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"删除员工失败：{error_msg}",
            )

        logger.info(f"[employee-manage] Deleted user_id={user_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"user_id": user_id},
            message="员工已删除",
        )

    async def _reset_password(
        self,
        context: ToolContext,
        user_id: Optional[str],
        new_password: Optional[str],
    ) -> ToolResult:
        """重置员工密码"""
        if not user_id:
            return ToolResult(
                success=False,
                error="缺少员工 ID",
                message="重置密码时必须提供员工 ID（user_id）",
            )

        json_data: Dict[str, Any] = {}
        if new_password:
            json_data["newPassword"] = new_password

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/users/{user_id}/reset-password",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "重置失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"重置密码失败：{error_msg}",
            )

        logger.info(f"[employee-manage] Reset password for user_id={user_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"user_id": user_id},
            message="密码已重置",
        )

    async def _toggle_status(
        self,
        context: ToolContext,
        user_id: Optional[str],
        status: Optional[str],
    ) -> ToolResult:
        """启用/禁用员工"""
        if not user_id:
            return ToolResult(
                success=False,
                error="缺少员工 ID",
                message="切换状态时必须提供员工 ID（user_id）",
            )
        if not status or status not in ("active", "disabled"):
            return ToolResult(
                success=False,
                error="无效的状态值",
                message="切换状态时必须提供状态（status），可选：active / disabled",
            )

        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/users/{user_id}/status",
            json_data={"status": status},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "操作失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"切换员工状态失败：{error_msg}",
            )

        status_text = "启用" if status == "active" else "禁用"
        logger.info(f"[employee-manage] Toggled user_id={user_id} to {status} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"user_id": user_id, "status": status},
            message=f"员工已{status_text}",
        )
