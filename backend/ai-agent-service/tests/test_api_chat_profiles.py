# case_ids: MC-269
"""`app/api/chat_profiles.py`（chat.py 切片单元）的镜像判据。

只经单元自身 import（不经 `chat.py`）⇒ 同时证明单元可独立装配、无反向依赖。

钉的行为：四个 fire-and-forget / 可降级档案面，**失败一律不打断对话**但**必须留痕**：
昵称与企业名的 Redis→DB 两跳、会话标题生成（只在默认标题上生效）、记忆候选累积（count=0 不喧哗）。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from loguru import logger

from app.api.chat_profiles import (
    _extract_memories_async,
    _generate_title_async,
    _get_tenant_name,
    _get_user_nickname,
)


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeDB:
    def __init__(self, row=None, boom=None):
        self.row = row
        self.boom = boom

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def execute(self, sql, params):
        if self.boom:
            raise self.boom
        return _FakeResult(self.row)


def _logs_of(coro_fn):
    records = []
    sink = logger.add(lambda m: records.append(m.record["message"]), level=0)
    try:
        result = asyncio.run(coro_fn())
    finally:
        logger.remove(sink)
    return result, records


class TestNicknameAndTenantName:
    def test_nickname_falls_back_to_db(self):
        with patch("app.utils.database.AsyncSessionLocal",
                   return_value=_FakeDB(row=("张老板",))), \
                patch("app.utils.redis_client.redis_pool", None):
            got, records = _logs_of(lambda: _get_user_nickname(1, "u1"))
        assert got == "张老板"
        assert records == []

    def test_nickname_db_failure_degrades_to_none_with_a_warning(self):
        with patch("app.utils.database.AsyncSessionLocal",
                   return_value=_FakeDB(boom=RuntimeError("db down"))), \
                patch("app.utils.redis_client.redis_pool", None):
            got, records = _logs_of(lambda: _get_user_nickname(1, "u1"))
        assert got is None
        assert len(records) == 1
        assert records[0].startswith("[chat] Failed to query user nickname")

    def test_tenant_name_falls_back_to_db(self):
        with patch("app.utils.database.AsyncSessionLocal",
                   return_value=_FakeDB(row=("词元通达",))), \
                patch("app.utils.redis_client.redis_pool", None):
            got, records = _logs_of(lambda: _get_tenant_name(7))
        assert got == "词元通达"
        assert records == []


class TestTitleGeneration:
    def _run(self, session, llm_content="窗帘报价", llm_boom=None):
        memory = MagicMock()
        memory.get_session = AsyncMock(return_value=session)
        memory.update_session_title = AsyncMock(return_value=True)

        class _LLM:
            async def ainvoke(self, prompt):
                if llm_boom:
                    raise llm_boom
                return type("R", (), {"content": llm_content})()

        class _Factory:
            @staticmethod
            def create_summary_llm():
                return _LLM()

        class _Memory:
            def __new__(cls):
                return memory

        with patch("app.memory.session_memory.SessionMemory", _Memory), \
                patch("app.llm.factory.LLMFactory", _Factory):
            _, records = _logs_of(
                lambda: _generate_title_async("sess-1", "用户问价", "报价 1395.56"))
        return memory, records

    def test_default_title_is_replaced_by_generated_one(self):
        memory, records = self._run({"metadata": {"title": "会话 20261106-1142"}})
        assert memory.update_session_title.await_args.args == ("sess-1", "窗帘报价")
        assert records == ["[chat/send] Title generated | session=sess-1 title=窗帘报价"]

    def test_manual_title_is_never_overwritten(self):
        memory, records = self._run({"metadata": {"title": "手动标题"}}, llm_content="不该用到")
        assert memory.update_session_title.await_count == 0
        assert records == []

    def test_empty_llm_answer_does_not_write(self):
        memory, records = self._run({"metadata": {"title": "会话 20261106-1142"}}, llm_content="   ")
        assert memory.update_session_title.await_count == 0
        assert records == []

    def test_llm_failure_is_a_visible_warning_not_an_exception(self):
        memory, records = self._run(
            {"metadata": {"title": "会话 20261106-1142"}}, llm_boom=RuntimeError("llm down"))
        assert memory.update_session_title.await_count == 0
        assert len(records) == 1
        assert records[0].startswith(
            "[chat/send] Session title update failed (non-fatal) | session=sess-1 "
            "error=RuntimeError: llm down")


class TestMemoryExtraction:
    def _run(self, count=3, boom=None):
        calls = []

        async def _fake(**kwargs):
            calls.append(kwargs)
            if boom:
                raise boom
            return count

        with patch("app.memory.extractor.extract_and_accumulate", _fake):
            _, records = _logs_of(lambda: _extract_memories_async(
                1, "u1", "用户问价", "报价 1395.56", "sess-1"))
        return calls, records

    def test_candidates_are_accumulated_with_the_rounds_facts(self):
        calls, records = self._run(count=3)
        assert calls == [{"tenant_id": 1, "user_id": "u1", "agent_type": "xiaobu",
                          "session_id": "sess-1", "user_message": "用户问价",
                          "assistant_reply": "报价 1395.56"}]
        assert records == [
            "[chat/send] Memory accumulated | session=sess-1 agent=xiaobu count=3"]

    def test_zero_candidates_is_quiet(self):
        _, records = self._run(count=0)
        assert records == []

    def test_extraction_failure_is_a_visible_warning(self):
        _, records = self._run(boom=RuntimeError("extract down"))
        assert len(records) == 1
        assert records[0].startswith("[chat/send] Memory accumulation failed (non-fatal)")
