/**
 * 平台判别与 h5 能力出路（issue #5650）
 *
 * 背景：用户 2026-09-26 裁定「**暂时只做 H5 浏览器访问，小程序链路先搁置**」
 * ⇒ `frontend/bmini-app` 的 h5 编译产物 = **唯一的用户可达形态**。
 * 而 Taro 的 h5 实现包对一部分小程序专有 API 只给 stub、或只给微信 JS-SDK 通道
 * ⇒ 端侧不给显式平台分支，用户看到的就是「点了没反应 / 白屏 / 静默什么都没发生」。
 *
 * 🔴 判据不许靠源码印象（本 issue 立单时正是凭印象写错规格、并被评论区更正登记了教训）——
 * **唯一权威是实现包** `node_modules/@tarojs/taro-h5/dist`，两张清单：
 *   ① **明确不实现** = `temporarilyNotSupport('<api>')`
 *      （实测 taro-h5 4.2.1 共 313 条；例 `dist/api/open-api/login.js` 逐字
 *      `const login = …temporarilyNotSupport('login')`）；
 *   ② **只在微信内置浏览器可用** = `processOpenApi({ … })` **且无 `standardMethod`**
 *      （例 `dist/api/device/scan.js` 的 `scanCode` → `name: 'scanQRCode'` = 微信 JS-SDK）
 *      ⇒ 纯浏览器（Chrome / Safari）下 `window.wx` 不存在，Taro 走 `weixinCorpSupport` 的
 *      notSupported 分支，errMsg 逐字「h5 端当前仅在微信公众号 JS-SDK 环境下支持此 API」。
 * 带 `standardMethod` 的 `processOpenApi`（如 `getLocation` 的 W3C 兜底）不在清单 ② 里。
 *
 * 类级守卫 = `tests/h5-platform-api-guard.test.ts`：它**现取**上面两张清单 ∩ 本仓 `Taro.*` 用法，
 * 命中项必须在 `H5_API_OUTLET_LEDGER` 里登记出路、且**调用点所在文件**必须引入本模块
 * （= 有显式平台分支）。新增一个 h5 没实现的 Taro API 调用而未登记 ⇒ 守卫判红。
 */

/** Taro 编译目标（`taro build --type <x>` 注入；jest 下由测试显式设置） */
export function getPlatformEnv(): string {
  // DefinePlugin 在构建期把 `process.env.TARO_ENV` 替换成字面量 —— 写在函数体内同样被替换，
  // 因此运行期读到的就是本次编译的目标平台。
  return process.env.TARO_ENV || 'unknown'
}

/** 本次编译目标是否为 h5（浏览器） */
export function isH5(): boolean {
  return getPlatformEnv() === 'h5'
}

/** 本次编译目标是否为微信小程序 */
export function isWeapp(): boolean {
  return getPlatformEnv() === 'weapp'
}

/**
 * 是否运行在**微信内置浏览器**里 —— h5 下微信 JS-SDK 通道（`scanQRCode` 等）的唯一前提。
 *
 * 判据与 Taro 的实现同源：`processOpenApi` 取的就是 `window.wx[name]`，
 * 拿不到就走 `weixinCorpSupport` 的 notSupported 分支 ⇒ 这里同样要求
 * 「UA 含 MicroMessenger」**且**「`window.wx.scanQRCode` 是函数」，两者缺一即不可用。
 */
export function isWechatWebview(): boolean {
  if (!isH5()) return false
  if (typeof window === 'undefined') return false
  const ua = String((window as any).navigator?.userAgent || '').toLowerCase()
  const wx = (window as any).wx
  return ua.includes('micromessenger') && typeof wx?.scanQRCode === 'function'
}

/**
 * h5 下 `Taro.scanCode` 能否走通。
 *
 * ⚠️ 它不是「没实现」，而是「实现依赖微信 JS-SDK」⇒ 判据必须看**运行环境**，不能只看编译目标：
 * 同一份 h5 产物，在微信内置浏览器里能扫（走 `window.wx.scanQRCode`），
 * 在 Chrome / Safari 里**不能**（Taro 直接走 notSupported 分支）。
 */
export function canUseNativeScan(): boolean {
  return isH5() ? isWechatWebview() : true
}

/** h5 扫码不可用时的**显式**出路文案（降级到手输单号 —— `production/index/index.tsx` 既有的第二条路径） */
export const H5_SCAN_UNAVAILABLE_HINT = '当前浏览器不支持扫码，请在手输框输入加工单号'

/** h5 语音不可用时的**显式**提示（入口保留可见但禁用，点击给解释 —— 不静默消失、不留「点了没反应」） */
export const H5_VOICE_UNAVAILABLE_HINT = '浏览器暂不支持语音输入，请用文字发送'

/** h5 微信登录不可用时的**显式**提示（浏览器走账号密码 —— 用户裁定「浏览器仍然需要账号密码」） */
export const H5_WECHAT_LOGIN_UNAVAILABLE_HINT =
  '浏览器环境不支持微信登录，请用「用户名@企业编码 + 密码」登录'

/**
 * 类级台账：本仓用到、且 h5 侧**必须**有显式去处的 Taro API。
 *
 * 键 = Taro API 名（现取自上面两张清单 ∩ 本仓用法，**唯一权威是实现包**）；
 * 值 = 该 API 在 h5 的出路（一句话说清「用户看到什么」）。
 *
 * 🔴 台账**只许缩短**，且条目必须仍然活着：仍登记、但「清单 ∩ 用法」里已经不存在的 ⇒ 守卫判红
 * （防止台账变成一份自我复制的历史文档）。
 * 新增一条的**正确顺序**：先在调用点落平台分支（引入本模块）+ 在此登记出路，再让守卫绿。
 */
export const H5_API_OUTLET_LEDGER: Record<string, string> = {
  login: 'h5 不走微信换码：miniAppLogin 直接拒绝并指向账号密码登录（employeeLogin → POST /api/auth/employee/login）',
  getRecorderManager:
    'h5 不调用它（stub）：语音入口保留可见但禁用，点击给显式提示（H5_VOICE_UNAVAILABLE_HINT）',
  scanCode:
    'h5 仅微信内置浏览器可用（JS-SDK）；纯浏览器降级为手输单号，点「扫一扫」给显式提示（H5_SCAN_UNAVAILABLE_HINT）',
}
