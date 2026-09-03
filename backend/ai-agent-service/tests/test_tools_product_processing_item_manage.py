"""ProductProcessingItemManageTool 单元测试 — 商品加工项关联管理写工具。

覆盖：安全属性（审计 07 P0-L1 requires_confirmation）、add/remove 行为、角色权限。
"""
# case_ids: PP-002, PP-003
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.base import ToolContext
from app.tools.product_processing_item_manage import ProductProcessingItemManageTool

# 32 位 hex UUID（id_resolver 对 UUID 直接返回，不触发查询）
PRODUCT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ITEM_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture
def tool():
    return ProductProcessingItemManageTool()


@pytest.fixture
def context():
    return ToolContext(tenant_id=1, user_id="admin_001", session_id="sess", role="admin")


class TestSecurityMetadata:
    """安全元数据：写工具必须标记 requires_confirmation（审计 07 P0-L1）"""

    def test_requires_confirmation_flag(self, tool):
        assert tool.read_only is False
        assert tool.requires_confirmation is True, "商品加工项关联修改属写操作，必须要求用户确认"

    def test_allowed_roles_are_admin_only(self, tool):
        assert set(tool.allowed_roles) == {"admin", "tenant_admin"}


class TestExecute:
    @pytest.mark.asyncio
    @patch("app.tools.product_processing_item_manage.get_admin_api_client")
    async def test_add_items_success(self, mock_client_factory, tool, context):
        client = AsyncMock()
        # 加工项列表查询（resolve_processing_item_ids 前置）返回空列表，UUID 直返
        client.get = AsyncMock(return_value={"success": True, "data": {"items": []}})
        client.patch = AsyncMock(return_value={"success": True})
        mock_client_factory.return_value = client

        result = await tool.execute(context, product_id=PRODUCT_ID, action="add", item_ids=[ITEM_ID])

        assert result.success is True
        client.patch.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.tools.product_processing_item_manage.get_admin_api_client")
    async def test_remove_items_success(self, mock_client_factory, tool, context):
        client = AsyncMock()
        client.get = AsyncMock(return_value={"success": True, "data": {"items": []}})
        client.patch = AsyncMock(return_value={"success": True})
        mock_client_factory.return_value = client

        result = await tool.execute(context, product_id=PRODUCT_ID, action="remove", item_ids=[ITEM_ID])

        assert result.success is True
        client.patch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_action_rejected(self, tool, context):
        result = await tool.execute(context, product_id=PRODUCT_ID, action="delete", item_ids=[ITEM_ID])
        assert result.success is False
        assert "add" in str(result.message) or "remove" in str(result.message)

    @pytest.mark.asyncio
    async def test_missing_item_ids_rejected(self, tool, context):
        result = await tool.execute(context, product_id=PRODUCT_ID, action="add", item_ids=[])
        assert result.success is False
        assert "加工项" in str(result.message)

    def test_permission_check(self, tool):
        customer_ctx = ToolContext(tenant_id=1, user_id="c1", session_id="s", role="customer")
        admin_ctx = ToolContext(tenant_id=1, user_id="admin_1", session_id="s", role="admin")
        assert tool.check_permission(customer_ctx) is False
        assert tool.check_permission(admin_ctx) is True

    @pytest.mark.asyncio
    async def test_denied_role_rejected_before_any_call(self, tool):
        """customer 角色 execute 直接被拒（权限守卫前置），不触发 ID 解析/API 调用"""
        customer_ctx = ToolContext(tenant_id=1, user_id="c1", session_id="s", role="customer")
        result = await tool.execute(customer_ctx, product_id=PRODUCT_ID, action="add", item_ids=[ITEM_ID])
        assert result.success is False
        assert "权限" in (result.error or "")
