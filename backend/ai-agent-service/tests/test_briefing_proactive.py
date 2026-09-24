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


#: 装配后的快照（族 3 跨域视图内核，issue #5358）—— 与 admin-api
#: `DailyBriefingService.aggregateSnapshot` 的产物**同形**：
#: · 行级数组 orders/skus/returns + 装配层自描述 `row_fields`（它真的给了哪些字段）
#: · orders 行**没有 `cost_amount`**（`orders` 表无成本列）⇒ `below_cost_price` 仍接不通
#: · **没有 `price_changes`**（全仓无改价流水表）⇒ `price_change_over` 接不通
ASSEMBLED = {
    "biz_date": BIZ_DATE,
    "row_fields": {
        "orders": ["order_no", "status", "customer_id", "created_at", "shipped_at", "sale_amount"],
        "skus": ["sku_id", "product_id", "product_name", "stock"],
        "returns": ["return_no", "customer_id", "product_id", "returned_at", "amount"],
    },
    "orders": [
        # 超 N 天未发货（09-12 下单 ⇒ 10 天）
        {"order_no": "SO-1", "status": "confirmed", "customer_id": "C-1",
         "created_at": "2026-09-12T10:00:00+08:00", "shipped_at": None, "sale_amount": 1200.0},
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

#: 已接线的三条（本单接上的）/ 未接线的两条（结构性不可达）—— 逐规则，不是整体
WIRED_RULES = frozenset({"unshipped_overdue", "low_stock", "repeat_returns"})
NOT_WIRED_RULES = frozenset({"below_cost_price", "price_change_over"})

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

    def test_assembled_snapshot_unlocks_the_three_wired_rules(self):
        """判据 1：装配行级数组后，3 条规则**真的命中**（同 (snapshot, as_of, config) ⇒ 同一命中列表）"""
        daily = daily_findings(ASSEMBLED)
        assert {f["rule_id"] for f in daily} == WIRED_RULES
        assert _digest(daily_findings(ASSEMBLED)) == _digest(daily), "同一快照两次扫描必须逐字一致"

    def test_unlocking_does_not_depend_on_the_rule_registry_being_replaced(self):
        """三条规则的命中来自**数组内容**，不是「接了哪几条规则」的声明：清空数组即无命中"""
        assert daily_findings(ASSEMBLED_QUIET) == []

    def test_status_is_per_rule_not_whole(self):
        """判据 3：接线状态**逐规则**（部分接线是可能的：本单接 3 条、2 条结构性不可达）"""
        status = proactive_status(ASSEMBLED)
        assert {r for r, s in status.items() if s["status"] == WIRED} == set(WIRED_RULES)
        assert {r for r, s in status.items() if s["status"] == NOT_WIRED} == set(NOT_WIRED_RULES)

    def test_below_cost_stays_unwired_even_though_orders_are_assembled(self):
        """风险不对称（#5348）：`orders` 装配好了，`below_cost_price` 仍接不通 —— 缺的是成本价"""
        entry = proactive_status(ASSEMBLED)["below_cost_price"]
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
        assert {f["rule_id"] for f in findings} == WIRED_RULES
        assert _by_rule(findings, "unshipped_overdue")["criterion"]["observed"][0]["days"] == 12
        assert _by_rule(findings, "repeat_returns")["impact"]["count"] == 3

    def test_only_fully_wired_rules_may_read_empty_as_fine(self):
        """**不变式**：`reason is None` ⟺ `status == wired`（= 已接入**且本次完整**）。

        调用方只看这一条就能决定「空命中能不能读成没问题」—— 三类状态（wired / not_wired /
        incomplete）共用同一个不变式，不给第二套判断口径。
        """
        for snapshot in (ASSEMBLED, ASSEMBLED_QUIET, TRUNCATED, DIMENSION_GAP, {"metrics": {}}):
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
        assert status["below_cost_price"]["status"] == NOT_WIRED

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
        assert daily_findings_total(SNAPSHOT, config=narrow) == len(EXPECTED_DAILY) == 5
