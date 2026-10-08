# case_ids: PG-068
"""具名跨域视图 `delivery_risk`（生产交付风险）—— 视图语义测试（issue #6217，族 3 · 包 4 / V2）

判据来源：issue #6217 的六条口径（逐字段三态 / 「未知」≠「0」/ 数据面确定性 / 只读 + 权限逐字对齐 /
不并进简报表快照 / 声明点登记）。本文件盯**视图语义**（`app/briefing/delivery_risk.py`）：
逐字段三态、null ≠ 0、跨单聚合（卡点 Top）、fail-closed 可归因、注入式红证。

## 本单与本屏既有能力的**分野**（为什么值得单开一个视图）

生产页是**单任务视图**（一次一张加工单）⇒ 结构上答不出「哪些单快到交期还卡着工序」
「卡在哪个工序最多」。后者需要**跨单聚合** —— 本文件的 `TestStuckAggregation` 就是它的判据。

## 最容易做错的一条：**把「没填交期」读成「今天到期」**

`expected_delivery_date` 为空是**未知**，不是 `0 天`（那会把没填交期的单排进最紧急的一批，
把真正快到期的单挤下去）。同理「工序进度没取到」不是「没有卡着的工序」——
前者是 `None` + `unwired`，后者是 `[]`。⇒ `TestUnknownIsNotNullZero` 与它的注入式红证是承重判据。

case_ids 说明（照实登记）：`PG-068` = 本视图的**专属**用例条目（同批登记进
`.github/cases/processing-order.yml`）—— 逐字段三态 / 「未知」≠「0」/ 跨单聚合 / 注入式红证；
工具面（action 白名单 / 端点字面量 / 披露纪律）见 `tests/test_tools_processing_order_query.py`
的 `TestDeliveryRiskAction`，它同样声明 `PG-068`。
"""

from __future__ import annotations

import ast
import datetime as _dt
import json
from pathlib import Path

import pytest

from app.briefing import delivery_risk as view_module
from app.briefing.proactive import INCOMPLETE, NOT_WIRED, WIRED

VIEW_SRC = Path(view_module.__file__)
AS_OF = _dt.date(2026, 10, 3)

ORDER_FIELDS = ("processing_order_no", "order_no", "customer_name", "processor",
                "expected_delivery_date", "status")
PROGRESS_FIELDS = ("order_no", "expected_delivery_date", "current_operation",
                   "pending_operations", "total_operations", "done_operations",
                   "progress_percent")


def snapshot(*, orders=None, progress=None, progress_truncated=False) -> dict:
    """装配层形态的快照（形态 = 工具层 `_assemble` 的产出）。"""
    return {
        "row_fields": {
            "processing_orders": list(ORDER_FIELDS),
            "production_progress": list(PROGRESS_FIELDS),
        },
        "row_meta": {
            "processing_orders": {"limit": 101, "count": len(orders or []), "truncated": False},
            "production_progress": {"limit": 51, "count": len(progress or []),
                                    "truncated": progress_truncated},
        },
        "processing_orders": list(orders or []),
        "production_progress": list(progress or []),
    }


def order(no="JG-1", *, order_no="ORD-1", days=None, **extra) -> dict:
    row = {"processing_order_no": no, "order_no": order_no, "customer_name": "张三",
           "processor": "李师傅", "status": "in_processing",
           "expected_delivery_date": None if days is None
           else (AS_OF + _dt.timedelta(days=days)).isoformat()}
    row.update(extra)
    return row


def progress(order_no="ORD-1", *, pending=None, current=None, total=10, done=4, days=None) -> dict:
    return {"order_no": order_no,
            "expected_delivery_date": None if days is None
            else (AS_OF + _dt.timedelta(days=days)).isoformat(),
            "current_operation": current,
            "pending_operations": list(pending) if pending is not None else None,
            "total_operations": total, "done_operations": done,
            "progress_percent": None}


# ══════════════════════════════════════════════════════════════════════════════
# 一、逐字段三态（判据 1）
# ══════════════════════════════════════════════════════════════════════════════


class TestFieldStatusIsTriState:
    def test_all_declared_fields_are_classified(self):
        status = view_module.field_status(snapshot())

        assert set(status) == set(view_module.FIELD_SOURCES)
        for name, entry in status.items():
            assert entry["status"] in (WIRED, NOT_WIRED, INCOMPLETE), name

    def test_no_truth_fields_are_not_wired_with_named_reason(self):
        status = view_module.field_status(snapshot())

        for name in view_module.NO_TRUTH_REASONS:
            assert status[name]["status"] == NOT_WIRED, name
            assert status[name]["truth"] == view_module.NO_TRUTH
            assert "既有只读端点无此来源" in status[name]["reason"], name

    def test_missing_array_is_not_wired_with_reason(self):
        snap = snapshot()
        del snap["row_fields"]["production_progress"]
        del snap["production_progress"]

        entry = view_module.field_status(snap)["stuck_operation"]

        assert entry["status"] == NOT_WIRED
        assert entry["missing"] == ["production_progress"]
        assert "未提供 production_progress 行数组" in entry["reason"]

    def test_missing_column_in_declared_array_is_not_wired(self):
        snap = snapshot()
        snap["row_fields"]["production_progress"] = [
            name for name in PROGRESS_FIELDS if name != "pending_operations"]

        entry = view_module.field_status(snap)["stuck_operation"]

        assert entry["status"] == NOT_WIRED
        assert entry["missing"] == ["pending_operations"]

    def test_invariant_reason_none_iff_wired(self):
        for snap in (snapshot(orders=[order(days=5)], progress=[progress(days=5)]),
                     snapshot(), None, {"row_fields": {"processing_orders": list(ORDER_FIELDS)}}):
            for name, entry in view_module.field_status(snap).items():
                assert (entry["reason"] is None) == (entry["status"] == WIRED), (snap, name)

    def test_missing_progress_for_some_orders_is_incomplete(self):
        """少数单没取到逐单进度 ⇒ 相关字段**不完整**（不得读成「这些单没有卡点」）"""
        snap = snapshot(orders=[order("JG-1"), order("JG-2", order_no="ORD-2")],
                        progress=[progress("ORD-1", pending=["裁剪"], days=5)])

        entry = view_module.field_status(snap)["stuck_operation"]

        assert entry["status"] == INCOMPLETE
        assert "没有逐单工序进度" in entry["reason"]

    def test_blank_deadline_makes_deadline_field_incomplete(self):
        snap = snapshot(orders=[order(days=None)], progress=[progress(days=None)])

        entry = view_module.field_status(snap)["expected_delivery_date"]

        assert entry["status"] == INCOMPLETE
        assert "没有交期" in entry["reason"]

    def test_truncated_progress_array_is_incomplete_not_wired(self):
        snap = snapshot(orders=[order(days=5)], progress=[progress(days=5)],
                        progress_truncated=True)

        entry = view_module.field_status(snap)["stuck_operation"]

        assert entry["status"] == INCOMPLETE
        assert "截断" in entry["reason"]

    def test_missing_snapshot_is_not_wired_not_crash(self):
        status = view_module.field_status(None)

        assert status
        for name, entry in status.items():
            if entry["truth"] == view_module.NO_TRUTH:
                continue
            assert entry["status"] == NOT_WIRED, name
            assert entry["reason"]


# ══════════════════════════════════════════════════════════════════════════════
# 二、「未知」不等于 0（核心口径 + 注入式红证）
# ══════════════════════════════════════════════════════════════════════════════


class TestUnknownIsNotNullZero:
    def test_order_without_deadline_is_unknown_not_today(self):
        view = view_module.delivery_risk(snapshot(orders=[order(days=None)]), tenant_id=7,
                                         as_of=AS_OF)

        row = view["rows"][0]
        assert row["expected_delivery_date"] is None
        assert row["days_to_deadline"] is None, "没填交期 ⇒ **未知**，不得回填 0（0 = 今天到期）"
        assert row["risk_band"] == "unknown", "未知 ≠ 不紧急"
        assert "expected_delivery_date" in row["unwired"]

    def test_order_without_progress_is_unknown_not_empty_pending(self):
        """🔴 「这一单没取到进度」的**两种形态**都必须落「未知」，都**不得**填 `[]`：

        ① 该单在 `production_progress` 里**整行缺席**（逐单取数没取到，被上限截断）；
        ② 该单的进度行**在场但缺 `pending_operations` 键**（端点契约漂移 / 部分响应）。

        ② 是注入式红证的**唯一可注入面**（`_pending` 只在进度行在场时才被调用）——
        首版夹具只写了 ①，注入「`None` → `[]`」后 46 passed 全绿（判据是空断言）。
        """
        absent = view_module.delivery_risk(snapshot(orders=[order(days=5)]), tenant_id=7, as_of=AS_OF)
        drifted = view_module.delivery_risk(
            snapshot(orders=[order(days=5)],
                     progress=[{"order_no": "ORD-1", "expected_delivery_date": "2026-10-08"}]),
            tenant_id=7, as_of=AS_OF)

        for view in (absent, drifted):
            row = view["rows"][0]
            assert row["pending_operations"] is None, "没取到进度 ⇒ 未知，不得填 []（[] = 没有卡点）"
            assert row["pending_count"] is None
            assert row["stuck_operation"] is None
            assert set(row["unwired"]) >= {"stuck_operation", "pending_operations"}

    def test_real_zero_pending_is_kept_apart_from_unknown(self):
        """待完工序 **真 0 道**（工序全完成）与「没取到进度」必须可分"""
        snap = snapshot(orders=[order(days=5)], progress=[progress(pending=[], days=5)])

        row = view_module.delivery_risk(snap, tenant_id=7, as_of=AS_OF)["rows"][0]

        assert row["pending_operations"] == []
        assert row["pending_count"] == 0
        assert row["unwired"] == []

    def test_days_to_deadline_is_negative_when_overdue(self):
        snap = snapshot(orders=[order(days=-4)], progress=[progress(pending=["印花"], days=-4)])

        row = view_module.delivery_risk(snap, tenant_id=7, as_of=AS_OF)["rows"][0]

        assert row["days_to_deadline"] == -4
        assert row["risk_band"] == "overdue"

    def test_progress_percent_falls_back_to_done_over_total(self):
        """端点给 `progress_percent` 就用它；没给则用 done/total 算（**同口径**，不猜 0%）"""
        snap = snapshot(orders=[order(days=5)],
                        progress=[dict(progress(pending=["裁剪"], total=10, done=3),
                                       progress_percent=30.0)])

        assert view_module.delivery_risk(snap, tenant_id=7, as_of=AS_OF)["rows"][0][
            "progress_percent"] == 30.0

        snap2 = snapshot(orders=[order(days=5)],
                         progress=[progress(pending=["裁剪"], total=4, done=1)])
        assert view_module.delivery_risk(snap2, tenant_id=7, as_of=AS_OF)["rows"][0][
            "progress_percent"] == 25.0

    def test_progress_percent_unknown_when_no_denominator(self):
        snap = snapshot(orders=[order(days=5)],
                        progress=[dict(progress(pending=["裁剪"]), total_operations=0,
                                       done_operations=0)])

        row = view_module.delivery_risk(snap, tenant_id=7, as_of=AS_OF)["rows"][0]

        assert row["progress_percent"] is None, "没有总工序数 ⇒ 进度**未知**（不得折算成 0%）"
        assert "progress_percent" in row["unwired"]

    def test_injected_zero_filling_turns_the_same_assertion_red(self, monkeypatch):
        """🔴 注入式红证（§23 G7）：把「交期未知」填成 0 天 ⇒ 同一断言必须变红。"""
        assert self._row()["days_to_deadline"] is None  # 注入前：绿

        original = view_module._row

        def zero_filled(order_row, progress_row, **kwargs):
            row = original(order_row, progress_row, **kwargs)
            if row["days_to_deadline"] is None:
                row["days_to_deadline"] = 0
                row["risk_band"] = view_module._band(0)
            return row

        monkeypatch.setattr(view_module, "_row", zero_filled)
        injected = self._row()
        monkeypatch.undo()

        assert injected["days_to_deadline"] == 0, "注入未生效（本红证会变成空断言）"
        assert injected["risk_band"] == "critical"
        assert injected["risk_band"] != self._row()["risk_band"], (
            "交期未知被填成 0 天后，分层必须变（否则「未知≠今天到期」这条是空断言）")

    def _row(self) -> dict:
        return view_module.delivery_risk(snapshot(orders=[order(days=None)]), tenant_id=7,
                                         as_of=AS_OF)["rows"][0]


# ══════════════════════════════════════════════════════════════════════════════
# 三、跨单聚合：卡在哪个工序最多（本视图存在的理由）
# ══════════════════════════════════════════════════════════════════════════════


class TestStuckAggregation:
    def test_stuck_top_ranks_operations_by_order_count(self):
        snap = snapshot(
            orders=[order("JG-1", order_no="O1"), order("JG-2", order_no="O2"),
                    order("JG-3", order_no="O3")],
            progress=[progress("O1", current="裁剪", pending=["裁剪"], days=2),
                      progress("O2", pending=["裁剪"], days=-1),
                      progress("O3", pending=["缝制"], days=9)],
        )

        view = view_module.delivery_risk(snap, tenant_id=7, as_of=AS_OF)

        top = {item["operation"]: item["order_count"] for item in view["stuck_top"]}
        assert top == {"裁剪": 2, "缝制": 1}
        assert view["stuck_top"][0] == {"operation": "裁剪", "order_count": 2}
        assert any(row["stuck_operation"] == "缝制" for row in view["rows"])

    def test_stuck_top_ignores_unknown_rows(self):
        """**未知不参与聚合**（否则「没取到进度」会被算成「不卡」或算到某个工序头上）"""
        snap = snapshot(orders=[order("JG-1", order_no="O1"), order("JG-2", order_no="O2")],
                        progress=[progress("O1", pending=["裁剪"], days=2)])

        view = view_module.delivery_risk(snap, tenant_id=7, as_of=AS_OF)

        assert view["stuck_top"] == [{"operation": "裁剪", "order_count": 1}]
        assert view["missing_progress"] == 1

    def test_stuck_top_uses_all_rows_not_the_truncated_page(self):
        """聚合用**全量**行 —— 否则「卡在哪个工序最多」会随视图行数上限变化"""
        rows, progress_rows = [], []
        for index in range(60):
            rows.append(order(f"JG-{index}", order_no=f"O{index}"))
            progress_rows.append(progress(f"O{index}",
                                          pending=["印花"] if index == 59 else ["裁剪"],
                                          days=index))
        snap = snapshot(orders=rows, progress=progress_rows)

        view = view_module.delivery_risk(snap, tenant_id=7, as_of=AS_OF, limit=10)

        assert view["count"] == 10
        assert view["truncated"] is True
        assert view["stuck_top"][0] == {"operation": "裁剪", "order_count": 59}, (
            "第 60 张单卡在「印花」—— 若聚合只看前 10 行，这里会是 10")

    def test_falls_back_to_first_pending_operation_when_current_is_absent(self):
        snap = snapshot(orders=[order(days=3)], progress=[progress(pending=["裁剪", "缝制"],
                                                                   current=None, days=3)])

        assert view_module.delivery_risk(snap, tenant_id=7, as_of=AS_OF)["rows"][0][
            "stuck_operation"] == "裁剪"

    def test_empty_aggregate_when_every_row_is_unknown(self):
        view = view_module.delivery_risk(snapshot(orders=[order(days=5)]), tenant_id=7, as_of=AS_OF)

        assert view["stuck_top"] == [], "全是未知 ⇒ 聚合为空（不是「没有卡点」的结论）"


# ══════════════════════════════════════════════════════════════════════════════
# 四、口径同源 + 确定性 / 有界 / 租户 / fail-closed
# ══════════════════════════════════════════════════════════════════════════════


class TestSourceOfTruthIsSingle:
    def test_every_row_key_read_is_declared(self):
        """机械判据：视图模块读的每一个行键都必须在 `FIELD_SOURCES` 里声明过。"""
        tree = ast.parse(VIEW_SRC.read_text(encoding="utf8"))
        declared = {name for _array, needed in view_module.FIELD_SOURCES.values() for name in needed}

        read_keys = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "get" or len(node.args) != 1:
                continue
            name = getattr(func.value, "id", None) or getattr(func.value, "attr", None)
            value = node.args[0]
            if name in ("row", "entry", "order", "progress") \
                    and isinstance(value, ast.Constant) and isinstance(value.value, str):
                read_keys.add(value.value)

        assert read_keys, "判据会空跑：一个行键都没扫到（形态漂移 ⇒ 去改本判据）"
        assert read_keys - declared == set(), f"这些行键被读了却没声明来源：{sorted(read_keys - declared)}"

    def test_view_uses_kernel_helpers_not_a_copy(self):
        src = VIEW_SRC.read_text(encoding="utf8")

        assert "from app.briefing.proactive import" in src
        for helper in ("_declared_fields", "_rows", "_row_meta", "INCOMPLETE", "NOT_WIRED", "WIRED"):
            assert helper in src, helper

    def test_injected_removal_of_declaration_turns_the_same_assertion_red(self, monkeypatch):
        """🔴 注入式红证：把某字段的真值来源摘掉 ⇒ `field_status` 必须变红。"""
        assert view_module.field_status(snapshot())["stuck_operation"]["status"] == WIRED

        monkeypatch.setitem(view_module.FIELD_SOURCES, "stuck_operation", ("nope", ("order_no",)))
        injected = view_module.field_status(snapshot())
        monkeypatch.undo()

        assert injected["stuck_operation"]["status"] == NOT_WIRED
        assert "nope" in injected["stuck_operation"]["reason"]

    def test_deleting_a_declared_no_truth_entry_turns_the_same_assertion_red(self, monkeypatch):
        """🔴 注入式红证：删掉「声明无真值」的条目 ⇒ 该字段不再被具名披露（本判据必红）。"""
        assert view_module.field_status(snapshot())[
            "scheduled_delivery_date"]["truth"] == view_module.NO_TRUTH

        monkeypatch.delitem(view_module.NO_TRUTH_REASONS, "scheduled_delivery_date")
        result = view_module.delivery_risk(snapshot(orders=[order(days=5)]), tenant_id=7, as_of=AS_OF)
        monkeypatch.undo()

        assert "scheduled_delivery_date" not in result["no_truth_fields"]


class TestDeterminismAndBoundedness:
    def test_same_snapshot_same_output(self):
        snap = snapshot(orders=[order(days=2), order("JG-2", order_no="O2", days=-1)],
                        progress=[progress(days=2), progress("O2", pending=["裁剪"], days=-1)])

        first = json.dumps(view_module.delivery_risk(snap, tenant_id=7, as_of=AS_OF),
                           sort_keys=True, ensure_ascii=False)
        second = json.dumps(view_module.delivery_risk(snap, tenant_id=7, as_of=AS_OF),
                            sort_keys=True, ensure_ascii=False)

        assert first == second

    def test_row_order_does_not_change_output(self):
        snap = snapshot(orders=[order(days=2), order("JG-2", order_no="O2", days=-1)],
                        progress=[progress(days=2), progress("O2", pending=["裁剪"], days=-1)])
        base = json.dumps(view_module.delivery_risk(snap, tenant_id=7, as_of=AS_OF),
                          sort_keys=True, ensure_ascii=False)
        snap["processing_orders"] = list(reversed(snap["processing_orders"]))
        snap["production_progress"] = list(reversed(snap["production_progress"]))

        assert json.dumps(view_module.delivery_risk(snap, tenant_id=7, as_of=AS_OF),
                          sort_keys=True, ensure_ascii=False) == base

    def test_module_reads_no_clock_and_no_randomness(self):
        src = VIEW_SRC.read_text(encoding="utf8")

        for forbidden in ("datetime.now", "date.today", "time.time", "random.", "uuid"):
            assert forbidden not in src, f"视图模块出现非确定来源：{forbidden}"

    def test_tenant_is_echoed_and_not_guessed_from_rows(self):
        snap = snapshot(orders=[dict(order(days=2), tenant_id=999)], progress=[progress(days=2)])

        view = view_module.delivery_risk(snap, tenant_id=42, as_of=AS_OF)

        assert view["tenant_id"] == 42
        assert view["rows"][0]["processing_order_no"] == "JG-1"

    def test_rows_are_bounded_and_truncation_marks_fields_incomplete(self):
        rows = [order(f"JG-{i}", order_no=f"O{i}", days=i % 30) for i in range(
            view_module.MAX_VIEW_ROWS + 3)]

        view = view_module.delivery_risk(snapshot(orders=rows), tenant_id=7, as_of=AS_OF)

        assert view["count"] == view_module.MAX_VIEW_ROWS
        assert view["truncated"] is True
        assert view["rows_total"] == view_module.MAX_VIEW_ROWS + 3
        assert view["fields"]["processing_order_no"]["status"] == INCOMPLETE
        assert view["fields"]["scheduled_delivery_date"]["status"] == NOT_WIRED

    def test_risk_band_ordering_is_disclosed_and_applied(self):
        snap = snapshot(
            orders=[order("JG-1", order_no="O1", days=-1), order("JG-2", order_no="O2", days=2),
                    order("JG-3", order_no="O3", days=20), order("JG-4", order_no="O4", days=None)],
            progress=[progress("O1", pending=["a"], days=-1), progress("O2", pending=["b"], days=2),
                      progress("O3", pending=["c"], days=20)],
        )

        view = view_module.delivery_risk(snap, tenant_id=7, as_of=AS_OF)

        assert [row["risk_band"] for row in view["rows"]] == ["overdue", "critical", "safe", "unknown"]
        assert view["band_counts"]["overdue"] == 1
        assert "row_order" in view["basis"]

    def test_limit_and_as_of_are_validated(self):
        for bad in (0, -1, True, "5"):
            with pytest.raises(ValueError):
                view_module.delivery_risk(snapshot(), tenant_id=7, as_of=AS_OF, limit=bad)
        for bad in (None, "2026-10-03", _dt.datetime(2026, 10, 3)):
            with pytest.raises(ValueError):
                view_module.delivery_risk(snapshot(), tenant_id=7, as_of=bad)

    def test_non_dict_snapshot_is_not_wired_not_crash(self):
        view = view_module.delivery_risk(None, tenant_id=7, as_of=AS_OF)

        assert view["rows"] == []
        assert view["count"] == 0
        assert view["no_truth_fields"]
