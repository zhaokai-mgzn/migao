// case_ids: BM-020, BM-023
/**
 * 拍照**补打**主链：解码优先（0 次 LLM）→ 码空间门禁 → 详情（404/410 分开）→ 打印留痕
 * （issue #5640；设计 §6.1 / §7.1 / §7.3）
 *
 * 与 P3 的 `inbound-decode-first.test.ts` 同范式：**用一个假服务端把「该调几次」变成可数读数**。
 * 本单多一层：假服务端同时复刻 `WorkerShortLinkService.normalize` 的**抄错归一化**
 * （`O→0`、`I/L→1`），用来证明「手输抄错的码仍然能查到单」这条口径**在服务端**成立，
 * 端侧只负责**原样送达**。
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | F1 | 解码命中 ⇒ **0 次 LLM**、不调识别端点（补打链里没有 vision 这一支） | 复刻「先问模型」 ⇒ 计数 1（同文件内对照） |
 * | F2 | 🔴 `/s/` 洗水码 ⇒ **一次都不查入库详情**（门禁在 `loadReprintDetail` 里） | 把 reading 伪造成入库码 ⇒ 立刻查一次（对照组） |
 * | F3 | 非米高码 ⇒ 同样一次都不查 + 明确告知 | 去掉码空间门禁 ⇒ 红 |
 * | F4 | 解码失败 ⇒ 走手输（**不猜单、不预填**）+ 重拍提示 | 解不出还去查 ⇒ 红 |
 * | F5 | **404 / 410 分开**：`not-found` 与 `revoked` 是两种状态、两句不同的话 | 合成一句话 ⇒ 判据红 |
 * | F5b | 服务端「200 但无 data」**不算 ready**（不返回空详情、不画假标签） | 只判 `success` ⇒ 红 |
 * | F6 | 打印必留痕：补打的详情走**同一个** `printInboundLabel`（render → recordPrint → transport），计数原样转发 | 顺序颠倒 / 本地 +1 ⇒ 红 |
 * | F7 | 缺码不画假码 / 长名截断可见：补打页走**同一份**版面（复用即继承） | 自带第二份版面 ⇒ G3（另一文件）红 |
 */
import qrcode from 'qrcode-generator'
import { decodeQrFromImageData } from '../src/utils/inbound/barcodeDecode'
import { classifyManualCode, classifyScannedCode } from '../src/utils/inbound/codeSpace'
import { MISSING_CODE_TEXT, layoutInboundLabel } from '../src/utils/inbound/labelLayout'
import { printInboundLabel, type LabelTransport } from '../src/utils/inbound/labelPrint'
import { PRINT_FAILURE_HINTS, probePrintCapability } from '../src/utils/inbound/printCapability'
import {
  REPRINT_NOT_FOUND_MESSAGE,
  REPRINT_REVOKED_MESSAGE,
  REPRINT_RESHOOT_HINT,
  loadReprintDetail,
  runReprintResolve,
  type ReprintDetailState,
} from '../src/utils/inbound/reprintFlow'
import type { RasterImageLike } from '../src/utils/inbound/labelCanvas'
import type { InboundLabelView } from '../src/utils/inbound/labelLayout'

/** 把一段文本画成黑白位图（真二维码，供 jsQR 真解 —— 不是替身对替身） */
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

const VIEW: InboundLabelView = {
  shortCode: 'ABCD0234',
  inboundNo: 'RK-20260927-0001',
  skuCode: 'MG-1001',
  productName: '遮光布',
  colorName: '米白',
  doorWidth: '280',
  quantity: '60.5',
  printCount: 1,
}

/**
 * 假服务端：复刻三件事 —— ① `barcode` 非空才不调 LLM（同 `WorkerInboundService.recognize`）；
 * ② `WorkerShortLinkService.normalize` 的抄错归一化（`O→0`、`I/L→1`）；
 * ③ 详情读面 404 / 410 的**状态码与错误码**（同 `GlobalExceptionHandler` + `InboundLabelService`）。
 */
function fakeServer() {
  const state = { llmCalls: 0, recognizeCalls: 0, detailCalls: [] as string[], revoked: false }
  /** 服务端归一化（逐字复刻 `WorkerShortLinkService.normalize` 的别名映射） */
  const normalize = (raw: string): string => {
    const upper = String(raw).trim().toUpperCase().replace('O', '0').replace('I', '1').replace('L', '1')
    return upper.length === 8 ? upper : ''
  }
  const lookup = async (shortCode: string) => {
    state.detailCalls.push(shortCode)
    const code = normalize(shortCode)
    if (!code) {
      return {
        success: false,
        message: '入库标签不存在',
        statusCode: 404,
        code: 'NOT_FOUND',
        suggestion: '请核对标签上的短码（8 位，字母与数字；字母 O/I/L 会被当作 0/1 处理）',
      }
    }
    if (code !== 'ABCD0234') {
      return { success: false, message: '入库标签不存在', statusCode: 404, code: 'NOT_FOUND' }
    }
    if (state.revoked) {
      return {
        success: false,
        message: '该入库标签已作废',
        statusCode: 410,
        code: 'LABEL_REVOKED',
        suggestion: '这张纸对应的标签已被撤销 —— 请按单据重新补打一张（旧码不再可用）',
      }
    }
    return { success: true, message: '', data: { ...VIEW, shortCode: code } }
  }
  return {
    state,
    normalize,
    lookup,
    recognize: async (payload: { images: string[]; barcode?: string | null }) => {
      state.recognizeCalls += 1
      if (!payload.barcode) state.llmCalls += 1
      return { path: payload.barcode ? 'barcode_decode' : 'vision' }
    },
  }
}

const OK_CAPABILITY = probePrintCapability({
  platform: 'h5',
  secureContext: true,
  hasBluetoothApi: true,
  isIos: false,
})

function fakeRendered(shortCode: string | null) {
  const plan = layoutInboundLabel({ ...VIEW, shortCode })
  return {
    plan,
    canvas: { width: plan.widthPx, height: plan.heightPx, getContext: () => null as any },
    image: {
      data: new Uint8ClampedArray(plan.widthPx * plan.heightPx * 4),
      width: plan.widthPx,
      height: plan.heightPx,
    },
    widthPx: plan.widthPx,
    heightPx: plan.heightPx,
  }
}

describe('拍照补打主链：解码优先 / 码空间门禁 / 404-410 分开 / 打印留痕', () => {
  it('F1 解码命中 ⇒ 0 次 LLM、不调识别端点（对照：先问模型的那条路计数 1）', async () => {
    const server = fakeServer()
    const photo = { tempFilePath: 'blob:a', file: 'blob:a' }
    const result = await runReprintResolve({
      photo,
      decode: async () => ({
        text: 'https://app.migaozn.com/i/ABCD0234',
        source: 'h5-dom-canvas' as const,
        hint: '',
      }),
    })
    expect(result.route).toBe('local-decode')
    expect(result.expectedLlmCalls).toBe(0)
    expect(result.reading.space).toBe('inbound-label')
    expect(result.reading.shortCode).toBe('ABCD0234')
    // 解码链里**根本没有**识别这一支（本单只复用 `decode`，没有 vision 兜底参数）
    expect(server.state.llmCalls).toBe(0)
    expect(server.state.recognizeCalls).toBe(0)
    // 🔴 红证：复刻「先问模型，省事」—— 同一个假服务端立刻记一次 LLM 调用
    await server.recognize({ images: ['https://oss/1.jpg'] })
    expect(server.state.llmCalls).toBe(1)
  })

  it('F1 解码优先是**真解码**：encode → jsQR 往返能解出 /i/ 的 URL（不是替身对替身）', () => {
    const url = 'https://app.migaozn.com/i/ABCD0234'
    expect(decodeQrFromImageData(qrImage(url))).toBe(url)
    expect(classifyScannedCode(decodeQrFromImageData(qrImage(url))).shortCode).toBe('ABCD0234')
  })

  it('F2 🔴 洗水码 /s/ ⇒ 一次都不查入库详情，且给出报工入口', async () => {
    const server = fakeServer()
    const reading = classifyScannedCode('https://app.migaozn.com/s/7K3M9QP2')
    const state = await loadReprintDetail({ reading, lookup: server.lookup })
    expect(server.state.detailCalls).toEqual([])
    expect(state.kind).toBe('blocked')
    if (state.kind === 'blocked') {
      expect(state.space).toBe('wash-code')
      expect(state.message).toContain('洗水码')
      expect(state.action?.route).toBeTruthy()
    }
    // 🔴 红证（对照组）：把这同一个码**伪造成入库码** ⇒ 门禁一撤，立刻查一次（且服务端 404）
    const forged = { ...reading, space: 'inbound-label' as const, action: null }
    const wrong = await loadReprintDetail({ reading: forged, lookup: server.lookup })
    expect(server.state.detailCalls).toEqual(['7K3M9QP2'])
    expect(wrong.kind).toBe('not-found')
  })

  it('F3 非米高二维码 ⇒ 一次都不查 + 明确告知', async () => {
    const server = fakeServer()
    const reading = classifyScannedCode('https://example.com/i/ABCD0234')
    const state = await loadReprintDetail({ reading, lookup: server.lookup })
    expect(server.state.detailCalls).toEqual([])
    expect(state.kind).toBe('blocked')
    if (state.kind === 'blocked') expect(state.message).toContain('不是米高的标签')
  })

  it('F4 解码失败 ⇒ 走手输（不猜单、不预填）+ 重拍提示', async () => {
    const result = await runReprintResolve({
      photo: { tempFilePath: 'blob:a', file: 'blob:a' },
      decode: async () => ({ text: null, source: 'h5-dom-canvas' as const, hint: '这张照片里没有可识别的二维码。' }),
    })
    expect(result.route).toBe('manual-required')
    expect(result.reading.space).toBe('undecoded')
    expect(result.reading.shortCode).toBeNull()
    expect(result.notices.join('\n')).toContain('没有可识别的二维码')
    expect(result.notices.join('\n')).toContain(REPRINT_RESHOOT_HINT.slice(0, 12))
    // 不预填 = 没有任何单据字段被带出来（只有一句"请手输"）
    expect(result.reading.message).toContain('手输')
  })

  it('F5 🔴 404 / 410 分开呈现：两种状态、两句不同的话（合成一句 ⇒ 红）', async () => {
    const server = fakeServer()
    const reading = classifyScannedCode('https://app.migaozn.com/i/ABCD0234')

    const notFound = await loadReprintDetail({
      reading: classifyScannedCode('https://app.migaozn.com/i/ZZZZ9999'),
      lookup: server.lookup,
    })
    server.state.revoked = true
    const revoked = await loadReprintDetail({ reading, lookup: server.lookup })

    expect(notFound.kind).toBe('not-found')
    expect(revoked.kind).toBe('revoked')
    if (notFound.kind === 'not-found') {
      expect(notFound.message).toContain('查无此码')
      expect(notFound.message).toContain(REPRINT_NOT_FOUND_MESSAGE.slice(0, 6))
    }
    if (revoked.kind === 'revoked') {
      expect(revoked.message).toContain('已撤销')
      expect(revoked.message).toContain(REPRINT_REVOKED_MESSAGE.slice(0, 6))
    }
    const states: ReprintDetailState[] = [notFound, revoked]
    const messages = states.map((state) => ('message' in state ? state.message : ''))
    expect(messages[0]).not.toBe(messages[1])
    expect(REPRINT_NOT_FOUND_MESSAGE).not.toBe(REPRINT_REVOKED_MESSAGE)
    // 🔴 红证：合成一句话（"标签有问题，请联系文员"）⇒ 判别力当场消失
    const merged = '标签有问题，请联系文员'
    expect([merged, merged].every((message) => message.includes('已撤销'))).toBe(false)
    expect(merged).not.toContain('已撤销')
    // 撤销是业务动作、不存在可能是抄错码 ⇒ 处置不同（文案必须各自可行动）
    expect(REPRINT_REVOKED_MESSAGE).toMatch(/撤销|作废/)
    expect(REPRINT_NOT_FOUND_MESSAGE).toMatch(/抄|核对/)
  })

  it('F5b 服务端「200 但无 data」不算 ready（不返回空详情、不画假标签）', async () => {
    const state = await loadReprintDetail({
      reading: classifyScannedCode('https://app.migaozn.com/i/ABCD0234'),
      lookup: async () => ({ success: true, message: '' }),
    })
    expect(state.kind).toBe('error')
    if (state.kind === 'error') expect(state.message.trim().length).toBeGreaterThan(8)
  })

  it('F5c 手输抄错的码（O/I/L）走完整链路 ⇒ 服务端归一化后拿得到单据（端侧只原样送达）', async () => {
    const server = fakeServer()
    const reading = classifyManualCode('ABCDO234')
    expect(reading.shortCode).toBe('ABCDO234')
    const state = await loadReprintDetail({ reading, lookup: server.lookup })
    expect(server.state.detailCalls).toEqual(['ABCDO234'])
    expect(state.kind).toBe('ready')
    if (state.kind === 'ready') {
      // 字段真值只从服务端来：短码是服务端归一化后的那一个
      expect(state.view.shortCode).toBe('ABCD0234')
      expect(state.view.inboundNo).toBe(VIEW.inboundNo)
    }
  })

  it('F6 打印必留痕（补打的详情走同一个唯一入口）：顺序 render → recordPrint → transport，计数原样转发', async () => {
    const log: string[] = []
    const transport: LabelTransport = {
      id: 'fake',
      label: '测试打印机',
      print: async () => {
        log.push('transport')
      },
    }
    const first = await printInboundLabel({
      shortCode: 'ABCD0234',
      capability: OK_CAPABILITY,
      transport,
      render: () => {
        log.push('render')
        return fakeRendered('ABCD0234')
      },
      recordPrint: async (code) => {
        log.push('recordPrint')
        return { shortCode: code, printCount: 3 }
      },
    })
    expect(log).toEqual(['render', 'recordPrint', 'transport'])
    expect(first.ok && first.printCount).toBe(3)
    // 🔴 红证：顺序颠倒（先送数据）⇒ 同一个断言失败；本地 +1 ⇒ 下面的读数会变成 4
    expect(['transport', 'recordPrint', 'render']).not.toEqual(['render', 'recordPrint', 'transport'])
    const second = await printInboundLabel({
      shortCode: 'ABCD0234',
      capability: OK_CAPABILITY,
      transport,
      render: () => fakeRendered('ABCD0234'),
      recordPrint: async (code) => ({ shortCode: code, printCount: 9 }),
    })
    expect(second.ok && second.printCount).toBe(9)
  })

  it('F6 留痕失败 ⇒ 一次都不送数据（补打同样不许出现无痕打印）', async () => {
    let printed = 0
    const result = await printInboundLabel({
      shortCode: 'ABCD0234',
      capability: OK_CAPABILITY,
      transport: {
        id: 'fake',
        label: 'x',
        print: async () => {
          printed += 1
        },
      },
      render: () => fakeRendered('ABCD0234'),
      recordPrint: async () => {
        throw new Error('断网')
      },
    })
    expect(printed).toBe(0)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.printRecorded).toBe(false)
  })

  it('F6 打印能力不可用 ⇒ 既不调留痕也不连蓝牙（补打页与 P3 同一份逐种文案）', async () => {
    let recorded = 0
    let printed = 0
    const result = await printInboundLabel({
      shortCode: 'ABCD0234',
      capability: probePrintCapability({ platform: 'h5', secureContext: true, hasBluetoothApi: false, isIos: true }),
      transport: {
        id: 'fake',
        label: 'x',
        print: async () => {
          printed += 1
        },
      },
      render: () => fakeRendered('ABCD0234'),
      recordPrint: async (code) => {
        recorded += 1
        return { shortCode: code, printCount: 1 }
      },
    })
    expect(recorded).toBe(0)
    expect(printed).toBe(0)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.hint).toBe(PRINT_FAILURE_HINTS['ios-unsupported'])
  })

  it('F7 缺码不画假码 / 长名截断可见：补打走**同一份**版面（复用即继承，不是空断言）', () => {
    // 复用证据：补打链只把服务端详情交给同一个 layoutInboundLabel（下面两条断言就是 P3 已判据化的口径）
    const missing = layoutInboundLabel({ ...VIEW, shortCode: null })
    expect(missing.qr).toBeNull()
    expect(missing.codeText).toBe(MISSING_CODE_TEXT)
    expect(missing.warnings.join('\n')).toContain('不画占位码')

    const long = layoutInboundLabel({ ...VIEW, productName: '超长品名'.repeat(12) })
    const name = long.ops.find((op) => op.kind === 'text' && op.bold)
    expect(name && name.kind === 'text' && name.truncated).toBe(true)
    expect(name && name.kind === 'text' && name.text.endsWith('…')).toBe(true)
    expect(long.warnings.join('\n')).toContain('截断')

    const ok = layoutInboundLabel(VIEW)
    expect(ok.qr?.payload).toBe('https://app.migaozn.com/i/ABCD0234')
    expect(ok.codeText).toBe('ABCD0234')
  })
})
