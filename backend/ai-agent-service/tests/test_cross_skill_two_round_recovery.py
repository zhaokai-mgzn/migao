# case_ids: AS-003, OR-029
"""常驻判据：**被拒 → 回锁 → 下一轮同一目标真的可执行**（issue #4152，两轮串联，全确定性）。

## 缺口（为什么不是重复既有判据）

| 既有判据 | 覆盖到哪 |
|---|---|
| `backend/ai-agent-service/tests/test_cross_skill_target_routing.py`（#4124 / W1） | **单轮**：判决被消费、回锁发生、轮末不覆盖、指引进下一轮入参 —— 它**没有真的跑第二轮**去证明该目标在归属域**可执行** |
| `backend/ai-agent-service/tests/test_order_cross_skill_tool_not_found.py`（#3976） | 用的是**桩**（`get_tool` 恒 `None`、`get_pending_skill` 直接返回 `"order"`）⇒ 证的是"给定 pending 时的轮末行为"，**不是**"真实回锁后的下一轮" |

⇒ 本文件把主会话在 #4123 上跑过的**一次性探针**固化成常驻判据。探针结论（逐字）：

    第 1 轮（product 域）validate_input(order_manage, cancel)
      → 判决 = cross_skill_target ；轮末 pending_interact_skill = 'order'（事实 derive 的归属域）
    第 2 轮（order 域工具集）
      → 含 order_manage = True ；validate_input(order_manage, cancel) = {'success': True, ...}

判据本身**一字不改**地搬过来；载体（哪两个域）按 #5247 后的活真值重新锚定 —— B 端只读化后
`product` 已解绑 `validate_input`、`order_manage` 已无任何 skill 声明，旧 premise 在 B 端整体消失
（同 `test_cross_skill_target_routing.py` 的「载体从 B 端换成 C 端」口径）。

## 判据形态

- **第 1 轮**：真注册表 / 真域闸门（`_declared_tools(CARRIER_SKILL)` 经 `create_skill_registry`
  登记执行域），脚本化 LLM 调 `validate_input(CARRIER_TARGET)` ⇒ 判决 `cross_skill_target`；
- **第 2 轮**：skill = 第 1 轮**轮末**给出的 `pending_interact_skill`（= 下一轮路由真正读的那个键），
  工具集 = `SkillConfig.tool_names`（**注册表事实**，不手写清单）⇒ 断言**同一目标不再是
  `cross_skill_target`**：`success=True` **且**该工具真的进了下一轮 `bind_tools` 的入参
  （"可执行"不是"`pending_*` 被写过"—— 这才是自愈）。

## harness 只有一份

`_run_turn`（真 `execute_skill` + 真注册表 + 真域闸门，只 mock LLM 与会话存储）、载体常量、fake 存储
**全部 import 自** `tests.test_cross_skill_target_routing` —— 不复制第二份（复制的那份会随 W1 演进而腐烂）。

## 红证（为什么换成注入式，而不是"在改前实现上跑"）

#4152 交付要求原写"在干净 `origin/main`（W1 之前）上跑 ⇒ 必红"；但 W1（#4124）**已合并** ⇒ 干净
main 上已不存在"零消费判决"的实现，该形态无法再复现 ⇒ 改用**注入式红证**（`TestTheCriterionCanGoRed`，
常驻、可随时复跑）：把机制打回两种已知失效形态，同一条判据**必须**判红 ——
① **回锁被删**（改前形态：判决被丢弃，`grep -rn cross_skill_target app/graph/skills/` 只命中一处注释）；
② **轮末覆盖回来**（#3976 P3 形态：轮末持久化的读回保护失效，`pending_skill` 被写回本轮 skill）。
每条注入都**先自证注入生效**（判决消费点真的被调用过 / 下一轮的路由输入真的被打回原域），
否则那次"红"是空跑 —— 不许留一条不会红的判据。

## R2 阴性负例（链级）

① 域**内**目标：第 1 轮就成功 ⇒ 链**不迁移**（下一轮仍是本轮域，目标照旧可执行）；
② 归属 derive 不出：**不改任何状态**、下一轮仍不可执行（fail-safe：不假装自愈）。
单轮口径的对应断言归 W1 文件，本文件只钉**链级**事实，不重复它的断言面。
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.graph.skills.base_skill import _execute_tool_safe, _flow_owner_skill

from tests.test_cross_skill_target_routing import (
    AS003_FACTS,
    CARRIER_SKILL,
    CARRIER_TARGET,
    OWNERLESS_TARGET,
    XIAOBU_STATE,
    _FakeStateStore,
    _ai,
    _declared_tools,
    _run_turn,
    _validate_input_call,
    _validate_payloads,
)

#: 载体 persona（C 端 xiaobu：持有全部剩余写绑定，见模块 docstring 的 #5247 说明）
PERSONA = XIAOBU_STATE["agent_type"]


@pytest.fixture(autouse=True)
def _fresh_process_state():
    """用例级复位：fake 会话存储 + `validate_input` 的进程级结果缓存。

    缓存必须清：`_execute_tool_safe` 的只读缓存键含**执行域**（#4079 / A5），同一 (域, 工具, 入参)
    的**成功**结论 60s 内会跨用例命中 ⇒ 后续用例的"通过"可能来自缓存而不是真的执行过（假绿）。
    """
    _FakeStateStore._states = {}
    getattr(_execute_tool_safe, "_cache", {}).clear()
    yield
    _FakeStateStore._states = {}
    getattr(_execute_tool_safe, "_cache", {}).clear()


def _neutral_reply():
    """本轮收尾语：**不得**含 `CREATION_SKILL_NAMES` 的完成/取消标记。

    命中那些标记 ⇒ `finalize_turn` 第 10 节会**清掉** pending_skill（流程视为已结束），
    本判据赖以串联的"下一轮路由输入"就没了 —— 那不是本判据要证的自愈形态。
    """
    return _ai("好的，我把当前的情况说明一下。")


def _ownerless_validate_call():
    """归属 derive 不出的目标（#5247 后没有任何 skill 声明它）。"""
    return _ai(tool_calls=[{
        "name": "validate_input",
        "args": {"target_tool": OWNERLESS_TARGET, "target_action": "cancel",
                 "params": {"order_id": "20260910619250007"}},
        "id": "tc_validate_input_ownerless",
    }])


def _assert_carrier_premises():
    """§18.4 前置自断言：判据前提不成立时宁可红，不要空跑。"""
    carrier_tools = _declared_tools(CARRIER_SKILL)
    if CARRIER_TARGET in carrier_tools:
        pytest.fail(f"前提不成立：AS-003 形态要求第 1 轮所在流程**不含** {CARRIER_TARGET}")
    if "validate_input" not in carrier_tools:
        pytest.fail(f"前提不成立：{CARRIER_SKILL} 必须绑 validate_input（判决的产生者）")
    owner = _flow_owner_skill({"agent_type": PERSONA}, CARRIER_TARGET)
    if not owner or owner == CARRIER_SKILL:
        pytest.fail(f"前提不成立：{CARRIER_TARGET} 的归属域应是**别的**流程，实得 {owner!r}")
    if CARRIER_TARGET not in _declared_tools(owner):
        pytest.fail(f"前提不成立：归属域 {owner!r} 并未声明 {CARRIER_TARGET}")


async def _two_round_turn_chain(*, first_skill=CARRIER_SKILL, first_call=None,
                                first_facts=None, state_overrides=None):
    """跑**两轮**真 `execute_skill`；第 2 轮的一切都来自第 1 轮的结果 + 注册表事实。

    第 2 轮的 skill = `r1["pending_interact_skill"]`（轮末给出的下一轮路由输入，**不手写 skill 名**），
    工具集 = `_declared_tools(该 skill)`（`SkillConfig.tool_names` 事实）；两轮用**同一目标**再校验一次。
    """
    base = dict(state_overrides or XIAOBU_STATE)
    call = _validate_input_call() if first_call is None else first_call
    r1, _, _ = await _run_turn(
        skill=first_skill, tool_names=_declared_tools(first_skill),
        replies=[call, _neutral_reply()], facts=first_facts, state_overrides=base)
    next_skill = str(r1.get("pending_interact_skill") or "")
    assert next_skill, (
        f"第 1 轮轮末没有给出下一轮的路由输入（pending_interact_skill 为空）"
        f"⇒ 两轮判据无从成立：{r1.get('pending_interact_skill')!r}")
    tool_names_next = _declared_tools(next_skill)
    r2, _, env2 = await _run_turn(
        skill=next_skill, tool_names=tool_names_next, replies=[call, _neutral_reply()],
        state_overrides={**base, "pending_interact_skill": next_skill})
    return {"r1": r1, "r2": r2, "next_skill": next_skill,
            "tool_names_next": tool_names_next, "env2": env2}


def _first_payload(result, which: str) -> dict:
    """该轮模型**实际看到**的 `validate_input` 结果（空 ⇒ 判据会变成空跑，故直接失败）。"""
    payloads = _validate_payloads(result)
    assert payloads, f"{which}的 validate_input 没有被真的执行过 —— 本判据会是空跑"
    return payloads[0]


def _bound_tool_names(env) -> list:
    """本轮**真的绑给模型**的工具名（`bind_tools` 的真实入参，不是我们传进去的清单）。"""
    calls = env["llm"].bind_tools.call_args_list
    assert calls, "本轮没有调用过 bind_tools —— 判据前提不成立"
    tools = calls[-1].args[0] if calls[-1].args else []
    return [getattr(t, "name", "") for t in tools]


def _assert_injection_broke_the_recovery(chain) -> None:
    """注入后的**可归因性**自证：第 1 轮判决不变，**只有恢复那一步**没了 ⇒ 第 2 轮仍不可执行。

    没有这一层时，"判据红了"可能红在别处（第 1 轮就没跑起来 / 14 个工具之外的原因）——
    那样红证不可归因，等于没证。这里逐条把差异钉在"恢复"上。
    """
    p1 = _first_payload(chain["r1"], "第 1 轮")
    assert p1.get("error") == "cross_skill_target", (
        f"注入不该改变第 1 轮的判决（否则本次'红'不可归因）：{p1}")
    assert chain["next_skill"] == CARRIER_SKILL, (
        f"注入没生效：下一轮的路由输入仍在归属域（next_skill={chain['next_skill']!r}）"
        f"⇒ 本次'红'是空跑")
    p2 = _first_payload(chain["r2"], "第 2 轮")
    assert p2.get("error") == "cross_skill_target", (
        f"注入后第 2 轮居然可执行了（本次'红'不可归因）：{p2}")


def _assert_self_heal_holds(chain) -> None:
    """**判据本体**：被拒 → 回锁 → 下一轮同一目标真的可执行。

    抽成普通函数（只用 `assert`）是为了让"这条判据会红"可被机械自证：注入失效形态后
    同一个函数**必须**抛 `AssertionError`（见 `TestTheCriterionCanGoRed`）。
    """
    p1 = _first_payload(chain["r1"], "第 1 轮")
    # ① 强度不降：域外目标在第 1 轮**仍被拒**（不得为了"自愈"放松闸门）
    assert p1.get("success") is False and p1.get("error") == "cross_skill_target", (
        f"第 1 轮域外目标没被拒（前提不成立 / 闸门被放松）：{p1}")
    # ② **判据本体**：下一轮**同一目标真的可执行** —— 三条事实一起给（红时能直接读出"仍走本轮域"）。
    #    ③ 下一轮的工具集是**注册表事实**；④ 判决不再是 `cross_skill_target` 且 `success=True`。
    p2 = _first_payload(chain["r2"], "第 2 轮")
    assert (CARRIER_TARGET in chain["tool_names_next"] and p2.get("success") is True
            and p2.get("error") != "cross_skill_target"), (
        f"第 2 轮同一目标仍不可执行（自愈链断开）：next_skill={chain['next_skill']!r} "
        f"工具集含 {CARRIER_TARGET}={CARRIER_TARGET in chain['tool_names_next']} payload={p2}")
    # ⑤ 过程事实（定位用）：下一轮的路由输入 = **事实 derive** 的归属域，且不是本轮域
    owner = _flow_owner_skill({"agent_type": PERSONA}, CARRIER_TARGET)
    assert owner and owner != CARRIER_SKILL, f"归属域解析不出：{owner!r}"
    assert chain["next_skill"] == owner, (
        f"第 1 轮轮末没有把会话回锁到归属域（下一轮仍走本轮域 ⇒ 自愈链断开）："
        f"next_skill={chain['next_skill']!r} owner={owner!r}")
    assert CARRIER_TARGET in _declared_tools(owner), (
        f"归属域 {owner!r} 并未声明 {CARRIER_TARGET} ⇒ 回锁后下一轮仍然调不到它")
    # ⑥ "可执行" = 模型真的拿得到它：本轮 `bind_tools` 的入参里必须有该工具
    bound = _bound_tool_names(chain["env2"])
    assert CARRIER_TARGET in bound, (
        f"第 2 轮没有把 {CARRIER_TARGET} 绑给模型（工具集里有、模型却看不见 ⇒ 不可执行）：{bound}")


class TestTwoRoundRecoveryIsPermanent:
    """常驻判据：被拒 → 回锁 → 下一轮同一目标真的可执行（issue #4152）。"""

    async def test_rejected_target_becomes_executable_in_the_owners_next_round(self):
        _assert_carrier_premises()
        chain = await _two_round_turn_chain(first_facts=AS003_FACTS)
        _assert_self_heal_holds(chain)


class TestChainLevelNegatives:
    """R2：链级阴性负例 —— 域内目标不迁移；归属 derive 不出时不改状态、也不假装自愈。"""

    async def test_in_domain_target_does_not_migrate_the_next_round(self):
        """① 域**内**目标：第 1 轮就成功 ⇒ 链**不迁移**，下一轮仍是本轮域且照旧可执行。"""
        owner = _flow_owner_skill({"agent_type": PERSONA}, CARRIER_TARGET)
        if not owner or "validate_input" not in _declared_tools(owner):
            pytest.fail(f"前提不成立：{owner!r} 必须同时声明 validate_input 与 {CARRIER_TARGET}")
        chain = await _two_round_turn_chain(first_skill=owner)
        p1 = _first_payload(chain["r1"], "第 1 轮")
        assert p1.get("success") is True, f"域内合法校验被误伤：{p1}"
        assert chain["next_skill"] == owner, (
            f"域内目标触发了迁移/回锁（回锁的唯一触发条件应是 `cross_skill_target`）："
            f"next_skill={chain['next_skill']!r} owner={owner!r}")
        p2 = _first_payload(chain["r2"], "第 2 轮")
        assert p2.get("success") is True, f"域内目标在下一轮不可执行（链被自己打坏）：{p2}"

    async def test_underivable_owner_leaves_the_chain_unchanged(self):
        """② 归属 derive 不出 ⇒ **不改任何状态**，链不迁移、下一轮仍不可执行（不假装自愈）。"""
        if _flow_owner_skill({"agent_type": PERSONA}, OWNERLESS_TARGET):
            pytest.fail(f"前提不成立：{OWNERLESS_TARGET} 现在有归属了（本用例要的是 derive 不出的形态）")
        chain = await _two_round_turn_chain(first_call=_ownerless_validate_call())
        p1 = _first_payload(chain["r1"], "第 1 轮")
        assert p1.get("success") is False and p1.get("error") == "cross_skill_target", (
            f"域外拦截被放松：{p1}")
        assert chain["next_skill"] == CARRIER_SKILL, (
            f"归属解析不出却迁移了会话状态（fail-safe 破）：next_skill={chain['next_skill']!r}")
        p2 = _first_payload(chain["r2"], "第 2 轮")
        assert p2.get("error") == "cross_skill_target", (
            f"归属解析不出却宣称下一轮可执行（对模型的假承诺）：{p2}")


class TestTheCriterionCanGoRed:
    """红证自证：把机制打回两种已知失效形态，同一条判据**必须**判红（issue #4152）。

    为什么是注入式：W1（#4124）已合并 ⇒ 干净 main 上不存在"零消费判决"的实现，无法再在改前实现上复现红。
    每条注入都**先自证生效**再断言判据会红 —— 否则"红"可能是空跑（注入没打中）。
    """

    async def test_relock_removed_turns_the_criterion_red(self):
        """① **回锁被删**（改前形态）：判决被丢弃 ⇒ 下一轮仍走本轮域 ⇒ 判据必红。"""
        _assert_carrier_premises()
        with patch("app.graph.skills.base_skill._route_cross_skill_target",
                   new=AsyncMock(return_value="")) as dropped:
            chain = await _two_round_turn_chain(first_facts=AS003_FACTS)
        if dropped.await_count < 1:
            pytest.fail(f"注入没生效：判决消费点没被调用过（await_count={dropped.await_count}）"
                        f"⇒ 本次'红'是空跑")
        _assert_injection_broke_the_recovery(chain)
        with pytest.raises(AssertionError):
            _assert_self_heal_holds(chain)

    async def test_round_end_overwrite_turns_the_criterion_red(self):
        """② **轮末覆盖回来**（#3976 P3 形态）：回锁结果被轮末写回本轮 skill ⇒ 判据必红。"""
        import app.graph.skills.execution.finalize_turn as _finalize_module
        _real_finalize = _finalize_module.finalize_turn

        async def _overwrite_at_round_end(**kwargs):
            out = await _real_finalize(**kwargs)
            # 生产形态：轮末第 10 节的持久化把 pending_skill 写回**本轮** skill（读回保护失效）
            out["pending_interact_skill"] = kwargs["skill_name"]
            from app.memory.session_memory import SessionMemory
            await SessionMemory().set_pending_skill(
                kwargs.get("session_id"), kwargs["skill_name"])
            return out

        _assert_carrier_premises()
        with patch("app.graph.skills.execution.finalize_turn.finalize_turn",
                   new=_overwrite_at_round_end):
            chain = await _two_round_turn_chain(first_facts=AS003_FACTS)
        if chain["next_skill"] != CARRIER_SKILL:
            pytest.fail(f"注入没生效：轮末覆盖后下一轮的路由输入仍是 {chain['next_skill']!r}"
                        f"⇒ 本次'红'是空跑")
        _assert_injection_broke_the_recovery(chain)
        with pytest.raises(AssertionError):
            _assert_self_heal_holds(chain)