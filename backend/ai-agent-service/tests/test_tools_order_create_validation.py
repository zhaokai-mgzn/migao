"""order_create 写操作前置校验 — L2 单测（issue #3029 复盘回归防线）

背景：_VALIDATION_RULES["order_create"] 曾为平铺结构（{required, ...}），
而 execute 按 tool_rules.get(target_action) 分层读取（取 ["create"]）→ 恒为 None
→ 永远走「无需校验（该操作无预定义规则）」跳过，手机号/必填报错全空转
（线上会话 sess_7f27137647e14b1e A5 轮实证）。
修复为 {create: {...}} 分层（与 product_manage/aftersale_create 对齐）后，
以下用例必须全部通过。
"""
# case_ids: OR-015
import pytest
from app.tools.validate_input import ValidateInputTool


@pytest.fixture
def tool():
    return ValidateInputTool()


class TestOrderCreateValidation:
    async def test_valid_params_passes(self, tool, admin_tool_context):
        """合法参数（客户/11位手机号/商品明细）→ 校验通过"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params={
                "customer_name": "张三",
                "customer_phone": "13800138000",
                "items": [{"product_id": "p1", "quantity": 3}],
            },
        )
        assert result.success is True
        assert result.data["validated"] is True

    async def test_missing_required_fails(self, tool, admin_tool_context):
        """缺 customer_name → 校验失败并列出缺失字段（不允许跳过）"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params={
                "customer_phone": "13800138000",
                "items": [{"product_id": "p1", "quantity": 3}],
            },
        )
        assert result.success is False
        assert "客户姓名" in result.message
        assert "缺少必填字段" in result.message

    async def test_missing_items_fails(self, tool, admin_tool_context):
        """缺 items → 校验失败"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params={
                "customer_name": "张三",
                "customer_phone": "13800138000",
            },
        )
        assert result.success is False
        assert "商品明细" in result.message

    async def test_invalid_phone_fails(self, tool, admin_tool_context):
        """手机号非 11 位 → 校验失败并提示格式（防 LLM 编造号码）"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params={
                "customer_name": "张三",
                "customer_phone": "12345",
                "items": [{"product_id": "p1", "quantity": 3}],
            },
        )
        assert result.success is False
        assert "11 位" in result.message

    async def test_missing_phone_fails(self, tool, admin_tool_context):
        """缺 customer_phone → 必填报错"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params={
                "customer_name": "张三",
                "items": [{"product_id": "p1", "quantity": 3}],
            },
        )
        assert result.success is False

    async def test_never_skips_validation(self, tool, admin_tool_context):
        """回归防线：order_create/create 绝不返回「无需校验」跳过分支"""
        result = await tool.execute(
            context=admin_tool_context,
            target_tool="order_create",
            target_action="create",
            params={
                "customer_name": "张三",
                "customer_phone": "13800138000",
                "items": [{"product_id": "p1", "quantity": 3}],
            },
        )
        assert result.data.get("skipped") is not True