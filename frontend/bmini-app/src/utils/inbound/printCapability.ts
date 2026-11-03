/**
 * 打印通道的**能力探测 + 失败原因分类 + 逐条可行动文案**（issue #5052 P3/P4；设计 §8.3 / N1）
 *
 * 用户已裁定（2026-09-26）：**标签打印只在 Android / 桌面 Chrome 可用**（Web Bluetooth），
 * iOS Safari 打不了 ⇒ h5 上必须在**动手前**就把这个能力缺口说清楚，**不是打完才失败**。
 *
 * ## 为什么每个失败原因都要**各自**的文案（验收判据 9）
 *
 * 「打印失败」这一句话对工人**不可行动**：他不知道是换浏览器、换手机、开蓝牙、还是叫文员。
 * 五种以上失败形态（非 h5 / 非安全上下文 / 浏览器没有 Web Bluetooth / iOS Safari / 用户拒绝授权 /
 * 建连失败 / 机型不支持 / SDK 未就绪）⇒ **每一种都要说清「现在能做什么」**。
 * 合并成一条通用文案 ⇒ 守卫判红（`tests/inbound-print-channel.test.ts` 的 D3：文案两两不同 + 非空）。
 *
 * ## 界线（照实登记，不粉饰）
 *
 * 本文件只做**判定与文案**；真正连蓝牙在 `./lpapiTransport`（真机未验证，见该文件与 PR 正文的
 * 「未完成」段）。**没有真机**也能把判据钉死：探测与文案是纯函数，传输层是可注入接口。
 */
import { isH5 } from '../platform'

/** 打印失败 / 不可用的原因（**分类即文案**：每一类一个去处） */
export type PrintFailureReason =
  | 'not-h5'
  | 'insecure-context'
  | 'no-bluetooth-api'
  | 'wechat-webview'
  | 'ios-unsupported'
  | 'sdk-unavailable'
  | 'user-cancelled'
  | 'device-unsupported'
  | 'connect-failed'
  | 'print-failed'
  | 'render-failed'
  // 手持标签机（观星台 Android 终端）的两条：**能力在原生侧**，页面只能转述原生上报的事实。
  // 分开两条是因为出口的"为什么"不同（一个确知没有打印机，一个**判不了**）—— 见 `terminalPrintState`。
  | 'terminal-printer-unavailable'
  | 'terminal-print-unknown'

/**
 * 逐条可行动文案（**唯一生成处**）。
 *
 * 🔴 要求：说清「为什么」+「现在能做什么」。空值 / 两两相同 / 少于 10 字 ⇒ 守卫判红。
 */
export const PRINT_FAILURE_HINTS: Record<PrintFailureReason, string> = {
  'not-h5':
    '小程序端暂不支持打印标签。请用安卓手机或电脑的 Chrome 打开本页再打印；标签仍可在电脑端补打。',
  'insecure-context':
    '当前网页地址不是 https://，浏览器不让连蓝牙打印机。请把地址栏里的 http:// 改成 https:// 后重新打开本站打印（公司内网的 http 地址都打不了）。',
  'no-bluetooth-api':
    '这个浏览器不支持蓝牙打印。请换安卓 Chrome 或电脑版 Chrome / Edge 打开；iPhone 上任何浏览器都不行。',
  // 2026-09-29 新增：安卓微信内置浏览器（X5）同样**没有**蓝牙接口，但它的可行动出口与
  // 「换一个浏览器」不同 —— 人就在微信里，要教的是**怎么离开微信**（右上角 ⋯ → 在浏览器打开）。
  'wechat-webview':
    '微信里打开的网页不能连蓝牙打印（群里 / 公众号里点开的链接也一样）。请点右上角「⋯」→「在浏览器打开」；或到电脑端补打。',
  'ios-unsupported':
    'iPhone / iPad 上的浏览器（含 Safari）不支持蓝牙打印（苹果没有开放这个功能，不是本页的故障）。请改用安卓手机打印，或在电脑端补打。',
  'sdk-unavailable':
    '打印组件没加载起来（离线或被网络拦截）。请保持联网后刷新页面重试；已生成的标签不会丢，可稍后重打。',
  // ⚠️ 这一条**不许**对"记没记打印次数"下结论：取消发生在**留痕之后**（顺序见 `./labelPrint`），
  //    所以"这次记了没有"取决于 `result.printRecorded`，由 `printFailureText` 统一补一句。
  //    历史缺陷（issue #5052 验收 D6）：这里曾写「重打不会重复计数」——与实现和 `print-failed` 两条都相反。
  'user-cancelled':
    '已取消选择打印机（这次没打成）。点「打印标签」重新选择即可重试。',
  'device-unsupported':
    '选中的设备不是标签打印机。请重新点「打印标签」，在系统弹出的设备列表里选择标签打印机。',
  'connect-failed':
    '连不上打印机：请确认打印机已开机、在 3 米内、且没被别的手机占用，然后重试。',
  'print-failed':
    '打印机已连上但这次没打出来：请检查纸仓是否装好、是否缺纸 / 卡纸，处理好后点「重打」。',
  'render-failed':
    '标签图没画出来，已中止打印（不会打出空白标签）。请重试；若反复失败请把单号报给文员在电脑端补打。',
  // 🔴 下面两条治的是「**说能打却不能打**」（issue #8310 真机：`PrinterLink.mode()` = -1，页面却写
  //    「由本机打印机直接出纸」）。两句都必须**只陈述事实 + 给出口**（§31 P4）：不责备、不催促、
  //    不猜机器的状态。⚠️ 两句**不许**合并成一句通用文案（守卫 D5 判两两不同）。
  'terminal-printer-unavailable':
    '本机没有检测到标签打印机，标签在这里打不出来。请到电脑端补打；需要本机出纸请联系管理员开启打印服务。',
  'terminal-print-unknown':
    '还没确认这台手持机能不能打标签，所以这里先不提供打印。请到电脑端补打；需要本机出纸请联系管理员。',
}

/** 探测用的环境快照（**注入式**：浏览器传真实值，测试传构造值） */
export interface PrintEnv {
  /** 编译目标（`process.env.TARO_ENV`） */
  platform: string
  /** `window.isSecureContext`（缺失 ⇒ undefined，按**不安全**处理 = fail-closed） */
  secureContext?: boolean
  /** 是否有 `navigator.bluetooth` */
  hasBluetoothApi: boolean
  /** `navigator.userAgent` */
  userAgent?: string
  /** 是否运行在 iOS/iPadOS（含 iPad 桌面 UA 的 `Macintosh` + 触摸点特例由调用方判） */
  isIos?: boolean
  /** 是否运行在微信内置浏览器（UA 含 `MicroMessenger`）—— 出口是「在浏览器打开」，不是「换浏览器」 */
  isWechat?: boolean
  /** 是否运行在观星台手持终端（WebView + `window.chrome.webview` 桥）—— 打印走商米内置打印机 */
  terminalBridge?: boolean
  /**
   * 终端原生上报的**打印服务模式**（与终端仓 `PrinterLink.mode()` 同源；issue #8310）。
   *
   * 缺省 = **原生没送这个值** ⇒ 能力**判不了**（`unknown`），**不许**当能打。
   * 值域口径见 `terminalPrintState()`；本仓只认符号，不解释具体正整数。
   */
  printerMode?: number
}

/** 浏览器真实环境快照（**只在 h5 分支被调用**） */
export function readPrintEnv(): PrintEnv {
  const nav: any = typeof navigator === 'undefined' ? undefined : navigator
  const ua = String(nav?.userAgent ?? '')
  return {
    platform: process.env.TARO_ENV || 'unknown',
    secureContext: typeof window === 'undefined' ? undefined : (window as any).isSecureContext,
    hasBluetoothApi: typeof nav?.bluetooth !== 'undefined' && nav?.bluetooth !== null,
    userAgent: ua,
    isIos: /iPhone|iPad|iPod/i.test(ua),
    isWechat: /MicroMessenger/i.test(ua),
    terminalBridge: typeof window !== 'undefined' && !!(window as any).chrome?.webview,
    printerMode: readPrinterMode(),
  }
}

/**
 * 读终端原生注入的**运行期配置** `window.__CFG__.printerMode`（issue #8310）。
 *
 * 🔴 这是**仓外事实**：`__CFG__` 由终端仓（`zhaokai-mgzn/migao-terminal`）注入，不来自本仓。
 * 截至本条落地（终端壳 1.0.19，2026-11-01 真机），原生**只**注入了 `window.chrome.webview` 与
 * `window.migaoTerminal`，`__CFG__` 里**还没有** `printerMode` —— 所以本函数现在读到的永远是
 * `undefined`，能力判定落 `unknown`（**判不了**，页面不再说能打）。原生补送之后**本文件不用再改**：
 * 非数字 / NaN / Infinity 一律按「读不到」处理（fail-closed，**不猜**）。
 */
function readPrinterMode(): number | undefined {
  if (typeof window === 'undefined') return undefined
  const raw = (window as any).__CFG__?.printerMode
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : undefined
}

/** 终端打印能力的**三态**（`unknown` 必须与 `unavailable` 分开：前者是「不知道」，后者是「确知没有」）。 */
export type TerminalPrintState = 'available' | 'unavailable' | 'unknown'

/**
 * 终端打印能力的三态判定（issue #8310 的唯一判定点）。
 *
 * 🔴 病根：旧实现只看「**壳在不在**」（`chrome.webview`）就判 `ok: true` —— 桥证明的是**壳**，
 * 不是**打印机**。2026-11-01 真机（商米 V2s / 终端壳 1.0.19）：`PrinterLink.mode()` = **-1**，
 * 设备上只有 `com.sunmi.printer.firmware`，没有 `com.sunmi.printer` 服务也没有打印节点 ——
 * 这台机器打不出来，页面却写「由本机打印机直接出纸」（工人先拍照、先过账，过账不可逆）。
 *
 * | 入参 | 判定 | 为什么 |
 * |---|---|---|
 * | `> 0` | `available` | 原生报的是**正向**模式（正整数含义由终端仓定义，本仓只认符号） |
 * | `< 0` | `unavailable` | 实测 **-1** = 没有商米打印服务 |
 * | `0` / 缺省 / 非有限数字 | `unknown` | **不猜**：`0` 的语义仓外未定义、读不到就更不该说能打 |
 *
 * ⚠️ 方向是**单向**的：只有正向读数才允许说能打；判不了与确知没有**分开**说（出口都是电脑端补打）。
 */
export function terminalPrintState(printerMode?: number): TerminalPrintState {
  if (typeof printerMode !== 'number' || !Number.isFinite(printerMode)) return 'unknown'
  if (printerMode < 0) return 'unavailable'
  if (printerMode > 0) return 'available'
  return 'unknown'
}

export interface PrintCapability {
  ok: boolean
  reason?: PrintFailureReason
  /** 不可用时的**可行动**文案（`ok: true` 时为空串） */
  hint: string
  /** **可用**时的正向说法（`ok: false` 时缺省）。两端流程不同：h5 有系统弹窗、小程序是自己搜 */
  readyHint?: string
}

/**
 * 能力探测（**动手前**调用；页面据此在打印按钮旁先给出说明）。
 *
 * 判定顺序 = 「越早死越省事」：非 h5 → 非安全上下文 → iOS → 无 Web Bluetooth。
 * ⚠️ iOS 排在「无 API」**之前**：iOS 上 `navigator.bluetooth` 本来就不存在，
 * 若先判无 API，用户只会看到「换浏览器」—— 而 iPhone 上**换任何浏览器都不行**，
 * 那句话会把人引向一个走不通的动作（这正是本单要防的「一句通用文案」）。
 */
export function probePrintCapability(env: PrintEnv = readPrintEnv()): PrintCapability {
  // 🔴 小程序（weapp）**排在最前**：它有原生 BLE（`wx.*BLE`），既不需要 Web Bluetooth，
  //    也不需要 https，iOS 也照样能打（小程序 BLE 在 iOS 是开放的）—— 拿 h5 那三条判据去卡它，
  //    会把唯一能在「微信里不跳出去」打标签的载体判成不可用（issue #7802）。
  if (env.platform === 'weapp') {
    return { ok: true, hint: '', readyHint: PRINT_READY_HINT_WX }
  }
  // 观星台手持标签机：页面跑在 Android WebView 里，打印走终端的商米内置打印机桥，
  // 不依赖 Web Bluetooth（WebView 也没有这个接口）。
  // 🔴 但「桥在」只证明**壳在**，不证明**打印机在**（issue #8310）⇒ 能不能打由原生上报的
  //    `printerMode` 说话：正向才算能打；负向 = 确知打不了；读不到 = **判不了**（不许说能打）。
  if (env.terminalBridge) {
    const state = terminalPrintState(env.printerMode)
    if (state === 'available') {
      return { ok: true, hint: '', readyHint: PRINT_READY_HINT_TERMINAL }
    }
    const reason: PrintFailureReason =
      state === 'unavailable' ? 'terminal-printer-unavailable' : 'terminal-print-unknown'
    return { ok: false, reason, hint: PRINT_FAILURE_HINTS[reason] }
  }
  if (env.platform !== 'h5') {
    return { ok: false, reason: 'not-h5', hint: PRINT_FAILURE_HINTS['not-h5'] }
  }
  if (env.secureContext !== true) {
    return { ok: false, reason: 'insecure-context', hint: PRINT_FAILURE_HINTS['insecure-context'] }
  }
  if (env.isIos) {
    return { ok: false, reason: 'ios-unsupported', hint: PRINT_FAILURE_HINTS['ios-unsupported'] }
  }
  if (!env.hasBluetoothApi) {
    // 微信内置浏览器（含小程序里打开的网页）没有这个接口 ⇒ 出口是「在浏览器打开」，
    // **不是**「换一个浏览器」（人在微信里，"换浏览器"不是他能执行的动作）
    const reason: PrintFailureReason = env.isWechat ? 'wechat-webview' : 'no-bluetooth-api'
    return { ok: false, reason, hint: PRINT_FAILURE_HINTS[reason] }
  }
  return { ok: true, hint: '', readyHint: PRINT_READY_HINT }
}

/** 取某原因的文案；未知原因 ⇒ 回落到 `print-failed`（**不返回空串**：空提示 = 静默失败） */
export function printFailureHint(reason: PrintFailureReason): string {
  return PRINT_FAILURE_HINTS[reason] || PRINT_FAILURE_HINTS['print-failed']
}

/**
 * 「这次已经记过打印次数了」的**唯一说法**（issue #5052 验收 D6 修复）。
 *
 * 为什么是一句话常量而不是散在各条文案里：`PRINT_FAILURE_HINTS` 是**静态**文案表，
 * 而"记没记"是**运行期**事实（`InboundPrintResult.printRecorded`）——
 * 静态文案**没有资格**对运行期事实下结论。历史缺陷正是如此：`user-cancelled` 写了
 * 「重打不会重复计数」，而同表 `print-failed` 写「重打会再记一次」，两句**互相矛盾**，
 * 且实现（取消发生在 `recordPrint()` **之后**）站在后者一边 ⇒ 工人被误导。
 */
export const PRINT_COUNT_REPRINT_NOTICE = '本次已记一次打印次数；重打会再记一次。'

/**
 * 给工人看的**失败文案**：静态 hint + 运行期事实（是否已留痕）。
 *
 * 🔴 页面**只能**用本函数拼失败文案（不许直接上屏 `result.hint`）——
 * 否则 `printRecorded` 这个结构化事实就没有读者，页面对"记没记"只能靠猜。
 * 判据 = `tests/inbound-print-channel.test.ts` 的「D9 两个出标签的页面必须消费 `printRecorded`」
 * （射程 = 两个出标签的页面；去掉任何一页的引用 ⇒ 该判据点名判红）。
 */
export function printFailureText(hint: string, printRecorded: boolean): string {
  return printRecorded ? `${hint}${PRINT_COUNT_REPRINT_NOTICE}` : hint
}

/**
 * 页面文案：动手前的能力说明（可用时的正向说法也固定一句，免得页面各写一份）。
 *
 * 🔴 历史缺陷（issue #7802 修）：这里曾写「点『**选打印机**』」，而页面上**没有**这个按钮
 * —— 真实按钮叫「打印标签」（`data-testid=inbound-print`）⇒ 工人照着提示找不到入口。
 * 文案里的按钮名必须与页面**逐字**相同（判据见 `tests/inbound-print-weapp.test.ts` 的 W1）。
 */
export const PRINT_READY_HINT = '点「打印标签」，在系统弹出的设备列表里选择标签打印机。'

/**
 * 小程序侧的正向说法 —— 与 h5 **不同**：小程序**没有系统设备弹窗**，SDK 自己搜自己连，
 * 工人唯一要做的是把机器开机并放在近处（多台机器的选择见 `lpapiTransport` 的边界登记）。
 */
export const PRINT_READY_HINT_WX =
  '点「打印标签」即可：小程序会自己搜索附近的标签机（请先把打印机开机、放在 1~3 米内）'

/**
 * 手持标签机（观星台 Android 终端）的正向说法：打印走机身内置打印机，不需要选设备。
 *
 * 🔴 **只有** `terminalPrintState(printerMode) === 'available'` 时**才允许**说这句话
 * （issue #8310：这句话曾在打不出来的机器上照旧出现）。页面**不许**自己写死它 ——
 * 只能用 `capability.readyHint`（判据 = `tests/inbound-print-capability-terminal.test.ts` 的 T4）。
 */
export const PRINT_READY_HINT_TERMINAL = '点「打印标签」，由本机打印机直接出纸。'

/** 本页是否处在「可打印」平台（给页面做分支用；真正的判定仍是 `probePrintCapability`） */
export function isPrintPlatform(): boolean {
  return isH5()
}
