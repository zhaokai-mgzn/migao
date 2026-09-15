# case_ids: OR-014
"""思考模式 + 多轮工具调用下的 `400` 回归（`reasoning_content must be passed back`）。

## 这条 400 是什么、为什么首轮能通

上游（DeepSeek thinking mode）的规则是**有则必须回传、无则不得凭空造**：

    if msg.role == "assistant" and msg.tool_calls and thinking_enabled and "reasoning_content" not in msg:
        raise BadRequestError("The `reasoning_content` in the thinking mode must be passed back to the API.")

判定跑 `34908262839`（main `2b8dfbc2`）B 端腿 OR-014 的实测形态（会话 `sess_cdeb6050ed524462`）：
* iter=1 通 —— 首轮请求里**没有** assistant 消息，规则无从触发；
* iter=2 400 —— 请求里多出了本轮 iter=1 的 `assistant(tool_calls)` 消息，
  而这轮 `AIMessage.additional_kwargs["reasoning_content"]` 在拼装请求体时被丢掉。

丢它的**不是**我们的代码，而是被依赖的 `langchain_openai.chat_models.base._convert_message_to_dict`
—— 它只挑 `content`/`name`/`role`/`tool_calls`/`function_call`/`audio` 六个字段，
`additional_kwargs` 里除这几个之外的一切（含 `ChatDeepSeek` 从响应里正确提取出来的
`reasoning_content`）都**不会**进请求体。这是**产品侧缺陷**：上游对我们提出契约要求，
我们的请求体不满足它，且失败只能靠兜底话术收场（#3805 病灶）。

## 本文件的红证策略（零真实 LLM）

`_FakeUpstream` 是**按上游规则返回 400 的假客户端**：它挂在真实 `openai` 异步客户端的
`create` 上，因此**真正走完整链路** —— `AIMessage → _convert_message_to_dict → 请求体 → 校验`，
而不是把请求体断言硬编码在测试里（否则改前改后都只有我们自己的假设在场）。

* 改前：`reasoning_content` 缺失 ⇒ 假上游抛 400 ⇒ 用 `execute_skill` 跑完整 skill 时
  本轮以兜底话术收场（`final_answer` 不是模型正文）；
* 改后：请求体带 `reasoning_content` ⇒ 不再 400；
* 反向守卫：上游**没给** reasoning_content 时，请求体里**不得**多出该字段
  （防"到处塞 reasoning_content"引入新问题）。
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.graph.skills import base_skill
from loguru import logger

from app.llm import factory as llm_factory
from app.llm.message_payload import ReasoningPassthroughChatModel, ensure_reasoning_content
from app.graph.skills.base_skill import create_skill_registry as _real_create_skill_registry
from app.utils.error_incident import llm_incident_id

#: 上游 400 的**原文**（判定跑 34908262839 里的实测文本，不转述）
UPSTREAM_400 = "The `reasoning_content` in the thinking mode must be passed back to the API."


# ────────────────────── 假上游：按上游规则返回 400 ──────────────────────

class _FakeUpstream:
    """记录每一次请求体，并按「上游规则」对不合规的 assistant 消息抛 400。

    判定思想模式是否开启：**和上游一样**看请求体自己 —— 顶层出现 `thinking` 段，
    或任何 assistant 消息带 `reasoning_content`（上游把这种请求整体按思考模式处理，
    这正是 iter=2 明明走 `force_no_think` 客户端却也 400 的解释）。
    """

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[dict] = []

    # ── 校验 ──
    def _thinking_on(self, payload) -> bool:
        """请求体是否处在思考模式。

        ⚠️ 位置随层而异：我们交给 openai SDK 的是 `extra_body={"thinking": …}`，
        因此**在传输层**看到的是那个 `extra_body` 形参（SDK 之后才把它平铺进出网 body）。
        判据两处都认，避免"看错位置 ⇒ 假上游永远不红 ⇒ 假绿"。
        """
        if "thinking" in payload or "thinking" in (payload.get("extra_body") or {}):
            return True
        return any(
            m.get("role") == "assistant" and m.get("reasoning_content")
            for m in payload.get("messages", [])
        )

    def _validate(self, payload):
        if not self._thinking_on(payload):
            return
        for m in payload.get("messages", []):
            if (m.get("role") == "assistant" and m.get("tool_calls")
                    and not m.get("reasoning_content")):
                raise openai.BadRequestError(
                    f"Error code: 400 - {{'error': {{'message': '{UPSTREAM_400}',"
                    f" 'type': 'invalid_request_error', 'param': None,"
                    f" 'code': 'invalid_request_error'}}}}",
                    response=MagicMock(status_code=400),
                    body=None,
                )

    # ── openai 客户端替身（`AsyncCompletions.create`）──
    # ⚠️ 坑（实测踩过）：`patch(new=…)` 是替换**类属性**，不再经过描述符协议 ⇒ 绑定丢失，
    #    真实客户端实例会被当成第一个**位置**参数传进来 ⇒ `create(**kwargs)` 直接 TypeError。
    #    故必须用 `*_args` 吃掉它；也不能改成 `upstream.create.__get__(upstream)`
    #    （那会把 `upstream` 顶到第一位、客户端实例落进 `**kwargs`）。
    def transport(self):
        async def create(*_args, **kwargs):
            self.requests.append(kwargs)
            self._validate(kwargs)
            reply = self.replies[min(len(self.requests) - 1, len(self.replies) - 1)]
            return _FakeStream(_chunks(kwargs.get("model", "m"), reply))
        return create

    def transports(self):
        return [r["messages"] for r in self.requests]


class _FakeStream:
    """`async with client.create(...) as response:` + `async for chunk in response`。"""

    def __init__(self, chunks):
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for c in self._chunks:
            yield c


def _chunks(model, reply):
    """把 `(content, tool_calls, reasoning)` 三元组编成上游流式分片。"""
    content, tool_calls, reasoning = reply
    delta: dict = {"role": "assistant"}
    if reasoning:
        delta["reasoning_content"] = reasoning
    if content:
        delta["content"] = content
    if tool_calls:
        delta["tool_calls"] = [
            {"index": i, "id": tc["id"], "type": "function",
             "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
            for i, tc in enumerate(tool_calls)
        ]
    return [
        openai.types.chat.ChatCompletionChunk(
            id="c1", created=0, model=model, object="chat.completion.chunk",
            choices=[{"index": 0, "delta": delta, "finish_reason": None}]),
        openai.types.chat.ChatCompletionChunk(
            id="c1", created=0, model=model, object="chat.completion.chunk",
            choices=[{"index": 0, "delta": {}, "finish_reason": "tool_calls" if tool_calls else "stop"}]),
    ]


def _fake_credentials():
    """假凭据上下文（只为让 `ChatDeepSeek` 通过构造期校验；调用点已全部走假传输层）。

    不依赖本地 `.env` —— 否则本文件在本地过、在 CI 又因为环境不同而变异。
    """
    return (patch.object(llm_factory, "LLM_API_KEY", "sk-local-fake"),
            patch.object(llm_factory, "LLM_BASE_URL", "https://api.deepseek.com/v1"))


def _skill_llm(**kwargs):
    """真实 `LLMFactory` 造实例（连 thinking 开关一起走真链路），只换掉网络传输层。"""
    a, b = _fake_credentials()
    with a, b:
        return llm_factory.LLMFactory.create_skill_llm(
            model_override="deepseek-flash", **kwargs)


# ────────────────────── ① 改前必红：assistant(tool_calls) 丢 reasoning_content ──────────────────────

class TestReasoningContentIsPassedBack:
    def test_iter2_request_carries_reasoning_content_for_tool_call_turn(self):
        """多轮工具调用：iter=2 的请求体必须带上 iter=1 那条 assistant 消息的 reasoning_content。

        改前（`origin/main`）此条必红：请求体里 assistant 消息只有 `tool_calls`，
        假上游按上游规则直接 400 —— 与判定跑 34908262839 的实测形态同构。
        """
        upstream = _FakeUpstream(replies=[
            ("", [{"id": "call_1", "name": "order_create", "args": {"sku": "A"}}], "先查库存再算价"),
            ("下单成功啦～", [], None),
        ])
        llm = _skill_llm(enable_thinking=True)

        async def _drive():
            ai = await llm.ainvoke([HumanMessage(content="帮我下单，遮光窗帘 3 米")])
            assert ai.tool_calls, "假上游没有产出 tool_calls，用例前提不成立"
            return await llm.ainvoke([
                HumanMessage(content="帮我下单，遮光窗帘 3 米"),
                ai,
                ToolMessage(content='{"success": true}', tool_call_id="call_1"),
            ])

        with patch("openai.resources.chat.completions.AsyncCompletions.create",
                   new=upstream.transport()):
            second = asyncio.run(_drive())

        assert len(upstream.requests) == 2, "第二轮请求没有发出去（首轮就失败了）"
        second_msgs = upstream.transports()[1]
        assistant_msgs = [m for m in second_msgs if m.get("role") == "assistant"]
        assert assistant_msgs, "第二轮请求里没有 assistant 消息 —— 用例前提不成立"
        assert [m.get("reasoning_content") for m in assistant_msgs] == ["先查库存再算价"], (
            "第二轮请求里带 tool_calls 的 assistant 消息丢了 reasoning_content ⇒ "
            f"上游必 400（{UPSTREAM_400}）。实际请求体："
            + json.dumps(second_msgs, ensure_ascii=False)
        )
        assert second.content == "下单成功啦～"

    def test_missing_reasoning_content_really_is_a_400(self):
        """**上游判据本身的红证**：把 reasoning_content 摘掉，假上游必须 400。

        这条不依赖我们的实现，钉的是"假上游确实会按上游规则红"——
        否则上面那条绿可能是假绿（假上游永远不红 ⇒ 测了个寂寞）。
        """
        upstream = _FakeUpstream(replies=[("ok", [], None)])
        llm = _skill_llm(enable_thinking=True)
        stripped = AIMessage(
            content="",
            tool_calls=[{"name": "order_create", "args": {"sku": "A"},
                         "id": "call_1", "type": "tool_call"}],
        )  # 刻意不带 additional_kwargs["reasoning_content"]
        msgs = [HumanMessage(content="x"), stripped,
                ToolMessage(content="{}", tool_call_id="call_1")]

        with patch("openai.resources.chat.completions.AsyncCompletions.create",
                   new=upstream.transport()):
            with pytest.raises(openai.BadRequestError) as err:
                asyncio.run(llm.ainvoke(msgs))
        assert UPSTREAM_400 in str(err.value)


# ────────────────────── ② 反向守卫：不得凭空造字段 ──────────────────────

class TestNoFabricatedReasoningContent:
    def test_plain_reply_gains_no_reasoning_content_field(self):
        """上游没给 reasoning_content ⇒ 请求体里不得出现该字段（不凭空造）。"""
        upstream = _FakeUpstream(replies=[("好的", [], None)])
        llm = _skill_llm()  # 不启用 thinking，走 force_no_think 之外的原路径
        msgs = [HumanMessage(content="你好")]
        with patch("openai.resources.chat.completions.AsyncCompletions.create",
                   new=upstream.transport()):
            asyncio.run(llm.ainvoke(msgs))
        sent = upstream.transports()[0]
        assert [m.get("reasoning_content") for m in sent] == [None] * len(sent), (
            "无 thinking / 无 reasoning 的一轮被塞进了 reasoning_content 字段："
            + json.dumps(sent, ensure_ascii=False)
        )

    def test_thinking_off_client_does_not_fabricate(self):
        """`force_no_think` 分支同样不得凭空造字段（它连 thinking 段都不该下发）。"""
        upstream = _FakeUpstream(replies=[("好的", [], None)])
        llm = _skill_llm(force_no_think=True)
        with patch("openai.resources.chat.completions.AsyncCompletions.create",
                   new=upstream.transport()):
            asyncio.run(llm.ainvoke([HumanMessage(content="你好")]))
        sent = upstream.transports()[0]
        assert all(m.get("reasoning_content") is None for m in sent)
        assert (upstream.requests[0].get("extra_body") or {}) == {"thinking": {"type": "disabled"}}, (
            "force_no_think 轮次的 extra_body 不是 disabled："
            f"{upstream.requests[0].get('extra_body')!r}"
        )

    def test_helper_never_invents_and_never_mutates_the_source(self):
        """单一来源 helper 的契约：只做"有则回传"，且不就地改调用方的消息对象。"""
        with_reasoning = AIMessage(
            content="", additional_kwargs={"reasoning_content": "想一想"},
            tool_calls=[{"name": "t", "args": {}, "id": "c1", "type": "tool_call"}])
        without = AIMessage(content="直接回答")
        got = ensure_reasoning_content([with_reasoning, without])

        assert got[0].additional_kwargs["reasoning_content"] == "想一想"
        assert "reasoning_content" not in got[1].additional_kwargs
        # 只读：调用方对象不被就地改写（否则同一 message 会被后续/历史复用污染）
        assert got[0] is not with_reasoning or got[1] is not without, (
            "helper 就地改写了调用方的消息对象"
        )


# ────────────────────── ②b 接线与 MRO 的机械守卫 ──────────────────────

class TestWiringInvariants:
    """防"改回去"的机械守卫：这三条不会红=接线又断了（本单的首个实现即栽在这里）。"""

    def test_mro_keeps_chatdeepseek_before_chatopenai(self):
        """`ChatDeepSeek` 必须排在 `ChatOpenAI` **之前**。

        否则 C3 线性化会让 `ChatDeepSeek._get_request_payload`（tool/assistant content
        归一化等模型专属行为）**永远不被调用** —— 本单首个实现就写成
        `(混入, ChatOpenAI, ChatDeepSeek)`，实测 payload 少了模型专属段且 reasoning 仍丢。
        """
        from app.llm.factory import _PassthroughDeepSeek
        from langchain_deepseek import ChatDeepSeek
        from langchain_openai import ChatOpenAI as _ChatOpenAI
        mro = _PassthroughDeepSeek.__mro__
        assert mro.index(ChatDeepSeek) < mro.index(_ChatOpenAI), (
            f"MRO 顺序错了：{[c.__name__ for c in mro]}"
        )
        assert mro[1] is ReasoningPassthroughChatModel, (
            "混入类不在第一位 ⇒ 永远接管不到请求体组装："
            f"{[c.__name__ for c in mro]}"
        )

    def test_payload_keeps_provider_normalization(self):
        """混入不得架空被混入类的 payload 逻辑：assistant 的 list content 仍被归一化成字符串。"""
        llm = _skill_llm()
        ai = AIMessage(content=[{"type": "text", "text": "两段"},
                                {"type": "text", "text": "合成"}])
        payload = llm._get_request_payload([HumanMessage(content="x"), ai])
        assert payload["messages"][1]["content"] == "两段合成", (
            "ChatDeepSeek 的 content 归一化被绕过了 —— 请求体形态回退："
            + json.dumps(payload["messages"], ensure_ascii=False)
        )

    def test_payload_injection_handles_empty_reasoning(self):
        """`reasoning_content` 为空串/空值时不得被当成"有"（无则不得凭空造）。"""
        llm = _skill_llm()
        for empty in ("", None):
            ai = AIMessage(content="答", additional_kwargs={"reasoning_content": empty})
            payload = llm._get_request_payload([HumanMessage(content="x"), ai])
            assert "reasoning_content" not in payload["messages"][1], (
                f"reasoning_content={empty!r} 时仍被塞进请求体："
                + json.dumps(payload["messages"][1], ensure_ascii=False)
            )


# ────────────────────── ③ 端到端：skill 循环里不再 400 ──────────────────────

class _FakeStateStore:
    """只回放事实的假会话存储（单测不连真实存储，见 dev-flow §9.2）。

    接口照抄 `test_capability_denial_guard._FakeStateStore`（`load`/`commit`）：
    `execute_skill` 里多处 `SessionStateStore()` 无参构造后直接 `load`/`commit`，
    少一个方法就是一堆 "non-fatal" 警告（不致命，但日志噪声会盖住真实断言）。
    """

    def __init__(self, facts=None):
        self._facts = facts or {}

    async def load(self, _sid):
        return dict(self._facts)

    async def commit(self, _sid, full):
        self._facts.update(full or {})
        return True


def _drive_order_skill(replies, wrap_llm=None):
    """用真实 `LLMFactory`（只换传输层）跑一遍 `execute_skill` 的两轮工具调用。

    `wrap_llm`：可选的模型包装器（用于"强制失败"对照组，见 `_strip_reasoning`）。
    """
    upstream = _FakeUpstream(replies=replies)
    executed = []

    async def fake_execute(tool, args, ctx, state):
        executed.append(tool.name)
        return (json.dumps({"success": True, "data": {}}), {"success": True, "data": {}})

    def _build(**kw):
        model = _skill_llm(**{k: v for k, v in kw.items()
                              if k in ("enable_thinking", "force_no_think")})
        return wrap_llm(model) if wrap_llm else model

    # ⚠️ `execute_skill` 里**有两处**造 LLM：`get_skill_llm`（经工厂）与
    #    `base_skill.LLMFactory.create_skill_llm(force_no_think=True)`（iter 2+ 直连工厂）。
    #    只 patch 前者会让后者拿真 key 去构造 —— 本地无凭据时直接 ValidationError，
    #    用例会"红得不明不白"。故两处都从同一工厂转出。
    class _FakeFactory:
        create_skill_llm = staticmethod(_build)

    _cred_a, _cred_b = _fake_credentials()
    with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
         patch("app.memory.session_state_store.SessionStateStore",
               return_value=_FakeStateStore({
                   # 写操作确认门禁（issue #3445）走"本会话已确认过 order_create"的
                   # 真实事实分支 —— 否则本轮会在执行前被拦回（`confirmation_required_no_card`），
                   # 根本到不了 iter=2 那条会 400 的请求。
                   "confirmed_write_tool": "order_create"})), \
         patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
         patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
         patch("app.graph.skills.base_skill.set_tool_context"), \
         patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute), \
         patch("app.graph.skills.base_skill.get_skill_llm", side_effect=_build), \
         patch("app.graph.skills.base_skill.LLMFactory", _FakeFactory), \
         _cred_a, _cred_b, \
         patch("openai.resources.chat.completions.AsyncCompletions.create",
               new=upstream.transport()):
        # ⚠️ 必须用**真实工具实例**搭 registry 子集（照 `test_capability_denial_guard` 的同款
        #    理由）：① `bind_tools` 走 `convert_to_openai_tool`，MagicMock 连 `__name__`
        #    都没有（本用例首版即踩，红得与 400 无关）；② 守卫读的是工具属性
        #    （`destructive` / `requires_confirmation`），mock 出来判据会失真。
        #    又：必须用**模块级导入的真函数** —— 此刻 `base_skill.create_skill_registry`
        #    已被 patch 成 mock，调它只会拿到 mock 返回值。
        registry = _real_create_skill_registry(["order_create"])
        create_reg.return_value = registry

        breaker = MagicMock()

        async def _pt(fn):
            return await fn()

        breaker.call = _pt
        get_breaker.return_value = breaker
        mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)
        mem_cls.return_value.get_history = AsyncMock(return_value=[])

        state = {
            "messages": [HumanMessage(content="帮我下单，遮光窗帘 3 米")],
            "tenant_id": 1, "user_id": 100, "session_id": "sess_cdeb6050ed524462",
            "agent_type": "mibao", "final_answer": "", "skill_used": "",
        }
        out = asyncio.run(base_skill.execute_skill(
            state=state, skill_name="order", tool_names=["order_create"],
            system_prompt="你是米宝"))
    return out, upstream, executed


class TestSkillLoopSurvivesThinkingModeToolCalls:
    """判定跑的实测形态：iter=1 出 tool_calls、iter=2 继续 —— 改前 iter=2 必 400。"""

    FINAL = "已经帮您把遮光窗帘 3 米记下了，还需要确认加工方式～"

    def test_second_iteration_is_not_a_400(self):
        out, upstream, executed = _drive_order_skill(replies=[
            ("", [{"id": "call_1", "name": "order_create", "args": {"sku": "A"}}], "先建草稿"),
            (self.FINAL, [], None),
        ])
        assert executed == ["order_create"], f"工具没有被执行：{executed}"
        assert out["final_answer"] == self.FINAL, (
            "本轮以兜底话术收场（说明 iter=2 又 400 了）："
            f"{out['final_answer']!r}"
        )
        second_msgs = upstream.transports()[1]
        assert any(m.get("reasoning_content") == "先建草稿"
                   for m in second_msgs if m.get("role") == "assistant"), (
            "iter=2 的请求体没带上 iter=1 的 reasoning_content："
            + json.dumps(second_msgs, ensure_ascii=False)
        )


# ────────────────────── ④ 万一仍失败：必须可归因，不得静默（#3809 / #3805） ──────────────────────

def _strip_reasoning(model, thinking_mode: bool = True):
    """把 assistant 的 `reasoning_content` 从请求体里抹掉（就地改模型实例）。

    用来钉**"万一还是失败"那条路径**的行为 —— 本单的修复不会、也不该让归因能力退化：
    失败必须留下 `[SLS] LLM failed … | incident=<短码>` + traceback，而不是静默。

    ⚠️ 两个实测踩到的坑：
    ① 用"包装对象 + `__getattr__` 委托"是**无效**的 —— `ainvoke` 被委托到真模型上执行，
       真模型用的 `self` 是它自己，包装的覆盖永远不会被调用（请求体里 reasoning 原样还在，
       链路一路成功，链路根本没被行使 ⇒ 假绿）。必须**就地改实例**。
    ② 抹掉之后必须**显式声明本请求仍处思考模式**（`extra_body.thinking=enabled`）：
       否则假上游的 `_thinking_on` 会因"看不到任何思考证据"而放弃校验、静默放行。
       真实上游无此问题：它的思考模式由**模型与请求参数**决定。
    """
    original = model._get_request_payload

    def stripped(input_, **kwargs):
        payload = original(input_, **kwargs)
        for m in payload.get("messages") or []:
            m.pop("reasoning_content", None)
        if thinking_mode:
            payload["extra_body"] = {**(payload.get("extra_body") or {}),
                                     "thinking": {"type": "enabled"}}
        return payload

    model._get_request_payload = stripped
    return model


def _drive_order_skill_with_stripped_reasoning(replies):
    """同 `_drive_order_skill`，但强制让 iter=2 的请求体缺 reasoning ⇒ 必然 400。"""
    out, upstream, executed = _drive_order_skill(replies, wrap_llm=_strip_reasoning)
    return out, upstream, executed


class TestFailureStaysAttributable:
    def test_400_is_logged_with_incident_code_and_traceback(self):
        """复现判定跑的失败形态：日志必须带 incident 短码 + 上下文 + traceback。

        `34908262839` 的实测审计行（本用例断言的就是这一形态）：

            [order][SLS] LLM failed session=sess_cdeb6050ed524462
            error=BadRequestError: Error code: 400 - {…reasoning_content…}
            | incident=b9f9180a tenant=1 iter=2 req=-

        绿 = 失败**不静默**（R9/R10 那种"用户只看到一句兜底、日志查不出根因"的形态被排除）。

        ⚠️ 用 loguru 自己的 sink 抓 record（`caplog` 抓不到 loguru —— 除非额外配
        propagation handler，本仓未配）。`record["exception"]` 非空才算"traceback 真的落盘"。
        """
        captured: list = []
        sink_id = logger.add(lambda m: captured.append(m.record), level="ERROR")
        try:
            out, _, executed = _drive_order_skill_with_stripped_reasoning(replies=[
                ("", [{"id": "call_1", "name": "order_create", "args": {"sku": "A"}}], "先建草稿"),
                ("不该走到这里", [], None),
            ])
        finally:
            logger.remove(sink_id)
        assert executed == ["order_create"], f"工具没有被执行：{executed}"

        audits = [r for r in captured
                  if "[SLS] LLM failed" in (r["message"] or "")]
        assert audits, (
            "失败没有留下任何 `[SLS] LLM failed` 审计行 ⇒ 静默失败（#3805 病灶）："
            f"{[r['message'] for r in captured]}"
        )
        record = audits[-1]
        line = record["message"]
        expected_incident = llm_incident_id("sess_cdeb6050ed524462", "BadRequestError")
        assert f"incident={expected_incident}" in line, (
            f"审计行缺 incident 短码（无法把多轮同一失败聚成一个 incident）：{line!r}"
        )
        assert "session=sess_cdeb6050ed524462" in line and "tenant=1" in line, (
            f"审计行缺会话/租户上下文（定位不到是哪个商户的哪一步）：{line!r}"
        )
        assert "BadRequestError" in line, f"审计行缺异常类型：{line!r}"
        assert "iter=" in line, f"审计行缺 ReAct 轮次锚点：{line!r}"
        assert record["exception"] is not None, (
            "审计行没有 traceback（record['exception'] 为空）—— "
            "只有 type+message 时定位不到出错行"
        )
        # 用户可见话术仍是**已合入**的合规兜底（本单不改话术，也不把它改成"静默成功"）
        assert out["final_answer"] == "刚才这轮没成功，请您再说一次，我继续为您办理。", (
            f"失败话术被改成了别的东西：{out['final_answer']!r}"
        )
