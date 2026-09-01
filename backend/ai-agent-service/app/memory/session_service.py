"""
会话生命周期状态机 — 会话状态迁移的唯一写入者（会话管理重构 P2）。

设计（见 docs/design/session-management-redesign.md §3.1）：
- 状态迁移表集中定义：active ⇄ closed。
  - active → closed：用户手动关闭 / 转人工 / 空闲超时（后台任务）
  - closed → active：reopen（只恢复消息历史，工作状态从空开始）
  - closed → 物理删除：保留期后清理（delete/purge）
- 只有 SessionService 能改 sessions.status；API / graph / 后台任务都走它。
- 底层 SQL 委托 SessionMemory（close/reopen/close_idle/cleanup 已实现），
  本类负责状态机约束与守卫校验，避免语义散落。

注：DB sessions.status 只有 active / closed / waiting（schema 定义）。
「空闲超时」与「手动关闭」同落 closed，用 ended_at 区分；不引入 expired 状态
（避免与前端/历史 API 的 status 语义分叉，见设计文档 P3c 评估同理）。
"""

from typing import Any, Dict, Optional, Tuple

from loguru import logger


class SessionService:
    """会话生命周期唯一写入者"""

    # 状态迁移表：from → allowed to 集合
    STATE_TRANSITIONS = {
        "active": {"closed"},
        "closed": {"active"},
    }

    def __init__(self, memory=None):
        from app.memory.session_memory import SessionMemory
        self._memory = memory or SessionMemory()

    @classmethod
    def can_transition(cls, from_state: str, to_state: str) -> bool:
        """检查状态迁移是否合法"""
        return to_state in cls.STATE_TRANSITIONS.get(from_state, set())

    # ── 生命周期动作 ──

    async def close(self, session_id: str) -> bool:
        """active → closed（幂等：已 closed 返回 True）"""
        # 幂等语义与 SessionMemory.close_session 一致（本就 closed 也返回 True）
        return await self._memory.close_session(session_id)

    async def reopen(self, session_id: str) -> bool:
        """closed → active；非法状态（active 等）返回 False"""
        session = await self._memory.get_session(session_id)
        if not session:
            return False
        if not self.can_transition(session.get("status", ""), "active"):
            logger.info(
                f"[session-service] Reopen rejected | session={session_id} "
                f"status={session.get('status')}"
            )
            return False
        return await self._memory.reopen_session(session_id)

    async def delete(self, session_id: str) -> bool:
        """物理删除会话及消息（终态）"""
        return await self._memory.delete_session(session_id)

    async def expire_idle(self, idle_minutes: int = 30) -> int:
        """active → closed：批量关闭空闲会话（与手动 close 同落 closed）"""
        return await self._memory.close_idle_sessions(idle_minutes=idle_minutes)

    async def purge(self, older_than_days: int = 90) -> int:
        """closed → 物理清理：清理过期已关闭会话"""
        return await self._memory.cleanup_closed_sessions(older_than_days=older_than_days)

    # ── 发送守卫（供 API send/page 复用）──

    async def send_gate(
        self,
        session_id: str,
        *,
        tenant_id: int,
        user_id: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[str, str]]]:
        """校验会话可发送，返回 (session, error)。

        语义：
        - session_id 为空：返回 (None, None)，调用方负责创建新会话
        - 会话不存在：error = ("SESSION_NOT_FOUND", "会话不存在")
        - 跨租户 / 跨用户：error = ("PERMISSION_DENIED", "无权访问该会话")
        - 已关闭：error = ("SESSION_CLOSED", "该会话已结束，请创建新对话")
        - 合法：返回 (session, None) 并刷新 last_activity_at

        错误统一返回 (code, message) 元组，由 API 层用 make_response 格式化，
        避免 memory 层依赖 API 响应格式。
        """
        if not session_id:
            return None, None

        session = await self._memory.get_session(session_id)
        if not session:
            return None, ("SESSION_NOT_FOUND", "会话不存在")

        if session.get("tenant_id") != tenant_id:
            logger.warning(
                f"[session-service] Cross-tenant access | session={session_id} "
                f"user_tenant={tenant_id} session_tenant={session.get('tenant_id')}"
            )
            return None, ("PERMISSION_DENIED", "无权访问该会话")

        if session.get("customer_id") != user_id:
            logger.warning(
                f"[session-service] Cross-user access | session={session_id} "
                f"user={user_id} owner={session.get('customer_id')}"
            )
            return None, ("PERMISSION_DENIED", "无权访问该会话")

        if session.get("status") == "closed":
            return None, ("SESSION_CLOSED", "该会话已结束，请创建新对话")

        # 刷新活动时间（best-effort，失败不影响发送）
        try:
            await self._memory.touch_activity(session_id)
        except Exception as e:
            logger.debug(f"[session-service] touch_activity failed | session={session_id} error={e}")

        return session, None
