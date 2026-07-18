"""
AI 智能客服系统 - 客服会话管理 Tool

管理客服会话，包括查询列表、监控面板、会话详情、手动分配、结束会话。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"list", "monitor", "detail", "assign", "end"}


class SessionManageTool(BaseTool):
    """客服会话管理 Tool

    管理客服会话：查询会话列表、获取监控面板数据、查看详情、手动分配、结束会话。

    使用场景：
    - 查看当前所有客服会话列表
    - 获取客服监控面板统计数据（在线客服数、排队人数等）
    - 查看某个会话的详细信息
    - 将会话手动分配给指定客服
    - 结束某个会话
    """

    name = "session_manage"
    description = (
        "【触发】用户说'会话列表''排队多少人''在线客服''客服情况''分配会话''结束会话'时调用。【前置】list/monitor/detail 查。assign 需 session_id+agent_id。end 需确认。【何时不用】经营概况用 dashboard_stats。查客服员工用 employee_manage。【标注】WRITE(assign/end) — 查询安全，写需确认"
    )
    allowed_roles = ["admin", "agent", "tenant_admin"]

    read_only = False
    destructive = False  # 分配/结束会话非破坏性（可重新分配）
    idempotent = False   # 分配/结束非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：list（会话列表）/ monitor（监控面板）/ detail（会话详情）/ assign（分配会话）/ end（结束会话）",
                "enum": ["list", "monitor", "detail", "assign", "end"],
            },
            "session_id": {
                "type": "string",
                "description": "会话 ID（detail/assign/end 时必填）",
            },
            "employee_id": {
                "type": "string",
                "description": "客服员工 ID（assign 时必填，list 时可选用于筛选）",
            },
            "status": {
                "type": "string",
                "description": "会话状态筛选（list 时可选）",
            },
            "keyword": {
                "type": "string",
                "description": "搜索关键词（list 时可选）",
            },
            "page": {
                "type": "integer",
                "description": "页码，默认 1",
                "default": 1,
            },
            "size": {
                "type": "integer",
                "description": "每页数量，默认 10",
                "default": 10,
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        session_id: Optional[str] = None,
        employee_id: Optional[str] = None,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        size: int = 10,
    ) -> ToolResult:
        """执行客服会话管理操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行会话管理操作",
                suggestion="请联系管理员获取执行会话管理操作权限",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
            )

        try:
            if action == "list":
                return await self._list_sessions(context, page, size, status, employee_id, keyword)
            elif action == "monitor":
                return await self._get_monitor(context)
            elif action == "detail":
                return await self._get_detail(context, session_id)
            elif action == "assign":
                return await self._assign_session(context, session_id, employee_id)
            elif action == "end":
                return await self._end_session(context, session_id)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )

        except Exception as e:
            logger.error(f"[session-manage] Failed: action={action}, error={type(e).__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="会话管理操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    async def _list_sessions(
        self,
        context: ToolContext,
        page: int,
        size: int,
        status: Optional[str],
        employee_id: Optional[str],
        keyword: Optional[str],
    ) -> ToolResult:
        """查询会话列表"""
        page = int(page) if page else 1
        size = int(size) if size else 10

        params: Dict[str, Any] = {"page": page, "size": size}
        if status:
            params["status"] = status
        if employee_id:
            params["employeeId"] = employee_id
        if keyword:
            params["keyword"] = keyword

        logger.info(
            f"[session-manage] List: status={status}, employee_id={employee_id}, "
            f"keyword={keyword}, page={page}, size={size} | tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/agent-sessions",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"查询会话列表失败：{error_msg}",
            )

        data = response.get("data", {}) or {}
        records = data.get("items") or data.get("records") or []
        total = data.get("total", len(records))

        return ToolResult(
            success=True,
            data={
                "items": records,
                "total": total,
                "page": page,
                "size": size,
            },
            message=f"共找到 {total} 个会话",
        )

    async def _get_monitor(self, context: ToolContext) -> ToolResult:
        """获取监控面板数据"""
        logger.info(f"[session-manage] Monitor | tenant={context.tenant_id}")

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/agent-sessions/monitor",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"获取监控面板数据失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data=response.get("data", {}),
            message="已获取客服监控面板数据",
        )

    async def _get_detail(self, context: ToolContext, session_id: Optional[str]) -> ToolResult:
        """查看会话详情"""
        if not session_id:
            return ToolResult(
                success=False,
                error="缺少会话 ID",
                message="查看会话详情时必须提供 session_id",
            )

        logger.info(f"[session-manage] Detail: session_id={session_id} | tenant={context.tenant_id}")

        client = get_admin_api_client()
        response = await client.get(
            f"/api/admin/agent-sessions/{session_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"查询会话详情失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data=response.get("data", {}),
            message="已获取会话详情",
        )

    async def _assign_session(
        self, context: ToolContext, session_id: Optional[str], employee_id: Optional[str]
    ) -> ToolResult:
        """手动分配会话"""
        if not session_id:
            return ToolResult(
                success=False,
                error="缺少会话 ID",
                message="分配会话时必须提供 session_id",
            )
        if not employee_id:
            return ToolResult(
                success=False,
                error="缺少客服员工 ID",
                message="分配会话时必须提供 employee_id",
            )

        logger.info(
            f"[session-manage] Assign: session_id={session_id}, employee_id={employee_id} "
            f"| tenant={context.tenant_id}"
        )

        client = get_admin_api_client()
        response = await client.post(
            f"/api/admin/agent-sessions/{session_id}/assign",
            json_data={"employeeId": employee_id},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "分配失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"分配会话失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"session_id": session_id, "employee_id": employee_id},
            message=f"会话已分配给客服 {employee_id}",
        )

    async def _end_session(self, context: ToolContext, session_id: Optional[str]) -> ToolResult:
        """结束会话"""
        if not session_id:
            return ToolResult(
                success=False,
                error="缺少会话 ID",
                message="结束会话时必须提供 session_id",
            )

        logger.info(f"[session-manage] End: session_id={session_id} | tenant={context.tenant_id}")

        client = get_admin_api_client()
        response = await client.post(
            f"/api/admin/agent-sessions/{session_id}/end",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "结束失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"结束会话失败：{error_msg}",
            )

        return ToolResult(
            success=True,
            data={"session_id": session_id},
            message="会话已结束",
        )
