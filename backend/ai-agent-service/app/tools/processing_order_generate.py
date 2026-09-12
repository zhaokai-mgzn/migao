"""
AI 智能客服系统 - 加工单生成 Tool（issue #3340）

把已确认且含加工项的订单批量生成加工单（快照固化五要素 + options，不含销售价），
并联动订单 confirmed → producing。幂等：同一订单已有加工单时拒绝重复生成。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class ProcessingOrderGenerateTool(BaseTool):
    """生成加工单 Tool"""

    name = "processing_order_generate"
    description = (
        "【触发】用户说'生成加工单''把这几单发加工''今天确认的订单都生成加工单'时调用。"
        "【前置】需要 order_ids（订单 ID 或订单号列表）。"
        "【语义】仅已确认且含加工项的订单可生成；生成后订单进入生产中（producing）。"
        "【反例】查询加工单用 processing_order_query；更新加工单状态用 processing_order_update。"
        "【标注】WRITE — 批量生成前必须列出订单清单并二次确认"
    )

    allowed_roles = ["admin", "tenant_admin", "operator"]
    read_only = False
    destructive = False
    idempotent = True

    parameters = {
        "type": "object",
        "properties": {
            "order_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "订单 ID 或订单号（ORD-xxx）列表，支持批量",
            },
        },
        "required": ["order_ids"],
    }

    async def execute(self, context: ToolContext, order_ids: List[str]) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(success=False, error="权限不足", message="您没有权限生成加工单")

        if not order_ids or not isinstance(order_ids, list) or len(order_ids) == 0:
            return ToolResult(
                success=False, error="缺少订单列表",
                message="请提供要生成加工单的订单 ID 或订单号",
                suggestion="请先从订单列表或查询结果中获取订单号，格式如 ORD-20260718-0001",
            )
        if len(order_ids) > 100:
            return ToolResult(
                success=False, error="批量超限",
                message="单次最多生成 100 个加工单，请分批操作",
            )

        try:
            client = get_admin_api_client()
            response = await client.post(
                "/api/admin/processing-orders/generate",
                json_data={"orderIds": order_ids},
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(f"Processing order generate error: {e}", exc_info=True)
            return ToolResult(
                success=False, error="tool_execution_failed",
                message="生成加工单失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = error_info.get("message", "生成加工单失败") if isinstance(error_info, dict) else str(error_info)
            return ToolResult(
                success=False, error=error_msg,
                message=f"生成加工单失败：{error_msg}",
                suggestion="请确认订单已确认且含加工项；已有加工单的订单不可重复生成",
            )

        results = response.get("data", []) or []
        ok_count = sum(1 for r in results if r.get("success"))
        fail_msgs = [r.get("message") for r in results if not r.get("success")]
        logger.info(f"[processing_order_generate] done: total={len(results)}, ok={ok_count}")

        if fail_msgs:
            return ToolResult(
                success=ok_count > 0,
                data={"results": results},
                message=f"加工单生成完成 {ok_count}/{len(results)} 个"
                        + (f"；失败原因：{'；'.join(fail_msgs[:3])}" if fail_msgs else ""),
            )
        return ToolResult(
            success=True,
            data={"results": results},
            message=f"已生成 {ok_count} 个加工单，订单已进入生产中"
                    + ("，可让加工方开始安排" if ok_count else ""),
        )
