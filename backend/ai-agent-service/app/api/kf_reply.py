"""微信客服 AI 回复生成（内部接口）—— C 端对话内核产文，不是 agent 形态。

母单 #9302（「C 端 = 智能客服，只提供技术能力」裁定 2026-11-28）缺的那一跳：

    admin-api `KfSyncWorker` → `KfDecisionService.decide` == AI_REPLY
      → 本端点（内核产一条**客户可见正文**）
      → `KfSendService.enqueueReply` 入 kf_outbox（预算 / 48h 窗口 / msgid 幂等全在那一侧）

口径（用户裁定 2026-11-28：「不提供 agent 形态，只提供技术能力」）：

- **内核不是 agent 形态**：走 `agent_type="xiaobu"` 的 C 端对话内核，工具集原样保留
  （只读：商品/价格/库存/订单/物流/算料）；本端点不出 persona 开场白、不发卡片、不发起转人工。
- **通道稀缺资源**（微信客服 48h 内最多 5 条、单条 ≤2048 字节）⇒ **一次入站至多 1 条回复**：
  本端点只返回**一条最终正文**，中间过程（「正在查询…」「稍等」）一律丢弃；
- **单轮工具调用 ≤3 次**（母单裁定 2026-11-28）：超出 ⇒ 判不可用（admin-api 转人工）；
- **总超时 ≤8s**：内核跑超时就判不可用，绝不把过期答案发给客户；
- **fail-closed**：内核异常 / 空正文 / 只有中间过程 ⇒ `success=false`（`KF_REPLY_UNAVAILABLE`），
  admin-api 据此**转人工** —— 宁可转人工，也不发半句话、空话或假承诺。
- **写动作一律不在本端点**（建单/改单/退款/发券/改价）：需要写动作的诉求由判定侧转人工；
  本端点只产文本，`kf_outbox` 也只收 `parts=[{type:text}]`。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel, Field

from app.agents.customer_service_agent import AgentContext, get_agent
from app.api.response_models import make_response
from app.utils.auth import verify_service_token

router = APIRouter()

ERR_REPLY_UNAVAILABLE = "KF_REPLY_UNAVAILABLE"
TEXT_MAX_CHARS = 2000
#: C 端内核的 agent_type（C 端不再有 agent 形态，但内核标识沿用 "xiaobu" 以免动工具/路由口径）
CUSTOMER_AGENT_TYPE = "xiaobu"
#: 单轮工具调用上限（母单裁定 2026-11-28：预算稀缺 + 延迟敏感）
MAX_TOOL_CALLS = 3
#: 总超时（秒）——与 admin-api `wechat.kf.reply-timeout-ms` 默认 8s 同源
REPLY_TIMEOUT_SECONDS = 8.0


class KfReplyRequest(BaseModel):
    """回复生成请求（tenant_id / session_id 用于内核上下文与 trace，不参与判定）。"""

    tenant_id: Optional[int] = Field(None, description="租户 ID")
    session_id: Optional[str] = Field(None, description="会话 ID（kf_session = sessions.id）")
    external_userid: Optional[str] = Field(None, description="微信 external_userid（客户身份）")
    text: str = Field(..., max_length=TEXT_MAX_CHARS, description="客户最新一条消息")


class KfReplyResult(BaseModel):
    text: str
    tool_calls: int = 0


@dataclass(frozen=True)
class Generated:
    """一条可外发的最终答复 + 本轮工具调用次数（admin-api 据此判「数值是否真来自工具」）。"""

    text: str
    tool_calls: int


async def _stream_reply(agent, content: str, context: AgentContext) -> tuple[Optional[str], int]:
    """消费内核流，只留**最后一条**文本（中间过程话术丢弃），并数工具调用。

    返回 (最终文本 | None, 工具调用次数)。超上限 / 内核报错 ⇒ (None, n)。
    """
    tool_calls = 0
    final_text = ""
    stream = agent.astream_chat(content, context)
    try:
        async for resp in stream:
            kind = getattr(resp, "type", "text")
            if kind == "error":
                logger.warning(
                    "[kf-reply] 内核报错（转人工）: {}",
                    (getattr(resp, "metadata", None) or {}).get("error_type"),
                )
                return None, tool_calls
            if kind == "tool_call":
                tool_calls += 1
                if tool_calls > MAX_TOOL_CALLS:
                    logger.warning(
                        "[kf-reply] 单轮工具调用超上限（{} > {}）⇒ 转人工",
                        tool_calls, MAX_TOOL_CALLS,
                    )
                    return None, tool_calls
                continue
            if kind != "text":
                continue
            piece = (getattr(resp, "content", "") or "").strip()
            if piece:
                # 只保留最后一条：中间过程（「正在查询…」「稍等」）绝不外发（会烧掉 5 条预算且更差）
                final_text = piece
    finally:
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:  # noqa: BLE001 — 关闭失败不重要
                pass
    return (final_text or None), tool_calls


async def generate_reply(
    tenant_id: Optional[int],
    session_id: Optional[str],
    text: str,
    external_userid: Optional[str] = None,
) -> Optional[Generated]:
    """内核产一条客户可见正文。异常 / 超时 / 空正文 / 超工具上限 ⇒ None（调用方转人工）。"""
    content = (text or "").strip()
    if not content:
        return None
    try:
        agent = get_agent(agent_type=CUSTOMER_AGENT_TYPE)
        context = AgentContext(
            user_id=external_userid or session_id or "",
            tenant_id=tenant_id or 0,
            session_id=session_id or "",
            role="customer",
            identity_type="wechat_kf",
        )
        reply, tool_calls = await asyncio.wait_for(
            _stream_reply(agent, content, context), timeout=REPLY_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        logger.warning("[kf-reply] 生成超时（>{}s）⇒ 转人工", REPLY_TIMEOUT_SECONDS)
        return None
    except Exception as e:  # noqa: BLE001 — 生成失败必须降级，不能冒泡成 500
        logger.warning("[kf-reply] 生成失败（转人工）: {}", e)
        return None
    if not reply:
        return None
    return Generated(text=reply, tool_calls=tool_calls)


@router.post("/reply")
async def kf_reply_endpoint(
    request: KfReplyRequest,
    authorized: bool = Depends(verify_service_token),
):
    """微信客服回复生成（Service Token 认证，仅供 admin-api 调用）。"""
    generated = await generate_reply(
        request.tenant_id, request.session_id, request.text, request.external_userid
    )
    if generated is None:
        return make_response(
            False,
            error_code=ERR_REPLY_UNAVAILABLE,
            error_message="回复生成不可用，请转人工",
        )
    logger.info(
        "[kf-reply] tenant={} session={} len={} tool_calls={}",
        request.tenant_id, request.session_id, len(generated.text), generated.tool_calls,
    )
    return make_response(True, data={"text": generated.text, "tool_calls": generated.tool_calls})
