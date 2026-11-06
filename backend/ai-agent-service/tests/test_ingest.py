# case_ids: MC-340
"""口径卡 P1 写面：会话候选 → `draft` 卡 → 人工审核（issue #8175）。

四条判据逐条在这里落红证（都是**注入式**，删接线 / 改回覆盖都会当场红）：

1. 一次「纠正」会话 ⇒ **1 条** `draft` 候选（从 P1a 抽取器一路跑到 INSERT，不手搓候选）；
2. **未审核的卡不得出现在 system prompt**：正控 = 注入 `draft` ⇒ 渲染结果必须为空；
   负控 = 同一张卡改成 `active` ⇒ 必须出现**且带来源**（否则「过滤」把好东西也滤掉了）；
3. 同 key 两个不同值 ⇒ **两条并存并标记冲突**，不是覆盖（同 key 同值 ⇒ 幂等跳过）；
4. 审核通过 ⇒ 进 prompt 且带来源（会话 id + 轮次）；退役 ⇒ 不再出现。

PII / 报价的红证在最后一段：手机号 / 报价 / 中文 PII 词根各一条 ⇒ **整条不产卡**。
"""

import importlib.util
import json
from pathlib import Path

import pytest

from app.playbook import ingest as ingest_mod
from app.playbook.prompt import (
    _context_from_state,
    render_playbook_block,
    select_playbooks,
)
from app.playbook.store import PlaybookStore, _row_to_playbook

REPO_ROOT = Path(__file__).resolve().parents[3]

#: 真实的 P1a 抽取器（不发包、不复制规则：本测试跑的就是线上那一个）
_P1A_PATH = REPO_ROOT / "scripts/distill_agent_sessions.py"


def _p1a():
    spec = importlib.util.spec_from_file_location("distill_agent_sessions", _P1A_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def cand(correct, session_id="sess-1", turn=2, tenant_id=1, category="纠正"):
    """一条 P1a 形态的候选（字段与 scripts/distill_agent_sessions.py 的产物逐位对齐）。"""
    return {
        "tenant_id": tenant_id,
        "session_id": session_id,
        "turn": turn,
        "category": category,
        "trigger_text": correct,
        "context_before": "",
        "confidence": 0.8,
        "reason": "测试构造",
    }


def read_side(row):
    """落库行 → **读面**结构（走 store 的真实列映射，不另写一份）。"""
    return _row_to_playbook(
        (
            row["id"],
            row["tenant_id"],
            row["scope"],
            row["scope_role"],
            row["trigger_json"],
            row["correct_text"],
            row["counter_json"],
            row["source_session_id"],
            row["source_turn"],
            0,
            row["state"],
        )
    )


class Row(dict):
    """假结果行：`load_existing` 用 `row._mapping` 取字典，这里就是它自己。"""

    @property
    def _mapping(self):
        return self


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class FakeSession:
    """最小假会话：记录 SQL / 参数；SELECT 返回调用方塞进来的既有行。"""

    def __init__(self, existing=None):
        self.existing = list(existing or [])
        self.calls = []
        self.commits = 0

    async def execute(self, sql, params):
        self.calls.append((str(sql), dict(params)))
        if str(sql).strip().upper().startswith("SELECT"):
            return FakeResult(self.existing)
        return FakeResult([])

    async def commit(self):
        self.commits += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def statements(self, prefix):
        return [
            (sql, params)
            for sql, params in self.calls
            if sql.strip().upper().startswith(prefix.upper())
        ]


class FakeMessage:
    """LangChain 消息的最小替身：`_context_from_state` 只认 `type` / `content`。"""

    def __init__(self, kind, content):
        self.type = kind
        self.content = content


# ── 判据 1：一次纠正会话 ⇒ 1 条 draft 候选 ─────────────────────────────────


P1A_SESSION = {
    "tenant_id": 1,
    "session_id": "sess-1",
    "agent_type": "mibao",
    "messages": [
        {"role": "user", "content": "整卷这个单怎么算"},
        {"role": "assistant", "content": "按米算，零裁也行"},
        {"role": "user", "content": "不对，我们按整卷算"},
    ],
}


def test_one_correction_session_yields_exactly_one_draft_card():
    """端到端（抽取器 → 计划）：1 条纠正 ⇒ 1 行，状态 **draft**，来源 = 会话 + 轮次。"""
    result = _p1a().distill([P1A_SESSION])
    assert len(result["candidates"]) == 1

    plan = ingest_mod.plan_ingest(result["candidates"], [], tenant_id=1)

    assert len(plan["rows"]) == 1
    row = plan["rows"][0]
    assert row["state"] == "draft"
    assert row["correct_text"] == "不对，我们按整卷算"
    assert row["source_session_id"] == "sess-1"
    assert row["source_turn"] == 2
    assert row["scope"] == "tenant"
    assert json.loads(row["trigger_json"]) == {
        "field": "user_text",
        "op": "contains",
        "value": "整卷",
    }


def test_chitchat_session_produces_no_card():
    """反向对照：同一形态的会话，没有纠正 ⇒ **0 行**（否则判据 1 是「总会产卡」）。"""
    session = {
        "tenant_id": 1,
        "session_id": "sess-2",
        "agent_type": "mibao",
        "messages": [
            {"role": "user", "content": "今天天气不错"},
            {"role": "assistant", "content": "是的"},
        ],
    }
    result = _p1a().distill([session])
    assert result["candidates"] == []
    assert ingest_mod.plan_ingest(result["candidates"], [], tenant_id=1)["rows"] == []


@pytest.mark.asyncio
async def test_apply_writes_draft_rows_and_dry_run_writes_nothing():
    """接线判据：`apply=True` 真的 INSERT（且**硬编码** draft）；`apply=False` 零写。"""
    session = FakeSession()
    dry = await ingest_mod.ingest(session, [cand("不对，我们按整卷算")], 1, apply=False)
    assert dry["planned"] == 1
    assert dry["inserted"] == 0
    assert session.statements("INSERT") == []

    written = await ingest_mod.ingest(session, [cand("不对，我们按整卷算")], 1, apply=True)
    inserts = session.statements("INSERT")
    assert len(inserts) == 1
    sql, params = inserts[0]
    assert "'draft'" in " ".join(sql.split())
    assert params["state"] == "draft"
    assert params["source_session_id"] == "sess-1"
    assert params["source_turn"] == 2
    assert params["conflict_key"] is None
    assert written["inserted"] == 1
    assert session.commits == 1


# ── 判据 2：draft 绝不进 prompt（正控 + 负控）────────────────────────────────


def _card(state="draft", correct="不对，我们按整卷算", session_id="sess-1", turn=2):
    row = ingest_mod.plan_ingest([cand(correct, session_id=session_id, turn=turn)], [], 1)["rows"][0]
    row["state"] = state
    return read_side(row)


def test_positive_control_draft_injection_renders_nothing():
    """**正控**：把刚蒸馏出来的 draft 直接塞进渲染入参 ⇒ 正文一个字符都不许出现。"""
    card = _card(state="draft")
    context = {"user_text": "整卷这个单怎么算", "agent_type": "mibao"}
    block = render_playbook_block([card], context)
    assert block == ""
    assert select_playbooks([card], context) == []


def test_negative_control_active_renders_with_source():
    """**负控**：同一张卡改成 active ⇒ 必须出现，且 `<do>` 与来源（会话 id#轮次）都在。"""
    card = _card(state="active")
    block = render_playbook_block([card], {"user_text": "整卷这个单怎么算", "agent_type": "mibao"})
    assert "<do>不对，我们按整卷算</do>" in block
    assert 'source="sess-1#2"' in block


@pytest.mark.asyncio
async def test_draft_row_is_also_filtered_at_the_store_layer():
    """第二道：即使 SQL 漏了 `state='active'`（读面拿到 draft 行）⇒ 仍然读不到。"""
    row = ingest_mod.plan_ingest([cand("不对，我们按整卷算")], [], 1)["rows"][0]
    fake_row = (
        row["id"], row["tenant_id"], row["scope"], row["scope_role"], row["trigger_json"],
        row["correct_text"], row["counter_json"], row["source_session_id"], row["source_turn"],
        0, "draft",
    )
    store = PlaybookStore(db_session=FakeSession([fake_row]))
    assert await store.list_active(1) == []


def test_runtime_context_carries_user_text_so_the_trigger_can_fire():
    """`user_text` 必须真的进语境：条件语言里有这个字段，语境里没有 = 字段存在但功能不生效。"""
    context = _context_from_state(
        {"agent_type": "mibao", "messages": [FakeMessage("human", "整卷这个单怎么算")]}
    )
    assert context["user_text"] == "整卷这个单怎么算"
    assert render_playbook_block([_card(state="active")], context) != ""


# ── 判据 3：冲突值两条并存 + 标记（不是覆盖）────────────────────────────────


def test_same_key_different_value_coexists_and_is_marked():
    """同 key 两个不同值 ⇒ **两行都在**，且两行都带同一个 `conflict_key`。"""
    a = cand("不对，「整卷」要优先", turn=2)
    b = cand("不对，「整卷」不用优先", turn=4)
    plan = ingest_mod.plan_ingest([a, b], [], tenant_id=1)

    assert len(plan["rows"]) == 2
    correct_texts = sorted(row["correct_text"] for row in plan["rows"])
    assert correct_texts == ["不对，「整卷」不用优先", "不对，「整卷」要优先"]
    conflict_keys = {row["conflict_key"] for row in plan["rows"]}
    assert len(conflict_keys) == 1
    assert None not in conflict_keys
    assert len(plan["conflicts"]) == 1


def test_same_key_same_value_is_idempotent():
    """同 key 同值 ⇒ 只留一条，第二条记 `duplicate`（重跑不会堆重复卡）。"""
    a = cand("不对，「整卷」要优先", turn=2)
    b = cand("不对，「整卷」要优先", turn=6)
    plan = ingest_mod.plan_ingest([a, b], [], tenant_id=1)

    assert len(plan["rows"]) == 1
    assert plan["skip_counts"]["duplicate"] == 1


def test_existing_sibling_is_marked_not_overwritten():
    """库里已有同 key 的卡（不同值）⇒ 新卡照插，**旧卡只补标记**、正解一字不改。"""
    first = ingest_mod.plan_ingest([cand("不对，「整卷」要优先")], [], 1)["rows"][0]
    existing = [
        Row(id="pb_old", trigger_json=first["trigger_json"],
            correct_text="不对，「整卷」不用优先", state="draft")
    ]
    plan = ingest_mod.plan_ingest(
        [cand("不对，「整卷」要优先")], existing, tenant_id=1
    )

    assert len(plan["rows"]) == 1
    assert plan["rows"][0]["conflict_key"] is not None
    assert plan["conflict_updates"] == [
        {
            "id": "pb_old",
            "tenant_id": 1,
            "conflict_key": plan["rows"][0]["conflict_key"],
        }
    ]


def test_mark_sql_only_writes_the_conflict_column():
    """「改回覆盖 ⇒ 红」的源码级第二道：标记语句里**不许出现** `correct_text`，INSERT 不许 upsert。"""
    mark = " ".join(ingest_mod._MARK_CONFLICT_SQL.split())
    assert "correct_text" not in mark
    assert "state" not in mark
    assert "ON CONFLICT" not in " ".join(ingest_mod._INSERT_SQL.split())


# ── 判据 4：审核通过带来源进 prompt / 退役不再出现 ──────────────────────────


def test_retired_card_disappears_from_the_prompt():
    """退役 ⇒ 下一次渲染就没有它（读面不缓存，store 层判据另见 test_store.py）。"""
    card = _card(state="retired")
    block = render_playbook_block([card], {"user_text": "整卷这个单怎么算"})
    assert block == ""


# ── 边界：PII / 报价不得进口径卡（互斥：规则单测在 tests/test_redact.py）──────────


def test_phone_message_is_skipped_before_it_becomes_a_candidate():
    """抽取侧（#2815 家族）：含手机号的会话 ⇒ 0 条候选（P1a 已在原句上拦截）。"""
    session = dict(P1A_SESSION)
    session["messages"] = [
        {"role": "user", "content": "不对，我们按整卷算，有事打 13800138000"},
    ]
    result = _p1a().distill([session])
    assert result["candidates"] == []
    assert result["stats"]["pii_skipped"] == 1


def test_price_candidate_is_rejected_at_ingest():
    """**加严**（P1a 不拦的那一类）：含报价的候选 ⇒ 0 行，原因具名。"""
    plan = ingest_mod.plan_ingest([cand("不对，「整卷」报价 128 元")], [], 1)
    assert plan["rows"] == []
    assert plan["skip_counts"]["pii_or_price"] == 1


def test_pii_word_root_candidate_is_rejected_at_ingest():
    """**加严**：中文 PII 词根（#2815 的英文 key 词根覆盖不到中文自由文本）。"""
    plan = ingest_mod.plan_ingest([cand("不对，联系人一律填店主")], [], 1)
    assert plan["rows"] == []
    assert plan["skip_counts"]["pii_or_price"] == 1


# ── 其余 fail-closed 边界 ──────────────────────────────────────────────────


def test_cross_tenant_candidate_is_dropped():
    """跨租户的候选不许落进本租户（口径直接进 prompt，越权即污染）。"""
    plan = ingest_mod.plan_ingest([cand("不对，我们按整卷算", tenant_id=2)], [], 1)
    assert plan["rows"] == []
    assert plan["skip_counts"]["tenant_mismatch"] == 1


def test_exception_candidate_stays_out_of_the_queue_in_p1():
    """`例外` 类不自动变反例（会造出出口③生成不出用例的卡，理由见 ingest 模块 docstring）。"""
    plan = ingest_mod.plan_ingest([cand("除非客户要零裁", category="例外")], [], 1)
    assert plan["rows"] == []
    assert plan["skip_counts"]["not_a_card_category"] == 1


def test_candidate_without_a_usable_keyword_is_not_a_card():
    """抽不出关键词 ⇒ 不产卡（一张永远不触发的卡 = 占位的能力幻觉）。"""
    plan = ingest_mod.plan_ingest([cand("不对，OK")], [], 1)
    assert plan["rows"] == []
    assert plan["skip_counts"]["no_keyword"] == 1


def test_cli_dry_run_prints_the_plan_and_apply_goes_through_the_same_wiring(tmp_path):
    """命令行入口：默认 dry-run 只打印计划；`--apply` 走同一条写入路径（同一份计划）。"""
    payload = {"schema_version": 1, "candidates": [cand("不对，我们按整卷算")]}
    source = tmp_path / "candidates.json"
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    session = FakeSession()
    assert ingest_mod.main(["--in", str(source), "--tenant-id", "1"], session_factory=lambda: session) == 0
    assert session.statements("INSERT") == []

    assert (
        ingest_mod.main(
            ["--in", str(source), "--tenant-id", "1", "--apply"], session_factory=lambda: session
        )
        == 0
    )
    assert len(session.statements("INSERT")) == 1
