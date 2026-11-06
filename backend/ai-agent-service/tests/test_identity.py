# case_ids: MC-230
"""口径卡的**身份**（issue #8175 P2）：同一条口径的 key 稳定、与键顺序无关、`correct` 不参与。

这四个判据都在防同一类事故：**同一条口径被算成两条不同的 key**（或反过来），
而它不会让任何功能测试红 —— 只会让「冲突消解」漏掉真正矛盾的两条，或把两条不同的口径
误判成冲突（后者的代价是：一条企业口径被另一条无理由地挤掉）。

红证（改任意一条即红）：把 `canonical` 的 `sort_keys` 去掉 ⇒ 顺序无关判据红；
把 `value_key` 里的 `correct` 去掉 ⇒ 不同说法同 key ⇒ 晋升计数会把两种说法合并。
"""

from app.playbook import identity

TRIGGER = {"field": "user_text", "op": "contains", "value": "整卷"}
REORDERED = {"value": "整卷", "op": "contains", "field": "user_text"}


def test_canonical_is_key_order_insensitive_and_keeps_chinese():
    assert identity.canonical(TRIGGER) == identity.canonical(REORDERED)
    assert "整卷" in identity.canonical(TRIGGER)
    assert " " not in identity.canonical(TRIGGER)


def test_playbook_key_is_stable_and_order_insensitive():
    assert identity.playbook_key(TRIGGER) == identity.playbook_key(REORDERED)
    assert identity.playbook_key(TRIGGER) == identity.playbook_key(TRIGGER)
    assert len(identity.playbook_key(TRIGGER)) == 16


def test_scope_and_role_are_part_of_the_identity():
    """岗位口径与全企业口径是**两条**口径（同 trigger 也不能并成一条）。"""
    tenant_key = identity.playbook_key(TRIGGER, scope="tenant")
    role_key = identity.playbook_key(TRIGGER, scope="role", scope_role="sales")
    other_role = identity.playbook_key(TRIGGER, scope="role", scope_role="designer")
    assert len({tenant_key, role_key, other_role}) == 3


def test_value_key_distinguishes_the_two_statements_of_the_same_identity():
    """同 identity 两个说法 ⇒ 两个 value_key（晋升计数按说法分组，不合并）。"""
    key_a = identity.value_key(TRIGGER, "整卷优先")
    key_b = identity.value_key(TRIGGER, "整卷不用优先")
    assert key_a != key_b
    assert key_a == identity.value_key(REORDERED, "整卷优先")


def test_group_key_is_computed_from_content_not_from_the_stored_marker():
    """读面兜底不得信任落库标记：同一内容、不同 `conflict_key`（甚至 NULL）⇒ 同组。"""
    first = {"trigger": TRIGGER, "scope": "tenant", "scope_role": None, "conflict_key": None}
    second = {"trigger": dict(REORDERED), "scope": "tenant", "scope_role": None, "conflict_key": "stale"}
    assert identity.group_key(first) == identity.group_key(second)
