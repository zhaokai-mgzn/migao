"""
Tests for app/api/asr.py — ASR voice transcription endpoint
"""
# case_ids: API-012
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestGetAudioFormat:
    """音频格式推断"""

    def test_webm_from_content_type(self):
        from app.api.asr import _get_audio_format
        fmt, sr = _get_audio_format("recording.webm", "audio/webm")
        assert fmt == "opus"
        assert sr == 16000

    def test_webm_from_filename(self):
        from app.api.asr import _get_audio_format
        fmt, sr = _get_audio_format("recording.webm", None)
        assert fmt == "opus"
        assert sr == 16000

    def test_wav_from_content_type(self):
        from app.api.asr import _get_audio_format
        fmt, sr = _get_audio_format("audio.wav", "audio/wav")
        assert fmt == "wav"
        assert sr == 16000

    def test_wav_from_filename(self):
        from app.api.asr import _get_audio_format
        fmt, sr = _get_audio_format("audio.wav", None)
        assert fmt == "wav"
        assert sr == 16000

    def test_mp3_from_content_type(self):
        from app.api.asr import _get_audio_format
        fmt, sr = _get_audio_format("audio.mp3", "audio/mpeg")
        assert fmt == "mp3"
        assert sr == 16000

    def test_mp3_from_filename(self):
        from app.api.asr import _get_audio_format
        fmt, sr = _get_audio_format("audio.mp3", None)
        assert fmt == "mp3"
        assert sr == 16000

    def test_default_wav(self):
        from app.api.asr import _get_audio_format
        fmt, sr = _get_audio_format("", None)
        assert fmt == "wav"
        assert sr == 16000


class TestCollectorCallback:
    """回调收集器"""

    def test_full_text_empty_initially(self):
        from app.api.asr import _CollectorCallback
        cb = _CollectorCallback()
        assert cb.full_text == ""

    def test_full_text_returns_last_sentence(self):
        from app.api.asr import _CollectorCallback
        cb = _CollectorCallback()
        cb.sentences.append("你好")
        cb.sentences.append("帮我查订单")
        assert cb.full_text == "帮我查订单"

    def test_on_event_skips_empty(self):
        from app.api.asr import _CollectorCallback
        cb = _CollectorCallback()
        mock_result = MagicMock()
        mock_result.get_sentence.return_value = None
        cb.on_event(mock_result)
        assert cb.full_text == ""

    def test_on_event_skips_whitespace(self):
        from app.api.asr import _CollectorCallback
        cb = _CollectorCallback()
        mock_result = MagicMock()
        mock_result.get_sentence.return_value = {"text": "   "}
        cb.on_event(mock_result)
        assert cb.full_text == ""


class TestTranscribeResponse:
    """响应模型"""

    def test_defaults(self):
        from app.api.asr import TranscribeResponse
        r = TranscribeResponse(text="测试")
        assert r.text == "测试"
        assert r.language == "zh"
        assert r.duration_ms == 0

    def test_full_fields(self):
        from app.api.asr import TranscribeResponse
        r = TranscribeResponse(text="hello", language="en", duration_ms=3000)
        assert r.text == "hello"
        assert r.language == "en"
        assert r.duration_ms == 3000


class TestSupportedMimeTypes:
    """支持的格式常量"""

    def test_webm_supported(self):
        from app.api.asr import SUPPORTED_MIME_TYPES
        assert "audio/webm" in SUPPORTED_MIME_TYPES

    def test_wav_supported(self):
        from app.api.asr import SUPPORTED_MIME_TYPES
        assert "audio/wav" in SUPPORTED_MIME_TYPES

    def test_mp3_supported(self):
        from app.api.asr import SUPPORTED_MIME_TYPES
        assert "audio/mpeg" in SUPPORTED_MIME_TYPES


def _mock_file(data: bytes, filename: str = "recording.webm", content_type: str = "audio/webm"):
    """构造 mock UploadFile：read() 返回 data，格式信息齐全"""
    f = MagicMock()
    f.read = AsyncMock(return_value=data)
    f.filename = filename
    f.content_type = content_type
    return f


class TestTranscribeAudioFriendlyErrors:
    """#2984 语音容错：空/极小/静音音频返回友好 4xx/5xx，不裸 500
    （生产实证：无声音停止 → 空/极小 webm → 后端裸 500 → 前端 Failed to fetch）"""

    @patch("app.api.asr._transcribe_audio", new_callable=AsyncMock)
    async def test_empty_audio_returns_400(self, mock_transcribe):
        from app.api.asr import transcribe_audio
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await transcribe_audio(
                audio=_mock_file(b""),
                current_user=MagicMock(tenant_id=1),
            )
        assert exc.value.status_code == 400
        assert "音频文件为空" in exc.value.detail
        mock_transcribe.assert_not_called()

    @patch("app.api.asr._transcribe_audio", new_callable=AsyncMock)
    async def test_tiny_audio_returns_400(self, mock_transcribe):
        from app.api.asr import transcribe_audio
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await transcribe_audio(
                audio=_mock_file(b"\x00" * 120),
                current_user=MagicMock(tenant_id=1),
            )
        assert exc.value.status_code == 400
        assert "有效音频" in exc.value.detail
        mock_transcribe.assert_not_called()

    @patch("app.api.asr._transcribe_audio", new_callable=AsyncMock)
    async def test_oversize_audio_returns_400(self, mock_transcribe):
        from app.api.asr import transcribe_audio
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await transcribe_audio(
                audio=_mock_file(b"\x00" * (11 * 1024 * 1024)),
                current_user=MagicMock(tenant_id=1),
            )
        assert exc.value.status_code == 400
        assert "过大" in exc.value.detail
        mock_transcribe.assert_not_called()

    @patch("app.api.asr._convert_to_wav", return_value=b"fake-wav-16000hz" * 2000)
    @patch("app.api.asr._transcribe_audio", new_callable=AsyncMock)
    async def test_silent_audio_returns_400(self, mock_transcribe, mock_convert):
        from app.api.asr import transcribe_audio
        from fastapi import HTTPException

        mock_transcribe.side_effect = RuntimeError("未识别到语音内容，请检查音频输入")
        with pytest.raises(HTTPException) as exc:
            await transcribe_audio(
                audio=_mock_file(b"\x00" * 64 * 1024),
                current_user=MagicMock(tenant_id=1),
            )
        assert exc.value.status_code == 400
        assert "未识别到语音内容" in exc.value.detail

    @patch("app.api.asr._convert_to_wav", return_value=b"fake-wav-16000hz" * 2000)
    @patch("app.api.asr._transcribe_audio", new_callable=AsyncMock)
    async def test_asr_service_down_returns_503(self, mock_transcribe, mock_convert):
        from app.api.asr import transcribe_audio
        from fastapi import HTTPException

        mock_transcribe.side_effect = RuntimeError("ASR 识别失败: 上游超时")
        with pytest.raises(HTTPException) as exc:
            await transcribe_audio(
                audio=_mock_file(b"\x00" * 64 * 1024),
                current_user=MagicMock(tenant_id=1),
            )
        assert exc.value.status_code == 503
        assert "暂时不可用" in exc.value.detail

    @patch("app.api.asr._convert_to_wav", return_value=b"fake-wav-16000hz" * 2000)
    @patch("app.api.asr._transcribe_audio", new_callable=AsyncMock)
    async def test_valid_audio_returns_text(self, mock_transcribe, mock_convert):
        from app.api.asr import transcribe_audio

        mock_transcribe.return_value = "帮我查一下订单"
        resp = await transcribe_audio(
            audio=_mock_file(b"\x00" * 64 * 1024),
            current_user=MagicMock(tenant_id=1),
        )
        assert resp.text == "帮我查一下订单"
        assert resp.duration_ms > 0
