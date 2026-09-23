"""
AI 智能客服系统 - 工序库 / 工艺路线查询 Tool（issue #5247 模块覆盖：生产）

只读两个 action（`ProductionController` 的类级 `@RequirePermission("order:list")` 生效）：
- `operations` → `GET /api/admin/production/operations-catalog`（工序库：分组/单位/计件单价/开始标记）
- `routings`   → `GET /api/admin/production/routings`（工艺路线模板：主线 + 适用帘种 + 默认标记）

⚠️ 权限码口径（issue #5247）：这两个读端点原先只吃 `ProductionController` 的**类级** `order:list`
⇒ 持 `order:list` 的客服/销售/财务能经米宝读工艺数据，而侧边栏「工艺配置」页（`processing:manage`）
对它们不可见 = 用户裁定禁止的权限泄露形态。故本次给这两个端点补**方法级**
`@RequirePermission("processing:manage")`，工具同码 —— 方向是**收窄**（cs/sales/finance 失去该读面），
与 #5246 对 `processing_order_query` / `piecework_query` / `production_*_query` 的处置一致。
生产域「读面没有专属读码」的粒度债由 `tests/unit_ci_workflows/test_agent_permission_parity.py`
的 `READ_WRITE_EXCEPTIONS` 逐条登记。
"""

from typing import Any, Dict
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client

VALID_ACTIONS = {"operations", "routings"}


class OperationCatalogQueryTool(BaseTool):
    """工序库 / 工艺路线查询 Tool（只读）"""

    name = "operation_catalog_query"
    description = (
        "【触发】用户问'有哪些工序''工序库''裁剪/精裁的单价''工艺路线模板''默认路线是什么'时调用。"
        "【参数】action 必填：operations（工序库目录）/ routings（工艺路线模板）—— 均无额外参数。"
        "【反例】加工项（店铺级目录，含分类/单位）用 processing_item_query；算料参数用 craft_calc_config_query；"
        "某张订单做到哪道工序用 production_progress_query；某单过程明细/报工用 production_worklog_query。"
        "【标注】READONLY — 只读查询"
    )

    # 权限码（admin-api 目录）：`ProductionController.GET /operations-catalog` 与
    # `GET /routings` 的方法级 `@RequirePermission("processing:manage")`（本次新增）——
    # 与侧边栏「工艺配置」节点同码（生产域无专属读码，粒度债见守具的 READ_WRITE_EXCEPTIONS）。
    required_permissions = ["processing:manage"]
    read_only = True
    destructive = False
    idempotent = True

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：operations（工序库目录）/ routings（工艺路线模板）—— 均为只读",
                "enum": ["operations", "routings"],
            },
        },
        "required": ["action"],
    }

    async def execute(self, context: ToolContext, action: str) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查询工序库与工艺路线",
                suggestion="请联系管理员为您开通「订单列表」或生产域查看权限后重试",
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
            # ⚠️ 路径必须**字面量写在调用点**：`tests/test_tool_payload_backend_contract.py` 的
            # 「payload 调用点必须静态归属到端点」门禁 + 权限守卫的端点归属都靠静态可渲染
            # （抽成常量/变量会让该调用点脱离射程 ⇒ 工具变成「没有端点」⇒ 判据 1 红，实测踩到）。
            if action == "operations":
                response = await client.get(
                    "/api/admin/production/operations-catalog",
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
            else:
                response = await client.get(
                    "/api/admin/production/routings",
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                )
        except Exception as e:
            logger.error(f"Operation catalog query error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="工序库查询失败，请稍后重试",
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
                message=f"工序库查询失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请先确认该租户是否已配置工序库",
            )

        data: Dict[str, Any] = response.get("data") or {}
        logger.info(f"[operation_catalog_query] action={action} done")
        return ToolResult(
            success=True,
            data=data,
            message="工序库目录如下" if action == "operations" else "工艺路线模板如下",
        )