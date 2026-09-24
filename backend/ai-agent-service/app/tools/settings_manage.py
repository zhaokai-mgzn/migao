"""
AI 智能客服系统 - 系统设置管理 Tool（**只读**）

查询系统设置、AI 客服配置与登录日志。

🔴 **B 端米宝只读化**（issue #5247 用户裁定 2026-09-23；settings 域整域收口 = issue #5302）：
写能力（`update_settings` / `update_ai_config` / `change_password`）**已从本工具删除**，
对应写方法与**写参数**一并删除（不是"只从 description 里摘掉"）。
⚠️ `VALID_ACTIONS` 是本工具 action 面的**唯一真值**：往这里加回写 action = 写能力复活
（判据：`backend/ai-agent-service/tests/test_settings_domain_readonly.py` +
`tests/unit_ci_workflows/test_mibao_b_end_readonly.py` 的判据 6 —— 后者按 **skill 声明的 persona**
取射程，故「把 skill 从 skill_names 解绑」不能把本工具移出只读约束）。
"""

from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型 —— **全部只读**（#5302）。三个 action 与 admin-api 读端点一对一：
#   get_settings  → `GET /api/admin/settings`
#   get_ai_config → `GET /api/admin/tenant/ai-config`
#   login_logs    → `GET /api/admin/settings/login-logs`
VALID_ACTIONS = {"get_settings", "get_ai_config", "login_logs"}


class SettingsManageTool(BaseTool):
    """系统设置查询 Tool（只读）

    查询系统设置、AI 客服配置与登录日志。

    使用场景：
    - 获取当前系统设置（商户名称、行业等）
    - 获取 AI 客服配置（问候语模板、营业时间等）
    - 查看登录日志

    **不提供**：调整系统参数 / 修改 AI 配置 / 修改密码 —— 引导用户到商户后台页面自助操作
    （改密码在后台亦无自助入口，见 issue #3006/#3098 ⇒ 引导联系管理员）。
    """

    name = "settings_manage"
    description = (
        "【触发】用户问'系统设置''配置''AI配置''模型''问候语''登录日志'时调用。"
        "【参数】action 必填：**只有 get_settings（获取设置）/ get_ai_config（获取AI配置）/ "
        "login_logs（登录日志）三个只读 action**（B 端已只读化，issue #5247 / #5302）。"
        "【反例】通知查询用 notification_manage；角色权限用 role_manage。"
        "【反例】调整系统参数 / 修改 AI 配置**不在本工具能力内** —— 引导用户到商户后台"
        "「企业基础信息 → 基本设置 / AI 客服设置」页自助修改。"
        "【反例】修改密码**不在本工具能力内**（后台暂无自助改密入口）—— 如实告知，"
        "并引导用户联系管理员处理，禁止承诺「已改好」。"
        "【标注】READONLY — 纯查询，不含任何写 action"
    )
    # 权限码（admin-api 目录）：本工具**仍调用**的三个读端点都是
    # `@RequirePermission("system:manage")`（`SettingsController`）⇒ 该码是**读码**，必须保留：
    # 移除它会让三个读 action 全量 403。该域读写同码（写粒度债如实登记在
    # `tests/unit_ci_workflows/test_agent_permission_parity.py` 的
    # `REGISTERED_RESIDUALS`「settings 域写面未注解」）⇒ #5302 后本工具不再调用任何写端点，
    # **没有**可移除的写码（不是漏删）。
    required_permissions = ["system:manage"]

    read_only = True
    read_only_actions = {"get_settings", "get_ai_config", "login_logs"}  # 只读 action 免确认拦截

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "操作类型：get_settings（获取设置）/ get_ai_config（获取AI配置）/ "
                    "login_logs（登录日志）—— 均为只读"
                ),
                "enum": ["get_settings", "get_ai_config", "login_logs"],
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
        page: int = 1,
        size: int = 10,
        **kwargs,
    ) -> ToolResult:
        """执行系统设置**查询**操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行系统设置管理操作",
                suggestion="请联系管理员获取执行系统设置管理操作权限",
            )

        # 参数校验（写 action 在这里即被拒 —— 不是"描述里没写"，而是**不存在**）
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(sorted(VALID_ACTIONS))}",
                suggestion=(
                    "本工具只提供只读查询（get_settings / get_ai_config / login_logs）。"
                    "调整系统参数 / 修改 AI 配置 / 修改密码不在本工具能力内 —— "
                    "请如实告知用户，并引导其到商户后台「企业基础信息」页自助操作"
                    "（改密码在后台无自助入口 ⇒ 引导联系管理员）"
                ),
            )

        try:
            if action == "get_settings":
                return await self._get_settings(context)
            elif action == "get_ai_config":
                return await self._get_ai_config(context)
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
            logger.error(f"Settings manage error: action={action}, error={e}", exc_info=True)
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
            return admin_api_failure(response,
                error=error_msg,
                message=f"获取系统设置失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请让用户通过商户后台「系统设置」页查看，或联系平台管理员",
            )

        data = response.get("data", {})

        logger.info(f"Settings fetched: tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data=data,
            message="系统设置已获取",
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
            return admin_api_failure(response,
                error=error_msg,
                message=f"获取AI配置失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请让用户通过商户后台「AI 配置」页查看，或联系平台管理员",
            )

        data = response.get("data", {})

        logger.info(f"AI config fetched: tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data=data,
            message="AI配置已获取",
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
            return admin_api_failure(response,
                error=error_msg,
                message=f"查询登录日志失败：{error_msg}",
                suggestion="请稍后重试；若持续失败，请缩小时间范围或请用户联系管理员核对登录日志数据",
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