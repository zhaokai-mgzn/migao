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
            "required": ["name", "price", "category_id"],
            "name": {"type": str, "min_len": 1, "label": "商品名称"},
            "price": {"type": (int, float), "min": 0, "label": "价格"},
            "stock_quantity": {"type": int, "min": 0, "label": "库存数量"},
            "category_id": {"type": str, "label": "分类ID"},
            "description": {"type": str, "label": "描述"},
            "processing_item_ids": {"type": list, "label": "加工项ID列表"},
            "status": {"type": str, "label": "商品状态(on_sale/off_sale)"},
        },
        "update": {
            "required": ["product_id"],
            "product_id": {"type": str, "min_len": 1, "label": "商品ID"},
        },
    },
    "order_create": {
        "create": {
            "required": ["customer_name", "customer_phone", "items"],
            "customer_name": {"type": str, "min_len": 1, "label": "客户姓名"},
            "customer_phone": {"type": str, "min_len": 1, "label": "客户电话（11位手机号）"},
            "items": {"type": list, "min_len": 1, "label": "商品明细"},
            "customer_address": {"type": str, "label": "收货地址"},
            "remark": {"type": str, "label": "备注"},
        },
    },
    "product_processing_item_manage": {
        "add": {
            "required": ["product_id", "item_ids"],
            "product_id": {"type": str, "min_len": 1, "label": "商品ID（支持名称/UUID/序号）"},
            "item_ids": {"type": list, "min_len": 1, "label": "加工项ID列表（支持名称/UUID/序号）"},
        },
        "remove": {
            "required": ["product_id", "item_ids"],
            "product_id": {"type": str, "min_len": 1, "label": "商品ID（支持名称/UUID/序号）"},
            "item_ids": {"type": list, "min_len": 1, "label": "加工项ID列表（支持名称/UUID/序号）"},
        },
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
    "inventory_manage": {
        "adjust": {
            "required": ["product_id", "adjustment", "reason"],
            "product_id": {"type": str, "min_len": 1, "label": "商品ID"},
            "adjustment": {"type": int, "label": "调整数量（正数增加，负数减少，不能为0）"},
            "reason": {"type": str, "min_len": 1, "label": "调整原因"},
        },
    },
    "after_sales_manage": {
        "create": {
            "required": ["ticket_type", "order_id", "reason"],
            "ticket_type": {"type": str, "min_len": 1, "label": "工单类型(退款/换货/维修/投诉/其他; 传值 refund/exchange/repair/complaint/other)"},
            "order_id": {"type": str, "min_len": 1, "label": "关联订单ID"},
            "reason": {"type": str, "min_len": 1, "label": "原因说明"},
            "description": {"type": str, "label": "详细描述"},
            "images": {"type": list, "label": "凭证图片URL列表"},
            "priority": {"type": str, "label": "优先级(普通/紧急/严重; 传值 normal/urgent/critical)"},
            "refund_amount": {"type": (int, float), "min": 0, "label": "退款金额"},
        },
    },
    "aftersale_create": {
        "create": {
            "required": ["order_id", "ticket_type", "reason"],
            "order_id": {"type": str, "min_len": 1, "label": "订单ID"},
            "ticket_type": {
                "type": str,
                "min_len": 1,
                "label": "工单类型",
                "enum": ["refund", "exchange", "repair", "complaint", "other"],
            },
            "reason": {"type": str, "min_len": 1, "label": "原因说明"},
            "description": {"type": str, "label": "详细描述"},
            "images": {"type": list, "label": "凭证图片URL列表"},
            "priority": {
                "type": str,
                "label": "优先级",
                "enum": ["normal", "urgent", "critical"],
            },
            "refund_amount": {"type": (int, float), "min": 0, "label": "退款金额"},
        },
    },
    "employee_manage": {
        "create": {
            "required": ["name", "phone"],
            "name": {"type": str, "min_len": 1, "label": "员工姓名"},
            "phone": {"type": str, "min_len": 1, "label": "手机号"},
        },
    },
    # CU-004 回归防线：validate_input 对 customer_manage(update) 此前无规则 → 返回
    # 「未知工具/无需校验」，LLM 据此幻觉「手机号修改不支持」——但 admin-api
    # updateCustomer 明确支持 phone。补规则消除空转信号。
    "customer_manage": {
        "update": {
            "required": ["customer_id", "data"],
            "customer_id": {"type": str, "min_len": 1, "label": "客户 UUID"},
            "data": {"type": dict, "label": "更新数据（可含 phone/name 等字段）"},
        },
        "add_tag": {
            "required": ["customer_id", "tag_id"],
            "customer_id": {"type": str, "min_len": 1, "label": "客户 UUID"},
            "tag_id": {"type": str, "min_len": 1, "label": "标签 ID"},
        },
    },
    # HR-005 回归防线：role_manage 写操作此前无规则 → validate_input 返回「未知工具」，
    # LLM 据此退化到文本预览确认（不走 interact confirm 卡），角色创建流程不稳定。
    # 补规则让角色创建/更新/删除走标准校验+确认链（对齐 role_manage.py 硬必填）。
    # Round 45 WRITE 工具覆盖审计：finance_api/notification_manage/
    # processing_item_manage/product_update/session_manage/settings_manage/
    # sku_update 写操作此前无规则 → validate_input 返回「未知工具」→ agent 按
    # 安全规则拒绝执行。补规则让所有写工具走标准校验+确认链。
    "finance_api": {
        "create_transaction": {
            "required": ["type", "amount"],
            "type": {"type": str, "label": "收支类型(income/refund)", "enum": ["income", "refund"]},
            "amount": {"type": (int, float), "min": 0, "label": "金额"},
        },
    },
    "notification_manage": {
        "mark_read": {
            "required": ["notification_id"],
            "notification_id": {"type": str, "min_len": 1, "label": "通知 ID"},
        },
        "delete": {
            "required": ["notification_id"],
            "notification_id": {"type": str, "min_len": 1, "label": "通知 ID"},
        },
        "create": {
            "required": ["title", "content"],
            "title": {"type": str, "min_len": 1, "label": "通知标题"},
            "content": {"type": str, "min_len": 1, "label": "通知内容"},
        },
    },
    "processing_item_manage": {
        "create_processing_item": {
            "required": ["name", "category_id"],
            "name": {"type": str, "min_len": 1, "label": "加工项名称"},
            "category_id": {"type": str, "min_len": 1, "label": "分类 ID"},
        },
        "update_item": {
            "required": ["item_id"],
            "item_id": {"type": str, "min_len": 1, "label": "加工项 ID"},
        },
        "delete": {
            "required": ["item_id"],
            "item_id": {"type": str, "min_len": 1, "label": "加工项 ID"},
        },
    },
    "product_update": {
        "update": {
            "required": ["product_id"],
            "product_id": {"type": str, "min_len": 1, "label": "商品 ID"},
        },
    },
    "session_manage": {
        "assign": {
            "required": ["session_id", "employee_id"],
            "session_id": {"type": str, "min_len": 1, "label": "会话 ID"},
            "employee_id": {"type": str, "min_len": 1, "label": "客服 ID"},
        },
        "end": {
            "required": ["session_id"],
            "session_id": {"type": str, "min_len": 1, "label": "会话 ID"},
        },
    },
    "settings_manage": {
        "change_password": {
            "required": ["old_password", "new_password"],
            "old_password": {"type": str, "min_len": 1, "label": "旧密码"},
            "new_password": {"type": str, "min_len": 1, "label": "新密码"},
        },
        "update_settings": {
            "required": ["data"],
            "data": {"type": dict, "label": "配置更新数据"},
        },
        "update_ai_config": {
            "required": ["data"],
            "data": {"type": dict, "label": "AI 配置更新数据"},
        },
    },
    "sku_update": {
        "update": {
            "required": ["product_id"],
            "product_id": {"type": str, "min_len": 1, "label": "商品 ID"},
        },
    },
    # CT-002 回归防线：category_manage 写操作此前无规则 → validate_input 返回
    # 「未知工具」→ agent 按安全规则拒绝创建（PROMPT-rules：校验失败禁止执行写工具）。
    # 补规则让分类创建/更新/删除走标准校验+确认链（对齐 category_manage.py 契约：
    # create 只需 name，无需父分类；update/delete 需 category_id）。
    "category_manage": {
        "create": {
            "required": ["name"],
            "name": {"type": str, "min_len": 1, "label": "分类名称"},
        },
        "update": {
            "required": ["category_id", "name"],
            "category_id": {"type": str, "min_len": 1, "label": "分类 ID"},
            "name": {"type": str, "min_len": 1, "label": "分类名称"},
        },
        "delete": {
            "required": ["category_id"],
            "category_id": {"type": str, "min_len": 1, "label": "分类 ID"},
        },
    },
    "role_manage": {
        "create": {
            "required": ["name", "code"],
            "name": {"type": str, "min_len": 1, "label": "角色名称"},
            "code": {"type": str, "min_len": 1, "label": "角色编码"},
            "permission_ids": {"type": list, "label": "权限 ID 列表"},
            "description": {"type": str, "label": "角色描述"},
        },
        "update": {
            "required": ["role_id"],
            "role_id": {"type": str, "min_len": 1, "label": "角色 ID"},
        },
        "delete": {
            "required": ["role_id"],
            "role_id": {"type": str, "min_len": 1, "label": "角色 ID"},
        },
    },
}

# 管理类操作的通用必填校验
_MANAGE_UPDATE_REQUIRED = ["product_id"]


def _format_param_value(val: Any, max_items: int = 20) -> str:
    """格式化参数值用于回显摘要，数组截断避免 token 爆炸"""
    if isinstance(val, list):
        if len(val) == 0:
            return "`[]` (空)"
        items = [str(v) for v in val[:max_items]]
        suffix = f" ... (+{len(val) - max_items})" if len(val) > max_items else ""
        return f"`[{', '.join(items)}{suffix}]` ({len(val)} 项)"
    if isinstance(val, dict):
        keys = list(val.keys())[:10]
        return f"`{{{', '.join(keys)}}}`"
    if isinstance(val, str):
        return f"`{val}`"
    if val is None:
        return "`(空)`"
    return f"`{val}`"


class ValidateInputTool(BaseTool):
    """前置校验工具

    在调用 admin-api 写操作前，本地验证参数完整性。
    返回结构化缺失字段列表，让 LLM 能理解并纠正。
    """

    name = "validate_input"
    description = (
        "【触发】调用 product_manage、order_create、order_manage 等写操作前，先调用本工具校验参数完整性。【前置】需要 target_tool + target_action + params。校验通过返回 success=true。【反例】不要跳过校验直接调写操作。查询操作不需要校验。【标注】READONLY — 纯本地校验，不调用外部API"
    )
    # ⚠️ 必须含 `customer`（C 端小布）：本工具是**纯本地参数校验**（description 自述
    # READONLY、不调用外部 API），小布的 `customer_aftersales` 绑定它，而 `base_skill`
    # 的「确认-执行链」依赖它**成功**才持久化「已校验待执行」状态：
    #     if tool_name == "validate_input" and result_dict.get("success"): → 落 pending
    # 此前不含 customer → 顾客调用一律 `权限不足` → C 端售后 confirm 永远换不来执行
    # （CI 实证 run 34620594324：`failed=validate_input!权限不足` → 兜底 human_handoff，
    #  aftersale_create 整轮 0 次成功）。
    # 安全性：本工具不读库、不写库、不访问外部服务，只校验调用方自己传来的参数；
    # 真正的权限门禁在各自写工具的 allowed_roles 上，放开这里不构成越权。
    allowed_roles = ["admin", "agent", "tenant_admin", "customer"]

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

        tool_rules = _VALIDATION_RULES.get(target_tool)
        if tool_rules is None:
            # 未知工具 → 拒绝校验，防止绕过
            return ToolResult(
                success=False,
                error="未知的工具",
                message=f"未知的工具或操作: {target_tool}/{target_action}，无法进行输入校验。请联系管理员确认工具是否已注册。",
            )

        rules = tool_rules.get(target_action)
        if not rules:
            # 工具已注册但该操作无校验规则 → 跳过（不是所有操作都有规则）
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

            # 枚举值检查（如工单类型/售卖方式等受限枚举）
            enum_vals = rule.get("enum")
            if enum_vals and val not in enum_vals:
                label = rule.get("label", field)
                issues.append(
                    f"取值非法: {label} ({field}) 应为 {enum_vals} 之一，实际为 {val!r}"
                )

        # 3. update 操作检查 product_id（仅商品类工具；customer_manage 等用规则表
        #    声明的 customer_id，不得误套 product_id——CU-004 回归）
        if target_action == "update" and target_tool in ("product_manage", "product_update"):
            pid = params.get("product_id") or params.get("id")
            if not pid:
                issues.append("缺少 product_id（更新操作必须指定商品ID）")

        # 4. 手机号格式检查（对抗编程：order_create 中防止 LLM 编造号码）
        if target_tool == "order_create":
            phone = params.get("customer_phone")
            if phone and isinstance(phone, str):
                phone = phone.strip()
                if not (len(phone) == 11 and phone.startswith("1") and phone.isdigit()):
                    issues.append(
                        f"手机号 \"{phone}\" 格式不正确。"
                        f"请输入 11 位中国大陆手机号（1 开头）。"
                    )

        # 5. 加工项ID格式检查
        pids = params.get("processing_item_ids")
        if pids and isinstance(pids, list):
            for pid in pids:
                pid_str = str(pid).strip()
                # 纯数字 → 拒绝，引导LLM使用真实UUID
                if pid_str.isdigit():
                    issues.append(
                        f"加工项ID \"{pid_str}\" 是序号而非真实ID。"
                        f"请使用 processing_item_query 返回的真实ID（如 pi_xxxxxxxxxxxxxxxx），"
                        f"不要使用行号/序号。"
                    )
                # 非数字非 UUID 格式的 ID — 宽松通过（processing_item_query 返回的 ID 格式多样）

        # 6. 建品参数确定性兜底（issue #3052，2026-09-08 Round2 实拍）：
        #    prompt 指令会被 LLM 方差漏掉 → validate_input 必须成为确定性闸门
        #    - specifications 键必须存在（用户明确拒绝规格时传空对象 {}）
        #    - 选了加工项 → processing_item_configs 必须存在且每项含 customPrice+unit
        if target_tool == "product_manage" and target_action == "create":
            if "specifications" not in params:
                issues.append(
                    "缺少 specifications（窗帘默认规格：{\"克重\":\"200-300g\",\"材质\":\"涤纶\",\"功能\":\"遮光\","
                    "\"工艺\":\"色织\",\"风格\":\"现代简约\",\"图案\":\"纯色\"}；"
                    "用户明确表示不需要规格时传空对象 {}）"
                )
            pcs = params.get("processing_item_configs")
            if (pids and isinstance(pids, list) and pids) or (pcs and isinstance(pcs, list) and pcs):
                if not pcs or not isinstance(pcs, list) or not pcs:
                    issues.append(
                        "选了加工项但未传 processing_item_configs（必须为列表，每项含 "
                        "{processingItemId, customPrice, unit}；customPrice 取 processing_item_query 返回的 unit_price）"
                    )
                else:
                    for pc in pcs:
                        if not isinstance(pc, dict):
                            issues.append("processing_item_configs 元素必须是对象")
                            break
                        if not (pc.get("customPrice") or pc.get("unit_price")):
                            issues.append(
                                f"processing_item_configs 缺价格 customPrice/unit_price: {str(pc)[:100]}"
                            )
                            break
                        if not pc.get("unit"):
                            issues.append(
                                f"processing_item_configs 缺单位 unit: {str(pc)[:100]}"
                            )
                            break

        if issues:
            return ToolResult(
                success=False,
                data={"issues": issues, "missing_fields": missing},
                error="参数校验失败",
                message=f"参数校验失败，请补充以下信息后重试:\n" + "\n".join(f"  - {i}" for i in issues),
            )

        logger.info(f"[validate_input] {target_tool}.{target_action} passed validation")

        # 校验通过后回显完整参数摘要，让 LLM 在调用前自我检查是否遗漏
        summary_lines = ["## ✅ 校验通过 — 即将发送的参数", ""]
        summary_lines.append("| 参数 | 值 |")
        summary_lines.append("|------|-----|")
        for key, val in params.items():
            if key == "action":
                continue
            display = _format_param_value(val)
            summary_lines.append(f"| {key} | {display} |")
        summary_lines.append("")
        summary_lines.append("> ⚠️ 请逐项核对以上参数是否与你向用户确认的内容一致。")
        summary_lines.append("> 如有遗漏（如少了某个售卖方式/颜色/门幅），请立即修正参数后重新校验。")
        # product_manage.create 加工项遗漏提醒
        if target_tool == "product_manage" and target_action == "create":
            pids = params.get("processing_item_ids")
            if not pids:
                summary_lines.append("> ⚠️ 未传入 processing_item_ids，如用户已选加工项请务必添加")
        summary_lines.append(f"> 确认无误后，立即调用 {target_tool}(action='{target_action}', ...) 执行。")
        summary = "\n".join(summary_lines)

        return ToolResult(
            success=True,
            data={"validated": True, "params": params},
            message=summary,
        )
