"""`execute_skill` 的 0~6 节：防御层 / 上下文与工具 / 消息 / LLM / system prompt / 跨轮注入 / Vision。

**逐字搬迁**自 `base_skill.py`（issue #4049；拆分源头是「关联 #4043」的 S3 条 —— 原
`execute_skill` 是 1699 行单函数、内含 9 类职责 ⇒ 其余四个包只能串行改同一个文件）。
本文件的 `prepare_turn` 函数体 = 原第 3597~3888 行**去掉一层缩进后的逐字副本**：
一个字符都没改，只做机械重绑定 —— 函数头收拢入参、函数尾补一个 `return` 把
「之后还要用」的变量交回编排壳。

⚠️ **import 方向是单向的**：本模块顶层 import `base_skill` 的模块级助手，而
`base_skill.execute_skill` 在**函数体内** import 本模块 —— 加载期只有一个方向。
理由、图示与「别整理这三行 import」的原因见 `app/graph/skills/execution/__init__.py`。
"""
import asyncio
import time
from typing import Any, List

from app.graph.skills.base_skill import (
    AIMessage, AgentState, CircuitBreakerOpenError, HumanMessage,
    LLM_CALL_TIMEOUT_S, SystemMessage, VISION_CLARIFY_GUIDE, _build_system_prompt,
    _extract_content, _extract_intent_name, _inject_pending_validated, _inject_user_memories,
    _inject_user_preferences, _inject_write_input_recovery, _sanitize_messages_for_text_path, _track_llm_cost,
    _usable_vision_analysis, _vision_retry_needed, build_tool_context, has_images,
    llm_breaker_name,
)


async def prepare_turn(
    state: AgentState,
    skill_name: str,
    tool_names: List[str],
    system_prompt: str,
    execute_skill,
) -> dict:
    """0~6 节：防御层（速率/截断）→ 上下文与工具 → 消息 → LLM → system prompt → 跨轮注入/压缩 → Vision。

    `execute_skill` 作为参数传入只为**守住速率限制的状态锚点**：原实现把限流窗口挂在
    `execute_skill._rate_map` 这个**函数属性**上（下面三行逐字未改），拆出去后若改挂到
    `prepare_turn` 自己身上，就等于换了一个状态容器（进程内重启/重载语义、外部按
    `execute_skill._rate_map` 观察的路径都会静默失效）。故由编排壳把**它自身**传进来，
    按原样读写同一个属性。
    """
    # ── patch 点：下面这些名字必须**调用期**从 base_skill 取值（别改成模块顶层 import）──
    # 既有守卫用 `patch.object(base_skill, "<name>")` / `patch("app.graph.skills.base_skill.<name>")`
    # 给它们打桩（接缝清单由测试**机械提取**：tests/unit/test_execute_skill_split.py）。
    # 模块顶层 `from ... import <name>` 会把绑定**冻在 import 那一刻** ⇒ patch 静默失效
    #（本仓最忌讳的「判据自己选择沉默」）。拆分前这些名字是 base_skill 的模块全局、**调用期**
    # 解析；下面这几行恢复**同一解析时机**，语义与拆分前一致。
    # 机械守护：tests/unit/test_execute_skill_split.py::test_no_patch_seam_is_frozen_at_module_level
    from app.graph.skills import base_skill as _base
    LLMFactory = _base.LLMFactory
    create_skill_registry = _base.create_skill_registry
    get_breaker = _base.get_breaker
    call_with_retry = _base.call_with_retry
    get_skill_llm = _base.get_skill_llm
    logger = _base.logger
    set_tool_context = _base.set_tool_context
    raw_messages = state["messages"]
    session_id = state.get("session_id", "")
    tenant_id = int(state.get("tenant_id", 0) or 0)

    # ── 0. 防御层：输入/输出限制 ──
    MAX_USER_INPUT_LEN = 2000   # 单条用户消息最大字符数
    MAX_CONVERSATION_MSGS = 50  # 对话历史最大消息数
    # 速率限制：同 session 120 秒内最多 180 条消息（1.5条/秒）
    _RATE_WINDOW = 120
    _RATE_LIMIT = 180
    if session_id:
        now = time.time()
        key = f"rate:{session_id}"
        if not hasattr(execute_skill, '_rate_map'):
            execute_skill._rate_map = {}
        rm = execute_skill._rate_map
        if key not in rm:
            rm[key] = []
        rm[key] = [t for t in rm[key] if now - t < _RATE_WINDOW]
        if len(rm[key]) >= _RATE_LIMIT:
            logger.warning(f"[{skill_name}] RATE LIMITED: {len(rm[key])} msgs in {_RATE_WINDOW}s | session={session_id}")
            return {"messages": [], "final_answer": "请求过于频繁，请稍后再试。", "skill_used": skill_name}
        rm[key].append(now)
        if len(rm) > 200:  # 清理过期 session
            rm.pop(next(iter(rm)))

    # 截断超长输入
    if raw_messages and isinstance(raw_messages[-1], HumanMessage):
        content = getattr(raw_messages[-1], "content", "") or ""
        if isinstance(content, str) and len(content) > MAX_USER_INPUT_LEN:
            raw_messages[-1] = HumanMessage(content=content[:MAX_USER_INPUT_LEN] + "...")
            logger.warning(f"[{skill_name}] Input truncated: {len(content)}→{MAX_USER_INPUT_LEN} | session={session_id}")

    # 超过消息数上限时裁剪 + 友善提醒
    if len(raw_messages) > MAX_CONVERSATION_MSGS:
        raw_messages = list(raw_messages[-MAX_CONVERSATION_MSGS:])
        truncation_msg = (
            f"⚠️ 对话已达 {len(state.get('messages',[]))} 轮，历史记录已自动裁剪。"
            f"早期对话内容无法再被引用。建议新建会话以获得最佳体验。"
        )
        raw_messages.insert(0, SystemMessage(content=truncation_msg))
        logger.warning(f"[{skill_name}] History truncated: {len(state.get('messages',[]))}→{MAX_CONVERSATION_MSGS} msgs | session={session_id}")

    # 会话长度提示已移除（2026-09-08 sess_c1fce183dae24f22 复盘）：
    # 旧实现把「当前对话已持续 N 轮」提示拼入最新用户消息，污染确认守卫判定
    # （长度 >24 无法识别为确认 → 长会话写操作确认被反复拦截、死循环）。
    # 不再计算/拼接会话长度提示，用户消息原样保留。

    # ── 1. 上下文 & 工具准备 ──
    from app.memory.session_memory import SessionMemory  # noqa: F811 — 函数内多处使用
    # issue #3976：本轮是否发生过「订单写工具跨 skill 缺失」的 relock —— 必须在
    # ReAct 循环外初始化（循环内赋值使该变量成为闭包 cell；若 LLM 首轮即返回文本、
    # 循环体从未执行，第 10 步访问未绑定 cell 会抛
    # `cannot access local variable ... where it is not associated with a value`）。
    _relocked_this_round: bool = False
    tool_context = build_tool_context(state)
    set_tool_context(tool_context)
    skill_registry = create_skill_registry(tool_names)
    langchain_tools = skill_registry.get_langchain_tools()
    intent_name = _extract_intent_name(state)

    # ── 2. 消息准备 ──
    messages = state["messages"]
    is_multimodal = has_images(messages)
    if not is_multimodal:
        messages = _sanitize_messages_for_text_path(messages)
    text_length = sum(len(getattr(m, "content", "") or "") for m in messages) + len(system_prompt)

    # ── 3. LLM 准备 ──
    llm = get_skill_llm(intent=intent_name, tool_count=len(langchain_tools), text_length=text_length, messages=messages)
    llm_model_name = getattr(llm, "model_name", None) or getattr(llm, "model", "")

    llm_no_thinking = None
    if langchain_tools:
        # 与首轮 llm 使用同一模型，仅关闭思考（避免路由选型不一致）
        llm_no_thinking = LLMFactory.create_skill_llm(model_override=llm_model_name, force_no_think=True)
        llm_no_thinking = llm_no_thinking.bind_tools(langchain_tools)

    if is_multimodal:
        llm_with_tools = llm
    elif langchain_tools:
        llm_with_tools = llm.bind_tools(langchain_tools)
    else:
        llm_with_tools = llm

    # ── 4. System Prompt 组装 ──
    user_name_raw = state.get("user_name", "")
    user_role_raw = state.get("role", "")
    identity_prefix = ""
    if user_name_raw:
        user_name_safe = user_name_raw.replace("\n", " ").replace("\r", " ").strip()[:50]
        user_role_safe = user_role_raw.replace("\n", " ").replace("\r", " ").strip()[:50]
        identity_prefix += (
            "【用户信息】当前对话用户: " + user_name_safe
            + "（角色: " + user_role_safe + "）\n"
            "【用户信息结束】\n"
        )
    # 企业信息注入：对应管理后台「企业基础信息」中的公司名称设置（identity.md 的
    # 企业名是模板措辞，实际企业名以这里为准，多租户下不再张冠李戴）
    tenant_name_raw = state.get("tenant_name", "")
    if tenant_name_raw:
        tenant_name_safe = tenant_name_raw.replace("\n", " ").replace("\r", " ").strip()[:50]
        identity_prefix += (
            "【企业信息】你当前服务的企业是「" + tenant_name_safe + "」"
            "（即该企业商家管理后台的 AI 助手）。"
            "企业名称请以此处为准，介绍自己时使用「" + tenant_name_safe + "商家管理后台的 AI 助手」。\n"
            "【企业信息结束】\n"
        )
    if identity_prefix:
        system_prompt = identity_prefix + "\n" + system_prompt
    system_prompt = _build_system_prompt(skill_name, inline_prompt=system_prompt)

    # 4b. C 端长期记忆注入（issue #2815：仅 xiaobu；mibao 不注入）
    system_prompt = await _inject_user_memories(system_prompt, state)

    # 4c. 建议个性化偏好注入（issue #2997：flag 门控默认关闭；仅 xiaobu）
    system_prompt = await _inject_user_preferences(system_prompt, state)

    # 4d. 确认-执行链「已校验待执行」注入（issue #3031：确认轮直接执行写工具）
    # last_user_msg 需在此处可用：从 raw_messages 反向取最后一条 HumanMessage
    _confirm_msg = ""
    for _m in reversed(raw_messages):
        if isinstance(_m, HumanMessage):
            _confirm_msg = _extract_content(_m)
            break
    system_prompt = await _inject_pending_validated(system_prompt, state, _confirm_msg)
    # 4e. 写工具缺参等待期注入（issue #3365，OR-017）：顾客欠验证码等参数时，
    # 明令"索要参数、禁止重复调用、禁止重发同一张确认卡"——模型层不遵从是死循环的真因。
    system_prompt = await _inject_write_input_recovery(system_prompt, state, _confirm_msg)

    if is_multimodal:
        system_prompt = (
            "【图片理解能力已启用】您可以识别和分析用户上传的图片内容。\n"
            "当用户上传图片时，请：\n"
            "1. 仔细观察图片内容，识别其中的关键信息\n"
            "2. 根据用户的提问，结合图片内容给出准确回答\n"
            "3. 如果图片中包含可操作的信息，可以主动建议使用相关工具处理\n\n"
            + VISION_CLARIFY_GUIDE
            + "\n\n"
            + system_prompt
        )

    # ── 5. 跨轮上下文注入 ──
    cached_vision = ""
    if not is_multimodal and session_id:
        try:
            cached_vision = await SessionMemory().get_vision_analysis(session_id)
        except Exception as e:
            logger.warning(f"[{skill_name}] get_vision_analysis failed | session={session_id} error={e}")

    full_messages: List[Any] = []
    msg_list = list(messages)

    if cached_vision and msg_list:
        for i in range(len(msg_list) - 1, -1, -1):
            if isinstance(msg_list[i], HumanMessage):
                msg_list[i] = HumanMessage(content=(
                    f"[系统提示] 你上一轮已经完成了对用户图片的识别分析，结果如下。"
                    f"这是你自己的推理产物，请直接基于它回答用户问题：\n"
                    f"--- 图片分析 ---\n{cached_vision}\n--- 分析结束 ---\n"
                    f"--- 用户消息 ---\n{msg_list[i].content or ''}"
                ))
                break

    full_messages.extend(msg_list)
    # ── 5.5 跨 Skill 上下文注入 + 对话压缩 + 记录当前 skill ──
    ctx_text = ""
    compression_text = ""
    if session_id:
        try:
            from app.memory.context_manager import get_context_manager
            ctx_mgr = get_context_manager()
            await ctx_mgr.load(session_id)  # Redis 恢复
            # T1 主题域切换：先记录切换（异域时旧域实体标 stale），再更新当前 skill
            ctx_mgr.record_domain_switch(session_id, skill_name)
            ctx_mgr.set_last_skill(session_id, skill_name)
            ctx_text = ctx_mgr.build_context(session_id, skill_name)
            # 对话压缩：超过 20 条消息时只保留最近 12 条，其余生成摘要
            if len(msg_list) > 20:
                compression_text = await ctx_mgr.compress_conversation(session_id, msg_list, max_recent=12)
                if compression_text:
                    logger.info(f"[{skill_name}] Compressed conversation: {len(msg_list)}→12 msgs | session={session_id}")
                    msg_list = msg_list[-12:]  # 只保留最近 12 条
            if ctx_text:
                logger.info(f"[{skill_name}] Injected cross-skill context: {len(ctx_text)} chars | session={session_id}")
        except Exception as e:
            logger.warning(f"[{skill_name}] Context manager failed: {e} | session={session_id}")

    full_msg_parts = [system_prompt]
    if compression_text:
        full_msg_parts.append("\n" + compression_text)
    if ctx_text:
        full_msg_parts.append("\n" + ctx_text)
    full_messages.insert(0, SystemMessage(content="\n\n".join(full_msg_parts)))

    # ── 6. Vision 分支 ──
    new_messages: List[Any] = []
    final_content = ""
    _denial_corrected = False      # 文本级能力误宣只纠正一次（issue #3443）
    _stall_corrected = False       # 「确认却不动手」只纠正一次（issue #3445 类）
    _no_card_blocked_args = None   # 本轮"没发过确认卡就写单"被拦的参数（issue #3445 代码兜底）
    _write_ok = False              # 本轮是否有**写工具成功**（8.6 草稿态归一的前置，issue #3750）
    vision_analysis = ""

    if is_multimodal:
        if session_id:
            try:
                await SessionMemory().clear_vision_analysis(session_id)
            except Exception:
                logger.debug(f"[{skill_name}] clear_vision_analysis failed (non-critical) | session={session_id}")

        for vision_attempt in range(2):
            try:
                logger.info(f"[{skill_name}][DIAG] Vision LLM calling | attempt={vision_attempt+1}/2 session={session_id}")
                llm_breaker = get_breaker(llm_breaker_name(skill_name))

                async def _vision_invoke():
                    return await asyncio.wait_for(llm.ainvoke(full_messages),
                                                  timeout=LLM_CALL_TIMEOUT_S)

                response: AIMessage = await call_with_retry(lambda: llm_breaker.call(_vision_invoke))
                _track_llm_cost(response, model=llm_model_name, tenant_id=state.get("tenant_id"), session_id=session_id)
                vision_analysis = _extract_content(response) or (
                    response.content if isinstance(response.content, str) else str(response.content)
                )
                logger.info(f"[{skill_name}] Vision completed | len={len(vision_analysis)}")
                # issue #2914：vision 偶发输出只有概括、没有实体的弱分析（如"受图片分辨率限制…"）。
                # 空或弱分析重试一次；重试后仍弱则清空（不缓存、走兜底），防弱结果毒化会话后续轮次。
                if _vision_retry_needed(vision_analysis, vision_attempt):
                    logger.warning(
                        f"[{skill_name}] Vision returned degraded/empty analysis, retrying "
                        f"| attempt={vision_attempt+1}/2 session={session_id}"
                    )
                    continue
                break
            except CircuitBreakerOpenError:
                logger.error(f"[{skill_name}][SLS] Vision circuit_breaker_open | session={session_id}")
                vision_analysis = ""
                break
            except Exception as e:
                logger.error(f"[{skill_name}] Vision failed: {e} | session={session_id}")
                vision_analysis = ""
                break

        # 重试后仍弱 → 清空，不缓存不注入（防"你识别不出颜色?"拿到缓存的弱文本）
        if vision_analysis:
            vision_analysis = _usable_vision_analysis(vision_analysis)
            if not vision_analysis:
                logger.warning(f"[{skill_name}] Vision degraded after retry, discarding (no cache) | session={session_id}")

        if not vision_analysis:
            final_content = "抱歉，图片分析暂时无法完成，请用文字描述您的需求，我会帮您处理。"
        else:
            vision_context = (
                f"[图片分析结果]\n用户上传了图片，以下是图片中识别到的信息：\n{vision_analysis}\n"
                f"请严格基于以上分析结果和用户的原始问题，使用可用工具完成操作。不要编造图片中没有的信息。"
            )
            if session_id and vision_analysis:
                try:
                    await SessionMemory().set_vision_analysis(session_id, vision_analysis)
                except Exception as e:
                    logger.error(f"[{skill_name}] set_vision_analysis failed | session={session_id} error={e}")
                # 切片 C：vision 分析全文落上下文槽，跨 skill 召回「图=什么」（G10 收口）
                try:
                    from app.memory.context_manager import get_context_manager
                    ctx_mgr = get_context_manager()
                    ctx_mgr.record_vision_analysis(session_id, vision_analysis)
                except Exception as e:
                    logger.warning(f"[{skill_name}] record_vision_analysis failed | session={session_id} error={e}")

            messages = _sanitize_messages_for_text_path(list(messages))
            system_msg = SystemMessage(content=system_prompt)
            full_messages = [system_msg] + messages
            full_messages.append(SystemMessage(content=vision_context))

            text_length = sum(len(getattr(m, "content", "") or "") for m in messages) + len(system_prompt) + len(vision_context)
            llm = get_skill_llm(intent=intent_name, tool_count=len(langchain_tools), text_length=text_length, messages=messages, enable_thinking=True)
            llm_model_name = getattr(llm, "model_name", None) or getattr(llm, "model", "")

            if "processing_item_query" in tool_names:
                langchain_tools = [t for t in langchain_tools if t.name != "processing_item_query"]
                logger.info(f"[{skill_name}] Multimodal: hiding processing_item_query | {len(langchain_tools)} tools remain")

            if langchain_tools:
                llm_with_tools = llm.bind_tools(langchain_tools)
            else:
                llm_with_tools = llm

            llm_no_thinking = None
            if langchain_tools:
                llm_no_thinking = LLMFactory.create_skill_llm(model_override=llm_model_name, force_no_think=True)
                llm_no_thinking = llm_no_thinking.bind_tools(langchain_tools)

    # ── 交回编排壳 ──
    # 原实现里这些变量与第 7~10 节同处**一个函数作用域**，直接可见；拆开后必须显式交回。
    # `new_messages` / `raw_messages` 交回的是**对象本身**（第 7 节只 append/clear，第 8 节
    # 还要 append 到同一个 list ⇒ 不得复制、不得重建，否则返回值里的 messages 与卡片判据
    # /双单判据看到的是两个容器）。其余为不可变值或只读引用，按值交回即可。
    # `SessionMemory` 不在接口里：第 7/8 节各自 import（同一模块对象，无状态）。
    return {
        "raw_messages": raw_messages,
        "session_id": session_id,
        "tenant_id": tenant_id,
        "tool_context": tool_context,
        "skill_registry": skill_registry,
        "new_messages": new_messages,
        "is_multimodal": is_multimodal,
        "llm_model_name": llm_model_name,
        "llm_no_thinking": llm_no_thinking,
        "llm_with_tools": llm_with_tools,
        "intent_name": intent_name,
        "full_messages": full_messages,
        "vision_analysis": vision_analysis,
        "final_content": final_content,
        "_denial_corrected": _denial_corrected,
        "_stall_corrected": _stall_corrected,
        "_no_card_blocked_args": _no_card_blocked_args,
        "_write_ok": _write_ok,
        "_relocked_this_round": _relocked_this_round,
    }
