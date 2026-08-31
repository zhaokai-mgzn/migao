/**
 * 语音输入工具（按住说话模式）
 *
 * 链路：RecorderManager 录音（mp3）→ 上传后端 /api/chat/transcribe → 返回文本
 * 后端：ai-agent-service ASR 模块（DashScope paraformer），免前端插件配置
 *
 * 交互契约（供 MessageInput 使用）：
 *   - startRecording()          touchStart 时调用：开始录音（最长 60s）
 *   - stopRecording()           touchEnd 时调用：停止录音，resolve 音频临时路径
 *   - transcribeFile(path)      上传转写，返回 { text, durationMs } 或 null
 *   - stopAndTranscribe()       停止 + 转写一步到位（松开直接发送用）
 */

import Taro from '@tarojs/taro'
import { getToken } from './auth'
import { AI_API_BASE_URL, STORAGE_KEYS } from './constants'

export interface VoiceResult {
  text: string
  durationMs?: number
}

interface TranscribeResponse {
  success?: boolean
  text?: string
  duration_ms?: number
  error?: { message?: string }
}

// ── 录音器单例：onStop/onError 只注册一次，避免重复累加监听 ──

const recorderManager = Taro.getRecorderManager()
let pendingResolve: ((path: string) => void) | null = null
let pendingReject: ((e: Error) => void) | null = null
let recording = false

recorderManager.onStop((res) => {
  recording = false
  const resolve = pendingResolve
  const reject = pendingReject
  pendingResolve = null
  pendingReject = null
  if (res.tempFilePath) {
    resolve?.(res.tempFilePath)
  } else {
    reject?.(new Error('录音结果为空'))
  }
})

recorderManager.onError((err) => {
  recording = false
  const reject = pendingReject
  pendingResolve = null
  pendingReject = null
  reject?.(new Error(err.errMsg || '录音失败'))
})

/** 是否正在录音（供 UI 展示状态） */
export function isRecordingNow(): boolean {
  return recording
}

/** 开始录音（touchStart）。重复调用前先 stop。 */
export function startRecording(): void {
  if (recording) return
  recording = true
  pendingResolve = null
  pendingReject = null
  recorderManager.start({
    duration: 60000, // 最长 60s（后端 MAX_AUDIO_DURATION_S 同为 60s）
    sampleRate: 16000,
    numberOfChannels: 1,
    encodeBitRate: 48000,
    format: 'mp3',
  })
}

/** 停止录音，resolve 音频临时路径（touchEnd）。 */
export function stopRecording(): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    pendingResolve = resolve
    pendingReject = reject
    recorderManager.stop()
  })
}

/** 上传音频并转写。失败返回 null（调用方自行 toast）。 */
export async function transcribeFile(tempFilePath: string): Promise<VoiceResult | null> {
  const token = getToken()
  const tenantId = Taro.getStorageSync(STORAGE_KEYS.TENANT_ID) || 1

  const resp = await Taro.uploadFile({
    url: `${AI_API_BASE_URL}/api/chat/transcribe`,
    filePath: tempFilePath,
    name: 'audio',
    header: {
      Authorization: token ? `Bearer ${token}` : '',
      'X-Client-Type': 'wechat_mini',
    },
    formData: {
      language: 'zh',
      tenant_id: String(tenantId),
    },
  })

  let parsed: TranscribeResponse
  try {
    parsed = JSON.parse(resp.data) as TranscribeResponse
  } catch {
    return null
  }

  if (resp.statusCode !== 200 || !parsed.text) {
    return null
  }

  return {
    text: parsed.text,
    durationMs: parsed.duration_ms,
  }
}

/** 停止录音并转写（松开发送一步到位）。 */
export async function stopAndTranscribe(): Promise<VoiceResult | null> {
  const tempFilePath = await stopRecording()
  return transcribeFile(tempFilePath)
}
