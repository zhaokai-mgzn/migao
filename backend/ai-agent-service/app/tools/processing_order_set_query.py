"""
AI 智能客服系统 - 加工套件 / 扫码循环查询 Tool（issue #5247 模块覆盖：加工单套件）

只读三个 action，与 `ProcessingOrderSetController` 一一对应：
- `list`          → `GET /api/admin/processing-order-sets`（套件列表；可选 order_no / processing_order_no）
- `detail`        → `GET /api/admin/processing-order-sets/{id}`（套件 → 部位 → 工序明细）
- `scan_progress` → `GET /api/admin/processing-order-sets/scan-progress`（扫码循环进度）

⚠️ **不得另造第二份套件聚合**（规格 #5247 §4 + `docs/design/set-code-and-scan-loop.md` §5.3.2）：
三个端点全部复用服务端**同一份** `setOverview` 聚合，本工具只做转发与展示，不做任何二次计算。
⚠️ **未定价不得折 0**（既有 #4696 口径）：`unit_price` 为 null 时保持 null（服务端返回什么就转述什么），
禁止在工具侧填 0 或估算。

权限码：三个端点（#5246 收尾）为方法级 `@RequirePermission("processing:manage")` ——
与侧边栏「生产看板」节点同码（生产域无专属读码，粒度债见权限守卫的 `READ_WRITE_EXCEPTIONS`）。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client

VALID_ACTIONS = {"list", "detail", "scan_progress"}


def set_rows(data: Any) -> list:
    """容错取列表：`PageResponse`（records/items/list/rows）与裸列表两种形态都收。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("records", "items", "list", "rows", "sets"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


class ProcessingOrderSetQueryTool(BaseTool):
    """加工套件 / 扫码循环查询 Tool（只读）"""

    name = "processing_order_set_query"
    description = (
        "【触发】用户问'加工套件''这套窗分几个部位''某个部位要做哪些工序''扫码做到哪了/套件进度'时调用。"
        "【参数】action 必填：list（套件列表，可选 order_no / processing_order_no）/ "
        "detail（单个套件 → 部位 → 工序明细，需 id）/ scan_progress（扫码循环进度，可选订单/加工单号）。"
        "【反例】加工单本身（JG-xxx 状态）用 processing_order_query；某单生产进度/报工明细用 "
        "production_progress_query / production_worklog_query；工序库与工艺路线模板用 operation_catalog_query。"
        "【口径】明细里的 unit_price 为 null 表示**尚未定价**，必须原样转述（不得说成 0 元、不得估算）。"
        "【标注】READONLY — 只读查询，不含任何写 action"
    )

    required_permissions = ["processing:manage"]
    read_only = True
    destructive = False
    idempotent = True

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：list（套件列表）/ detail（套件明细）/ scan_progress（扫码进度）—— 均为只读",
                "enum": ["list", "detail", "scan_progress"],
            },
            "id": {"type": "string", "description": "套件 id（detail 时必填，来自 list 结果）"},
            "order_no": {"type": "string", "description": "订单号 ORD-xxx（list/scan_progress 时可选）"},
            "processing_order_no": {
                "type": "string",
                "description": "加工单号 JG-xxx（list/scan_progress 时可选）",
            },
            "page": {"type": "integer", "description": "页码，默认 1（list 时）", "default": 1},
            "size": {"type": "integer", "description": "每页数量，默认 20（list 时）", "default": 20},
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        id: Optional[str] = None,
        order_no: Optional[str] = None,
        processing_order_no: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询加工套件与扫码进度",
                suggestion="请联系管理员为您开通「生产看板」查看权限后重试",
            )

        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(sorted(VALID_ACTIONS))}",
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )

        params: Dict[str, Any] = {}
        try:
            client = get_admin_api_client()
            if action == "detail":
                if not id:
                    return ToolResult(
                        success=False,
                        error="缺少参数",
                        message="查询套件明细需要套件 id",
                        suggestion="请先用 action=list 查出目标套件的 id，再调 detail",
                    )
                response = await client.get(
                    f"/api/admin/processing-order-sets/{id}",
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
            elif action == "scan_progress":
                if not order_no and not processing_order_no:
                    return ToolResult(
                        success=False,
                        error="缺少参数",
                        message="查询扫码进度需要订单号（order_no）或加工单号（processing_order_no）至少一个",
                        suggestion="请先向用户确认订单号（ORD-xxx）或加工单号（JG-xxx）后重试",
                    )
                if order_no:
                    params["orderNo"] = order_no.strip()
                if processing_order_no:
                    params["processingOrderNo"] = processing_order_no.strip()
                response = await client.get(
                    "/api/admin/processing-order-sets/scan-progress",
                    params=params,
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
            else:
                params["page"] = page
                params["size"] = size
                if order_no:
                    params["orderNo"] = order_no.strip()
                if processing_order_no:
                    params["processingOrderNo"] = processing_order_no.strip()
                response = await client.get(
                    "/api/admin/processing-order-sets",
                    params=params,
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
        except Exception as e:
            logger.error(f"Processing order set query error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="加工套件查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = (
                error_info.get("message", "查询失败")
                if isinstance(error_info, dict)
                else str(error_info)
            )
            return admin_api_failure(
                response,
                error=error_msg,
                message=f"加工套件查询失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请先确认该单是否已生成套件（未生成套件时为空列表属正常）",
            )

        data = response.get("data")
        if action == "detail":
            if not data:
                return ToolResult(success=True, data={}, message="未找到该套件（如已删除请重新 list 查询）")
            return ToolResult(
                success=True,
                data=data,
                message="套件明细如下（unit_price 为 null = 尚未定价，请原样转述）",
            )

        rows = set_rows(data)
        if not rows:
            return ToolResult(
                success=True,
                data={"list": []},
                message="暂无套件记录" if action == "list" else "暂无扫码进度记录",
            )

        logger.info(f"[processing_order_set_query] action={action} done: count={len(rows)}")
        return ToolResult(
            success=True,
            data={"list": rows},
            message=f"共 {len(rows)} 条{'套件' if action == 'list' else '扫码进度'}记录",
        )