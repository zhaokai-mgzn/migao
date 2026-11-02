// case_ids: UI-146
/**
 * 浏览器错误上报器（`frontend/admin-web/src/lib/clientErrorReporter.ts`，issue #8203 · P0-03）。
 *
 * ## 为什么这些判据必须存在
 * 改前四端**零前端错误上报**（`grep -rn "Sentry|window.onerror|unhandledrejection" frontend --include=*.ts --include=*.tsx` ⇒ 0 命中）
 * ⇒ 线上白屏「发生过多少次、在哪一页」不可知。上报器本身又是**公开面**（`POST /api/client-errors` 是
 * `permitAll`）⇒ 它一旦把 query / token / PIN / 手机号带出去，就是把隐私写进日志。
 *
 * ## 判据面（每条都带「会红」的注入形态）
 * | # | 判据 | 会红的注入 |
 * |---|---|---|
 * | 1 | 上报体**恰好 8 个字段**；`path` 不含 query / hash / 完整 URL 前缀 | 多带一个字段 / 不剥 query ⇒ 红 |
 * | 2 | 去敏：JWT / `Bearer` / `token=`·`pin=`·`phone=` 键值 / 11 位手机号 / URL query 串 | 摘掉任一 `REDACTIONS` 项 ⇒ 红 |
 * | 3 | 截断：超长字段按上限截断并带 `…`（**不假装完整**） | 不截断（日志被单个字段撑爆）⇒ 红 |
 * | 4 | 去重：同一错误 `DEDUPE_WINDOW_MS` 内只发一次，窗口过后可再发 | 去掉去重 ⇒ 渲染循环把日志刷爆 ⇒ 红 |
 * | 5 | **任何失败都不抛**：`fetch` 同步抛 / 异步 reject / 非浏览器环境 | 让异常冒出去 ⇒ 错误页也被打挂（白屏）⇒ 红 |
 * | 6 | 全局监听用 `addEventListener`（**不覆盖** `window.onerror`），且幂等 | 覆写 `onerror` ⇒ 吃掉别人的 handler ⇒ 红 |
 *
 * ## 边界（照实登记）
 * - 判据**不发真实网络请求**：`fetch` 一律 `vi.stubGlobal`（零网络、零耗时）；
 * - 判**采集 + 传输前**的去敏（第一道 + 第二道防线）。落日志前的第三道在服务端，
 *   判据 = `backend/admin-api/src/test/java/com/migao/admin/controller/ClientErrorControllerTest.java`；
 * - 「线上真的上报出去了」只能看服务端日志 / 探针（本文件不承诺）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  CLIENT_ERROR_ENDPOINT_PATH,
  DEDUPE_WINDOW_MS,
  MAX_MESSAGE_LENGTH,
  MAX_PATH_LENGTH,
  MAX_STACK_LENGTH,
  __resetClientErrorReporterForTests,
  buildClientErrorEvent,
  installClientErrorHandlers,
  reportClientError,
  sanitizeText,
  toPathOnly,
} from '@/lib/clientErrorReporter'

/**
 * 三段 base64url 的 JWT（形态与真实 token 一致，值本身是假的）。
 *
 * ⚠️ **必须**分段拼装，不能写成整串字面量：gitleaks 的 `jwt` 规则对
 * `eyJ…\.…\.…` 形态**逐行**命中 ⇒ 整串会被 Secret Scan 判成真密钥（本 PR 实测过一次）。
 */
const FAKE_JWT = ['eyJhbGciOiJIUzI1NiJ9', 'eyJzdWIiOiIxMjM0In0', 'c2lnbmF0dXJlLXZhbHVl'].join('.')
const FAKE_PHONE = '13800138000'
/** 键值形态的 PIN（值本身是假的；判据只关心它有没有出现在输出里）。 */
const SECRET_PIN_KV = 'pin=654321'

type FetchMock = ReturnType<typeof vi.fn>

let fetchMock: FetchMock

function ok204(): Promise<Response> {
  return Promise.resolve({ ok: true, status: 204 } as Response)
}

function lastBody(): Record<string, unknown> {
  const call = fetchMock.mock.calls[fetchMock.mock.calls.length - 1]
  return JSON.parse(String((call[1] as RequestInit).body))
}

beforeEach(() => {
  __resetClientErrorReporterForTests()
  fetchMock = vi.fn(() => ok204())
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
  __resetClientErrorReporterForTests()
})

describe('1. 上报体形状：恰好 8 个字段，path 只留 pathname', () => {
  it('字段集合逐字等于服务端白名单（多一个 / 少一个都红）', () => {
    const event = buildClientErrorEvent({
      source: 'error-boundary',
      error: new Error('boom'),
      pathname: '/orders/42',
    })
    // 服务端 `ClientErrorController.ClientErrorRequest` 的 8 个字段，逐字一致
    expect(Object.keys(event).sort()).toEqual(
      ['at', 'digest', 'message', 'name', 'path', 'source', 'stack', 'ua'],
    )
    expect(event.path).toBe('/orders/42')
    expect(event.name).toBe('Error')
    expect(event.message).toBe('boom')
    expect(event.source).toBe('error-boundary')
    // `at` 必须是可对时的 ISO-8601（服务端按 40 字符上限收）
    expect(Number.isNaN(Date.parse(event.at))).toBe(false)
    expect(event.at.length).toBeLessThanOrEqual(40)
  })

  it('path 剥掉 query / hash / 完整 URL 前缀（**这是「不含 token」的第一道防线**）', () => {
    expect(toPathOnly('/orders?token=leaked#frag')).toBe('/orders')
    expect(toPathOnly('https://merchant.migaozn.com/orders/1?x=1#y')).toBe('/orders/1')
    expect(toPathOnly('orders')).toBe('/orders')
    expect(toPathOnly('')).toBe('')
    expect(toPathOnly(undefined)).toBe('')
    expect(toPathOnly(`/${'a'.repeat(MAX_PATH_LENGTH + 50)}`).length).toBeLessThanOrEqual(
      MAX_PATH_LENGTH,
    )
  })

  it('buildClientErrorEvent 对 pathname 里的 query 同样剥掉（调用方忘了也不行）', () => {
    const event = buildClientErrorEvent({
      source: 'window.onerror',
      error: new Error('x'),
      pathname: '/dashboard?pin=123456',
    })
    expect(event.path).toBe('/dashboard')
    expect(JSON.stringify(event)).not.toContain('123456')
  })

  it('任意 unknown 都有确定的 name / message（null / undefined / 字符串 / 对象）', () => {
    expect(buildClientErrorEvent({ source: 'window.onerror', error: null }).name).toBe('NullThrown')
    expect(buildClientErrorEvent({ source: 'window.onerror', error: undefined }).name).toBe(
      'UndefinedThrown',
    )
    expect(buildClientErrorEvent({ source: 'window.onerror', error: 'plain' }).message).toBe('plain')
    expect(buildClientErrorEvent({ source: 'window.onerror', error: { message: 'obj-msg' } }).message)
      .toBe('obj-msg')
    // 没有栈 ⇒ 空串（**不伪造**）
    expect(buildClientErrorEvent({ source: 'window.onerror', error: 'plain' }).stack).toBe('')
  })
})

describe('2. 去敏：凭据 / 手机号 / query 一律不进上报体', () => {
  it('sanitizeText 逐项涂抹（JWT / Bearer / 键值 / 手机号 / query）', () => {
    const jwt = sanitizeText(`failed with ${FAKE_JWT}`, 300)
    expect(jwt).not.toContain(FAKE_JWT)
    expect(jwt).toContain('[redacted-jwt]')

    const bearer = sanitizeText('Authorization: Bearer abc.def.ghi', 300)
    expect(bearer).toBe('Authorization: Bearer [redacted]')

    // 键值形态逐项（单独喂，避免被下一条 query 规则整段覆盖 —— 两者是叠加的防线，见下一条断言）
    expect(sanitizeText(SECRET_PIN_KV, 300)).toBe('pin=[redacted]')
    expect(sanitizeText('phone=13800138000', 300)).toBe('phone=[redacted]')
    expect(sanitizeText('token=abc123token', 300)).toBe('token=[redacted]')
    expect(sanitizeText('password=hunter2', 300)).toBe('password=[redacted]')

    const phone = sanitizeText(`客户手机号 ${FAKE_PHONE} 打错了`, 300)
    expect(phone).not.toContain(FAKE_PHONE)
    expect(phone).toContain('[redacted-phone]')

    // 叠加防线：完整 URL 先被键值规则涂掉凭据值，整段 query 再被涂成 `[redacted-query]`
    // ⇒ 读者看不到任何键值（比只留 `pin=[redacted]` 更彻底，且不依赖某一条规则是否命中）
    const query = sanitizeText('GET /api/orders?page=1&x=2 失败', 300)
    expect(query).not.toContain('page=1')
    expect(query).toContain('[redacted-query]')

    const composed = sanitizeText(`retry /x?${SECRET_PIN_KV}&phone=13800138000`, 300)
    expect(composed).not.toContain('123456')
    expect(composed).not.toContain(FAKE_PHONE)
    expect(composed).toContain('[redacted-query]')
  })

  it('真实上报链路上：message / stack 里自带的凭据都不出现在请求体里', () => {
    const error = new Error(
      `请求失败 URL=/orders?token=leaked-query 凭据 ${FAKE_JWT} 手机 ${FAKE_PHONE} pin=998877`,
    )
    error.stack = `Error: ${error.message}\n    at Bearer abc.def.ghi`
    const result = reportClientError({ source: 'error-boundary', error, pathname: '/orders' })

    expect(result.sent).toBe(true)
    const raw = String((fetchMock.mock.calls[0][1] as RequestInit).body)
    for (const secret of ['leaked-query', FAKE_JWT, FAKE_PHONE, '998877', 'abc.def.ghi']) {
      expect(raw).not.toContain(secret)
    }
    expect(lastBody()).toMatchObject({ path: '/orders', source: 'error-boundary' })
  })
})

describe('3. 截断：超长字段按上限收，并让读日志的人看得出「这不是全文」', () => {
  it('message / stack 超过上限 ⇒ 截断 + 省略号，长度不超过上限', () => {
    const error = new Error('m'.repeat(MAX_MESSAGE_LENGTH + 100))
    error.stack = 's'.repeat(MAX_STACK_LENGTH + 100)
    const event = buildClientErrorEvent({ source: 'error-boundary', error })

    expect(event.message.length).toBe(MAX_MESSAGE_LENGTH)
    expect(event.message.endsWith('…')).toBe(true)
    expect(event.stack.length).toBe(MAX_STACK_LENGTH)
    expect(event.stack.endsWith('…')).toBe(true)
  })

  it('控制字符 / 换行压成单行（日志是一行事件，多行会把后续字段挤掉）', () => {
    expect(sanitizeText('a\nb\tc\r\nd', 100)).toBe('a b c d')
    expect(sanitizeText('a\u0000b', 100)).toBe('a b')
  })

  it('未超长的字段原样保留（不无脑截断）', () => {
    expect(sanitizeText('short message', 300)).toBe('short message')
  })
})

describe('4. 去重：同一错误短窗口内只发一次', () => {
  it('同 path|name|message|digest 的第二次上报被去重（fetch 只调一次）', () => {
    const first = reportClientError({ source: 'error-boundary', error: new Error('dup'), pathname: '/a' })
    const second = reportClientError({ source: 'error-boundary', error: new Error('dup'), pathname: '/a' })

    expect(first.sent).toBe(true)
    expect(second.sent).toBe(false)
    expect(second.reason).toBe('deduped')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('窗口过后可以再报（不是永久静音）', () => {
    const nowSpy = vi.spyOn(Date, 'now')
    nowSpy.mockReturnValue(1_000_000)
    expect(reportClientError({ source: 'error-boundary', error: new Error('later'), pathname: '/a' }).sent).toBe(true)

    nowSpy.mockReturnValue(1_000_000 + DEDUPE_WINDOW_MS - 1)
    expect(reportClientError({ source: 'error-boundary', error: new Error('later'), pathname: '/a' }).reason).toBe('deduped')

    nowSpy.mockReturnValue(1_000_000 + DEDUPE_WINDOW_MS)
    expect(reportClientError({ source: 'error-boundary', error: new Error('later'), pathname: '/a' }).sent).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('不同 path / 不同 message 是不同的错误（不被误去重）', () => {
    reportClientError({ source: 'error-boundary', error: new Error('same'), pathname: '/a' })
    reportClientError({ source: 'error-boundary', error: new Error('same'), pathname: '/b' })
    reportClientError({ source: 'error-boundary', error: new Error('other'), pathname: '/a' })
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })
})

describe('5. 失败不得影响页面：任何异常都不许冒出来', () => {
  it('fetch 同步抛 ⇒ sent=false / reason=send-failed，**不抛**', () => {
    vi.stubGlobal('fetch', vi.fn(() => {
      throw new Error('sync boom')
    }))
    const result = reportClientError({ source: 'window.onerror', error: new Error('x') })
    expect(result.sent).toBe(false)
    expect(result.reason).toBe('send-failed')
  })

  it('fetch 异步 reject（离线 / CORS / 5xx）⇒ 被吞掉，不产生 unhandled rejection', async () => {
    const rejections: unknown[] = []
    const onRejection = (reason: unknown) => rejections.push(reason)
    process.on('unhandledRejection', onRejection)
    try {
      vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('net down'))))
      const result = reportClientError({ source: 'window.onerror', error: new Error('net') })
      expect(result.sent).toBe(true) // 请求已发出；结果不在页面的事
      await new Promise((resolve) => setTimeout(resolve, 10))
      expect(rejections).toEqual([])
    } finally {
      process.off('unhandledRejection', onRejection)
    }
  })

  it('非浏览器环境（SSR / 预渲染）⇒ 短路 not-browser，不碰 fetch', () => {
    vi.stubGlobal('window', undefined)
    const result = reportClientError({ source: 'error-boundary', error: new Error('ssr') })
    expect(result.sent).toBe(false)
    expect(result.reason).toBe('not-browser')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('请求形态固定：POST + JSON + keepalive + 不带 cookie', () => {
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', 'https://api.example.com/')
    reportClientError({ source: 'error-boundary', error: new Error('shape'), pathname: '/x' })

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    // 尾斜杠被剥掉（否则会拼出 `//api/client-errors`）
    expect(url).toBe(`https://api.example.com${CLIENT_ERROR_ENDPOINT_PATH}`)
    expect(init.method).toBe('POST')
    expect(init.keepalive).toBe(true)
    // 上报面不携带任何会话凭据（cookie 也要 omit）
    expect(init.credentials).toBe('omit')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
  })
})

describe('6. 全局监听：addEventListener + 幂等 + 不覆盖别人的 handler', () => {
  type Listener = [string, (event: Event) => void]

  function fakeWindow(): { target: Window; listeners: Listener[]; onerror?: unknown } {
    const listeners: Listener[] = []
    const target = {
      onerror: undefined,
      addEventListener: (type: string, handler: (event: Event) => void) => listeners.push([type, handler]),
    } as unknown as Window
    return { target, listeners }
  }

  it('装上 error / unhandledrejection 两个监听，且**不覆写** onerror', () => {
    const { target, listeners } = fakeWindow()
    const original = vi.fn()
    ;(target as unknown as { onerror: unknown }).onerror = original

    expect(installClientErrorHandlers(target)).toBe(true)
    expect(listeners.map(([type]) => type)).toEqual(['error', 'unhandledrejection'])
    // 覆写 onerror 会吃掉监控 / 第三方库 / 既有守卫挂的 handler（行为回归）
    expect((target as unknown as { onerror: unknown }).onerror).toBe(original)
  })

  it('幂等：同一 window 装两次只装一份监听（第二次返回 false）', () => {
    const { target, listeners } = fakeWindow()
    expect(installClientErrorHandlers(target)).toBe(true)
    expect(installClientErrorHandlers(target)).toBe(false)
    expect(listeners).toHaveLength(2)
  })

  it('事件真的被转成上报：error ⇒ window.onerror，unhandledrejection ⇒ unhandledrejection', () => {
    const { target, listeners } = fakeWindow()
    installClientErrorHandlers(target)

    const errorEvent = new Event('error') as Event & { error?: unknown }
    errorEvent.error = new Error('render crashed')
    listeners.find(([type]) => type === 'error')?.[1](errorEvent)

    const rejectionEvent = new Event('unhandledrejection') as Event & { reason?: unknown }
    rejectionEvent.reason = new Error('promise rejected')
    listeners.find(([type]) => type === 'unhandledrejection')?.[1](rejectionEvent)

    expect(fetchMock).toHaveBeenCalledTimes(2)
    const sources = fetchMock.mock.calls
      .map((call) => JSON.parse(String((call[1] as RequestInit).body)).source)
      .sort()
    expect(sources).toEqual(['unhandledrejection', 'window.onerror'])
  })

  it('资源加载失败（只有 message、没有 error 对象）也会记一条', () => {
    const { target, listeners } = fakeWindow()
    installClientErrorHandlers(target)

    const event = new Event('error') as Event & { message?: string }
    event.message = 'Failed to load resource: /_next/static/chunk.js'
    listeners.find(([type]) => type === 'error')?.[1](event)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(lastBody().message).toContain('Failed to load resource')
  })
})
