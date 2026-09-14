"""product_update 工具 — 请求体字段名对齐（basePrice）回归测试

背景：product_update 把改价请求体写成 {"price": ...}，而 admin-api 的
AgentProductUpdateRequest 期望 {"basePrice": ...}（Jackson 忽略未知字段，
无 JsonAlias）。导致价格更新被静默忽略——LLM 报"改价为 200"，admin-api
仍返回旧价 199（E2E Real test_product_update_price 稳定失败，重试无效）。
product_manage 一直用 basePrice（正确），本测试防 product_update 再漂移。

第二类回归（issue #3560）：product_update 把 status（上下架）写进请求体，而
AgentProductUpdateRequest **没有 status 字段**，service 也从不读它 → 走 hasUpdate=false
分支直接返回商品详情（HTTP 200 + success）→ 米宝回「已下架」而库里状态没变（假成功）。
本测试静态比对「本工具下发的请求体字段」与「admin-api DTO 声明的字段」，任一侧漂移即红。
"""
# case_ids: DF-010, PR-007
import re
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.product_update import ProductUpdateTool

# .../migao/backend/ai-agent-service/tests/test_product_update.py → repo root = parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_PRODUCT_UPDATE_DTO = (
    REPO_ROOT
    / "backend/admin-api/src/main/java/com/migao/admin/dto/agent/AgentProductUpdateRequest.java"
)


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


class TestAllowReturnRestock:
    """allow_return_restock 字段透传（PR-017 回归防线，issue #2991）

    背景：admin-api 已支持 allowReturnRestock（AgentProductUpdateRequest），但 ai-agent
    product_update 工具 schema 未暴露该参数 → 用户「设置退货回补库存」时 agent 无工具可调
    （PR-017 失败 tools=[] 的根因）。
    """

    @pytest.mark.asyncio
    async def test_allow_return_restock_transmitted_as_allowReturnRestock(self, tool):
        ctx = ToolContext(tenant_id=1, user_id="u1", role="admin")
        patched = AsyncMock(return_value={"success": True, "data": {}})
        with patch("app.tools.product_update.get_admin_api_client") as m:
            m.return_value.patch = patched
            result = await tool.execute(ctx, product_id="p1", allow_return_restock=True)
        assert result.success
        _, kwargs = patched.call_args
        body = kwargs.get("json_data") or {}
        assert body.get("allowReturnRestock") is True, f"应透传 allowReturnRestock: {body}"

    @pytest.mark.asyncio
    async def test_allow_return_restock_false_transmitted(self, tool):
        """显式关闭（false）也须透传（null=不修改，false=明确关闭）。"""
        ctx = ToolContext(tenant_id=1, user_id="u1", role="admin")
        patched = AsyncMock(return_value={"success": True, "data": {}})
        with patch("app.tools.product_update.get_admin_api_client") as m:
            m.return_value.patch = patched
            result = await tool.execute(ctx, product_id="p1", allow_return_restock=False)
        assert result.success
        _, kwargs = patched.call_args
        body = kwargs.get("json_data") or {}
        assert body.get("allowReturnRestock") is False

    def test_schema_declares_allow_return_restock(self, tool):
        assert "allow_return_restock" in tool.parameters["properties"]
        desc = tool.parameters["properties"]["allow_return_restock"]["description"]
        assert "回补" in desc or "退货" in desc

    def test_description_mentions_return_restock(self, tool):
        assert "退货" in tool.description or "回补" in tool.description


def _java_dto_fields(java_file: Path) -> set:
    """解析 Java DTO 的私有字段名（`private <Type> <name>;`，含泛型/数组）。

    契约测试的「接收侧真值」——不用人工维护镜像清单，直接读 admin-api 源码，
    任何一侧漂移都会让下面的断言失败。
    """
    src = java_file.read_text(encoding="utf-8")
    return set(re.findall(r"private\s+[\w.<>,\[\]\s]+?\s+(\w+)\s*;", src))


class TestStatusContractWithAdminApiDto:
    """上下架 status 的跨端字段契约（issue #3560）

    「下发侧声明 → 接收侧必须存在」：ai-agent 工具 schema 里声明了 status 的字段，
    admin-api 的 DTO 必须真的接收它。缺失 = Jackson 静默丢弃 = 假成功（本 issue 根因）。
    原先「DTO 无 status 但工具照发」的漂移在修复前必红。
    """

    def test_parser_canary(self):
        """防「正则失配 → 空集合 → 断言空转变绿」：解析器必须能读到 DTO 的既有字段。"""
        fields = _java_dto_fields(AGENT_PRODUCT_UPDATE_DTO)
        assert {"name", "basePrice", "allowReturnRestock"} <= fields, (
            f"DTO 字段解析失效（收到 {sorted(fields)}），契约断言会空转"
        )

    def test_product_update_schema_fields_exist_in_dto(self, tool):
        """schema 声明的字段（camelCase 化后）必须都在 DTO 里，否则请求体被静默丢弃。"""
        props = tool.parameters["properties"]
        dto_fields = _java_dto_fields(AGENT_PRODUCT_UPDATE_DTO)
        # snake_case → camelCase（product_id 是路径参数，不是请求体字段）
        body_props = {k: k for k in props if k != "product_id"}
        camel = {k: re.sub(r"_(\w)", lambda m: m.group(1).upper(), k) for k in body_props}
        # price 是工具入参名，请求体实际下发 basePrice（见 TestProductUpdateRequestField）
        camel["price"] = "basePrice"

        missing = {k: v for k, v in camel.items() if v not in dto_fields}
        assert not missing, (
            f"schema 字段在 admin-api AgentProductUpdateRequest 中不存在 → 会被 Jackson 静默丢弃：{missing}"
        )

    def test_status_declared_on_both_sides(self, tool):
        """status 必须两端都在：工具 schema 有，DTO 也有（本 issue 的直接断言）。"""
        assert "status" in tool.parameters["properties"], "工具 schema 未声明 status"
        assert "status" in _java_dto_fields(AGENT_PRODUCT_UPDATE_DTO), (
            "admin-api AgentProductUpdateRequest 缺 status 字段 → product_update 的上下架会被静默丢弃（假成功）"
        )

    @pytest.mark.asyncio
    async def test_status_transmitted_in_request_body(self, tool):
        """execute(status=...) 必须把 status 放进 PATCH 请求体（且不额外塞字段）。"""
        ctx = ToolContext(tenant_id=1, user_id="u1", role="admin")
        patched = AsyncMock(return_value={"success": True, "data": {}})
        with patch("app.tools.product_update.get_admin_api_client") as m:
            m.return_value.patch = patched
            result = await tool.execute(ctx, product_id="p1", status="off_sale")
        assert result.success
        _, kwargs = patched.call_args
        body = kwargs.get("json_data") or {}
        assert body.get("status") == "off_sale", f"请求体应含 status=off_sale: {body}"
        assert set(body.keys()) == {"status"}, f"只传 status 时不应携带其他字段: {body}"
