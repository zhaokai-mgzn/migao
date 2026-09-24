"""具名跨域视图 `product_health`（商品健康度）—— 视图语义测试（issue #5369，族 3 · 包 2）

判据来源：issue #5369 的五条（逐字段三态 / 「未知」与「0」不混 / 口径同源 / 确定性 / 租户隔离 + 有界）。

本文件盯的是**视图语义**（`app/briefing/product_health.py`），不是数据装配（装配由 admin-api 的
`DailyBriefingServiceTest$SnapshotRows` 钉，快照契约与 族 1 共用 —— 同一内核、两种消费形态）。

为什么每条判据都要有红证（`migao-acceptance`）：断言不会红 = 空断言。本文件里两处关键判据是
**注入式**的 —— 「成本未知不得产出 0 毛利」与「低库存口径与族 1 同源」，注入后同一断言函数必须变红。

case_ids 说明（照实登记）：`DA-016`（行级快照按契约装配 —— 本单扩展了 `skus` 行字段并新增
`product_return_stats` 行数组，判据落在 admin-api 单测）、`DA-017`（逐规则接线状态 / 两种空可分 ——
本视图的逐字段三态同一纪律）、`DA-018`（未接线能力如实说明 —— 本视图的 not_wired/incomplete 披露同一纪律）。
本单**未改** `.github/cases/*.yml`（另一包在跑，避免生成物冲突）⇒ 族 3 包 2 的专属用例条目
由用例库 owner 另批补录，见 PR 的「未固化项」。
"""
# case_ids: DA-016, DA-017, DA-018

import ast

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Dict

import pytest

from app.briefing import product_health as view_module
from app.briefing.proactive import INCOMPLETE, NOT_WIRED, WIRED, scan_snapshot
from app.tools.stock_semantics import LOW_STOCK_OPERATOR, LOW_STOCK_THRESHOLD, STOCK_AUTHORITY

VIEW_SRC = Path(view_module.__file__)
KERNEL_DIR = VIEW_SRC.parent

#: 「商品级派生冗余列」读取点的**豁免台账**（冻结清单 + 燃尽靶，§23 G1/G2）。
#: 现状 = **空**（`app/briefing/**` 尚无任何模块读商品级派生列）⇒ 任何新增读取点**未登记即红**；
#: 台账与命中集合**双向相等**（悬空登记同样红 ⇒ 修好后自动销账，只许缩短）。
DERIVED_COLUMN_LEDGER: Dict[str, str] = {}

#: 「商品级派生冗余列」的机械形态：以**商品级数组/列名**为字符串键去读（权威是 SKU 级，#4038）
_DERIVED_READ_FORMS = ("products", "products_stock", "product_stock")
ASSEMBLER_SRC = (Path(__file__).resolve().parents[3]
                 / "backend/admin-api/src/main/java/com/migao/admin/service/DailyBriefingService.java")
MAPPER_SRC = (Path(__file__).resolve().parents[3]
              / "backend/admin-api/src/main/java/com/migao/admin/mapper/OrderItemMapper.java")

#: 有效订单状态集（口径真值 = `OrderItemMapper.selectProductRanking`：排除 pending 未付款 / cancelled 已取消）
EFFECTIVE_ORDER_STATUSES = frozenset({"confirmed", "producing", "shipped", "completed"})

_SELECT_METHOD_RE = re.compile(
    r"@Select\((?P<sql>.*?)\)\s*\n\s*List<Map<String, Object>>\s+(?P<name>\w+)\(",
    re.S,
)


def _order_status_sets(java_source: str) -> Dict[str, set]:
    """从 mapper 源码里取出「每个分组查询声明的订单状态集」——口径同源的机械读法。"""
    sets: Dict[str, set] = {}
    for match in _SELECT_METHOD_RE.finditer(java_source):
        sets[match.group("name")] = set(re.findall(r"'(\w+)'", match.group("sql")))
    return sets

SKU_FIELDS = ["sku_id", "product_id", "product_name", "stock", "sales_count", "price", "avg_cost"]
RETURN_FIELDS = ["return_no", "customer_id", "product_id", "returned_at", "amount"]
STATS_FIELDS = ["product_id", "return_tickets", "order_lines"]


def _meta(count, truncated=False):
    return {"limit": 500, "count": count, "truncated": truncated}


def snapshot(**overrides):
    """完整快照（逐字 = 装配层契约：`row_fields` 自描述 + `row_meta` 截断显式 + 行数组）。"""
    snap = {
        "biz_date": "2026-09-24",
        "row_fields": {
            "orders": ["order_no", "status", "customer_id", "created_at", "shipped_at", "sale_amount"],
            "skus": list(SKU_FIELDS),
            "returns": list(RETURN_FIELDS),
            "product_return_stats": list(STATS_FIELDS),
        },
        "row_meta": {
            "orders": _meta(1),
            "skus": _meta(3),
            "returns": _meta(2),
            "product_return_stats": _meta(2),
        },
        "skus": [
            # 库存 20.5 ≤ 100 ⇒ 告急；成本已知 ⇒ 毛利 168-100 = 68
            {"sku_id": "S1", "product_id": "P1", "product_name": "雪尼尔-米白",
             "stock": 20.5, "sales_count": 120.0, "price": 168.0, "avg_cost": 100.0},
            # 🔴 成本未知（存量不回填）：avg_cost NULL ⇒ 该行**成本未知**，不得产出 0 毛利
            {"sku_id": "S2", "product_id": "P1", "product_name": "雪尼尔-米白",
             "stock": 0.0, "sales_count": 30.5, "price": 168.0, "avg_cost": None},
            # 库存 900 > 100 ⇒ 不告急；毛利 90-40 = 50
            {"sku_id": "S3", "product_id": "P2", "product_name": "星空全遮光",
             "stock": 900.0, "sales_count": 5.0, "price": 90.0, "avg_cost": 40.0},
        ],
        "returns": [
            {"return_no": "RT-1", "customer_id": "C1", "product_id": "P1",
             "returned_at": "2026-09-22T10:00:00+08:00", "amount": 100.0},
            # 多商品订单：工单归属不到商品（装配层不猜）⇒ 退货率口径**不完整**（如实登记）
            {"return_no": "RT-2", "customer_id": "C2", "product_id": "P2",
             "returned_at": "2026-09-23T10:00:00+08:00", "amount": 50.0},
        ],
        "product_return_stats": [
            {"product_id": "P1", "return_tickets": 1, "order_lines": 4},
            # 订单行 2 条、退货 0 单 ⇒ 退货率**真 0**（有分母才算得出 0）
            {"product_id": "P2", "return_tickets": 0, "order_lines": 2},
        ],
    }
    snap.update(overrides)
    return snap


def unattributed_snapshot():
    """同一夹具 + 一行**归属不到商品**的退货（多商品订单：装配层不猜 ⇒ `product_id` 为 null）"""
    snap = snapshot()
    snap["returns"][1]["product_id"] = None
    return snap


def rows_by_sku(view):
    return {row["sku_id"]: row for row in view["rows"]}


def status_of(view, field):
    return view["fields"][field]["status"]


def assert_unknown_cost_is_not_zero(view):
    """判据 2 的断言函数（**与注入式红证共用**）：未知成本不得产出 0 毛利。"""
    unknown = rows_by_sku(view)["S2"]
    if unknown["gross_margin"] is not None:
        raise AssertionError(
            f"成本未知的 SKU 产出了毛利 {unknown['gross_margin']!r} —— 「未知」被冒充成「0」"
        )
    if unknown["cost_known"] is not False:
        raise AssertionError(f"cost_known 应为 False，实得 {unknown['cost_known']!r}")
    if unknown["avg_cost"] is not None:
        raise AssertionError(f"avg_cost 不应被回填，实得 {unknown['avg_cost']!r}")


class TestFieldStatusIsTriState:
    """判据 1：逐字段三态（`wired` / `not_wired` / `incomplete` + `reason`），不变式 `reason is None ⟺ wired`"""

    def test_all_fields_wired_when_snapshot_complete(self):
        view = view_module.product_health(snapshot(), tenant_id=7)

        assert set(view["fields"]) == {"sales_count", "stock", "gross_margin", "return_rate"}
        assert {f: status_of(view, f) for f in view["fields"]} == {
            "sales_count": WIRED, "stock": WIRED, "gross_margin": WIRED, "return_rate": WIRED,
        }, "完整快照下四个字段都该是 wired（否则「完整」与「不完整」不可分）"

    def test_missing_array_is_not_wired_with_reason(self):
        """装配层没给 `skus` ⇒ 销量/库存/成本毛利三个字段 `not_wired`（不是「都是 0」）"""
        snap = snapshot()
        del snap["skus"]
        del snap["row_fields"]["skus"]

        view = view_module.product_health(snap, tenant_id=7)

        for field in ("sales_count", "stock", "gross_margin"):
            entry = view["fields"][field]
            assert entry["status"] == NOT_WIRED, f"{field} 应为 not_wired，实得 {entry['status']}"
            assert entry["missing"] == ["skus"], entry["missing"]
            assert "skus" in entry["reason"]
        # 退货率不受影响（它的来源是另一对行数组）——部分接线必须逐字段可分
        assert status_of(view, "return_rate") == WIRED

    def test_missing_field_in_declared_array_is_not_wired(self):
        """`row_fields` 声明里没有 `sales_count` ⇒ 该字段 not_wired（声明优先，不靠某行碰巧带上）"""
        snap = snapshot()
        snap["row_fields"]["skus"] = ["sku_id", "product_id", "product_name", "stock",
                                      "price", "avg_cost"]
        snap["row_fields"]["product_return_stats"] = ["product_id", "order_lines"]

        view = view_module.product_health(snap, tenant_id=7)

        assert status_of(view, "sales_count") == NOT_WIRED
        assert view["fields"]["sales_count"]["missing"] == ["sales_count"]
        assert status_of(view, "return_rate") == NOT_WIRED
        assert view["fields"]["return_rate"]["missing"] == ["return_tickets"]
        assert status_of(view, "stock") == WIRED

    def test_truncated_array_is_incomplete_not_wired(self):
        """有界不许变成静默少报：SKU 行被上限截断 ⇒ 结论不完整"""
        snap = snapshot()
        snap["row_meta"]["skus"] = _meta(500, truncated=True)

        view = view_module.product_health(snap, tenant_id=7)

        for field in ("sales_count", "stock", "gross_margin"):
            entry = view["fields"][field]
            assert entry["status"] == INCOMPLETE, f"{field} 应为 incomplete"
            assert "截断" in entry["reason"] and "500" in entry["reason"], entry["reason"]
        assert status_of(view, "return_rate") == WIRED, (
            "退货率的来源是另一对行数组（product_return_stats / returns），SKU 被截断不影响它"
            " —— 逐字段可分正是「部分接线」必须能看见的原因"
        )

    def test_return_rows_without_product_are_incomplete(self):
        """退货行归属不到商品（多商品订单）⇒ 退货率**不完整**（如实登记，不假装全覆盖）"""
        snap = snapshot()
        snap["returns"] = [row for row in snap["returns"] if row["product_id"]]

        view = view_module.product_health(snap, tenant_id=7)

        assert status_of(view, "return_rate") == WIRED, "无归属缺失时不该自称不完整"
        assert status_of(view, "stock") == WIRED

        view_gap = view_module.product_health(unattributed_snapshot(), tenant_id=7)
        entry = view_gap["fields"]["return_rate"]
        assert entry["status"] == INCOMPLETE
        assert "1 行退货" in entry["reason"], entry["reason"]

    def test_view_output_truncation_marks_every_field_incomplete(self):
        """视图自身的有界（`limit`）同样不许静默：输出被截断 ⇒ 每个字段的结论都不完整"""
        view = view_module.product_health(snapshot(), tenant_id=7, limit=1)

        assert view["truncated"] is True
        assert view["count"] == 1
        assert view["rows_total"] == 3
        for field, entry in view["fields"].items():
            assert entry["status"] == INCOMPLETE, f"{field} 输出被截断却仍是 {entry['status']}"
            assert entry["reason"], f"{field} 的 incomplete 必须带原因"

    def test_limit_is_validated(self):
        for bad in (0, -1):
            with pytest.raises(ValueError):
                view_module.product_health(snapshot(), tenant_id=7, limit=bad)

    @pytest.mark.parametrize("case", [
        "complete", "no_skus", "no_stats", "skus_truncated", "stats_truncated",
        "returns_truncated", "return_without_product", "output_truncated",
    ])
    def test_invariant_reason_none_iff_wired(self, case):
        """不变式（一套口径）：`reason is None` ⟺ `status == wired` —— 调用方只看这一条"""
        snap = snapshot()
        kwargs = {}
        if case == "no_skus":
            del snap["skus"], snap["row_fields"]["skus"]
        elif case == "no_stats":
            del snap["product_return_stats"], snap["row_fields"]["product_return_stats"]
        elif case == "skus_truncated":
            snap["row_meta"]["skus"] = _meta(500, truncated=True)
        elif case == "stats_truncated":
            snap["row_meta"]["product_return_stats"] = _meta(500, truncated=True)
        elif case == "returns_truncated":
            snap["row_meta"]["returns"] = _meta(500, truncated=True)
        elif case == "output_truncated":
            kwargs["limit"] = 2
        elif case == "return_without_product":
            snap = unattributed_snapshot()

        view = view_module.product_health(snap, tenant_id=7, **kwargs)

        for field, entry in view["fields"].items():
            wired = entry["status"] == WIRED
            assert (entry["reason"] is None) == wired, (
                f"{case}/{field}: status={entry['status']} reason={entry['reason']!r}"
            )
            assert entry["status"] in (WIRED, NOT_WIRED, INCOMPLETE)


class TestUnknownIsNotZero:
    """判据 2：「未知」与「0」不混（含注入式红证）"""

    def test_unknown_cost_never_becomes_zero_margin(self):
        view = view_module.product_health(snapshot(), tenant_id=7)

        assert_unknown_cost_is_not_zero(view)
        assert rows_by_sku(view)["S2"]["gross_margin"] is None
        # 已知成本的行照常算（判据不能被上一行带偏）
        assert rows_by_sku(view)["S1"]["gross_margin"] == 68.0
        assert rows_by_sku(view)["S3"]["gross_margin"] == 50.0
        assert view["unknown_cost_rows"] == 1, "行级未知要能被计数披露（否则调用方看不见）"

    def test_zero_margin_is_kept_apart_from_unknown_margin(self):
        """售价 = 成本 ⇒ 毛利**真 0**（有真值）；成本未知 ⇒ None —— 两者必须不同"""
        snap = snapshot()
        snap["skus"] = [
            {"sku_id": "S1", "product_id": "P1", "product_name": "A",
             "stock": 5.0, "sales_count": 1.0, "price": 100.0, "avg_cost": 100.0},
            {"sku_id": "S2", "product_id": "P1", "product_name": "A",
             "stock": 5.0, "sales_count": 1.0, "price": 100.0, "avg_cost": None},
        ]

        rows = rows_by_sku(view_module.product_health(snap, tenant_id=7))

        assert rows["S1"]["gross_margin"] == 0.0, "真 0 毛利必须保留"
        assert rows["S1"]["cost_known"] is True
        assert rows["S2"]["gross_margin"] is None, "未知不得被写成 0"
        assert rows["S2"]["cost_known"] is False

    def test_unknown_price_is_unknown_margin_too(self):
        snap = snapshot()
        snap["skus"][0]["price"] = None

        row = rows_by_sku(view_module.product_health(snap, tenant_id=7))["S1"]

        assert row["price"] is None
        assert row["gross_margin"] is None, "缺售价 ⇒ 毛利未知（不得用 0 兜底）"
        assert row["cost_known"] is True

    def test_unknown_stock_is_not_reported_as_not_low(self):
        """库存读不出 ⇒ 告急状态是**未知**（None），不是 False（`False` 会被读成「没问题」）"""
        snap = snapshot()
        snap["skus"][0]["stock"] = None

        row = rows_by_sku(view_module.product_health(snap, tenant_id=7))["S1"]

        assert row["stock"] is None
        assert row["low_stock"] is None, "读不到库存不得判成「不告急」"
        assert rows_by_sku(view_module.product_health(snapshot(), tenant_id=7))["S1"]["low_stock"] is True

    def test_zero_return_rate_is_kept_apart_from_no_denominator(self):
        """退货率：有分母且 0 退货 ⇒ 真 0；无分母 ⇒ 未知（不得倒推 0）"""
        snap = snapshot()
        snap["product_return_stats"] = [
            {"product_id": "P1", "return_tickets": 0, "order_lines": 4},
            {"product_id": "P2", "return_tickets": 1, "order_lines": 0},
        ]
        snap["returns"] = [{"return_no": "RT-1", "customer_id": "C1", "product_id": "P1",
                            "returned_at": "2026-09-22T10:00:00+08:00", "amount": 1.0}]

        rows = rows_by_sku(view_module.product_health(snap, tenant_id=7))

        assert rows["S1"]["return_rate"] == 0.0, "有 4 条订单行、0 退货 ⇒ 真 0"
        assert rows["S3"]["return_rate"] is None, "分母 0 ⇒ 退货率未知，不得写成 0"
        assert rows["S3"]["return_rate_basis"] == "no_order_lines"

    def test_missing_product_stats_row_is_unknown_not_zero(self):
        """商品没有统计行 ⇒ 该行退货率未知（不假装 0 退货）"""
        snap = snapshot()
        snap["product_return_stats"] = [row for row in snap["product_return_stats"]
                                        if row["product_id"] != "P2"]

        row = rows_by_sku(view_module.product_health(snap, tenant_id=7))["S3"]

        assert row["return_rate"] is None
        assert row["return_rate_basis"] == "no_product_stats"

    def test_injected_zero_filling_turns_the_same_assertion_red(self):
        """🔴 注入式红证：把成本未知的毛利改成 0 ⇒ **同一断言函数**必须变红（判据有判别力）"""
        original = view_module._gross_margin
        view_module._gross_margin = (
            lambda price, avg_cost: (price or Decimal(0)) - (avg_cost or Decimal(0))
        )
        try:
            injected = view_module.product_health(snapshot(), tenant_id=7)
            # 先自证注入生效（否则红证会退化成恒绿）：未知成本被当成 0 ⇒ 毛利虚高成售价本身
            assert rows_by_sku(injected)["S2"]["gross_margin"] == 168.0, "注入未生效"
            with pytest.raises(AssertionError):
                assert_unknown_cost_is_not_zero(injected)
        finally:
            view_module._gross_margin = original

        # 还原后判据回到绿（说明变红来自注入，不是夹具本身坏了）
        assert_unknown_cost_is_not_zero(view_module.product_health(snapshot(), tenant_id=7))


class TestSourceOfTruthIsShared:
    """判据 3：口径同源（机械判据，防「同一真值两处投影」）"""

    def test_stock_authority_is_sku_level(self):
        """权威方向显式钉死：商品级派生列（`products.stock` / `products.sales_count`）不作真值来源"""
        assert STOCK_AUTHORITY == "sku"
        assert LOW_STOCK_OPERATOR == "≤"
        view = view_module.product_health(snapshot(), tenant_id=7)
        assert view["basis"]["stock_authority"] == "sku"
        assert view["basis"]["sales_authority"] == "sku"

    def test_low_stock_judgement_equals_family1_rule(self):
        """🔴 机械等价：同一快照下，本视图的「库存告急」SKU 集合 == 族 1 `low_stock` 规则的观测集合

        两入口共用内核 ⇒ 口径一致；视图另写一份阈值/比较时本判据必红。
        """
        snap = snapshot()
        snap["skus"].append({"sku_id": "S4", "product_id": "P2", "product_name": "星空全遮光",
                             "stock": 100.0, "sales_count": 0.0, "price": 10.0, "avg_cost": 5.0})

        view = view_module.product_health(snap, tenant_id=7)
        from_view = sorted(row["sku_id"] for row in view["rows"] if row["low_stock"] is True)

        findings = [f for f in scan_snapshot(snap, as_of="2026-09-24")
                    if f["rule_id"] == "low_stock"]
        assert len(findings) == 1, "族 1 的低库存规则本次应恰好命中一条（夹具自证）"
        from_rule = sorted(o["ref"] for o in findings[0]["criterion"]["observed"])

        # 含上界（≤）：100 也算告急 —— 两侧都必须含 S4
        assert from_view == ["S1", "S2", "S4"], from_view
        assert from_view == from_rule, f"视图 {from_view} != 族 1 规则 {from_rule}"

    def test_injected_own_threshold_turns_equivalence_red(self):
        """🔴 注入式红证：视图自带另一份阈值口径（`< 100`）⇒ 上面那条等价判据必须变红"""
        original = view_module.LOW_STOCK_THRESHOLD
        view_module.LOW_STOCK_THRESHOLD = 99          # 99 ⇒ 100 不再告急（含上界被破坏）
        try:
            snap = snapshot()
            snap["skus"].append({"sku_id": "S4", "product_id": "P2", "product_name": "星空全遮光",
                                 "stock": 100.0, "sales_count": 0.0, "price": 10.0, "avg_cost": 5.0})
            injected = view_module.product_health(snap, tenant_id=7)
            found = sorted(r["sku_id"] for r in injected["rows"] if r["low_stock"] is True)
            assert found == ["S1", "S2"], "注入未生效"
            assert found != ["S1", "S2", "S4"], "注入的口径必须与族 1 不一致（否则红证恒绿）"
        finally:
            view_module.LOW_STOCK_THRESHOLD = original

    def test_kernel_modules_are_registered_before_reading_derived_columns(self):
        """🔴 类级元守卫（§23 G1/G2）：`app/briefing/**` 任一模块读**商品级派生冗余列** ⇒ 必须登记在台账里。

        为什么是**类级**而不是只钉本视图：新视图/新内核模块只要落在这个目录里就自动走这条闸 ——
        「同一真值两处投影」这一类（本单的 库存/销量/成本 权威面）不靠人记得写判据。
        判据形态：未登记即红；**悬空登记也红**（命中数涨跌都红 ⇒ 台账只会缩短）；
        失败信息带**现取**条数与可复制命令。
        """
        offenders = {}
        for path in sorted(KERNEL_DIR.glob("*.py")):
            strings = {node.value for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                       if isinstance(node, ast.Constant) and isinstance(node.value, str)}
            if set(_DERIVED_READ_FORMS) & strings:
                offenders[path.name] = DERIVED_COLUMN_LEDGER.get(path.name, "")

        assert offenders or KERNEL_DIR.exists(), "扫描面为空 ⇒ 判据空转（目录枚举口径坏了）"
        assert sorted(offenders) == sorted(DERIVED_COLUMN_LEDGER), (
            "内核模块读商品级派生列（权威是 SKU 级，#4038）——"
            f"未登记：{sorted(set(offenders) - set(DERIVED_COLUMN_LEDGER))}；"
            f"悬空登记（修好后请销账）：{sorted(set(DERIVED_COLUMN_LEDGER) - set(offenders))}；"
            f"台账现取 {len(DERIVED_COLUMN_LEDGER)} 条"
            "（复算：python3 -m pytest tests/test_briefing_product_health.py -q -k registered）"
        )

    def test_order_line_count_query_shares_the_ranking_status_set(self):
        """Java 侧口径同源：退货率分母的有效订单状态集 == 销量排行查询的状态集（**两处一份口径**）

        `OrderItemMapper` 里两条分组 SQL 各写一份状态集 ⇒「有效订单」这个判据就有了两个投影；
        本守卫机械比对（改任一处 ⇒ 必红）。真值 = `selectProductRanking` 的 #2984 口径。
        """
        sets = _order_status_sets(MAPPER_SRC.read_text(encoding="utf-8"))

        assert sets["selectProductRanking"] == EFFECTIVE_ORDER_STATUSES
        assert sets["selectProductOrderLineCounts"] == EFFECTIVE_ORDER_STATUSES, (
            "退货率分母的状态集与销量排行不一致 ⇒ 同一口径两处投影"
            "（复算：python3 -m pytest tests/test_briefing_product_health.py -q -k ranking_status）"
        )

    def test_injected_status_drift_turns_the_equivalence_red(self):
        """🔴 注入式红证：把排行查询的状态集改掉（去掉 shipped）⇒ 上面那条同源判据必须变红"""
        java = MAPPER_SRC.read_text(encoding="utf-8")
        mutated = java.replace("'confirmed','producing','shipped','completed'",
                               "'confirmed','producing','completed'", 1)
        assert mutated != java, "注入未生效（夹具匹配不到状态集字面量）"

        sets = _order_status_sets(mutated)
        assert sets["selectProductRanking"] != sets["selectProductOrderLineCounts"], (
            "注入后两侧仍然相同 ⇒ 该判据没有判别力"
        )

    def test_view_module_has_no_second_projection(self):
        """AST 硬守卫：视图模块不得自带第二份口径（裸阈值 / 商品级派生列 / 自算销量成本）"""
        tree = ast.parse(VIEW_SRC.read_text(encoding="utf-8"))

        literals = [node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
                    and not isinstance(node.value, bool)]
        assert LOW_STOCK_THRESHOLD not in literals, (
            f"视图里出现裸阈值字面量 {LOW_STOCK_THRESHOLD} —— 低库存口径必须来自 stock_semantics"
        )
        strings = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                   and isinstance(node.value, str)}
        assert "products" not in strings, "视图不得读商品级派生数组（权威是 product_skus 级）"
        for forbidden in ("product_stock", "products_stock"):
            assert forbidden not in strings, f"视图出现商品级派生列引用：{forbidden}"

    def test_view_uses_kernel_helpers_not_a_copy(self):
        """口径同源的另一半：三态驱动复用内核（`proactive` 的声明/元信息读取），不复制一份"""
        src = VIEW_SRC.read_text(encoding="utf-8")
        assert "from app.briefing.proactive import" in src
        for helper in ("_declared_fields", "_row_meta", "_rows"):
            assert helper in src, f"未复用内核读取器 {helper}"

    def test_attention_gap_helpers_match_assembler_contract(self):
        """契约里的技术字面量不许凭语义推测（§17.3）：视图需要的行字段必须真的在装配层声明里"""
        java = ASSEMBLER_SRC.read_text(encoding="utf-8")
        declared = {}
        for array, body in re.findall(r'fields\.put\("(\w+)",\s*List\.of\(([^)]*)\)\)', java):
            declared[array] = set(re.findall(r'"(\w+)"', body))

        for array, needed in view_module.REQUIRED_ROW_FIELDS.items():
            assert array in declared, f"装配层没有声明行数组 {array}（视图会永远 not_wired）"
            missing = sorted(set(needed) - declared[array])
            assert not missing, f"{array} 声明里缺 {missing}（装配层实得 {sorted(declared[array])}）"


class TestDeterminismAndIsolation:
    """判据 4 + 判据 5：确定性（同一快照 ⇒ 同一输出）+ 租户隔离 + 有界行数"""

    def test_same_snapshot_same_output(self):
        first = json.dumps(view_module.product_health(snapshot(), tenant_id=7),
                           sort_keys=True, ensure_ascii=False)
        second = json.dumps(view_module.product_health(snapshot(), tenant_id=7),
                            sort_keys=True, ensure_ascii=False)

        assert first == second

    def test_row_order_does_not_change_output(self):
        """确定性来自内容而非输入顺序（打乱行序 ⇒ 逐字相同）"""
        base = view_module.product_health(snapshot(), tenant_id=7)

        snap = snapshot()
        for key in ("skus", "returns", "product_return_stats"):
            snap[key] = list(reversed(snap[key]))

        assert json.dumps(view_module.product_health(snap, tenant_id=7), sort_keys=True,
                          ensure_ascii=False) == json.dumps(base, sort_keys=True,
                                                            ensure_ascii=False)

    def test_module_reads_no_clock_and_no_randomness(self):
        """确定性不许靠挂钟/随机（挂钟一进来，「同一快照同一输出」当场失效）"""
        src = VIEW_SRC.read_text(encoding="utf-8")
        for forbidden in ("datetime.now", "date.today", "time.time", "random.", "uuid"):
            assert forbidden not in src, f"视图模块出现非确定来源：{forbidden}"

    def test_tenant_is_echoed_and_not_guessed_from_rows(self):
        """租户隔离：租户来自调用方（不由行数据反推）；行里塞 tenant 字段也改不了输出"""
        view = view_module.product_health(snapshot(), tenant_id=42)

        assert view["tenant_id"] == 42
        snap = snapshot()
        for row in snap["skus"]:
            row["tenant_id"] = 999
        assert view_module.product_health(snap, tenant_id=42)["tenant_id"] == 42

    def test_rows_are_bounded_by_default(self):
        """有界是硬前提（热路径）：默认上限存在，且不随快照行数增长"""
        snap = snapshot()
        snap["skus"] = [
            {"sku_id": f"S{i}", "product_id": f"P{i}", "product_name": "X",
             "stock": 1.0, "sales_count": 1.0, "price": 10.0, "avg_cost": 5.0}
            for i in range(view_module.MAX_VIEW_ROWS + 50)
        ]

        view = view_module.product_health(snap, tenant_id=7)

        assert view["count"] == view_module.MAX_VIEW_ROWS
        assert view["truncated"] is True
        assert view["rows_total"] == view_module.MAX_VIEW_ROWS + 50

    def test_non_dict_snapshot_is_not_wired_not_crash(self):
        """快照缺失（老调用方/未接线）⇒ 全部字段 not_wired，不抛异常"""
        view = view_module.product_health(None, tenant_id=7)

        assert view["rows"] == []
        for entry in view["fields"].values():
            assert entry["status"] == NOT_WIRED
            assert entry["reason"]


class TestRowShape:
    """行级契约：字段名逐字（跨端消费）—— 与装配层行键同源"""

    def test_row_carries_single_source_columns(self):
        row = rows_by_sku(view_module.product_health(snapshot(), tenant_id=7))["S1"]

        assert row["sku_id"] == "S1"
        assert row["product_id"] == "P1"
        assert row["product_name"] == "雪尼尔-米白"
        assert row["stock"] == 20.5, "库存 0.1 米粒度不得丢位数（#5063）"
        assert row["sales_count"] == 120.0
        assert row["price"] == 168.0
        assert row["avg_cost"] == 100.0
        assert row["return_tickets"] == 1
        assert row["order_lines"] == 4
        assert row["return_rate"] == 0.25

    def test_unattributed_returns_are_counted_for_disclosure(self):
        assert view_module.product_health(snapshot(), tenant_id=7)["unattributed_returns"] == 0
        view = view_module.product_health(unattributed_snapshot(), tenant_id=7)

        assert view["unattributed_returns"] == 1, "归属不到的退货行要能被披露（否则退货率静默偏低）"

    def test_view_id_is_stable(self):
        assert view_module.product_health(snapshot(), tenant_id=7)["view"] == "product_health"

    def test_all_values_are_json_native(self):
        """视图输出要能直接进 LLM 上下文/JSONB：不得混入 Decimal / date 对象"""
        view = view_module.product_health(snapshot(), tenant_id=7)
        text = json.dumps(view, ensure_ascii=False)      # Decimal / date 会当场抛
        assert '"gross_margin": 68.0' in text
        assert '"return_rate": 0.25' in text