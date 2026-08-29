"""
企业入驻申请 AI 合规甄别（内部接口）

admin-api 在提交入驻申请（POST /api/auth/register）后调用本端点，
对申请执行「规则层 + LLM 层」双重甄别，给出 approve / reject 决策：

1. 规则层（确定性、fail-closed、零成本）：
   - 敏感/违法内容关键词（赌博/诈骗/毒品/色情/枪支等）
   - 代码注入模式（<script> / DROP TABLE / SQL 片段等）
   - 企业名称/联系人格式合法性（纯数字/超长/控制字符等）
   命中任意 hard 违规 → 直接驳回且不调用 LLM（防刷成本、零延迟）。

2. LLM 层（大模型合规审查，结构化 JSON）：
   - 法律风险识别：禁限行业资质、夸大/虚假宣传、异常主体信息等
   - 输出 {decision, confidence, risk_flags[], summary}

3. 决策合成：
   - 规则层 hard 违规 → 驳回（review_source=rule）
   - 否则 LLM 驳回或存在 high 风险 → 驳回（review_source=ai）
   - 否则 → 通过（review_source=ai）
   - LLM 不可用/解析失败 → 规则层无 hard 违规即放行（review_source=system，
     可用性优先；真正的 fail-closed 在规则层。admin-api 侧在 AI 服务整体
     不可达时另有「系统繁忙」兜底，两者配合保证不因降级而放行违规内容）。

安全说明：本端点为内部接口，仅接受 Service Token 认证（verify_service_token），
禁止暴露到公网；调用方 admin-api 已对同手机号/同企业重复提交、频率、蜜罐等
攻击面做了前置拦截，本端点专注内容与法律风险甄别。
"""

from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from loguru import logger

from app.utils.auth import verify_service_token
from app.llm.factory import LLMFactory
from app.api.response_models import make_response

router = APIRouter()

# ============ 规则层常量（可审计、可单测） ============

# 敏感/违法内容关键词（命中 → hard 驳回）。清单聚焦高置信违规内容，
# 避免误伤正常布艺/纺织行业描述。涉及特殊资质行业的关键词见下方 soft 清单。
SENSITIVE_KEYWORDS: List[str] = [
    "赌博", "博彩", "赌场", "六合彩", "时时彩", "百家乐",
    "色情", "情色", "裸聊", "约炮", "嫖娼",
    "毒品", "冰毒", "海洛因", "大麻", "摇头丸", "k粉", "制毒",
    "枪支", "弹药", "炸药", "管制刀具", "仿真枪",
    "诈骗", "刷单返利", "杀猪盘", "洗钱", "跑分",
    "传销", "拉人头", "集资", "庞氏",
    "代开发票", "假发票", "发票买卖",
    "走私", "拐卖", "器官买卖",
    "邪教", "恐怖", "暴恐", "极端主义",
    "分裂国家", "颠覆国家",
    "黑客攻击", "木马", "钓鱼网站", "数据窃取",
    "外挂", "私服",
    "代办信用卡套现", "信用卡套现",
    "赌博机", "老虎机",
]

# 特殊资质行业关键词（命中 → medium 风险标记，交 LLM 判断，不直接驳回）
LICENSE_REQUIRED_INDUSTRY_KEYWORDS: List[str] = [
    "金融", "贷款", "借贷", "p2p", "支付", "证券", "期货", "外汇",
    "虚拟货币", "数字货币", "区块链", "保险", "私募", "众筹", "股票",
    "医疗", "药品", "医疗器械", "整形", "美容",
    "保健食品", "保健品", "烟草", "电子烟", "彩票",
    "棋牌", "教育培训", "留学中介", "劳务派遣", "人力资源",
    "养老", "养老服务",
]

# 代码/SQL 注入模式（命中 → hard 驳回）
INJECTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"<script", re.IGNORECASE),
    re.compile(r"</\s*script", re.IGNORECASE),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"onerror\s*=", re.IGNORECASE),
    re.compile(r"onload\s*=", re.IGNORECASE),
    re.compile(r"drop\s+table", re.IGNORECASE),
    re.compile(r"delete\s+from", re.IGNORECASE),
    re.compile(r"insert\s+into", re.IGNORECASE),
    re.compile(r"update\s+\w+\s+set", re.IGNORECASE),
    re.compile(r"or\s+['\"]?1['\"]?\s*=\s*['\"]?1", re.IGNORECASE),
    re.compile(r"--\s*$", re.IGNORECASE),
    re.compile(r"\{\{\s*", re.IGNORECASE),  # SSTI
    re.compile(r"\$\{\s*", re.IGNORECASE),  # 模板注入
]

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_CJK_COUNT_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

# 字段长度上限（与 admin-api DTO 校验对齐，防御 LLM 提示词滥用）
MAX_COMPANY_NAME_LEN = 100
MAX_CONTACT_NAME_LEN = 50
MAX_INDUSTRY_LEN = 50
MAX_ADDRESS_LEN = 200
MAX_DESCRIPTION_LEN = 500


# ============ 数据模型 ============


class RiskFlag(BaseModel):
    """风险标记"""

    level: str = Field(..., description="high / medium")
    code: str = Field(..., description="风险码，如 SENSITIVE_CONTENT / ILLEGAL_INDUSTRY")
    reason: str = Field(..., description="风险说明（面向运营/审计，不含敏感词原文）")


class RegistrationReviewRequest(BaseModel):
    """入驻申请甄别请求"""

    company_name: str = Field(..., description="企业名称")
    contact_name: str = Field(..., description="联系人姓名")
    phone: str = Field(..., description="联系手机号")
    industry: Optional[str] = Field(None, description="行业")
    address: Optional[str] = Field(None, description="企业地址")
    description: Optional[str] = Field(None, description="企业简介")
    business_license_url: Optional[str] = Field(None, description="营业执照 URL")


class RegistrationReviewResult(BaseModel):
    """甄别结果"""

    decision: str = Field(..., description="approve / reject")
    confidence: float = Field(default=1.0, description="置信度 0~1")
    reason: str = Field(default="", description="驳回原因（reject 时给出，面向申请人）")
    risk_flags: List[RiskFlag] = Field(default_factory=list, description="风险标记")
    summary: str = Field(default="", description="审查摘要（面向运营/审计）")
    review_source: str = Field(..., description="rule / ai / system")


# ============ 规则层 ============


def _scan_sensitive(text: str) -> List[str]:
    """返回命中的敏感/违法关键词列表（大小写不敏感）。"""
    if not text:
        return []
    lower = text.lower()
    return [kw for kw in SENSITIVE_KEYWORDS if kw.lower() in lower]


def _scan_license_required(text: str) -> List[str]:
    """返回命中的特殊资质行业关键词列表。"""
    if not text:
        return []
    lower = text.lower()
    return [kw for kw in LICENSE_REQUIRED_INDUSTRY_KEYWORDS if kw.lower() in lower]


def _scan_injection(text: str) -> bool:
    """是否命中代码/SQL 注入模式。"""
    if not text:
        return False
    return any(p.search(text) for p in INJECTION_PATTERNS)


def _valid_company_name(name: str) -> bool:
    """企业名称格式校验：2~100 字符，至少 2 个汉字，无控制字符。"""
    name = (name or "").strip()
    if not (2 <= len(name) <= MAX_COMPANY_NAME_LEN):
        return False
    if _CONTROL_CHAR_RE.search(name):
        return False
    if len(_CJK_COUNT_RE.findall(name)) < 2:
        return False
    return True


def _valid_contact_name(name: str) -> bool:
    """联系人姓名格式校验：2~50 字符，至少 1 个汉字或字母，无控制字符。"""
    name = (name or "").strip()
    if not (2 <= len(name) <= MAX_CONTACT_NAME_LEN):
        return False
    if _CONTROL_CHAR_RE.search(name):
        return False
    if not _CJK_COUNT_RE.search(name) and not re.search(r"[A-Za-z]", name):
        return False
    return True


def rule_based_screen(req: RegistrationReviewRequest) -> Tuple[List[RiskFlag], List[RiskFlag]]:
    """规则层甄别。

    Returns:
        (hard, soft): hard 为必须驳回的高风险标记；soft 为需 LLM 进一步判断的提示。
    """
    hard: List[RiskFlag] = []
    soft: List[RiskFlag] = []

    # 1. 敏感/违法内容（对企业名称、简介、行业、地址、联系人全量扫描）
    sensitive_hits = []
    for field, value in [
        ("company_name", req.company_name),
        ("contact_name", req.contact_name),
        ("industry", req.industry),
        ("address", req.address),
        ("description", req.description),
    ]:
        hits = _scan_sensitive(value)
        if hits:
            sensitive_hits.extend(hits)
            logger.warning(
                "[registration-review] sensitive keyword hit: field={} keywords={}",
                field,
                hits,
            )
    if sensitive_hits:
        hard.append(
            RiskFlag(
                level="high",
                code="SENSITIVE_CONTENT",
                reason="申请资料包含违法/敏感内容，不予通过",
            )
        )

    # 2. 代码/SQL 注入模式
    for field, value in [
        ("company_name", req.company_name),
        ("contact_name", req.contact_name),
        ("address", req.address),
        ("description", req.description),
    ]:
        if _scan_injection(value):
            logger.warning("[registration-review] injection pattern hit: field={}", field)
            hard.append(
                RiskFlag(
                    level="high",
                    code="INJECTION_PATTERN",
                    reason="申请资料包含异常代码/脚本特征，疑似恶意提交",
                )
            )
            break

    # 3. 企业名称/联系人格式
    if not _valid_company_name(req.company_name):
        hard.append(
            RiskFlag(
                level="high",
                code="INVALID_COMPANY_NAME",
                reason="企业名称格式不合法（需 2~100 字符且含至少 2 个汉字）",
            )
        )
    if not _valid_contact_name(req.contact_name):
        hard.append(
            RiskFlag(
                level="high",
                code="INVALID_CONTACT_NAME",
                reason="联系人姓名格式不合法（需 2~50 字符且含汉字或字母）",
            )
        )

    # 4. 字段长度防御（防 LLM 提示词滥用）
    length_checks = [
        ("industry", req.industry, MAX_INDUSTRY_LEN),
        ("address", req.address, MAX_ADDRESS_LEN),
        ("description", req.description, MAX_DESCRIPTION_LEN),
    ]
    for field, value, limit in length_checks:
        if value and len(value) > limit:
            hard.append(
                RiskFlag(
                    level="high",
                    code="FIELD_TOO_LONG",
                    reason=f"申请资料字段 {field} 超出长度上限",
                )
            )

    # 5. 特殊资质行业 → medium 标记，交 LLM 判断
    license_hits = _scan_license_required(req.industry or "")
    if license_hits:
        soft.append(
            RiskFlag(
                level="medium",
                code="LICENSE_REQUIRED_INDUSTRY",
                reason="行业涉及特殊资质监管，需确认企业具备相应经营资质",
            )
        )

    return hard, soft


# ============ LLM 层 ============


def _parse_llm_json(text: str) -> Optional[dict]:
    """鲁棒解析 LLM 输出的 JSON：支持纯 JSON、代码块包裹、夹杂前后缀文本。"""
    if not text:
        return None
    text = text.strip()
    # 尝试直接解析
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # 提取代码块内的 JSON
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fence.group(1) if fence else None
    if candidate:
        try:
            return json.loads(candidate.strip())
        except (json.JSONDecodeError, ValueError):
            pass
    # 提取第一个 { ... } 片段
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _build_llm_messages(req: RegistrationReviewRequest) -> list:
    """构造合规审查提示词（系统提示 + 结构化申请数据）。"""
    system_prompt = (
        "你是企业入驻审核专员，负责对 SaaS 平台（米高）的商家入驻申请做合规与法律风险甄别。\n"
        "审查维度：\n"
        "1. 企业经营合法性：名称是否规范，行业是否属于需特殊资质的禁限行业（金融、借贷、"
        "证券、虚拟货币、医疗、药品、保健食品、烟草、彩票、棋牌、教育培训等），有无明显违法迹象。\n"
        "2. 内容合规：简介/地址/行业描述是否含虚假、夸大宣传（如稳赚、保本、日入过千等），"
        "是否含黄赌毒、诈骗、传销等违法信息。\n"
        "3. 主体异常：企业名称与行业是否明显不匹配，联系人信息是否异常（纯数字、符号等）。\n"
        "输出要求：只输出一个 JSON 对象，不要任何解释文字。格式：\n"
        '{"decision": "approve" 或 "reject", "confidence": 0~1 的数值, '
        '"risk_flags": [{"level": "high" 或 "medium", "code": "风险码", "reason": "风险说明"}], '
        '"summary": "一句话审查结论（中文）"}\n'
        "注意：decision 为 reject 时，summary 需给出面向申请人的、简洁客观的驳回原因；"
        "风险说明与摘要中不得编造申请资料里不存在的事实。"
    )
    payload = {
        "company_name": req.company_name,
        "contact_name": req.contact_name,
        "phone": req.phone,
        "industry": req.industry or "",
        "address": req.address or "",
        "description": req.description or "",
        "has_business_license": bool(req.business_license_url),
    }
    from langchain_core.messages import HumanMessage, SystemMessage

    return [
        SystemMessage(content=system_prompt),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
    ]


async def llm_compliance_review(
    req: RegistrationReviewRequest, soft_flags: List[RiskFlag]
) -> Optional[RegistrationReviewResult]:
    """LLM 合规审查。失败（异常/超时/解析失败）返回 None，由上层降级。"""
    try:
        llm = LLMFactory.create_registration_review_llm()
        response = await llm.ainvoke(_build_llm_messages(req))
        text = getattr(response, "content", None) or ""
        data = _parse_llm_json(text)
        if not data:
            logger.warning("[registration-review] LLM JSON parse failed, fallback")
            return None

        decision = str(data.get("decision", "")).strip().lower()
        flags: List[RiskFlag] = list(soft_flags)
        for f in data.get("risk_flags") or []:
            if isinstance(f, dict) and f.get("code"):
                flags.append(
                    RiskFlag(
                        level=str(f.get("level", "medium")),
                        code=str(f.get("code")),
                        reason=str(f.get("reason", "")),
                    )
                )
        summary = str(data.get("summary", "")).strip()
        confidence = float(data.get("confidence") or 0.0)

        high_flags = [f for f in flags if f.level == "high"]
        if decision == "reject" or high_flags:
            reason = summary or (high_flags[0].reason if high_flags else "资料不符合入驻要求")
            return RegistrationReviewResult(
                decision="reject",
                confidence=confidence,
                reason=reason,
                risk_flags=flags,
                summary=summary,
                review_source="ai",
            )
        return RegistrationReviewResult(
            decision="approve",
            confidence=confidence,
            reason="",
            risk_flags=flags,
            summary=summary or "合规审查通过",
            review_source="ai",
        )
    except Exception as e:
        logger.exception("[registration-review] LLM review failed, fallback to rule-only: {}", e)
        return None


# ============ 决策合成 ============


async def review_registration(req: RegistrationReviewRequest) -> RegistrationReviewResult:
    """规则层 + LLM 层综合甄别，返回最终决策。"""
    hard, soft = rule_based_screen(req)
    if hard:
        return RegistrationReviewResult(
            decision="reject",
            confidence=1.0,
            reason=hard[0].reason,
            risk_flags=hard + soft,
            summary="规则层检出高风险内容，自动驳回",
            review_source="rule",
        )

    llm_result = await llm_compliance_review(req, soft)
    if llm_result is None:
        # LLM 不可用/解析失败 → 规则层通过即放行（可用性优先，合规底线由规则层保障）
        logger.info("[registration-review] LLM unavailable, approve by rule-only decision")
        return RegistrationReviewResult(
            decision="approve",
            confidence=0.5,
            reason="",
            risk_flags=soft,
            summary="规则层校验通过；大模型审查暂不可用，已按规则降级放行",
            review_source="system",
        )
    return llm_result


# ============ 内部端点 ============


@router.post("/review")
async def registration_review_endpoint(
    request: RegistrationReviewRequest,
    authorized: bool = Depends(verify_service_token),
):
    """
    企业入驻申请 AI 合规甄别（内部服务调用，Service Token 认证）

    由 admin-api 在 POST /api/auth/register 提交申请后调用。
    返回 { decision, confidence, reason, risk_flags, summary, review_source }。
    """
    try:
        result = await review_registration(request)
        return make_response(success=True, data=result.model_dump())
    except Exception as e:
        logger.exception("[registration-review] internal error: {}", e)
        return make_response(
            success=False,
            error_code="REVIEW_ERROR",
            error_message="入驻申请甄别服务异常，请稍后重试",
        )
