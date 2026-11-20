"""LLM 主凭据健康 —— 「凭据失效」必须是**可观测事件**，不能只剩一句兜底话术（issue #8084）。

## 病（2026-10-29 15:29 +08 线上实测，逐字读数见 issue）

DeepSeek 主凭据在供应商侧失效（每轮 10 条 `401 AuthenticationError`，0 条 `LLM done`）时：

- **全部** AI 面（黄金策 / 米宝 / 意图分类 / 会话标题 / 视觉识别）共用 `Settings.PRIMARY_API_KEY`
  ⇒ 一把 key 失效 = 100% 不可用；
- 主循环把它当「不可重试」处理（正确），但**每轮**只落一条互不相识的普通 ERROR，**没有告警面**；
- `/ready` 只探 DB + Redis ⇒ 200 全绿、容器 `healthy`、`docker ps` 一路绿；
- 用户只看到通用兜底句「刚才这轮没成功，请您再说一次」，被读成「我的网络/操作有问题」（靠人肉发现）。

## 两道出口（都**不**并进 `/ready`）

① **进程级标志 + 恰好一条可行动 ERROR**：确定性鉴权失败（401）/ 额度耗尽（402）**首次**命中时
   置 `broken`，日志只落一条（带「更换 PRIMARY_API_KEY」的可行动提示）；任一成功调用即清标志。
   ⇒ 把「每轮一条、彼此无法聚合的 ERROR」变成「一次事件、一条可行动记录」。
② **只读探针** `llm_health_snapshot()`（`GET /internal/llm-health`）：60s 缓存 + 一次最小真实调用，
   `ok=false` ⇒ 非 200。⇒ 「服务活着但 LLM 不可用」可判读。

## 为什么不并进 `/ready`（口径选择，PR body 同步登记）

`/ready` 是 compose healthcheck 的**唯一**判据：把供应商侧问题放进去 ⇒ 容器 unhealthy ⇒
重启 churn（本仓已被这类形态咬过）。本模块只裁**确定性**类（401 / 402，见 issue 的边界），
并把结论放在一个**独立**端点：探针可以红，容器不必重启。
超时 / 5xx / 429 **不进**本标志 —— 那已有 `app/llm/retry_policy.call_with_retry` 与熔断器。

## 边界（照实登记）

- 不自动换 key、不降级到备用供应商（涉钱 + 质量口径，须人工裁定）；
- `ok` 只回答「主凭据现在还能不能用」，不回答「每条链路都健康」（工具 / DB / 检索各有自己的面）；
- 探针在缓存窗口内**不发**真实调用 ⇒ 端点可被任意频率打，成本上限 = 1 次 / 分钟 / 进程；
- 探针只证明「同一把 key + 同一个 endpoint 能通」，不证明模型 / 额度 / 供应商侧配额的健康度。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger

#: 确定性「凭据不可用」类的 HTTP 状态码（issue #8084 的边界：鉴权失败 401 + 额度耗尽 402）。
#: **不含** 429 / 5xx / 超时 —— 那些是供应商抖动，已有重试 + 熔断，混进来会把探针变成抖动放大器。
CREDENTIAL_STATUS: frozenset = frozenset({401, 402})

#: 状态码 → 稳定短名。日志与探针的 `error_class` 共用**同一套词表**（换 SDK / 换供应商时
#: 读数仍可对比，且不把异常类名直接透给消费方）。
ERROR_CLASS_BY_STATUS: Dict[int, str] = {
    401: "authentication_error",
    402: "quota_exceeded",
}

#: 探针结果的缓存窗口（秒）。窗口内重复请求**不发**真实调用。
PROBE_TTL_S = 60.0

#: 日志检索锚（与 `[SLS]` / `incident=` 同族：一条 `grep` 就能捞出「凭据被拒」那次事件）
LOG_MARK = "[llm_health]"

#: 进程级状态（单进程单实例；不做锁 —— 都是整体赋值，且读侧只做快照）
_broken: bool = False
_last_error_class: Optional[str] = None
_last_error_status: Optional[int] = None
_last_error_at: Optional[float] = None
_last_ok_at: Optional[float] = None
_probe_cached: Optional[Dict[str, Any]] = None
_probe_cached_monotonic: float = 0.0


# ── 状态读写 ────────────────────────────────────────────────────────────────

def credential_status(exc: BaseException) -> Optional[int]:
    """从异常里取「确定性凭据类」状态码：401 / 402 ⇒ 该状态码；其余 ⇒ `None`。

    状态码抽取复用 `app/llm/retry_policy.py` 的**同一份**口径（openai / httpx / requests
    三种属性命名），不在这里写第二份 —— 两份口径会各自漂移（见 `app/utils/error_incident.py`
    的同一条纪律：同一条口径只许有一个实现）。延迟导入是为了不让 `app.llm` 包级导入进入
    本模块的加载面（`app/llm/factory.py` 会在导入期引用本模块）。
    """
    from app.llm.retry_policy import _extract_status_code

    status = _extract_status_code(exc)
    if status in CREDENTIAL_STATUS:
        return status
    # 没有状态码的替身 / SDK 二次封装（线上形态是 openai.AuthenticationError）：按类名兜底，
    # 否则「抛的还是同一个 401」会因为包装层而漏记（假绿）。
    if type(exc).__name__ == "AuthenticationError":
        return 401
    return None


def note_llm_failure(exc: BaseException) -> Optional[int]:
    """记一次 LLM 调用失败；**确定性**凭据失败 ⇒ 置进程级标志 + 跃变时落一条可行动 ERROR。

    Returns: 命中的凭据类状态码（401 / 402）；非确定性类返回 `None`（不改标志）。
    """
    global _broken, _last_error_class, _last_error_status, _last_error_at

    status = credential_status(exc)
    if status is None:
        return None

    _last_error_class = ERROR_CLASS_BY_STATUS[status]
    _last_error_status = status
    _last_error_at = time.time()
    if _broken:  # 已处于 broken：**不再**逐轮刷屏（这正是改前「每轮一条、聚合不出来」的病）
        return status

    _broken = True
    from app.utils.error_incident import safe_exc_message  # 单行 + 脱敏 + 截断（同一条口径）

    logger.error(
        f"{LOG_MARK} LLM 主凭据被供应商拒绝，全部 AI 面不可用"
        f" | error_class={_last_error_class} status={status}"
        f" provider_msg={safe_exc_message(exc)}"
        f" | action=更换 PRIMARY_API_KEY 并重启 ai-agent-service；"
        f"在此之前黄金策/米宝/意图分类/会话标题/视觉识别只会回兜底话术"
    )
    return status


def note_llm_success() -> None:
    """记一次真实成功调用 ⇒ 清 broken 标志（恢复即自愈，无需重启）。"""
    global _broken, _last_ok_at

    _broken = False
    _last_ok_at = time.time()


def is_llm_auth_broken() -> bool:
    """主凭据是否处于「被供应商确定性拒绝」状态（其他模块可直接读，不必拉探针）。"""
    return _broken


def reset_llm_health() -> None:
    """复位进程级状态 + 探针缓存（单测用例间隔离用；生产路径没有调用点）。"""
    global _broken, _last_error_class, _last_error_status, _last_error_at
    global _last_ok_at, _probe_cached, _probe_cached_monotonic

    _broken = False
    _last_error_class = None
    _last_error_status = None
    _last_error_at = None
    _last_ok_at = None
    _probe_cached = None
    _probe_cached_monotonic = 0.0


# ── 只读探针 ────────────────────────────────────────────────────────────────

def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return (
        datetime.fromtimestamp(ts, timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _snapshot() -> Dict[str, Any]:
    return {
        "ok": not _broken,
        "last_error_class": _last_error_class,
        "last_ok_at": _iso(_last_ok_at),
        "cached_at": _iso(time.time()),
    }


async def _probe_once() -> None:
    """对主凭据发一次**最小**真实调用（走 `LLMFactory` 这个唯一组合处 ⇒ 失败/成功自动记账）。"""
    from langchain_core.messages import HumanMessage

    from app.llm.factory import LLMFactory

    await LLMFactory.create_intent_llm().ainvoke([HumanMessage(content="ping")])


async def llm_health_snapshot(force: bool = False) -> Dict[str, Any]:
    """只读快照：`{ok, last_error_class, last_ok_at, cached_at}`（结果缓存 `PROBE_TTL_S` 秒）。

    `ok=false` 只可能来自**确定性**凭据类失败（401 / 402）—— 供应商抖动（超时 / 5xx / 429）
    不会让探针变红，因此不会有「抖动把容器探针打红」的放大效应。

    Args:
        force: 跳过缓存、强制发一次真实调用（运维手工复探用；探针端点不暴露该开关）。
    """
    global _probe_cached, _probe_cached_monotonic

    now = time.monotonic()
    if not force and _probe_cached is not None and now - _probe_cached_monotonic < PROBE_TTL_S:
        snapshot = dict(_probe_cached)
    else:
        try:
            await _probe_once()
        except Exception:
            # 瞬时类不进结论；确定性类已由 `app/llm/factory.py` 的混入层记账（`note_llm_failure`）。
            # 这里只吞掉探针自身的异常 —— 探针不许把「LLM 供应商抖动」变成「探针 500」。
            pass
        snapshot = _snapshot()
        _probe_cached = snapshot
        _probe_cached_monotonic = now

    # 活跃标志**永远**优先于缓存：真实流量刚打中 401，不能因为缓存窗口还剩几十秒就继续报 ok。
    snapshot["ok"] = not _broken
    snapshot["last_error_class"] = _last_error_class
    return snapshot
