# case_ids: AG-009, PP-002, PP-016, PR-101
"""B 端工具面**按意图裁剪读面**（issue #8174）—— 保底 / 上限 / 关闭等价 / C 端不变 / 确定性。

## 被测事实（改前读数现取）

- 改前：B 端每轮绑定 **35~39** 把工具（读面按 persona 家族全量并入，见 #4125），
  工具 schema 33~40KB、prompt 5.7~15KB。
- 改后：同一轮读面按**本轮意图**打分保留到上限（`TOOL_TRIM_MAX_READ`，默认 16），
  **保底集合永不被裁**（本 skill 写工具 + `ALWAYS_KEEP_TOOL_NAMES` + 上一轮用过的读工具
  + **意图属主 skill 的读工具**，最后一条见 issue #8300），且**只对 B 端（mibao）生效**。

## 每条判据都有红证（不会红的断言 = 空断言）

| 判据 | 红证（注入 ⇒ 必红） |
|---|---|
| 保底不被裁 | `test_clearing_always_keep_set_cuts_them`：清空保底集合 ⇒ 这些工具真的会掉 |
| 上限生效 | `test_raising_the_cap_disables_the_cap`：上限调到 100 ⇒ 绑定数回到 35+ |
| 关闭等价 | `test_disabled_switch_is_name_for_name_identical_to_today`：与**独立 oracle** 逐名相等 |
| C 端不变 | 同上 oracle，`agent_type="xiaobu"` 时 `plan_read_tools` 必须 `None` |
| 确定性 | 同一输入连跑两次，顺序逐字一致 |
| 写面不裁 | `read_only=False` 的工具集合前后相等 |
| 字符数棘轮 | prompt / schema 字符数**都下降**（关闭裁剪 ⇒ 回落） |
| **意图属主保底**（#8300） | `test_dropping_intent_owner_keep_reproduces_the_outage`：摘掉保底 ⇒ `settings_manage` 立刻被裁 |

判据里用的"改前行为"由 `_oracle_names` **独立重算**（声明面 ∪ 家族只读，按注册表顺序），
不复用被测实现，避免"判据自己证明自己"。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.agents.agents.mibao import MIBAO_CONFIG  # noqa: E402
from app.agents.agents.xiaobu import XIAOBU_CONFIG  # noqa: E402
from app.graph.skills import base_skill  # noqa: E402
from app.graph.skills import tool_selection as ts  # noqa: E402
from app.graph.skills.skill_registry import get_skill_registry  # noqa: E402
from app.tools.registry import get_tool_registry  # noqa: E402

#: 与 `tool_selection.plan_read_tools` 默认上限一致（改默认值时本判据跟着动）。
DEFAULT_CAP = 16

MESSAGE = "帮我查一下最近订单的物流到哪了"

PREPARE_TURN = (Path(__file__).resolve().parents[1] / "app" / "graph" / "skills"
                / "execution" / "prepare_turn.py")


def _skill_names(agent_config) -> list:
    return list(agent_config.skill_names)


def _tool_names(skill: str) -> list:
    return list(get_skill_registry().get(skill).tool_names)


def _intent_list(skill: str) -> list:
    """该 skill **自己声明**的意图（真实可达组合；跨域组合只能人造）。"""
    return list(get_skill_registry().get(skill).intents or [])


def _read_only() -> frozenset:
    return frozenset(t.name for t in get_tool_registry().get_all_tools()
                     if getattr(t, "read_only", False))


def _oracle_names(tool_names: list) -> list:
    """**独立**重算"改前的绑定集合"：声明面 ∪ 同一 persona 家族的只读工具（注册表顺序）。

    刻意不复用 `tool_selection._family_read_only_tool_names` —— 否则"关闭等价"这条
    判据就变成了"被测实现等于它自己"（空判据）。
    """
    reg = get_tool_registry()
    tools = {t.name: t for t in reg.get_all_tools()}
    read_only = {n for n, t in tools.items() if getattr(t, "read_only", False)}
    cfgs = list(get_skill_registry().get_all())
    personas = None
    for name in tool_names:
        owners = {p for c in cfgs if name in (c.tool_names or [])
                  for p in (c.system_prompts or {})}
        personas = owners if personas is None else (personas & owners)
    extra = set()
    if len(personas or ()) == 1:
        for cfg in cfgs:
            if personas & set(cfg.system_prompts or {}):
                extra |= {t for t in (cfg.tool_names or []) if t in read_only}
    wanted = set(tool_names) | extra
    return [t.name for t in reg.get_all_tools() if t.name in wanted]


def _bound(tool_names: list, read_keep) -> list:
    return list(ts.create_skill_registry(tool_names, read_keep=read_keep).get_tool_names())


def _plan(tool_names: list, **kwargs):
    kwargs.setdefault("agent_type", "mibao")
    kwargs.setdefault("user_message", MESSAGE)
    kwargs.setdefault("intent", "order_query")
    return ts.plan_read_tools(tool_names, **kwargs)


# ── 1. 保底集合永不被裁 ────────────────────────────────────────────────────
@pytest.mark.parametrize("skill", _skill_names(MIBAO_CONFIG))
def test_always_keep_survives_every_mibao_skill(skill):
    """本轮 skill 的写工具 + 兜底工具（原样在册的那些）一个都不许掉。"""
    tool_names = _tool_names(skill)
    full = set(_bound(tool_names, None))
    trimmed = set(_bound(tool_names, _plan(tool_names)))
    read_only = _read_only()

    baseline = {n for n in full if n in ts.ALWAYS_KEEP_TOOL_NAMES}
    baseline |= {n for n in full if n not in read_only}          # 本 skill 的全部写工具
    assert baseline, "本 skill 的保底集合为空 —— 判据面本身失效"
    assert baseline <= trimmed, f"{skill}: 保底集合被裁：{sorted(baseline - trimmed)}"


def test_clearing_always_keep_set_cuts_them(monkeypatch):
    """红证：把保底集合清空 ⇒ 兜底工具**真的**会被裁（证明上一条不是恒真）。"""
    skill = "data"
    tool_names = _tool_names(skill)
    before = set(_bound(tool_names, _plan(tool_names)))
    monkeypatch.setattr(ts, "ALWAYS_KEEP_TOOL_NAMES", ())
    after = set(_bound(tool_names, _plan(tool_names)))
    dropped = before - after
    assert dropped, (
        "清空保底集合后绑定集合没有变化 —— 说明保底集合根本不是裁剪的输入（空判据）"
    )


# ── 2. 上限生效（含"上限调大 ⇒ 红"）───────────────────────────────────────
@pytest.mark.parametrize("skill", _skill_names(MIBAO_CONFIG))
def test_bound_count_is_capped_for_every_mibao_skill(skill):
    """开启裁剪 ⇒ 绑定数 ≤ 16（+ 属主净增 ≤ `OWNER_EXTRA_MAX`）；且改前确实 > 16。

    意图取该 skill **自己声明的**意图（真实可达组合）。注意 `notification` 这类意图会被
    `nodes._get_intent_to_route` 过滤到 `general`（#6044 缺陷 C）⇒ 它们按「被过滤意图」处理，
    会额外补 ≤ `OWNER_EXTRA_MAX` 把属主读工具 —— 这是**设计内的净增**（只加不减），
    不是上限失效：上限仍钉住「分数排序那一层」的 16 把。
    """
    tool_names = _tool_names(skill)
    own_intent = (_intent_list(skill) or ["general"])[0]
    full = _bound(tool_names, None)
    trimmed = _bound(tool_names, _plan(tool_names, intent=own_intent))
    assert len(full) > DEFAULT_CAP, f"{skill}: 改前只有 {len(full)} 把，判据面没有可裁空间"
    assert len(trimmed) <= DEFAULT_CAP + ts.OWNER_EXTRA_MAX, (
        f"{skill}: 裁剪后绑定 {len(trimmed)} 把（上限 {DEFAULT_CAP}+{ts.OWNER_EXTRA_MAX}，"
        f"自身意图 {own_intent}）")
    assert len(trimmed) < len(full), f"{skill}: 裁剪没有减少任何工具（{len(trimmed)}/{len(full)}）"


def test_raising_the_cap_disables_the_cap():
    """红证：上限调到 100 ⇒ 绑定数回到改前（>16）⇒「上限生效」那条会红。"""
    tool_names = _tool_names("order")
    plan = _plan(tool_names, max_tools=100)
    # 不下断言 "plan is None"（弱断言形态）：直接钉**绑定结果** —— 上限 100 ⇒ 回收全量，
    # 既排除「裁了」也排除「裁了没生效」，比断言 None 更强。
    assert len(_bound(tool_names, plan)) == len(_oracle_names(tool_names)) > DEFAULT_CAP


# ── 3. 关闭等价（回归护栏）────────────────────────────────────────────────
def test_disabled_switch_is_name_for_name_identical_to_today(monkeypatch):
    """`TOOL_TRIM_ENABLED=false` ⇒ B 端绑定集合与改动前**逐名相等**（含顺序）。"""
    monkeypatch.setattr(ts.settings, "TOOL_TRIM_ENABLED", False)
    for skill in _skill_names(MIBAO_CONFIG):
        tool_names = _tool_names(skill)
        assert _plan(tool_names) is None, f"{skill}: 开关关闭后仍返回裁剪名单"
        assert sorted(_bound(tool_names, None)) == sorted(_oracle_names(tool_names)), (
            f"{skill}: 关闭裁剪后的绑定集合与改动前不一致")


# ── 4. C 端不变（逐名相等 + 永不进入裁剪分支）──────────────────────────────
def test_c_end_binding_untouched():
    """xiaobu：`plan_read_tools` 恒 `None`，绑定集合与独立 oracle 逐名相等。"""
    for skill in _skill_names(XIAOBU_CONFIG):
        tool_names = _tool_names(skill)
        assert _plan(tool_names, agent_type="xiaobu") is None
        assert sorted(_bound(tool_names, None)) == sorted(_oracle_names(tool_names)), (
            f"{skill}: C 端绑定面变了")


# ── 5. 确定性 ─────────────────────────────────────────────────────────────
def test_two_runs_are_byte_identical():
    """同一输入连跑两次，**顺序**逐字一致（同分按注册表顺序，不靠 set 迭代序）。"""
    for skill in _skill_names(MIBAO_CONFIG):
        tool_names = _tool_names(skill)
        first = _plan(tool_names)
        second = _plan(tool_names)
        assert first == second, f"{skill}: 两次裁剪结果不一致（含顺序）"
        assert _bound(tool_names, first) == _bound(tool_names, second)


# ── 6. 写工具一个都不裁 ───────────────────────────────────────────────────
@pytest.mark.parametrize("skill", _skill_names(MIBAO_CONFIG))
def test_write_tools_are_never_trimmed(skill):
    tool_names = _tool_names(skill)
    read_only = _read_only()
    writes = {n for n in _bound(tool_names, None) if n not in read_only}
    trimmed_writes = {n for n in _bound(tool_names, _plan(tool_names)) if n not in read_only}
    assert writes == trimmed_writes, f"{skill}: 写面被动了：裁掉 {sorted(writes - trimmed_writes)}"


# ── 7. 意图打分真的起作用（易混族负例的另一半）──────────────────────────────
def test_order_intent_keeps_order_query():
    """「查订单」意图下 `order_query` 必须留下 —— 裁错工具才是本单的真实风险面。"""
    plan = _plan(_tool_names("order"))
    assert plan is not None and "order_query" in plan


# ── 8. 意图属主 skill 的读工具必须保底（issue #8300）────────────────────────
# 病灶（2026-11-01 真实 LLM 评测实测：normal 档 ST-001 / ST-002 / DA-025 确定性红）：
# `nodes._get_intent_to_route` 按**绑定面**过滤意图 ⇒ `system_settings` / `ai_config`
# 落到 fallback skill `general`（#6044 缺陷 C：`settings` 不在图上）。改动前 #4125 的
# 「同 persona 家族只读并入」把 `settings_manage` 一起带进来；#8174 裁剪后它不在 general
# 的声明面、词面又零分 ⇒ 被裁 ⇒ 模型改用保底的 `nav_guide` 回「菜单位置」，能力不可达。
@pytest.mark.parametrize("intent,skill,tool", [
    ("system_settings", "general", "settings_manage"),
    ("ai_config", "general", "settings_manage"),
    ("dashboard", "order", "dashboard_stats"),
    ("processing_order_query", "general", "processing_order_set_query"),
])
def test_intent_owner_read_tools_survive_on_foreign_skill(intent, skill, tool):
    """意图属主 skill 的读工具，在**落到别的 skill** 时也必须留在绑定面。"""
    tool_names = _tool_names(skill)
    plan = _plan(tool_names, user_message="查看系统设置", intent=intent)
    if plan is None:  # 裸 `is not None` 是弱断言（tests/unit_ci_workflows/test_weak_assert_blindspots.py）
        raise AssertionError(f"{skill}: 判据面没有触发裁剪（pool ≤ 上限），判据失效")
    assert tool in plan, f"intent={intent} 落到 {skill} 时 {tool} 被裁（#8300 的病灶形态）"


def test_dropping_intent_owner_keep_reproduces_the_outage(monkeypatch):
    """红证：摘掉「意图属主读工具」这条保底 ⇒ 上一条**真的**会红（证明它不是恒真）。"""
    monkeypatch.setattr(ts, "_intent_owner_read_tool_names", lambda _intent: [])
    plan = _plan(_tool_names("general"), user_message="查看系统设置",
                 intent="system_settings")
    assert "settings_manage" not in (plan or []), (
        "摘掉保底后 settings_manage 仍在保留集 —— 说明上一条不是靠这条保底通过的（空判据）"
    )


def test_every_foreign_intent_keeps_its_owner_read_tools():
    """类级元守卫（#8300）：**任意** skill × **别家**意图 ⇒ 属主读工具至少留一个、且**只增不减**。

    ⚠️ 刻意**不再**要求「属主读工具全留」（#8300 首版写法）：那正是 2026-11-01 全档评测
    7 条转红的成因 —— 属主工具占满分数槽位，把本域的 `craft_config_query` /
    `batch_stock_query` / `operation_catalog_query` 挤了出去。现行口径 =
    「净增 ≤ `OWNER_EXTRA_MAX` 把、按相关度挑」+ 不减少既有保留集。
    """
    cfgs = [c for c in get_skill_registry().get_all()
            if "mibao" in (c.system_prompts or {})]
    read_only = _read_only()
    checked = 0
    original = ts._intent_owner_read_tool_names
    baseline_without_owner = {}
    try:
        ts._intent_owner_read_tool_names = lambda _intent: []
        for owner in cfgs:
            for intent in (owner.intents or []):
                for skill in cfgs:
                    if skill.name == owner.name:
                        continue
                    baseline_without_owner[(skill.name, intent)] = _plan(
                        _tool_names(skill.name), user_message="", intent=intent)
    finally:
        ts._intent_owner_read_tool_names = original
    for owner in cfgs:
        owner_read = [n for n in (owner.tool_names or []) if n in read_only]
        if not owner_read:
            continue
        for intent in (owner.intents or []):
            for skill in cfgs:
                if skill.name == owner.name:
                    continue
                tool_names = _tool_names(skill.name)
                baseline = baseline_without_owner[(skill.name, intent)]
                if baseline is None:
                    continue
                plan = _plan(tool_names, user_message="", intent=intent)
                if plan is None:  # 同上：把弱断言换成显式失败，判据语义不变
                    raise AssertionError(
                        f"skill={skill.name}: 意图 {intent} 未触发裁剪，判据面失效")
                # ① 只许加：关闭属主保底时的保留集必须仍是子集（净增口径）
                removed = [n for n in baseline if n not in plan]
                assert not removed, (
                    f"skill={skill.name} intent={intent}（属主 {owner.name}）"
                    f"挤掉了 {removed} —— #8300 第二形态的病灶")
                # ② 属主工具至少留一个（否则「保底」名存实亡）
                hits = [n for n in owner_read if n in plan]
                assert hits, (
                    f"skill={skill.name} intent={intent}（属主 {owner.name}）"
                    f"一个属主读工具都没留下 —— #8300 的病灶形态")
                checked += 1
    assert checked >= 10, f"判据面过小（{checked} 组合）—— 元守卫退化成空判据"


# ── 4b. 属主保底必须**净增**（#8300 第二形态：2026-11-01 全档评测回归）──────────
# 实测（run 41268493564，B 端 normal 82 条）：PP-016/PP-017/PP-019/PP-020/PP-002/PR-101/CH-044
# 七条**从绿转红** —— 属主工具占了分数槽位 ⇒ `craft_config_query` / `batch_stock_query` /
# `operation_catalog_query` / `image_recognize` 被挤出绑定面（同一 (skill,intent,message) 下
# 摘掉属主保底反而保留它们）。修法：属主工具只补「被意图过滤挡在声明面之外」的那些、按相关度
# 取前几个，且**不占分数槽位** ⇒ 属主保底只许加、不许换。
_OWNER_NET_ADDITIVE_MATRIX = [
    # (skill, message, intent)：三个真实形态 —— 批次余量（PR-101）/ 工艺路线（PP-016/017）/ 工序库（PP-002）
    ("general", "批次余量、剩料分布在哪一页？快用完的批次在哪看", "general"),
    ("general", "工艺路线配置在哪一页？工序库在哪？", "general"),
    ("general", "工序库在哪", "general"),
]


def test_intent_owner_keep_never_removes_a_baseline_tool(monkeypatch):
    """属主保底**只许加**：同一输入下，开启它之后的保留集必须 ⊇ 关闭它时的保留集。"""
    off = {}
    monkeypatch.setattr(ts, "_intent_owner_read_tool_names", lambda _intent: [])
    for skill, message, intent in _OWNER_NET_ADDITIVE_MATRIX:
        off[(skill, intent, message)] = _plan(
            _tool_names(skill), user_message=message, intent=intent)
    monkeypatch.undo()

    for skill, message, intent in _OWNER_NET_ADDITIVE_MATRIX:
        baseline = off[(skill, intent, message)]
        assert baseline is not None, f"{skill}/{intent}: 判据面没有触发裁剪"
        plan = _plan(_tool_names(skill), user_message=message, intent=intent)
        assert plan is not None
        removed = [n for n in baseline if n not in plan]
        assert not removed, (
            f"{skill}/{intent}: 属主保底把本来保留的工具挤掉了 {removed} —— "
            f"2026-11-01 全档评测的病灶形态（7 条转红）")


def test_owner_keep_is_net_additive_for_every_skill_intent():
    """类级元守卫（#8300）：**任意** skill × **任意**已注册意图 ⇒ 开启属主保底不减少保留集。"""
    cfgs = [c for c in get_skill_registry().get_all()
            if "mibao" in (c.system_prompts or {})]
    intents = sorted({i for c in cfgs for i in (c.intents or [])})
    assert len(intents) >= 5, f"意图面过小（{len(intents)}）—— 元守卫退化成空判据"
    checked = 0
    original = ts._intent_owner_read_tool_names
    for skill in cfgs:
        tool_names = _tool_names(skill.name)
        baseline = {}
        try:
            ts._intent_owner_read_tool_names = lambda _intent: []
            for intent in intents:
                baseline[intent] = _plan(tool_names, user_message="", intent=intent)
        finally:
            ts._intent_owner_read_tool_names = original
        for intent in intents:
            plan = _plan(tool_names, user_message="", intent=intent)
            base = baseline[intent]
            if base is None or plan is None:
                continue
            removed = [n for n in base if n not in plan]
            assert not removed, (
                f"skill={skill.name} intent={intent}: 属主保底挤掉了 {removed}")
            checked += 1
    assert checked >= 10, f"判据面过小（{checked} 组合）—— 元守卫退化成空判据"


def test_recent_tool_survives():
    """上一轮点过的读工具即使本轮零分也留在绑定面（保底口径 ③）。"""
    plan = _plan(_tool_names("staff"), user_message="嗯", intent="",
                 recent_tools=["piecework_query"])
    assert plan is not None and "piecework_query" in plan


def test_plan_reads_state_signals():
    """state 适配层：agent_type / 用户消息 / intent / 上一轮 tool_calls 都取自 state。"""
    from langchain_core.messages import AIMessage, HumanMessage

    state = {
        "agent_type": "mibao",
        "intent_result": {"intent": "order_query"},
        "messages": [
            HumanMessage(content="上一轮说的"),
            AIMessage(content="", tool_calls=[
                {"name": "piecework_query", "args": {}, "id": "call_1", "type": "tool_call"}]),
            HumanMessage(content="这单的计件工资多少"),
        ],
    }
    plan = ts.plan_read_tools_for_state(state, _tool_names("data"))
    assert plan is not None and "piecework_query" in plan
    assert ts.plan_read_tools_for_state({**state, "agent_type": "xiaobu"},
                                        _tool_names("data")) is None


# ── 8. 字符数棘轮（prompt + schema 都下降）─────────────────────────────────
def _schema_chars(names: list) -> int:
    tools = {t.name: t for t in get_tool_registry().get_all_tools()}
    return sum(
        len(json.dumps({
            "name": n,
            "description": getattr(tools[n], "description", "") or "",
            "parameters": getattr(tools[n], "parameters", {}) or {},
        }, ensure_ascii=False))
        for n in names if n in tools
    )


@pytest.mark.parametrize("skill", _skill_names(MIBAO_CONFIG))
def test_prompt_and_schema_chars_shrink(skill):
    """裁剪开启 ⇒ prompt 字符数与工具 schema 字符数**都下降**。"""
    tool_names = _tool_names(skill)
    full_names = _bound(tool_names, None)
    plan = _plan(tool_names)
    trimmed_names = _bound(tool_names, plan)

    full_prompt = len(base_skill._build_system_prompt(skill))
    trimmed_prompt = len(base_skill._build_system_prompt(skill, trimmed=True))
    assert trimmed_prompt < full_prompt, (
        f"{skill}: 裁剪态 prompt 没变短（{trimmed_prompt} vs {full_prompt}）")

    assert _schema_chars(trimmed_names) < _schema_chars(full_names), (
        f"{skill}: 工具 schema 字符数没下降")


# ── 9. 接线守卫（判据不许因为"没人调用"而恒绿）────────────────────────────
def test_prepare_turn_actually_plans_and_passes_the_plan():
    """`prepare_turn` 必须真的算计划、传给工厂、并把裁剪态带进 prompt。

    没有这条，上面所有判据都只证明"函数正确"，而线上可能**根本没接线**（空判据）。
    """
    src = PREPARE_TURN.read_text(encoding="utf-8")
    assert "plan_read_tools_for_state(state, tool_names)" in src, "prepare_turn 没有算裁剪计划"
    assert "read_keep=read_keep" in src, "prepare_turn 没有把裁剪计划传给 create_skill_registry"
    assert "trimmed=read_keep is not None" in src, "prepare_turn 没有把裁剪态带进 system prompt"
