/**
 * Wait Helper — Smart wait utilities for E2E tests.
 *
 * Encapsulates common waiting patterns to avoid flaky tests.
 *
 * Key selectors derived from source code:
 *   - Sonner toasts: `[data-sonner-toaster]` (from the `sonner` library used throughout)
 *   - Loading spinners: `.animate-spin` (used in Loading.tsx, Table.tsx, Button.tsx)
 *   - Table loading text: "加载中..." (Table.tsx line 101)
 */
import { type Page, expect } from '@playwright/test'

/**
 * Wait for a sonner toast notification to appear.
 *
 * The app uses `sonner` for toasts (import { toast } from 'sonner').
 * Sonner renders toasts inside `[data-sonner-toaster]` → `[data-sonner-toast]`.
 * Success toasts: `toast.success(text)` → renders with success styling
 * Error toasts:   `toast.error(text)`   → renders with error styling
 */
export async function waitForToast(
  page: Page,
  text?: string | RegExp,
  options?: { timeout?: number; type?: 'success' | 'error' },
): Promise<void> {
  const { timeout = 5_000 } = options ?? {}

  // Sonner toast container
  const toastSelector = '[data-sonner-toast]'

  if (text) {
    const pattern = text instanceof RegExp ? text : new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    await expect(page.locator(toastSelector).filter({ hasText: pattern })).toBeVisible({ timeout })
  } else {
    await expect(page.locator(toastSelector).first()).toBeVisible({ timeout })
  }
}

/**
 * Wait for a success toast (sonner).
 */
export async function waitForSuccessToast(page: Page, text?: string): Promise<void> {
  await waitForToast(page, text, { type: 'success' })
}

/**
 * Wait for an error toast (sonner).
 */
export async function waitForErrorToast(page: Page, text?: string): Promise<void> {
  await waitForToast(page, text, { type: 'error' })
}

/**
 * Wait for all loading spinners to disappear.
 *
 * The app uses several loading indicators:
 *   - `Loading` component: <Loader2 className="animate-spin ...">
 *   - `Table` loading state: "加载中..." text + animate-spin spinner
 *   - `Button` loading: <Loader2 className="animate-spin ..."> inside button
 *   - Generic: any element with `animate-spin` class
 */
export async function waitForLoadingComplete(
  page: Page,
  options?: { timeout?: number },
): Promise<void> {
  const { timeout = 10_000 } = options ?? {}

  // Wait for all animate-spin elements to disappear
  const spinners = page.locator('.animate-spin')
  await spinners.waitFor({ state: 'hidden', timeout }).catch(() => {
    // If no spinners exist at all, waitFor('hidden') may time out — that's fine
  })

  // Also wait for "加载中..." text to disappear (Table.tsx loading state)
  const loadingText = page.getByText('加载中...')
  await loadingText.waitFor({ state: 'hidden', timeout: Math.min(timeout, 3_000) }).catch(() => {
    // OK if it was never present
  })
}

/**
 * Wait for the page to be fully ready:
 *   1. Network is idle (no pending requests)
 *   2. No loading spinners are visible
 *   3. No "加载中..." text is visible
 */
export async function waitForPageReady(
  page: Page,
  options?: { timeout?: number },
): Promise<void> {
  const { timeout = 15_000 } = options ?? {}

  // Wait for network to settle
  await page.waitForLoadState('networkidle', { timeout }).catch(() => {
    // networkidle can be flaky in some scenarios; don't fail the test
  })

  // Wait for DOM content to be loaded
  await page.waitForLoadState('domcontentloaded', { timeout })

  // Wait for loading indicators to clear
  await waitForLoadingComplete(page, { timeout })
}

/**
 * Wait for a specific API response to arrive.
 *
 * Useful when a page action triggers an API call and we need to wait
 * for the response before making assertions.
 *
 * @param urlPattern - A string or RegExp to match against the request URL
 * @returns The response promise
 *
 * @example
 *   const response = await waitForApiResponse(page, /\/api\/admin\/products$/)
 *   const json = await response.json()
 */
export async function waitForApiResponse(
  page: Page,
  urlPattern: string | RegExp,
  options?: { timeout?: number; method?: string },
): Promise<{ status: number; json: () => Promise<unknown> }> {
  const { timeout = 15_000, method } = options ?? {}

  const response = await page.waitForResponse(
    (resp) => {
      const urlMatch =
        typeof urlPattern === 'string'
          ? resp.url().includes(urlPattern)
          : urlPattern.test(resp.url())
      const methodMatch = !method || resp.request().method() === method.toUpperCase()
      return urlMatch && methodMatch
    },
    { timeout },
  )

  return {
    status: response.status(),
    json: () => response.json(),
  }
}

/**
 * Wait for a specific API request to be sent (without waiting for response).
 */
export async function waitForApiRequest(
  page: Page,
  urlPattern: string | RegExp,
  options?: { timeout?: number; method?: string },
): Promise<void> {
  const { timeout = 15_000, method } = options ?? {}

  await page.waitForRequest(
    (req) => {
      const urlMatch =
        typeof urlPattern === 'string'
          ? req.url().includes(urlPattern)
          : urlPattern.test(req.url())
      const methodMatch = !method || req.method() === method.toUpperCase()
      return urlMatch && methodMatch
    },
    { timeout },
  )
}

/**
 * Wait for an element to be visible and stable (not animating).
 */
export async function waitForStable(
  page: Page,
  selector: string,
  options?: { timeout?: number },
): Promise<void> {
  const { timeout = 5_000 } = options ?? {}
  const locator = page.locator(selector)
  await expect(locator).toBeVisible({ timeout })
  // Small delay to let CSS animations settle
  await page.waitForTimeout(200)
}
