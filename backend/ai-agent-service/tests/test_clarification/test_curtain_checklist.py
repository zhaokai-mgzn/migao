"""窗帘下单澄清清单引擎单元测试（app/clarification/curtain_checklist.py）

覆盖（M3-E，issue #3986）：
- 必填检测：尺寸缺失必须追问（不阻塞报价流程，缺省即报）
- 矛盾拦截：4.6m 单开→建议双开、四开偏窄、折数整除、工艺互斥、打孔不按折数、倍数<1.5
- 默认三层合成：行业【标】 < 商家【默】 < 客户记忆（craft_profile）
- 轮次上限：每轮 ≤3 问，超上限转复尺/人工
- **清单 → 下单行要素**（issue #4362，S1）：`to_craft_spec` 把已收集字段映射成
  `processing_info` 顶层键（**「问到了却不落库」的修法**）

真值源：docs/curtain-fabric-quote-rules.md §1/§8 + docs/curtain-production-rules.md §7
"""
# case_ids: CH-037
import pytest

from app.clarification.curtain_checklist import (
    CALC_OUTPUT_PASSTHROUGH_KEYS,
    CHECKLIST,
    CHECKLIST_TO_CRAFT_SPEC,
    ask_batch,
    conflicts,
    merged_defaults,
    missing_required,
    to_craft_spec,
)


# ── 1. 必填检测（尺寸缺失必须追问）──
def test_missing_required_empty_collector():
    missing = missing_required({})
    assert "intent" in missing
    assert "room" in missing
    assert "width" in missing
    assert "height" in missing


def test_missing_required_width_height_collected():
    missing = missing_required({"width": 4.64, "height": 2.6})
    assert "width" not in missing
    assert "height" not in missing


# ── 2. 矛盾拦截 ──
def test_conflict_single_open_too_wide():
    warns = conflicts({"width": 4.6, "open_count": 1})
    assert any("建议双开" in w for w in warns)


def test_conflict_four_open_too_narrow():
    warns = conflicts({"width": 3.0, "open_count": 4})
    assert any("四开偏窄" in w for w in warns)


def test_conflict_pleat_divisibility():
    warns = conflicts({"pleat_count": 47, "open_count": 2})
    assert any("整除" in w for w in warns)


def test_conflict_invalid_craft():
    warns = conflicts({"craft": "波浪褶"})
    assert any("不在可选范围" in w for w in warns)


def test_conflict_eyelet_ignores_pleats():
    warns = conflicts({"craft": "打孔", "pleat_count": 48})
    assert any("不按折数" in w for w in warns)


def test_conflict_fullness_below_red_line():
    warns = conflicts({"fullness": 1.4})
    assert any("低于行业下限" in w for w in warns)


def test_no_conflict_normal_case():
    assert conflicts({"width": 4.6, "open_count": 2, "pleat_count": 48, "craft": "韩褶"}) == []


# ── 3. 默认三层合成（客户记忆 > 商家【默】 > 行业【标】）──
def test_industry_defaults_basic():
    d = merged_defaults({"width": 4.64, "curtain_type": "布帘"})
    assert "curtain_type" not in d        # 已收集字段不出现在默认里
    assert d["craft"] == "韩褶"
    assert d["pleat_spacing"] == 0.1
    assert d["open_count"] == 2          # 4.64m > 2.2m → 双开
    assert d["is_shaped"] is True        # 布帘默认定型


def test_industry_default_single_open_by_width():
    # 客户实证：2.05m 宽仍用单开
    d = merged_defaults({"width": 2.05})
    assert d["open_count"] == 1


def test_industry_default_sheer_not_shaped():
    d = merged_defaults({"curtain_type": "纱帘"})
    assert d["is_shaped"] is False


def test_customer_profile_overrides_industry():
    profile = {"craft_profile": {"open_count": 4, "is_shaped": True}, "craft_mode": "economy"}
    d = merged_defaults({"width": 4.64}, customer_profile=profile)
    assert d["open_count"] == 4          # 客户记忆优先于行业规则


def test_merchant_overrides_industry():
    d = merged_defaults({}, merchant_defaults={"craft": "打孔", "pleat_spacing": 0.12})
    assert d["craft"] == "打孔"
    assert d["pleat_spacing"] == 0.12


def test_defaults_skip_collected_fields():
    d = merged_defaults({"curtain_type": "帘头", "craft": "打孔"})
    assert "curtain_type" not in d
    assert "craft" not in d


# ── 4. 轮次上限（每轮 ≤3，超限转复尺/人工）──
def test_ask_batch_limited_per_round():
    questions, cont = ask_batch({}, rounds=0)
    assert len(questions) <= 3
    assert cont is True


def test_ask_batch_handoff_after_max_rounds():
    questions, cont = ask_batch({}, rounds=3)
    assert cont is False
    assert any("量尺" in q or "预算" in q for q in questions)


def test_ask_batch_complete_when_all_collected():
    collector = {"intent": "报价", "room": "客厅", "width": 4.64, "height": 2.6}
    questions, cont = ask_batch(collector, rounds=0)
    assert questions == []
    assert cont is True


# ── 5. 清单 → 下单行要素（issue #4362，S1）──
# 判据：真值源 §1 的下单行要素此前「问到了却不落库」（只活在 collector 字典里，会话结束即丢）
# ⇒ 加工单只能靠加工项名**猜**部位/工艺。`to_craft_spec` 是修法，且必须**只搬运**：
# 不补默认值、不猜、不做业务推导（用户裁定「部位不是必填的」）。

def test_craft_spec_maps_checklist_ids_to_processing_info_keys():
    spec = to_craft_spec({
        "curtain_type": "纱帘", "craft": "打孔", "open_count": 4,
        "is_shaped": False, "pleat_spacing": 0.1, "has_pattern": True,
        "window_type": "转角",
    })
    assert spec == {
        "curtainType": "纱帘",
        "craft": "打孔",
        "openCount": 4,
        "isShaped": False,
        "pleatSpacing": 0.1,
        "hasPattern": True,
        "corner": "转角",          # 清单里「转角」就是窗型的一项（note：转角影响开数与片数）
    }


def test_craft_spec_omits_missing_fields_never_invents_defaults():
    # 只收集了帘型 ⇒ 只有这一个键；**不得**补 craft/pleat_spacing 的行业默认值
    # （默认值由 merged_defaults 管，落库只认真实采集到的值 —— 否则库里会出现「没人说过」的工艺）
    spec = to_craft_spec({"curtain_type": "布帘"})
    assert spec == {"curtainType": "布帘"}
    assert "craft" not in spec
    assert "pleatSpacing" not in spec
    assert "openCount" not in spec


def test_craft_spec_passes_calc_output_through_verbatim():
    spec = to_craft_spec({"curtain_type": "布帘"}, calc={
        "fullness": 2.0, "fullness_actual": 1.86, "pleat_count": 48, "fabric_meters": 12.3})
    # 算料输出键名原样（= Java 侧 CALC_INFO_KEYS 口径），只透传白名单里的三个
    assert spec["fullness"] == 2.0
    assert spec["fullness_actual"] == 1.86
    assert spec["pleat_count"] == 48
    assert "fabric_meters" not in spec      # 米数走 processingMeters / 加工项口径，不经本映射


def test_craft_spec_collected_value_wins_over_calc_output():
    # 顾客/商家明确填过的值不得被算料输出覆盖（否则「人改的」被「算的」静默盖掉）
    spec = to_craft_spec({"pleat_spacing": 0.12}, calc={"fullness": 2.0})
    assert spec["pleatSpacing"] == 0.12
    assert spec["fullness"] == 2.0


def test_craft_spec_mapping_targets_are_all_declared_order_line_elements():
    # 双向自证（防「映射表里写了、落库侧不认」）：目标键必须落在**已声明**的两组键里
    declared = set(CHECKLIST_TO_CRAFT_SPEC.values()) | set(CALC_OUTPUT_PASSTHROUGH_KEYS)
    assert declared == {
        "curtainType", "craft", "openCount", "isShaped", "pleatSpacing",
        "hasPattern", "corner", "fullness", "fullness_actual", "pleat_count",
    }


def test_craft_spec_mapping_sources_are_real_checklist_fields():
    # 映射源必须是清单里**真实存在**的字段 id（写错一个 id ⇒ 该项永远映射不到 = 静默丢值）
    ids = {item["id"] for item in CHECKLIST}
    unknown = set(CHECKLIST_TO_CRAFT_SPEC) - ids
    assert unknown == set()


def test_checklist_asks_has_pattern():
    # 是否对花（真值源 §1 下单行要素）：此前只在 fabric 的 note 里一笔带过 ⇒ 没人问、也没处落库
    by_id = {item["id"]: item for item in CHECKLIST}
    assert "has_pattern" in by_id
    assert by_id["has_pattern"]["required"] is False   # 可空、不阻塞报价
