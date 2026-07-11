"""
AI 智能客服系统 - 交互式组件 Tool

提供结构化交互组件（选择卡片、确认卡片、内联表单），
让用户在对话中通过点击选择代替文本输入，提升复杂场景的交互体验。

组件类型：
- choice:  单选/多选卡片，用户点击选项即可回复
- confirm: 确认卡片，展示待确认信息 + 确认/取消按钮
- form:    内联表单，一次性收集多个信息字段，用户填写后提交
"""

import json
from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult


def _ensure_list(value: Any, field_name: str) -> Optional[List]:
    """将 LLM 可能传入的 JSON 字符串或数组规范化为 list，失败返回 None"""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                logger.info(f"[interact] Parsed {field_name} from JSON string, got {len(parsed)} items")
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    logger.warning(
        f"[interact] {field_name} is not a list: type={type(value).__name__} value={value}"
    )
    return None


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
        "向用户展示交互式选择卡片、确认卡片或内联表单，让用户通过点击/填写代替文本输入。"
        "当需要用户从固定选项中选择（如加工项、分类、色号）、"
        "或需要在执行写操作前确认信息时使用。"
        "使用后对话暂停等待用户操作，不要再继续生成文本。"
        "【重要】confirm 组件的 confirmValue 必须包含上下文（如'确认创建商品'而非'确认'），以便系统正确路由后续消息。"
    )

    # 所有角色可用
    allowed_roles = ["admin", "agent", "tenant_admin", "customer"]

    parameters = {
        "type": "object",
        "properties": {
            "component": {
                "type": "string",
                "description": "组件类型：choice（选项卡片）/ confirm（确认卡片）/ form（内联表单，一次性收集多个信息）",
                "enum": ["choice", "confirm", "form"],
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
            "formFields": {
                "type": "array",
                "description": "form 组件的表单字段列表（component=form 时必填）。每个字段需要 key（标识）、label（显示名）、可选的 placeholder、预填 value、required",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "字段标识，如 name/price/stock"},
                        "label": {"type": "string", "description": "显示标签，如 商品名称"},
                        "placeholder": {"type": "string", "description": "输入提示"},
                        "value": {"type": "string", "description": "预填值（如图片识别出的信息）"},
                        "required": {"type": "boolean", "description": "是否必填", "default": False},
                    },
                    "required": ["key", "label"],
                },
            },
            "submitLabel": {
                "type": "string",
                "description": "form 组件提交按钮文字（默认：提交）",
                "default": "提交",
            },
            "pageMeta": {
                "type": "object",
                "description": "choice 组件分页元数据（可选）。提供时前端渲染分页按钮。包含 current（当前页）、total（总页数）、totalCount（总条数）、tool（查询工具名）、params（查询参数 JSON 字符串）。用户点击翻页后自动调用工具获取对应页数据，无需 LLM 参与。",
                "properties": {
                    "current": {"type": "integer", "description": "当前页码"},
                    "total": {"type": "integer", "description": "总页数"},
                    "totalCount": {"type": "integer", "description": "总条数"},
                    "tool": {"type": "string", "description": "查询工具名（如 processing_item_query）"},
                    "params": {"type": "string", "description": "查询参数的 JSON 字符串（如 {\"keyword\":\"窗帘\",\"page\":1,\"size\":10}）"},
                },
                "required": ["current", "total", "totalCount", "tool", "params"],
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
        formFields: Optional[List[Dict[str, str]]] = None,
        submitLabel: str = "提交",
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
            # 处理 LLM 可能传入 JSON 字符串而非数组的问题
            options = _ensure_list(options, "options")
            if options is None:
                return ToolResult(
                    success=False,
                    error="options 必须是数组",
                    message="选项列表格式错误，请重试",
                )
            if len(options) == 0:
                return ToolResult(
                    success=False,
                    error="choice 组件需要至少一个 option",
                    message="选项列表不能为空",
                )
            # 限制选项数量防止 UI 溢出（auto-interact 生成的上限更高）
            MAX_OPTIONS = 50
            if len(options) > MAX_OPTIONS:
                logger.warning(
                    f"[interact] Too many options ({len(options)}), truncating to {MAX_OPTIONS}"
                )
                options = options[:MAX_OPTIONS]

            interactive_data = {
                "component": "choice",
                "title": title,
                "options": options,
                "multiSelect": multiSelect,
            }

        elif component == "confirm":
            # 处理 LLM 可能传入 JSON 字符串而非数组的问题
            fields = _ensure_list(fields, "fields")
            if fields is None:
                return ToolResult(
                    success=False,
                    error="fields 必须是数组",
                    message="确认信息格式错误，请重试",
                )
            if len(fields) == 0:
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

        elif component == "form":
            formFields = _ensure_list(formFields, "formFields")
            if formFields is None or len(formFields) == 0:
                return ToolResult(
                    success=False,
                    error="form 组件需要至少一个 formField",
                    message="表单字段不能为空",
                )
            # 限制字段数量
            if len(formFields) > 6:
                formFields = formFields[:6]

            # 确保每个字段有 key 和 label
            for f in formFields:
                if not isinstance(f, dict) or "key" not in f or "label" not in f:
                    return ToolResult(
                        success=False,
                        error="每个 formField 必须有 key 和 label",
                        message="表单字段格式错误",
                    )

            interactive_data = {
                "component": "form",
                "title": title,
                "formFields": formFields,
                "submitLabel": submitLabel or "提交",
            }

        else:
            return ToolResult(
                success=False,
                error=f"不支持的组件类型: {component}",
                message="仅支持 choice、confirm、form 组件",
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
