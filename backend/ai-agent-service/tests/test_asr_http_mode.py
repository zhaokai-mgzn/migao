"""Token Plan **非实时**语音识别（HTTP 通道，issue #8987）

# case_ids: API-024

## 为什么要这一组判据

Token Plan 订阅（`sk-sp-` key）里唯一可用的语音识别模型 `qwen-audio-3.0-asr-flash` 是
**非实时**的：它走与生图**完全相同**的多模态端点，不接 WebSocket 实时识别 ⇒ 既有
`app/api/asr.py` 只有实时通道时，语音在生产**根本不通**。

三个「静默错」形态，缺一条就重新踩回去：
1. 🔴 **`parameters.format` 必填** —— 少了它网关回 **`400 {}`（空 body，~90ms 拒单）**，
   没有 message 可读。本组用「发出去的请求体」钉住它（`TestHttpRequestContract`），
   把实现里的 `parameters` 删掉 ⇒ 判据必须红。
2. **响应文本在 `output.text`** —— 读错字段 ⇒ 识别成功却回「未识别到语音内容」。
3. **默认值必须是 `realtime`** —— 缺省切通道 ⇒ 改一个必填项就悄悄改掉既有部署行为。

断言只认**结构**（请求体字段、异常类型、HTTP 状态码），**不拿识别文案当锚点**。
"""
import json

import pytest

from app.api import asr as asr_mod


class _Resp:
    """httpx.Response 的最小替身（只用到 status_code / text / json()）。"""

    def __init__(self, status_code, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else (
            json.dumps(payload) if payload is not None else ""
        )

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeAsyncClient:
    """`httpx.AsyncClient` 替身：记录**发出去的请求**，回放预设响应。

    记录请求体是本组判据的核心能力 —— `parameters.format` 这种「漏了就 400 空 body」
    的契约，只有断言**实际发出**的载荷才拦得住（断言返回值拦不住）。
    """

    calls: list = []
    response = None
    raise_on_post = None

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, headers=None, json=None):
        type(self).calls.append({"url": url, "headers": dict(headers or {}), "json": json})
        if type(self).raise_on_post is not None:
            raise type(self).raise_on_post
        return type(self).response


def _reset_fake(response=None, raise_on_post=None):
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = response
    _FakeAsyncClient.raise_on_post = raise_on_post


@pytest.fixture
def http_mode(monkeypatch):
    """把模块级 settings 就位到 http 通道；音频转码与 httpx 都换成替身。"""
    monkeypatch.setattr(asr_mod.settings, "ASR_MODE", "http")
    monkeypatch.setattr(asr_mod.settings, "ASR_API_KEY", "sk-sp-test-key")
    monkeypatch.setattr(asr_mod, "_convert_to_wav", lambda data, fmt: b"wav-16k-mono-bytes")
    monkeypatch.setattr(asr_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _reset_fake()
    return _FakeAsyncClient


def _ok_json(text, **extra):
    payload = {"output": {"text": text}}
    payload["output"].update(extra)
    return {"output": payload["output"]}


async def _transcribe(audio: bytes = b"raw-audio", fmt: str = "wav") -> str:
    return await asr_mod._transcribe_audio(audio, format=fmt, sample_rate=16000)


class TestHttpRequestContract:
    """请求契约：模型 / 端点 / 鉴权 / data-URI / **`parameters.format` 必填**"""

    async def test_returns_output_text(self, http_mode):
        _reset_fake(_Resp(200, _ok_json("这是一段识别结果")))
        text = await _transcribe()
        assert text == "这是一段识别结果"

    async def test_request_body_carries_parameters_format(self, http_mode):
        """🔴 注入式红证：把实现里的 `parameters`（尤其 `format`）删掉 ⇒ 本条必须红。

        Token Plan 网关对缺 `parameters.format` 的请求回 `400 {}`（空 body），
        只有断言**发出去**的载荷才拦得住。
        """
        _reset_fake(_Resp(200, _ok_json("x")))
        await _transcribe()

        body = http_mode.calls[0]["json"]
        assert "parameters" in body, "请求体缺 parameters ⇒ 网关 400 空 body"
        params = body["parameters"]
        assert params["format"] == "wav", "parameters.format 是必填项，缺了网关 400 空 body"
        assert params["sample_rate"] == 16000
        assert params["language_hints"] == ["zh"]

    async def test_request_shape_endpoint_auth_and_audio_data_uri(self, http_mode):
        _reset_fake(_Resp(200, _ok_json("x")))
        await _transcribe(audio=b"raw-audio")

        call = http_mode.calls[0]
        assert call["url"] == asr_mod.settings.ASR_HTTP_URL
        assert call["url"].endswith("/api/v1/services/aigc/multimodal-generation/generation")
        assert call["headers"]["Authorization"] == "Bearer sk-sp-test-key"
        assert call["headers"]["Content-Type"] == "application/json"

        body = call["json"]
        assert body["model"] == asr_mod.settings.ASR_HTTP_MODEL
        content = body["input"]["messages"][0]["content"]
        assert content[0]["type"] == "input_audio"
        data_uri = content[0]["input_audio"]["data"]
        assert data_uri.startswith("data:audio/wav;base64,")
        import base64

        assert base64.b64decode(data_uri.split(",", 1)[1]) == b"wav-16k-mono-bytes"

    async def test_top_level_text_is_also_accepted(self, http_mode):
        """2026-11-21 生产实测里响应顶层也带 `text` ⇒ 读不到 `output.text` 时按实测形态兜底。"""
        _reset_fake(_Resp(200, {"text": "顶层文本"}))
        assert await _transcribe() == "顶层文本"


class TestHttpNoSpeech:
    def test_extract_sentence_text(self):
        """句子级形态 `output.sentence.text` 也能取到（官方契约的第二种形状）。"""
        data = {"output": {"sentence": {"text": "句子级文本"}}}
        assert asr_mod._extract_http_text(data) == "句子级文本"

    async def test_empty_output_text_raises_no_speech(self, http_mode):
        _reset_fake(_Resp(200, {"output": {"text": "   "}}))
        with pytest.raises(asr_mod.ASRNoSpeechError) as excinfo:
            await _transcribe()
        assert "未识别到语音内容" in str(excinfo.value)

    async def test_empty_output_text_maps_to_http_400(self, http_mode):
        """端点层沿用既有语义：没识别到语音 ⇒ 400（不是 500、也不是「识别成功空串」）。"""
        from unittest.mock import AsyncMock, MagicMock

        from fastapi import HTTPException

        _reset_fake(_Resp(200, {"output": {"text": ""}}))
        audio = MagicMock()
        audio.read = AsyncMock(return_value=b"\x00" * 64 * 1024)
        audio.filename = "recording.wav"
        audio.content_type = "audio/wav"

        with pytest.raises(HTTPException) as excinfo:
            await asr_mod.transcribe_audio(audio=audio, current_user=MagicMock(tenant_id=1))
        assert excinfo.value.status_code == 400


class TestHttpErrorMapping:
    """错误映射：401/403 不可用 · 429 配额 · 5xx 暂时不可用（各是各的下一个动作）"""

    @pytest.mark.parametrize("status", [401, 403])
    async def test_auth_failures_raise_auth_error(self, http_mode, status):
        _reset_fake(_Resp(status, {"code": "InvalidApiKey"}))
        with pytest.raises(asr_mod.ASRAuthError):
            await _transcribe()

    async def test_429_raises_quota_error(self, http_mode):
        _reset_fake(_Resp(429, {"code": "Throttling"}))
        with pytest.raises(asr_mod.ASRQuotaError):
            await _transcribe()

    @pytest.mark.parametrize("status", [500, 502, 503])
    async def test_5xx_raises_unavailable(self, http_mode, status):
        _reset_fake(_Resp(status, {}))
        with pytest.raises(asr_mod.ASRUnavailableError):
            await _transcribe()

    async def test_400_mentions_format_pitfall(self, http_mode):
        """400 最常见的成因是 `parameters.format` 漏了（空 body）；仍按「暂时不可用」上抛。"""
        _reset_fake(_Resp(400, {}))
        with pytest.raises(asr_mod.ASRUnavailableError):
            await _transcribe()

    async def test_network_failure_is_unavailable(self, http_mode):
        import httpx

        _reset_fake(raise_on_post=httpx.ConnectError("boom"))
        with pytest.raises(asr_mod.ASRUnavailableError):
            await _transcribe()

    async def test_non_json_body_is_unavailable(self, http_mode):
        _reset_fake(_Resp(200, payload=ValueError("not json"), text="<html>not json</html>"))
        with pytest.raises(asr_mod.ASRUnavailableError):
            await _transcribe()

    async def test_failure_maps_to_http_503(self, http_mode):
        from unittest.mock import AsyncMock, MagicMock

        from fastapi import HTTPException

        _reset_fake(_Resp(500, {}))
        audio = MagicMock()
        audio.read = AsyncMock(return_value=b"\x00" * 64 * 1024)
        audio.filename = "recording.wav"
        audio.content_type = "audio/wav"

        with pytest.raises(HTTPException) as excinfo:
            await asr_mod.transcribe_audio(audio=audio, current_user=MagicMock(tenant_id=1))
        assert excinfo.value.status_code == 503

    async def test_logs_never_carry_key_or_response_body(self, http_mode, monkeypatch):
        """🔴 日志里不得出现 key、也不得出现响应体（响应体可能回显请求片段）。"""
        from unittest.mock import MagicMock

        fake_logger = MagicMock()
        monkeypatch.setattr(asr_mod, "logger", fake_logger)
        secret_body = '{"code":"InvalidApiKey","message":"resp-body-marker-7f3a"}'
        _reset_fake(_Resp(401, {"code": "InvalidApiKey"}, text=secret_body))

        with pytest.raises(asr_mod.ASRAuthError):
            await _transcribe()

        logged = " ".join(
            str(call.args[0] if call.args else call.kwargs)
            for call in (
                fake_logger.error.call_args_list
                + fake_logger.warning.call_args_list
                + fake_logger.info.call_args_list
            )
        )
        assert logged, "失败路径至少要留一条日志（否则线上只看到 503，无法归因）"
        assert "sk-sp-test-key" not in logged, f"日志泄漏了 key：{logged}"
        assert "resp-body-marker" not in logged, f"日志泄漏了响应体：{logged}"


class TestRealtimeRollbackPath:
    """默认口径：`ASR_MODE` 缺省 = `realtime`，既有实时通道仍是回滚口"""

    def test_default_mode_is_realtime(self):
        from app.config import Settings

        assert Settings.model_fields["ASR_MODE"].default == "realtime"

    def test_default_http_url_points_to_maas_endpoint(self):
        from app.config import Settings

        assert Settings.model_fields["ASR_HTTP_URL"].default == (
            "https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/"
            "multimodal-generation/generation"
        )
        assert Settings.model_fields["ASR_HTTP_MODEL"].default == "qwen-audio-3.0-asr-flash"

    def test_constructed_settings_default_mode_is_realtime(self, monkeypatch):
        """不带 env / .env 构造 ⇒ 仍是 realtime（不改变既有部署行为）。"""
        from app.config import Settings

        monkeypatch.delenv("ASR_MODE", raising=False)
        s = Settings(
            _env_file=None,
            DEBUG=False,
            SERVICE_TOKEN="svc-token",
            JWT_PUBLIC_KEY="jwt-key",
            LOGISTICS_API_URL="https://wuliu.example.com",
            LOGISTICS_APPCODE="appcode",
            SSE_TIMEOUT=300,
            SSE_PING_INTERVAL=30,
            CORS_ALLOWED_ORIGINS="http://localhost:3000",
        )
        assert s.ASR_MODE == "realtime"

    async def test_realtime_mode_never_calls_http_endpoint(self, monkeypatch):
        """realtime 通道行为不变：不构造 httpx、仍走 Recognition（回滚口真的还在）。"""
        monkeypatch.setattr(asr_mod.settings, "ASR_MODE", "realtime")
        monkeypatch.setattr(asr_mod.settings, "ASR_API_KEY", "sk-sp-test-key")
        monkeypatch.setattr(asr_mod, "_convert_to_wav", lambda data, fmt: b"wav-bytes")
        monkeypatch.setattr(asr_mod.httpx, "AsyncClient", _FakeAsyncClient)
        _reset_fake(_Resp(200, _ok_json("不该被用到")))

        class _Sentence:
            def get_sentence(self):
                return {"sentence_id": 0, "text": "实时通道"}

        built = []

        class _FakeRecognition:
            def __init__(self, **kwargs):
                self._callback = kwargs["callback"]
                self.frames = []
                self.stopped = False
                built.append(self)

            def start(self):
                self._callback.on_event(_Sentence())

            def send_audio_frame(self, data):
                self.frames.append(data)

            def stop(self):
                self.stopped = True

        monkeypatch.setattr(asr_mod, "Recognition", _FakeRecognition)
        text = await _transcribe()
        assert text == "实时通道"
        # 送帧/收尾确实发生（否则「识别成功」可能只是一次空跑）
        assert built[0].frames == [b"wav-bytes"]
        assert built[0].stopped
        assert _FakeAsyncClient.calls == [], "realtime 模式不得打 HTTP 通道"
