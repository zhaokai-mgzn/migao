# case_ids: CH-003
"""C 端**模糊意图轮**不得投影业务查询工具（issue #9280 / CH-003）。

## 现场（run 46086496186，2026-11-28 08:2x +08，sha be827c3d4，独立栈 + 真实 LLM）

CH-003（`.github/cases/chat.yml`，`user_inputs=["帮我看看"]`，期望 `direct_reply or interact`）
首跑读数：`tools=['product_search','product_search','product_detail']`，
`callargs=product_search{"keyword":"遮光窗帘"} / product_search{"keyword":"奶油风"}` ——
顾客一个字都没说偏好，模型**自己编了两个偏好**（遮光 / 奶油风）就直接查商品。

## 机制（两条都在运行时主线上，缺一它就能猜）

1. `customer_general` 是 C 端兜底 skill，**声明面本身就含全套业务查询工具**
   （`product_search` / `customer_order_query` / …，每条的理由都是"缺它就是能力谎报"）；
   `create_skill_registry` 再把**同 persona 家族的只读工具**全量并入 ⇒ 模糊轮与正常轮
   **工具面逐名相同**：没有任何"这一轮在澄清、不许查"的档位。
2. `nodes._vague_guess_route`（issue #5329「模糊输入 ⇒ 可点击猜测」）**只对 B 端生效**
   （`agent_type != "mibao"` 直接返回 None）⇒ C 端唯一的模糊轮处理是 `clarify_guard` 的
   **第二轮**示例兜底，第一轮模型手里就是全套业务工具。

## 修法与判据（L0，零 LLM；每条都会红）

`tool_selection.plan_vague_round_read_tools` 给 C 端补一档**模糊轮只读白名单**
（= 保底集合 `ALWAYS_KEEP_TOOL_NAMES`，**复用**既有集合、不新造清单），`prepare_turn`
在 B 端裁剪返回 `None` 时接这一档。判据落在**最近的可判层**：既有投影函数的返回值，
也有 `create_skill_registry` 造出的**真实注册表**（模型能调到的就是它）。

| 判据 | 红证（注入 ⇒ 必红，见 PR body 的注入自证） |
|---|---|
| 模糊轮注册表里没有业务查询工具 | `is_vague_intent_round` 恒 `False` ⇒ 3 条具名工具全部回来 |
| 白名单只含保底集合（类级） | 把 `return [n for n in ALWAYS_KEEP_TOOL_NAMES]` 改成返回声明面 ⇒ 立刻红 |
| 每个 C 端 skill 都掉光业务读工具（元守卫，新增工具自动覆盖） | 同上 |
| 领域信号轮 / 「怎么做」问答轮 / 具体意图轮 / B 端 / 答卡轮**不动** | 把判据改成"C 端一律裁" ⇒ 这 5 条红 |
| `prepare_turn` 真接线（防空判据） | 摘掉那 3 行调用 ⇒ 具名红 |

## 边界（照实登记）

- 只覆盖 **C 端（xiaobu）**；B 端模糊轮走 #5329 的猜测卡，本档刻意不碰。
- 不判"模型是否会照 prompt 发卡"（那是 eval 面：CH-003）；这里判的是**它有没有能力猜**。
"""
import sys
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.agents.xiaobu import XIAOBU_CONFIG  # noqa: E402
from app.graph.skills import tool_selection as ts  # noqa: E402
from app.graph.skills.customer_general_skill import (  # noqa: E402
    CUSTOMER_GENERAL_SYSTEM_PROMPT,
    CUSTOMER_GENERAL_TOOLS,
)
from app.graph.skills.skill_registry import get_skill_registry  # noqa: E402
from app.tools.registry import get_tool_registry  # noqa: E402

CASE_INPUT = "帮我看看"        # CH-003 的 user_inputs 原文

PREPARE_TURN = (Path(__file__).resolve().parents[1] / "app" / "graph" / "skills"
                / "execution" / "prepare_turn.py")

#: C 端 skill 全名单（含兜底）；与 `XIAOBU_CONFIG.skill_names` 现取一致由下面断言钉住。
C_SIDE_SKILLS = sorted(set(XIAOBU_CONFIG.skill_names) | {"customer_general"})


def _state(intent: str = "general", text: str = CASE_INPUT, *, agent_type: str = "xiaobu",
           confidence: float = 0.30, source: str = "classifier",
           pending: str = "") -> dict:
    """最小 AgentState 切片（与运行时 `intent_router_node` 写出的键逐名一致）。"""
    return {
        "agent_type": agent_type,
        "intent_result": {"intent": intent, "confidence": confidence, "source": source},
        "pending_interact_skill": pending,
        "messages": [HumanMessage(content=text)],
    }


def _tool_names(skill: str) -> list:
    return list(get_skill_registry().get(skill).tool_names)


def _bound(tool_names, read_keep) -> set:
    """走**真实的**工厂造注册表 —— 模型能调到的就是它（不是只测返回值）。"""
    return set(ts.create_skill_registry(tool_names, read_keep=read_keep).get_tool_names())


def _read_only() -> set:
    return {t.name for t in get_tool_registry().get_all_tools()
            if getattr(t, "read_only", False)}


def _business_read_tools(tool_names) -> set:
    """本域会被"猜着查"的**业务只读工具** = （声明面 ∪ 同 persona 家族只读）− 保底集合。

    刻意**独立重算**（不复用 `_family_read_only_tool_names`）：否则判据变成"被测实现等于它自己"。
    """
    reg_read_only = _read_only()
    cfgs = list(get_skill_registry().get_all())
    personas = None
    for name in tool_names:
        owners = {p for c in cfgs if name in (c.tool_names or [])
                  for p in (c.system_prompts or {})}
        personas = owners if personas is None else (personas & owners)
    family = set()
    if len(personas or ()) == 1:
        for cfg in cfgs:
            if personas & set(cfg.system_prompts or {}):
                family |= {t for t in (cfg.tool_names or []) if t in reg_read_only}
    return ((set(tool_names) | family) & reg_read_only) - set(ts.ALWAYS_KEEP_TOOL_NAMES)


# ── 1. 实例判据：CH-003 的输入 ⇒ 业务查询工具不可达 ─────────────────────────
def test_vague_round_registry_has_no_business_query_tool():
    """「帮我看看」这一轮，`product_search` / `customer_order_query` / `product_detail`
    必须**不在**本轮注册表里（模型连调用都发不出去）。"""
    keep = ts.plan_vague_round_read_tools(_state(), CUSTOMER_GENERAL_TOOLS)
    bound = _bound(CUSTOMER_GENERAL_TOOLS, keep)
    for name in ("product_search", "product_detail", "customer_order_query",
                 "customer_logistics_track", "processing_item_query"):
        assert name not in bound, f"模糊轮仍绑定了业务查询工具 {name}（CH-003 的猜测就是这么发生的）"
    # 澄清所需的卡片工具必须还在，否则模型连"问"都问不了
    assert "interact" in bound, "模糊轮把 interact 也裁了 ⇒ 只能反问，退化成空白追问"
    # 通用知识问答不涉及"猜对象"，保留
    assert "knowledge_search" in bound


def test_vague_round_keep_set_is_the_always_keep_set():
    """白名单 ⊆ 保底集合（复用既有集合，不新造清单）—— 新增业务工具自动被挡在门外。"""
    keep = ts.plan_vague_round_read_tools(_state(), CUSTOMER_GENERAL_TOOLS)
    assert list(keep) == list(ts.ALWAYS_KEEP_TOOL_NAMES), (
        f"模糊轮白名单必须逐名等于保底集合，实际 {keep}")


# ── 2. 类级元守卫：每个 C 端 skill 都掉光业务读工具 ─────────────────────────
@pytest.mark.parametrize("skill", C_SIDE_SKILLS)
def test_every_c_side_skill_loses_its_business_read_tools(skill):
    """**类级**：C 端任何 skill 在模糊轮都不得留下业务读工具（新增工具自动纳入，无白名单）。"""
    tool_names = _tool_names(skill)
    business = _business_read_tools(tool_names)
    keep = ts.plan_vague_round_read_tools(_state(), tool_names)
    if not business:
        assert _bound(tool_names, keep) == _bound(tool_names, None), (
            f"{skill}: 本域没有业务读工具却仍裁剪（绑定面变了，且会无谓翻 prompt 裁剪态抬头）")
        return
    bound = _bound(tool_names, keep)
    leaked = bound & business
    assert not leaked, f"{skill}: 模糊轮仍绑定业务读工具 {sorted(leaked)}"


def test_c_side_fallback_declares_no_write_tool():
    """C 端兜底 skill **零写工具** —— 否则"模糊轮只裁读面"会给它留一条可写的猜法。"""
    read_only = _read_only()
    writes = [n for n in CUSTOMER_GENERAL_TOOLS if n not in read_only]
    assert not writes, f"customer_general 声明了写工具 {writes}；模糊轮的裁面只覆盖只读工具"


# ── 3. 五个"不动"的对照（防判据被改成"C 端一律裁"）────────────────────────
def test_domain_signal_round_is_untouched():
    """用户给了商品对象（句式信号命中的口语）⇒ 不是模糊轮，业务工具照旧绑定。"""
    state = _state(text="我想看看遮光窗帘")
    assert ts.plan_vague_round_read_tools(state, CUSTOMER_GENERAL_TOOLS) is None
    assert "product_search" in _bound(CUSTOMER_GENERAL_TOOLS, None), (
        "不裁剪时 product_search 本来就该在（否则这条对照不是对照）")


def test_howto_question_is_untouched():
    """「怎么付款」是问做法（知识/指引），不是"说不清要什么" ⇒ 工具面不动。"""
    for text in ("怎么付款", "如何扫码支付", "怎样付款"):
        assert ts.plan_vague_round_read_tools(
            _state(text=text), CUSTOMER_GENERAL_TOOLS) is None, f"{text!r} 被判成模糊轮"


def test_l1_business_phrasing_is_never_a_vague_round():
    """含业务词的问法（#4085 的「收款码在哪」）在 **L1** 就落业务意图 ⇒ 根本到不了模糊轮。

    这条把「为什么模糊轮不会误伤收款码」钉在**路由层的既成事实**上（不是本单的宽容），
    免得下游把它读成本档的副作用。
    """
    from app.router.rule_matcher import RuleMatcher

    hit = RuleMatcher().match("收款码在哪")
    assert hit is not None and hit.intent.value != "general", (
        "「收款码在哪」在 L1 未命中业务意图 ⇒ 它会落 general 并被当模糊轮，收款码将查不到")
    state = _state(intent=hit.intent.value, text="收款码在哪")
    assert ts.plan_vague_round_read_tools(state, CUSTOMER_GENERAL_TOOLS) is None


def test_concrete_intent_round_is_untouched():
    """意图已被定到具体业务域（不是 general 兜底）⇒ 工具面不动。"""
    for intent in ("order_query", "product_inquiry", "knowledge_faq", "after_sales"):
        assert ts.plan_vague_round_read_tools(
            _state(intent=intent), CUSTOMER_GENERAL_TOOLS) is None, f"intent={intent} 被判成模糊轮"


def test_mibao_round_is_untouched():
    """B 端（mibao）不吃这一档：它的模糊轮走 #5329 的可点击猜测，工具面由 #8174 裁剪负责。"""
    assert ts.plan_vague_round_read_tools(
        _state(agent_type="mibao"), CUSTOMER_GENERAL_TOOLS) is None


def test_pending_card_round_is_untouched():
    """答卡轮（用户正在回答上一张卡）不是模糊轮 —— 那一轮必须能真的去查。"""
    assert ts.plan_vague_round_read_tools(
        _state(pending="customer_general"), CUSTOMER_GENERAL_TOOLS) is None


# ── 4. 确定性 + 接线守卫（防空判据）──────────────────────────────────────
def test_two_runs_are_identical():
    """同一输入连跑两次，顺序逐字一致（白名单是常量，不靠 set 迭代序）。"""
    first = ts.plan_vague_round_read_tools(_state(), CUSTOMER_GENERAL_TOOLS)
    second = ts.plan_vague_round_read_tools(_state(), CUSTOMER_GENERAL_TOOLS)
    assert first == second == ["nav_guide", "knowledge_search", "interact",
                              "validate_input", "confirm_value"]


def test_prepare_turn_actually_wires_the_vague_projection():
    """`prepare_turn` 必须真的接这一档 —— 否则上面所有判据只证明"函数正确"（空判据）。"""
    src = PREPARE_TURN.read_text(encoding="utf-8")
    assert "plan_vague_round_read_tools(state, tool_names)" in src, (
        "prepare_turn 没有调用模糊轮投影 ⇒ 线上模型仍然拿全套业务工具")
    assert "read_keep = plan_vague_round_read_tools" in src


# ── 5. prompt 层（补充约束，源码级钉住防静默删除）──────────────────────────
def test_customer_general_prompt_forbids_guessing_on_vague_intent():
    """纯文本模糊输入同样要有禁令（图片段那条只覆盖"仅发图"）。"""
    assert "意图不明先问、不猜" in CUSTOMER_GENERAL_SYSTEM_PROMPT
    assert "不要自己假设偏好" in CUSTOMER_GENERAL_SYSTEM_PROMPT
