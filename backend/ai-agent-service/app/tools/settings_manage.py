"""
AI 智能客服系统 - 系统设置管理 Tool

管理系统设置，支持获取/更新系统设置、获取/更新AI配置、修改密码、查询登录日志。
"""

from typing import Any, Dict, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {
    "get_settings", "update_settings",
    "get_ai_config", "update_ai_config",
    "change_password", "login_logs",
}


class SettingsManageTool(BaseTool):
    """系统设置管理 Tool

    管理系统设置：获取/更新系统设置、获取/更新AI配置、修改密码、查询登录日志。

    使用场景：
    - 获取当前系统设置（商户名称、行业等）
    - 更新系统设置
    - 获取AI客服配置（问候语模板、营业时间等）
    - 更新AI客服配置
    - 修改账户密码
    - 查看登录日志
    """

    name = "settings_manage"
    description = (
        "【触发】用户问'系统设置''配置''AI配置''模型''问候语''改密码''登录日志'时调用。【前置】get_settings/get_ai_config/login_logs 是查询。update_settings/update_ai_config/change_password 需确认。【反例】通知管理用 notification_manage。快捷回复用 quick_reply_manage。【标注】WRITE|DESTRUCTIVE — 修改全局配置/密码需二次确认"
    )    allowed_roles = ["admin", "tenant_admin"]

    read_only = False
    destructive = True   # 可修改关键系统配置/AI配置/密码
    idempotent = False   # 配置修改非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型：get_settings（获取设置）/ update_settings（更新设置）/ "
                    "get_ai_config（获取AI配置）/ update_ai_config（更新AI配置）/ "
                    "change_password（修改密码）/ login_logs（登录日志）"
                ),
                "enum": [
                    "get_settings", "update_settings",
                    "get_ai_config", "update_ai_config",
                    "change_password", "login_logs",
                ],
            },
            "name": {
                "type": "string",
                "description": "商户名称（update_settings 时可选）",
            },
            "industry": {
                "type": "string",
                "description": "所属行业（update_settings 时可选）",
            },
            "greeting_template": {
                "type": "string",
                "description": "AI问候语模板（update_ai_config 时可选）",
            },
            "business_hours": {
                "type": "string",
                "description": "营业时间描述（update_ai_config 时可选）",
            },
            "ai_config": {
                "type": "object",
                "description": "其他AI配置字段，以字典形式传递（update_ai_config 时可选）",
            },
            "old_password": {
                "type": "string",
                "description": "旧密码（change_password 时必填）",
            },
            "new_password": {
                "type": "string",
                "description": "新密码（change_password 时必填）",
            },
            "page": {
                "type": "integer",
                "description": "页码，默认 1（login_logs 时可选）",
                "default": 1,
            },
            "size": {
                "type": "integer",
                "description": "每页数量，默认 10（login_logs 时可选）",
                "default": 10,
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        name: Optional[str] = None,
        industry: Optional[str] = None,
        greeting_template: Optional[str] = None,
        business_hours: Optional[str] = None,
        ai_config: Optional[Dict[str, Any]] = None,
        old_password: Optional[str] = None,
        new_password: Optional[str] = None,
        page: int = 1,
        size: int = 10,
        **kwargs,
    ) -> ToolResult:
        """执行系统设置管理操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行系统设置管理操作",
                suggestion="请联系管理员获取执行系统设置管理操作权限",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(VALID_ACTIONS)}",
            )

        try:
            if action == "get_settings":
                return await self._get_settings(context)
            elif action == "update_settings":
                return await self._update_settings(context, name, industry)
            elif action == "get_ai_config":
                return await self._get_ai_config(context)
            elif action == "update_ai_config":
                return await self._update_ai_config(
                    context, greeting_template, business_hours, ai_config
                )
            elif action == "change_password":
                return await self._change_password(context, old_password, new_password)
            elif action == "login_logs":
                return await self._login_logs(context, page, size)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )

        except Exception as e:
            logger.error(f"Settings manage error: action={action}, error={e}")
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="系统设置操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    async def _get_settings(
        self,
        context: ToolContext,
    ) -> ToolResult:
        """获取系统设置"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/settings",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"获取系统设置失败：{error_msg}",
            )

        data = response.get("data", {})

        logger.info(f"Settings fetched: tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data=data,
            message="系统设置已获取",
        )

    async def _update_settings(
        self,
        context: ToolContext,
        name: Optional[str],
        industry: Optional[str],
    ) -> ToolResult:
        """更新系统设置"""
        json_data: Dict[str, Any] = {}
        if name:
            json_data["name"] = name
        if industry:
            json_data["industry"] = industry

        if not json_data:
            return ToolResult(
                success=False,
                error="缺少更新参数",
                message="更新设置时至少需要提供一个字段（name 或 industry）",
            )

        client = get_admin_api_client()
        response = await client.put(
            "/api/admin/settings",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"更新系统设置失败：{error_msg}",
            )

        logger.info(
            f"Settings updated: data={json_data}, tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data=json_data,
            message="系统设置已更新",
        )

    async def _get_ai_config(
        self,
        context: ToolContext,
    ) -> ToolResult:
        """获取AI配置"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/tenant/ai-config",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"获取AI配置失败：{error_msg}",
            )

        data = response.get("data", {})

        logger.info(f"AI config fetched: tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data=data,
            message="AI配置已获取",
        )

    async def _update_ai_config(
        self,
        context: ToolContext,
        greeting_template: Optional[str],
        business_hours: Optional[str],
        ai_config: Optional[Dict[str, Any]],
    ) -> ToolResult:
        """更新AI配置"""
        json_data: Dict[str, Any] = {}

        if greeting_template:
            json_data["greetingTemplate"] = greeting_template
        if business_hours:
            json_data["businessHours"] = business_hours
        if ai_config and isinstance(ai_config, dict):
            json_data.update(ai_config)

        if not json_data:
            return ToolResult(
                success=False,
                error="缺少更新参数",
                message="更新AI配置时至少需要提供一个配置字段",
            )

        client = get_admin_api_client()
        response = await client.put(
            "/api/admin/tenant/ai-config",
            json_data=json_data,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "更新失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"更新AI配置失败：{error_msg}",
            )

        logger.info(
            f"AI config updated: keys={list(json_data.keys())}, tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data=json_data,
            message="AI配置已更新",
        )

    async def _change_password(
        self,
        context: ToolContext,
        old_password: Optional[str],
        new_password: Optional[str],
    ) -> ToolResult:
        """修改密码"""
        if not old_password:
            return ToolResult(
                success=False,
                error="缺少旧密码",
                message="修改密码时必须提供旧密码（old_password）",
            )

        if not new_password:
            return ToolResult(
                success=False,
                error="缺少新密码",
                message="修改密码时必须提供新密码（new_password）",
            )

        if len(new_password) < 6:
            return ToolResult(
                success=False,
                error="新密码过短",
                message="新密码长度不能少于 6 位",
            )

        client = get_admin_api_client()
        response = await client.put(
            "/api/admin/settings/password",
            json_data={
                "oldPassword": old_password,
                "newPassword": new_password,
            },
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "修改失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"修改密码失败：{error_msg}",
            )

        logger.info(
            f"Password changed: user={context.user_id}, tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"status": "password_changed"},
            message="密码已修改成功",
        )

    async def _login_logs(
        self,
        context: ToolContext,
        page: int,
        size: int,
    ) -> ToolResult:
        """查询登录日志"""
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/settings/login-logs",
            params={"page": page, "size": size},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return ToolResult(
                success=False,
                error=error_msg,
                message=f"查询登录日志失败：{error_msg}",
            )

        data = response.get("data", {})
        items = data.get("items", [])
        total = data.get("total", 0)

        logger.info(
            f"Login logs fetched: page={page}, size={size}, total={total}, "
            f"tenant={context.tenant_id}"
        )

        return ToolResult(
            success=True,
            data={"items": items, "total": total, "page": page, "size": size},
            message=f"共找到 {total} 条登录日志",
        )
