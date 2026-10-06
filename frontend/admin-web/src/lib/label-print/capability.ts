/**
 * 标签打印的**通道能力探测 + 逐条可行动文案**（issue #6439）。
 *
 * ## 为什么是「通道」而不是「打印机型号」
 *
 * 用户 2026-10-06 逐字裁定：「**不要做成打印机定制功能**，因为可能企业内部用的是其他类型的打印机，
 * 只要我们功能支持能连接上不同类型的打印机即可」「需要考虑用户有通过 window 电脑安装打印机驱动
 * 或者蓝牙连接，或者 usb 连接各种情况」。
 *
 * ⇒ 现实里只有两条通道，**边界必须说清**（照实登记，不粉饰）：
 *
 * | 通道 | 覆盖谁 | 落点 |
 * |---|---|---|
 * | **系统打印** `window.print()` | **任何**装了驱动的打印机：Windows 驱动 / USB / 网络 / 已配对蓝牙 | `frontend/admin-web/src/lib/print-doc.ts`（既有，本单不改） |
 * | **浏览器直连** Web Bluetooth / WebHID | **只有带 SDK 协议的机型** —— Web Bluetooth 是**点对点协议、没有通用标准** | 本目录（本单新建） |
 *
 * 🔴 所以「支持任意打印机」的**唯一通用路径是系统打印**；直连是「免驱动」的补充，不是替代。
 * 这正是 {@link SYSTEM_PRINT_HINT} 存在的原因，也是**每一条失败文案都必须把它指出来**的原因
 * （否则用户会以为「直连不可用 = 打不了」）。
 *
 * ## 为什么每一类失败都要各自的文案
 *
 * 「打印失败」这四个字对用户不可行动：他不知道是该换浏览器、开蓝牙、插 USB、还是去装驱动。
 * 合并成一条通用文案 ⇒ 守卫判红（`tests/unit/lib/label-print/capability.test.ts`）。
 */
import type { PrintTarget } from '../print-doc'

/** 直连通道不可用 / 失败的原因（**分类即文案**：每一类一个去处） */
export type DirectPrintFailureReason =
  | 'insecure-context'
  | 'no-web-bluetooth'
  | 'ios-unsupported'
  | 'wechat-webview'
  | 'sdk-unavailable'
  | 'not-connected'
  | 'user-cancelled'
  | 'device-unsupported'
  | 'connect-failed'
  | 'print-failed'
  | 'render-failed'

/**
 * 系统打印那条路的**说明**（唯一生成处）。
 * 🔴 它不是「失败文案」——它是**兜底路径的宣示**：不接直连的打印机照样要能打。
 */
export const SYSTEM_PRINT_HINT =
  '「打印任务卡」走的是这台电脑的系统打印：只要装了打印机驱动（USB / 网络 / 蓝牙配对成系统打印机都算），' +
  '任何品牌的标签机都能打 —— 这条路不挑机型。'

/**
 * 直连通道可用时的正向说法（页面各写一份会漂移）。
 *
 * 🔴 **本模块的文案一律不带 markdown 强调标记**（`**x**`）—— 是**有意**的，别"顺手"加回去：
 * 本文件是**数据模块**（没有 JSX），带标记就必须同时登记进
 * `copy-no-markdown-emphasis.test.ts` 的 `REGISTERED_MARKER_FILES` **并**给渲染点接
 * `@/lib/inline-markdown`；而这几条都是**一行可行动提示**，强调不承载任何层级信息，
 * 为此拉一条渲染依赖是净亏。守卫会自动把「加了标记却没接线」判红（判据 ③ 未登记即红）。
 */
export const DIRECT_PRINT_READY_HINT =
  '点「直连打印机打印」后选一台标签机即可免驱动打印：不用装驱动，但只支持带网页蓝牙协议的机型。'

/**
 * 逐条可行动文案（**唯一生成处**）。
 *
 * 🔴 每条都要求：说清「为什么」+「现在能做什么」，**且必须指回系统打印兜底路径**。
 * 空值 / 两两相同 / 少于 12 字 / 不含动作词 ⇒ 守卫判红。
 */
export const DIRECT_PRINT_HINTS: Record<DirectPrintFailureReason, string> = {
  'insecure-context':
    '当前页面不是安全上下文（https 或 127.0.0.1），浏览器禁止网页连蓝牙。请改用 https 打开本系统，或直接用「打印任务卡」走系统打印。',
  'no-web-bluetooth':
    '这个浏览器没有提供网页蓝牙接口。请换 Chrome 或 Edge 打开，或直接用「打印任务卡」走系统打印（装了驱动的打印机都能用）。',
  'ios-unsupported':
    'iPhone / iPad 上的浏览器不支持网页直连打印机（Apple 未实现 Web Bluetooth，不是本页故障）。请换电脑用 Chrome 打开，或直接用「打印任务卡」走系统打印。',
  'wechat-webview':
    '微信内置浏览器没有蓝牙接口。请点右上角「⋯」→「在浏览器打开」换系统浏览器，或直接用「打印任务卡」走系统打印。',
  'sdk-unavailable':
    '打印组件没加载起来（离线或被网络拦截）。请保持联网后刷新页面重试，或直接用「打印任务卡」走系统打印。',
  'not-connected':
    '还没有选择打印机。请点「直连打印机打印」在弹框里选一台标签机，或直接用「打印任务卡」走系统打印。',
  'user-cancelled':
    '已取消选择打印机（这次没打成）。请重新点「直连打印机打印」选一台，或直接用「打印任务卡」走系统打印。',
  'device-unsupported':
    '选中的设备不是本通道支持的标签机。请在设备列表里选标签打印机，或直接用「打印任务卡」走系统打印。',
  'connect-failed':
    '连不上打印机：请确认打印机已开机、在 3 米内、且没被别的手机占用，然后重试；或直接用「打印任务卡」走系统打印。',
  'print-failed':
    '打印机已连上但这次没打出来：请检查纸仓是否装好、是否缺纸卡纸，处理好后重试；或直接用「打印任务卡」走系统打印。',
  'render-failed':
    '标签图没画出来，已中止打印（不会打出空白标签）。请重试；或直接用「打印任务卡」走系统打印。',
}

/** 探测用的环境快照（**注入式**：浏览器传真实值，测试传构造值） */
export interface LabelPrintEnv {
  /** `window.isSecureContext`（缺失 ⇒ undefined，按**不安全**处理 = fail-closed） */
  secureContext?: boolean
  /** 是否有 `navigator.bluetooth`（Web Bluetooth） */
  hasBluetoothApi: boolean
  /** `navigator.userAgent` */
  userAgent?: string
  /** 是否运行在 iOS / iPadOS */
  isIos?: boolean
  /** 是否运行在微信内置浏览器（出口是「在浏览器打开」，不是「换浏览器」） */
  isWechat?: boolean
}

/** 浏览器真实环境快照（只在客户端被调用） */
export function readLabelPrintEnv(): LabelPrintEnv {
  const nav: Navigator | undefined = typeof navigator === 'undefined' ? undefined : navigator
  const ua = String(nav?.userAgent ?? '')
  return {
    secureContext: typeof window === 'undefined' ? undefined : window.isSecureContext,
    hasBluetoothApi: typeof (nav as { bluetooth?: unknown } | undefined)?.bluetooth !== 'undefined',
    userAgent: ua,
    isIos: /iPhone|iPad|iPod/i.test(ua),
    isWechat: /MicroMessenger/i.test(ua),
  }
}

export interface DirectPrintCapability {
  ok: boolean
  reason?: DirectPrintFailureReason
  /** 不可用时的**可行动**文案（`ok: true` 时为空串） */
  hint: string
}

/**
 * 直连通道能力探测（**动手前**调用；页面据此在按钮旁先给出说明）。
 *
 * 判定顺序 = 「越早死越省事」：非安全上下文 → iOS → 无 Web Bluetooth。
 * ⚠️ iOS 排在「无 API」**之前**：iOS 上 `navigator.bluetooth` 本来就不存在，
 * 先判无 API 会把人引向「换浏览器」这个**在 iPhone 上走不通**的动作。
 */
export function probeDirectPrint(env: LabelPrintEnv = readLabelPrintEnv()): DirectPrintCapability {
  if (env.secureContext !== true) {
    return { ok: false, reason: 'insecure-context', hint: DIRECT_PRINT_HINTS['insecure-context'] }
  }
  if (env.isIos) {
    return { ok: false, reason: 'ios-unsupported', hint: DIRECT_PRINT_HINTS['ios-unsupported'] }
  }
  if (!env.hasBluetoothApi) {
    const reason: DirectPrintFailureReason = env.isWechat ? 'wechat-webview' : 'no-web-bluetooth'
    return { ok: false, reason, hint: DIRECT_PRINT_HINTS[reason] }
  }
  return { ok: true, hint: '' }
}

/** 取某原因的文案；未知原因 ⇒ 回落到连接失败文案（**不返回空串**：空提示 = 静默失败） */
export function directPrintHint(reason: DirectPrintFailureReason): string {
  return DIRECT_PRINT_HINTS[reason] || DIRECT_PRINT_HINTS['connect-failed']
}

/**
 * 本次出口走的哪条通道（给文案用）。
 *
 * ⚠️ 只是**说明性的分类**，不是权限或门禁：两条通道**并存**，
 * 系统打印那条永远可用（`PRINT_TARGET_SPECS.labels` ⇒ `usePrintDoc`）。
 */
export const LABEL_PRINT_CHANNEL_IDS = ['system', 'direct'] as const
export type LabelPrintChannelId = (typeof LABEL_PRINT_CHANNEL_IDS)[number]

/** 直连通道负责的打印目标（本单只接洗水码；将来别的单据复用同一层时在这里登记） */
export const DIRECT_PRINT_TARGETS: readonly PrintTarget[] = ['labels']
