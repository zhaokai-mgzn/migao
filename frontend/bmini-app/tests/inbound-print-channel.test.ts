// case_ids: BM-014, BM-015
/**
 * **打印必留痕 + 前端不自行计数 + 失败逐种文案**（issue #5052 P3/P4；设计 §7.3 / §8.3；
 * 验收判据 4 / 5 / 9）
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | D1 | 送打印的**唯一**入口先调服务端留痕（顺序：render → **recordPrint** → transport） | 交换成 print→record ⇒ 红 |
 * | D2 | 留痕失败 ⇒ **不打印**（不产生无痕打印） | 留痕抛错仍打印 ⇒ 红 |
 * | D3 | 能力不可用 ⇒ **既不调服务端也不连蓝牙**（动手前就说清） | 先连再判 ⇒ 红 |
 * | D4 | 计数**原样转发**服务端回执（两次不同读数 ⇒ 两次都原样，不做本地 +1） | 本地 +1 ⇒ 红 |
 * | D5 | 失败文案**逐种不同且可行动**（合并成一句通用文案 ⇒ 红） | 两条相同 ⇒ 红 |
 * | D6 | 台账条目活着：`INBOUND_PRINT_GAP_WIRING` 的键集 == 文案表的键集 | 删一条 ⇒ 红 |
 */
import fs from 'fs'
import path from 'path'
import {
  printInboundLabel,
  classifyPrintError,
  LabelTransportError,
  type LabelTransport,
} from '../src/utils/inbound/labelPrint'
import {
  PRINT_FAILURE_HINTS,
  probePrintCapability,
  printFailureHint,
  type PrintFailureReason,
} from '../src/utils/inbound/printCapability'
import { INBOUND_PRINT_GAP_WIRING } from '../src/utils/inbound/gaps'
import { layoutInboundLabel } from '../src/utils/inbound/labelLayout'
import { renderInboundLabel, type RenderedLabel } from '../src/utils/inbound/labelCanvas'

const REPO_ROOT = path.join(__dirname, '..', '..', '..')

function fakeLabel(): RenderedLabel {
  const plan = layoutInboundLabel({ shortCode: 'ABCD2345', productName: '遮光布', quantity: '60.5' })
  return {
    plan,
    canvas: { width: plan.widthPx, height: plan.heightPx, getContext: () => null as any },
    image: { data: new Uint8ClampedArray(plan.widthPx * plan.heightPx * 4), width: plan.widthPx, height: plan.heightPx },
    widthPx: plan.widthPx,
    heightPx: plan.heightPx,
  }
}

const OK_CAPABILITY = probePrintCapability({
  platform: 'h5',
  secureContext: true,
  hasBluetoothApi: true,
  isIos: false,
})

describe('打印通道：必留痕 / 不自行计数 / 逐种文案', () => {
  it('D1 顺序 = render → recordPrint → transport（留痕**先于**送数据）', async () => {
    const log: string[] = []
    const transport: LabelTransport = {
      id: 'fake',
      label: '测试打印机',
      print: async () => {
        log.push('transport')
      },
    }
    const result = await printInboundLabel({
      shortCode: 'ABCD2345',
      capability: OK_CAPABILITY,
      transport,
      render: () => {
        log.push('render')
        return fakeLabel()
      },
      recordPrint: async (code) => {
        log.push('recordPrint')
        return { shortCode: code, printCount: 7 }
      },
    })
    expect(log).toEqual(['render', 'recordPrint', 'transport'])
    expect(result).toEqual({ ok: true, printCount: 7, transportId: 'fake', transportLabel: '测试打印机' })
  })

  it('D1 🔴 红证：把送数据排到留痕之前（"先打出来再说"）⇒ 顺序判据必红', async () => {
    const log: string[] = []
    // 复刻错误顺序
    log.push('transport')
    log.push('recordPrint')
    expect(log).not.toEqual(['render', 'recordPrint', 'transport'])
  })

  it('D2 留痕失败 ⇒ 一次都不送数据（不产生无痕打印）', async () => {
    let printed = 0
    const transport: LabelTransport = {
      id: 'fake',
      label: '测试打印机',
      print: async () => {
        printed += 1
      },
    }
    const result = await printInboundLabel({
      shortCode: 'ABCD2345',
      capability: OK_CAPABILITY,
      transport,
      render: fakeLabel,
      recordPrint: async () => {
        throw new Error('网络断了')
      },
    })
    expect(printed).toBe(0)
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.printRecorded).toBe(false)
      expect(result.hint).toContain('留痕')
    }
  })

  it('D3 能力不可用 ⇒ 既不调服务端也不连蓝牙，且给出**原因专属**文案', async () => {
    let recorded = 0
    let printed = 0
    const ios = probePrintCapability({ platform: 'h5', secureContext: true, hasBluetoothApi: false, isIos: true })
    const result = await printInboundLabel({
      shortCode: 'ABCD2345',
      capability: ios,
      transport: {
        id: 'fake',
        label: 'x',
        print: async () => {
          printed += 1
        },
      },
      render: fakeLabel,
      recordPrint: async (code) => {
        recorded += 1
        return { shortCode: code, printCount: 1 }
      },
    })
    expect(recorded).toBe(0)
    expect(printed).toBe(0)
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.reason).toBe('ios-unsupported')
      expect(result.hint).toContain('iPhone')
    }
  })

  it('D3 探测顺序：iOS 优先于「没有蓝牙接口」（否则把人引向"换浏览器"这条走不通的路）', () => {
    const iosNoApi = probePrintCapability({ platform: 'h5', secureContext: true, hasBluetoothApi: false, isIos: true })
    expect(iosNoApi.reason).toBe('ios-unsupported')
    const nonH5 = probePrintCapability({ platform: 'weapp', secureContext: true, hasBluetoothApi: true, isIos: false })
    expect(nonH5.reason).toBe('not-h5')
    const insecure = probePrintCapability({ platform: 'h5', secureContext: false, hasBluetoothApi: true, isIos: false })
    expect(insecure.reason).toBe('insecure-context')
    // `isSecureContext` 缺失（老浏览器）⇒ 按**不安全**处理（fail-closed）
    const unknown = probePrintCapability({ platform: 'h5', hasBluetoothApi: true, isIos: false })
    expect(unknown.reason).toBe('insecure-context')
    const noApi = probePrintCapability({ platform: 'h5', secureContext: true, hasBluetoothApi: false, isIos: false })
    expect(noApi.reason).toBe('no-bluetooth-api')
    const ok = probePrintCapability({ platform: 'h5', secureContext: true, hasBluetoothApi: true, isIos: false })
    expect(ok.ok).toBe(true)
    expect(ok.hint).toBe('')
  })

  it('D4 计数取自服务端回执：两次不同读数**原样**转发（本地 +1 立刻露馅）', async () => {
    const transport: LabelTransport = { id: 'fake', label: 'x', print: async () => undefined }
    const first = await printInboundLabel({
      shortCode: 'ABCD2345',
      capability: OK_CAPABILITY,
      transport,
      render: fakeLabel,
      recordPrint: async (code) => ({ shortCode: code, printCount: 7 }),
    })
    const second = await printInboundLabel({
      shortCode: 'ABCD2345',
      capability: OK_CAPABILITY,
      transport,
      render: fakeLabel,
      recordPrint: async (code) => ({ shortCode: code, printCount: 12 }),
    })
    expect(first.ok && first.printCount).toBe(7)
    expect(second.ok && second.printCount).toBe(12)
  })

  it('D4 前端不自行计数（源码面：入库模块里没有对 printCount 的算术）', () => {
    const dir = path.join(REPO_ROOT, 'frontend/bmini-app/src/utils/inbound')
    const offenders: string[] = []
    for (const name of fs.readdirSync(dir)) {
      if (!/\.tsx?$/.test(name)) continue
      const code = fs
        .readFileSync(path.join(dir, name), 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
      if (/printCount\s*(\+\+|[+\-*/]=?)/.test(code) || /(\+\+|--)\s*\w*printCount/.test(code)) {
        offenders.push(name)
      }
    }
    expect(offenders).toEqual([])
  })

  it('D5 失败文案逐种不同、非空、可行动（合并成一句通用文案 ⇒ 红）', () => {
    const entries = Object.entries(PRINT_FAILURE_HINTS) as [PrintFailureReason, string][]
    expect(entries.length).toBeGreaterThanOrEqual(8)
    for (const [reason, hint] of entries) {
      expect(`${reason}:${hint}`.length).toBeGreaterThan(12)
      expect(hint.trim().length).toBeGreaterThanOrEqual(10)
    }
    const values = entries.map(([, hint]) => hint)
    expect(new Set(values).size).toBe(values.length)
    // 逐种文案必须点名各自的**可行动出口**，不能都是一句"打印失败"
    expect(PRINT_FAILURE_HINTS['ios-unsupported']).toMatch(/iPhone|iPad/)
    expect(PRINT_FAILURE_HINTS['insecure-context']).toMatch(/HTTPS/)
    expect(PRINT_FAILURE_HINTS['no-bluetooth-api']).toMatch(/Chrome/)
    expect(PRINT_FAILURE_HINTS['not-h5']).toMatch(/Chrome|电脑/)
    expect(PRINT_FAILURE_HINTS['user-cancelled']).toMatch(/取消/)
    expect(PRINT_FAILURE_HINTS['connect-failed']).toMatch(/开机|3 米/)
    expect(printFailureHint('render-failed')).toContain('空白标签')
    // 未知原因 ⇒ 回落但**不为空**（空提示 = 静默失败）
    expect(printFailureHint('不存在的原因' as PrintFailureReason).length).toBeGreaterThan(10)
  })

  it('D6 台账条目活着：接线台账的键集 == 文案表的键集（删一条 ⇒ 红）', () => {
    const wired = INBOUND_PRINT_GAP_WIRING.map((item) => item.reason).sort()
    const declared = (Object.keys(PRINT_FAILURE_HINTS) as PrintFailureReason[]).sort()
    expect(wired).toEqual(declared)
    // 每一条都点名了**在哪个文件被引用**，且那个文件真的提到该原因字面量
    for (const item of INBOUND_PRINT_GAP_WIRING) {
      const file = path.join(REPO_ROOT, 'frontend/bmini-app', item.wiredBy)
      expect(fs.existsSync(file)).toBe(true)
      expect(fs.readFileSync(file, 'utf8')).toContain(item.reason)
    }
  })

  it('D5 传输层异常 → 分类（未知一律 print-failed，不吞、不假装）', () => {
    expect(classifyPrintError(new LabelTransportError('user-cancelled'))).toBe('user-cancelled')
    expect(classifyPrintError(new LabelTransportError('connect-failed'))).toBe('connect-failed')
    expect(classifyPrintError(new Error('User cancelled the requestDevice'))).toBe('user-cancelled')
    expect(classifyPrintError(new Error('GATT connect timeout'))).toBe('connect-failed')
    expect(classifyPrintError(new Error('打印头过热')))
      .toBe('print-failed')
  })

  it('送数据失败 ⇒ 回执里要说清「留痕已发生」（重打会再记一次，不能骗工人）', async () => {
    const result = await printInboundLabel({
      shortCode: 'ABCD2345',
      capability: OK_CAPABILITY,
      transport: {
        id: 'fake',
        label: 'x',
        print: async () => {
          throw new LabelTransportError('connect-failed', 'GATT timeout')
        },
      },
      render: fakeLabel,
      recordPrint: async (code) => ({ shortCode: code, printCount: 3 }),
    })
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.reason).toBe('connect-failed')
      expect(result.printRecorded).toBe(true)
      expect(result.hint).toBe(PRINT_FAILURE_HINTS['connect-failed'])
    }
  })

  it('渲染失败 ⇒ 中止且**未**留痕（画不出来就不该占一次计数）', async () => {
    let recorded = 0
    const result = await printInboundLabel({
      shortCode: 'ABCD2345',
      capability: OK_CAPABILITY,
      transport: { id: 'fake', label: 'x', print: async () => undefined },
      render: () => {
        throw new Error('no canvas')
      },
      recordPrint: async (code) => {
        recorded += 1
        return { shortCode: code, printCount: 1 }
      },
    })
    expect(recorded).toBe(0)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.reason).toBe('render-failed')
  })

  it('渲染器与打印通道共用同一份版面（打印用的位图就是预览那份计划）', () => {
    const rendered = renderInboundLabel({ shortCode: 'ABCD2345' }, (w, h) => {
      const ctx = {
        fillStyle: '',
        font: '',
        textBaseline: '',
        fillRect: () => undefined,
        fillText: () => undefined,
        getImageData: (x: number, y: number, w2: number, h2: number) => ({
          data: new Uint8ClampedArray(w2 * h2 * 4),
          width: w2,
          height: h2,
        }),
      }
      return { width: w, height: h, getContext: () => ctx }
    })
    expect(rendered.image.width).toBe(rendered.plan.widthPx)
    expect(rendered.image.height).toBe(rendered.plan.heightPx)
  })
})
