/**
 * 拍照入库页的**平台能力面台账**（issue #5052 P3；照 #5654 的范式：缺口必须登记 + **被真的接线**）
 *
 * 「声明了能力缺口却没接线」是本仓被点过名的形态（#5654 的 P9）：台账里写一句
 * 「iOS 打不了蓝牙」，而页面上**没有任何地方**把这句话显示给用户 ⇒ 用户看到的仍是
 * 「点了没反应」。故本文件与 `frontend/bmini-app/tests/inbound-page-platform-gaps.test.ts` 一起钉住三件事：
 *
 * ① **声明 == 实测**（双向）：射程内实际用到的 `Taro.*` 集合必须**逐值等于** `INBOUND_PAGE_TARO_APIS`
 *    —— 新增一处 Taro 调用而不同步声明 ⇒ 红；
 * ② **命中 #5650 清单的 API 必须有缺口文案，且文案被射程内文件引用**（登记而不接线 ⇒ 红）；
 * ③ **台账只许缩短且条目必须活着**：声明里已经没有的 API ⇒ 红（防台账变成自我复制的历史文档）。
 *
 * ## 本页的能力缺口（照实登记）
 *
 * | 能力 | h5（唯一上线形态） | weapp（小程序链路已搁置） |
 * |---|---|---|
 * | 拍照 | `Taro.chooseImage`（taro-h5 **有真实实现**，走 `<input type=file accept=image/*>`） | 同左 |
 * | 本机解码 | `<img>` + canvas `getImageData` + `jsQR` | 需 `Taro.createOffscreenCanvas`（**h5 里是 stub**，且本机**未实测**） |
 * | 打印 | Web Bluetooth（**Android / 桌面 Chrome**；iOS 任何浏览器都不行） | **不支持**（`not-h5` 文案；用户裁定小程序链路搁置） |
 */
import { WEAPP_DECODE_UNAVAILABLE_HINT } from './barcodeDecode'
import { PRINT_FAILURE_HINTS, type PrintFailureReason } from './printCapability'

/** 页面路由（`src/app.config.ts` 的 pages 字面量必须逐字含它 —— 守卫判据 G0） */
export const INBOUND_PAGE_ROUTE = '/pages/worker/inbound/index'

/** 页面文件（守卫射程起点） */
export const INBOUND_PAGE_FILE = 'src/pages/worker/inbound/index.tsx'

/**
 * **补打页**路由与文件（issue #5640 功能②）—— 与入库页**同族**，共用下面这一份能力台账。
 * 两个页面都要在 `app.config.ts` 登记（没登记 = 死链，G0 一并核验）。
 */
export const REPRINT_PAGE_ROUTE = '/pages/worker/reprint/index'
export const REPRINT_PAGE_FILE = 'src/pages/worker/reprint/index.tsx'

/**
 * 射程内**声明**用到的 Taro API（实测集必须与它逐值相等，多一个 / 少一个都红）。
 * 顺序无意义（守卫按排序集合比对）。
 */
export const INBOUND_PAGE_TARO_APIS: string[] = [
  'chooseImage', // 拍照/选图（h5 有真实实现，非 stub）
  'createOffscreenCanvas', // weapp 侧取像素解码（h5 = temporarilyNotSupport 的 stub ⇒ 见下面的缺口文案）
  'navigateTo', // 未登录工人 ⇒ 跳工人登录页
  'showModal', // 过账前二次确认（复用 utils/adminConfirm）
  'uploadFile', // 照片上传（multipart；h5 有真实 XHR 实现）
]

/**
 * **缺口文案台账**：键 = Taro API 名，值 = 该 API 在**用不了的平台**上用户看到什么。
 *
 * 本轮只有一条：`createOffscreenCanvas` 在 h5 里是 `temporarilyNotSupport(...)` 的 stub
 * （#5650 的清单 A）。而 h5 恰好**不需要**它（h5 走 `<img>` + canvas）⇒ 文案要说清
 * 「h5 用户不受影响；小程序端解不了码时会明说并回落到服务端识别」。
 *
 * 🔴 该文案必须被**射程内文件真的引用**（守卫判据 G2）—— 只写在这里不算数。
 */
export const INBOUND_PAGE_PLATFORM_GAP_HINTS: Record<string, string> = {
  createOffscreenCanvas: `${WEAPP_DECODE_UNAVAILABLE_HINT}（h5 不受影响：h5 用 <img> + canvas 取像素解码）`,
}

/** 修图/选图失败时给工人的话（页面直接渲染它，不在页面里另写一句） */
export const INBOUND_PHOTO_FAILED_HINT = '没能拿到照片（可能没授权相册/相机权限），请重试或换用手机浏览器打开。'

/** 未登录工人身份时的引导（不静默跳走：页面明说为什么） */
export const INBOUND_WORKER_LOGIN_REQUIRED =
  '请先用工号 + PIN 登录工人身份，再拍照入库（商家账号不能走这条路径）。'

/** 工人登录页路由（`app.config.ts` 已登记；守卫 G0 一并核验） */
export const WORKER_LOGIN_ROUTE = '/pages/worker/login/index'

/** 补打页未登录时的引导（与入库页同一口径，但说清本页是"补打"） */
export const REPRINT_WORKER_LOGIN_REQUIRED =
  '请先用工号 + PIN 登录工人身份，再拍照补打标签（商家账号不能走这条路径）。'

/**
 * 守卫射程：**工人标签面**（入库页 + 补打页）+ 它们依赖的入库模块
 * （服务 / 门禁 / 解码 / 打印 / 共用件 / 确认框）。
 *
 * 🔴 两个页面**共用一份**声明集：新增一处 `Taro.*` 调用而不同步声明 ⇒ 红（判据 G1）。
 * 「同族页面各写一套台账」本身就是分叉的开始 ⇒ 台账只有这一份。
 */
export const INBOUND_PAGE_SCOPE_FILES: string[] = [
  INBOUND_PAGE_FILE,
  REPRINT_PAGE_FILE,
  'src/utils/inbound/codeSpace.ts',
  'src/utils/inbound/reprintFlow.ts',
  'src/utils/inbound/labelPageKit.ts',
  'src/services/workerInboundService.ts',
  'src/utils/inbound/truth.ts',
  'src/utils/inbound/shortCode.ts',
  'src/utils/inbound/labelLayout.ts',
  'src/utils/inbound/labelCanvas.ts',
  'src/utils/inbound/barcodeDecode.ts',
  'src/utils/inbound/recognizeFlow.ts',
  'src/utils/inbound/recognizeGate.ts',
  'src/utils/inbound/printCapability.ts',
  'src/utils/inbound/labelPrint.ts',
  'src/utils/inbound/lpapiTransport.ts',
  'src/utils/adminConfirm.ts',
]

/**
 * 本页**必须显式呈现**的打印能力缺口（键 = `PrintFailureReason`，值 = 引用它的射程文件）。
 *
 * 判据 G5：每一条都必须在射程内**被引用**（页面或它调用的模块真的会把它显示出来），
 * 且文案两两不同（合并成一句通用文案 ⇒ 红）。
 */
export const INBOUND_PRINT_GAP_WIRING: { reason: PrintFailureReason; wiredBy: string }[] = [
  { reason: 'not-h5', wiredBy: 'src/utils/inbound/printCapability.ts' },
  { reason: 'insecure-context', wiredBy: 'src/utils/inbound/printCapability.ts' },
  { reason: 'no-bluetooth-api', wiredBy: 'src/utils/inbound/printCapability.ts' },
  { reason: 'ios-unsupported', wiredBy: 'src/utils/inbound/printCapability.ts' },
  { reason: 'sdk-unavailable', wiredBy: 'src/utils/inbound/lpapiTransport.ts' },
  { reason: 'user-cancelled', wiredBy: 'src/utils/inbound/labelPrint.ts' },
  { reason: 'device-unsupported', wiredBy: 'src/utils/inbound/labelPrint.ts' },
  { reason: 'connect-failed', wiredBy: 'src/utils/inbound/labelPrint.ts' },
  { reason: 'print-failed', wiredBy: 'src/utils/inbound/labelPrint.ts' },
  { reason: 'render-failed', wiredBy: 'src/utils/inbound/labelPrint.ts' },
]

/** 供页面/判据读取（不复制文案，只转发键集） */
export function printGapReasons(): PrintFailureReason[] {
  return Object.keys(PRINT_FAILURE_HINTS) as PrintFailureReason[]
}
