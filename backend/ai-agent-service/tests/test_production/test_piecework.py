"""计件与完工判定测试（app/production/piecework.py，issue #3993，M4-G-1）

issue #4589（用户裁定 2026-09-19）：计件工资 = **报工数量 × 计件单价**，系数不再由下单流程产生
—— 「一分为二」这类特殊选项的 ×1.7 系数已从**新报工**里退场（新实例不带 `factor` 键）。

issue #4604（用户裁定 B：**不追溯**）：**历史实例**仍按**当时快照**的系数继续算（历史仍 1.7×）；
只有新实例（`factor` 缺省）才是 1×。⇒ 本文件两条判据成对：历史面**必须乘**、新面**必须不乘**。
⚠️ #4589 期间「读时不算系数」的效果恰恰是**回溯**（历史金额从 1.7× 掉到 1×）——「落库不动」≠「历史不回溯」。
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


def test_compute_piecework_applies_historical_snapshot_factor():
    """#4604 历史面：实例带**当时快照**的系数（1.7）⇒ 金额 = 数量 × 单价 × 1.7（用户裁定 B 不追溯）。

    红证（main 实测，改前）：实现里已去掉乘系数 ⇒ 韩褶 48 折 × 0.4 = **19.20**，
    而本断言期望 **32.64** ⇒ 逐值红（正好差 1.7 倍）。逐笔、总额、按工序**三条路径**都断言
    —— 本单恢复的就是「逐笔 + 总额」两处公式。
    """
    insts = [{**i, "factor": 1.7} for i in INSTANCES]
    logs = [{"operation": "韩褶-布", "worker": "李红梅", "qty": 48, "qualified_qty": 48, "type": "normal"}]
    r = compute_piecework(insts, logs)
    assert r["per_worker"]["李红梅"] == pytest.approx(48 * 0.4 * 1.7, abs=0.01)
    assert r["total"] == pytest.approx(48 * 0.4 * 1.7, abs=0.01)
    per_operation = {row["operation"]: row["amount"] for row in r["per_operation"]}
    assert per_operation["韩褶-布"] == pytest.approx(48 * 0.4 * 1.7, abs=0.01)
    # 判别性：不得是 1 倍（防「把期望值改回不乘」式的假修复）
    assert r["total"] != pytest.approx(48 * 0.4, abs=0.01)


def test_compute_piecework_new_instance_without_factor_key_is_one():
    """#4604 新报工面（**反向护栏**）：新实例（#4589 起不带 `factor` 键）⇒ 系数缺省 1 ⇒ 不乘。

    防「系数又被加回新单」：若实现写成 `inst["factor"]`（无缺省）⇒ KeyError 红；
    若写成「先按选项名反查系数」⇒ 金额会变 32.64 ⇒ 红。
    """
    insts = [{k: v for k, v in i.items() if k != "factor"} for i in INSTANCES]
    logs = [{"operation": "韩褶-布", "worker": "李红梅", "qty": 48, "qualified_qty": 48, "type": "normal"}]
    r = compute_piecework(insts, logs)
    assert r["per_worker"]["李红梅"] == pytest.approx(48 * 0.4, abs=0.01)
    assert r["total"] == pytest.approx(48 * 0.4, abs=0.01)
    per_operation = {row["operation"]: row["amount"] for row in r["per_operation"]}
    assert per_operation["韩褶-布"] == pytest.approx(48 * 0.4, abs=0.01)
    # 判别性：不得是 1.7 倍
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


#: #4961 判别性夹具：`外帘装袋`（**必完**）已报满，`精裁-布`（**非**必完）一行没报。
#: ⚠️ 上面的 `INSTANCES` **不是**判别性夹具：它的必完集合 `{外帘装袋}` ⊆ 实例集合，
#: 且三条既有用例的报工都覆盖了全部实例 ⇒ 新旧口径给**同一个**答案（对本次改判是空断言）。
_NON_MUST_FINISH_UNFINISHED = [
    {"operation": "精裁-布", "unit": "米", "unit_price": 0.4, "qty": 12.3, "is_must_finish": False},
    {"operation": "外帘装袋", "unit": "套", "unit_price": 1.0, "qty": 1, "is_must_finish": True},
]
_ONLY_MUST_FINISH_REPORTED = [
    {"operation": "外帘装袋", "qty": 1, "qualified_qty": 1, "type": "normal"},
]


def test_is_production_done_rejects_unfinished_non_must_finish_operation():
    """🔴 #4961 判别性红证：**非**必完工序未完成 ⇒ 未完工（与 Java `ProductionService` 同口径）。

    用户裁定 2026-09-21：「完工 = **全部工序全绿**」。改前实现只看 `is_must_finish` 工序
    ⇒ 本夹具下**恒 True**（`精裁-布` 的 False 让它被跳过）⇒ 本用例逐值红
    （实测输出 `assert True is False`）。
    """
    assert is_production_done(_NON_MUST_FINISH_UNFINISHED, _ONLY_MUST_FINISH_REPORTED) is False


def test_is_production_done_requires_every_instance_done():
    """#4961 绿侧（新口径的下界）：**全部**实例都报满 ⇒ 完工。

    与上一条成对 ⇒ 「恒 False」的偷懒实现（例如把 `return False` 写死）过不了本用例。
    """
    logs = _ONLY_MUST_FINISH_REPORTED + [
        {"operation": "精裁-布", "qty": 12.3, "qualified_qty": 12.3, "type": "normal"},
    ]
    assert is_production_done(_NON_MUST_FINISH_UNFINISHED, logs) is True


def test_is_production_done_ignores_the_retired_must_finish_key():
    """#4961 反向护栏：实例上**残留**的 `is_must_finish` 键不再有语义（历史载体，恒 false）。

    防「实现又回去读那个键」：把 `外帘装袋` 标成非必完、`精裁-布` 标成必完并报满 ⇒
    若实现按 `is_must_finish` 判，就会返回 True（而正确答案是 False —— `外帘装袋` 没报）。
    本用例因此**双向**可红：读键 ⇒ True（红）；不读键 ⇒ False（绿）。
    """
    flipped = [
        {"operation": "精裁-布", "unit": "米", "unit_price": 0.4, "qty": 12.3, "is_must_finish": True},
        {"operation": "外帘装袋", "unit": "套", "unit_price": 1.0, "qty": 1, "is_must_finish": False},
    ]
    logs = [{"operation": "精裁-布", "qty": 12.3, "qualified_qty": 12.3, "type": "normal"}]
    assert is_production_done(flipped, logs) is False
