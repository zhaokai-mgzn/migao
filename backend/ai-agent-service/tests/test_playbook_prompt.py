# case_ids: MC-230
"""口径卡出口①（issue #8175）：只有 `active` 进 prompt · 租户隔离 · 退役立即生效。

三个判据的红证都是**注入式**：
- 判据 1：往渲染入参里塞一张 `draft` / 一张 `retired` ⇒ 正文一个字符都不许出现；
- 判据 4：伪造「SQL 漏了租户条件」的读面（同一批行里混进 B 租户的卡）⇒ B 的卡不许露头；
- 判据 5：同一 store 实例上 retire 后**立刻**再读 ⇒ 必须读不到（任何缓存都会让这条红）。
"""

from pathlib import Path

import pytest

from app.playbook.prompt import (
    PROMPT_HEADER,
    inject_playbook_prompt,
    render_playbook_block,
    select_playbooks,
)
from app.playbook.store import PlaybookStore

REPO_ROOT = Path(__file__).resolve().parents[3]

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


# ── 判据 1：只有 active 的卡进 prompt ────────────────────────────────────────


@pytest.mark.parametrize("state", ["draft", "retired"])
def test_non_active_state_never_reaches_the_prompt(state):
    """注入一张 draft / retired ⇒ 它的正文**一个字符都不许**出现在 prompt 片段里。"""
    block = render_playbook_block([make_card(state=state)], {"intent": "quote"})
    assert block == ""


def test_active_card_does_reach_the_prompt():
    """反向对照：同一张卡改成 active ⇒ 必须在（否则「过滤」把好东西也滤掉了）。"""
    block = render_playbook_block([make_card()], {"intent": "quote"})
    assert PROMPT_HEADER in block
    assert "<do>报价默认按整卷走</do>" in block
    assert "<when>意图属于［quote］</when>" in block
    assert "<except>用户原话包含「零裁」（命中例外时不套用本口径）</except>" in block


def test_mixed_input_only_lets_active_through():
    """一次给三张（active / draft / retired）⇒ 只有 active 那张出现，且**具名**核对。"""
    block = render_playbook_block(
        [
            make_card(id="pb_active", correct="整卷优先"),
            make_card(id="pb_draft", state="draft", correct="草稿口径"),
            make_card(id="pb_retired", state="retired", correct="已退役口径"),
        ],
        {"intent": "quote"},
    )
    assert '<rule id="pb_active"' in block
    assert "pb_draft" not in block
    assert "草稿口径" not in block
    assert "pb_retired" not in block
    assert "已退役口径" not in block


def test_free_text_trigger_is_not_executable_and_drops_the_card():
    """判据 2 的出口面：自由文本 trigger ⇒ 整张卡不出现在 prompt（不是「原样塞进去」）。"""
    block = render_playbook_block([make_card(trigger="整卷优先")], {"intent": "quote"})
    assert block == ""


def test_unexecutable_counter_drops_the_card():
    """判据 6 的出口面：反例不可判 = 注释 ⇒ 整卡不用（宁可不用，不可乱用）。"""
    block = render_playbook_block([make_card(counter="除非客户要零裁")], {"intent": "quote"})
    assert block == ""


def test_counter_hit_removes_the_card_at_render_time():
    """反例真的进判定面：反例命中的语境下，同一张卡不出现。"""
    hit = render_playbook_block([make_card()], {"intent": "quote", "user_text": "这次要零裁"})
    assert hit == ""
    miss = render_playbook_block([make_card()], {"intent": "quote", "user_text": "整卷"})
    assert '<rule id="pb_1"' in miss


def test_select_playbooks_caps_at_documented_limit():
    cards = [make_card(id=f"pb_{i}") for i in range(20)]
    assert len(select_playbooks(cards, {"intent": "quote"})) == 12


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


# ── 出口①接线：C 端零回归 + B 端真注入 ────────────────────────────────────


@pytest.mark.asyncio
async def test_c_end_is_untouched_and_returns_the_same_object():
    prompt = "你是元元"
    out = await inject_playbook_prompt(prompt, {"agent_type": "xiaobu", "tenant_id": 1})
    assert out is prompt


@pytest.mark.asyncio
async def test_b_end_prompt_really_gets_the_block(monkeypatch):
    async def fake_list_active(self, tenant_id, role=None):
        assert tenant_id == 7
        return [make_card(tenant_id=7, correct="整卷优先")]

    monkeypatch.setattr(
        "app.playbook.prompt.PlaybookStore.list_active", fake_list_active
    )
    out = await inject_playbook_prompt(
        "原 system prompt", {"agent_type": "mibao", "tenant_id": 7, "skill_name": "product"}, "product"
    )
    assert out.startswith(PROMPT_HEADER)
    assert "<do>整卷优先</do>" in out
    assert out.endswith("\n原 system prompt")


def test_injection_is_wired_into_the_turn_assembly():
    """删接线 ⇒ 红：`prepare_turn` 必须在 system prompt 组装序列里调用注入。"""
    source = (REPO_ROOT / "backend/ai-agent-service/app/graph/skills/execution/prepare_turn.py").read_text()
    build_at = source.index("system_prompt = _build_system_prompt(")
    inject_at = source.index("system_prompt = await inject_playbook_prompt(system_prompt, state, skill_name)")
    assert build_at < inject_at, "口径卡注入必须在 _build_system_prompt 之后（口径比临时提示更靠前）"
    assert "from app.playbook.prompt import inject_playbook_prompt" in source
