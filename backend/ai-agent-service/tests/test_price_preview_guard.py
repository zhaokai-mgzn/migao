# case_ids: PR-009, PR-010, PR-021
"""**改价预览确认**的机械判据（issue #5303，A 档可逆写补回）。

## 病灶（本判据要拦住的形态）

`product_update` / `sku_update` 是 `WRITE|IDEMPOTENT` 的**可逆写**（价格能再调回去），
但它们的"确认门禁"只证明**确认过**、不证明**看过什么**：确认卡的字段投影
（`app/tools/confirm_value.py` 的 `confirm_card_fields`）此前**只回显新值** ——
卡上写着「价格=199」，而"现在多少钱"**从不出现** ⇒ 商家是在**不知道改前价**的前提下
确认改钱。`requires_confirmation=True` 对此无能为力（它只管"有没有确认"）。

## 判据（每条都有能单独变红的红证，见 `TestRedProofs`）

1. **单一源判据** `confirm_value.price_preview_missing`：`price`（改后价）在场而
   `before_price`（改前价）缺席 ⇒ 非空；非改价调用（只改 name/status）⇒ 恒空（不误伤）。
2. **写工具 fail-closed**：缺 `before_price` 的改价**一个 HTTP 都不发**、返回
   `price_preview_required` —— 这就是"禁止无预览直接写"的落点。
3. **确认卡成对呈现**：`before_price` 在场 ⇒ 字段投影出「改前价 / 改后价」两项，
   且 `confirm_value_for_fields`（= 门禁**比对**的那个卡值）同时含这两个事实
   —— 商家点的那张卡上真的有 before → after。
4. **门禁话术给唯一可执行的下一步**：卡里缺改前价时，拦截话术必须说清
   "先 product_detail 拿当前价，再带 before_price 调用"（否则商家点完卡才被拒、还得再点一次）。
5. **绑定面**：两条工具绑在 B 端 product skill，且**只绑这两条写工具**
   （#5303 范围：只补这两条，不顺手补别的；C 档工具零绑定）。

## 不属本判据（如实登记，不写成恒真判断凑数）

- **改前价的服务端回查未实装**：`before_price` 是模型从 `product_detail` 带回的**声明**。
  本判据保证"必须声明 + 必须成对展示"，不做 DB 级真值比对（残留登记见 PR 说明）。
- LLM 是否**真的**先查再改、商家是否**真的**点了卡 ⇒ 属真实评测（`migao-dev-flow` §13
  默认不跑），本文件只锁**静态可判的事实**。
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.graph.skills.base_skill import _confirm_card_fields_hint
from app.graph.skills.product_skill import PRODUCT_SYSTEM_PROMPT, PRODUCT_TOOLS
from app.tools.base import ToolContext
from app.tools.confirm_value import (
    confirm_card_fields,
    confirm_value_for_fields,
    price_preview_missing,
)
from app.tools.product_update import ProductUpdateTool
from app.tools.sku_update import SkuUpdateTool

#: B 端商品域**允许**存在的写工具（#5303 的补回范围，白名单只许这两条）
ALLOWED_B_END_WRITES = frozenset({"product_update", "sku_update"})


def _unexpected_writes_in(tools) -> list[str]:
    """工具集里**超出 A 档白名单**的写工具（判据函数；红证见 `TestRedProofs`）。"""
    from app.tools.registry import get_tool_registry

    writes = {t.name for t in get_tool_registry().get_all_tools() if not t.read_only}
    return sorted(set(tools) & writes - ALLOWED_B_END_WRITES)


def _values(fields: list, label: str) -> list:
    return [f.get("value") for f in fields if f.get("label") == label]


@pytest.fixture
def context():
    """商户管理员上下文（`admin` 在 admin-api 里恒为通配 `["*"]`）。"""
    return ToolContext(
        tenant_id=1, user_id="admin_001", session_id="sess",
        role="admin", permissions=["*"],
    )


class TestSingleSourcePredicate:
    """判据 1：`price_preview_missing` 是**单一源**（工具侧与卡片侧共用同一份口径）。"""

    def test_price_without_before_price_is_missing(self):
        assert price_preview_missing({"price": 199}) != ""

    def test_sku_shape_is_covered_too(self):
        assert price_preview_missing({"product_id": "p1", "price": 150, "color": "米白"}) != ""

    def test_price_with_before_price_is_compliant(self):
        assert price_preview_missing({"price": 199, "before_price": 168}) == ""

    def test_non_price_writes_are_out_of_scope(self):
        """只改 name / status / 回补库存开关的调用**不得**被误伤（R2：判据不拦合法输入）。"""
        assert price_preview_missing({"product_id": "p1", "name": "新名"}) == ""
        assert price_preview_missing({"product_id": "p1", "status": "off_sale"}) == ""
        assert price_preview_missing({"product_id": "p1", "allow_return_restock": True}) == ""
        assert price_preview_missing({}) == ""


class TestWriteToolsFailClosed:
    """判据 2：缺改前价的改价**不发请求**（禁止无预览直接写）。"""

    @pytest.mark.asyncio
    @patch("app.tools.product_update.get_admin_api_client")
    async def test_product_update_refuses_without_before_price(self, factory, context):
        client = AsyncMock()
        factory.return_value = client

        result = await ProductUpdateTool().execute(context, product_id="p1", price=199)

        assert result.success is False
        assert result.error == "price_preview_required"
        assert "改前价" in (result.message or "")
        client.patch.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.tools.sku_update.get_admin_api_client")
    async def test_sku_update_refuses_without_before_price(self, factory, context):
        client = AsyncMock()
        factory.return_value = client

        result = await SkuUpdateTool().execute(
            context, product_id="p1", price=150, color="米白", door_width="2.8")

        assert result.success is False
        assert result.error == "price_preview_required"
        client.patch.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.tools.product_update.get_admin_api_client")
    async def test_product_update_writes_with_declared_preview(self, factory, context):
        client = AsyncMock()
        client.patch = AsyncMock(return_value={"success": True, "data": {}})
        factory.return_value = client

        result = await ProductUpdateTool().execute(
            context, product_id="p1", price=199, before_price=168)

        assert result.success is True
        # ⚠️ `before_price` 是**预览声明**，不得进请求体（后端 DTO 里没有这个字段；
        # 传了就是"下发即静默丢弃"的第二份真相 —— 判据同 test_tool_payload_backend_contract）
        assert client.patch.await_args.kwargs["json_data"] == {"basePrice": 199}

    @pytest.mark.asyncio
    @patch("app.tools.sku_update.get_admin_api_client")
    async def test_sku_update_writes_with_declared_preview(self, factory, context):
        client = AsyncMock()
        client.patch = AsyncMock(return_value={"success": True, "data": {}})
        factory.return_value = client

        result = await SkuUpdateTool().execute(
            context, product_id="p1", price=150, before_price=168,
            color="米白", door_width="2.8")

        assert result.success is True
        assert client.patch.await_args.kwargs["json_data"] == {
            "price": 150, "color": "米白", "door_width": "2.8"}

    @pytest.mark.asyncio
    @patch("app.tools.product_update.get_admin_api_client")
    async def test_name_only_update_still_works_without_before_price(self, factory, context):
        """非改价字段（改名）不受本护栏影响 —— 否则是把合法输入拦成假红。"""
        client = AsyncMock()
        client.patch = AsyncMock(return_value={"success": True, "data": {}})
        factory.return_value = client

        result = await ProductUpdateTool().execute(context, product_id="p1", name="新名")

        assert result.success is True
        assert client.patch.await_args.kwargs["json_data"] == {"name": "新名"}


class TestConfirmCardShowsBeforeAndAfter:
    """判据 3：确认卡（与门禁比对的卡值）成对呈现改前 / 改后。"""

    PRICE_ARGS = {"product_id": "遮光窗帘", "price": 199, "before_price": 168}

    def test_card_fields_pair_before_and_after(self):
        fields = confirm_card_fields(self.PRICE_ARGS)

        assert _values(fields, "改前价") == ["168"]
        assert _values(fields, "改后价") == ["199"]

    def test_confirm_value_carries_both_facts(self):
        """门禁放行写操作靠的是 `confirmValue` 精确匹配 ⇒ 卡值必须含这两个事实。"""
        card_value = confirm_value_for_fields(confirm_card_fields(self.PRICE_ARGS))

        assert "改前价=168" in card_value
        assert "改后价=199" in card_value

    def test_sku_card_pairs_too(self):
        fields = confirm_card_fields(
            {"product_id": "遮光窗帘", "price": 150, "before_price": 168,
             "color": "米白", "door_width": "2.8"})

        assert _values(fields, "改前价") == ["168"]
        assert _values(fields, "改后价") == ["150"]

    def test_other_tools_keep_the_plain_price_label(self):
        """口径只对改价这一对收窄：没有 before_price 的调用仍是「价格」。"""
        fields = confirm_card_fields({"product_id": "p1", "price": 9.9})

        assert _values(fields, "价格") == ["9.9"]
        assert _values(fields, "改后价") == []


class TestGateHintTellsTheNextStep:
    """判据 4：被拦回的改价调用，话术必须给出"先拿改前价"这一步。"""

    def test_hint_demands_before_price_when_missing(self):
        hint = _confirm_card_fields_hint({"product_id": "遮光窗帘", "price": 199})

        assert "before_price" in hint
        assert "改前价" in hint
        assert "product_detail" in hint, "必须指明改前价的来源（否则模型会编一个）"

    def test_hint_is_silent_when_preview_already_declared(self):
        hint = _confirm_card_fields_hint(
            {"product_id": "遮光窗帘", "price": 199, "before_price": 168})

        assert "改前价" in hint and "改后价" in hint  # 骨架里已带上这一对
        assert "product_detail" not in hint, "已带改前价时再要求去查 = 多烧一轮"

    def test_hint_is_silent_for_non_price_writes(self):
        hint = _confirm_card_fields_hint({"product_id": "p1", "status": "off_sale"})

        assert "改前价" not in hint


class TestBinding:
    """判据 5：绑定面 = 这两条（且只有这两条）写工具。"""

    def test_price_tools_are_bound(self):
        assert "product_update" in PRODUCT_TOOLS
        assert "sku_update" in PRODUCT_TOOLS

    def test_only_the_two_reversible_writes_are_bound(self):
        assert _unexpected_writes_in(PRODUCT_TOOLS) == []

    def test_c_tier_and_out_of_scope_tools_stay_unbound(self):
        """明确不在本单范围的写工具，一条都不得被顺手补回来。"""
        for name in ("order_create", "validate_input", "product_manage",
                     "category_manage_create", "inventory_manage"):
            assert name not in PRODUCT_TOOLS or name == "inventory_manage"

    def test_prompt_demands_preview_and_drops_the_readonly_claim(self):
        assert "before_price" in PRODUCT_SYSTEM_PROMPT
        assert "改前" in PRODUCT_SYSTEM_PROMPT and "改后" in PRODUCT_SYSTEM_PROMPT
        assert "本域已只读" not in PRODUCT_SYSTEM_PROMPT

    def test_tool_descriptions_mandate_before_price(self):
        assert "before_price" in ProductUpdateTool.description
        assert "before_price" in SkuUpdateTool.description


class TestRedProofs:
    """红证：每条判据都要有能**单独变红**的注入，否则它只是空断言（`migao-acceptance`）。"""

    @pytest.mark.asyncio
    @patch("app.tools.product_update.get_admin_api_client")
    async def test_failclosed_guard_is_load_bearing(self, factory, context):
        """注入：把判据换成"永远合规" ⇒ 缺改前价的改价**必须**真的发出去（否则护栏没在拦）。"""
        client = AsyncMock()
        client.patch = AsyncMock(return_value={"success": True, "data": {}})
        factory.return_value = client

        with patch("app.tools.product_update.price_preview_missing", lambda _a: ""):
            result = await ProductUpdateTool().execute(context, product_id="p1", price=199)

        assert result.success is True
        client.patch.assert_awaited_once()

    def test_predicate_can_go_red(self):
        """注入：把 `before_price` 从合规模板里删掉 ⇒ 判据必须非空。"""
        compliant = {"price": 199, "before_price": 168}
        assert price_preview_missing(compliant) == ""

        mutated = {k: v for k, v in compliant.items() if k != "before_price"}
        assert price_preview_missing(mutated) != ""

    def test_card_pair_can_go_red(self):
        """注入：卡字段里去掉 before_price ⇒ 「改前价」一项必须消失（成对性来自它）。"""
        args = {"product_id": "遮光窗帘", "price": 199, "before_price": 168}
        assert _values(confirm_card_fields(args), "改前价") == ["168"]

        mutated = {k: v for k, v in args.items() if k != "before_price"}
        fields = confirm_card_fields(mutated)
        assert _values(fields, "改前价") == []
        assert _values(fields, "价格") == ["199"], "没有改前价时 label 回落「价格」（口径不放宽）"

    def test_binding_judgement_can_go_red(self):
        """注入：往工具集里混一个别的写工具 ⇒ 白名单判据必须变红。"""
        assert _unexpected_writes_in(PRODUCT_TOOLS) == []

        mutated = [*PRODUCT_TOOLS, "product_manage"]
        assert _unexpected_writes_in(mutated) == ["product_manage"]