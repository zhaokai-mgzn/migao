"""
AI 智能客服系统 - 算料配置查询 Tool（issue #5247 模块覆盖：算料）

只读：`CraftCalcConfigController`（类级 `@RequirePermission("processing:manage")`）→
`GET /api/admin/production/craft-calc-config`。

⚠️ 门宽方案**不建工具**（用户裁定 2026-09-23）：只有计算型 `POST /api/admin/orders/door-width-plan`，
没有可查对象 ⇒ 在 issue #5247 与 PR 里登记为已知缺口。
"""

from typing import Any, Dict
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


class CraftCalcConfigQueryTool(BaseTool):
    """算料配置查询 Tool（只读）"""

    name = "craft_calc_config_query"
    description = (
        "【触发】用户问'算料参数''上下卷边多少''搭接损耗怎么算''算料配置''门幅加放'时调用。"
        "【参数】无参数（取本租户当前算料配置）。"
        "【反例】具体一单的用布量/报价计算请引导用户到后台算料页填写尺寸后计算（本工具**只读配置**，"
        "不做计算）；工序库/路线模板用 operation_catalog_query。"
        "【标注】READONLY — 只读查询"
    )

    # 权限码（admin-api 目录）：`CraftCalcConfigController` 类级 `@RequirePermission("processing:manage")`
    # —— 与侧边栏「工艺配置」节点同码（生产域无专属读码，粒度债见守卫的 READ_WRITE_EXCEPTIONS）。
    required_permissions = ["processing:manage"]
    read_only = True
    destructive = False
    idempotent = True

    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, context: ToolContext) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限查看算料配置",
                suggestion="请联系管理员为您开通「工艺配置」查看权限后重试",
            )

        try:
            client = get_admin_api_client()
            response = await client.get(
                "/api/admin/production/craft-calc-config",
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(f"Craft calc config query error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="算料配置查询失败，请稍后重试",
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
                message=f"算料配置查询失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请引导用户到后台算料页查看当前配置",
            )

        data: Dict[str, Any] = response.get("data") or {}
        logger.info("[craft_calc_config_query] done")
        return ToolResult(
            success=True,
            data=data,
            message="当前算料配置如下（配置项以服务端返回为准）" if data else "暂未取到算料配置",
        )