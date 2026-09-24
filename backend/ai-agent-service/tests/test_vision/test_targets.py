# case_ids: PR-008, OR-008
"""识别 target 的字段表与消歧策略（issue #5321 包 1）。

判据（用户裁定 2026-09-24：「**不要做成一套字段两个页面填**」）：

1. `product` 与 `order` 是**两个不同的 target** —— 字段表**不重叠**（重叠 = 又变回一套字段）；
2. 订单侧「不确定的宁可不填」**严于**商品侧（客户信息错 ⇒ 货发错人）——
   阈值必须是**严格大于**，不是「都设一个数」；
3. 每个字段都有中文 `label` 与给模型的 `hint`（缺了会让模型自由发挥）；
4. `field_keys()` 与 `TARGET_FIELDS` 同源（不做第二份键表）。

红证：把订单侧阈值改成与商品侧相同 ⇒ `test_order_side_threshold_is_strictly_higher` 红；
把 order 的两个键改回与 product 同名 ⇒ 不重叠断言红。
"""
from app.vision.targets import (
    TARGET_FIELDS,
    TARGET_POLICY,
    TARGET_SIDE_LABEL,
    field_keys,
)


class TestSchemas:
    def test_product_target_fields(self):
        assert field_keys("product") == (
            "name", "color", "material", "craft", "door_width", "price",
        )
        assert [f.label for f in TARGET_FIELDS["product"]] == [
            "商品名称", "颜色", "材质", "工艺", "门幅", "售价",
        ]

    def test_order_target_fields(self):
        assert field_keys("order") == (
            "customer_name", "customer_phone", "customer_address",
            "items", "quantity", "curtain_width", "curtain_height",
        )
        assert [f.label for f in TARGET_FIELDS["order"]] == [
            "客户名", "电话", "地址", "商品明细", "数量", "帘宽", "帘高",
        ]

    def test_two_targets_do_not_share_a_single_key(self):
        """「一套字段两个页面填」的机械判据：两份字段表**零交集**。"""
        overlap = set(field_keys("product")) & set(field_keys("order"))
        assert overlap == set()

    def test_every_field_carries_a_label_and_a_hint_for_the_model(self):
        missing = [
            (target, f.key)
            for target, fields in TARGET_FIELDS.items()
            for f in fields
            if not f.label.strip() or not f.hint.strip()
        ]
        assert missing == []


class TestOrderSideCarriesTheDerivationInputs:
    """issue #5349：订单侧字段表必须带**推导链的原始输入**（帘宽 / 帘高）。

    为什么是这两个：`frontend/admin-web/src/lib/craft-calc-request.ts` 的 `craftCalcParamsOf`
    对**宽 / 高**是 fail-closed（缺任一个就**不发试算**）—— 它们是「不可推导的原始输入」，
    其余（加工类型 / 分幅 / 拼接 / 接高 / 接宽 / 超高 / 超宽）全部由引擎按这组输入推导。
    ⇒ 「图片建单能自动推导」的前提 = 识别**提供这组输入**，而不是识别侧另写一份推导。
    """

    def test_order_side_has_both_size_inputs(self):
        keys = field_keys("order")
        assert "curtain_width" in keys
        assert "curtain_height" in keys

    def test_order_side_does_not_reuse_the_product_sides_door_width(self):
        """**不把商品侧的 `door_width` 搬到订单侧**（两条判据同时挡着）。

        ① 用户 2026-09-24 裁定「不要做成一套字段两个页面填」——
           `test_two_targets_do_not_share_a_single_key` 就是它的机械判据；
        ② 订单侧的 `door_width` **今天没有消费方**：推导链的 `fabric_width` 唯一来源是
           `frontend/admin-web/src/app/(dashboard)/orders/new/page.tsx` 的
           `parseDoorWidth(line.selectedSku?.doorWidth)`（**所选 SKU 的门幅**）
           ⇒ 没有选品就没有门幅，而选品归 issue #5345。

        改名绕开判据（如 `curtain_door_width`）= 「为了过门禁去绕判据」，本仓禁止
        （`migao-dev-flow` §17.3）。
        """
        assert "door_width" not in field_keys("order")

    def test_size_hints_carry_the_direction_disambiguation(self):
        """消歧口径要落在**给模型的 hint** 里（`recognizer.py` 的硬闸是第二道）。

        手写单常见 `2.8×2.4`，而「哪个是宽、哪个是高」的约定不统一 ⇒ hint 必须写明
        **方向不明就留空**，否则模型只会自由发挥地猜一个顺序。
        """
        hints = {f.key: f.hint for f in TARGET_FIELDS["order"]}
        for key in ("curtain_width", "curtain_height"):
            assert "留空" in hints[key]
            assert "方向" in hints[key]


class TestPolicy:
    def test_order_side_threshold_is_strictly_higher(self):
        assert TARGET_POLICY["order"]["min_confidence"] > TARGET_POLICY["product"]["min_confidence"]
        assert TARGET_POLICY["order"]["min_confidence"] == 0.85
        assert TARGET_POLICY["product"]["min_confidence"] == 0.60

    def test_every_target_has_a_policy_and_a_side_label(self):
        assert set(TARGET_POLICY) == set(TARGET_FIELDS)
        assert set(TARGET_SIDE_LABEL) == set(TARGET_FIELDS)
        assert TARGET_SIDE_LABEL["order"] == "订单侧"