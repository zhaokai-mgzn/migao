/**
 * 微信隐私授权（**选中的照片或视频信息 / 摄像头 / 麦克风**）—— 自定义弹窗的接入层
 *
 * ## 为什么需要它（不是「加个弹窗美化」）
 *
 * 小程序后台已按上述**三类**申报《用户隐私保护指引》。微信规则（官方《小程序隐私协议开发指南》
 * 「二、接入流程」）：**只有已申报的隐私接口/组件才可用；且用户未同意前调用会被拦截**。
 * 本仓真正会用到的三类入口是 `chooseImage`（拍照入库 / 补打 / 发货 / 库存修正 / AI 识图问答）、
 * `scanCode`（扫码报工 / 裁高 / 精裁 / 质检）、`getRecorderManager`（语音输入转文字）。
 *
 * 🔴 代码里此前**一处都没有**隐私授权流程 ⇒ 未同意的用户点「扫一扫」/「拍照」/「按住说话」
 * 拿到的是微信侧失败（`fail privacy permission is not authorized`），现场表现 = **工人功能全挂**，
 * 而且没有任何东西会变红（接口调用本身写得没问题）。
 *
 * ## 为什么是**自定义弹窗**，而不是「什么都不做、等微信官方弹窗」
 *
 * 官方文档「六、官方隐私弹窗功能说明」：开发者不响应 `onNeedPrivacyAuthorization` 时，微信会
 * 兜底弹**官方**弹窗。但官方弹窗只有「允许/拒绝」，**没有**本店要告知的三类用途说明，也**打不开**
 * 《隐私保护指引》全文；而《用户隐私保护指引》5.2 要求「变更用途时以弹窗、站内消息等显著方式告知」
 * ⇒ 我们自己的弹窗是**可复用**的告知面（不止首次），官方弹窗只留作「我们没响应」时的兜底。
 *
 * ## 流程（官方字段名逐一核对，勿改名）
 *
 * 1. 入口 `app.tsx` 调 {@link setupPrivacyAuthorization} **一次**：注册 `Taro.onNeedPrivacyAuthorization`；
 * 2. 用户触发隐私接口 ⇒ 微信触发该事件，**接口进入 pending（不报错）**，回调把 `resolve` 入队并通知订阅者；
 * 3. 页面上的 `<PrivacyPopup />` 显示 ⇒ 用户点「同意并继续」（`<Button openType="agreePrivacyAuthorization" id="agree-btn">`）
 *    ⇒ 我们调 `resolve({ event: 'agree', buttonId: 'agree-btn' })`：**`buttonId` 必填**，微信会校验
 *    对应 id 的同意按钮**确实被点过**（少了它平台不认，pending 接口不会继续）；
 * 4. 用户点「暂不同意」⇒ `resolve({ event: 'disagree' })` ⇒ 原接口失败，页面既有的错误分支照常提示。
 *
 * ## h5 降级（本仓 h5 产物是**唯一用户可达形态**之一，不许因为小程序专有 API 而白屏）
 *
 * `@tarojs/taro-h5` 把 `onNeedPrivacyAuthorization` / `openPrivacyContract` 都实现成
 * `temporarilyNotSupport(...)` 的 stub（`node_modules/@tarojs/taro-h5/dist/api/open-api/privacy.js`）
 * ⇒ **`typeof` 判断拦不住**（函数存在、只是假实现），必须按编译目标判（`isH5()`）。
 * h5 下：注册 = no-op（返回同一个空 unsubscribe），`resolvePrivacy` / `openPrivacyContract` 都不碰 stub。
 */
import Taro from '@tarojs/taro'
import { isH5 } from './platform'

/** 同意按钮的 `id`：微信按它校验「用户点过同意按钮」，必须与弹窗里 `<Button id=…>` 逐字相等 */
export const AGREE_BUTTON_ID = 'agree-btn'

/** `resolve` 的入参（官方字段名：`event` + `buttonId`；`buttonId` 仅 `agree` 必填） */
export interface PrivacyResolveOption {
  event: 'agree' | 'disagree'
  buttonId?: string
}

type PrivacyResolver = (option: PrivacyResolveOption) => void
type PrivacySubscriber = (needAuthorization: boolean) => void

/** 幂等句柄：非 null 即已注册过（重复调用返回**同一个** unsubscribe） */
let unsubscribeAll: (() => void) | null = null

/**
 * 待响应的 `resolve` 队列。
 *
 * 为什么是队列而不是单个：同一次交互可能连续触发多个隐私接口（例：拍照后立即录音），
 * 每个事件各带一个 `resolve`；只留最后一个 ⇒ 先到的那个接口**永远 pending**（既不成功也不失败）。
 * 官方 demo2（「多个页面、多个隐私接口同时调用」）就是这个形态。
 */
let pendingResolvers: PrivacyResolver[] = []

const subscribers = new Set<PrivacySubscriber>()

/** 当前编译目标是否真有隐私授权能力（h5 的 stub 存在但不做事，见文件头） */
function privacyApiAvailable(): boolean {
  return !isH5() && typeof Taro.onNeedPrivacyAuthorization === 'function'
}

/**
 * 注册一次隐私授权监听（**幂等**：重复调用只 bind 一次，返回同一个 unsubscribe）。
 *
 * 返回的 unsubscribe 只用于「测试里把注册态复位」这类场景 —— 微信侧注册是按小程序生命周期
 * 生效的一次性动作（Taro 4.2.1 的类型里没有 `offNeedPrivacyAuthorization`）。
 */
export function setupPrivacyAuthorization(): () => void {
  if (unsubscribeAll) return unsubscribeAll
  if (!privacyApiAvailable()) {
    unsubscribeAll = () => {}
    return unsubscribeAll
  }
  Taro.onNeedPrivacyAuthorization((resolve) => {
    pendingResolvers.push(resolve as unknown as PrivacyResolver)
    subscribers.forEach((notify) => notify(true))
  })
  unsubscribeAll = () => {}
  return unsubscribeAll
}

/** 订阅「需要用户授权」状态（弹窗组件用它决定渲染与否）；返回退订函数 */
export function subscribePrivacy(subscriber: PrivacySubscriber): () => void {
  subscribers.add(subscriber)
  return () => {
    subscribers.delete(subscriber)
  }
}

/**
 * 回应用户的选择（**必须由弹窗的两个按钮调用**，不能由页面自行 SDK 调用后直接改状态）。
 *
 * `agree` ⇒ 带上按钮 id（微信校验过了才放行 pending 接口）；`disagree` ⇒ 只带 `event`。
 */
export function resolvePrivacy(agree: boolean): void {
  const resolvers = pendingResolvers
  pendingResolvers = []
  const option: PrivacyResolveOption = agree
    ? { event: 'agree', buttonId: AGREE_BUTTON_ID }
    : { event: 'disagree' }
  resolvers.forEach((resolve) => resolve(option))
  subscribers.forEach((notify) => notify(false))
}

/** 打不开《隐私保护指引》时的**可行动**说明（不是在无认证的浏览器里给一个打不开的链接） */
export const PRIVACY_CONTRACT_UNAVAILABLE_HINT =
  '当前环境无法打开《隐私保护指引》：请在微信里打开小程序，点右上角「···」→「隐私保护指引」查看'

function showContractFallback(): void {
  void Taro.showModal({
    title: '隐私保护指引',
    content: PRIVACY_CONTRACT_UNAVAILABLE_HINT,
    showCancel: false,
  })
}

/** 打开微信侧的《隐私保护指引》全文（h5 / 低版本基础库 ⇒ 降级为说明弹窗，不留死链） */
export function openPrivacyContract(): void {
  if (!isH5() && typeof Taro.openPrivacyContract === 'function') {
    Taro.openPrivacyContract({ fail: showContractFallback })
    return
  }
  showContractFallback()
}
