"""
AI 智能客服系统 - 会话记忆管理

管理会话消息（短期记忆），存储于 PostgreSQL 的 session_messages 表
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger



class SessionMemory:
    """会话消息管理（短期记忆）"""
    
    def __init__(self, db_session: Optional[AsyncSession] = None):
        """
        初始化 SessionMemory
        
        Args:
            db_session: 可选的数据库会话，如果不传则每次操作创建新会话
        """
        self._db = db_session
    
    async def _get_session(self) -> AsyncSession:
        """获取数据库会话"""
        if self._db is not None:
            return self._db
        # 创建新会话（用于依赖注入场景）
        from app.utils.database import AsyncSessionLocal
        return AsyncSessionLocal()
    
    def _generate_session_id(self) -> str:
        """生成会话 ID"""
        return f"sess_{uuid.uuid4().hex[:16]}"
    
    def _generate_message_id(self) -> str:
        """生成消息 ID"""
        return f"msg_{uuid.uuid4().hex[:16]}"
    
    def _now_iso(self) -> str:
        """获取当前时间 ISO 格式"""
        return datetime.utcnow().isoformat() + "Z"
    
    def _now(self) -> datetime:
        """获取当前 UTC 时间（datetime 对象，asyncpg 需要）"""
        return datetime.utcnow()
    
    async def create_session(
        self, 
        tenant_id: int, 
        customer_id: str, 
        title: Optional[str] = None,
        channel: str = "web"
    ) -> str:
        """
        创建新会话，返回 session_id
        
        Args:
            tenant_id: 租户 ID
            customer_id: 客户 ID
            title: 会话标题（存储在 metadata JSON 中）
            channel: 渠道类型 (wechat_mini / wechat_h5 / web)
            
        Returns:
            str: 新创建的会话 ID
        """
        session_id = self._generate_session_id()
        now = self._now()
        
        # 自动生成标题
        if not title:
            title = f"会话 {now.strftime('%Y-%m-%d')}"
        
        # sessions 表无 title 列，存入 metadata JSON
        import json
        metadata = json.dumps({"title": title})
        
        # 使用原始 SQL 插入会话记录
        # 表结构: sessions(id, tenant_id, customer_id, channel, status, metadata, created_at, updated_at)
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                sql = text("""
                    INSERT INTO sessions (id, tenant_id, customer_id, channel, status, metadata, created_at, updated_at)
                    VALUES (:id, :tenant_id, :customer_id, :channel, 'active', CAST(:metadata AS jsonb), :created_at, :updated_at)
                """)
                await db.execute(sql, {
                    "id": session_id,
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "channel": channel,
                    "metadata": metadata,
                    "created_at": now,
                    "updated_at": now,
                })
                await db.commit()
                logger.info(f"[session-memory] Session created | session_id={session_id} tenant={tenant_id}")
                return session_id
            except Exception as e:
                await db.rollback()
                logger.warning(f"[session-memory] Transaction rolled back | session_id={session_id} error={e}")
                logger.error(f"[session-memory] Operation failed | session_id={session_id} error={type(e).__name__}: {e}", exc_info=True)
                raise
    
    async def save_message(
        self, 
        session_id: str, 
        role: str, 
        content: str, 
        tool_calls: Optional[List[dict]] = None,
        tenant_id: Optional[int] = None,
        content_type: str = "text",
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        保存消息到 session_messages 表
        
        Args:
            session_id: 会话 ID
            role: 消息角色 (user / assistant / system / tool)
            content: 消息内容
            tool_calls: Tool 调用信息（存储在 metadata JSON 中）
            tenant_id: 租户 ID（可选）
            content_type: 内容类型 (text / mixed / image / card 等)
            extra_metadata: 额外的 metadata 字段（如 images 等）
            
        Returns:
            str: 消息 ID
        """
        message_id = self._generate_message_id()
        now = self._now()
        
        # session_messages 表无 tool_calls / user_id 列，tool_calls 存入 metadata
        import json
        meta_dict = {}
        if tool_calls:
            meta_dict["tool_calls"] = tool_calls
        if extra_metadata:
            meta_dict.update(extra_metadata)
        metadata = json.dumps(meta_dict) if meta_dict else "{}"
        
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                sql = text("""
                    INSERT INTO session_messages 
                    (id, session_id, role, content_type, content, metadata, tenant_id, created_at)
                    VALUES (:id, :session_id, :role, :content_type, :content, CAST(:metadata AS jsonb), :tenant_id, :created_at)
                """)
                await db.execute(sql, {
                    "id": message_id,
                    "session_id": session_id,
                    "role": role,
                    "content_type": content_type,
                    "content": content,
                    "metadata": metadata,
                    "tenant_id": tenant_id,
                    "created_at": now,
                })
                
                # 更新会话的 updated_at
                update_sql = text("""
                    UPDATE sessions 
                    SET updated_at = :updated_at 
                    WHERE id = :session_id
                """)
                await db.execute(update_sql, {
                    "session_id": session_id,
                    "updated_at": self._now(),
                })
                
                await db.commit()
                logger.debug(f"[session-memory] Message saved | session_id={session_id} role={role}")
                logger.debug(f"[session-memory] Session updated | session_id={session_id}")
                return message_id
            except Exception as e:
                await db.rollback()
                logger.warning(f"[session-memory] Transaction rolled back | session_id={session_id} error={e}")
                logger.error(f"[session-memory] Operation failed | session_id={session_id} error={type(e).__name__}: {e}", exc_info=True)
                raise
    
    async def get_history(
        self, 
        session_id: str, 
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        获取会话历史消息
        
        Args:
            session_id: 会话 ID
            limit: 返回消息数量限制
            
        Returns:
            List[dict]: 消息列表，按时间正序排列
        """
        logger.debug(f"[session-memory] Loading messages | session_id={session_id}")
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                sql = text("""
                    SELECT id, session_id, role, content_type, content, metadata, created_at
                    FROM session_messages
                    WHERE session_id = :session_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                """)
                result = await db.execute(sql, {
                    "session_id": session_id,
                    "limit": limit,
                })
                rows = result.fetchall()
                
                # 转换为字典列表并反转顺序（正序）
                messages = []
                for row in reversed(rows):
                    # 从 metadata 中提取 tool_calls（降级处理）
                    metadata = row[5] or {}
                    tool_calls = metadata.get("tool_calls") if isinstance(metadata, dict) else None
                    messages.append({
                        "id": row[0],
                        "session_id": row[1],
                        "role": row[2],
                        "content_type": row[3],
                        "content": row[4],
                        "tool_calls": tool_calls,
                        "metadata": metadata,
                        "created_at": row[6],
                    })
                
                return messages
            except Exception as e:
                logger.error(f"[session-memory] Operation failed | session_id={session_id} error={type(e).__name__}: {e}", exc_info=True)
                return []
    
    async def get_sessions(
        self, 
        tenant_id: int, 
        customer_id: str, 
        page: int = 1, 
        size: int = 20
    ) -> List[Dict[str, Any]]:
        """
        获取客户的会话列表
        
        Args:
            tenant_id: 租户 ID
            customer_id: 客户 ID
            page: 页码，从 1 开始
            size: 每页数量
            
        Returns:
            List[dict]: 会话列表
        """
        offset = (page - 1) * size
        
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                # 获取会话列表及消息数量、状态、最后一条消息、客户名称
                sql = text("""
                    SELECT 
                        s.id, s.tenant_id, s.customer_id, s.metadata,
                        s.created_at, s.updated_at,
                        COUNT(m.id) as message_count,
                        s.status,
                        (
                            SELECT SUBSTRING(sm.content FROM 1 FOR 100)
                            FROM session_messages sm
                            WHERE sm.session_id = s.id
                            ORDER BY sm.created_at DESC
                            LIMIT 1
                        ) as last_message,
                        u.nickname as customer_name
                    FROM sessions s
                    LEFT JOIN session_messages m ON s.id = m.session_id
                    LEFT JOIN users u ON s.customer_id = u.id
                    WHERE s.tenant_id = :tenant_id AND s.customer_id = :customer_id
                    GROUP BY s.id, s.tenant_id, s.customer_id, s.metadata,
                             s.created_at, s.updated_at, s.status, u.nickname
                    ORDER BY s.updated_at DESC
                    LIMIT :limit OFFSET :offset
                """)
                result = await db.execute(sql, {
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "limit": size,
                    "offset": offset,
                })
                rows = result.fetchall()
                
                sessions = []
                for row in rows:
                    metadata = row[3] or {}
                    title = metadata.get("title") if isinstance(metadata, dict) else None
                    sessions.append({
                        "id": row[0],
                        "tenant_id": row[1],
                        "customer_id": row[2],
                        "title": title,
                        "metadata": metadata,
                        "created_at": row[4],
                        "updated_at": row[5],
                        "message_count": row[6],
                        "status": row[7] or "active",
                        "last_message": row[8],
                        "customer_name": row[9],
                    })
                
                return sessions
            except Exception as e:
                logger.error(f"[session-memory] Operation failed | session_id=list tenant={tenant_id} error={type(e).__name__}: {e}", exc_info=True)
                return []
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单个会话信息
        
        Args:
            session_id: 会话 ID
            
        Returns:
            Optional[dict]: 会话信息，不存在则返回 None
        """
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                sql = text("""
                    SELECT id, tenant_id, customer_id, metadata, status, channel, created_at, updated_at
                    FROM sessions
                    WHERE id = :session_id
                """)
                result = await db.execute(sql, {"session_id": session_id})
                row = result.fetchone()
                
                if row:
                    metadata = row[3] or {}
                    title = metadata.get("title") if isinstance(metadata, dict) else None
                    return {
                        "id": row[0],
                        "tenant_id": row[1],
                        "customer_id": row[2],
                        "title": title,
                        "metadata": metadata,
                        "status": row[4],
                        "channel": row[5],
                        "created_at": row[6],
                        "updated_at": row[7],
                    }
                return None
            except Exception as e:
                logger.error(f"[session-memory] Operation failed | session_id={session_id} error={type(e).__name__}: {e}", exc_info=True)
                return None
    
    async def session_exists(self, session_id: str) -> bool:
        """
        检查会话是否存在
        
        Args:
            session_id: 会话 ID
            
        Returns:
            bool: 是否存在
        """
        session = await self.get_session(session_id)
        return session is not None
    
    async def close_session(self, session_id: str) -> bool:
        """
        关闭会话：将 status 置为 'closed'，并记录 ended_at；不删除任何消息。

        Args:
            session_id: 会话 ID

        Returns:
            bool: 实际更新的会话是否存在（True 表示已关闭或本就 closed）
        """
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                sql = text("""
                    UPDATE sessions
                    SET status = 'closed',
                        ended_at = COALESCE(ended_at, :now),
                        updated_at = :now
                    WHERE id = :session_id
                """)
                result = await db.execute(sql, {
                    "session_id": session_id,
                    "now": self._now(),
                })
                await db.commit()
                affected = result.rowcount or 0
                logger.info(
                    f"[session-memory] Session closed | session_id={session_id} affected={affected}"
                )
                return affected > 0
            except Exception as e:
                await db.rollback()
                logger.error(
                    f"[session-memory] Close session failed | session_id={session_id} error={type(e).__name__}: {e}",
                    exc_info=True,
                )
                raise

    async def close_other_active_sessions(
        self,
        tenant_id: int,
        customer_id: str,
        except_session_id: Optional[str] = None,
    ) -> int:
        """
        批量关闭某用户在某租户下其他 active 会话。

        Args:
            tenant_id: 租户 ID
            customer_id: 客户/用户 ID
            except_session_id: 排除该会话（一般是新创建/当前活跃的会话）

        Returns:
            int: 被关闭的会话数量
        """
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                params = {
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "now": self._now(),
                }
                exclude_clause = ""
                if except_session_id:
                    exclude_clause = "AND id <> :except_id"
                    params["except_id"] = except_session_id
                sql = text(f"""
                    UPDATE sessions
                    SET status = 'closed',
                        ended_at = COALESCE(ended_at, :now),
                        updated_at = :now
                    WHERE tenant_id = :tenant_id
                      AND customer_id = :customer_id
                      AND status = 'active'
                      {exclude_clause}
                """)
                result = await db.execute(sql, params)
                await db.commit()
                affected = result.rowcount or 0
                if affected > 0:
                    logger.info(
                        f"[session-memory] Closed other active sessions | "
                        f"tenant={tenant_id} user={customer_id} affected={affected} "
                        f"except={except_session_id}"
                    )
                return affected
            except Exception as e:
                await db.rollback()
                logger.error(
                    f"[session-memory] Close other active sessions failed | "
                    f"tenant={tenant_id} user={customer_id} error={type(e).__name__}: {e}",
                    exc_info=True,
                )
                return 0

    async def set_pending_skill(self, session_id: str, skill_name: str) -> bool:
        """持久化 pending_interact_skill 到 session metadata

        用于跨 graph 调用维持交互连续性。
        用户回应交互组件后，下一轮路由时加载此值跳过 L1/L2 分类。

        Args:
            session_id: 会话 ID
            skill_name: 当前 skill 名称

        Returns:
            bool: 是否成功
        """
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                sql = text("""
                    UPDATE sessions
                    SET metadata = jsonb_set(
                        COALESCE(metadata, '{}'::jsonb),
                        '{pending_skill}',
                        :skill_json
                    )
                    WHERE id = :session_id
                """)
                await db.execute(sql, {
                    "session_id": session_id,
                    "skill_json": f'"{skill_name}"',
                })
                await db.commit()
                logger.debug(
                    f"[session-memory] Pending skill set | "
                    f"session={session_id} skill={skill_name}"
                )
                return True
            except Exception as e:
                await db.rollback()
                logger.warning(f"[session-memory] set_pending_skill failed: {e}")
                return False

    async def get_pending_skill(self, session_id: str) -> str:
        """读取 pending_interact_skill

        Args:
            session_id: 会话 ID

        Returns:
            str: skill 名称，无则空字符串
        """
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                sql = text("""
                    SELECT metadata->>'pending_skill' AS pending_skill
                    FROM sessions WHERE id = :session_id
                """)
                result = await db.execute(sql, {"session_id": session_id})
                row = result.fetchone()
                val = row[0] if row else ""
                return val or ""
            except Exception as e:
                logger.warning(f"[session-memory] get_pending_skill failed: {e}")
                return ""

    async def clear_pending_skill(self, session_id: str) -> bool:
        """清除 pending_interact_skill"""
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                sql = text("""
                    UPDATE sessions
                    SET metadata = COALESCE(metadata, '{}'::jsonb) - 'pending_skill'
                    WHERE id = :session_id
                """)
                await db.execute(sql, {"session_id": session_id})
                await db.commit()
                return True
            except Exception as e:
                await db.rollback()
                logger.warning(f"[session-memory] clear_pending_skill failed: {e}")
                return False

    async def get_last_message_time(self, session_id: str) -> Optional[datetime]:
        """
        获取会话最后一条消息的创建时间，用于空闲超时判断。

        Args:
            session_id: 会话 ID

        Returns:
            Optional[datetime]: 最后消息时间；若无消息则返回 None
        """
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                sql = text("""
                    SELECT created_at FROM session_messages
                    WHERE session_id = :session_id
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
                result = await db.execute(sql, {"session_id": session_id})
                row = result.fetchone()
                return row[0] if row else None
            except Exception as e:
                logger.error(
                    f"[session-memory] Get last message time failed | session_id={session_id} error={type(e).__name__}: {e}",
                    exc_info=True,
                )
                return None

    async def delete_session(self, session_id: str) -> bool:
        """
        删除会话及其所有消息
        
        Args:
            session_id: 会话 ID
            
        Returns:
            bool: 是否成功删除
        """
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                # 先删除消息
                delete_messages_sql = text("""
                    DELETE FROM session_messages WHERE session_id = :session_id
                """)
                await db.execute(delete_messages_sql, {"session_id": session_id})
                
                # 再删除会话
                delete_session_sql = text("""
                    DELETE FROM sessions WHERE id = :session_id
                """)
                await db.execute(delete_session_sql, {"session_id": session_id})
                
                await db.commit()
                logger.info(f"[session-memory] Session deleted | session_id={session_id}")
                return True
            except Exception as e:
                await db.rollback()
                logger.warning(f"[session-memory] Transaction rolled back | session_id={session_id} error={e}")
                logger.error(f"[session-memory] Operation failed | session_id={session_id} error={type(e).__name__}: {e}", exc_info=True)
                raise
