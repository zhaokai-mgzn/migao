# case_ids: DA-011, DA-015, DA-017, DA-018
"""改价幅度（**审计日志**源）× 让利幅度（**订单列**源）—— issue #5388

判据来源：#5388 的「裁定 + 冻结判据」评论（**评论里的裁定优先于正文**）。

## 本文件盯的四件事（每一件都能单独变红）

1. **改价的数据面 = 审计日志**，且**两个工具都算改价** —— `product_update`（商品级统一定价）与
   `sku_update`（单 SKU 调价）**只筛一个会漏一半**；幅度 = `abs(new_price - before_price) / before_price`。
2. **两条固有边界不许静默**（`RuleSpec.caveats`）：① 审计是 **fail-open**（3s 上限、允许丢行）
   ⇒ **只会漏报、不会误报**；② 审计留痕只有 #5303 之后带 `before_price` ⇒ 无 `before_price` 的
   记录**不判定**（**不是「幅度 0」**）—— 由 `judgeable_fields` 落成行级「未判定」+ `gaps` 点名。
3. 🔴 **「租户从没改过价」与「审计根本没在跑」必须不同**（#5388 点名最易做错的一条）：
   两者都表现为「没有改价记录」，但一个是**正常的空**（⇒ `wired`）、一个是**故障的空**
   （⇒ `not_enabled` + `reason`）。判据 = 租户级事实 `audit_tool_logging`（窗口内是否存在
   **任意** `resource_type='agent_tool'` 的审计行 = 审计上报在本租户上确实在产出）。
   **缺省（老快照看不见该事实）不宣称「没开」** —— 看不见不是 `False`。
4. **让利幅度**（`discount_over`）= `discount_amount / total_amount`（`orders` 主库列，非旁路）
   ⇒ 它的空是**可信的空**（数组已接入且完整 ⇒ `wired`）；与 3 的「故障的空」**并列、不可合并**
   —— 这条差异本身有判据（见 `test_discount_empty_is_trustworthy_while_audit_empty_is_not`）。

⚠️ 这些断言会红吗：把 `sku_update` 从改价面里删掉 ⇒ 判据 1 红；把 `judgeable_fields` 去掉
（未判定的行被当成「幅度 0」）⇒ 判据 2 红；把 `audit_tool_logging=false` 也落 `wired`
⇒ 判据 3 红；让 `caveats` 不再进 `reason` ⇒ 判据 2 的披露断言红。
"""
# case_ids 声明必须在**前 50 行内**（`.github/growth_gate.py::extract_case_ids` 只扫前 50 行）
from dataclasses import replace

import pytest

from app.briefing.proactive import (
    INCOMPLETE,
    NOT_ENABLED,
    NOT_WIRED,
    RULES,
    WIRED,
    ProactiveConfig,
    daily_findings,
    proactive_status,
    scan_snapshot,
)

BIZ = "2026-09-22"

#: 装配层自描述（`row_fields`）—— 值一律**逐字**，与 `DailyBriefingService.SNAPSHOT_ROW_FIELDS` 同形
PRICE_FIELDS = ["change_no", "tool_name", "product_id", "before_price", "new_price", "changed_at"]
DISCOUNT_FIELDS = ["order_no", "total_amount", "discount_amount", "created_at"]


def _row_fields(price=True, discount=True):
    fields = {"orders": ["order_no", "sale_amount", "cost_amount"]}
    if price:
        fields["price_changes"] = list(PRICE_FIELDS)
    if discount:
        fields["order_discounts"] = list(DISCOUNT_FIELDS)
    return fields


def _touch(change_no="PC-1", tool="product_update", before=200.0, new=120.0, day=BIZ):
    """一条审计来源的改价行（键名逐字 = 快照契约）。"""
    return {"change_no": change_no, "tool_name": tool, "product_id": "P-1",
            "before_price": before, "new_price": new, "changed_at": f"{day}T09:30:00+08:00"}


def _discount(order_no="OD-1", total=1000.0, discount=400.0, day=BIZ):
    return {"order_no": order_no, "total_amount": total, "discount_amount": discount,
            "created_at": f"{day}T08:00:00+08:00"}


def _snapshot(price_changes=(), order_discounts=(), audit_logging=True,
              price=True, discount=True, biz=BIZ):
    """装配后的快照（与 `aggregateSnapshot` 产物同形）。`audit_logging=None` ⇒ 该事实**缺省**。"""
    snap = {
        "biz_date": biz,
        "row_fields": _row_fields(price=price, discount=discount),
        "price_changes": list(price_changes),
        "order_discounts": list(order_discounts),
    }
    if audit_logging is not None:
        snap["audit_tool_logging"] = audit_logging
    return snap


def _by_rule(findings, rule_id):
    hits = [f for f in findings if f["rule_id"] == rule_id]
    assert len(hits) == 1, f"{rule_id} 期望恰好 1 条命中，实得 {len(hits)}"
    return hits[0]


# ── 判据 1：改价的数据面（两个工具都算改价）──────────────────────────────────


class TestPriceChangeComesFromTheAuditLog:
    def test_both_price_tools_are_price_changes(self):
        """`product_update` 与 `sku_update` **都是改价** —— 只筛一个会漏一半（#5388 冻结判据）"""
        snap = _snapshot(price_changes=[
            _touch("PC-1", "product_update", 200.0, 120.0),      # 40%
            _touch("PC-2", "sku_update", 500.0, 250.0),          # 50%
        ])
        hit = _by_rule(daily_findings(snap), "price_change_over")
        assert hit["impact"]["count"] == 2
        assert [r["ref"] for r in hit["criterion"]["observed"]] == ["PC-1", "PC-2"]
        assert {r["tool_name"] for r in hit["criterion"]["observed"]} == {"product_update", "sku_update"}

    def test_each_tool_row_is_a_real_candidate(self):
        """红证前提：任取一个工具的行删掉 ⇒ 计数必须掉（证明两行都在射程内，不是凑数）"""
        for dropped in ("PC-1", "PC-2"):
            snap = _snapshot(price_changes=[
                _touch("PC-1", "product_update", 200.0, 120.0),
                _touch("PC-2", "sku_update", 500.0, 250.0),
            ])
            snap = dict(snap, price_changes=[r for r in snap["price_changes"] if r["change_no"] != dropped])
            assert _by_rule(daily_findings(snap), "price_change_over")["impact"]["count"] == 1

    def test_pct_is_relative_to_before_price(self):
        """幅度 = `abs(new - before) / before`（涨跌都算，取绝对值）"""
        down = _by_rule(daily_findings(_snapshot(price_changes=[_touch(before=100.0, new=60.0)])),
                        "price_change_over")["criterion"]["observed"][0]
        up = _by_rule(daily_findings(_snapshot(price_changes=[_touch(before=100.0, new=150.0)])),
                      "price_change_over")["criterion"]["observed"][0]
        assert down["pct"] == 40.0 and up["pct"] == 50.0

    def test_threshold_is_exclusive(self):
        """恰等阈值不命中（30% == 阈值）/ 超一点即命中 —— 两侧都在同一断言里"""
        exact = _snapshot(price_changes=[_touch(before=100.0, new=70.0)])
        over = _snapshot(price_changes=[_touch(before=100.0, new=69.99)])
        assert daily_findings(exact) == []
        assert _by_rule(daily_findings(over), "price_change_over")["impact"]["count"] == 1
        looser = ProactiveConfig(price_change_pct=29.0)
        assert _by_rule(daily_findings(exact, config=looser), "price_change_over") is not None


# ── 判据 2：未判定的行 + 固有边界（不许静默）─────────────────────────────────


class TestUnjudgedRowsAndSourceCaveats:
    def test_row_without_before_price_is_not_judged_not_zero(self):
        """无 `before_price` / 无 `new_price` 的行：**不判定**（不是「幅度 0」，也不算「没问题」）"""
        snap = _snapshot(price_changes=[
            _touch("PC-1", "product_update", 200.0, 120.0),          # 可判定
            _touch("PC-2", "product_update", None, 120.0),           # 无改前价（#5303 之前的历史行）
            _touch("PC-3", "sku_update", 300.0, None),               # 无改后价（脱敏期落库的历史行）
        ])
        entry = proactive_status(snap)["price_change_over"]
        assert entry["status"] == INCOMPLETE, "有行未判定 ⇒ 本次不完整（不是 wired）"
        assert any("before_price" in gap for gap in entry["gaps"])
        assert any("new_price" in gap for gap in entry["gaps"])
        assert entry["reason"], "不完整必须给出原因（不变式：reason is None ⟺ wired）"
        hit = _by_rule(daily_findings(snap), "price_change_over")
        assert [r["ref"] for r in hit["criterion"]["observed"]] == ["PC-1"], \
            "未判定的行既不进命中，也不得被当成「没有改价」"

    def test_the_unjudged_rows_are_real_candidates(self):
        """红证前提：把缺的价补上（各 50% 幅度）⇒ 未判定消失且两条都进命中"""
        filled = _snapshot(price_changes=[
            _touch("PC-1", "product_update", 200.0, 120.0),
            _touch("PC-2", "product_update", 240.0, 120.0),
            _touch("PC-3", "sku_update", 300.0, 150.0),
        ])
        assert proactive_status(filled)["price_change_over"]["status"] == WIRED
        assert _by_rule(daily_findings(filled), "price_change_over")["impact"]["count"] == 3

    def test_caveats_are_never_silent(self):
        """固有边界（fail-open 漏报 / #5303 之前无 before_price）必须**始终**可取到"""
        wired = proactive_status(_snapshot(price_changes=[_touch()]))["price_change_over"]
        assert wired["status"] == WIRED and wired["reason"] is None
        text = "；".join(wired["caveats"])
        assert "fail-open" in text and "漏报" in text, f"漏报边界未披露：{text}"
        assert "#5303" in text and "不判定" in text, f"历史边界未披露：{text}"

    def test_caveats_ride_into_the_reason_when_anything_is_off(self):
        """非 `wired` 时，边界要**并入 reason**（#5388 冻结判据：不许静默）"""
        for snap in (_snapshot(price_changes=[_touch(before=None)]),            # incomplete
                     _snapshot(price_changes=[], audit_logging=False)):         # not_enabled
            entry = proactive_status(snap)["price_change_over"]
            assert entry["status"] != WIRED
            assert "fail-open" in entry["reason"], f"边界未进 reason：{entry['reason']}"

    def test_red_proof_the_gap_detector_is_load_bearing(self):
        """**注入式红证**：谎报 `wired`（抹掉未判定）⇒ 未判定判据必红"""
        silent = dict(proactive_status(_snapshot(price_changes=[_touch(before=None)]))["price_change_over"],
                      status=WIRED, reason=None, gaps=[])
        assert silent["gaps"] == [] and silent["status"] == WIRED
        with pytest.raises(AssertionError):
            _unjudged_rows_are_disclosed({"price_change_over": silent})


def _unjudged_rows_are_disclosed(status, rule_id="price_change_over"):
    """**判据本体**：未判定的行必须落 `incomplete` + `gaps` 点名（不得静默跳过）。"""
    entry = status[rule_id]
    assert entry["status"] == INCOMPLETE
    assert entry["gaps"], "未判定必须点名"
    assert entry["reason"], "不完整必须带原因"
    return True


# ── 判据 3：两种「没有改价记录」必须可分 ────────────────────────────────────


def _normal_and_fault_empty_are_separable(normal, fault):
    """**判据本体**（#5388 的关键区分）：正常的空（从没改过价）与故障的空（审计没在跑）不可合并。"""
    assert normal["status"] == WIRED, f"审计在跑 + 无改价记录 ⇒ 正常的空（实得 {normal['status']}）"
    assert normal["reason"] is None, "正常的空不带原因（不变式）"
    assert fault["status"] == NOT_ENABLED, f"审计没在跑 ⇒ 故障的空（实得 {fault['status']}）"
    assert fault["reason"], "故障的空必须带原因"
    assert fault["status"] != normal["status"], "两种空不得共用一个说法"
    assert not fault["missing"], "字段是接了的（缺的是**数据**）⇒ 不得记成 not_wired"
    return True


class TestTheTwoKindsOfEmptyPriceRecord:
    def test_tenant_who_never_changed_price_is_normal_empty(self):
        """审计在跑（窗口内有其它写工具留痕）+ 没有改价记录 ⇒ `wired`：这才是「从没改过价」"""
        entry = proactive_status(_snapshot(price_changes=[], audit_logging=True))["price_change_over"]
        assert entry["status"] == WIRED and entry["reason"] is None

    def test_audit_not_running_is_a_fault_empty(self):
        """窗口内**一条写工具审计行都没有** ⇒ 无法区分「没改过价」与「审计丢行」⇒ 不判定"""
        entry = proactive_status(_snapshot(price_changes=[], audit_logging=False))["price_change_over"]
        assert entry["status"] == NOT_ENABLED
        assert "写工具审计留痕" in entry["reason"] and "开启" in entry["reason"]
        assert "audit_tool_logging" in entry["reason"], "判红要能归因到那条租户级事实"

    def test_the_two_empties_are_separable_in_one_assertion(self):
        assert _normal_and_fault_empty_are_separable(
            proactive_status(_snapshot(price_changes=[], audit_logging=True))["price_change_over"],
            proactive_status(_snapshot(price_changes=[], audit_logging=False))["price_change_over"],
        ) is True

    def test_legacy_snapshot_without_the_fact_does_not_claim_not_enabled(self):
        """滚动升级：老快照看不见 `audit_tool_logging` ⇒ **不宣称「没开」**（看不见 ≠ false）"""
        entry = proactive_status(_snapshot(price_changes=[], audit_logging=None))["price_change_over"]
        assert entry["status"] == WIRED

    def test_red_proof_fault_empty_may_not_be_wired(self):
        """**注入式红证**：把故障的空谎报成 `wired` ⇒ 判据本体必红（否则两种空又被合并）"""
        coerced = dict(proactive_status(
            _snapshot(price_changes=[], audit_logging=False))["price_change_over"],
            status=WIRED, reason=None)
        with pytest.raises(AssertionError):
            _normal_and_fault_empty_are_separable(
                proactive_status(_snapshot(price_changes=[], audit_logging=True))["price_change_over"],
                coerced)


# ── 判据 4：让利幅度（orders 主库列）────────────────────────────────────────


class TestDiscountOver:
    def test_ratio_and_threshold(self):
        """幅度 = `discount_amount / total_amount`；恰等阈值不命中、超一点命中"""
        exact = _snapshot(order_discounts=[_discount(total=1000.0, discount=300.0)])
        over = _snapshot(order_discounts=[_discount(total=1000.0, discount=301.0)])
        assert daily_findings(exact) == []
        hit = _by_rule(daily_findings(over), "discount_over")
        assert hit["impact"]["count"] == 1
        assert hit["impact"]["amount"] == 301.0
        assert hit["criterion"]["observed"][0]["pct"] == 30.1

    def test_threshold_is_configurable(self):
        loose = ProactiveConfig(discount_pct=25.0)
        assert _by_rule(daily_findings(
            _snapshot(order_discounts=[_discount(total=1000.0, discount=300.0)]),
            config=loose), "discount_over")["impact"]["count"] == 1

    def test_event_rows_are_grouped_by_order_date(self):
        """事件型规则：命中日期 = 下单日；历史异常在全量视图里在、日报里不在"""
        snap = _snapshot(order_discounts=[_discount("OD-1", day=BIZ),
                                          _discount("OD-2", day="2026-09-05")])
        assert [(f["rule_id"], f["detected_on"]) for f in scan_snapshot(snap)] == [
            ("discount_over", BIZ), ("discount_over", "2026-09-05")]
        assert [f["detected_on"] for f in daily_findings(snap)] == [BIZ]

    def test_missing_amounts_are_unjudged_not_zero(self):
        """`discount_amount` / `total_amount` 缺失或非数 ⇒ **未判定**（不是「没有让利」）"""
        snap = _snapshot(order_discounts=[
            _discount("OD-1", total=1000.0, discount=400.0),      # 可判定 ⇒ 命中
            _discount("OD-2", total=1000.0, discount=None),       # 让利未知
            _discount("OD-3", total=None, discount=400.0),        # 应收未知（分母未知）
            _discount("OD-4", total=0.0, discount=400.0),         # 分母 0 ⇒ 不判（不是 100%）
        ])
        entry = proactive_status(snap)["discount_over"]
        assert entry["status"] == INCOMPLETE
        assert any("discount_amount" in gap for gap in entry["gaps"])
        assert any("total_amount" in gap for gap in entry["gaps"])
        hit = _by_rule(daily_findings(snap), "discount_over")
        assert [r["ref"] for r in hit["criterion"]["observed"]] == ["OD-1"], \
            "分母为 0 的行不得被当成 100% 让利，也不得被当成「没问题」"

    def test_the_unjudged_discount_rows_are_real_candidates(self):
        """红证前提：补齐金额（各 40%）⇒ 未判定消失、四条都进命中"""
        filled = _snapshot(order_discounts=[
            _discount("OD-1", total=1000.0, discount=400.0),
            _discount("OD-2", total=1000.0, discount=400.0),
            _discount("OD-3", total=1000.0, discount=400.0),
            _discount("OD-4", total=1000.0, discount=400.0),
        ])
        assert proactive_status(filled)["discount_over"]["status"] == WIRED
        assert _by_rule(daily_findings(filled), "discount_over")["impact"]["count"] == 4

    def test_discount_empty_is_trustworthy_while_audit_empty_is_not(self):
        """🔴 两条规则的「空」**性质不同**：`orders` 是主库列（空=真空）；审计是 fail-open 旁路（空可能假）。

        同一份断言里两种空并存 ⇒ 这不是「统一处理」能替代的判断，而是**两条规则各自的判据**。
        """
        snap = _snapshot(price_changes=[], order_discounts=[], audit_logging=True)
        status = proactive_status(snap)
        assert status["discount_over"]["status"] == WIRED, "让利：数组已接入且完整 ⇒ 空命中可信"
        assert status["discount_over"]["reason"] is None
        assert status["price_change_over"]["status"] == WIRED, "审计在跑 ⇒ 改价：空命中同样可信"
        # 审计没在跑 ⇒ 只有改价那条翻成「不判定」；让利那条**不受影响**（不同源）
        fault = proactive_status(_snapshot(price_changes=[], order_discounts=[], audit_logging=False))
        assert fault["price_change_over"]["status"] == NOT_ENABLED
        assert fault["discount_over"]["status"] == WIRED

    def test_discount_has_no_tenant_switch_because_its_source_is_not_a_bypass(self):
        """注册表不变式：让利**不**声明租户级前置（没有诚实的开关；它的故障空是结构性的 `not_wired`）"""
        spec = next(r for r in RULES if r.rule_id == "discount_over")
        assert spec.enabled_by is None
        unwired = _snapshot(order_discounts=[], discount=False)
        entry = proactive_status(unwired)["discount_over"]
        assert entry["status"] == NOT_WIRED and entry["missing"] == ["order_discounts"]


# ── 注册表与不变式（单一源）─────────────────────────────────────────────────


class TestRegistrationAndInvariant:
    def test_rules_declare_their_inputs(self):
        price = next(r for r in RULES if r.rule_id == "price_change_over")
        discount = next(r for r in RULES if r.rule_id == "discount_over")
        assert price.requires == ("price_changes",
                                  ("change_no", "before_price", "new_price", "changed_at"))
        assert price.judgeable_fields == ("before_price", "new_price")
        assert price.enabled_by == (
            "audit_tool_logging", "写工具审计留痕",
            "让米宝或员工通过 AI 助手至少执行一次写操作（如改价）以产生审计留痕；"
            "若你确实用过写操作而这里仍为空，说明审计上报没有在跑（该通道 fail-open、可能丢行），"
            "请联系技术支持排查")
        assert price.caveats == (
            "审计上报是 fail-open（3s 硬上限、允许丢行）⇒ 本项**可能漏报**；审计只记「调用过」，"
            "而 `success=false`（服务端拒绝 / 工具抛错）的调用**不算改价**（价根本没变）"
            "⇒ 本项不会把失败的改价报成改价",
            "审计留痕自 #5303 起才带改价真值：更早的改价没有 before_price ⇒ 那类记录**不判定**（不是幅度 0）",
            "批量改价（product_batch_update）**在射程内**，但取数面与审计腿不同：它走批次明细 "
            "agent_batch_items 的 old_value / new_value（执行批量时参数只有 batch_id，审计行里没有价格可落）"
            "；「从未生效」的条目（pending / failed / skipped）不算改价，**已撤销的批次仍算**（价确实动过）"
            "；审计腿的租户级前置（audit_tool_logging）**只管审计腿** —— 它 false 时批量腿不受影响，"
            "该租户仍可能因批量改价而命中（那种情形下「本次未判定」只对审计腿成立）",
            "覆盖面仍窄于「所有改价」：只覆盖经米宝执行的 product_update / sku_update / "
            "product_batch_update 三条路径；product_manage（能改 basePrice，但改前价不可得 ⇒ 幅度不可判定）"
            "与后台页面直接改价（不经 Agent ⇒ 不写 agent_tool 审计）是本项**显式豁免**的两条路径"
            "（豁免在册 + 理由，见 app/tools/registry.py 的 _UNTRACKED_PRICE_PATHS）",
            "改前价由模型据 product_detail 的当前价填写（#5303 起必填），服务端按值回查（#5317）**不符即拒**"
            " ⇒ 被拒的调用不入本项；幅度取**落库真值**（审计腿 = action_details.priceChange，"
            "批量腿 = agent_batch_items 的 old/new 值）",
        )
        assert discount.requires == ("order_discounts",
                                     ("order_no", "total_amount", "discount_amount", "created_at"))
        assert discount.judgeable_fields == ("discount_amount", "total_amount")
        assert discount.caveats, "让利源的固有边界（默认 0 / 只含有让利的订单）也要披露"

    def test_the_two_rules_are_complementary_not_substitutes(self):
        """两条规则**互补不是替代**：一条盯「动作」（有人动了价）、一条盯「结果」（这单让利过多）"""
        ids = [r.rule_id for r in RULES]
        assert "price_change_over" in ids and "discount_over" in ids
        price = next(r for r in RULES if r.rule_id == "price_change_over")
        discount = next(r for r in RULES if r.rule_id == "discount_over")
        assert price.requires[0] != discount.requires[0], "数据源不同（审计 vs 订单列）"
        assert price.action_url != discount.action_url, "处置入口各自指向真能改变结果的页面"
        assert price.expression != discount.expression

    def test_reason_is_none_iff_wired(self):
        """**不变式**：`reason is None` ⟺ `status == wired`（#5388 明确：不给任何态开例外）"""
        for snap in (
            _snapshot(price_changes=[_touch()], order_discounts=[_discount()]),
            _snapshot(price_changes=[], order_discounts=[], audit_logging=True),
            _snapshot(price_changes=[], order_discounts=[], audit_logging=False),
            _snapshot(price_changes=[_touch(before=None)], order_discounts=[_discount(discount=None)]),
            _snapshot(price_changes=[], order_discounts=[], price=False, discount=False),
            _snapshot(price_changes=[_touch()], order_discounts=[], audit_logging=None),
        ):
            for rule_id, entry in proactive_status(snap).items():
                assert (entry["reason"] is None) == (entry["status"] == WIRED), (rule_id, entry)

    def test_every_status_entry_carries_the_caveats_key(self):
        """调用方（briefing_query）要能**始终**拿到固有边界 ⇒ 该键恒在（可为空列表）"""
        for entry in proactive_status(_snapshot(price_changes=[_touch()])).values():
            assert isinstance(entry["caveats"], list)

    def test_caveats_belong_to_the_rule_spec_not_to_a_second_register(self):
        """边界只有**一处**声明（`RuleSpec.caveats`）：替换规则表 ⇒ 边界随之改变（不是另抄一份）"""
        stripped = tuple(replace(spec, caveats=()) if spec.rule_id == "price_change_over" else spec
                         for spec in RULES)
        entry = proactive_status(_snapshot(price_changes=[_touch()]), rules=stripped)["price_change_over"]
        assert entry["caveats"] == []


def _batch_touch(change_no="ABI-7", before=200.0, new=120.0, day=BIZ):
    """一条**批次明细来源**的改价行（issue #5411）：键名逐字 = 快照契约（与审计腿**同形**）。

    值来自 `agent_batch_items.old_value / new_value`（不是审计的 `action_details.priceChange`）——
    **取数口径不同、行的形态相同**（复用同一个 `price_changes` 数组，不另立第二套）。
    """
    return {"change_no": change_no, "tool_name": "product_batch_update", "product_id": "P-9",
            "before_price": before, "new_price": new, "changed_at": f"{day}T10:05:00+08:00"}


class TestBatchPriceChangeIsInScope:
    """🔴 issue #5411：**批量降价必须能被发现**（判据 1）。

    ⚠️ **哪一层承重（别把这条读成空断言）**：让批量行进 `price_changes` 数组的是**装配层**
    （`DailyBriefingService.assemblePriceChangeRows`）—— 引擎对 `tool_name` 不设限。所以
    「装配真的产出了它」由 Java 判据承重（`DailyBriefingServiceTest::batchPriceRowsComeFromTheBatchItems`
    + `AuditLogPriceChangeRealDbTest::batchPriceDropIsDiscoveredFromTheBatchItems`，真库注入式红证）；
    **本类**承重的是「同形消费」：批量行按**同一形态**进来后，规则必须照常命中 ——
    谁给 `_detect_price_change` 加上「只认审计工具」这类过滤，这里就红。
    """

    def test_batch_price_drop_is_discovered(self):
        """批量降价（200 → 120 = 40% > 30%）⇒ 必须命中，且证据逐字给出批次来源的行"""
        snapshot = _snapshot(price_changes=[_batch_touch()])
        finding = next(f for f in scan_snapshot(snapshot) if f["rule_id"] == "price_change_over")

        assert finding["impact"]["count"] == 1
        row = finding["criterion"]["observed"][0]
        assert row["ref"] == "ABI-7"
        assert row["tool_name"] == "product_batch_update"
        assert row["before_price"] == 200.0 and row["new_price"] == 120.0
        assert row["pct"] == 40.0

    def test_batch_row_shape_is_the_same_as_the_audit_row_shape(self):
        """**不另立第二套**：批量行与审计行的键集**逐字相同**（规则只声明一份输入契约）"""
        assert set(_batch_touch()) == set(_touch())
        assert set(_batch_touch()) == set(PRICE_FIELDS)

    def test_red_proof_batch_row_is_the_load_bearing_input(self):
        """红证：把批次行从快照里摘掉 ⇒ 同一快照不再命中（证明上面那条断言吃的是这个输入）"""
        without = _snapshot(price_changes=[])
        assert [f for f in scan_snapshot(without) if f["rule_id"] == "price_change_over"] == []
        with_row = _snapshot(price_changes=[_batch_touch()])
        assert [f["rule_id"] for f in scan_snapshot(with_row)].count("price_change_over") == 1

    def test_caveats_disclose_the_batch_leg_and_both_exempt_paths(self):
        """披露面（判据 4）：批量腿的**取数口径不同**要说出 来，两条豁免路径也**不许静默**"""
        caveats = "；".join(next(r for r in RULES if r.rule_id == "price_change_over").caveats)

        assert "product_batch_update" in caveats, "批量改价的取数面不同 ⇒ 必须在 caveats 里说明"
        assert "agent_batch_items" in caveats, "取数面要点名到表（否则「在射程内」只是一句宣称）"
        assert "product_manage" in caveats, "显式豁免的路径必须点名（缺口不许只活在代码里）"
        assert "后台页面直接改价" in caveats, (
            "不经 Agent 的改价路径（后台页面）必须登记为显式豁免 + 理由，或指出它归哪个面")