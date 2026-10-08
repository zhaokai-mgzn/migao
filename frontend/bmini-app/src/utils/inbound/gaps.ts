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
  'getCurrentInstance', // 读**页面参数**（`router.params.code`）：h5 路由 query 与小程序深链共用这一侧
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

/**
 * **平台能力缺口台账（Taro API 之外的那一类）** —— issue #5052 实现 PR。
 *
 * `INBOUND_PAGE_PLATFORM_GAP_HINTS` 管的是「某个 `Taro.*` 在这个平台上用不了」；
 * 这里管的是「**这条路在某个平台上根本不存在**」（不是 API 缺失，是形态差异）。
 * 本轮只有一条：**URL query 深链**（`/b/?code=<短码>`，服务端 `/i/` 302 的落点）是
 * **h5 专有形态** —— 小程序没有 URL query，深链走**页面参数**（`router.params`）。
 *
 * 🔴 照本文件的既有范式：缺口**必须有登记**（这里），且**由真的调用它的文件接线**
 * （`wiredBy` 里必须真的出现 `wiredToken`）—— 「登记而不接线」在本仓被点过名
 * （#5654 的 P9：台账里写一句，而没有任何东西把它变成用户看得见的路径）。
 */
export interface WorkerSurfacePlatformGap {
  /** 缺口键（登记名，供守卫点名） */
  key: string
  /** 给不出这条路的平台 */
  missingOn: 'weapp' | 'h5'
  /** 另一侧走什么形态（**具体路径**，不是"以后再说"） */
  fallback: string
  /** 接线处（仓库相对 bmini 根路径）—— 守卫核它真的引用了 `wiredToken` */
  wiredBy: string
  /** 接线记号：`wiredBy` 的**代码**里必须出现它（注释不算） */
  wiredToken: string
}

export const WORKER_SURFACE_PLATFORM_GAPS: WorkerSurfacePlatformGap[] = [
  {
    key: 'url-query-deeplink',
    missingOn: 'weapp',
    fallback:
      '小程序没有 URL query ⇒ 深链走**页面参数**：`Taro.getCurrentInstance().router.params.code`（与 h5 共用同一处判定与同一个下游页面 —— `src/utils/inbound/deepLink.ts` 的 `landingCodeFromParams` / `classifyLandingCode`）',
    wiredBy: 'src/pages/worker/reprint/index.tsx',
    wiredToken: 'landingCodeFromParams(',
  },
]

/** 修图/选图失败时给工人的话（页面直接渲染它，不在页面里另写一句） */
export const INBOUND_PHOTO_FAILED_HINT = '没能拿到照片（可能没授权相册/相机权限），请重试或换用手机浏览器打开。'

/** 未登录工人身份时的引导（不静默跳走：页面明说为什么） */
export const INBOUND_WORKER_LOGIN_REQUIRED =
  '请先用工号 + PIN 登录工人身份，再拍照入库（商家账号不能走这条路径）。'

/** 工人登录页路由（`app.config.ts` 已登记；守卫 G0 一并核验） */
export const WORKER_LOGIN_ROUTE = '/pages/worker/login/index'

/**
 * **商家登录页上的工人入口**（issue #6467 切片 1）—— `?tab=worker` 直达第三 tab。
 *
 * 「报工页 / 工人首页」的引导都指向**这一条**（而不是独立的 `pages/worker/login/index`）：
 * 商家登录页是 H5 的主登录门（`/b/` 的常规落点），从那里进去的人不必再找第二个登录页；
 * 两条链路的**身份判定都在服务端**（工号 + PIN ⇒ 工人 session），前端只是入口不同。
 */
export const WORKER_TAB_LOGIN_ROUTE = '/pages/auth/login/index?tab=worker'

/**
 * **工人首页**路由（issue #6467 切片 1）：纯工人设备登录成功后的落地页。
 *
 * 为什么必须有它：工人零商家权限（`/api/admin/**` 的拒绝集合含 `worker`）⇒ 落进商家 tabBar
 * （问黄金策 / 数据 / 坐席 / 我的）只会看到 403 / 空页；而 `Taro.switchTab` **只能**落 tabBar 页
 * ⇒ 工人登录成功后的去向只能是 `redirectTo` 一个**非 tabBar** 的工人页。
 *
 * 🔴 路由字面量是**单一真值**：`src/app.config.ts` 的 pages 必须逐字含它
 * （没登记 = 死链；守卫 = `tests/inbound-page-platform-gaps.test.ts` 的 G0 同款口径 +
 * `tests/page-entry-reachability.test.ts` 的 L0/L2）。
 */
export const WORKER_HOME_ROUTE = '/pages/worker/home/index'

/** 工人首页文件（守卫射程起点） */
export const WORKER_HOME_PAGE_FILE = 'src/pages/worker/home/index.tsx'

/**
 * **扫码报工**页路由（工人首页的三件功能之一）。
 * 该页早已在 `app.config.ts` 登记（也是「我的」页的入口），这里只把**工人面的引用**收敛到常量
 * —— 工人首页不再写第二份字面量（入口台账要能核「跳转语句里带着这个记号」）。
 */
export const PRODUCTION_PAGE_ROUTE = '/pages/production/index/index'

/** 工人首页未登录工人身份时的引导（与入库页同一口径，说清本页是「工人功能」） */
export const WORKER_HOME_LOGIN_REQUIRED =
  '请先用工号 + PIN 登录工人身份，再使用工人功能（商家账号不能走这条路径）。'

/** 报工页未登录工人身份时的引导（照报工页的语义写；写入口只在这个前提下渲染） */
export const PRODUCTION_WORKER_LOGIN_REQUIRED =
  '请先用工号 + PIN 登录工人身份，再扫码报工（商家账号不能走这条路径）。'

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
  'src/utils/inbound/deepLink.ts',
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
  { reason: 'wechat-webview', wiredBy: 'src/utils/inbound/printCapability.ts' },
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
