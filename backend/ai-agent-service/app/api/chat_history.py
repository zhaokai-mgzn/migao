"""历史消息 / 会话守卫 / 落库失败上报（`chat.py` 切片单元，issue #8725 第三档）。

## 单一职责
「把**已经发生过的事**读出来、把**这一轮的事**写下去」：历史行 → agent 形态（多模态 / `<think>` /
页面信封 / 存量主动提示）、会话归属与状态校验、一次落库的唯一策略点与**失败必留痕**的审计行。
它不决定发不发卡、不生成回复 —— 那些是出站面（`app/api/chat_outbound.py`）与流式桥的事。

## 搬运口径
定义逐行搬自 `app/api/chat.py`（含 `#4084`「落库失败：单一策略点」整段文档注释）。
`chat.py` 保留同名 re-export ⇒ 既有调用点与 `patch("app.api.chat._save_message_or_report")`
的测试面零改动；落库静默守卫的登记面同批改到本文件（见 PR body 的登记面表）。
"""

import asyncio
import app.utils.error_incident as _err_inc
from typing import (
    Any,
    Dict,
    List,
    Optional,
)
from datetime import datetime
from fastapi import HTTPException
from loguru import logger
from app.api.response_models import make_response
from app.memory.session_memory import SessionMemory
from app.context.page_registry import strip_page_context_envelope
from app.context.menu_navigator import is_legacy_proactive_tip
from app.vision.pipeline import (
    image_url_hint as _image_url_hint,
    rewrite_image_url as _rewrite_image_url,
    validate_image_url as _validate_image_url,
)


# ============ 落库失败：单一策略点（issue #4084） ============
#
# 病灶：本文件对 `session_memory.save_message(...)` 有 4 处调用，**每处各写一个 `except`**、
# 降级策略各异 —— 分页分支的 assistant 落库是 `except Exception: pass`：消息没落库、
# 日志里也没有，而 SSE 照常 `done` ⇒ 顾客这轮"看起来成功"，下次回放历史才发现少一条
# （验收取证也看不到）。同族形态（#4070 实测）：生产签名新增一个可选参数、替身不认识该
# 关键字 ⇒ `TypeError` 被同一个 `except Exception` 吞掉 ⇒ assistant 消息静默不落库。
#
# 归口：本文件的落库/状态写都经 `_save_message_or_report` / `_report_persist_failure`
# （唯一策略点），失败**必留痕且可归因**：
#   · `log_exception_audit` ⇒ ERROR + traceback + `incident=` 短码（同会话同异常同码，
#     `grep "persist FAILED"` 即可聚合「连续 N 轮落库失败」）；
#   · 按异常类型**分类**："CODE DEFECT"（TypeError/AttributeError/KeyError/NameError ——
#     签名漂移、字段改名一类，须改代码）与 "degraded"（超时/连接类，可降级）处置完全不同，
#     混成一个 `except Exception` 正是这类缺陷能潜伏的原因；
#   · 返回 `None` = **没写进去**：调用方不得当成功（`done` 事件的 message_id 亦为 null）。
#
# ⚠️ 为什么默认 fail-open（`fail_open=True`）：落库失败时模型回复**已经流给顾客**，此时中断
# 整轮会把"历史缺一条"升级成"这轮白聊"。本仓纪律是"允许 fail-open，不允许静默" ——
# 该形态由 L0 守卫 `tests/unit_ci_workflows/test_persistence_failure_swallow_guard.py`
# 钉住（裸 `except: pass` / `except: continue` 吞落库调用 ⇒ 门禁红）。
# 少数落点保持 fail-closed（`fail_open=False`，*用户消息是后续轮次历史的锚*）：行为与本
# 函数引入前一致，只是把归因从"event_stream error"改成"落库失败"。

#: 审计行标记（稳定检索入口）：`grep "persist FAILED"` 捞出全部落库/状态写失败
PERSIST_FAILED_MARK = "[chat/send] persist FAILED"

#: 编程错误类异常（**代码缺陷**，不是存储故障）—— 见模块上方 #4070 的实测形态
_CODE_DEFECT_EXCS = (TypeError, AttributeError, KeyError, NameError)

#: 分类 → 处置建议（进审计行；不含用户可见文本）
_PERSIST_SUGGESTION = {
    "CODE DEFECT": (
        "这是编程错误（签名漂移/字段改名一类：例如 SessionMemory 新增参数而调用方或测试替身"
        "没跟上，见 #4070），须修代码；反复出现说明落库契约已不一致"
    ),
    "degraded": (
        "按存储瞬态故障处置：本轮已 fail-open 继续，但**这一条不会出现在历史里**；"
        "连续出现须查 DB/连接池"
    ),
}


def _report_persist_failure(
    *, exc: BaseException, op: str, source: str,
    session_id: str = "", role: str = "", tenant_id: Any = None,
) -> str:
    """落库/状态写失败 → 审计行（返回 incident 短码）。

    只陈述**失败**（不写成功）；分类只回答"这是代码缺陷还是存储故障"。
    `source` 是**归因键**（哪条路径的落库，如 `chat.assistant`），不作任何分支判据。
    """
    kind = "CODE DEFECT" if isinstance(exc, _CODE_DEFECT_EXCS) else "degraded"
    return _err_inc.log_exception_audit(
        logger=logger,
        mark=f"{PERSIST_FAILED_MARK} ({kind}) op={op} write={source} role={role or '-'}",
        exc=exc,
        session_id=session_id,
        extra=(
            f"tenant={tenant_id if tenant_id is not None else '-'} "
            f"req={_err_inc.current_request_id()} suggestion：{_PERSIST_SUGGESTION[kind]}"
        ),
    )


async def _save_message_or_report(
    session_memory: Any,
    *,
    source: str,
    fail_open: bool = True,
    timeout: float = 10.0,
    **kwargs: Any,
) -> Optional[str]:
    """落库单一策略点（issue #4084）：返回 message_id；失败留痕（返回 None / 按需上抛）。

    Args:
        source: 归因键（哪条路径的落库，如 `chat.assistant` / `page.user`）—— 只进审计行。
        fail_open: `True`（默认）落库失败不打断用户对话（留痕后返回 None）；
            `False` 留痕后**原样上抛**（"用户消息是后续轮次历史的锚"这类必须 fail-closed 的落点）。
        timeout: `asyncio.wait_for` 超时（秒）—— 避免落库阻塞 SSE 流关闭。
    """
    try:
        return await asyncio.wait_for(
            session_memory.save_message(**kwargs), timeout=timeout)
    except Exception as exc:
        _report_persist_failure(
            exc=exc, op="save_message", source=source,
            session_id=kwargs.get("session_id", ""), role=kwargs.get("role", ""),
            tenant_id=kwargs.get("tenant_id"),
        )
        if not fail_open:
            raise
        return None

def _history_user_text(role: Any, content: Any) -> Any:
    """历史里**用户消息**的文本：剥掉页面上下文注入信封（issue #7112）。

    信封是**元数据**（「用户在哪一页」），不是用户说的话 —— 落库侧自 #7112 起不再写它，
    旧行则由**读**这一侧归一（不改写历史数据）。展示面（`get_history`）与 LLM 历史
    （`_convert_history_to_agent_format`）**共用本函数**：两处各写一份口径 = 迟早漂移。
    """
    if role == "user" and isinstance(content, str):
        return strip_page_context_envelope(content)
    return content


def _is_legacy_proactive_tip_row(msg: Dict[str, Any]) -> bool:
    """历史里的一条**存量主动导航提示**（issue #7324）：读侧消化，不回放、不进模型历史。

    这类行是 #6030 起落库的（后缀带「（只给导航：…）」元指令）。**新行已不再落库**；旧行**不回写**，
    只在读的两处（`get_history` / `_convert_history_to_agent_format`）跳过 —— 与 #7112 同口径。
    """
    return msg.get("role") == "assistant" and is_legacy_proactive_tip(msg.get("content"))


def _format_datetime(dt: Any) -> str:
    """格式化日期时间为 ISO 8601 字符串（UTC，以 Z 结尾）"""
    if isinstance(dt, datetime):
        # 如果有时区信息，先转为 UTC 再去掉 tzinfo
        if dt.tzinfo is not None:
            from datetime import timezone
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.isoformat() + "Z"
    # 字符串兜底：移除可能已有的 +00:00Z 双重后缀
    s = str(dt)
    if s.endswith("+00:00Z"):
        s = s.replace("+00:00Z", "Z")
    elif s.endswith("+00:00"):
        s = s.replace("+00:00", "Z")
    return s


async def _guard_session(
    session_memory: SessionMemory,
    session_id: str,
    *,
    tenant_id: int,
    user_id: str,
    action: str = "访问",
) -> dict:
    """会话守卫（会话管理重构 P2）：统一 404/403 校验。

    替代原先散落在 close/reopen/delete/history 各端点的重复校验：
    - 会话不存在 → 404 SESSION_NOT_FOUND
    - 跨租户 / 跨用户 → 403 PERMISSION_DENIED

    Returns:
        session dict；校验失败抛 HTTPException（错误格式统一 make_response）。
    """
    session = await session_memory.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=make_response(False, error_code="SESSION_NOT_FOUND", error_message="会话不存在"),
        )
    if session.get("tenant_id") != tenant_id:
        logger.warning(
            f"[chat/guard] Cross-tenant {action} attempt: user_tenant={tenant_id}, "
            f"session_tenant={session.get('tenant_id')}, session_id={session_id}, "
            f"user_id={user_id}"
        )
        raise HTTPException(
            status_code=403,
            detail=make_response(False, error_code="PERMISSION_DENIED", error_message=f"无权{action}该会话"),
        )
    if session.get("customer_id") != user_id:
        logger.warning(
            f"[chat/guard] Unauthorized {action} attempt: user_id={user_id}, "
            f"session_owner={session.get('customer_id')}, session_id={session_id}, "
            f"tenant_id={tenant_id}"
        )
        raise HTTPException(
            status_code=403,
            detail=make_response(False, error_code="PERMISSION_DENIED", error_message=f"无权{action}该会话"),
        )
    return session


def _raise_session_error(code: str, message: str) -> None:
    """把 send_gate 的 (code, message) 转为统一 make_response 格式的 HTTPException。

    状态码映射：SESSION_NOT_FOUND→404, PERMISSION_DENIED→403, SESSION_CLOSED→409。
    """
    status_map = {
        "SESSION_NOT_FOUND": 404,
        "PERMISSION_DENIED": 403,
        "SESSION_CLOSED": 409,
    }
    status_code = status_map.get(code, 400)
    raise HTTPException(
        status_code=status_code,
        detail=make_response(False, error_code=code, error_message=message),
    )


def _convert_history_to_agent_format(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将数据库消息格式转换为 Agent 所需的格式（支持多模态）

    对 assistant 消息剥离 <think> 块，防止：
    1. 旧数据中的思考内容挤占上下文预算
    2. 上轮推理内容干扰当前轮次的工具调用决策
    """
    import re
    history = []
    for msg in messages:
        if _is_legacy_proactive_tip_row(msg):
            continue  # 存量主动导航提示不进模型历史（issue #7324）
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "assistant":
            content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
        else:
            content = _history_user_text(role, content)
        entry: Dict[str, Any] = {
            "role": role,
            "content": content,
        }
        # 携带多模态信息
        content_type = msg.get("content_type", "text")
        if content_type and content_type != "text":
            entry["content_type"] = content_type
        metadata = msg.get("metadata")
        if isinstance(metadata, dict) and metadata.get("images"):
            entry["images"] = [_rewrite_image_url(url) for url in metadata["images"] if _validate_image_url(url)]
            # issue #3046：图片 URL 必须同时以文本注入，LLM 才能在工具调用中直接引用
            # （否则仅 vision 图像块可见，LLM 会回复「无法提取图片存储地址」）
            entry["content"] = content + _image_url_hint(metadata["images"])
        elif isinstance(metadata, str):
            try:
                import json
                meta_parsed = json.loads(metadata)
                if meta_parsed.get("images"):
                    entry["images"] = [_rewrite_image_url(url) for url in meta_parsed["images"] if _validate_image_url(url)]
                    entry["content"] = content + _image_url_hint(meta_parsed["images"])
            except (json.JSONDecodeError, TypeError):
                pass
        history.append(entry)
    return history
