"""ValidateInputTool 单元测试 — 纯本地校验，无 API 调用"""
# case_ids: PR-005, AS-003
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
            params={"name": "遮光窗帘", "price": 299, "category_id": "cat-test-001"},
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
