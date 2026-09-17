# case_ids: OR-009
"""`validate_input` 校验失败禁止写 —— prompt 铁律落成**代码闸门**（issue #4073，S2）。

铁律原文（`app/graph/skills/references/PROMPT-rules.md`）：
> **铁律：validate_input 校验失败时，禁止继续执行写工具。**
> 禁止"校验失败就直接执行"——校验层的存在就是为了拦住参数错误；绕过它等于关闭安全网。

**改前的病灶**（issue #4073 实测判据）：这条铁律**只活在 prompt 里** ——
`react_turn.py` 只在 `tool_name == "validate_input" and result_dict.get("success")` 时落
`PENDING_KEY`（成功路径），**失败路径不留任何痕迹**，写工具调用点没有任何"校验失败过就拦住"
的判据 ⇒ 模型"校验失败后照写"时代码侧无从拦，唯一防线是模型自觉。
同一条产线上「单价接地」（`unit_price_grounding_error`）**有**代码闸门（fail-closed），
这条只有措辞 —— 本文件把保护等级拉平。

**本文件的两类判据**（缺一不可）：

* 红证 `TestValidationFailureBlocksWrite`：校验失败后仍写 ⇒ **改前放行、改后拦下**。
  ④ 用 `confirmed_write_tool` 预置"顾客已点确认卡"的状态 —— 证明闸门在**确认门禁之外
  独立生效**（#3414「只补卡不放行写」同族）。
* R2 阴性负例 `TestNoLegitimateWriteIsBlocked`（四条，issue 要求全有）：
  ① 从未 `validate_input` 过的写流程照常放行；② 校验**成功后**的写照常放行；
  ③ 校验失败 → 补参并重新校验成功 → 写恢复放行；④ 只读工具不受影响。

**适用域声明**：本闸门只对**被 `validate_input` 校验过的目标**生效（没有记录 = 不管）——
这正是 R2 ① 之所以必须放行的机制原因，不是巧合。

**范式**：scripted-LLM 驱动**真实** `execute_skill`（同 `tests/test_order_logistics_chain.py`
/ `tests/test_capability_denial_guard.py`），`_execute_tool_safe` 换成记账假实现 ——
断言落在"这个写到底有没有被执行"上（效果层），不是"某个函数被调用过"。
`case_ids` 选 OR-009：本闸门拦的写调用里，`validate_input` 已注册规则且失败面最完整的
就是**下单**流程（`order_create` + `inventory_manage` 等写工具共用同一处执行路径），
OR-009 正是该写路径的用例，故挂它。（闸门本身**不绑 skill**，见 `react_turn.py` 的注释。）
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.skills import base_skill
from app.graph.skills.base_skill import create_skill_registry


# ────────────────────── 夹具：真实 execute_skill + scripted LLM ──────────────────────

_ORDER_ITEMS = [{
    "product_id": "prod_eval_blackout",
    "product_name": "遮光窗帘",
    "quantity": 2,
    "unit_price": 168.0,
    "subtotal": 336.0,
}]

# 校验失败形态（真实 validate_input 的产物形状）：缺必填字段 ⇒ success=False + 可执行 suggestion
_BAD_ORDER_ARGS = {"action": "create", "customer_name": "赵凯"}     # 缺 phone/items
_BAD_INVENTORY_ARGS = {"product_id": "p1", "reason": "盘亏"}        # 缺 adjustment
_BAD_AFTERSALE_ARGS = {"ticket_type": "exchange"}                  # 缺 order_id

_FAILURE_RESULT = {
    "success": False,
    "error": "参数校验失败",
    "message": "参数校验失败，请补充以下信息后重试:\n  - 缺少必填字段: 客户电话 (customer_phone)",
    "suggestion": "按上面逐条补齐/改正参数后**重新调用 validate_input**",
}


class _FakeStateStore:
    """只回放事实的假会话存储（单测不连真实存储，见 migao-dev-flow §9.2）。"""

    def __init__(self, facts=None):
        self._facts = dict(facts or {})

    async def load(self, sid):
        return json.loads(json.dumps(self._facts, default=str))

    async def commit(self, sid, full):
        self._facts = json.loads(json.dumps(full or {}, default=str))
        return True


def _ai(content="", tool_calls=None):
    m = MagicMock()
    m.content = content
    m.tool_calls = list(tool_calls or [])
    m.usage_metadata = None
    return m


def _tc(name, args, cid):
    return {"name": name, "args": args, "id": cid, "type": "tool_call"}


def _run(replies, *, store_facts=None, tool_names=("validate_input", "order_create",
                                                   "inventory_manage"),
         skill_name="order", role="agent", agent_type="mibao",
         user_msg="确认调整库存", intent="order_create",
         validate_results=None, terminal_tools=()):
    """scripted-LLM 驱动**真实** `execute_skill`，返回 (out, llm, executed, store)。

    `executed` 只记**真正走到 `_execute_tool_safe`** 的调用 —— 被门禁拦下的调用不在其中，
    这正是"这个写到底有没有被执行"的效果层证据。

    `validate_results`：`{target_tool: 是否通过}`。默认**全部失败** —— 假 execute 若一律返回
    `success=True`，所有 validate_input 都会"通过"，失败路径根本不会被行使（首版即此错：
    测试红得在"改前"、绿不了在"改后"，因为根本没有失败账可拦）。
    `terminal_tools`：这些工具的成功结果带 `terminal=True`（触发 T2 事务终态重置）。
    """
    executed = []          # [(tool_name, args)]
    _vr = {k: bool(v) for k, v in (validate_results or {}).items()}
    _terminal = set(terminal_tools)

    async def fake_execute(tool, args, ctx, state):
        executed.append((tool.name, dict(args or {})))
        if tool.name == "validate_input":
            # 按 target_tool 分流：默认失败（本文件的被测形态就是"校验失败"）
            _target = str((args or {}).get("target_tool") or "")
            if _vr.get(_target, False):
                payload = {"success": True, "data": {"validated": True},
                           "message": "## ✅ 校验通过", "suggestion": ""}
            else:
                payload = dict(_FAILURE_RESULT)
        else:
            payload = {"success": True, "data": {"ok": True}, "summary": "ok",
                       "terminal": tool.name in _terminal}
        return json.dumps(payload, ensure_ascii=False), payload

    llm = MagicMock()
    llm.bind_tools.return_value = llm
    llm.ainvoke = AsyncMock(side_effect=replies)

    breaker = MagicMock()

    async def _pass_through(fn):
        return await fn()

    breaker.call = _pass_through
    store = _FakeStateStore(store_facts)

    with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
         patch("app.memory.session_state_store.SessionStateStore", return_value=store), \
         patch("app.graph.skills.base_skill.get_breaker", return_value=breaker), \
         patch("app.graph.skills.base_skill.get_skill_llm", return_value=llm), \
         patch("app.graph.skills.base_skill.LLMFactory") as llm_factory, \
         patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
         patch("app.graph.skills.base_skill.set_tool_context"), \
         patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute):
        create_reg.return_value = create_skill_registry(list(tool_names))
        llm_factory.create_skill_llm.return_value = llm
        mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)
        mem_cls.return_value.get_vision_analysis = AsyncMock(return_value="")
        mem_cls.return_value.clear_pending_skill = AsyncMock(return_value=True)
        state = {
            "messages": [HumanMessage(content=user_msg)],
            "intent_result": {"intent": intent, "confidence": 0.95, "source": "rule"},
            "tenant_id": 1,
            "user_id": 100,
            "session_id": "sess_4073_gate",
            "role": role,
            "agent_type": agent_type,
            "final_answer": "",
            "skill_used": "",
        }
        out = asyncio.run(base_skill.execute_skill(
            state=state, skill_name=skill_name, tool_names=list(tool_names),
            system_prompt="你是米宝"))

    return out, llm, executed, store


def _tool_calls_sent(llm):
    """每次 LLM 调用**实际发出**的 tool_calls（名字列表）—— 与 executed 对照可区分
    「模型发了但被门禁拦下」与「模型根本没发」。"""
    sent = []
    for call in llm.ainvoke.call_args_list:
        msgs = call.args[0] if call.args else call.kwargs.get("messages", [])
        for m in msgs:
            for tc in (getattr(m, "tool_calls", None) or []):
                if isinstance(tc, dict) and tc.get("name"):
                    sent.append(tc["name"])
    return sent


def _written_messages(llm):
    """最后一次 LLM 调用里追加的 ToolMessage/SystemMessage 文本（门禁话术的落点）。"""
    out = []
    for call in llm.ainvoke.call_args_list:
        msgs = call.args[0] if call.args else call.kwargs.get("messages", [])
        for m in msgs:
            txt = str(getattr(m, "content", ""))
            if isinstance(m, SystemMessage) or "validate" in txt or "拦截" in txt:
                out.append(txt)
    return out


def _failure_key(tool, action):
    """失败账的复合键（`<tool>::<action>`）—— 与 `pending_validated.validation_failure_key`
    同口径；这里**内联**而不 import，让"改前"的快照也能收集本文件（红证落在行为断言上）。"""
    return f"{tool}::{action}"


# ────────────────────── 红证：校验失败后仍写 ⇒ 必须被拦下 ──────────────────────

class TestValidationFailureBlocksWrite:
    """改前这些写**全部被执行**（放行）；改后必须一次都不执行。"""

    def test_write_after_failed_validation_is_blocked(self):
        """红证主形态：`validate_input` 失败（缺 phone/items）→ 模型直接调 `order_create`。

        改前：`order_create` 出现在 `executed` 里（订单真的落库）；
        改后：`executed` 里没有任何写工具调用，模型拿到 `validation_failed_write_blocked`
        + 可执行建议（补参 → 重新 validate_input → 再写），且该失败账**已落会话状态**。
        """
        replies = [
            _ai(tool_calls=[_tc("validate_input", {
                "target_tool": "order_create", "target_action": "create",
                "params": _BAD_ORDER_ARGS}, "c1")]),
            # 校验失败后照写（模型跳过"补参+重新校验"这一步）：
            _ai(tool_calls=[_tc("order_create", {
                "action": "create", "customer_name": "赵凯", "items": _ORDER_ITEMS}, "c2")]),
            _ai("好的，已为您提交订单。"),
        ]
        out, llm, executed, store = _run(replies)

        names = [n for n, _ in executed]
        assert "validate_input" in names, (
            f"前置条件不成立：validate_input 必须先真的跑过一次（否则这条测试什么都没验证），"
            f"实际 executed={names}")
        assert "order_create" not in names, (
            f"**校验失败后仍执行了写工具**（铁律：校验失败禁止继续写）：executed={names}")
        # 模型确实发出了这个写调用（排除"模型自己没发"造成的假绿）
        assert "order_create" in _tool_calls_sent(llm), "前置条件不成立：模型没发过写调用"
        # 失败账已落库（闸门的判据来源）
        assert store._facts.get("validation_failure", {}).get(
            _failure_key("order_create", "create")), (
            f"校验失败没有留痕 ⇒ 后续写调用点无从拦：{store._facts.get('validation_failure')}")
        # 拦下的那一步给了**可执行**的恢复路径
        blocked = [t for t in _written_messages(llm) if "order_create" in t and "validate_input" in t]
        assert blocked, (
            "拦下写调用时没有给出「补参 → 重新 validate_input → 再写」的可执行路径"
            "（fail-closed 不得死锁）")

    def test_gate_is_independent_of_the_confirmation_gate(self):
        """④ 顾客**已经点过确认卡**（`confirmed_write_tool` 已置位）也**不得**放行。

        #3414「只补卡不放行写」的同族：确认卡解决"要不要做"，不解决"参数对不对"——
        而校验失败正是参数不对。改前：确认门禁放行 ⇒ 写被执行；改后：本闸门先拦。
        """
        replies = [
            _ai(tool_calls=[_tc("validate_input", {
                "target_tool": "order_create", "target_action": "create",
                "params": _BAD_ORDER_ARGS}, "c1")]),
            _ai(tool_calls=[_tc("order_create", {
                "action": "create", "customer_name": "赵凯", "items": _ORDER_ITEMS}, "c2")]),
            _ai("好的，已为您提交订单。"),
        ]
        _, _, executed, _ = _run(replies, store_facts={"confirmed_write_tool": "order_create"})
        assert "order_create" not in [n for n, _ in executed], (
            "顾客点了确认卡就放行了**校验失败**的写 —— 闸门必须独立于确认门禁生效")

    def test_gate_is_not_skill_specific(self):
        """R1 机制级：**不是**给某个 skill 打补丁 —— 换个 skill/工具同样被拦。

        `product` skill + `inventory_manage(adjust)`（校验失败：缺 adjustment）⇒ 同样拦下。
        """
        replies = [
            _ai(tool_calls=[_tc("validate_input", {
                "target_tool": "inventory_manage", "target_action": "adjust",
                "params": _BAD_INVENTORY_ARGS}, "c1")]),
            _ai(tool_calls=[_tc("inventory_manage", {
                "action": "adjust", "product_id": "p1", "adjustment": -3,
                "reason": "盘亏"}, "c2")]),
            _ai("已调整库存。"),
        ]
        _, _, executed, _ = _run(
            replies, tool_names=("validate_input", "inventory_manage"),
            skill_name="product", intent="inventory_manage")
        assert "inventory_manage" not in [n for n, _ in executed], (
            f"闸门只对某个 skill 生效（本包要求共享执行路径）：executed={[n for n, _ in executed]}")

    def test_untouched_other_target_is_not_collateral_damage(self):
        """另一形态：失败的 `after_sales_manage` 不得拦住 `order_create`（账按目标对）。

        与下面 R2 ① 的区别：这里**有一条**失败账，只是目标不同 —— 证明拦截判据是
        「同 tool + 同 action」而不是"有失败账就全拦"。
        """
        replies = [
            _ai(tool_calls=[_tc("validate_input", {
                "target_tool": "after_sales_manage", "target_action": "create",
                "params": _BAD_AFTERSALE_ARGS}, "c1")]),
            _ai(tool_calls=[_tc("order_create", {
                "action": "create", "customer_name": "赵凯", "items": _ORDER_ITEMS}, "c2")]),
            _ai("好的，已为您提交订单。"),
        ]
        _, _, executed, _ = _run(
            replies, tool_names=("validate_input", "after_sales_manage", "order_create"),
            skill_name="order", intent="order_create")
        assert "order_create" in [n for n, _ in executed], (
            "别的目标（after_sales_manage）校验失败把无关的 order_create 也拦了 —— 误伤合法写")


# ────────────────────── R2 阴性负例：不许拦掉原本合法的写 ──────────────────────

class TestNoLegitimateWriteIsBlocked:
    """issue #4073 的 R2 四条，**必须全有**（每条都证明"没有拦掉原本合法的写"）。"""

    def test_r2_1_never_validated_write_passes(self):
        """R2 ① 从未 `validate_input` 过的写流程照常放行（适用域：没记录 = 不管）。

        各端都有这种写（B 端库存调整、C 端售后建单……不经校验层）。若本闸门按
        "会话里没有成功校验记录"判，就会把这**全部**合法写拦死 —— 故判据必须是
        "存在**未被覆盖的失败记录**"，而不是"没有成功记录"。
        """
        replies = [
            # 直接调写工具（本会话**从未**调过 validate_input）：
            _ai(tool_calls=[_tc("order_create", {
                "action": "create", "customer_name": "赵凯", "items": _ORDER_ITEMS}, "c1")]),
            _ai("好的，已为您提交订单。"),
        ]
        _, _, executed, store = _run(replies)
        assert "order_create" in [n for n, _ in executed], (
            "从未校验过的写被拦了 —— 闸门越界（适用域：只对校验过的目标生效）")
        assert not store._facts.get("validation_failure"), (
            f"没校验过却落了失败账：{store._facts.get('validation_failure')}")

    def test_r2_2_write_after_successful_validation_passes(self):
        """R2 ② 校验**成功后**的写照常放行（正常主路径，占绝大多数写）。"""
        replies = [
            _ai(tool_calls=[_tc("validate_input", {
                "target_tool": "order_create", "target_action": "create",
                "params": {"action": "create", "customer_name": "赵凯",
                           "customer_phone": "13800001111", "items": _ORDER_ITEMS}}, "c1")]),
            _ai(tool_calls=[_tc("order_create", {
                "action": "create", "customer_name": "赵凯",
                "customer_phone": "13800001111", "items": _ORDER_ITEMS}, "c2")]),
            _ai("好的，已为您提交订单。"),
        ]
        _, _, executed, store = _run(replies, validate_results={"order_create": True})
        assert "order_create" in [n for n, _ in executed], (
            f"校验成功后的写被拦了（正常主路径被误伤）：executed={[n for n, _ in executed]}")
        assert not store._facts.get("validation_failure"), "校验成功却落了失败账"

    def test_r2_3_param_fix_then_revalidate_restores_the_write(self):
        """R2 ③ 校验失败 → **补参并重新校验成功** → 写恢复放行（fail-closed 的恢复路径）。

        这条同时是「不得死锁」的判据：拦住之后模型必须能靠"补参 + 重新 validate_input"
        走回来。实现上对应"新的成功校验**清除**该目标的失败账"。
        """
        replies = [
            _ai(tool_calls=[_tc("validate_input", {
                "target_tool": "order_create", "target_action": "create",
                "params": _BAD_ORDER_ARGS}, "c1")]),                       # 失败
            _ai(tool_calls=[_tc("order_create", {
                "action": "create", "customer_name": "赵凯",
                "items": _ORDER_ITEMS}, "c2")]),                            # 被拦
            _ai(tool_calls=[_tc("validate_input", {
                "target_tool": "order_create", "target_action": "create",
                "params": {"action": "create", "customer_name": "赵凯",
                           "customer_phone": "13800001111",
                           "items": _ORDER_ITEMS}}, "c3")]),                 # 补参后重新校验 → 通过
            _ai(tool_calls=[_tc("order_create", {
                "action": "create", "customer_name": "赵凯",
                "customer_phone": "13800001111", "items": _ORDER_ITEMS}, "c4")]),
            _ai("好的，已为您提交订单。"),
        ]
        _, _, executed, store = _run(replies, validate_results={"order_create": True})
        names = [n for n, _ in executed]
        assert names.count("validate_input") == 2, (
            f"前置条件不成立：应有两次 validate_input（失败 → 补参后成功），实际 {names}")
        assert "order_create" in names, (
            f"补参并重新校验成功后写仍未恢复 —— fail-closed 变成了死锁：executed={names}")
        assert not store._facts.get("validation_failure"), (
            f"成功校验没有清除失败账：{store._facts.get('validation_failure')}")

    def test_r2_4_read_only_tools_are_unaffected(self):
        """R2 ④ 只读工具不受影响（本会话**有**失败账时，顾客要查商品照旧能查）。

        形态取最容易误伤的一种：**本会话已欠着一笔失败账**（`order_create::create`），
        顾客接着要查商品 —— 若闸门按"会话里有失败记录"判，查询就会被一起拦掉。
        判据必须是"本次调用**自己**是写工具 + 目标对得上"，与"欠不欠账"无关。
        """
        replies = [
            _ai(tool_calls=[_tc("validate_input", {
                "target_tool": "order_create", "target_action": "create",
                "params": _BAD_ORDER_ARGS}, "c1")]),                    # 留一笔失败账
            _ai(tool_calls=[_tc("product_search", {"keyword": "窗帘"}, "c2")]),
            _ai("为您找到以下窗帘……"),
        ]
        _, _, executed, store = _run(
            replies, tool_names=("validate_input", "product_search", "order_create"),
            skill_name="product", intent="product_inquiry", user_msg="看看有什么窗帘")
        assert "product_search" in [n for n, _ in executed], (
            "只读工具被拦了 —— 欠账期间顾客连查都查不了（过度拦截）")
        assert store._facts.get("validation_failure"), (
            "前置条件不成立：本测试要求会话里**确实**欠着一笔失败账")


# ────────────────────── 清除点（写成功 / 事务终态）──────────────────────

class TestFailureLedgerClearPoints:
    """交付形态 2 的三个清除点里，行为面能钉住的两个（第 2 个已在 R2 ③ 钉住）。"""

    def test_write_success_clears_that_targets_ledger(self):
        """清除点①：目标写工具**成功**执行 → 该目标的校验失败账闭环（且**只清这一个**）。

        形态（**闸门之外**的真实形态）：会话里欠着一笔 `order_create::create` 的失败账，
        而本次执行成功的是**另一个目标**（`inventory_manage::adjust`）——
        清账若按"哪个工具写成功了"就能清掉无关的账，等于"写成功一次全放行"
        （`update` 修好了 ≠ `create` 的参数对了）。

        ⚠️ 本测试**在改前也绿**（改前根本不存在失败账概念）—— 它不是红证，是**清除点口径**
        的守卫；红证在 `TestValidationFailureBlocksWrite`。断言落在判据（账的内容）上，
        不是"某个函数被调用过"。
        """
        replies = [
            _ai(tool_calls=[_tc("order_create", {
                "action": "create", "customer_name": "赵凯", "items": _ORDER_ITEMS}, "c1")]),
            _ai("好的，已为您提交订单。"),
        ]
        _, _, executed, store = _run(
            replies,
            store_facts={"validation_failure": {
                "inventory_manage::adjust": {"target_tool": "inventory_manage",
                                             "target_action": "adjust",
                                             "error": "参数校验失败"},
            }})
        assert "order_create" in [n for n, _ in executed], (
            "写没被执行（本测试的被测形态是「写成功要清账」，不是拦）")
        ledger = store._facts.get("validation_failure") or {}
        assert "inventory_manage::adjust" in ledger, (
            f"清账误伤：`order_create` 写成功却把 `inventory_manage::adjust` 的账抹了"
            f"（等价于'写成功一次全放行'）：{ledger}")

    def test_write_success_clears_only_its_own_matching_entry(self):
        """清除点①的**正向面**：同工具同 action 的账在写成功后清掉（否则同一目标永久锁死）。

        这里直接调 `clear_validation_failure`（纯函数）+ 行为面各钉一半：行为面无法构造
        "账还在却仍执行成功"的调用（闸门保证不会发生 —— 那正是它的职责），故正向面在
        纯函数层钉：**清指定目标 ⇒ 该目标不再命中，别的目标不受影响**。
        """
        import app.graph.pending_validated as m
        failure = {"target_tool": "inventory_manage", "target_action": "adjust",
                   "error": "参数校验失败"}
        other = {"target_tool": "order_create", "target_action": "create",
                 "error": "参数校验失败"}
        full = m.mark_validation_failure(
            m.mark_validation_failure({}, failure), other)
        out = m.clear_validation_failure(full, "inventory_manage", "adjust")
        assert m.is_failure_for(out, "inventory_manage", "adjust") is False
        assert m.is_failure_for(out, "order_create", "create") is True

    def test_terminal_success_clears_the_whole_ledger(self):
        """清除点③：事务终态（`terminal=True` → `reset_domain` 族）→ 上一笔的账全清。

        一笔业务已经走完，残留的失败账属于**上一笔**的参数形态；留给下一笔会把新流程误拦
        （fail-closed 不得变成"永久锁死"）。这里 `terminal=True` 的是**另一个**工具 ——
        终态重置的语义与"哪个工具写的"无关。
        """
        replies = [
            _ai(tool_calls=[_tc("order_create", {
                "action": "create", "customer_name": "赵凯", "items": _ORDER_ITEMS}, "c1")]),
            _ai("好的，已为您提交订单。"),
        ]
        _, _, executed, store = _run(
            replies,
            store_facts={"validation_failure": {
                "inventory_manage::adjust": {"target_tool": "inventory_manage",
                                             "target_action": "adjust",
                                             "error": "参数校验失败"}}},
            tool_names=("validate_input", "order_create"),
            terminal_tools=("order_create",))
        assert "order_create" in [n for n, _ in executed]
        assert not store._facts.get("validation_failure"), (
            f"事务终态没有清除校验失败账 ⇒ 下一笔业务会被上一笔的账误拦："
            f"{store._facts.get('validation_failure')}")

    def test_terminal_success_without_ledger_keeps_state(self):
        """阴性：没有失败账时终态重置**不得**动这件事（不写空壳键）。"""
        replies = [
            _ai(tool_calls=[_tc("order_create", {
                "action": "create", "customer_name": "赵凯", "items": _ORDER_ITEMS}, "c1")]),
            _ai("好的，已为您提交订单。"),
        ]
        _, _, _, store = _run(replies, store_facts={"some_other_key": 1},
                              terminal_tools=("order_create",))
        assert store._facts.get("some_other_key") == 1
        assert "validation_failure" not in store._facts


# ────────────────────── 纯函数层（判据本身可单测，零 IO）──────────────────────

class TestFailureLedgerPureFunctions:
    """留痕/清除/匹配三个纯函数直接钉住（行为面之外的口径守卫）。"""

    @staticmethod
    def _mod():
        import app.graph.pending_validated as m
        return m

    def test_extract_failure_only_on_failure(self):
        m = self._mod()
        args = {"target_tool": "order_create", "target_action": "create"}
        assert m.extract_validation_failure(args, {"success": True}) is None, \
            "校验成功也被记成失败 ⇒ 会把全部写流程锁死"
        assert m.extract_validation_failure(args, None) is None
        out = m.extract_validation_failure(args, dict(_FAILURE_RESULT))
        assert out["target_tool"] == "order_create" and out["target_action"] == "create"
        assert "customer_phone" in out["message"], "失败原因必须带上（模型才知道补什么）"

    def test_extract_failure_needs_a_target(self):
        m = self._mod()
        assert m.extract_validation_failure({}, dict(_FAILURE_RESULT)) is None, \
            "没有目标工具 ⇒ 无从判断拦哪个写工具（适用域：没记录 = 不管）"

    def test_extract_failure_truncates_long_text(self):
        """落库前截断：`validate_input` 的 message 是逐条明细，可能很长。

        不截断 = 给会话状态塞一个不受控大小的值（`SessionStateStore` 整存整取）。
        """
        m = self._mod()
        out = m.extract_validation_failure(
            {"target_tool": "order_create", "target_action": "create"},
            {"success": False, "error": "E" * 900, "message": "M" * 9000,
             "suggestion": "S" * 900})
        assert len(out["message"]) == 2000, f"message 未截断：{len(out['message'])}"
        assert len(out["error"]) == 200 and len(out["suggestion"]) == 500

    def test_mark_then_match_then_clear(self):
        m = self._mod()
        failure = m.extract_validation_failure(
            {"target_tool": "order_create", "target_action": "create"}, dict(_FAILURE_RESULT))
        full = m.mark_validation_failure({}, failure)
        assert m.is_failure_for(full, "order_create", "create") is True
        assert m.is_failure_for(full, "order_create", "update") is False, \
            "action 不同不得命中（同 tool 同 action 才拦）"
        assert m.is_failure_for(full, "inventory_manage", "adjust") is False
        assert m.is_failure_for({}, "order_create", "create") is False, "没账不得拦"
        cleared = m.clear_validation_failure(full, "order_create", "create")
        assert m.is_failure_for(cleared, "order_create", "create") is False
        assert m.VALIDATION_FAILURE_KEY not in cleared, "清空后不该留空壳键"

    def test_clear_only_touches_the_named_target(self):
        m = self._mod()
        f1 = m.extract_validation_failure(
            {"target_tool": "order_create", "target_action": "create"}, dict(_FAILURE_RESULT))
        f2 = m.extract_validation_failure(
            {"target_tool": "inventory_manage", "target_action": "adjust"}, dict(_FAILURE_RESULT))
        full = m.mark_validation_failure(m.mark_validation_failure({}, f1), f2)
        out = m.clear_validation_failure(full, "order_create", "create")
        assert m.is_failure_for(out, "inventory_manage", "adjust") is True, \
            "清除一个目标时把另一个目标的账也抹了（等于'新校验一次全放行'）"

    def test_block_message_is_actionable(self):
        """拦下的话术必须**可执行**：写明补参 → 重新 validate_input → 再写（不得死锁）。"""
        m = self._mod()
        failure = m.extract_validation_failure(
            {"target_tool": "order_create", "target_action": "create"}, dict(_FAILURE_RESULT))
        msg = m.format_failure_block_message("order_create", "create", failure)
        for token in ("validate_input", "order_create", "禁止", "重新调用"):
            assert token in msg, f"拦截话术缺要素 {token!r}：{msg}"
        assert "确认卡" in msg, "必须明确「靠顾客确认卡也绕不过」—— 否则模型会去发卡重试"