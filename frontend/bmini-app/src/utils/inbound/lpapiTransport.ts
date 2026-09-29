/**
 * 真实打印通道：**浏览器 Web Bluetooth（`lpapi-ble`，德佟 DothanTech）**（issue #5052 P4 / CP-1；设计 §8.3 分支 B）
 *
 * ## 为什么是它，以及**未来形态**下的复用面（2026-09-29 补充）
 *
 * 用户裁定（2026-09-26）：**只做 h5**（小程序链路搁置）⇒ 取 `lpapi-ble`。
 * 2026-09-29 用户补充产品形态 = **一端双编译（形态 A：小程序走原生页，不用 web-view）**
 * ⇒ 小程序侧接打印时**只需换 SDK**（`lpapi-ble-wx`，它本身就依赖 `lpapi-ble` 核心包、API 同形：
 * `getInstance` / `requestDevice` / `openPrinter` / `printImageData` / `getPrinterInfo`）
 * ⇒ 本文件的**回执判定、打印参数、状态面三层可原样复用**，页面与判据都不用重写。
 *
 * ## 五条实测口径（2026-09-29，读本机已装 `lpapi-ble@1.7.260618` 的 `libs/*.d.ts` 与 `libs/index.umd.js`）
 *
 * 1. **回执包络 = `{statusCode, resultInfo}` / `{statusCode, errMsg}`**（`success()` / `complete()`
 *    / `onResult(...)` 三处构造点实测），**没有** `success` / `result` / `code` 字段
 *    ⇒ 判定**只能**看 `statusCode`。历史缺陷：旧 `ensureOk` 查的正是那三个不存在的字段
 *    ⇒ 取消 / 环境不支持 / 未指定打印机**全部静默通过**，最后给工人一句错误归因的文案。
 * 2. **`requestDevice` 从不 reject**：失败（含用户在系统弹窗点取消）走
 *    `.catch(… → complete(ERROR_CANCEL, [], options))` **resolve 回来**
 *    ⇒ 「取消」必须由 `statusCode === 25` 认出来，**不能**靠 `try/catch`。
 * 3. **`requestDevice` 的过滤是写死的**：`filters = [{namePrefix:'DT'},{namePrefix:'DP'},{namePrefix:'P'}]`，
 *    `optionalServices` 只放 `FF00` / `FF10` / `49535343-fe7d-4ae5-8fa9-9fafd205e455`（Microchip 透传 UART）/ `180A`
 *    ⇒ 机器不满足这两条（名字前缀 + 服务白名单）就**根本不出现在系统列表里**（排障第一现场）。
 * 4. **不锁型号**：型号过滤走 `SupportPrinterMatcher` / `isSupportedDevice`，判不中就回
 *    `不支持的打印机设备:[<名>]`。实机是 **DP235S**（2026-09-29 到货），而仓库当时写死 `DP30S`
 *    ⇒ 这里**不传 `models`**（SDK 默认支持德佟全系），型号只用于**文案**。
 * 5. **打印参数就是实机那一屏**（`IEncodeParam`）：`gapType` / `gapLength` / `printDarkness` /
 *    `printSpeed` / `orientation` / `horizontalOffset` / `horizontalFlip`。不传 ⇒ 一切**随机器残留设置**
 *    （打歪 / 间距错 / 方向错），而机器上的设置是上一次谁用微打 APP 打什么留下的，**不可复现**。
 *
 * ## 边界（照实登记，不粉饰）
 *
 * - **只 h5**：weapp 端 `loadLpapi()` 返回 `null`（那一侧打印能力在 `printCapability` 里显式判，
 *   给的是可行动文案，不是静默失败）。
 * - **真机仍未实打**（2026-09-29）：本机没有安卓蓝牙环境 ⇒ 判据全部跑替身 + **真实回执包络形状**。
 *   重启条件（拿到安卓机后跑一次）：① 打出的点阵 1:1（不被缩放/居中）② 整幅在 30mm 纸内
 *   ③ 服务端 `print_count` +1 ④ 状态行显示「已连接」，机器关机后再打显示「未连上」。
 */
import { isH5 } from '../platform'
import { LabelTransportError, type LabelTransport } from './labelPrint'
import type { RenderedLabel } from './labelCanvas'
import {
  isAbnormalPrintable,
  linkStateAfterFailure,
  printerLink,
  toTransportError,
  type PrinterLinkStore,
} from './printerLink'

/** 打印机型号（**只用于文案**；型号过滤已移除，见文件头第 4 条） */
export const LPAPI_MODEL = 'DP235S'

/**
 * 打印参数（`IEncodeParam`）—— 值 = **2026-09-29 微打 APP 实机读数**：
 * 纸张类型「不干胶」、间隔长度 `3.00 毫米`、出纸方向随画布朝向。
 *
 * 🔴 与画布朝向的关系：微打 APP 的样例模板是**横版画布 + 270° 出纸方向**；我们的画布是
 * **30×40 竖版正立**（`truth.ts` 的口径）⇒ 取 `orientation: 0`（少一处旋转依赖）。
 * 真机核对项见 `frontend/admin-web/src/lib/print-media.json` 的 `pendingMeasurements`。
 */
export const LABEL_PRINT_PARAMS = {
  /** `LPA_GapType.Gap` = 2（间隙纸 = 不干胶标签纸；见 SDK `LPA_GapType`） */
  gapType: 2,
  /** 间隔长度（mm） */
  gapLength: 3,
  /** 出纸方向（0 = 不旋转） */
  orientation: 0,
} as const

/** LPAPI 回执状态码（`LPA_Result`；实测 `libs/lpapi/LPAUtils.d.ts`） */
const LPA_STATUS = { OK: 0, CANCEL: 25, UN_SUPPORTED: 19 } as const

/** 回执包络（**实测形状**：`{statusCode, resultInfo}` / `{statusCode, errMsg}`） */
interface LpaEnvelope {
  statusCode?: number
  resultInfo?: unknown
  errMsg?: string
}

/** LPAPI 实例的**窄接口**（只取本单要用的方法；SDK 的其余能力不进来） */
export interface LpapiPrinterLike {
  requestDevice(options?: unknown): Promise<unknown>
  openPrinter(options?: unknown): Promise<unknown>
  printImageData(options: Record<string, unknown>): Promise<unknown>
  /** 连上后可读机器自检态（`IPrinterInfoExt`：`printable` / `batteryCount` / `gapType` …） */
  getPrinterInfo?(): unknown
}

/** LPAPI 模块（`getInstance` / `create` 二者其一即可） */
export interface LpapiModuleLike {
  getInstance?: (options?: Record<string, unknown>) => LpapiPrinterLike
  create?: (options?: Record<string, unknown>) => LpapiPrinterLike
  /** **静态**方法（实测：`LPAPI.getPrintableMessage` 挂在 UMD 导出的 LPAPI 类上） */
  getPrintableMessage?: (printable: number) => string
}

/**
 * 加载 `lpapi-ble`（**仅 h5**）。
 *
 * 返回 `null` 的两种情况都**不是异常**，而是「这条通道在当前环境不存在」：
 * ① 非 h5（形态 A 下由小程序原生页承接）；② 动态加载失败（离线 / 被拦截）⇒ 调用方给
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

/**
 * LPAPI 回执 → 失败即抛分类错误（**唯一判定处**）。
 *
 * 🔴 判定只看 `statusCode`（文件头第 1 条）：`success` / `result` / `code` 这三个字段在真实包络里
 * **不存在** ⇒ 查它们等于**没有判据**。`25`（取消）与 `19`（环境不支持）各自有专属原因，
 * 因为二者的可行动出口与「打印机没连上」**完全不同**。
 */
function ensureOk(response: unknown, reason: 'connect-failed' | 'print-failed'): LpaEnvelope {
  const res = (response || {}) as LpaEnvelope
  const status = typeof res.statusCode === 'number' ? res.statusCode : LPA_STATUS.OK
  if (status !== LPA_STATUS.OK) {
    const detail =
      String(res.errMsg ?? (typeof res.resultInfo === 'string' ? res.resultInfo : '')).trim() ||
      `statusCode=${status}`
    if (status === LPA_STATUS.CANCEL) throw new LabelTransportError('user-cancelled', detail)
    if (status === LPA_STATUS.UN_SUPPORTED) throw new LabelTransportError('sdk-unavailable', detail)
    throw new LabelTransportError(reason, detail)
  }
  return res
}

/** 回执里的设备名（`requestDevice` 的 `resultInfo` = `LPA_Device[]`） */
function firstDeviceName(resultInfo: unknown): string {
  const list = Array.isArray(resultInfo) ? resultInfo : []
  const first: any = list[0]
  return String(first?.name ?? '').trim()
}

/**
 * 读机器的**自检**提示（用**厂商表**，不自造第二份）：`getPrinterInfo().printable` ≥ 20 才算异常
 * ⇒ `LPAPI.getPrintableMessage(code)` 给中文（缺纸 / 开盖 / 打印头过热…）。
 * 任何一步取不到 ⇒ 空串（**不猜、不编**）。
 */
function readPrinterWarning(api: LpapiPrinterLike, lpapi: LpapiModuleLike): string {
  try {
    const info: any = api.getPrinterInfo?.()
    if (!info || !isAbnormalPrintable(info.printable)) return ''
    const code = Number(info.printable)
    const vendor = lpapi.getPrintableMessage?.(code)
    return String(vendor || `打印机状态码 ${code}`)
  } catch {
    return ''
  }
}

/**
 * 造一个 Web Bluetooth 标签打印通道。
 *
 * @param options.lpapi 已加载的 LPAPI 模块（**注入**：测试传替身，生产传 `loadLpapi()` 的结果）
 * @param options.link  连接状态仓（默认 = 模块级单例 `printerLink`；测试注入自己的仓）
 */
export function createLpapiTransport(options: {
  lpapi: LpapiModuleLike
  model?: string
  link?: PrinterLinkStore
}): LabelTransport {
  const { lpapi } = options
  const model = options.model || LPAPI_MODEL
  const link = options.link || printerLink
  let printer: LpapiPrinterLike | null = null

  const ensurePrinter = (): LpapiPrinterLike => {
    if (printer) return printer
    const factory = lpapi.getInstance || lpapi.create
    if (!factory) throw new LabelTransportError('sdk-unavailable', 'LPAPI 模块没有 getInstance/create')
    // 🔴 **不传 `models`**：写死型号会把别的德佟机器判成「不支持的打印机设备」（文件头第 4 条）
    printer = factory.call(lpapi, { webBLE: true })
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
      const before = link.get()
      link.set({ status: 'connecting' })

      // ① 选设备（系统弹窗）—— 取消是 **resolve 回来** 的 `statusCode=25`，不是异常
      let device: LpaEnvelope
      try {
        device = ensureOk(await api.requestDevice(), 'connect-failed')
      } catch (error) {
        if (error instanceof LabelTransportError) {
          link.set(linkStateAfterFailure(error.reason, before))
        } else {
          link.set({ status: 'disconnected' })
        }
        throw toTransportError(error, 'connect-failed')
      }
      const deviceName = firstDeviceName(device.resultInfo)

      // ② 连接
      try {
        ensureOk(await api.openPrinter(), 'connect-failed')
      } catch (error) {
        link.set(linkStateAfterFailure('connect-failed', before, deviceName))
        throw toTransportError(error, 'connect-failed')
      }

      // ③ 连上了：状态 + 机器自检提示（`printable`），再送点阵
      const warning = readPrinterWarning(api, lpapi)
      link.set({ status: 'connected', deviceName, warning })
      try {
        // 1:1 送点阵：宽高就是渲染出来的像素数，不加任何缩放参数；打印参数见 `LABEL_PRINT_PARAMS`
        ensureOk(
          await api.printImageData({
            imageData: label.image,
            width: label.widthPx,
            height: label.heightPx,
            ...LABEL_PRINT_PARAMS,
            // 「第几次」取自**服务端回执**（前端不自行计数）—— 交给 SDK 打日志/纸面标注
            copies: 1,
            jobName: `inbound-label-${context.printCount}`,
          }),
          'print-failed',
        )
      } catch (error) {
        // 🔴 「打不出来」≠「没连上」：状态留 `connected`，异常交给自检提示说
        const reason = error instanceof LabelTransportError ? error.reason : 'print-failed'
        link.set(linkStateAfterFailure(reason, { status: 'connected', deviceName, warning }, deviceName))
        if (reason === 'print-failed') {
          link.set({ status: 'connected', deviceName, warning: readPrinterWarning(api, lpapi) || warning })
        }
        throw toTransportError(error, 'print-failed')
      }
    },
  }
}
