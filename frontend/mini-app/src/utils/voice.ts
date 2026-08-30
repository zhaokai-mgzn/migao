/**
 * 语音输入工具
 *
 * 链路：RecorderManager 录音（mp3）→ 上传后端 /api/chat/transcribe → 返回文本
 * 后端：ai-agent-service ASR 模块（DashScope paraformer），免前端插件配置
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

/**
 * 录音并转文字
 * @returns 转写文本；失败返回 null（调用方自行 toast）
 */
export async function recordAndTranscribe(): Promise<VoiceResult | null> {
  const recorderManager = Taro.getRecorderManager()

  // 1. 录音
  const tempFilePath = await new Promise<string>((resolve, reject) => {
    let stopped = false
    recorderManager.onStart(() => {})
    recorderManager.onError((err) => {
      if (!stopped) {
        stopped = true
        reject(new Error(err.errMsg || '录音失败'))
      }
    })
    recorderManager.onStop((res) => {
      if (!stopped) {
        stopped = true
        if (res.tempFilePath) {
          resolve(res.tempFilePath)
        } else {
          reject(new Error('录音结果为空'))
        }
      }
    })
    recorderManager.start({
      duration: 30000, // 最长 30s
      sampleRate: 16000,
      numberOfChannels: 1,
      encodeBitRate: 48000,
      format: 'mp3',
    })
  })

  // 2. 上传转写
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
