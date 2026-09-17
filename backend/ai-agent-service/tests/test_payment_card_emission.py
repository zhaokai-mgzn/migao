# case_ids: ST-011, ST-012
"""收款二维码卡的**发射点**：工具 → `_detect_card_type` → 卡载荷 → 渲染（issue #4085 第 1 项）。

## 缺陷形态（本文件守卫的那条链）

`PaymentCard` 组件与 `GET /chat/payment-qrcodes` 早在 #3990 就交付在 main，但**没有任何发射点**：
#4016 P14 按「工具层无数据源」裁掉了 C 端 `MessageBubble` 的 `case 'payment'`（同时把
`payment` 从「后端可产出集合」的反向契约里剔除）。生产表现 = 顾客在对话里永远拿不到收款码，
而**没有任何东西会红** —— 这是 `production_progress` 的同构形态（用户 2026-09-18 对两者
下的裁定相同：**建触发机制 / 补发射点**）。

工具自身的契约（元数据/成功面/失败面/suggestion）在 `tests/test_payment_qrcode_query.py`；
本文件只管**链路**：

    payment_qrcode_query（工具）
      → 工具 data = {"payment_qrcodes": {...}}        （卡载荷）
      → chat.py `_detect_card_type` → "payment"       （发射点）
      → `_card_payload` 原样下发                       （SSE card 事件）
      → mini-app `MessageBubble.renderCard` case 'payment' → PaymentCard

## 判据为什么必须落在「可达性」而不只是「映射存在」

`_detect_card_type` 里写了映射，不等于模型调得到该工具：模型可见工具集**唯一**来自
`create_skill_registry(SkillConfig.tool_names)`（`base_skill`，`get_langchain_tools` 绑给模型）。
故本文件额外断言 **Skill 注册表事实**：该工具在小布 persona 的 skill 工具集里（两个：
`customer_order` 下单/付款语境 + `customer_general` 兜底语境 —— 后者是低置信问法的落点），
且**不在**米宝 persona 的工具集里（C 端专属，`allowed_roles=["customer"]`）。

## 红证（每条断言都能红 —— 见本 PR 的实测输出）

- **去掉 `_detect_card_type` 的 payment 分支** ⇒ `TestEmissionChain` 红
  （实测 4 failed，`assert None == 'payment'`）；
- **把工具从 skill 的 tool_names 摘掉** ⇒ `TestToolIsReachableByXiaobu` 红
  （实测「小布的工具集里没有 payment_qrcode_query ⇒ 模型永远调不到该工具」），
  同时 L0 工具集同步守卫 `tests/unit_ci_workflows/test_xiaobu_case_set.py` 也红。
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.api.chat import _card_payload, _detect_card_type, _should_send_card
from app.graph.skills.skill_registry import get_skill_registry
from app.tools.base import ToolContext
from app.tools.registry import get_tool_registry


class TestEmissionChain:
    """发射点：工具名 → 卡型 → 卡载荷 → 是否下发（全部对**真实函数**求值）"""

    def test_tool_maps_to_payment_card(self):
        assert _detect_card_type("payment_qrcode_query", {}) == "payment"

    def test_card_payload_is_the_tool_data(self):
        data = {"payment_qrcodes": {"wechat": {"payment_type": "wechat",
                                               "image_url": "https://img/w.png",
                                               "payee_name": "亿家纺织"}}}
        card_type, card_data = _card_payload(
            "payment_qrcode_query", {"success": True, "data": data}
        )
        assert card_type == "payment"
        # 载荷原样下发（非 order 类不做归一化）——前端 PaymentCard 直接读 payment_qrcodes
        assert card_data == data

    @pytest.mark.parametrize("result,expected", [
        ({"success": True, "data": {"payment_qrcodes": {}}}, True),      # 空态也要发卡
        ({"success": True, "data": {"payment_qrcodes": {"wechat": {}}}}, True),
        ({"success": True, "data": {}}, False),                          # 无载荷不发卡
        ({"success": False, "data": {"payment_qrcodes": {}}}, False),    # 失败不发卡
        ({"success": True}, False),
    ])
    def test_should_send_card_matrix(self, result, expected):
        assert _should_send_card("payment_qrcode_query", result) is expected

    def test_mapping_is_not_vacuous(self):
        """判别性：注册表里**只有一个**工具产出 payment 卡，且它就是这个工具。

        防「映射写成兜底默认」这类恒真形态（那样任何工具都会发支付卡）。
        """
        producers = sorted(
            name for name in get_tool_registry().get_tool_names()
            if _detect_card_type(name, {}) == "payment"
        )
        assert producers == ["payment_qrcode_query"], producers

    def test_card_payload_carries_no_extra_keys(self):
        """载荷只带 payment_qrcodes：前端 PaymentCard 的读键与后端下发键必须一致"""
        _, payload = _card_payload(
            "payment_qrcode_query",
            {"success": True, "data": {"payment_qrcodes": {"wechat": {"image_url": "u"}}}},
        )
        assert set(payload) == {"payment_qrcodes"}

class TestToolIsReachableByXiaobu:
    """可达性（**能力真的可达**的判据）——与跨端卡型契约守卫同源事实、各自独立断言。

    病根形态：工具写好了却没进任何 skill 的 tool_names ⇒ 注册表里有、模型永远调不到
    （`create_skill_registry` 是唯一的模型可见工具集工厂）。
    """

    def test_registered_in_global_registry(self):
        assert "payment_qrcode_query" in get_tool_registry().get_tool_names()

    def test_skill_registry_exposes_it_to_xiaobu(self):
        registry = get_skill_registry()
        skills = list(getattr(registry, "_skills", {}).values())
        assert skills, "Skill 注册表为空 —— 可达性断言会退化成空断言"

        xiaobu_skills = [s for s in skills if "xiaobu" in (s.system_prompts or {})]
        assert xiaobu_skills, "没有小布 persona 的 skill —— 判据的被测对象不存在"
        xiaobu_tools = {t for s in xiaobu_skills for t in (s.tool_names or [])}
        assert "payment_qrcode_query" in xiaobu_tools, (
            "小布的工具集里没有 payment_qrcode_query ⇒ 模型永远调不到该工具，"
            "收款码卡仍是零发射点（不允许「只注册不绑定」）"
        )

        # 兜底 skill 也必须绑（低置信/跨域问法是本能力最常见的落点）
        fallback = [s for s in xiaobu_skills if s.name == "customer_general"]
        assert fallback, "小布兜底 skill（customer_general）不在注册表里"
        assert "payment_qrcode_query" in (fallback[0].tool_names or []), (
            "兜底 skill 未绑定 ⇒「我想付款」这类不在订单域关键词里的问法拿不到收款码"
        )

    def test_not_exposed_to_mibao(self):
        """C 端专属：米宝 persona 的工具集里不得出现（商家设置走 SettingsController）"""
        skills = list(getattr(get_skill_registry(), "_skills", {}).values())
        mibao_tools = {
            t for s in skills if "mibao" in (s.system_prompts or {})
            for t in (s.tool_names or [])
        }
        assert "payment_qrcode_query" not in mibao_tools

    def test_tool_is_callable_through_a_skill_registry_subset(self):
        """端到端可达性：按 skill 工具集造出的子注册表里能取到该工具实例"""
        from app.graph.skills.base_skill import create_skill_registry

        subset = create_skill_registry(["payment_qrcode_query"])
        assert subset.get_tool("payment_qrcode_query") is not None

    @patch("app.tools.payment_qrcode_query.get_admin_api_client")
    async def test_end_to_end_emission_for_the_real_tool_payload(self, mock_get_client):
        """链路闭环（对真工具求值）：工具 execute 的 data 原样成为 payment 卡载荷。

        上游 mock 掉 admin-api（零网络），下游走**真实的** `_detect_card_type` /
        `_card_payload` / `_should_send_card` —— 这样「工具的 data 就是卡载荷」
        不是靠注释声称，而是判据。
        """
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": True,
            "data": {"wechat": {"paymentType": "wechat",
                                "imageUrl": "https://img/w.png",
                                "payeeName": "亿家纺织"}},
        })
        mock_get_client.return_value = mock_client

        from app.tools.payment_qrcode_query import PaymentQrcodeQueryTool

        ctx = ToolContext(tenant_id=1, user_id="customer_001",
                          session_id="sess_pay_e2e", role="customer")
        result = await PaymentQrcodeQueryTool().execute(context=ctx)
        assert result.success is True

        envelope = {"success": result.success, "data": result.data}
        assert _detect_card_type("payment_qrcode_query", envelope) == "payment"
        assert _should_send_card("payment_qrcode_query", envelope) is True

        card_type, card_data = _card_payload("payment_qrcode_query", envelope)
        assert card_type == "payment"
        assert card_data == result.data
        assert card_data["payment_qrcodes"]["wechat"]["image_url"] == "https://img/w.png"