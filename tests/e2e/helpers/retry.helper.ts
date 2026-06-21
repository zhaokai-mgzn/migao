/**
 * Retry helper — exponential backoff for transient HTTP failures.
 *
 * Used by record-fixtures and E2E auth to survive temporary dev-server outages.
 */

export interface RetryOptions {
  /** Max retry attempts (default 3). Total calls = 1 + maxRetries. */
  maxRetries?: number
  /** Base delay in ms (default 1000). Delay = baseDelay * 2^attempt (exponential). */
  baseDelayMs?: number
  /**
   * Optional predicate — only retry if this returns true.
   * Default: retries on all errors.
   * Use to skip retry on permanent errors (4xx, etc.).
   */
  shouldRetry?: (error: any) => boolean
}

/**
 * Execute fn with exponential backoff retry.
 *
 * On failure, retries up to maxRetries times with delays: 1s, 2s, 4s, ...
 * If all attempts fail, throws the last error.
 *
 * @example
 *   const data = await withRetry(() => ctx.post(url, { data }), { maxRetries: 3 })
 */
export async function withRetry<T>(
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
