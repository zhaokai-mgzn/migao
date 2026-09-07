// case_ids: UI-025
import { describe, it, expect } from 'vitest'
import {
  shouldTranscribeVoice,
  toFriendlyTranscribeError,
  MIN_RECORDING_MS,
  MIN_AUDIO_BLOB_SIZE,
} from '@/lib/voice-guard'

describe('voice-guard 语音防护（#2984）', () => {
  it('正常录音（时长足够 + 文件足够大）→ 值得转写', () => {
    expect(shouldTranscribeVoice(Math.max(MIN_RECORDING_MS, 1500), 20_000)).toBe(true)
  })

  it('时长过短（<0.8s）→ 拦截，不调转写', () => {
    expect(shouldTranscribeVoice(MIN_RECORDING_MS - 1, 50_000)).toBe(false)
  })

  it('落盘文件过小（<4KB）→ 拦截，不调转写', () => {
    expect(shouldTranscribeVoice(5000, MIN_AUDIO_BLOB_SIZE - 1)).toBe(false)
  })

  it('边界值（恰好 0.8s 且 4KB）→ 可转写', () => {
    expect(shouldTranscribeVoice(MIN_RECORDING_MS, MIN_AUDIO_BLOB_SIZE)).toBe(true)
  })

  it('网络层失败（Failed to fetch）→ 网络异常提示，不是生硬报错', () => {
    expect(toFriendlyTranscribeError(new TypeError('Failed to fetch'))).toBe(
      '网络异常，语音识别未完成，请检查网络后重试'
    )
  })

  it('后端裸 500 → 服务暂时不可用提示', () => {
    expect(toFriendlyTranscribeError(new Error('Internal Server Error'))).toBe(
      '语音识别服务暂时不可用，请稍后重试'
    )
  })

  it('后端已友好化的 detail 原样透传', () => {
    expect(toFriendlyTranscribeError(new Error('未识别到语音内容，请靠近麦克风重新录音'))).toBe(
      '未识别到语音内容，请靠近麦克风重新录音'
    )
  })

  it('无 message 的异常 → 通用失败提示', () => {
    expect(toFriendlyTranscribeError(new Error())).toBe('语音识别失败，请稍后重试')
    expect(toFriendlyTranscribeError(null)).toBe('语音识别失败，请稍后重试')
  })
})