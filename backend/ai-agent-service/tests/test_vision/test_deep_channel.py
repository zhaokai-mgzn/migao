# case_ids: CH-021, PR-008, OR-008
"""**Agent 深通道**的确定性半边（issue #5368 包 2）。

包 1（PR #5343）交付的是**页面快通道**；本包是**深通道**，两者**共用识别内核**
（`backend/ai-agent-service/app/vision/recognizer.py`）但**互不依赖**。

深通道只补页面做不到的三种（issue #5368 的定位表）：
**歧义消解** / **领域解读** / **跨实体追问** —— 前两种的**可判定部分**落在本模块（纯函数），
第三种（多轮澄清）由 Agent 用既有 `interact` 卡完成，不需要新代码。

本文件钉住的五条（与 issue 的验收判据逐条对应）：

| # | 判据 | 断言 |
|---|---|---|
| 2 | **来源标注可区分**（识别 vs 解读） | 两个标记串**不同**、且识别标记就是内核常量**本身**（不是抄一份）；每一格最多一个来源 |
| 3 | **歧义给候选 + 解释，不擅自填值** | 目录未命中 ⇒ `value` 留空 + `candidates` + `reason`；**注入式红证**：把留空改成填值 ⇒ 断言变红 |
| 4 | **不落库** | 本模块在 `app/vision/*.py` 的既有静态扫描射程内（射程自证，见 `TestScannedByPackageOneGuard`） |
| — | **领域解读**有独立来源、且**订单侧只解读不填值** | 商品侧仅填空格且仅限可解读键；订单侧一格都不填（客户信息错 ⇒ 货发错人） |
| 1 | **零 PII 落日志** | `log_summary()` 只含 target/计数/键名 —— 值一律不进摘要，且有判别力红证 |

🔴 **本模块不落库、也不持久化任何东西**：它只产出「填哪几格 + 候选 + 解读」这一个出口形状；
同页填充的**瞬时通道**（SSE `page_fill` → 浏览器内存事件）不在本模块，提交永远是人的动作。
"""
import importlib.util
import sys
from pathlib import Path

from app.vision.deep_channel import (
    INTERPRETABLE_KEYS,
    PAGE_FILL_COMPONENT,
    SOURCE_INTERPRETED,
    SOURCE_RECOGNIZED,
    build_page_fill,
    log_summary,
    resolve_against_catalog,
)
from app.vision.recognizer import FIELD_MARKER, extract_fields

DEEP_CHANNEL_PY = (
    Path(__file__).resolve().parents[2] / "app" / "vision" / "deep_channel.py"
)

# ── 固定夹具：钉住 vision 输出（与包 1 同口径，本文件不重复测内核）─────────────
PRODUCT_VISION = """{"fields": {
  "name":       {"value": "雪尼尔遮光窗帘", "confidence": 0.95},
  "color":      {"value": "雾霾蓝", "confidence": 0.90},
  "material":   {"value": null, "reason": "图片未标注材质"},
  "craft":      {"value": "遮光", "confidence": 0.80},
  "door_width": {"value": null, "reason": "图片未标注门幅"},
  "price":      {"value": null, "reason": "图上没有价格"}
}}"""

ORDER_VISION = """{"fields": {
  "customer_name":    {"value": "王秀英", "confidence": 0.95},
  "customer_phone":   {"value": "138 0013 8000", "confidence": 0.92},
  "customer_address": {"value": "杭州市余杭区某小区 3 幢", "confidence": 0.90},
  "items":            {"value": "雪尼尔遮光窗帘", "confidence": 0.90},
  "quantity":         {"value": "3 套", "confidence": 0.90},
  "curtain_width":    {"value": "窗宽 2.8 米", "confidence": 0.92},
  "curtain_height":   {"value": "2.4 米", "confidence": 0.92}
}}"""

CATALOG_WITHOUT_THE_RECOGNISED_COLOR = ["藏青", "天蓝", "灰蓝", "奶茶色"]


def product_fields():
    return extract_fields("product", PRODUCT_VISION)


def order_fields():
    return extract_fields("order", ORDER_VISION)


def field_of(plan, key):
    return next(f for f in plan["fields"] if f["key"] == key)


def _load_mutated(source: str, tmp_path: Path, name: str = "deep_channel_mutant"):
    """把变异后的源码当**独立模块**加载（真跑，不是读文本）。"""
    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


# ══════════════════════════════════════════════════════════════════════════════
# 判据 2：来源标注可区分
# ══════════════════════════════════════════════════════════════════════════════
class TestSourceMarkersAreDistinguishable:
    def test_recognised_marker_is_the_kernel_constant_object_itself(self):
        """「识别来的」标记必须**就是**内核那份（`is` 身份），不是抄一遍的同值副本。"""
        assert SOURCE_RECOGNIZED is FIELD_MARKER
        assert SOURCE_RECOGNIZED == "[图片识别]"

    def test_interpreted_marker_is_a_different_non_empty_string(self):
        assert SOURCE_INTERPRETED == "[米宝解读]"
        assert SOURCE_INTERPRETED != SOURCE_RECOGNIZED
        assert SOURCE_RECOGNIZED not in SOURCE_INTERPRETED
        assert SOURCE_INTERPRETED not in SOURCE_RECOGNIZED

    def test_every_filled_cell_carries_exactly_one_of_the_two_sources(self):
        plan = build_page_fill(
            "product",
            product_fields(),
            interpretations={"material": {"value": "雪尼尔", "note": "看着是雪尼尔，克重偏厚"}},
        )
        filled = [f for f in plan["fields"] if f["value"]]
        assert [f["key"] for f in filled] == ["name", "color", "material", "craft"]
        assert {f["source"] for f in filled} == {SOURCE_RECOGNIZED, SOURCE_INTERPRETED}
        assert field_of(plan, "material")["source"] == SOURCE_INTERPRETED
        assert field_of(plan, "craft")["source"] == SOURCE_RECOGNIZED


# ══════════════════════════════════════════════════════════════════════════════
# 判据 3：歧义 ⇒ 候选 + 解释，绝不擅自填值（含注入式红证）
# ══════════════════════════════════════════════════════════════════════════════
class TestAmbiguityGivesCandidatesAndNeverFills:
    def test_catalog_miss_is_ambiguous_with_candidates_and_an_explanation(self):
        resolution = resolve_against_catalog("雾霾蓝", CATALOG_WITHOUT_THE_RECOGNISED_COLOR)
        assert resolution["status"] == "ambiguous"
        assert resolution["matched"] is None or resolution["matched"] == ""
        assert resolution["candidates"], "歧义必须给候选（否则商家无从选）"
        assert {c["value"] for c in resolution["candidates"]} <= set(
            CATALOG_WITHOUT_THE_RECOGNISED_COLOR
        )
        assert "雾霾蓝" in resolution["reason"]
        assert "宁可不填" in resolution["reason"]
        assert all("雾霾蓝" in c["reason"] for c in resolution["candidates"])

    def test_catalog_hit_is_matched_not_ambiguous(self):
        resolution = resolve_against_catalog("藏青", CATALOG_WITHOUT_THE_RECOGNISED_COLOR)
        assert resolution["status"] == "matched"
        assert resolution["matched"] == "藏青"
        assert resolution["candidates"] == []

    def test_without_a_catalog_the_value_is_left_unchecked_not_guessed(self):
        """没有目录 ⇒ **不做无据的消歧**（既不说命中、也不说没命中）。"""
        resolution = resolve_against_catalog("雾霾蓝", None)
        assert resolution["status"] == "unchecked"
        assert resolution["candidates"] == []

    def test_plan_leaves_the_ambiguous_cell_empty_and_offers_candidates(self):
        plan = build_page_fill(
            "product", product_fields(), catalog={"color": CATALOG_WITHOUT_THE_RECOGNISED_COLOR}
        )
        color = field_of(plan, "color")
        assert color["value"] is None
        assert color["source"] is None
        assert color["candidates"]
        assert "宁可不填" in color["reason"]
        # 该值**不得**从任何一格溜进表单（连"降级成其它键"也不行）
        assert "雾霾蓝" not in [f["value"] for f in plan["fields"] if f["value"]]
        assert [f["key"] for f in plan["fields"] if f["value"]] == ["name", "craft"]

    def test_ambiguity_is_never_overridden_by_an_interpretation(self):
        """歧义格即使 Agent 给了推荐值，也**必须**由商家选（不得替用户拍板）。"""
        plan = build_page_fill(
            "product",
            product_fields(),
            catalog={"craft": ["印花"]},
            interpretations={"craft": {"value": "遮光", "note": "看着像遮光工艺"}},
        )
        craft = field_of(plan, "craft")
        assert craft["value"] is None
        assert craft["source"] is None
        assert craft["candidates"]
        # 解读仍然要能表达出来（只是不能变成表单里的值）
        assert craft["note"] == "看着像遮光工艺"
        assert craft["note_source"] == SOURCE_INTERPRETED

    def test_injected_mutation_that_fills_an_ambiguous_cell_turns_it_red(self, tmp_path):
        """**注入式红证**：把「歧义 ⇒ 留空」改成「歧义 ⇒ 直接填」⇒ 上面的断言必须变红。

        红证**前提自证**：变异前后源码必须真的不同（否则"没变红"只是因为注入没生效）。
        """
        source = DEEP_CHANNEL_PY.read_text(encoding="utf-8")
        anchor = 'cell["value"] = None\n    cell["source"] = None'
        assert anchor in source, "注入锚点已漂移 —— 先更新本用例的锚点，别把「注入没生效」当绿"
        mutant_src = source.replace(
            anchor,
            'cell["value"] = original\n    cell["source"] = SOURCE_RECOGNIZED',
            1,
        )
        assert mutant_src != source

        mutant = _load_mutated(mutant_src, tmp_path)
        plan = mutant.build_page_fill(
            "product", product_fields(), catalog={"color": CATALOG_WITHOUT_THE_RECOGNISED_COLOR}
        )
        color = next(f for f in plan["fields"] if f["key"] == "color")
        assert color["value"] == "雾霾蓝", "注入必须真的改变行为（否则红证不成立）"
        assert color["source"] == SOURCE_RECOGNIZED


# ══════════════════════════════════════════════════════════════════════════════
# 领域解读：独立来源 + 商品 / 订单两侧的不对称
# ══════════════════════════════════════════════════════════════════════════════
class TestInterpretationIsMarkedAndAsymmetric:
    def test_product_interpretation_fills_an_empty_interpretable_cell(self):
        plan = build_page_fill(
            "product",
            product_fields(),
            interpretations={"material": {"value": "雪尼尔", "note": "克重偏厚，适合客厅"}},
        )
        material = field_of(plan, "material")
        assert material["value"] == "雪尼尔"
        assert material["source"] == SOURCE_INTERPRETED
        assert material["note_source"] == SOURCE_INTERPRETED

    def test_product_interpretation_never_overwrites_a_recognised_cell(self):
        plan = build_page_fill(
            "product",
            product_fields(),
            interpretations={"craft": {"value": "印花", "note": "也许是印花"}},
        )
        craft = field_of(plan, "craft")
        assert craft["value"] == "遮光"
        assert craft["source"] == SOURCE_RECOGNIZED
        assert craft["note"] == "也许是印花"
        assert craft["note_source"] == SOURCE_INTERPRETED

    def test_product_interpretation_cannot_fill_a_non_interpretable_cell(self):
        """**结算面**（售价 / 门幅）不接受解读填值 —— 猜出来的钱格比空格贵。"""
        plan = build_page_fill(
            "product",
            product_fields(),
            interpretations={"price": {"value": "128", "note": "同类商品大约 128"}},
        )
        price = field_of(plan, "price")
        assert price["value"] is None
        assert price["source"] is None
        assert price["note"] == "同类商品大约 128"

    def test_order_interpretation_never_fills_any_cell(self):
        """订单侧风险更高（客户信息错 ⇒ 货发错人）⇒ 解读**只解释、一格都不填**。"""
        plan = build_page_fill(
            "order",
            order_fields(),
            interpretations={
                "customer_name": {"value": "王秀英", "note": "手写体看着像王秀英"},
                "items": {"value": "雪尼尔窗帘", "note": "图上两件商品"},
            },
        )
        assert field_of(plan, "customer_name")["source"] == SOURCE_RECOGNIZED
        assert field_of(plan, "customer_name")["note_source"] == SOURCE_INTERPRETED
        assert INTERPRETABLE_KEYS["order"] == ()

    def test_order_interpretation_is_reported_but_not_fillable(self):
        """商品侧可解读、订单侧不可 —— 同一个键在两 target 上的处置**必须不同**。"""
        empty_material = [f for f in product_fields()]
        for f in empty_material:
            if f["key"] == "material":
                f["value"] = None
                f["source"] = None
        filled_product = build_page_fill(
            "product", empty_material, interpretations={"material": {"value": "雪尼尔"}}
        )
        assert field_of(filled_product, "material")["value"] == "雪尼尔"

        order_with_empty_items = order_fields()
        for f in order_with_empty_items:
            if f["key"] == "items":
                f["value"] = None
                f["source"] = None
        filled_order = build_page_fill(
            "order", order_with_empty_items, interpretations={"items": {"value": "雪尼尔窗帘"}}
        )
        assert field_of(filled_order, "items")["value"] is None
        assert field_of(filled_order, "items")["source"] is None


# ══════════════════════════════════════════════════════════════════════════════
# 同页填充计划的形状契约（前端按它逐格填、逐格标注）
# ══════════════════════════════════════════════════════════════════════════════
class TestPageFillPlanContract:
    def test_plan_has_exactly_the_three_contracted_keys(self):
        """没有 id / saved / created 之类的落库痕迹（同包 1 端点返回体的口径）。"""
        plan = build_page_fill("product", product_fields())
        assert set(plan.keys()) == {"component", "target_type", "fields"}
        assert plan["component"] == PAGE_FILL_COMPONENT == "page_fill"
        assert plan["target_type"] == "product"

    def test_every_field_has_the_uniform_eight_keys(self):
        plan = build_page_fill("order", order_fields())
        assert [sorted(f.keys()) for f in plan["fields"]] == [
            ["candidates", "key", "label", "note", "note_source", "reason", "source", "value"]
        ] * len(plan["fields"])

    def test_filled_cells_have_a_source_and_empty_cells_have_a_reason(self):
        """不变式（两个 target 都过）：有值 ⇒ 必带来源标注；留空 ⇒ 必给理由。"""
        for target, fields in (("product", product_fields()), ("order", order_fields())):
            plan = build_page_fill(target, fields)
            for f in plan["fields"]:
                if f["value"]:
                    assert f["source"] in (SOURCE_RECOGNIZED, SOURCE_INTERPRETED), f
                    assert f["label"], f
                else:
                    assert f["reason"], f
                    assert f["note_source"] in (None, SOURCE_INTERPRETED), f

    def test_unknown_target_is_rejected(self):
        try:
            build_page_fill("invoice", product_fields())
        except ValueError as e:
            assert "invoice" in str(e)
        else:
            raise AssertionError("未知 target 必须 fail-closed")


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1 的日志半边：值（含 PII）绝不进日志摘要
# ══════════════════════════════════════════════════════════════════════════════
def leaks_a_value(summary: str, plan: dict) -> bool:
    """判别器：摘要里是否出现任何**字段值**（或订单侧手机号的数字串）。"""
    for f in plan["fields"]:
        value = f["value"]
        if isinstance(value, str) and value and value in summary:
            return True
    return "13800138000" in summary


class TestNothingButCountsAndKeysGoesToLogs:
    def test_summary_contains_counts_and_keys_but_no_value(self):
        plan = build_page_fill("order", order_fields())
        summary = log_summary(plan)
        assert "target=order" in summary
        assert "customer_phone" in summary  # 键名可以（排查要靠它）
        assert "王秀英" not in summary
        assert "杭州市余杭区某小区 3 幢" not in summary
        assert "138" not in summary
        assert not leaks_a_value(summary, plan)

    def test_leak_detector_has_discriminative_power(self):
        """红证：把值拼进摘要 ⇒ 判别器必须认出来（否则上面那条是空断言）。"""
        plan = build_page_fill("order", order_fields())
        leaky = f"{log_summary(plan)} phone={field_of(plan, 'customer_phone')['value'].replace(' ', '')}"
        assert leaks_a_value(leaky, plan)
        assert not leaks_a_value("component=page_fill target=order filled=7", plan)


# ══════════════════════════════════════════════════════════════════════════════
# 判据 4：不落库 —— 射程自证（复用包 1 的静态扫描口径，不另写一份）
# ══════════════════════════════════════════════════════════════════════════════
class TestScannedByPackageOneGuard:
    def test_new_module_is_inside_the_scanned_package(self):
        """包 1 的 `TestNoWriteBoundary.test_vision_package_touches_no_write_seam` 按
        `app/vision/*.py` 取射程 ⇒ 本模块必须在那个 glob 里；否则「不落库」对本包**空跑**
        （测试全绿而判据从不运行，正是本仓最忌的静默失效）。

        ⚠️ 本用例**不重新实现**扫描（第二份口径必然漂移）：它只证明**射程覆盖**，
        真正的写入缝扫描仍由包 1 的那条用例执行。
        """
        assert DEEP_CHANNEL_PY.parent.name == "vision"
        assert DEEP_CHANNEL_PY in sorted(DEEP_CHANNEL_PY.parent.glob("*.py"))