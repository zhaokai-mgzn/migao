"""`execute_skill` 的 8.3b / 8.4 / 8.5 / 8.6 节 + 9 / 10 节。

**逐字搬迁**自 `base_skill.py`（issue #4049，源头是「关联 #4043」的 S3 条）：
补发确认卡兜底 / 确认-执行链代码侧收口 / 草稿态回复归一 / 返回值组装 / 跨轮
`pending_skill` 持久化。本文件的 `finalize_turn` 函数体 = 原第 5076~5283 行
**去掉一层缩进后的逐字副本**（含末尾 `return result`）：一个字符都没改，
只做机械重绑定 —— 函数头收拢入参。

⚠️ **import 方向是单向的**：本模块顶层 import `base_skill` 的模块级助手，而
`base_skill.execute_skill` 在**函数体内** import 本模块 —— 加载期只有一个方向。
理由、图示与「别整理这三行 import」的原因见 `app/graph/skills/execution/__init__.py`。
"""
from typing import Any, List

from app.graph.skills.base_skill import (
    AgentState, CREATION_SKILL_NAMES, SMS_GATED_WRITE_TOOLS, ToolMessage,
    _b_create_flow_confirm_eligible, _confirm_card_seen, _is_card_confirm_value, _is_customer_role,
    _is_explicit_confirmation, _should_code_close_loop, _stored_sms_code, build_confirm_interact_xml,
    build_tool_context, confirm_card_fields, confirm_value_for_fields, extract_sms_code,
    is_pending_for, normalize_draft_state_reply, resolve_sms_code,
)


async def finalize_turn(
    state: AgentState,
    skill_name: str,
    session_id: str,
    skill_registry,
    new_messages: List[Any],
    final_content: str,
    _no_card_blocked_args,
    _write_ok: bool,
    _relocked_this_round: bool,
    _executed_tools,
    PENDING_KEY,
    last_user_msg,
) -> dict:
    """8.3b~10 节：补卡兜底 → 确认-执行链收口 → 草稿态归一 → 返回值 → 跨轮持久化。

    末三个入参（`_executed_tools` / `PENDING_KEY` / `last_user_msg`）来自第 7 节，且可能是
    `react_turn.UNBOUND`（第 7 节那个 `if` 未执行 ⇒ 原实现里它们**未绑定**）。此时本条函数
    的 8.4 `try` 会在首次使用时抛错并被 `except Exception` 吞掉 —— 这正是原实现的形态
    （收口整体跳过、不执行任何写）。**不要**把 UNBOUND 归一成 None/空容器（见 `react_turn` 注释）。
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
    logger = _base.logger
    # ── 8.3b 代码兜底**补发确认卡**（issue #3445 / #3882）──
    # 实测（CI 三次 `confirmation_required_no_card`）：模型**从没发过确认卡**就直接写单，
    # 被门禁拦回后仍会跳过发卡（话术已给唯一可执行的下一步，3 次复验仍有 2 次命中）。
    # 卡片有两个发射点（`chat.py`）：`interact` 工具结果分支、以及解析回复文本里的
    # `<interact>` 块 ⇒ 这里把卡补进**文本**：顾客因此始终有点卡的入口，而不是
    # "卡在写单被拦、又没有卡可点"。
    # 覆盖范围（issue #3882）：原实现只对 `skill_name == "customer_order"`（C 端）生效，
    # B 端 skill（product/general 等）没有兜底 —— 模型同样会跳过发卡，客户侧却无卡可点、
    # 只能打字。放宽为**所有 skill**（C 端既有行为不回归；`confirmation_required_no_card`
    # 只可能来自需确认写工具，所有已注册写技能都已绑 interact —— 由
    # `tests/test_skill_config_registry.py` 的三条不变式机械守护，本文件确认门禁
    # 话术处的注释有完整说明）。
    # 硬约束（#3414 教训）：**只补卡、不放行写** —— 写仍必须等顾客点卡后由门禁放行；
    # 且仅在"本会话从未出现过确认卡"的形态下补（`card_not_clicked` 说明顾客没点，
    # 那时替他补卡等于替他做决定，不做）。
    if (_no_card_blocked_args
            and final_content and "<interact>" not in final_content
            # ⚠️ **本轮不许补第二张**（issue #3445 复现）：`interact` 工具路径自己也会发射
            # 交互卡（`chat.py` 的 `tool_name == "interact"` 分支），与"解析文本里的
            # `<interact>` 块"是**两个独立发射点**。实测形态（本地复现，同一轮）：
            #   ① 模型直接写单 → 门禁拦下（`no_card`）→ 记为待补卡；
            #   ② 模型在**后续迭代**里调 `interact(confirm)` → 工具路径发卡（顾客已看到）；
            #   ③ 收尾文本里没有 `<interact>` 块 → 这里再补一张 → **同轮两张重复卡**。
            # 判据取本轮 `new_messages`（本次 `execute_skill` 产生的消息）：它包含第 ② 步
            # 那个 `interact` 工具结果，能证明"本轮的卡已经发过了"。
            # 注意**不能**用会话级一次性标记：顾客后续改地址/数量时，新明细仍需要新卡。
            and not _confirm_card_seen(new_messages)):
        _bfields = confirm_card_fields(_no_card_blocked_args)
        if _bfields:
            _bvalue = confirm_value_for_fields(_bfields)
            # 标题按端适配（issue #3882）：C 端保持既有「请确认订单信息」；
            # B 端写技能（product/general 等）用通用标题 —— 下架/删加工项弹一张
            # "订单信息"卡只会让客户更困惑。
            _btitle = ("请确认订单信息" if skill_name == "customer_order"
                       else "请确认操作")
            final_content = final_content + "\n" + build_confirm_interact_xml(
                _btitle, _bfields, confirm_value=_bvalue)
            # ⚠️ **必须同时持久化该卡的 confirmValue**（否则卡是"死的"）：门禁放行写操作靠
            # `_is_card_confirm_value(last_user_msg, last_confirm_value)`（见本文件 :3119），
            # 而这个值原本只在 `interact` 工具路径里落库 —— 代码补的卡若不落，
            # 顾客点了也判"未确认"，最坏是"补卡→点了仍被拦→再补卡"的往返。
            try:
                from app.memory.session_state_store import SessionStateStore
                _bstore = SessionStateStore()
                _bfull = await _bstore.load(session_id) or {}
                _bfull["last_confirm_value"] = _bvalue
                # 同处记发卡 skill（#3557）：路由层的答卡轮判据需要"这张卡是谁发的"
                _bfull["last_confirm_skill"] = skill_name
                await _bstore.commit(session_id, _bfull)
            except Exception as _be:
                logger.warning(f"[{skill_name}] 补发卡的 confirmValue 落库失败（非致命）: {_be}")
            logger.info(
                f"[{skill_name}] 代码兜底补发确认卡（模型跳过确认卡）| "
                f"session={session_id} fields={len(_bfields)}")

    # ── 8.4 确认-执行链的**代码侧收口**（issue #3410，C-A1 实证）──
    # 实证（run 34758421478，C-A1 主路径）：顾客点了确认（回传系统自产的确认卡值），
    # 模型回「这就帮您提交~」，随后两轮顾客又说「确认下单」，模型答「都核对好啦」「还差最后一步」
    # —— **整场没有 order_create 调用**，订单永不落库、验收 L1 报「order_create 未调用」；
    # 同一剧本别的轮次却通过（模型碰巧动手）→ 间歇性失败。
    # 既有机制（`_inject_pending_validated`）只做到"注入执行提示"，**动不动手仍由模型决定**。
    # 这里把收口前移到代码：顾客已明确确认 + 存在已校验待执行写 + 本轮模型没调那个工具
    # → **代码直接执行**（同一条执行路径：同样的确认门禁状态、同样的验证码回填链），
    # 并用工具返回的 message 作为给顾客的回复（说真话，而不是"这就帮您提交"）。
    # 覆盖范围（2026-09-15 扩展，issue PR-016 / run 34916256903 归因）：
    #   · C 端（customer 角色）任意确认-执行链（原 8.4 范围）；
    #   · B 端**建品**（product_manage/create）：B 端此前**没有**任何确认后兜底 ——
    #     实证 PR-016 首跑：用户 R7 回传确认卡值，模型调 product_search 宣称
    #     「✅ 商品已创建成功！」而 product_manage 从未执行（no_success 指纹）；
    #     重试轮 R4/R5/R6 三张同事实 confirm 卡不收敛。B 端其它写流程（update/
    #     toggle_status 等）仍由既有门禁 + 模型自觉，**不**在本收口范围（分端纪律，
    #     待各自有分支级回归证据后再评估）。
    if session_id:
        try:
            from app.memory.session_state_store import SessionStateStore as _S8
            _f8 = await _S8().load(session_id) or {}
            _pending8 = _f8.get(PENDING_KEY)
            _cv8 = _f8.get("last_confirm_value")
            _confirmed8 = (_is_explicit_confirmation(last_user_msg or "")
                           or _is_card_confirm_value(last_user_msg or "", _cv8))
            _target8 = str((_pending8 or {}).get("target_tool") or "")
            _b_create_ok = _b_create_flow_confirm_eligible(_pending8, _confirmed8)
            if not (_is_customer_role(state) or _b_create_ok):
                _pending8 = None  # 不在收口范围（B 端非建品流程）→ 不执行收口
            if _should_code_close_loop(_pending8, _target8, _confirmed8, _executed_tools):
                _tool8 = skill_registry.get_tool(_target8)
                if _tool8 is not None:
                    _args8 = dict((_pending8.get("params") or {}))
                    # 只在该工具**确实声明了 action** 时才带 action（C 端 order_create 没有）
                    try:
                        _props8 = ((getattr(_tool8, "parameters", None) or {}).get("properties") or {})
                    except Exception:
                        _props8 = {}
                    if "action" in _props8 and _pending8.get("target_action"):
                        _args8.setdefault("action", str(_pending8["target_action"]))
                    # 验证码真值链（与门禁同源）：本轮消息里的码 → 会话记住的码；
                    # 模型/校验链留下的不一致值同样纠正（`resolve_sms_code`）。
                    if _target8 in SMS_GATED_WRITE_TOOLS:
                        _known8 = (extract_sms_code(last_user_msg)
                                   or await _stored_sms_code(session_id))
                        _final8, _why8 = resolve_sms_code(_known8, _args8.get("sms_code"))
                        if _final8 and _why8:
                            _args8["sms_code"] = _final8
                            logger.info(
                                f"[{skill_name}] 确认收口：代码{_why8} {_target8}.sms_code"
                                f" | session={session_id}")
                    _ctx8 = build_tool_context(state)
                    _str8, _res8 = await _execute_tool_safe(_tool8, _args8, _ctx8, state)
                    new_messages.append(ToolMessage(
                        content=_str8, tool_call_id=f"closure_{_target8}", name=_target8))
                    _executed_tools.add(_target8)
                    logger.info(
                        f"[{skill_name}] 确认收口：模型未发起写，代码执行 {_target8} "
                        f"success={bool((_res8 or {}).get('success'))} | session={session_id}")
                    _msg8 = str((_res8 or {}).get("message") or "").strip()
                    if _msg8:
                        final_content = _msg8
                    if (_res8 or {}).get("success"):
                        _write_ok = True
                    if (_res8 or {}).get("success") and is_pending_for(_pending8, _target8):
                        _f8.pop(PENDING_KEY, None)
                        await _S8().commit(session_id, _f8)
        except Exception as _e8:
            logger.warning(f"[{skill_name}] 确认收口失败（非致命，交回模型）: {_e8}")

    # ── 8.5 这里**刻意不做** C 端回复脱敏（issue #3386：曾经做过，是错的）──
    # 首版在此处 `mask_pii(final_content)`，理由是"验收剧本里 AI 回显了完整手机号"。
    # 但 `final_answer` 同时是 `_agent_stream_to_sse` 里 `full_response.append(clean)`
    # 的来源 —— 也就是 `save_message` 落库的 assistant 消息、模型**下一轮读到的自己的历史**。
    # 于是：R5 脱敏 `13800138000` → `138****8000` 落库 → R7 模型读到残缺值，
    # 把 `****` 填成 `0` 得到 `13800008000`（11 位纯数字，`order_create` 的格式校验放行）
    # → 订单 `20260913384380002` 落库手机号就是 `13800008000`，**静默脏数据**：
    # 顾客收不到短信与配送联系（DB 实证见 issue #3386）。
    # 正确分界：**记忆/落库保原文，脱敏只做在出站展示层** ——
    # SSE 文本/卡片在 `app/api/chat.py` 的 `_mask_for_customer` / `_mask_card_for_customer`，
    # C 端 `GET /history` 回放在 `app/api/chat.py::get_history`。
    # 另有一层兜底：模型若真把掩码值填回写工具，`_masked_phone_write_block` 会拦下并回放真号。

    # ── 8.6 草稿态回复归一（issue #3750）──
    # 判据（保守，四条同时成立才动文本；任一不成立就一字不改）：
    #   ① C 端 + 下单域 Skill（与 8.3b 同域；B 端写流程各异，不在此列）；
    #   ② 存在「已校验待执行」的写（`validate_input` 通过后落库的 `pending_validated_input`，
    #      写成功后由本文件 `:3915` 清除 ⇒ 已闭环的轮次自动不在范围内）；
    #   ③ 该写**还没被顾客确认**（`confirmed_write_tool != target`）。点卡/文本确认的轮次由
    #      `_inject_pending_validated`（`:2742-2751`）在**开轮前**就记下放行标记 ⇒
    #      "已确认、正在等验证码"这一正常形态**不会**被误归（否则会把"请输入短信验证码"
    #      这句**必要**引导也删掉，反倒造出真死锁）；
    #   ④ 本轮没有任何写工具成功（成功即闭环，回复该说"订单已提交成功"）。
    # 命中后只改**回复文本**：完成/变更态措辞 → 草稿态；去掉验证码诉求句（唯一下一步＝点卡）。
    # ⚠️ 不放行任何写调用（#3414），确认门禁与 `:3614` 的拦截逻辑一字不动。
    if (session_id and final_content and skill_name == "customer_order"
            and not _write_ok and _is_customer_role(state)):
        try:
            from app.memory.session_state_store import SessionStateStore as _S9
            _f9 = await _S9().load(session_id) or {}
            _pend9 = _f9.get(PENDING_KEY) or {}
            _target9 = str((_pend9 or {}).get("target_tool") or "")
            if _target9 and _f9.get("confirmed_write_tool") != _target9:
                _new9, _notes9 = normalize_draft_state_reply(final_content)
                if _notes9 and _new9 != final_content:
                    logger.info(
                        f"[{skill_name}] 草稿态回复归一（{_target9} 写未成功）："
                        f"{'；'.join(_notes9)} | session={session_id}")
                    final_content = _new9
        except Exception as _e9:
            logger.warning(f"[{skill_name}] 草稿态回复归一失败（非致命）: {_e9}")

    # ── 9. 返回值 ──
    result: dict[str, Any] = {"messages": new_messages, "final_answer": final_content, "skill_used": skill_name}

    # ── 10. 跨轮持久化 ──
    # creation_skills 覆盖所有「多轮引导写流程」的域：创建类流程在未完成前必须锁
    # pending_skill，否则用户后续轮补充信息时重新走完整路由被关键词误判跳域
    # （HR-005 角色创建、CU-003 客户打标签：staff/customer 此前缺失 → 引导漂移 + 能力误宣）。
    if skill_name in CREATION_SKILL_NAMES:
        success_markers = ("创建成功", "已创建", "下单成功", "工单已创建", "售后工单",
                          "账号已创建", "角色已创建", "标签已添加", "已更新", "已添加")
        cancel_markers = ("已取消", "已取消创建", "好的，已取消", "不创建了", "算了不买了")
        has_succeeded = any(kw in final_content for kw in success_markers)
        has_cancelled = any(kw in final_content for kw in cancel_markers)

        if has_succeeded or has_cancelled:
            try:
                await SessionMemory().set_pending_skill(session_id, None)
                logger.info(f"[{skill_name}] Flow complete, pending_skill cleared | session={session_id}")
            except Exception as e:
                logger.warning(f"[{skill_name}] Failed to clear pending_skill | session={session_id} error={e}")
        else:
            result["pending_interact_skill"] = skill_name
            try:
                # issue #3976（P3）：轮内 `_relock_order_skill` 已把 pending_skill
                # 迁到订单归属 skill 时，轮末**不得覆盖回本轮 skill** —— 否则恢复
                # 路径失效、下一轮短消息快捷路由仍走无写工具的 skill（DB 实证
                # sess_202d55d49a254a10：relock 写入 order 后被轮末 commit 覆盖回
                # product）。只在「本轮发生过 relock」时读回保留，不改变其它轮次语义。
                if _relocked_this_round:
                    _relocked_to = await SessionMemory().get_pending_skill(session_id) or ""
                    if _relocked_to:
                        result["pending_interact_skill"] = _relocked_to
                        skill_name = _relocked_to
                        logger.info(
                            f"[{skill_name}] 轮末保留 relock 的 pending_skill"
                            f" → {_relocked_to} | session={session_id}")
                await SessionMemory().set_pending_skill(session_id, result["pending_interact_skill"])
            except Exception as e:
                logger.warning(f"[{skill_name}] Failed to persist pending_skill | session={session_id} error={e}")

    return result
