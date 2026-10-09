/**
 * 语音输入工具（按住说话模式）
 *
 * 链路：录音 → 上传后端 /api/chat/transcribe → 返回文本
 * 后端：ai-agent-service ASR 模块（DashScope paraformer），免前端插件配置
 *
 * ## 录音实现按平台分流（issue #6596）
 *
 * - **weapp**：`Taro.getRecorderManager()`，`format: 'mp3'`，交回 `tempFilePath`
 * - **h5**：浏览器 `getUserMedia` + `MediaRecorder`（`./voiceBrowserRecorder`），交回 **blob URL**
 *   —— 旧实现里 h5 直接 `return null`（Taro 的 h5 实现是 stub），#6476 据此判定「H5 不许写按住说话」；
 *   用户 2026-10-09 要「默认按住说话」⇒ 把 H5 录音**做出来**（后端已支持 webm/mp4，不改后端）。
 *   只有浏览器**确实没有**这两个 API 时 `isVoiceSupported()` 才为假（⇒ 输入条回落文字模式）。
 *
 * 交互契约（供 MessageInput 使用）：
 *   - isVoiceSupported()       当前环境是否支持录音（小程序 ✅ / 具备 MediaRecorder 的浏览器 ✅）
 *   - startRecording()          touchStart 时调用：开始录音（最长 60s）
 *   - stopRecording()           touchEnd 时调用：停止录音，resolve 音频临时路径 / blob URL
 *   - transcribeFile(path)      上传转写，返回 { text, durationMs } 或 null
 *   - stopAndTranscribe()       停止 + 转写一步到位（松开直接发送用）
 *
 * 注意：RecorderManager 仅微信小程序可用；**禁止在模块顶层调用**（否则 H5 页面加载即崩溃）。
 */

import Taro from '@tarojs/taro'
import { getToken } from './auth'
import { AI_API_BASE_URL } from './constants'
import { isH5 } from './platform'
import { startBrowserRecording, supportsBrowserRecording, type BrowserRecording } from './voiceBrowserRecorder'

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

// ── 录音器懒加载单例（顶层禁止调用）──

let recorderManager: any = null
let listenersReady = false
let pendingResolve: ((path: string) => void) | null = null
let pendingReject: ((e: Error) => void) | null = null
let recording = false
/** h5 当前这次浏览器录音会话（null = 没在录） */
let browserRecording: BrowserRecording | null = null

/** weapp 的录音器；h5 不走它（Taro h5 的实现是 stub） */
function getRecorder(): any {
  if (recorderManager) return recorderManager
  if (isH5()) return null
  try {
    recorderManager = Taro.getRecorderManager()
  } catch {
    recorderManager = null
  }
  return recorderManager
}

/**
 * 当前环境是否支持录音（issue #6596 改判）
 *
 * - **h5**：现取浏览器能力（`MediaRecorder` + `getUserMedia`）—— 有就是有，**不写死**。
 *   微信 webview / Safari / Chrome 都具备 ⇒ B 端默认语音模式在真机上才是真的。
 * - **weapp**：`RecorderManager` 具备 `onStop` / `start`。
 * - 其余编译目标：无语音入口。
 */
export function isVoiceSupported(): boolean {
  if (isH5()) return supportsBrowserRecording()
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
  recording = true

  if (isH5()) {
    // 浏览器：getUserMedia 是异步的（可能弹授权）⇒ 会话对象先拿住，授权完成由它的 ready 承载
    browserRecording = startBrowserRecording()
    if (!browserRecording) recording = false
    return
  }

  ensureListeners()
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

/** 停止录音，resolve 音频临时路径 / blob URL（touchEnd）。 */
export function stopRecording(): Promise<string> {
  if (isH5()) {
    const session = browserRecording
    browserRecording = null
    recording = false
    if (!session) return Promise.reject(new Error('当前环境不支持录音'))
    return session.stop()
  }

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

/** `blob:` URL ⇒ 反查回 Blob（h5 录音的载体就是它） */
async function resolveAudioBlob(path: string): Promise<Blob> {
  const resp = await fetch(path)
  return await resp.blob()
}

/** h5：blob → 后端认得的**扩展名**（`_get_audio_format` 按 media type / 文件名判族：webm 与 mp4） */
function audioFileName(blob: Blob): string {
  const type = String(blob.type || '').toLowerCase()
  return type.includes('mp4') ? 'voice.m4a' : 'voice.webm'
}

/**
 * 上传音频并转写。失败返回 null（调用方自行 toast）。
 *
 * 两种载体都走**同一个上传点**（避免第二份鉴权/字段口径）：
 * weapp = `Taro.uploadFile`；h5 = `blob:` URL → `fetch` + `FormData`（浏览器原生 multipart）。
 */
export async function transcribeFile(tempFilePath: string): Promise<VoiceResult | null> {
  const token = getToken()
  const authHeader = token ? `Bearer ${token}` : ''
  const url = `${AI_API_BASE_URL}/api/chat/transcribe`

  let statusCode: number
  let raw: string

  if (isH5()) {
    const blob = await resolveAudioBlob(tempFilePath)
    const form = new FormData()
    form.append('audio', blob, audioFileName(blob))
    form.append('language', 'zh')
    const resp = await fetch(url, {
      method: 'POST',
      // ⚠️ 不要手写 Content-Type：boundary 由浏览器生成
      headers: {
        Authorization: authHeader,
        'X-Client-Type': 'bmini_h5',
      },
      body: form,
    })
    statusCode = resp.status
    raw = await resp.text()
  } else {
    const resp = await Taro.uploadFile({
      url,
      filePath: tempFilePath,
      name: 'audio',
      header: {
        Authorization: authHeader,
        'X-Client-Type': 'wechat_mini',
      },
      formData: {
        language: 'zh',
        // 租户来自 JWT，上传时不带 tenant_id（后端 transcribe 签名只有 audio + language）
      },
    })
    statusCode = resp.statusCode
    raw = resp.data
  }

  let parsed: TranscribeResponse
  try {
    parsed = JSON.parse(raw) as TranscribeResponse
  } catch {
    return null
  }

  if (statusCode !== 200 || !parsed.text) {
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
