"""
AI 智能客服系统 - 交互式组件 Tool

提供结构化交互组件（选择卡片、确认卡片、内联表单），
让用户在对话中通过点击选择代替文本输入，提升复杂场景的交互体验。

组件类型：
- choice:  单选/多选卡片，用户点击选项即可回复
- confirm: 确认卡片，展示待确认信息 + 确认/取消按钮
- form:    内联表单（预留，后续迭代）
"""

from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult


class InteractTool(BaseTool):
    """交互式组件 Tool

    向用户展示结构化交互组件，替代纯文本问答。
    LLM 在需要用户做选择、确认操作时调用此工具。

    使用场景：
    - 选项选择：加工项、分类、规格等固定选项的场景
    - 操作确认：创建商品/订单前的信息确认
    - 信息补全：表单式信息收集（预留）
    """

    name = "interact"
    description = (
        "向用户展示交互式选择卡片或确认卡片，让用户通过点击选择代替文本输入。"
        "当需要用户从固定选项中选择（如加工项、分类、色号）、"
        "或需要在执行写操作前确认信息时使用。"
        "使用后对话暂停等待用户操作，不要再继续生成文本。"
    )

    # 所有角色可用
    allowed_roles = ["admin", "agent", "tenant_admin", "customer"]

    parameters = {
        "type": "object",
        "properties": {
            "component": {
                "type": "string",
                "description": "组件类型：choice（选项卡片）/ confirm（确认卡片）",
                "enum": ["choice", "confirm"],
            },
            "title": {
                "type": "string",
                "description": "组件标题，简要说明需要用户做什么",
            },
            "options": {
                "type": "array",
                "description": "choice 组件的选项列表（component=choice 时必填）",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "选项显示文本",
                        },
                        "value": {
                            "type": "string",
                            "description": "选项值（用户点击后发送的文本）",
                        },
                        "description": {
                            "type": "string",
                            "description": "选项补充说明（可选，如价格、单位等）",
                        },
                    },
                    "required": ["label", "value"],
                },
            },
            "multiSelect": {
                "type": "boolean",
                "description": "choice 组件是否支持多选（默认 false）",
                "default": False,
            },
            "fields": {
                "type": "array",
                "description": "confirm 组件的展示字段列表（component=confirm 时必填）",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "字段名"},
                        "value": {"type": "string", "description": "字段值"},
                    },
                    "required": ["label", "value"],
                },
            },
            "confirmLabel": {
                "type": "string",
                "description": "确认按钮文字（默认：确认）",
                "default": "确认",
            },
            "cancelLabel": {
                "type": "string",
                "description": "取消按钮文字（默认：取消）",
                "default": "取消",
            },
            "confirmValue": {
                "type": "string",
                "description": "点击确认后发送的文本（默认：确认）",
                "default": "确认",
            },
            "cancelValue": {
                "type": "string",
                "description": "点击取消后发送的文本（默认：取消）",
                "default": "取消",
            },
        },
        "required": ["component", "title"],
    }

    async def execute(
        self,
        context: ToolContext,
        component: str,
        title: str,
        options: Optional[List[Dict[str, str]]] = None,
        multiSelect: bool = False,
        fields: Optional[List[Dict[str, str]]] = None,
        confirmLabel: str = "确认",
        cancelLabel: str = "取消",
        confirmValue: str = "确认",
        cancelValue: str = "取消",
    ) -> ToolResult:
        """执行交互组件请求

        不等待用户输入，仅生成交互组件数据并返回。
        用户点击后，前端发送对应的 value 作为下一条消息。

        Args:
            context: Tool 执行上下文
            component: 组件类型
            title: 组件标题
            options: 选项列表（choice 组件）
            multiSelect: 是否多选（choice 组件）
            fields: 展示字段（confirm 组件）
            confirmLabel: 确认按钮文字
            cancelLabel: 取消按钮文字
            confirmValue: 确认按钮值
            cancelValue: 取消按钮值

        Returns:
            ToolResult: 包含交互组件定义
        """
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="无法展示交互组件",
            )

        if component == "choice":
            if not options or len(options) == 0:
                return ToolResult(
                    success=False,
                    error="choice 组件需要至少一个 option",
                    message="选项列表不能为空",
                )
            # 限制选项数量防止 UI 溢出
            if len(options) > 8:
                logger.warning(
                    f"[interact] Too many options ({len(options)}), truncating to 8"
                )
                options = options[:8]

            interactive_data = {
                "component": "choice",
                "title": title,
                "options": options,
                "multiSelect": multiSelect,
            }

        elif component == "confirm":
            if not fields or len(fields) == 0:
                return ToolResult(
                    success=False,
                    error="confirm 组件需要至少一个 field",
                    message="确认信息不能为空",
                )

            interactive_data = {
                "component": "confirm",
                "title": title,
                "fields": fields,
                "confirmLabel": confirmLabel,
                "cancelLabel": cancelLabel,
                "confirmValue": confirmValue,
                "cancelValue": cancelValue,
            }

        else:
            return ToolResult(
                success=False,
                error=f"不支持的组件类型: {component}",
                message="仅支持 choice 和 confirm 组件",
            )

        logger.info(
            f"[interact] {component} component | title={title} "
            f"tenant={context.tenant_id} user={context.user_id}"
        )

        return ToolResult(
            success=True,
            data=interactive_data,
            message=f"已展示{title}交互组件，等待用户操作",
        )
