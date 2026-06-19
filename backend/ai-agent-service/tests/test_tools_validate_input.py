"""ValidateInputTool 单元测试 — 纯本地校验，无 API 调用"""
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
            params={"name": "遮光窗帘", "price": 299},
        )
        assert result.success is True
        assert result.data["validated"] is True

    async def test_no_rules_skip(self, tool, admin_tool_context):
        """无规则的操作返回 skipped"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="unknown_tool",
            target_action="unknown_action",
            params={"foo": "bar"},
        )
        assert result.success is True
        assert result.data.get("skipped") is True

    async def test_update_has_product_id(self, tool, admin_tool_context):
        """update 带 product_id 通过校验"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="product_manage",
            target_action="update",
            params={"product_id": "prod-001", "name": "新名称"},
        )
        assert result.success is True


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
# QA Gate: PR #485 covers this module
