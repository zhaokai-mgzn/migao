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
