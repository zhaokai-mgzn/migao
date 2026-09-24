"""
AI 智能客服系统 - 员工管理 Tool

管理员工账号，支持查询员工列表、详情、创建、更新、删除、重置密码、启用/禁用。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import (
    admin_api_failure,
    BaseTool,
    ToolContext,
    ToolResult,
    permission_denied,
)
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"list", "detail"}


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
        "【触发】用户问'员工''客服''账号''同事''有哪些人''谁在岗'时调用。"
        "【参数】action 必填：**只有 list（可按 keyword/status/role 过滤 + 分页）/ detail（需 user_id）两个只读 action**"
        "（B 端已只读化，issue #5247）。"
        "【反例】管理角色权限用 role_manage；查客户用 customer_manage。"
        "【反例】建账号/改资料/禁用/删除/重置密码**不在本工具能力内**——引导用户到后台「组织管理 → 员工管理」页操作。"
        "【标注】READONLY — 纯查询，不含任何写 action"
    )
    # 权限码（admin-api 目录）：AdminUserController 类级 `@RequirePermission("employee:list")`，
    # 写操作（PUT/DELETE/reset-password/status）为 `employee:create`。
    # 具体 action 的权限在 execute 内二次校验，防止仅 employee:list 者执行写操作。
    # 不再用 allowed_roles —— 手写角色白名单会与目录漂移（#4106 F4）。
    required_permissions = ["employee:list"]  # B 端只读化（#5247）：写码 employee:create 已随写 action 移除
    read_only = True
    read_only_actions = {"list", "detail"}  # 只读 action 免确认拦截

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：list（员工列表）/ detail（员工详情）—— 均为只读",
                "enum": ["list", "detail"],
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
        # 权限检查（粗粒度：角色 + required_permissions 任一命中）
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行员工管理操作",
                suggestion="请联系管理员获取执行员工管理操作权限",
            )

        # 细粒度权限：查询类 action 需要 employee:list，写操作需要 employee:create。
        # 与后端 AdminUserController 的 @RequirePermission 口径一致，防止仅 employee:list
        # 的员工通过米宝执行创建/删除/重置密码等写操作。
        required = "employee:list"  # B 端只读化（issue #5247）：本工具只剩查询 action
        if "*" not in (context.permissions or []) and required not in (context.permissions or []):
            # 门禁**之外**的动作级拒绝 ⇒ 必须自己走共享构造点带码（issue #4147 G2；
            # 被 L0 静态锁 tests/test_tool_denial_semantics.py 覆盖）。
            return permission_denied(
                message="您没有权限执行该员工操作",
                suggestion=(
                    "请联系管理员在「员工管理」中为您开通相应权限"
                    f"（{'查询' if required == 'employee:list' else '管理'}员工）"
                ),
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
                return await self._list_users(context, page, size, keyword, status, role)
            elif action == "detail":
                return await self._detail_user(context, user_id)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )

        except Exception as e:
            logger.error(f"[employee-manage] Error: action={action}, error={type(e).__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="员工管理操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
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
            return admin_api_failure(response,
                error=error_msg,
                message="员工列表查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
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
                suggestion="缺少 user_id，请先用 employee_manage 的 list 操作查到该员工后再重试",
            )

        client = get_admin_api_client()
        response = await client.get(
            f"/api/admin/users/{user_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="员工详情查询失败",
                suggestion="请检查输入参数是否正确，或稍后重试",
            )

        data = response.get("data", {})
        logger.info(f"[employee-manage] Detail user_id={user_id} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data=data,
            message=f"员工【{data.get('name', '')}】的详细信息",
        )