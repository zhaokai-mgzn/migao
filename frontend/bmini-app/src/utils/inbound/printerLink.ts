/**
 * 打印机的**连接状态**（issue #5052 CP-1；2026-09-29 用户要求「加个提示用户是否已连接打印机」）
 *
 * ## 这一层是**运行期事实**，与能力探测**是两件事**（不许互相冒充）
 *
 * | 面 | 回答的问题 | 真值来源 | 落在哪 |
 * |---|---|---|---|
 * | 能力探测 | 「**这台手机**能不能打标签」 | UA / `isSecureContext` / `navigator.bluetooth` | `./printCapability` |
 * | 连接状态 | 「**此刻**有没有连上那台打印机」 | 传输层**每一次真实交互**的读数 | 本文件 |
 *
 * 🔴 能力 OK 但机器没开机（= 没连上）是现场最常见的形态。把「能打」显示成「已连接」，
 * 工人就会以为机器就绪 —— 那正是本仓被点过名的「静默把不确定说成确定」。
 *
 * ## 边界（照实登记，不粉饰）：浏览器侧**做不到**持续真值
 *
 * Web Bluetooth 的权限模型是「**用户手势**才能 `requestDevice()`」，而「已配对设备列表」
 * （`navigator.bluetooth.getDevices()`）在 Chrome 里**默认不开放**（`lpapi-ble` 自己的类型注释
 * 也这么写）⇒ 页面既**不能**在加载时静默重连，也拿不到 GATT 连接对象去挂
 * `gattserverdisconnected`。故本状态的口径**只**是：
 *
 * **「我们最后一次与打印机真实交互（连接 / 打印）的结果」** —— 所以 `connected` 的文案里
 * 明写「以最近一次打印时为准」，**不谎报"持续在线"**（谎报的代价 = 工人拿着"已连接"去贴标签，
 * 而机器其实早就自动关机了）。
 *
 * 小程序侧（形态 A：原生页）有 `wx.onBLEConnectionStateChange` 真事件 ⇒ 那一侧能做到实时，
 * 但**共用本状态面**（届时由 weapp 的传输层写同一个 store，页面不用改）。
 */
import { LabelTransportError } from './labelPrint'

/** 四态：**`unselected` 与 `disconnected` 必须分开**（"还没选过"不是故障，"没连上"才是） */
export type PrinterLinkStatus = 'unselected' | 'connecting' | 'connected' | 'disconnected'

export interface PrinterLinkState {
  status: PrinterLinkStatus
  /** 设备名（SDK 回执里的 `name`；没连上时为空） */
  deviceName?: string
  /** 打印机**自检**提示（异常状态码 ⇒ 厂商中文文案；正常态为空） */
  warning?: string
}

/** 初始态：**还没选过打印机**（不是"连接失败"） */
export const PRINTER_LINK_UNSELECTED: PrinterLinkState = { status: 'unselected' }

export interface PrinterLinkStore {
  get(): PrinterLinkState
  set(next: PrinterLinkState): void
  subscribe(listener: (state: PrinterLinkState) => void): () => void
  /** 仅供测试复位（生产代码不调用） */
  reset(): void
}

/** 造一个状态仓（可注入 ⇒ 判据能跑替身；页面用下面的模块级单例） */
export function createPrinterLinkStore(initial: PrinterLinkState = PRINTER_LINK_UNSELECTED): PrinterLinkStore {
  let state = initial
  const listeners = new Set<(state: PrinterLinkState) => void>()
  const set = (next: PrinterLinkState): void => {
    state = next
    for (const listener of listeners) listener(state)
  }
  return {
    get: () => state,
    set,
    subscribe(listener) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    reset() {
      listeners.clear()
      set(initial)
    },
  }
}

/** 一页只有一台打印机 ⇒ 模块级单例：传输层默认写它、页面默认读它（两边不用互相知道） */
export const printerLink = createPrinterLinkStore()

/**
 * 打印机**异常**状态码的分界。
 *
 * 厂商 `LPA_Printable`（`lpapi-ble` README「打印机异常状态码」节）：`0/1/2/10/11/12` 是
 * 「可打印 / 正在打印 / 马达转动 / 无任务 / 页面未收完 / 任务被取消」这类**正常或瞬时**态，
 * **≥ 20** 才是异常（电压、打印头、开盖、缺纸、碳带、标签盒…）。故只需一个阈值，**不抄整张表**。
 */
export function isAbnormalPrintable(printable: unknown): boolean {
  return typeof printable === 'number' && printable >= 20
}

/**
 * 连接状态的**唯一说法**（运行期事实只由它出口）。
 *
 * 🔴 页面**只许**用它，不许自己拼文案：四态各有各的**可行动出口**（"还没选过"要教怎么选、
 * "没连上"要教怎么排障），合成一句「打印机状态异常」对工人不可行动。
 * 判据 = `frontend/bmini-app/tests/inbound-print-channel.test.ts` 的 D10。
 */
export function printerLinkText(state: PrinterLinkState): string {
  const name = String(state.deviceName || '').trim()
  const warning = String(state.warning || '').trim()
  const warnSuffix = warning ? `；打印机提示：${warning}` : ''
  switch (state.status) {
    case 'connecting':
      return '正在连接打印机…请在系统弹窗里选择名字以 DP 开头的标签机。'
    case 'connected':
      return `打印机已连接${name ? `：${name}` : ''}${warnSuffix}（连接状态以最近一次打印时为准）`
    case 'disconnected':
      return `打印机未连上（最近一次没连通）${warnSuffix}。请确认机器已开机、在 3 米内、没被别的手机占用，再点「打印标签」重连。`
    default:
      return '还没选过打印机：点「打印标签」时系统会弹出设备列表，请选名字以 DP 开头的标签机。'
  }
}

/** 由打印失败分类推出「打印机状态」（🔴「打不出来」≠「没连上」：打印失败仍可能连着） */
export function linkStateAfterFailure(
  reason: string,
  before: PrinterLinkState,
  deviceName?: string,
): PrinterLinkState {
  if (reason === 'user-cancelled' || reason === 'sdk-unavailable') {
    // 这两条都**没有产生关于打印机的信息**（用户放弃 / SDK 没起来）⇒ 保持原读数，不冒充"断开"
    return before
  }
  if (reason === 'print-failed') {
    // 连上了但没打出来（缺纸 / 开盖 / 过热…）：状态仍是**已连接**，异常由 `warning` 说
    return { status: 'connected', deviceName, warning: before.warning }
  }
  return { status: 'disconnected', deviceName }
}

/** 把任意异常转成分类错误（已经是分类错误就原样传） */
export function toTransportError(
  error: unknown,
  reason: 'connect-failed' | 'print-failed' | 'sdk-unavailable',
): LabelTransportError {
  if (error instanceof LabelTransportError) return error
  return new LabelTransportError(reason, String((error as any)?.message ?? error ?? reason))
}
