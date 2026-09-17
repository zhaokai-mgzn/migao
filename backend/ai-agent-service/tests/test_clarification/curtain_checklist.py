"""窗帘下单澄清清单引擎单元测试（app/clarification/curtain_checklist.py）

覆盖（M3-E，issue #3986）：
- 必填检测：尺寸缺失必须追问（不阻塞报价流程，缺省即报）
- 矛盾拦截：4.6m 单开→建议双开、四开偏窄、折数整除、工艺互斥、打孔不按折数、倍数<1.5
- 默认三层合成：行业【标】 < 商家【默】 < 客户记忆（craft_profile）
- 轮次上限：每轮 ≤3 问，超上限转复尺/人工

真值源：docs/curtain-fabric-quote-rules.md §1/§8 + docs/curtain-production-rules.md §7
"""
# case_ids: CH-037
import pytest

from app.clarification.curtain_checklist import (
    ask_batch,
    conflicts,
    merged_defaults,
    missing_required,
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
