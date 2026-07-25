"""
Tests for app/api/asr.py — ASR voice transcription endpoint
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestGetAudioFormat:
    """音频格式推断"""

    def test_webm_from_content_type(self):
        from app.api.asr import _get_audio_format
        fmt, sr = _get_audio_format("recording.webm", "audio/webm")
        assert fmt == "webm"
        assert sr == 16000

    def test_webm_from_filename(self):
        from app.api.asr import _get_audio_format
        fmt, sr = _get_audio_format("recording.webm", None)
        assert fmt == "webm"
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


class TestValidateAudioFormat:
    """音频格式校验 — 使用 SUPPORTED_MIME_TYPES"""

    def test_valid_webm_passes(self):
        from app.api.asr import _validate_audio_format
        _validate_audio_format("audio/webm")

    def test_valid_wav_passes(self):
        from app.api.asr import _validate_audio_format
        _validate_audio_format("audio/wav")

    def test_valid_mp3_content_type_passes(self):
        from app.api.asr import _validate_audio_format
        _validate_audio_format("audio/mpeg")

    def test_unsupported_format_raises(self):
        from app.api.asr import _validate_audio_format
        with pytest.raises(ValueError, match="不支持的音频格式"):
            _validate_audio_format("application/zip")

    def test_none_content_type_raises(self):
        from app.api.asr import _validate_audio_format
        with pytest.raises(ValueError, match="无法识别音频格式"):
            _validate_audio_format(None)


class TestTranscribeAudioApiKey:
    """API Key 配置：不应回退到 PRIMARY_API_KEY（DeepSeek）"""

    def test_raises_when_asr_api_key_not_set(self):
        from app.api.asr import _transcribe_audio
        with patch("app.api.asr.settings") as mock_settings:
            mock_settings.ASR_API_KEY = ""
            mock_settings.ASR_MODEL = "paraformer-realtime-8k-v2"
            mock_settings.ASR_LANGUAGE_HINTS = "zh"
            with pytest.raises(ValueError, match="ASR_API_KEY 未配置"):
                import asyncio
                asyncio.run(_transcribe_audio(b"fake", "wav"))


class TestDurationCalculation:
    """响应中 duration_ms：WebM/MP3 不应使用 WAV 公式"""

    def test_wav_duration(self):
        from app.api.asr import _estimate_duration_ms
        # WAV: 16000 samples/s * 2 bytes * 1s = 32000 bytes
        duration = _estimate_duration_ms(32000, "wav")
        assert duration == 1000  # 1 second

    def test_webm_duration(self):
        from app.api.asr import _estimate_duration_ms
        # WebM ~128kbps: 128*1024/8 = 16384 bytes/s
        duration = _estimate_duration_ms(16384, "webm")
        assert duration == 1000  # 1 second

    def test_mp3_duration(self):
        from app.api.asr import _estimate_duration_ms
        duration = _estimate_duration_ms(16384, "mp3")
        assert duration == 1000  # 1 second
