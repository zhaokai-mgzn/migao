"""
会话工作状态存储 — 跨轮工作状态的单一事实源（会话管理重构 P1）。

设计（见 docs/design/session-management-redesign.md §3.3）：
- 跨轮工作状态（entities / pending_skill / stage / vision_fields / last_skill / plan）
  从 sessions.metadata 与多套 Redis key 迁出，统一存于 PG `session_states` 表。
- 深模块接口：load / commit / clear 三个方法，调用方不感知存储细节。
- 序列化：state 为 JSON dict，整存整取；异常降级（读返回 None/{}，写返回 False），
  不抛出，与 SessionMemory 既有错误语义保持一致。
"""

import json
from typing import Any, Dict, Optional

from loguru import logger


class SessionStateStore:
    """会话工作状态存储（PG session_states 表）"""

    def __init__(self, db_session: Optional[Any] = None):
        self._db = db_session

    async def _get_session(self):
        """获取数据库会话（依赖注入或新建）"""
        if self._db is not None:
            return self._db
        from app.utils.database import AsyncSessionLocal
        return AsyncSessionLocal()

    async def load(self, session_id: str) -> Optional[Dict[str, Any]]:
        """读取会话工作状态。

        Returns:
            dict: 反序列化后的状态；会话不存在或 state 为空返回 {}；
                  DB 异常返回 None（调用方按"无状态"降级）。
        """
        if not session_id:
            return None
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                sql = text("""
                    SELECT state FROM session_states
                    WHERE session_id = :session_id
                """)
                result = await db.execute(sql, {"session_id": session_id})
                row = result.fetchone()
                if not row or not row[0]:
                    return None
                # asyncpg 对 jsonb 列返回 dict，对 text/varchar 返回 str；
                # 两类驱动行为都兼容：dict 原样返回，str 反序列化。
                state = row[0]
                if isinstance(state, dict):
                    return state
                return json.loads(state)
            except Exception as e:
                logger.warning(f"[session-state] load failed | session={session_id} error={e}")
                return None

    async def commit(self, session_id: str, state: Dict[str, Any]) -> bool:
        """写入会话工作状态（upsert 语义）。

        Returns:
            bool: 是否成功；DB 异常返回 False。
        """
        if not session_id:
            return False
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                sql = text("""
                    INSERT INTO session_states (session_id, state, updated_at)
                    VALUES (:session_id, CAST(:state AS jsonb), :now)
                    ON CONFLICT (session_id)
                    DO UPDATE SET state = EXCLUDED.state, updated_at = EXCLUDED.updated_at
                """)
                # naive utcnow 会被 asyncpg 按连接时区（Asia/Shanghai）解读 → 落库偏移 8h
                # （线上 sess_60238786c0694dbc 实证），必须用 timezone-aware UTC
                from datetime import datetime, timezone
                await db.execute(sql, {
                    "session_id": session_id,
                    "state": json.dumps(state or {}, ensure_ascii=False, default=str),
                    "now": datetime.now(timezone.utc),
                })
                await db.commit()
                return True
            except Exception as e:
                await db.rollback()
                logger.warning(f"[session-state] commit failed | session={session_id} error={e}")
                return False

    async def clear(self, session_id: str) -> bool:
        """清除会话工作状态。

        Returns:
            bool: 是否成功（幂等，会话不存在也返回 True）；DB 异常返回 False。
        """
        if not session_id:
            return False
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                sql = text("""
                    DELETE FROM session_states WHERE session_id = :session_id
                """)
                await db.execute(sql, {"session_id": session_id})
                await db.commit()
                return True
            except Exception as e:
                await db.rollback()
                logger.warning(f"[session-state] clear failed | session={session_id} error={e}")
                return False
