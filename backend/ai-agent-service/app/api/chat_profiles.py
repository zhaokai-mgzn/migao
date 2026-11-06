"""会话周边档案（`chat.py` 切片单元，issue #8725 第三档）。

## 单一职责
「这一轮对话周边要读/要写的**档案**」：用户昵称、企业名（Redis → DB 两跳，失败静默 None）、
会话标题生成、每轮记忆候选累积。**四者都是 fire-and-forget 或可降级**，没有一条是对话主链的判据。

## 搬运口径
定义逐行搬自 `app/api/chat.py`（未改一行实现、未删一条注释）。`chat.py` 保留同名 re-export，
既有调用点与 `patch("app.api.chat.<name>")` 的测试面因此**零改动**（见该文件的切片块注释）。
"""

from typing import Optional
from loguru import logger


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


async def _get_tenant_name(tenant_id: int) -> Optional[str]:
    """获取企业名称（Redis 缓存 → DB 回退）

    缓存 key: tenant_name:{tenant_id}，TTL 1 小时。
    用于黄金策 System Prompt 注入企业身份（此前 identity.md 硬编码"词元通达"，多租户下错误）。
    失败时静默返回 None（企业名非必需，身份模板有兜底措辞）。
    """
    cache_key = f"tenant_name:{tenant_id}"

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
        pass

    # 2. 缓存未命中，查 DB（tenants 表，与 admin-api 同库）
    try:
        from sqlalchemy import text
        from app.utils.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            sql = text("SELECT name FROM tenants WHERE id = :tenant_id AND deleted = 0")
            result = await db.execute(sql, {"tenant_id": tenant_id})
            row = result.fetchone()
            if row and row[0]:
                tenant_name = str(row[0])
                try:
                    from app.utils.redis_client import redis_pool
                    if redis_pool:
                        import redis.asyncio as aioredis
                        client = aioredis.Redis(connection_pool=redis_pool)
                        await client.setex(cache_key, 3600, tenant_name)
                except Exception:
                    pass
                return tenant_name
    except Exception as e:
        logger.warning(
            f"[chat] Failed to query tenant name | tenant={tenant_id} error={e}"
        )

    return None


async def _generate_title_async(
    session_id: str,
    user_message: str,
    assistant_reply: str,
) -> None:
    """fire-and-forget：用 LLM 根据首轮对话生成会话标题"""
    try:
        from app.memory.session_memory import SessionMemory
        sm = SessionMemory()
        session = await sm.get_session(session_id)
        if not session:
            return
        # 仅处理自动生成的默认标题
        title = (session.get("metadata", {}) or {}).get("title", "")
        if not title.startswith("会话 20"):
            return  # 已被手动设置过

        from app.llm.factory import LLMFactory
        llm = LLMFactory.create_summary_llm()
        prompt = (
            f"根据以下对话生成一个简短的会话标题（不超过10个字），只返回标题文本：\n"
            f"用户：{user_message[:100]}\n"
            f"助手：{assistant_reply[:200]}"
        )
        resp = await llm.ainvoke(prompt)
        new_title = (resp.content or "").strip().replace('"', '').replace("'", "")[:20]
        if new_title and new_title != title:
            await sm.update_session_title(session_id, new_title)
            logger.info(f"[chat/send] Title generated | session={session_id} title={new_title}")
    except Exception as e:
        # #4084：`update_session_title` 是**落库**写，且这里是 fire-and-forget ⇒ 失败只留一句
        # `debug` 在默认 INFO 级别下**等于没留痕**（#3357 的同款教训：user_memories 长期为 0
        # 却无人发现）。会话标题失败代价小，故不升到 ERROR/incident，但必须是可见的 warning。
        logger.warning(
            f"[chat/send] Session title update failed (non-fatal) | "
            f"session={session_id} error={type(e).__name__}: {e}"
        )


async def _extract_memories_async(
    tenant_id: int,
    user_id: str,
    user_message: str,
    assistant_reply: str,
    session_id: str,
    agent_type: str = "xiaobu",
) -> None:
    """fire-and-forget：每轮把记忆候选累积到会话状态（issue #2815 会话末聚合）。

    - 仅 xiaobu（C 端）累积；mibao 直接跳过
    - 候选按 key 去重累积于 session_states，会话关闭时由 flush_memories 批量落库
    - 失败不阻塞主流程（fire-and-forget 语义）
    """
    try:
        from app.memory.extractor import extract_and_accumulate
        count = await extract_and_accumulate(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_type=agent_type,
            session_id=session_id,
            user_message=user_message,
            assistant_reply=assistant_reply,
        )
        if count > 0:
            logger.debug(
                f"[chat/send] Memory accumulated | session={session_id} "
                f"agent={agent_type} count={count}"
            )
    except Exception as e:
        # warning 而非 debug（issue #3357）：记忆链路断掉时"什么都没发生"，
        # debug 级日志在默认 INFO 级别下不可见 —— 这正是 user_memories 长期为 0
        # 却无人发现的原因。失败必须可见。
        logger.warning(
            f"[chat/send] Memory accumulation failed (non-fatal) | session={session_id} "
            f"agent={agent_type} error={type(e).__name__}: {e}"
        )
