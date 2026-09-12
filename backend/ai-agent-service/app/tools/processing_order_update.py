"""
AI 智能客服系统 - 加工单状态更新 Tool（issue #3340）

action: issue（发加工，可填加工方/交期）/ start（开始加工）/ complete（加工完成）/
cancel（取消，必填原因；generated 取消联动订单回退已确认）。
状态机与服务端校验：非法流转拒绝；completed 后冻结。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


VALID_ACTIONS = {"issue", "start", "complete", "cancel"}

ACTION_LABELS = {
    "issue": "已发加工",
    "start": "开始加工",
    "complete": "加工完成",
    "cancel": "已取消加工单",
}


class ProcessingOrderUpdateTool(BaseTool):
    """更新加工单状态 Tool"""

    name = "processing_order_update"
    description = (
        "【触发】用户说'发加工''加工好了''开始加工''取消加工单'时调用。"
        "【前置】需要 id（加工单号 JG-xxx / 订单号 / UUID）+ action。"
        "【语义】issue 可填加工方 processor 与交期 expectedDeliveryDate（yyyy-MM-dd，手工填）；"
        "cancel 必填 reason；取消已发加工及以上的加工单需人工确认（填原因）。"
        "【反例】查询用 processing_order_query；生成用 processing_order_generate。"
        "【标注】WRITE|DESTRUCTIVE — cancel 会联动订单回退，必须二次确认"
    )

    allowed_roles = ["admin", "tenant_admin", "operator"]
    read_only = False
    destructive = True
    idempotent = False

    parameters = {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "加工单号（JG-xxx）/ 订单号（ORD-xxx）/ UUID，服务端自动解析",
            },
            "action": {
                "type": "string",
                "enum": ["issue", "start", "complete", "cancel"],
                "description": "操作：issue(发加工)/start(开始加工)/complete(加工完成)/cancel(取消)",
            },
            "processor": {
                "type": "string",
                "description": "加工方（issue 时可选）",
            },
            "expected_delivery_date": {
                "type": "string",
                "description": "交期 yyyy-MM-dd（issue 时可选，手工填写）",
            },
            "reason": {
                "type": "string",
                "description": "取消原因（cancel 时必填）",
            },
        },
        "required": ["id", "action"],
    }

    async def execute(
        self,
        context: ToolContext,
        id: str,
        action: str,
        processor: Optional[str] = None,
        expected_delivery_date: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(success=False, error="权限不足", message="您没有权限更新加工单")

        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False, error=f"无效的操作: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
                suggestion=f"请从 {', '.join(sorted(VALID_ACTIONS))} 中选择一个",
            )
        if not id:
            return ToolResult(
                success=False, error="缺少加工单 ID",
                message="请提供加工单号（JG-xxx）或订单号",
                suggestion="请先用 processing_order_query 查询加工单号",
            )
        if action == "cancel" and not reason:
            return ToolResult(
                success=False, error="缺少取消原因",
                message="取消加工单必须填写原因（涉及订单状态联动）",
                suggestion="请补充取消原因后再试",
            )

        try:
            json_data: Dict[str, Any] = {"action": action}
            if action == "issue":
                if processor:
                    json_data["processor"] = processor
                if expected_delivery_date:
                    json_data["expectedDeliveryDate"] = expected_delivery_date
            if action == "cancel":
                json_data["reason"] = reason

            client = get_admin_api_client()
            response = await client.patch(
                f"/api/admin/processing-orders/{id}",
                json_data=json_data,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(f"Processing order update error: action={action}, error={e}", exc_info=True)
            return ToolResult(
                success=False, error="tool_execution_failed",
                message="加工单操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = error_info.get("message", "操作失败") if isinstance(error_info, dict) else str(error_info)
            return ToolResult(
                success=False, error=error_msg,
                message=f"加工单操作失败：{error_msg}",
                suggestion="请确认加工单号正确且当前状态允许该操作",
            )

        po = response.get("data") or {}
        logger.info(f"[processing_order_update] done: id={id}, action={action}")
        return ToolResult(
            success=True,
            data={"id": id, "action": action, "processingOrderNo": po.get("processingOrderNo"), "result": po},
            message=ACTION_LABELS.get(action, f"加工单{action}操作成功"),
        )
