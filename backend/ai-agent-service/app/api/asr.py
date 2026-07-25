"""
语音识别（ASR）API — 基于 DashScope paraformer-realtime-8k-v2

POST /api/chat/transcribe
  接收音频文件，返回转写文本。

免费额度: 36,000 秒（paraformer-realtime-8k-v2），用完即停。
"""

from __future__ import annotations

import logging
from typing import Optional

from dashscope.audio.asr.recognition import Recognition, RecognitionCallback
from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field

from app.utils.auth import get_current_user, UserIdentity
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ASR"])

# 支持的音频格式
SUPPORTED_MIME_TYPES = {
    "audio/wav", "audio/wave", "audio/x-wav",
    "audio/webm",
    "audio/mp4", "audio/mpeg",
    "audio/ogg", "audio/opus",
}

MAX_AUDIO_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_AUDIO_DURATION_S = 60          # 最长 60 秒


class TranscribeResponse(BaseModel):
    """语音转文字响应"""
    text: str = Field(description="转写文本")
    language: str = Field(default="zh", description="识别语言")
    duration_ms: float = Field(default=0, description="音频时长（毫秒）")


class _CollectorCallback(RecognitionCallback):
    """收集 ASR 识别结果"""

    def __init__(self):
        self.sentences: list[str] = []

    def on_event(self, result) -> None:
        sentence = result.get_sentence()
        if sentence and sentence.get("text"):
            text = sentence["text"].strip()
            if text:
                self.sentences.append(text)

    @property
    def full_text(self) -> str:
        """已稳定的完整文本（取最后一个句子作为最终结果）"""
        if not self.sentences:
            return ""
        return self.sentences[-1]


async def _transcribe_audio(
    audio_data: bytes,
    format: str,
    sample_rate: int = 16000,
    language_hints: Optional[list[str]] = None,
) -> str:
    """调用 DashScope ASR 转写音频

    Args:
        audio_data: 原始音频字节
        format: 音频格式 (wav, pcm, mp3 等)
        sample_rate: 采样率
        language_hints: 语言提示列表，如 ["zh"], ["yue"]

    Returns:
        转写文本
    """
    if language_hints is None:
        language_hints = [settings.ASR_LANGUAGE_HINTS]

    api_key = settings.ASR_API_KEY or settings.PRIMARY_API_KEY
    if not api_key:
        raise ValueError("ASR_API_KEY 未配置")

    callback = _CollectorCallback()

    recognition = Recognition(
        model=settings.ASR_MODEL,
        format=format,
        sample_rate=sample_rate,
        language_hints=language_hints,
        callback=callback,
        api_key=api_key,
    )

    try:
        recognition.start()
        recognition.send_audio_frame(audio_data)
        recognition.stop()
    except Exception as e:
        logger.error(f"ASR 识别失败: {e}", exc_info=True)
        raise RuntimeError("语音识别服务暂时不可用，请稍后重试") from e

    text = callback.full_text
    if not text:
        raise RuntimeError("未识别到语音内容，请检查音频输入")

    return text


def _get_audio_format(filename: str, content_type: Optional[str]) -> tuple[str, int]:
    """从文件名和 Content-Type 推断音频格式和采样率"""
    # WebM 格式（浏览器 MediaRecorder 默认）
    if content_type and "webm" in content_type:
        return "webm", 16000
    if filename and filename.lower().endswith(".webm"):
        return "webm", 16000

    # WAV 格式
    if content_type and "wav" in content_type:
        return "wav", 16000
    if filename and filename.lower().endswith(".wav"):
        return "wav", 16000

    # MP3 格式
    if content_type and "mpeg" in content_type:
        return "mp3", 16000
    if filename and filename.lower().endswith((".mp3", ".mpeg")):
        return "mp3", 16000

    # 默认 WAV
    return "wav", 16000


@router.post("/chat/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(
    audio: UploadFile = File(..., description="音频文件（WAV/WebM/MP3）"),
    language: Optional[str] = None,
    current_user: UserIdentity = Depends(get_current_user),
) -> TranscribeResponse:
    """语音转文字

    接收音频文件，调用 DashScope ASR 进行语音识别，返回转写文本。

    - **audio**: 音频文件，支持 WAV/WebM/MP3，最大 10MB，最长 60 秒
    - **language**: 语言提示，如 zh（中文）、yue（粤语）、wuu（吴语），默认 zh
    """
    # 校验文件大小
    audio_data = await audio.read()
    if len(audio_data) > MAX_AUDIO_SIZE:
        raise ValueError(f"音频文件过大，最大 {MAX_AUDIO_SIZE // 1024 // 1024}MB")

    if len(audio_data) == 0:
        raise ValueError("音频文件为空")

    # 推断格式
    audio_format, sample_rate = _get_audio_format(
        audio.filename or "", audio.content_type
    )

    # 校验音频时长：根据格式估算，防止绕过前端 60s 限制
    if audio_format == "wav":
        # WAV PCM: 字节 / (采样率 * 2字节/sample * 1声道)
        estimated_s = len(audio_data) / (sample_rate * 2)
    else:
        # WebM/MP3 有损压缩，按较高码率 128kbps 估算
        estimated_s = len(audio_data) / (128 * 1024 / 8)
    if estimated_s > MAX_AUDIO_DURATION_S + 5:  # 5s 容差
        raise ValueError(
            f"音频时长约 {int(estimated_s)}s，超过上限 {MAX_AUDIO_DURATION_S}s"
        )

    # 语言提示
    language_hints = [language] if language else [settings.ASR_LANGUAGE_HINTS]

    logger.info(
        f"ASR transcribe: tenant={current_user.tenant_id}, "
        f"format={audio_format}, size={len(audio_data)} bytes, "
        f"language={language_hints[0]}"
    )

    # 调用 ASR
    try:
        text = await _transcribe_audio(
            audio_data,
            format=audio_format,
            sample_rate=sample_rate,
            language_hints=language_hints,
        )
    except RuntimeError as e:
        logger.error(f"ASR failed for tenant {current_user.tenant_id}: {e}")
        raise

    # 估算音频时长（WAV: 字节 / (采样率 * 2字节/采样 * 1声道)）
    duration_ms = len(audio_data) / (sample_rate * 2) * 1000

    return TranscribeResponse(
        text=text,
        language=language_hints[0],
        duration_ms=round(duration_ms),
    )
