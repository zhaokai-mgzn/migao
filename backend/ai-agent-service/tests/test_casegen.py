# case_ids: MC-230
"""口径卡出口③（issue #8175 判据 2 / 3 / 6）：从 `trigger` + `counter` 生成**真能跑**的用例。

「真能跑」在这里是可验的：生成物带机器载荷（`traces.playbook`），`run_case` 用它与
**生产同一条判定链**去算 passed/failed。判据 3 的红证 = 把判定链换成坏引擎
（不读 counter / 不看 state）⇒ 同一份生成物**当场 failed**。
"""

import copy

import pytest

from app.playbook import prompt as prompt_module
from app.playbook.casegen import (
    PlaybookNotExecutable,
    cases_digest,
    generate_case,
    generate_cases,
    run_case,
)

TRIGGER = {"field": "intent", "op": "in", "value": ["quote"]}
COUNTER = {"field": "user_text", "op": "contains", "value": "零裁"}


def make_card(**overrides):
    card = {
        "id": "pb_1",
        "tenant_id": 1,
        "scope": "tenant",
        "scope_role": None,
        "trigger": dict(TRIGGER),
        "correct": "报价默认按整卷走",
        "counter": dict(COUNTER),
        "source": {"session_id": "sess-1", "turn": 3},
        "hits": 0,
        "state": "active",
    }
    card.update(overrides)
    return card


REQUIRED_KEYS = (
    "id", "legacy_id", "title", "domains", "tier", "tags", "truths_ref",
    "user_inputs", "expectations", "data_checks", "skip_reason", "merge_log", "traces",
)


# ── 判据 3：生成物是「本仓用例 schema」的形态 ──────────────────────────────


def test_generated_case_carries_the_real_case_schema():
    case = generate_case(make_card())
    assert tuple(case.keys()) == REQUIRED_KEYS
    assert case["domains"] == ["agent", "playbook"]
    assert case["truths_ref"] == []
    assert case["skip_reason"] == ""
    assert case["id"] == "PB-pb_1"
    assert case["expectations"] == [{"tool": "direct_reply"}]


def test_generated_case_is_deterministic():
    """同一张卡连生成两次 ⇒ 逐字节相同（非确定性会让「用例」变成第二个真相源）。"""
    card = make_card()
    assert cases_digest([generate_case(card)]) == cases_digest([generate_case(copy.deepcopy(card))])


# ── 判据 3：生成物**真能跑** ───────────────────────────────────────────────


def test_generated_case_runs_and_passes_against_the_production_judgement_chain():
    card = make_card()
    case = generate_case(card)
    result = run_case(case, [card])
    assert result["passed"] is True
    assert [c["name"] for c in result["checks"]] == [
        "trigger_fires",
        "prompt_contains_rule",
        "counter_blocks",
        "prompt_excludes_rule_on_counter",
    ]
    assert all(c["passed"] for c in result["checks"])


def test_red_proof_engine_that_ignores_counter_fails_the_generated_case(monkeypatch):
    """**判据 6 的红证**：把选取换成「不读 counter」的坏引擎 ⇒ 反例那条断言必须红。"""
    card = make_card()
    case = generate_case(card)

    def bad_select(playbooks, context=None):
        # 坏引擎：只看 state，不看 counter（= 把反例当注释）
        return [p for p in (playbooks or []) if p.get("state") == "active"]

    monkeypatch.setattr(prompt_module, "select_playbooks", bad_select)
    result = run_case(case, [card])

    assert result["passed"] is False
    failed = [c["name"] for c in result["checks"] if not c["passed"]]
    assert failed == ["counter_blocks", "prompt_excludes_rule_on_counter"]


def test_red_proof_engine_that_ignores_state_flips_the_generated_case(monkeypatch):
    """判据 1 的红证（出口③面）：**单变量对照** —— 换掉状态过滤，同一份生成物结论翻转。

    正确引擎：语料里那张卡是 draft ⇒ 不生效 ⇒ 用例红（这正是我们要的：容器把 draft
    放行才会「绿」）。坏引擎（不看 state）：同一份用例反而变绿 ⇒ 证明这条断言有牙。
    """
    card = make_card()
    case = generate_case(card)
    draft_corpus = [make_card(state="draft")]

    assert run_case(case, draft_corpus)["passed"] is False

    from app.playbook.condition import evaluate

    def bad_select(playbooks, context=None):
        # 单变量：只摘掉状态过滤，反例判定照旧（否则「翻转」归因不清）
        out = []
        for p in playbooks or []:
            counter = p.get("counter")
            if context is not None and counter is not None and evaluate(counter, context):
                continue
            out.append(p)
        return out

    monkeypatch.setattr(prompt_module, "select_playbooks", bad_select)
    assert run_case(case, draft_corpus)["passed"] is True


# ── 判据 2 / 6：生成器拒绝「不可判」的卡（不降级成少几条断言）────────────


@pytest.mark.parametrize(
    "overrides,expected_fragment",
    [
        ({"state": "draft"}, "只有 active"),
        ({"state": "retired"}, "只有 active"),
        ({"trigger": "整卷优先"}, "trigger 不可执行"),
        ({"trigger": {"field": "intent", "op": "模糊匹配", "value": "整卷"}}, "trigger 不可执行"),
        ({"counter": "除非客户要零裁"}, "counter 不可执行"),
        ({"trigger": {"all": []}}, "trigger 不可执行"),
    ],
)
def test_generator_refuses_cards_that_cannot_be_judged(overrides, expected_fragment):
    with pytest.raises(PlaybookNotExecutable) as excinfo:
        generate_case(make_card(**overrides))
    assert expected_fragment in str(excinfo.value)


def test_generator_refuses_when_the_satisfying_context_cannot_be_constructed():
    """可满足性采样回代验算不成立 ⇒ 拒绝生成（绝不产出一条永远绿的断言）。"""
    contradictory = {
        "all": [
            {"field": "intent", "op": "eq", "value": "quote"},
            {"field": "intent", "op": "eq", "value": "order"},
        ]
    }
    with pytest.raises(PlaybookNotExecutable) as excinfo:
        generate_case(make_card(trigger=contradictory))
    assert "满足语境无法构造" in str(excinfo.value)


def test_generate_cases_skips_unjudgeable_cards_but_keeps_the_rest():
    good = make_card(id="pb_good")
    bad = make_card(id="pb_bad", trigger="整卷优先")
    cases = generate_cases([good, bad])
    assert [c["id"] for c in cases] == ["PB-pb_good"]


def test_case_without_counter_records_that_fact_instead_of_a_comment():
    case = generate_case(make_card(id="pb_nc", counter=None))
    assert "**本卡无反例**" in " ".join(case["data_checks"])
    assert case["traces"]["playbook"]["has_counter"] is False
    assert case["traces"]["playbook"]["counter_context"] is None
    assert run_case(case, [make_card(id="pb_nc", counter=None)])["passed"] is True


def test_counter_context_satisfies_both_trigger_and_counter():
    """反例语境必须「触发仍成立 + 反例命中」——否则负向断言分不清是两个原因里的哪一个。"""
    case = generate_case(make_card())
    counter_context = case["traces"]["playbook"]["counter_context"]
    from app.playbook.condition import evaluate

    assert evaluate(COUNTER, counter_context) is True
    assert evaluate(TRIGGER, counter_context) is True


def test_counter_context_is_rejected_when_it_would_cancel_the_trigger():
    """反例语境与触发互斥 ⇒ 拒绝生成（而不是产出一条分不清归因的负向断言）。"""
    conflicting = {"field": "intent", "op": "eq", "value": "aftersale"}
    with pytest.raises(PlaybookNotExecutable) as excinfo:
        generate_case(make_card(counter=conflicting))
    assert "互斥" in str(excinfo.value)
