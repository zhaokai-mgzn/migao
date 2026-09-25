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
 * 取服务端可展示文案（issue #5485）。
 *
 * 后端统一信封 `{success:false, error:{code, message}}` ⇒ 详情在 `response.data.error.message`。
 * 登录 / 改密页需要把 401 / 422 的**服务端原文**直接展示：
 * - 反枚举（AU-003）：企业编码不存在 / 用户名不存在 / 密码错 ⇒ 服务端**同一条文案**，
 *   前端不得改写、更不得自己编一条更细的提示（那等于把账号是否存在泄露出去）；
 * - 改密 422（弱密码 / 旧密码错）、企业编码 422（格式 / 占用 / 保留字）同样直接透传原文。
 *
 * 兜底顺序与 `request.ts` 拦截器的口径一致，最后才落到调用方给的 fallback。
 */
export function extractApiErrorMessage(error: unknown, fallback: string): string {
  const err = error as {
    response?: { data?: { error?: { message?: string }; message?: string } }
    message?: string
  }
  return (
    err?.response?.data?.error?.message ||
    err?.response?.data?.message ||
    err?.message ||
    fallback
  )
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