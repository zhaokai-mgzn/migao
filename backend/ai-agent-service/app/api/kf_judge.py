"""微信客服语义判定（内部接口）

母单 #9194 子项 1（子单 #9196）。admin-api 的 `POST /api/internal/kf/decide` 原先只有
规则短路（state / 人工词 / 风险词），本模块补上语义判定面：intent / risk / emotion /
confidence / escalate。

口径（与 admin-api 的 `KfDecisionService` 共同构成「升级取并集」）：

- **规则优先**：admin-api 命中人工词/风险词时**不调用**本端点（省成本、省延迟，高风险不漏）；
  本端点只在规则未命中时被调用，用于补召回（情绪激动、模糊不满、要求承诺等规则抓不到的形态）。
- **高风险取保守侧**：模型给出 `risk=high` 但 `escalate=false`（自相矛盾）⇒ 仍判升级。
- **失败即回退**：LLM 异常 / 输出不可解析 / 空对象 ⇒ 返回 `success=false`
  （错误码 `KF_JUDGE_UNAVAILABLE`），admin-api 按规则结论放行 ——
  **绝不**因判定服务不可用而拒答客户（这是比误判更坏的故障）。
- 温度 0（复用 `LLMFactory.create_intent_llm`，thinking disabled 以降延迟），只取一个 JSON 对象。
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel, Field

from app.api.response_models import make_response
from app.llm.factory import LLMFactory
from app.utils.auth import verify_service_token

router = APIRouter()

ERR_JUDGE_UNAVAILABLE = "KF_JUDGE_UNAVAILABLE"
TEXT_MAX_CHARS = 2000

_JUDGE_PROMPT = (
    "你是微信客服的「是否需要人工接管」判定器。只输出一个 JSON 对象，不要任何解释文字。\n"
    "判定维度：\n"
    "1. intent：客户这句话的意图（询价 price / 下单 order / 售后 after_sales / "
    "物流 logistics / 转人工 human_request / 闲聊 chitchat / 其他 other）\n"
    "2. risk：风险等级 none | low | high"
    "（无法兑现的承诺、价格争议、质量投诉、法律威胁、索要隐私 ⇒ high）\n"
    "3. emotion：情绪 calm | upset | angry\n"
    "4. confidence：0~1，你对上述判定的置信度\n"
    "5. escalate：是否需要人工客服接管"
    "（客户明确要人工、投诉/退款/赔偿、情绪 angry、risk=high、"
    "或意图不清且涉及承诺时 true）\n"
    "6. reason：一句话中文说明（不超过 40 字）\n"
    '输出格式：{"intent":"...","risk":"...","emotion":"...",'
    '"confidence":0.0,"escalate":false,"reason":"..."}'
)


class KfJudgeRequest(BaseModel):
    """语义判定请求（tenant_id / session_id 只用于日志与 trace，不参与判定）。"""

    tenant_id: Optional[int] = Field(None, description="租户 ID")
    session_id: Optional[str] = Field(None, description="会话 ID")
    text: str = Field(..., max_length=TEXT_MAX_CHARS, description="客户最新一条消息")


class KfJudgeResult(BaseModel):
    intent: str = "other"
    risk: str = "none"
    emotion: str = "calm"
    confidence: float = 0.0
    escalate: bool = False
    reason: str = ""


def _parse_json(text: str) -> Optional[dict]:
    """从模型输出里抠出第一个 JSON 对象；抠不出（或空对象）返回 None。"""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and data else None


async def judge_text(text: str) -> Optional[KfJudgeResult]:
    """语义判定。LLM 异常 / 不可解析 / 空对象 ⇒ None（调用方回退规则）。"""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = LLMFactory.create_intent_llm()
        content = text[:TEXT_MAX_CHARS] if text else ""
        if not content.strip():
            return None
        response = await llm.ainvoke(
            [SystemMessage(content=_JUDGE_PROMPT), HumanMessage(content=content)]
        )
        raw = getattr(response, "content", None) or ""
        data = _parse_json(raw)
        if not data:
            logger.warning("[kf-judge] LLM 输出不可解析，回退规则: {}", str(raw)[:200])
            return None

        risk = str(data.get("risk") or "none").strip().lower()
        return KfJudgeResult(
            intent=str(data.get("intent") or "other").strip(),
            risk=risk,
            emotion=str(data.get("emotion") or "calm").strip().lower(),
            confidence=max(0.0, min(1.0, float(data.get("confidence") or 0.0))),
            # 模型自相矛盾时取保守侧：risk=high 一律升级（与 admin-api 的「永不漏」同口径）
            escalate=bool(data.get("escalate")) or risk == "high",
            reason=str(data.get("reason") or "").strip()[:80],
        )
    except Exception as e:  # noqa: BLE001 — 判定失败必须降级，不能冒泡成 500
        logger.warning("[kf-judge] 语义判定失败，回退规则: {}", e)
        return None


@router.post("/judge")
async def kf_judge_endpoint(
    request: KfJudgeRequest,
    authorized: bool = Depends(verify_service_token),
):
    """微信客服语义判定（Service Token 认证，仅供 admin-api 调用）。"""
    result = await judge_text(request.text or "")
    if result is None:
        return make_response(
            False,
            error_code=ERR_JUDGE_UNAVAILABLE,
            error_message="语义判定不可用，请按规则回退",
        )
    logger.info(
        "[kf-judge] tenant={} session={} intent={} risk={} escalate={} conf={}",
        request.tenant_id, request.session_id,
        result.intent, result.risk, result.escalate, result.confidence,
    )
    return make_response(True, data=result.model_dump())
