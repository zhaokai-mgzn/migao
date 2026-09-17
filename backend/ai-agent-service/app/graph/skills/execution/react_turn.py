"""`execute_skill` 的第 7 节：ReAct 循环（写门禁链 / 工具调用 / 卡片发射 / 纠偏）。

**逐字搬迁**自 `base_skill.py`（issue #4049，源头是「关联 #4043」的 S3 条）。
本文件的 `react_turn` 函数体 = 原第 3890~5074 行**去掉一层缩进后的逐字副本**
（含 `# ── 7. ReAct 循环 ──` 分节注释）：一个字符都没改，只做机械重绑定 ——
函数头收拢入参、函数尾补一个 `return` 把「8~10 节还要用」的状态交回编排壳。

⚠️ 区内那 21 处 `return {...}` **全部在嵌套闭包**（`_llm_invoke` / `_run_one_tool`）里，
不是本节对外的早退 ⇒ 本节对外**只有一个出口**（末尾那个 `return`）。

⚠️ **import 方向是单向的**：本模块顶层 import `base_skill` 的模块级助手，而
`base_skill.execute_skill` 在**函数体内** import 本模块 —— 加载期只有一个方向。
理由、图示与「别整理这三行 import」的原因见 `app/graph/skills/execution/__init__.py`。
"""
import asyncio
import json
from typing import Any, List

from app.graph.skills.base_skill import (
    AIMessage, AgentState, CARD_EMIT_COUNTS_KEY, CircuitBreakerOpenError,
    HumanMessage, KNOWN_ADDRESS_KEY, LLM_CALL_TIMEOUT_S, ORDER_WRITE_TOOL,
    RECOGNIZABLE_INPUT_PARAMS, SystemMessage, ToolMessage, WRITE_INPUT_ERROR_KEY,
    _MULTI_TURN_THINKING_INTENTS, _STALL_CORRECTIVE, _TEXT_DENIAL_CORRECTIVE, _TEXT_DENIAL_CORRECTIVE_BIZ,
    _TEXT_DENIAL_CORRECTIVE_MIDORDER, _TEXT_DENIAL_CORRECTIVE_PRODUCT_IMAGE, _b_create_processing_items_not_asked, _capability_denial_reason,
    _card_loop_block, _clear_write_input_error, _confirm_card_fields_hint, _confirm_card_seen,
    _current_request_id, _curtain_calc_dimension_block, _ensure_processing_items_multiselect, _err_inc,
    _extract_content, _flow_state_in_progress, _form_prefill_fidelity_block, _handoff_guard_applies,
    _has_ordering_intent, _has_processing_choice_in_turn, _is_cancel_message, _is_card_confirm_value,
    _is_customer_role, _is_explicit_confirmation, _is_processing_items_card, _is_retryable,
    _last_product_id, _logistics_chain_corrective, _logistics_chain_incomplete, _mark_processing_items_asked,
    _masked_phone_write_block, _order_capability_available, _order_flow_in_progress, _order_flow_started,
    _order_write_tool_here, _pending_card_before_last_user, _plan_b_create_processing_items_rewrite, _plan_processing_items_rewrite,
    _processing_items_already_asked, _product_image_capability_available, _product_image_denial_hit, _quantity_choice_block,
    _relock_order_skill, _remember_known_value, _remember_raw_phones, _remember_sms_code,
    _requires_confirmation, _self_correct_retry, _stall_has_progress, _stored_sms_code,
    _track_llm_cost, _write_input_recovery_block, capability_denial_text_hit, card_fingerprint,
    extract_pending, extract_product_keyword, extract_sms_code, is_pending_for,
    llm_breaker_name, llm_incident_id, missing_input_param, raw_phones_in,
    resolve_sms_code, safe_exc_message, unit_price_grounding_error,
)


# 「第 7 节未执行 ⇒ 该名未绑定」的哨兵。
# 原实现里这是一种**未绑定**状态：8.4 的 `try` 首次引用即抛 `UnboundLocalError`，被
# `except Exception` 吞掉 ⇒ 收口整体跳过。跨函数后无法保留「未绑定」本身，故用同一个
# 对象把该状态如实带过边界：`finalize_turn` 里首次求真值/取属性即抛错
#（`_is_explicit_confirmation` 的 `(text or "").strip()`）⇒ 与「8.4 整体跳过、且不执行
# 任何写」一致；即便某条路径不抛错，`_should_code_close_loop(..., confirmed=False, ...)`
# 也**必然**返回 False（纯函数真值表见 `tests/test_base_skill.py`）⇒ 仍不会写。
UNBOUND = object()


async def react_turn(
    state: AgentState,
    skill_name: str,
    max_iterations: int,
    raw_messages: list,
    session_id: str,
    tenant_id: int,
    tool_context,
    skill_registry,
    new_messages: List[Any],
    is_multimodal: bool,
    llm_model_name: str,
    llm_no_thinking,
    llm_with_tools,
    intent_name: str,
    full_messages: List[Any],
    vision_analysis: str,
    final_content: str,
    _denial_corrected: bool,
    _stall_corrected: bool,
    _no_card_blocked_args,
    _write_ok: bool,
    _relocked_this_round: bool,
) -> dict:
    """第 7 节：ReAct 循环（LLM 自主推理 → Tool 调用 → 观察结果 → 继续推理）。

    入参里 `_denial_corrected` / `_stall_corrected` / `_no_card_blocked_args` / `_write_ok` /
    `_relocked_this_round` / `final_content` 是**编排侧已初始化的本轮状态**（原实现里与本节
    同处一个作用域）：它们在本节里都**先读后写**，所以必须按值传入而不是在本节里重新初始化。
    其中 `_no_card_blocked_args` / `_write_ok` / `_relocked_this_round` 是 `_run_one_tool` 的
    `nonlocal` 目标 —— 参数是合法的 `nonlocal` 绑定目标，故闭包内那三条 `nonlocal` **逐字保留**
    （改成「在本节内重新初始化」会让门禁置位只落在本节里、8.4/8.3b 永远读不到）。
    """
    # ── patch 点：下面这些名字必须**调用期**从 base_skill 取值（别改成模块顶层 import）──
    # 既有守卫用 `patch.object(base_skill, "<name>")` / `patch("app.graph.skills.base_skill.<name>")`
    # 给它们打桩（接缝清单由测试**机械提取**：tests/unit/test_execute_skill_split.py）。
    # 模块顶层 `from ... import <name>` 会把绑定**冻在 import 那一刻** ⇒ patch 静默失效
    #（本仓最忌讳的「判据自己选择沉默」）。拆分前这些名字是 base_skill 的模块全局、**调用期**
    # 解析；下面这几行恢复**同一解析时机**，语义与拆分前一致。
    # 机械守护：tests/unit/test_execute_skill_split.py::test_no_patch_seam_is_frozen_at_import
    from app.graph.skills import base_skill as _base
    from app.memory.session_memory import SessionMemory
    _execute_tool_safe = _base._execute_tool_safe
    call_with_retry = _base.call_with_retry
    get_breaker = _base.get_breaker
    logger = _base.logger
    # ── 7. ReAct 循环 ──
    if not is_multimodal or (is_multimodal and vision_analysis):
        # 取消检测（生产回归修复：原实现纯关键词子串匹配，
        # "回归测试取消Z03"这类商品名、"帮我取消订单X"这类业务动作都被误判为取消指令）
        last_user_msg = ""
        for m in reversed(raw_messages):
            if isinstance(m, HumanMessage):
                last_user_msg = _extract_content(m)
                break
        # 只有在**确实有在办流程**时才允许"取消"短路（验收发现，issue #3367）。
        # 实证（验收剧本 C-A2，transcripts/ci-34730957920）：
        #   顾客「算了，先看看你们有什么窗帘」→ AI「好的，**已取消**。」且**零工具调用**。
        # 两处危害：① 假状态变更（什么都没在办却说"已取消"，顾客可能以为订单被撤了）；
        #           ② 整句吞掉真实诉求（"看看有什么窗帘"没有触发 product_search）。
        # 判据：pending 流程标记 / pending_interact_skill / 历史里未完结的交互卡 —— 三者皆无
        # 就说明"没有东西可取消"，此时应正常处理顾客这句话（该搜索就搜索）。
        _pending_validated = False
        if session_id:
            try:
                from app.memory.session_state_store import SessionStateStore
                from app.graph.pending_validated import PENDING_KEY
                _full_cancel = await SessionStateStore().load(session_id) or {}
                _pending_validated = bool(_full_cancel.get(PENDING_KEY))
            except Exception:
                _pending_validated = False
        _inflight = _pending_card_before_last_user(state.get("messages", [])) or _pending_validated
        # 验证码轮记账（issue #3379 P2-1）：顾客先给码、下一轮回「确认」是**正常流程**，
        # 不记就会在写工具那一步要求顾客**再发一次码**（验收 C-A1 R7 空转的根因）。
        if session_id and extract_sms_code(last_user_msg):
            await _remember_sms_code(session_id, last_user_msg)

        if _is_cancel_message(last_user_msg) and _inflight:
            logger.info(f"[{skill_name}] Cancel detected | session={session_id} "
                        f"msg={last_user_msg[:24]!r}")
            final_content = "好的，已取消。有什么其他需要帮您的吗？"
            new_messages.clear()
            if session_id:
                try:
                    await SessionMemory().clear_pending_skill(session_id)
                except Exception:
                    pass
        else:
            if _is_cancel_message(last_user_msg) and not _inflight:
                logger.info(
                    f"[{skill_name}] 「取消」类措辞但无在办流程 → 不短路，按正常诉求处理 "
                    f"| session={session_id} msg={last_user_msg[:24]!r}")
            # 本轮**模型自己执行过**的工具名（供 8.4 收口判重：防双单）
            _executed_tools: set = set()
            # 本回合 `order_query` 成功返回过的**真实订单号**（订单→物流链收口的判据③，
            # 只记事实；跨迭代累计，见 issue #3799）
            _turn_order_nos: list = []
            # 链收口纠正**有界**：每个回合一经注入即置位，不再二次注入（见下方判据）
            _logistics_chain_corrected = False
            # 本次 execute_skill 调用（= 顾客的一个回合）**已下发过的卡片组件**：
            # 同一组件每轮只允许一张（issue #3445）。**整轮**生效，跨 LLM 迭代也要认
            # （模型可能在后续迭代"再补一张"）—— 故在循环**外**初始化（放循环里会被每轮重置，
            # 跨迭代的重复卡就漏了，实测如此）。
            # 只按**组件**判重、不按"整轮一张"：OR-021 R3 实测 `choice(加工项)+form(收货信息)`
            # 是**合法**的一条消息两个问题（两个组件各有答案面，前端逐张渲染）——
            # 一刀切"只准一张"会把这个正常流程也拦掉。
            _turn_card_components: set = set()
            # `_llm_error_retried`：**本次 `execute_skill`（= 顾客的一个回合）**是否已因
            # "瞬时类异常"重试过一次。刻意放**循环外**：预算是"一轮对话一次机会"，
            # 不是"每个 ReAct 迭代一次" —— 后者在同一故障持续时会把 8 个迭代全烧在重试上，
            # 最后退化成"轮次耗尽"话术（用户仍得不到任何进展，且白烧 8 次配额）。
            _llm_error_retried = False
            for iteration in range(max_iterations):
                logger.info(f"[{skill_name}] Iteration {iteration+1}/{max_iterations} | session={session_id}")

                # 首轮保持 thinking（规划工具调用）
                # 迭代 2+ 轮：多步推理意图保留 thinking（工具结果可能驱动新一轮规划），
                # 单步检索意图关闭 thinking 以节省 5-8s/轮（仍保留工具绑定，支持多步工具调用）
                if iteration == 0:
                    current_llm = llm_with_tools
                elif intent_name in _MULTI_TURN_THINKING_INTENTS:
                    current_llm = llm_with_tools
                else:
                    current_llm = llm_no_thinking or llm_with_tools

                # ── LLM 调用（超时 + 熔断保护）──
                # 熔断 / 超时 / 轮次耗尽的守卫**不动**（它们各有自己的分支与话术）。
                # 瞬时类异常的**一次**自动恢复预算由循环外的 `_llm_error_retried` 管
                # （每回合一次，不随迭代重置）。
                try:
                    logger.info(f"[{skill_name}][DIAG] LLM calling | iter={iteration+1} msgs={len(full_messages)+len(new_messages)} session={session_id}")
                    llm_breaker = get_breaker(llm_breaker_name(skill_name))

                    async def _llm_invoke():
                        return await asyncio.wait_for(
                            current_llm.ainvoke(full_messages + new_messages),
                            timeout=LLM_CALL_TIMEOUT_S,
                        )

                    response: AIMessage = await call_with_retry(lambda: llm_breaker.call(_llm_invoke))
                    _track_llm_cost(response, model=llm_model_name, tenant_id=state.get("tenant_id"), session_id=session_id)
                    logger.info(
                        f"[{skill_name}][DIAG] LLM done | iter={iteration+1} "
                        f"has_tools={bool(response.tool_calls)} content_len={len(response.content or '')} "
                        f"session={session_id}"
                    )
                except CircuitBreakerOpenError:
                    logger.error(f"[{skill_name}][SLS] LLM circuit_breaker_open | session={session_id}")
                    final_content = "抱歉，AI 服务暂时不可用，请稍后重试。"
                    break
                except asyncio.TimeoutError:
                    logger.error(f"[{skill_name}][SLS] LLM timeout | iter={iteration+1} session={session_id}")
                    final_content = "抱歉，响应超时，请换个方式描述您的需求。"
                    break
                except Exception as e:
                    # ── ① 瞬时类异常：**允许有限次自动恢复**（issue #3810 演示护航）──
                    # 判据是**事实驱动**的：异常类型是否属"瞬时/可重试"（`_is_retryable`：
                    # 超时、429/5xx、连接层），以及本回合是否已经重试过 ——
                    # **不看**兜底话术里有没有关键词（那会把"事实"变成"措辞匹配"）。
                    # 为什么必须有这一步：#3805 的实测形态正是"同一会话连吞 3 轮同一句兜底"
                    # （R9–R11）——会话卡在同一个瞬时故障上。对瞬时故障再给**一次**机会，
                    # 演示现场就能自愈，而不是每一轮都撞同一堵墙。
                    # 预算：**每回合 1 次**（`_llm_error_retried` 在循环外初始化）——
                    # 不用"每迭代 1 次"，否则同一故障持续时 8 个迭代全烧在重试上，
                    # 最后退化成"轮次耗尽"话术（用户仍无进展，还白烧 8 次配额）。
                    # ⚠️ 不得把失败伪装成成功：重试仍失败时走下面同一条如实兜底。
                    if _is_retryable(e) and not _llm_error_retried:
                        _llm_error_retried = True
                        _retry_incident = llm_incident_id(session_id, type(e).__name__)
                        logger.opt(exception=e).warning(
                            f"[{skill_name}][SLS] LLM call 重试（瞬时类异常）"
                            f" | session={session_id} error={type(e).__name__}: "
                            f"{safe_exc_message(e)} | incident={_retry_incident} "
                            f"tenant={state.get('tenant_id')} iter={iteration+1} "
                            f"req={_current_request_id()}"
                        )
                        continue
                    # ── ② 重试后仍失败 / 不可重试：如实告知"这轮没成功、可以重试" ──
                    # #3805 的 `抱歉，我遇到了一些问题…` 属于**无信息量通用句**（用户不知道
                    # 这轮有没有成功、下一步该做什么），且 #3810 要求不得改成"静默成功"。
                    # 现话术：纯中文 + 说明"这轮没成功" + 给出可执行的下一步，**不出现**
                    # 异常类型/英文标识/堆栈/字段名（C 端低学历用户约定，见 #3707 族）。
                    # 复杂度上刻意保持通用：这里区分不了"有部分工具结果"（工具结果落库在
                    # 失败迭代之后，本点拿不到事实），无事实依据的分支就是过度建设。
                    # ⚠️ 措辞不得含 CREATION_SKILL_NAMES 流程的成功/取消标记（如"已创建"
                    #    "已下单"）——否则第 10 步的 pending_skill 判定会把失败的写流程
                    #    当成"已完成"解锁，那是把失败伪装成成功。
                    _err_inc.log_exception_audit(
                        logger=logger,
                        mark=f"[{skill_name}][SLS] LLM failed",
                        exc=e,
                        session_id=session_id,
                        extra=(f"tenant={state.get('tenant_id')} iter={iteration+1} "
                               f"req={_current_request_id()}"),
                    )
                    final_content = "刚才这轮没成功，请您再说一次，我继续为您办理。"
                    break

                new_messages.append(response)

                # ── 文本级能力误宣检查 ──
                new_text = _extract_content(response)
                # 下单域能力误宣（issue #3443）：只在**纯文本回复**检查
                # （无 tool_calls → LLM 已完成回复；带工具调用的回复文本是过程性旁白）。
                if not response.tool_calls:
                    # 能力误宣（issue #3443）：文本里"我做不了下单"→ 带纠正提示**重答一次**
                    # （只一次，防死循环）。重答走完整循环，故模型可以继续调工具把单下掉。
                    _denial_hit = capability_denial_text_hit(new_text)
                    # 判据 = **在办下单流程状态 × 工具能力事实**（与 skill 名无关，#3477 根治）：
                    #   · `_has_write_now`：下单写工具就在**本 skill** 手上（注册表事实）；
                    #   · `_order_in_progress`：顾客处于在办下单流程（跨轮状态事实，不靠本轮措辞）。
                    _order_in_progress = await _order_flow_in_progress(
                        session_id, state, last_user_msg)
                    _has_write_now = _order_write_tool_here(skill_registry)
                    if (_denial_hit and not _denial_corrected
                            and _order_capability_available(
                                skill_registry, order_in_progress=_order_in_progress)):
                        # issue #3477：顾客在办下单时，即使当前 skill 没有写工具
                        # （如会话被 choice 卡锁在 customer_product），也不许"我下不了单"。
                        # 无写工具时用 MIDORDER 版话术（不声称"order_create 就是本流程的工具"），
                        # 并把会话锁回下单流程（含在办确认卡的归属迁移，见 `_relock_order_skill`），
                        # 下一轮才能真的把单下掉。
                        _denial_corrected = True
                        logger.warning(
                            f"[{skill_name}] 拦截文本级能力误宣并重答 | session={session_id} "
                            f"hit={_denial_hit!r} mid_order={_order_in_progress}")
                        if _order_in_progress and not _has_write_now:
                            await _relock_order_skill(session_id, state,
                                                      migrate_card_owner=True)
                        if _has_write_now:
                            _fix = (_TEXT_DENIAL_CORRECTIVE if _is_customer_role(state)
                                    else _TEXT_DENIAL_CORRECTIVE_BIZ)
                        else:
                            _fix = _TEXT_DENIAL_CORRECTIVE_MIDORDER
                        new_messages.append(SystemMessage(content=_fix))
                        continue
                    # ── 订单→物流链收口（issue #3799）──
                    # 模型把「查到订单号」当交付物就收尾 ⇒ 顾客要的轨迹没给（链只走一半）。
                    # 命中判据全是事实（见 `_logistics_chain_incomplete`），**有界一次**：
                    # 注入纠正后继续循环让模型自己调 logistics_track；若注入后仍不调，
                    # 接受本轮结束（不无限注入），但留一条可检索日志便于归因"注入了但模型没跟"。
                    _chain_incomplete = _logistics_chain_incomplete(
                        intent_name=intent_name,
                        registry=skill_registry,
                        order_nos=_turn_order_nos,
                        executed_tools=_executed_tools,
                    )
                    if _chain_incomplete and not _logistics_chain_corrected:
                        _logistics_chain_corrected = True
                        logger.warning(
                            f"[{skill_name}][logistics-chain] 流程链未走完：本轮 intent={intent_name}、"
                            f"order_query 已返回 {len(_turn_order_nos)} 个真实订单号、"
                            f"logistics_track 从未尝试 → 注入纠正并继续本轮 | session={session_id}")
                        new_messages.append(SystemMessage(
                            content=_logistics_chain_corrective(_turn_order_nos)))
                        continue
                    if _chain_incomplete and _logistics_chain_corrected:
                        logger.warning(
                            f"[{skill_name}][logistics-chain] 已注入纠正但模型仍未调用 "
                            f"logistics_track → 接受本轮结束（不二次注入）| session={session_id} "
                            f"intent={intent_name} order_nos={len(_turn_order_nos)}")
                    if new_text:
                        final_content = new_text
                    elif not final_content:
                        final_content = "抱歉，我暂时无法生成回复，请换个方式描述您的需求。"
                    break

                # ── 商品图片域能力误宣（issue #3931，迭代3 #3940）──
                # 与下单域同一条「纠正重答」路径：AI 说「该入口不支持图片/拿不到地址」，
                # 而 product_manage(action=update, images=…) 在**本 skill 工具子集**里真实可达
                # （判据 = `_product_image_denial_hit`（图片域文本）× 注册表事实）。
                # ⚠️ 迭代3 关键修正（PR-026/027 复现 run 34978506935）：**不 gate
                # tool_calls** —— flash 常把拒绝文本与查询工具调用**同回合**生成
                # （transcript：`text「换主图这个动作我这边做不了」+ product_detail 调用
                # 同一条消息），旧判据只看纯文本回复 → 守卫从未触发、拒绝原样出站。
                # 命中即丢弃本轮查询调用、带纠正话术重答（正是期望行为）。
                _image_denial_hit = _product_image_denial_hit(new_text)
                if (_image_denial_hit and not _denial_corrected
                        and _product_image_capability_available(skill_registry)):
                    _denial_corrected = True
                    logger.warning(
                        f"[{skill_name}] 拦截商品图片域能力误宣并重答 | session={session_id} "
                        f"hit={_image_denial_hit!r}")
                    new_messages.append(SystemMessage(
                        content=_TEXT_DENIAL_CORRECTIVE_PRODUCT_IMAGE))
                    continue

                # ── 执行 Tool 调用（并发）──
                # 本轮「同轮重复写调用」去重槽（issue #3361）：见下方 _run_one_tool 内的说明。
                # 每轮重置：去重范围严格限定在**同一次 LLM 回复**内，绝不跨轮/跨时间窗。
                _turn_write_slots: dict = {}
                # issue #3976：每轮重置 relock 标记（跨轮语义见函数体顶部初始化）。
                _relocked_this_round = False

                async def _run_one_tool(tool_call: dict, allow_card: bool = True):
                    """执行单个 tool，返回 (tool_call, result_str, result_dict)。

                    `allow_card`：该组件在本轮的**第一张**卡才为 True（调用侧按回复里
                    `interact` 出现的位置 + `_turn_card_components` 预计算 ——
                    并发 gather 下"先检查后置位"的标志有竞态，见调用侧注释）。
                    """
                    # 需要 nonlocal：门禁在下面给 `_no_card_blocked_args` 赋值，而它是
                    # `execute_skill` 的局部变量 —— 不加 `nonlocal` 会创建一个**新局部**，
                    # 收尾的"补发确认卡"永远读不到（首版即此错，被新增用例当场抓住）。
                    nonlocal _no_card_blocked_args
                    # 同理 `_write_ok`（issue #3750）：不加 nonlocal 只会创建一个**新局部**，
                    # 收尾 8.6 永远读到 False ⇒ "本轮写成功了"判不出来，成功回执也可能被归一。
                    nonlocal _write_ok
                    nonlocal _relocked_this_round
                    tool_name = tool_call["name"]
                    args = tool_call.get("args", {})
                    # ── C 端同一组件每轮只允许**一张**卡（issue #3445，OR-023 实证）──
                    # 实测 run 34785793796：OR-023 首跑 R1 `tools=…,interact,interact`
                    # → `cards=choice,choice` —— 一张问「有两个颜色可选，您要哪一款呀？」、
                    # 一张「颜色选好啦～」。会话侧只保存**最后一张**待答卡
                    # （`chat.py` 的 `last_interactive_payload` 单槽）⇒ 顾客点第一张，
                    # 回传的值与"当前待答卡"对不上，点卡链路错位。
                    # 同一组件的一次消息两张卡没有第二种解释（同一答案面），
                    # 故本轮同组件第二张起直接拦下并回一条可执行的提示（不静默丢弃）。
                    # **不同组件不受限**（OR-021 R3 的 choice+form 是合法形态）。
                    # **只对 C 端生效**（分端纪律）：B 端表单/卡片流程尚未按此校准。
                    # 判重**只在调用侧**做一次（`allow_card`）：并发 gather 下"先检查后置位"
                    # 必然有竞态（真实工具会 await I/O），故这里只消费已经算好的结论。
                    if tool_name == "interact" and _is_customer_role(state) and not allow_card:
                        logger.warning(
                            f"[{skill_name}] 本轮已下发过同组件卡片 → 拦下重复的 interact 调用"
                            f"| session={session_id}"
                            f" component={(args or {}).get('component')}"
                            f" title={str((args or {}).get('title') or '')[:30]}")
                        return (tool_call,
                                json.dumps({
                                    "success": False,
                                    "error": "card_already_emitted_this_turn",
                                    "message": ("本轮已经给顾客下发过同类型的卡片了 —— "
                                                "同一种卡片一轮只该有一张，重复发卡会让顾客点错、"
                                                "答案与当前卡对不上。请**等顾客操作**后再继续；"
                                                "若第一张卡的内容有误，用文本更正即可，不要重发卡。"),
                                }, ensure_ascii=False),
                                {"success": False,
                                 "error": "card_already_emitted_this_turn"})
                    # 模式 C 代码兜底：加工项 choice 卡漏传 multiSelect → 自动补 true（PR-014/015）
                    args = _ensure_processing_items_multiselect(tool_name, args)
                    # 代码兜底：顾客上一条就是验证码，但模型调 order_create 时没带上
                    # → 自动补齐（issue #3365 实证：CI 里 order_create!缺少短信验证码 ×3，
                    #   顾客明明给了 123456；模型漏参 → 订单不落库 → 用例红且看着像"能力不行"）
                    if tool_name == "order_create":
                        # 验证码真值链（issue #3365 补齐 / #3379 P2-1 记码 / #3434 纠正）：
                        #   ① 顾客上一条消息**整条就是验证码**（原有）；
                        #   ② **本会话此前记住的验证码** —— 顾客先给码、再回「确认」时，
                        #      上一轮已经不是码了，若不记就会要求顾客**再发一次**
                        #      （验收 C-A1 实证：验证码轮空转、AI 还说"稍后还需要您手机验证"）。
                        # 与旧行为的差别：模型**带了**码但与我们知道的真值不一致时，也要纠正
                        # （旧行为只管"漏参"，于是模型自造的码一路走到工具校验失败，见
                        #  `resolve_sms_code` 的实证说明）。没有真值时不动模型入参。
                        _known_code = (extract_sms_code(last_user_msg)
                                       or await _stored_sms_code(session_id))
                        _given_code = str((args or {}).get("sms_code") or "").strip()
                        _final_code, _why = resolve_sms_code(_known_code, _given_code)
                        if _final_code and _why:
                            args = {**args, "sms_code": _final_code}
                            logger.info(
                                f"[{skill_name}] 代码{_why} order_create.sms_code"
                                f"（{'本轮消息' if extract_sms_code(last_user_msg) else '会话记住的验证码'}）"
                                f"| session={session_id}"
                            )
                        elif _given_code and not _known_code and _is_customer_role(state):
                            # ── 没有真值 → 不许自造（issue #3434 第三种形态）──
                            # 实证（全量档 run 34789368315，OR-022 **首跑失败**）：脚本轮与实际卡序
                            # 错位后流程变噪，模型在**顾客还没给过任何码**时自己写了一个码去调
                            # order_create → 必然被工具拒（订单落库失败），只能靠重试捞回来。
                            # 短信只发到**顾客手机**上，模型"写一个"没有第二种结局 ——
                            # 唯一正确的下一步是**问顾客要码**，故这里拦下并给出这条路。
                            # 只对 C 端生效（分端纪律）：B 端店员代客下单的码来自线下沟通。
                            logger.warning(
                                f"[{skill_name}] 拦下**自造验证码**的 order_create"
                                f"（本会话没有任何已知的码）| session={session_id}"
                                f" given_len={len(_given_code)}")
                            return (tool_call,
                                    json.dumps({
                                        "success": False,
                                        "error": "sms_code_not_from_customer",
                                        "message": ("顾客**还没给过验证码** —— 请不要自己写一个："
                                                    "短信只发到顾客手机上，写错必然被拒、订单落不了库。"
                                                    "本轮正确的下一步是**向顾客要码**："
                                                    "回复里明确请顾客把收到的短信验证码发过来"
                                                    "（或先发确认卡让顾客点确认），拿到码之后再调用 order_create。"),
                                    }, ensure_ascii=False),
                                    {"success": False,
                                     "error": "sms_code_not_from_customer"})
                    if args is not tool_call.get("args"):
                        tool_call = {**tool_call, "args": args}
                    # ── 缺参等待期拦截（issue #3365，OR-017）──
                    # 顾客欠参数期间：不放行同一个写工具（注定失败）、不放行逐字重发的同一张
                    # 确认卡（死循环）。见 _write_input_recovery_block 的实证说明。
                    _blocked = await _write_input_recovery_block(
                        tool_name, args, tool_call, session_id, skill_name, last_user_msg)
                    if _blocked is not None:
                        return _blocked
                    _blocked2 = await _card_loop_block(
                        tool_name, args, tool_call, session_id, skill_name)
                    if _blocked2 is not None:
                        return _blocked2
                    # ── 掩码形态手机号拦截（issue #3386，DB 实证静默脏数据）──
                    # 在写工具真正执行**之前**：`13800008000` 这种"星号填 0"的形态能通过
                    # 11 位格式校验，一旦放行就是无告警的错号码落库。
                    # 只拦**写**工具：脏数据风险来自"用掩码值建单"，只读查询用掩码值只是
                    # 查不到，拦它反而多一轮往返。判据用 `tool.read_only`（`tool` 就在下面
                    # 解析 —— 放到解析之后，守卫内不再查 registry，避免"注册表拿不到工具
                    # → 静默放行"的假守卫）。
                    tool = skill_registry.get_tool(tool_name)
                    if tool is None:
                        logger.warning(f"[{skill_name}] Tool not found: {tool_name} | session={session_id}")
                        # ── 订单写工具跨 skill 缺失的恢复（issue #3976，P2）──
                        # 实证（sess_202d55d49a254a10）：product skill 内完成
                        # validate_input(order_create)+确认卡后，模型按执行提示调
                        # order_create → 本 skill 注册表没有 → tool_not_found →
                        # 旧逻辑只回失败，模型随后空头承诺「请稍候，我这就提交」、
                        # 订单永不落库。与转人工守卫（见下 :4300/:4328 同族）一致：
                        # 订单在办时 relock 到归属 skill（含确认卡归属迁移），
                        # 下一轮即走下单流程；话术给出**可执行**下一步（不得空头承诺）。
                        if tool_name == ORDER_WRITE_TOOL and await _order_flow_in_progress(
                                session_id, state, last_user_msg):
                            _relocked_this_round = True
                            await _relock_order_skill(session_id, state, migrate_card_owner=True)
                            _recover_msg = (
                                "订单流程已切换到订单模块，请再回复「继续」，我马上为您提交。"
                                if not _is_customer_role(state)
                                else "您的订单已确认，请再回复「继续」，我马上为您提交。")
                            return (tool_call,
                                    json.dumps({"success": False,
                                                "error": "tool_not_found_relocked",
                                                "message": _recover_msg},
                                               ensure_ascii=False),
                                    {"success": False, "error": "tool_not_found_relocked"})
                        return tool_call, json.dumps({"success": False, "error": "tool_not_found", "message": f"工具 {tool_name} 不可用"}, ensure_ascii=False), {"success": False}
                    # 数量口径产出层守卫（issue #3402）：顾客已报数量时不得给"用量/褶皱倍数"选项
                    _blocked_q = await _quantity_choice_block(
                        tool_name, args, tool_call, session_id, skill_name, state)
                    if _blocked_q is not None:
                        return _blocked_q
                    # 收货信息预填保真守卫（issue #3397）：interact 是只读工具，单独接。
                    _blocked_prefill = await _form_prefill_fidelity_block(
                        tool_name, args, tool_call, session_id, skill_name,
                        last_user_msg, state)
                    if _blocked_prefill is not None:
                        return _blocked_prefill
                    # 算料前提守卫（issue #3395）：只读工具，故在读写分流之前单独接。
                    _blocked_calc = await _curtain_calc_dimension_block(
                        tool_name, args, tool_call, session_id, skill_name, state)
                    if _blocked_calc is not None:
                        return _blocked_calc
                    if not getattr(tool, "read_only", False):
                        _blocked3 = await _masked_phone_write_block(
                            tool_name, args, tool_call, session_id, skill_name,
                            last_user_msg, state)
                        if _blocked3 is not None:
                            return _blocked3
                    # ── 兜底：C 端在办流程中禁止「无信号误转人工」（CH-012 实证）──
                    # R1 已下发选单卡、R3 用户仅回「质量问题」，agent 却 human_handoff
                    # （还创建了投诉工单）→ 流程被放弃、轮数耗尽、aftersale_create 未发生。
                    # 判据与 handoff_judge 同源：显式请求 / 负面情绪 / 能力外诉求 三者皆无
                    # → 不是用户要的转人工，而是模型放弃流程 → 阻止并给出可执行指引。
                    #
                    # 适用性判据（issue #3477 根治）：旧实现是 `skill_name in
                    # ("customer_order", "customer_aftersales")` 这一**字面量白名单** ——
                    # 会话被 choice 卡锁在 `customer_product` 时整段失效（C-A1 run 34791767013
                    # 实测：顾客「确认下单」→ 转人工照过、建了工单）。现在由
                    # `_handoff_guard_applies` 按**事实/状态**判定（见其 docstring）。
                    # ⚠️ 只在真是 human_handoff 时才查会话状态：本函数对**每个** tool 调用
                    # 都会跑，而下单流程本身就在办（必然有 pending 锁）→ 无条件查会白加 N 次存储往返。
                    _order_in_progress = (
                        await _order_flow_in_progress(session_id, state, last_user_msg)
                        if tool_name == "human_handoff" else False)
                    _denial_now = _capability_denial_reason(args)
                    if (tool_name == "human_handoff"
                            and _handoff_guard_applies(
                                skill_registry, order_in_progress=_order_in_progress,
                                denial_reason_hit=_denial_now)):
                        from app.graph.handoff_judge import has_escalation_signal
                        # 在办判据两条取并集（issue #3361 实证）：
                        #   ① 消息历史里能扫到未完结的交互卡（原实现）；
                        #   ② **跨轮持久化的 pending_interact_skill 非空** —— 这是
                        #      「流程锁定中」的权威标记（卡片发出即写、写操作成功即清），
                        #      不依赖 state["messages"] 是否带回上一轮的 ToolMessage。
                        # 为何 ② 必需（CI run 34689293179，CH-012）：R1 已下发选单卡、
                        # R2 顾客点明订单、R3 顾客只回退货原因「质量问题」，agent 直接
                        # human_handoff（并建了投诉工单）→ 流程被放弃、aftersale_create
                        # 未发生；当时 ① 判为 False（历史里扫不到那张卡）→ 兜底形同虚设。
                        _inflight = _flow_state_in_progress(state)
                        # 能力误宣（issue #3389）：以"我下不了单/无法代为提交订单"为理由转人工，
                        # 无论有没有在办卡都拦 —— 这是**能力否定**，不是顾客诉求。
                        _denial = _capability_denial_reason(args)
                        if _denial and not has_escalation_signal(last_user_msg):
                            # 能力误宣分域给话术（issue #3931）：商品图片域的理由用商品域纠正话术，
                            # 否则会把「设主图」诉求错引向 order_create（消息按域区分）。
                            _reason_img = (_product_image_denial_hit(str(args.get("reason") or ""))
                                           or _product_image_denial_hit(str(args.get("summary") or "")))
                            if _reason_img:
                                logger.warning(
                                    f"[{skill_name}] 拦截商品图片域能力误宣式转人工 | "
                                    f"session={session_id} reason={_reason_img!r}")
                                return (tool_call,
                                        json.dumps({"success": False,
                                                    "error": "handoff_blocked_capability_denial",
                                                    "message": _TEXT_DENIAL_CORRECTIVE_PRODUCT_IMAGE},
                                                   ensure_ascii=False),
                                        {"success": False,
                                         "error": "handoff_blocked_capability_denial"})
                            logger.warning(
                                f"[{skill_name}] 拦截能力误宣式转人工 | session={session_id} "
                                f"reason={_denial!r}")
                            _msg = (
                                f"你的转人工理由写的是「{_denial}」—— 但**你能下单**："
                                f"`order_create` 就是本流程的写工具（参数齐了就能真实落单）。"
                                f"「无法代为提交订单」属**能力误宣**：顾客明明要买，"
                                f"却被告知系统做不到，转化路径被自己掐断。"
                                f"正确做法：缺收货信息就先 `customer_address_query` 查历史地址，"
                                f"没有再发 `interact(component=form)` 或用自然语言问姓名/手机号/地址；"
                                f"参数齐了走 confirm 卡 → `validate_input` → `order_create`（含 sms_code）。"
                                f"只有当顾客**显式**要求人工、情绪激烈或诉求超出能力时，才允许转人工。")
                            if _order_in_progress and not _order_write_tool_here(skill_registry):
                                await _relock_order_skill(session_id, state,
                                                          migrate_card_owner=True)
                            return (tool_call,
                                    json.dumps({"success": False,
                                                "error": "handoff_blocked_capability_denial",
                                                "message": _msg}, ensure_ascii=False),
                                    {"success": False, "error": "handoff_blocked_capability_denial"})
                        # 补一条（issue #3421，C-A1 实证）：顾客**正在下单**且流程**已真实启动**
                        # （查过商品详情）时，即使没有待答卡片，无信号转人工也是放弃流程。
                        # 不这么做会漏掉 C-A1 的形态：卡片已被顾客点掉 → `_inflight` 为假 →
                        # 放行转人工 → 9 轮不下单（L1 违规 3 条）。
                        # 判据用**状态驱动**的 `_order_in_progress`（#3477）：旧写法
                        # `_has_ordering_intent(last_user_msg) and _order_flow_started(...)`
                        # 由**本轮措辞关键词**决定，顾客改说「好的，就按这个来」即失效。
                        if (not has_escalation_signal(last_user_msg)
                                and not _inflight
                                and _order_in_progress):
                            logger.warning(
                                f"[{skill_name}] 拦截「顾客在下单却无信号转人工」 | "
                                f"session={session_id} last_msg={last_user_msg[:30]!r}")
                            _msg2 = (
                                "顾客正在下单（本轮消息仍在推进下单），且本会话已经查过商品详情 —— "
                                "**不要转人工**：`order_create` 就是本流程的写工具，参数齐了就能真实落单。"
                                "缺收货信息就先 `customer_address_query` 查历史地址，没有再发 "
                                "`interact(component=form)` 或直接问；然后走 confirm 卡 → "
                                "`validate_input` → `order_create`（含 sms_code）。"
                                "只有当顾客**显式**要求人工、情绪激烈或诉求超出能力时，才允许转人工。")
                            if _order_in_progress and not _order_write_tool_here(skill_registry):
                                await _relock_order_skill(session_id, state,
                                                          migrate_card_owner=True)
                            return (tool_call,
                                    json.dumps({"success": False,
                                                "error": "handoff_blocked_inflight",
                                                "message": _msg2}, ensure_ascii=False),
                                    {"success": False, "error": "handoff_blocked_inflight"})
                        if not has_escalation_signal(last_user_msg) and _inflight:
                            logger.warning(
                                f"[{skill_name}] 拦截在办流程中的无信号转人工 | session={session_id} "
                                f"last_msg={last_user_msg[:30]!r}"
                            )
                            # 拦截话术必须**可执行**（issue #3361，CI run 34703192730 实证）：
                            # CH-012 R2/R3/R4 每轮都被拦（handoff_blocked_inflight ×3），
                            # 但模型只是**反复重试 human_handoff**、始终不调 aftersale_create
                            # → 流程原地打转、售后单永不创建（复现型红灯）。
                            # 原话术只说"请继续完成当前流程"，没点出**下一步该调哪个工具** ——
                            # 模型读到了"不许转人工"，却不知道"那该干什么"。
                            # 与确认门禁同一手法：把可执行动作（工具名）写进 tool result。
                            _flow_hint = ""
                            for _flow_tool, _hint in (
                                ("aftersale_create",
                                 "顾客是在办**售后**（退货/换货/退款/维修）：请先与顾客确认订单与原因"
                                 "（interact 卡），然后调用 aftersale_create 创建工单"
                                 "（order_id 用已查到的订单号）"),
                                ("order_create",
                                 "顾客是在办**下单**：请继续收齐信息并调用 order_create 完成下单"),
                            ):
                                try:
                                    if skill_registry.get_tool(_flow_tool) is not None:
                                        _flow_hint = _hint
                                        break
                                except Exception:
                                    continue
                            _msg = (
                                "顾客正在办理的业务尚未完成，且本轮消息没有要求转人工、"
                                "没有情绪激动、也不涉及赔偿/法律。**不要再次调用 human_handoff**，"
                                "继续完成当前流程。"
                                + (_flow_hint + "。" if _flow_hint else "请按交互卡与提示继续下一步。")
                                + "若顾客确实要求人工，需其明确说出「转人工/找人工/找客服」"
                                "后再调用本工具。"
                            )
                            return tool_call, json.dumps({
                                "success": False,
                                "error": "handoff_blocked_inflight",
                                "message": _msg,
                            }, ensure_ascii=False), {"success": False, "error": "handoff_blocked_inflight"}

                    # ── 下单接地闸门（issue #3361，OR-014 复现型红灯）──
                    # 实证：C 端「帮我下单，遮光窗帘 3 米，要打孔加工」时模型**一次都没查商品**
                    # （R1 tools=-），凭记忆发确认卡（金额 ¥95.4，而该商品真实单价 ¥168/米）
                    # 并直接下单 → 单价/加工项/金额全不可信，且用例期望的 product_detail 缺失。
                    # prompt 里的「商品详情铁律（confirm 前必须先调 product_detail）」模型不守，
                    # 故加代码闸门：本会话没成功查过商品详情 → 不许下单，并把可执行步骤写进结果。
                    # B 端（order）同守此闸门（run 34916256903 OR-014：B 端也查过详情但编造
                    # 分色价 150 落单）—— 未接地与单价不接地都是"金额不可信"的同族形态。
                    if tool_name == "order_create" and skill_name in ("customer_order", "order") and session_id:
                        _grounded = True
                        try:
                            from app.memory.session_state_store import SessionStateStore as _SG
                            _sg = await _SG().load(session_id) or {}
                            _grounded = bool(_sg.get("grounded_product_detail"))
                        except Exception as _ge:
                            logger.debug(f"[{skill_name}] ground gate check failed (non-fatal): {_ge}")
                        if not _grounded and skill_name == "customer_order":
                            logger.warning(
                                f"[{skill_name}] 下单接地闸门：本会话未查商品详情，拦截 order_create "
                                f"| session={session_id}"
                            )
                            # ── 接地自动驾驶（issue #3365 候选修法 1）──
                            # 实证：闸门拦下后模型**只是反复重试 order_create**（CI run 34707941520
                            # 里被拦 6 次仍不搜索），提示词与拦截话术都劝不动 → 属模型层不遵从。
                            # 代码层直接代跑 product_search → product_detail（**只读**），落接地标记，
                            # 并把查到的真实单价/商品 id 回给模型，让它基于真值重新下单。
                            # 只在"能确定唯一商品"时落地（多命中则把候选交回模型，不猜）。
                            _pilot = None
                            # 关键词来自**会话里对商品的提及**，而不只是本轮消息：
                            # 实证（CI run 34709584877）—— 被拦那一轮用户发的是「确认下单」/表单回传，
                            # 本轮抽不到商品词 → 自动驾驶根本没触发（order_create 仍被拦 5 次）。
                            # 取**最早**一次商品提及（顾客最初要买什么），比最近一次更稳。
                            _kw = extract_product_keyword(last_user_msg)
                            if not _kw:
                                try:
                                    for _m in (state.get("messages") or []):
                                        if not isinstance(_m, HumanMessage):
                                            continue
                                        _kw = extract_product_keyword(_extract_content(_m) or "")
                                        if _kw:
                                            logger.info(
                                                f"[{skill_name}] 接地自动驾驶：从会话历史取得商品关键词"
                                                f"'{_kw}' | session={session_id}"
                                            )
                                            break
                                except Exception:
                                    _kw = ""
                            if _kw:
                                try:
                                    _ps = skill_registry.get_tool("product_search")
                                    _pd = skill_registry.get_tool("product_detail")
                                except Exception:
                                    _ps = _pd = None
                                if _ps is not None and _pd is not None:
                                    try:
                                        _rs, _rd = await _execute_tool_safe(
                                            _ps, {"keyword": _kw}, tool_context, state)
                                        _prods = ((_rd.get("data") or {}).get("products")
                                                  if isinstance(_rd.get("data"), dict) else None) or []
                                        if isinstance(_prods, list) and len(_prods) == 1:
                                            _pid = _prods[0].get("id") or _prods[0].get("productId")
                                            if _pid:
                                                _ds, _dd = await _execute_tool_safe(
                                                    _pd, {"product_id": _pid}, tool_context, state)
                                                if _dd.get("success"):
                                                    _data = _dd.get("data") or {}
                                                    _pilot = {
                                                        "product_id": _pid,
                                                        "name": _data.get("name") or _prods[0].get("name"),
                                                        "price": _data.get("price"),
                                                    }
                                                    from app.memory.session_state_store import (
                                                        SessionStateStore as _SP)
                                                    _sp = await _SP().load(session_id) or {}
                                                    _sp["grounded_product_detail"] = {"product_id": _pid}
                                                    await _SP().commit(session_id, _sp)
                                                    logger.warning(
                                                        f"[{skill_name}] 接地自动驾驶：代跑 "
                                                        f"product_search('{_kw}')→product_detail 完成，"
                                                        f"接地标记已落 | session={session_id}"
                                                    )
                                    except Exception as _pe:
                                        logger.debug(f"[{skill_name}] 接地自动驾驶失败（回落到话术）: {_pe}")
                            if _pilot:
                                return tool_call, json.dumps({
                                    "success": False,
                                    "error": "product_not_grounded",
                                    "message": (
                                        f"下单被拦截，但**已代为查询商品**："
                                        f"{_pilot.get('name')}（product_id={_pilot.get('product_id')}，"
                                        f"单价 ¥{_pilot.get('price')}）。请基于该真实商品与单价"
                                        f"重新组织 items 并调用 order_create；"
                                        f"加工项/规格请用 product_detail 结果中的值，不要凭记忆填。"
                                    ),
                                }, ensure_ascii=False), {"success": False, "error": "product_not_grounded"}
                            return tool_call, json.dumps({
                                "success": False,
                                "error": "product_not_grounded",
                                "message": (
                                    "下单被拦截：本会话还没有**成功查询过商品详情**"
                                    "（价格/规格/加工项都无从确认）。请**立即**按顺序执行，"
                                    "**不要重复调用 order_create**（重复无效，这是硬性前置条件）：\n"
                                    "1) product_search(keyword=顾客提到的商品名) —— 顾客说"
                                    "「遮光窗帘 3 米」就用 keyword=\"遮光窗帘\"；\n"
                                    "2) product_detail(product_id=第 1 步选中的商品)；\n"
                                    "3) 拿到真实单价/加工项/规格后，按顾客确认的信息再下单。\n"
                                    "禁止凭记忆填价格或加工项。"
                                ),
                            }, ensure_ascii=False), {"success": False, "error": "product_not_grounded"}
                        # ── 单价接地校验（issue OR-014，run 34916256903 归因）──
                        # 已查过商品详情（grounded）但 items 单价 ≠ 库价（含编造的分色价）：
                        # 查详情 ≠ 金额可信 —— 规格卡上的「米白 ¥150/米」就是查完详情后编的。
                        # 拦截并回填库价（用 product_detail 结果里的真值，不写死任何金额）。
                        else:
                            try:
                                _pg = await _SG().load(session_id) or {}
                                _grounded_detail = _pg.get("grounded_product_detail") or {}
                                _price_err = unit_price_grounding_error(
                                    (args or {}).get("items") or [], _grounded_detail)
                                if _price_err:
                                    logger.warning(
                                        f"[{skill_name}] 单价接地校验拦截 order_create: {_price_err[:80]}"
                                        f" | session={session_id}"
                                    )
                                    return tool_call, json.dumps({
                                        "success": False,
                                        "error": "unit_price_not_grounded",
                                        "message": f"下单被拦截（单价与商品库不符）：{_price_err}",
                                    }, ensure_ascii=False), {
                                        "success": False,
                                        "error": "unit_price_not_grounded",
                                    }
                            except Exception as _pe2:
                                logger.debug(f"[{skill_name}] 单价接地校验失败（非致命）: {_pe2}")

                    # 写操作（destructive 或 requires_confirmation 高风险写）：必须经用户明确确认
                    # （代码层兜底，防间接提示注入驱动未确认写操作，审计 07 P0-L1）
                    # 豁免：action ∈ tool.read_only_actions 的纯只读调用（list/detail/tree 等）
                    # 卡片确认优先：用户消息**精确等于**最近确认卡的 confirmValue = 用户点了
                    # 确认按钮 → 最强确认信号，直接放行（长 confirmValue 过不了 24 字上限，
                    # 见 _is_card_confirm_value —— 不加这个，mini-app 点确认卡写操作永不落库）。
                    _card_confirmed = False
                    if _requires_confirmation(tool, args, last_user_msg):
                        try:
                            from app.memory.session_state_store import SessionStateStore
                            _store = SessionStateStore()
                            _full = await _store.load(session_id) or {}
                            _card_confirmed = _is_card_confirm_value(
                                last_user_msg, _full.get("last_confirm_value"))
                            if _card_confirmed:
                                # 记录「该写工具已获确认」：确认卡点击后，后续轮补充信息
                                # （如 customer 下单需 sms_code）不再重复要求确认。
                                # CI 实证（run 34682324499 诊断）：confirmValue 点击在上一轮，
                                # 本轮消息是验证码「123456」→ 未记录的话 order_create 被门禁拦。
                                _full["confirmed_write_tool"] = tool_name
                                await _store.commit(session_id, _full)
                                logger.info(
                                    f"[{skill_name}] 确认卡 confirmValue 精确匹配 → 放行写操作 "
                                    f"{tool_name} | session={session_id}"
                                )
                        except Exception as e:
                            logger.warning(f"[{skill_name}] card-confirm check failed (non-fatal): {e}")
                    _write_was_confirmed = False
                    if _card_confirmed is False and _requires_confirmation(tool, args, last_user_msg):
                        try:
                            from app.memory.session_state_store import SessionStateStore as _S3
                            _f3 = await _S3().load(session_id) or {}
                            _write_was_confirmed = _f3.get("confirmed_write_tool") == tool_name
                            if _write_was_confirmed:
                                logger.info(
                                    f"[{skill_name}] 写工具 {tool_name} 前轮已确认 → 放行 | session={session_id}"
                                )
                        except Exception as _e3:
                            logger.warning(f"[{skill_name}] confirmed_write_tool check failed (non-fatal): {_e3}")
                    if _requires_confirmation(tool, args, last_user_msg) and not _card_confirmed and not _write_was_confirmed:
                        logger.warning(
                            f"[{skill_name}] 拦截未确认的写操作 {tool_name} | session={session_id} "
                            f"last_msg={last_user_msg[:30]!r}"
                        )
                        # 诊断：为什么卡片确认没放行（stored 值 vs 本轮消息）
                        try:
                            from app.memory.session_state_store import SessionStateStore as _S2
                            _f2 = await _S2().load(session_id) or {}
                            logger.warning(
                                f"[{skill_name}] card-confirm 诊断: stored={str(_f2.get('last_confirm_value'))[:40]!r} "
                                f"msg={last_user_msg[:40]!r} equal={_is_card_confirm_value(last_user_msg, _f2.get('last_confirm_value'))} "
                                f"| session={session_id}"
                            )
                        except Exception as _e2:
                            logger.warning(f"[{skill_name}] card-confirm 诊断失败: {_e2}")
                        # ── 确认话术**唯一形态 = 确认卡**（交互形态统一，产品裁定 2026-09-14）──
                        # 历史（issue #3317）：这里曾按「本 Skill 是否绑 `interact`」分流 ——
                        # 没绑的（B 端 staff/settings/data）退化成"用文本完整复述并请用户口头确认"。
                        # 该处置**已被产品裁定推翻**（「写操作应该安全、交互形态要统一」），
                        # 处置改为**配置层统一**：staff/settings/data 补绑 `interact`
                        # （#3577 / PR #3590，squash 851e63ce），并由
                        # `tests/test_skill_config_registry.py` 的三条不变式机械守护
                        #   · `test_confirmed_write_tools_require_interact_in_same_skill`
                        #     （绑需确认写工具 → 必须绑 interact）
                        #   · `test_prompt_promising_confirm_card_requires_interact`
                        #   · interact 缺席台账（缺席必须写明只读理由）
                        # ⇒ **"无 interact" 的降级分支对全部已注册 Skill 已不可达**，故整段删除
                        #   （唯一还能触发门禁却不绑 interact 的 skill 不存在：只剩
                        #    knowledge/customer_knowledge 未绑，它们只有只读工具 → 门禁不会触发）。
                        # ⚠️ 不要重新引入按 skill 能力分流的话术分支：那会让"交互形态"再次不统一，
                        #   且新增 skill 会静默落进降级态 —— 正确做法是补绑 `interact`（配置层）。
                        #
                        # 可执行下一步（issue #3445）：CI 实测 `confirmation_required_no_card ×3`
                        # —— 模型**从没发过确认卡**就直接写单，被拦回后仍反复重试同一个写调用、
                        # 把轮数烧完（R10 时订单仍未落库）。故话术给出**唯一可执行的下一步**：
                        #   ① 明确"再调写工具没用"（防重试）；② 指明必须调 interact(confirm)；
                        #   ③ 回填**已校验参数**（pending_validated_input）与
                        #      **本次被拦调用的字段骨架**（它自己传过的值），让它照抄即可发卡。
                        _pending_hint = ""
                        try:
                            from app.graph.pending_validated import PENDING_KEY as _PK
                            from app.graph.pending_validated import is_pending_for as _is_pending
                            from app.memory.session_state_store import SessionStateStore as _S4
                            _f4 = await _S4().load(session_id) or {}
                            _pend4 = _f4.get(_PK) or {}
                            if _is_pending(_pend4, tool_name) and _pend4.get("params"):
                                _pending_hint = (
                                    " 已校验的参数（**原样**用作卡片 fields，不要改写）："
                                    + json.dumps(_pend4["params"], ensure_ascii=False,
                                                 default=str)[:400])
                        except Exception as _e4:
                            logger.warning(f"[{skill_name}] pending 参数回填失败（非致命）: {_e4}")
                        msg = (
                            f"工具 {tool_name} 是写操作（可能不可逆或产生数据变更），必须先向用户展示"
                            f"确认卡片并取得明确确认。**不要再次调用 {tool_name}** —— 在顾客点击"
                            f"确认卡之前它会被同样拦下、白烧一轮。本轮唯一的下一步是：调用 "
                            f"interact(component=confirm, fields=[…]) "
                            f"把将要执行的内容展示给顾客，等顾客**点击确认卡**之后再调用 {tool_name}。"
                            + _confirm_card_fields_hint(args)
                            + _pending_hint
                        )
                        # 归因细分（issue #3445）：保留 `confirmation_required` 前缀
                        # （既有断言按子串匹配），后缀说明**是哪一种**：
                        #   · _no_card          → 本会话从没发过确认卡（模型跳过确认直接写）
                        #   · _card_not_clicked → 发过卡，但这次回复不是卡值（顾客回文本/未点卡）
                        # 会话卡片证据取自**落库的会话状态**（issue #3750）：`state["messages"]`
                        # 里不会有跨轮 `interact` 的 ToolMessage（原因见 `_confirm_card_seen`），
                        # 只靠它会让细分码恒为 `_no_card`。
                        _card_state3 = {}
                        try:
                            from app.memory.session_state_store import SessionStateStore as _S6
                            _card_state3 = await _S6().load(session_id) or {}
                        except Exception as _e6:
                            logger.warning(f"[{skill_name}] 最近确认卡读取失败（非致命）: {_e6}")
                        _err3 = ("confirmation_required_card_not_clicked"
                                 if _confirm_card_seen(state.get("messages", []), _card_state3)
                                 else "confirmation_required_no_card")
                        if _err3 == "confirmation_required_no_card":
                            # 代码兜底（issue #3445）：本轮模型**从没发过确认卡**就写了单 ——
                            # 拦截话术已给"可执行下一步"，但实测它仍会跳过发卡（3 次复验 2 次命中）。
                            # 收尾时由代码把确认卡 XML 追加到回复文本（发射点在 chat.py 解析
                            # `<interact>` 块），顾客因此始终有点卡的入口。
                            _no_card_blocked_args = dict(args or {})
                        return tool_call, json.dumps(
                            {"success": False, "error": _err3, "message": msg},
                            ensure_ascii=False,
                        ), {"success": False, "error": _err3}
                    # ── 同轮重复写调用合并（issue #3361）──
                    # 模型有时在**同一次回复**里对同一个写工具发多次**完全相同**的调用
                    # （CI 实证 CH-010：一轮里 order_create ×3 → 2 次 tool_execution_failed、
                    # 1 次成功；幸而没变成 2 张订单，纯属运气）。
                    # 写工具刻意不走 60s 读缓存（重复的**非幂等写**不能被静默吞掉，见
                    # _execute_tool_safe 的注释）—— 但"同轮 + 同工具 + 同参数"不是新的写需求，
                    # 而是同一次意图的重复表达：合并为一次执行，其余复用同一结果。
                    # 与缓存的关键区别：作用域只有本轮（下一次回复即失效），参数不同不合并。
                    if not tool.read_only:
                        _dedupe_key = (tool_name, json.dumps(args, sort_keys=True, default=str))
                        _slot = _turn_write_slots.get(_dedupe_key)
                        if _slot is None:
                            _slot = _turn_write_slots[_dedupe_key] = {
                                "lock": asyncio.Lock(), "result": None}
                        async with _slot["lock"]:
                            if _slot["result"] is not None:
                                logger.warning(
                                    f"[{skill_name}] 同轮重复写调用已合并：{tool_name}"
                                    f"（同参数第 2+ 次，复用首次结果）| session={session_id}"
                                )
                                return tool_call, _slot["result"][0], _slot["result"][1]
                            result_str, result_dict = await _execute_tool_safe(
                                tool, args, tool_context, state)
                            _slot["result"] = (result_str, result_dict)
                    else:
                        result_str, result_dict = await _execute_tool_safe(tool, args, tool_context, state)
                    _executed_tools.add(tool_name)
                    if result_dict.get("success") and not getattr(tool, "read_only", False):
                        _write_ok = True
                    if not result_dict.get("success") and result_dict.get("suggestion"):
                        corrected = await _self_correct_retry(tool, args, tool_context, skill_name, result_dict, session_id, tenant_id, state)
                        if corrected:
                            result_str, result_dict = corrected
                    # ── 记住读到的**真实**手机号（issue #3386 写守卫的判据来源）──
                    # 只读工具读回来的号码是权威原文（写工具的入参可能是模型填的掩码变体，
                    # 若从写结果里学号码就等于让脏数据自我合法化，故只看只读工具）。
                    if (session_id and result_dict.get("success")
                            and getattr(tool, "read_only", False)):
                        try:
                            _payload = json.dumps(result_dict.get("data"),
                                                  ensure_ascii=False, default=str)
                            _found = raw_phones_in(_payload)
                            if _found:
                                await _remember_raw_phones(session_id, _found)
                            _addr = (result_dict.get("data") or {}).get("customer_address")
                            if _addr:
                                await _remember_known_value(
                                    session_id, KNOWN_ADDRESS_KEY, str(_addr))
                        except Exception as _e7:
                            logger.warning(f"[{skill_name}] 记录真实号码失败（非致命）: {_e7}")
                    # ── 落地"本会话已查过商品详情"标记（issue #3361 下单接地闸门用）──
                    # 只在成功时写；失败不写（避免"查了但没查到"被当成接地）。
                    # 同一张交互卡的下发计数（issue #3365）：第 3 次起会被 _card_loop_block 拦下。
                    # 必须在这里（而不是外层循环）计数 —— 只有这一层拿得到 `args`（外层只有
                    # result_dict，没有调用参数；首版写在外层，运行时 NameError 被吞成
                    # "计数失败（非致命）"，计数永远为 0 = 拦不住的假守卫）。
                    # 登记本轮已下发的**组件**（C 端同组件一张，issue #3445）：**成功才登记** ——
                    # 被校验拦下的 interact（如 fields 为空）不该消耗"这个组件的名额"，
                    # 否则模型第二次（这次是对的）调用会被误拦、顾客一张卡都收不到。
                    # 与 session_id 无关（会话缺失也不能让该守卫失效）。
                    if tool_name == "interact" and result_dict.get("success"):
                        _turn_card_components.add(str((args or {}).get("component") or ""))
                    if tool_name == "interact" and result_dict.get("success") and session_id:
                        _fp_emit = card_fingerprint(args)
                        if _fp_emit:
                            try:
                                from app.memory.session_state_store import SessionStateStore as _S6
                                _s6 = _S6()
                                _f6 = await _s6.load(session_id) or {}
                                _c6 = _f6.get(CARD_EMIT_COUNTS_KEY) or {}
                                if not isinstance(_c6, dict):
                                    _c6 = {}
                                _c6[_fp_emit] = int(_c6.get(_fp_emit) or 0) + 1
                                _f6[CARD_EMIT_COUNTS_KEY] = _c6
                                await _s6.commit(session_id, _f6)
                                logger.info(
                                    f"[{skill_name}] 卡下发计数 {_c6[_fp_emit]} "
                                    f"({_fp_emit[:60]}) | session={session_id}"
                                )
                            except Exception as _e6:
                                logger.warning(f"[{skill_name}] 卡下发计数失败（非致命）: {_e6}")
                    if tool_name == "product_detail" and result_dict.get("success") and session_id:
                        try:
                            from app.memory.session_state_store import SessionStateStore
                            _gs = SessionStateStore()
                            _g = await _gs.load(session_id) or {}
                            # 接地快照含**库价真值**（price + skus，issue OR-014）：
                            # 下单单价校验（`unit_price_grounding_error`）以本快照为库价来源 ——
                            # 只存 product_id 时校验无从比对（编造的分色价 150 对不上任何真值）。
                            # skus 扁平化只留校验所需键（color_name/sku_code/price），
                            # 不整包透传（防大 JSON 撑爆 session state）。
                            _g_data = result_dict.get("data") or {}
                            _g_skus = []
                            for _sk in (_g_data.get("skus") or []):
                                if not isinstance(_sk, dict):
                                    continue
                                _g_skus.append({
                                    "color_name": _sk.get("color_name"),
                                    "sku_code": _sk.get("sku_code"),
                                    "price": _sk.get("price"),
                                })
                            _g["grounded_product_detail"] = {
                                "product_id": str(_g_data.get("id") or ""),
                                "name": str(_g_data.get("name") or ""),
                                "price": _g_data.get("price"),
                                "skus": _g_skus,
                            }
                            await _gs.commit(session_id, _g)
                        except Exception as _e:
                            logger.debug(f"[{skill_name}] ground flag persist failed (non-fatal): {_e}")
                    return tool_call, result_str, result_dict

                # 同一条回复里每个**组件**的第一张卡才有名额：按位置预计算（并发 gather 下
                # 不能用"先检查后置位"的标志 —— 真实工具会 await I/O，两个协程会同时通过
                # 检查，实测变体即漏，issue #3445）。
                # 非 C 端不预计算（B 端不受这条守卫约束）。
                _card_allow: list[bool] = []
                if _is_customer_role(state):
                    _seen_in_reply: set = set()
                    for _ctc in (response.tool_calls or []):
                        if str(_ctc.get("name") or "") == "interact":
                            _cc = str((_ctc.get("args") or {}).get("component") or "")
                            _card_allow.append(
                                _cc not in _seen_in_reply and _cc not in _turn_card_components)
                            _seen_in_reply.add(_cc)
                        else:
                            _card_allow.append(True)
                else:
                    _card_allow = [True] * len(response.tool_calls or [])
                tool_results = await asyncio.gather(*[
                    _run_one_tool(tc, allow_card=_card_allow[_i])
                    for _i, tc in enumerate(response.tool_calls)])

                # ── 模式 C 代码兜底：加工项漏问 → confirm 卡改写为加工项 choice 卡（OR-017）──
                # 仅作用于 C 端下单/售后写流程：这些 Skill 的商品详情含加工项数据、
                # 且业务铁律要求 confirm 前必须先问。B 端流程不动。
                if skill_name in ("customer_order", "customer_aftersales"):
                    try:
                        _proc_msgs = new_messages + state.get("messages", [])
                        _proc_pid = _last_product_id(_proc_msgs)
                        # 跨轮已问过（同一商品）→ 不再改写：否则模型的 confirm 卡会被无限
                        # 改写成同一张加工项卡，confirm 永远落不了地（OR-017 实测 4 次）。
                        _proc_asked = await _processing_items_already_asked(session_id, _proc_pid)
                        plan = None if _proc_asked else _plan_processing_items_rewrite(tool_results, _proc_msgs)
                        if plan is not None:
                            idx, choice_data = plan
                            _tc, _rs, rd = tool_results[idx]
                            rd = dict(rd)
                            rd["data"] = choice_data
                            rd["message"] = f"已展示{choice_data['title']}（代码兜底：LLM 漏问加工项，confirm 卡改写为 choice 卡）"
                            result_str_new = json.dumps(rd, ensure_ascii=False, default=str)
                            tool_results[idx] = (_tc, result_str_new, rd)
                            logger.info(
                                f"[{skill_name}] 加工项漏问兜底：confirm 卡改写为加工项 choice 卡 "
                                f"(options={len(choice_data['options'])}) | session={session_id}"
                            )
                        # 记账：本轮任何一张加工项卡发出去过（改写来的或模型自己发的）→ 记「已问过」
                        if any(
                            (rd or {}).get("success")
                            and str((rd or {}).get("data", {}).get("component") or "") == "choice"
                            and _is_processing_items_card((rd or {}).get("data") or {})
                            for _tc, _rs, rd in tool_results
                        ):
                            await _mark_processing_items_asked(session_id, _proc_pid)
                    except Exception as e:
                        logger.warning(f"[{skill_name}] processing-items fallback failed (non-fatal): {e}")

                # ── 模式 C 代码兜底（B 端**建品**同构，issue #3320）──
                # 上面那条只覆盖 C 端（数据源是 product_detail）；B 端建品时商品还没建出来，
                # 事实源只有本会话真实调用过的 `processing_item_query` 返回。
                # 仅当「建品在办 + 有真实加工项 + 未问过」才把 confirm 卡改写为多选卡；
                # 其余形态（其它 action / 没查过 / 已问过 / 已答过 / 用户拒绝）一律**原样不动**。
                if skill_name == "product":
                    try:
                        _bp_msgs = new_messages + state.get("messages", [])
                        if await _b_create_processing_items_not_asked(session_id):
                            _bp_plan = _plan_b_create_processing_items_rewrite(tool_results, _bp_msgs)
                            if _bp_plan is not None:
                                _bp_idx, _bp_choice = _bp_plan
                                _bp_tc, _bp_rs, _bp_rd = tool_results[_bp_idx]
                                _bp_rd = dict(_bp_rd)
                                _bp_rd["data"] = _bp_choice
                                _bp_rd["message"] = (
                                    f"已展示{_bp_choice['title']}"
                                    "（代码兜底：建品漏问加工项，confirm 卡改写为多选 choice 卡）")
                                tool_results[_bp_idx] = (
                                    _bp_tc, json.dumps(_bp_rd, ensure_ascii=False, default=str), _bp_rd)
                                logger.info(
                                    f"[{skill_name}] 建品加工项漏问兜底：confirm 卡改写为 choice 卡 "
                                    f"(options={len(_bp_choice['options'])}) | session={session_id}")
                            # 记账：本轮任何一张加工项卡发出去过（改写来的或模型自己发的）→ 记「已问过」。
                            # 必须与改写分支**并列**（原先嵌在 `if _bp_plan is not None` 内）：
                            # 模型**自己**发卡时 `_bp_plan` 为 None ⇒ 原先不记账 ⇒ 本会话后续轮次的
                            # confirm 卡会被兜底重问一遍，正是 PR-014 data_check「未再次询问加工项」要防的形态
                            # （与 C 端 OR-017 的"同一件事问第二遍"同族）。判据未变，只调记账时机。
                            if _has_processing_choice_in_turn(tool_results):
                                await _mark_processing_items_asked(session_id, "")
                    except Exception as e:
                        logger.warning(f"[{skill_name}] b-create processing-items fallback failed (non-fatal): {e}")

                for tool_call, result_str, result_dict in tool_results:
                    tool_name = tool_call["name"]
                    # 订单→物流链收口（issue #3799）判据③：记账本回合查到的**真实订单号**
                    # （只读 facts；类型不对就跳过——这条路径不该因为结果形状异常而炸掉主流程）
                    if tool_name == "order_query" and result_dict.get("success"):
                        _oq_data = result_dict.get("data")
                        if isinstance(_oq_data, dict):
                            for _o in (_oq_data.get("orders") or []):
                                _no = str((_o or {}).get("order_no") or "").strip() \
                                    if isinstance(_o, dict) else ""
                                if _no and _no not in _turn_order_nos:
                                    _turn_order_nos.append(_no)
                    # 记录 tool 结果到 ContextManager，跨 skill 共享
                    if session_id and result_dict.get("success"):
                        try:
                            from app.memory.context_manager import get_context_manager
                            mgr = get_context_manager()
                            mgr.record_tool_result(session_id, tool_name, result_dict)
                            await mgr.save(session_id)  # Redis 持久化
                        except Exception:
                            pass
                    # ── 确认-执行链状态（issue #3031）──
                    # validate_input 通过 → 持久化「已校验待执行」状态，下一轮确认时
                    # 直接执行写工具，不再从零重走 validate+interact（sess_50ff 三张 confirm 卡根因）。
                    if session_id and tool_name == "validate_input" and result_dict.get("success"):
                        try:
                            pending = extract_pending(tool_call.get("args") or {})
                            if pending:
                                from app.memory.session_state_store import SessionStateStore
                                store = SessionStateStore()
                                full = await store.load(session_id) or {}
                                full[PENDING_KEY] = pending
                                await store.commit(session_id, full)
                                logger.info(
                                    f"[{skill_name}] Pending validated persisted: "
                                    f"{pending['target_tool']}.{pending['target_action']} | session={session_id}"
                                )
                        except Exception as e:
                            logger.warning(f"[{skill_name}] pending_validated persist failed (non-fatal): {e}")
                    # 缺参失败 → 跨轮记账（下一轮注入索要指令 + 拦截重复动作，issue #3365）
                    # 清除只认**同一把工具**成功：product_search 之类只读工具成功不能清账，
                    # 否则欠参标记被顺手抹掉、下一轮又回到"重发卡 + 重复调用"的老路。
                    if session_id and tool_name != "validate_input":
                        _param = "" if result_dict.get("success") else missing_input_param(
                            result_dict.get("error") or "")
                        try:
                            from app.memory.session_state_store import SessionStateStore as _S5
                            _s5 = _S5()
                            _f5 = await _s5.load(session_id) or {}
                            _prev5 = _f5.get(WRITE_INPUT_ERROR_KEY) or {}
                            if _param and _param not in RECOGNIZABLE_INPUT_PARAMS:
                                _param = ""   # 判不出"已补齐"的参数不记账（否则永久锁死该工具）
                            if _param:
                                _f5[WRITE_INPUT_ERROR_KEY] = {
                                    "tool": tool_name,
                                    "param": _param,
                                    "error": str(result_dict.get("error") or ""),
                                    "message": str(result_dict.get("message") or ""),
                                }
                                await _s5.commit(session_id, _f5)
                                logger.info(
                                    f"[{skill_name}] 缺参记账 {tool_name}.{_param} | session={session_id}"
                                )
                            elif result_dict.get("success") and _prev5.get("tool") == tool_name:
                                await _s5.commit(session_id, _clear_write_input_error(_f5))
                                logger.info(
                                    f"[{skill_name}] {tool_name} 成功 → 清除欠参标记 | session={session_id}"
                                )
                        except Exception as _e5:
                            logger.warning(f"[{skill_name}] 缺参记账失败（非致命）: {_e5}")
                    # 写工具执行成功 → 清除对应「已校验待执行」状态与「已确认写工具」标记
                    # （闭环完成；否则后续同类写操作会在无新确认的情况下被放行）。
                    if session_id and result_dict.get("success") and tool_name != "validate_input":
                        try:
                            from app.memory.session_state_store import SessionStateStore as _S4
                            _f4 = await _S4().load(session_id) or {}
                            if _f4.get("confirmed_write_tool") == tool_name:
                                _f4.pop("confirmed_write_tool", None)
                                await _S4().commit(session_id, _f4)
                        except Exception as _e4:
                            logger.warning(f"[{skill_name}] confirmed_write_tool clear failed (non-fatal): {_e4}")
                    # 注意：不能依赖 result_dict["terminal"] —— after_sales_manage(create) 等
                    # B 端写工具不返回 terminal=True（仅 order_create/aftersale_create/human_handoff
                    # 有），依赖 terminal 会导致售后换货的 pending 执行成功后残留。
                    # 正确判定：pending.target_tool 匹配当前工具 + 执行成功 → 清除。
                    if session_id and result_dict.get("success") and tool_name != "validate_input":
                        try:
                            from app.memory.session_state_store import SessionStateStore
                            store = SessionStateStore()
                            full = await store.load(session_id) or {}
                            pending = full.get(PENDING_KEY)
                            if is_pending_for(pending, tool_name):
                                full.pop(PENDING_KEY, None)
                                await store.commit(session_id, full)
                                logger.info(
                                    f"[{skill_name}] Pending validated cleared after {tool_name} | session={session_id}"
                                )
                        except Exception as e:
                            logger.warning(f"[{skill_name}] pending_validated clear failed (non-fatal): {e}")
                    # T2 事务终态：terminal 工具成功后重置当前域上下文（草稿/实体/待确认）
                    if session_id and result_dict.get("success") and result_dict.get("terminal"):
                        try:
                            from app.memory.context_manager import get_context_manager
                            mgr = get_context_manager()
                            mgr.reset_domain(session_id, skill_name)
                            await mgr.save(session_id)
                            logger.info(
                                f"[{skill_name}] Terminal tool {tool_name} — domain context reset | session={session_id}"
                            )
                        except Exception as e:
                            logger.warning(f"[{skill_name}] Terminal reset failed | session={session_id} error={e}")
                    new_messages.append(ToolMessage(content=result_str, tool_call_id=tool_call["id"], name=tool_name))
                    if tool_name == "interact" and result_dict.get("success"):
                        try:
                            await SessionMemory().set_pending_skill(session_id, skill_name)
                        except Exception:
                            pass
                        # 记录最近一次确认卡的 confirmValue（会话状态）：下一轮用户点击
                        # 回传的正是这个值 —— 精确匹配它 = 显式确认（见 _is_card_confirm_value）。
                        # 否则长 confirmValue（工具描述强制含上下文）过不了 24 字上限，
                        # 写操作永不落库（run 34678939564 + DB 审计实证假绿）。
                        # 同处记 `last_confirm_skill`（#3557）：路由层靠"本 skill 自己发的卡"
                        # 判定答卡轮（否则卡值里的跨域词会把会话甩到别的 skill）。
                        # 并**同时**记下最近一张卡整体（任意 component，含 choice / form）
                        # —— 路由层的答卡轮豁免此前只覆盖 confirm 卡，于是
                        # 「已选加工项：纳米圈打孔 · ¥9.5/米」这类系统自产的 choice 卡答卡值
                        # 被 L1 规则表（关键词「加工项」→ product_inquiry）当成话题切换，
                        # 清掉会话锁 → 落到 product skill（无 order_create）→ 零工具拒答
                        # （run 34841029062 OR-015 R4/R5、OR-016 R2 实证）。
                        try:
                            _data = result_dict.get("data") or {}
                            _component = str(_data.get("component") or "")
                            if _component:
                                from app.memory.session_state_store import SessionStateStore
                                _store = SessionStateStore()
                                _full = await _store.load(session_id) or {}
                                _full["last_card"] = _data
                                _full["last_card_skill"] = skill_name
                                if _component == "confirm" and _data.get("confirmValue"):
                                    _full["last_confirm_value"] = str(_data["confirmValue"])
                                    _full["last_confirm_skill"] = skill_name
                                    logger.info(
                                        f"[{skill_name}] last_confirm_value 持久化: "
                                        f"{str(_data['confirmValue'])[:40]} | session={session_id}"
                                    )
                                await _store.commit(session_id, _full)
                        except Exception as e:
                            logger.warning(f"[{skill_name}] last_card persist failed (non-fatal): {e}")

                # ── 「顾客已确认却不动手」：一次纠正重试（issue #3445/#3477 类）──
                # 实测（run 34794687762 的 OR-024 首跑，`ai=` 让轨迹第一次可读）：
                # 顾客 R4「确认下单」、R5「确认」、R6/R7 给验证码，模型却 9 轮全在
                # product_detail/customer_address_query 打转，validate_input → order_create
                # **从未发生**。8.4 确认收口要求先有 pending（validate_input 跑过才写）——
                # validate_input 没跑 → 收口也救不了，只能靠重试碰巧捞回。
                # 判据（保守）：C 端 + 顾客本轮明确确认/推进下单 + 商品已接地 + 本轮
                # **没有实质推进**（无 validate_input/order_create/interact）→ 注入一次纠正。
                # interact 在等顾客回答不算空转（模型刚问了问题，等输入是正确行为）。
                if (not _stall_corrected and _is_customer_role(state)
                        and (_is_explicit_confirmation(last_user_msg)
                             or _has_ordering_intent(last_user_msg))
                        and await _order_flow_started(session_id, state)
                        and not _stall_has_progress(response.tool_calls)):
                    _stall_corrected = True
                    logger.warning(
                        f"[{skill_name}] 顾客已确认但本轮空转（无写/无 interact）→ 纠正重答"
                        f" | session={session_id} last_msg={last_user_msg[:20]!r}")
                    new_messages.append(SystemMessage(content=_STALL_CORRECTIVE))
                    continue
            else:
                # 达到 max_iterations — 不暴露 LLM 的半截思考，用友好兜底
                final_content = "抱歉，处理步骤较多，请稍后重试或换个简单的方式描述需求。"

    # ── 交回编排壳（原实现里这些变量在同一个函数作用域内直接可见）──
    # `new_messages` / `_executed_tools` 交回**对象本身**：第 8 节还要 append/add 到同一个
    # 容器（`result["messages"]` 是它、8.4 的防双单判据也读它）⇒ 不得复制、不得重建。
    # 另三个名（`PENDING_KEY` / `_executed_tools` / `last_user_msg`）在上面那个 `if` 里是
    # **条件绑定**（原第 3910 / 3937 / 3894 行）：原实现中「未进入该分支」时它们保持未绑定，
    # 8.4 的 `try` 首次引用即抛 `UnboundLocalError`、被 `except Exception` 吞掉 ⇒ 收口整体
    # 跳过且**不执行任何写**。跨函数后无法保留「未绑定」本身，故用 `UNBOUND` 哨兵如实带过
    # 边界（等价性论证见 `UNBOUND` 定义处）—— 不要「顺手」把它们初始化成 None/空容器：
    # 那会让 8.4 在「第 7 节本就没跑」的轮次里**真的去执行写**。
    try:
        _carry_pending_key = PENDING_KEY
    except UnboundLocalError:
        _carry_pending_key = UNBOUND
    try:
        _carry_executed_tools = _executed_tools
    except UnboundLocalError:
        _carry_executed_tools = UNBOUND
    try:
        _carry_last_user_msg = last_user_msg
    except UnboundLocalError:
        _carry_last_user_msg = UNBOUND
    return {
        "final_content": final_content,
        "new_messages": new_messages,
        "_no_card_blocked_args": _no_card_blocked_args,
        "_write_ok": _write_ok,
        "_relocked_this_round": _relocked_this_round,
        "PENDING_KEY": _carry_pending_key,
        "_executed_tools": _carry_executed_tools,
        "last_user_msg": _carry_last_user_msg,
    }
