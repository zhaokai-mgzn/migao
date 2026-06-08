"""
AI 智能客服系统 - 用户记忆管理

跨会话持久化用户偏好、关键事实、反馈等。
每次对话结束后 LLM 自动提取，下次对话时注入 System Prompt。

表：user_memories（PostgreSQL）
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger


class UserMemoryManager:
    """用户记忆管理器（跨会话长期记忆）"""

    _INJECT_MIN_IMPORTANCE = 0.5  # 注入阈值：只注入 importance >= 此值的记忆

    def __init__(self, db_session: Optional[AsyncSession] = None):
        self._db = db_session

    async def _get_session(self) -> AsyncSession:
        if self._db is not None:
            return self._db
        from app.utils.database import AsyncSessionLocal
        return AsyncSessionLocal()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── 读取 ──

    async def get_important_memories(
        self,
        tenant_id: int,
        user_id: str,
        min_importance: float = None,
    ) -> List[Dict[str, Any]]:
        """获取用户的高重要性记忆（用于注入 System Prompt）

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            min_importance: 最低重要性阈值，默认 0.5

        Returns:
            记忆列表，按重要性降序排列
        """
        threshold = min_importance if min_importance is not None else self._INJECT_MIN_IMPORTANCE
        async with await self._get_session() as db:
            from sqlalchemy import text
            sql = text("""
                SELECT id, tenant_id, user_id, type, key, value,
                       importance, context, created_at, updated_at
                FROM user_memories
                WHERE tenant_id = :tenant_id AND user_id = :user_id
                  AND importance >= :min_importance
                ORDER BY importance DESC
                LIMIT 20
            """)
            result = await db.execute(sql, {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "min_importance": threshold,
            })
            rows = result.fetchall()
            memories = [
                {
                    "id": r[0], "tenant_id": r[1], "user_id": r[2],
                    "type": r[3], "key": r[4], "value": r[5],
                    "importance": r[6], "context": r[7],
                    "created_at": r[8], "updated_at": r[9],
                }
                for r in rows
            ]
            if memories:
                logger.debug(
                    f"[user-memory] Loaded {len(memories)} memories | "
                    f"tenant={tenant_id} user={user_id}"
                )
            return memories

    async def format_for_prompt(
        self,
        tenant_id: int,
        user_id: str,
    ) -> str:
        """将用户记忆格式化为 System Prompt 注入文本

        Returns:
            XML 格式的记忆文本，无记忆时返回空字符串
        """
        memories = await self.get_important_memories(tenant_id, user_id)
        if not memories:
            return ""

        # 按类型分组
        preferences = [m for m in memories if m["type"] == "preference"]
        facts = [m for m in memories if m["type"] == "fact"]
        feedbacks = [m for m in memories if m["type"] == "feedback"]

        lines = ["<user_memories>"]
        if preferences:
            lines.append("  <preferences>")
            for m in preferences:
                lines.append(f"    {m['value']}")
            lines.append("  </preferences>")
        if facts:
            lines.append("  <facts>")
            for m in facts:
                lines.append(f"    {m['key']}: {m['value']}")
            lines.append("  </facts>")
        if feedbacks:
            lines.append("  <feedback>")
            for m in feedbacks:
                lines.append(f"    {m['value']}")
            lines.append("  </feedback>")
        lines.append("</user_memories>")

        formatted = "\n".join(lines)
        logger.debug(
            f"[user-memory] Formatted for prompt | "
            f"tenant={tenant_id} user={user_id} len={len(formatted)}"
        )
        return formatted

    # ── 写入 ──

    async def upsert(
        self,
        tenant_id: int,
        user_id: str,
        type_: str,
        key: str,
        value: str,
        importance: float = 0.5,
        context: str = "",
        related_to: Optional[List[str]] = None,
    ) -> Optional[str]:
        """写入或更新一条记忆（按 tenant_id + user_id + key 去重）

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            type_: 记忆类型（preference / fact / feedback / reference）
            key: 记忆 key
            value: 记忆值
            importance: 重要性 (0-1)
            context: 记录时的上下文
            related_to: 关联记忆 ID 列表

        Returns:
            记忆 ID，失败返回 None
        """
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text

                # 先查是否存在
                check_sql = text("""
                    SELECT id FROM user_memories
                    WHERE tenant_id = :tenant_id AND user_id = :user_id AND key = :key
                """)
                check_result = await db.execute(check_sql, {
                    "tenant_id": tenant_id, "user_id": user_id, "key": key,
                })
                existing = check_result.fetchone()

                if existing:
                    memory_id = existing[0]
                    update_sql = text("""
                        UPDATE user_memories
                        SET value = :value, importance = :importance,
                            context = :context, related_to = CAST(:related_to AS text[]),
                            updated_at = NOW()
                        WHERE id = :id
                    """)
                    await db.execute(update_sql, {
                        "id": memory_id, "value": value, "importance": importance,
                        "context": context,
                        "related_to": related_to if related_to else [],
                    })
                    logger.debug(
                        f"[user-memory] Updated | id={memory_id} key={key}"
                    )
                else:
                    memory_id = f"mem_{uuid.uuid4().hex[:16]}"
                    insert_sql = text("""
                        INSERT INTO user_memories
                        (id, tenant_id, user_id, type, key, value, importance, context, related_to)
                        VALUES (:id, :tenant_id, :user_id, :type, :key, :value,
                                :importance, :context, CAST(:related_to AS text[]))
                    """)
                    await db.execute(insert_sql, {
                        "id": memory_id, "tenant_id": tenant_id, "user_id": user_id,
                        "type": type_, "key": key, "value": value,
                        "importance": importance, "context": context,
                        "related_to": related_to if related_to else [],
                    })
                    logger.info(
                        f"[user-memory] Created | id={memory_id} type={type_} key={key} "
                        f"user={user_id}"
                    )

                await db.commit()
                return memory_id

            except Exception as e:
                await db.rollback()
                logger.warning(
                    f"[user-memory] Upsert failed | user={user_id} key={key} error={e}"
                )
                return None

    async def batch_upsert(
        self,
        tenant_id: int,
        user_id: str,
        items: List[Dict[str, Any]],
    ) -> int:
        """批量写入记忆

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            items: 记忆列表，每项含 type, key, value, importance(可选), context(可选)

        Returns:
            成功写入的条数
        """
        count = 0
        for item in items:
            rid = await self.upsert(
                tenant_id=tenant_id,
                user_id=user_id,
                type_=item.get("type", "fact"),
                key=item.get("key", ""),
                value=item.get("value", ""),
                importance=item.get("importance", 0.5),
                context=item.get("context", ""),
                related_to=item.get("related_to"),
            )
            if rid:
                count += 1
        return count

    # ── 衰减 ──

    async def decay_importance(
        self,
        tenant_id: int,
        user_id: str,
        decay_factor: float = 0.9,
    ) -> int:
        """衰减所有记忆的重要性（未确认的记忆逐渐降低权重）

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            decay_factor: 衰减因子，每次乘以该值

        Returns:
            受影响的条数
        """
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                sql = text("""
                    UPDATE user_memories
                    SET importance = GREATEST(importance * :factor, 0.1)
                    WHERE tenant_id = :tenant_id AND user_id = :user_id
                      AND type != 'feedback'  -- 反馈类不衰减
                """)
                result = await db.execute(sql, {
                    "tenant_id": tenant_id, "user_id": user_id, "factor": decay_factor,
                })
                await db.commit()
                affected = result.rowcount or 0
                if affected > 0:
                    logger.debug(
                        f"[user-memory] Decayed {affected} memories | "
                        f"tenant={tenant_id} user={user_id}"
                    )
                return affected
            except Exception as e:
                await db.rollback()
                logger.warning(f"[user-memory] Decay failed: {e}")
                return 0

    # ── 清理 ──

    async def delete(self, memory_id: str) -> bool:
        """删除单条记忆"""
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                await db.execute(text("DELETE FROM user_memories WHERE id = :id"), {"id": memory_id})
                await db.commit()
                return True
            except Exception as e:
                await db.rollback()
                logger.warning(f"[user-memory] Delete failed: {e}")
                return False

    async def delete_by_key(self, tenant_id: int, user_id: str, key: str) -> bool:
        """按 key 删除记忆"""
        async with await self._get_session() as db:
            try:
                from sqlalchemy import text
                result = await db.execute(
                    text("DELETE FROM user_memories WHERE tenant_id = :tid AND user_id = :uid AND key = :key"),
                    {"tid": tenant_id, "uid": user_id, "key": key},
                )
                await db.commit()
                return (result.rowcount or 0) > 0
            except Exception as e:
                await db.rollback()
                logger.warning(f"[user-memory] Delete by key failed: {e}")
                return False
