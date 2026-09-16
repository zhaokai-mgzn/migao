"""在途记忆抽取任务登记 + 会话关闭前 drain（app/memory/extraction_tasks.py，issue #3357）

覆盖：
- register/done 回调注销（在途计数归零，注册表不泄漏）
- drain：等待在途任务收口（返回等待条数）；无在途 → 0；超时**不取消**任务
- 超时配置：环境变量可调，非法/负值回落默认
- **顺序铁律**：`SessionMemory._flush_pending_memories` 必须先 drain 再 flush
  —— 否则关闭紧跟最后一轮时候选为空、偏好静默丢失（CI 实证 user_memories 恒 0）
- chat.py 接线：每轮抽取任务必须登记（否则 drain 永远等不到它）

为什么这些不是"实现细节测试"：记忆链路断掉时**没有任何报错**——报告全绿、
user_memories 空表。drain 是这条链上唯一阻止"关闭抢在抽取之前"的机制，
它一旦失效，症状与"用户没表达偏好"完全一样（无法归因）。
"""
# case_ids: CH-024
import asyncio
import inspect
from pathlib import Path

import pytest

from app.memory import extraction_tasks as et
from app.memory.session_memory import SessionMemory

CHAT_PY = Path(__file__).resolve().parents[1] / "app" / "api" / "chat.py"


@pytest.fixture(autouse=True)
def _clean_registry():
    """进程内单例登记表：用例间必须清空（否则残留任务影响计数断言）。"""
    et.reset_inflight_registry()
    yield
    et.reset_inflight_registry()


class TestRegisterAndForget:
    async def test_register_counts_inflight(self):
        started = asyncio.Event()

        async def _slow():
            started.set()
            await asyncio.sleep(0.05)

        task = asyncio.create_task(_slow())
        et.register_extraction_task("s1", task)
        await started.wait()
        assert et.inflight_extraction_count("s1") == 1
        await task
        await asyncio.sleep(0)  # 让 done 回调跑完
        assert et.inflight_extraction_count("s1") == 0

    async def test_done_callback_removes_empty_bucket(self):
        task = asyncio.create_task(asyncio.sleep(0))
        et.register_extraction_task("s2", task)
        await task
        await asyncio.sleep(0)
        assert "s2" not in et._inflight, "空桶必须回收（否则 session 维度长期泄漏）"

    async def test_register_ignores_empty_session_or_none_task(self):
        et.register_extraction_task("", asyncio.create_task(asyncio.sleep(0)))
        et.register_extraction_task("s3", None)
        assert et.inflight_extraction_count("") == 0
        assert et.inflight_extraction_count("s3") == 0

    async def test_reset_clears_registry(self):
        task = asyncio.create_task(asyncio.sleep(5))
        et.register_extraction_task("s4", task)
        et.reset_inflight_registry()
        assert et.inflight_extraction_count("s4") == 0
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class TestDrain:
    async def test_drain_waits_for_inflight_task(self):
        """drain 必须等到在途抽取完成——这正是"关闭不丢偏好"的机制。"""
        done = {"flag": False}

        async def _extract():
            await asyncio.sleep(0.05)
            done["flag"] = True

        task = asyncio.create_task(_extract())
        et.register_extraction_task("s1", task)
        waited = await et.drain_inflight_extractions("s1", timeout=5)
        assert waited == 1
        assert done["flag"] is True, "drain 返回时在途任务必须已完成"

    async def test_drain_zero_when_nothing_pending(self):
        assert await et.drain_inflight_extractions("nobody") == 0

    async def test_drain_zero_after_task_finished(self):
        task = asyncio.create_task(asyncio.sleep(0))
        et.register_extraction_task("s1", task)
        await task
        assert await et.drain_inflight_extractions("s1") == 0

    async def test_drain_timeout_does_not_cancel_task(self):
        """超时放行但**不取消**：取消会丢候选并掩盖故障（宁可告警 + flush 不完整）。"""
        task = asyncio.create_task(asyncio.sleep(5))
        et.register_extraction_task("s1", task)
        waited = await et.drain_inflight_extractions("s1", timeout=0.01)
        assert waited == 1
        # 取消是"请求"不是"立即完成"：必须让出事件循环才能观察到取消被投递
        # （否则误取消与不取消在本断言下无法区分——mutation 实测漏过）。
        await asyncio.sleep(0.05)
        assert not task.cancelled(), "超时不得取消在途任务（取消会丢候选）"
        assert not task.done(), "超时不得取消在途任务"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class TestDrainTimeoutConfig:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("MEMORY_DRAIN_TIMEOUT_SECONDS", raising=False)
        assert et._drain_timeout() == et.DEFAULT_DRAIN_TIMEOUT_SECONDS

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("MEMORY_DRAIN_TIMEOUT_SECONDS", "0.5")
        assert et._drain_timeout() == 0.5

    def test_invalid_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("MEMORY_DRAIN_TIMEOUT_SECONDS", "abc")
        assert et._drain_timeout() == et.DEFAULT_DRAIN_TIMEOUT_SECONDS

    def test_negative_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("MEMORY_DRAIN_TIMEOUT_SECONDS", "-1")
        assert et._drain_timeout() == et.DEFAULT_DRAIN_TIMEOUT_SECONDS


class TestFlushDrainsFirst:
    """顺序铁律：flush 前必须 drain（issue #3357 的直接修复）。"""

    async def test_candidates_written_by_inflight_task_are_flushed(self, monkeypatch):
        from app.memory import extractor

        observed = {}

        async def _fake_flush(session_id):
            # flush 看到的"候选是否已写入"就是被测事实：drain 缺失时这里是 None
            observed["candidates"] = observed.get("written")
            return 1

        monkeypatch.setattr(extractor, "flush_memories", _fake_flush)

        async def _extract():
            await asyncio.sleep(0.05)
            observed["written"] = [{"key": "curtain_style", "value": "奶油风"}]

        task = asyncio.create_task(_extract())
        et.register_extraction_task("sess-mem", task)

        await SessionMemory()._flush_pending_memories("sess-mem")

        assert observed.get("candidates"), (
            "flush 执行时在途抽取尚未收口 → 候选为空 → 偏好静默丢失（drain 缺失？）"
        )
        assert observed["candidates"] == [{"key": "curtain_style", "value": "奶油风"}]

    async def test_flush_still_runs_when_drain_raises(self, monkeypatch):
        """drain 异常不得阻断 flush（关闭主流程优先）。"""
        from app.memory import extractor

        called = {"flush": 0}

        async def _fake_flush(session_id):
            called["flush"] += 1

        async def _boom(session_id, timeout=None):
            raise RuntimeError("drain exploded")

        monkeypatch.setattr(extractor, "flush_memories", _fake_flush)
        monkeypatch.setattr(et, "drain_inflight_extractions", _boom)

        await SessionMemory()._flush_pending_memories("sess-x")
        assert called["flush"] == 1


class TestChatWiring:
    """chat.py 每轮抽取任务必须登记——否则 drain 永远等不到它（接线断了没症状）。"""

    def test_extraction_task_is_registered(self):
        src = CHAT_PY.read_text(encoding="utf-8")
        assert "register_extraction_task(session_id, _mem_task)" in src, (
            "chat.py 的 fire-and-forget 抽取任务未登记到 extraction_tasks —— "
            "会话关闭时 drain 等不到它，关闭紧跟最后一轮即丢记忆（issue #3357）"
        )
        # 任务必须先创建再登记（登记一个未创建的任务无意义）
        assert "asyncio.create_task(" in src

    def test_extraction_helper_still_fire_and_forget(self):
        """抽取仍不得阻塞 SSE（登记 ≠ await）；否则每轮响应变慢。"""
        src = CHAT_PY.read_text(encoding="utf-8")
        assert "await _extract_memories_async(" not in src

    def test_drain_is_awaited_in_flush_path(self):
        """顺序铁律的接线检查（行为断言见 TestFlushDrainsFirst）。"""
        src = inspect.getsource(SessionMemory._flush_pending_memories)
        assert "drain_inflight_extractions" in src
