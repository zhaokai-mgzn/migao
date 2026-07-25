import { describe, it, expect, vi, beforeEach } from 'vitest'
import { chatApi } from '@/lib/api'

describe('chatApi', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  describe('transcribeAudio', () => {
    it('sends POST to /api/chat/transcribe with FormData', async () => {
      const mockResponse = {
        ok: true,
        json: () => Promise.resolve({ text: '帮我查一下最近的订单', language: 'zh', duration_ms: 2500 }),
      }
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(mockResponse as Response)

      const blob = new Blob(['fake-audio-data'], { type: 'audio/webm' })
      const result = await chatApi.transcribeAudio(blob, 'test-token')

      expect(fetch).toHaveBeenCalledTimes(1)
      const [url, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
      expect(url).toContain('/api/chat/transcribe')
      expect(options.method).toBe('POST')
      expect(options.headers).toHaveProperty('Authorization', 'Bearer test-token')
      expect(options.body).toBeInstanceOf(FormData)
      expect(result.text).toBe('帮我查一下最近的订单')
    })

    it('appends language query param when provided', async () => {
      const mockResponse = {
        ok: true,
        json: () => Promise.resolve({ text: '你好', language: 'zh', duration_ms: 1000 }),
      }
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(mockResponse as Response)

      const blob = new Blob(['audio'], { type: 'audio/webm' })
      await chatApi.transcribeAudio(blob, 'token', 'zh')

      const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
      expect(url).toContain('language=zh')
    })

    it('throws on non-ok response with detail message', async () => {
      const mockResponse = {
        ok: false,
        status: 400,
        json: () => Promise.resolve({ detail: '音频文件为空' }),
      }
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(mockResponse as Response)

      const blob = new Blob([], { type: 'audio/webm' })
      await expect(chatApi.transcribeAudio(blob, 'token')).rejects.toThrow('音频文件为空')
    })

    it('throws on non-ok response without detail (fallback to status)', async () => {
      const mockResponse = {
        ok: false,
        status: 500,
        json: () => Promise.resolve({}),
      }
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(mockResponse as Response)

      const blob = new Blob(['audio'], { type: 'audio/webm' })
      await expect(chatApi.transcribeAudio(blob, 'token')).rejects.toThrow('语音识别失败: 500')
    })

    it('returns typed result with text, language, duration_ms', async () => {
      const mockResponse = {
        ok: true,
        json: () => Promise.resolve({ text: '测试', language: 'zh', duration_ms: 1500 }),
      }
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(mockResponse as Response)

      const blob = new Blob(['data'], { type: 'audio/webm' })
      const result = await chatApi.transcribeAudio(blob, 'token')

      expect(result).toHaveProperty('text')
      expect(result).toHaveProperty('language')
      expect(result).toHaveProperty('duration_ms')
      expect(typeof result.text).toBe('string')
      expect(typeof result.duration_ms).toBe('number')
    })
  })
})
