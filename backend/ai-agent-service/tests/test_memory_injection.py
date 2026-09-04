# case_ids: CH-024, MC-014
"""用户长期记忆注入测试（issue #2815，C 端小布专属）

覆盖 base_skill 的记忆注入接线：
- 仅 xiaobu（C 端）注入 format_for_prompt 输出
- mibao（B 端）不注入
- 无记忆 / 异常时不注入且不破坏主流程
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage

from app.graph.skills.base_skill import _inject_user_memories


def _make_state(agent_type: str, tenant_id: int = 1, user_id: str = "u1") -> dict:
    return {
        "agent_type": agent_type,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "session_id": "s1",
        "messages": [HumanMessage(content="你好")],
    }


class TestInjectUserMemories:
    @pytest.mark.asyncio
    async def test_xiaobu_injects_memories(self):
        """xiaobu + 有记忆 → 消毒后的记忆块前置注入 system prompt"""
        base_prompt = "你是小布，米高窗帘的智能客服。"
        with patch(
            "app.graph.skills.base_skill.UserMemoryManager"
        ) as mock_cls:
            mgr = mock_cls.return_value
            mgr.format_for_prompt = AsyncMock(
                return_value="<user_memories>\n  <preferences>\n    奶油风\n  </preferences>\n</user_memories>"
            )
            result = await _inject_user_memories(
                base_prompt, _make_state("xiaobu")
            )

        assert "<user_memories>" in result
        assert "奶油风" in result
        assert result.startswith("<user_memories>")
        mock_cls.return_value.format_for_prompt.assert_awaited_once_with(
            1, "u1", agent_type="xiaobu"
        )

    @pytest.mark.asyncio
    async def test_mibao_does_not_inject(self):
        """mibao（B 端）不注入用户记忆（agent_type 分流）"""
        base_prompt = "你是米宝，商家后台助手。"
        with patch(
            "app.graph.skills.base_skill.UserMemoryManager"
        ) as mock_cls:
            mgr = mock_cls.return_value
            mgr.format_for_prompt = AsyncMock(
                return_value="<user_memories>...</user_memories>"
            )
            result = await _inject_user_memories(
                base_prompt, _make_state("mibao")
            )

        assert result == base_prompt
        mock_cls.return_value.format_for_prompt.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_memories_no_inject(self):
        """xiaobu 但无记忆 → 原样返回"""
        base_prompt = "你是小布。"
        with patch(
            "app.graph.skills.base_skill.UserMemoryManager"
        ) as mock_cls:
            mock_cls.return_value.format_for_prompt = AsyncMock(return_value="")
            result = await _inject_user_memories(
                base_prompt, _make_state("xiaobu")
            )

        assert result == base_prompt

    @pytest.mark.asyncio
    async def test_exception_does_not_break(self):
        """DB/提取异常 → 不注入且不抛（fire-and-forget 语义）"""
        base_prompt = "你是小布。"
        with patch(
            "app.graph.skills.base_skill.UserMemoryManager"
        ) as mock_cls:
            mock_cls.return_value.format_for_prompt = AsyncMock(
                side_effect=RuntimeError("db down")
            )
            result = await _inject_user_memories(
                base_prompt, _make_state("xiaobu")
            )

        assert result == base_prompt
