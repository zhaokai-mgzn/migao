# case_ids: MC-230
"""口径卡条件语言（issue #8175 判据 2）：`trigger` / `counter` 必须**机器可判**。

这里的红证是**内存变异**（与仓内既有口径一致：改磁盘的变异可能不被读到）：
把条件换成自由文本 / 未知算子 / 类型不对的 value ⇒ 同一批判据当场判红并具名。
"""

import json

import pytest

from app.playbook.condition import (
    MAX_DEPTH,
    OPS,
    describe,
    evaluate,
    is_executable,
    validate,
)

TRIGGER = {"field": "intent", "op": "in", "value": ["quote", "product_quote"]}


def test_valid_condition_is_executable_with_no_problems():
    assert validate(TRIGGER) == []
    assert is_executable(TRIGGER) is True


@pytest.mark.parametrize(
    "bad,expected_fragment",
    [
        ("整卷优先", "必须是 JSON 对象"),
        ("", "必须是 JSON 对象"),
        ({}, "空对象"),
        ({"field": "intent"}, "未知算子"),
        ({"field": "intent", "op": "matches_regex", "value": "x"}, "未知算子"),
        ({"field": "intent", "op": "in", "value": "quote"}, "必须是非空数组"),
        ({"field": "intent", "op": "contains", "value": ["x"]}, "必须是非空字符串"),
        ({"field": "intent", "op": "exists", "value": 1}, "不得带 value"),
        ({"field": "", "op": "eq", "value": "x"}, "缺 field"),
        ({"all": []}, "必须是非空数组"),
        ({"all": [TRIGGER], "any": [TRIGGER]}, "多个组合键"),
        ({"all": [TRIGGER], "field": "intent"}, "不得与其它键共存"),
        ({"all": ["整卷优先"]}, "all[0]: 条件必须是 JSON 对象"),
    ],
)
def test_free_text_and_malformed_conditions_are_rejected(bad, expected_fragment):
    """自由文本 / 结构不合法 ⇒ 问题清单**具名**报出（判据 2 的负控面）。"""
    problems = validate(bad)
    assert problems, f"应当判红：{json.dumps(bad, ensure_ascii=False)}"
    assert any(expected_fragment in p for p in problems), problems
    assert is_executable(bad) is False


def test_depth_limit_is_enforced():
    condition = {"field": "intent", "op": "eq", "value": "quote"}
    for _ in range(MAX_DEPTH + 2):
        condition = {"not": condition}
    assert any("嵌套超过" in p for p in validate(condition))


def test_operators_whitelist_is_exactly_the_documented_eight():
    assert OPS == (
        "eq",
        "ne",
        "in",
        "not_in",
        "contains",
        "not_contains",
        "exists",
        "not_exists",
    )


def test_evaluate_semantics_for_every_operator():
    context = {"intent": "quote", "user_text": "我们整卷优先"}
    assert evaluate({"field": "intent", "op": "eq", "value": "quote"}, context) is True
    assert evaluate({"field": "intent", "op": "ne", "value": "quote"}, context) is False
    assert evaluate({"field": "intent", "op": "in", "value": ["quote"]}, context) is True
    assert evaluate({"field": "intent", "op": "not_in", "value": ["quote"]}, context) is False
    assert evaluate({"field": "user_text", "op": "contains", "value": "整卷"}, context) is True
    assert evaluate({"field": "user_text", "op": "not_contains", "value": "整卷"}, context) is False
    assert evaluate({"field": "intent", "op": "exists"}, context) is True
    assert evaluate({"field": "role", "op": "not_exists"}, context) is True


def test_missing_context_field_is_fail_closed():
    """语境缺字段 ⇒ 叶子为假（宁可不用，不可乱用）。"""
    assert evaluate(TRIGGER, {}) is False
    assert evaluate({"field": "intent", "op": "not_in", "value": ["quote"]}, {}) is False
    assert evaluate({"any": [TRIGGER, {"field": "role", "op": "eq", "value": "admin"}]}, {}) is False


def test_evaluate_never_raises_on_hostile_input():
    for hostile in (None, "整卷优先", [], {}, {"field": "x", "op": "eq", "value": {"a": 1}}):
        assert evaluate(hostile, None) is False


def test_composites():
    context = {"intent": "quote", "skill": "product"}
    both = {"all": [TRIGGER, {"field": "skill", "op": "eq", "value": "product"}]}
    either = {"any": [{"field": "skill", "op": "eq", "value": "order"}, TRIGGER]}
    negated = {"not": {"field": "skill", "op": "eq", "value": "order"}}
    assert evaluate(both, context) is True
    assert evaluate(either, context) is True
    assert evaluate(negated, context) is True
    assert evaluate(both, {"intent": "quote"}) is False


def test_describe_renders_from_structure_and_refuses_free_text():
    assert describe(TRIGGER) == "意图属于［quote、product_quote］"
    assert describe("整卷优先") == ""
    both = {"all": [TRIGGER, {"field": "role", "op": "eq", "value": "sales"}]}
    assert describe(both) == "（且 意图属于［quote、product_quote］；岗位等于「sales」）"
