# case_ids: PR-110, PR-111, BM-052
"""入库侧识别 target（issue #5052 P1）—— 字段表 / 消歧阈值 / 留空理由。

本文件钉住三件事（每条都能红）：

1. **`inbound` 是第三个 target，不是「复用 product」**：字段键与 `product` / `order`
   **不共用任何未登记的键**（用户裁定 2026-09-24「不要做成一套字段两个页面填」的机械判据）；
   issue #7759 起唯一例外是 `door_width`（与 `product` 共享 —— 同一列名、**同一事实**
   `product_skus.door_width`，已登记进 `SHARED_FIELD_KEYS`）；
2. **阈值取严档 0.85**（与订单侧同档、严于商品侧 0.60）：这一格经工人确认后**直接进库存**，
   米数抄错 = 账实不符 ⇒ 错填比留空贵得多；
3. **不确定 ⇒ 留空 + 给理由**，且理由里出现「入库侧」（`TARGET_SIDE_LABEL` 同源，
   不另写一份文案）。

红证：把 `inbound` 的阈值改成 0.60 ⇒ `test_inbound_threshold_is_the_strict_one` 红；
把 `quantity_meters` 改名为 `quantity`（与 order 同名）⇒ 零交集断言红。

**issue #7759 追加**（供应商侧布料标签恒零命中的根因之一）：`inbound` 必须有一格承载
**型号 / 货号**（`model_no`）—— 图上唯一靠得住的标识（`2659-4`）此前**没有任何字段可填**，
识别得再准也进不了 admin-api 的货号匹配。判据 = `TestSupplierLabel`。
"""
from app.vision.recognizer import build_messages, extract_fields
from app.vision.targets import (
    SHARED_FIELD_KEYS,
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
        assert field_keys("inbound") == (
            # 型号 / 货号（issue #7759）：供应商标签上最可靠的那个标识 —— 没有它，
            # 识别结果里**没有任何格子**能进 admin-api 的货号匹配（实测恒零命中）。
            "model_no", "product_name", "color_name",
            # 门幅（issue #7759 用户裁定 2026-10-25）：**只抄写明**；没印 ⇒ 留空，
            # 2.8 是匹配侧的业务默认值（不是这一格的值）。
            "door_width",
            "quantity_meters", "barcode",
        )
        assert [f.label for f in TARGET_FIELDS["inbound"]] == [
            "型号 / 货号", "品名", "色号", "门幅", "米数", "条码原文",
        ]

    def test_zero_key_overlap_with_the_two_existing_targets(self):
        """与 `product` / `order` **不共用任何未登记的键**（登记的共享键见 `SHARED_FIELD_KEYS`）。

        issue #7759 起 `door_width` 是唯一例外：`product` 与 `inbound` 读的是**同一列名、同一事实**
        （`product_skus.door_width`，门幅米数）—— 不是「一套字段两个页面填」，而是同一个字段在两个
        target 上确实都存在。未登记的共享仍然红（判据 =
        `tests/test_vision/test_targets.py::test_no_target_shares_an_unregistered_field_key`）。
        """
        inbound = set(field_keys("inbound"))
        registered = {key for key, targets in SHARED_FIELD_KEYS.items() if "inbound" in targets}
        assert inbound & set(field_keys("product")) == registered & set(field_keys("product"))
        assert inbound & set(field_keys("order")) == set()
        # 反向护栏：登记表不是空壳（否则上面第一条会退化成「什么都不检查」）——
        # 与**前两个** target 共享的登记键只有 door_width（`product_name` 登记的是 shipment 那一条）
        shared_with_first_two = registered & (set(field_keys("product")) | set(field_keys("order")))
        assert shared_with_first_two == {"door_width"}

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
        for label in ("型号 / 货号", "品名", "色号", "门幅", "米数", "条码原文"):
            assert label in text
        # 图片块照旧挂在同一条多模态消息上（不新造第二条调用形态）
        assert messages[0].content[1]["type"] == "image_url"

    def test_unknown_target_is_still_fail_closed(self):
        # 反向护栏：新增 target 不得把「未知 target 一律拒绝」这条既有判据变成默认回落
        import pytest

        with pytest.raises(ValueError):
            extract_fields("not-a-target", ROLL_LABEL_VISION_OUTPUT)


class TestSupplierLabel:
    """供应商侧**布料标签**（issue #7759，2026-10-25 用户实测）。

    真值（云 dev 真库）：图上型号 `雪尼尔2659-4绵绵奶咖`、对应内部 `products.sku_code='2659'` +
    `product_skus` 的 `2659-04-28` / `2659-04-32`（`color_name='2659-04 绵绵奶咖'`）。

    识别侧只负责**抄清楚**：型号进 `model_no`（`2659-4`）、色名进 `color_name`（`绵绵奶咖`）
    —— 命中与否由 admin-api 读库判定（本文件不复制第二份匹配口径）。

    红证：把 `model_no` 从 `TARGET_FIELDS["inbound"]` 删掉 ⇒ 字段键元组、label 列表、
    提示词 label 三处同时红（`extract_fields` 也会少这一格，`test_..._is_adopted` 取不到键）。
    """

    #: 模型对这张标签的原样输出（型号 + 色名分开抄；条码只有图形没有可读数字）
    SUPPLIER_LABEL_VISION_OUTPUT = (
        '{"fields": {'
        '"model_no": {"value": "2659-4", "confidence": 0.92},'
        '"product_name": {"value": "雪尼尔2659-4绵绵奶咖", "confidence": 0.90},'
        '"color_name": {"value": "绵绵奶咖", "confidence": 0.88},'
        '"quantity_meters": {"value": "52.4", "confidence": 0.93},'
        '"barcode": {"value": null, "confidence": 0.0, "reason": "只有图形，没有可读数字"}'
        "}}"
    )

    def test_model_number_is_adopted_and_colour_keeps_only_the_colour_name(self):
        fields = {f["key"]: f for f in extract_fields("inbound", self.SUPPLIER_LABEL_VISION_OUTPUT)}

        # 型号这一格是**匹配键**：图上 `雪尼尔2659-4绵绵奶咖` ⇒ `2659-4`
        assert fields["model_no"]["value"] == "2659-4"
        assert fields["model_no"]["source"] == "[图片识别]"
        # 连写的标签：型号进 model_no，色号那格只留色名（不再把 `2659-4` 糊在色名前）
        assert fields["color_name"]["value"] == "绵绵奶咖"
        assert fields["product_name"]["value"] == "雪尼尔2659-4绵绵奶咖"
        assert fields["quantity_meters"]["value"] == "52.4"
        # 这张标签**没有印门幅** ⇒ 本格留空（2.8 是匹配侧的业务默认值，识别侧不许补）
        assert fields["door_width"]["value"] is None

    def test_missing_model_number_stays_blank_with_a_reason(self):
        """图上看不到型号 / 看不清 ⇒ **留空 + 给理由**，绝不用品名去凑（凑出来的值会去匹配货号）。"""
        fields = {f["key"]: f for f in extract_fields(
            "inbound",
            '{"fields": {"model_no": {"value": null, "confidence": 0.0, "reason": "标签磨损"},'
            ' "color_name": {"value": "绵绵奶咖", "confidence": 0.9}}}',
        )}

        assert fields["model_no"]["value"] is None
        assert fields["model_no"]["reason"] == "标签磨损"
        assert fields["model_no"]["source"] is None
        # 反向护栏：同一次里别的格子照常采纳（不因为这一格留空就整张丢掉）
        assert fields["color_name"]["value"] == "绵绵奶咖"

    def test_prompt_explains_where_the_model_number_lives(self):
        messages = build_messages("inbound", ["https://oss.example.com/supplier-label.jpg"])
        text = messages[0].content[0]["text"]
        # 提示词必须点明「型号 / 货号」这一格，并给出连写标签的拆法（否则模型只会把它糊进品名）
        assert "型号 / 货号" in text
        assert "2659-4" in text
        assert "color_name" in text


class TestDoorWidth:
    """门幅只**抄**不**推**（issue #7759 用户裁定 2026-10-25，逐字：

    「这张图没有展示门幅是多少，按照行业标准就是 2.8 的，如果是其他规格的门幅会在标签上展示真实门幅数字」）。

    ⇒ 分工：**图上没印 ⇒ 识别侧留空**（本文件钉住这一半）；**默认 2.8 由 admin-api 匹配侧补**
    （`WorkerInboundService.DEFAULT_DOOR_WIDTH`，那里有另一组判据）。
    让模型在图没印时输出 2.8 = 把「抄」写成「推」，与 `recognizable` 那条既有的「抄 vs 推」边界同族。
    红证：在 `extract_fields` 里给 `door_width` 兜一个默认值 ⇒ 本类第一条当场红。
    """

    def test_absent_door_width_is_never_filled_with_the_industry_default(self):
        # 图上一格都没认出（模型按铁律全留空）⇒ 门幅必须是 None
        fields = {f["key"]: f for f in extract_fields("inbound", '{"fields": {}}')}
        assert fields["door_width"]["value"] is None
        assert fields["door_width"]["source"] is None
        # 认出了型号但**没有门幅**（本条缺陷那张标签的真实形态）⇒ 门幅仍然留空
        fields = {f["key"]: f for f in extract_fields(
            "inbound", '{"fields": {"model_no": {"value": "2659-4", "confidence": 0.92}}}')}
        assert fields["door_width"]["value"] is None
        # 反向护栏：同一次里别的格子照常采纳（不因为门幅空着就整张丢掉）
        assert fields["model_no"]["value"] == "2659-4"

    def test_written_door_width_is_adopted_verbatim(self):
        # 非标准门幅标签上会印真实数字 ⇒ 照抄（归一与取档在 admin-api 侧，识别侧不动它）
        fields = {f["key"]: f for f in extract_fields(
            "inbound", '{"fields": {"door_width": {"value": "3.2", "confidence": 0.91}}}')}
        assert fields["door_width"]["value"] == "3.2"
        assert fields["door_width"]["source"] == "[图片识别]"

    def test_hint_forbids_inferring_the_default(self):
        hint = {f.key: f for f in TARGET_FIELDS["inbound"]}["door_width"].hint
        assert "留空" in hint
        assert "不要" in hint
        # 明确点名「不要按行业惯例补 2.8」—— 不点名的话模型最爱补的就是它
        assert "2.8" in hint
