# case_ids: CH-003
"""CH-003 的**判据强度** + 与「纯看轮投影」机制的接线（issue #9280）。

## 为什么本文件存在（本 PR 唯一的固化面）

`#9298` 已经从**机制面**根修了同一个病灶（run 46086496186：顾客只发「帮我看看」，
模型自编「遮光窗帘」「奶油风」两个偏好直接 `product_search` + `product_detail`）：
`app/graph/skills/tool_selection.py::plan_vague_round_read_tools` 让「纯看」轮**只投影**
保底集合（交互卡 / 知识 / 校验 / 导航）⇒ 三个业务查询工具**不在本轮注册表里**。

但它**明写「不改任何用例期望与判分口径」** —— 于是 CH-003 的判据仍停在
`direct_reply or interact`：只测**形状**。实测（见 PR body 的对照读数）「猜关键词直接搜 +
再补一张 choice 卡」这种形态**照样判绿**（`interact` 分支命中），也就是**模型可以一边猜一边过**。
本文件补的正是那一块：**把用例判据与机制语义绑在一起**。

## 本文件钉住的三件事（每件都有红证）

| # | 断言 | 红证（改这一处即红） |
|---|---|---|
| ① | CH-003 的期望是**产出侧** `reply or interact` | 改回 `direct_reply or interact` ⇒ 红（形态判据回归） |
| ② | CH-003 的 `forbidden_tools` 覆盖三个业务查询工具 | 删掉 `forbidden_tools` 任一条 ⇒ 红（意图不明时又能臆断检索） |
| ③ | 「纯看」轮的工具面**确实**不含它们，且**明确输入照旧** | `is_vague_round` 恒假 / 白名单改成返回声明面 ⇒ 红；`prepare_turn` 摘掉接线 ⇒ 红 |

## 边界（照实登记）

- 机制本体与它的 34 条 L0 判据在 `backend/ai-agent-service/tests/test_vague_round_tool_scope.py`
  （#9298）；本文件**不重复**它的判据，只做「用例期望 ⇄ 机制语义」这一层接线 + 用例面收强的守卫。
- 「模型被拦后是否真的改成发候选卡/追问」依赖模型遵从，属**评测面**（CH-003 的
  `reply or interact` + `forbidden_tools` 就是它的判据）；本文件不做真实 LLM 判定（#4262）。
"""
import sys
from pathlib import Path

import yaml
from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graph.skills.customer_general_skill import CUSTOMER_GENERAL_TOOLS  # noqa: E402
from app.graph.skills.tool_selection import (  # noqa: E402
    is_vague_round,
    plan_vague_round_read_tools,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CHAT_CASES = REPO_ROOT / ".github" / "cases" / "chat.yml"

#: 意图不明时**不得**臆断调用的业务查询工具（= CH-003 的 `forbidden_tools` 必须覆盖的集合；
#: 与 #9298 的「纯看轮白名单把它们摘掉」是**同一组事实**）。
BUSINESS_QUERY_TOOLS = ("product_search", "product_detail", "customer_order_query")


def _case(case_id: str) -> dict:
    """按 id 取用例块（fail-closed：取不到就报错，不静默通过）。"""
    data = yaml.safe_load(CHAT_CASES.read_text(encoding="utf-8"))
    hit = next((c for c in (data or {}).get("cases") or [] if str(c.get("id")) == case_id), None)
    if hit is None:
        raise AssertionError(f"{CHAT_CASES} 里没有用例 {case_id}（fail-closed）")
    return hit


def _state(text: str) -> dict:
    """C 端（xiaobu）单轮 state（判据只看这两样：agent_type + 最后一条用户消息）。"""
    return {"agent_type": "xiaobu", "messages": [HumanMessage(content=text)]}


# ── ① 期望是产出侧 token，不是形状判据 ─────────────────────────────────────────

def test_ch003_expectation_is_production_side():
    """CH-003 的期望必须是 `reply or interact`（旧写法只测形状：猜完再补卡就判绿）。"""
    case = _case("CH-003")
    expectations = [str((e or {}).get("tool") or e) for e in case.get("expectations") or []]
    assert expectations == ["reply or interact"]


# ── ② 意图不明时不得臆断检索（用例面收强）─────────────────────────────────────

def test_ch003_forbids_business_query_tools():
    """`forbidden_tools` 必须覆盖三个业务查询工具 —— 这是「猜关键词直接搜」的**具名红**通道。"""
    case = _case("CH-003")
    forbidden = {
        str((spec or {}).get("tool") or spec) for spec in case.get("forbidden_tools") or []
    }
    missing = [t for t in BUSINESS_QUERY_TOOLS if t not in forbidden]
    assert not missing, f"CH-003 的 forbidden_tools 缺 {missing}（意图不明时又能臆断检索）"


# ── ③ 与机制的接线：纯看轮不得投影业务查询工具，明确输入照旧 ────────────────────

def test_ch003_input_is_a_pure_look_round():
    """CH-003 的 R1 原话必须落进「纯看轮」（否则机制的射程不覆盖本用例）。"""
    case = _case("CH-003")
    assert case.get("user_inputs") == ["帮我看看"]
    for text in case["user_inputs"]:
        assert is_vague_round(_state(text)) is True


def test_vague_round_surface_excludes_the_forbidden_tools():
    """纯看轮的工具面**确实**不含那三个工具（机制被改回去 ⇒ 本判据具名红）。"""
    keep = plan_vague_round_read_tools(_state("帮我看看"), list(CUSTOMER_GENERAL_TOOLS))
    assert isinstance(keep, list), "纯看轮回到了「不裁」⇒ 业务查询工具又在注册表里（#9298 机制被摘）"
    removed = set(CUSTOMER_GENERAL_TOOLS) - set(keep)
    still_there = [t for t in BUSINESS_QUERY_TOOLS if t not in removed]
    assert not still_there, f"纯看轮仍投影 {still_there} —— 与 CH-003 的 forbidden_tools 矛盾"


def test_clear_input_keeps_the_full_tool_face():
    """对照（防过度拦截）：顾客说了具体对象 ⇒ 工具面**不动**。"""
    assert plan_vague_round_read_tools(
        _state("遮光窗帘多少钱"), list(CUSTOMER_GENERAL_TOOLS)) is None


def test_prepare_turn_wires_the_vague_projection():
    """接线守卫：`prepare_turn` 必须真的调用那档投影（摘掉 = 判据变空壳）。"""
    src = (REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph" / "skills"
           / "execution" / "prepare_turn.py").read_text(encoding="utf-8")
    assert "plan_vague_round_read_tools(" in src
