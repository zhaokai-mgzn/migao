"""
AI 智能客服系统 - 加工单查询 Tool（issue #3340）

按加工单号/订单号/关键词查询加工单列表，或查单个加工单详情。
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 加工单状态中文映射（与后端 ProcessingOrderService 状态机对齐）
PO_STATUS_TEXT = {
    "generated": "已生成",
    "issued": "已发加工",
    "in_processing": "加工中",
    "completed": "加工完成",
    "cancelled": "已取消",
}


class ProcessingOrderQueryTool(BaseTool):
    """加工单查询 Tool"""

    name = "processing_order_query"
    description = (
        "【触发】用户问'加工单到哪了''JG-xxx 什么状态''这个订单的加工单'时调用。"
        "【前置】可选 keyword（加工单号 JG-xxx / 订单号 ORD-xxx）或 status 筛选。"
        "【反例】生成加工单用 processing_order_generate；改加工单状态用 processing_order_update。"
        "【标注】READ — 只读查询"
    )

    allowed_roles = ["admin", "agent", "tenant_admin", "operator", "customer_service", "knowledge_editor"]
    read_only = True
    destructive = False
    idempotent = True

    parameters = {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "加工单号（JG-xxx）/ 订单号（ORD-xxx）或订单 UUID，可选",
            },
            "status": {
                "type": "string",
                "enum": ["generated", "issued", "in_processing", "completed", "cancelled"],
                "description": "按加工单状态筛选（可选）",
            },
        },
        "required": [],
    }

    async def execute(
        self,
        context: ToolContext,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
    ) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(success=False, error="权限不足", message="您没有权限查询加工单")

        try:
            client = get_admin_api_client()
            params: Dict[str, str] = {}
            if keyword:
                params["keyword"] = keyword.strip()
            if status:
                params["status"] = status
            response = await client.get(
                "/api/admin/processing-orders",
                params=params,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(f"Processing order query error: {e}", exc_info=True)
            return ToolResult(
                success=False, error="tool_execution_failed",
                message="加工单查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = error_info.get("message", "查询失败") if isinstance(error_info, dict) else str(error_info)
            return ToolResult(success=False, error=error_msg, message=f"加工单查询失败：{error_msg}")

        data = response.get("data") or []
        if not data:
            return ToolResult(
                success=True, data={"list": []},
                message="未找到加工单" + (f"（关键词：{keyword}）" if keyword else ""),
            )

        # 组装人类可读列表
        rows = []
        for po in data:
            rows.append({
                "id": po.get("id"),
                "processingOrderNo": po.get("processingOrderNo"),
                "orderNo": po.get("orderNo"),
                "customerName": po.get("customerName"),
                "processor": po.get("processor"),
                "expectedDeliveryDate": po.get("expectedDeliveryDate"),
                "status": po.get("status"),
                "statusText": PO_STATUS_TEXT.get(po.get("status"), po.get("status")),
                "printCount": po.get("printCount"),
            })
        logger.info(f"[processing_order_query] done: count={len(rows)}")
        return ToolResult(
            success=True,
            data={"list": rows},
            message=f"共找到 {len(rows)} 个加工单",
        )
