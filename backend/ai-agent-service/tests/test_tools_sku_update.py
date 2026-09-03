"""SkuUpdateTool 单元测试 — SKU 调价写工具。

覆盖：安全属性（审计 07 P0-L1 requires_confirmation）、参数校验、成功/失败行为、角色权限。
"""
# case_ids: PR-003, PR-009
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.base import ToolContext
from app.tools.sku_update import SkuUpdateTool


@pytest.fixture
def tool():
    return SkuUpdateTool()


@pytest.fixture
def context():
    return ToolContext(tenant_id=1, user_id="admin_001", session_id="sess", role="admin")


class TestSecurityMetadata:
    """安全元数据：写工具必须标记 requires_confirmation（审计 07 P0-L1）"""

    def test_requires_confirmation_flag(self, tool):
        assert tool.read_only is False
        assert tool.requires_confirmation is True, "SKU 调价属写操作，必须要求用户确认"

    def test_allowed_roles_are_admin_only(self, tool):
        assert set(tool.allowed_roles) == {"admin", "tenant_admin"}


class TestExecute:
    @pytest.mark.asyncio
    @patch("app.tools.sku_update.get_admin_api_client")
    async def test_update_price_success(self, mock_client_factory, tool, context):
        client = AsyncMock()
        client.patch = AsyncMock(return_value={"success": True})
        mock_client_factory.return_value = client

        result = await tool.execute(
            context, product_id="prod-001", price=9.9,
            color="白色", selling_method="bulk_cut", door_width="2.8米",
        )

        assert result.success is True
        assert result.data["new_price"] == 9.9
        client.patch.assert_awaited_once_with(
            "/api/admin/agent/products/prod-001/skus/price",
            json_data={"price": 9.9, "color": "白色",
                       "selling_method": "bulk_cut", "door_width": "2.8米"},
            tenant_id=1, user_id="admin_001",
        )

    @pytest.mark.asyncio
    @patch("app.tools.sku_update.get_admin_api_client")
    async def test_update_price_failure_returns_suggestion(self, mock_client_factory, tool, context):
        client = AsyncMock()
        client.patch = AsyncMock(return_value={
            "success": False,
            "error": {"message": "SKU 不存在"},
        })
        mock_client_factory.return_value = client

        result = await tool.execute(context, product_id="prod-404", price=5.0)

        assert result.success is False
        assert "SKU 调价失败" in result.message
        assert "product_detail" in result.suggestion, "失败时应引导 LLM 重新查询 SKU"

    @pytest.mark.asyncio
    async def test_invalid_product_id_rejected(self, tool, context):
        result = await tool.execute(context, product_id="prod/../etc", price=5.0)
        assert result.success is False
        assert "Invalid product_id" in result.error

    def test_permission_check(self, tool):
        # customer 角色无权调用 SKU 调价
        customer_ctx = ToolContext(tenant_id=1, user_id="c1", session_id="s", role="customer")
        admin_ctx = ToolContext(tenant_id=1, user_id="admin_1", session_id="s", role="admin")
        assert tool.check_permission(customer_ctx) is False
        assert tool.check_permission(admin_ctx) is True

    @pytest.mark.asyncio
    async def test_denied_role_rejected_before_api_call(self, tool):
        """customer 角色 execute 直接被拒（权限守卫前置），不发调价请求"""
        customer_ctx = ToolContext(tenant_id=1, user_id="c1", session_id="s", role="customer")
        result = await tool.execute(customer_ctx, product_id="prod-001", price=9.9)
        assert result.success is False
        assert "权限" in (result.error or "")
