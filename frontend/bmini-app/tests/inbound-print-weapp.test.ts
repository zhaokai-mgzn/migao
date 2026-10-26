// case_ids: BM-014, BM-015
/**
 * **小程序（weapp）蓝牙打印通道**（issue #7802；用户裁定 2026-10-26「现在接吧，这是我们当前的方案了」）
 *
 * ## 为什么需要这一层
 *
 * 工人从**微信扫一扫**进来，落在微信内置浏览器里 —— 那里**没有** `navigator.bluetooth`
 * （安卓 X5 / iOS WKWebView 都不暴露）⇒ h5 的 Web Bluetooth 通道在工人的日常入口上是死的。
 * 小程序有原生 BLE（`wx.*BLE`），是**唯一**能在「微信内不跳出去」把标签打出来的载体，
 * 也是**唯一**能覆盖 iPhone 的载体（小程序 BLE 在 iOS 开放）。
 *
 * ## 判据（每条都能单独变红）
 *
 * | # | 判据 | 红证（怎么让它单独红） |
 * |---|---|---|
 * | W1 | `weapp` 的能力探测 = **可用**（不再返回 `not-h5`） | 退回旧的 `platform !== 'h5' ⇒ not-h5` ⇒ 红 |
 * | W2 | 非 h5 / 非 weapp（alipay / tt / swan）仍判 `not-h5`（**不把"小程序能用"扩写成"任何端都能用"**） | 删掉 platform 判定 ⇒ 红 |
 * | W3 | `lpapi-ble-wx` 的入口是 **`LPAPIFactory`**（不是 h5 的 `LPAPI`）—— 适配器必须转出来 | 只认 `LPAPI` ⇒ 红 |
 * | W4 | `getPrintableMessage`（厂商自检文案）在 weapp 侧也要透传 | 丢掉透传 ⇒ 红 |
 * | W5 | 通道标识必须**区分**小程序与浏览器（同一个 id 会让排障时分不清走的哪条路） | 写死 `web-bluetooth-lpapi` ⇒ 红 |
 * | W6 | 小程序**没有系统设备弹窗** ⇒ `requestDevice()` 失败也要**降级**成 `openPrinter({autoScan:true})` 并打成 | 直接抛 `connect-failed` ⇒ 红 |
 * | W7 | `loadLpapi()` 必须**两条通道都在**（只接小程序或只接 h5 都算半成品） | 删任一条 ⇒ 红 |
 */
import fs from 'fs'
import path from 'path'
import {
  adaptWeappLpapi,
  createLpapiTransport,
  type LpapiModuleLike,
} from '../src/utils/inbound/lpapiTransport'
import { probePrintCapability, PRINT_READY_HINT_WX } from '../src/utils/inbound/printCapability'
import { createPrinterLinkStore } from '../src/utils/inbound/printerLink'
import type { RenderedLabel } from '../src/utils/inbound/labelCanvas'

// 🔴 只读**本模块内**的文件（不跨目录去读仓根）：`tests/unit_ci_workflows/test_local_gate_matrix.py`
// 的「触发面闭合」判据会把跨目录输入当成漏面风险（实测本次就是被它判红的）——
// bmini 的判据读 bmini 的文件，触发面天然覆盖。
const TRANSPORT_FILE = path.resolve(__dirname, '../src/utils/inbound/lpapiTransport.ts')

const LABEL: RenderedLabel = {
  image: { data: new Uint8ClampedArray(4), width: 1, height: 1 } as any,
  widthPx: 240,
  heightPx: 320,
  plan: { widthPx: 240, heightPx: 320 } as any,
} as RenderedLabel

/** 造一个 LPAPI 实例替身：记录调用序，按脚本回包 */
function fakePrinter(script: {
  requestDevice?: () => Promise<unknown>
  openPrinter?: (options: any) => Promise<unknown>
  printImageData?: (options: any) => Promise<unknown>
  getPrinterInfo?: () => unknown
}) {
  const calls: { name: string; options?: any }[] = []
  return {
    calls,
    printer: {
      requestDevice: async (options?: unknown) => {
        calls.push({ name: 'requestDevice', options })
        return script.requestDevice ? script.requestDevice() : { statusCode: 0, resultInfo: [] }
      },
      openPrinter: async (options?: unknown) => {
        calls.push({ name: 'openPrinter', options })
        return script.openPrinter ? script.openPrinter(options) : { statusCode: 0 }
      },
      printImageData: async (options?: unknown) => {
        calls.push({ name: 'printImageData', options })
        return script.printImageData ? script.printImageData(options) : { statusCode: 0 }
      },
      getPrinterInfo: () => (script.getPrinterInfo ? script.getPrinterInfo() : { printable: 0 }),
    },
  }
}

function fakeModule(printer: ReturnType<typeof fakePrinter>['printer']): LpapiModuleLike {
  return { getInstance: () => printer }
}

describe('W1/W2 能力探测：小程序可用，别的端不许跟着放行', () => {
  it('W1 weapp ⇒ ok（否则小程序里按钮永远是灰的，工人拿着机器也打不了）', () => {
    const cap = probePrintCapability({ platform: 'weapp', secureContext: false, hasBluetoothApi: false })
    expect(cap.ok).toBe(true)
    expect(cap.reason).toBeUndefined()
    // 正向说法必须指向**本页真实存在的**按钮（历史缺陷：让用户点「选打印机」，而页面没有这个按钮）
    expect(cap.readyHint).toBe(PRINT_READY_HINT_WX)
    expect(PRINT_READY_HINT_WX).toContain('打印标签')
    expect(PRINT_READY_HINT_WX).not.toContain('选打印机')
  })

  it('W2 其它编译目标（alipay / tt / unknown）仍判 not-h5', () => {
    for (const platform of ['alipay', 'tt', 'swan', 'unknown']) {
      const cap = probePrintCapability({ platform, secureContext: true, hasBluetoothApi: true })
      expect({ platform, ok: cap.ok }).toEqual({ platform, ok: false })
      expect(cap.reason).toBe('not-h5')
    }
  })

  it('W2 小程序判定**先于**安全上下文 / iOS（小程序没有 https 概念，iOS 也能打）', () => {
    const cap = probePrintCapability({
      platform: 'weapp',
      secureContext: false,
      hasBluetoothApi: false,
      isIos: true,
      isWechat: true,
    })
    expect(cap.ok).toBe(true)
  })
})

describe('W3/W4 `lpapi-ble-wx` 入口适配（它的工厂叫 LPAPIFactory，不是 LPAPI）', () => {
  it('W3 有 LPAPIFactory ⇒ 适配出 getInstance 并透传到工厂', () => {
    const instance = { printImageData: async () => ({ statusCode: 0 }) }
    const seen: unknown[] = []
    const factory = {
      getInstance: (options?: unknown) => {
        seen.push(options)
        return instance
      },
    }
    const adapted = adaptWeappLpapi({ LPAPIFactory: factory })
    const got = adapted!.getInstance!({ logLevel: 2 })
    expect(got).toBe(instance)
    expect(seen).toEqual([{ logLevel: 2 }])
  })

  it('W3 🔴 只有 h5 的 LPAPI（没有 LPAPIFactory）⇒ null（不许把浏览器工厂当小程序工厂用）', () => {
    expect(adaptWeappLpapi({ LPAPI: { getInstance: () => ({}) } })).toBeNull()
    expect(adaptWeappLpapi(null)).toBeNull()
    expect(adaptWeappLpapi({})).toBeNull()
  })

  it('W3 支持 default 导出形态（打包器把 ESM 塞进 default 时也要认）', () => {
    const instance = { printImageData: async () => ({ statusCode: 0 }) }
    const adapted = adaptWeappLpapi({ default: { LPAPIFactory: { getInstance: () => instance } } })
    expect(adapted!.getInstance!()).toBe(instance)
  })

  it('W4 getPrintableMessage 透传（缺纸/开盖的中文来自厂商表，不自造第二份）', () => {
    const adapted = adaptWeappLpapi({
      LPAPIFactory: { getInstance: () => ({ printImageData: async () => ({ statusCode: 0 }) }) },
      LPAPI: { getPrintableMessage: (code: number) => `厂商文案-${code}` },
    })!
    expect(adapted.getPrintableMessage!(35)).toBe('厂商文案-35')
    // 缺失 ⇒ 空串（不编造，不抛）
    const bare = adaptWeappLpapi({ LPAPIFactory: { getInstance: () => ({}) } })!
    expect(bare.getPrintableMessage!(35)).toBe('')
  })
})

describe('W5/W6 小程序通道的运行时形态', () => {
  it('W5 通道标识区分小程序与浏览器（排障时能一眼看出走的哪条路）', () => {
    const { printer } = fakePrinter({})
    const weapp = createLpapiTransport({ lpapi: fakeModule(printer), platform: 'weapp' })
    const h5 = createLpapiTransport({ lpapi: fakeModule(printer), platform: 'h5' })
    expect(weapp.id).toBe('weapp-native-ble')
    expect(weapp.label).toContain('小程序')
    expect(h5.id).toBe('web-bluetooth-lpapi')
    expect(h5.label).not.toContain('小程序')
    expect(weapp.label).not.toBe(h5.label)
  })

  it('W6 小程序没有系统设备弹窗 ⇒ requestDevice 失败时降级 autoScan 并真的打成', async () => {
    const { calls, printer } = fakePrinter({
      // 小程序侧 SDK 的搜索走不通（没有用户手势 / 没有弹窗接口）
      requestDevice: async () => {
        throw new Error('requestDevice is not supported in weapp')
      },
      openPrinter: async () => ({ statusCode: 0 }),
      printImageData: async () => ({ statusCode: 0 }),
    })
    const link = createPrinterLinkStore()
    const transport = createLpapiTransport({ lpapi: fakeModule(printer), platform: 'weapp', link })

    await transport.print(LABEL, { printCount: 1 })

    const opened = calls.find((c) => c.name === 'openPrinter')!
    // 降级的关键：不传 deviceId ⇒ 必须显式 autoScan:true，否则 SDK 回 ERROR_NO_PRINTER
    expect(opened.options).toMatchObject({ autoScan: true })
    expect(calls.map((c) => c.name)).toEqual(['requestDevice', 'openPrinter', 'printImageData'])
    expect(link.get().status).toBe('connected')
  })

  it('W6 搜索成功（有 deviceId）⇒ 仍走「显式喂设备 + autoScan:false」（不重复扫）', async () => {
    const { calls, printer } = fakePrinter({
      requestDevice: async () => ({
        statusCode: 0,
        resultInfo: [{ name: 'DP235S-Y608220585', deviceId: 'AA:BB:CC' }],
      }),
      openPrinter: async () => ({ statusCode: 0 }),
    })
    const transport = createLpapiTransport({ lpapi: fakeModule(printer), platform: 'weapp' })
    await transport.print(LABEL, { printCount: 2 })
    const opened = calls.find((c) => c.name === 'openPrinter')!
    expect(opened.options).toMatchObject({ name: 'DP235S-Y608220585', deviceId: 'AA:BB:CC', autoScan: false })
  })
})

describe('W7 源码面：两条通道都必须接线（只接一条 = 半成品）', () => {
  const source = fs.readFileSync(TRANSPORT_FILE, 'utf8')

  it('W7 loadLpapi 同时引用 lpapi-ble（h5）与 lpapi-ble-wx（小程序）', () => {
    expect(source).toContain('lpapi-ble-wx/lib/index.js')
    expect(source).toMatch(/import\(\s*\/\*[^*]*\*\/\s*'lpapi-ble'\s*\)/)
  })

  it('W7 weapp 分支必须在 h5 分支**之前**判（h5 检查返回 null 会先把小程序挡掉）', () => {
    const weappAt = source.indexOf('lpapi-ble-wx/lib/index.js')
    const h5At = source.indexOf("'lpapi-ble'")
    expect(weappAt).toBeGreaterThan(0)
    expect(h5At).toBeGreaterThan(0)
    const guardAt = source.indexOf('isWeapp()')
    expect(guardAt).toBeGreaterThan(0)
    expect(guardAt).toBeLessThan(h5At)
  })
})
