"""在途记忆抽取任务登记（issue #3357）。

## 为什么需要这个模块

`chat.py` 每轮回复后以 `asyncio.create_task(_extract_memories_async(...))`
fire-and-forget 抽取记忆候选，候选累积在 `session_states.state["memory_candidates"]`，
由会话关闭路径 `SessionMemory.close_session → _flush_pending_memories → flush_memories`
批量落库到 `user_memories`（issue #2815 会话末聚合）。

抽取本身是一次 LLM 调用（秒级）。若关闭请求紧跟最后一轮到达，抽取**还没返回**就
flush → 候选为空 → 记忆静默丢失。这不是理论风险：

- CI 实证（issue #3357）评测跑完后 `user_memories` 恒为 0 条；
- 生产同构路径：用户说完偏好就退出、坐席手动结束会话、空闲扫描关闭会话
  （`expire_idle`）都可能抢在抽取返回之前。

本模块把在途任务登记在内存里，flush 前 `drain_inflight_extractions(session_id)`
等在途抽取收口（有超时上限，绝不阻塞关闭主流程）。

## 边界

- 登记/注销是同步操作（同一事件循环内无 await 间隙），因此无需锁。
- 进程内状态：多副本部署时，关闭请求与抽取若落在不同副本，本模块无能为力
  （那属于会话亲和性问题，需外部粘性路由）；单副本与评测栈（CI 单实例）成立。
- 超时后**不取消**任务（取消会丢候选且掩盖故障），仅告警并放行 flush。
"""

import asyncio
import os
from typing import Dict, List, Set

from loguru import logger

# 在途抽取等待上限（秒）。抽取 = 单次轻量 LLM 调用，正常 1-3s；
# 上限过大会把关闭主流程拖长（关闭路径持有一个 DB 连接），过小则等于没等。
DEFAULT_DRAIN_TIMEOUT_SECONDS = 8.0

# session_id → 未结束的抽取任务集合
_inflight: Dict[str, Set[asyncio.Task]] = {}


def _drain_timeout() -> float:
    """等待上限：环境变量可调（CI/本地调试），非法值回落默认。"""
    raw = os.environ.get("MEMORY_DRAIN_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_DRAIN_TIMEOUT_SECONDS
    try:
        val = float(raw)
    except (TypeError, ValueError):
        logger.warning(f"[memory-tasks] 非法 MEMORY_DRAIN_TIMEOUT_SECONDS={raw!r}，回落默认")
        return DEFAULT_DRAIN_TIMEOUT_SECONDS
    return val if val >= 0 else DEFAULT_DRAIN_TIMEOUT_SECONDS


def register_extraction_task(session_id: str, task: asyncio.Task) -> None:
    """登记一个在途记忆抽取任务（session 维度）。"""
    if not session_id or task is None:
        return
    _inflight.setdefault(session_id, set()).add(task)
    task.add_done_callback(lambda t: _forget(session_id, t))


def _forget(session_id: str, task: asyncio.Task) -> None:
    """任务结束后注销（回调不抛：注销失败不得冒泡进事件循环）。"""
    try:
        bucket = _inflight.get(session_id)
        if bucket is None:
            return
        bucket.discard(task)
        if not bucket:
            _inflight.pop(session_id, None)
    except Exception as e:  # pragma: no cover - 防御性
        logger.debug(f"[memory-tasks] Forget failed | session={session_id} error={e}")


def inflight_extraction_count(session_id: str) -> int:
    """当前在途（未结束）抽取任务数——诊断/测试用。"""
    bucket = _inflight.get(session_id) or set()
    return sum(1 for t in bucket if not t.done())


async def drain_inflight_extractions(
    session_id: str, timeout: float = None
) -> int:
    """等待该会话在途抽取任务收口；返回**等待过的任务数**（0 = 无需等待）。

    调用点：`SessionMemory._flush_pending_memories`（会话关闭/删除/空闲回收前）。
    任何异常不外抛（关闭主流程优先）；超时仅告警，不取消任务。
    """
    bucket = _inflight.get(session_id)
    if not bucket:
        return 0
    pending: List[asyncio.Task] = [t for t in bucket if not t.done()]
    if not pending:
        return 0
    wait_timeout = _drain_timeout() if timeout is None else timeout
    try:
        await asyncio.wait(pending, timeout=wait_timeout)
    except Exception as e:
        # 跨事件循环/已关闭循环等（单测重建 loop 场景）
        logger.warning(
            f"[memory-tasks] Drain wait failed | session={session_id} "
            f"count={len(pending)} error={type(e).__name__}: {e}"
        )
        return len(pending)
    still_pending = [t for t in pending if not t.done()]
    if still_pending:
        logger.warning(
            f"[memory-tasks] Drain timeout | session={session_id} "
            f"waited={len(pending)} still_pending={len(still_pending)} "
            f"timeout={wait_timeout}s（记忆候选可能不完整，flush 继续）"
        )
    else:
        logger.info(
            f"[memory-tasks] Drained {len(pending)} in-flight extraction(s) "
            f"before flush | session={session_id}"
        )
    return len(pending)


def reset_inflight_registry() -> None:
    """清空登记表（仅测试用：进程内单例状态会跨用例泄漏）。"""
    _inflight.clear()
