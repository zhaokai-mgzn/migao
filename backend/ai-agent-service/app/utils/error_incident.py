# app/utils/error_incident.py
"""异常归因的共用口径（incident 短码 / 审计消息 / 请求锚点）。

**为什么单独成模块**：`incident=` 短码口径最初由 issue #3805（LLM 调用异常吞点可归因，
PR #3809）建立在 `app/graph/skills/base_skill.py`；issue #3810 又需要同一条口径
（同会话同异常同码）在**另外两个用户可见错误落点**复用 —— `app/agents/customer_service_agent.py`
的 `astream_chat` 与 `app/api/chat.py` 的 SSE error 分支。

复用意图是"同一条口径"，不是"抄一份同样的代码"：抄两份哈希算法，将来任一处改动都会
让同一会话的同一异常在两个落点算出**不同**短码，聚合直接失效。故收敛为单一实现，
`base_skill` 反向导入并 re-export（既有的 `base_skill.llm_incident_id` 引用面零变更）。

**用户可见文本与归因的边界（本模块的纪律）**：短码、类型、异常消息只落**日志/审计**；
用户那一句必须由调用方给**纯中文短句**（面向低学历用户的既有约定，见 issue #3707 族）。
"""

from __future__ import annotations

import hashlib

from app.middleware.logging_middleware import get_request_id
from app.utils.log_sanitizer import LogSanitizer

#: `str(exc)` 在审计行里的字符上限（防多行/超长异常消息破坏"一行 = 一条审计"）
EXC_MSG_MAX = 300


def llm_incident_id(session_id: str, exc_type: str) -> str:
    """异常吞点的稳定 incident 短码：`(会话, 异常类型)` → 8 位十六进制。

    确定性（不随机）是刻意的：同一会话连续 N 轮吞同一个异常必须得到**同一个**短码，
    否则"连续 3 轮同一句兜底"在日志里是 3 条互不相识的记录，聚合不出来。
    短码是哈希，不回显会话号/异常原文 ⇒ 不含内部细节。
    """
    raw = f"{session_id or '-'}|{exc_type or 'Unknown'}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:8]


def safe_exc_message(exc: BaseException, limit: int = EXC_MSG_MAX) -> str:
    """异常消息 → 单行 + 脱敏 + 截断（结构化审计专用）。

    单行化：判定跑产物与线上排查都是按行检索，多行异常消息（供应商错误常回显多行
    JSON / 请求体）会把「一行 = 一条审计」撕开，grep 直接失效。
    脱敏 + 截断：异常回显里可能带手机号/邮箱与超长请求体（复用既有 LogSanitizer）。
    """
    text = " ".join(str(exc).split())
    text = LogSanitizer.mask_text(text)
    if len(text) > limit:
        text = text[:limit] + "…"
    return text


def current_request_id() -> str:
    """当前 HTTP 请求的 request_id（与响应头 `X-Request-ID` / 中间件请求日志同源）。

    它是把「用户看到那一句兜底」对到「日志里那次失败」的锚点：一轮 = 一个请求，
    中间件的 `[<req_id>] POST /api/chat/… started/completed` 给出该轮的墙钟窗口。
    单测/非请求上下文里为空 ⇒ 记 `-`，不影响审计其它字段。
    """
    return get_request_id() or "-"


def log_exception_audit(
    *,
    logger,
    mark: str,
    exc: BaseException,
    session_id: str = "",
    extra: str = "",
) -> str:
    """**唯一**的"异常 → 审计行"落笔点：返回 incident 短码，审计行落 ERROR + traceback。

    统一形态（`#3805`/`#3810` 共用，便于跨落点 `grep` 聚合）：

        [<mark>] session=<sid> error=<类型>: <单行脱敏消息> | incident=<8位> <extra…>

    用 `logger.opt(exception=…)` 而不是把 traceback 拼进消息：只有
    `record["exception"]` 非空才算"traceback 真的落盘"，且不破坏"一行 = 一条审计"。
    `extra` 由调用方给**上下文键值**（skill / 租户 / 轮次 / req 等），不含用户可见文本。
    """
    incident = llm_incident_id(session_id, type(exc).__name__)
    ctx = f" {extra.strip()}" if extra and extra.strip() else ""
    logger.opt(exception=exc).error(
        f"{mark} session={session_id or '-'} "
        f"error={type(exc).__name__}: {safe_exc_message(exc)}"
        f" | incident={incident}{ctx}"
    )
    return incident
