/**
 * 客户端错误上报（issue #8203 · P0-03；审计原文 `acceptance/2026-10-31-launch-audit/findings.md` 的 P0-03）。
 *
 * ## 病（改前，durable 读数）
 * `grep -rn "Sentry\|window.onerror\|unhandledrejection" frontend --include=*.ts --include=*.tsx` ⇒ **0 命中**：
 * 58 个页面里 57 个没有错误边界，渲染期异常 ⇒ Next.js 默认错误页（整页白屏、无重试出口），
 * 且**线上发生无人知道**（无事件、无聚合）。
 *
 * ## 本模块只做三件事（刻意不引入 Sentry / APM 依赖）
 * 1. `buildClientErrorEvent()` —— 把任意 `unknown` 归一成**固定 8 个字段**的上报体；
 * 2. `reportClientError()` —— 去重 + 去敏 + 截断 + `fetch(keepalive)`，**任何失败都不抛**；
 * 3. `installClientErrorHandlers()` —— 装 `window` 的 `error` / `unhandledrejection` 监听（幂等）。
 *
 * ## 隐私边界（**硬约束**，违反即缺陷）
 * 上报体**只有**：路由 `path`（**不含 query / hash**）、错误名、错误摘要（截断）、栈摘要（截断）、
 * React `digest`、发生时刻、UA、上报来源。
 * **不含**：PIN / token / 手机号 / 请求体 / 请求头 / cookie / 表单值 / 用户标识。
 * 两道防线：① 本模块**采集阶段**就不取这些东西（没有入参能带进来）；② `sanitizeText()` 对
 * 摘要/栈再做一次**模式化涂抹**（JWT、`token=`/`pin=`/`phone=` 键值、`Bearer`、11 位手机号、
 * 路径后面的 query 串）—— 因为第三方库抛出的 message 里可能**自带**这些东西。
 * 服务端还有第三道（`ClientErrorController` 落日志前再涂一次 + 字段白名单），三处都不许省。
 *
 * ## 失败不得影响页面（**硬约束**）
 * 上报器跑在**错误页**上：页面已经处于故障态，任何从上报器冒出来的异常都会把错误页也打挂 ⇒ 白屏。
 * 因此：`fetch` 用 try/catch + `.catch(() => {})` 包裹；序列化失败（`JSON.stringify` 循环引用）也只告吹、
 * 不抛；`typeof window === 'undefined'`（SSR / 预渲染）直接短路。
 *
 * ## 去重（同一错误短时间只报一次）
 * 键 = `path|name|message|digest`，窗口 30s。理由：React 错误边界与 `window.onerror` 可能对**同一次**
 * 异常各触发一次；同一页面的渲染循环会持续抛同一个错误 ⇒ 不去重就会把服务端日志刷爆、把页面拖慢。
 *
 * ## 已知不覆盖（照实登记）
 * - **不发** `sendBeacon`：单一传输通道（`fetch` keepalive）便于判据；`keepalive` 让页面卸载时请求仍可发出；
 * - **不做**错误采样 / 聚合 / 告警升级：那是外部通道（SLS / Sentry）的事，本包明确不接（见
 *   `docs/deployment/observability-minimum.md` 的「未覆盖」）；
 * - **不上报** C 端（mini-app / bmini / worker-h5）：issue #8203 的范围只有 admin-web。
 */

/** 上报来源（服务端按白名单校验，加新值必须同批改 `ClientErrorController`）。 */
export type ClientErrorSource = 'error-boundary' | 'window.onerror' | 'unhandledrejection'

/** 服务端端点（**相对路径**，由 `NEXT_PUBLIC_API_BASE_URL` 前缀拼出；同源部署时为空前缀）。 */
export const CLIENT_ERROR_ENDPOINT_PATH = '/api/client-errors'

/** 同一条错误在此窗口内只报一次（ms）。 */
export const DEDUPE_WINDOW_MS = 30_000

/** 字段长度上限（与 `ClientErrorController` 的校验**同值**；两边分叉 ⇒ 服务端 400 / 日志截断）。 */
export const MAX_PATH_LENGTH = 200
export const MAX_NAME_LENGTH = 80
export const MAX_MESSAGE_LENGTH = 300
export const MAX_STACK_LENGTH = 800
export const MAX_DIGEST_LENGTH = 64
export const MAX_UA_LENGTH = 200

/** 上报体（唯一形状；`ClientErrorController` 的字段白名单与它逐字对应）。 */
export interface ClientErrorEvent {
  path: string
  name: string
  message: string
  stack: string
  digest: string
  at: string
  ua: string
  source: ClientErrorSource
}

/** `reportClientError()` 的入参。 */
export interface ReportInput {
  source: ClientErrorSource
  error?: unknown
  digest?: string
  /** 显式路由（缺省取 `window.location.pathname`）；**总是**会被剥掉 query / hash。 */
  pathname?: string
}

/** `reportClientError()` 的结果（`sent=false` 时 `reason` 说明为什么没发 —— 不静默）。 */
export interface ReportResult {
  sent: boolean
  event: ClientErrorEvent
  reason?: 'deduped' | 'not-browser' | 'send-failed'
}

/**
 * 去敏表：**只做涂抹，不做结构判断**（结构判断在采集阶段：入参里根本没有这些字段）。
 *
 * 顺序敏感：JWT 与 `Bearer` 先抹（否则 `token=` 那条会把 JWT 的片段留下来）。
 */
const REDACTIONS: ReadonlyArray<readonly [RegExp, string]> = [
  // JWT（三段 base64url）—— 最常见的一类「错误 message 里自带凭据」
  [/\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b/g, '[redacted-jwt]'],
  // Authorization 头形态
  [/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, 'Bearer [redacted]'],
  // 键值形态：token= / pin= / password= / phone= / mobile= / code= / secret=
  [
    /\b(access_token|refresh_token|token|password|passwd|pin|phone|mobile|secret|code)=[^&\s"',}]*/gi,
    '$1=[redacted]',
  ],
  // 中国大陆手机号（11 位）
  [/\b1[3-9]\d{9}\b/g, '[redacted-phone]'],
  // 路径 / URL 后面的 query 串（错误信息里常带完整 URL）
  [/(\/[A-Za-z0-9._~%/-]*)\?[^\s"',}]*/g, '$1?[redacted-query]'],
]

/**
 * 涂抹 + 截断。**顺序**：先涂抹（可能变长），后截断（保证长度上限）。
 * 截断追加 `…` 以让读日志的人看得出「这不是全文」（不假装完整）。
 */
export function sanitizeText(raw: string, maxLength: number): string {
  let out = String(raw ?? '')
  for (const [pattern, replacement] of REDACTIONS) {
    out = out.replace(pattern, replacement)
  }
  // 控制字符 / 换行压成空格：日志是单行事件，多行会把后续字段挤到看不见的地方
  out = out.replace(/[\u0000-\u001f\u007f]+/g, ' ').replace(/\s+/g, ' ').trim()
  if (out.length > maxLength) {
    out = `${out.slice(0, maxLength - 1)}…`
  }
  return out
}

/** 只留 pathname：剥掉 query / hash（**这是「不含 token」的第一道防线**）。 */
export function toPathOnly(raw: string | undefined): string {
  const value = typeof raw === 'string' ? raw : ''
  if (!value) return ''
  // 完整 URL（window.onerror 的 filename / 用户传入）⇒ 取 pathname
  let candidate = value
  const schemeIdx = candidate.indexOf('://')
  if (schemeIdx >= 0) {
    const slashIdx = candidate.indexOf('/', schemeIdx + 3)
    candidate = slashIdx >= 0 ? candidate.slice(slashIdx) : '/'
  }
  const cut = candidate.search(/[?#]/)
  if (cut >= 0) candidate = candidate.slice(0, cut)
  if (!candidate.startsWith('/')) candidate = `/${candidate}`
  return sanitizeText(candidate, MAX_PATH_LENGTH)
}

/** 从任意 `unknown` 取出错误名（`Error` / 字符串 / 对象 / null 都有确定答案）。 */
function errorName(error: unknown): string {
  if (error instanceof Error && typeof error.name === 'string' && error.name) return error.name
  if (error === null) return 'NullThrown'
  if (error === undefined) return 'UndefinedThrown'
  const ctor = (error as { constructor?: { name?: string } })?.constructor?.name
  return ctor || typeof error
}

/** 从任意 `unknown` 取出错误摘要。 */
function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message || error.name || 'Error'
  if (typeof error === 'string') return error
  if (error && typeof error === 'object') {
    const message = (error as { message?: unknown }).message
    if (typeof message === 'string' && message) return message
    try {
      return JSON.stringify(error)
    } catch {
      return Object.prototype.toString.call(error)
    }
  }
  return String(error)
}

/** 从任意 `unknown` 取出栈摘要（没有栈 ⇒ 空串，**不伪造**）。 */
function errorStack(error: unknown): string {
  if (error instanceof Error && typeof error.stack === 'string') return error.stack
  const stack = (error as { stack?: unknown })?.stack
  return typeof stack === 'string' ? stack : ''
}

/** 当前浏览器的 pathname（SSR 时为空串）。 */
function currentPathname(): string {
  if (typeof window === 'undefined') return ''
  return window.location?.pathname || ''
}

/** 当前浏览器的 UA（SSR 时为空串）。 */
function currentUserAgent(): string {
  if (typeof navigator === 'undefined') return ''
  return navigator.userAgent || ''
}

/**
 * 归一化上报体（纯函数 —— 判据直接打它，不需要浏览器环境）。
 * 时间取「现在」；`at` 用 ISO-8601（带时区标记，便于与 CI/服务端日志对时）。
 */
export function buildClientErrorEvent(input: ReportInput): ClientErrorEvent {
  const digest = sanitizeText(input.digest ?? '', MAX_DIGEST_LENGTH)
  return {
    path: toPathOnly(input.pathname ?? currentPathname()),
    name: sanitizeText(errorName(input.error), MAX_NAME_LENGTH),
    message: sanitizeText(errorMessage(input.error), MAX_MESSAGE_LENGTH),
    stack: sanitizeText(errorStack(input.error), MAX_STACK_LENGTH),
    digest,
    at: new Date().toISOString(),
    ua: sanitizeText(currentUserAgent(), MAX_UA_LENGTH),
    source: input.source,
  }
}

/** 去重键（**不含 UA / 时刻**：同一错误在不同秒不该被当成不同错误）。 */
function dedupeKey(event: ClientErrorEvent): string {
  return [event.path, event.name, event.message, event.digest].join('|')
}

/** 已上报的键 ⇒ 上次上报时刻（模块级；跨页面生命周期共享）。 */
const reportedAt = new Map<string, number>()

/** 上限：页面故障时错误可能成千上万种 ⇒ 表不能无界增长（超了丢最旧的）。 */
const MAX_TRACKED_KEYS = 64

/** 判据用：清空去重表（不要在业务代码里调用）。 */
export function __resetClientErrorReporterForTests(): void {
  reportedAt.clear()
}

/** 上报端点（`NEXT_PUBLIC_API_BASE_URL` 为空 ⇒ 相对路径 = 同源）。 */
function endpointUrl(): string {
  const base = (process.env.NEXT_PUBLIC_API_BASE_URL || '').replace(/\/$/, '')
  return `${base}${CLIENT_ERROR_ENDPOINT_PATH}`
}

/**
 * 上报一条客户端错误。
 *
 * **不抛异常**是契约的一部分（见文件头「失败不得影响页面」）—— 唯一会返回的直接信号是
 * `{sent}`：`false` 时页面**什么都不做**，也不重试（重试会形成上报循环）。
 */
export function reportClientError(input: ReportInput): ReportResult {
  const event = buildClientErrorEvent(input)

  // SSR / 预渲染 / 非浏览器测试环境：没有上报通道，直接告吹（不算失败）
  if (typeof window === 'undefined' || typeof fetch !== 'function') {
    return { sent: false, event, reason: 'not-browser' }
  }

  const key = dedupeKey(event)
  const now = Date.now()
  const last = reportedAt.get(key)
  if (last !== undefined && now - last < DEDUPE_WINDOW_MS) {
    return { sent: false, event, reason: 'deduped' }
  }
  reportedAt.set(key, now)
  if (reportedAt.size > MAX_TRACKED_KEYS) {
    // 丢最旧的一条（Map 保插入顺序）
    const oldest = reportedAt.keys().next()
    if (!oldest.done) reportedAt.delete(oldest.value)
  }

  try {
    const pending = fetch(endpointUrl(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(event),
      // 页面卸载 / 跳转时请求仍可发出（错误页上点「回首页」正是这个场景）
      keepalive: true,
      credentials: 'omit',
    })
    // 🔴 **必须吞掉 rejection**：网络失败（离线 / CORS / 5xx）在上报面上不是页面的事
    if (pending && typeof pending.catch === 'function') {
      pending.catch(() => undefined)
    }
    return { sent: true, event }
  } catch {
    return { sent: false, event, reason: 'send-failed' }
  }
}

/** `window` 上的安装标记（幂等；重复安装不叠加监听）。 */
const INSTALL_FLAG = '__migaoClientErrorHandlersInstalled'

type WindowWithFlag = Window & { [INSTALL_FLAG]?: boolean }

/**
 * 装全局错误监听（幂等）。
 *
 * 用 `addEventListener('error' / 'unhandledrejection')` 而不是覆写 `window.onerror`：
 * 覆写会**吃掉**别人（监控 / 第三方库 / 既有守卫）挂的 handler —— 那是行为回归，不是本单的目标。
 * `error` 事件与 `window.onerror` 是同一事件的两种挂法，语义等价。
 *
 * @returns 本次是否**真的装了**（已装过 / 非浏览器 ⇒ `false`）
 */
export function installClientErrorHandlers(target?: Window): boolean {
  if (typeof window === 'undefined') return false
  const win = (target ?? window) as WindowWithFlag
  if (!win || typeof win.addEventListener !== 'function') return false
  if (win[INSTALL_FLAG]) return false
  win[INSTALL_FLAG] = true

  win.addEventListener('error', (event: Event) => {
    // 资源加载失败（<img>/<script>）没有 `error` 字段，只有 target ⇒ 仍然值得记一条
    const errorEvent = event as ErrorEvent
    reportClientError({
      source: 'window.onerror',
      error: errorEvent.error ?? errorEvent.message ?? 'unknown window error',
    })
  })

  win.addEventListener('unhandledrejection', (event: Event) => {
    const rejection = (event as PromiseRejectionEvent).reason
    reportClientError({ source: 'unhandledrejection', error: rejection })
  })

  return true
}
