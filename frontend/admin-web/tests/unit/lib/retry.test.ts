import { describe, test, expect, vi } from 'vitest'

/**
 * withRetry 算法单元测试
 *
 * 测试与 tests/e2e/helpers/retry.helper.ts 相同的算法。
 * vitest 无法解析 project-root 外部的 import，因此在此内联相同实现。
 */

interface RetryOptions {
  maxRetries?: number
  baseDelayMs?: number
  shouldRetry?: (error: any) => boolean
}

async function withRetry<T>(
  fn: () => Promise<T>,
  options: RetryOptions = {},
): Promise<T> {
  const { maxRetries = 3, baseDelayMs = 1000, shouldRetry = () => true } = options

  let lastError: any
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn()
    } catch (error) {
      lastError = error
      if (attempt === maxRetries || !shouldRetry(error)) {
        throw error
      }
      const delay = baseDelayMs * 2 ** attempt
      await new Promise((resolve) => setTimeout(resolve, delay))
    }
  }
  throw lastError
}

describe('withRetry', () => {
  test('succeeds on first attempt — no retries needed', async () => {
    const fn = vi.fn().mockResolvedValue('ok')
    const result = await withRetry(fn)
    expect(result).toBe('ok')
    expect(fn).toHaveBeenCalledTimes(1)
  })

  test('retries on failure and succeeds on 2nd attempt', async () => {
    const fn = vi.fn()
      .mockRejectedValueOnce(new Error('fail 1'))
      .mockResolvedValue('ok')

    const result = await withRetry(fn, { baseDelayMs: 0 })
    expect(result).toBe('ok')
    expect(fn).toHaveBeenCalledTimes(2)
  })

  test('succeeds on 3rd attempt (last retry)', async () => {
    const fn = vi.fn()
      .mockRejectedValueOnce(new Error('fail 1'))
      .mockRejectedValueOnce(new Error('fail 2'))
      .mockResolvedValue('ok')

    const result = await withRetry(fn, { baseDelayMs: 0 })
    expect(result).toBe('ok')
    expect(fn).toHaveBeenCalledTimes(3)
  })

  test('throws after exhausting all retries (default maxRetries=3 → 4 calls)', async () => {
    const fn = vi.fn().mockRejectedValue(new Error('always fail'))

    await expect(withRetry(fn, { baseDelayMs: 0 })).rejects.toThrow('always fail')
    expect(fn).toHaveBeenCalledTimes(4) // initial + 3 retries
  })

  test('throws after exhausting custom maxRetries', async () => {
    const fn = vi.fn().mockRejectedValue(new Error('fail'))

    await expect(withRetry(fn, { maxRetries: 1, baseDelayMs: 0 })).rejects.toThrow('fail')
    expect(fn).toHaveBeenCalledTimes(2) // initial + 1 retry
  })

  test('maxRetries=0 means no retries (only initial call)', async () => {
    const fn = vi.fn().mockRejectedValue(new Error('fail'))

    await expect(withRetry(fn, { maxRetries: 0, baseDelayMs: 0 })).rejects.toThrow('fail')
    expect(fn).toHaveBeenCalledTimes(1)
  })

  test('shouldRetry predicate — skips retry when false', async () => {
    const fn = vi.fn()
      .mockRejectedValueOnce(new Error('permanent error'))
      .mockResolvedValue('should not be called')

    await expect(
      withRetry(fn, {
        baseDelayMs: 0,
        shouldRetry: (err: Error) => err.message.includes('retry'),
      }),
    ).rejects.toThrow('permanent error')
    expect(fn).toHaveBeenCalledTimes(1) // no retry — shouldRetry returned false
  })

  test('shouldRetry predicate — retries when true', async () => {
    const fn = vi.fn()
      .mockRejectedValueOnce(new Error('transient error — please retry'))
      .mockResolvedValue('ok')

    const result = await withRetry(fn, {
      baseDelayMs: 0,
      shouldRetry: (err: Error) => err.message.includes('retry'),
    })
    expect(result).toBe('ok')
    expect(fn).toHaveBeenCalledTimes(2)
  })

  test('exponential backoff delays: baseDelay * 2^attempt', async () => {
    const fn = vi.fn()
      .mockRejectedValueOnce(new Error('e1'))
      .mockRejectedValueOnce(new Error('e2'))
      .mockRejectedValueOnce(new Error('e3'))
      .mockResolvedValue('ok')

    const start = Date.now()
    const result = await withRetry(fn, { baseDelayMs: 100 })
    const elapsed = Date.now() - start

    expect(result).toBe('ok')
    expect(fn).toHaveBeenCalledTimes(4)
    // Allow generous margin for timer imprecision
    expect(elapsed).toBeGreaterThanOrEqual(100 + 200 + 400 - 50)
  })

  test('throws the LAST error, not the first', async () => {
    // maxRetries=2: 3 calls total. The last rejection is what surfaces.
    const fn = vi.fn()
      .mockRejectedValueOnce(new Error('first error'))
      .mockRejectedValueOnce(new Error('second error'))
      .mockRejectedValueOnce(new Error('last error'))

    await expect(withRetry(fn, { maxRetries: 2, baseDelayMs: 0 })).rejects.toThrow('last error')
    expect(fn).toHaveBeenCalledTimes(3)
  })
})
