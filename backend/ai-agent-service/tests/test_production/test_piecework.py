"""计件与完工判定测试（app/production/piecework.py，issue #3993，M4-G-1）

issue #4589（用户裁定 2026-09-19）：计件工资 = **报工数量 × 计件单价**，不再乘任何系数
—— 「一分为二」这类特殊选项的 ×1.7 系数已从算法里退场。
"""
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


def test_compute_piecework_ignores_factor():
    """#4589：工序实例带系数（历史快照 1.7）时，金额仍 = 数量 × 单价。

    红证（改前实测）：实现里乘了 `inst["factor"]` ⇒ 韩褶 48 折 × 0.4 × 1.7 = **32.64**，
    而本断言期望 19.20 ⇒ 逐值红（正好差 1.7 倍）。逐笔与总额**两条路径**都断言：
    本单改的就是这两处。
    """
    insts = [{**i, "factor": 1.7} for i in INSTANCES]
    logs = [{"operation": "韩褶-布", "worker": "李红梅", "qty": 48, "qualified_qty": 48, "type": "normal"}]
    r = compute_piecework(insts, logs)
    assert r["per_worker"]["李红梅"] == pytest.approx(48 * 0.4, abs=0.01)
    assert r["total"] == pytest.approx(48 * 0.4, abs=0.01)
    per_operation = {row["operation"]: row["amount"] for row in r["per_operation"]}
    assert per_operation["韩褶-布"] == pytest.approx(48 * 0.4, abs=0.01)
    # 判别性：不得是 1.7 倍（防「把期望值改成 1.7 倍」式的假修复）
    assert r["total"] != pytest.approx(48 * 0.4 * 1.7, abs=0.01)


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
