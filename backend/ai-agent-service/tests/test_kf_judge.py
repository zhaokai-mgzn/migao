# case_ids: KF-025
"""app/api/kf_judge.py 单元测试 — 微信客服语义判定（issue #9196 / 母单 #9194 子项 1）。

覆盖：
- 解析：裸 JSON / ```json 围栏 / 前后杂文字
- 合成：risk=high ⇒ escalate 强制 true（高风险永不漏）；confidence 透传
- 降级：LLM 异常 / 不可解析 / 缺字段 ⇒ judge_text 返回 None（调用方按规则回退）
- 端点：合法入参 ⇒ success=true 且 intent/risk/emotion/confidence/escalate 齐全；
  LLM 不可用 ⇒ success=false + error.code=KF_JUDGE_UNAVAILABLE（HTTP 仍 200）
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.kf_judge import _parse_json, judge_text
from app.config import settings


def _llm_returning(content: str) -> MagicMock:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=content))
    return llm


# ============ 解析 ============


class TestParseJson:
    def test_plain_json(self):
        assert _parse_json('{"intent":"price","risk":"none"}') == {
            "intent": "price",
            "risk": "none",
        }

    def test_fenced_json(self):
        text = '```json\n{"intent":"chitchat","risk":"low","escalate":false}\n```'
        assert _parse_json(text)["intent"] == "chitchat"

    def test_surrounded_by_prose(self):
        text = '判定如下：{"intent":"price","confidence":0.8} 以上。'
        assert _parse_json(text)["confidence"] == 0.8

    def test_garbage_returns_none(self):
        assert _parse_json("抱歉，我无法判断") is None


# ============ 合成 ============


class TestJudgeText:
    @pytest.mark.asyncio
    async def test_ok_parses_all_fields(self):
        payload = {
            "intent": "human_request",
            "risk": "high",
            "emotion": "angry",
            "confidence": 0.91,
            "escalate": True,
            "reason": "客户要求人工并提到投诉",
        }
        with patch(
            "app.api.kf_judge.LLMFactory.create_intent_llm",
            return_value=_llm_returning(json.dumps(payload, ensure_ascii=False)),
        ):
            result = await judge_text("我要投诉，转人工")

        assert result is not None
        assert result.intent == "human_request"
        assert result.risk == "high"
        assert result.emotion == "angry"
        assert result.confidence == pytest.approx(0.91)
        assert result.escalate is True
        assert "投诉" in result.reason

    @pytest.mark.asyncio
    async def test_risk_high_forces_escalate(self):
        """LLM 说不用升级、但 risk=high ⇒ 仍升级（模型自相矛盾时取保守侧）。"""
        payload = {"intent": "complaint", "risk": "high", "escalate": False, "confidence": 0.6}
        with patch(
            "app.api.kf_judge.LLMFactory.create_intent_llm",
            return_value=_llm_returning(json.dumps(payload)),
        ):
            result = await judge_text("你们这什么破质量")
        assert result is not None
        assert result.escalate is True

    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self):
        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("upstream 502"))
        with patch("app.api.kf_judge.LLMFactory.create_intent_llm", return_value=llm):
            assert await judge_text("这款多少钱") is None

    @pytest.mark.asyncio
    async def test_unparseable_returns_none(self):
        with patch(
            "app.api.kf_judge.LLMFactory.create_intent_llm",
            return_value=_llm_returning("我不知道该怎么回答"),
        ):
            assert await judge_text("这款多少钱") is None

    @pytest.mark.asyncio
    async def test_empty_json_object_returns_none(self):
        """空对象 = 没有可用信号，按不可用处理（回退规则），不伪造默认升级。"""
        with patch(
            "app.api.kf_judge.LLMFactory.create_intent_llm",
            return_value=_llm_returning("{}"),
        ):
            assert await judge_text("这款多少钱") is None


# ============ 端点 ============


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with patch("app.utils.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.database.close_db", new_callable=AsyncMock), \
         patch("app.utils.redis_client.init_redis", new_callable=AsyncMock), \
         patch("app.utils.redis_client.close_redis", new_callable=AsyncMock):
        from app.main import create_app

        app = create_app()
        with TestClient(app) as c:
            yield c


def _post(client, payload=None, token="__default__"):
    return client.post(
        "/api/internal/kf/judge",
        headers={
            "X-Service-Token": settings.SERVICE_TOKEN if token == "__default__" else token
        },
        json=payload or {"tenant_id": 1, "session_id": "s-1", "text": "这款多少钱"},
    )


class TestJudgeEndpoint:
    def test_ok(self, client):
        from app.api.kf_judge import KfJudgeResult

        result = KfJudgeResult(
            intent="price",
            risk="none",
            emotion="calm",
            confidence=0.88,
            escalate=False,
            reason="询价",
        )
        with patch("app.api.kf_judge.judge_text", new=AsyncMock(return_value=result)):
            resp = _post(client)

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert data["intent"] == "price"
        assert data["risk"] == "none"
        assert data["emotion"] == "calm"
        assert data["confidence"] == pytest.approx(0.88)
        assert data["escalate"] is False

    def test_llm_unavailable_is_reported_not_500(self, client):
        with patch("app.api.kf_judge.judge_text", new=AsyncMock(return_value=None)):
            resp = _post(client)

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "KF_JUDGE_UNAVAILABLE"

    def test_requires_service_token(self, client):
        resp = _post(client, token="wrong-token")
        assert resp.status_code in (401, 403)
