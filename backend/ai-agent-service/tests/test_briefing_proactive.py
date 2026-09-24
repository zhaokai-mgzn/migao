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
# case_ids: DA-011, DA-012, DA-013, DA-014, DA-015
import copy
import json
import random
from dataclasses import replace

import pytest

from app.briefing.proactive import (
    DEFAULT_CONFIG,
    RULES,
    ProactiveConfig,
    daily_findings,
    scan_snapshot,
)

BIZ_DATE = "2026-09-22"

#: 固定数据快照（判据 1 的「给定快照」）。同一份快照同时承载：
#: 当天异常（SO-4 / SO-1 / C-1 / PC-1 / SKU-1,SKU-3）与**历史异常**
#: （SO-5 @09-01 / C-7 @09-03 / PC-3 @09-01）—— 判据 4 的两侧都取自它。
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
        {"change_no": "PC-1", "order_no": "SO-4", "product_id": "P-1",
         "original_price": 200.0, "new_price": 120.0, "changed_at": "2026-09-22T09:30:00+08:00"},
        {"change_no": "PC-2", "order_no": "SO-2", "product_id": "P-2",
         "original_price": 100.0, "new_price": 70.0, "changed_at": "2026-09-22T09:40:00+08:00"},
        # **历史**异常（09-01，幅度 50%）
        {"change_no": "PC-3", "order_no": "SO-5", "product_id": "P-5",
         "original_price": 100.0, "new_price": 50.0, "changed_at": "2026-09-01T09:00:00+08:00"},
    ],
}

#: 当天异常（日报）的**逐字**命中集合：按 紧急度 → 规则注册序 排序
EXPECTED_DAILY = [
    ("below_cost_price", BIZ_DATE),
    ("unshipped_overdue", BIZ_DATE),
    ("repeat_returns", BIZ_DATE),
    ("low_stock", BIZ_DATE),
    ("price_change_over", BIZ_DATE),
]

#: 全量扫描（含历史异常）：按 日期倒序 → 紧急度 → 规则注册序
EXPECTED_SCAN = [
    ("below_cost_price", BIZ_DATE),
    ("unshipped_overdue", BIZ_DATE),
    ("repeat_returns", BIZ_DATE),
    ("low_stock", BIZ_DATE),
    ("price_change_over", BIZ_DATE),
    ("repeat_returns", "2026-09-03"),
    ("below_cost_price", "2026-09-01"),
    ("price_change_over", "2026-09-01"),
]

#: 历史异常的三条证据（判据 4 的「必不出现」侧：按 ref 断言，避免只盯日期）
HISTORICAL_REFS = ("SO-5", "C-7", "PC-3")


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
        assert len(ids) == 5
        assert len(set(ids)) == 5
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
        daily = daily_findings(SNAPSHOT)
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
        assert [r["ref"] for r in observed] == ["PC-1"]     # PC-2 恰 30% 落到界外
        assert observed[0]["pct"] == 40.0

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
