"""
主动发现 · 规则引擎（确定性扫描）测试 —— issue #5322（族 1 · 包 1）

判据来源：`docs/agent-feature-design.md` §三 族 1（PR #5320 入库）。
本文件是 `app/briefing/proactive.py` 的对应单测，逐条覆盖五条可执行验收判据：

1. **确定性**：同一数据快照两次扫描**逐字一致**，且与快照内行序无关（打乱行序 ⇒ 结果不变）；
2. **三件套**：每条命中带 `criterion`（可复算判据）/ `impact`（影响面）/ `action`（一键处置入口）；
3. **无处置入口的条目不发** —— **注入式红证**：把某条规则的处置入口拿掉 ⇒ 该条必不出现，
   而**同一快照上未注入的其它规则必须照常出现**（证明注入的是真候选，不是空跑）；
4. **日报只含当天异常** —— **双侧断言**：历史异常在 `scan_snapshot`（全量）里**在**，
   在 `daily_findings`（日报）里**必不在**（只断言「不在」会让「引擎完全不工作」也变绿）；
5. **阈值可配 + 边界值**：N / N+1、`≤`（含上界）/ `>`、恰等阈值 / 超阈值两侧行为各一条。

⚠️ 这些断言会红吗：改掉任一条规则的判据、去掉 `action` 过滤、让 `daily_findings` 不过日期、
把阈值写死成字面量（不读 `config`）—— 都会红（每条断言盯的都是一个**会变的**真值）。
"""
# case_ids: DA-011, DA-012, DA-013, DA-014, DA-015, DA-017
import copy
import json
import random
from dataclasses import replace

import pytest

from app.briefing.proactive import (
    DEFAULT_CONFIG,
    INCOMPLETE,
    NOT_ENABLED,
    NOT_WIRED,
    RULES,
    WIRED,
    ProactiveConfig,
    daily_findings,
    daily_findings_total,
    proactive_status,
    scan_snapshot,
)

BIZ_DATE = "2026-09-22"

#: 固定数据快照（判据 1 的「给定快照」）。同一份快照同时承载：
#: 当天异常（SO-4 / SO-1 / C-1 / PC-1,PC-4 / SKU-1,SKU-3 / OD-1）与**历史异常**
#: （SO-5 @09-01 / C-7 @09-03 / PC-3 @09-01 / OD-3 @09-05）—— 判据 4 的两侧都取自它。
SNAPSHOT = {
    "biz_date": BIZ_DATE,
    "orders": [
        # 超 N 天未发货：09-12 下单（10 天）⇒ 命中；09-19 下单（恰 N=3 天）⇒ 不命中（边界）
        {"order_no": "SO-1", "status": "confirmed", "customer_id": "C-1",
         "created_at": "2026-09-12T10:00:00+08:00", "shipped_at": None,
         "sale_amount": 1200.0, "cost_amount": 1000.0},
        {"order_no": "SO-2", "status": "confirmed", "customer_id": "C-2",
         "created_at": "2026-09-19T10:00:00+08:00", "shipped_at": None,
         "sale_amount": 800.0, "cost_amount": 700.0},
        # 已发货 ⇒ 不进「未发货」集合
        {"order_no": "SO-3", "status": "shipped", "customer_id": "C-3",
         "created_at": "2026-09-01T10:00:00+08:00", "shipped_at": "2026-09-02T10:00:00+08:00",
         "sale_amount": 500.0, "cost_amount": 400.0},
        # 低于成本价（当天）：700 < 1000，亏损 300
        {"order_no": "SO-4", "status": "confirmed", "customer_id": "C-1",
         "created_at": "2026-09-22T09:00:00+08:00", "shipped_at": None,
         "sale_amount": 700.0, "cost_amount": 1000.0},
        # 低于成本价的**历史**异常（09-01）：亏损 200
        {"order_no": "SO-5", "status": "completed", "customer_id": "C-9",
         "created_at": "2026-09-01T09:00:00+08:00", "shipped_at": "2026-09-02T09:00:00+08:00",
         "sale_amount": 100.0, "cost_amount": 300.0},
    ],
    "skus": [
        # stock == 阈值 ⇒ 命中（含上界，与 low_stock_alert 同口径）；100.1 ⇒ 不命中（边界）
        {"sku_id": "SKU-1", "product_id": "P-1", "product_name": "雪尼尔-米白", "stock": 100.0},
        {"sku_id": "SKU-2", "product_id": "P-2", "product_name": "棉麻-灰", "stock": 100.1},
        {"sku_id": "SKU-3", "product_id": "P-3", "product_name": "绒布-蓝", "stock": 0.0},
    ],
    "returns": [
        # 客户 C-1：09-18 / 09-20 / 09-22 三次（窗口 7 天）⇒ 09-22 命中
        {"return_no": "RT-1", "customer_id": "C-1", "product_id": "P-9",
         "returned_at": "2026-09-18T10:00:00+08:00", "amount": 100.0},
        {"return_no": "RT-2", "customer_id": "C-1", "product_id": "P-9",
         "returned_at": "2026-09-20T10:00:00+08:00", "amount": 120.0},
        {"return_no": "RT-3", "customer_id": "C-1", "product_id": "P-8",
         "returned_at": "2026-09-22T10:00:00+08:00", "amount": 130.0},
        # 客户 C-7：09-01 / 09-02 / 09-03 三次 ⇒ **历史**命中（09-03）
        {"return_no": "RT-4", "customer_id": "C-7", "product_id": "P-7",
         "returned_at": "2026-09-01T10:00:00+08:00", "amount": 50.0},
        {"return_no": "RT-5", "customer_id": "C-7", "product_id": "P-7",
         "returned_at": "2026-09-02T10:00:00+08:00", "amount": 60.0},
        {"return_no": "RT-6", "customer_id": "C-7", "product_id": "P-7",
         "returned_at": "2026-09-03T10:00:00+08:00", "amount": 70.0},
    ],
    "price_changes": [
        # 幅度 40% > 30% ⇒ 命中；恰 30% ⇒ 不命中（边界）
        # ⚠️ 两行都是**改价**：`product_update`（商品级统一定价）与 `sku_update`（单 SKU 调价）
        # —— 只筛前者会**漏一半**（审计日志 tool_name 的两个取值，issue #5388 冻结判据）。
        {"change_no": "PC-1", "tool_name": "product_update", "product_id": "P-1",
         "before_price": 200.0, "new_price": 120.0, "changed_at": "2026-09-22T09:30:00+08:00"},
        {"change_no": "PC-2", "tool_name": "product_update", "product_id": "P-2",
         "before_price": 100.0, "new_price": 70.0, "changed_at": "2026-09-22T09:40:00+08:00"},
        {"change_no": "PC-4", "tool_name": "sku_update", "product_id": "P-1",
         "before_price": 500.0, "new_price": 250.0, "changed_at": "2026-09-22T09:50:00+08:00"},
        # **历史**异常（09-01，幅度 50%）
        {"change_no": "PC-3", "tool_name": "product_update", "product_id": "P-5",
         "before_price": 100.0, "new_price": 50.0, "changed_at": "2026-09-01T09:00:00+08:00"},
    ],
    "order_discounts": [
        # 让利 40% > 30% ⇒ 命中；恰 30% ⇒ 不命中（边界）
        {"order_no": "OD-1", "total_amount": 1000.0, "discount_amount": 400.0,
         "created_at": "2026-09-22T08:00:00+08:00"},
        {"order_no": "OD-2", "total_amount": 1000.0, "discount_amount": 300.0,
         "created_at": "2026-09-22T08:10:00+08:00"},
        # **历史**异常（09-05，让利 50%）—— 「日报只放当天」的另一侧断言
        {"order_no": "OD-3", "total_amount": 1000.0, "discount_amount": 500.0,
         "created_at": "2026-09-05T08:00:00+08:00"},
    ],
}

#: 当天异常（日报）的**逐字**命中集合：按 紧急度 → 规则注册序 排序
EXPECTED_DAILY = [
    ("below_cost_price", BIZ_DATE),
    ("unshipped_overdue", BIZ_DATE),
    ("repeat_returns", BIZ_DATE),
    ("low_stock", BIZ_DATE),
    ("price_change_over", BIZ_DATE),
    ("discount_over", BIZ_DATE),
]

#: 全量扫描（含历史异常）：按 日期倒序 → 紧急度 → 规则注册序
EXPECTED_SCAN = [
    ("below_cost_price", BIZ_DATE),
    ("unshipped_overdue", BIZ_DATE),
    ("repeat_returns", BIZ_DATE),
    ("low_stock", BIZ_DATE),
    ("price_change_over", BIZ_DATE),
    ("discount_over", BIZ_DATE),
    ("discount_over", "2026-09-05"),
    ("repeat_returns", "2026-09-03"),
    ("below_cost_price", "2026-09-01"),
    ("price_change_over", "2026-09-01"),
]

#: 历史异常的四条证据（判据 4 的「必不出现」侧：按 ref 断言，避免只盯日期）
HISTORICAL_REFS = ("SO-5", "C-7", "PC-3", "OD-3")


def _digest(findings):
    """逐字摘要：同一快照两次扫描必须逐字一致（判据 1 的机械判据）。"""
    return json.dumps(findings, ensure_ascii=False, sort_keys=True)


def _by_rule(findings, rule_id):
    hits = [f for f in findings if f["rule_id"] == rule_id]
    assert len(hits) == 1, f"{rule_id} 期望恰好 1 条命中，实得 {len(hits)}"
    return hits[0]


def _refs(finding):
    """一条命中里出现过的全部对象标识（观测值 + 处置入口）。"""
    return json.dumps(finding, ensure_ascii=False)


class TestDeterminism:
    """判据 1：确定性 —— 逐字可复现，不是「AI 觉得异常」"""

    def test_two_scans_are_byte_identical(self):
        assert _digest(scan_snapshot(SNAPSHOT)) == _digest(scan_snapshot(SNAPSHOT))

    def test_scan_is_independent_of_row_order(self):
        """打乱快照内行序 ⇒ 命中集合逐字不变（确定性来自内容，不是输入顺序）"""
        shuffled = copy.deepcopy(SNAPSHOT)
        rng = random.Random(5322)
        for key in ("orders", "skus", "returns", "price_changes"):
            rng.shuffle(shuffled[key])
        assert shuffled != SNAPSHOT, "行序未被打乱 ⇒ 本断言是空跑"
        assert _digest(scan_snapshot(shuffled)) == _digest(scan_snapshot(SNAPSHOT))

    def test_full_scan_hit_set_is_frozen(self):
        """全量命中集合（含历史异常）逐字钉住：规则 id + 命中日期 + 顺序"""
        hits = scan_snapshot(SNAPSHOT)
        assert [(f["rule_id"], f["detected_on"]) for f in hits] == EXPECTED_SCAN

    def test_empty_snapshot_yields_no_findings(self):
        """空快照（backend 未给 sourceSnapshot）⇒ 空集合，不得抛异常"""
        assert scan_snapshot(None) == []
        assert scan_snapshot({}) == []
        assert daily_findings(None) == []


class TestThreePiece:
    """判据 2：每条命中带三件套（判据 / 影响面 / 处置入口）"""

    def test_every_finding_carries_the_three_pieces(self):
        for f in daily_findings(SNAPSHOT):
            criterion, impact, action = f["criterion"], f["impact"], f["action"]
            assert isinstance(criterion["expression"], str) and criterion["expression"]
            assert criterion["thresholds"], f"{f['rule_id']} 判据缺阈值（不可复算）"
            assert criterion["observed"], f"{f['rule_id']} 判据缺观测值（不可复算）"
            assert isinstance(impact["count"], int) and impact["count"] > 0
            assert impact["unit"]
            assert action["label"] and action["url"].startswith("/")

    def test_criterion_observed_is_the_real_offending_rows(self):
        """判据的观测值 = 真命中行（不是「大概识别出异常」）"""
        daily = daily_findings(SNAPSHOT)
        below_cost = _by_rule(daily, "below_cost_price")["criterion"]["observed"]
        assert [r["ref"] for r in below_cost] == ["SO-4"]
        assert below_cost[0]["sale_amount"] == 700.0
        assert below_cost[0]["cost_amount"] == 1000.0

        overdue = _by_rule(daily, "unshipped_overdue")["criterion"]["observed"]
        assert [r["ref"] for r in overdue] == ["SO-1"]      # SO-2 恰 3 天、SO-3 已发货
        assert overdue[0]["days"] == 10

        low = _by_rule(daily, "low_stock")["criterion"]["observed"]
        assert [r["ref"] for r in low] == ["SKU-1", "SKU-3"]  # 含上界 100 命中、100.1 不命中

    def test_impact_carries_count_and_money(self):
        """影响面 = 几条 / 多少钱"""
        daily = daily_findings(SNAPSHOT)
        assert _by_rule(daily, "below_cost_price")["impact"] == {
            "count": 1, "unit": "单", "amount": 300.0, "amount_unit": "元"}
        assert _by_rule(daily, "unshipped_overdue")["impact"]["amount"] == 1200.0
        assert _by_rule(daily, "repeat_returns")["impact"] == {
            "count": 3, "unit": "笔退货", "amount": 350.0, "amount_unit": "元"}
        assert _by_rule(daily, "low_stock")["impact"]["count"] == 2

    def test_every_registered_rule_is_named_and_has_an_action(self):
        """规则注册表自身的不变式：具名 + 唯一 id + 有处置入口"""
        ids = [r.rule_id for r in RULES]
        assert len(ids) == 6
        assert len(set(ids)) == 6
        for spec in RULES:
            assert spec.rule_name
            assert spec.action_url.startswith("/")
            assert spec.action_label


class TestActionGate:
    """判据 3：没有处置入口的不发（注入式红证）"""

    def test_finding_without_action_is_dropped(self):
        """注入：把「库存告急」的处置入口拿掉 ⇒ 该条必不出现"""
        stripped = tuple(
            replace(spec, action_url="", action_label="") if spec.rule_id == "low_stock" else spec
            for spec in RULES
        )
        ids = [f["rule_id"] for f in daily_findings(SNAPSHOT, rules=stripped)]
        assert "low_stock" not in ids

    def test_the_injection_target_is_a_real_candidate(self):
        """同上快照、未注入 ⇒ 该条**必须**出现（否则上一条是空跑：注入的压根不是候选）"""
        assert "low_stock" in [f["rule_id"] for f in daily_findings(SNAPSHOT)]

    def test_other_rules_survive_the_injection(self):
        """注入只影响被注入的那条，不得连带削掉别的命中"""
        stripped = tuple(
            replace(spec, action_url="") if spec.rule_id == "low_stock" else spec
            for spec in RULES
        )
        ids = [f["rule_id"] for f in daily_findings(SNAPSHOT, rules=stripped)]
        assert ids == [r for r, _ in EXPECTED_DAILY if r != "low_stock"]


class TestDailyViewIsNarrow:
    """判据 4：日报只含当天异常（历史异常必须不出现）"""

    def test_daily_findings_are_all_today(self):
        # 当天成立的异常**全集**（把展示上限抬到条数以上 ⇒ 本断言盯的是「当天」而不是「前 N 条」；
        # 默认上限下被截断的那一条由 `test_daily_total_is_not_capped_by_max_findings` 兜住）
        daily = daily_findings(SNAPSHOT, config=ProactiveConfig(max_findings=len(EXPECTED_DAILY)))
        assert [(f["rule_id"], f["detected_on"]) for f in daily] == EXPECTED_DAILY
        assert {f["detected_on"] for f in daily} == {BIZ_DATE}

    def test_historical_anomalies_are_in_the_full_scan(self):
        """「必不出现」侧的前提：历史异常确实被引擎识别到了（否则下一条是空跑）"""
        full = _digest(scan_snapshot(SNAPSHOT))
        for ref in HISTORICAL_REFS:
            assert ref in full, f"历史异常 {ref} 未被引擎识别 ⇒ 判据 4 是空跑"

    def test_historical_anomalies_are_not_in_the_daily_view(self):
        daily = _digest(daily_findings(SNAPSHOT))
        for ref in HISTORICAL_REFS:
            assert ref not in daily, f"历史异常 {ref} 混进了日报"

    def test_as_of_can_be_pinned_by_the_caller(self):
        """扫描基准日可由调用方钉住（简报 bizDate），不依赖机器当前时间"""
        assert [f["detected_on"] for f in daily_findings(SNAPSHOT, as_of="2026-09-03")] == [
            "2026-09-03", "2026-09-03"]

    def test_daily_view_is_capped_by_max_findings(self):
        """日报要窄：条数上限可配，超出时按紧急度截断"""
        narrow = daily_findings(SNAPSHOT, config=ProactiveConfig(max_findings=2))
        assert [f["rule_id"] for f in narrow] == ["below_cost_price", "unshipped_overdue"]


class TestThresholdsAreConfigurable:
    """判据 5：阈值可配，且边界值两侧行为都有断言"""

    def test_defaults_are_the_documented_ones(self):
        assert DEFAULT_CONFIG.unshipped_days == 3
        assert DEFAULT_CONFIG.low_stock_threshold == 100   # 与 low_stock_alert 同源口径
        assert DEFAULT_CONFIG.repeat_return_count == 3
        assert DEFAULT_CONFIG.price_change_pct == 30.0
        assert DEFAULT_CONFIG.discount_pct == 30.0

    def test_unshipped_days_boundary(self):
        """恰 N 天不命中 / N+1 天命中 —— 同一张快照上的两侧断言（SO-2 恰 3 天）"""
        default = _by_rule(daily_findings(SNAPSHOT), "unshipped_overdue")["criterion"]["observed"]
        assert [r["ref"] for r in default] == ["SO-1"]          # SO-2 恰 3 天（= N）⇒ 落在界外
        looser = ProactiveConfig(unshipped_days=2)
        observed = _by_rule(
            daily_findings(SNAPSHOT, config=looser), "unshipped_overdue")["criterion"]["observed"]
        assert [r["ref"] for r in observed] == ["SO-1", "SO-2"]  # 3 天 > 2 ⇒ 进界
        assert [r["days"] for r in observed] == [10, 3]

    def test_low_stock_threshold_is_inclusive_upper_bound(self):
        """口径 = `stock <= threshold`（含上界）：把阈值压到 100 以下 ⇒ 恰 100 的不再命中"""
        strict = ProactiveConfig(low_stock_threshold=99)
        observed = _by_rule(daily_findings(SNAPSHOT, config=strict), "low_stock")["criterion"]["observed"]
        assert [r["ref"] for r in observed] == ["SKU-3"]   # 100.0 落到界外，0.0 仍在界内

    def test_repeat_return_count_boundary(self):
        """N（3 次）命中 / N+1（4 次）不命中"""
        assert _by_rule(daily_findings(SNAPSHOT), "repeat_returns")["impact"]["count"] == 3
        stricter = ProactiveConfig(repeat_return_count=4)
        assert "repeat_returns" not in [f["rule_id"] for f in daily_findings(SNAPSHOT, config=stricter)]

    def test_price_change_pct_boundary(self):
        """恰等阈值（30%）不命中 / 超阈值（40%）命中"""
        observed = _by_rule(daily_findings(SNAPSHOT), "price_change_over")["criterion"]["observed"]
        # PC-1（商品级改价 40%）与 PC-4（单 SKU 改价 50%）都命中；PC-2 恰 30% 落到界外
        assert [r["ref"] for r in observed] == ["PC-1", "PC-4"]
        assert observed[0]["pct"] == 40.0
        assert {r["tool_name"] for r in observed} == {"product_update", "sku_update"}

    def test_thresholds_can_come_from_the_snapshot(self):
        """阈值可随快照下发（租户级配置的落点），显式入参优先"""
        snapshot = dict(SNAPSHOT, config={"low_stock_threshold": 99})
        assert [r["ref"] for r in
                _by_rule(daily_findings(snapshot), "low_stock")["criterion"]["observed"]] == ["SKU-3"]
        forced = daily_findings(snapshot, config=ProactiveConfig(low_stock_threshold=100))
        assert [r["ref"] for r in
                _by_rule(forced, "low_stock")["criterion"]["observed"]] == ["SKU-1", "SKU-3"]

    def test_rejects_nonsense_thresholds(self):
        """阈值非法 ⇒ 抛错（静默接受会让「可配」变成「配了也不生效」）"""
        with pytest.raises(ValueError):
            ProactiveConfig(unshipped_days=0)
        with pytest.raises(ValueError):
            ProactiveConfig(price_change_pct=-1.0)
        with pytest.raises(ValueError):
            ProactiveConfig(discount_pct=-1.0)


#: 装配后的快照（族 3 跨域视图内核，issue #5358 / #5348）—— 与 admin-api
#: `DailyBriefingService.aggregateSnapshot` 的产物**同形**：
#: · 行级数组 orders/skus/returns + 装配层自描述 `row_fields`（它真的给了哪些字段）
#: · orders 行带 `cost_amount`（#5348 接通：**Σ(行数量 × 该行 SKU 的 avg_cost)**；`null` = 成本未知）
#: · 租户级事实 `cost_accounting`（该租户是否存在 `avg_cost IS NOT NULL` 的 SKU）
#: · **没有 `price_changes` / `order_discounts`**（本快照只演示「未接线」那一侧：无该能力时
#:   规则落 `not_wired`，**不是「命中 0 条」**）；接通了的那一侧见
#:   `test_briefing_proactive_price_and_discount.py` 的 `ASSEMBLED_AUDIT`
ASSEMBLED = {
    "biz_date": BIZ_DATE,
    "cost_accounting": True,
    "row_fields": {
        "orders": ["order_no", "status", "customer_id", "created_at", "shipped_at",
                   "sale_amount", "cost_amount"],
        "skus": ["sku_id", "product_id", "product_name", "stock"],
        "returns": ["return_no", "customer_id", "product_id", "returned_at", "amount"],
    },
    "orders": [
        # 超 N 天未发货（09-12 下单 ⇒ 10 天）；成本 1000 < 成交 1200 ⇒ **不**低于成本价
        {"order_no": "SO-1", "status": "confirmed", "customer_id": "C-1",
         "created_at": "2026-09-12T10:00:00+08:00", "shipped_at": None, "sale_amount": 1200.0,
         "cost_amount": 1000.0},
    ],
    "skus": [
        # stock ≤ 100（含上界）
        {"sku_id": "SKU-1", "product_id": "P-1", "product_name": "雪尼尔-米白", "stock": 20.0},
    ],
    "returns": [
        # 同一客户 7 天内 3 次退货（09-18/09-20/09-22）
        {"return_no": "RT-1", "customer_id": "C-1", "product_id": "P-9",
         "returned_at": "2026-09-18T10:00:00+08:00", "amount": 100.0},
        {"return_no": "RT-2", "customer_id": "C-1", "product_id": "P-9",
         "returned_at": "2026-09-20T10:00:00+08:00", "amount": 120.0},
        {"return_no": "RT-3", "customer_id": "C-1", "product_id": "P-9",
         "returned_at": "2026-09-22T10:00:00+08:00", "amount": 130.0},
    ],
}

#: 装配后**当天一条都没命中**、但三条规则确实已接线的快照 ——
#: 「两种空」里「真的没问题」的那一种（对照 `price_changes` 那种「没接线」的空）。
ASSEMBLED_QUIET = dict(
    ASSEMBLED,
    orders=[],
    skus=[{"sku_id": "SKU-9", "product_id": "P-9", "product_name": "绒布-蓝", "stock": 500.0}],
    returns=[],
)

#: `ASSEMBLED` 上**真的命中**的三条 / **已接线**的五条
#: （多出来的两条 = `below_cost_price` 已接通但该快照上成本 1000 ≥ 成交 1200 ⇒ 无命中）/
#: **未接线的两条**（本快照没装配改价审计与让利订单两个数组）
HITTING_RULES = frozenset({"unshipped_overdue", "low_stock", "repeat_returns"})
WIRED_RULES = HITTING_RULES | {"below_cost_price"}
NOT_WIRED_RULES = frozenset({"price_change_over", "discount_over"})

#: **被行数上限截断**的快照：`row_meta` 显式登记（截断不许静默 —— 有界是热路径必须，
#: 但它会新开一个「看不见的行 ⇒ 不命中 ⇒ 被读成没问题」的面）。
TRUNCATED = dict(ASSEMBLED, row_meta={
    "orders": {"limit": 500, "count": 500, "truncated": True},
    "skus": {"limit": 500, "count": 1, "truncated": False},
    "returns": {"limit": 500, "count": 3, "truncated": False},
})

#: **分组维度缺值**的快照：退货行缺 `product_id`（多商品订单的退货）⇒ 商品维度走不到，
#: 但客户维度照样命中 ⇒ 既不是「没数据」也不是「完整」。
DIMENSION_GAP = dict(ASSEMBLED, returns=[
    {"return_no": f"RT-{n}", "customer_id": "C-1", "product_id": None,
     "returned_at": f"2026-09-{day}T10:00:00+08:00", "amount": 100.0}
    for n, day in ((1, 16), (2, 18), (3, 22))     # 7 天窗口内 3 次 ⇒ 命中日 = 基准日 09-22
])


def _truncation_is_explicit(status):
    """**判据本体**（「截断必须显式」）：被截断的数组所属规则必须落在 `incomplete` 且给出原因。"""
    entry = status["unshipped_overdue"]
    assert entry["status"] == INCOMPLETE, f"截断的规则必须落 incomplete，实得 {entry['status']}"
    assert entry["gaps"], "截断必须给出具体原因（gaps）"
    assert "截断" in entry["reason"]
    return True


def _two_kinds_of_empty_are_separable(status):
    """**判据本体**（issue #5358 判据 2）：未接线 / 本次不完整 与「已接线且完整（当天无命中）」必须可分。

    可分 = ① 两类同时存在（否则本判据是空跑）② 非 `wired` 的规则必带原因 ③ `wired` 不带原因。
    返回 True 只是为了让调用处能写成断言；真正的判别力在三条 assert 上。
    """
    unwired = {r for r, s in status.items() if s.get("status") != WIRED}
    wired = {r for r, s in status.items() if s.get("status") == WIRED}
    assert unwired and wired, f"必须同时存在两类规则（实得 wired={sorted(wired)} 非wired={sorted(unwired)}）"
    assert all(status[r].get("reason") for r in unwired), "未接线/不完整必须给出原因（否则与「无命中」不可分）"
    assert not any(status[r].get("reason") for r in wired), "已接线且完整的规则不得带原因"
    return True


class TestWiringStatusIsPerRule:
    """判据 1/2/3/6（issue #5358）：逐规则接线状态 ——「没数据」≠「没问题」的数据层可分。

    对照判据（会红吗）：把 `orders`/`skus`/`returns` 任一数组从装配产物里去掉 ⇒ 对应规则
    变成 not_wired（本类第 1 条会红）；让 `proactive_status` 只返回一个整体状态 ⇒ 逐规则断言会红；
    抹掉 status 字段 ⇒ 两种空的判别函数会红（注入式红证）。
    """

    def test_assembled_snapshot_unlocks_the_wired_rules(self):
        """判据 1：装配行级数组后，接线的规则**真的命中**（同 (snapshot, as_of, config) ⇒ 同一命中列表）"""
        daily = daily_findings(ASSEMBLED)
        assert {f["rule_id"] for f in daily} == HITTING_RULES
        assert _digest(daily_findings(ASSEMBLED)) == _digest(daily), "同一快照两次扫描必须逐字一致"

    def test_unlocking_does_not_depend_on_the_rule_registry_being_replaced(self):
        """三条规则的命中来自**数组内容**，不是「接了哪几条规则」的声明：清空数组即无命中"""
        assert daily_findings(ASSEMBLED_QUIET) == []

    def test_status_is_per_rule_not_whole(self):
        """判据 3：接线状态**逐规则**（部分接线是可能的：本快照接 5 条、2 条结构性不可达）"""
        status = proactive_status(ASSEMBLED)
        assert {r for r, s in status.items() if s["status"] == WIRED} == set(WIRED_RULES)
        assert {r for r, s in status.items() if s["status"] == NOT_WIRED} == set(NOT_WIRED_RULES)

    def test_below_cost_is_wired_once_cost_amount_is_assembled(self):
        """#5348：`orders` 行带上 `cost_amount` ⇒ 低于成本价**接通**（从 not_wired 变 wired）"""
        entry = proactive_status(ASSEMBLED)["below_cost_price"]
        assert entry["status"] == WIRED
        assert entry["missing"] == []

    def test_below_cost_stays_unwired_when_the_field_is_missing(self):
        """反向：装配层**没给** `cost_amount` 字段（= 系统没实现）⇒ 仍是 not_wired（不是「命中 0 条」）"""
        withoutCost = dict(
            ASSEMBLED,
            row_fields={**ASSEMBLED["row_fields"],
                        "orders": [f for f in ASSEMBLED["row_fields"]["orders"]
                                   if f != "cost_amount"]},
        )
        entry = proactive_status(withoutCost)["below_cost_price"]
        assert entry["status"] == NOT_WIRED
        assert entry["missing"] == ["cost_amount"]
        assert "cost_amount" in entry["reason"]

    def test_price_changes_rule_is_not_wired_not_silently_empty(self):
        """判据 6：`price_changes` 数组**不存在**，且其规则在未接线清单里（不是「命中 0 条」）"""
        assert "price_changes" not in ASSEMBLED
        assert "price_changes" not in ASSEMBLED["row_fields"]
        entry = proactive_status(ASSEMBLED)["price_change_over"]
        assert entry["status"] == NOT_WIRED
        assert entry["missing"] == ["price_changes"]
        assert "price_changes" in entry["reason"]

    def test_two_kinds_of_empty_are_distinguishable(self):
        """判据 2：五条规则「一条都没命中」，但数据层能分出哪两条是**没接线**"""
        assert daily_findings(ASSEMBLED_QUIET) == []
        assert _two_kinds_of_empty_are_separable(proactive_status(ASSEMBLED_QUIET)) is True

    def test_red_proof_status_field_is_load_bearing(self):
        """**注入式红证**：抹掉 status 字段 ⇒ 上面的判别函数必须变红（否则它是空断言）"""
        stripped = {
            rule: {k: v for k, v in entry.items() if k != "status"}
            for rule, entry in proactive_status(ASSEMBLED_QUIET).items()
        }
        with pytest.raises(AssertionError):
            _two_kinds_of_empty_are_separable(stripped)

    def test_red_proof_wired_reason_is_load_bearing(self):
        """**注入式红证**：给已接线规则补一个「原因」⇒ 判别函数必须变红（两类不许长得一样）"""
        polluted = {
            rule: dict(entry, reason="随便一个原因") if entry["status"] == WIRED else entry
            for rule, entry in proactive_status(ASSEMBLED_QUIET).items()
        }
        with pytest.raises(AssertionError):
            _two_kinds_of_empty_are_separable(polluted)

    def test_declared_fields_are_authoritative_over_rows(self):
        """装配层的自描述是权威：声明里没给 `created_at` ⇒ 该规则未接线（不靠「行里碰巧有」）"""
        weakened = dict(
            ASSEMBLED,
            row_fields={**ASSEMBLED["row_fields"], "orders": ["order_no", "status"]},
        )
        entry = proactive_status(weakened)["unshipped_overdue"]
        assert entry["status"] == NOT_WIRED
        assert "created_at" in entry["missing"]

    def test_legacy_snapshot_without_row_fields_falls_back_to_rows(self):
        """滚动升级口径：老快照没有 `row_fields` 自描述 ⇒ 按实际行的字段并集判定（否则会把已接线读成未接线）"""
        status = proactive_status(SNAPSHOT)          # 老 SNAPSHOT：无 row_fields，行里带 cost_amount 与 price_changes
        assert {r for r, s in status.items() if s["status"] == WIRED} == {r.rule_id for r in RULES}

    def test_rule_with_no_array_at_all_is_not_wired(self):
        """断言言快照（只有聚合指标）⇒ 三条规则全部 not_wired（不是「今天没异常」）"""
        status = proactive_status({"metrics": {"today_orders": 3}})
        assert {r for r, s in status.items() if s["status"] == NOT_WIRED} == {r.rule_id for r in RULES}

    def test_java_emitted_timestamp_form_is_parsed(self):
        """跨模块口径：admin-api 落的是 `OffsetDateTime.toString()`（**秒为 0 时省略秒**）⇒ 引擎必须认。

        这与 `SNAPSHOT` 里的 `...T10:00:00+08:00` 是**两种串**，只测其中一种就是「两处投影只钉了一处」。
        """
        snapshot = {
            "biz_date": "2026-09-24",
            "row_fields": ASSEMBLED["row_fields"],
            "orders": [{"order_no": "SO-1", "status": "confirmed", "customer_id": "C-1",
                        "created_at": "2026-09-12T10:00+08:00", "shipped_at": None,
                        "sale_amount": 1200.0}],
            "skus": [{"sku_id": 7, "product_id": "P-1", "product_name": "雪尼尔-米白", "stock": 20.0}],
            "returns": [{"return_no": f"RT-{n}", "customer_id": "C-1", "product_id": "P-9",
                         "returned_at": f"2026-09-{day}T10:00+08:00", "amount": 100.0}
                        for n, day in ((1, 18), (2, 20), (3, 24))],
        }
        findings = daily_findings(snapshot)
        assert {f["rule_id"] for f in findings} == HITTING_RULES
        assert _by_rule(findings, "unshipped_overdue")["criterion"]["observed"][0]["days"] == 12
        assert _by_rule(findings, "repeat_returns")["impact"]["count"] == 3

    def test_only_fully_wired_rules_may_read_empty_as_fine(self):
        """**不变式**：`reason is None` ⟺ `status == wired`（= 已接入**且本次完整**）。

        调用方只看这一条就能决定「空命中能不能读成没问题」—— 三类状态（wired / not_wired /
        incomplete）共用同一个不变式，不给第二套判断口径。
        """
        for snapshot in (ASSEMBLED, ASSEMBLED_QUIET, TRUNCATED, DIMENSION_GAP, {"metrics": {}},
                         COST_PARTIAL, NOT_ENABLED_SNAPSHOT):
            for rule_id, entry in proactive_status(snapshot).items():
                assert (entry["reason"] is None) == (entry["status"] == WIRED), (rule_id, entry)


class TestTruncationAndGapsAreExplicit:
    """判据 7（「有界不许变成静默少报」）：截断与维度缺值都必须**显式**，且空命中不得被读成没问题。

    对照判据（会红吗）：抹掉 `row_meta` ⇒ 截断判据必红；抹掉行的 `product_id` 缺失（补上一个值）
    ⇒ 维度判据必红；把 `status` 直接塞成 `wired` ⇒ 不变式断言必红。
    """

    def test_truncated_array_is_incomplete_not_wired(self):
        assert _truncation_is_explicit(proactive_status(TRUNCATED)) is True

    def test_truncation_is_per_rule_again(self):
        """逐规则：只有被截断的那条不完整，未被截断的照旧 `wired`（不许整体拉黑）"""
        status = proactive_status(TRUNCATED)
        assert status["low_stock"]["status"] == WIRED
        assert status["repeat_returns"]["status"] == WIRED
        # 低于成本价读的是 `orders` 数组 ⇒ 同样被截断波及（#5348 接通后不再是 not_wired）
        assert status["below_cost_price"]["status"] == INCOMPLETE
        assert status["price_change_over"]["status"] == NOT_WIRED

    def test_red_proof_truncation_flag_is_load_bearing(self):
        """**注入式红证**：抹掉 `row_meta` ⇒ 截断判据必红（否则「显式」只是文案）"""
        stripped = {key: value for key, value in TRUNCATED.items() if key != "row_meta"}
        with pytest.raises(AssertionError):
            _truncation_is_explicit(proactive_status(stripped))

    def test_dimension_gap_is_incomplete_but_still_hits_on_the_other_dimension(self):
        """退货行缺 `product_id`（多商品订单）⇒ 商品维度走不到：登记为不完整，但客户维度照样命中"""
        findings = daily_findings(DIMENSION_GAP)
        # 客户维度照样命中（09-18/09-20/09-24 同一客户 3 次）⇒ 这不是「没数据」，是「不完整」
        assert "repeat_returns" in [f["rule_id"] for f in findings]
        assert _by_rule(findings, "repeat_returns")["impact"]["count"] == 3
        entry = proactive_status(DIMENSION_GAP)["repeat_returns"]
        assert entry["status"] == INCOMPLETE
        assert any("product_id" in gap for gap in entry["gaps"])
        assert not entry["missing"], "字段本身是接了的（缺的是部分行的取值），不许记成 not_wired"

    def test_red_proof_dimension_gap_is_load_bearing(self):
        """**注入式红证**：把缺值补齐 ⇒ 维度判据必红（证明它盯的是真值）"""
        filled = dict(DIMENSION_GAP, returns=[
            dict(row, product_id="P-9") for row in DIMENSION_GAP["returns"]
        ])
        with pytest.raises(AssertionError):
            assert proactive_status(filled)["repeat_returns"]["status"] == INCOMPLETE

    def test_daily_total_is_not_capped_by_max_findings(self):
        """「日报要窄」是**展示口径**：条数上限不许把「今天有几项」变成少报"""
        narrow = ProactiveConfig(max_findings=2)
        assert len(daily_findings(SNAPSHOT, config=narrow)) == 2
        assert daily_findings_total(SNAPSHOT, config=narrow) == len(EXPECTED_DAILY) == 6


#: **部分行成本未知**的快照（issue #5348 的行级三态）：装配层逐行解析 SKU，
#: 任一行不可解析或该行 `avg_cost` 为 NULL ⇒ 该订单行 `cost_amount = null`（整单不可判定）。
#: SO-A 可判定且确实低于成本；SO-B 成本未知 —— 后者**不得**被当成「没低于成本」。
COST_PARTIAL = {
    "biz_date": BIZ_DATE,
    "cost_accounting": True,
    "row_fields": {
        "orders": ["order_no", "status", "customer_id", "created_at", "shipped_at",
                   "sale_amount", "cost_amount"],
    },
    "orders": [
        {"order_no": "SO-A", "status": "confirmed", "customer_id": "C-1",
         "created_at": "2026-09-22T09:00:00+08:00", "shipped_at": None,
         "sale_amount": 700.0, "cost_amount": 1000.0},
        {"order_no": "SO-B", "status": "confirmed", "customer_id": "C-2",
         "created_at": "2026-09-22T09:30:00+08:00", "shipped_at": None,
         "sale_amount": 700.0, "cost_amount": None},
    ],
}

#: 该租户**没开启成本核算**（快照事实 `cost_accounting=false` = 没有任何 SKU 有 `avg_cost`）——
#: 系统**有**这个能力（`cost_amount` 字段在），是**该租户没开** ⇒ `not_enabled`（可行动：去开启）。
NOT_ENABLED_SNAPSHOT = dict(
    COST_PARTIAL, cost_accounting=False,
    orders=[dict(row, cost_amount=None) for row in COST_PARTIAL["orders"]],
)

#: **系统没实现**的同一条规则（`orders` 行压根没有 `cost_amount` 字段）⇒ `not_wired`（不可行动）
COST_UNWIRED_SNAPSHOT = {
    "biz_date": BIZ_DATE,
    "row_fields": {
        "orders": ["order_no", "status", "customer_id", "created_at", "shipped_at", "sale_amount"],
    },
    "orders": [{"order_no": "SO-A", "status": "confirmed", "customer_id": "C-1",
                "created_at": "2026-09-22T09:00:00+08:00", "shipped_at": None,
                "sale_amount": 700.0}],
}


def _unknown_cost_rows_are_disclosed(status, rule_id="below_cost_price"):
    """**判据本体**（#5348 判据 5）：成本未知的行必须**显式**登记为「未判定」。

    不得静默跳过 —— 静默跳过 = 把「没数据」读成「没低于成本」（「没数据 ≠ 没问题」的**行级**版本）。
    """
    entry = status[rule_id]
    assert entry["status"] == INCOMPLETE, f"有行未判定 ⇒ 本条本次不完整，实得 {entry['status']}"
    assert entry["reason"], "不完整必须给出原因"
    assert any("cost_amount" in gap for gap in entry["gaps"]), \
        f"必须点名未判定的行，实得 {entry['gaps']}"
    return True


def _two_unavailable_kinds_are_separable(unwired, not_enabled):
    """**判据本体**（#5348 判据 3）：**系统没实现**（`not_wired`）与**该租户没开**（`not_enabled`）必须可分。

    可分 = ① 两态取值不同（不可合并成一个说法）② 都带原因（不变式：`reason is None` ⟺ `wired`）
    ③ `not_wired` 缺的是**字段/数组**（系统没有），`not_enabled` 的字段**是有的**（系统有、租户没开）。
    """
    assert unwired["status"] == NOT_WIRED
    assert not_enabled["status"] == NOT_ENABLED
    assert unwired["status"] != not_enabled["status"], "两态不可合并"
    assert unwired["reason"] and not_enabled["reason"], "两态都必须带原因（不变式不给 not_enabled 开例外）"
    assert unwired["missing"] and not not_enabled["missing"], \
        "not_wired 缺的是字段/数组；not_enabled 字段是有的（区别就在这）"
    return True


class TestCostJoinAndNotEnabled:
    """判据 3/4/5（issue #5348）：成本 join 接通后的**行级三态** + **`not_enabled` 新态**。

    对照判据（会红吗）：把未知行静默跳过（不登记 gaps）⇒ 判据 5 必红；把 `not_enabled` 并进 `not_wired`
    （同一个说法/同一个取值）⇒ 判据 3 必红；把租户级事实当人工配置项（而不是从 `avg_cost` 推出）
    ⇒ 判据 4 的两侧断言必红（见 `test_tenant_switch_is_the_derived_fact`）。
    """

    def test_unknown_cost_row_is_not_judged_but_is_disclosed(self):
        """判据 5：成本未知的行**不进入**「低于成本」的判定，但也**不**等于「没低于成本」"""
        below = _by_rule(daily_findings(COST_PARTIAL), "below_cost_price")["criterion"]["observed"]
        assert [r["ref"] for r in below] == ["SO-A"], "SO-B 成本未知 ⇒ 不判定（既不入命中、也不算没问题）"
        assert _unknown_cost_rows_are_disclosed(proactive_status(COST_PARTIAL)) is True

    def test_the_unknown_row_is_a_real_candidate(self):
        """红证前提：把 SO-B 的成本补上（成交 700、成本 800 ⇒ 亏损 100）⇒ 它**必须**进判定"""
        filled = dict(COST_PARTIAL, orders=[
            dict(row, cost_amount=800.0) if row["order_no"] == "SO-B" else row
            for row in COST_PARTIAL["orders"]])
        observed = _by_rule(daily_findings(filled), "below_cost_price")["criterion"]["observed"]
        assert [r["ref"] for r in observed] == ["SO-A", "SO-B"]
        assert proactive_status(filled)["below_cost_price"]["status"] == WIRED

    def test_red_proof_unknown_rows_must_be_disclosed(self):
        """**注入式红证**：把未知行静默丢掉（谎报 `wired`、不留 gaps）⇒ 判据 5 必红"""
        silent = dict(proactive_status(COST_PARTIAL)["below_cost_price"],
                      status=WIRED, reason=None, gaps=[])
        with pytest.raises(AssertionError):
            _unknown_cost_rows_are_disclosed({"below_cost_price": silent})

    def test_not_enabled_and_not_wired_are_separable(self):
        """判据 3：两态分别可测，且断言的是**两态之间**的差别（不是各自单独看一眼）"""
        assert _two_unavailable_kinds_are_separable(
            proactive_status(COST_UNWIRED_SNAPSHOT)["below_cost_price"],
            proactive_status(NOT_ENABLED_SNAPSHOT)["below_cost_price"]) is True

    def test_not_enabled_reason_is_actionable_guidance(self):
        """判据 3：`not_enabled` 的 reason **非 None** 且要能渲染成**引导去开启**的话术"""
        entry = proactive_status(NOT_ENABLED_SNAPSHOT)["below_cost_price"]
        assert entry["status"] == NOT_ENABLED
        assert "成本核算" in entry["reason"] and "开启" in entry["reason"]
        assert daily_findings(NOT_ENABLED_SNAPSHOT) == [], "没开启 ⇒ 不判定（不是「命中 0 条 = 没问题」）"

    def test_red_proof_merging_the_two_states_fails(self):
        """**注入式红证**：把两态合并（`not_enabled` 谎报成 `not_wired`）⇒ 判据 3 必红"""
        merged = dict(proactive_status(NOT_ENABLED_SNAPSHOT)["below_cost_price"],
                      status=NOT_WIRED, missing=["cost_amount"])
        with pytest.raises(AssertionError):
            _two_unavailable_kinds_are_separable(
                proactive_status(COST_UNWIRED_SNAPSHOT)["below_cost_price"], merged)

    def test_tenant_switch_is_the_derived_fact(self):
        """判据 4：开关判据 = 快照事实 `cost_accounting`（该租户是否存在 `avg_cost IS NOT NULL` 的 SKU）

        两侧断言：`true` ⇒ 可判定（wired）；`false` ⇒ `not_enabled`。**缺省不宣称「没开」** ——
        老快照看不见这个事实时，「看不见」不是「false」（否则滚动升级期会把已开启的租户误报成没开）。
        """
        assert proactive_status(dict(ASSEMBLED, cost_accounting=True))["below_cost_price"]["status"] == WIRED
        assert proactive_status(
            dict(ASSEMBLED, cost_accounting=False))["below_cost_price"]["status"] == NOT_ENABLED
        legacy = {key: value for key, value in ASSEMBLED.items() if key != "cost_accounting"}
        assert proactive_status(legacy)["below_cost_price"]["status"] == WIRED

    def test_rule_declares_what_it_needs_for_the_new_state(self):
        """注册表自身的不变式：低于成本价声明了租户级前置与行级可判定字段（判据源只有这一处）"""
        spec = next(r for r in RULES if r.rule_id == "below_cost_price")
        assert spec.requires == ("orders", ("order_no", "sale_amount", "cost_amount"))
        assert spec.enabled_by == ("cost_accounting", "成本核算",
                                   "在商品入库时录入单价（系统按移动加权算出成本价）")
        assert spec.judgeable_fields == ("cost_amount",)
        # 🔴 只有**声明了租户级前置**的规则才有 `enabled_by`（#5388：改价的审计留痕是第二条）
        assert all(r.enabled_by is None
                   for r in RULES if r.rule_id not in ("below_cost_price", "price_change_over"))
        change = next(r for r in RULES if r.rule_id == "price_change_over")
        assert change.enabled_by == (
            "audit_tool_logging", "写工具审计留痕",
            "让米宝或员工通过 AI 助手执行一次写操作（如改价）以产生审计留痕")
        assert change.judgeable_fields == ("before_price", "new_price")
