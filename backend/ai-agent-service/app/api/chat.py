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
import time
import traceback
from typing import AsyncGenerator, Optional, List, Dict, Any, Union
from datetime import datetime, timedelta, timezone

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
from app.memory.session_memory import SessionMemory
from app.agents.customer_service_agent import (
    BaseAgent,
    AgentContext,
    get_agent,
)
from app.tools import ToolRegistry, get_tool_registry
from app.utils.auth import get_current_user, UserIdentity

router = APIRouter()

# 会话空闲超时：超过该时间未收到新消息，下一次 send 时自动关闭旧会话并新建
SESSION_IDLE_TIMEOUT_MINUTES = 30


# ============ 辅助函数 ============

async def _get_user_nickname(tenant_id: int, user_id: str) -> Optional[str]:
    """获取用户昵称（Redis 缓存 → DB 回退）

    缓存 key: nickname:{tenant_id}:{user_id}，TTL 1 小时。
    失败时静默返回 None（昵称非必需）。
    """
    cache_key = f"nickname:{tenant_id}:{user_id}"

    # 1. 尝试 Redis 缓存
    try:
        from app.utils.redis_client import redis_pool
        if redis_pool:
            import redis.asyncio as aioredis
            client = aioredis.Redis(connection_pool=redis_pool)
            cached = await client.get(cache_key)
            if cached:
                return cached
    except Exception:
        pass  # Redis 不可用时回退到 DB

    # 2. 缓存未命中，查 DB
    try:
        from sqlalchemy import text
        from app.utils.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            sql = text("SELECT nickname FROM users WHERE id = :user_id")
            result = await db.execute(sql, {"user_id": user_id})
            row = result.fetchone()
            if row and row[0]:
                nickname = row[0]
                # 3. 写入缓存
                try:
                    from app.utils.redis_client import redis_pool
                    if redis_pool:
                        import redis.asyncio as aioredis
                        client = aioredis.Redis(connection_pool=redis_pool)
                        await client.setex(cache_key, 3600, nickname)
                except Exception:
                    pass
                return nickname
    except Exception as e:
        logger.warning(
            f"[chat] Failed to query user nickname | user={user_id} error={e}"
        )

    return None


async def _extract_memories_async(
    tenant_id: int,
    user_id: str,
    user_message: str,
    assistant_reply: str,
    session_id: str,
) -> None:
    """fire-and-forget：从对话中提取并保存用户记忆"""
    try:
        from app.memory.extractor import extract_and_save
        count = await extract_and_save(
            tenant_id=tenant_id,
            user_id=user_id,
            user_message=user_message,
            assistant_reply=assistant_reply,
            session_id=session_id,
        )
        if count > 0:
            logger.info(
                f"[chat/send] Memory extracted | session={session_id} count={count}"
            )
    except Exception as e:
        logger.debug(f"[chat/send] Memory extraction failed (non-fatal): {e}")

def _format_datetime(dt: Any) -> str:
    """格式化日期时间为 ISO 8601 字符串（UTC，以 Z 结尾）"""
    if isinstance(dt, datetime):
        # 如果有时区信息，先转为 UTC 再去掉 tzinfo
        if dt.tzinfo is not None:
            from datetime import timezone
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.isoformat() + "Z"
    # 字符串兜底：移除可能已有的 +00:00Z 双重后缀
    s = str(dt)
    if s.endswith("+00:00Z"):
        s = s.replace("+00:00Z", "Z")
    elif s.endswith("+00:00"):
        s = s.replace("+00:00", "Z")
    return s


def _convert_history_to_agent_format(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将数据库消息格式转换为 Agent 所需的格式（支持多模态）

    对 assistant 消息剥离 <think> 块，防止：
    1. 旧数据中的思考内容挤占上下文预算
    2. 上轮推理内容干扰当前轮次的工具调用决策
    """
    import re
    history = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "assistant":
            content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
        entry: Dict[str, Any] = {
            "role": role,
            "content": content,
        }
        # 携带多模态信息
        content_type = msg.get("content_type", "text")
        if content_type and content_type != "text":
            entry["content_type"] = content_type
        metadata = msg.get("metadata")
        if isinstance(metadata, dict) and metadata.get("images"):
            entry["images"] = [_rewrite_image_url(url) for url in metadata["images"] if _validate_image_url(url)]
        elif isinstance(metadata, str):
            try:
                import json
                meta_parsed = json.loads(metadata)
                if meta_parsed.get("images"):
                    entry["images"] = [_rewrite_image_url(url) for url in meta_parsed["images"] if _validate_image_url(url)]
            except (json.JSONDecodeError, TypeError):
                pass
        history.append(entry)
    return history


def _validate_image_url(url: str) -> bool:
    """校验图片 URL 格式（必须是 https:// 或 /api/files 开头）"""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    return url.startswith("https://") or url.startswith("/api/files")


def _rewrite_image_url(url: str) -> str:
    """将 CDN 域名图片 URL 重写为 OSS URL（由 IMAGE_URL_REWRITE_FROM/TO 配置）"""
    if not settings.IMAGE_URL_REWRITE_FROM or not settings.IMAGE_URL_REWRITE_TO:
        return url
    return url.replace(settings.IMAGE_URL_REWRITE_FROM, settings.IMAGE_URL_REWRITE_TO)


def _detect_card_type(tool_name: str, result: Dict[str, Any]) -> Optional[str]:
    """
    根据 Tool 名称和结果检测应该发送的卡片类型
    
    Returns:
        Optional[str]: 卡片类型或 None
    """
    if tool_name == "product_search":
        return "product_list"
    elif tool_name == "product_detail":
        return "product_detail"
    elif tool_name == "logistics_track":
        return "logistics"
    elif tool_name == "order_query":
        return "order"
    return None


def _should_send_card(tool_name: str, result: Dict[str, Any]) -> bool:
    """判断是否应该发送卡片事件"""
    if not result.get("success", False):
        return False
    
    # 商品搜索有结果时发送卡片
    if tool_name == "product_search":
        data = result.get("data", {})
        products = data.get("products", [])
        return len(products) > 0
    
    # 商品详情有结果时发送卡片
    if tool_name == "product_detail":
        data = result.get("data", {})
        return data.get("product") is not None
    
    # 物流查询有结果时发送卡片
    if tool_name == "logistics_track":
        data = result.get("data", {})
        return data.get("tracking_number") is not None
    
    # 订单查询有结果时发送卡片
    if tool_name == "order_query":
        data = result.get("data", {})
        return data.get("order") is not None
    
    return False


# ============ SSE 流生成器 ============

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
) -> AsyncGenerator[str, None]:
    """
    将 Agent 的流式输出转换为 SSE 事件
    
    这是一个桥接函数，负责：
    1. 调用 Agent 的流式对话方法（LangGraph astream_events）
    2. 将 Agent 输出转换为 SSE 事件
    3. Tool 调用由 LangGraph Skill 节点内部处理
    4. 根据 Tool 结果发送卡片事件
    5. 保存消息到数据库
    6. 后续问题建议由图内 suggestions_node 生成
    """
    full_response = []
    tool_calls_info = []
    _done_sent = False

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
                        # 文本回复
                        if response.content:
                            full_response.append(response.content)
                            yield SSEEvent.text(response.content)

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
                                yield SSEEvent.tool_call(tool_name, tool_input)

                    elif response.type == "tool_result":
                        # Tool 执行结果（来自 LangGraph Skill 节点）
                        if response.tool_calls:
                            for tc in response.tool_calls:
                                tool_name = tc.get("tool", "")
                                result_dict = tc.get("result", {})
                                yield SSEEvent.tool_result(tool_name, result_dict)

                                # 检查是否需要发送卡片
                                if _should_send_card(tool_name, result_dict):
                                    card_type = _detect_card_type(tool_name, result_dict)
                                    if card_type:
                                        yield SSEEvent.card(card_type, result_dict.get("data", {}))

                                # 检查是否来自 interact 工具 → 发送交互式组件事件
                                if tool_name == "interact" and result_dict.get("success"):
                                    data = result_dict.get("data", {})
                                    component_type = data.get("component", "")
                                    if component_type in ("choice", "confirm", "form"):
                                        yield SSEEvent.interactive(component_type, data)

                    elif response.type == "suggestions":
                        # 后续问题建议（来自 LangGraph suggestions_node）
                        sugs = response.metadata.get("suggestions", []) if response.metadata else []
                        if sugs:
                            yield SSEEvent.suggestions(sugs)

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
        if not assistant_content:
            # LLM 未生成文本回复，进行容错降级
            if tool_calls_info:
                assistant_content = "我已为您查询了相关信息，请查看上方的结果卡片。如需更多帮助请继续提问。"
            else:
                assistant_content = "抱歉，我暂时无法生成回复，请稍后重试或联系人工客服。"
            yield SSEEvent.text(assistant_content)

        # 超时/异常时清除 tool_calls 元数据，避免泄漏到前端
        if timed_out:
            tool_calls_info = []

        # 保存消息到数据库（带超时保护，避免阻塞 SSE 流关闭）
        message_id = None
        try:
            message_id = await asyncio.wait_for(
                session_memory.save_message(
                    session_id=session_id,
                    role="assistant",
                    content=assistant_content,
                    tool_calls=tool_calls_info if tool_calls_info else None,
                    tenant_id=tenant_id,
                ),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"[chat/send] save_message timeout | session={session_id} tenant={tenant_id}"
            )
        except Exception as save_err:
            logger.error(
                f"[chat/send] save_message failed | session={session_id} error={save_err}",
                exc_info=True,
            )

        # suggestions 已在 LangGraph 图内的 suggestions_node 生成并通过流传递
        # 无需在此额外生成

        # 异步提取用户记忆（fire-and-forget，不阻塞 SSE 流）
        # user_message 提取自 message 参数（可能为 str 或 list）
        user_msg_text = message if isinstance(message, str) else (
            " ".join(p.get("text", "") for p in message if isinstance(p, dict) and p.get("type") == "text")
        ) if isinstance(message, list) else ""
        if assistant_content and user_msg_text:
            try:
                asyncio.create_task(
                    _extract_memories_async(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        user_message=user_msg_text,
                        assistant_reply=assistant_content,
                        session_id=session_id,
                    )
                )
            except Exception as mem_err:
                logger.debug(f"[chat/send] Memory extraction scheduling skipped: {mem_err}")

        # 发送完成事件（始终发送，即使 save_message 失败或超时）
        _done_sent = True
        yield SSEEvent.done(session_id, message_id)

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"[chat/send] Agent stream error: {tb}")
        yield SSEEvent.error(f"处理失败: {type(e).__name__}: {str(e)}")
    finally:
        # 仅在尚未发送 done 时补发，避免客户端收到重复 done 事件
        if not _done_sent:
            yield SSEEvent.done(session_id, None)
        logger.debug(f"[chat/send] SSE stream ended | session={session_id}")


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
    - event: card - 卡片数据（商品列表、订单等）
    - event: error - 错误信息
    - event: done - 对话完成
    
    心跳：每 15 秒发送一次 heartbeat
    """
    tenant_id = current_user.tenant_id
    user_id = current_user.user_id
    
    logger.info(
        f"[chat/send] Message received | tenant={tenant_id} user={user_id} session={request.session_id or 'new'} msg_len={len(request.message)}"
    )

    # 记录被忽略的上一轮建议（用于训练数据分析）
    if request.ignored_suggestions:
        import json as _json
        from app.utils.log_sanitizer import LogSanitizer
        for s in request.ignored_suggestions:
            logger.info(
                "[suggestion:feedback]",
                _json.dumps({
                    "session_id": request.session_id or "",
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "suggestion": LogSanitizer.mask_text(s),
                    "clicked": False,
                    "source": "ignored",
                }, ensure_ascii=False),
            )
    
    # 初始化组件
    session_memory = SessionMemory()
    tool_registry = get_tool_registry()
    
    # 根据用户角色选择 Agent 类型（配置驱动路由）
    from app.agents.agent_router import get_agent_router
    agent_router = get_agent_router()
    agent_type = agent_router.route(current_user)

    # 确定 Agent 角色（用于 ToolContext 权限检查）
    if current_user.role in ("admin", "agent", "tenant_admin"):
        agent_role = current_user.role
    else:
        agent_role = "customer"

    agent = get_agent(tool_registry, agent_type=agent_type)
    
    # 1. 创建或获取 session
    session_id = request.session_id
    if not session_id:
        # 创建新会话，并关闭该用户其他活跃会话
        session_id = await session_memory.create_session(
            tenant_id=tenant_id,
            customer_id=user_id,
            title=None,  # 自动生成标题
        )
        await session_memory.close_other_active_sessions(
            tenant_id=tenant_id,
            customer_id=user_id,
            except_session_id=session_id,
        )
    else:
        # 验证会话存在且属于当前用户
        session = await session_memory.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=404,
                detail=make_response(False, error_code="SESSION_NOT_FOUND", error_message="会话不存在")
            )
        # 先验证租户隔离
        if session.get("tenant_id") != tenant_id:
            logger.warning(
                f"Cross-tenant session access attempt: user_tenant={tenant_id}, "
                f"session_tenant={session.get('tenant_id')}, session_id={session_id}, "
                f"user_id={user_id}"
            )
            raise HTTPException(
                status_code=403,
                detail=make_response(False, error_code="PERMISSION_DENIED", error_message="无权访问该会话")
            )
        # 再验证用户所有权
        if session.get("customer_id") != user_id:
            logger.warning(
                f"Unauthorized session access attempt: user_id={user_id}, "
                f"session_owner={session.get('customer_id')}, session_id={session_id}, "
                f"tenant_id={tenant_id}"
            )
            raise HTTPException(
                status_code=403,
                detail=make_response(False, error_code="PERMISSION_DENIED", error_message="无权访问该会话")
            )
        # 拒绝在已关闭会话上发送消息
        if session.get("status") == "closed":
            logger.info(
                f"[chat/send] Reject send on closed session | session={session_id} user={user_id}"
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "success": False,
                    "error": {
                        "code": "SESSION_CLOSED",
                        "message": "该会话已结束，请创建新对话",
                    }
                }
            )
        # 方案 B：空闲超时自动关闭旧会话并新建
        try:
            last_msg_time = await session_memory.get_last_message_time(session_id)
            if last_msg_time is not None:
                now = datetime.now(timezone.utc)  # aware datetime，与 DB 返回一致
                if (now - last_msg_time) > timedelta(minutes=SESSION_IDLE_TIMEOUT_MINUTES):
                    logger.info(
                        f"[chat/send] Session idle timeout, rotating | session={session_id} "
                        f"last_msg={last_msg_time} threshold={SESSION_IDLE_TIMEOUT_MINUTES}min"
                    )
                    try:
                        await session_memory.close_session(session_id)
                    except Exception as close_err:
                        logger.warning(
                            f"[chat/send] close_session failed during rotation | "
                            f"session={session_id} error={close_err}"
                        )
                    # 新建会话承接本次发送，并关闭该用户其他活跃会话
                    session_id = await session_memory.create_session(
                        tenant_id=tenant_id,
                        customer_id=user_id,
                        title=None,
                    )
                    await session_memory.close_other_active_sessions(
                        tenant_id=tenant_id,
                        customer_id=user_id,
                        except_session_id=session_id,
                    )
                    # 方案 B：旧会话已因超时关闭，新会话承接
        except HTTPException:
            raise
        except Exception as idle_err:
            logger.warning(
                f"[chat/send] Idle-timeout check failed (non-fatal) | "
                f"session={session_id} error={idle_err}"
            )
    
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
            
            await session_memory.save_message(
                session_id=session_id,
                role="user",
                content=request.message,
                tenant_id=tenant_id,
                content_type=content_type,
                extra_metadata=extra_metadata,
            )
            
            # 3. 构建多模态消息内容
            if images:
                user_message_content: Union[str, List[Dict[str, Any]]] = [
                    {"type": "text", "text": request.message}
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

            # 4a. 如果历史超限，压缩早期消息为摘要
            if needs_compression:
                try:
                    from app.context.tracker import ConversationTracker
                    tracker = ConversationTracker()
                    history_messages = await tracker.compress_history(
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

            agent_context = AgentContext(
                user_id=user_id,
                tenant_id=tenant_id,
                session_id=session_id,
                role=agent_role,
                identity_type=current_user.identity_type,
                user_name=user_name,
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
            ):
                yield event
                
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"[chat/send] event_stream error: {tb}")
            yield SSEEvent.error(f"发生错误: {type(e).__name__}: {str(e)}")
    
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

    # 关闭该用户其他活跃会话，保持"一个用户一个活跃会话"语义
    await session_memory.close_other_active_sessions(
        tenant_id=current_user.tenant_id,
        customer_id=current_user.user_id,
        except_session_id=session_id,
    )

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

    session = await session_memory.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "message": "会话不存在",
                }
            },
        )

    if session.get("tenant_id") != current_user.tenant_id:
        logger.warning(
            f"Cross-tenant session close attempt: user_tenant={current_user.tenant_id}, "
            f"session_tenant={session.get('tenant_id')}, session_id={session_id}, "
            f"user_id={current_user.user_id}"
        )
        raise HTTPException(
            status_code=403,
            detail={
                "success": False,
                "error": {
                    "code": "PERMISSION_DENIED",
                    "message": "无权关闭该会话",
                }
            },
        )
    if session.get("customer_id") != current_user.user_id:
        logger.warning(
            f"Unauthorized session close attempt: user_id={current_user.user_id}, "
            f"session_owner={session.get('customer_id')}, session_id={session_id}, "
            f"tenant_id={current_user.tenant_id}"
        )
        raise HTTPException(
            status_code=403,
            detail={
                "success": False,
                "error": {
                    "code": "PERMISSION_DENIED",
                    "message": "无权关闭该会话",
                }
            },
        )

    # 幂等语义：已 closed 仍返回成功
    if session.get("status") == "closed":
        logger.info(f"[chat/close] Session already closed | session_id={session_id}")
        return make_response(True, data={
            "session_id": session_id,
            "status": "closed",
            "message": "会话已处于关闭状态",
        })

    await session_memory.close_session(session_id)
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
    session = await session_memory.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": {"code": "SESSION_NOT_FOUND", "message": "会话不存在"}},
        )
    if session.get("tenant_id") != current_user.tenant_id or session.get("customer_id") != current_user.user_id:
        raise HTTPException(
            status_code=403,
            detail={"success": False, "error": {"code": "PERMISSION_DENIED", "message": "无权操作该会话"}},
        )
    if session.get("status") != "closed":
        return make_response(True, data={"session_id": session_id, "status": session.get("status"), "message": "会话已是活跃状态"})

    await session_memory.reopen_session(session_id)
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
    
    # 验证会话存在且属于当前用户
    session = await session_memory.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "message": "会话不存在",
                }
            }
        )
    
    # 先验证租户隔离
    if session.get("tenant_id") != current_user.tenant_id:
        logger.warning(
            f"Cross-tenant session delete attempt: user_tenant={current_user.tenant_id}, "
            f"session_tenant={session.get('tenant_id')}, session_id={session_id}, "
            f"user_id={current_user.user_id}"
        )
        raise HTTPException(
            status_code=403,
            detail={
                "success": False,
                "error": {
                    "code": "PERMISSION_DENIED",
                    "message": "无权删除该会话",
                }
            }
        )
    # 再验证用户所有权
    if session.get("customer_id") != current_user.user_id:
        logger.warning(
            f"Unauthorized session delete attempt: user_id={current_user.user_id}, "
            f"session_owner={session.get('customer_id')}, session_id={session_id}, "
            f"tenant_id={current_user.tenant_id}"
        )
        raise HTTPException(
            status_code=403,
            detail={
                "success": False,
                "error": {
                    "code": "PERMISSION_DENIED",
                    "message": "无权删除该会话",
                }
            }
        )
    
    # 删除会话
    await session_memory.delete_session(session_id)
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
    
    # 验证会话存在且属于当前用户
    session = await session_memory.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "message": "会话不存在",
                }
            }
        )
    
    # 先验证租户隔离
    if session.get("tenant_id") != current_user.tenant_id:
        logger.warning(
            f"Cross-tenant history access attempt: user_tenant={current_user.tenant_id}, "
            f"session_tenant={session.get('tenant_id')}, session_id={session_id}, "
            f"user_id={current_user.user_id}"
        )
        raise HTTPException(
            status_code=403,
            detail={
                "success": False,
                "error": {
                    "code": "PERMISSION_DENIED",
                    "message": "无权访问该会话",
                }
            }
        )
    # 再验证用户所有权
    if session.get("customer_id") != current_user.user_id:
        logger.warning(
            f"Unauthorized history access attempt: user_id={current_user.user_id}, "
            f"session_owner={session.get('customer_id')}, session_id={session_id}, "
            f"tenant_id={current_user.tenant_id}"
        )
        raise HTTPException(
            status_code=403,
            detail={
                "success": False,
                "error": {
                    "code": "PERMISSION_DENIED",
                    "message": "无权访问该会话",
                }
            }
        )
    
    # 获取历史消息
    messages = await session_memory.get_history(session_id, limit=limit)
    
    # 格式化响应
    formatted_messages = []
    for msg in messages:
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
        
        formatted_messages.append({
            "id": msg["id"],
            "session_id": msg["session_id"],
            "role": msg["role"],
            "content": msg["content"],
            "content_type": msg.get("content_type", "text"),
            "images": msg_images if msg_images else None,
            "tool_calls": msg.get("tool_calls"),
            "created_at": _format_datetime(msg["created_at"]),
        })
    
    return make_response(True, data={
        "session_id": session_id,
        "messages": formatted_messages,
    })


@router.post("/suggestion-feedback")
async def suggestion_feedback(
    body: dict,
    current_user: UserIdentity = Depends(get_current_user),
):
    """
    记录建议反馈（点击），用于后续训练数据分析

    ⚠️ 数据安全：日志包含用户建议文本（已脱敏手机号/邮箱），
    应配置日志访问权限和保留策略。

    Body:
        session_id: str - 会话 ID
        suggestion: str - 被点击的建议文本
        message_id: str (optional) - 关联的消息 ID
    """
    import json as _json
    from app.utils.log_sanitizer import LogSanitizer
    logger.info(
        "[suggestion:feedback]",
        _json.dumps({
            "session_id": body.get("session_id", ""),
            "tenant_id": current_user.tenant_id,
            "user_id": current_user.user_id,
            "suggestion": LogSanitizer.mask_text(body.get("suggestion", "")),
            "clicked": True,
            "message_id": body.get("message_id", ""),
            "source": "click",
        }, ensure_ascii=False),
    )
    return {"ok": True}


@router.get("/quick-actions")
async def get_quick_actions(
    current_user: UserIdentity = Depends(get_current_user),
):
    """
    获取快捷功能菜单
    
    Returns:
        快捷功能列表
    """
    logger.debug(f"[chat/quick-actions] Fetching | tenant={current_user.tenant_id}")
    
    # B 端管理视角快捷操作（米宝定位：智能工作助手）
    actions = [
        {
            "id": "order_manage",
            "name": "订单管理",
            "icon": "clipboard-list",
            "prompt": "查看待处理订单",
        },
        {
            "id": "product_manage",
            "name": "商品管理",
            "icon": "package",
            "prompt": "查看商品列表",
        },
        {
            "id": "dashboard",
            "name": "经营看板",
            "icon": "bar-chart-3",
            "prompt": "查看今日经营数据",
        },
        {
            "id": "customer_manage",
            "name": "客户管理",
            "icon": "users",
            "prompt": "查看客户列表",
        },
    ]
    
    return make_response(True, data={
        "actions": actions,
    })
