"""
AI 智能客服系统 - 订单跟进状态 Tool

查询或更新订单的跟进状态，支持查看跟进统计。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 有效的跟进状态
VALID_FOLLOW_STATUSES = {"pending", "following", "completed"}

# 操作类型
VALID_ACTIONS = {"query", "update", "stats"}


class OrderFollowStatusTool(BaseTool):
    """订单跟进状态管理 Tool
    
    查询或更新订单的跟进状态，支持查看跟进统计。
    
    使用场景：
    - 商家想知道某个订单的跟进进度
    - 商家要更新订单的跟进状态（待跟进→跟进中→已完成）
    - 商家想看所有订单的跟进情况统计
    """
    
    name = "manage_order_follow_status"
    description = (
        "查询或更新订单的跟进状态，支持查看跟进统计。"
        "当需要查看订单跟进进度、标记订单为已跟进/跟进中/已完成、或查看跟进统计数据时使用。"
    )
    
    # admin、agent、tenant_admin 可使用
    allowed_roles = ["admin", "agent", "tenant_admin"]
    
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：query（查询跟进状态）/ update（更新跟进状态）/ stats（跟进统计）",
                "enum": ["query", "update", "stats"],
            },
            "order_id": {
                "type": "string",
                "description": "订单 ID（query/update 时必填）",
            },
            "new_status": {
                "type": "string",
                "description": "新的跟进状态（update 时必填）：pending（待跟进）/ following（跟进中）/ completed（已完成）",
                "enum": ["pending", "following", "completed"],
            },
        },
        "required": ["action"],
    }
    
    async def execute(
        self,
        context: ToolContext,
        action: str,
        order_id: Optional[str] = None,
        new_status: Optional[str] = None,
    ) -> ToolResult:
        """执行订单跟进状态操作
        
        Args:
            context: Tool 执行上下文
            action: 操作类型（query/update/stats）
            order_id: 订单 ID
            new_status: 新的跟进状态
            
        Returns:
            ToolResult: 操作结果
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限管理订单跟进状态",
            )
        
        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
            )
        
        try:
            if action == "query":
                return await self._query_follow_status(context, order_id)
            elif action == "update":
                return await self._update_follow_status(context, order_id, new_status)
            elif action == "stats":
                return await self._get_follow_stats(context)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                )
                
        except Exception as e:
            logger.error(
                f"[order-follow-status] Failed: action={action}, order_id={order_id}, "
                f"error={type(e).__name__}: {e} | tenant={context.tenant_id}"
            )
            return ToolResult(
                success=False,
                error=str(e),
                message="订单跟进状态操作失败，请稍后重试",
            )
    
    async def _query_follow_status(
        self,
        context: ToolContext,
        order_id: Optional[str],
    ) -> ToolResult:
        """查询订单跟进状态"""
        if not order_id:
            return ToolResult(
                success=False,
                error="缺少订单 ID",
                message="查询跟进状态时必须提供订单 ID（order_id）",
            )
        
        client = get_admin_api_client()
        response = await client.get(
            f"/api/admin/orders/{order_id}/follow-status",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"查询订单跟进状态失败：{error_msg}",
            )
        
        data = response.get("data", {})
        follow_status = data.get("followStatus") or data.get("follow_status", "pending")
        updated_at = data.get("updatedAt") or data.get("updated_at", "")
        
        status_labels = {
            "pending": "待跟进",
            "following": "跟进中",
            "completed": "已完成",
        }
        
        logger.info(
            f"[order-follow-status] Query: order_id={order_id}, status={follow_status} | tenant={context.tenant_id}"
        )
        
        return ToolResult(
            success=True,
            data={
                "order_id": order_id,
                "follow_status": follow_status,
                "follow_status_label": status_labels.get(follow_status, follow_status),
                "updated_at": updated_at,
            },
            message=f"订单 {order_id} 的跟进状态为：{status_labels.get(follow_status, follow_status)}",
        )
    
    async def _update_follow_status(
        self,
        context: ToolContext,
        order_id: Optional[str],
        new_status: Optional[str],
    ) -> ToolResult:
        """更新订单跟进状态"""
        if not order_id:
            return ToolResult(
                success=False,
                error="缺少订单 ID",
                message="更新跟进状态时必须提供订单 ID（order_id）",
            )
        
        if not new_status:
            return ToolResult(
                success=False,
                error="缺少新状态",
                message="更新跟进状态时必须提供新状态（new_status）：pending/following/completed",
            )
        
        if new_status not in VALID_FOLLOW_STATUSES:
            return ToolResult(
                success=False,
                error=f"无效的跟进状态: {new_status}",
                message=f"不支持的跟进状态，可选：{', '.join(VALID_FOLLOW_STATUSES)}",
            )
        
        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/orders/{order_id}/follow-status",
            json_data={"followStatus": new_status},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"更新订单跟进状态失败：{error_msg}",
            )
        
        status_labels = {
            "pending": "待跟进",
            "following": "跟进中",
            "completed": "已完成",
        }
        
        logger.info(
            f"[order-follow-status] Updated: order_id={order_id}, new_status={new_status} | "
            f"tenant={context.tenant_id}, user={context.user_id}"
        )
        
        return ToolResult(
            success=True,
            data={"order_id": order_id, "follow_status": new_status},
            message=f"订单 {order_id} 的跟进状态已更新为：{status_labels.get(new_status, new_status)}",
        )
    
    async def _get_follow_stats(self, context: ToolContext) -> ToolResult:
        """获取跟进状态统计"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/orders/follow-status/stats",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"查询跟进统计失败：{error_msg}",
            )
        
        data = response.get("data", {})
        
        pending = data.get("pending", 0)
        following = data.get("following", 0)
        completed = data.get("completed", 0)
        total = data.get("total", pending + following + completed)
        
        logger.info(
            f"[order-follow-status] Stats: pending={pending}, following={following}, "
            f"completed={completed} | tenant={context.tenant_id}"
        )
        
        return ToolResult(
            success=True,
            data={
                "total": total,
                "pending": pending,
                "following": following,
                "completed": completed,
            },
            message=(
                f"订单跟进统计：共 {total} 单，"
                f"待跟进 {pending} 单，跟进中 {following} 单，已完成 {completed} 单"
            ),
        )
