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
            "items", "quantity", "spec",
        )
        assert [f.label for f in TARGET_FIELDS["order"]] == [
            "客户名", "电话", "地址", "商品明细", "数量", "规格",
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


class TestPolicy:
    def test_order_side_threshold_is_strictly_higher(self):
        assert TARGET_POLICY["order"]["min_confidence"] > TARGET_POLICY["product"]["min_confidence"]
        assert TARGET_POLICY["order"]["min_confidence"] == 0.85
        assert TARGET_POLICY["product"]["min_confidence"] == 0.60

    def test_every_target_has_a_policy_and_a_side_label(self):
        assert set(TARGET_POLICY) == set(TARGET_FIELDS)
        assert set(TARGET_SIDE_LABEL) == set(TARGET_FIELDS)
        assert TARGET_SIDE_LABEL["order"] == "订单侧"