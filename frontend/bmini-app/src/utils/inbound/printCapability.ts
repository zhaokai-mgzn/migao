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

/**
 * 逐条可行动文案（**唯一生成处**）。
 *
 * 🔴 要求：说清「为什么」+「现在能做什么」。空值 / 两两相同 / 少于 10 字 ⇒ 守卫判红。
 */
export const PRINT_FAILURE_HINTS: Record<PrintFailureReason, string> = {
  'not-h5':
    '小程序端暂不支持打印标签（用户 2026-09-26 裁定：小程序链路搁置）。请用安卓手机或电脑的 Chrome 打开本页再打印；标签仍可在电脑端补打。',
  'insecure-context':
    '当前页面不是 HTTPS 安全上下文，浏览器禁止用蓝牙。请把地址栏的 http:// 换成 https:// 重新打开本站再打印（企业内网的 http 地址一律打不了）。',
  'no-bluetooth-api':
    '这个浏览器没有提供蓝牙接口（Web Bluetooth）。请换 Android 版 Chrome 或桌面版 Chrome / Edge 打开；iPhone 上任何浏览器都不行。',
  // 2026-09-29 新增：安卓微信内置浏览器（X5）同样**没有**蓝牙接口，但它的可行动出口与
  // 「换一个浏览器」不同 —— 人就在微信里，要教的是**怎么离开微信**（右上角 ⋯ → 在浏览器打开）。
  'wechat-webview':
    '微信里打开的网页没有蓝牙接口，打不了标签（含群里/公众号里点开的链接）。请点右上角「⋯」→「在浏览器打开」改用系统浏览器（安卓手机有这一项）；或在电脑端补打。',
  'ios-unsupported':
    'iPhone / iPad 上的浏览器（含 Safari）不支持本打印通道 —— 这是 Apple 未实现 Web Bluetooth，不是本页的故障。请改用安卓手机打印，或在电脑端补打。',
  'sdk-unavailable':
    '打印组件没加载起来（离线或被网络拦截）。请保持联网后刷新页面重试；已生成的标签不会丢，可稍后重打。',
  // ⚠️ 这一条**不许**对"记没记打印次数"下结论：取消发生在**留痕之后**（顺序见 `./labelPrint`），
  //    所以"这次记了没有"取决于 `result.printRecorded`，由 `printFailureText` 统一补一句。
  //    历史缺陷（issue #5052 验收 D6）：这里曾写「重打不会重复计数」——与实现和 `print-failed` 两条都相反。
  'user-cancelled':
    '已取消选择打印机（这次没打成）。请点「选打印机」重新选择 DP235S 后重试。',
  'device-unsupported':
    '选中的设备不是标签打印机（或不是德佟 DP 系列）。请在系统弹出的设备列表里选择名字以 DP 开头的标签机。',
  'connect-failed':
    '连不上打印机：请确认打印机已开机、在 3 米内、且没被别的手机占用，然后重试。',
  'print-failed':
    '打印机已连上但这次没打出来：请检查纸仓是否装好、是否缺纸 / 卡纸，处理好后点「重打」。',
  'render-failed':
    '标签图没画出来，已中止打印（不会打出空白标签）。请重试；若反复失败请把单号报给文员在电脑端补打。',
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
  }
}

export interface PrintCapability {
  ok: boolean
  reason?: PrintFailureReason
  /** 不可用时的**可行动**文案（`ok: true` 时为空串） */
  hint: string
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
  return { ok: true, hint: '' }
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

/** 页面文案：动手前的能力说明（h5 且可用时的正向说法也固定一句，免得页面各写一份） */
export const PRINT_READY_HINT = '点「选打印机」后选择 DP235S 标签机即可打印'

/** 本页是否处在「可打印」平台（给页面做分支用；真正的判定仍是 `probePrintCapability`） */
export function isPrintPlatform(): boolean {
  return isH5()
}
