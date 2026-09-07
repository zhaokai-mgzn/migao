/**
 * #2984 语音防护：录音是否值得提交转写 与 转写错误友好化。
 *
 * 背景：浏览器「没录到声音就停止」会产出空口语/极小 webm，
 * 旧实现无条件 POST /api/chat/transcribe → 后端 500 → 前端 toast 「Failed to fetch/Internal Server Error」。
 * 这里前置拦截 + 错误文案降噪，语音输入体验不再被空录音误触破坏。
 */

/** 最短有效录音时长（毫秒）：低于视为误触/空口 */
export const MIN_RECORDING_MS = 800
/** 最小有效音频大小（字节）：webm 容器最小开销约几百字节，空口语静音帧通常 <4KB */
export const MIN_AUDIO_BLOB_SIZE = 4 * 1024

/**
 * 判断本次录音是否值得提交转写。
 * 时长远短或落盘文件过小 → 没有有效声音，不调转写接口。
 */
export function shouldTranscribeVoice(recordingMs: number, blobSize: number): boolean {
  return recordingMs >= MIN_RECORDING_MS && blobSize >= MIN_AUDIO_BLOB_SIZE
}

/**
 * 把转写 fetch 的错误转换为用户可理解的 toast 文案。
 * - 网络层失败（fetch reject）→ 网络提示，避免生硬的 "Failed to fetch"
 * - 后端裸 500 → 服务降级提示；后端已友好化的 detail（400/503 中文）原样透传
 */
export function toFriendlyTranscribeError(err: unknown): string {
  const msg = err instanceof Error ? err.message : ''
  if (/failed to fetch|networkerror|load failed|network error/i.test(msg)) {
    return '网络异常，语音识别未完成，请检查网络后重试'
  }
  if (/internal server error|\b500\b/i.test(msg)) {
    return '语音识别服务暂时不可用，请稍后重试'
  }
  return msg || '语音识别失败，请稍后重试'
}