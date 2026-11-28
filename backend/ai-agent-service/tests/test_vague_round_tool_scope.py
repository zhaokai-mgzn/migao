# case_ids: CH-003
"""C 端「纯看」轮不得投影业务查询工具（issue #9280 / CH-003）。

## 现场（run 46086496186，2026-11-28 08:2x +08，sha be827c3d4，独立栈 + 真实 LLM）

CH-003（`.github/cases/chat.yml`，`user_inputs=["帮我看看"]`，期望 `direct_reply or interact`）
首跑读数：`tools=['product_search','product_search','product_detail']`，
`callargs=product_search{"keyword":"遮光窗帘"} / product_search{"keyword":"奶油风"}` ——
顾客一个字都没说偏好，模型**自己编了两个偏好**（遮光 / 奶油风）就直接查商品。

## 机制（两条都在运行时主线上，缺一它就能猜）

1. `customer_general` 是 C 端兜底 skill，**声明面本身就含全套业务查询工具**
   （`product_search` / `customer_order_query` / …，每条的理由都是"缺它就是能力谎报"）；
   `create_skill_registry` 再把**同 persona 家族的只读工具**全量并入 ⇒ 任何一轮的工具面
   都与正常轮**逐名相同**：没有"这一轮顾客没说看什么、不许查"的档位。而
   `CUSTOMER_GENERAL_SYSTEM_PROMPT` 里唯一的"意图不明先澄清"只写在**图片**段
   （"仅发图/意图不明"），纯文本的「帮我看看」没有任何禁令。
2. `nodes._vague_guess_route`（issue #5329「模糊输入 ⇒ 可点击猜测」）**只对 B 端生效**
   （`agent_type != "mibao"` 直接返回 None）⇒ C 端唯一的模糊轮处理是 `clarify_guard` 的
   **第二轮**示例兜底；第一轮模型手里就是全套业务工具。

## 修法与判据（L0，零 LLM；每条都会红）

`tool_selection.plan_vague_round_read_tools` 给 C 端补一档**「纯看」轮只读白名单**
（= 保底集合 `ALWAYS_KEEP_TOOL_NAMES`，**复用**既有集合、不新造清单），`prepare_turn`
在 B 端裁剪返回 `None` 时接这一档。判据落在**最近的可判层**：既有投影函数的返回值，
也有 `create_skill_registry` 造出的**真实注册表**（模型能调到的就是它）。

| 判据 | 红证（注入 ⇒ 必红，读数见 PR body 的注入自证） |
|---|---|
| 纯看轮注册表里没有业务查询工具 | `is_vague_round` 恒 `False` ⇒ 8 条具名工具全部回来 |
| 白名单逐名等于保底集合（类级） | 把返回改成声明面 ⇒ 8 条红 |
| 每个 C 端 skill 都掉光业务读工具（元守卫，新增工具自动覆盖） | 同上 |
| 有对象的话 / B 端 / 答卡轮**不动** | 把判据改成"C 端一律裁" ⇒ 这 3 组红 |
| 纯看轮**不看**分类器猜的意图（猜 product_inquiry 也要拦） | 加回 `intent == "general"` 门 ⇒ 该条红 |
| `prepare_turn` 真接线（防空判据） | 摘掉那 3 行调用 ⇒ 具名红 |

## 边界（照实登记）

- 只覆盖 **C 端（xiaobu）**；B 端同形走 #5329 的猜测卡，本档刻意不碰。
- "纯看"的定义 = 去掉礼貌/语气填充词后**逐字等于**一个"看"类动词（`_VAGUE_LOOK_VERBS`）——
  有对象的话（「看看这款面料」「查一下遮光窗帘」）**一律不动**：那些轮模型本来就该去查。
- 不判"模型是否会照 prompt 发卡"（那是 eval 面：CH-003 / CH-026）；这里判的是**它有没有能力猜**。
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

CASE_INPUT = "帮我看看"             # CH-003 的 user_inputs 原文（CH-026 的 R1 也是它）

#: 「纯看」形态（顾客没说看什么）—— 全部必须被拦。
PURE_LOOK_INPUTS = ["帮我看看", "随便看看", "看看", "看一下", "看下", "先看看",
                    "帮我看一下", "麻烦帮我看看", "看"]

#: 有对象 / 有做法的话 —— **一律不动**（这些轮模型本来就该去查 / 该去答）。
OBJECT_INPUTS = ["我想看看遮光窗帘", "看看这款面料", "查一下遮光窗帘", "搜索遮光窗帘",
                 "怎么付款", "我想付款，收款码在哪里？", "帮我搜一下星空梦幻窗帘",
                 "列出所有商品", "帮我算一下窗宽 3 米要多少布"]

PREPARE_TURN = (Path(__file__).resolve().parents[1] / "app" / "graph" / "skills"
                / "execution" / "prepare_turn.py")

#: C 端 skill 全名单（含兜底）；与 `XIAOBU_CONFIG.skill_names` 现取一致由模块导入处钉住。
C_SIDE_SKILLS = sorted(set(XIAOBU_CONFIG.skill_names) | {"customer_general"})


def _state(text: str = CASE_INPUT, *, intent: str = "general", agent_type: str = "xiaobu",
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
def test_pure_look_round_registry_has_no_business_query_tool():
    """「帮我看看」这一轮，`product_search` / `customer_order_query` / `product_detail`
    必须**不在**本轮注册表里（模型连调用都发不出去）。"""
    keep = ts.plan_vague_round_read_tools(_state(), CUSTOMER_GENERAL_TOOLS)
    bound = _bound(CUSTOMER_GENERAL_TOOLS, keep)
    for name in ("product_search", "product_detail", "customer_order_query",
                 "customer_logistics_track", "processing_item_query"):
        assert name not in bound, f"纯看轮仍绑定了业务查询工具 {name}（CH-003 的猜测就是这么发生的）"
    # 澄清所需的卡片工具必须还在，否则模型连"问"都问不了
    assert "interact" in bound, "纯看轮把 interact 也裁了 ⇒ 只能反问，退化成空白追问"
    # 通用知识问答不涉及"猜对象"，保留
    assert "knowledge_search" in bound


@pytest.mark.parametrize("text", PURE_LOOK_INPUTS)
def test_every_pure_look_variant_is_caught(text):
    """「纯看」形态的每一种说法都要被拦（不是只认 CH-003 那一条原文）。"""
    assert ts.is_vague_round(_state(text=text)), f"{text!r} 没被识别成纯看轮"
    keep = ts.plan_vague_round_read_tools(_state(text=text), CUSTOMER_GENERAL_TOOLS)
    assert "product_search" not in _bound(CUSTOMER_GENERAL_TOOLS, keep)


def test_vague_round_keep_set_is_the_always_keep_set():
    """白名单逐名等于保底集合（复用既有集合，不新造清单）—— 新增业务工具自动被挡在门外。"""
    keep = ts.plan_vague_round_read_tools(_state(), CUSTOMER_GENERAL_TOOLS)
    assert list(keep) == list(ts.ALWAYS_KEEP_TOOL_NAMES), (
        f"纯看轮白名单必须逐名等于保底集合，实际 {keep}")


# ── 2. 类级元守卫：每个 C 端 skill 都掉光业务读工具 ─────────────────────────
@pytest.mark.parametrize("skill", C_SIDE_SKILLS)
def test_every_c_side_skill_loses_its_business_read_tools(skill):
    """**类级**：C 端任何 skill 在纯看轮都不得留下业务读工具（新增工具自动纳入，无白名单）。"""
    tool_names = _tool_names(skill)
    business = _business_read_tools(tool_names)
    keep = ts.plan_vague_round_read_tools(_state(), tool_names)
    if not business:
        assert _bound(tool_names, keep) == _bound(tool_names, None), (
            f"{skill}: 本域没有业务读工具却仍裁剪（绑定面变了，且会无谓翻 prompt 裁剪态抬头）")
        return
    bound = _bound(tool_names, keep)
    leaked = bound & business
    assert not leaked, f"{skill}: 纯看轮仍绑定业务读工具 {sorted(leaked)}"


def test_c_side_fallback_declares_no_write_tool():
    """C 端兜底 skill **零写工具** —— 否则"纯看轮只裁读面"会给它留一条可写的猜法。"""
    read_only = _read_only()
    writes = [n for n in CUSTOMER_GENERAL_TOOLS if n not in read_only]
    assert not writes, f"customer_general 声明了写工具 {writes}；纯看轮的裁面只覆盖只读工具"


# ── 3. 三个"不动"的对照（防判据被改成"C 端一律裁"）────────────────────────
@pytest.mark.parametrize("text", OBJECT_INPUTS)
def test_object_bearing_message_is_untouched(text):
    """说了对象 / 问了做法 ⇒ 不是纯看轮，绑定面与不裁剪逐名相同（这些轮该去查 / 该去答）。"""
    keep = ts.plan_vague_round_read_tools(_state(text=text), CUSTOMER_GENERAL_TOOLS)
    assert _bound(CUSTOMER_GENERAL_TOOLS, keep) == _bound(CUSTOMER_GENERAL_TOOLS, None), (
        f"{text!r} 被判成纯看轮（绑定面变了；有对象的话不许裁）")
    assert "product_search" in _bound(CUSTOMER_GENERAL_TOOLS, None), (
        "不裁剪时 product_search 本来就该在（否则这条对照不是对照）")


def test_mibao_round_is_untouched():
    """B 端（mibao）不吃这一档：它的模糊轮走 #5329 的可点击猜测，读面由 #8174 裁剪负责。"""
    assert ts.plan_vague_round_read_tools(
        _state(agent_type="mibao"), CUSTOMER_GENERAL_TOOLS) is None


def test_pending_card_round_is_untouched():
    """答卡轮（用户正在回答上一张卡）不是纯看轮 —— 那一轮必须能真的去查。"""
    assert ts.plan_vague_round_read_tools(
        _state(pending="customer_general"), CUSTOMER_GENERAL_TOOLS) is None


def test_pure_look_is_stripped_whatever_the_classifier_guessed():
    """**刻意不看意图**：分类器把「帮我看看」猜成商品 / 订单 / 报价，也必须拦。

    这正是 CH-003 失败的形态 —— 若按 `intent == general` 设门，就会变成"猜对了才拦"。
    """
    for intent in ("general", "product_inquiry", "order_query", "quote", "after_sales"):
        keep = ts.plan_vague_round_read_tools(
            _state(intent=intent, confidence=0.9, source="classifier"), CUSTOMER_GENERAL_TOOLS)
        bound = _bound(CUSTOMER_GENERAL_TOOLS, keep)
        assert "product_search" not in bound and "interact" in bound, (
            f"intent={intent} 时纯看轮没被拦（绑定面={sorted(bound)}）")


def test_l1_business_phrasing_is_never_a_vague_round():
    """含业务词的问法（#4085 的「收款码在哪」）在 **L1** 就落业务意图，且不是纯看形态。

    把「为什么本档不会误伤收款码」钉在**两条既成事实**上（不是本单的宽容）。
    """
    from app.router.rule_matcher import RuleMatcher

    hit = RuleMatcher().match("收款码在哪")
    assert hit is not None and hit.intent.value != "general", (
        "「收款码在哪」在 L1 未命中业务意图 ⇒ 它会落 general 兜底，收款码将查不到")
    assert ts.plan_vague_round_read_tools(
        _state(text="收款码在哪", intent=hit.intent.value), CUSTOMER_GENERAL_TOOLS) is None


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
        "prepare_turn 没有调用纯看轮投影 ⇒ 线上模型仍然拿全套业务工具")
    assert "read_keep = plan_vague_round_read_tools" in src


# ── 5. prompt 层（补充约束，源码级钉住防静默删除）──────────────────────────
def test_customer_general_prompt_forbids_guessing_on_vague_intent():
    """纯文本模糊输入同样要有禁令（图片段那条只覆盖"仅发图"）。"""
    assert "意图不明先问、不猜" in CUSTOMER_GENERAL_SYSTEM_PROMPT
    assert "不要自己假设偏好" in CUSTOMER_GENERAL_SYSTEM_PROMPT
