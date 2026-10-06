/**
 * 免驱动直连通道的 **provider**（issue #6439）—— 首批实现 = 德佟 LPAPI（浏览器 Web Bluetooth）。
 *
 * ## 为什么是 provider（而不是「德佟打印按钮」）
 *
 * 用户 2026-10-06 逐字：「**不要做成打印机定制功能** … 只要我们功能支持能连接上不同类型的打印机即可」。
 * ⇒ 页面只认 {@link LabelPrinterProvider} 这个接口；换厂商 = **加一个 adapter**，页面一行不改。
 *
 * ⚠️ 边界（照实登记，不粉饰）：Web Bluetooth 是**点对点协议、没有通用标准** ⇒ 直连通道
 * **永远只覆盖「带 SDK 协议的机型」**。要打任意品牌，走的是**系统打印**那条路
 * （见 `frontend/admin-web/src/lib/label-print/capability.ts` 的 `SYSTEM_PRINT_HINT`）。
 *
 * ## 🔴 本文件里那条**真机实测**出来的硬约束（2026-10-06，本机 DP235S / Chrome 153）
 *
 * `openPrinter()` **空参必失败**。反混淆 `lpapi-ble@1.7.260618` 的 `libs/index.umd.js` 读出的分支：
 *
 * ```js
 * // 没给 name/deviceId ⇒ c 取不到 ⇒ 落到这里：
 * if (e.autoScan !== false) e.autoScan = true
 * c = await this.searchPrinter({ name: e.name, deviceId: e.deviceId, models: e.models, timeout: 5000 })
 * if (!c) return { statusCode: 2, errMsg: '未搜索到到打印机设备！' }   // ERROR_NO_PRINTER
 * ```
 *
 * 而 **Web Bluetooth 没有用户手势就扫不了**（只能靠 `requestDevice` 弹框）⇒ 空参**恒失败**。
 * ⇒ 正确形态 = {@link openPrinterOptions}：把弹框选中的设备**显式喂进去** + `autoScan:false`。
 * 本机实测：改成这个形态后连接与打印均成功。
 *
 * 🔴 同一缺陷**已存在于** `frontend/bmini-app/src/utils/inbound/lpapiTransport.ts`（空参调用）——
 * 同族缺陷，链内一并修（同一 PR）。
 */
import type { DirectPrintFailureReason } from './capability'

/** `requestDevice` 回执里的设备（`LPA_Device` 的子集） */
export interface LpapiDeviceLike {
  name?: string
  deviceId?: string
  [key: string]: unknown
}

/** 回执包络（**实测形状**：`{statusCode, resultInfo, errMsg}`；判定只看 `statusCode`） */
export interface LpapiResponseLike {
  statusCode?: number
  errMsg?: string
  codeName?: string
  resultInfo?: unknown
  printable?: number
  [key: string]: unknown
}

/** LPAPI 实例的窄接口（只取本单要用的方法） */
export interface LpapiPrinterLike {
  requestDevice(options?: unknown): Promise<LpapiResponseLike>
  /** @param options `openPrinterOptions()` 的结果 —— **空参必失败**，见文件头 */
  openPrinter(options?: unknown): Promise<LpapiResponseLike>
  printImageData(options: Record<string, unknown>): Promise<LpapiResponseLike>
  /** 连上后可读机器自报参数（`printerDPI` / `printerWidth` / `printable` …） */
  getPrinterInfo?(): Record<string, unknown> | undefined
}

/** LPAPI 模块（UMD 挂在 `globalThis.LPAPI`；`getInstance` / `create` 二者其一即可） */
export interface LpapiModuleLike {
  getInstance?: (options?: Record<string, unknown>) => LpapiPrinterLike
  create?: (options?: Record<string, unknown>) => LpapiPrinterLike
}

/** 一次送印的位图（**像素**宽高；不含任何机型参数） */
export interface PrintJob {
  imageData: ImageData
  widthPx: number
  heightPx: number
  jobName: string
}

/**
 * 直连打印机通道接口 —— 页面只认它。
 * 换厂商（别的 SDK / WebHID / 将来的 WebUSB）⇒ 加实现，**页面不改**。
 */
export interface LabelPrinterProvider {
  readonly id: string
  readonly label: string
  /** 已连接的设备名；`null` = 还没连 */
  deviceName: string | null
  /** 机器自报参数（`getPrinterInfo()` 原文；几何由它推出 —— 不写死机型） */
  printerInfo: Record<string, unknown> | null
  connect(): Promise<void>
  print(jobs: PrintJob[]): Promise<void>
}

/** 直连通道的错误（带**分类**：分类决定给用户看哪一条可行动文案） */
export class LabelPrintError extends Error {
  readonly reason: DirectPrintFailureReason
  constructor(reason: DirectPrintFailureReason, message?: string) {
    super(message || reason)
    this.name = 'LabelPrintError'
    this.reason = reason
  }
}

/** LPAPI 回执状态码（`LPA_Result`；实测 `libs/lpapi/LPAUtils.d.ts`） */
export const LPAPI_STATUS = {
  OK: 0,
  NO_PRINTER: 2,
  DISCONNECTED: 3,
  CONNECT_FAILED: 4,
  UN_SUPPORTED: 19,
  CANCEL: 25,
} as const

/** `LPA_GapType.Unset` = 255（**随机器设置**）—— 介质类型由机器上的装纸决定，页面不替用户猜 */
export const LPAPI_GAP_TYPE_UNSET = 255
/** 位图黑白阈值（SDK 默认口径） */
export const LPAPI_THRESHOLD_DEFAULT = 192

/** `printImageData` 的纸张类型：**不替用户猜介质**（连续纸 / 间隙纸 / 黑标由机器上的装纸决定） */

/**
 * 回执状态码 ⇒ 失败分类（`null` = 成功）。
 *
 * 🔴 同一状态码在**连接期与打印期归到不同的类**：两类失败给用户的**可行动出口完全不同**
 * （「连不上」⇒ 检查开机/距离/占用；「打不出」⇒ 检查纸仓/卡纸）。
 */
export function classifyLpapiStatus(
  statusCode: number | undefined,
  phase: 'connect' | 'print',
): DirectPrintFailureReason | null {
  if (statusCode === undefined || statusCode === LPAPI_STATUS.OK) return null
  if (statusCode === LPAPI_STATUS.CANCEL) return 'user-cancelled'
  if (statusCode === LPAPI_STATUS.UN_SUPPORTED) return 'device-unsupported'
  return phase === 'print' ? 'print-failed' : 'connect-failed'
}

/**
 * `openPrinter` 的**必填形态**（真机实测，见文件头）：
 * 显式 `name` + `deviceId`，并关掉 `checkDeviceName` 与 `autoScan`。
 *
 * 红证：改回空参（`{}`）⇒ 判据必红（真机已证该形态恒回 `ERROR_NO_PRINTER`）。
 */
export function openPrinterOptions(device: LpapiDeviceLike): Record<string, unknown> {
  return {
    name: device.name,
    deviceId: device.deviceId,
    checkDeviceName: false,
    autoScan: false,
  }
}

/** 从模块命名空间 / 全局作用域取 LPAPI 模块（三种挂法都认；取不到 ⇒ `null`，**不抛**） */
export function resolveLpapiModule(scope: unknown): LpapiModuleLike | null {
  const root = scope as
    | { LPAPI?: unknown; default?: unknown }
    | null
    | undefined
  if (!root) return null
  // ⚠️ 先把候选**全部取出来**再逐个判：写成 `if (is(root.LPAPI)) … ; root.LPAPI?.LPAPI`
  //    会让 TS 在否定分支里把 `root.LPAPI` 收窄成 `never`（实测 `tsc` 报 TS2339）。
  const candidates: unknown[] = [
    root.LPAPI,
    (root.LPAPI as { LPAPI?: unknown } | null | undefined)?.LPAPI,
    (root.default as { LPAPI?: unknown } | null | undefined)?.LPAPI,
    root.default,
  ]
  for (const candidate of candidates) {
    if (isLpapiModule(candidate)) return candidate
  }
  return null
}

/** `getInstance` / `create` 至少有一个 ⇒ 这就是那个模块（**类型守卫独立成函数**，避免内联收窄） */
function isLpapiModule(candidate: unknown): candidate is LpapiModuleLike {
  const module = candidate as LpapiModuleLike | null | undefined
  return !!module && (typeof module.getInstance === 'function' || typeof module.create === 'function')
}

/**
 * 造一个 LPAPI provider（**注入式**：测试传替身，生产传真实实例）。
 *
 * ⚠️ 不传 `models`：写死型号会把别的机型判成「不支持的打印机设备」（SDK 默认已支持德佟全系）。
 */
export function createLpapiProvider(api: LpapiPrinterLike): LabelPrinterProvider {
  const provider: LabelPrinterProvider = {
    id: 'lpapi-ble',
    label: '标签打印机（网页直连 · 免驱动）',
    deviceName: null,
    printerInfo: null,
    async connect() {
      // ① 选设备（系统弹窗）—— 用户取消是 **resolve 回来** 的 statusCode=25，不是异常
      const picked = await api.requestDevice()
      const pickReason = classifyLpapiStatus(picked?.statusCode, 'connect')
      if (pickReason) throw new LabelPrintError(pickReason, picked?.errMsg)

      const device = (Array.isArray(picked?.resultInfo) ? picked.resultInfo[0] : null) as LpapiDeviceLike | null
      if (!device) throw new LabelPrintError('connect-failed', '未选择打印机设备')

      // ② 连接 —— 🔴 必须显式喂设备 + autoScan:false（空参必失败，见文件头）
      const opened = await api.openPrinter(openPrinterOptions(device))
      const openReason = classifyLpapiStatus(opened?.statusCode, 'connect')
      if (openReason) throw new LabelPrintError(openReason, opened?.errMsg)

      provider.deviceName = device.name ?? null
      try {
        provider.printerInfo = api.getPrinterInfo?.() ?? null
      } catch {
        provider.printerInfo = null
      }
    },
    async print(jobs: PrintJob[]) {
      for (const job of jobs) {
        // 1:1 送点阵：宽高就是渲染出来的像素数，不加任何缩放参数；
        // 纸张类型取「随机器设置」—— 连续纸 / 间隙纸 / 黑标由机器上的装纸决定
        const sent = await api.printImageData({
          imageData: job.imageData,
          width: job.widthPx,
          height: job.heightPx,
          gapType: LPAPI_GAP_TYPE_UNSET,
          threshold: LPAPI_THRESHOLD_DEFAULT,
          copies: 1,
          jobName: job.jobName,
        })
        const reason = classifyLpapiStatus(sent?.statusCode, 'print')
        if (reason) throw new LabelPrintError(reason, sent?.errMsg)
      }
    },
  }
  return provider
}

/**
 * 动态加载厂商 SDK（**npm 依赖 `lpapi-ble`**，与 `frontend/bmini-app` 侧**同一个包、同一个版本口径**）。
 *
 * ⚠️ 为什么不 vendor 一份 UMD 到 `public/`：那份 bundle 里带着自己的像素口径字面量，
 * 会撞上「打印头宽只许出现在介质矩阵」的类级守卫
 * （`frontend/bmini-app/tests/inbound-print-geometry-single-source.test.ts` C2b）；
 * 而 npm 依赖走 `node_modules`，既不在守卫射程内、又不进仓库。
 *
 * 取不到 ⇒ `null`（**不抛**）：调用方翻成 `sdk-unavailable` 文案（可行动：保持联网刷新重试）。
 * 动态 `import()` ⇒ 这个包只在**用户点「直连打印机打印」时**才下载（不影响首屏）。
 */
export async function loadLpapiApi(): Promise<LpapiPrinterLike | null> {
  try {
    const mod = (await import(/* webpackChunkName: "lpapi-ble" */ 'lpapi-ble')) as unknown
    // 与 bmini 侧 `loadLpapi()` 同口径：命名空间 `LPAPI` / `default.LPAPI` / `default` 三选一；
    // 兜底再看全局（有些打包器会把它挂到 `globalThis`）
    const module = resolveLpapiModule(mod) ?? resolveLpapiModule(globalThis)
    return module ? instantiate(module) : null
  } catch {
    return null
  }
}

/** UMD 实例化（`webBLE: true` = 走浏览器蓝牙适配层） */
function instantiate(module: LpapiModuleLike): LpapiPrinterLike | null {
  const factory = module.getInstance ?? module.create
  if (!factory) return null
  return factory.call(module, { webBLE: true })
}
