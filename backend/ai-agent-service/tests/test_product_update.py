"""product_update 工具 — 请求体字段名对齐（basePrice）回归测试

背景：product_update 把改价请求体写成 {"price": ...}，而 admin-api 的
AgentProductUpdateRequest 期望 {"basePrice": ...}（Jackson 忽略未知字段，
无 JsonAlias）。导致价格更新被静默忽略——LLM 报"改价为 200"，admin-api
仍返回旧价 199（E2E Real test_product_update_price 稳定失败，重试无效）。
product_manage 一直用 basePrice（正确），本测试防 product_update 再漂移。
"""
# case_ids: DF-010
import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.product_update import ProductUpdateTool


@pytest.fixture
def tool():
    return ProductUpdateTool()


class TestProductUpdateRequestField:
    @pytest.mark.asyncio
    async def test_price_sent_as_base_price(self, tool):
        """改价请求体必须用 basePrice 字段（对齐 admin-api AgentProductUpdateRequest）"""
        ctx = ToolContext(tenant_id=1, user_id="u1", role="admin")
        patched = AsyncMock(return_value={"success": True, "data": {}})
        with patch("app.tools.product_update.get_admin_api_client") as m:
            m.return_value.patch = patched
            result = await tool.execute(ctx, product_id="p1", price=200.0)
        assert result.success
        _, kwargs = patched.call_args
        body = kwargs.get("json_data") or {}
        assert "basePrice" in body, f"请求体应含 basePrice 字段（而非 price）: {body}"
        assert body["basePrice"] == 200.0
        assert "price" not in body, f"请求体不应再含 price 字段: {body}"

    @pytest.mark.asyncio
    async def test_other_fields_untouched_when_only_price(self, tool):
        """只改价时请求体不得携带其他字段（传什么改什么）"""
        ctx = ToolContext(tenant_id=1, user_id="u1", role="admin")
        patched = AsyncMock(return_value={"success": True, "data": {}})
        with patch("app.tools.product_update.get_admin_api_client") as m:
            m.return_value.patch = patched
            await tool.execute(ctx, product_id="p1", price=88.8)
        _, kwargs = patched.call_args
        body = kwargs.get("json_data") or {}
        assert set(body.keys()) == {"basePrice"}, f"只应传 basePrice: {body}"

    @pytest.mark.asyncio
    async def test_denied_role_rejected_before_api_call(self, tool):
        """customer 角色 execute 直接被拒（权限守卫前置），不发修改请求"""
        ctx = ToolContext(tenant_id=1, user_id="c1", role="customer")
        result = await tool.execute(ctx, product_id="p1", price=200.0)
        assert result.success is False
        assert "权限" in (result.error or "")
