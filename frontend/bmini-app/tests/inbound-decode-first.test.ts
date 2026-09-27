// case_ids: BM-013
/**
 * **解码优先（0 次 LLM 调用）**判据（issue #5052 P3；设计 §6.1，验收判据 1）
 *
 * 成本守卫必须有**可数的证据**，不能只是「代码里先调了 decode」这种印象式断言。
 * 本文件用一个**假服务端**复刻服务端语义（`WorkerInboundService.recognize`：`barcode` 非空 ⇒
 * `PATH_BARCODE`，**一次 LLM 都不调**；否则走 vision），然后断言**调用次数**：
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | C1 | 照片含可解条码 ⇒ `llmCalls === 0`、上传 **1** 张、`barcode` 非空 | 把识别排到解码前面 ⇒ 红 |
 * | C2 | 解码失败 ⇒ 全量上传 + 不带 barcode（服务端 vision 兜底，1 次 LLM） | 不传 barcode 却仍走"解码优先"分支 ⇒ 红 |
 * | C3 | **解码库真能解出码**（真跑 encode → decode 往返，不是替身对替身） | 关掉 jsQR 调用 ⇒ 红 |
 * | C4 | 解码/降级过程**有话要说**（不静默） | 丢掉 notices ⇒ 红 |
 */
import qrcode from 'qrcode-generator'
import { decodeQrFromImageData } from '../src/utils/inbound/barcodeDecode'
import { runInboundRecognize, MAX_INBOUND_PHOTOS } from '../src/utils/inbound/recognizeFlow'
import type { RasterImageLike } from '../src/utils/inbound/labelCanvas'

/** 把一段文本画成黑白位图（真二维码，供 jsQR 真解——不是替身对替身） */
function qrImage(text: string, cell = 4, quiet = 4): RasterImageLike {
  const qr = qrcode(0, 'M')
  qr.addData(text)
  qr.make()
  const modules = qr.getModuleCount()
  const size = (modules + quiet * 2) * cell
  const data = new Uint8ClampedArray(size * size * 4).fill(255)
  for (let row = 0; row < modules; row += 1) {
    for (let col = 0; col < modules; col += 1) {
      if (!qr.isDark(row, col)) continue
      for (let dy = 0; dy < cell; dy += 1) {
        for (let dx = 0; dx < cell; dx += 1) {
          const y = (row + quiet) * cell + dy
          const x = (col + quiet) * cell + dx
          const offset = (y * size + x) * 4
          data[offset] = 0
          data[offset + 1] = 0
          data[offset + 2] = 0
          data[offset + 3] = 255
        }
      }
    }
  }
  return { data, width: size, height: size }
}

/** 假服务端：复刻 `WorkerInboundService.recognize` 的 llm 计数语义 */
function fakeServer() {
  const state = { uploads: 0, llmCalls: 0, recognizeCalls: [] as { images: string[]; barcode?: string | null }[] }
  return {
    state,
    upload: async () => {
      state.uploads += 1
      return `https://oss.example/inbound/${state.uploads}.jpg`
    },
    recognize: async (payload: { images: string[]; barcode?: string | null }) => {
      state.recognizeCalls.push(payload)
      // 服务端：barcode 非空 ⇒ PATH_BARCODE（0 次 LLM）；否则 vision（1 次）
      if (!payload.barcode) state.llmCalls += 1
      return {
        path: payload.barcode ? 'barcode_decode' : 'vision',
        barcode: payload.barcode ?? null,
        skuMatches: payload.barcode ? [{ skuId: 9, productId: 'p1', skuCode: 'MG-1001' }] : [],
        requiresManualEntry: !payload.barcode,
      }
    },
  }
}

const PHOTO_A = { tempFilePath: 'blob:photo-a', file: 'blob:photo-a' }
const PHOTO_B = { tempFilePath: 'blob:photo-b', file: 'blob:photo-b' }

/**
 * LLM 成本判定（真判据与注入式红证**共用同一份**，见 `migao-dev-flow` §23.5）：
 * 照片里有可解条码时，**一次 vision 都不许有**。
 */
function llmCostProblems(llmCalls: number): string[] {
  return llmCalls > 0 ? [`照片含可解条码却仍调了 ${llmCalls} 次 LLM/vision（本链要求 0 次）`] : []
}

describe('识别主链：解码优先（0 次 LLM 调用）', () => {
  it('C3 解码库真能解出码（encode → decode 真往返，不是替身）', () => {
    const url = 'https://app.migaozn.com/i/ABCD2345'
    const decoded = decodeQrFromImageData(qrImage(url))
    expect(decoded).toBe(url)
    // 反向：纯白图不该解出任何东西（防"永远返回第一个参数"式的假实现）
    const blank = { data: new Uint8ClampedArray(64 * 64 * 4).fill(255), width: 64, height: 64 }
    expect(decodeQrFromImageData(blank)).toBeNull()
  })

  it('C1 照片含可解条码 ⇒ 0 次 LLM 调用 + 只上传 1 张 + 条码原文带上', async () => {
    const server = fakeServer()
    const result = await runInboundRecognize({
      photos: [PHOTO_A, PHOTO_B],
      decode: async (photo) =>
        photo === PHOTO_A
          ? { text: 'MG-1001', source: 'h5-dom-canvas' as const, hint: '' }
          : { text: null, source: 'h5-dom-canvas' as const, hint: '这张没有码' },
      upload: server.upload,
      recognize: server.recognize,
    })
    expect(server.state.llmCalls).toBe(0)
    expect(result.expectedLlmCalls).toBe(0)
    expect(result.route).toBe('local-barcode')
    expect(result.uploadedCount).toBe(1)
    expect(server.state.uploads).toBe(1)
    expect(server.state.recognizeCalls).toHaveLength(1)
    expect(server.state.recognizeCalls[0].barcode).toBe('MG-1001')
    // 第一张就解出来了 ⇒ **不**继续解第二张（不白跑）
    expect(result.decodedBarcode).toBe('MG-1001')
  })

  it('C1 🔴 红证：把识别排到解码之前（"先问模型，省事"）⇒ 同一判定必红', async () => {
    const server = fakeServer()
    // 坏形态 = "先问模型"：`decode` 自己**先去调一次 vision**（正是被判据禁止的那一步）。
    // 它作为 `deps.decode` 喂给**真函数** `runInboundRecognize` ⇒ 真函数照样会调它 ⇒ 成本计数变正。
    const wrongOrderDecode = async () => {
      await server.recognize({ images: [await server.upload()] })
      return { text: null, source: null, hint: '' }
    }
    const result = await runInboundRecognize({
      photos: [PHOTO_A],
      decode: wrongOrderDecode,
      upload: server.upload,
      recognize: server.recognize,
    })
    expect(llmCostProblems(server.state.llmCalls).join('\n')).toContain('LLM/vision')
    // 走的是**贵的**那条路（vision 兜底），而不是解码优先那条 0 成本的路
    expect(result.route).toBe('server-vision')
    // 对照：正确顺序（解码优先，真函数自带的语义）下**同一判定**判绿 ——
    // 这一半让本 case 真的走被测函数（把它整体禁用 ⇒ 本 case 必红，不再是空断言）
    const ok = fakeServer()
    await runInboundRecognize({
      photos: [PHOTO_A],
      decode: async () => ({ text: 'MG-1001', source: 'h5-dom-canvas' as const, hint: '' }),
      upload: ok.upload,
      recognize: ok.recognize,
    })
    expect(llmCostProblems(ok.state.llmCalls)).toEqual([])
  })

  it('C2 解码失败 ⇒ 全量上传（≤3）+ 不带 barcode ⇒ 服务端 vision 兜底', async () => {
    const server = fakeServer()
    const result = await runInboundRecognize({
      photos: [PHOTO_A, PHOTO_B],
      decode: async () => ({ text: null, source: 'h5-dom-canvas' as const, hint: '这张照片里没有可识别的二维码' }),
      upload: server.upload,
      recognize: server.recognize,
    })
    expect(result.route).toBe('server-vision')
    expect(server.state.uploads).toBe(2)
    expect(server.state.recognizeCalls[0].barcode).toBeUndefined()
    expect(server.state.llmCalls).toBe(1)
    // 一次最多 3 张（与服务端 MAX_IMAGES 同口径）
    expect(result.uploadedCount).toBeLessThanOrEqual(MAX_INBOUND_PHOTOS)
  })

  it('C2 超过 3 张 ⇒ 端侧先截到 3 张（不让工人白等一次 400）', async () => {
    const server = fakeServer()
    const result = await runInboundRecognize({
      photos: [PHOTO_A, PHOTO_B, PHOTO_A, PHOTO_B, PHOTO_A],
      decode: async () => ({ text: null, source: null, hint: 'x' }),
      upload: server.upload,
      recognize: server.recognize,
    })
    expect(result.uploadedCount).toBe(MAX_INBOUND_PHOTOS)
  })

  it('C4 解码/降级过程有话要说（不静默）', async () => {
    const server = fakeServer()
    const result = await runInboundRecognize({
      photos: [PHOTO_A],
      decode: async () => ({ text: null, source: null, hint: '这张照片读不出像素（可能不是图片）' }),
      upload: server.upload,
      recognize: server.recognize,
    })
    expect(result.notices.join('\n')).toContain('读不出像素')
    expect(result.notices.join('\n')).toContain('已改用服务端识别')
  })

  it('一张照片都没有 ⇒ 明说（不静默走一次空请求）', async () => {
    const server = fakeServer()
    await expect(
      runInboundRecognize({
        photos: [],
        decode: async () => ({ text: null, source: null, hint: '' }),
        upload: server.upload,
        recognize: server.recognize,
      }),
    ).rejects.toThrow(/请先拍照/)
    expect(server.state.uploads).toBe(0)
  })
})
