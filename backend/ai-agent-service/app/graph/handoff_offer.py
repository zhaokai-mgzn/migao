"""
小布 AI 主动引导转人工 — 建议节点（handoff_offer）

确定性节点（不调 LLM）：当 handoff_judge 判定 D3（AI 主动建议）命中后，
由 builder 路由到此节点，产出：
1. 安抚文案（final_answer → SSE text 事件）
2. interact choice 卡片（ToolMessage → SSE interactive 事件 → 前端 ChoiceCard）

卡片语义（value 即用户点击后发送的消息文本）：
- "转人工客服" → 下轮 intent_router 命中 D1 显式请求 → complaint 直转 human_handoff
- "继续咨询小布" → 正常 general 流程，且会话记冷却（本会话不再自动建议）

会话状态（session_states.state["handoff"]）：
- offer_count：累计自动建议次数（达上限后不再建议）
- last_user_refused：用户拒绝过 → 不再自动建议
读写 best-effort（失败仅记日志，不影响主流程），与 handoff_judge 共用语义。

设计见 docs/design/xiaobu-ai-handoff-guidance.md §4/§6。
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict
from uuid import uuid4

from langchain_core.messages import AIMessage, ToolMessage
from loguru import logger

from app.graph.handoff_judge import DEFAULT_HANDOFF_MAX_OFFERS

# ── 建议卡片文案 ──

_OFFER_TITLE = "这个问题比较特殊，需要为您转接人工客服吗？"
_OFFER_OPTIONS = [
    {"label": "👩‍💼 转人工客服", "value": "转人工客服"},
    {"label": "继续咨询小布", "value": "继续咨询小布"},
]

# 安抚文案模板（按信号定制首句）
_COMFORT_BY_SIGNAL = {
    "S1": "非常抱歉让您有不愉快的体验🙏 您反馈的问题我已经记下了，"
          "不过有些情况由人工客服专员跟进会更高效。",
    "S2": "非常抱歉这个问题反复给您添麻烦🙏 为了尽快帮您解决，"
          "建议转人工客服专员为您全程跟进。",
    "S3": "我理解您的情况比较特殊，这类问题需要人工客服专员按政策为您处理。",
}

# 兜底文案
_COMFORT_DEFAULT = "非常抱歉，为了更快帮您解决问题，建议转人工客服专员为您处理。"


def _build_offer_data(signal: str = "") -> Dict[str, Any]:
    """构造 interact choice 卡片数据（与 InteractTool choice 组件同构）"""
    return {
        "component": "choice",
        "title": _OFFER_TITLE,
        "options": _OFFER_OPTIONS,
    }


async def _load_handoff_state(session_id: str) -> Dict[str, Any]:
    """读取会话 handoff 状态（session_states.state["handoff"]），失败返回 {}"""
    if not session_id:
        return {}
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full_state = await store.load(session_id) or {}
        return full_state.get("handoff") or {}
    except Exception as e:
        logger.warning(f"[handoff_offer] load handoff state failed: {e}")
        return {}


async def _commit_offer_state(session_id: str, handoff_state: Dict[str, Any]) -> None:
    """写入会话 handoff 状态（best-effort，保留其余 state 字段）"""
    if not session_id:
        return
    try:
        from app.memory.session_state_store import SessionStateStore
        store = SessionStateStore()
        full_state = await store.load(session_id) or {}
        full_state["handoff"] = handoff_state
        await store.commit(session_id, full_state)
    except Exception as e:
        logger.warning(f"[handoff_offer] commit handoff state failed: {e}")


async def handoff_offer_node(state: dict) -> dict:
    """建议转人工节点：安抚文案 + interact choice 卡片 + 冷却状态写入

    输入 state 需含：session_id / tenant_id / user_id / intent_result（signal 来源）。
    """
    session_id = state.get("session_id", "")
    signal = (state.get("intent_result") or {}).get("signal", "")

    # 1. 安抚文案
    comfort = _COMFORT_BY_SIGNAL.get(signal, _COMFORT_DEFAULT)

    # 2. interact choice 卡片（value 语义见模块 docstring）
    choice_data = _build_offer_data(signal)
    tool_call_id = f"handoff_{uuid4().hex[:8]}"
    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "interact",
                "args": choice_data,
                "id": tool_call_id,
            }
        ],
    )
    tool_payload = {
        "success": True,
        "data": choice_data,
        "message": f"已展示{choice_data['title']}交互组件，等待用户操作",
    }
    tool_msg = ToolMessage(
        name="interact",
        tool_call_id=tool_call_id,
        content=json.dumps(tool_payload, ensure_ascii=False),
    )

    # 3. 冷却状态：offer_count +1（best-effort）
    try:
        handoff_state = await _load_handoff_state(session_id)
        offer_count = int(handoff_state.get("offer_count") or 0) + 1
        handoff_state["offer_count"] = offer_count
        handoff_state["last_offer_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await _commit_offer_state(session_id, handoff_state)
        logger.info(
            f"[handoff_offer] offer_count={offer_count}/{DEFAULT_HANDOFF_MAX_OFFERS} "
            f"| session={session_id}"
        )
    except Exception as e:
        logger.warning(f"[handoff_offer] cooldown update failed (non-fatal): {e}")

    return {
        "messages": [ai_msg, tool_msg],
        "final_answer": comfort,
        "skill_used": "handoff_offer",
    }
