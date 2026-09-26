# case_ids: OR-014
"""L1 域逃逸的「伪域切换」：**已知窗口**的可执行证据（issue #3784）。

## 这是什么（不是修复，是**登记**）

用户 **2026-09-26 裁定 ②**：「只做缓解 + 登记口径」—— 引入「本 skill 在纯文本轮里问过问题」
这个**新会话状态事实**的机械修法**被明确拒绝**（它会误吞合法换域：紧随一句提问之后的
「改一下遮光窗帘的价格」正是最常见形态，见 issue #3784 的假阴性风险段）。

⇒ 本文件把"窗口**存在**"变成**会红的判据**（而不是一段散文）：

1. 用**真实** `RuleMatcher` + `route_by_intent` 逐条复算 OR-014 R3 的链路；
2. 断言"逃逸后落到的 skill **服务不了**在办流程的写动作"——**事实驱动**
   （读工具注册表声明），**不含** skill 名白名单、**不含**整句原文白名单
   （issue #3784 验收判据 4）；
3. 同时钉住「为什么不能加判据」：**合法换域**与 R3 式回答在本判据可见的**全部事实**上
   **完全同形**（同一段代码路径、同一组注册表事实）—— 这条一旦被"顺手加个白名单/整句判断"
   破坏，本文件会红。
4. **窗口被关闭**（无论是引入状态事实还是别的机制）⇒ 判据 #1 变红 ⇒ 必须**显式**改口径，
   不允许静默漂移；口径与关闭条件写在
   `docs/wiki/AI-Agent.md` 的「意图路由流程 / 已知窗口」一节。

## 本文件**不**做的事

· 不改任何产品行为（不放宽、也不加白名单）；
· 不引入新的会话状态事实（用户裁定不做）；
· 不声称任何行为修复 —— 缓解在**下游**（#3782 的熔断 + 回锁），本窗口本身仍然开着。
"""
import sys
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from app.graph.nodes import route_by_intent
from app.graph.skills.base_skill import ORDER_WRITE_TOOL
from app.graph.skills.skill_registry import get_skill_registry
from app.router.rule_matcher import RuleMatcher

REPO_ROOT = Path(__file__).resolve().parents[3]

#: R3 的真实原文（OR-014 的第 3 轮台词；判定跑 run 34856561459）
R3_ANSWER = "不需要其他加工项"
#: 合法换域的真实原文（#3625 G3/T2 契约的绿证输入，见 `test_or014_flow_owner_guard.py`）
LEGITIMATE_SWITCH = "改一下遮光窗帘的价格"

#: 在办流程（C 端下单）的 skill —— 事实来自注册表，不是白名单：
#: 取"其工具集**含**在办写工具"的那个 skill。
PENDING_SKILL = "customer_order"


def _state(msg: str, *, intent_result: dict, skill: str = PENDING_SKILL) -> dict:
    """OR-014 的会话状态（**没有**任何卡事实 —— R2 的提问是纯文本，这正是窗口的成因）。"""
    return {
        "messages": [HumanMessage(content=msg)],
        "pending_interact_skill": skill,
        # 刻意不设 `last_card` / `last_confirm_*`：R2 是**纯文本**提问 ⇒
        # 基于卡的豁免链（#3677 / #3718）天然看不见 R3（issue #3784 的机制半边）。
        "agent_type": "xiaobu",
        "tenant_id": 1,
        "session_id": "sess_or014_window",
        "intent_result": intent_result,
    }


def _l1(msg: str) -> dict:
    """真实 L1 判定（`RuleMatcher`）→ `intent_result` 形态；不命中即让用例失败。"""
    m = RuleMatcher().match(msg)
    if m is None:
        pytest.fail(f"L1 未命中 {msg!r} —— 本判据的前提不成立")
    return {"intent": m.intent.value, "confidence": 0.95, "source": m.source}


def _skill_tools(skill: str) -> set:
    """该 skill 声明的工具集（**事实源** = 技能注册表，不是测试里的白名单）。"""
    reg = get_skill_registry()
    for s in reg.get_all():
        if str(getattr(s, "name", "")) == skill:
            return {str(t) for t in (getattr(s, "tool_names", None) or [])}
    pytest.fail(f"技能注册表里没有 {skill!r} —— 本判据的事实源失效（先核对注册表）")


class TestTheWindowExistsToday:
    """**窗口存在的可执行证据**：逐条复算 OR-014 R3 的链路。"""

    def test_r3_is_a_high_confidence_rule_hit_on_another_domain(self):
        l1 = _l1(R3_ANSWER)
        assert l1["source"] == "rule", f"R3 不再是规则命中（本判据前提变化）：{l1}"
        assert l1["intent"] == "product_inquiry", (
            f"R3 的 L1 判定变了（{l1['intent']}）—— 若已不是商品域，本窗口的成因应重新核对")

    def test_the_escape_clears_the_session_lock_and_leaves_the_order_flow(self):
        """🔴 这就是窗口本身：**回答本流程刚问的问题**被当成话题切换。"""
        state = _state(R3_ANSWER, intent_result=_l1(R3_ANSWER))
        routed = route_by_intent(state)
        assert routed != PENDING_SKILL, (
            f"逃逸没有发生（routed={routed}）—— 窗口可能已被关闭；"
            f"若这是**有意**关闭，请同步改 docs/wiki/AI-Agent.md 的「已知窗口」一节"
            f"与本文件的判据（本红即「口径漂移」信号）")
        assert state["pending_interact_skill"] == "", "逃逸未释放会话锁"

    def test_the_routed_skill_cannot_serve_the_in_flight_write(self):
        """**后果**（事实驱动）：落到的新 skill 工具集里**没有**在办流程的写工具。

        反证同一件事不是空断言：在办 skill 的工具集里**有**它 —— 差异由注册表事实给出。
        """
        routed = route_by_intent(_state(R3_ANSWER, intent_result=_l1(R3_ANSWER)))
        target_tools = _skill_tools(routed)
        pending_tools = _skill_tools(PENDING_SKILL)
        assert ORDER_WRITE_TOOL in pending_tools, (
            f"{PENDING_SKILL} 的工具集里没有 {ORDER_WRITE_TOOL} —— 在办「写流程」的前提不成立："
            f"{sorted(pending_tools)}")
        assert ORDER_WRITE_TOOL not in target_tools, (
            f"{routed} 现在**能**服务 {ORDER_WRITE_TOOL} 了 —— 伪域切换的后果已消失，"
            f"本登记需要重新核对（别把「窗口还在」当结论）")

    def test_the_trigger_keyword_is_the_live_rule_not_a_test_double(self):
        """成因面（零 LLM）：触发逃逸的是 `rule_matcher` 的**商品域关键词表**里的「加工项」。"""
        l1 = _l1(R3_ANSWER)
        assert l1["intent"] == "product_inquiry" and l1["source"] == "rule"
        # 去掉那个关键词 ⇒ 不再判商品域（证明成因确实是它，而不是别的规则）
        stripped = R3_ANSWER.replace("加工项", "工序")
        m = RuleMatcher().match(stripped)
        got = m.intent.value if m is not None else ""
        assert got != "product_inquiry", (
            f"不含「加工项」的同类句子仍被判商品域（{got}）⇒ 本判据的归因指向错了对象")


class TestWhyNoCriterionWasAdded:
    """**为什么留着**：合法换域与 R3 式回答在本判据可见的**全部事实**上同形。"""

    def test_both_inputs_take_the_same_escape_path(self):
        """两条输入走**同一个分支**、同样释放会话锁 ⇒ 用"注册表事实 + 会话状态"区分不了它们。

        这正是 issue #3784 的反例表（#3625 G3/T2 的正当诉求与 R3 事实集合完全同形）；
        任何"写流程不许逃逸"的判据都会连合法换域一起拦 ⇒ 本窗口**只能**靠新的状态事实区分，
        而那个事实被用户裁定不做（2026-09-26）。
        """
        legit_l1 = _l1(LEGITIMATE_SWITCH)
        assert legit_l1["source"] == "rule", legit_l1
        r3_state = _state(R3_ANSWER, intent_result=_l1(R3_ANSWER))
        legit_state = _state(LEGITIMATE_SWITCH, intent_result=legit_l1)
        r3_routed, legit_routed = route_by_intent(r3_state), route_by_intent(legit_state)
        assert r3_routed == legit_routed, (
            f"两条输入已被分开（{r3_routed} vs {legit_routed}）—— 说明出现了新的区分事实；"
            f"若那是**有意**引入的判据，请把本文件与文档的「已知窗口」口径一起改掉")
        assert (r3_state["pending_interact_skill"], legit_state["pending_interact_skill"]) \
            == ("", ""), "两条输入对会话锁的作用不同 —— 与声明的事实不同形"

    def test_legitimate_switch_must_keep_switching(self):
        """合法换域**必须**照旧换（#3625 G3/T2 契约）—— 它是"不加判据"的核心理由。"""
        state = _state(LEGITIMATE_SWITCH, intent_result=_l1(LEGITIMATE_SWITCH))
        assert route_by_intent(state) != PENDING_SKILL, (
            "在办订单流程里明确的商品诉求被锁死在订单域 —— #3625 G3/T2 契约回归"
            "（本文件存在的意义之一就是守住「不许为了让 R3 变绿而把逃逸一刀切关掉」）")


class TestTheRegistrationCanGoRed:
    """**判据不是恒真的**：注入"窗口被关闭"的形态 ⇒ `TestTheWindowExistsToday` 必须变红。"""

    def test_closing_the_window_turns_the_evidence_red(self, monkeypatch):
        """注入：让 L1 判定不再落到别的域（= 逃逸口不再触发）⇒ 会话留在订单流程。"""
        import app.graph.nodes as nodes

        monkeypatch.setattr(nodes, "_rule_intent_domain", lambda intent, agent_type: "")
        state = _state(R3_ANSWER, intent_result=_l1(R3_ANSWER))
        assert route_by_intent(state) == PENDING_SKILL, (
            "注入式关闭窗口后会话**没有**留在在办流程 —— 本红证的前提不成立（先核对注入）")
        # ⇒ 同一条断言在窗口存在时判红、在窗口关闭时判绿（方向相反）⇒ 判据是承重的
        assert state["pending_interact_skill"] == PENDING_SKILL

    def test_downstream_mitigation_is_not_confused_with_a_fix(self):
        """**缓解 ≠ 修复**：下游归属仍有事实源（#3782 的回锁按注册表声明取归属），
        但它不改本窗口的路由行为 —— 本登记不许被读成"已修"。

        判据：路由结果稳定地**不是**在办 skill（窗口照旧），而归锁机制另有其判据
        （`test_or014_flow_owner_guard.py`）。
        """
        routed = route_by_intent(_state(R3_ANSWER, intent_result=_l1(R3_ANSWER)))
        assert routed != PENDING_SKILL


class TestRegistrationIsDurable:
    """登记必须**落仓**（不是只存在于会话上下文/PR 描述里）：文档 + 代码指针都在。"""

    def test_the_doc_owns_the_wording(self):
        doc = (REPO_ROOT / "docs" / "wiki" / "AI-Agent.md").read_text(encoding="utf-8")
        assert "已知窗口" in doc and "伪域切换" in doc, "路由语义文档里的窗口登记被删掉了"
        for token in ("只做缓解 + 登记口径", "重开条件"):
            assert token in doc, f"登记缺少「{token}」—— 读者会把它读成「已修」或「待修」"

    def test_the_escape_hatch_points_at_the_registration(self):
        src = (REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph"
               / "nodes.py").read_text(encoding="utf-8")
        assert "已知窗口（有意不修" in src, (
            "逃逸口旁边的登记指针被删掉了 —— 下一位改这里的人会以为它是「待修的 bug」或「正常行为」")
        assert "test_or014_pseudo_domain_switch_window.py" in src, (
            "代码里没有指向本证据文件的指针 ⇒ 口径与判据会各自漂移")
