/**
 * 失败提示里的**追踪编号**（issue #6957）—— 让「商家截图」能对上「服务端那条 incident」。
 *
 * ## 病（改前，逐字）
 * `src/lib/request.ts` 的失败分支只 toast `message`：商家看到「服务器内部错误」，客服
 * 拿不到任何可反查的串；而服务端的 `requestId` 既不进日志、也不上屏 ⇒ 号线断在中间。
 *
 * ## 形态（§31 产品设计原则：事实 + 该做什么，不摆内部标识）
 * 提示仍是**一句人话**（服务端/既有文案），追踪编号作为**第二行的可复制引用**出现：
 *
 *   ┌ 服务器内部错误
 *   │ 联系客服时提供这串编号，可据此查到这次失败：req_1a2b3c4d5e6f7a8b   [复制编号]
 *
 * 三条取舍（都写进 PR body 的 §31 自检）：
 * ① **只上屏 requestId，不上屏 error.code** —— `INTERNAL_ERROR` / `VALIDATION_ERROR` 是**机读枚举**，
 *    商家读不懂（§31 P3「不摆内部标识」）；反查只需要 requestId，code 在服务端信封与日志里都有。
 * ② **不打印整个响应体 JSON** —— 那是把协议细节端给商家（UI-057 / #6488 的同族禁忌）。
 * ③ **不新增常驻面** —— toast 天然短暂，不挂横幅、不占首屏（§31 P1）。
 *
 * ## 边界（照实登记）
 * - 只在**服务端信封里确实带了 requestId** 时展示（形状不合法的 id 不采信，见 `readErrorReference`）；
 * - 网络层失败（断网 / 超时 / 跨域）没有服务端 id ⇒ 仍是原来的纯文案 toast；
 * - 「复制」失败（非安全上下文没有 `navigator.clipboard`）静默降级：文字仍可手动选中复制。
 */
import { toast } from 'sonner'

/** 商家可见的引导句（事实 + 该做什么；不含内部机制名）。 */
export const ERROR_REFERENCE_HINT = '联系客服时提供这串编号，可据此查到这次失败'

/** 复制动作的按钮文案。 */
export const ERROR_REFERENCE_COPY_LABEL = '复制编号'

/**
 * 追踪编号的合法形状（与服务端 `RequestId.acceptOrGenerate` 的接受集**同口径**）：
 * URL 安全字符 + 8~64 位。形状不符（空串 / 带空格 / 超长 / 非字符串）⇒ 不展示。
 */
const REQUEST_ID_PATTERN = /^[A-Za-z0-9._-]{8,64}$/

export interface ErrorReference {
  /** 服务端请求追踪编号（唯一反查键）。 */
  requestId: string
  /** 机读错误码（**不上屏**，留给调用方/日志）。 */
  code?: string
}

/**
 * 从服务端信封里取追踪编号（`{success:false, error:{code,message}, requestId}`）。
 *
 * @param payload 响应体（任意 `unknown`；形状不符 ⇒ `null`，绝不抛）
 */
export function readErrorReference(payload: unknown): ErrorReference | null {
  if (!payload || typeof payload !== 'object') return null
  const envelope = payload as { requestId?: unknown; error?: { code?: unknown } | null }
  const requestId = typeof envelope.requestId === 'string' ? envelope.requestId.trim() : ''
  if (!REQUEST_ID_PATTERN.test(requestId)) return null
  const code = typeof envelope.error?.code === 'string' ? envelope.error.code : undefined
  return code ? { requestId, code } : { requestId }
}

/**
 * 失败提示的统一出口：有追踪编号就**多给一行可复制引用**，没有就与改前逐字相同。
 *
 * @param message 面向商家的第一行（既有文案 / 服务端 message，不改写）
 * @param payload 响应体（取 `requestId`；拿不到 ⇒ 纯文案 toast）
 */
export function showRequestErrorToast(message: string, payload: unknown): void {
  const reference = readErrorReference(payload)
  if (!reference) {
    toast.error(message)
    return
  }
  toast.error(message, {
    description: `${ERROR_REFERENCE_HINT}：${reference.requestId}`,
    action: {
      label: ERROR_REFERENCE_COPY_LABEL,
      onClick: () => copyToClipboard(reference.requestId),
    },
  })
}

/** 复制到剪贴板：**任何失败都不抛**（提示本身不能因为复制不了而消失）。 */
function copyToClipboard(text: string): void {
  try {
    const pending = globalThis.navigator?.clipboard?.writeText(text)
    if (pending && typeof pending.catch === 'function') pending.catch(() => {})
  } catch {
    // 非安全上下文 / 老浏览器：静默降级（文字仍可手动选中复制）
  }
}
