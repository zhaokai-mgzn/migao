"""app/api/registration_review.py 单元测试 — 企业入驻申请 AI 合规甄别。

覆盖：
- 规则层（确定性 fail-closed）：敏感/违法内容、注入模式、企业名称格式
- LLM 层：结构化 JSON 审查、解析失败/异常降级
- 决策合成：规则 hard 违规优先驳回；LLM 不可用时规则通过即放行
- 内部端点：Service Token 认证、错误封装
"""
# case_ids: OB-001, OB-002, OB-003

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.registration_review import (
    RegistrationReviewRequest,
    RegistrationReviewResult,
    rule_based_screen,
    review_registration,
    _parse_llm_json,
)
from app.config import settings

# ============ 规则层 ============


def _req(**overrides):
    base = dict(
        company_name="杭州锦绣布艺有限公司",
        contact_name="张三",
        phone="13800138000",
        industry="布艺纺织",
        address="浙江省杭州市余杭区",
        description="主营窗帘、家纺布艺产品的设计生产与销售",
        business_license_url="",
    )
    base.update(overrides)
    return RegistrationReviewRequest(**base)


class TestRuleBasedScreen:
    def test_clean_data_no_violations(self):
        hard, soft = rule_based_screen(_req())
        assert hard == []
        assert soft == []

    @pytest.mark.parametrize(
        "field,value,keyword",
        [
            ("company_name", "某某网络赌博平台", "赌博"),
            ("description", "专业办理刷单返利，日入过千", "刷单"),
            ("industry", "博彩运营", "博彩"),
            ("address", "售卖管制刀具一条街", "刀具"),
        ],
    )
    def test_sensitive_keyword_hard_reject(self, field, value, keyword):
        hard, soft = rule_based_screen(_req(**{field: value}))
        assert hard, f"字段 {field}={value!r} 应命中敏感词 {keyword}"
        assert hard[0].level == "high"
        assert "SENSITIVE_CONTENT" in {f.code for f in hard}

    @pytest.mark.parametrize(
        "company_name",
        ["12345678", "AAAA", "😀😀😀😀", "x", "a" * 101, "   "],
    )
    def test_invalid_company_name_format(self, company_name):
        hard, soft = rule_based_screen(_req(company_name=company_name))
        assert hard
        assert hard[0].code == "INVALID_COMPANY_NAME"

    @pytest.mark.parametrize(
        "company_name",
        ["<script>alert(1)</script>", "DROP TABLE tenant_applications;--", "张三'); DELETE FROM users; --"],
    )
    def test_injection_pattern_hard_reject(self, company_name):
        hard, soft = rule_based_screen(_req(company_name=company_name))
        assert hard
        assert hard[0].code == "INJECTION_PATTERN"

    def test_license_required_industry_is_soft_flag(self):
        hard, soft = rule_based_screen(_req(industry="网络借贷信息中介"))
        assert hard == []
        assert any(f.code == "LICENSE_REQUIRED_INDUSTRY" for f in soft)
        assert all(f.level == "medium" for f in soft)


# ============ 决策合成 ============


class TestReviewDecision:
    @pytest.mark.asyncio
    async def test_llm_approve_with_medium_flags(self):
        with patch(
            "app.api.registration_review.LLMFactory.create_registration_review_llm"
        ) as mk:
            llm = MagicMock()
            llm.ainvoke = AsyncMock(
                return_value=MagicMock(
                    content=json.dumps(
                        {
                            "decision": "approve",
                            "confidence": 0.95,
                            "risk_flags": [],
                            "summary": "合法合规，准予入驻",
                        },
                        ensure_ascii=False,
                    )
                )
            )
            mk.return_value = llm
            result = await review_registration(_req())
        assert result.decision == "approve"
        assert result.review_source == "ai"

    @pytest.mark.asyncio
    async def test_llm_reject_legal_risk(self):
        with patch(
            "app.api.registration_review.LLMFactory.create_registration_review_llm"
        ) as mk:
            llm = MagicMock()
            llm.ainvoke = AsyncMock(
                return_value=MagicMock(
                    content=json.dumps(
                        {
                            "decision": "reject",
                            "confidence": 0.9,
                            "risk_flags": [
                                {
                                    "level": "high",
                                    "code": "ILLEGAL_INDUSTRY",
                                    "reason": "企业名称暗示无资质开展金融业务",
                                }
                            ],
                            "summary": "疑似无资质金融业务",
                        },
                        ensure_ascii=False,
                    )
                )
            )
            mk.return_value = llm
            result = await review_registration(_req())
        assert result.decision == "reject"
        assert result.review_source == "ai"
        assert "金融" in result.reason

    @pytest.mark.asyncio
    async def test_rule_hard_violation_overrides_llm_approve(self):
        with patch(
            "app.api.registration_review.LLMFactory.create_registration_review_llm"
        ) as mk:
            llm = MagicMock()
            llm.ainvoke = AsyncMock(
                return_value=MagicMock(
                    content=json.dumps({"decision": "approve", "confidence": 1.0, "risk_flags": [], "summary": "ok"})
                )
            )
            mk.return_value = llm
            result = await review_registration(_req(description="开设网络赌场，欢迎下注"))
        assert result.decision == "reject"
        assert result.review_source == "rule"
        mk.assert_not_called()  # 规则命中后不再调用 LLM（防刷成本）

    @pytest.mark.asyncio
    async def test_llm_unavailable_fallback_approve(self):
        with patch(
            "app.api.registration_review.LLMFactory.create_registration_review_llm",
            side_effect=RuntimeError("LLM service down"),
        ):
            result = await review_registration(_req())
        assert result.decision == "approve"
        assert result.review_source == "system"

    @pytest.mark.asyncio
    async def test_llm_unparseable_fallback_approve(self):
        with patch(
            "app.api.registration_review.LLMFactory.create_registration_review_llm"
        ) as mk:
            llm = MagicMock()
            llm.ainvoke = AsyncMock(return_value=MagicMock(content="抱歉，我无法提供该服务"))
            mk.return_value = llm
            result = await review_registration(_req())
        assert result.decision == "approve"
        assert result.review_source == "system"

    @pytest.mark.asyncio
    async def test_llm_unavailable_with_rule_hard_violation_still_rejects(self):
        with patch(
            "app.api.registration_review.LLMFactory.create_registration_review_llm",
            side_effect=RuntimeError("LLM service down"),
        ):
            result = await review_registration(_req(description="诈骗电话引流"))
        assert result.decision == "reject"
        assert result.review_source == "rule"


class TestParseLlmJson:
    def test_pure_json(self):
        assert _parse_llm_json('{"decision": "approve"}')["decision"] == "approve"

    def test_json_inside_code_fence(self):
        text = '```json\n{"decision": "reject"}\n```'
        assert _parse_llm_json(text)["decision"] == "reject"

    def test_json_with_prose(self):
        text = '审查结论如下：\n{"decision": "approve", "confidence": 0.9}\n以上。'
        assert _parse_llm_json(text)["decision"] == "approve"

    def test_invalid_returns_none(self):
        assert _parse_llm_json("not json at all") is None


class TestLlmPromptRules:
    """LLM 提示词判定原则（防止大模型误驳回合法商家）"""

    def test_license_optional_not_reject_ground(self):
        from app.api.registration_review import _build_llm_messages

        sys_msg = _build_llm_messages(_req())[0].content
        assert "营业执照为选填项" in sys_msg
        assert "不构成驳回理由" in sys_msg

    def test_missing_optional_fields_not_reject_ground(self):
        from app.api.registration_review import _build_llm_messages

        sys_msg = _build_llm_messages(_req())[0].content
        assert "缺失字段" in sys_msg and "不构成驳回理由" in sys_msg

    def test_payload_contains_license_flag(self):
        from app.api.registration_review import _build_llm_messages

        human_msg = _build_llm_messages(_req(business_license_url="https://oss.example.com/a.jpg"))[1].content
        assert '"has_business_license": true' in human_msg
        human_msg2 = _build_llm_messages(_req())[1].content
        assert '"has_business_license": false' in human_msg2


# ============ 内部端点 ============


@pytest.fixture
def client():
    """本地 TestClient（conftest 的 test_client fixture 引用了已移除的
    app.main.get_rag_pipeline，此处仅 patch 实际存在的生命周期依赖）。"""
    from fastapi.testclient import TestClient

    with patch("app.utils.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.database.close_db", new_callable=AsyncMock), \
         patch("app.utils.redis_client.init_redis", new_callable=AsyncMock), \
         patch("app.utils.redis_client.close_redis", new_callable=AsyncMock):
        from app.main import create_app
        app = create_app()
        with TestClient(app) as c:
            yield c


def _call_endpoint(client, token=None, payload=None):
    """默认携带 settings.SERVICE_TOKEN（CI 中为 ci-dummy，本地为 .env 值），
    与 verify_service_token 的实际校验值保持一致。"""
    return client.post(
        "/api/internal/registration/review",
        headers={"X-Service-Token": token if token is not None else settings.SERVICE_TOKEN},
        json=payload or _req().model_dump(),
    )


class TestReviewEndpoint:
    @pytest.fixture(autouse=True)
    def _mock_llm(self):
        llm = MagicMock()
        llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content=json.dumps(
                    {"decision": "approve", "confidence": 0.95, "risk_flags": [], "summary": "合规"}
                )
            )
        )
        with patch(
            "app.api.registration_review.LLMFactory.create_registration_review_llm",
            return_value=llm,
        ):
            yield

    def test_requires_service_token(self, client):
        resp = _call_endpoint(client, token="")
        assert resp.status_code == 401
        assert "AUTH_REQUIRED" in resp.text

    def test_rejects_bad_token(self, client):
        resp = _call_endpoint(client, token="wrong-token")
        assert resp.status_code == 401
        assert "AUTH_REQUIRED" in resp.text

    def test_approve_response_shape(self, client):
        resp = _call_endpoint(client)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["decision"] == "approve"
        assert body["data"]["review_source"] == "ai"
        assert isinstance(body["data"]["risk_flags"], list)

    def test_rule_reject_response(self, client):
        payload = _req(description="网络赌博平台招商加盟").model_dump()
        resp = _call_endpoint(client, payload=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["decision"] == "reject"
        assert body["data"]["review_source"] == "rule"
