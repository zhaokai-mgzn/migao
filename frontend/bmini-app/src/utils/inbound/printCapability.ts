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
    '当前页面不是 HTTPS 安全上下文，浏览器禁止蓝牙。请用 https://app.migaozn.com/b/ 打开本页（内网 http 地址一律打不了）。',
  'no-bluetooth-api':
    '这个浏览器没有提供蓝牙接口（Web Bluetooth）。请换 Android 版 Chrome 或桌面版 Chrome / Edge 打开；iPhone 上任何浏览器都不行。',
  'ios-unsupported':
    'iPhone / iPad 上的浏览器（含 Safari）不支持本打印通道 —— 这是 Apple 未实现 Web Bluetooth，不是本页的故障。请改用安卓手机打印，或在电脑端补打。',
  'sdk-unavailable':
    '打印组件没加载起来（离线或被网络拦截）。请保持联网后刷新页面重试；已生成的标签不会丢，可稍后重打。',
  'user-cancelled':
    '已取消选择打印机。请点「选打印机」重新选择 DP30S 后重试（标签未打印，但打印次数已记一次，重打不会重复计数）。',
  'device-unsupported':
    '选中的设备不是标签打印机（或不是 DP30S 系列）。请在系统弹出的设备列表里选择名字以 DP 开头的标签机。',
  'connect-failed':
    '连不上打印机：请确认打印机已开机、在 3 米内、且没被别的手机占用，然后重试。',
  'print-failed':
    '打印机已连上但这次没打出来：请检查纸仓是否装好、是否缺纸 / 卡纸，处理好后点「重打」（重打会再记一次打印次数）。',
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
    return { ok: false, reason: 'no-bluetooth-api', hint: PRINT_FAILURE_HINTS['no-bluetooth-api'] }
  }
  return { ok: true, hint: '' }
}

/** 取某原因的文案；未知原因 ⇒ 回落到 `print-failed`（**不返回空串**：空提示 = 静默失败） */
export function printFailureHint(reason: PrintFailureReason): string {
  return PRINT_FAILURE_HINTS[reason] || PRINT_FAILURE_HINTS['print-failed']
}

/** 页面文案：动手前的能力说明（h5 且可用时的正向说法也固定一句，免得页面各写一份） */
export const PRINT_READY_HINT = '点「选打印机」后选择 DP30S 标签机即可打印'

/** 本页是否处在「可打印」平台（给页面做分支用；真正的判定仍是 `probePrintCapability`） */
export function isPrintPlatform(): boolean {
  return isH5()
}
