"""
AI 智能客服系统 - C端售后查询 Tool (小布专用)

客户通过小布查询自己的售后工单列表/详情。
与 after_sales_manage（管理员使用）分开：客户只能查自己的工单。
"""
from typing import Optional, Dict, Any
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class AftersaleQueryTool(BaseTool):
    """C端售后查询 Tool

    小布（C端客服）专用：客户查询自己的售后工单。
    只能查看当前客户的工单（通过 tenant_id + user_id 隔离）。

    action:
    - list: 查询工单列表
    - detail: 查看工单详情
    """

    name = "aftersale_query"
    description = (
        "【触发】客户说'查看售后''我的工单''退款进度''投诉处理得怎么样了'时调用。"
        "【前置】list: 无需参数，可传status筛选。detail: 需要ticket_id。"
        "【安全】只能查询当前客户自己的工单。"
        "【标注】READONLY — 纯查询，无需确认"
    )
    allowed_roles = ["customer"]

    read_only = True
    destructive = False
    idempotent = True

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型: list(查询列表) / detail(查看详情)",
                "enum": ["list", "detail"],
            },
            "ticket_id": {
                "type": "string",
                "description": "工单ID（detail时必填）",
            },
            "status": {
                "type": "string",
                "description": "按状态筛选（list时可选）: pending / processing / resolved / rejected / closed",
                "enum": ["pending", "processing", "resolved", "rejected", "closed"],
            },
            "page": {
                "type": "integer",
                "description": "页码，默认1",
                "default": 1,
            },
            "size": {
                "type": "integer",
                "description": "每页数量，默认5",
                "default": 5,
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        ticket_id: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 5,
    ) -> ToolResult:
        """执行售后查询操作

        Args:
            context: Tool 执行上下文
            action: 操作类型 (list / detail)
            ticket_id: 工单ID
            status: 按状态筛选
            page: 页码
            size: 每页数量

        Returns:
            ToolResult: 查询结果
        """
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询售后工单",
                suggestion="售后查询功能仅供客户使用",
            )

        if action not in ("list", "detail"):
            return ToolResult(
                success=False,
                error=f"无效操作: {action}",
                message="不支持的操作类型，可选: list / detail",
                suggestion="请使用 list（查看列表）或 detail（查看详情）",
            )

        try:
            if action == "list":
                return await self._list_tickets(context, page, size, status)
            elif action == "detail":
                return await self._get_detail(context, ticket_id)

        except Exception as e:
            logger.error(
                f"[aftersale_query] Failed: action={action}, error={type(e).__name__}: {e}"
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="查询售后工单失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系客服",
            )

    async def _list_tickets(
        self,
        context: ToolContext,
        page: int,
        size: int,
        status: Optional[str],
    ) -> ToolResult:
        """查询售后工单列表"""
        # Gap-4 安全加固: customer 查询必须带 customer_id 做双重隔离
        params: Dict[str, Any] = {
            "page": page,
            "size": size,
            "customerId": str(context.user_id),  # 强制 customer_id 过滤
        }
        if status:
            params["status"] = status

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/after-sales",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"查询售后工单失败: {error_msg}",
            )

        data = response.get("data", {})
        items = data.get("items", [])
        total = data.get("total", 0)

        # Gap-4 安全加固: 防御性校验 — 过滤不属于当前客户的工单
        verified_items = []
        filtered_count = 0
        for item in items:
            resp_customer_id = (
                item.get("customerId")
                or item.get("customer_id")
                or item.get("userId")
            )
            if resp_customer_id is not None and str(resp_customer_id) != str(context.user_id):
                logger.error(
                    f"Customer data integrity violation in aftersale_query: "
                    f"response customer_id={resp_customer_id}, expected={context.user_id}"
                )
                filtered_count += 1
                continue
            verified_items.append(item)
        if filtered_count > 0:
            logger.warning(
                f"Aftersale query filtered {filtered_count} records due to customer_id mismatch, "
                f"user={context.user_id}"
            )
            total = max(0, total - filtered_count)

        logger.info(
            f"[aftersale_query] List: page={page}, size={size}, total={total} | "
            f"tenant={context.tenant_id}, user={context.user_id}"
        )

        return ToolResult(
            success=True,
            data={"items": verified_items, "total": total, "page": page, "size": size},
            message=f"您共有 {total} 条售后工单记录",
            summary=f"售后工单: {total}条",
        )

    async def _get_detail(
        self,
        context: ToolContext,
        ticket_id: Optional[str],
    ) -> ToolResult:
        """查看售后工单详情"""
        if not ticket_id:
            return ToolResult(
                success=False,
                error="缺少工单ID",
                message="查看详情时需要提供工单ID",
                suggestion="请从工单列表中选择一个工单查看详情",
            )

        client = get_admin_api_client()
        response = await client.get(
            f"/api/admin/after-sales/{ticket_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"查询工单详情失败: {error_msg}",
            )

        data = response.get("data", {})

        # Gap-4 安全加固: 校验工单详情属于当前客户
        resp_customer_id = (
            data.get("customerId")
            or data.get("customer_id")
            or data.get("userId")
        )
        if resp_customer_id is not None and str(resp_customer_id) != str(context.user_id):
            logger.error(
                f"Customer data integrity violation in aftersale_query detail: "
                f"ticket_id={ticket_id}, response customer_id={resp_customer_id}, "
                f"expected={context.user_id}"
            )
            return ToolResult(
                success=False,
                error="权限不足",
                message="该工单不属于您，无法查看",
                suggestion="请从您的工单列表中选择一个工单查看详情",
            )

        logger.info(
            f"[aftersale_query] Detail: ticket_id={ticket_id} | "
            f"tenant={context.tenant_id}, user={context.user_id}"
        )

        return ToolResult(
            success=True,
            data=data,
            message=f"工单 {ticket_id} 详情已获取",
            summary=f"工单{ticket_id}: {data.get('status', 'unknown')}"
        )
