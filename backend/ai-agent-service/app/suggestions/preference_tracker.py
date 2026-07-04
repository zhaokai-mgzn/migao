"""
用户建议偏好追踪器

记录用户点击建议的行为，用于个性化推荐。
- 写入：每次用户点击建议时 upsert（click_count + 1）
- 读取：生成建议时查询用户 TOP N 偏好意图

数据存储：PostgreSQL user_suggestion_prefs 表（与 admin-api 共享）
"""

from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger


# ──────────────── intent → 中文标签映射 ────────────────

INTENT_LABELS: dict[str, str] = {
    "order_query": "订单查询",
    "order_create": "创建订单",
    "logistics_track": "物流跟踪",
    "after_sales": "售后管理",
    "after_sales_create": "创建售后",
    "complaint": "投诉处理",
    "product_inquiry": "商品查询",
    "category_manage": "分类管理",
    "processing_manage": "加工项管理",
    "customer_manage": "客户管理",
    "customer_query": "客户查询",
    "employee_manage": "员工管理",
    "staff_manage": "人事管理",
    "role_manage": "角色管理",
    "permission_manage": "权限管理",
    "system_settings": "系统设置",
    "ai_config": "AI配置",
    "notification": "通知管理",
    "quick_reply": "快捷回复",
    "dashboard": "经营看板",
    "statistics": "数据统计",
    "data_report": "数据报表",
    "session_manage": "会话管理",
    "knowledge_faq": "知识问答",
    "knowledge_manage": "知识库管理",
    "greeting": "问候",
    "capabilities": "功能探索",
    "general": "通用查询",
}


def _intent_label(intent_type: str) -> str:
    """获取意图的中文标签"""
    return INTENT_LABELS.get(intent_type, intent_type)


class PreferenceTracker:
    """用户建议偏好追踪器"""

    def __init__(self, db_session: Optional[AsyncSession] = None):
        self._db = db_session

    async def _get_session(self) -> AsyncSession:
        """获取数据库会话"""
        if self._db is not None:
            return self._db
        from app.utils.database import AsyncSessionLocal
        return AsyncSessionLocal()

    async def record_click(
        self,
        tenant_id: int,
        user_id: int,
        intent_type: str,
        suggestion_text: str = "",
    ) -> None:
        """记录一次建议点击（upsert: click_count + 1）

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            intent_type: 当前对话的意图类型
            suggestion_text: 被点击的建议文本（仅用于日志）
        """
        if not tenant_id or not user_id:
            return

        db = await self._get_session()
        try:
            sql = text("""
                INSERT INTO user_suggestion_prefs (tenant_id, user_id, intent_type, click_count, last_clicked_at, created_at, updated_at)
                VALUES (:tenant_id, :user_id, :intent_type, 1, NOW(), NOW(), NOW())
                ON CONFLICT (tenant_id, user_id, intent_type)
                DO UPDATE SET
                    click_count = user_suggestion_prefs.click_count + 1,
                    last_clicked_at = NOW(),
                    updated_at = NOW()
            """)
            await db.execute(sql, {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "intent_type": intent_type,
            })
            await db.commit()
            logger.debug(
                f"[preference] recorded click: tenant={tenant_id} user={user_id} "
                f"intent={intent_type} suggestion={suggestion_text[:50]}"
            )
        except Exception as e:
            await db.rollback()
            logger.warning(f"[preference] failed to record click: {e}")
        finally:
            if self._db is None:
                await db.close()

    async def get_top_intents(
        self,
        tenant_id: int,
        user_id: int,
        limit: int = 5,
    ) -> list[dict]:
        """获取用户 TOP N 偏好意图

        Returns:
            [{"intent_type": "order_query", "click_count": 12, "label": "订单查询"}, ...]
        """
        if not tenant_id or not user_id:
            return []

        db = await self._get_session()
        try:
            sql = text("""
                SELECT intent_type, click_count
                FROM user_suggestion_prefs
                WHERE tenant_id = :tenant_id AND user_id = :user_id
                ORDER BY click_count DESC, last_clicked_at DESC
                LIMIT :limit
            """)
            result = await db.execute(sql, {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "limit": limit,
            })
            rows = result.fetchall()
            return [
                {
                    "intent_type": row[0],
                    "click_count": row[1],
                    "label": _intent_label(row[0]),
                }
                for row in rows
            ]
        except Exception as e:
            logger.warning(f"[preference] failed to query top intents: {e}")
            return []
        finally:
            if self._db is None:
                await db.close()

    async def get_user_stats(
        self,
        tenant_id: int,
        user_id: int,
    ) -> dict:
        """获取用户偏好统计摘要

        Returns:
            {"total_clicks": 42, "top_intents": [...], "distinct_intents": 5}
        """
        if not tenant_id or not user_id:
            return {"total_clicks": 0, "top_intents": [], "distinct_intents": 0}

        db = await self._get_session()
        try:
            sql = text("""
                SELECT
                    COALESCE(SUM(click_count), 0) as total_clicks,
                    COUNT(*) as distinct_intents
                FROM user_suggestion_prefs
                WHERE tenant_id = :tenant_id AND user_id = :user_id
            """)
            result = await db.execute(sql, {
                "tenant_id": tenant_id,
                "user_id": user_id,
            })
            row = result.fetchone()
            top_intents = await self.get_top_intents(tenant_id, user_id, limit=5)
            return {
                "total_clicks": row[0] if row else 0,
                "distinct_intents": row[1] if row else 0,
                "top_intents": top_intents,
            }
        except Exception as e:
            logger.warning(f"[preference] failed to query user stats: {e}")
            return {"total_clicks": 0, "top_intents": [], "distinct_intents": 0}
        finally:
            if self._db is None:
                await db.close()
