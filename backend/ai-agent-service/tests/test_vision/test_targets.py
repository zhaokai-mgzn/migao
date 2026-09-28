# case_ids: PR-008, OR-008, OR-048
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
import re
from pathlib import Path

from app.vision.targets import (
    SHARED_FIELD_KEYS,
    TARGET_FIELDS,
    TARGET_POLICY,
    TARGET_SIDE_LABEL,
    field_keys,
)

#: 仓库根（`backend/ai-agent-service/tests/test_vision/<本文件>` ⇒ parents[3] = `backend`）
REPO = Path(__file__).resolve().parents[3]


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

    def test_shipment_target_fields(self):
        """发货侧字段面（issue #5648 用户裁定 2026-09-26：「识别订单行 / 商品标签」）。

        键名**逐字取自既有列名**（`orders.order_no` / `order_items.product_name` /
        `order_items.quantity` / `order_items.width` / `order_items.height`）——
        自造字段名 = 第二套口径。机械判据见
        `test_shipment_keys_are_existing_order_columns`。
        """
        assert field_keys("shipment") == (
            "order_no", "product_name", "quantity", "width", "height",
        )
        assert [f.label for f in TARGET_FIELDS["shipment"]] == [
            "订单号", "商品名称", "数量", "宽", "高",
        ]

    def test_shipment_keys_are_existing_order_columns(self):
        """🔴 字段面必须与**订单域既有列同名**（不许自造第二套口径）。

        判据读的是 Java 实体的**列声明**（真值源），不是本文件里的字符串常量 ——
        两边各写一份「字段名清单」正是本条要消灭的形态。
        """
        entity_dir = (REPO / "admin-api" / "src" / "main"
                      / "java" / "com" / "migao" / "admin" / "entity")
        assert entity_dir.is_dir(), f"读不到 Java 实体目录（判据不能空跑）：{entity_dir}"
        declared = set()
        for name in ("Order.java", "OrderItem.java"):
            src = (entity_dir / name).read_text(encoding="utf-8")
            for field in re.findall(r"^\s*private\s+[\w<>.,\s]+?\s+(\w+);", src, re.M):
                # Java 字段是驼峰、DB 列是蛇形 ⇒ 按同一套映射换算（`orderNo` → `order_no`）。
                # 认这个映射而不是认一份手抄的清单：自造一个 `qty` 换算出 `qty`，表里没有 ⇒ 红。
                declared.add(re.sub(r"(?<!^)(?=[A-Z])", "_", field).lower())
        missing = [k for k in field_keys("shipment") if k not in declared]
        assert missing == [], f"发货侧字段面出现了既有列名之外的键（=第二套口径）：{missing}"

    def test_no_target_shares_an_unregistered_field_key(self):
        """「一套字段两个页面填」的机械判据（issue #5321 裁定 / #5648 收口）。

        形态由「两两**零交集**」升级为「**未登记的共享键即红**」——
        因为 #5648 的 `shipment` 与 `order` 在 `quantity` 上**必然同名**：「数量」在库里
        就叫 `order_items.quantity`，而字段面要求与订单行同名（不许自造口径）。
        两者是**同一列名、两个不同的事实**（下单数量 vs 实发数量）。

        ⇒ 共享必须逐条登记在 `SHARED_FIELD_KEYS`（登记项**只许缩短**）；任何**未登记**的
        共享键当场红 —— 把 shipment 整份字段表改成与 order 逐字相同 ⇒ 五格全部未登记 ⇒ 红。
        """
        registered = {k: frozenset(v) for k, v in SHARED_FIELD_KEYS.items()}
        targets = list(TARGET_FIELDS)
        offenders = []
        for i, a in enumerate(targets):
            for b in targets[i + 1:]:
                for key in sorted(set(field_keys(a)) & set(field_keys(b))):
                    if registered.get(key) != frozenset({a, b}):
                        offenders.append((a, b, key))
        assert offenders == [], (
            "出现**未登记**的跨 target 共享字段键（登记表 = targets.py 的 SHARED_FIELD_KEYS）："
            f"{offenders}"
        )

    def test_shared_key_ledger_only_shrinks(self):
        """登记项**只许缩短**：登记了「共享」但实际上不再共享 ⇒ 红（豁免必带死亡条件）。"""
        dead = [
            (key, pair)
            for key, pair in SHARED_FIELD_KEYS.items()
            for a, b in [tuple(pair)]
            if key not in (set(field_keys(a)) & set(field_keys(b)))
        ]
        assert dead == [], f"共享键登记表里有过期条目（不再共享却没删）：{dead}"

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

    def test_shipment_side_is_the_strictest(self):
        """发货侧 0.90 **严于**订单侧 0.85（issue #5648）。

        理由不是"多发一个数"：订单侧认错 ⇒ 客户信息错（货发错人，还能追）；
        发货侧认错 ⇒ **数量/规格错**，而那是**已经出了车间**的既成事实 —— 追回来贵得多。
        """
        assert TARGET_POLICY["shipment"]["min_confidence"] > TARGET_POLICY["order"]["min_confidence"]
        assert TARGET_POLICY["shipment"]["min_confidence"] == 0.90

    def test_every_target_has_a_policy_and_a_side_label(self):
        assert set(TARGET_POLICY) == set(TARGET_FIELDS)
        assert set(TARGET_SIDE_LABEL) == set(TARGET_FIELDS)
        assert TARGET_SIDE_LABEL["order"] == "订单侧"
        assert TARGET_SIDE_LABEL["shipment"] == "发货侧"