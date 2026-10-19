"""product_update 工具 — 请求体字段名对齐（basePrice）回归测试

背景：product_update 把改价请求体写成 {"price": ...}，而 admin-api 的
AgentProductUpdateRequest 期望 {"basePrice": ...}（Jackson 忽略未知字段，
无 JsonAlias）。导致价格更新被静默忽略——LLM 报"改价为 200"，admin-api
仍返回旧价 199（E2E Real test_product_update_price 稳定失败，重试无效）。
product_manage 一直用 basePrice（正确），本测试防 product_update 再漂移。

第二类回归（issue #3560）：product_update 曾把 status（上下架）写进请求体，而
AgentProductUpdateRequest 没有 status 字段 → 静默丢弃 → 假成功。该历史缺陷的收口方向
在 2026-10-19 改判：用户裁定「上下架都 ❌」（#7054 / #7334 裁定 A）⇒ **工具不再声明 status**，
本文件改为钉住「status 不得回流」的负向契约（schema / execute 签名 / 能力话术三面）。
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


#: 商户管理员 JWT 的权限码（`admin` 在 admin-api 里恒为通配 `["*"]`）。
#: #4106 F3：工具层细粒度门禁按 JWT `permissions` claim 判定，夹具必须带上权限码。
ADMIN_PERMISSIONS = ["*"]


def _admin_ctx(user_id: str = "u1") -> ToolContext:
    """商户管理员上下文（有权限改商品）"""
    return ToolContext(tenant_id=1, user_id=user_id, role="admin", permissions=list(ADMIN_PERMISSIONS))


@pytest.fixture
def tool():
    return ProductUpdateTool()


class TestProductUpdateRequestField:
    @pytest.mark.asyncio
    async def test_price_sent_as_base_price(self, tool):
        """改价请求体必须用 basePrice 字段（对齐 admin-api AgentProductUpdateRequest）

        issue #5303：改价必须带 `before_price`（改前价预览声明）才能执行 ⇒ 夹具同步带上。
        issue #5317 改判：`before_price` 从「预览声明、不进请求体」变为**必须下发**
        （字段名 `beforePrice`，服务端据此与 DB 当前值按值核对，不符即 422）。
        """
        ctx = _admin_ctx()
        patched = AsyncMock(return_value={"success": True, "data": {}})
        with patch("app.tools.product_update.get_admin_api_client") as m:
            m.return_value.patch = patched
            result = await tool.execute(ctx, product_id="p1", price=200.0, before_price=168.0)
        assert result.success
        _, kwargs = patched.call_args
        body = kwargs.get("json_data") or {}
        assert "basePrice" in body, f"请求体应含 basePrice 字段（而非 price）: {body}"
        assert body["basePrice"] == 200.0
        assert "price" not in body, f"请求体不应再含 price 字段: {body}"
        assert body.get("beforePrice") == 168.0, (
            f"改前价必须**下发**（服务端靠它回查，不下发就只能证明「模型声称」）: {body}"
        )
        assert "before_price" not in body, (
            f"字段名必须逐字等于 DTO 字段 beforePrice（snake_case 会被 Jackson 静默丢弃）: {body}"
        )

    @pytest.mark.asyncio
    async def test_other_fields_untouched_when_only_price(self, tool):
        """只改价时请求体不得携带其他字段（传什么改什么）"""
        ctx = _admin_ctx()
        patched = AsyncMock(return_value={"success": True, "data": {}})
        with patch("app.tools.product_update.get_admin_api_client") as m:
            m.return_value.patch = patched
            await tool.execute(ctx, product_id="p1", price=88.8, before_price=88.8)
        _, kwargs = patched.call_args
        body = kwargs.get("json_data") or {}
        assert set(body.keys()) == {"basePrice", "beforePrice"}, f"只应传 basePrice + 改前价: {body}"

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
        ctx = _admin_ctx()
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
        ctx = _admin_ctx()
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


class TestStatusNotExposed:
    """上下架 status 不得回流（2026-10-16 裁定 / #7054 / #7334 裁定 A）。

    为什么是负向契约：旧缺陷是「工具声称支持、DTO 静默丢弃」；现在的产品口径是
    **单件与批量上下架都不做** ⇒ 正确的工具面是「schema 没有 status、execute 不收 status、
    话术明确说不在能力内」。任何一处长回来，模型就又有理由承诺上下架。
    """

    def test_tool_schema_does_not_declare_status(self, tool):
        assert "status" not in tool.parameters["properties"], (
            "product_update 不得再声明 status：上下架按 2026-10-16 裁定（单件/批量都 ❌）"
        )

    def test_execute_signature_does_not_accept_status(self, tool):
        import inspect

        assert "status" not in inspect.signature(tool.execute).parameters, (
            "execute 不得再接收 status；传了应当在入口就失败，而不是静默不下发"
        )

    def test_description_says_status_is_out_of_scope(self, tool):
        assert "不在 B 端能力内" in tool.description, "工具描述必须明确说上下架不在能力内"
        assert "禁止" in tool.description and "status" in tool.description, (
            "工具描述必须明确禁止再传 status / 声称已上下架"
        )

    def test_schema_fields_exist_in_dto(self, tool):
        """非 status 的 schema 字段仍须与 admin-api DTO 对齐（防旧 basePrice 类漂移）。"""
        props = tool.parameters["properties"]
        dto_fields = _java_dto_fields(AGENT_PRODUCT_UPDATE_DTO)
        camel = {
            k: ("basePrice" if k == "price" else re.sub(r"_(\w)", lambda m: m.group(1).upper(), k))
            for k in props if k != "product_id"
        }
        missing = {k: v for k, v in camel.items() if v not in dto_fields}
        assert not missing, (
            f"schema 字段在 admin-api AgentProductUpdateRequest 中不存在 → 会被 Jackson 静默丢弃：{missing}"
        )
        assert "beforePrice" in dto_fields, (
            "DTO 缺 beforePrice ⇒ 改前价回查链路断了（服务端无从核对，护栏只防漏填不防填错）"
        )
