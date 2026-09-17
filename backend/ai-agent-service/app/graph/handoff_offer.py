"""
小布 AI 主动引导（"问题比较特殊"时的替代出路）— 建议节点（handoff_offer）

确定性节点（不调 LLM）：当 handoff_judge 判定 D3（AI 主动建议）命中后，
由 builder 路由到此节点，产出：
1. 安抚文案（final_answer → SSE text 事件）
2. interact choice 卡片（ToolMessage → SSE interactive 事件 → 前端 ChoiceCard）

⚠️ **2026-09-19 用户裁定「不应该存在 human_handoff 这种东西，以后全是 AI 来判断」**：
本节点原为「邀约人工转接」的卡片，退场后那种卡片就成了**用户可见面在邀约一个
不存在的能力**（点下去只会得到"无人工通道"的诚实回答 = 自相矛盾）。
本次**只改文案与选项语义**（确定性节点与卡片机制保留，子系统删除属阶段二）：
卡片从「要不要人工介入」变成「要不要我把您的情况整理成**售后工单**跟进」= **继续受理**。

卡片语义（value 即用户点击后发送的消息文本）：
- "帮我把问题整理成售后工单" → 下轮 `rule_matcher` 命中 `after_sales`（source=rule）→
  售后 skill 受理（收集订单/原因 → 弹确认卡 → `aftersale_create` 落成工单）
- "继续咨询小布" → 正常 general 流程，且会话记冷却（本会话不再自动建议）

**本文件的字符串文案不得出现"邀约人工转接"的措辞**（判据锚在本文件的字面量上：
`tests/unit_ci_workflows/test_human_handoff_retired.py::test_offer_copy_does_not_invite_a_handoff`；
注释可留档历史）。

会话状态（session_states.state["handoff"]）：
- offer_count：累计自动建议次数（达上限后不再建议）
- last_user_refused：用户拒绝过 → 不再自动建议
读写 best-effort（失败仅记日志，不影响主流程），与 handoff_judge 共用语义。

设计沿革见 docs/design/xiaobu-ai-handoff-guidance.md（**该文档描述的"人工转接建议卡"已失效**，
阶段二随子系统删除一并清理）。
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict
from uuid import uuid4

from langchain_core.messages import AIMessage, ToolMessage
from loguru import logger

from app.graph.handoff_judge import DEFAULT_HANDOFF_MAX_OFFERS

# ── 建议卡片文案（"继续受理"形态：把问题整理成售后工单，而不是转给不存在的人工）──

_OFFER_TITLE = "这个问题比较特殊，要我把您的情况整理成售后工单跟进吗？"
_OFFER_OPTIONS = [
    # value = 用户点击后发送的消息：命中 `rule_matcher` 的 after_sales 关键词（"售后"）
    # ⇒ 下轮进入售后 skill 受理（可落成工单），见模块 docstring 的语义表。
    {"label": "🧾 整理成售后工单", "value": "帮我把问题整理成售后工单"},
    {"label": "继续咨询小布", "value": "继续咨询小布"},
]

# 安抚文案模板（按信号定制首句）—— 一律给"继续受理"的出路，不承诺人工转接
_COMFORT_BY_SIGNAL = {
    "S1": "非常抱歉让您有不愉快的体验🙏 您反馈的问题我已经记下了。"
          "为了不让您反复复述，要不要我把情况整理成售后工单，由商家按流程跟进？",
    "S2": "非常抱歉这个问题反复给您添麻烦🙏 为了尽快帮您解决，"
          "建议我把您的情况整理成售后工单，由商家核实后跟进。",
    "S3": "我理解您的情况比较特殊，这类问题建议整理成售后工单，由商家按流程为您处理。",
}

# 兜底文案
_COMFORT_DEFAULT = "非常抱歉，为了更快帮您解决问题，建议我把您的情况整理成售后工单跟进。"


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
    """主动建议节点（退场后语义 = 建议把问题整理成售后工单）：安抚文案 + interact choice 卡片 + 冷却状态写入

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
