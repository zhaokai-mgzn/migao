"""ValidateInputTool 单元测试 — 纯本地校验，无 API 调用"""
# case_ids: PR-005, AS-003, PR-019, OR-015, HR-005
import pytest
from app.tools.validate_input import ValidateInputTool


@pytest.fixture
def tool():
    return ValidateInputTool()


class TestValidateInputSuccess:
    async def test_product_create_valid(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="create",
            params={"name": "遮光窗帘", "price": 299, "category_id": "cat-test-001",
                    "specifications": {"材质": "涤纶", "功能": "遮光"}},
        )
        assert result.success is True
        assert result.data["validated"] is True

    async def test_no_rules_skip(self, tool, admin_tool_context):
        """未知工具/操作返回失败（防止绕过校验）"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="unknown_tool",
            target_action="unknown_action",
            params={"foo": "bar"},
        )
        assert result.success is False
        assert "未知" in result.message or "无法" in result.message

    async def test_update_has_product_id(self, tool, admin_tool_context):
        """update 带 product_id 通过校验"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="update",
            params={"product_id": "prod-001", "name": "新名称"},
        )
        assert result.success is True

    async def test_customer_update_valid(self, tool, admin_tool_context):
        """CU-004 回归：customer_manage(update) 必须有规则（旧实现返回「未知工具」，
        LLM 据此幻觉「手机号修改不支持」——实际 admin-api updateCustomer 支持 phone）。"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="customer_manage",
            target_action="update",
            params={"customer_id": "9a97c0415c204702f3c6efaf3d162509", "data": {"phone": "13900001111"}},
        )
        assert result.success is True
        assert result.data["validated"] is True

    async def test_customer_update_missing_customer_id_fails(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="customer_manage",
            target_action="update",
            params={"data": {"phone": "13900001111"}},
        )
        assert result.success is False

    async def test_inventory_adjust_valid(self, tool, admin_tool_context):
        """生产回归：inventory_manage/adjust 必须有校验规则（旧实现返回"未知的工具"，
        且 LLM 绕过校验直接执行写操作）"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="inventory_manage",
            target_action="adjust",
            params={"product_id": "prod-001", "adjustment": 30, "reason": "盘点"},
        )
        assert result.success is True
        assert result.data["validated"] is True

    async def test_inventory_adjust_missing_reason(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="inventory_manage",
            target_action="adjust",
            params={"product_id": "prod-001", "adjustment": 30},
        )
        assert result.success is False


class TestValidateInputAftersaleCreate:
    """aftersale_create（C 端售后创建）参数校验 — audit-2026-09 P2：

    售后创建是写操作（会生成工单），customer_aftersales_skill 的 validate_input
    前置必须能校验其必填参数（order_id/ticket_type/reason），否则 LLM 可绕过校验
    直接以残缺参数创建工单（对账/状态机破坏，GB-03 承诺边界）。
    """

    async def test_aftersale_create_valid(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="aftersale_create",
            target_action="create",
            params={
                "order_id": "ORD-001",
                "ticket_type": "refund",
                "reason": "窗帘有色差",
            },
        )
        assert result.success is True
        assert result.data["validated"] is True

    async def test_aftersale_create_missing_order_id(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="aftersale_create",
            target_action="create",
            params={"ticket_type": "refund", "reason": "窗帘有色差"},
        )
        assert result.success is False
        assert "订单ID" in result.message or "order_id" in result.message.lower()

    async def test_aftersale_create_missing_reason(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="aftersale_create",
            target_action="create",
            params={"order_id": "ORD-001", "ticket_type": "refund"},
        )
        assert result.success is False
        assert "原因" in result.message or "reason" in result.message.lower()

    async def test_aftersale_create_invalid_ticket_type(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="aftersale_create",
            target_action="create",
            params={"order_id": "ORD-001", "ticket_type": "bogus", "reason": "测试"},
        )
        assert result.success is False


class TestValidateInputMissing:
    async def test_missing_params_arg(self, tool, admin_tool_context):
        """未传 params"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="create",
        )
        assert result.success is False
        assert "缺少参数" in result.error

    async def test_missing_required_name(self, tool, admin_tool_context):
        """缺少必填字段 name"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="create",
            params={"price": 299},
        )
        assert result.success is False
        assert "商品名称" in result.message

    async def test_missing_required_order_id_cancel(self, tool, admin_tool_context):
        """order_manage.cancel 缺少 order_id"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_manage",
            target_action="cancel",
            params={"reason": "客户要求取消"},
        )
        assert result.success is False
        assert "order_id" in result.message.lower() or "订单ID" in result.message


class TestValidateInputTypeCheck:
    async def test_type_error_negative_price(self, tool, admin_tool_context):
        """价格不能为负数"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="create",
            params={"name": "窗帘", "price": -1},
        )
        assert result.success is False
        assert "数值过小" in result.message or "校验失败" in result.message


class TestValidateInputPermission:
    async def test_unauthorized(self, tool, unauthorized_tool_context):
        result = await tool.execute(
            context=unauthorized_tool_context,
            target_tool="product_manage",
            target_action="create",
            params={"name": "x", "price": 1},
        )
        assert result.success is False
        assert "权限" in result.error


class TestProductCreateDeterministicAttrs:
    """#3052：建品 create 参数确定性兜底——缺 specifications / 加工项价格即拦截。

    背景（2026-09-08 扩大验收 Round 2 实拍）：#3028 上线后仍非确定性——旅程 S3
    「验收常青0908」create 缺 specifications、processing_item_configs 只传名称不带
    customPrice/unit → DB specs={}、加工项价格 NULL。prompt 指令会被 LLM 方差漏掉，
    validate_input 必须成为确定性闸门（#3030 order_create 同款思路）。
    """

    async def test_missing_specifications_fails(self, tool, admin_tool_context):
        """缺 specifications 键 → 拦截（Round2 S3 实拍缺陷原型）。"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="create",
            params={"name": "验收常青0908", "price": 26.2, "category_id": "cat-1"},
        )
        assert result.success is False
        assert "specifications" in result.message

    async def test_empty_specifications_escape_passes(self, tool, admin_tool_context):
        """用户明确不需要规格 → 传空对象 {} 放行（escape hatch）。"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="create",
            params={"name": "x", "price": 1, "category_id": "cat-1", "specifications": {}},
        )
        assert result.success is True

    async def test_full_specifications_passes(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="create",
            params={"name": "x", "price": 1, "category_id": "cat-1",
                    "specifications": {"材质": "涤纶", "克重": "200-300g"}},
        )
        assert result.success is True

    async def test_processing_items_without_configs_fails(self, tool, admin_tool_context):
        """选了加工项但未传 processing_item_configs → 拦截（价格无法落库）。"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="create",
            params={"name": "x", "price": 1, "category_id": "cat-1",
                    "specifications": {"材质": "涤纶"},
                    "processing_item_ids": ["pi_aaa"]},
        )
        assert result.success is False
        assert "processing_item_configs" in result.message

    async def test_processing_configs_without_price_fails(self, tool, admin_tool_context):
        """#3028 假成功原型：configs 只传名称不带 customPrice/unit。"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="create",
            params={"name": "x", "price": 1, "category_id": "cat-1",
                    "specifications": {"材质": "涤纶"},
                    "processing_item_ids": ["pi_a", "pi_b"],
                    "processing_item_configs": [{"processingItemId": "pi_a"}, {"processingItemId": "pi_b"}]},
        )
        assert result.success is False
        assert "customPrice" in result.message or "unit" in result.message

    async def test_processing_configs_missing_unit_fails(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="create",
            params={"name": "x", "price": 1, "category_id": "cat-1",
                    "specifications": {"材质": "涤纶"},
                    "processing_item_ids": ["pi_a"],
                    "processing_item_configs": [{"processingItemId": "pi_a", "customPrice": 30.0}]},
        )
        assert result.success is False
        assert "unit" in result.message

    async def test_processing_configs_with_price_passes(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="create",
            params={"name": "x", "price": 1, "category_id": "cat-1",
                    "specifications": {"材质": "涤纶"},
                    "processing_item_ids": ["pi_a"],
                    "processing_item_configs": [{"processingItemId": "pi_a", "customPrice": 30.0, "unit": "平方米"}]},
        )
        assert result.success is True


class TestValidateInputRoleManage:
    """HR-005 回归：role_manage 写操作（create/update/delete）必须有校验规则。

    背景（Round 29 实拍）：validate_input 对 role_manage 此前无规则 → 返回
    「未知的工具或操作」，LLM 据此退化到文本预览确认（不走 interact confirm 卡），
    角色创建流程不稳定（HR-005 失败根因之一，与 creation_skills 缺 staff 并列）。
    """

    async def test_role_create_valid(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="role_manage",
            target_action="create",
            params={"name": "库管", "code": "warehouse_keeper",
                    "permission_ids": ["perm_product_manage"]},
        )
        assert result.success is True
        assert result.data["validated"] is True

    async def test_role_create_missing_name(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="role_manage",
            target_action="create",
            params={"code": "warehouse_keeper"},
        )
        assert result.success is False
        assert "角色名称" in result.message

    async def test_role_create_missing_code(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="role_manage",
            target_action="create",
            params={"name": "库管"},
        )
        assert result.success is False
        assert "角色编码" in result.message

    async def test_role_update_missing_role_id(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="role_manage",
            target_action="update",
            params={"name": "新名称"},
        )
        assert result.success is False
        assert "role_id" in result.message.lower() or "角色 ID" in result.message

    async def test_role_delete_missing_role_id(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="role_manage",
            target_action="delete",
            params={"reason": "不再需要"},
        )
        assert result.success is False
        assert "role_id" in result.message.lower() or "角色 ID" in result.message


class TestValidateInputCategoryManage:
    """CT-002 回归：category_manage 写操作必须有校验规则（此前无规则 →
    validate_input 返回「未知工具」→ agent 按安全规则拒绝创建，CT-002 恒失败）。"""

    async def test_category_create_valid(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="category_manage",
            target_action="create",
            params={"name": "轻奢系列"},
        )
        assert result.success is True
        assert result.data["validated"] is True

    async def test_category_create_missing_name(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="category_manage",
            target_action="create",
            params={"parent_id": "cat_1"},
        )
        assert result.success is False
        assert "分类名称" in result.message

    async def test_category_delete_missing_id(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="category_manage",
            target_action="delete",
            params={"reason": "不再需要"},
        )
        assert result.success is False
        assert "分类 ID" in result.message or "category_id" in result.message.lower()


class TestValidateInputWriteToolAudit:
    """Round 45 审计：7 个 WRITE 工具补规则后，写操作可正常校验（此前「未知工具」→ agent 拒绝执行）。"""

    async def test_finance_create_transaction(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context, target_tool="finance_api",
            target_action="create_transaction", params={"type": "income", "amount": 100},
        )
        assert result.success is True

    async def test_finance_missing_amount(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context, target_tool="finance_api",
            target_action="create_transaction", params={"type": "income"},
        )
        assert result.success is False

    async def test_notification_mark_read(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context, target_tool="notification_manage",
            target_action="mark_read", params={"notification_id": "n1"},
        )
        assert result.success is True

    async def test_processing_item_create(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context, target_tool="processing_item_manage",
            target_action="create_processing_item", params={"name": "刺绣", "category_id": "cat_1"},
        )
        assert result.success is True

    async def test_session_assign(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context, target_tool="session_manage",
            target_action="assign", params={"session_id": "s1", "employee_id": "e1"},
        )
        assert result.success is True

    async def test_session_end_missing_id(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context, target_tool="session_manage",
            target_action="end", params={"reason": "下班"},
        )
        assert result.success is False

    async def test_settings_change_password(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context, target_tool="settings_manage",
            target_action="change_password",
            params={"old_password": "old", "new_password": "new123"},
        )
        assert result.success is True

    async def test_product_update_has_id(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context, target_tool="product_update",
            target_action="update", params={"product_id": "p1", "name": "新名"},
        )
        assert result.success is True

    async def test_sku_update_has_id(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context, target_tool="sku_update",
            target_action="update", params={"product_id": "p1", "price": 99},
        )
        assert result.success is True
