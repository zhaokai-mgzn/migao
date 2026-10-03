# case_ids: CU-012
"""具名跨域视图 `customer_value`（客户价值分层 / 流失预警）—— 视图语义测试（issue #6217，族 3 · 包 4）

判据来源：issue #6217 的六条口径（逐字段三态 / 「未知」≠「0」/ 数据面确定性 / 只读 + 权限逐字对齐 /
不并进简报表快照 / 声明点登记）。本文件盯**视图语义**（`app/briefing/customer_value.py`）：
逐字段三态、null ≠ 0、缺声明具名披露、fail-closed 可归因、五种注入式红证。

## 本单最容易做错的一条：**把「未知」写成 0**

跨域视图的解读者是 LLM，而消息是它的**唯一**输入源。若「该客户没有订单行」被算成
`order_count=0` / `days_since_last_order=0` / `total_consumption=0`，模型会把它讲成
「这位客户最近很活跃 / 消费 0 元」—— 前者把**从未下单**的人排到榜尾、后者把**读不出**讲成**真 0**。
⇒ 本文件的 `TestUnknownIsNotNullZero` 与它的注入式红证是本单的承重判据。

case_ids 说明（照实登记）：`CU-012` = 本视图的**专属**用例条目（同批登记进
`.github/cases/customer.yml`）—— 逐字段三态 / 「未知」≠「0」/ 口径同源 / 注入式红证；
工具面（action 白名单 / 端点字面量 / 披露纪律）见 `tests/test_customer_manage.py` 的
`TestCustomerValueAction`，它同样声明 `CU-012`。
"""

from __future__ import annotations

import ast
import datetime as _dt
import json
from pathlib import Path

import pytest

from app.briefing import customer_value as view_module
from app.briefing.proactive import INCOMPLETE, NOT_WIRED, WIRED

VIEW_SRC = Path(view_module.__file__)
AS_OF = _dt.date(2026, 10, 3)

PROFILE_FIELDS = ("customer_id", "name", "phone", "vip_level", "source_channel", "tags")
ORDER_FIELDS = ("order_no", "customer_phone", "created_at", "total_amount", "actual_amount")
TICKET_FIELDS = ("ticket_id", "customer_id", "ticket_type", "created_at")


def snapshot(*, customers=None, orders=None, tickets=None, window_days=90,
             truncated_customers=False) -> dict:
    """装配层形态的快照（形态 = 工具层 `_assemble` 的产出；不复制字段清单的业务含义）。"""
    return {
        "row_fields": {
            "profile": list(PROFILE_FIELDS),
            "orders": list(ORDER_FIELDS),
            "tickets": list(TICKET_FIELDS),
        },
        "row_meta": {
            "profile": {"limit": 51, "count": len(customers or []),
                        "truncated": truncated_customers},
            "orders": {"limit": 201, "count": len(orders or []), "truncated": False},
            "tickets": {"limit": 201, "count": len(tickets or []), "truncated": False},
        },
        "window_days": window_days,
        "profile": list(customers or []),
        "orders": list(orders or []),
        "tickets": list(tickets or []),
    }


def customer(cid="C1", phone="13800000001", **extra) -> dict:
    row = {"customer_id": cid, "name": f"客户{cid}", "phone": phone,
           "vip_level": "vip2", "source_channel": "wechat_mini", "tags": ["活跃"]}
    row.update(extra)
    return row


def order(phone="13800000001", *, days_ago=1, total="100.00", actual="90.00", no="ORD-1") -> dict:
    day = (AS_OF - _dt.timedelta(days=days_ago)).isoformat()
    return {"order_no": no, "customer_phone": phone, "created_at": f"{day}T10:00:00+08:00",
            "total_amount": total, "actual_amount": actual}


def ticket(cid="C1", *, kind="return", tid="T1") -> dict:
    return {"ticket_id": tid, "customer_id": cid, "ticket_type": kind,
            "created_at": f"{AS_OF.isoformat()}T10:00:00+08:00"}


# ══════════════════════════════════════════════════════════════════════════════
# 一、逐字段三态（判据 1）
# ══════════════════════════════════════════════════════════════════════════════


class TestFieldStatusIsTriState:
    def test_all_declared_fields_are_classified(self):
        status = view_module.field_status(snapshot())

        assert set(status) == set(view_module.FIELD_SOURCES), (
            "每个声明字段都必须有状态（漏一个 = 调用方看不见它为什么空）")
        for name, entry in status.items():
            assert entry["status"] in (WIRED, NOT_WIRED, INCOMPLETE), name

    def test_no_truth_fields_are_not_wired_with_named_reason(self):
        status = view_module.field_status(snapshot())

        for name in view_module.NO_TRUTH_REASONS:
            assert status[name]["status"] == NOT_WIRED, name
            assert status[name]["truth"] == view_module.NO_TRUTH
            # 具名披露：说清缺哪个列 / 为什么（不是「未接线」四个字）
            assert "既有只读端点无此来源" in status[name]["reason"], name

    def test_missing_array_is_not_wired_with_reason(self):
        snap = snapshot()
        del snap["row_fields"]["orders"]
        del snap["orders"]

        entry = view_module.field_status(snap)["order_count"]

        assert entry["status"] == NOT_WIRED
        assert entry["missing"] == ["orders"]
        assert "未提供 orders 行数组" in entry["reason"]

    def test_missing_column_in_declared_array_is_not_wired(self):
        snap = snapshot()
        snap["row_fields"]["orders"] = [name for name in ORDER_FIELDS if name != "created_at"]

        entry = view_module.field_status(snap)["days_since_last_order"]

        assert entry["status"] == NOT_WIRED
        assert entry["missing"] == ["created_at"]

    def test_invariant_reason_none_iff_wired(self):
        for snap in (snapshot(customers=[customer()], orders=[order()]),
                     snapshot(), None, {"row_fields": {"profile": list(PROFILE_FIELDS)}}):
            for name, entry in view_module.field_status(snap).items():
                assert (entry["reason"] is None) == (entry["status"] == WIRED), (snap, name)

    def test_truncated_input_array_is_incomplete_not_wired(self):
        snap = snapshot(customers=[customer()], orders=[order()], truncated_customers=True)

        entry = view_module.field_status(snap)["name"]

        assert entry["status"] == INCOMPLETE
        assert "截断" in entry["reason"]

    def test_unattributed_orders_make_metrics_incomplete(self):
        """订单行手机号缺失 ⇒ 归并不上 ⇒ 受影响字段**不完整**（不得静默偏低）"""
        snap = snapshot(customers=[customer()], orders=[dict(order(), customer_phone=None)])

        entry = view_module.field_status(snap)["order_count"]

        assert entry["status"] == INCOMPLETE
        assert "无法归属" in entry["reason"]

    def test_unattributed_returns_make_return_rate_incomplete(self):
        snap = snapshot(customers=[customer()], orders=[order()],
                        tickets=[dict(ticket(), customer_id=None)])

        entry = view_module.field_status(snap)["return_rate"]

        assert entry["status"] == INCOMPLETE
        assert "无法归属" in entry["reason"]

    def test_missing_snapshot_is_not_wired_not_crash(self):
        status = view_module.field_status(None)

        assert status, "快照缺失也要给出逐字段状态（fail-closed 的说明面）"
        for name, entry in status.items():
            if entry["truth"] == view_module.NO_TRUTH:
                continue
            assert entry["status"] == NOT_WIRED, name
            assert entry["reason"]


# ══════════════════════════════════════════════════════════════════════════════
# 二、「未知」不等于 0（本单的核心口径 + 注入式红证）
# ══════════════════════════════════════════════════════════════════════════════


class TestUnknownIsNotNullZero:
    def test_customer_without_any_order_is_unknown_not_zero(self):
        view = view_module.customer_value(snapshot(customers=[customer(phone="13800000009")]),
                                         tenant_id=7, as_of=AS_OF)

        row = view["rows"][0]
        assert row["order_count"] is None, "没有订单行 ⇒ 复购**未知**，不得回填 0"
        assert row["days_since_last_order"] is None
        assert row["total_consumption"] is None
        assert row["avg_order_amount"] is None
        assert row["return_rate"] is None
        assert row["risk_band"] == "unknown", "未知 ≠ 活跃（更 ≠ 流失）"
        for key in ("order_count_basis", "days_since_last_order_basis",
                    "total_consumption_basis", "return_rate_basis"):
            assert row[key] in ("no_orders", "no_in_window_orders", "no_order_lines"), key
        assert set(row["outstanding_amount"] for _ in [0]) == {None}

    def test_zero_and_unknown_are_distinguishable_on_the_same_row(self):
        """真 0 与未知**同一行共存且可分**：窗口内 0 单是真 0，退货率未知（无分母）"""
        snap = snapshot(customers=[customer()], orders=[order(days_ago=200)])

        row = view_module.customer_value(snap, tenant_id=7, as_of=AS_OF)["rows"][0]

        assert row["order_count"] == 0, "窗口外有行、窗口内 0 行 = **真 0**"
        assert row["order_count_basis"] == "all_rows_out_of_window"
        assert row["total_consumption"] is None, "窗口内没有订单 ⇒ 消费额**未知**（不是 0 元）"
        assert row["return_rate"] is None, "无分母 ⇒ 未知（不产出 0）"
        assert row["days_since_last_order"] == 200, "间隔是**全量**订单算的"

    def test_real_zero_return_rate_is_kept(self):
        """有分母且 0 退货 ⇒ **真 0**（不是未知）—— 与无分母的未知必须可分"""
        snap = snapshot(customers=[customer()], orders=[order()], tickets=[])

        row = view_module.customer_value(snap, tenant_id=7, as_of=AS_OF)["rows"][0]

        assert row["return_rate"] == 0.0
        assert row["return_rate_basis"] == "return_tickets/order_lines"

    def test_real_zero_discount_is_kept(self):
        """实收 == 总额 ⇒ 让利率**真 0**（有真值时 0 是正确结论）"""
        snap = snapshot(customers=[customer()],
                        orders=[order(total="100.00", actual="100.00")])

        row = view_module.customer_value(snap, tenant_id=7, as_of=AS_OF)["rows"][0]

        assert row["discount_rate"] == 0.0
        assert row["discount_rate_basis"] == "in_window_orders"

    def test_masked_phone_is_not_used_as_a_join_key(self):
        """档案里被打码的手机号**不得**参与归并（拿它去归并 = 把「读不出」当「读到了」）。

        🔴 夹具刻意让打码号经「只留数字」提炼后**恰好等于**订单里的手机号
        （`138****0001` → `1380001`，订单手机号写这个值）—— 这样「忽略打码」的注入
        才会**真的**把这两行归并到一起。若不这样构造，缺陷形态与正确形态输出逐字相同
        ⇒ 本判据是**空断言**（实测踩到：首版夹具用 `1380000001` 做订单号，注入后 30 passed 全绿）。
        """
        snap = snapshot(customers=[customer(phone="138****0001")],
                        orders=[order(phone="1380001", days_ago=3)])

        row = view_module.customer_value(snap, tenant_id=7, as_of=AS_OF)["rows"][0]

        assert row["order_count"] is None, "打码号归并出的「有订单」是假证据（这就是要拦的缺陷）"
        assert row["merged"] is False
        assert row["days_since_last_order_basis"] == "no_orders"

    def test_injected_zero_filling_turns_the_same_assertion_red(self, monkeypatch):
        """🔴 注入式红证（§23 G7）：把「未知」填成 0 ⇒ 同一断言必须变红。"""
        assert self._unknown_row()["order_count"] is None  # 注入前：绿

        def zero_filled(customer, orders, **kwargs):
            row = original(customer, orders, **kwargs)
            for key in ("order_count", "days_since_last_order", "total_consumption",
                        "avg_order_amount", "return_rate"):
                if row[key] is None:
                    row[key] = 0
            return row

        original = view_module._row
        monkeypatch.setattr(view_module, "_row", zero_filled)
        injected = self._unknown_row()
        monkeypatch.undo()

        assert injected["order_count"] == 0, "注入未生效（本红证会变成空断言）"
        assert injected["order_count"] != self._unknown_row()["order_count"], (
            "零回填注入后输出必须与真值不同 —— 否则「未知≠0」这条断言是空断言")

    def _unknown_row(self) -> dict:
        snap = snapshot(customers=[customer(phone="13800000009")])
        return view_module.customer_value(snap, tenant_id=7, as_of=AS_OF)["rows"][0]


# ══════════════════════════════════════════════════════════════════════════════
# 三、口径同源（真值判断只有一份）+ 无第二份投影
# ══════════════════════════════════════════════════════════════════════════════


class TestSourceOfTruthIsSingle:
    def test_field_declaration_is_the_single_ledger(self):
        """每个字段都必须出现在 `FIELD_SOURCES`（漏声明 = 字段凭空出现，没人能查它凭什么有值）"""
        view = view_module.customer_value(snapshot(customers=[customer()], orders=[order()]),
                                         tenant_id=7, as_of=AS_OF)

        row_keys = {key for key in view["rows"][0] if not key.endswith("_basis")}
        undeclared = row_keys - set(view_module.FIELD_SOURCES) - {
            "customer_id", "risk_band", "merged"}
        assert undeclared == set(), f"这些行键没有对应声明：{sorted(undeclared)}"

    def test_every_row_key_read_is_declared(self):
        """机械判据：视图模块**读端点的每一个行键**都必须在 `FIELD_SOURCES` 里声明过。

        （替代「正文里不许出现某几个字符串」那种形态学判据 —— 后者会误伤 `NO_TRUTH_REASONS`
        里**说明缺哪一列**的正常文字。这里判的是真东西：谁读了一个没人担保来源的键。）
        """
        tree = ast.parse(VIEW_SRC.read_text(encoding="utf8"))
        declared = {name for _array, needed in view_module.FIELD_SOURCES.values() for name in needed}

        read_keys = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "get" or len(node.args) != 1:
                continue
            target = func.value
            name = getattr(target, "id", None) or getattr(target, "attr", None)
            value = node.args[0]
            if name in ("row", "entry", "customer", "order", "progress") \
                    and isinstance(value, ast.Constant) and isinstance(value.value, str):
                read_keys.add(value.value)

        undeclared = read_keys - declared - {"pending_operations", "progress_percent",
                                             "total_operations", "done_operations",
                                             "current_operation", "expected_delivery_date"}
        assert read_keys, "判据会空跑：一个行键都没扫到（形态漂移 ⇒ 去改本判据）"
        assert undeclared == set(), f"这些行键被读了却没声明来源：{sorted(undeclared)}"

    def test_view_uses_kernel_helpers_not_a_copy(self):
        """三态词表与内核读取器**同一份**（改词表时两侧一起红 —— 复制一份就漂移了）"""
        src = VIEW_SRC.read_text(encoding="utf8")

        assert "from app.briefing.proactive import" in src
        for helper in ("_declared_fields", "_rows", "_row_meta", "INCOMPLETE", "NOT_WIRED", "WIRED"):
            assert helper in src, helper

    def test_injected_removal_of_declaration_turns_the_same_assertion_red(self, monkeypatch):
        """🔴 注入式红证：把某字段的**真值来源**摘掉 ⇒ `field_status` 必须变红（not_wired）。"""
        assert view_module.field_status(snapshot())["order_count"]["status"] == WIRED

        monkeypatch.setitem(view_module.FIELD_SOURCES, "order_count", ("nope", ("order_no",)))
        injected = view_module.field_status(snapshot())
        monkeypatch.undo()

        assert injected["order_count"]["status"] == NOT_WIRED
        assert "nope" in injected["order_count"]["reason"]

    def test_deleting_a_declared_no_truth_entry_turns_the_same_assertion_red(self, monkeypatch):
        """🔴 注入式红证：把「声明无真值」的条目删掉 ⇒ 该字段不再被具名披露（本判据必红）。"""
        assert view_module.field_status(snapshot())["outstanding_amount"]["truth"] == view_module.NO_TRUTH

        monkeypatch.delitem(view_module.NO_TRUTH_REASONS, "outstanding_amount")
        injected = view_module.field_status(snapshot())
        result = view_module.customer_value(snapshot(customers=[customer()]), tenant_id=7, as_of=AS_OF)
        monkeypatch.undo()

        assert injected["outstanding_amount"]["truth"] == view_module.HAS_TRUTH
        assert "outstanding_amount" not in result["no_truth_fields"]


# ══════════════════════════════════════════════════════════════════════════════
# 四、数据面确定性 / 有界 / 租户 / fail-closed
# ══════════════════════════════════════════════════════════════════════════════


class TestDeterminismAndBoundedness:
    def test_same_snapshot_same_output(self):
        snap = snapshot(customers=[customer(), customer("C2", "13800000002")],
                        orders=[order(), order("13800000002", no="ORD-2")])

        first = json.dumps(view_module.customer_value(snap, tenant_id=7, as_of=AS_OF),
                           sort_keys=True, ensure_ascii=False)
        second = json.dumps(view_module.customer_value(snap, tenant_id=7, as_of=AS_OF),
                            sort_keys=True, ensure_ascii=False)

        assert first == second

    def test_row_order_does_not_change_output(self):
        snap = snapshot(customers=[customer(), customer("C2", "13800000002")],
                        orders=[order(), order("13800000002", no="ORD-2")])
        base = json.dumps(view_module.customer_value(snap, tenant_id=7, as_of=AS_OF),
                          sort_keys=True, ensure_ascii=False)
        snap["profile"] = list(reversed(snap["profile"]))
        snap["orders"] = list(reversed(snap["orders"]))

        assert json.dumps(view_module.customer_value(snap, tenant_id=7, as_of=AS_OF),
                          sort_keys=True, ensure_ascii=False) == base

    def test_module_reads_no_clock_and_no_randomness(self):
        """确定性不许靠挂钟/随机 —— `as_of` 由调用方传入（这是「同一快照同一输出」的前提）"""
        src = VIEW_SRC.read_text(encoding="utf8")

        for forbidden in ("datetime.now", "date.today", "time.time", "random.", "uuid"):
            assert forbidden not in src, f"视图模块出现非确定来源：{forbidden}"

    def test_as_of_is_echoed_and_drives_the_metrics(self):
        snap = snapshot(customers=[customer()], orders=[order(days_ago=10)])

        assert view_module.customer_value(snap, tenant_id=7, as_of=AS_OF)["rows"][0][
            "days_since_last_order"] == 10
        assert view_module.customer_value(snap, tenant_id=7, as_of=AS_OF)["as_of"] == AS_OF.isoformat()

    def test_tenant_is_echoed_and_not_guessed_from_rows(self):
        snap = snapshot(customers=[dict(customer(), tenant_id=999)], orders=[order()])

        view = view_module.customer_value(snap, tenant_id=42, as_of=AS_OF)

        assert view["tenant_id"] == 42
        assert view["rows"][0]["customer_id"] == "C1"

    def test_rows_are_bounded_and_truncation_marks_fields_incomplete(self):
        customers = [customer(f"C{i}", f"1380000{i:04d}") for i in range(view_module.MAX_VIEW_ROWS + 5)]

        view = view_module.customer_value(snapshot(customers=customers), tenant_id=7, as_of=AS_OF)

        assert view["count"] == view_module.MAX_VIEW_ROWS
        assert view["truncated"] is True
        assert view["rows_total"] == view_module.MAX_VIEW_ROWS + 5
        assert view["fields"]["name"]["status"] == INCOMPLETE
        assert "截断" in view["fields"]["name"]["reason"]
        # 无真值字段**不因截断变化**（它本来就没有真值，与行数无关）
        assert view["fields"]["outstanding_amount"]["status"] == NOT_WIRED

    def test_risk_band_ordering_is_disclosed_and_applied(self):
        """行序 = 流失风险降序（本视图的用途就是「谁最值得维护」）"""
        snap = snapshot(
            customers=[customer("C1", "13800000001"), customer("C2", "13800000002"),
                       customer("C3", "13800000003")],
            orders=[order("13800000001", days_ago=1, no="A"),
                    order("13800000002", days_ago=120, no="B")],
        )

        view = view_module.customer_value(snap, tenant_id=7, as_of=AS_OF)

        assert [row["risk_band"] for row in view["rows"]] == ["lost", "active", "unknown"]
        assert view["band_counts"]["lost"] == 1
        assert "row_order" in view["basis"]

    def test_limit_is_validated(self):
        for bad in (0, -1, True, "5"):
            with pytest.raises(ValueError):
                view_module.customer_value(snapshot(), tenant_id=7, as_of=AS_OF, limit=bad)

    def test_as_of_must_be_a_date(self):
        for bad in (None, "2026-10-03", _dt.datetime(2026, 10, 3)):
            with pytest.raises(ValueError):
                view_module.customer_value(snapshot(), tenant_id=7, as_of=bad)

    def test_non_dict_snapshot_is_not_wired_not_crash(self):
        view = view_module.customer_value(None, tenant_id=7, as_of=AS_OF)

        assert view["rows"] == []
        assert view["count"] == 0
        assert view["no_truth_fields"], "声明无真值的字段必须仍被披露（与快照在不在无关）"
