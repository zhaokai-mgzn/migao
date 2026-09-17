# case_ids: AS-003, OR-029
"""域闸门判决的消费：`cross_skill_target` ⇒ 回锁归属流程 + 让模型拿到**可执行**的下一步（issue #4124）。

## 为什么本文件属于 AS-003（红证来源）与 OR-029（同族契约）

`AS-003` 的 artifact 原文（run `35256153429`，issue #4123）：

    tools=validate_input failed=validate_input!cross_skill_target
    data=validate_input(cross_skill_target=order_manage scope_size=12)
    ai=⚠️ 抱歉，刚才的确认卡片我这边发早了——**取消订单这个操作…

`scope_size=12` 正是 `product` 流程声明并绑给模型的工具数（`SkillConfig.tool_names`，注册表事实），
而 `order_manage` 不在其中 ⇒ 判决 `cross_skill_target`。改前 skills 层**零消费**这条判决
（`grep -rn "cross_skill_target" app/graph/skills/` 只命中一处注释）⇒ 模型只拿到劝导语
（"请把会话切到具备该工具的流程后再执行"）而**没有切换原语** ⇒ 整条链路被放弃
（期望的 `after_sales_manage` 从未被调用）。本文件把"判决必须被消费"钉在机制层：
回锁到**事实 derive** 的归属流程 + 指引同时含「下一轮可用」与「本轮该做什么」。

`OR-029`（issue #3976 的跨 skill 恢复契约）与本文件同族：同一份「回锁 + 轮末不得覆盖回本轮
skill（`_relocked_this_round`）」契约。本文件把它扩到 `cross_skill_target` 路径，防两处口径漂移
——`product` 就在 `CREATION_SKILL_NAMES` 里，轮末覆盖风险（#3976 P3 形态）是真实的。

## 强度不降

域外目标**仍被拒**（`success=False` / `error=cross_skill_target`）：本包只加"路由"，
**不**改成 `success=True`（#3976 的空头承诺形态——本轮 `bind_tools` 已定，目标工具本轮不可执行）。
`#4017` 的逐条死角拦截判据在 `tests/test_skill_tool_reachability.py`，本文件不复制、不放宽。
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.agent_config import get_agent_config
from app.graph.skills.base_skill import _flow_owner_skill, execute_skill
from app.graph.skills.skill_registry import get_skill_registry

SID = "sess_4124_cross_skill"

# AS-003 形态：agent 所在流程已发过确认卡（点卡那一轮才发现目标工具属于别的流程）。
AS003_FACTS = {
    "last_card": {"component": "confirm", "title": "请确认取消订单",
                  "confirmValue": "确认：取消订单 20260910619250007"},
    "last_card_skill": "product",
    "last_confirm_skill": "product",
    "last_confirm_value": "确认：取消订单 20260910619250007",
}


def _declared_tools(skill: str) -> list:
    """skill 声明的工具集（**注册表事实**，不手写清单 —— 手写清单会随产品演进腐烂）。"""
    cfg = get_skill_registry().get(skill)
    if cfg is None:   # 存在性判据用显式失败分支（`is not None` 断言会被 QA Gate 判弱断言）
        pytest.fail(f"skill {skill!r} 未注册 —— 本文件的判据前提不成立")
    return list(cfg.tool_names)


class _FakeStateStore:
    """内存会话状态（单测不连真实存储，`migao-dev-flow` §9.2）。"""

    _states: dict = {}

    def __init__(self, *a, **k):
        self._noop = True

    async def load(self, session_id: str) -> dict:
        return dict(_FakeStateStore._states.get(session_id) or {})

    async def commit(self, session_id: str, full: dict) -> None:
        _FakeStateStore._states[session_id] = dict(full)

    async def clear(self, session_id: str) -> None:
        _FakeStateStore._states.pop(session_id, None)


@pytest.fixture(autouse=True)
def _clean_state():
    _FakeStateStore._states = {}
    yield
    _FakeStateStore._states = {}


def _ai(content: str = "", tool_calls=None):
    m = MagicMock(spec=AIMessage)
    m.content = content
    m.tool_calls = list(tool_calls or [])
    return m


def _validate_input_call(target_tool="order_manage", target_action="cancel", params=None):
    return _ai(tool_calls=[{
        "name": "validate_input",
        "args": {"target_tool": target_tool, "target_action": target_action,
                 "params": {"order_id": "20260910619250007"} if params is None else params},
        "id": "tc_validate_input",
    }])


def _base_state(skill: str, **overrides):
    state = {
        "messages": [HumanMessage(content="确认")],
        "tenant_id": 1,
        "user_id": "user_admin_001",
        "session_id": SID,
        "role": "admin",
        "agent_type": "mibao",
        "pending_interact_skill": skill,
        "intent_result": None,
        "route_decision": None,
        "entities": {},
        "intent_chain": [],
        "stage": "initial",
        "cached_answer": None,
        "final_answer": "",
        "skill_used": "",
        "suggestions": [],
    }
    state.update(overrides)
    return state


def _tool_payloads(result, tool_name: str) -> list:
    """模型**实际看到**的某个工具的结果（ToolMessage 原文 → JSON）。

    按 `ToolMessage.name` 取（不是按错误码猜）—— 判据看着被拒工具的**原文**，
    失败形态再变也不会让本文件的断言静默变成"空跑然后判过"。
    """
    out = []
    for m in result["messages"]:
        if not isinstance(m, ToolMessage) or getattr(m, "name", "") != tool_name:
            continue
        if isinstance(m.content, str) and m.content.startswith("{"):
            try:
                out.append(json.loads(m.content))
            except json.JSONDecodeError:
                continue
    return out


def _validate_payloads(result) -> list:
    return _tool_payloads(result, "validate_input")


def _foreign_pending(rec, skill: str) -> list:
    """本轮写过的**非本轮流程**的 pending_skill（= 回锁落点）。"""
    return [name for _, name in rec["calls"] if name != skill]


async def _run_turn(*, skill, tool_names, replies, facts=None, state_overrides=None):
    """驱动真实 `execute_skill`（真实注册表/真实工具/真实域闸门；只 mock LLM 与会话存储）。"""
    if facts:
        _FakeStateStore._states[SID] = dict(facts)
    rec = {"calls": [], "pending": {}}

    mem = MagicMock()
    async def _set_pending(sid, name):
        rec["calls"].append((sid, name))
        rec["pending"][sid] = name
        return True
    async def _get_pending(sid):
        return rec["pending"].get(sid)
    mem.set_pending_skill = AsyncMock(side_effect=_set_pending)
    mem.get_pending_skill = AsyncMock(side_effect=_get_pending)
    mem.get_vision_analysis = AsyncMock(return_value="")
    mem.get_plan_state = AsyncMock(return_value="")
    mem.get_last_confirm_value = AsyncMock(return_value="")
    mem.get_user_memories = AsyncMock(return_value=[])
    mem.get_user_preferences = AsyncMock(return_value={})

    breaker = MagicMock()
    async def _passthrough(fn):
        return await fn()
    breaker.call = _passthrough

    llm = MagicMock()
    llm.bind_tools.return_value = llm
    llm.ainvoke = AsyncMock(side_effect=list(replies))

    no_think = MagicMock()
    no_think.bind_tools.return_value = no_think
    no_think.ainvoke = AsyncMock(return_value=_ai("好的，已说明情况。"))

    state = _base_state(skill, **(state_overrides or {}))
    with patch("app.memory.session_memory.SessionMemory", return_value=mem), \
         patch("app.memory.session_state_store.SessionStateStore", _FakeStateStore), \
         patch("app.graph.skills.base_skill.get_breaker", return_value=breaker), \
         patch("app.graph.skills.base_skill.get_skill_llm", return_value=llm), \
         patch("app.graph.skills.base_skill.LLMFactory") as llm_factory, \
         patch("app.graph.skills.base_skill.set_tool_context"):
        llm_factory.create_skill_llm.return_value = no_think
        result = await execute_skill(
            state=state, skill_name=skill, tool_names=list(tool_names),
            system_prompt="你是米宝")
    return result, rec, {"llm": llm, "no_think": no_think}


class TestCrossSkillTargetIsRouted:
    """红证：改前**只有劝导语**（`pending_interact_skill` 不变）；改后回锁到归属流程且指引点名它。"""

    async def test_out_of_domain_target_relocks_and_guidance_names_owner(self):
        skill = "product"
        tool_names = _declared_tools(skill)
        # 前置自断言（§18.4）：判据前提不成立时宁可红，不要空跑
        if "order_manage" in tool_names:
            pytest.fail("前提不成立：AS-003 形态要求 agent 所在流程**不含** order_manage")
        if "validate_input" not in tool_names:
            pytest.fail("前提不成立：该流程必须绑了 validate_input（判决的产生者）")
        state = _base_state(skill)
        owner = _flow_owner_skill(state, "order_manage")
        if not owner or owner == skill:
            pytest.fail(f"前提不成立：order_manage 的归属流程应为**别的**流程，实得 {owner!r}")

        result, rec, env = await _run_turn(
            skill=skill, tool_names=tool_names,
            replies=[_validate_input_call(), _ai("抱歉，这个操作需要在对应流程里办理。")],
            facts=AS003_FACTS)

        payloads = _validate_payloads(result)
        if not payloads:
            pytest.fail("validate_input 没有被真的执行过 —— 本用例会是空跑")
        p = payloads[0]
        # ① 强度不降：域外目标**仍被拒**（不得改成 success=True = #3976 空头承诺）
        assert p.get("success") is False and p.get("error") == "cross_skill_target", (
            f"域外拦截被放松（本包只加路由）：{p}")
        # ② 回锁到**事实 derive** 的归属流程
        assert owner in _foreign_pending(rec, skill), (
            f"域闸门判决未被消费：被拒后没有回锁到归属流程 {owner!r}"
            f"（改前形态 = 只有劝导语）| payload={p} | pending 落点={rec['calls']}")
        # ③ 指引可执行 + 点名归属流程
        combined = f"{p.get('message') or ''}\n{p.get('suggestion') or ''}"
        assert "本会话已切到" in combined and owner in combined, (
            f"指引没有点名归属流程 {owner!r}：{combined!r}")
        assert "下一轮" in combined and "order_manage" in combined, (
            f"指引没说清「下一轮可用」这件事：{combined!r}")
        assert "不要再调用" in combined and "确认" in combined, (
            f"指引没说清「本轮该做什么」（不重试 / 向用户要一次确认）：{combined!r}")
        # ④ 劝导语必须被换掉（改前原文就是这句"请你自己切流程"）
        assert "请把会话切到具备该工具的流程后再执行" not in combined, (
            f"仍然只有劝导语（模型没有切换原语）：{combined!r}")
        # ⑤ 本条指引是**本轮**的收尾动作：ReAct 循环必须把指引真的交回模型再说一次
        #    （否则"本轮请向用户说明"落不了地 —— 被拒即收场正是 #4123 的形态）。
        #    迭代 2+ 走 `llm_no_thinking`（见 react_turn 的 `current_llm` 选择），故两处都算；
        #    并核**真实入参**：下一轮 LLM 调用看到的 messages 里必须有这条指引。
        assert env["llm"].ainvoke.await_count + env["no_think"].ainvoke.await_count >= 2, (
            f"被拒后循环没有继续（本轮没有继续的机会）："
            f"ainvoke={env['llm'].ainvoke.await_count + env['no_think'].ainvoke.await_count}")
        _again = env["no_think"].ainvoke.await_args
        _sent = "\n".join(str(getattr(m, "content", ""))
                          for m in ((_again.args[0] if _again else []) or []))
        assert "本会话已切到" in _sent and owner in _sent, (
            f"下一轮 LLM 调用的入参里没有这条指引（模型实际收不到）：{_sent[-400:]!r}")

    async def test_round_end_keeps_relocked_pending_not_this_skill(self):
        """#3976 P3 同款：轮末跨轮持久化**不得**把回锁结果覆盖回本轮流程。

        为什么必须（`product` 就在 `CREATION_SKILL_NAMES` 里）：下一轮的路由取
        `SessionMemory.get_pending_skill`；被覆盖回 product ⇒ "下一轮即可执行"是空头承诺。
        """
        skill = "product"
        state = _base_state(skill)
        owner = _flow_owner_skill(state, "order_manage")
        result, rec, env = await _run_turn(
            skill=skill, tool_names=_declared_tools(skill),
            replies=[_validate_input_call(), _ai("抱歉，这个操作需要在对应流程里办理。")],
            facts=AS003_FACTS)
        assert owner, "前提不成立：归属流程解析不出"
        assert rec["calls"], "本轮没有任何 pending_skill 落点 —— 本用例会是空跑"
        assert rec["calls"][-1][1] == owner, (
            f"轮末把 pending_skill 覆盖回本轮流程：{rec['calls']}")
        assert result.get("pending_interact_skill") == owner, (
            f"图状态仍指向本轮流程（下一轮路由不会走归属流程）："
            f"{result.get('pending_interact_skill')!r}")

    async def test_inflight_confirm_card_ownership_follows_the_route(self):
        """AS-003 正是"已发过确认卡"的形态：卡归属不迁移 ⇒ 下一轮答卡豁免失效（乒乓）。"""
        skill = "product"
        state = _base_state(skill)
        owner = _flow_owner_skill(state, "order_manage")
        await _run_turn(
            skill=skill, tool_names=_declared_tools(skill),
            replies=[_validate_input_call(), _ai("抱歉，这个操作需要在对应流程里办理。")],
            facts=AS003_FACTS)
        facts = _FakeStateStore._states.get(SID) or {}
        assert facts.get("last_card_skill") == owner, (
            f"在办确认卡的归属未随流程迁移（下一轮答卡轮不豁免）：{facts.get('last_card_skill')!r}")
        assert facts.get("last_confirm_skill") == owner


class TestNegativePaths:
    """R2：四条阴性负例 —— 证明没有拦掉/改写原本合法的输入，也没有把会话打坏。"""

    async def test_in_domain_success_path_is_untouched(self):
        """① 域**内**目标的校验成功路径完全不受影响。"""
        skill = "order"
        tool_names = _declared_tools(skill)
        if "order_manage" not in tool_names:
            pytest.fail("前提不成立：order 流程应声明 order_manage")
        result, rec, env = await _run_turn(
            skill=skill, tool_names=tool_names,
            replies=[_validate_input_call(), _ai("已核对，请确认。")])
        payloads = _validate_payloads(result)
        if not payloads:
            pytest.fail("validate_input 没有被真的执行过 —— 本用例会是空跑")
        p = payloads[0]
        assert p.get("success") is True, f"域内合法校验被误伤（R2）：{p}"
        combined = f"{p.get('message') or ''}\n{p.get('suggestion') or ''}"
        assert "本会话已切到" not in combined, f"合法路径被改写成跨域指路：{combined!r}"
        assert not _foreign_pending(rec, skill), (
            f"域内成功路径被回锁（R2 破）：{rec['calls']}")

    async def test_other_validation_failures_do_not_relock(self):
        """② 非 `cross_skill_target` 的失败（缺参等）不触发回锁。

        形态刻意选**域内**目标 + **域闸门之后**才失败（缺 status）：证明"判决不是
        `cross_skill_target`"这一条是回锁的**唯一**触发条件，而不是"校验失败就回锁"。
        """
        skill = "order"
        result, rec, env = await _run_turn(
            skill=skill, tool_names=_declared_tools(skill),
            replies=[_validate_input_call(target_action="update_status"),
                     _ai("请补充要改成哪个状态。")])
        payloads = _validate_payloads(result)
        if not payloads:
            pytest.fail("validate_input 没有被真的执行过 —— 本用例会是空跑")
        p = payloads[0]
        assert p.get("success") is False, f"缺参失败应保持失败：{p}"
        assert p.get("error") != "cross_skill_target", (
            f"前提不成立：本用例要的是**别的**失败形态，实得 {p.get('error')!r}")
        assert not _foreign_pending(rec, skill), (
            f"非跨域失败被误回锁（R2 破）：{rec['calls']}")
        combined = f"{p.get('message') or ''}\n{p.get('suggestion') or ''}"
        assert "本会话已切到" not in combined, f"非跨域失败被写成跨域指路：{combined!r}"

    async def test_underivable_owner_changes_nothing_and_keeps_the_advice(self):
        """③ 归属 derive 不出（persona 不可达）⇒ 不改任何状态，退回既有劝导语（fail-safe）。"""
        skill = "product"
        result, rec, env = await _run_turn(
            skill=skill, tool_names=_declared_tools(skill),
            replies=[_validate_input_call(), _ai("抱歉，这个操作需要在对应流程里办理。")],
            state_overrides={"agent_type": "no_such_persona"})
        payloads = _validate_payloads(result)
        if not payloads:
            pytest.fail("validate_input 没有被真的执行过 —— 本用例会是空跑")
        p = payloads[0]
        assert p.get("error") == "cross_skill_target", f"域外拦截被放松：{p}"
        combined = f"{p.get('message') or ''}\n{p.get('suggestion') or ''}"
        assert "本会话已切到" not in combined, (
            f"归属解析不出却宣称已切流程（对模型的假承诺）：{combined!r}")
        assert "请把会话切到具备该工具的流程后再执行" in combined, (
            f"derive 失败时应退回**既有**劝导语：{combined!r}")
        assert not _foreign_pending(rec, skill), (
            f"derive 失败却改了会话状态（fail-safe 破）：{rec['calls']}")

    async def test_missing_session_does_not_break(self):
        """④ 无 session（单测直调形态）不炸：判决照旧、状态无从改。"""
        skill = "product"
        result, rec, env = await _run_turn(
            skill=skill, tool_names=_declared_tools(skill),
            replies=[_validate_input_call(), _ai("抱歉，这个操作需要在对应流程里办理。")],
            state_overrides={"session_id": ""})
        payloads = _validate_payloads(result)
        if not payloads:
            pytest.fail("validate_input 没有被真的执行过 —— 本用例会是空跑")
        p = payloads[0]
        assert p.get("error") == "cross_skill_target", f"无 session 时域外拦截被放松：{p}"
        combined = f"{p.get('message') or ''}\n{p.get('suggestion') or ''}"
        assert "本会话已切到" not in combined, (
            f"无 session 却宣称已切流程（无从落地的承诺）：{combined!r}")
        assert not _foreign_pending(rec, skill), (
            f"无 session 却产生了回锁落点：{rec['calls']}")


class TestRouteTargetIsFactDerived:
    """回锁目标必须**真的**在该 persona 的图里、且真的声明了被拒工具（不得写死 skill 名）。"""

    @pytest.mark.parametrize("tool", ["order_manage", "order_create"])
    def test_owner_declares_the_tool_and_is_reachable(self, tool):
        owner = _flow_owner_skill({"agent_type": "mibao"}, tool)
        if not owner:
            pytest.fail(f"mibao 解析不出 {tool} 的归属流程")
        cfg = get_agent_config("mibao")
        assert owner in cfg.get_all_skill_names(), (
            f"回锁目标 {owner!r} 不在 mibao 的 skill_names 里 → 图里没有该节点（#3571 族教训）")
        declared = get_skill_registry().get(owner)
        if declared is None:   # 显式失败分支（弱断言门禁）
            pytest.fail(f"回锁目标 {owner!r} 不在 skill 注册表里")
        assert tool in declared.tool_names, (
            f"回锁目标 {owner!r} 并未声明 {tool} —— 回锁后下一轮仍然调不到它")