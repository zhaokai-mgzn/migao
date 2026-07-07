"""
AI 智能客服系统 - 订单管理 Tool

执行订单管理操作，包括更新状态、更新物流信息、取消订单、确认支付、退款。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 允许的订单状态
VALID_ORDER_STATUSES = {
    "pending", "confirmed", "processing", "shipped", "completed", "cancelled",
}

# 操作类型
VALID_ACTIONS = {"update_status", "update_logistics", "cancel", "confirm_payment", "refund"}


class OrderManageTool(BaseTool):
    """订单管理 Tool
    
    执行订单管理操作：更新状态、更新物流信息、取消订单、确认支付、退款。
    
    使用场景：
    - 客服更新订单状态（如确认订单、标记发货）
    - 客服录入物流信息（快递公司、运单号）
    - 客服取消订单
    - 客服确认客户已支付
    - 客服发起退款
    """
    
    name = "order_manage"
    description = (
        "【触发】用户说'取消订单''退款''修改订单''标记发货''更新物流''确认支付'时调用。【前置】需要 action + order_id。cancel/refund 是破坏性操作，必须二次确认。【反例】仅查看订单用 order_query。创建新订单用 order_create。【标注】WRITE|DESTRUCTIVE — 取消/退款前必须二次确认"
    )
    
    # admin、agent、tenant_admin 可使用    allowed_roles = ["admin", "agent", "tenant_admin"]

    read_only = False
    destructive = True   # 可取消/退款订单
    idempotent = False   # 取消/退款非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：update_status（更新状态）/ update_logistics（更新物流）/ cancel（取消订单）/ confirm_payment（确认支付）/ refund（退款）",
                "enum": ["update_status", "update_logistics", "cancel", "confirm_payment", "refund"],
            },
            "order_id": {
                "type": "string",
                "description": "订单 ID",
            },
            "status": {
                "type": "string",
                "description": "新状态（update_status 时必填）：pending=待付款, confirmed=待发货, processing=生产中, shipped=已发货, completed=已完成, cancelled=已关闭",
                "enum": ["pending", "confirmed", "processing", "shipped", "completed", "cancelled"],
            },
            "logistics_company": {
                "type": "string",
                "description": "快递公司（update_logistics 时必填）",
            },
            "tracking_number": {
                "type": "string",
                "description": "运单号（update_logistics 时必填）",
            },
            "cancel_reason": {
                "type": "string",
                "description": "取消原因（cancel 时可选）",
            },
            "refund_amount": {
                "type": "number",
                "description": "退款金额（refund 时可选，不填则为全额退款）",
            },
            "refund_reason": {
                "type": "string",
                "description": "退款原因（refund 时可选）",
            },
        },
        "required": ["action", "order_id"],
    }
    
    async def execute(
        self,
        context: ToolContext,
        action: str,
        order_id: str,
        status: Optional[str] = None,
        logistics_company: Optional[str] = None,
        tracking_number: Optional[str] = None,
        cancel_reason: Optional[str] = None,
        refund_amount: Optional[float] = None,
        refund_reason: Optional[str] = None,
    ) -> ToolResult:
        """执行订单管理操作

        Args:
            context: Tool 执行上下文
            action: 操作类型
            order_id: 订单 ID
            status: 新状态（update_status 时必填）
            logistics_company: 快递公司（update_logistics 时必填）
            tracking_number: 运单号（update_logistics 时必填）
            cancel_reason: 取消原因（cancel 时可选）
            refund_amount: 退款金额（refund 时可选）
            refund_reason: 退款原因（refund 时可选）
            
        Returns:
            ToolResult: 操作结果
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行订单管理操作",
            )
        
        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
            )
        
        if not order_id:
            return ToolResult(
                success=False,
                error="缺少订单 ID",
                message="请提供订单 ID",
            )
        
        try:
            if action == "update_status":
                return await self._update_status(context, order_id, status)
            elif action == "update_logistics":
                return await self._update_logistics(
                    context, order_id, logistics_company, tracking_number
                )
            elif action == "cancel":
                return await self._cancel_order(context, order_id, cancel_reason)
            elif action == "confirm_payment":
                return await self._confirm_payment(context, order_id)
            elif action == "refund":
                return await self._refund_order(context, order_id, refund_amount, refund_reason)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                )
                
        except Exception as e:
            logger.error(f"Order manage error: action={action}, order_id={order_id}, error={e}")
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="订单操作失败，请稍后重试",
            )
    
    async def _update_status(
        self,
        context: ToolContext,
        order_id: str,
        status: Optional[str],
    ) -> ToolResult:
        """更新订单状态
        
        Args:
            context: Tool 执行上下文
            order_id: 订单 ID
            status: 新状态
            
        Returns:
            ToolResult: 操作结果
        """
        if not status:
            return ToolResult(
                success=False,
                error="缺少状态参数",
                message="更新状态时必须提供新状态（status）",
            )
        
        if status not in VALID_ORDER_STATUSES:
            return ToolResult(
                success=False,
                error=f"无效的订单状态: {status}",
                message=f"不支持的状态值，可选：{', '.join(VALID_ORDER_STATUSES)}",
            )
        
        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/orders/{order_id}/status",
            json_data={"status": status},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"更新订单状态失败：{error_msg}",
            )
        
        logger.info(
            f"Order status updated: order_id={order_id}, status={status}, "
            f"tenant={context.tenant_id}, user={context.user_id}"
        )
        
        return ToolResult(
            success=True,
            data={"order_id": order_id, "status": status},
            message=f"订单状态已更新为「{status}」",
        )
    
    async def _update_logistics(
        self,
        context: ToolContext,
        order_id: str,
        logistics_company: Optional[str],
        tracking_number: Optional[str],
    ) -> ToolResult:
        """更新物流信息
        
        Args:
            context: Tool 执行上下文
            order_id: 订单 ID
            logistics_company: 快递公司
            tracking_number: 运单号
            
        Returns:
            ToolResult: 操作结果
        """
        if not logistics_company:
            return ToolResult(
                success=False,
                error="缺少快递公司",
                message="更新物流信息时必须提供快递公司（logistics_company）",
            )
        
        if not tracking_number:
            return ToolResult(
                success=False,
                error="缺少运单号",
                message="更新物流信息时必须提供运单号（tracking_number）",
            )
        
        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/orders/{order_id}/logistics",
            json_data={
                "logisticsCompany": logistics_company,
                "trackingNo": tracking_number,
            },
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"更新物流信息失败：{error_msg}",
            )
        
        logger.info(
            f"Order logistics updated: order_id={order_id}, "
            f"company={logistics_company}, tracking_no={tracking_number}, "
            f"tenant={context.tenant_id}, user={context.user_id}"
        )
        
        return ToolResult(
            success=True,
            data={
                "order_id": order_id,
                "logistics_company": logistics_company,
                "tracking_number": tracking_number,
            },
            message=f"物流信息已更新：{logistics_company} {tracking_number}",
        )
    
    async def _cancel_order(
        self,
        context: ToolContext,
        order_id: str,
        cancel_reason: Optional[str],
    ) -> ToolResult:
        """取消订单
        
        Args:
            context: Tool 执行上下文
            order_id: 订单 ID
            cancel_reason: 取消原因
            
        Returns:
            ToolResult: 操作结果
        """
        client = get_admin_api_client()

        # 如果 order_id 是订单号（ORD-开头），先查 API 获取 UUID
        actual_id = order_id
        if order_id.upper().startswith("ORD-"):
            try:
                lookup = await client.get(
                    "/api/admin/orders",
                    params={"keyword": order_id, "page": 1, "size": 1},
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
                items = (lookup.get("data", {}) or {}).get("items", [])
                if items and items[0].get("id"):
                    actual_id = items[0]["id"]
                    logger.info(f"[order-manage] Resolved {order_id} → {actual_id}")
            except Exception:
                pass

        json_data: Dict[str, Any] = {}
        if cancel_reason:
            json_data["closeReason"] = cancel_reason

        response = await client.put(
            f"/api/admin/orders/{actual_id}/cancel",
            json_data=json_data if json_data else None,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "取消失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"取消订单失败：{error_msg}",
            )
        
        logger.info(
            f"Order cancelled: order_id={order_id}, reason={cancel_reason}, "
            f"tenant={context.tenant_id}, user={context.user_id}"
        )
        
        return ToolResult(
            success=True,
            data={"order_id": order_id, "status": "cancelled", "reason": cancel_reason},
            message=f"订单已取消" + (f"，原因：{cancel_reason}" if cancel_reason else ""),
        )

    async def _confirm_payment(
        self,
        context: ToolContext,
        order_id: str,
    ) -> ToolResult:
        """确认支付
        
        Args:
            context: Tool 执行上下文
            order_id: 订单 ID
            
        Returns:
            ToolResult: 操作结果
        """
        client = get_admin_api_client()
        response = await client.put(
            f"/api/admin/orders/{order_id}/payment",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "确认支付失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"确认支付失败：{error_msg}",
            )
        
        logger.info(
            f"Order payment confirmed: order_id={order_id}, "
            f"tenant={context.tenant_id}, user={context.user_id}"
        )
        
        return ToolResult(
            success=True,
            data={"order_id": order_id, "action": "confirm_payment"},
            message="订单已确认支付",
        )

    async def _refund_order(
        self,
        context: ToolContext,
        order_id: str,
        refund_amount: Optional[float] = None,
        refund_reason: Optional[str] = None,
    ) -> ToolResult:
        """退款

        Args:
            context: Tool 执行上下文
            order_id: 订单 ID
            refund_amount: 退款金额（可选）
            refund_reason: 退款原因（可选）

        Returns:
            ToolResult: 操作结果
        """
        client = get_admin_api_client()
        json_data: Dict[str, Any] = {}
        if refund_amount is not None:
            json_data["refund_amount"] = refund_amount
        if refund_reason:
            json_data["refund_reason"] = refund_reason
        # Build URL with refund_reason as query param for Java controller compatibility
        url = f"/api/admin/orders/{order_id}/refund"
        if refund_reason:
            from urllib.parse import urlencode
            url += "?" + urlencode({"reason": refund_reason})
        response = await client.put(
            url,
            json_data=json_data if json_data else None,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        
        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "退款失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"退款操作失败：{error_msg}",
            )
        
        logger.info(
            f"Order refund initiated: order_id={order_id}, "
            f"amount={refund_amount}, reason={refund_reason}, "
            f"tenant={context.tenant_id}, user={context.user_id}"
        )

        return ToolResult(
            success=True,
            data={
                "order_id": order_id,
                "action": "refund",
                "refund_amount": refund_amount,
                "refund_reason": refund_reason,
            },
            message="订单退款已发起" + (f"，退款金额：{refund_amount}" if refund_amount is not None else ""),
        )
