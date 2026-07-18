"""
AI 智能客服系统 - 订单管理 Tool

执行订单管理操作。Agent BFF: 统一走 PATCH /api/admin/agent/orders/{id}。
ID 解析、ORD-xxx→UUID 转换由 Java Agent 端点负责。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


VALID_ACTIONS = {"update_status", "update_logistics", "cancel", "confirm_payment", "refund"}


class OrderManageTool(BaseTool):
    """订单管理 Tool"""

    name = "order_manage"
    description = (
        "【触发】用户说'取消订单''退款''修改订单''标记发货''更新物流''确认支付'时调用。"
        "【前置】需要 action + order_id。cancel/refund 是破坏性操作，必须二次确认。"
        "【反例】仅查看订单用 order_query。创建新订单用 order_create。"
        "【标注】WRITE|DESTRUCTIVE — 取消/退款前必须二次确认"
    )

    allowed_roles = ["admin", "agent", "tenant_admin"]
    read_only = False
    destructive = True
    idempotent = False

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["update_status", "update_logistics", "cancel", "confirm_payment", "refund"],
                "description": "操作类型。update_status(改状态)/update_logistics(发货填运单)/cancel(取消)/confirm_payment(确认支付)/refund(退款)",
            },
            "order_id": {
                "type": "string",
                "description": "订单 ID 或订单号（ORD-xxx）。支持 UUID / 订单号，服务端自动解析",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "confirmed", "producing", "shipped", "completed", "cancelled"],
                "description": "新状态（update_status 时必填）",
            },
            "logistics_company": {"type": "string", "description": "快递公司（update_logistics 时必填）"},
            "tracking_number": {"type": "string", "description": "运单号（update_logistics 时必填）"},
            "cancel_reason": {"type": "string", "description": "取消原因（cancel 时可选）"},
            "refund_amount": {"type": "number", "description": "退款金额（refund 时可选）"},
            "refund_reason": {"type": "string", "description": "退款原因（refund 时可选）"},
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
        if not self.check_permission(context):
            return ToolResult(success=False, error="权限不足", message="您没有权限执行订单管理操作")

        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False, error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
                suggestion=f"请从 {', '.join(sorted(VALID_ACTIONS))} 中选择一个",
            )

        if not order_id:
            return ToolResult(
                success=False, error="缺少订单 ID",
                message="请提供订单 ID 或订单号（ORD-xxx）",
                suggestion="请先从订单列表或查询结果中获取订单号，格式如 ORD-20260718-0001",
            )

        try:
            return await self._execute_action(context, action, order_id, status,
                logistics_company, tracking_number, cancel_reason, refund_amount, refund_reason)
        except Exception as e:
            logger.error(f"Order manage error: action={action}, order_id={order_id}, error={e}")
            return ToolResult(
                success=False, error="tool_execution_failed",
                message="订单操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    async def _execute_action(self, context, action, order_id, status,
                               logistics_company, tracking_number, cancel_reason,
                               refund_amount, refund_reason) -> ToolResult:
        """统一通过 Agent PATCH 端点执行所有操作。ID 解析由 Java 负责。"""
        json_data: Dict[str, Any] = {"action": action}

        if action == "update_status":
            if not status:
                return ToolResult(success=False, error="缺少状态参数", message="更新状态时必须提供新状态（status）")
            json_data["status"] = status
        elif action == "update_logistics":
            if not logistics_company:
                return ToolResult(success=False, error="缺少快递公司", message="请提供快递公司")
            if not tracking_number:
                return ToolResult(success=False, error="缺少运单号", message="请提供运单号")
            json_data["logisticsCompany"] = logistics_company
            json_data["trackingNumber"] = tracking_number
        elif action == "cancel":
            if cancel_reason:
                json_data["cancelReason"] = cancel_reason
        elif action == "refund":
            if refund_amount is not None:
                json_data["refundAmount"] = refund_amount
            if refund_reason:
                json_data["refundReason"] = refund_reason

        logger.info(f"[order_manage] Agent PATCH: id={order_id}, action={action}")
        client = get_admin_api_client()
        response = await client.patch(f"/api/admin/agent/orders/{order_id}",
            json_data=json_data, tenant_id=context.tenant_id, user_id=context.user_id)

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = error_info.get("message", "操作失败") if isinstance(error_info, dict) else str(error_info)
            return ToolResult(
                success=False, error=error_msg,
                message=f"订单操作失败：{error_msg}",
                suggestion="请确认订单号/UUID 正确，或刷新订单列表获取最新的订单信息",
            )

        order_data = response.get("data", {})
        action_labels = {
            "update_status": f"订单状态已更新为「{status}」",
            "update_logistics": f"物流信息已更新：{logistics_company} {tracking_number}",
            "cancel": "订单已取消" + (f"，原因：{cancel_reason}" if cancel_reason else ""),
            "confirm_payment": "订单已确认支付",
            "refund": "订单退款已发起" + (f"，退款金额：{refund_amount}" if refund_amount is not None else ""),
        }

        logger.info(f"[order_manage] Agent {action} done: id={order_id}")
        return ToolResult(
            success=True,
            data={"order_id": order_id, "action": action, "result": order_data},
            message=action_labels.get(action, f"订单{action}操作成功"),
        )
