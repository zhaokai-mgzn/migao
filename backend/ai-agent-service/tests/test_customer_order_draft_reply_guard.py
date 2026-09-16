"""写未成功前的回复归一（草稿态措辞 + 唯一下一步）—— OR-026 两条真实失败指纹的守卫。

## 为什么需要（issue #3750，run 34849029334 / SHA 929732b4）

C 端下单 prompt 的两处铁律只写在 prompt 里、**没有代码兜底**，实测被 LLM 违反：

- `customer_order_skill.py:81-82`：「在办流程里的任何修改…都只是草稿、订单未创建 →
  说「记下了，下单时一并提交」；**禁止**「已更新/已修改」」；
- `customer_order_skill.py:91`：「**验证码**：顾客**确认后**，友好引导…」（点确认卡**之后**）。

违反后果同族 —— **顾客可见的"承诺与事实不符"**，且第二条会让流程**不收敛**：

| 真实指纹（逐字取自 flake 台账） | 机制 |
|---|---|
| 次败 `状态宣告无工具落地(R2): 回复称「已更新」，但截至本轮没有任何写工具成功` | R2 说「手机号已更新」，而**没有任何写工具成功** |
| 首败 `must_succeed: order_create 共 2 次调用**无一成功**（R3:confirmation_required_no_card, R4:confirmation_required_no_card）` | 确认卡**待顾客点击**期间反复索要/复述验证码 → 顾客按话术供码 → 写调用被门禁拦下（**正确行为**）→ 顾客的动作推不动流程 → 循环到轮数耗尽 |

## 本文件的守卫（每条断言都要**会红**）

1. 纯函数判据：完成/变更态措辞被归一为草稿态；验证码诉求句被去掉；`<interact>` 卡片块原样保留；
2. **红证（注入式）**：把 OR-026 的真实回复喂给**旧实现**（等价于"不做归一"的恒等映射），
   断言它**必然**命中 `_WRITE_CLAIM_MARKERS` / 含验证码诉求 —— 证明第 1 组断言改前会红；
3. 端到端（`execute_skill` + mock LLM）：存在未确认的「已校验待执行」写时回复被归一；
4. **反向守卫（防误伤）**：顾客已点卡（`confirmed_write_tool == target`）时，
   「请输入短信验证码」这句**必要**引导必须原样保留 —— 删掉它才是真死锁；
   写已闭环（pending 已清）时「订单已提交成功」也必须原样保留。
"""
# case_ids: OR-026
import asyncio
import json

from unittest.mock import patch, AsyncMock, MagicMock

from langchain_core.messages import HumanMessage, AIMessage

from app.graph.skills.base_skill import (
    execute_skill,
    normalize_draft_state_reply,
    _DRAFT_CLAIM_MARKERS,
    _DRAFT_CODE_ASK_HINTS,
    _DRAFT_STATE_PHRASE,
)

# ── OR-026 真实夹具（逐字取自 run 34849029334 的 xiaobu flake 台账 / trace）──
# 次败 R2：手机号改成 13800138000 后，模型**没有任何写工具成功**却说「已更新」。
OR026_R2_REPLY = (
    "好的亲，手机号已更新～\n"
    "地址就用您上次的：**浙江省杭州市西湖区文三路 1 号 1 幢 101 室** ✅\n"
    "为了您的账户安全，创建订单前需要验证手机号。请把收到的短信验证码发我～"
)
# 首败 R3：顾客刚供码、确认卡待点，模型复述验证码并把顾客引向"再给一次码"。
OR026_R3_REPLY = (
    "验证码收到啦～ 正在为您提交订单，请您稍等一下下哦 💕\n"
    "亲，订单明细都在这儿啦，麻烦您核对一下～ 没问题就点一下「确认下单」"
)
_CONFIRM_CARD_XML = (
    '\n<interact>{"component": "confirm", "title": "请确认订单信息", '
    '"fields": [{"label": "手机号", "value": "13800138000"}], '
    '"confirmValue": "确认：手机号=13800138000"}</interact>'
)


def _legacy_reply(text: str) -> str:
    """**旧实现**的等价物（issue #3750 之前：收尾不做任何归一）—— 只用于证明"改前会红"。"""
    return str(text or "")


def _hits_marker(text: str) -> str:
    return next((m for m in _DRAFT_CLAIM_MARKERS if m in str(text or "")), "")


def _hits_code_ask(text: str) -> str:
    return next((h for h in _DRAFT_CODE_ASK_HINTS if h in str(text or "")), "")


# ── 1. 纯函数判据 ────────────────────────────────────────────────────────────

class TestNormalizeDraftStateReply:
    def test_claim_marker_replaced_by_draft_phrase(self):
        out, notes = normalize_draft_state_reply(OR026_R2_REPLY)
        assert _hits_marker(out) == "", f"归一后仍残留完成态措辞：{out!r}"
        assert _DRAFT_STATE_PHRASE in out, f"未落到草稿态措辞：{out!r}"
        assert notes, "命中了措辞却没留归因说明（报告里无从归因）"

    def test_code_ask_sentence_dropped(self):
        out, _ = normalize_draft_state_reply(OR026_R3_REPLY)
        assert _hits_code_ask(out) == "", f"归一后仍在索要/复述验证码：{out!r}"
        # 唯一下一步（点卡）必须留下 —— 否则顾客没有可执行动作
        assert "确认下单" in out, f"把「点确认卡」这个唯一下一步也删了：{out!r}"

    def test_confirm_card_block_preserved_verbatim(self):
        out, _ = normalize_draft_state_reply(OR026_R2_REPLY + _CONFIRM_CARD_XML)
        # 卡片块**内容**必须逐字保留（含 confirmValue —— 门禁比对的就是它；
        # 只有块前的换行可能因整句删除被一并吃掉，不影响卡片解析）。
        payload = _CONFIRM_CARD_XML.strip()
        assert payload in out, f"卡片块被改写/删除了（卡是顾客唯一的操作入口）：{out!r}"
        assert '"confirmValue": "确认：手机号=13800138000"' in out, (
            f"confirmValue 被动过 → 顾客点卡也过不了门禁：{out!r}")

    def test_all_claim_markers_are_normalized(self):
        """判据是全表生效的（不是只为 OR-026 挑的几个词）。"""
        for marker in _DRAFT_CLAIM_MARKERS:
            out, _ = normalize_draft_state_reply(f"好的，{marker}了")
            assert _hits_marker(out) == "", f"标记「{marker}」未被归一：{out!r}"

    def test_empty_after_strip_keeps_one_actionable_reply(self):
        out, _ = normalize_draft_state_reply("请把收到的短信验证码发我～")
        assert out.strip(), "全删净后回复为空 —— 顾客拿不到任何可执行动作"
        assert _hits_code_ask(out) == "", f"兜底话术自己又提了验证码：{out!r}"


# ── 2. 红证（注入式）：同一夹具在**旧实现**下必红 ──────────────────────────────

class TestRedProofAgainstLegacyBehaviour:
    """证明第 1 组断言不是空断言 —— 旧实现下它们**必然**红。"""

    def test_or026_r2_reply_legacy_hits_claim_marker(self):
        assert _hits_marker(_legacy_reply(OR026_R2_REPLY)) == "已更新", (
            "旧实现下该回复竟不含完成态措辞 —— 夹具失效，第 1 组断言就成了空断言")

    def test_or026_r3_reply_legacy_hits_code_ask(self):
        assert _hits_code_ask(_legacy_reply(OR026_R3_REPLY)) == "验证码", (
            "旧实现下该回复竟不含验证码诉求 —— 夹具失效，收敛类断言就成了空断言")

    def test_legacy_differs_from_normalized(self):
        """双向判据：归一**真的改了东西**（防把归一实现成恒等映射）。"""
        for fixture in (OR026_R2_REPLY, OR026_R3_REPLY):
            out, _ = normalize_draft_state_reply(fixture)
            assert out != _legacy_reply(fixture), f"归一没生效（恒等）：{fixture!r}"


# ── 3/4. 端到端：execute_skill 走完整收尾（含 mock 会话状态）──────────────────

_PENDING = {"target_tool": "order_create", "target_action": "create", "params": {}}


class _DemoWriteTool:
    """测试替身：`read_only=False` + 不受确认门禁（只用来隔离判据④）。"""

    name = "demo_write"
    read_only = False
    destructive = False
    requires_confirmation = False
    parameters = {"type": "object", "properties": {}}


def _tool_call(name: str, args: dict):
    msg = MagicMock(spec=AIMessage)
    msg.content = ""
    msg.tool_calls = [{"name": name, "args": args, "id": "t1"}]
    return msg


def _run_epilogue(reply_text: str, *, store_state: dict | None = None,
                  tool_side: list | None = None, write_tool=None):
    """跑一次 `execute_skill`，返回 `final_answer`。

    `store_state` = 会话状态（模拟 SessionStateStore 里已落库的内容）；
    `tool_side`   = 额外的 LLM 回复（用于"模型先调写工具、再给最终文本"的两步形态）。
    """
    shared = dict(store_state or {})

    class _Store:
        async def load(self, sid):
            out = {"grounded_product_detail": {"product_id": "prod_eval_blackout"}}
            out.update(shared)
            return out

        async def commit(self, sid, full):
            shared.clear()
            shared.update({k: v for k, v in (full or {}).items()
                           if k != "grounded_product_detail"})
            return True

        async def clear(self, sid):
            return True

    final = MagicMock(spec=AIMessage)
    final.content = reply_text
    final.tool_calls = []
    side = list(tool_side or []) + [final]

    async def fake_execute(tool, args, ctx, state):
        payload = {"success": True, "data": {}}
        return json.dumps(payload, ensure_ascii=False), payload

    with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
         patch("app.memory.session_state_store.SessionStateStore",
               side_effect=lambda *a, **k: _Store()), \
         patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
         patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
         patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
         patch("app.graph.skills.base_skill.set_tool_context"), \
         patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute):
        registry = MagicMock()
        registry.get_langchain_tools.return_value = []
        registry.get_tool.side_effect = lambda n: (write_tool if n == getattr(write_tool, "name", None)
                                                  else None)
        create_reg.return_value = registry
        breaker = MagicMock()

        async def _pt(fn):
            return await fn()

        breaker.call = _pt
        get_breaker.return_value = breaker
        llm = MagicMock()
        llm.bind_tools.return_value = llm
        llm.ainvoke = AsyncMock(side_effect=side)
        get_llm.return_value = llm
        mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)
        out = asyncio.run(execute_skill(
            state={
                "messages": [HumanMessage(content="123456")],
                "tenant_id": 1, "user_id": 100, "session_id": "sess_draft_guard",
                "role": "customer", "intent_result": None, "route_decision": None,
                "entities": {}, "intent_chain": [], "stage": "initial",
                "cached_answer": None, "final_answer": "", "skill_used": "",
                "suggestions": [],
            },
            skill_name="customer_order",
            tool_names=["order_create"],
            system_prompt="你是小布",
        ))
    return str(out.get("final_answer") or ""), shared


class TestEpilogueGuard:
    def test_unconfirmed_pending_write_normalizes_reply(self):
        """存在未确认的「已校验待执行」写 → 回复被归一（措辞 + 验证码诉求）。"""
        answer, _ = _run_epilogue(OR026_R2_REPLY,
                                  store_state={"pending_validated_input": _PENDING})
        assert _hits_marker(answer) == "", f"完成态措辞没被归一：{answer!r}"
        assert _hits_code_ask(answer) == "", f"验证码诉求没被去掉：{answer!r}"

    def test_blocked_write_round_reply_normalized(self):
        """首败 R3 形态（顾客供码、卡待点）→ 不再把顾客引向"再给一次码"。"""
        answer, _ = _run_epilogue(OR026_R3_REPLY,
                                  store_state={"pending_validated_input": _PENDING})
        assert _hits_code_ask(answer) == "", f"仍在复述验证码：{answer!r}"
        assert "确认下单" in answer, f"唯一下一步（点卡）被删掉了：{answer!r}"

    def test_card_clicked_keeps_necessary_sms_ask(self):
        """**反向守卫**：顾客已点卡（confirmed_write_tool==order_create）→
        「请输入短信验证码」是**必要**引导，必须原样保留（删掉它才是真死锁）。"""
        ask = "为了您的账户安全，创建订单前需要验证手机号。请输入短信验证码"
        answer, _ = _run_epilogue(
            ask, store_state={"pending_validated_input": _PENDING,
                              "confirmed_write_tool": "order_create"})
        assert ask in answer, f"误伤了已点卡轮的必要验证码引导：{answer!r}"

    def test_closed_loop_keeps_success_wording(self):
        """写已闭环（pending 已清）→「订单已提交成功」必须原样保留（不得误改成草稿态）。"""
        # 用**命中标记**的话术（真实回执就长这样）：这样一旦判据②失效（把已闭环的轮次
        # 也纳入归一），断言就会红 —— 否则测试是空断言（"没改"可能只是"本来就没命中"）。
        done = "亲，订单已提交成功啦！📋 订单号：20260914991500013"
        answer, _ = _run_epilogue(done, store_state={})
        assert "订单已提交成功" in answer, (
            f"把已成功的回执误改成草稿态（顾客会以为没下单）：{answer!r}")
        assert _DRAFT_STATE_PHRASE not in answer, (
            f"成功的回执被改写成草稿态措辞：{answer!r}")

    def test_write_success_this_turn_disables_normalization(self):
        """**反向红证（隔离判据④）**：同一轮有**非只读工具成功** ⇒ 不得归一。

        构造方式：pending 目标仍是 `order_create` 且**未被确认**（判据②③仍成立），
        只让本轮成功执行一把**非只读且不受确认门禁**的工具 ⇒ 唯一能让守卫闭嘴的就是判据④
        （`not _write_ok`）。用本文件自带的测试替身而不是真实 B 端工具，避免测试与
        另一个包的改动面耦合。
        为什么必须有这条：否则"把守卫写成恒真"也能过前面所有断言（假绿）。
        """
        answer, _ = _run_epilogue(
            "好的亲，已为您提交转人工申请，客服马上就联系您～",
            store_state={"pending_validated_input": _PENDING},
            tool_side=[_tool_call("demo_write", {"note": "x"})],
            write_tool=_DemoWriteTool())
        assert "已为您提交转人工申请" in answer, (
            f"本轮有非只读工具成功，回复却被归一（守卫判据④失效）：{answer!r}")
