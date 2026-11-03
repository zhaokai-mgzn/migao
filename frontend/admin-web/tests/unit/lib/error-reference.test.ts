// case_ids: MC-139
// （MC-139 = 「商家可见的失败提示与服务端 incident 用同一个 requestId 串联」的行为用例；
//   同族承载体：backend 的 RequestIdTraceabilityTest / ErrorResponseRequestIdMetaGuardTest。）
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { toast } from 'sonner'

import {
  ERROR_REFERENCE_COPY_LABEL,
  ERROR_REFERENCE_HINT,
  readErrorReference,
  showRequestErrorToast,
} from '@/lib/error-reference'

/**
 * issue #6957：失败提示**带出服务端追踪编号**（客服据此反查 incident），且**不是**把响应体 JSON 打印出来。
 *
 * 红证（注入式）：把 `request.ts` 里 `showRequestErrorToast(...)` 改回 `toast.error(...)`
 * ⇒ 本文件第 3 组 + `request.test.ts` 的「失败提示里的追踪编号」组当场红。
 */
describe('readErrorReference', () => {
  it('从服务端信封里取 requestId 与机读 code', () => {
    expect(
      readErrorReference({
        success: false,
        requestId: 'req_1a2b3c4d5e6f7a8b',
        error: { code: 'INTERNAL_ERROR', message: '服务器内部错误' },
      })
    ).toEqual({ requestId: 'req_1a2b3c4d5e6f7a8b', code: 'INTERNAL_ERROR' })
  })

  it('没有 requestId / 形状不合法 ⇒ null（不展示，也不猜）', () => {
    expect(readErrorReference({ success: false })).toBeNull()
    expect(readErrorReference(null)).toBeNull()
    expect(readErrorReference(undefined)).toBeNull()
    expect(readErrorReference('req_1a2b3c4d5e6f7a8b')).toBeNull()
    expect(readErrorReference({ requestId: 'has space in it' })).toBeNull()
    expect(readErrorReference({ requestId: 'short' })).toBeNull()
    expect(readErrorReference({ requestId: 'x'.repeat(65) })).toBeNull()
    expect(readErrorReference({ requestId: 42 })).toBeNull()
  })

  it('只有 requestId、没有 error.code 也照样可用', () => {
    expect(readErrorReference({ requestId: 'req_abcdef0123456789' })).toEqual({
      requestId: 'req_abcdef0123456789',
    })
  })
})

describe('showRequestErrorToast', () => {
  const REQUEST_ID = 'req_1a2b3c4d5e6f7a8b'
  let writeText: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.clearAllMocks()
    writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(globalThis.navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
  })

  afterEach(() => {
    // @ts-expect-error jsdom 里 clipboard 可能不存在；测试内显式清掉，避免串到别的用例
    delete globalThis.navigator.clipboard
  })

  it('有 requestId ⇒ 第一行仍是人话，第二行是这串编号（可复制）', () => {
    showRequestErrorToast('服务器内部错误', {
      success: false,
      requestId: REQUEST_ID,
      error: { code: 'INTERNAL_ERROR', message: '服务器内部错误' },
    })

    const [message, options] = vi.mocked(toast.error).mock.calls[0]
    expect(message).toBe('服务器内部错误')
    const description = String((options as { description?: unknown }).description)
    expect(description).toContain(REQUEST_ID)
    expect(description).toContain(ERROR_REFERENCE_HINT)
    // 🔴 不是把整个响应体 JSON 端给商家，也不把机读错误码摆上屏（§31 P3）
    expect(description).not.toContain('{')
    expect(description).not.toContain('INTERNAL_ERROR')
    expect((options as { action?: { label?: string } }).action?.label).toBe(
      ERROR_REFERENCE_COPY_LABEL
    )
  })

  it('点「复制编号」把 requestId 写进剪贴板', () => {
    showRequestErrorToast('服务器内部错误', { requestId: REQUEST_ID })
    const [, options] = vi.mocked(toast.error).mock.calls[0]
    ;(options as unknown as { action: { onClick: () => void } }).action.onClick()
    expect(writeText).toHaveBeenCalledWith(REQUEST_ID)
  })

  it('没有 requestId ⇒ 与改前逐字相同（一个参数的纯文案）', () => {
    showRequestErrorToast('服务器内部错误', { success: false })
    expect(toast.error).toHaveBeenCalledTimes(1)
    expect(toast.error).toHaveBeenCalledWith('服务器内部错误')
    expect(vi.mocked(toast.error).mock.calls[0]).toHaveLength(1)
  })

  it('剪贴板不可用 ⇒ 不抛（提示本身不能因复制失败而消失）', () => {
    Object.defineProperty(globalThis.navigator, 'clipboard', {
      configurable: true,
      value: undefined,
    })
    expect(() => showRequestErrorToast('服务器内部错误', { requestId: REQUEST_ID })).not.toThrow()
    const [, options] = vi.mocked(toast.error).mock.calls[0]
    expect(() =>
      (options as unknown as { action: { onClick: () => void } }).action.onClick()
    ).not.toThrow()
  })
})
