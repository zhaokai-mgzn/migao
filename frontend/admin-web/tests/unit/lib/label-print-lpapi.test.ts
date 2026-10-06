// case_ids: PP-011
// @vitest-environment jsdom
//
// PP-011（issue #6439）：**免驱动直连通道的 provider**（首批 = 德佟 LPAPI，Web Bluetooth）。
//
// 🔴 本文件的核心是一条**真机实测出来的**缺陷（2026-10-06，本机 DP235S / Chrome 153）：
//   `openPrinter()` **空参必失败** —— 反混淆 `lpapi-ble@1.7.260618` 的 `libs/index.umd.js` 读出：
//   空参 ⇒ SDK 走自己的 `searchPrinter()` 重扫，而 Web Bluetooth **没有用户手势就扫不了**
//   ⇒ 恒回 `statusCode=2 ERROR_NO_PRINTER`「未搜索到到打印机设备！」。
//   正确形态 = **把弹框选中的设备显式喂进去** + `autoScan:false`（关掉它回去扫描的退路）。
//
// 逐条判据（都能判红）：
// ① `openPrinterOptions` 必须带 `name` / `deviceId` / `checkDeviceName:false` / `autoScan:false`
//    —— 红证：改回空参（`{}`）⇒ 判据必红（真机已证该形态恒失败）；
// ② 状态码**逐条分类**（不相干的两类不能合成一类）：19 = 机型不支持、25 = 用户取消、连接期其余 = 连不上、
//    打印期其余 = 打不出；`0` ⇒ null（成功不是失败）；
// ③ `connect()`：先 `requestDevice`（取消即 `user-cancelled`，**不得**继续 `openPrinter`），
//    再用 ① 的参数 `openPrinter`，成功后读机器自报 `getPrinterInfo()`；
// ④ `print()`：位图按 `width`/`height`（**像素**）+ 中性纸张类型逐张送；任一非 0 ⇒ 抛分类错误；
// ⑤ 失败一律抛 `LabelPrintError`（带 `reason`），页面据此给**可行动文案** —— 不静默。
import { describe, expect, it, vi } from 'vitest'
import {
  LabelPrintError,
  LPAPI_STATUS,
  classifyLpapiStatus,
  createLpapiProvider,
  openPrinterOptions,
  resolveLpapiModule,
  type LpapiPrinterLike,
  type LpapiResponseLike,
} from '@/lib/label-print/lpapi'

const OK = (over: Partial<LpapiResponseLike> = {}): LpapiResponseLike => ({
  statusCode: LPAPI_STATUS.OK,
  errMsg: 'OK',
  ...over,
})

/** 记录调用序的 LPAPI 替身（真实回执包络形状：`{statusCode, resultInfo, errMsg}`） */
function fakePrinter(over: {
  device?: LpapiResponseLike
  open?: LpapiResponseLike
  print?: LpapiResponseLike
  info?: Record<string, unknown>
} = {}) {
  const calls: Array<{ fn: string; args: unknown[] }> = []
  const api: LpapiPrinterLike = {
    requestDevice: vi.fn(async (...args: unknown[]) => {
      calls.push({ fn: 'requestDevice', args })
      return over.device ?? OK({ resultInfo: [{ name: 'DP235S-Y608220585', deviceId: 'dev-1' }] })
    }),
    openPrinter: vi.fn(async (...args: unknown[]) => {
      calls.push({ fn: 'openPrinter', args })
      return over.open ?? OK({ resultInfo: { deviceName: 'DP235S-Y608220585', printerDPI: 203, printerWidth: 384 } })
    }),
    printImageData: vi.fn(async (options: Record<string, unknown>) => {
      calls.push({ fn: 'printImageData', args: [options] })
      return over.print ?? OK({ printable: 0 })
    }),
    getPrinterInfo: () => over.info ?? { deviceName: 'DP235S-Y608220585', printerDPI: 203, printerWidth: 384 },
  }
  return { api, calls }
}

const job = (n = 1) =>
  Array.from({ length: n }, (_, i) => ({
    imageData: { width: 384, height: 320, data: new Uint8ClampedArray(4) } as unknown as ImageData,
    widthPx: 384,
    heightPx: 320,
    jobName: `wash-label-${i}`,
  }))

describe('openPrinterOptions — 真机实测的必填形态（issue #6439 判据 ①）', () => {
  it('🔴 必须显式喂设备 + 关掉 autoScan（改回空参 ⇒ 真机恒 ERROR_NO_PRINTER）', () => {
    expect(openPrinterOptions({ name: 'DP235S-Y608220585', deviceId: 'dev-1' })).toEqual({
      name: 'DP235S-Y608220585',
      deviceId: 'dev-1',
      checkDeviceName: false,
      autoScan: false,
    })
  })

  it('缺 deviceId 也不能退回空参（照样要带 name 与两个开关）', () => {
    const opts = openPrinterOptions({ name: 'DP235S-Y' })
    expect(opts.name).toBe('DP235S-Y')
    expect(opts.checkDeviceName).toBe(false)
    expect(opts.autoScan).toBe(false)
    expect(Object.keys(opts).length).toBeGreaterThanOrEqual(4)
  })
})

describe('classifyLpapiStatus — 逐条分类（issue #6439 判据 ②）', () => {
  it('0 ⇒ null（成功不是失败）', () => {
    expect(classifyLpapiStatus(LPAPI_STATUS.OK, 'connect')).toBeNull()
    expect(classifyLpapiStatus(undefined, 'print')).toBeNull()
  })

  it('取消 / 机型不支持 各成一类（出口完全不同）', () => {
    expect(classifyLpapiStatus(LPAPI_STATUS.CANCEL, 'connect')).toBe('user-cancelled')
    expect(classifyLpapiStatus(LPAPI_STATUS.UN_SUPPORTED, 'connect')).toBe('device-unsupported')
  })

  it('同一状态码在连接期与打印期归到**不同**的类（可行动出口不同）', () => {
    expect(classifyLpapiStatus(LPAPI_STATUS.NO_PRINTER, 'connect')).toBe('connect-failed')
    expect(classifyLpapiStatus(LPAPI_STATUS.NO_PRINTER, 'print')).toBe('print-failed')
    expect(classifyLpapiStatus(9, 'connect')).toBe('connect-failed')
    expect(classifyLpapiStatus(9, 'print')).toBe('print-failed')
  })
})

describe('createLpapiProvider — 连接（issue #6439 判据 ③）', () => {
  it('成功路径：requestDevice → openPrinter(带真机参数) → 读机器自报', async () => {
    const { api, calls } = fakePrinter()
    const provider = createLpapiProvider(api)
    await provider.connect()
    expect(calls.map((c) => c.fn)).toEqual(['requestDevice', 'openPrinter'])
    expect(calls[1].args[0]).toMatchObject({ name: 'DP235S-Y608220585', deviceId: 'dev-1', autoScan: false })
    expect(provider.deviceName).toBe('DP235S-Y608220585')
    expect(provider.printerInfo).toMatchObject({ printerDPI: 203, printerWidth: 384 })
  })

  it('用户在弹框点取消（statusCode 25）⇒ 抛 user-cancelled，且**不再**去 openPrinter', async () => {
    const { api, calls } = fakePrinter({ device: { statusCode: LPAPI_STATUS.CANCEL, errMsg: 'cancel' } })
    const provider = createLpapiProvider(api)
    await expect(provider.connect()).rejects.toBeInstanceOf(LabelPrintError)
    await expect(provider.connect()).rejects.toMatchObject({ reason: 'user-cancelled' })
    expect(calls.filter((c) => c.fn === 'openPrinter')).toHaveLength(0)
  })

  it('连不上（statusCode 2）⇒ 抛 connect-failed（真机首次实测就是这一条）', async () => {
    const { api } = fakePrinter({ open: { statusCode: LPAPI_STATUS.NO_PRINTER, errMsg: '未搜索到到打印机设备！' } })
    await expect(createLpapiProvider(api).connect()).rejects.toMatchObject({ reason: 'connect-failed' })
  })

  it('机型不支持（statusCode 19）⇒ device-unsupported（出口是「换一台」，不是「重试连接」）', async () => {
    const { api } = fakePrinter({ open: { statusCode: LPAPI_STATUS.UN_SUPPORTED, errMsg: '不支持的打印机设备' } })
    await expect(createLpapiProvider(api).connect()).rejects.toMatchObject({ reason: 'device-unsupported' })
  })
})

describe('createLpapiProvider — 打印（issue #6439 判据 ④⑤）', () => {
  it('逐张送位图：像素宽高 + 中性纸张类型（随机器设置，不替用户猜介质）', async () => {
    const { api, calls } = fakePrinter()
    await createLpapiProvider(api).print(job(2))
    const sent = calls.filter((c) => c.fn === 'printImageData').map((c) => c.args[0] as Record<string, unknown>)
    expect(sent).toHaveLength(2)
    expect(sent[0]).toMatchObject({ width: 384, height: 320, jobName: 'wash-label-0' })
    // 默认「随机器设置」—— 连续纸/间隙纸/黑标由机器上的装纸决定，页面不写死
    expect(sent[0].gapType).toBe(255)
  })

  it('非 0 回执 ⇒ 抛 print-failed（分类错误，不静默吞掉）', async () => {
    const { api } = fakePrinter({ print: { statusCode: 9, errMsg: '数据接收异常' } })
    await expect(createLpapiProvider(api).print(job(1))).rejects.toMatchObject({ reason: 'print-failed' })
  })

  it('打印中途失败 ⇒ 后续张不再送（不在坏状态下继续吐纸）', async () => {
    const { api, calls } = fakePrinter({ print: { statusCode: 9, errMsg: 'x' } })
    await expect(createLpapiProvider(api).print(job(3))).rejects.toBeInstanceOf(LabelPrintError)
    expect(calls.filter((c) => c.fn === 'printImageData')).toHaveLength(1)
  })
})

describe('resolveLpapiModule — SDK 从全局取（issue #6439）', () => {
  it('UMD 挂到 globalThis.LPAPI ⇒ 取到 getInstance；两者都没有 ⇒ null（不抛）', () => {
    const fake = { LPAPI: { getInstance: () => ({}) } }
    expect(resolveLpapiModule(fake)).toBe(fake.LPAPI)
    expect(resolveLpapiModule({ LPAPI: { LPAPI: { create: () => ({}) } } })).toEqual({ create: expect.any(Function) })
    expect(resolveLpapiModule({})).toBeNull()
    expect(resolveLpapiModule(undefined)).toBeNull()
  })
})
