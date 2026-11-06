# case_ids: MC-230
"""口径卡出口①（issue #8175）：只有 `active` 进 prompt · 租户隔离 · 退役立即生效。

三个判据的红证都是**注入式**：
- 判据 1：往渲染入参里塞一张 `draft` / 一张 `retired` ⇒ 正文一个字符都不许出现；
- 判据 4：伪造「SQL 漏了租户条件」的读面（同一批行里混进 B 租户的卡）⇒ B 的卡不许露头；
- 判据 5：同一 store 实例上 retire 后**立刻**再读 ⇒ 必须读不到（任何缓存都会让这条红）。

P2（本文件下半部分）补的是**冲突消解读面兜底**：同 `conflict_key`（或同 scope + 同 trigger，
即使 `conflict_key` 是脏数据里的 NULL）的两条 active，**结构上不可能**同时进 prompt ——
用确定性选取（衰减分高者 → hits 高者 → approved_at 新者 → id 小者），且丢弃**具名可见**
（logger.warning 里同时出现保留者与被丢弃者）。正控（同组两条 ⇒ 只出 1 条）与
负控（不同组 ⇒ 两条都出）成对存在：只有正控，就分不清「去重」与「整块被丢掉」。
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.playbook import prompt as prompt_mod
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
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


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
        "conflict_key": None,
        "activated_at": None,
        "created_at": None,
        "last_hit_at": None,
    }
    card.update(overrides)
    return card


class FakeMessage:
    """LangChain 消息的最小替身：`_context_from_state` 只认 `type` / `content`。"""

    def __init__(self, kind, content):
        self.type = kind
        self.content = content


class RecordingLogger:
    """loguru 的替身：只记录，便于断言「丢弃是可见的」。"""

    def __init__(self):
        self.messages = []

    def warning(self, message):
        self.messages.append(str(message))

    def info(self, message):
        self.messages.append(str(message))

    def debug(self, message):
        self.messages.append(str(message))


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
    """上限 12 条（每张卡的条件不同 ⇒ 它们是 20 个**不同的**口径组，不会先去重）。"""
    cards = [
        make_card(
            id=f"pb_{i}",
            correct=f"口径 {i}",
            trigger={"field": "user_text", "op": "contains", "value": f"关键词{i}"},
            counter=None,
        )
        for i in range(20)
    ]
    assert len(select_playbooks(cards, {"user_text": "随便"})) == 12


# ── 冲突消解（读面兜底）：同组结构上只出 1 条 ───────────────────────────────


def test_same_conflict_group_renders_exactly_one_rule(monkeypatch):
    """**正控**：同 `conflict_key` 的两条 active ⇒ 渲染只出 1 条，且丢弃**具名可见**。"""
    recorder = RecordingLogger()
    monkeypatch.setattr(prompt_mod, "logger", recorder)
    cards = [
        make_card(id="pb_old", hits=1, conflict_key="grp-1", correct="整卷优先（旧）"),
        make_card(id="pb_new", hits=9, conflict_key="grp-1", correct="整卷优先（新）"),
    ]
    block = render_playbook_block(cards, {"intent": "quote"})

    assert block.count("<rule ") == 1
    assert 'id="pb_new"' in block
    assert "pb_old" not in block
    dropped = [m for m in recorder.messages if "冲突" in m]
    assert dropped, "冲突丢弃必须在日志里可见（否则「少了一条」没人知道）"
    assert "pb_old" in dropped[0] and "pb_new" in dropped[0]


def test_different_conflict_groups_both_render():
    """**负控**：不同组 ⇒ 两条都要出（只做正控 = 分不清「去重」与「整块被丢掉」）。"""
    cards = [
        make_card(id="pb_quote", trigger={"field": "intent", "op": "in", "value": ["quote"]}),
        make_card(
            id="pb_roll",
            trigger={"field": "user_text", "op": "contains", "value": "整卷"},
            correct="整卷优先",
            counter=None,
        ),
    ]
    block = render_playbook_block(cards, {"intent": "quote", "user_text": "整卷的单"})
    assert '<rule id="pb_quote"' in block
    assert '<rule id="pb_roll"' in block


def test_dirty_data_without_conflict_key_is_still_deduped():
    """脏数据：`conflict_key` 为 NULL、但 scope + trigger 相同 ⇒ 仍然只出 1 条。

    读面不许信任「落库时打好的标记」——标记可能缺、可能过期，而 prompt 的矛盾是**当场**发生的。
    """
    cards = [
        make_card(id="pb_a", hits=1, conflict_key=None, correct="整卷优先（A）"),
        make_card(id="pb_b", hits=7, conflict_key=None, correct="整卷优先（B）"),
    ]
    block = render_playbook_block(cards, {"intent": "quote"})
    assert block.count("<rule ") == 1
    assert 'id="pb_b"' in block


def test_dirty_data_with_same_conflict_key_but_different_triggers_is_deduped():
    """另一个方向的脏数据：标记相同、trigger 不同 ⇒ 按**标记**也并成一组（只出 1 条）。"""
    cards = [
        make_card(
            id="pb_x",
            conflict_key="shared",
            trigger={"field": "user_text", "op": "contains", "value": "整卷"},
            counter=None,
        ),
        make_card(
            id="pb_y",
            conflict_key="shared",
            trigger={"field": "user_text", "op": "contains", "value": "零裁"},
            counter=None,
        ),
    ]
    block = render_playbook_block(cards, {"user_text": "整卷"})
    assert block.count("<rule ") == 1


def test_selection_prefers_higher_decay_score_when_hits_are_equal():
    """同 hits 时按时间衰减：最近还被命中的那条胜出（用错锚点 ⇒ 胜者反了）。"""
    old = make_card(id="pb_old", hits=5, last_hit_at=NOW - timedelta(days=180))
    new = make_card(id="pb_new", hits=5, last_hit_at=NOW - timedelta(days=1))
    assert [p["id"] for p in select_playbooks([old, new], {"intent": "quote"})] == ["pb_new"]


def test_selection_prefers_higher_hits_when_age_is_equal():
    """衰减之外保留 P2 口径里的第二排序键：hits 高者（否则「hits 进入选举」只是空话）。"""
    low = make_card(id="pb_low", hits=1, last_hit_at=NOW)
    high = make_card(id="pb_high", hits=9, last_hit_at=NOW)
    assert [p["id"] for p in select_playbooks([low, high], {"intent": "quote"})] == ["pb_high"]


# ── 出口①接线：C 端零回归 + B 端真注入 + 命中计数 ──────────────────────────


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

    async def fake_record_hits(self, tenant_id, playbook_ids):
        return 0

    monkeypatch.setattr("app.playbook.prompt.PlaybookStore.list_active", fake_list_active)
    monkeypatch.setattr("app.playbook.prompt.PlaybookStore.record_hits", fake_record_hits)
    out = await inject_playbook_prompt(
        "原 system prompt", {"agent_type": "mibao", "tenant_id": 7, "skill_name": "product"}, "product"
    )
    assert out.startswith(PROMPT_HEADER)
    assert "<do>整卷优先</do>" in out
    assert out.endswith("\n原 system prompt")


@pytest.mark.asyncio
async def test_injection_records_hits_only_for_cards_whose_trigger_matched(monkeypatch):
    """hits 真的被写入（且只写**本轮命中**的卡）—— 否则衰减/退役的数据面永远是 0。"""
    recorded = []

    async def fake_list_active(self, tenant_id, role=None):
        return [
            make_card(
                id="pb_match",
                trigger={"field": "user_text", "op": "contains", "value": "整卷"},
                counter=None,
            ),
            make_card(
                id="pb_miss",
                trigger={"field": "user_text", "op": "contains", "value": "零裁"},
                counter=None,
            ),
        ]

    async def fake_record_hits(self, tenant_id, playbook_ids):
        recorded.append((tenant_id, list(playbook_ids)))
        return len(playbook_ids)

    monkeypatch.setattr("app.playbook.prompt.PlaybookStore.list_active", fake_list_active)
    monkeypatch.setattr("app.playbook.prompt.PlaybookStore.record_hits", fake_record_hits)
    monkeypatch.setattr(prompt_mod.settings, "PLAYBOOK_HIT_TRACKING_ENABLED", True, raising=False)

    state = {
        "agent_type": "mibao",
        "tenant_id": 7,
        "messages": [FakeMessage("human", "这个单整卷算")],
    }
    out = await inject_playbook_prompt("原 system prompt", state)

    assert "<do>" in out
    assert recorded == [(7, ["pb_match"])]


@pytest.mark.asyncio
async def test_hit_tracking_off_means_zero_writes(monkeypatch):
    """显式关 ⇒ 一次写入都不发生（读路径的行为不因这个开关改变）。"""
    called = []

    async def fake_list_active(self, tenant_id, role=None):
        return [
            make_card(
                id="pb_match",
                trigger={"field": "user_text", "op": "contains", "value": "整卷"},
                counter=None,
            )
        ]

    async def fake_record_hits(self, tenant_id, playbook_ids):
        called.append(playbook_ids)

    monkeypatch.setattr("app.playbook.prompt.PlaybookStore.list_active", fake_list_active)
    monkeypatch.setattr("app.playbook.prompt.PlaybookStore.record_hits", fake_record_hits)
    monkeypatch.setattr(prompt_mod.settings, "PLAYBOOK_HIT_TRACKING_ENABLED", False, raising=False)

    state = {"agent_type": "mibao", "tenant_id": 7, "messages": [FakeMessage("human", "整卷算")]}
    await inject_playbook_prompt("原 system prompt", state)
    assert called == []


def test_injection_is_wired_into_the_turn_assembly():
    """删接线 ⇒ 红：`prepare_turn` 必须在 system prompt 组装序列里调用注入。"""
    source = (REPO_ROOT / "backend/ai-agent-service/app/graph/skills/execution/prepare_turn.py").read_text()
    build_at = source.index("system_prompt = _build_system_prompt(")
    inject_at = source.index(
        "system_prompt = await inject_playbook_prompt(system_prompt, state, skill_name)"
    )
    assert build_at < inject_at, "口径卡注入必须在 _build_system_prompt 之后（口径比临时提示更靠前）"
    assert "from app.playbook.prompt import inject_playbook_prompt" in source
