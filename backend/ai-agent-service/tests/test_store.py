# case_ids: MC-230
"""口径卡读面（issue #8175 判据 4 / 5）：租户隔离是**两层**、退役**立即**生效。

这里的红证都是注入式：① 伪造「SQL 漏了租户条件」的读面（同一批行里混进 B 租户的卡）
⇒ B 的卡不许露头；② 同一 store 实例上 retire 后**立刻**再读 ⇒ 必须读不到（任何进程内缓存
都会让这条红 —— 退役是库内状态变更，进程无从感知）。
"""

import json

import pytest

from app.playbook.prompt import render_playbook_block
from app.playbook.store import PlaybookStore

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


# ── 判据 4：租户隔离 ────────────────────────────────────────────────────────

COLUMNS = (
    "id", "tenant_id", "scope", "scope_role", "trigger_json", "correct_text",
    "counter_json", "source_session_id", "source_turn", "hits", "state",
)


def row(card):
    import json

    return (
        card["id"],
        card["tenant_id"],
        card["scope"],
        card["scope_role"],
        json.dumps(card["trigger"], ensure_ascii=False),
        card["correct"],
        json.dumps(card["counter"], ensure_ascii=False) if card["counter"] is not None else None,
        card["source"]["session_id"],
        card["source"]["turn"],
        card["hits"],
        card["state"],
    )


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class FakeSession:
    """最小可用的假会话：记录 SQL / 参数，返回**调用方塞进来的行**。

    故意**不**替被测代码做租户过滤 —— 只有那样，「应用层第二层过滤」才真的被考到。
    """

    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    async def execute(self, sql, params):
        self.calls.append((str(sql), dict(params)))
        return FakeResult(list(self.rows))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_tenant_isolation_holds_even_if_the_query_leaks_other_tenants():
    """把 B 租户的卡混进返回行（模拟「SQL 漏了租户条件」）⇒ A 的读面里一条都不许有。"""
    mine = make_card(id="pb_mine", tenant_id=1, correct="我的口径")
    theirs = make_card(id="pb_theirs", tenant_id=2, correct="别人的口径")
    session = FakeSession([row(mine), row(theirs)])

    playbooks = await PlaybookStore(db_session=session).list_active(1)

    assert [p["id"] for p in playbooks] == ["pb_mine"]
    block = render_playbook_block(playbooks, {"intent": "quote"})
    assert "我的口径" in block
    assert "别人的口径" not in block

    sql, params = session.calls[0]
    assert "WHERE tenant_id = :tenant_id" in sql
    assert params["tenant_id"] == 1


@pytest.mark.asyncio
async def test_missing_tenant_id_reads_nothing():
    """没有租户 ⇒ 空列表（**不许**退化成「查全表」）。"""
    session = FakeSession([row(make_card(tenant_id=1))])
    assert await PlaybookStore(db_session=session).list_active(0) == []
    assert session.calls == []


@pytest.mark.asyncio
async def test_role_scope_only_applies_to_the_matching_role():
    tenant_card = make_card(id="pb_tenant", correct="全企业口径")
    role_card = make_card(id="pb_role", scope="role", scope_role="sales", correct="销售口径")
    store = PlaybookStore(db_session=FakeSession([row(tenant_card), row(role_card)]))

    assert [p["id"] for p in await store.list_active(1, role="sales")] == ["pb_tenant", "pb_role"]
    assert [p["id"] for p in await store.list_active(1, role=None)] == ["pb_tenant"]


# ── 判据 5：退役立即生效（读面不缓存）──────────────────────────────────────


@pytest.mark.asyncio
async def test_retire_takes_effect_immediately_on_the_same_store_instance():
    session = FakeSession([row(make_card(id="pb_1", state="active"))])
    store = PlaybookStore(db_session=session)

    assert [p["id"] for p in await store.list_active(1)] == ["pb_1"]

    # 退役 = 库内状态变更；进程无从感知 ⇒ 任何进程内缓存都会让下面这条红
    session.rows = [row(make_card(id="pb_1", state="retired"))]
    assert await store.list_active(1) == []


@pytest.mark.asyncio
async def test_retire_removes_the_card_from_the_prompt_on_the_next_turn():
    session = FakeSession([row(make_card(id="pb_1", correct="整卷优先"))])
    store = PlaybookStore(db_session=session)
    before = render_playbook_block(await store.list_active(1), {"intent": "quote"})
    assert "<do>整卷优先</do>" in before

    session.rows = [row(make_card(id="pb_1", correct="整卷优先", state="retired"))]
    after = render_playbook_block(await store.list_active(1), {"intent": "quote"})
    assert "整卷优先" not in after
