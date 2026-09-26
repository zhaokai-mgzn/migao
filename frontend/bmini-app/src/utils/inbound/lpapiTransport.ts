/**
 * 真实打印通道：**浏览器 Web Bluetooth（`lpapi-ble`，德佟 DothanTech）**（issue #5052 P4；设计 §8.3 分支 B）
 *
 * ## 为什么是它，而不是小程序侧那个包
 *
 * 用户裁定（2026-09-26）：**只做 h5**（小程序链路搁置）⇒ 取 `lpapi-ble`（`main` = `libs/index.umd.js`，
 * 「一款基于浏览器自带蓝牙的标签打印接口」）。`lpapi-ble-wx` 属小程序链路，**本单不引**。
 *
 * ## 三条边界（照实登记）
 *
 * 1. **只在 h5 加载**：`loadLpapi()` 先判平台再 `import()` ⇒ 小程序端**不加载**（那一侧打印能力
 *    在 `printCapability` 里显式判 `not-h5`，给的是可行动文案，不是静默失败）。
 * 2. **真机未验证**（⚠️ 未完成项，见 PR 正文）：本机没有 DP30S，也没有 Android / 桌面 Chrome 的
 *    蓝牙环境 ⇒ 「连上机器并真的打出一张」**没有实测**。故传输层做成**可注入接口**
 *    （`LabelTransport`），判据全部跑在替身上；真实实现只保留**薄胶水**。
 *    重启条件：拿到 DP30S 后跑一次 `createLpapiTransport` 的 `print()`，并确认
 *    ① 打出的点阵 1:1（不是被缩放/居中）② 版心右边界 ≤ 48mm ③ 服务端 `print_count` +1。
 * 3. **厂商口径未核实**（设计 §8.5 ①②③④）：SDK 是否厂商官方发布、DP30S 的 BLE 口是否开放、
 *    精确打印宽度 —— 全部未核实 ⇒ 本文件**不写死**任何「实测值」，只按安全侧（有效版心 ≤48mm，
 *    见 `./truth` 的 `effectiveWidthPx`）送图。
 */
import { isH5 } from '../platform'
import { LabelTransportError, type LabelTransport } from './labelPrint'
import type { RenderedLabel } from './labelCanvas'

/** 打印机型号（设计 §3.3 第一候选；`models` 是 LPAPI 的型号过滤参数） */
export const LPAPI_MODEL = 'DP30S'

/** LPAPI 实例的**窄接口**（只取本单要用的三个方法；SDK 的其余能力不进来） */
export interface LpapiPrinterLike {
  requestDevice(options?: unknown): Promise<unknown>
  openPrinter(options?: unknown): Promise<unknown>
  printImageData(options: Record<string, unknown>): Promise<unknown>
}

/** LPAPI 模块（`getInstance` / `create` 二者其一即可） */
export interface LpapiModuleLike {
  getInstance?: (options?: Record<string, unknown>) => LpapiPrinterLike
  create?: (options?: Record<string, unknown>) => LpapiPrinterLike
}

/**
 * 加载 `lpapi-ble`（**仅 h5**）。
 *
 * 返回 `null` 的两种情况都**不是异常**，而是「这条通道在当前环境不存在」：
 * ① 非 h5（用户裁定小程序链路搁置）；② 动态加载失败（离线 / 被拦截）⇒ 调用方给
 * `sdk-unavailable` 文案（可行动：保持联网刷新重试）。
 */
export async function loadLpapi(): Promise<LpapiModuleLike | null> {
  if (!isH5()) return null
  try {
    const mod: any = await import(/* webpackChunkName: "lpapi-ble" */ 'lpapi-ble')
    const candidate = mod?.LPAPI ?? mod?.default?.LPAPI ?? mod?.default ?? null
    if (!candidate) return null
    if (typeof candidate.getInstance === 'function' || typeof candidate.create === 'function') {
      return candidate as LpapiModuleLike
    }
    return null
  } catch {
    return null
  }
}

/** LPAPI 的回执包络（`{success, code, result, message}`）⇒ 失败即抛分类错误 */
function ensureOk(response: unknown, reason: 'connect-failed' | 'print-failed'): void {
  const res: any = response
  if (!res || typeof res !== 'object') return
  if (res.success === false || res.result === false) {
    throw new LabelTransportError(reason, String(res.message ?? res.errMsg ?? reason))
  }
  if (typeof res.code === 'number' && res.code !== 0) {
    throw new LabelTransportError(reason, String(res.message ?? `LPAPI code=${res.code}`))
  }
}

/**
 * 造一个 Web Bluetooth 标签打印通道。
 *
 * @param options.lpapi 已加载的 LPAPI 模块（**注入**：测试传替身，生产传 `loadLpapi()` 的结果）
 */
export function createLpapiTransport(options: {
  lpapi: LpapiModuleLike
  model?: string
}): LabelTransport {
  const { lpapi } = options
  const model = options.model || LPAPI_MODEL
  let printer: LpapiPrinterLike | null = null

  const ensurePrinter = (): LpapiPrinterLike => {
    if (printer) return printer
    const factory = lpapi.getInstance || lpapi.create
    if (!factory) throw new LabelTransportError('sdk-unavailable', 'LPAPI 模块没有 getInstance/create')
    printer = factory.call(lpapi, { models: model, webBLE: true })
    if (!printer || typeof printer.printImageData !== 'function') {
      throw new LabelTransportError('sdk-unavailable', 'LPAPI 实例没有 printImageData')
    }
    return printer
  }

  return {
    id: 'web-bluetooth-lpapi',
    label: `德佟 ${model}（浏览器蓝牙）`,
    async print(label: RenderedLabel, context: { printCount: number }): Promise<void> {
      const api = ensurePrinter()
      let device: unknown
      try {
        device = await api.requestDevice()
      } catch (error) {
        // 用户在系统弹窗里点了取消 ⇒ 与「连不上」是两件事（文案也不同）
        throw new LabelTransportError('user-cancelled', String((error as any)?.message ?? error))
      }
      ensureOk(device, 'connect-failed')
      try {
        const opened = await api.openPrinter()
        ensureOk(opened, 'connect-failed')
      } catch (error) {
        if (error instanceof LabelTransportError) throw error
        throw new LabelTransportError('connect-failed', String((error as any)?.message ?? error))
      }
      try {
        // 1:1 送点阵：宽高就是渲染出来的像素数，不加任何缩放参数
        const printed = await api.printImageData({
          imageData: label.image,
          width: label.widthPx,
          height: label.heightPx,
          // 「第几次」取自**服务端回执**（前端不自行计数）—— 交给 SDK 打日志/纸面标注
          copies: 1,
          jobName: `inbound-label-${context.printCount}`,
        })
        ensureOk(printed, 'print-failed')
      } catch (error) {
        if (error instanceof LabelTransportError) throw error
        throw new LabelTransportError('print-failed', String((error as any)?.message ?? error))
      }
    },
  }
}
