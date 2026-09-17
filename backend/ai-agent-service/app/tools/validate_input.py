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
        # issue #4011 A4：此前无规则 ⇒ skipped 假绿（上下架是**面向顾客可见性**的写操作）。
        # required/枚举按工具实现 `_toggle_status` 与 `VALID_PRODUCT_STATUSES`：on_sale/off_sale
        # （draft/under_review 是后台人工流程，Agent 无权限，issue #3686）。
        "toggle_status": {
            "required": ["product_id", "status"],
            "status": {"type": str, "enum": ["on_sale", "off_sale"], "label": "商品状态"},
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
        # 三个此前无规则的 action（issue #3566 核查）：闸门走「该操作无预定义规则」分支，
# 改前**直接放行**（连 order_id 都不校验——其中 confirm_payment 是**资金动作**）；
# issue #4011 A4 起该分支已改为 fail-closed，规则仍必须补齐（否则模型拿不到闸门保护）。
        # 真实契约在 Service 分支里（`OrderService.java:1585-1629`），工具统一 PATCH
        # `/api/admin/agent/orders/{id}`（`order_manage.py:128`）。
        "update_status": {
            "required": ["order_id", "status"],
            "order_id": {"type": str, "min_len": 1, "label": "订单ID或订单号"},
            # 状态集 = `OrderService.java:79-86` STATUS_TRANSITIONS（key ∪ 目标值），
            # 非法值/非法流转由 Service 拒（`:507-521`），闸门先拦非法取值
            "status": {
                "type": str,
                "min_len": 1,
                "label": "订单新状态（pending/confirmed/producing/shipped/completed/cancelled）",
                "enum": ["pending", "confirmed", "producing", "shipped", "completed", "cancelled"],
            },
        },
        "update_logistics": {
            "required": ["order_id", "logistics_company", "tracking_number"],
            "order_id": {"type": str, "min_len": 1, "label": "订单ID或订单号"},
            "logistics_company": {"type": str, "min_len": 1, "label": "快递公司"},
            "tracking_number": {"type": str, "min_len": 1, "label": "运单号"},
        },
        "confirm_payment": {
            "required": ["order_id"],
            "order_id": {"type": str, "min_len": 1, "label": "订单ID或订单号"},
        },
        "cancel": {
            "required": ["order_id"],
            "order_id": {"type": str, "min_len": 1, "label": "订单ID或订单号"},
            "cancel_reason": {"type": str, "label": "取消原因（可选）"},
        },
        "refund": {
            "required": ["order_id"],
            "order_id": {"type": str, "min_len": 1, "label": "订单ID或订单号"},
            # 退款额可选（缺省全额，`OrderService.java:1123`），但显式传 0 必被拒
            # （`:1125-1135`：负数拒、累计封顶后 <=0 → 「已全额退款，无需重复退款」）
            "refund_amount": {
                "type": (int, float),
                "min": 0.01,
                "label": "退款金额（元，可选；不传=全额退款）",
            },
            "refund_reason": {"type": str, "label": "退款原因（可选）"},
        },
    },
    # ⚠️ 加工单工具的闸门规则已随注册表移除（产品决策 2026-09-15，issue #3917）：
    # agent 暂不接入 processing_order_*，工具不可达 ⇒ 规则永不命中 = 死键
    # （test_tools_validate_input 的 L0 不变式会拦）。未来恢复接入时（registry +
    # order_skill + prompts/order.md 三处一起恢复）把下方两个规则块加回来：
    #   "processing_order_generate": {"generate": {"required": ["order_ids"], ...}},
    #   "processing_order_update": {"issue": {required:["id"]...}, "start":..., ...}
    # （旧规则全文见 git 历史：validate_input.py 在 2026-09-15 前的版本）
    "inventory_manage": {
        "adjust": {
            "required": ["product_id", "adjustment", "reason"],
            "product_id": {"type": str, "min_len": 1, "label": "商品ID"},
            # nonzero：adjustment=0 被 Service 拒（`ProductService.java:1716-1718`
            # 「调整量 adjustment 不能为空或 0」）→ 闸门必须同样拦下（issue #3566 核查）
            "adjustment": {"type": int, "nonzero": True, "label": "调整数量（正数增加，负数减少，不能为0）"},
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
        # issue #4011 A4（本次全量审计补出的同族缺口，issue 正文未列）：
        # `update_status` 是工单状态变更（对顾客可见的写），此前同样无规则 ⇒ skipped 假绿。
        # required/枚举按工具实现 `_update_status` 与 `VALID_TICKET_STATUSES`
        # （`after_sales_manage.py`：pending/processing/resolved/rejected/closed）。
        "update_status": {
            "required": ["ticket_id", "status"],
            "status": {"type": str, "enum": ["pending", "processing", "resolved",
                                             "rejected", "closed"],
                       "label": "工单状态"},
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
        # issue #4011 A4：下面 4 个 action 此前无规则 ⇒ 闸门返回 skipped 假绿。
        # required 只列**工具实现硬拦**的字段（`employee_manage.py`）：`_update_user`/
        # `_delete_user`/`_reset_password` 硬拦 user_id（“至少一个可改字段”与 new_password
        # 缺省随机生成都由工具自己兜底）；`_toggle_status` 硬拦 user_id + status。
        # 可选字段不声明字段级规则 = 不误拦合法取值（最简：只有会真拦的东西才写）。
        "update": {"required": ["user_id"]},
        "delete": {"required": ["user_id"]},
        "reset_password": {"required": ["user_id"]},
        "toggle_status": {
            "required": ["user_id", "status"],
            # 枚举值取工具白名单，非法值由工具/服务端拒（这里只提前拦）
            "status": {"type": str, "enum": ["active", "disabled"], "label": "员工状态"},
        },
    },
    # CU-004 回归防线：validate_input 对 customer_manage(update) 此前无规则 → 返回
    # 「未知工具/无需校验」，LLM 据此幻觉「手机号修改不支持」——但 admin-api
    # updateCustomer 明确支持 phone。补规则消除空转信号。
    "customer_manage": {
        "update": {
            "required": ["customer_id", "data"],
            "customer_id": {"type": str, "min_len": 1, "label": "客户 UUID"},
            "data": {"type": dict, "label": "更新数据（可写字段：wechatNickname/phone/gender/region*/vipLevel/customerStatus/agentNotes/tags/customFields）"},
        },
        "add_tag": {
            "required": ["customer_id", "tag_id"],
            "customer_id": {"type": str, "min_len": 1, "label": "客户 UUID"},
            "tag_id": {"type": str, "min_len": 1, "label": "标签 ID"},
        },
        # issue #4011 A4：4 个 tag 写操作此前无规则 ⇒ skipped 假绿。
        # required 按工具实现硬拦的字段（`customer_manage.py` `_*_tag`）：add/remove 要
        # customer_id+tag_id，create 要 name，update 要 tag_id（name/color 至少一项由工具
        # 自己兜底报错），delete 要 tag_id。
        "remove_tag": {"required": ["customer_id", "tag_id"]},
        "create_tag": {"required": ["name"]},
        "update_tag": {"required": ["tag_id"]},
        "delete_tag": {"required": ["tag_id"]},
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
            # 契约下限 0.01（`FinanceTransactionCreateRequest.java:21-23` @DecimalMin(0.01)），
            # 旧规则 min=0 → amount=0 放行后必被 422（issue #3566 核查）
            "amount": {"type": (int, float), "min": 0.01, "label": "金额（>0，最低 0.01）"},
        },
    },
    # ── issue #4011 A4：缺口补齐的通用口径（本次补的规则分散在各自的工具块里）──
    # 缺口形态：工具已注册、该 action 无规则 ⇒ 旧实现返回 `success=True, data={"skipped": True}`
    # （假绿）⇒ 模型读到“校验通过”继续执行，还会把 `pending_validated_input` 落账、下一轮被
    # 注入“直接调用写工具…不要再发确认卡”的执行提示。补的规则：
    #   employee_manage（update/delete/reset_password/toggle_status）、
    #   product_manage（toggle_status）、customer_manage（4 个 tag 写）、
    #   processing_item_manage（toggle_item_status + 3 个 category 写）。
    # 同时把「无规则」分支改为 fail-closed（见 `execute()` 里的「该操作无校验规则」分支）。
    # ⚠️ required 一律按**工具实现的真实必填**声明（不是照抄契约 DTO）：声明比实现更严
    # = 合法调用被闸门拦（#3566 的 `settings_manage.update_settings` 就是这么坏掉的）。
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
            # recipient_id 是工具硬必填（`notification_manage.py:392-397`）且契约
            # `CreateNotificationRequest.java:17-18` @NotBlank → 旧规则漏了它（issue #3566 核查）
            "required": ["recipient_id", "title", "content"],
            "recipient_id": {"type": str, "min_len": 1, "label": "接收人用户 ID"},
            "title": {"type": str, "min_len": 1, "label": "通知标题"},
            "content": {"type": str, "min_len": 1, "label": "通知内容"},
        },
    },
    "processing_item_manage": {
        # 契约对齐（issue #3566）：`ProcessingItemCreateRequest.java:19-43` 必填集为
        # name(@NotBlank,@Size max=20) / categoryId(@NotBlank) / pricingMethod(@NotBlank)
        # / unitPrice(@NotNull,@DecimalMin 0.10,@DecimalMax 999.99,@Digits(3,2))；
        # 合法计价方式枚举见 `ProcessingItemService.java:297-302`（per_piece 非法）。
        # 闸门校验的是工具对外参数名（`processing_item_manage.py`）：price → unitPrice。
        # 旧规则只要求 name/category_id → 放行注定 422 的调用（agent 白跑一轮才失败）。
        "create_processing_item": {
            "required": ["name", "category_id", "pricing_method", "price"],
            "name": {"type": str, "min_len": 1, "max_len": 20, "label": "加工项名称"},
            "category_id": {"type": str, "min_len": 1, "label": "分类 ID"},
            "pricing_method": {
                "type": str,
                "min_len": 1,
                "label": "计价方式（仅 per_meter/per_set/fixed/per_area；per_piece 按个不支持）",
                "enum": ["per_meter", "per_set", "fixed", "per_area"],
            },
            "price": {
                "type": (int, float),
                "min": 0.10,
                "max": 999.99,
                "label": "单价（元，0.10~999.99）",
            },
            "description": {"type": str, "label": "描述"},
            "unit": {"type": str, "label": "计量单位"},
        },
        # 契约侧 `ProcessingItemUpdateRequest.java:19-43` 是全量替换语义（同样 @NotBlank
        # name/categoryId/pricingMethod + @NotNull unitPrice），但工具 `_update_item()`
        # 目前只发部分字段（PR #3555 遗留，另一包负责）。此处 required **既不放宽也不提前
        # 收紧**（收紧会让 update 在工具修好前完全不可用），只对齐字段级约束：非法枚举/
        # 越界单价在闸门即拒，不必等 422。
        "update_item": {
            "required": ["item_id"],
            "item_id": {"type": str, "min_len": 1, "label": "加工项 ID"},
            "pricing_method": {
                "type": str,
                "label": "计价方式（仅 per_meter/per_set/fixed/per_area；per_piece 按个不支持）",
                "enum": ["per_meter", "per_set", "fixed", "per_area"],
            },
            "price": {
                "type": (int, float),
                "min": 0.10,
                "max": 999.99,
                "label": "单价（元，0.10~999.99）",
            },
            "name": {"type": str, "min_len": 1, "max_len": 20, "label": "加工项名称"},
            "category_id": {"type": str, "min_len": 1, "label": "分类 ID"},
        },
        # 规则键必须与工具 action 同名：工具 action 是 `delete_item`
        # （`processing_item_manage.py:17` VALID_ACTIONS），旧键写 `delete` → 永不命中，
        # 破坏性删除完全不过闸门（issue #3566 核查）
        "delete_item": {
            "required": ["item_id"],
            "item_id": {"type": str, "min_len": 1, "label": "加工项 ID"},
        },
        # issue #4011 A4：下面 4 个 action 此前无规则 ⇒ 闸门返回 skipped 假绿。
        # required 按工具实现（`processing_item_manage.py`）：`_toggle_item_status` 硬拦
        # item_id + status；`_create_category` 要 name；`_update_category` 要
        # category_id + name；`_delete_category` 要 category_id（工具无“父分类”参数）。
        "toggle_item_status": {
            "required": ["item_id", "status"],
            "status": {"type": str, "enum": ["active", "inactive"], "label": "加工项状态"},
        },
        "create_category": {"required": ["name"]},
        "update_category": {"required": ["category_id", "name"]},
        "delete_category": {"required": ["category_id"]},
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
            # 字段名错修复（issue #3566 核查）：旧规则必填 `data`，但工具没有 data 参数
            # （`settings_manage.py:69-77` 真实参数 name/industry）→ 合法写路径被闸门
            # 100% 拦住。此处按工具实参声明；「至少传一个字段」由工具自己兜底
            # （`settings_manage.py:214` 空 json_data → 明确报错）。
            "required": [],
            "name": {"type": str, "min_len": 1, "label": "商户名称"},
            "industry": {"type": str, "min_len": 1, "label": "所属行业"},
        },
        "update_ai_config": {
            # 同上：真实参数 greeting_template/business_hours/ai_config（`settings_manage.py:78-90`）
            "required": [],
            "greeting_template": {"type": str, "min_len": 1, "label": "AI 问候语模板"},
            "business_hours": {"type": str, "min_len": 1, "label": "营业时间描述"},
            "ai_config": {"type": dict, "label": "AI 配置字段（字典）"},
        },
    },
    "sku_update": {
        "update": {
            # 工具 schema 硬必填 product_id+price（`sku_update.py:46`）→ 旧规则漏 price
            "required": ["product_id", "price"],
            "product_id": {"type": str, "min_len": 1, "label": "商品 ID"},
            "price": {"type": (int, float), "min": 0, "label": "新价格（元）"},
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
                suggestion=(
                    "不要依赖本工具放行：核对 target_tool 拼写，或先确认该工具是否已注册；"
                    "只读工具不需要调用 validate_input"
                ),
            )

        rules = tool_rules.get(target_action)
        if not rules:
            # 工具已注册但该 action 无校验规则 —— **不得假绿**（issue #4011 A4）。
            #
            # 改前这里是 `ToolResult(success=True, data={"validated": True, "skipped": True})`：
            # 模型读到“校验通过”继续执行；更糟的是 `base_skill` 按
            # `tool_name == "validate_input" and result.success` 落 `pending_validated_input`
            # ⇒ 下一轮被注入执行提示「直接调用 {tool}(action=...) 执行写操作，不要再发
            # interact(confirm) 确认卡」——**一道没跑过的闸门换来了逐字执行的授权**。
            #
            # 诚实语义：`success=True` 只允许表示**真跑了校验并通过**（下方 `validated=True`
            # 且无 skipped）。没跑就是没跑 —— 失败 + 可行动建议（R5：fail-closed 分支必带
            # suggestion，否则 `_self_correct_retry` 无从启动）。
            #
            # 为什么直接判死而不做“白名单跳过”：白名单会把「有规则的工具漏了某个写 action」
            # 永久合法化（正是本次 A4 的病灶）。缺规则就是缺规则 —— 补规则才是出口。
            return ToolResult(
                success=False,
                error="该操作无校验规则",
                message=(
                    f"无法校验 {target_tool}/{target_action}：该操作没有预定义校验规则，"
                    "校验**没有执行**（不要把它当成“校验通过”）。"
                    "写操作请先确认参数完整（必填字段逐个自检）再提交；"
                    "查询/只读操作不需要调用本工具。"
                ),
                suggestion=(
                    f"不要依赖本工具放行：直接自检 {target_tool}(action='{target_action}') 的必填参数，"
                    "或改用已登记规则的 action；参数齐备后再调用写工具执行"
                ),
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

            max_val = rule.get("max")
            if max_val is not None and isinstance(val, (int, float)) and val > max_val:
                label = rule.get("label", field)
                issues.append(f"数值过大: {label} ({field}) 最大值为 {max_val}")

            if rule.get("nonzero") and isinstance(val, (int, float)) and val == 0:
                label = rule.get("label", field)
                issues.append(f"数值非法: {label} ({field}) 不能为 0")

            min_len = rule.get("min_len")
            if min_len is not None and isinstance(val, (str, list)) and len(val) < min_len:
                label = rule.get("label", field)
                issues.append(f"长度不足: {label} ({field}) 最少需要 {min_len} 个")

            max_len = rule.get("max_len")
            if max_len is not None and isinstance(val, (str, list)) and len(val) > max_len:
                label = rule.get("label", field)
                issues.append(f"长度超限: {label} ({field}) 最多 {max_len} 个字符")

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
                        "{processingItemId, customPrice}；customPrice 取 processing_item_query 返回的 unit_price）"
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
                        # ⚠️ 不再要求 `unit`（issue #3566 核查）：契约里**没有**这个字段——
                        # agent 路径 `AgentProductCreateRequest.AgentProcessingItemConfig`
                        # 只有 processingItemId + customPrice（`AgentProductCreateRequest.java:88-93`），
                        # 表单路径 `ProcessingItemConfigInput.java:12-22` 同。旧规则逼 LLM
                        # 编一个接收侧不读的键（Jackson 静默丢弃）=「下发字段接收侧不读」同型缺陷。

        # 7. 下单加工费一致性兜底（issue #3521，与上面 #3052 同一理由：
        #    prompt 指令会被 LLM 方差漏掉 → validate_input 必须是确定性闸门）。
        #    服务端 OrderService.sumProcessingFee() 只按 `processingItems[i].unitPrice × quantity`
        #    计总额（Java 侧 brief.amount 就是这两个字段相乘），**`processingFee` 字段不参与**。
        #    两者不一致时：顾客在确认卡上看到的总额 ≠ 实际落库/收款金额（钱对不上）。
        #    实证 CH-010 首跑签名 `总额 311.4 ≠ Σ小计71.4+加工费252.0=323.4`：
        #      小计 71.4 = 3×23.8，落库 311.4 = 71.4 + 240（明细 30×8），
        #      而声明的 processingFee = 252（把按面积的项另算成 30×8.4）—— 同一个订单两份数字。
        #    为什么必须拦在**发确认卡之前**：卡上金额由模型按声明值渲染，落库由服务端按明细重算，
        #    只有校验阶段能同时纠正两边（prompt 只写"必须相等"，方差下不足以兜住）。
        #    只拦"声明了合计且与明细不符"；没写 processingItems 明细（老形态）不拦，避免误伤。
        if target_tool == "order_create":
            for idx, item in enumerate(params.get("items") or []):
                if not isinstance(item, dict):
                    continue
                pinfo = item.get("processing_info")
                if not isinstance(pinfo, dict):
                    continue
                raw_items = pinfo.get("processingItems")
                if not isinstance(raw_items, list) or not raw_items:
                    continue
                detail_sum = 0.0
                detail_ok = True
                parts = []
                for entry in raw_items:
                    if not isinstance(entry, dict):
                        detail_ok = False
                        break
                    try:
                        up = float(entry.get("unitPrice"))
                        qty = float(entry.get("quantity"))
                    except (TypeError, ValueError):
                        detail_ok = False
                        break
                    detail_sum += up * qty
                    parts.append(f"{entry.get('name') or '?'} {up}×{qty}={round(up * qty, 2)}")
                if not detail_ok:
                    continue
                declared = pinfo.get("processingFee")
                if declared is None:
                    continue
                try:
                    declared_f = float(declared)
                except (TypeError, ValueError):
                    continue
                if abs(declared_f - detail_sum) > 0.01:
                    issues.append(
                        f"items[{idx}].processing_info.processingFee={declared_f} 与 "
                        f"Σ加工项(unitPrice×quantity)={round(detail_sum, 2)} 不一致"
                        f"（{'、'.join(parts)}）。服务端按明细计总额 → 不一致时顾客在确认卡上"
                        f"看到的总额 ≠ 实际落库/收款金额（issue #3521）。"
                        f"请把 processingFee 改成 {round(detail_sum, 2)} 后重新校验。"
                    )

        if issues:
            return ToolResult(
                success=False,
                data={"issues": issues, "missing_fields": missing},
                error="参数校验失败",
                message=f"参数校验失败，请补充以下信息后重试:\n" + "\n".join(f"  - {i}" for i in issues),
                # R5（issue #4011）：fail-closed 分支必须带 suggestion —— `_self_correct_retry`
                # 靠它启动自我纠正；只给失败不给下一步 = 模型原地重试同一组参数。
                suggestion=(
                    "按上面逐条补齐/改正参数后**重新调用 validate_input**；"
                    f"全部通过（validated=true）后再调用 {target_tool}(action='{target_action}')"
                ),
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
