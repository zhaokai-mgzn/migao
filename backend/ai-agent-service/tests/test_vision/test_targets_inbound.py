# case_ids: PR-110, PR-111
"""入库侧识别 target（issue #5052 P1）—— 字段表 / 消歧阈值 / 留空理由。

本文件钉住三件事（每条都能红）：

1. **`inbound` 是第三个 target，不是「复用 product」**：字段键与前两个 target **零交集**
   （用户裁定 2026-09-24「不要做成一套字段两个页面填」的机械判据同源）；
2. **阈值取严档 0.85**（与订单侧同档、严于商品侧 0.60）：这一格经工人确认后**直接进库存**，
   米数抄错 = 账实不符 ⇒ 错填比留空贵得多；
3. **不确定 ⇒ 留空 + 给理由**，且理由里出现「入库侧」（`TARGET_SIDE_LABEL` 同源，
   不另写一份文案）。

红证：把 `inbound` 的阈值改成 0.60 ⇒ `test_inbound_threshold_is_the_strict_one` 红；
把 `quantity_meters` 改名为 `quantity`（与 order 同名）⇒ 零交集断言红。
"""
from app.vision.recognizer import build_messages, extract_fields
from app.vision.targets import (
    TARGET_FIELDS,
    TARGET_POLICY,
    TARGET_SIDE_LABEL,
    field_keys,
)

#: 固定夹具：一张布卷标签（品名 / 色号 抄得清楚，米数潦草，条码只有图形没有可读数字）
ROLL_LABEL_VISION_OUTPUT = (
    '{"fields": {'
    '"product_name": {"value": "雪尼尔遮光窗帘", "confidence": 0.95},'
    '"color_name": {"value": "01 米白", "confidence": 0.90},'
    '"quantity_meters": {"value": "60.5", "confidence": 0.40, "reason": "字迹潦草"},'
    '"barcode": {"value": null, "confidence": 0.0, "reason": "只有图形，没有可读数字"}'
    "}}"
)


class TestInboundSchema:
    def test_field_keys_and_labels(self):
        assert field_keys("inbound") == ("product_name", "color_name", "quantity_meters", "barcode")
        assert [f.label for f in TARGET_FIELDS["inbound"]] == ["品名", "色号", "米数", "条码原文"]

    def test_zero_key_overlap_with_the_two_existing_targets(self):
        inbound = set(field_keys("inbound"))
        assert inbound & set(field_keys("product")) == set()
        assert inbound & set(field_keys("order")) == set()

    def test_policy_and_side_label_cover_every_target(self):
        assert set(TARGET_POLICY) == set(TARGET_FIELDS)
        assert set(TARGET_SIDE_LABEL) == set(TARGET_FIELDS)
        assert TARGET_SIDE_LABEL["inbound"] == "入库侧"

    def test_threshold_is_the_strict_one(self):
        assert TARGET_POLICY["inbound"]["min_confidence"] == 0.85
        assert (
            TARGET_POLICY["inbound"]["min_confidence"]
            > TARGET_POLICY["product"]["min_confidence"]
        )


class TestInboundRecognition:
    def test_low_confidence_meters_are_left_blank_with_a_reason(self):
        fields = {f["key"]: f for f in extract_fields("inbound", ROLL_LABEL_VISION_OUTPUT)}

        assert fields["quantity_meters"]["value"] is None
        assert "入库侧" in fields["quantity_meters"]["reason"]
        assert fields["barcode"]["value"] is None
        assert fields["barcode"]["reason"] == "只有图形，没有可读数字"

    def test_confident_values_carry_the_recognition_marker(self):
        fields = {f["key"]: f for f in extract_fields("inbound", ROLL_LABEL_VISION_OUTPUT)}

        assert fields["product_name"]["value"] == "雪尼尔遮光窗帘"
        assert fields["product_name"]["source"] == "[图片识别]"
        assert fields["color_name"]["label"] == "色号"

    def test_prompt_carries_every_field_label(self):
        messages = build_messages("inbound", ["https://oss.example.com/roll-1.jpg"])
        text = messages[0].content[0]["text"]
        for label in ("品名", "色号", "米数", "条码原文"):
            assert label in text
        # 图片块照旧挂在同一条多模态消息上（不新造第二条调用形态）
        assert messages[0].content[1]["type"] == "image_url"

    def test_unknown_target_is_still_fail_closed(self):
        # 反向护栏：新增 target 不得把「未知 target 一律拒绝」这条既有判据变成默认回落
        import pytest

        with pytest.raises(ValueError):
            extract_fields("not-a-target", ROLL_LABEL_VISION_OUTPUT)
