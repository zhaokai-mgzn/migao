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

/**
 * 非微信浏览器（含 iPhone Safari）下的**降级告知**（issue #5750）。
 *
 * 不是一句「不支持」，而是「已换一条路」：本仓在拍照入库链路上早已验证
 * 「`Taro.chooseImage`（h5 真实实现）+ `<img>`/canvas + `jsQR` 本机解码」在任何浏览器都能走通
 * ⇒ 报工页把扫码降级成**拍照识别**，而不是把工人丢回手输。
 * 判据（行为面）= `tests/production-page.test.tsx` 的「降级为拍照识别 → 同一条 scanResolve」。
 * ⚠️ 2026-10-14（issue #6868 实现包 D1）：那个**消费页面**（小程序报工页
 * `src/pages/production/index/index.tsx`）已下架，该判据文件同批删除 ⇒ 本常量当前的消费方
 * 只剩 H5 侧同类降级面与 `tests/h5-platform-runtime.test.ts` 的平台判据（历史留痕不改）。
 */
export const H5_SCAN_PHOTO_HINT = '当前浏览器不能直接扫码：已改用拍照识别，对准二维码拍一张即可'

/**
 * 拍照识别**也没成功**时的可行动文案（用户取消 / 没给权限 / 照片里没码）。
 *
 * 两个出口都要写出来（重拍 + 手输），否则又回到「一句话不可行动」的老形态。
 */
export const H5_SCAN_PHOTO_FAILED_HINT =
  '照片里没识别出二维码：请对准二维码重拍一张，或在下框手输加工单号'

/**
 * 浏览器**确实没有**录音能力时的显式提示（issue #5650 / #6596）。
 *
 * 只在 `MediaRecorder` + `getUserMedia` 都拿不到时才走到这里（h5 的录音已于 #6596 用浏览器原生 API 做出来，
 * 见 `frontend/bmini-app/src/utils/voiceBrowserRecorder.ts`）⇒ 这是**罕见**分支：切换键点了给解释 +
 * 告诉用户下一步怎么办，不静默消失、也不留「点了没反应」。
 */
export const H5_VOICE_UNAVAILABLE_HINT = '当前浏览器不支持语音输入：请用文字发送'

/**
 * 是否运行在**支付宝内置浏览器**里（issue #7310，真机对照实证）
 *
 * 2026-10-19 同一台华为 ALN-AL00 的对照读数（服务端 nginx 逐条可查）：
 * - **支付宝** webview（`AliApp(AP/12.12.30.5600)`）：8/8 次「按住说话」上传的都是 **0 字节音频**
 *   ⇒ 服务端 400「音频文件为空」；`getUserMedia` **不报拒绝**（否则客户端会给「没有麦克风权限」），
 *   返回的流里没有有效音频 ⇒ `MediaRecorder` 只吐一个空 Blob。
 * - 同一台机器换**百度 App** 打同一份 H5：同链路 11:10:28 / 11:11:02 两次 **200 转写成功**。
 * ⇒ 设备 / 系统麦克风权限 / 网络 / 服务端全部无关，是**支付宝 webview 拦截了麦克风数据**。
 *
 * 故按 #5650 / #6476 的口径（**不摆按不动的键**）在支付宝内不把「按住说话」摆成可用形态。
 * 重启条件：某版支付宝放开麦克风时，按真机读数复核后撤掉这道门（不要凭印象撤）。
 */
export function isAlipayWebview(): boolean {
  if (!isH5()) return false
  if (typeof window === 'undefined') return false
  const ua = String((window as any).navigator?.userAgent || '').toLowerCase()
  return ua.includes('alipayclient') || ua.includes('aliapp')
}

/** 支付宝内语音不可用的**可行动**解释（说清「为什么 + 怎么办」，issue #7310） */
export const ALIPAY_VOICE_UNAVAILABLE_HINT =
  '支付宝里无法使用语音输入：请用手机浏览器打开，或直接用文字发送'

/** 「语音不可用」的那句话：支付宝点名支付宝（用户才知道该换 App），其余走通用文案 */
export function voiceUnavailableHint(): string {
  return isAlipayWebview() ? ALIPAY_VOICE_UNAVAILABLE_HINT : H5_VOICE_UNAVAILABLE_HINT
}

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
    'h5 不调用它（stub）⇒ 语音改走**浏览器原生** `getUserMedia` + `MediaRecorder`（issue #6596，见 frontend/bmini-app/src/utils/voiceBrowserRecorder.ts）；浏览器确实没有这两个 API 时才回落文字模式，切换键点了给显式提示（H5_VOICE_UNAVAILABLE_HINT）',
  // 🔴 2026-10-26（issue #7812 P2a）：`scanCode` 的用法**回来了** —— 小程序报工页
  // （`src/pages/worker/report/index.tsx`）的「扫一扫」是小程序独有能力；h5 产物里没有它，
  // 页面靠 {@link canUseNativeScan} 决定**摆不摆**这个按钮（不摆 = 手输码仍可用，不是死路）。
  scanCode:
    'h5 不暴露原生扫码：`canUseNativeScan()` 为假 ⇒ 页面**不渲染**「扫一扫」，只给手输码（短码 / 加工单号 / 订单号）这一条降级路径；小程序端走原生扫码（能力探测见本文件）',
  createOffscreenCanvas:
    'h5 不调用它（未实现的 stub）：拍照入库的**本机解码**在 h5 走 <img> + canvas 取像素，只有小程序端才用它；小程序端取不到像素时明说「已改用服务端识别」（src/utils/inbound/barcodeDecode.ts 的平台分支）',
}
