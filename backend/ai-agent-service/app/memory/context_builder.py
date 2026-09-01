"""
上下文构建管道（会话管理重构 P3）

职责：
- compress_history：超限时压缩早期消息为摘要（原 ConversationTracker 职责，已迁入）
- 压缩摘要回写 SessionStateStore（state.summary），并在下次压缩时读回并入输入，
  形成滚动摘要（历史累积不丢）。

设计（见 docs/design/session-management-redesign.md §3.5）：
历史窗口 → 压缩 → 摘要回写（滚动），集中一处、可测试。
实体/vision 注入仍由 AgentContextManager.build_context 承担（单一实现）。
"""

from typing import Any, Dict, List

from loguru import logger

from app.memory.session_state_store import SessionStateStore


class ContextBuilder:
    """上下文构建管道（历史压缩）"""

    # ========== 历史压缩（原 tracker.compress_history）==========

    async def compress_history(
        self,
        chat_history: List[Dict[str, Any]],
        session_id: str,
        max_turns: int = 10,
        keep_recent: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        对话历史压缩：超过 max_turns 轮时，对早期历史做摘要。

        一轮 = 一组 user + assistant。压缩摘要回写 SessionStateStore（state.summary），
        并在下次压缩时读回作为「更早历史」并入输入，形成滚动摘要（历史不丢、累积）。

        Args:
            chat_history: 完整的对话历史列表
            session_id: 会话 ID
            max_turns: 超过此轮数时触发压缩
            keep_recent: 保留最近的完整轮数

        Returns:
            压缩后的对话历史
        """
        if not chat_history:
            return chat_history

        # 计算轮数（以 user 消息计）
        user_count = sum(1 for m in chat_history if m.get("role") == "user")
        if user_count <= max_turns:
            return chat_history

        logger.info(
            f"[context-builder] Compressing history: {user_count} turns > {max_turns}, "
            f"session={session_id}"
        )

        keep_idx = self._find_keep_boundary(chat_history, keep_recent)
        early_history = chat_history[:keep_idx]
        recent_history = chat_history[keep_idx:]

        if not early_history:
            return chat_history

        # 读回已有摘要，作为「更早历史」并入本次摘要输入（滚动摘要）
        previous_summary = None
        try:
            store = SessionStateStore()
            existing = await store.load(session_id)
            previous_summary = (existing or {}).get("summary")
        except Exception as e:
            logger.warning(f"[context-builder] load previous summary failed: {e}")

        summary = await self._summarize_history(
            early_history, session_id, previous_summary=previous_summary
        )

        # 摘要回写工作状态（合并语义，不覆盖其它字段）
        try:
            store = SessionStateStore()
            existing = await store.load(session_id) or {}
            existing["summary"] = summary
            await store.commit(session_id, existing)
        except Exception as e:
            logger.warning(f"[context-builder] summary writeback failed: {e}")

        compressed: List[Dict[str, Any]] = [
            {
                "role": "system",
                "content": f"[以下是早期对话摘要]\n{summary}",
                "content_type": "text",
            }
        ]
        compressed.extend(recent_history)
        return compressed

    @staticmethod
    def _find_keep_boundary(
        chat_history: List[Dict[str, Any]], keep_recent: int
    ) -> int:
        """找到应保留的最近 N 轮的起始索引"""
        user_indices = [
            i for i, m in enumerate(chat_history) if m.get("role") == "user"
        ]
        if len(user_indices) <= keep_recent:
            return 0
        return user_indices[-keep_recent]

    async def _summarize_history(
        self,
        history: List[Dict[str, Any]],
        session_id: str,
        previous_summary: str | None = None,
    ) -> str:
        """使用轻量模型对早期历史生成摘要（支持滚动摘要）。

        previous_summary 为上一轮压缩生成的摘要，作为「更早历史」并入输入，
        使新摘要累积覆盖全部历史而非仅本轮早期消息。
        """
        text_parts: list[str] = []
        for msg in history:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            text_parts.append(f"{role}: {content}")

        conversation_text = "\n".join(text_parts)

        if previous_summary:
            conversation_text = (
                f"[更早对话摘要]\n{previous_summary}\n\n[本轮早期对话]\n{conversation_text}"
            )

        summarize_prompt = (
            "请将以下客服对话历史压缩为一段简洁的摘要（不超过200字）。\n"
            "要求：\n"
            "1. 保留关键实体信息（订单号、商品名、金额等）\n"
            "2. 保留用户的核心诉求和已解决的问题\n"
            "3. 不要遗漏重要的操作结果\n\n"
            f"对话历史：\n{conversation_text}"
        )

        try:
            from app.llm import LLMFactory
            llm = LLMFactory.create_summary_llm(temperature=0.3, max_tokens=512)
            response = await llm.ainvoke(summarize_prompt)
            summary = response.content.strip()
            logger.info(
                f"[context-builder] History summarized: {len(history)} messages → "
                f"{len(summary)} chars | session={session_id}"
            )
            return summary
        except Exception as e:
            logger.error(f"[context-builder] Summarization failed: {e}")
            fallback_parts = text_parts[:6]
            return "早期对话概要：\n" + "\n".join(fallback_parts)
