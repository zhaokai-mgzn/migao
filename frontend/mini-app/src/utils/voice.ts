/**
 * 语音输入工具（按住说话模式）
 *
 * 链路：RecorderManager 录音（mp3）→ 上传后端 /api/chat/transcribe → 返回文本
 * 后端：ai-agent-service ASR 模块（DashScope paraformer），免前端插件配置
 *
 * 交互契约（供 MessageInput 使用）：
 *   - isVoiceSupported()       当前环境是否支持录音（小程序 ✅ / H5 stub ❌）
 *   - startRecording()          touchStart 时调用：开始录音（最长 60s）
 *   - stopRecording()           touchEnd 时调用：停止录音，resolve 音频临时路径
 *   - transcribeFile(path)      上传转写，返回 { text, durationMs } 或 null
 *   - stopAndTranscribe(ms)     停止 + 守卫（<0.8s/<4KB）+ 转写一步到位（松开直接发送用）
 *   - shouldTranscribeVoice()   录音守卫纯函数（对齐 B 端 admin-web voice-guard #2984）
 *
 * 注意：RecorderManager 仅微信小程序可用；H5 下 getRecorderManager 返回 stub，
 * 必须懒加载 + 能力检测，禁止在模块顶层调用（否则 H5 页面加载即崩溃）。
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

// ── 录音器懒加载单例（H5 环境不可用，顶层禁止调用）──

let recorderManager: any = null
let listenersReady = false
let pendingResolve: ((path: string) => void) | null = null
let pendingReject: ((e: Error) => void) | null = null
let recording = false

function getRecorder(): any {
  if (recorderManager) return recorderManager
  try {
    recorderManager = Taro.getRecorderManager()
  } catch {
    recorderManager = null
  }
  return recorderManager
}

/** 当前环境是否支持录音（微信小程序 ✅；H5 的 stub 无 onStop/start → ❌） */
export function isVoiceSupported(): boolean {
  const rm = getRecorder()
  return !!rm && typeof rm.onStop === 'function' && typeof rm.start === 'function'
}

/** 注册 onStop/onError 监听（只注册一次） */
function ensureListeners(): void {
  if (listenersReady) return
  listenersReady = true
  const rm = getRecorder()
  if (!rm) return
  rm.onStop((res: any) => {
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
  rm.onError((err: any) => {
    recording = false
    const reject = pendingReject
    pendingResolve = null
    pendingReject = null
    reject?.(new Error(err.errMsg || '录音失败'))
  })
}

/** 是否正在录音（供 UI 展示状态） */
export function isRecordingNow(): boolean {
  return recording
}

/** 开始录音（touchStart）。重复调用前先 stop。 */
export function startRecording(): void {
  if (!isVoiceSupported() || recording) return
  ensureListeners()
  recording = true
  pendingResolve = null
  pendingReject = null
  getRecorder().start({
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
    if (!isVoiceSupported()) {
      reject(new Error('当前环境不支持录音'))
      return
    }
    pendingResolve = resolve
    pendingReject = reject
    getRecorder().stop()
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

// ── 语音守卫（对齐 B 端 admin-web voice-guard，issue #2984）──

/** 最短有效录音时长（毫秒）：低于视为误触/空口 */
export const MIN_RECORDING_MS = 800
/** 最小有效音频大小（字节）：mp3 静音帧通常 <4KB（后端对 <1KB 文件直接 400 拦截） */
export const MIN_AUDIO_SIZE = 4 * 1024

/** 判断本次录音是否值得提交转写（时长过短或文件过小 → 无有效声音，不调转写接口） */
export function shouldTranscribeVoice(recordingMs: number, fileSize: number): boolean {
  return recordingMs >= MIN_RECORDING_MS && fileSize >= MIN_AUDIO_SIZE
}

/** 获取本地临时音频文件大小（字节）。拿不到时保守返回 0 → 守卫拦截（fail-closed，对齐后端 <1KB 拦截语义） */
export function getAudioFileSize(filePath: string): Promise<number> {
  return new Promise<number>(resolve => {
    try {
      Taro.getFileSystemManager().getFileInfo({
        filePath,
        success: r => resolve(r.size),
        fail: () => resolve(0),
      })
    } catch {
      resolve(0)
    }
  })
}

/** stopAndTranscribe 三态结果：blocked=守卫拦截（<0.8s 或 <4KB）/ ok=转写成功 / failed=转写失败（含后端 400/空文本） */
export type StopTranscribeResult =
  | { status: 'blocked' }
  | { status: 'ok'; text: string; durationMs?: number }
  | { status: 'failed' }

/** 停止录音并转写（松开发送一步到位）。先过语音守卫：<0.8s 或 <4KB 不调转写接口，返回 blocked。 */
export async function stopAndTranscribe(recordingMs: number): Promise<StopTranscribeResult> {
  const tempFilePath = await stopRecording()
  const fileSize = await getAudioFileSize(tempFilePath)
  if (!shouldTranscribeVoice(recordingMs, fileSize)) {
    return { status: 'blocked' }
  }
  const result = await transcribeFile(tempFilePath)
  if (!result || !result.text) return { status: 'failed' }
  return { status: 'ok', text: result.text, durationMs: result.durationMs }
}
