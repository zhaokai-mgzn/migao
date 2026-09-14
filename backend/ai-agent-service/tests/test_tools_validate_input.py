"""ValidateInputTool 单元测试 — 纯本地校验，无 API 调用"""
# case_ids: PR-005, AS-003, PR-019, OR-015, HR-005, PP-006, PR-021, FN-001, ST-001
# 域级映射（本文件覆盖 20+ 写工具的闸门规则）：PP-006 加工项计价方式、PR-005 调整库存、
# PR-021 SKU 调价、FN-001 资金流水登记、ST-001 系统设置。
# 缺口（不编造 id）：settings_manage 的 update_settings/update_ai_config 与
# notification_manage.create 没有专属可执行用例（§14.1 候选，用例文件属另一包独占区）。
from unittest.mock import AsyncMock, patch

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

    async def test_processing_configs_without_unit_passes(self, tool, admin_tool_context):
        """过严修复（issue #3566 核查）：`unit` 不是加工项配置的契约字段。

        契约（agent 路径）：`AgentProductCreateRequest.AgentProcessingItemConfig` 只有
        `processingItemId` + `customPrice`（`AgentProductCreateRequest.java:88-93`）；
        表单路径 `ProcessingItemConfigInput.java:12-22` 同样无 `unit`。
        旧闸门强制每项含 `unit` → 逼 LLM 编一个接收侧根本不读的键（Jackson 静默丢弃），
        属「下发字段接收侧不读」同型缺陷。`customPrice` 仍在契约里，继续必填。
        """
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="create",
            params={"name": "x", "price": 1, "category_id": "cat-1",
                    "specifications": {"材质": "涤纶"},
                    "processing_item_ids": ["pi_a"],
                    "processing_item_configs": [{"processingItemId": "pi_a", "customPrice": 30.0}]},
        )
        assert result.success is True, result.message
        assert "unit" not in result.message

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
        # 契约对齐（issue #3566）：create 必填集 = name/category_id/pricing_method/price
        # （ProcessingItemCreateRequest.java:19-43），原断言只传前两个 → 曾是「闸门过松」的
        # 假绿（实际调用必 422）。
        result = await tool.execute(
            context=admin_tool_context, target_tool="processing_item_manage",
            target_action="create_processing_item",
            params={"name": "刺绣", "category_id": "cat_1",
                    "pricing_method": "per_meter", "price": 8},
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


class TestProcessingItemCreateGateMatchesContract:
    """闸门 vs 真实契约（issue #3566，case_ids: PP-006）

    真实契约（admin-api）：
    - `ProcessingItemCreateRequest.java:19-21` name @NotBlank @Size(max=20)
    - `:26-27` categoryId @NotBlank
    - `:33-34` pricingMethod @NotBlank
    - `:39-43` unitPrice @NotNull @DecimalMin(0.10) @DecimalMax(999.99) @Digits(3,2)
    - `ProcessingItemService.java:297-302` 合法枚举 per_meter/per_set/fixed/per_area
    - `ProcessingItemController.java:57` @Valid → 校验失败 422

    闸门校验的是 ai-agent 工具对外参数名（`processing_item_manage.py:60-123`）：
    name / category_id / pricing_method / price（price 显式映射 unitPrice）。
    """

    # 合法基线：契约要求全部齐备
    LEGAL = {"name": "测试加工", "category_id": "pcat_1",
             "pricing_method": "per_meter", "price": 8}

    async def test_legal_call_passes(self, tool, admin_tool_context):
        """防过严：契约合法的调用必须放行。"""
        result = await tool.execute(
            context=admin_tool_context, target_tool="processing_item_manage",
            target_action="create_processing_item", params=dict(self.LEGAL),
        )
        assert result.success is True, result.message

    async def test_missing_pricing_method_blocked(self, tool, admin_tool_context):
        """红→绿：缺 pricing_method 在调用写工具前被拦下，且提示可行动（含合法枚举）。"""
        params = {k: v for k, v in self.LEGAL.items() if k != "pricing_method"}
        result = await tool.execute(
            context=admin_tool_context, target_tool="processing_item_manage",
            target_action="create_processing_item", params=params,
        )
        assert result.success is False
        assert "pricing_method" in result.message
        assert "计价方式" in result.message
        for legal in ("per_meter", "per_set", "fixed", "per_area"):
            assert legal in result.message, result.message
        assert any("计价方式" in f for f in result.data["missing_fields"])

    async def test_missing_price_blocked(self, tool, admin_tool_context):
        """红→绿：缺 price（映射 admin-api unitPrice）同样前置拦下。"""
        params = {k: v for k, v in self.LEGAL.items() if k != "price"}
        result = await tool.execute(
            context=admin_tool_context, target_tool="processing_item_manage",
            target_action="create_processing_item", params=params,
        )
        assert result.success is False
        assert "price" in result.message and "单价" in result.message
        assert any("单价" in f for f in result.data["missing_fields"])

    async def test_per_piece_rejected_with_legal_enum_hint(self, tool, admin_tool_context):
        """per_piece（按个）在契约侧非法（issue #3005）→ 闸门拒绝并列出 4 个合法值。"""
        result = await tool.execute(
            context=admin_tool_context, target_tool="processing_item_manage",
            target_action="create_processing_item",
            params={**self.LEGAL, "pricing_method": "per_piece"},
        )
        assert result.success is False
        assert "per_piece" in result.message
        for legal in ("per_meter", "per_set", "fixed", "per_area"):
            assert legal in result.message, result.message

    @pytest.mark.parametrize("price", [0.05, 1000, -1])
    async def test_price_out_of_contract_range_blocked(self, tool, admin_tool_context, price):
        """@DecimalMin(0.10)/@DecimalMax(999.99)：越界 = 注定 422，闸门必须先拒绝。"""
        result = await tool.execute(
            context=admin_tool_context, target_tool="processing_item_manage",
            target_action="create_processing_item",
            params={**self.LEGAL, "price": price},
        )
        assert result.success is False
        assert "单价" in result.message

    async def test_price_boundaries_pass(self, tool, admin_tool_context):
        """边界值合法（0.10 / 999.99）→ 放行，防闸门过严。"""
        for price in (0.10, 999.99):
            result = await tool.execute(
                context=admin_tool_context, target_tool="processing_item_manage",
                target_action="create_processing_item",
                params={**self.LEGAL, "price": price},
            )
            assert result.success is True, (price, result.message)

    async def test_name_over_20_chars_blocked(self, tool, admin_tool_context):
        """@Size(max=20)：名称超长 = 注定 422。"""
        result = await tool.execute(
            context=admin_tool_context, target_tool="processing_item_manage",
            target_action="create_processing_item",
            params={**self.LEGAL, "name": "加" * 21},
        )
        assert result.success is False
        assert "加工项名称" in result.message

    async def test_gate_blocks_before_write_tool_called(self, tool, admin_tool_context):
        """闸门价值：拦下后写工具一次都不会被调用（否则白跑一轮撞 422）。

        模拟确认-执行链的标准调用序：validate_input 通过才调写工具
        （`base_skill` 依赖 validate_input 成功才落「已校验待执行」）。
        """
        from app.tools.processing_item_manage import ProcessingItemManageTool

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value={"success": True, "data": {}})
        assert ProcessingItemManageTool().name == "processing_item_manage"  # 工具已注册
        calls = []

        with patch("app.tools.processing_item_manage.get_admin_api_client",
                   return_value=mock_client):
            for params in (
                # 旧闸门放行、但注定 422 的参数集（缺 pricing_method）
                {"name": "测试加工", "category_id": "pcat_1", "price": 8},
                # 契约完整 → 放行，写工具进入调用序
                dict(self.LEGAL),
            ):
                gate = await tool.execute(
                    context=admin_tool_context, target_tool="processing_item_manage",
                    target_action="create_processing_item", params=params,
                )
                if gate.success:
                    calls.append(params)

        assert calls == [self.LEGAL], "只有契约完整的参数集才应放行到写工具"
        # 闸门本身永不调外部 API（READONLY）；被拦下的注定失败调用也没走到写工具
        mock_client.post.assert_not_called()


class TestValidateInputGateContractAudit:
    """闸门 vs 契约全量核查的修复项（issue #3566）。

    同一缺陷族：闸门规则与**工具实参名 / 下游硬校验**脱节 →
    要么放行注定失败的调用（白跑一轮），要么拦住合法调用（写路径不可用）。
    每条证据见对应注释的 `文件:行号`。
    """

    async def test_processing_item_delete_item_is_validated(self, tool, admin_tool_context):
        """P0 规则键错：栅门写的是 `delete`，工具 action 是 `delete_item`（`processing_item_manage.py:17`）
        → 规则永不命中、破坏性删除走 skipped 完全不过闸门。"""
        result = await tool.execute(
            context=admin_tool_context, target_tool="processing_item_manage",
            target_action="delete_item", params={"action": "delete_item"},
        )
        assert result.success is False
        assert "item_id" in result.message

    async def test_settings_update_settings_accepts_real_params(self, tool, admin_tool_context):
        """P0 字段名错：旧规则必填 `data`，而工具没有 data 参数（`settings_manage.py:69-77`
        真实参数 name/industry）→ 合法写路径 100% 被闸门拦住。"""
        result = await tool.execute(
            context=admin_tool_context, target_tool="settings_manage",
            target_action="update_settings", params={"name": "米高布艺旗舰店"},
        )
        assert result.success is True, result.message

    async def test_settings_update_ai_config_accepts_real_params(self, tool, admin_tool_context):
        """同上：真实参数 greeting_template/business_hours/ai_config（`settings_manage.py:78-90`）。"""
        result = await tool.execute(
            context=admin_tool_context, target_tool="settings_manage",
            target_action="update_ai_config",
            params={"greeting_template": "您好，欢迎咨询米高布艺"},
        )
        assert result.success is True, result.message

    async def test_notification_create_requires_recipient_id(self, tool, admin_tool_context):
        """过松：工具硬必填 recipient_id（`notification_manage.py:392-397`），契约
        `CreateNotificationRequest.java:17-18` @NotBlank → 闸门旧规则只要 title/content。"""
        missing = await tool.execute(
            context=admin_tool_context, target_tool="notification_manage",
            target_action="create", params={"title": "到货通知", "content": "已到货"},
        )
        assert missing.success is False
        assert "recipient_id" in missing.message

        ok = await tool.execute(
            context=admin_tool_context, target_tool="notification_manage",
            target_action="create",
            params={"recipient_id": "u1", "title": "到货通知", "content": "已到货"},
        )
        assert ok.success is True, ok.message

    async def test_finance_amount_below_api_min_blocked(self, tool, admin_tool_context):
        """过松：契约下限 0.01（`FinanceTransactionCreateRequest.java:21-23` @DecimalMin(0.01)），
        闸门旧规则 min=0 → amount=0 放行后必被 422。

        位置：`backend/ai-agent-service/app/tools/validate_input.py`"""
        blocked = await tool.execute(
            context=admin_tool_context, target_tool="finance_api",
            target_action="create_transaction", params={"type": "income", "amount": 0},
        )
        assert blocked.success is False
        assert "amount" in blocked.message

        ok = await tool.execute(
            context=admin_tool_context, target_tool="finance_api",
            target_action="create_transaction", params={"type": "income", "amount": 0.01},
        )
        assert ok.success is True, ok.message

    async def test_inventory_adjustment_zero_blocked(self, tool, admin_tool_context):
        """过松：adjustment=0 被 Service 拒（`ProductService.java:1716-1718`
        「调整量 adjustment 不能为空或 0」），闸门 label 自称「不能为0」却无法表达。"""
        blocked = await tool.execute(
            context=admin_tool_context, target_tool="inventory_manage",
            target_action="adjust",
            params={"product_id": "p1", "adjustment": 0, "reason": "盘点修正"},
        )
        assert blocked.success is False
        assert "adjustment" in blocked.message

        ok = await tool.execute(
            context=admin_tool_context, target_tool="inventory_manage",
            target_action="adjust",
            params={"product_id": "p1", "adjustment": -5, "reason": "出库"},
        )
        assert ok.success is True, ok.message

    async def test_sku_update_requires_price(self, tool, admin_tool_context):
        """过松：工具 schema 必填 product_id+price（`sku_update.py:46`），闸门旧规则只要 product_id。"""
        blocked = await tool.execute(
            context=admin_tool_context, target_tool="sku_update",
            target_action="update", params={"product_id": "p1"},
        )
        assert blocked.success is False
        assert "price" in blocked.message

        ok = await tool.execute(
            context=admin_tool_context, target_tool="sku_update",
            target_action="update", params={"product_id": "p1", "price": 99},
        )
        assert ok.success is True, ok.message


def _dead_rule_keys(rules_by_tool):
    """死键检测器：闸门规则的工具不存在、或 action 不在该工具 action 枚举里。

    死键 = 规则永不命中（validate_input 会走「该操作无预定义规则」直接放行），
    即 `delete` vs `delete_item` 这类规则键错（issue #3566，L0 静态不变式）。
    """
    from app.tools.registry import get_tool_registry

    by_name = {t.name: t for t in get_tool_registry().get_all_tools()}
    dead = []
    for tool, rules in rules_by_tool.items():
        target = by_name.get(tool)
        if target is None:
            dead.append((tool, "<工具未注册>"))
            continue
        enum = ((target.parameters.get("properties") or {}).get("action") or {}).get("enum")
        if enum:  # 单动作工具（无 action 枚举）不参与该不变式
            dead.extend((tool, action) for action in rules if action not in enum)
    return dead


class TestValidationRuleKeysAreLive:
    """L0 静态不变式：闸门规则键必须能命中工具的 action（issue #3566）。"""

    def test_no_dead_rule_keys(self):
        from app.tools.validate_input import _VALIDATION_RULES

        assert _dead_rule_keys(_VALIDATION_RULES) == [], (
            "闸门规则键与工具 action 枚举不一致 → 规则永不命中（破坏性操作不过闸门）"
        )

    def test_detector_catches_dead_rule_key(self):
        """检测器自证：注入旧 bug 形态（`delete` vs `delete_item`）必须被报出。"""
        from app.tools.validate_input import _VALIDATION_RULES

        broken = {**_VALIDATION_RULES,
                  "processing_item_manage": {"delete": {"required": ["item_id"]}}}
        assert _dead_rule_keys(broken) == [("processing_item_manage", "delete")]


class TestOrderManageGateMatchesContract:
    """`order_manage` 三个此前无规则的 action（issue #3566，含资金动作 confirm_payment）。

    工具统一走 `PATCH /api/admin/agent/orders/{id}`（`order_manage.py:128`），
    真实契约在 Service 分支里（`OrderService.java:1585-1629`）：
    - `update_status` → `status` 必填 + 合法状态集
      （`OrderService.java:1595-1597`；状态集 `:79-86` STATUS_TRANSITIONS 的 key ∪ 目标值）
    - `update_logistics` → `logisticsCompany` + `trackingNumber` 均必填（`:1614-1619`）
    - `confirm_payment` → 只需 `order_id`
    - `cancel` / `refund` → 只需 `order_id`（reason/amount 可选；`refund_amount=0`
      必被拒：`OrderService.java:1125-1135` 退款额 <0 拒、累计封顶后 `<=0` 报「已全额退款」）
    """

    ORDER = "ORD-20260101-0001"

    async def test_update_status_missing_status_blocked(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context, target_tool="order_manage",
            target_action="update_status", params={"order_id": self.ORDER},
        )
        assert result.success is False
        assert "status" in result.message

    async def test_update_status_illegal_value_blocked(self, tool, admin_tool_context):
        """LLM 传中文状态（「已发货」）会被 Service 拒（`OrderService.java:507-511`）→ 闸门先拦。"""
        result = await tool.execute(
            context=admin_tool_context, target_tool="order_manage",
            target_action="update_status",
            params={"order_id": self.ORDER, "status": "已发货"},
        )
        assert result.success is False
        assert "status" in result.message
        assert "shipped" in result.message and "cancelled" in result.message

    async def test_update_status_legal_passes(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context, target_tool="order_manage",
            target_action="update_status",
            params={"order_id": self.ORDER, "status": "shipped"},
        )
        assert result.success is True, result.message

    async def test_update_logistics_requires_company_and_tracking(self, tool, admin_tool_context):
        missing_tracking = await tool.execute(
            context=admin_tool_context, target_tool="order_manage",
            target_action="update_logistics",
            params={"order_id": self.ORDER, "logistics_company": "顺丰"},
        )
        assert missing_tracking.success is False
        assert "tracking_number" in missing_tracking.message

        ok = await tool.execute(
            context=admin_tool_context, target_tool="order_manage",
            target_action="update_logistics",
            params={"order_id": self.ORDER, "logistics_company": "顺丰",
                    "tracking_number": "SF1234567890"},
        )
        assert ok.success is True, ok.message

    async def test_confirm_payment_requires_order_id(self, tool, admin_tool_context):
        """资金动作：此前连 order_id 都不校验。"""
        blocked = await tool.execute(
            context=admin_tool_context, target_tool="order_manage",
            target_action="confirm_payment", params={"action": "confirm_payment"},
        )
        assert blocked.success is False
        assert "order_id" in blocked.message

        ok = await tool.execute(
            context=admin_tool_context, target_tool="order_manage",
            target_action="confirm_payment", params={"order_id": self.ORDER},
        )
        assert ok.success is True, ok.message

    async def test_refund_zero_amount_blocked(self, tool, admin_tool_context):
        """退款额 0 → Service 必拒（`OrderService.java:1132-1135` 累计封顶后 <=0）。"""
        blocked = await tool.execute(
            context=admin_tool_context, target_tool="order_manage",
            target_action="refund",
            params={"order_id": self.ORDER, "refund_amount": 0},
        )
        assert blocked.success is False
        assert "refund_amount" in blocked.message

        ok = await tool.execute(
            context=admin_tool_context, target_tool="order_manage",
            target_action="refund",
            params={"order_id": self.ORDER, "refund_amount": 120.5, "refund_reason": "尺寸不符"},
        )
        assert ok.success is True, ok.message
