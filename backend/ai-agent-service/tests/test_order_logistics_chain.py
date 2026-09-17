"""订单 → 物流链收口（issue #3799）—— 顾客要物流时，链路必须真的走完。

**缺口实证**（判定跑 run 34873715194，SHA 30527b73，mibao 腿 `Run mibao normal` 日志）：
```
🔵 ✅ OR-013: B 端物流查询 - 仅支持真实订单号，拒绝快递单号直查
   rounds=4 tools=['order_query','logistics_track','logistics_track','logistics_track']
   [R1 …用快递单号 SF1234567890 查一下物流 → 正确拒绝并要订单号]
   [R2 那用我最近一笔订单的订单号查一下物流  tools=order_query
       ai=您最近的一笔订单是 **20260915294490006**（赵凯…）]        ← 只报了订单号就停手
   [R3 就用你查到的那笔订单号帮我查物流  tools=logistics_track …]    ← 被追问后才补上
```
⇒ 用例因 `#3792` 协作轮判绿，但 **R2 的行为缺口仍在**（"跑绿"不构成证据）。
本文件把"链要走完"钉成**可执行判据**（零 LLM）：

  ① **契约面**：模型可见的指令面（order skill 的组装 prompt = 领域规则 + few-shot、
     两个工具的 description、拿不到 order_id 时的 suggestion）必须写明
     「订单号是入参、不是交付物；拿到后必须继续调 logistics_track(order_id=…)」；
  ② **行为面**：用 scripted-LLM 驱动**真实 `execute_skill`**（范式同
     `tests/test_capability_denial_guard.py`），复现 R2 的"查完订单就收尾"决定序列 ⇒
     框架**不得**把该终答当完成（有界注入一条纠正并继续本轮），同轮补上 `logistics_track`；
  ③ **反向守卫**：这些路径**一律不得**触发纠正（避免"一律补查物流"的过度纠正）——
     非物流意图 / 本轮 `order_query` 没返回真实订单号 / 本轮已尝试过 logistics_track /
     本 skill 工具集里没有 logistics_track（C 端小布用小布的物流工具）；
     并且第 1 轮的**安全行为**（拒绝快递单号直查）与 `logistics_track` 的**参数契约**
     （只收 order_id）一个字都没被改坏。
"""
# case_ids: OR-013, OR-005

import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from app.graph.skills import base_skill
from app.graph.skills.base_skill import (
    _build_system_prompt,
    _PROMPT_CACHE,
    create_skill_registry,
)
from app.tools.base import ToolContext
from app.tools.logistics_track import LogisticsTrackTool
from app.tools.order_query import OrderQueryTool


# ────────────────────── 夹具：真实 execute_skill + scripted LLM ──────────────────────

REAL_ORDER_NO = "20260915294490006"   # 与 run 34873715194 的 R2 同一形态的真实订单号
TRACKING_NO = "SF1234567890"          # 第 1 轮被拒的快递单号（R1 安全行为）

# R2 的红形态：只查订单（拿到订单号），然后把订单信息当交付物收尾
RED_REPLY = f"您最近的一笔订单是 **{REAL_ORDER_NO}**（赵凯，2026-09-15 01:30 创建），当前状态：待付款"


class _FakeStateStore:
    """只回放事实的假会话存储（单测不连真实存储，见 migao-dev-flow §9.2）。"""

    def __init__(self, facts=None):
        self._facts = dict(facts or {})

    async def load(self, sid):
        return dict(self._facts)

    async def commit(self, sid, full):
        self._facts.update(full or {})
        return True


def _ai(content="", tool_calls=None):
    """构造一条 scripted 模型回复（只读属性，够走完真实循环）。"""
    m = MagicMock(spec=AIMessage)
    m.content = content
    m.tool_calls = list(tool_calls or [])
    m.usage_metadata = None
    return m


def _tc(name, args, cid):
    return {"name": name, "args": args, "id": cid, "type": "tool_call"}


def _order_query_result(order_nos):
    return {
        "success": True,
        "data": {
            "orders": [{"order_no": n, "customer_name": "赵凯", "status": "pending"} for n in order_nos],
            "total": len(order_nos),
            "page": 1,
            "page_size": 10,
        },
        "summary": f"找到{len(order_nos)}个订单",
    }


def _legacy_registry_without_family_share(tool_names):
    """**反向守卫专用**的域构造：只注册声明的工具，**不经** #4125 的家族只读共享。

    为什么需要它（issue #4125）：只读工具跨域共享后，**B 端任一域都带 `logistics_track`**
    （它是 B 端只读工具，家族共享必然并入）⇒「有 `order_query` 却没有 `logistics_track`」的域
    在**生产里已不可构造**，而"缺该工具 ⇒ 不得触发纠正"这条反向守卫仍必须可判。
    判据本体一个字没改：谁把 `_logistics_chain_incomplete` 的 `_registry_has_tool` 那一项删掉，
    用本夹具的用例照样红（这正是它存在的意义）。生产路径仍只走 `create_skill_registry`。
    """
    from app.tools.registry import ToolRegistry, get_tool_registry, set_tool_scope

    reg = ToolRegistry()
    full = get_tool_registry()
    for name in tool_names:
        tool = full.get_tool(name)
        if tool:
            reg.register(tool)
    set_tool_scope(reg.get_tool_names())
    return reg


def _run_chain(replies, *, intent="logistics_track", tool_names=("order_query", "logistics_track"),
               order_nos=(REAL_ORDER_NO,), skill_name="order", role="agent",
               agent_type="mibao", family_share=True):
    """用 scripted LLM 驱动**真实** `execute_skill`，返回执行过的事实。

    工具不真跑（`_execute_tool_safe` 换成记账假实现），但**注册表用真实工具实例** ——
    链收口判据读的正是 `registry.get_tool("logistics_track")` 这一事实，mock 掉会失真。

    `family_share=False` ⇒ 用 `_legacy_registry_without_family_share`（pre-#4125 形态的域），
    仅供"缺该工具的域"这条反向守卫使用。
    """
    executed = []          # [(tool_name, args)]
    injected = []          # 实际被注入的 SystemMessage 文本

    async def fake_execute(tool, args, ctx, state):
        executed.append((tool.name, dict(args or {})))
        if tool.name == "order_query":
            payload = _order_query_result(order_nos)
            return json.dumps(payload, ensure_ascii=False), payload
        payload = {"success": True, "data": {"status_text": "运输中", "trailing": []}}
        return json.dumps(payload, ensure_ascii=False), payload

    llm = MagicMock()
    llm.bind_tools.return_value = llm
    llm.ainvoke = AsyncMock(side_effect=replies)

    breaker = MagicMock()

    async def _pass_through(fn):
        return await fn()

    breaker.call = _pass_through

    with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
         patch("app.memory.session_state_store.SessionStateStore",
               return_value=_FakeStateStore()), \
         patch("app.graph.skills.base_skill.get_breaker", return_value=breaker), \
         patch("app.graph.skills.base_skill.get_skill_llm", return_value=llm), \
         patch("app.graph.skills.base_skill.LLMFactory") as llm_factory, \
         patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
         patch("app.graph.skills.base_skill.set_tool_context"), \
         patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute):
        create_reg.return_value = (
            create_skill_registry(list(tool_names)) if family_share
            else _legacy_registry_without_family_share(list(tool_names)))
        # 只读迭代可能换用"关思考"的 LLM 实例（同一模型）：统一回我们这条 scripted stub，
        # 否则第 2+ 次迭代的回复不来自脚本、测试变成"在测 mock"。
        llm_factory.create_skill_llm.return_value = llm
        mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)
        mem_cls.return_value.get_vision_analysis = AsyncMock(return_value="")
        state = {
            "messages": [HumanMessage(content="那用我最近一笔订单的订单号查一下物流")],
            "intent_result": {"intent": intent, "confidence": 0.95, "source": "rule"},
            "tenant_id": 1,
            "user_id": 100,
            "session_id": "sess_or013_chain",
            "role": role,
            "agent_type": agent_type,
            "final_answer": "",
            "skill_used": "",
        }
        out = asyncio.run(base_skill.execute_skill(
            state=state, skill_name=skill_name, tool_names=list(tool_names),
            system_prompt="你是米宝"))

    # 注入事件（**不是**"消息列表里出现过"）：new_messages 是累积的，纠正会留在后续每次
    # LLM 调用的上下文里 —— 只有"本次调用比上次多出来的纠正"才算一次注入，否则永远数成 N 次。
    prev = 0
    for call in llm.ainvoke.call_args_list:
        msgs = call.args[0] if call.args else call.kwargs.get("messages", [])
        cur = [str(getattr(m, "content", "")) for m in msgs
               if isinstance(m, SystemMessage) and "订单→物流链未完成" in str(getattr(m, "content", ""))]
        if len(cur) > prev:
            injected.extend(cur[prev:])
            prev = len(cur)
    return out, llm, executed, injected


# ────────────────────── ① 契约面（零 LLM 红证：改前这些面都没写这条链）──────────────────────

class TestChainContractSurfaces:
    """模型可见的每个指令面都必须写明"订单号是入参、交付物是轨迹"。"""

    def setup_method(self):
        _PROMPT_CACHE.clear()

    @pytest.mark.parametrize("phrase", [
        "订单 → 物流链",              # 领域规则小节（prompts/order.md）
        "中间步",                     # 禁止把中间结果当交付物
        "同一轮内继续",               # 链必须在同一轮内走完
        "logistics_track(order_id=",  # 可执行的下一步（带上真实入参名）
        f"order_query",               # 第 1 步的工具
    ])
    def test_order_skill_prompt_states_the_chain(self, phrase):
        prompt = _build_system_prompt("order")
        assert phrase in prompt, (
            f"order skill 的组装 prompt 缺「订单→物流链」要素：{phrase!r} —— "
            f"顾客要物流时模型没有任何依据知道「查到订单号不算完成」")

    def test_few_shot_has_the_same_turn_chain_example(self):
        """few-shot 必须给出"同一轮 order_query → logistics_track"的 ✅ 形态（L5 层）。"""
        prompt = _build_system_prompt("order")
        assert "例7" in prompt and "同一轮走完" in prompt, "缺 ✅ 链式示例"
        assert "链只走了一半" in prompt, "反例里没写「只调 order_query 就停手」这一形态"

    def test_order_query_description_obliges_the_next_step(self):
        d = OrderQueryTool.description
        assert "必须继续" in d and "logistics_track(order_id=" in d, (
            "order_query 的工具契约没说清「拿到订单号后必须继续查轨迹」（模型看不到下一步义务）")

    def test_logistics_track_description_states_deliverable(self):
        d = LogisticsTrackTool.description
        assert "交付物是轨迹" in d and "必须继续调用本工具" in d, (
            "logistics_track 的工具契约没说清「拿到订单号后必须回来调用本工具」")

    def test_missing_order_id_refusal_points_to_next_step(self):
        """拿不到订单号时的建议也必须指向下一步（模型在这一刻才知道要订单号）。"""
        tool = LogisticsTrackTool()
        ctx = ToolContext(tenant_id=1, user_id="u1", session_id="s1", role="agent")
        res = asyncio.run(tool.execute(ctx, order_id=None))
        assert res.success is False
        s = res.suggestion or ""
        assert "立即" in s and ("本工具" in s or "logistics_track" in s), (
            "缺订单号的建议没告诉模型「拿到订单号后立即调用本工具」，模型容易把订单号当交付物")


# ────────────────────── ② 行为面：链必须真的走完（红/绿对照）──────────────────────

class TestChainGateCompletesTheChain:
    """scripted-LLM 复现 R2 的决定序列：改前终答被接受，改后同轮补上 logistics_track。"""

    def test_early_stop_is_not_accepted_and_chain_completes(self):
        replies = [
            _ai(tool_calls=[_tc("order_query", {"action": "list", "page_size": 1}, "c1")]),
            _ai(RED_REPLY),                                        # R2 的红形态：只报订单号就收尾
            _ai(tool_calls=[_tc("logistics_track", {"order_id": REAL_ORDER_NO}, "c2")]),
            _ai("【顺丰速运】运输中：快件已到达【杭州转运中心】（04-18 14:30）"),
        ]
        out, llm, executed, injected = _run_chain(replies)

        names = [n for n, _ in executed]
        assert "logistics_track" in names, (
            f"顾客要物流、订单号已查到，logistics_track 却从未被调用（链只走一半）：{names}")
        assert [n for n, _ in executed].count("order_query") == 1, "不该重复查订单"
        args = dict(executed)["logistics_track"]
        assert str(args.get("order_id") or "").strip(), (
            "logistics_track 缺 order_id（用例 required_args 会判红）")
        assert args["order_id"] == REAL_ORDER_NO, "应当用工具刚返回的真实订单号"
        assert llm.ainvoke.await_count == 4, (
            f"提前终答没有被拦下（期望 4 次 LLM 调用：查订单→被纠正→查轨迹→收尾），"
            f"实际 {llm.ainvoke.await_count} 次")
        assert len(injected) == 1, (
            f"纠正注入次数应恰好为 1（0 = 链未收口；>1 = 可能死循环），实际 {len(injected)} 次")
        assert REAL_ORDER_NO in injected[0], "纠正文本必须带上工具刚返回的真实订单号"

    def test_corrective_is_injected_at_most_once(self):
        """模型不跟 ⇒ 接受本轮结束（不无限注入、不代跑工具），但纠正只注入一次。"""
        replies = [
            _ai(tool_calls=[_tc("order_query", {"action": "list", "page_size": 1}, "c1")]),
            _ai(RED_REPLY),
            _ai(RED_REPLY),      # 无视纠正，再报一次订单信息
        ]
        out, llm, executed, injected = _run_chain(replies)
        assert len(injected) == 1, (
            f"纠正注入次数应恰好为 1（0 = 链未收口；>1 = 可能死循环），实际 {len(injected)} 次")
        assert llm.ainvoke.await_count == 3, "应接受模型的不遵从并结束本轮，不再重试"
        assert out["final_answer"] == RED_REPLY


class TestChainGateReverseGuards:
    """反面边界：这些形态**一律不得**触发纠正（防"一律补查物流"的过度纠正）。"""

    def test_not_triggered_when_intent_is_not_logistics(self):
        """顾客要的是订单信息（本轮意图=查订单）⇒ 查到订单就算完成，不许强塞物流查询。"""
        replies = [
            _ai(tool_calls=[_tc("order_query", {"action": "list"}, "c1")]),
            _ai(RED_REPLY),
        ]
        _, llm, executed, injected = _run_chain(replies, intent="order_query")
        assert injected == [] and llm.ainvoke.await_count == 2
        assert [n for n, _ in executed] == ["order_query"]

    def test_not_triggered_when_no_real_order_no_returned(self):
        """本轮 `order_query` 一条订单都没返回（顾客可能还没下单）⇒ 没有可查的入参，不触发。"""
        replies = [
            _ai(tool_calls=[_tc("order_query", {"action": "list"}, "c1")]),
            _ai("没有查到符合条件的订单"),
        ]
        _, llm, _, injected = _run_chain(replies, order_nos=())
        assert injected == [] and llm.ainvoke.await_count == 2

    def test_not_triggered_when_tracking_already_attempted(self):
        """模型本轮已经试过 logistics_track（哪怕返回"未发货"）⇒ 链已走到，不再纠正。"""
        replies = [
            _ai(tool_calls=[_tc("logistics_track", {"order_id": REAL_ORDER_NO}, "c1")]),
            _ai("查不到物流——该订单目前是待付款状态，还没发货"),
        ]
        _, llm, executed, injected = _run_chain(replies)
        assert injected == [] and llm.ainvoke.await_count == 2
        assert [n for n, _ in executed] == ["logistics_track"]

    def test_not_triggered_when_skill_lacks_logistics_tool(self):
        """本 skill 工具集里没有 logistics_track（如 C 端小布用小布的物流工具）⇒ 不触发。

        #4125 起：B 端任一域都共享到 `logistics_track`，故"缺该工具的域"按 pre-#4125 形态
        **直接构造**（`family_share=False`）；判据本体未动 —— 缺工具就不得触发。
        """
        pre = _legacy_registry_without_family_share(["order_query"])
        assert "logistics_track" not in pre.get_tool_names(), (
            "夹具没造成『缺 logistics_track 的域』—— 反向守卫会空跑（fail-closed）")
        replies = [
            _ai(tool_calls=[_tc("order_query", {"action": "list"}, "c1")]),
            _ai(RED_REPLY),
        ]
        _, llm, _, injected = _run_chain(replies, tool_names=("order_query",), family_share=False)
        assert injected == [] and llm.ainvoke.await_count == 2

    def test_pure_predicate_conditions(self):
        """判据本身是纯函数：四条事实缺一不可（改判据必须同时改这里）。

        走 `base_skill.` 属性访问（不在模块级 import 这两个私有纯函数）—— 这样"改前"的快照
        仍能收集本文件，红证落在**行为断言**上，而不是"测试文件 import 不到新符号"。
        """
        predicate = base_skill._logistics_chain_incomplete
        registry = create_skill_registry(["order_query", "logistics_track"])
        # 「缺该工具的域」这一行（#4125 起生产工厂造不出来了，见 `_legacy_registry_without_family_share`）
        lacks_tool = _legacy_registry_without_family_share(["order_query"])
        assert "logistics_track" not in lacks_tool.get_tool_names(), (
            "夹具没造成『缺 logistics_track 的域』—— 该行变成同形重复（判据空跑）")
        assert predicate(
            intent_name="logistics_track", registry=registry,
            order_nos=[REAL_ORDER_NO], executed_tools={"order_query"}) is True
        for kw in (
            dict(intent_name="order_query", registry=registry,
                 order_nos=[REAL_ORDER_NO], executed_tools={"order_query"}),
            dict(intent_name="logistics_track", registry=registry,
                 order_nos=[], executed_tools={"order_query"}),
            dict(intent_name="logistics_track", registry=registry,
                 order_nos=[REAL_ORDER_NO], executed_tools={"logistics_track"}),
            dict(intent_name="logistics_track", registry=lacks_tool,
                 order_nos=[REAL_ORDER_NO], executed_tools={"order_query"}),
        ):
            assert predicate(**kw) is False, f"过度纠正风险：{kw}"
        assert REAL_ORDER_NO in base_skill._logistics_chain_corrective([REAL_ORDER_NO])


# ────────────────────── ③ 反向守卫：R1 的安全行为与参数契约不许被改坏 ──────────────────────

class TestTrackingNumberSafetyPreserved:
    """第 1 轮「拒绝快递单号直查」是**安全行为**（防用他人运单号刺探物流）——钉死。"""

    @staticmethod
    def _ctx():
        return ToolContext(tenant_id=1, user_id="u1", session_id="s1", role="agent")

    def test_direct_tracking_number_query_is_refused(self):
        res = asyncio.run(LogisticsTrackTool().execute(self._ctx(), tracking_number=TRACKING_NO))
        assert res.success is False
        assert res.error == "不支持快递单号查询"
        assert "订单号" in (res.message or "")

    def test_parameters_contract_unchanged(self):
        """参数契约（既有）一个字不许动：只收 order_id，且 required=[order_id]。"""
        params = LogisticsTrackTool.parameters
        assert params["required"] == ["order_id"]
        assert list(params["properties"].keys()) == ["order_id"]
        assert params["properties"]["order_id"]["type"] == "string"

    def test_description_keeps_the_safety_ironrule(self):
        d = LogisticsTrackTool.description
        assert "不接受用户提供的快递单号/运单号直接查询" in d
        assert "先问订单号，不要空调" in d

    def test_tracking_number_still_refused_even_with_order_id(self):
        """两个参数同时传 ⇒ 仍按快递单号直查拒绝（不得因为多了 order_id 就放行）。"""
        res = asyncio.run(LogisticsTrackTool().execute(
            self._ctx(), order_id=REAL_ORDER_NO, tracking_number=TRACKING_NO))
        assert res.success is False and res.error == "不支持快递单号查询"
