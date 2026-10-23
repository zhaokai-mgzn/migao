# case_ids: PR-053
"""
营销海报工具（issue #7351）单测

钉住四条口径：
1. 🔴 **文案必须由操作员提供**（用户 2026-10-19 逐字：「不要无脑的直接生成」）——
   缺主标题 / 缺卖点 / 卖点超限 ⇒ fail-closed，且**不调 admin-api**、不产出卡载荷；
2. 商品事实只来自 admin-api（主图 / 名称 / 价格 / 单位 / 规格），工具**不生成**营销文案
   （商品描述里的营销词不会被搬进卖点）；
3. 租户隔离与权限码（`product:list`）与 `product_detail` 同款；
4. 卡片发射点：`_detect_card_type` 映射 + `_should_send_card` 的「空文案不发卡」。
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.api.chat import _detect_card_type, _should_send_card
from app.tools.base import ToolContext
from app.tools.marketing_poster import MarketingPosterTool


def _context(permissions=("*",), role="admin") -> ToolContext:
    return ToolContext(
        tenant_id=1,
        user_id="user_001",
        session_id="sess_poster_001",
        role=role,
        permissions=list(permissions),
    )


def _product(**overrides):
    data = {
        "id": "prod_001",
        "tenantId": 1,
        "name": "高遮光雪尼尔窗帘",
        "description": "限时特惠！买二送一！全场五折！",  # ← 刻意放营销词：不得被搬进 copy
        "price": 299.0,
        "basePrice": 299.0,
        "unit": "米",
        "images": ["https://img.example.com/1.jpg"],
        "mainImage": "https://img.example.com/1.jpg",
        "specifications": {"遮光率": "95%", "材质": "雪尼尔", "门幅": "2.8m", "风格": "现代"},
    }
    data.update(overrides)
    return data


@pytest.fixture
def tool():
    return MarketingPosterTool()


def _mock_client(response):
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    return client


class TestCopyIsOperatorProvided:
    """缺文案 ⇒ 不生成、不查商品（「先问商家要文案」的机器护栏）。"""

    @pytest.mark.asyncio
    @patch("app.tools.marketing_poster.get_admin_api_client")
    async def test_missing_title_is_rejected_without_fetching(self, mock_get_client, tool):
        result = await tool.execute(
            context=_context(),
            product_id="prod_001",
            promo_title="   ",
            selling_points=["高遮光"],
        )

        assert result.success is False
        assert result.error == "COPY_REQUIRED"
        assert result.missing_params == ["promo_title"]
        assert "主标题" in (result.message or "")
        mock_get_client.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.tools.marketing_poster.get_admin_api_client")
    async def test_missing_selling_points_is_rejected_without_fetching(self, mock_get_client, tool):
        result = await tool.execute(
            context=_context(),
            product_id="prod_001",
            promo_title="新品上市",
            selling_points=["", "   "],
        )

        assert result.success is False
        assert result.error == "COPY_REQUIRED"
        assert result.missing_params == ["selling_points"]
        mock_get_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_too_many_selling_points_is_rejected(self, tool):
        result = await tool.execute(
            context=_context(),
            product_id="prod_001",
            promo_title="新品上市",
            selling_points=["一", "二", "三", "四"],
        )

        assert result.success is False
        assert result.error == "COPY_INVALID"
        assert "最多 3 条" in (result.message or "")

    @pytest.mark.asyncio
    async def test_overlong_title_is_rejected(self, tool):
        result = await tool.execute(
            context=_context(),
            product_id="prod_001",
            promo_title="超" * 25,
            selling_points=["高遮光"],
        )

        assert result.success is False
        assert result.error == "COPY_INVALID"


class TestSuccessPayload:
    @pytest.mark.asyncio
    @patch("app.tools.marketing_poster.get_admin_api_client")
    async def test_poster_payload_uses_product_truth_and_operator_copy(
        self, mock_get_client, tool
    ):
        mock_get_client.return_value = _mock_client({"success": True, "data": _product()})

        result = await tool.execute(
            context=_context(),
            product_id="prod_001",
            promo_title="新品上市",
            selling_points=["高遮光", "免烫易打理"],
        )

        assert result.success is True
        assert result.data["product"] == {
            "id": "prod_001",
            "name": "高遮光雪尼尔窗帘",
            "price": 299.0,
            "unit": "米",
            "image": "https://img.example.com/1.jpg",
            "specs": ["遮光率：95%", "材质：雪尼尔", "门幅：2.8m"],
        }
        # 🔴 文案逐字来自操作员；商品描述里的「限时特惠/买二送一/五折」一个字都不许进 copy
        assert result.data["copy"] == {
            "title": "新品上市",
            "selling_points": ["高遮光", "免烫易打理"],
        }

    @pytest.mark.asyncio
    @patch("app.tools.marketing_poster.get_admin_api_client")
    async def test_missing_image_is_degraded_not_fabricated(self, mock_get_client, tool):
        mock_get_client.return_value = _mock_client({
            "success": True,
            "data": _product(images=[], mainImage=None),
        })

        result = await tool.execute(
            context=_context(),
            product_id="prod_001",
            promo_title="限时特惠",
            selling_points=["整窗定制"],
        )

        assert result.success is True
        assert result.data["product"]["image"] is None  # 不编图、不拿第一张假图

    @pytest.mark.asyncio
    @patch("app.tools.marketing_poster.get_admin_api_client")
    async def test_price_falls_back_to_base_price(self, mock_get_client, tool):
        mock_get_client.return_value = _mock_client({
            "success": True,
            "data": _product(price=None),
        })

        result = await tool.execute(
            context=_context(),
            product_id="prod_001",
            promo_title="新品上市",
            selling_points=["高遮光"],
        )

        assert result.data["product"]["price"] == 299.0


class TestGuards:
    @pytest.mark.asyncio
    async def test_customer_without_permission_is_denied(self, tool):
        result = await tool.execute(
            context=_context(permissions=(), role="customer"),
            product_id="prod_001",
            promo_title="新品上市",
            selling_points=["高遮光"],
        )

        assert result.success is False
        assert "没有权限" in (result.message or "")

    @pytest.mark.asyncio
    @patch("app.tools.marketing_poster.get_admin_api_client")
    async def test_tenant_mismatch_is_treated_as_not_found(self, mock_get_client, tool):
        mock_get_client.return_value = _mock_client({
            "success": True,
            "data": _product(tenantId=999),
        })

        result = await tool.execute(
            context=_context(),
            product_id="prod_001",
            promo_title="新品上市",
            selling_points=["高遮光"],
        )

        assert result.success is False
        assert result.error == "商品不存在"

    @pytest.mark.asyncio
    @patch("app.tools.marketing_poster.get_admin_api_client")
    async def test_missing_product_is_reported(self, mock_get_client, tool):
        mock_get_client.return_value = _mock_client({
            "success": False,
            "error": {"code": "NOT_FOUND", "message": "商品不存在"},
        })

        result = await tool.execute(
            context=_context(),
            product_id="prod_x",
            promo_title="新品上市",
            selling_points=["高遮光"],
        )

        assert result.success is False

    def test_tool_is_read_only_and_b_only(self, tool):
        assert tool.read_only is True
        assert tool.required_permissions == ["product:list"]
        assert tool.c_end_reachable is False


class TestCardEmission:
    def test_card_type_mapping(self):
        assert _detect_card_type("marketing_poster", {}) == "marketing_poster"

    def test_card_is_sent_only_with_copy(self):
        product = {"id": "p1", "name": "帘"}
        assert _should_send_card("marketing_poster", {
            "success": True,
            "data": {"product": product, "copy": {"title": "新品上市", "selling_points": ["a"]}},
        }) is True
        # 空标题 / 空卖点 / 缺商品 ⇒ 不发卡（前端不画「空头海报」）
        assert _should_send_card("marketing_poster", {
            "success": True,
            "data": {"product": product, "copy": {"title": "  ", "selling_points": ["a"]}},
        }) is False
        assert _should_send_card("marketing_poster", {
            "success": True,
            "data": {"product": product, "copy": {"title": "新品上市", "selling_points": []}},
        }) is False
        assert _should_send_card("marketing_poster", {
            "success": True,
            "data": {"copy": {"title": "新品上市", "selling_points": ["a"]}},
        }) is False
        assert _should_send_card("marketing_poster", {"success": False}) is False

class TestRuleDisambiguation:
    """规则歧义回归（issue #7510，实证会话 sess_5742c5b5c43a48b1）。

    旧描述把「调用前必须先问商家（先用 product_search 定位 product_id）」写在同一句里 ⇒
    模型在「查商品算不算『调用』」上反复权衡，最后把权衡过程当回复发给商家。
    历史红线必须分成两条：**商品可以先查**、**文案必须先问**。
    """

    def test_description_allows_product_search_first(self):
        desc = MarketingPosterTool.description
        assert "允许先" in desc and "product_search" in desc, "缺「商品可以先查」的放行口径"
        assert "不属于" in desc, "缺「查商品不算被禁止的调用」的显式豁免"

    def test_description_forbids_call_without_copy(self):
        desc = MarketingPosterTool.description
        assert "不要调用本工具" in desc
        assert "不得自行拍板" in desc

    def test_old_ambiguous_phrasing_gone(self):
        assert "（先用 product_search 定位 product_id）" not in MarketingPosterTool.description

    def test_general_prompt_bifurcates_product_and_copy(self):
        from app.graph.skills.general_agent import GENERAL_SYSTEM_PROMPT
        assert "可以直接" in GENERAL_SYSTEM_PROMPT and "`product_search`" in GENERAL_SYSTEM_PROMPT
        assert "必须先问" in GENERAL_SYSTEM_PROMPT
        assert "只把结论说给商家" in GENERAL_SYSTEM_PROMPT
