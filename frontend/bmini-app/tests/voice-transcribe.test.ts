// case_ids: BM-044
/**
 * 转写**上传腿**判据（issue #7310，2026-10-19 生产实证）
 *
 * ## 病（服务端日志读数，不是推断）
 *
 * 2026-10-19 10:57–10:58 华为 ALN-AL00（ArkWeb / 支付宝 webview）7 次「按住说话」全部失败：
 * nginx 记 7 条 `POST /api/chat/transcribe → 400`、响应体**恰好 52 字节**
 * = `{"detail":"音频文件为空，未检测到声音"}`（`backend/ai-agent-service/app/api/asr.py` 的
 * `len(audio_data) == 0` 分支；1~1023 字节会得 85），ai-agent 侧 `duration=2.3~4.4ms`
 * 且**无任何 ASR/ffmpeg 报错** ⇒ 0 字节音频连 DashScope 都没走到。
 *
 * 两个客户端病灶（本文件判后一个，前一个在 `voice-browser-recorder.test.ts`）：
 *   ① 录音器把「有 chunk 但 0 字节」当正常录音交回；
 *   ② `transcribeFile()` 把**所有**非 200 / 空 text 一律降级成 `null`，**丢弃服务端 detail**
 *      ⇒「音频为空 / 太短 / 没人声」三种原因在 UI 上都是同一句「未听清，请重试」。
 *
 * ## 判据
 *
 * | # | 断言 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | 0 字节音频 **不发上传请求**（只取 blob 那一次 fetch） | 空音频重新出网 ⇒ 红 |
 * | 2 | 服务端 400 的**中文 detail 透传**（调用方可 toast 真实原因） | 又被吞成 `null`（用户只看到「未听清」）⇒ 红 |
 * | 3 | 400 但无 detail ⇒ 返回 `null`（旧文案「未听清，请重试」保留） | 抛空消息 / 崩 ⇒ 红 |
 * | 4 | 鉴权类（401 英文 detail）**不透传** ⇒ `null`（不把 `Not authenticated` 甩给商家） | 原样透传 ⇒ 红 |
 * | 5 | 200 + text ⇒ 交回文本与时长 | 文本丢了 ⇒ 红 |
 *
 * ## 边界（照实登记）
 *
 * - 本文件只判 **h5 上传腿**（`fetch` + `FormData`）；weapp 的 `Taro.uploadFile` 分支不在射程。
 * - **华为 ArkWeb 上「为什么」录不到字节**（权限静默 / 录音器产不出数据 / 按得太短）本单不能定论
 *   —— 需真机重试一次看透传后的真实文案（PR body 的未覆盖登记）。
 */
jest.mock('../src/utils/auth', () => ({ getToken: () => 'test-token' }))

import { transcribeFile } from '../src/utils/voice'

const originalFetch = global.fetch

/** 桩：取 blob 那一次 fetch + 上传那一次 fetch（按 URL 分流） */
function stubUpload(status: number, body: string) {
  const calls: string[] = []
  const mock = jest.fn(async (input: any) => {
    const url = String(input)
    calls.push(url)
    if (url.startsWith('blob:')) {
      return { blob: async () => new Blob(['voice-bytes'], { type: 'audio/webm' }) }
    }
    return { status, text: async () => body }
  })
  global.fetch = mock as any
  return { mock, calls }
}

beforeEach(() => {
  // 本文件判 h5 分支（`getRecorder()` 在 h5 直接 return null ⇒ 走 fetch + FormData）
  process.env.TARO_ENV = 'h5'
})

afterEach(() => {
  global.fetch = originalFetch
  ;(process.env as Record<string, string | undefined>).TARO_ENV = undefined
})

describe('B 端 H5 转写上传腿（issue #7310）', () => {
  it('🔴 0 字节音频不发上传请求', async () => {
    const calls: string[] = []
    const mock = jest.fn(async (input: any) => {
      calls.push(String(input))
      return { blob: async () => new Blob([], { type: 'audio/webm' }) }
    })
    global.fetch = mock as any

    await expect(transcribeFile('blob:hollow')).rejects.toThrow(/未检测到声音/)
    expect(calls).toHaveLength(1) // 只取了 blob；**没有** POST
  })

  it('服务端 400 的中文 detail 透传（不再一律吞成「未听清」）', async () => {
    stubUpload(400, JSON.stringify({ detail: '未识别到语音内容，请靠近麦克风重新录音' }))
    await expect(transcribeFile('blob:rec')).rejects.toThrow(
      '未识别到语音内容，请靠近麦克风重新录音',
    )
  })

  it('服务端 400 无 detail ⇒ 返回 null（保留「未听清，请重试」旧文案）', async () => {
    stubUpload(400, '{}')
    await expect(transcribeFile('blob:rec')).resolves.toBeNull()
  })

  it('鉴权类 detail（401 英文）不透传 ⇒ null', async () => {
    stubUpload(401, JSON.stringify({ detail: 'Not authenticated' }))
    await expect(transcribeFile('blob:rec')).resolves.toBeNull()
  })

  it('200 + text ⇒ 交回文本与时长', async () => {
    stubUpload(200, JSON.stringify({ text: '今天经营怎么样', language: 'zh', duration_ms: 1200 }))
    await expect(transcribeFile('blob:rec')).resolves.toEqual({
      text: '今天经营怎么样',
      durationMs: 1200,
    })
  })
})
