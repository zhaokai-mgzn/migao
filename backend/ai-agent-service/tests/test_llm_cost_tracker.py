"""LLM 成本追踪单元测试（app/llm/cost_tracker.py）

覆盖：
- _calc_cost_cny：已知模型按 MODEL_PRICING 计费、未知模型 fallback 主模型、round 6 位
- CostTracker.track_call：开关关闭返回 None；开启后累计记录与总额
- check_budget：预算 <=0 不告警；超预算仅首次 warning
- get_summary：按模型分组汇总
- reset：清零记录
"""
# case_ids: FN-002
import pytest

from app.config import settings
from app.llm.cost_tracker import (
    MODEL_PRICING,
    CostTracker,
    _calc_cost_cny,
)


class TestCalcCostCny:
    def test_known_fast_model(self):
        cost = _calc_cost_cny(settings.LLM_MODEL_FAST, 1_000_000, 1_000_000)
        expected = MODEL_PRICING[settings.LLM_MODEL_FAST]["input"] + \
            MODEL_PRICING[settings.LLM_MODEL_FAST]["output"]
        assert cost == pytest.approx(expected)

    def test_known_primary_model(self):
        cost = _calc_cost_cny(settings.LLM_MODEL_PRIMARY, 1_000_000, 0)
        expected = MODEL_PRICING[settings.LLM_MODEL_PRIMARY]["input"]
        assert cost == pytest.approx(expected)

    def test_unknown_model_falls_back_to_primary(self):
        primary = MODEL_PRICING[settings.LLM_MODEL_PRIMARY]
        cost = _calc_cost_cny("unknown-model", 1_000_000, 1_000_000)
        assert cost == pytest.approx(primary["input"] + primary["output"])

    def test_rounds_to_six_decimals(self):
        cost = _calc_cost_cny(settings.LLM_MODEL_FAST, 1, 1)
        # (1/1e6)*1.0 + (1/1e6)*4.0 = 0.000005
        assert cost == 0.000005


class TestTrackCall:
    def test_disabled_returns_none(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_COST_TRACKING_ENABLED", False)
        tracker = CostTracker()
        record = tracker.track_call(settings.LLM_MODEL_FAST, 100, 50)
        assert (record is None)
        assert tracker.total_cost == 0.0

    def test_enabled_records_and_accumulates(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_COST_TRACKING_ENABLED", True)
        monkeypatch.setattr(settings, "LLM_MONTHLY_BUDGET_CNY", 500.0)
        tracker = CostTracker()
        record = tracker.track_call(
            settings.LLM_MODEL_FAST, 1000, 500, tenant_id=1, session_id="s1"
        )
        assert record.model == settings.LLM_MODEL_FAST
        assert record.tenant_id == 1
        assert record.session_id == "s1"
        assert tracker.total_cost == pytest.approx(record.cost_cny)

    def test_enabled_with_default_budget(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_COST_TRACKING_ENABLED", True)
        monkeypatch.setattr(settings, "LLM_MONTHLY_BUDGET_CNY", 0.0)
        tracker = CostTracker()
        record = tracker.track_call(settings.LLM_MODEL_FAST, 1, 1)
        assert record.cost_cny > 0


class TestCheckBudget:
    def test_budget_zero_or_negative_never_over(self, monkeypatch):
        tracker = CostTracker()
        monkeypatch.setattr(settings, "LLM_MONTHLY_BUDGET_CNY", 0)
        assert tracker.check_budget() is False

    def test_under_budget(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_MONTHLY_BUDGET_CNY", 500.0)
        tracker = CostTracker()
        assert tracker.check_budget() is False

    def test_over_budget(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_MONTHLY_BUDGET_CNY", 1.0)
        monkeypatch.setattr(settings, "LLM_COST_TRACKING_ENABLED", True)
        tracker = CostTracker()
        tracker.track_call(settings.LLM_MODEL_FAST, 10_000_000, 0)
        assert tracker.check_budget() is True


class TestGetSummary:
    def test_groups_by_model(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_MONTHLY_BUDGET_CNY", 500.0)
        monkeypatch.setattr(settings, "LLM_COST_TRACKING_ENABLED", True)
        tracker = CostTracker()
        tracker.track_call(settings.LLM_MODEL_FAST, 1000, 500)
        tracker.track_call(settings.LLM_MODEL_FAST, 2000, 1000)
        # 主模型已统一为 deepseek-v4-flash（与快模型同名），用未知模型名模拟第三组
        tracker.track_call("qwen3.7-max", 500, 500)

        summary = tracker.get_summary()
        assert summary["total_calls"] == 3
        fast = summary["by_model"][settings.LLM_MODEL_FAST]
        assert fast["calls"] == 2
        assert fast["input_tokens"] == 3000
        assert fast["output_tokens"] == 1500
        assert summary["budget_cny"] == 500.0
        assert summary["over_budget"] is False

    def test_empty_summary(self):
        tracker = CostTracker()
        summary = tracker.get_summary()
        assert summary["total_calls"] == 0
        assert summary["by_model"] == {}


class TestReset:
    def test_reset_clears_records(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_COST_TRACKING_ENABLED", True)
        monkeypatch.setattr(settings, "LLM_MONTHLY_BUDGET_CNY", 500.0)
        tracker = CostTracker()
        tracker.track_call(settings.LLM_MODEL_FAST, 1000, 500)
        assert tracker.total_cost > 0
        tracker.reset()
        assert tracker.total_cost == 0.0
        assert tracker.get_summary()["total_calls"] == 0
