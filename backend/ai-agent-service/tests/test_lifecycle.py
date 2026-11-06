# case_ids: MC-340
"""口径卡生命周期 P2（issue #8175）：衰减 / 规则化退役 / 晋升判定。

四条判据各自**会红**（注入式，改回旧行为即具名红）：

- **衰减**：`hits=4` + 半衰期 90 天 ⇒ 90 天后 2.0、180 天后 1.0（把指数半衰改成线性 ⇒ 红）；
- **退役**：必须**两个条件同时成立**（连续 N 天无命中 **且** 衰减分 < 阈值），
  只看天数 / 只看分数 ⇒ 红；命中一次即推迟；转 retired 必须留**可审计原因**；
- **晋升**：**N 个不同员工**才够（同一个员工复现两次 ⇒ 红）；同组已有 active ⇒ 拒绝晋升
  （冲突消解前置，绝不制造第二条同组 active）；`scope != tenant` 不在 P2 晋升面；
- **默认关**：晋升 / 自动退役默认关闭（默认开 ⇒ 红）—— 缺省不改变线上行为。

另外三条**源码级契约**（纯字符串，零 DB）：退役 SQL 是 CAS + 租户列；晋升 SQL 也是 CAS；
复现计数 SQL 必须是 `COUNT(DISTINCT employee_id)`（改成 `COUNT(*)` 就会把「一个人说两次」
当成「两个人说」——晋升判据当场失效，而功能测试照样绿）。
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings, settings
from app.playbook import identity, lifecycle

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
TRIGGER = {"field": "user_text", "op": "contains", "value": "整卷"}


def make_card(**overrides):
    card = {
        "id": "pb_1",
        "tenant_id": 1,
        "scope": "tenant",
        "scope_role": None,
        "trigger": dict(TRIGGER),
        "correct": "整卷优先",
        "counter": None,
        "hits": 0,
        "state": "active",
        "last_hit_at": None,
        "activated_at": NOW - timedelta(days=90),
        "created_at": NOW - timedelta(days=90),
    }
    card.update(overrides)
    return card


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    """把配置钉成文档里的默认值（每个用例只改自己要考的那一项）。"""
    monkeypatch.setattr(settings, "PLAYBOOK_DECAY_HALF_LIFE_DAYS", 90.0, raising=False)
    monkeypatch.setattr(settings, "PLAYBOOK_RETIRE_AFTER_DAYS", 60, raising=False)
    monkeypatch.setattr(settings, "PLAYBOOK_RETIRE_DECAY_THRESHOLD", 0.5, raising=False)
    monkeypatch.setattr(settings, "PLAYBOOK_AUTO_RETIRE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "PLAYBOOK_PROMOTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "PLAYBOOK_PROMOTION_MIN_EMPLOYEES", 3, raising=False)
    monkeypatch.setattr(settings, "PLAYBOOK_HIT_TRACKING_ENABLED", True, raising=False)


# ── 衰减：由 hits + 时间推出的分数（指数半衰）────────────────────────────────


def test_decay_halves_each_half_life():
    """4 次命中：0 天 = 4.0；90 天 = 2.0；180 天 = 1.0（线性衰减 ⇒ 后两点必红）。"""
    fresh = make_card(hits=4, last_hit_at=NOW)
    one = make_card(hits=4, last_hit_at=NOW - timedelta(days=90))
    two = make_card(hits=4, last_hit_at=NOW - timedelta(days=180))

    assert lifecycle.decay_score(fresh, NOW) == pytest.approx(4.0)
    assert lifecycle.decay_score(one, NOW) == pytest.approx(2.0)
    assert lifecycle.decay_score(two, NOW) == pytest.approx(1.0)


def test_decay_without_hits_is_zero():
    """没被命中过 ⇒ 0 分（不是「按时间还很新所以满分」）。"""
    assert lifecycle.decay_score(make_card(hits=0, last_hit_at=NOW), NOW) == 0.0


def test_decay_uses_last_hit_before_activation_timestamp():
    """时间锚点优先级：`last_hit_at` > `activated_at` > `created_at`（用错锚点 ⇒ 分数偏大）。"""
    card = make_card(
        hits=2,
        last_hit_at=NOW - timedelta(days=90),
        activated_at=NOW - timedelta(days=1),
    )
    assert lifecycle.decay_score(card, NOW) == pytest.approx(1.0)


# ── 退役：两个条件同时成立 + 可审计原因 ─────────────────────────────────────


def test_auto_retire_is_disabled_by_default():
    """默认关 ⇒ 不判、不动作（**不是**「判了但没动」，读数里要区分）。"""
    verdict = lifecycle.retirement_verdict(make_card(), NOW)
    assert verdict["eligible"] is False
    assert verdict["reason"] == "disabled"


def test_retirement_requires_both_idle_days_and_low_decay():
    """① 停滞 61 天 + 0 命中 ⇒ 可退役；② 刚命中过 ⇒ 不可；③ 分数够高 ⇒ 不可。"""
    lifecycle_on = pytest.MonkeyPatch()
    lifecycle_on.setattr(settings, "PLAYBOOK_AUTO_RETIRE_ENABLED", True)
    try:
        idle = make_card(hits=0, last_hit_at=None, activated_at=NOW - timedelta(days=61))
        assert lifecycle.retirement_verdict(idle, NOW)["eligible"] is True

        # 只证明「分数低」不够：刚上线 5 天、0 命中的卡分数也是 0，但它**不该**退役
        # （缺这条，「只判分数」的实现照样绿 —— 两个条件里的天数那一条就成了摆设）
        recent = make_card(hits=0, last_hit_at=None, activated_at=NOW - timedelta(days=5))
        recent_verdict = lifecycle.retirement_verdict(recent, NOW)
        assert recent_verdict["eligible"] is False
        assert recent_verdict["reason"] == "not_idle"

        fresh = make_card(hits=1, last_hit_at=NOW - timedelta(days=1))
        assert lifecycle.retirement_verdict(fresh, NOW)["eligible"] is False

        # 61 天没涨（hits=8）但衰减分 8*0.5^(61/90) ≈ 5.0 > 0.5 ⇒ 不许退役
        busy = make_card(hits=8, last_hit_at=NOW - timedelta(days=61))
        verdict = lifecycle.retirement_verdict(busy, NOW)
        assert verdict["eligible"] is False
        assert verdict["reason"] == "decay_above_threshold"
    finally:
        lifecycle_on.undo()


def test_retirement_reason_is_auditable():
    """原因必须带**读数**（停滞天数 + 衰减分 + 阈值），不能只写一句「自动退役」。"""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "PLAYBOOK_AUTO_RETIRE_ENABLED", True)
        verdict = lifecycle.retirement_verdict(make_card(id="pb_old"), NOW)
    assert verdict["eligible"] is True
    reason = verdict["reason"]
    assert "90" in reason
    assert "0.000" in reason
    assert "0.5" in reason
    assert verdict["id"] == "pb_old"


def test_sweep_refuses_to_judge_when_hit_tracking_is_off():
    """自动退役开了但命中追踪关了 ⇒ **不可判定**（不是「0 条可退役」的假绿）。"""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "PLAYBOOK_AUTO_RETIRE_ENABLED", True)
        mp.setattr(settings, "PLAYBOOK_HIT_TRACKING_ENABLED", False)
        result = lifecycle.retire_sweep(cards=[make_card()], now=NOW)
    assert result["judged"] is False
    assert "hit_tracking" in result["reason"]


def test_retire_sql_is_cas_on_active_and_tenant_scoped():
    sql = " ".join(lifecycle._RETIRE_SQL.split())
    assert "SET state = 'retired'" in sql
    assert "lifecycle_reason = :reason" in sql
    assert "reviewed_by = 'system:auto-retire'" in sql
    assert "WHERE id = :id AND tenant_id = :tenant_id AND state = 'active'" in sql


# ── 晋升：N 个不同员工复现 ⇒ tenant 级 ──────────────────────────────────────


def test_promotion_requires_n_distinct_employees():
    """同一员工复现两次不算第二个人（`COUNT(DISTINCT employee_id)` 的语义）。"""
    key = identity.playbook_key(TRIGGER)
    value = identity.value_key(TRIGGER, "整卷优先")
    draft = make_card(id="pb_draft", state="draft")
    counts = {(key, value): 2}

    below = lifecycle.plan_promotions([draft], counts, active_group_keys=set(), min_employees=3)
    assert below["promotions"] == []
    assert below["below_threshold"][0]["employees"] == 2

    enough = lifecycle.plan_promotions([draft], counts | {(key, value): 3}, active_group_keys=set(), min_employees=3)
    assert [p["id"] for p in enough["promotions"]] == ["pb_draft"]


def test_promotion_never_creates_a_second_active_in_the_same_group():
    """同组已有 active ⇒ **拒绝晋升**（冲突消解前置：否则晋升自己就造出两条矛盾卡）。"""
    draft = make_card(id="pb_draft", state="draft")
    key = identity.playbook_key(TRIGGER)
    value = identity.value_key(TRIGGER, "整卷优先")
    result = lifecycle.plan_promotions(
        [draft], {(key, value): 9}, active_group_keys={key}, min_employees=3
    )
    assert result["promotions"] == []
    assert result["blocked"][0]["reason"] == "conflict_active"
    assert result["blocked"][0]["id"] == "pb_draft"


def test_promotion_only_applies_to_tenant_scope():
    """P2 晋升面只做 tenant（role 口径的晋升需要另一套「岗位内复现」数据，未做）。"""
    role_card = make_card(id="pb_role", state="draft", scope="role", scope_role="sales")
    key = identity.playbook_key(TRIGGER, scope="role", scope_role="sales")
    value = identity.value_key(TRIGGER, "整卷优先", scope="role", scope_role="sales")
    result = lifecycle.plan_promotions(
        [role_card], {(key, value): 9}, active_group_keys=set(), min_employees=3
    )
    assert result["promotions"] == []
    assert result["blocked"][0]["reason"] == "scope_not_tenant"


def test_promotion_plan_is_deterministic():
    """同一输入 ⇒ 同一顺序（按 id 排序）：后台 sweep 的输出可以逐字节复算。"""
    a = make_card(id="pb_b", state="draft")
    b = make_card(id="pb_a", state="draft")
    key = identity.playbook_key(TRIGGER)
    value = identity.value_key(TRIGGER, "整卷优先")
    result = lifecycle.plan_promotions([a, b], {(key, value): 5}, active_group_keys=set(), min_employees=3)
    assert [p["id"] for p in result["promotions"]] == ["pb_a", "pb_b"]


def test_promote_sql_is_cas_on_draft():
    sql = " ".join(lifecycle._PROMOTE_SQL.split())
    assert "SET state = 'active'" in sql
    assert "reviewed_by = 'system:promotion'" in sql
    assert "lifecycle_reason = :reason" in sql
    assert "WHERE id = :id AND tenant_id = :tenant_id AND state = 'draft'" in sql


def test_reproduction_count_sql_counts_distinct_employees():
    """改成 `COUNT(*)` 就把「一个人复现两次」读成「两个人复现」⇒ 晋升判据空转。"""
    sql = " ".join(lifecycle._REPRODUCTION_COUNT_SQL.split())
    assert "COUNT(DISTINCT employee_id)" in sql
    assert "GROUP BY playbook_key, value_key" in sql


# ── 配置默认值：默认不改变线上行为 ──────────────────────────────────────────


def test_default_settings_keep_the_new_paths_off():
    """晋升 / 自动退役默认关；冲突审批守卫（写面）默认开（恒开，不做开关）。"""
    fields = Settings.model_fields
    assert fields["PLAYBOOK_AUTO_RETIRE_ENABLED"].default is False
    assert fields["PLAYBOOK_PROMOTION_ENABLED"].default is False
    assert fields["PLAYBOOK_PROMOTION_MIN_EMPLOYEES"].default == 3
    assert fields["PLAYBOOK_DECAY_HALF_LIFE_DAYS"].default == 90.0
