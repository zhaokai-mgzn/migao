import { toast } from 'sonner'

/**
 * 请求错误提示去重（issue #2923）
 *
 * request.ts 的响应拦截器对后端错误（业务 success:false / HTTP 错误 / 网络错误）
 * 已统一 toast 具体错误信息。若页面 catch 块再 toast 一个通用 fallback，
 * 同一次失败会弹出两条提示（如「确认付款失败」+ 库存不足详情）。
 *
 * 约定：拦截器 toast 后给错误对象打标记；页面 catch 用 toastRequestError 判断，
 * 已提示过则不再重复弹（fallback 仅用于未经拦截器的错误，如客户端校验）。
 */

// Symbol.for 保证跨模块实例/HMR 稳定
const TOAST_SHOWN = Symbol.for('migao.request.errorToastShown')

/** 错误是否已被拦截器 toast 过（页面不应再重复提示） */
export function isErrorToastShown(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  try {
    return (error as Record<PropertyKey, unknown>)[TOAST_SHOWN] === true
  } catch {
    return false
  }
}

/** 标记错误已被 toast（供 request.ts 拦截器在所有 toast 后调用） */
export function markErrorToastShown(error: unknown): void {
  if (!error || typeof error !== 'object') return
  try {
    ;(error as Record<PropertyKey, unknown>)[TOAST_SHOWN] = true
  } catch {
    // 不可扩展对象（如 frozen）忽略标记，不影响报错本身
  }
}

export interface ToastRequestErrorOptions {
  /** 页面 loading toast 的 id：拦截器已提示时 dismiss，避免 loading 卡住 */
  id?: string | number
}

/**
 * 取服务端可展示文案（issue #5485；🔴 2026-10-17 收口）。
 *
 * 后端统一信封 `{success:false, error:{code, message}}` ⇒ 详情在 `response.data.error.message`。
 * 登录 / 改密页需要把 401 / 422 的**服务端原文**直接展示：
 * - 反枚举（AU-003）：企业编码不存在 / 用户名不存在 / 密码错 ⇒ 服务端**同一条文案**，
 *   前端不得改写、更不得自己编一条更细的提示（那等于把账号是否存在泄露出去）；
 * - 改密 422（弱密码 / 旧密码错）、企业编码 422（格式 / 占用 / 保留字）同样直接透传原文。
 *
 * 🔴 **传输层原文不上屏**（2026-10-17，用户逐字「这个错误提示非常低级，用户完全看不懂，
 * 得把报错原因用业务文案写清楚，而不是技术语言」—— 他在智能派单页看到的是
 * `合并预览失败：Request failed with status code 422`）。缺省顺序里原先还有一格 `err.message`，
 * 而 **axios 错误的 `.message` 就是那句传输层读数**（`Request failed with status code NNN` /
 * `Network Error`）⇒ 服务端文案缺失时会把技术语言端给商家。
 * 现在：**传输层错误一律不许用 `.message`**（按 `isAxiosError` / `response` / `request` 三面判定），
 * 落到调用方给的 `fallback`（业务话术）；非传输层的本地错误（客户端校验等）仍可用 `.message`。
 */
export function extractApiErrorMessage(error: unknown, fallback: string): string {
  const err = error as {
    isAxiosError?: boolean
    response?: { data?: { error?: { message?: string }; message?: string } }
    request?: unknown
    message?: string
  }
  const fromServer = err?.response?.data?.error?.message || err?.response?.data?.message
  if (typeof fromServer === 'string' && fromServer.trim()) return fromServer
  const isTransportError =
    err?.isAxiosError === true || err?.response !== undefined || err?.request !== undefined
  if (!isTransportError && typeof err?.message === 'string' && err.message) return err.message
  return fallback
}

/**
 * **常驻失败态**的文案（issue #7373 复盘）：服务端原文优先，没原因时按处境给能行动的话。
 *
 * <p>与 {@link extractApiErrorMessage} 的分工：那个用于「登录 / 改密」这类**必须逐字透传**的页面
 * （反枚举纪律要求不得改写服务端文案）；本函数用于**列表读面失败卡片** —— 它会长久挂在屏幕上，
 * 所以除了转述原文，还要在没有原因时说清「该找谁 / 该做什么」。</p>
 *
 * <p>🔴 两条既有纪律必须同时遵守：</p>
 * <ol>
 *   <li><b>传输层技术语言不上屏</b>（`Request failed with status code NNN` 不进界面）；</li>
 *   <li><b>协议细节不上屏</b>（issue #6488，R1 判据）：不写 `HTTP 500` 这种商家读不懂的字样 ——
 *       状态码的**含义**用业务话讲出来（「服务端出错了」/「没有查看权限」），码本身留给日志与客服。</li>
 * </ol>
 *
 * @param error    捕获到的异常
 * @param fallback 拿不到任何原因时的本页兜底句（例：「采购单加载失败」）
 */
export function loadErrorMessage(error: unknown, fallback: string): string {
  const err = error as { response?: { status?: number }; request?: unknown } | null
  const status = err?.response?.status
  const serverText = extractApiErrorMessage(error, '')

  // ① 服务端给了业务原因 ⇒ 原样转述（那是给人看的，别用通用句盖掉）
  if (serverText) {
    return serverText
  }
  // ② 没原因但有状态码 ⇒ 把**处境**讲成人话（不同处境该做的事不同）
  if (status === 401) {
    return '登录状态已失效，请重新登录'
  }
  if (status === 403) {
    return '当前账号没有查看权限，请联系管理员分配'
  }
  if (status !== undefined && status >= 500) {
    return `${fallback}：系统出了点问题，请稍后重试；若一直这样请联系技术支持`
  }
  if (status !== undefined) {
    return `${fallback}：这次没读成功，请刷新后重试；若仍不行请联系技术支持`
  }
  // ③ 压根没到服务端（断网 / 跨域 / 请求被取消）
  if (err?.request) {
    return '网络连不上，请检查网络后重试'
  }
  return fallback
}

/**
 * 页面 catch 块的统一错误提示入口：
 * - 拦截器已提示后端具体错误 → 不重复弹；若传了 loading id 先 dismiss（防止「操作中…」滞留）
 * - 未经拦截器（客户端校验等本地错误）→ 弹 fallback
 */
export function toastRequestError(error: unknown, fallback: string, options?: ToastRequestErrorOptions): void {
  if (isErrorToastShown(error)) {
    if (options?.id !== undefined) toast.dismiss(options.id)
    return
  }
  if (options?.id !== undefined) {
    toast.error(fallback, { id: options.id })
  } else {
    toast.error(fallback)
  }
}