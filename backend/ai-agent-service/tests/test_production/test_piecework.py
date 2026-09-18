"""计件与完工判定测试（app/production/piecework.py，issue #3993，M4-G-1）"""
# case_ids: PP-010
import pytest

from app.production.piecework import compute_piecework, is_production_done

INSTANCES = [
    {"operation": "精裁-布", "unit": "米", "unit_price": 0.4, "factor": 1.0,
     "is_must_finish": False, "is_start_marker": True, "qty": 12.3},
    {"operation": "韩褶-布", "unit": "折", "unit_price": 0.4, "factor": 1.0,
     "is_must_finish": False, "is_start_marker": False, "qty": 48},
    {"operation": "外帘装袋", "unit": "套", "unit_price": 1.0, "factor": 1.0,
     "is_must_finish": True, "is_start_marker": False, "qty": 1},
]


def test_compute_piecework_normal_only():
    """正常报工计件：韩褶 48 折×0.4=19.2；返工/报废不计件"""
    logs = [
        {"operation": "精裁-布", "worker": "肖梅", "qty": 12.3, "qualified_qty": 12.3, "type": "normal"},
        {"operation": "韩褶-布", "worker": "李红梅", "qty": 48, "qualified_qty": 48, "type": "normal"},
        {"operation": "韩褶-布", "worker": "李红梅", "qty": 5, "qualified_qty": 0, "type": "rework"},
        {"operation": "外帘装袋", "worker": "王姐", "qty": 1, "qualified_qty": 1, "type": "normal"},
    ]
    r = compute_piecework(INSTANCES, logs)
    assert r["total"] == pytest.approx(12.3 * 0.4 + 48 * 0.4 + 1 * 1.0, abs=0.01)
    assert r["per_worker"]["李红梅"] == pytest.approx(48 * 0.4, abs=0.01)
    assert r["per_worker"]["王姐"] == pytest.approx(1.0, abs=0.01)
    assert "计件合计" in r["summary"]


def test_compute_piecework_factor():
    """一分为二（ERP 名，issue #4389）系数 ×1.7：韩褶 48 折 × 0.4 × 1.7"""
    insts = [{**i, "factor": 1.7} for i in INSTANCES]
    logs = [{"operation": "韩褶-布", "worker": "李红梅", "qty": 48, "qualified_qty": 48, "type": "normal"}]
    r = compute_piecework(insts, logs)
    assert r["per_worker"]["李红梅"] == pytest.approx(48 * 0.4 * 1.7, abs=0.01)


def test_is_production_done_must_finish_insufficient():
    """必完工序（外帘装袋）未满 → 未完工"""
    logs = [
        {"operation": "精裁-布", "qty": 12.3, "qualified_qty": 12.3, "type": "normal"},
        {"operation": "韩褶-布", "qty": 48, "qualified_qty": 48, "type": "normal"},
    ]
    assert is_production_done(INSTANCES, logs) is False


def test_is_production_done_all_must_finish():
    """必完工序全绿 → 自动生产完成"""
    logs = [
        {"operation": "精裁-布", "qty": 12.3, "qualified_qty": 12.3, "type": "normal"},
        {"operation": "韩褶-布", "qty": 48, "qualified_qty": 48, "type": "normal"},
        {"operation": "外帘装袋", "qty": 1, "qualified_qty": 1, "type": "normal"},
    ]
    assert is_production_done(INSTANCES, logs) is True


def test_is_production_done_rework_not_counted():
    """必完工序只有返工报工 → 不算完成"""
    logs = [
        {"operation": "外帘装袋", "qty": 1, "qualified_qty": 0, "type": "rework"},
    ]
    assert is_production_done(INSTANCES, logs) is False
