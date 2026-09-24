"""
AI 智能客服系统 - 入库单/批次查询 Tool（issue #5247 模块覆盖：库存）

只读三个 action（与端点一一对应，`.github/cases` 的入库域口径）：
- `list`    → `GET /api/admin/inbound-orders`（`inbound:view`）
- `batches` → `GET /api/admin/inbound-orders/batches`（`inbound:view`）
- `detail`  → `GET /api/admin/inbound-orders/{id}`（`inbound:view`）

写面（开账模板 / 导入 / 新建 / 动作）**不在本工具内**：B 端已只读化（issue #5247）。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client

VALID_ACTIONS = {"list", "batches", "detail"}


def inbound_rows(data: Any) -> list:
    """容错取列表：裸列表与分页包装（records/items/list/rows）两种形态都收。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("records", "items", "list", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


class InboundOrderQueryTool(BaseTool):
    """入库单/批次查询 Tool（只读）"""

    name = "inbound_order_query"
    description = (
        "【触发】用户问'入库单''到货记录''批次''这批货什么时候到的''某个 SKU 的批次余量'时调用。"
        "【参数】action 必填：list（入库单列表，可选 keyword）/ batches（批次视图，可选 sku_id）/ "
        "detail（单张入库单，需 id）。"
        "【反例】商品/颜色的库存数用 inventory_manage(query)；库存台账分页用 stock_ledger_query；"
        "批次成本与省料金额用 batch_stock_query。"
        "【标注】READONLY — 只读查询，不含任何写 action"
    )

    # 权限码（admin-api 目录）：`InboundOrderController` 的三个读端点均方法级
    # `@RequirePermission("inbound:view")` —— 与侧边栏「入库单」节点同码。
    required_permissions = ["inbound:view"]
    read_only = True
    destructive = False
    idempotent = True

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：list（入库单列表）/ batches（批次视图）/ detail（入库单详情）—— 均为只读",
                "enum": ["list", "batches", "detail"],
            },
            "id": {"type": "string", "description": "入库单 id（detail 时必填，来自 list 结果）"},
            "keyword": {"type": "string", "description": "货号/单据关键词（list 时可选）"},
            "sku_id": {"type": "string", "description": "SKU id（batches 时可选，用于按 SKU 过滤批次）"},
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        id: Optional[str] = None,
        keyword: Optional[str] = None,
        sku_id: Optional[str] = None,
    ) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询入库单与批次",
                suggestion="请联系管理员为您开通「入库单」查看权限后重试",
            )

        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(sorted(VALID_ACTIONS))}",
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )

        try:
            client = get_admin_api_client()
            if action == "detail":
                if not id:
                    return ToolResult(
                        success=False,
                        error="缺少参数",
                        message="查询入库单详情需要入库单 id",
                        suggestion="请先用 action=list 查出目标入库单的 id，再调 detail",
                    )
                response = await client.get(
                    f"/api/admin/inbound-orders/{id}",
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
            elif action == "batches":
                # ⚠️ 独立字典（不要复用 `params`）：`tests/test_tool_payload_backend_contract.py` 的
                # 静态归属分析器按**调用点之前**收集 `name["k"]=v`，与 `list` 分支共用一个字典会把
                # `skuId` 误判成 `/inbound-orders`（list）的不可读键（实测踩到；HTTP 参数名本身没错）。
                batch_params: Dict[str, Any] = {}
                if sku_id:
                    batch_params["skuId"] = sku_id
                response = await client.get(
                    "/api/admin/inbound-orders/batches",
                    params=batch_params,
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
            else:
                list_params: Dict[str, Any] = {}
                if keyword:
                    list_params["keyword"] = keyword.strip()
                response = await client.get(
                    "/api/admin/inbound-orders",
                    params=list_params,
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
        except Exception as e:
            logger.error(f"Inbound order query error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="入库单查询失败，请稍后重试",
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
                message=f"入库单查询失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请用户核对单据关键词或 id 后重试",
            )

        data = response.get("data")
        if action == "detail":
            if not data:
                return ToolResult(success=True, data={}, message="未找到该入库单（如已删除请重新 list 查询）")
            return ToolResult(success=True, data=data, message="入库单详情如下")

        rows = inbound_rows(data)
        if not rows:
            return ToolResult(
                success=True,
                data={"list": []},
                message="未找到入库单记录" if action == "list" else "未找到批次记录",
            )

        logger.info(f"[inbound_order_query] action={action} done: count={len(rows)}")
        return ToolResult(
            success=True,
            data={"list": rows},
            message=f"共找到 {len(rows)} 条{'入库单' if action == 'list' else '批次'}记录",
        )