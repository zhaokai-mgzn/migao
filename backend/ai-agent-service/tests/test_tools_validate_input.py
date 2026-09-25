"""ValidateInputTool 单元测试 — 纯本地校验，无 API 调用"""
# case_ids: PR-005, AS-003, PR-019, OR-015, HR-005, PP-006, PR-021, FN-001, ST-001
# 域级映射（本文件覆盖 20+ 写工具的闸门规则）：PP-006 加工项计价方式、PR-005 调整库存、
# PR-021 SKU 调价、FN-001 资金流水登记、ST-001 系统设置。
# 🔴 #5247（B 端米宝只读化，用户裁定 2026-09-23）：8 把工具的**写 action 已从工具删除**
#    （收窄为只读），但这些 action 的**规则块仍在** `_VALIDATION_RULES` 里 ⇒
#    本文件里针对它们的行为用例**仍然有效**（`validate_input` 按 (工具, action) 查表，
#    与工具当前能不能收到该 action 无关）；它们的**时效性**由 `RETIRED_RULE_KEYS_5247`
#    台账单独治理（单次收窄的账，集合相等：新死键红、陈旧条目也红）。
#    ⚠️ 耦合登记：app 侧一旦清理这些规则块，对应行为用例（如
#    `TestValidateInputGateContractAudit.test_inventory_adjustment_zero_blocked` 用的
#    `inventory_manage.adjust`）会随之失去被测对象 ⇒ 必须**同批改判**（清理规则 + 改判用例
#    + 清空台账），三者不同批就会出现"断言不存在规则"的陈旧用例。
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
    """本工具的角色门禁 = **角色层不适用**（issue #4147 G1b）。

    改前：`allowed_roles = ["admin","agent","tenant_admin","customer"]` ⇒ 除 admin 外的
    **全部商户员工**（operator / product_manager / customer_service / sales / finance /
    自定义岗位）调用一律「权限不足」—— 而它是纯本地参数校验器，双端都要用。
    改后：角色不设限（`["*"]`，仍要求已认证），真正的授权边界在**目标写工具自己的
    `required_permissions`** 上（admin-api 权限码）—— 下一条用例即证明该边界仍在。
    """

    async def test_unknown_role_gets_a_real_verdict_not_a_false_denial(
        self, tool, unauthorized_tool_context
    ):
        result = await tool.execute(
            context=unauthorized_tool_context,
            target_tool="product_manage",
            target_action="create",
            params={"name": "x", "price": 1},
        )
        assert result.success is False
        assert "权限不足" not in (result.error or ""), (
            "角色层不适用：不得再对商户侧角色吐假拒绝（真问题是缺必填字段）"
        )
        assert "分类ID" in result.message, f"应给出真实校验结论（实际 {result.message!r}）"

    async def test_the_authorization_boundary_is_the_target_write_tool(
        self, unauthorized_tool_context
    ):
        """边界没消失，只是归位：同一身份写 `product_manage` 仍被目标工具自己的门禁拒绝。"""
        from app.tools.registry import get_tool_registry
        target = get_tool_registry().get_tool("product_manage")
        assert target.check_permission(unauthorized_tool_context) is False


class TestProductCreateDeterministicAttrs:
    """#3052：建品 create 参数确定性兜底——缺 specifications 即拦截。

    背景（2026-09-08 扩大验收 Round 2 实拍）：#3028 上线后仍非确定性——旅程 S3
    「验收常青0908」create 缺 specifications → DB specs={}。prompt 指令会被 LLM 方差
    漏掉，validate_input 必须成为确定性闸门（#3030 order_create 同款思路）。

    issue #4371（商品↔加工项解耦）：原「选了加工项 ⇒ processing_item_configs 必须含
    customPrice」那道闸门已随 create 的加工项参数一并删除（product_manage 不再有
    processing_item_ids/processing_item_configs），对应用例同步移除。
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
    """Round 45 审计：7 个 WRITE 工具补规则后，写操作可正常校验（此前「未知工具」→ agent 拒绝执行）。

    ⚠️ **#4025 F8 销账包（本包改判）**：`finance_api`（随 #5247 只读化）与
    `settings_manage.change_password`（随 #5302 只读化）的规则块已从 `_VALIDATION_RULES` 删除
    ⇒ 与之对应的用例**改判为锁 fail-closed 新真相**（旧断言「死配置照样放行」已不成立），
    不再是「写操作可正常校验」。本类余下用例覆盖的规则块仍在表里（单一台账在册）。
    """

    async def test_finance_create_transaction_is_fail_closed(self, tool, admin_tool_context):
        """改判（#4025 F8 销账）：`finance_api` 的**整个规则键**已从 `_VALIDATION_RULES` 删除。

        逐字读数：`finance_api.py` 的
        `VALID_ACTIONS = {get_summary, get_transactions, get_reconciliation}`
        （该工具随 B 端只读化 #5247 收窄为三个 `get_*`）⇒ `create_transaction` 是**死 action**，
        其规则块是死配置，已删。故闸门对**该工具名**整体走「未知的工具」fail-closed 分支。
        新锁方向：调用**必须被明确拒绝**且理由点名**工具级**缺口（不得静默通过）。
        """
        result = await tool.execute(
            context=admin_tool_context, target_tool="finance_api",
            target_action="create_transaction", params={"type": "income", "amount": 100},
        )
        assert result.success is False, result.message
        assert result.error == "未知的工具", result.error

    async def test_finance_missing_amount_is_not_field_level(self, tool, admin_tool_context):
        """改判（#4025 F8 销账）：缺 `amount` **不再由字段规则拦** —— 那条规则已不存在。

        改前本用例锁的是「缺 `amount` ⇒ 被字段校验拦」（理由在规则块的 `required` 上）；
        规则块随本包删除后那个理由**没有对象**了 ⇒ 锁新真相：拒绝落在「未知的工具」分支，
        且**报错里不出现字段名**（证明死配置已不再参与字段级校验）。
        反例方向：若有人把规则块加回来（字段级校验复活）⇒ 报错里会出现 `amount` ⇒ 本条变红。
        """
        result = await tool.execute(
            context=admin_tool_context, target_tool="finance_api",
            target_action="create_transaction", params={"type": "income"},
        )
        assert result.success is False, result.message
        assert result.error == "未知的工具", result.error
        assert "amount" not in result.message, (
            f"拒绝理由落到了字段级校验上（死规则块疑似复活）：{result.message!r}"
        )

    async def test_notification_mark_read(self, tool, admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context, target_tool="notification_manage",
            target_action="mark_read", params={"notification_id": "n1"},
        )
        assert result.success is True

    async def test_processing_item_create(self, tool, admin_tool_context):
        # 契约对齐（issue #3566 / #4882）：create 必填集 = name / category_id
        # —— `pricingMethod` / `unitPrice` 已随 #4882 从 DTO 整体删除。
        result = await tool.execute(
            context=admin_tool_context, target_tool="processing_item_manage",
            target_action="create_processing_item",
            params={"name": "刺绣", "category_id": "cat_1"},
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

    async def test_settings_change_password_is_fail_closed(self, tool, admin_tool_context):
        """改判（#4025 F8 销账）：`settings_manage.change_password` 规则块已随本包删除。

        逐字读数：`settings_manage.py` 的
        `VALID_ACTIONS = {get_settings, get_ai_config, login_logs}`
        （该工具随 #5302 收窄为三个只读 action）⇒ `change_password` 是**死 action**。
        与 `finance_api` 的**工具级**缺口不同：`settings_manage` 键**仍在**规则表里
        （另有两个死键规则块在册），故走的是 **action 级**「该操作无校验规则」fail-closed 分支
        —— 两个分支各由一条用例钉住，不重复。
        """
        result = await tool.execute(
            context=admin_tool_context, target_tool="settings_manage",
            target_action="change_password",
            params={"old_password": "old", "new_password": "new123"},
        )
        assert result.success is False, result.message
        assert result.error == "该操作无校验规则", result.error

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
    """闸门 vs 真实契约（issue #3566 / #4882，case_ids: PP-006）

    真实契约（admin-api `ProcessingItemCreateRequest`）：
    - name @NotBlank @Size(max=20)、categoryId @NotBlank —— **只有这两个必填**；
    - issue #4882：`pricingMethod` / `unitPrice` 字段**整体删除**（连同 0.10~999.99
      价格区间与 per_meter/per_set/fixed/per_area 枚举）⇒ 闸门不得再要求或校验它们。
    - Controller @Valid → 校验失败 422。

    闸门校验的是 ai-agent 工具对外参数名（`app/tools/processing_item_manage.py`）：
    name / category_id（可选 description / craft_hint）。
    """

    # 合法基线：契约要求的全部（#4882 后 = 仅 name + category_id）
    LEGAL = {"name": "测试加工", "category_id": "pcat_1"}

    async def test_legal_call_passes(self, tool, admin_tool_context):
        """防过严：契约合法的调用必须放行。"""
        result = await tool.execute(
            context=admin_tool_context, target_tool="processing_item_manage",
            target_action="create_processing_item", params=dict(self.LEGAL),
        )
        assert result.success is True, result.message

    async def test_gate_rules_no_longer_require_deleted_fields(self):
        """红证：闸门规则里不得再有 pricing_method / price（issue #4882 已从 DTO 删除）。

        改前形态：`required` = [name, category_id, pricing_method, price]（照 #3566 的旧契约抄）——
        留着它就会把**合法**的「新增加工项」判成缺参、100% 拦在闸门（比 422 更糟：连请求都不发，
        用户看不到任何服务端口径）。
        """
        from app.tools.validate_input import _VALIDATION_RULES
        rule = _VALIDATION_RULES["processing_item_manage"]["create_processing_item"]
        assert set(rule["required"]) == {"name", "category_id"}, (
            f"闸门 required 集与 #4882 后的 DTO 不符：{sorted(rule['required'])}")
        for key in ("pricing_method", "price"):
            assert key not in rule, f"闸门仍在校验已删字段 {key}（issue #4882）"

    async def test_missing_category_id_blocked(self, tool, admin_tool_context):
        """红→绿：缺 category_id（@NotBlank）在调用写工具前被拦下，且提示可行动。"""
        params = {k: v for k, v in self.LEGAL.items() if k != "category_id"}
        result = await tool.execute(
            context=admin_tool_context, target_tool="processing_item_manage",
            target_action="create_processing_item", params=params,
        )
        assert result.success is False
        assert "category_id" in result.message
        assert any("分类" in f for f in result.data["missing_fields"])

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
                # 缺 category_id（@NotBlank）→ 注定 422
                {"name": "测试加工"},
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

    async def test_finance_amount_min_rule_has_no_discriminating_power(self, tool, admin_tool_context):
        """改判（#4025 F8 销账）：该规则块的 `amount.min = 0.01` **判别力已归零**。

        改前本用例锁「过松」形态：`amount=0` 必被拦、`amount=0.01` 必放行（契约下限
        `FinanceTransactionCreateRequest.java` 的 `@DecimalMin(0.01)`）。规则块随本包删除后
        两侧落到**同一个** fail-closed 结论 ⇒ 锁新真相：**既不放行、也不设阈值**。
        反例方向：规则块复活 ⇒ 0 被拦而 0.01 放行 ⇒ 本条立刻变红。
        """
        blocked = await tool.execute(
            context=admin_tool_context, target_tool="finance_api",
            target_action="create_transaction", params={"type": "income", "amount": 0},
        )
        ok = await tool.execute(
            context=admin_tool_context, target_tool="finance_api",
            target_action="create_transaction", params={"type": "income", "amount": 0.01},
        )
        assert blocked.success is False, blocked.message
        assert ok.success is False, ok.message
        assert blocked.error == ok.error == "未知的工具", (blocked.error, ok.error)

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


#: 🔴 **#5247 退役台账**：`_VALIDATION_RULES` 里 **action 已从工具删除**的规则键
#: （B 端米宝只读化：#5247 的 8 把 + #5302 收口的 2 把（settings 域）工具的写 action 被删、
#: 规则块留在 app 侧未同批清理；**条数现取、不写死** —— 判据是集合相等，不是计数）。
#: ⚠️ **#4025 F8 销账包**：其中 2 条对应的规则块已从 app 侧删除
#:   （`finance_api.create_transaction` / `settings_manage.change_password`）⇒ 这 2 条**必须**
#:   从本台账删除，否则「陈旧条目」判红 —— 这正是本台账双向对账的应有之义，不是放宽。
#:
#: ⚠️ 常量名**不再带单个 issue 号**（原 `RETIRED_RULE_KEYS_5247`）：#5302 是同一轮
#:   「B 端只读化」的收口（settings 域漏网补齐），两批条目记在**同一张台账**上 ——
#:   单一台账、不抄第二份（仓内纪律）。
#:
#: 这是**单次收窄的账**、不是通用豁免池：
#:   · 判据是**集合相等**（见 `TestValidationRuleKeysAreLive`）⇒ 新死键照旧红、陈旧条目也红；
#:   · **去向**：`app/tools/validate_input.py` 删除这些规则块后，本台账必须同批清空。
#: 每个工具一条理由（`# [RETIRED #5247]`），避免"一堆元组说不清为什么"。
RETIRED_RULE_KEYS_B_END_READONLY: frozenset = frozenset({
    # [RETIRED #5247] after_sales_manage：收窄为 list/detail（写 action create/update_status 删除）
    ("after_sales_manage", "create"),
    ("after_sales_manage", "update_status"),
    # [RETIRED #5247] category_manage：收窄为 tree（写 action create/update/delete 删除）
    ("category_manage", "create"),
    ("category_manage", "delete"),
    ("category_manage", "update"),
    # [RETIRED #5247] customer_manage：收窄为 list/detail/list_tags（含打标签族写 action 全删）
    ("customer_manage", "add_tag"),
    ("customer_manage", "create_tag"),
    ("customer_manage", "delete_tag"),
    ("customer_manage", "remove_tag"),
    ("customer_manage", "update"),
    ("customer_manage", "update_tag"),
    # [RETIRED #5247] employee_manage：收窄为 list/detail（写 action 全删）
    ("employee_manage", "create"),
    ("employee_manage", "delete"),
    ("employee_manage", "reset_password"),
    ("employee_manage", "toggle_status"),
    ("employee_manage", "update"),
    # [RETIRED #5247] finance_api：收窄为三个 get_*（写 action create_transaction 删除）
    #   → [销账 #4025 F8] 该规则块已从 `_VALIDATION_RULES` 删除 ⇒ 不再计入本台账
    # [RETIRED #5247] inventory_manage：收窄为 query/low_stock_alert（写 action adjust 删除）
    ("inventory_manage", "adjust"),
    # [RETIRED #5247] role_manage：收窄为 list/all/detail/list_permissions（写 action 全删）
    ("role_manage", "create"),
    ("role_manage", "delete"),
    ("role_manage", "update"),
    # [RETIRED #5247] session_manage：收窄为 list/monitor/detail（写 action assign/end 删除）
    ("session_manage", "assign"),
    ("session_manage", "end"),
    # [RETIRED #5302] notification_manage：收窄为 list/unread_count（写 action 全删）
    #   （settings 域整域收口 = #5247 的漏网补齐；同一轮 B 端只读化 ⇒ 记在同一张台账）
    ("notification_manage", "create"),
    ("notification_manage", "delete"),
    ("notification_manage", "mark_read"),
    ("notification_manage", "read_all"),
    # [RETIRED #5302] settings_manage：收窄为 get_settings/get_ai_config/login_logs（写 action 全删）
    #   → [销账 #4025 F8] `change_password` 的规则块已从 `_VALIDATION_RULES` 删除 ⇒ 该条销账
    #     （`update_ai_config` / `update_settings` 的规则块仍在 app 侧 ⇒ 仍记在此）
    ("settings_manage", "update_ai_config"),
    ("settings_manage", "update_settings"),
})


class TestValidationRuleKeysAreLive:
    """L0 静态不变式：闸门规则键必须能命中工具的 action（issue #3566）。

    ## 🔴 issue #5247 改判（B 端米宝只读化，用户裁定 2026-09-23）—— 台账化，不是放宽

    本单把 8 把 B 端写工具的**写 action 全部删除**（收窄为只读），而这些 action 的规则块
    留在 `app/tools/validate_input.py` 的 `_VALIDATION_RULES` 里未同批清理 ⇒ 检测器报出
    **23 个死键**（见 `RETIRED_RULE_KEYS_B_END_READONLY`）。

    🔴 **#5302 收口（同一轮 B 端只读化）**：settings 域的两把（`notification_manage` /
    `settings_manage`）写 action 也全部删除 ⇒ 死键 23 → **30**，同一张台账（单一台账）。

    处置（按"前提没了不许悄悄放宽阈值"的纪律）：**退役台账 + 集合相等**，三个方向都有牙 ——
      ① 出现**台账之外**的死键（又有规则没人命中）⇒ 红（原判据的本意，一字未减）；
      ② 台账里的键**已不再是死键**（action 被加回 / app 侧已清理规则块）⇒ 红
         （陈旧台账 = 永久后门：`stale entries are red too`）；
      ③ 检测器自证（`test_detector_catches_dead_rule_key`）仍要求"注入即报"，
         且**注入不得掩盖台账**（除注入项外的输出必须与真值逐项一致）。
    **去向**：app 侧删除这些规则块（写 action 已不存在）后，本台账必须同批清空
    —— ②会把"清完了却没销账"也判红。
    🔴 **#4025 F8 销账包（已销 2 条）**：`finance_api.create_transaction` /
    `settings_manage.change_password` 的规则块已从 `_VALIDATION_RULES` 删除 ⇒ 这两条已从
    本台账销账（余下条目仍待清理，本包不扩大射程）。
    """

    def test_no_dead_rule_keys(self):
        from app.tools.validate_input import _VALIDATION_RULES

        dead = set(_dead_rule_keys(_VALIDATION_RULES))
        unexpected = sorted(dead - RETIRED_RULE_KEYS_B_END_READONLY)
        stale = sorted(RETIRED_RULE_KEYS_B_END_READONLY - dead)
        assert not unexpected, (
            "闸门规则键与工具 action 枚举不一致 → 规则永不命中（破坏性操作不过闸门）：\n  "
            + "\n  ".join(f"{t}.{a}" for t, a in unexpected)
            + "\n→ 修法二选一：①该 action 仍应存在 ⇒ 把它加回工具的 action 枚举；"
              "②action 已废弃 ⇒ 删除该规则块。**不许**把新死键塞进本轮退役台账"
              "（那是 B 端只读化（#5247 + #5302）的账，不是通用豁免池）"
        )
        assert not stale, (
            "以下本轮退役台账条目已**不再是死键**（action 又存在了，或规则块已被清理）：\n  "
            + "\n  ".join(f"{t}.{a}" for t, a in stale)
            + "\n→ 台账是唯一真值，陈旧条目必须销账：从 RETIRED_RULE_KEYS_B_END_READONLY 删除这些元组"
              "（若 app 侧已把这些规则清完，整张台账清空即可）"
        )

    def test_detector_catches_dead_rule_key(self):
        """检测器自证：注入旧 bug 形态（`delete` vs `delete_item`）必须被报出。

        注入口径（#5247 加强）：除注入项之外，检测器的输出必须与真值**逐项一致** ——
        否则"注入即报"可能只是注入顺手打翻了别的东西（判据漂移而看不出来）。
        """
        from app.tools.validate_input import _VALIDATION_RULES

        broken = {**_VALIDATION_RULES,
                  "processing_item_manage": {"delete": {"required": ["item_id"]}}}
        injected = ("processing_item_manage", "delete")
        reported = set(_dead_rule_keys(broken))
        assert injected in reported, (
            f"检测器漏报注入的死键 {injected} —— issue #3566 的形态会静默复发")
        assert reported - {injected} == set(_dead_rule_keys(_VALIDATION_RULES)), (
            "注入改动影响了检测器的其它输出 ⇒ 判据漂移（注入把真值一起打翻了）：\n"
            f"  注入后（去掉注入项）={sorted(reported - {injected})}\n"
            f"  真值={sorted(set(_dead_rule_keys(_VALIDATION_RULES)))}"
        )


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
