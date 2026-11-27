"""
聊天 API 路由（SSE 流式响应）

提供对话接口：
- POST /send: 发送消息并接收 SSE 流式响应
- POST /sessions: 创建新会话
- GET /sessions: 获取会话列表
- GET /history/{session_id}: 获取会话历史消息
"""

import asyncio
import json
import re
from types import SimpleNamespace
import time
import traceback
from typing import AsyncGenerator, Optional, List, Dict, Any, Union
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger

from app.api.schemas import (
    ChatSendRequest,
    ChatSessionCreate,
)
from app.api.response_models import make_response
from app.config import settings
from app.api.sse import SSEEvent
# 表单注入形态的**契约常量**（issue #5949）：入口注入与 `_card_accepts_answer` 的判据
# 必须引用同一个字符串，否则「入口注入的形态」与「判据认的形态」各写一份、谁改了都不红。
from app.graph.nodes import FORM_ANSWER_INJECT_PREFIX
from app.memory.session_memory import SessionMemory
from app.memory.user_memory import UserMemoryManager
from app.agents.customer_service_agent import (
    BaseAgent,
    AgentContext,
    get_agent,
)
from app.tools import ToolRegistry, get_tool_registry
from app.tools.base import CUSTOMER_ONLY_ROLES, ToolContext  # 角色口径单点（#4013 A10）
# 页面上下文（issue #5371 族 4）：route→真值源登记表 + **默认拒绝**的注入面
from app.context.page_registry import (
    build_page_context,
    render_page_context,
    strip_page_context_envelope,
)
# 主动新手引导（issue #5989 · P2）：route→功能登记表（复用 P1 真值源）+ 推送判定（纯函数）
from app.context.menu_navigator import build_proactive_push, is_legacy_proactive_tip
from app.utils.auth import get_current_user, UserIdentity
import app.utils.error_incident as _err_inc
# 内部路由清洗（issue #7236）：出站展示文案只写中文页面名，不得带前端路由
from app.utils.route_hygiene import strip_internal_routes
# 图片管线（URL 校验 / CDN 重写 / 文本提示）的**单一事实源**（issue #5321 包 1）：
# 这段规则原先是本文件的三个私有函数，页面入口（建品页 / 建单页）无法独立使用
# ⇒ 抽到 `app/vision/pipeline.py`，对话路径改为**调用它**（下面保留同名别名，
# 语义逐字不变、既有调用点与测试零改动）。两入口共用同一段代码 ⇒ 不会漂移。
from app.vision.pipeline import (
    image_url_hint as _image_url_hint,
    rewrite_image_url as _rewrite_image_url,
    validate_image_url as _validate_image_url,
)
# 同页填充的**安全日志摘要**（issue #5368 包 2）：只含 target/计数/键名 —— 值一律不进日志
from app.vision.deep_channel import log_summary


# ============ 切片单元（issue #8725 第三档）============
# 下列名字的**定义**已搬到同包单元；本模块只做**同名 re-export**：
#   ① 本文件内的调用点仍按**本模块全局名**查找 ⇒ `patch("app.api.chat.<name>")` 继续生效
#      （若把调用点也改到新模块，既有 patch 会变成**静默空跑** —— 那才是降判据）；
#   ② 外部 `from app.api.chat import <name>` 的 import 面零改动。
from app.api.chat_profiles import (  # noqa: F401  (re-export，见上)
    _get_user_nickname,
    _get_tenant_name,
    _generate_title_async,
    _extract_memories_async,
)
from app.api.chat_history import (  # noqa: F401  (re-export，见上)
    PERSIST_FAILED_MARK,
    _CODE_DEFECT_EXCS,
    _PERSIST_SUGGESTION,
    _report_persist_failure,
    _save_message_or_report,
    _history_user_text,
    _is_legacy_proactive_tip_row,
    _format_datetime,
    _guard_session,
    _raise_session_error,
    _convert_history_to_agent_format,
)
from app.api.chat_outbound import (  # noqa: F401  (re-export，见上)
    _detect_card_type,
    _should_send_card,
    _normalize_order_card_data,
    _card_payload,
    _mask_for_customer,
    _sanitize_outbound_text,
    _mask_card_for_customer,
    _CARD_ACTION_WORDS,
    _CARD_NOUNS,
    _CARD_WIDGET_NOUNS,
    _CARD_DELIVERED_VERBS,
    _CARD_ACTION_GAP,
    _CARD_POINT_RE,
    _CARD_GESTURE_RE,
    _CARD_ACTION_RE,
    _CARD_DELIVERED_RE,
    _CARD_DELIVERED_CONFIRM_RE,
    _CARD_GUARD_RE,
    _CARD_CLAIM_RE,
    _CARD_MISLEAD_RE,
    _has_card_claim,
    _rewrite_card_claims,
)
from app.api.chat_interact import (  # noqa: F401  (re-export，见上)
    _INTERACT_XML_RE,
    _extract_tag_value,
    _extract_tags,
    _parse_interact_xml,
    _strip_interact_xml,
    _parse_interact_block_or_report,
    _filter_products_by_reference,
)



def _to_agent_role(role: str) -> str:
    """将 JWT 角色映射为黄金策执行上下文角色。

    - C 端角色（customer/agent）→ customer（折叠，禁管理工具）；
    - 其余一律视为商户员工并保留原角色码（供 Tool.allowed_roles /
      required_permissions 判断）——包括 admin-api「角色管理」创建的任意自定义
      角色码（P1-C 修复：此前只认白名单 MERCHANT_STAFF_ROLES，自定义角色码
      被折叠成 customer 无法使用黄金策；admin-api 只给商户员工签发后台 JWT，
      工具级权限仍由 permissions claim 强控，放宽不会越权）。
    """
    if role in CUSTOMER_ONLY_ROLES:
        return "customer"
    return role

router = APIRouter()

# 会话空闲超时：由后台任务 _session_auto_close_loop 统一处理（main.py）
# send 路径不再做超时检测和会话轮换，仅拒绝已 closed 会话（409）
SESSION_IDLE_TIMEOUT_MINUTES = 240








# `_image_url_hint` / `_validate_image_url` / `_rewrite_image_url` 三个名字**已上移**到
# `app/vision/pipeline.py`（issue #5321 包 1，页面路径要复用同一段规则）——
# 本模块在文件头把它们 import 成同名别名，调用点与测试都无需改动。
# ⚠️ 不要再在本文件里重新实现一份：两入口各有一份必然漂移。






# ============ SSE 流生成器 ============



async def _pending_confirm_action(session_id: str) -> Optional[Dict[str, Any]]:
    """取会话里「已校验待执行」的写动作（`pending_validated_input`）。

    这是**补卡分支的严格 gating**：没有它就没有可确认的事实 ⇒ 不许造卡
    （键名/取值口径与 `base_skill` 一致：`target_tool` + `target_action` 双非空）。
    失败/无会话一律返回 None（fail-closed → 退回只改写）。
    """
    if not session_id:
        return None
    try:
        from app.graph.pending_validated import PENDING_KEY
        from app.memory.session_state_store import SessionStateStore
        full = await SessionStateStore().load(session_id) or {}
        pending = full.get(PENDING_KEY) or {}
        if not isinstance(pending, dict):
            return None
        if not (pending.get("target_tool") and pending.get("target_action")):
            return None
        return pending
    except Exception as e:
        logger.warning(f"[chat/card-claim] 读取待确认动作失败（退回只改写）: {e}")
        return None


async def _reissue_confirm_card(
    pending: Dict[str, Any], session_id: str, skill_name: str
) -> Optional[Dict[str, Any]]:
    """按待确认动作**真补一张确认卡**（issue #3967 缺口 2），返回 interactive 载荷。

    复用 base_skill 的既有机器（不复制平行实现）：
      `confirm_card_fields`（字段只回显已校验参数）→ `confirm_value_for_fields`
      （与门禁**同口径**的 confirmValue）→ `build_confirm_interact_xml`（生成 XML）→
      本文件既有的 `_parse_interact_block_or_report`（走**真解析器**，与模型自称发卡
      的路径同协议；解析失败同样留痕）。

    两条硬约束：
      1. **取不到字段就不补**（`fields` 为空 ⇒ `build_confirm_interact_xml` 返回 ""，
         绝不下发空卡）；
      2. **必须落 `last_confirm_value`（+ 发卡 skill）**（照 `base_skill` 8.3b 补卡段）——
         否则顾客点了卡也过不了确认门禁。
    """
    import json as _json

    from app.graph.skills.base_skill import (
        build_confirm_interact_xml,
        confirm_card_fields,
        confirm_value_for_fields,
    )

    fields = confirm_card_fields(pending.get("params") or {})
    if not fields:
        return None
    confirm_value = confirm_value_for_fields(fields)
    if not confirm_value:
        return None
    xml = build_confirm_interact_xml("请确认操作", fields, confirm_value=confirm_value)
    if not xml:
        return None
    payload = _parse_interact_block_or_report(xml, session_id=session_id)
    if not payload or not payload.get("component"):
        return None
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full = await store.load(session_id) or {}
        full["last_confirm_value"] = confirm_value
        # 同处记发卡 skill（#3557）：路由层的答卡轮判据需要"这张卡是谁发的"
        full["last_confirm_skill"] = skill_name
        await store.commit(session_id, full)
    except Exception as e:
        # 非致命：卡照发（门店/顾客至少有点卡入口），但留痕以便事后归因。
        # #4084：`last_confirm_value` 是**确认门禁**的比对值 —— 它没落库时顾客点了卡也过不了
        # 门禁，属"卡片态取证失真"的同族 ⇒ 归口到落库审计（incident 短码可聚合）。
        _report_persist_failure(
            exc=e, op="commit", source="chat.card_confirm_value", session_id=session_id,
        )
    logger.warning(
        f"[chat/card-claim] 文本声称发卡但本轮无卡 ⇒ 按待确认动作补发确认卡 "
        f"| session={session_id} tool={pending.get('target_tool')} "
        f"action={pending.get('target_action')} fields={len(fields)} "
        f"| payload={_json.dumps(payload, ensure_ascii=False)[:200]}"
    )
    return payload


async def _agent_stream_to_sse(
    agent: BaseAgent,
    message: Union[str, List[Dict[str, Any]]],
    context: AgentContext,
    chat_history: List[Dict[str, Any]],
    tool_registry: ToolRegistry,
    session_memory: SessionMemory,
    session_id: str,
    tenant_id: int,
    user_id: str,
    *,
    display_message: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    将 Agent 的流式输出转换为 SSE 事件
    
    这是一个桥接函数，负责：
    1. 调用 Agent 的流式对话方法（`app/agents/customer_service_agent.py` 的
       `graph.astream(initial_state, stream_mode="updates")` —— **节点级**更新，不是 `astream_events`）
    2. 将 Agent 输出转换为 SSE 事件
    3. Tool 调用由 LangGraph Skill 节点内部处理
    4. 根据 Tool 结果发送卡片事件
    5. 保存消息到数据库
    6. 后续问题建议由 LLM 在回复中自然生成
    """
    full_response = []
    tool_calls_info = []
    # 工具**执行结果**元信息（issue #4052，源自 #4043 C 组第 1 条）：与 `tool_calls_info`
    # **逐项对齐** —— `tool_results[i]` 说的是 `tool_calls_info[i]` 这次调用「成没成」。
    # 此前结果只在 SSE 里发给前端、从不落库 ⇒ 会话记录（metadata）分不出「调了 order_create」
    # 与「order_create 真落库了」，事后取证/回放只能看到「调用了谁」（#3361/#3778 的假绿面）。
    # 只落元信息三键（工具名 / 成败 / 错误码）：**不放** `result.data` 载荷与用户 PII
    # （metadata 会进历史回放），`error` 文本先过既有脱敏层 `_mask_for_customer`。
    tool_results_info: List[Dict[str, Any]] = []
    # 同名工具一回合可调多次 ⇒ 模型发起的调用按到达顺序**进队**，结果按同序**出队配对**
    # （生产端 `customer_service_agent.astream_chat` 按 ToolMessage 顺序补发 tool_result）。
    # 队列元素 = `tool_calls_info` 里的同一条记录（同一对象）。
    # 代码收口执行（base_skill 8.4，模型**没**发起调用而由代码执行，issue #3410/#3976）
    # 只有结果、没有 tool_call ⇒ 出队为空，结果照样落库，且不会挤掉别的调用的配对位。
    _pending_calls: Dict[str, List[dict]] = {}
    # LLM hallucinated <interact> XML block payload (issue #3036 / UI-032)
    last_interactive_payload = None
    # 本轮**真实发出**的卡型（去重、保序）→ 收尾 save_message(extra_metadata=…) 落
    # metadata.cards（issue #4016 A15）：展示卡此前完全不落库，导致「哪种卡被真实使用」
    # 无法统计、裁剪只能靠猜。与 interactive 同形：只在真发卡时写，无卡轮次不写键。
    emitted_card_types: List[str] = []
    _done_sent = False
    # B 端引用对齐（issue #3009 / case PR-018）：mibao 的 product_list 卡片
    # 延迟到文本生成后按引用过滤再发，避免「文本说 5 件、卡片列 20 件」两层皮
    pending_product_cards: List[Dict[str, Any]] = []
    agent_type = getattr(agent, "_agent_type", "xiaobu")

    try:
        # 发送加载状态
        yield SSEEvent.loading("正在思考...")
        logger.debug(f"[chat/send] _agent_stream_to_sse starting | session={session_id} tenant={tenant_id}")
        
        # 调用 Agent 流式对话（整体超时 120 秒，防止流永不关闭）
        # 注：使用 time.monotonic() deadline + asyncio.wait_for 实现兼容超时，
        #     比 asyncio.timeout()（Python 3.11+）更灵活地控制心跳间隔
        stream_timeout = 180  # 秒（P&E 多步骤需多次 LLM 调用）
        heartbeat_interval = 15  # 秒：心跳间隔，远小于 ALB 60 秒空闲超时
        timed_out = False
        deadline = time.monotonic() + stream_timeout
        feed_task: Optional[asyncio.Task] = None
        try:
            # 使用 Queue 解耦心跳与 agent 执行，避免 asyncio.wait_for 取消 async generator
            event_queue: asyncio.Queue = asyncio.Queue()

            async def _feed_agent_events():
                """在独立 Task 中运行 agent stream，将事件放入队列"""
                try:
                    async for resp in agent.astream_chat(message, context, chat_history):
                        await event_queue.put(("event", resp))
                except Exception as feed_err:
                    await event_queue.put(("error", feed_err))
                finally:
                    await event_queue.put(("done", None))

            feed_task = asyncio.create_task(_feed_agent_events())
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        # 整体超时
                        raise asyncio.TimeoutError()
                    # 单次等待时间取「心跳间隔」与「剩余总超时」较小值
                    wait_timeout = min(heartbeat_interval, remaining)
                    try:
                        msg_type, payload = await asyncio.wait_for(
                            event_queue.get(), timeout=wait_timeout
                        )
                    except asyncio.TimeoutError:
                        # 区分「心跳触发」和「整体超时」
                        if time.monotonic() >= deadline:
                            raise
                        # 心跳：保持 ALB 连接
                        yield SSEEvent.heartbeat()
                        logger.debug(f"[chat/send] Heartbeat sent | session={session_id}")
                        continue

                    if msg_type == "done":
                        break
                    elif msg_type == "error":
                        raise payload

                    response = payload

                    if response.type == "text":
                        # 文本回复（实时剥离 <think> 块，避免思考内容泄漏到前端）
                        if response.content:
                            import re as _re
                            clean = _re.sub(r"<think>[\s\S]*?</think>", "", response.content)
                            # LLM hallucinated <interact> XML block (issue #3036 / UI-032):
                            # 1) parse to interactive payload and emit SSE interactive event (same protocol as interact tool)
                            # 2) strip XML block from text regardless, prevent raw XML leaking to bubble
                            # issue #3959：解析失败必须留痕（此前「写残的块」被静默剥离 ⇒ 不发卡、零日志）
                            xml_payload = _parse_interact_block_or_report(clean, session_id=session_id)
                            if xml_payload:
                                last_interactive_payload = xml_payload
                                yield SSEEvent.interactive(
                                    xml_payload.get("component", ""),
                                    _mask_card_for_customer(xml_payload, context))
                            clean = _strip_interact_xml(clean)
                            if clean:
                                # ⚠️ 只脱敏/清洗**出站**（SSE），`full_response` 保持原值：
                                # 它是给**模型**看的上下文（下一轮还要用），脱敏会让模型
                                # 以为顾客号码不完整（run 34736385849 实证：反过来问顾客要号码）。
                                full_response.append(clean)
                                yield SSEEvent.text(_sanitize_outbound_text(clean, context))

                    elif response.type == "tool_call":
                        # Tool 调用通知（AgentExecutor 内部已处理执行）
                        if response.tool_calls:
                            for tc in response.tool_calls:
                                tool_name = tc.get("tool", "")
                                tool_input = tc.get("tool_input", {})
                                tool_calls_info.append({
                                    "tool": tool_name,
                                    "args": tool_input,
                                })
                                # 进配对队列（同一对象）：结果到达时按 FIFO 出队
                                _pending_calls.setdefault(tool_name, []).append(
                                    tool_calls_info[-1])
                                yield SSEEvent.tool_call(tool_name, tool_input)

                    elif response.type == "tool_result":
                        # Tool 执行结果（来自 LangGraph Skill 节点）
                        if response.tool_calls:
                            for tc in response.tool_calls:
                                tool_name = tc.get("tool", "")
                                result_dict = tc.get("result", {})
                                # issue #3976（P4）：未执行的调用（tool_not_found）不得
                                # 写进 metadata.tool_calls —— 工具根本没执行，记录它会让
                                # 评测/回放按 metadata 断言「调用了该工具」被**假绿**骗过
                                # （B 端实证 sess_202d55d49a254a10：最终消息 metadata 记录
                                # 了从未执行的 order_create，而订单实际未落库）。
                                _res_error = result_dict.get("error") if isinstance(result_dict, dict) else ""
                                # 本次结果配对的调用 = 同名调用队列的队首（无则说明是代码收口执行）
                                _queue = _pending_calls.get(tool_name) or []
                                _paired_call = _queue.pop(0) if _queue else None
                                if _res_error == "tool_not_found":
                                    # issue #4052：未执行的调用同样**不得**记成「执行结果」
                                    # （工具没执行，哪来的执行结果）；且剔除的是**与本次结果
                                    # 配对的那一次**同名调用（按到达顺序，不是最后一条）——
                                    # 否则同名多次调用时 tool_results 会与 tool_calls 错位，
                                    # 把「成了」配到那条**从未执行**的调用上。
                                    if _paired_call is not None:
                                        tool_calls_info.remove(_paired_call)
                                else:
                                    # issue #4052：执行过的调用 ⇒ 落「成没成」元信息。
                                    # success 只有**明确真值**才算 True（字段缺失/假值 ⇒ False）：
                                    # 宁可少报成功，不把「说不清」记成「成了」。
                                    _err_text = (_mask_for_customer(_res_error, context)
                                                 if isinstance(_res_error, str) else "")
                                    tool_results_info.append({
                                        "tool": tool_name,
                                        "success": bool(result_dict.get("success"))
                                        if isinstance(result_dict, dict) else False,
                                        "error": _err_text or None,
                                    })
                                yield SSEEvent.tool_result(tool_name, result_dict)

                                # 检查是否需要发送卡片（order 卡片自动归一化载荷）
                                card_type, card_data = _card_payload(tool_name, result_dict)
                                if card_type:
                                    if card_type == "product_list" and agent_type == "mibao":
                                        # B 端引用对齐：收集候选，等 LLM 文本生成后按引用过滤再发
                                        pending_product_cards.append(card_data)
                                        logger.info(
                                            f"[chat/card] Deferred product_list card | tool={tool_name} "
                                            f"candidates={len(card_data.get('products', []))}"
                                        )
                                    else:
                                        logger.info(
                                            f"[chat/card] Sending card | tool={tool_name} "
                                            f"type={card_type} data_keys={list(card_data.keys()) if isinstance(card_data, dict) else 'N/A'}"
                                        )
                                        yield SSEEvent.card(card_type, card_data)
                                        # 登记**真实发出**的卡型（A15 用量统计；放在 yield 之后
                                        # 使「落库 = 真发出」在代码顺序上也成立）
                                        if card_type not in emitted_card_types:
                                            emitted_card_types.append(card_type)

                                # 检查是否来自 interact 工具 → 发送交互式组件事件
                                # 与 LLM 幻觉 <interact> XML 分支同协议：把载荷写入
                                # last_interactive_payload，收尾 save_message(interactive=…)
                                # 才会持久化到 metadata（issue #3883 —— 此前工具路径只 emit
                                # SSE、不落库，刷新/重开会话卡片消失、interactive_answered
                                # 只读锁也无从标记）。
                                if tool_name == "interact" and result_dict.get("success"):
                                    data = result_dict.get("data", {})
                                    component_type = data.get("component", "")
                                    if component_type in ("choice", "confirm", "form"):
                                        last_interactive_payload = data
                                        yield SSEEvent.interactive(
                                            component_type,
                                            _mask_card_for_customer(data, context))

                                # ── 同页填充（issue #5368 包 2）：**瞬时**通道 ──
                                # 计划推给商家**当前页面**的表单（浏览器内存事件）：
                                # 不进 URL（access log / Referer）、不进浏览器历史、不进 localStorage。
                                # 🔴 **有意不登记进交互卡的持久化槽位**（收尾 `save_message(interactive=…)`）：
                                # 一旦登记，整张计划（订单侧含收货信息）就落进会话 metadata = PII 落盘。
                                # 日志只打安全摘要（target/计数/键名）——**值一律不进日志**。
                                # 判据：backend/ai-agent-service/tests/test_page_fill_channel.py
                                if tool_name == "image_recognize" and result_dict.get("success"):
                                    fill_plan = result_dict.get("data") or {}
                                    if fill_plan.get("component") == "page_fill":
                                        logger.info(f"[chat/page-fill] {log_summary(fill_plan)}")
                                        yield SSEEvent.page_fill(fill_plan)

                    elif response.type == "error":
                        # 错误（携带 traceback 诊断信息）
                        error_msg = response.content or "处理失败"
                        yield SSEEvent.error(error_msg)
                        return
            finally:
                if feed_task is not None and not feed_task.done():
                    feed_task.cancel()
                    try:
                        await feed_task
                    except (asyncio.CancelledError, Exception):
                        pass
        except asyncio.TimeoutError:
            timed_out = True
            tb = traceback.format_exc()
            logger.warning(
                f"[chat/send] Agent stream timed out after {stream_timeout}s | session={session_id}"
            )
            yield SSEEvent.error(f"响应超时({stream_timeout}s)，请重试")
        
        # 保存 assistant 消息（剥离 <think> 块后再存，避免思考内容
        # 膨胀 token 计数、挤占上下文预算、干扰后续轮次推理）
        import re
        assistant_content = "".join(full_response)
        assistant_content = re.sub(r"<think>[\s\S]*?</think>", "", assistant_content).strip()
        # 内部路由清洗在**写库前**（issue #7236）：历史回放读的是这一行 —— 清洗晚于落库
        # 就等于把路由原文永久写进会话记录（刷新/重开会话又上屏一次）。
        assistant_content = strip_internal_routes(assistant_content)
        if not assistant_content:
            # LLM 未生成文本回复，进行容错降级
            if tool_calls_info:
                assistant_content = "我已为您查询了相关信息，请查看上方的结果卡片。如需更多帮助请继续提问。"
            else:
                assistant_content = "抱歉，我暂时无法生成回复，请稍后重试或联系人工客服。"
            yield SSEEvent.text(_sanitize_outbound_text(assistant_content, context))

        # 超时/异常时清除 tool_calls 元数据，避免泄漏到前端
        # （#4052：tool_results 与 tool_calls **逐项对齐**，必须一起清 ——
        #   否则落库的结果条数多于调用条数，对齐关系失效）
        if timed_out:
            tool_calls_info = []
            tool_results_info = []

        # B 端引用对齐（issue #3009 / case PR-018）：文本生成后按引用过滤补发卡片。
        # 只有被 LLM 文本实际引用的商品才渲染；未引用任何商品 → 不发卡（宁可无卡，不误导）
        for card_data in pending_product_cards:
            kept = _filter_products_by_reference(assistant_content, card_data.get("products") or [])
            if kept:
                filtered_data = {**card_data, "products": kept}
                logger.info(
                    f"[chat/card] Sending reference-aligned product_list card | "
                    f"kept={len(kept)} total={len(card_data.get('products') or [])}"
                )
                yield SSEEvent.card("product_list", filtered_data)
                # 只记**真发出**的：被引用对齐丢弃的 pending 卡不算一次使用
                # （否则用量统计被「发了又被丢掉」的卡虚高，#4016 A15 口径）
                if "product_list" not in emitted_card_types:
                    emitted_card_types.append("product_list")
            else:
                logger.info(
                    f"[chat/card] Dropped product_list card (no product referenced in final text) | "
                    f"candidates={len(card_data.get('products') or [])}"
                )

        # 收尾守卫（issue #3929 → #4013 A7）：文本把顾客指向控件、但本轮**确实没卡**
        # ⇒ 客户侧无卡可点。判据主体 = 事实（本轮无交互载荷、也没调 interact）×
        # 意图（文本指向控件，见 `_has_card_claim`）。
        #
        # issue #3967（缺口 2）：用户真正要的是「弹出可点击的确认卡」，不是"改写话术"。
        # 旧行为只有 base_skill 8.3b 的补卡（仅在**写操作被确认门禁拦下**时触发），
        # 而实测那三次模型**压根没尝试写** ⇒ 门禁没拦 ⇒ 两条机制不组合、接缝无人兜底。
        # 故在此处补上接缝：命中 + 无卡 + **会话里存在待确认的已校验动作** ⇒ 真补卡
        # （gating 严格：无待确认动作 / 取不到字段 ⇒ 退回只改写，绝不凭空造卡）。
        _card_absent = (
            last_interactive_payload is None
            and not any(tc.get("tool") == "interact" for tc in tool_calls_info)
        )
        if _card_absent and _has_card_claim(assistant_content):
            _pending = await _pending_confirm_action(session_id)
            _reissued = (
                await _reissue_confirm_card(_pending, session_id, str(_pending.get(
                    "target_tool") or ""))
                if _pending else None
            )
            if _reissued:
                # 置 last_interactive_payload：收尾 save_message(interactive=…) 才会
                # 持久化到 metadata（issue #3883 —— 否则刷新/重开会话卡片又消失）
                last_interactive_payload = _reissued
                yield SSEEvent.interactive(
                    _reissued.get("component", ""),
                    _mask_card_for_customer(_reissued, context))
            else:
                _rewritten = _rewrite_card_claims(assistant_content)
                if _rewritten != assistant_content:
                    logger.warning(
                        f"[chat/card-claim] 文本指向控件但本轮未发卡，改写为纯文本确认指引 "
                        f"| session={session_id} tenant={tenant_id} "
                        f"| {assistant_content!r} -> {_rewritten!r}"
                    )
                    assistant_content = _rewritten
                    # 直播气泡里的声称话术是**边流式边发**的，收尾改写落库文本时用户已
                    # 看到「请点下方卡片」——追加一条 text 事件（并入同一条消息气泡末尾，
                    # done 之前），让直播侧也有可执行的下一步指引。
                    yield SSEEvent.text("（注：确认卡片未显示，请直接回复「确认」以继续）")
                else:
                    # 判据命中但**没有可改写的控件声称**（纯"点击选择/勾选加工项"类指令，
                    # 不含控件实物名词）且本轮无待确认动作 ⇒ 不动话术、也不追加"回复确认"
                    # 提示（那是错的下一步）—— 只留痕，不静默。
                    logger.warning(
                        f"[chat/card-claim] 文本指向控件但无可改写声称且无待确认动作，"
                        f"保持原文 | session={session_id} tenant={tenant_id} "
                        f"| {assistant_content!r}"
                    )

        # 保存消息到数据库（#4084：经落库单一策略点 —— 失败必留痕且归因到"落库"，
        # 超时保护仍在 helper 内；返回值 None = 没写进去，`done` 事件的 message_id 亦为 null）
        message_id = await _save_message_or_report(
            session_memory,
            source="chat.assistant",
            session_id=session_id,
            role="assistant",
            content=assistant_content,
            tool_calls=tool_calls_info if tool_calls_info else None,
            # 工具执行结果元信息（issue #4052）：与 tool_calls 逐项对齐
            tool_results=tool_results_info if tool_results_info else None,
            interactive=last_interactive_payload if last_interactive_payload else None,
            # 展示卡卡型落库（#4016 A15）：无卡轮次不写键，与 interactive 同形
            extra_metadata={"cards": emitted_card_types} if emitted_card_types else None,
            tenant_id=tenant_id,
        )

        # 异步提取用户记忆（fire-and-forget，不阻塞 SSE 流）
        # user_message 提取自 message 参数（可能为 str 或 list）
        # 记忆抽取 / 会话标题取**用户原话**（`display_message`）—— 不取注入了页面上下文的文本
        # （issue #7112：信封不该变成「用户记忆」或会话标题）。
        _text_source = message if display_message is None else display_message
        user_msg_text = _text_source if isinstance(_text_source, str) else (
            " ".join(p.get("text", "") for p in _text_source if isinstance(p, dict) and p.get("type") == "text")
        ) if isinstance(_text_source, list) else ""
        if assistant_content and user_msg_text:
            try:
                # 登记在途任务：会话关闭 flush 前会 drain 它们（issue #3357——
                # 关闭紧跟最后一轮时抽取尚未返回 → 候选为空 → 记忆静默丢失）。
                # 登记先于下方 done 事件发送，故客户端收到 done 时任务必已登记，
                # 「done 之后到达的关闭请求」一定能 drain 到它。
                from app.memory.extraction_tasks import register_extraction_task
                _mem_task = asyncio.create_task(
                    _extract_memories_async(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        user_message=user_msg_text,
                        assistant_reply=assistant_content,
                        session_id=session_id,
                        agent_type=getattr(agent, "_agent_type", "xiaobu"),
                    )
                )
                register_extraction_task(session_id, _mem_task)
            except Exception as mem_err:
                logger.warning(f"[chat/send] Memory extraction scheduling skipped: {mem_err}")
            # 自动生成会话标题（首条回复后）
            try:
                asyncio.create_task(
                    _generate_title_async(
                        session_id=session_id,
                        user_message=user_msg_text,
                        assistant_reply=assistant_content[:200],
                    )
                )
            except Exception as title_err:
                logger.debug(f"[chat/send] Title generation scheduling skipped: {title_err}")

        # 发送完成事件（始终发送，即使 save_message 失败或超时）
        _done_sent = True
        yield SSEEvent.done(session_id, message_id)

    except Exception as e:
        # issue #3810：SSE error 分支此前把 `处理失败: {类型}: {消息}` 原样推给用户 ——
        # 英文类名/内部字段/路径直接上屏，违反「面向低学历用户全中文、禁英文技术术语」
        # 的约定（#3707 族）。用户侧改为纯中文、且**有信息量**（说明这轮没成功、可以重试），
        # 不是"静默成功"也不是无信息量通用句；技术细节（类型/消息/traceback/会话/轮次/req）
        # 落日志并复用 #3809 的 `incident` 短码口径（同会话同异常同码，可 grep 聚合）。
        _err_inc.log_exception_audit(
            logger=logger,
            mark="[chat/send] Agent stream error",
            exc=e,
            session_id=session_id,
            extra=(f"tenant={tenant_id} user={user_id} "
                   f"req={_err_inc.current_request_id()}"),
        )
        yield SSEEvent.error("刚才这轮没成功，请您再说一次，我继续为您办理。")
    finally:
        # 仅在尚未发送 done 时补发，避免客户端收到重复 done 事件
        if not _done_sent:
            yield SSEEvent.done(session_id, None)
        logger.debug(f"[chat/send] SSE stream ended | session={session_id}")


# ============ 分页协议 ============

# __PAGE__ 协议白名单：仅允许只读查询工具，防止任意工具执行（审计 07 P0-L2）。
# ⚠️ 严禁加入任何含写/破坏性 action 的工具（product_manage/customer_manage/employee_manage
# 等管理类工具一律不得入列）——该路径直调 execute_tool、绕过 LLM 确认守卫。
_PAGE_WHITELIST = frozenset({
    "processing_item_query",
    "processing_items",
    "order_query",
    "customer_order_query",
    "product_search",
    "product_detail",
    "logistics_track",
    "customer_logistics_track",
    "aftersale_query",
    "knowledge_faq",
    "dashboard_stats",
})


def _page_action_allowed(tool_registry, tool_name: str, params: dict) -> bool:
    """翻页协议 action 级纵深校验（审计 07 P0-L2）。

    白名单工具若定义了 read_only_actions，请求中的 action/operation/op
    必须属于该只读集合，否则视为写操作拒绝（防未来白名单误加含写 action
    的工具后被 __PAGE__ 直调绕过确认守卫）。
    """
    tool = tool_registry.get_tool(tool_name)
    if tool is None:
        return False
    action = params.get("action") or params.get("operation") or params.get("op")
    read_only_actions = getattr(tool, "read_only_actions", None) or frozenset()
    if not action:
        return True
    if not read_only_actions:
        # 工具无只读 action 概念：由工具内部校验 action 合法性（如 aftersale_query 仅 list/detail）
        return True
    return action in read_only_actions

async def _handle_page_request(
    request: ChatSendRequest,
    tenant_id: int,
    user_id: str,
    current_user,
):
    """
    处理 __PAGE__ 翻页请求：解析工具名+参数，直接调用工具，绕过 LLM。

    消息格式：__PAGE__|tool_name|params_json
    例：__PAGE__|processing_item_query|{"keyword":"窗帘","page":2,"size":10}
    """
    session_memory = SessionMemory()
    tool_registry = get_tool_registry()

    # ── 安全校验：与 send_message 共用统一守卫（存在/租户/用户/closed + 刷新 last_activity）──
    from app.memory.session_service import SessionService
    session_service = SessionService(session_memory)
    session_id = request.session_id
    if not session_id:
        session_id = await session_memory.create_session(
            tenant_id=tenant_id, customer_id=user_id, title=None,
        )
    else:
        _session, _gate_error = await session_service.send_gate(
            session_id, tenant_id=tenant_id, user_id=user_id,
        )
        if _gate_error:
            _raise_session_error(*_gate_error)

    # 解析 __PAGE__ 消息
    try:
        _, tool_name, params_str = request.message.split("|", 2)
        params = json.loads(params_str)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"[page] Bad __PAGE__ message: {request.message[:100]}, error={e}")

        async def _bad_page_stream():
            yield SSEEvent.error("翻页请求格式错误，请重试")
            yield SSEEvent.done(session_id, None)
        return StreamingResponse(
            _bad_page_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    # 白名单校验：仅允许只读查询工具
    if tool_name not in _PAGE_WHITELIST:
        logger.warning(f"[page] Blocked non-whitelisted tool: {tool_name}")
        async def _blocked_stream():
            yield SSEEvent.error("不支持该操作的分页查询")
            yield SSEEvent.done(session_id, None)
        return StreamingResponse(
            _blocked_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    # 纵深防御（审计 07 P0-L2）：白名单工具也仅允许只读 action——
    # 若工具定义了 read_only_actions，请求的 action 必须属于该集合，否则拒绝。
    # 防未来白名单误加含写 action 的工具后被翻页协议直调绕过确认守卫。
    if not _page_action_allowed(tool_registry, tool_name, params):
        logger.warning(
            f"[page] Blocked write action on whitelisted tool: tool={tool_name} "
            f"params={params}"
        )
        async def _blocked_stream():
            yield SSEEvent.error("不支持该操作的分页查询")
            yield SSEEvent.done(session_id, None)
        return StreamingResponse(
            _blocked_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    logger.info(
        f"[page] Direct tool call | tool={tool_name} params={params} "
        f"session={session_id} tenant={tenant_id}"
    )

    async def _page_stream():
        # 本轮真实发出的卡型 → 落 metadata.cards（#4016 A15，与主流式路径同口径）
        page_card_types: List[str] = []
        # 保存用户的翻页消息（#4084：经落库单一策略点，且**移出**下面的工具 try）——
        # 旧形态把它跟在工具调用同一个 try 里，落库失败会被兜底成"工具执行失败/翻页查询失败"：
        # 归因错人（排查看错方向），顾客也被告知一件没发生的事。翻页是只读 UI 动作，
        # 合成标记（"查看第N页"）没写进去不该拦住这一页 ⇒ fail-open + 明确留痕。
        await _save_message_or_report(
            session_memory, source="page.user",
            session_id=session_id, role="user",
            content=f"查看第{params.get('page', '?')}页", tenant_id=tenant_id,
        )
        try:
            # paging is also a user reply -> old-page interactive marked answered
            _marker = getattr(session_memory, "mark_last_interactive_answered", None)
            if _marker is not None:
                try:
                    await _marker(session_id)
                except Exception as _me:
                    # 卡片态落库失败（#4084）：卡片会永远停在"未作答"，事后再看会话记录已失真
                    # ⇒ 留痕 + incident 短码（不再只留一句 warning）
                    _report_persist_failure(
                        exc=_me, op="mark_last_interactive_answered",
                        source="page.mark_answered", session_id=session_id, tenant_id=tenant_id,
                    )

            yield SSEEvent.loading("正在查询...")

            # 构建 ToolContext
            tool_context = ToolContext(
                tenant_id=tenant_id, user_id=user_id, session_id=session_id,
                role=_to_agent_role(current_user.role),
                permissions=getattr(current_user, "permissions", None) or [],
            )

            # 直接执行工具
            result = await tool_registry.execute_tool(tool_name, tool_context, **params)

            if result.success:
                tool_data = result.data or {}
                yield SSEEvent.tool_call(tool_name, params)
                yield SSEEvent.tool_result(tool_name, {
                    "success": True, "data": tool_data, "message": result.message,
                })

                # 检查并发送卡片（order 卡片自动归一化载荷）
                card_type, card_data = _card_payload(tool_name, {"success": True, "data": tool_data})
                if card_type:
                    yield SSEEvent.card(card_type, card_data)
                    if card_type not in page_card_types:
                        page_card_types.append(card_type)

                # 构建新一页的选项列表，触发交互组件
                page = params.get("page", 1)
                size = params.get("size", 10)
                items = tool_data.get("items") or tool_data.get("records") or []
                total = tool_data.get("total", len(items))
                total_pages = max(1, (total + size - 1) // size) if size else 1

                # 将前一页的其它查询参数保留
                prev_params = {k: v for k, v in params.items() if k not in ("page",)}
                next_params_str = json.dumps({**prev_params, "page": page, "size": size}, ensure_ascii=False)

                if items:
                    options = []
                    for item in items:
                        name = item.get("name", "")
                        price = item.get("unit_price") or item.get("unitPrice") or ""
                        unit = item.get("unit", "")
                        # issue #4882：加工项目录**已无单价**（只剩名称/分类/单位）⇒ 无价时不渲染
                        # 描述 —— 否则会拼出「/米」这种像缺价的残句（R5：禁止新增静默失效形态）。
                        if price and unit:
                            desc = f"¥{price}/{unit}"
                        elif price:
                            desc = f"¥{price}"
                        else:
                            desc = None
                        options.append({
                            "label": str(name),
                            "value": str(name),
                            "description": desc,
                        })

                    # 更新 page_meta 参数指向当前页（供前端再次翻页）
                    next_page_meta = {
                        "current": page,
                        "total": total_pages,
                        "totalCount": total,
                        "tool": tool_name,
                        "params": next_params_str,
                    }

                    # 加工项翻页场景：新页 choice 仍须保持多选模式
                    # （issue #2894：翻页后丢失 multiSelect → 前端退回单选择卡锁死）
                    interactive_payload = {
                        "component": "choice",
                        "title": f"{result.message} (第{page}/{total_pages}页)",
                        "options": options,
                        "pageMeta": next_page_meta,
                    }
                    if tool_name == "processing_item_query":
                        interactive_payload["multiSelect"] = True

                    # ⚠️ 本函数没有 `context` 参数（首版照抄别处写成 context → NameError →
                    # 被兜底成"翻页查询失败"，被 test_chat.py 的翻页用例当场抓住）。
                    # 角色从 current_user 取，经 `_to_agent_role` 归一（与其它调用点同口径）。
                    _role_ctx = SimpleNamespace(role=_to_agent_role(getattr(current_user, "role", "")))
                    yield SSEEvent.interactive(
                        "choice", _mask_card_for_customer(interactive_payload, _role_ctx))

            else:
                yield SSEEvent.error(result.message or "查询失败")

        except Exception as e:
            logger.error(f"[page] Tool execution failed: {e}", exc_info=True)
            yield SSEEvent.error("翻页查询失败，请稍后重试")

        # 保存 assistant 响应（#4084 病灶点：此前是 `except Exception: pass` —— 消息没落库、
        # 日志里也没有，翻页轮次在历史里凭空少一条且无人知道；现经单一策略点留痕）
        await _save_message_or_report(
            session_memory, source="page.assistant",
            session_id=session_id, role="assistant",
            content=f"已展示第{params.get('page', '?')}页结果",
            tenant_id=tenant_id,
            extra_metadata={"cards": page_card_types} if page_card_types else None,
        )

        yield SSEEvent.done(session_id, None)
        logger.debug(f"[page] SSE stream ended | session={session_id}")

    return StreamingResponse(
        _page_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ============ 表单协议 ============

# __FORM__ payload 大小上限（防超长注入；超出回退为普通文本）
_FORM_MAX_LEN = 2048


def _card_identity(card: dict) -> str:
    """卡片在会话里的身份（B 端 `card_answer.cardId` 口径，issue #5949）。

    组成 = `component|title|formField keys` 逐字 join（无哈希）—— 选它是因为**客户端也要算**：
    admin-web 的 `cardAnswerId()` 用同一条规则（跨端判据见
    `backend/ai-agent-service/tests/test_card_form_submit_shape_cross_end_contract.py`），
    服务端对**同一份真值源** `last_card` 复算 ⇒ 「答的是不是本会话待答的那张卡」可判。

    ⚠️ 射程（如实登记）：这是**卡片内容身份**，不是实例 id —— 同 component + 同 title +
    同字段 key 的第二张卡与之同 id（真正的实例 id 要在 `app/tools/interact.py` 落字段，
    越出本包文件面）。
    """
    fields = card.get("formFields")
    keys = ([str(f.get("key") or "") for f in fields if isinstance(f, dict)]
            if isinstance(fields, list) else [])
    return "|".join([str(card.get("component") or ""), str(card.get("title") or ""), *keys])


async def _card_answer_targets_pending_card(card_answer, session_id: str) -> bool:
    """`card_answer.cardId` 是否指向本会话待答的那张卡（真值源 = 会话状态里的 `last_card`）。

    - **未给出 cardId** ⇒ 不在这里判（`_is_card_answer_round` 的
      `pending_interact_skill` / `last_card_skill` / `last_card` 三元组兜底）；
    - **给出** ⇒ 必须与本会话 `last_card` 的身份**逐字相等**（防「答的是一张已经过期的卡」）；
    - 会话不存在 / 没有 `last_card` / 读状态异常 ⇒ **False**（fail-closed：值仍以普通消息进本轮，
      只是不进答卡豁免）。
    """
    card_id = str(getattr(card_answer, "cardId", "") or "").strip()
    if not card_id:
        return True
    try:
        from app.memory.session_state_store import SessionStateStore

        full = await SessionStateStore().load(session_id) or {}
    except Exception as e:
        logger.warning(f"[form] 读取会话卡状态失败（按非答卡处理）: {e}")
        return False
    last_card = full.get("last_card")
    return bool(isinstance(last_card, dict) and last_card
                and card_id == _card_identity(last_card))


async def _handle_form_request(
    request: "ChatSendRequest",
    tenant_id: int,
    user_id: str,
    current_user,
):
    """
    处理表单提交：解析字段 → 注入 LLM 上下文 → 走正常 agent 流程。

    **两条入口通道（issue #5949）**：
    - C 端：消息前缀 `__FORM__|{json}`
      例：`__FORM__|{"customer_name":"张三","customer_phone":"13800138000","quantity":"3"}`
    - B 端：请求体结构化字段 `card_answer = {cardId?, values}`
      —— **先归一到上面那条前缀形态**再走同一段链路（大小上限 / 非法回退 / PII 脱敏 /
      「非法 payload 不递归」全部复用，不新写第二份注入）；`cardId` 给出且与本会话
      `last_card` 不一致 ⇒ 本轮**不算答卡轮**，按普通消息走（值不丢）。

    设计（docs/design/miniapp-multiturn-form-scenarios.md §4）：
    - 表单字段以可读文本注入本轮会话上下文（LLM 无感协议，兼容现有 flow，
      保留 LLM 确认/校验能力；区别于 __PAGE__ 的直调工具）
    - payload 超限 / 非法 JSON / 非对象 → **降级**到普通文本路径（`_send_plain_message`），
      **不得**把原文交回分派入口 `send_message`（入口会按同一前缀再分派回本函数 ⇒ 互递归，
      issue #5451 实测 315 层后 RecursionError）
    - 日志手机号/邮箱脱敏（LogSanitizer），防敏感信息泄露
    """
    from app.memory.session_service import SessionService
    from app.utils.log_sanitizer import LogSanitizer

    # ── 安全校验：与 send_message 共用统一守卫（存在/租户/用户/closed + 刷新 last_activity）──
    session_memory = SessionMemory()
    session_service = SessionService(session_memory)
    session_id = request.session_id
    if not session_id:
        session_id = await session_memory.create_session(
            tenant_id=tenant_id, customer_id=user_id, title=None,
        )
    else:
        _session, _gate_error = await session_service.send_gate(
            session_id, tenant_id=tenant_id, user_id=user_id,
        )
        if _gate_error:
            _raise_session_error(*_gate_error)

    raw = request.message

    def _degrade() -> "ChatSendRequest":
        """回退用的请求：**换入口 + 带上已解析的 session_id**（出口必须真能改变结果）。

        - **换入口**：交回分派入口 `send_message` 会被按 `__FORM__|` 前缀再分派回本函数 ⇒ 递归；
        - **带上 session_id**：`session_id` 为空时上面已建好会话，交回原文会让普通路径再建一个
          （旧形态实测：同一次坏请求建 328 个会话）；
        - **清掉 `card_answer`**（issue #5949）：已归一的请求不得再把结构化字段带下去
          （否则入口按它二次分派 = 又一条自递归面）。
        """
        return request.model_copy(update={"session_id": session_id, "card_answer": None})

    # ── 结构化答卡（issue #5949）：B 端 `card_answer={cardId?, values}` → 归一到前缀形态 ──
    card_answer = request.card_answer
    if card_answer is not None:
        if not await _card_answer_targets_pending_card(card_answer, session_id):
            logger.info(
                f"[form] card_answer 的 cardId 未指向本会话待答卡 → 按普通消息处理"
                f" | session={session_id}"
            )
            return await _send_plain_message(_degrade(), current_user)
        raw = "__FORM__|" + json.dumps(card_answer.values, ensure_ascii=False)
        logger.info(
            f"[form] card_answer 归一为 __FORM__ 协议 | session={session_id} "
            f"fields={len(card_answer.values)}"
        )

    # 大小限制：超限回退普通文本（防超长注入）
    if len(raw) > _FORM_MAX_LEN:
        logger.warning(f"[form] __FORM__ payload too large ({len(raw)}B), fallback to plain text")
        return await _send_plain_message(_degrade(), current_user)

    try:
        payload = json.loads(raw[len("__FORM__|"):])
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"[form] Bad __FORM__ payload, fallback to plain text: {e}")
        return await _send_plain_message(_degrade(), current_user)

    if not isinstance(payload, dict):
        logger.warning("[form] __FORM__ payload not an object, fallback to plain text")
        return await _send_plain_message(_degrade(), current_user)

    logger.info(
        f"[form] Form submitted | tenant={tenant_id} user={user_id} session={session_id} "
        f"payload={LogSanitizer.mask_text(raw)}"
    )

    # 注入上下文：转可读文本作为本轮用户消息（LLM 自然理解，不改写历史）
    # ⚠️ 前缀必须用 `FORM_ANSWER_INJECT_PREFIX`（契约单一事实源）：图里的答卡判据
    # （`app/graph/nodes.py::_card_accepts_answer` 的 form 分支）认的就是这一条，
    # 两边各写一份字符串就会「入口换了形态、判据还认旧的」而没有任何东西会红。
    lines = [f"{k}: {v}" for k, v in payload.items() if v not in (None, "")]
    injected = FORM_ANSWER_INJECT_PREFIX + "；".join(lines)
    injected_request = ChatSendRequest(
        session_id=session_id,
        message=injected,
        images=request.images,
    )
    return await _send_plain_message(injected_request, current_user)


# ============ 页面上下文（issue #5371 族 4）============


async def _handle_page_ctx_request(
    request: "ChatSendRequest",
    tenant_id: int,
    user_id: str,
    current_user,
):
    """处理 `page_context` 字段：**按角色裁剪** → 登记 route 才注入 → 复算本轮用户消息。

    入参形态：`ChatSendRequest.page_context = {"route": "<当前页路径>", "entityId": "<uuid>"}`
    （**路径字面量不写在本文件** —— `app/context/page_registry.py` 的登记表才是它唯一落点；
    路由由各端自己拼，见 `tests/test_card_type_cross_end_contract.py` 的 L0 约束）

    设计（`docs/agent-feature-design.md` §三 族 4 / issue #5371）：
    - **只认路径与 id**：查询串在前端就丢、服务端再丢一次；payload 里的其它键（含
      `role` / 实体快照）**一律忽略** —— 上下文注入是新的越权面，客户端说了不算；
    - **角色/权限只从服务端会话取**（`current_user.role` / `.permissions`）；
    - 🔴 **未登记的 route ⇒ 不注入**（默认拒绝）：只注入**常量**降级提示，
      route / id **一个字都不进 LLM**（「猜错页面比不猜更烦」）。
    """
    from app.memory.session_service import SessionService
    from app.utils.log_sanitizer import LogSanitizer

    # ── 安全校验：与 send_message 共用统一守卫（存在/租户/用户/closed + 刷新 last_activity）──
    session_memory = SessionMemory()
    session_service = SessionService(session_memory)
    session_id = request.session_id
    if not session_id:
        session_id = await session_memory.create_session(
            tenant_id=tenant_id, customer_id=user_id, title=None,
        )
    else:
        _session, _gate_error = await session_service.send_gate(
            session_id, tenant_id=tenant_id, user_id=user_id,
        )
        if _gate_error:
            _raise_session_error(*_gate_error)

    payload = request.page_context if isinstance(request.page_context, dict) else {}

    # 角色 / 权限**只从服务端会话取**；payload 里的 role / permissions / 实体快照一律不读
    context = build_page_context(
        payload.get("route"),
        payload.get("entityId"),
        role=current_user.role,
        permissions=getattr(current_user, "permissions", None),
    )

    # 留痕只记「登记与否」，不记 route 原文 / id（防 PII 与路径进日志）；问题文本脱敏
    logger.info(
        f"[page-ctx] route={'registered' if context is not None else 'unregistered'} "
        f"| tenant={tenant_id} user={user_id} session={session_id} "
        f"msg={LogSanitizer.mask_text(request.message[:80])}"
    )

    injected_request = ChatSendRequest(
        session_id=session_id,
        message=render_page_context(request.message, context),
        images=request.images,
        # page_context 不再下发（本轮已消费：防重复注入，也防入口再分派成自递归）
    )
    # 🔴 信封**只进本轮 LLM 文本**，落库/展示用用户原话（issue #7112）：
    # 「页面上下文是元数据，不是用户说的话」（`app/context/page_registry.py` 的纪律），
    # 落库带上它 ⇒ 切回会话时整段内部提示上屏（并污染标题生成 / 记忆抽取）。
    return await _send_plain_message(
        injected_request, current_user, display_message=request.message,
    )


# ============ API 路由 ============

@router.post("/send")
async def send_message(
    request: ChatSendRequest,
    current_user: UserIdentity = Depends(get_current_user),
):
    """
    接收用户消息，返回 SSE 流式响应
    
    SSE 事件格式：
    - event: loading - 加载状态
    - event: text - AI 文本回复（流式）
    - event: tool_call - Tool 调用通知
    - event: tool_result - Tool 执行结果
    - event: card - 卡片数据（商品管理、订单等）
    - event: error - 错误信息
    - event: done - 对话完成
    
    心跳：每 15 秒发送一次 heartbeat
    """
    tenant_id = current_user.tenant_id
    user_id = current_user.user_id

    # ── __PAGE__ 分页协议：绕过 LLM 直接调工具，杜绝翻页幻觉 ──
    if request.message.startswith("__PAGE__|"):
        return await _handle_page_request(request, tenant_id, user_id, current_user)

    # ── __FORM__ 表单协议：解析字段注入 LLM 上下文（C 端表单化交互）──
    if request.message.startswith("__FORM__|"):
        return await _handle_form_request(request, tenant_id, user_id, current_user)

    # ── 结构化答卡（issue #5949）：B 端 form 卡提交 `card_answer={cardId?, values}` ──
    # 与上面同一条链路（归一 + 注入 + 护栏都在 `_handle_form_request` 里），
    # 不新写第二个分派入口 —— 也**不得**把它塞进上面的前缀分支（那要让前端拼协议串）。
    if request.card_answer is not None:
        return await _handle_form_request(request, tenant_id, user_id, current_user)

    # ── __PAGE_ENTER__ 协议（issue #5989 · P2）：客户端首次进页 ⇒ 主动导航提示 ──
    # 放在 `page_context` 之前：本轮的**意图**是「进页」而不是「问问题」，不注入页面上下文、
    # 不经 LLM（文案全部来自登记表 ⇒ 结构上不含步骤）。
    if request.message.startswith(PAGE_ENTER_PREFIX):
        return await _handle_page_enter_request(request, tenant_id, user_id, current_user)

    # ── 页面上下文（issue #5371 族 4）：未登记 route ⇒ 不注入（默认拒绝）──
    if request.page_context is not None:
        return await _handle_page_ctx_request(request, tenant_id, user_id, current_user)

    # 无前缀协议 ⇒ 普通文本路径。**回退/交接只能落到这个独立入口**，不得交回本函数：
    # 本函数按**前缀**分派，交回（未改变状态的）原文 = 按同一前缀再分派回原处理器 ⇒ 递归（issue #5451）。
    return await _send_plain_message(request, current_user)


# ============ 主动新手引导（issue #5989 · P2）============

#: 客户端**首次进入某个页面**时发的轻量轮次前缀（运输形态 = 复用 `/api/chat/send`，**不推送**）：
#: `__PAGE_ENTER__|{"route": "/products"}`。
#: ⚠️ 只允许 **route** 一个键 —— 客户端**说了不算**：可见性由服务端会话权限判（不读 role）。
PAGE_ENTER_PREFIX = "__PAGE_ENTER__|"

#: 「每页每会话最多 1 次」的**服务端**落点：`session_states.state` 的这个键
#: （存**功能 id** 列表，不是 route —— 同一功能的多个路径共享一次推送）。
_PROACTIVE_STATE_KEY = "onboarding_pushed_features"

#: 会话状态读写的超时（秒）—— 与 `_save_message_or_report` 同口径，不阻塞 SSE。
_PROACTIVE_STATE_TIMEOUT = 10.0


async def _load_pushed_features(session_id: str) -> List[str]:
    """读「本会话已推过的功能 id」。

    ⚠️ 本仓 `SessionStateStore.load` 对「没有这一行」（= 新会话的**正常**形态）与「存储故障」
    都返回 `None`（见 `app/memory/session_state_store.py`）⇒ **这里必须把两者都读成「没有记录」**。
    若把 `None` 读成「存储不可用 ⇒ 不发」，本功能会在**每个新会话的第一次进页**（`session_states`
    还没有行）静默失效 = 结构性死路（本仓最忌的「绿了但没跑」）。

    真正的安全网在**写**那一侧：`_commit_pushed_feature` 失败 ⇒ **不发**（存储不可用时不会
    退化成「每次进页都推」），而重复推由「先记账、后推送」挡住。
    """
    from app.memory.session_state_store import SessionStateStore

    try:
        state = await asyncio.wait_for(
            SessionStateStore().load(session_id), timeout=_PROACTIVE_STATE_TIMEOUT)
    except Exception as exc:
        _report_persist_failure(
            exc=exc, op="load", source="proactive.state_load", session_id=session_id,
        )
        return []
    if not isinstance(state, dict):
        return []
    pushed = state.get(_PROACTIVE_STATE_KEY)
    return [str(x) for x in pushed] if isinstance(pushed, list) else []


async def _commit_pushed_feature(session_id: str, feature_id: str, existing: List[str]) -> bool:
    """把 `feature_id` 记进会话状态（**推送前**调用：先记账，后推送 —— 重复推比漏推糟）。

    返回 `True` = 已记账（可推）；`False` = 没记上 ⇒ 本轮**不发**（否则一次存储故障会退回
    「每次进页都推」）。
    """
    from app.memory.session_state_store import SessionStateStore

    try:
        # 🔴 **必须取 commit 的返回值**：`SessionStateStore.commit` 用「返回 False」表示写失败
        # （不抛异常）—— 丢掉它就会把「没记上」当成功 ⇒ 一次存储故障退回「每次进页都推」。
        # 本行原本写成 `await …; return True`（实测被 `test_commit_failure_means_no_push` 抓出）。
        return bool(await asyncio.wait_for(
            SessionStateStore().commit(session_id, {_PROACTIVE_STATE_KEY: list(existing) + [feature_id]}),
            timeout=_PROACTIVE_STATE_TIMEOUT,
        ))
    except Exception as exc:
        _report_persist_failure(
            exc=exc, op="commit", source="proactive.state_commit", session_id=session_id,
        )
        return False


def _proactive_noop_stream(session_id: Optional[str]) -> StreamingResponse:
    """**不推**时的静默流：一个 `done` 事件，无文本、不进历史（前端什么都不渲染）。

    「宁可静默，也不要猜错 / 越权 / 骚扰」—— 未登记页面、无权页面、已推过、存储不可用，
    四条出口都落在这里。
    """
    async def _empty():
        yield SSEEvent.done(session_id or "", None)

    return StreamingResponse(_empty(), media_type="text/event-stream")


async def _handle_page_enter_request(
    request: "ChatSendRequest",
    tenant_id: int,
    user_id: str,
    current_user,
):
    """**客户端首次进页 ⇒ 黄金策在对话区主动发一条导航提示**（issue #5989 · P2）。

    运输形态：前端在**路由变化**时发一条 `__PAGE_ENTER__|{"route": …}`（复用 `/api/chat/send`）
    —— **客户端触发、服务端判定**。不新建 SSE 主动推 / 定时 / 队列等基础设施。

    判定（**每一条 fail-closed ⇒ 静默**，判定本体在 `app/context/menu_navigator.py`）：

    1. route ↔ 功能**唯一**对应（未登记 / 歧义 ⇒ 不推）；
    2. 该页在**服务端会话权限**下可见（客户端递交的 role / permissions **一律不读**）；
    3. 「**每页每会话最多 1 次**」——**服务端**判（`session_states`），不靠前端自觉；
    4. **可行动性**：文案必须带「你在哪一页 + 入口怎么走」，否则不发。

    命中时**不经 LLM**（文案来自登记表 ⇒ 结构上不含步骤）：只回一条 `text` + `done`。
    🔴 **不落库**（issue #7324，用户裁定）：主动导航提示是**当次进页**的轻提示 —— 落进历史后会在
    换端 / 退出重登时以普通「AI 助手」气泡回放（内容还说「你在【X】」，而用户当下在对话页），
    与 #7112（页面上下文信封被落库）同一形态。频率上限记在会话状态里，**不依赖**历史。
    """
    from app.memory.session_service import SessionService
    from app.utils.log_sanitizer import LogSanitizer

    # ── 会话守卫（与 `_handle_page_ctx_request` 复用同一守卫）──
    session_memory = SessionMemory()
    session_service = SessionService(session_memory)
    session_id = request.session_id
    if not session_id:
        logger.info("[proactive] skip | reason=no_session")
        return _proactive_noop_stream(None)
    _session, _gate_error = await session_service.send_gate(
        session_id, tenant_id=tenant_id, user_id=user_id,
    )
    if _gate_error:
        _raise_session_error(*_gate_error)

    # ── payload：只认 route（畸形 ⇒ 按未登记 ⇒ 静默）──
    try:
        payload = json.loads(request.message[len(PAGE_ENTER_PREFIX):])
    except (ValueError, json.JSONDecodeError):
        payload = None
    route = payload.get("route") if isinstance(payload, dict) else None

    # ── 服务端会话的权限（**唯一**裁剪输入；客户端 role/permissions 不读）──
    permissions = getattr(current_user, "permissions", None)

    # 「每页每会话 ≤ 1 次」：已推集（新会话没有 `session_states` 行 ⇒ 空集）
    already_pushed = await _load_pushed_features(session_id)

    verdict = build_proactive_push(route, permissions, already_pushed=already_pushed)

    # 留痕只记**判定结果**，不记 route 原文（防路径/PII 进日志）
    logger.info(
        f"[proactive] route_enter | push={verdict.should_push} reason={verdict.reason or '-'} "
        f"| tenant={tenant_id} user={user_id} session={session_id} "
        f"msg={LogSanitizer.mask_text(request.message[:80])}"
    )

    if not verdict.should_push or verdict.push is None:
        return _proactive_noop_stream(session_id)

    # 先记账（失败 ⇒ 不发）：一次存储故障不该退回「每次进页都推」
    if not await _commit_pushed_feature(session_id, verdict.push.feature_id, already_pushed):
        logger.info(f"[proactive] skip | reason=state_commit_failed session={session_id}")
        return _proactive_noop_stream(session_id)

    text = verdict.push.render()

    async def _push_stream():
        # 🔴 **不落库**（issue #7324）：见 handler docstring —— 历史里回放会让「你在【X】」永远停在
        # 重登后的对话区。提示只属于当次进页；频率上限由上面 `_commit_pushed_feature` 保证。
        yield SSEEvent.text(text)
        yield SSEEvent.done(session_id, None)

    return StreamingResponse(_push_stream(), media_type="text/event-stream")


async def _send_plain_message(
    request: ChatSendRequest,
    current_user: UserIdentity,
    *,
    display_message: Optional[str] = None,
):
    """普通文本路径：会话守卫 → 落库 → Agent 流式 SSE。**不含任何前缀分派**。

    调用方两处：入口 `send_message` 在「无前缀协议」时进入；`_handle_form_request`
    在 payload 非法/超限时**降级**到这里（issue #5451）。本函数**不是**分派入口，
    因此降级路径结构上不可能再回到 `send_message`（类级判据见
    `tests/test_form_fallback_degrade.py`）。
    """
    tenant_id = current_user.tenant_id
    user_id = current_user.user_id

    # 落库 / 展示 / 标题 / 记忆抽取用的**用户原话**：可与「本轮送给 LLM 的文本」不同
    # （页面上下文信封只属于后者，issue #7112）。
    user_text = request.message if display_message is None else display_message

    logger.info(
        f"[chat/send] Message received | tenant={tenant_id} user={user_id} session={request.session_id or 'new'} msg_len={len(request.message)}"
    )

    # 初始化组件
    session_memory = SessionMemory()
    tool_registry = get_tool_registry()
    
    # 根据用户角色选择 Agent 类型（配置驱动路由）
    from app.agents.agent_router import get_agent_router
    agent_router = get_agent_router()
    agent_type = agent_router.route(current_user)

    # 确定 Agent 角色（用于 ToolContext 权限检查）
    agent_role = _to_agent_role(current_user.role)

    agent = get_agent(tool_registry, agent_type=agent_type)
    
    # 1. 创建或获取 session（统一守卫：存在/租户/用户/closed + 刷新 last_activity）
    from app.memory.session_service import SessionService
    session_service = SessionService(session_memory)
    session_id = request.session_id
    if not session_id:
        # 创建新会话。不再强制关闭其他活跃会话，支持多会话并存
        session_id = await session_memory.create_session(
            tenant_id=tenant_id,
            customer_id=user_id,
            title=None,  # 自动生成标题
        )
    else:
        _session, _gate_error = await session_service.send_gate(
            session_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if _gate_error:
            _raise_session_error(*_gate_error)
        # 空闲超时统一由后台任务 _session_auto_close_loop 处理，
        # send 路径不做会话轮换，避免 session_id 突变导致前端状态不一致
    
    async def event_stream():
        try:
            # 2. 校验图片 URL 并保存用户消息
            images = request.images or []
            if images:
                if len(images) > 3:
                    yield SSEEvent.error("单条消息最多支持 3 张图片")
                    return
                invalid_urls = [url for url in images if not _validate_image_url(url)]
                if invalid_urls:
                    yield SSEEvent.error(f"图片 URL 格式不合法，仅支持 https:// 或 /api/files 开头: {invalid_urls}")
                    return
            
            content_type = "mixed" if images else "text"
            extra_metadata = {"images": images} if images else None
            
            # 用户消息是**后续轮次历史的锚**：它没写进去就不该装作这轮开始了
            # ⇒ fail_open=False（留痕后原样上抛，由本生成器的兜底给出"这轮没成功"）。
            # 旧形态：异常混进下面的通用 except，日志只说"event_stream error"，归因不明（#4084）。
            await _save_message_or_report(
                session_memory, source="chat.user", fail_open=False,
                session_id=session_id,
                role="user",
                content=user_text,
                tenant_id=tenant_id,
                content_type=content_type,
                extra_metadata=extra_metadata,
            )
            # user replied -> mark last interactive as answered (issue #3036 readonly persistence);
            # best-effort: in-memory/legacy stores may lack the method, never block the main flow
            _marker = getattr(session_memory, "mark_last_interactive_answered", None)
            if _marker is not None:
                try:
                    await _marker(session_id)
                except Exception as _me:
                    # 卡片态落库失败（#4084）：卡片停在"未作答"⇒ 会话记录里的卡片态失真
                    _report_persist_failure(
                        exc=_me, op="mark_last_interactive_answered",
                        source="chat.mark_answered", session_id=session_id, tenant_id=tenant_id,
                    )
            
            # 3. 构建多模态消息内容
            if images:
                user_message_content: Union[str, List[Dict[str, Any]]] = [
                    # issue #3046：图片 URL 以文本注入，LLM 工具调用可引用；vision 块并行保留
                    {"type": "text", "text": request.message + _image_url_hint(images)}
                ]
                for img_url in images:
                    user_message_content.append({
                        "type": "image_url",
                        "image_url": {"url": _rewrite_image_url(img_url)}
                    })
            else:
                user_message_content = request.message
            
            # 4. 获取对话历史（按 token 预算动态加载）
            MAX_CONTEXT_TOKENS = 65536  # 64K 输入预算，MiniMax-M3 1M 上下文有充足余量
            history_messages, needs_compression = await session_memory.get_history_by_tokens(
                session_id, max_tokens=MAX_CONTEXT_TOKENS
            )

            # 4a. 如果历史超限，压缩早期消息为摘要（经 ContextBuilder，摘要回写工作状态）
            if needs_compression:
                try:
                    from app.memory.context_builder import ContextBuilder
                    history_messages = await ContextBuilder().compress_history(
                        history_messages,
                        session_id=session_id,
                        max_turns=10,
                        keep_recent=5,
                    )
                    logger.info(
                        f"[chat/send] History compressed | session={session_id} "
                        f"messages={len(history_messages)}"
                    )
                except Exception as compress_err:
                    logger.warning(
                        f"[chat/send] History compression failed (non-fatal): {compress_err}"
                    )

            chat_history = _convert_history_to_agent_format(history_messages)
            
            # 5. 创建 Agent 上下文
            # 查询用户昵称（Redis 缓存 → DB 回退），注入到 System Prompt 让 Agent 认识当前对话的人
            user_name: Optional[str] = await _get_user_nickname(tenant_id, user_id)
            # 查询企业名称（Redis 缓存 → DB 回退），注入企业身份（对应「企业基础信息」的公司名称设置）
            tenant_name: Optional[str] = await _get_tenant_name(tenant_id)

            agent_context = AgentContext(
                user_id=user_id,
                tenant_id=tenant_id,
                session_id=session_id,
                role=agent_role,
                identity_type=current_user.identity_type,
                user_name=user_name,
                tenant_name=tenant_name,
                permissions=getattr(current_user, "permissions", None) or [],
            )
            
            # 6. 调用 Agent 处理（流式）
            async for event in _agent_stream_to_sse(
                agent=agent,
                message=user_message_content,
                context=agent_context,
                chat_history=chat_history,
                tool_registry=tool_registry,
                session_memory=session_memory,
                session_id=session_id,
                tenant_id=tenant_id,
                user_id=user_id,
                display_message=user_text,
            ):
                yield event
                
        except Exception as e:
            # issue #3810 同族扫描命中的第二个终端可见落点（本分支包住整个 SSE 生成器，
            # 与上面 `_agent_stream_to_sse` 那个兜底互不覆盖）：用户侧同样改纯中文，
            # 技术细节落日志 + incident 短码；`traceback` 由 loguru 的 exception 字段承载。
            _err_inc.log_exception_audit(
                logger=logger,
                mark="[chat/send] event_stream error",
                exc=e,
                session_id=session_id,
                extra=(f"tenant={tenant_id} user={user_id} "
                       f"req={_err_inc.current_request_id()}"),
            )
            yield SSEEvent.error("刚才这轮没成功，请您再说一次，我继续为您办理。")
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/sessions")
async def create_session(
    request: ChatSessionCreate,
    current_user: UserIdentity = Depends(get_current_user),
):
    """
    创建新会话
    
    Returns:
        ChatSessionResponse: 新创建的会话信息
    """
    session_memory = SessionMemory()

    session_id = await session_memory.create_session(
        tenant_id=current_user.tenant_id,
        customer_id=current_user.user_id,
        title=request.title,
    )
    logger.info(f"Session created: session_id={session_id}, user_id={current_user.user_id}, tenant_id={current_user.tenant_id}")

    # 获取创建的会话信息
    session = await session_memory.get_session(session_id)
    
    return make_response(True, data={
        "id": session["id"],
        "tenant_id": session["tenant_id"],
        "user_id": session["customer_id"],
        "title": session["title"],
        "created_at": _format_datetime(session["created_at"]),
        "updated_at": _format_datetime(session["updated_at"]),
        "message_count": 0,
    })


@router.get("/sessions")
async def list_sessions(
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user: UserIdentity = Depends(get_current_user),
):
    """
    获取用户的会话列表
    
    Args:
        page: 页码，从 1 开始
        size: 每页数量
        
    Returns:
        List[ChatSessionResponse]: 会话列表
    """
    session_memory = SessionMemory()
    logger.debug(f"[chat/sessions] Listing | tenant={current_user.tenant_id} user={current_user.user_id} page={page} size={size}")
    
    sessions = await session_memory.get_sessions(
        tenant_id=current_user.tenant_id,
        customer_id=current_user.user_id,
        page=page,
        size=size,
    )
    
    # 格式化响应
    formatted_sessions = []
    for session in sessions:
        formatted_sessions.append({
            "id": session["id"],
            "tenant_id": session["tenant_id"],
            "user_id": session["customer_id"],
            "title": session["title"],
            "status": session.get("status", "active"),
            "last_message": session.get("last_message"),
            "customer_name": session.get("customer_name"),
            "message_count": session.get("message_count", 0),
            "created_at": _format_datetime(session["created_at"]),
            "updated_at": _format_datetime(session["updated_at"]),
        })
    
    return make_response(True, data={
        "items": formatted_sessions,
        "page": page,
        "size": size,
        "total": len(formatted_sessions),
    })


@router.get("/sessions/latest")
async def get_latest_session(
    current_user: UserIdentity = Depends(get_current_user),
):
    """
    获取最近一次的活跃会话（无会话 UX：打开即续聊，前端无感知）。

    - 返回最近一条 active 会话（按 updated_at 倒序）；无则返回 null
    - 前端据此决定「续聊」或「新建」，不暴露会话列表概念

    Returns:
        { "session": {...} | null }
    """
    session_memory = SessionMemory()
    sessions = await session_memory.get_sessions(
        tenant_id=current_user.tenant_id,
        customer_id=current_user.user_id,
        page=1,
        size=1,
        status="active",  # #2726: 只续聊 active 会话，防续聊 closed 会话导致发送 409
    )
    if not sessions:
        return make_response(True, data={"session": None})

    session = sessions[0]
    return make_response(True, data={"session": {
        "id": session["id"],
        "tenant_id": session["tenant_id"],
        "user_id": session["customer_id"],
        "title": session["title"],
        "status": session.get("status", "active"),
        "last_message": session.get("last_message"),
        "message_count": session.get("message_count", 0),
        "created_at": _format_datetime(session["created_at"]),
        "updated_at": _format_datetime(session["updated_at"]),
    }})


@router.put("/sessions/{session_id}/close")
async def close_session_endpoint(
    session_id: str,
    current_user: UserIdentity = Depends(get_current_user),
):
    """
    关闭会话（仅转换状态为 'closed'，不删除消息）

    与 DELETE /sessions/{id} 区别：
    - DELETE: 物理删除会话及其所有消息。
    - PUT close: 仅将 status 置为 closed，保留历史消息。
    """
    session_memory = SessionMemory()
    session = await _guard_session(
        session_memory, session_id,
        tenant_id=current_user.tenant_id, user_id=current_user.user_id,
        action="关闭",
    )

    # 幂等语义：已 closed 仍返回成功
    if session.get("status") == "closed":
        logger.info(f"[chat/close] Session already closed | session_id={session_id}")
        return make_response(True, data={
            "session_id": session_id,
            "status": "closed",
            "message": "会话已处于关闭状态",
        })

    from app.memory.session_service import SessionService
    await SessionService(session_memory).close(session_id)
    logger.info(
        f"Session closed via API: session_id={session_id}, user_id={current_user.user_id}, "
        f"tenant_id={current_user.tenant_id}"
    )

    return make_response(True, data={
        "session_id": session_id,
        "status": "closed",
        "message": "会话已结束",
    })


@router.put("/sessions/{session_id}/reopen")
async def reopen_session_endpoint(
    session_id: str,
    current_user: UserIdentity = Depends(get_current_user),
):
    """
    重新打开已关闭的会话：status 'closed' → 'active'。
    仅会话所有者可操作。
    """
    session_memory = SessionMemory()
    session = await _guard_session(
        session_memory, session_id,
        tenant_id=current_user.tenant_id, user_id=current_user.user_id,
        action="操作",
    )
    if session.get("status") != "closed":
        return make_response(True, data={"session_id": session_id, "status": session.get("status"), "message": "会话已是活跃状态"})

    from app.memory.session_service import SessionService
    await SessionService(session_memory).reopen(session_id)
    logger.info(f"Session reopened: session_id={session_id}, user_id={current_user.user_id}")
    return make_response(True, data={"session_id": session_id, "status": "active", "message": "会话已重新打开"})


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    current_user: UserIdentity = Depends(get_current_user),
):
    """
    结束/删除会话

    Args:
        session_id: 会话 ID

    Returns:
        删除结果
    """
    session_memory = SessionMemory()
    
    # 统一会话守卫：存在 + 租户/用户所有权（404/403）
    await _guard_session(
        session_memory, session_id,
        tenant_id=current_user.tenant_id, user_id=current_user.user_id,
        action="删除",
    )
    
    # 删除会话（经 SessionService，终态 purged 语义）
    from app.memory.session_service import SessionService
    await SessionService(session_memory).delete(session_id)
    logger.info(f"Session deleted: session_id={session_id}, user_id={current_user.user_id}, tenant_id={current_user.tenant_id}")
    
    return make_response(True, data={
        "message": "会话已删除",
        "session_id": session_id,
    })


@router.get("/history/{session_id}")
async def get_history(
    session_id: str,
    limit: int = Query(50, ge=1, le=100, description="返回消息数量"),
    current_user: UserIdentity = Depends(get_current_user),
):
    """
    获取会话历史消息
    
    Args:
        session_id: 会话 ID
        limit: 返回消息数量限制
        
    Returns:
        List[ChatMessageResponse]: 消息列表
    """
    session_memory = SessionMemory()
    logger.debug(f"[chat/history] Fetching | tenant={current_user.tenant_id} user={current_user.user_id} session={session_id}")

    # 统一会话守卫：存在 + 租户/用户所有权（404/403）
    await _guard_session(
        session_memory, session_id,
        tenant_id=current_user.tenant_id, user_id=current_user.user_id,
        action="访问",
    )

    # 获取历史消息
    messages = await session_memory.get_history(session_id, limit=limit)
    
    # 格式化响应
    formatted_messages = []
    for msg in messages:
        # 存量主动导航提示不回放（issue #7324）：#6030 起这类行曾落库，读侧消化、不回写库
        if _is_legacy_proactive_tip_row(msg):
            continue
        # 解析 metadata 获取 images
        metadata = msg.get("metadata")
        msg_images = None
        if isinstance(metadata, dict):
            msg_images = metadata.get("images")
        elif isinstance(metadata, str):
            try:
                import json
                meta_parsed = json.loads(metadata)
                msg_images = meta_parsed.get("images")
            except (json.JSONDecodeError, TypeError):
                pass
        
        # interactive payload + answered flag passthrough (issue #3036 / UI-031)
        interactive_data = None
        interactive_answered = False
        # 展示卡卡型回传（#4016 A15）：与 interactive 对称 —— 落库的卡型要能**读出来**
        # 才不是只写不读的空字段（`metadata ? 'cards'` 亦可直接在库上做用量统计）。
        card_types = None
        # 工具**执行结果**元信息回传（issue #4097）：写侧自 #4052 起就落 `metadata.tool_results`
        # （`[{tool, success, error}]`，与 `metadata.tool_calls` 逐项对齐），但读侧一直没暴露
        # ⇒ 评测只能断言「模型说它调了」，不能断言「确实调了 / 确实成了」。
        # 与 `cards` 同款口径：落库值**原样**回传，缺失/非列表 → None（不猜、不补、不裁）。
        # 与 `tool_calls` 同层同权（本响应已在回传 args）⇒ 不引入新的数据暴露面。
        tool_results_data = None
        if isinstance(metadata, dict):
            interactive_data = metadata.get("interactive")
            interactive_answered = metadata.get("interactive_answered", False) is True
            card_types = metadata.get("cards")
            tool_results_data = metadata.get("tool_results")
        elif isinstance(metadata, str):
            try:
                meta_parsed = json.loads(metadata)
                interactive_data = meta_parsed.get("interactive")
                interactive_answered = meta_parsed.get("interactive_answered", False) is True
                card_types = meta_parsed.get("cards")
                tool_results_data = meta_parsed.get("tool_results")
            except (json.JSONDecodeError, TypeError):
                pass

        formatted_messages.append({
            "id": msg["id"],
            "session_id": msg["session_id"],
            "role": msg["role"],
            # C 端历史是**展示面**：顾客刷新页面走的就是这里回放（issue #3386）。
            # 出站脱敏此前只做在 SSE 流上 → 同一份对话「流上脱敏、历史里明文」两种口径。
            # 落库保持原文（模型下一轮/复核对账都要真号），脱敏只在这一层做。
            # 内部路由清洗同在此处（issue #7236）：新行写库前已清，这一层兜**存量旧行**
            # （如 sess_742201cbf83f4f58）—— 存量数据不回写，但回放不得再带出。
            "content": _sanitize_outbound_text(
                _history_user_text(msg.get("role"), msg["content"]), current_user),
            "content_type": msg.get("content_type", "text"),
            "images": msg_images if msg_images else None,
            "tool_calls": msg.get("tool_calls"),
            # 工具执行结果（落库值原样回传；空/缺失 → None）。与 `tool_calls` **逐项对齐**
            # （写侧 #4052 的对齐契约），消费者按同一索引取「这次调用成没成」。
            "tool_results": tool_results_data if isinstance(tool_results_data, list) else None,
            "interactive": _mask_card_for_customer(interactive_data, current_user)
            if isinstance(interactive_data, dict) else interactive_data,
            "interactive_answered": interactive_answered,
            # 卡型列表（落库值原样回传；空/缺失 → None，前端按「无卡」处理）
            "cards": card_types if isinstance(card_types, list) else None,
            # 卡型列表（落库值原样回传；空/缺失 → None，前端按「无卡」处理）
            "created_at": _format_datetime(msg["created_at"]),
        })
    
    return make_response(True, data={
        "session_id": session_id,
        "messages": formatted_messages,
    })


# ──────────────── B 端快捷入口（**单一真值**，issue #6468）────────────────
#
# 这份清单是 B 端「快捷入口」的**唯一内容源**：admin-web
# （`frontend/admin-web/src/store/chat.ts` 的 `fetchQuickActions`）与 B 端 H5
# （`frontend/bmini-app` 的「问黄金策」空态六格）都消费本接口。
# ⇒ 任何一侧再自己写一份清单 = **又抄一次** —— #6468 的病灶正是 H5 硬编码了
# C 端顾客口吻的六条（「推荐一下热门窗帘产品」「帮我查一下物流」…），而服务端这份
# 一直没被 H5 消费（`loadQuickActions` 是死代码）。
#
# 每条的 `skill` / `tool` 是**能力锚**，判据 = `tests/test_chat.py::TestQuickActions`：
# 引导必须能追溯到一条**真实注册、且黄金策已绑定**的能力 ——
# 「引导了却做不到，比不引导更伤」（`docs/agent-feature-design.md` §九）。
# `prompt` 逐字取该工具 `description` 的【触发】词，保证模型路由得到（不是文案巧合）。
# 反模式（§九 明列，勿改回来）：❌ 拿系统能力名当引导 ❌ 静态示例（不管角色/上下文）
# ❌ 推荐答不出来的问题。
QUICK_ACTIONS: tuple[dict, ...] = (
    {
        "id": "daily_business",
        "name": "今日经营",
        "icon": "bar-chart-3",
        "emoji": "📊",
        "prompt": "今天经营怎么样？",
        "skill": "data",
        "tool": "briefing_query",
    },
    {
        "id": "delivery_risk",
        "name": "交付风险",
        "icon": "clipboard-list",
        "emoji": "🚨",
        "prompt": "哪些订单快到交期还卡着工序？",
        "skill": "order",
        "tool": "processing_order_query",
    },
    {
        "id": "low_stock",
        "name": "库存告急",
        "icon": "package",
        "emoji": "📦",
        "prompt": "有哪些低库存的商品？",
        "skill": "product",
        "tool": "inventory_manage",
    },
    {
        "id": "product_health",
        "name": "商品健康度",
        "icon": "tag",
        "emoji": "🏷️",
        "prompt": "哪些商品卖得好但退货高？",
        "skill": "data",
        "tool": "briefing_query",
    },
    {
        "id": "after_sales_todo",
        "name": "售后待办",
        "icon": "headphones",
        "emoji": "🛠️",
        "prompt": "有哪些售后工单还没处理？",
        "skill": "aftersales",
        "tool": "after_sales_manage",
    },
    {
        "id": "customer_churn",
        "name": "客户回访",
        "icon": "users",
        "emoji": "👥",
        "prompt": "哪些老客户最近不下单了？",
        "skill": "customer",
        "tool": "customer_manage",
    },
)

#: 快捷入口里的**工具类**入口（issue #7351）：与上面的「问句型」六格分开下发 ——
#: 「做海报」不是提问，而是一个需要引导补文案的动作。前端把 `tools` 渲染成独立的工具行，
#: 六格 `actions` 的数量/形态**一字不动**（既有 #5747/#6468 的 2×3 契约不受影响）。
#: 能力锚判据同 `TestQuickActions`：必须有真实注册、且黄金策已绑定的能力。
TOOL_SHORTCUTS: tuple[dict, ...] = (
    {
        "id": "marketing_poster",
        "name": "营销海报",
        "icon": "image",
        "emoji": "🖼️",
        "prompt": "我要给商品做一张营销海报",
        "skill": "product",
        "tool": "marketing_poster",
    },
)

#: 能力锚字段 —— **只用于服务端自证**（`tests/test_chat.py` 的机械投影判据），不进响应体
_CAPABILITY_ANCHOR_KEYS = ("skill", "tool")


def _quick_action_visible(action: dict, current_user: UserIdentity) -> bool:
    """该快捷入口对当前用户是否可见（issue #7358）。

    **判定谓词唯一 = `BaseTool.check_permission`**（`app/tools/base.py`）—— 入口下发与
    工具执行用同一个谓词，才不会出现「看得见却做不了」的第二份口径。

    为什么按 `permissions` 而不是按岗位：权限自 issue #2969 起是**快照式**
    （`users.permissions`，与岗位脱钩）⇒ 同一岗位两名员工权限可不同，岗位清单会漂移。

    工具未注册 ⇒ 不可见（fail-closed；与能力锚判据同向：引导必须能追溯到真实能力）。
    """
    tool = get_tool_registry().get_tool(action["tool"])
    if tool is None:
        return False
    return tool.check_permission(ToolContext(
        tenant_id=current_user.tenant_id,
        user_id=current_user.user_id,
        role=current_user.role,
        permissions=current_user.permissions,
    ))


@router.get("/quick-actions")
async def get_quick_actions(
    current_user: UserIdentity = Depends(get_current_user),
):
    """
    获取快捷功能菜单（B 端场景入口，单一真值见 `QUICK_ACTIONS`）

    每条的可见性 = 其 `tool` 在当前用户权限下的可执行性（issue #7358）——
    「引导了却做不到，比不引导更伤」（`docs/agent-feature-design.md` §九）。

    Returns:
        快捷功能列表（id / name / icon / emoji / prompt）
    """
    logger.debug(f"[chat/quick-actions] Fetching | tenant={current_user.tenant_id}")

    all_entries = (*QUICK_ACTIONS, *TOOL_SHORTCUTS)
    visible_ids = {a["id"] for a in all_entries if _quick_action_visible(a, current_user)}
    # 观测口径（只进日志、不进 UI）：被过滤掉的入口 = 「该员工缺哪些授权」的可发现面。
    # 没有它，漏授权会从「点下去报错」退化成「根本看不见」，从此没人发现（#7358 的已知风险）。
    dropped = [a["id"] for a in all_entries if a["id"] not in visible_ids]
    if dropped:
        logger.info(
            f"[chat/quick-actions] 按权限过滤 | tenant={current_user.tenant_id} "
            f"role={current_user.role} dropped={dropped}"
        )

    actions = [
        {k: v for k, v in action.items() if k not in _CAPABILITY_ANCHOR_KEYS}
        for action in QUICK_ACTIONS
        if action["id"] in visible_ids
    ]
    tools = [
        {k: v for k, v in tool.items() if k not in _CAPABILITY_ANCHOR_KEYS}
        for tool in TOOL_SHORTCUTS
        if tool["id"] in visible_ids
    ]

    return make_response(True, data={
        "actions": actions,
        # 工具类快捷入口（issue #7351）：与六格 actions 分开 —— 六格「问句」契约不动。
        "tools": tools,
    })


# ──────────────── 用户记忆合规 API（issue #2815，个保法查询权/删除权）────────────────

@router.get("/memories")
async def get_user_memories(
    current_user: UserIdentity = Depends(get_current_user),
    agent_type: str = "xiaobu",  # FastAPI 自动视为 query 参数；默认 C 端记忆
):
    """查询当前用户已保存的记忆（个保法第 45 条查询权）。

    - 仅返回当前登录用户自己的记忆（tenant_id + user_id 强制过滤）
    - 默认只查 xiaobu（C 端画像）；B 端（mibao）本期不产生记忆
    - 异常时返回空列表，不抛 500
    """
    try:
        memories = await UserMemoryManager().get_all_memories(
            current_user.tenant_id,
            current_user.user_id,
            agent_type=agent_type,
        )
        return make_response(True, data={"memories": memories})
    except Exception as e:
        logger.warning(
            f"[chat/memories] Query failed | tenant={current_user.tenant_id} "
            f"user={current_user.user_id} error={e}"
        )
        return make_response(True, data={"memories": []})


@router.delete("/memories")
async def delete_user_memories(
    current_user: UserIdentity = Depends(get_current_user),
    agent_type: str = "xiaobu",  # FastAPI 自动视为 query 参数；默认 C 端记忆
):
    """删除当前用户已保存的记忆（个保法第 47 条删除权）。

    - 仅删除当前登录用户自己的记忆（tenant_id + user_id 强制过滤）
    - 默认只删 xiaobu（C 端画像）
    - 异常时返回 0，不抛 500
    """
    try:
        deleted = await UserMemoryManager().delete_all(
            current_user.tenant_id,
            current_user.user_id,
            agent_type=agent_type,
        )
        return make_response(True, data={"deleted": deleted})
    except Exception as e:
        logger.warning(
            f"[chat/memories] Delete failed | tenant={current_user.tenant_id} "
            f"user={current_user.user_id} error={e}"
        )
        return make_response(True, data={"deleted": 0})
