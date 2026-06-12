"""
前置校验工具 — 在调用 admin-api 写操作前验证参数完整性

将 422 错误转化为 LLM 可理解的结构化提示。
不调用任何外部 API，纯本地校验。
"""
from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult


# ── 各工具的参数校验规则 ──

_VALIDATION_RULES: Dict[str, Dict[str, Any]] = {
    "product_manage": {
        "create": {
            "required": ["name", "price"],
            "name": {"type": str, "min_len": 1, "label": "商品名称"},
            "price": {"type": (int, float), "min": 0, "label": "价格"},
            "stock_quantity": {"type": int, "min": 0, "label": "库存数量"},
            "category_id": {"type": str, "label": "分类ID"},
            "description": {"type": str, "label": "描述"},
        },
        "update": {
            "required": ["product_id"],
            "product_id": {"type": str, "min_len": 1, "label": "商品ID"},
        },
    },
    "order_create": {
        "required": ["customer_name", "customer_phone", "items"],
        "customer_name": {"type": str, "min_len": 1, "label": "客户姓名"},
        "customer_phone": {"type": str, "min_len": 1, "label": "客户电话"},
        "items": {"type": list, "min_len": 1, "label": "商品明细"},
    },
    "order_manage": {
        "cancel": {
            "required": ["order_id"],
            "order_id": {"type": str, "min_len": 1, "label": "订单ID或订单号"},
        },
        "refund": {
            "required": ["order_id"],
            "order_id": {"type": str, "min_len": 1, "label": "订单ID或订单号"},
        },
    },
    "after_sales_manage": {
        "create": {
            "required": ["ticket_type", "order_id", "reason"],
            "ticket_type": {"type": str, "min_len": 1, "label": "工单类型(refund/exchange/repair/complaint/other)"},
            "order_id": {"type": str, "min_len": 1, "label": "关联订单ID"},
            "reason": {"type": str, "min_len": 1, "label": "原因说明"},
        },
    },
    "employee_manage": {
        "create": {
            "required": ["name", "phone"],
            "name": {"type": str, "min_len": 1, "label": "员工姓名"},
            "phone": {"type": str, "min_len": 1, "label": "手机号"},
        },
    },
}

# 管理类操作的通用必填校验
_MANAGE_UPDATE_REQUIRED = ["product_id"]


class ValidateInputTool(BaseTool):
    """前置校验工具

    在调用 admin-api 写操作前，本地验证参数完整性。
    返回结构化缺失字段列表，让 LLM 能理解并纠正。
    """

    name = "validate_input"
    description = (
        "【触发】调用 product_manage、order_create、order_manage 等写操作前，先调用本工具校验参数完整性。【前置】需要 target_tool + target_action + params。校验通过返回 success=true。【反例】不要跳过校验直接调写操作。查询操作不需要校验。【标注】READONLY — 纯本地校验，不调用外部API"
    )
    allowed_roles = ["admin", "agent", "tenant_admin"]

    parameters = {
        "type": "object",
        "properties": {
            "target_tool": {
                "type": "string",
                "description": "要校验的目标写工具，如 product_manage、order_create",
            },
            "target_action": {
                "type": "string",
                "description": "目标工具的操作类型，如 create、update",
            },
            "params": {
                "type": "object",
                "description": "要传递给目标工具的参数（JSON 对象）",
            },
        },
        "required": ["target_tool", "target_action", "params"],
    }

    async def execute(
        self,
        context: ToolContext,
        target_tool: str,
        target_action: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        if not self.check_permission(context):
            return ToolResult(success=False, error="权限不足")

        if not params:
            return ToolResult(
                success=False,
                error="缺少参数",
                message="请提供要校验的参数",
            )

        rules = _VALIDATION_RULES.get(target_tool, {}).get(target_action)
        if not rules:
            # 无校验规则 → 跳过（不是所有工具都有规则）
            return ToolResult(
                success=True,
                data={"validated": True, "skipped": True},
                message="无需校验（该操作无预定义规则）",
            )

        issues: List[str] = []
        missing: List[str] = []

        # 1. 必填字段检查
        for field in rules.get("required", []):
            val = params.get(field)
            if val is None or (isinstance(val, str) and not val.strip()):
                label = rules.get(field, {}).get("label", field)
                missing.append(label)
                issues.append(f"缺少必填字段: {label} ({field})")

        # 2. 类型和范围检查
        for field, rule in rules.items():
            if field == "required":
                continue
            val = params.get(field)
            if val is None:
                continue

            expected_type = rule.get("type")
            if expected_type:
                if isinstance(expected_type, tuple):
                    type_ok = isinstance(val, expected_type)
                else:
                    type_ok = isinstance(val, expected_type)
                if not type_ok:
                    label = rule.get("label", field)
                    type_name = getattr(expected_type, "__name__", str(expected_type))
                    issues.append(f"类型错误: {label} ({field}) 应为 {type_name}")

            min_val = rule.get("min")
            if min_val is not None and isinstance(val, (int, float)) and val < min_val:
                label = rule.get("label", field)
                issues.append(f"数值过小: {label} ({field}) 最小值为 {min_val}")

            min_len = rule.get("min_len")
            if min_len is not None and isinstance(val, (str, list)) and len(val) < min_len:
                label = rule.get("label", field)
                issues.append(f"长度不足: {label} ({field}) 最少需要 {min_len} 个")

        # 3. update 操作检查 product_id
        if target_action == "update":
            pid = params.get("product_id") or params.get("id")
            if not pid:
                issues.append("缺少 product_id（更新操作必须指定商品ID）")

        if issues:
            return ToolResult(
                success=False,
                data={"issues": issues, "missing_fields": missing},
                error="参数校验失败",
                message=f"参数校验失败，请补充以下信息后重试:\n" + "\n".join(f"  - {i}" for i in issues),
            )

        logger.info(f"[validate_input] {target_tool}.{target_action} passed validation")
        return ToolResult(
            success=True,
            data={"validated": True},
            message="参数校验通过，可以执行操作",
        )
