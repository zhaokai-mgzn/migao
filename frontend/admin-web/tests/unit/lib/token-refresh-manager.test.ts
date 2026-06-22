import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { InternalAxiosRequestConfig } from 'axios'

// ── Mock @/store/auth ──
const mockClearAuth = vi.fn()
const mockRefreshAccessToken = vi.fn()
const mockGetState = vi.fn()

vi.mock('@/store/auth', () => ({
  useAuthStore: {
    getState: () => mockGetState(),
  },
}))

// ── Prevent jsdom navigation when window.location.href is set ──
let hrefValue = ''
beforeEach(() => {
  hrefValue = ''
  try {
    // jsdom allows replacing the location descriptor in practice
    Object.defineProperty(window, 'location', {
      configurable: true,
      enumerable: true,
      value: new Proxy(window.location, {
        get(target, prop) {
          if (prop === 'href') return hrefValue || target.href
          return Reflect.get(target, prop)
        },
        set(target, prop, value) {
          if (prop === 'href') {
            hrefValue = value as string
            return true
          }
          return Reflect.set(target, prop, value)
        },
      }),
    })
  } catch {
    // If defineProperty fails (rare), tests still run — jsdom tolerates href sets
  }
})

import { TokenRefreshManager } from '@/lib/token-refresh-manager'

// ── Helpers ──
function createMockConfig(url: string, headers?: Record<string, string>): InternalAxiosRequestConfig {
  return {
    url,
    headers: headers ?? { Authorization: 'Bearer old-token' },
  } as InternalAxiosRequestConfig
}

// ── Tests ──
describe('TokenRefreshManager', () => {
  let mockAxiosInstance: ReturnType<typeof vi.fn>
  let manager: TokenRefreshManager

  beforeEach(() => {
    vi.clearAllMocks()

    mockAxiosInstance = vi.fn()
    manager = new TokenRefreshManager(mockAxiosInstance as any)

    mockGetState.mockReturnValue({
      clearAuth: mockClearAuth,
      refreshAccessToken: mockRefreshAccessToken,
    })
  })

  // ──────────────────────────────────────────────────────────
  // getQueueStatus()
  // ──────────────────────────────────────────────────────────
  describe('getQueueStatus()', () => {
    it('should return initial idle state', () => {
      expect(manager.getQueueStatus()).toEqual({ isRefreshing: false, queueLength: 0 })
    })

    it('should report isRefreshing=true while refresh is in progress', async () => {
      // Hold the refresh promise so we can inspect mid-flight state
      let resolveRefresh!: (value: string) => void
      mockRefreshAccessToken.mockReturnValue(
        new Promise<string>((resolve) => { resolveRefresh = resolve })
      )

      const promise = manager.handle401Error(createMockConfig('/api/data'))

      expect(manager.getQueueStatus().isRefreshing).toBe(true)

      // Clean up
      mockAxiosInstance.mockResolvedValue({ data: 'ok' })
      resolveRefresh('new-token')
      await promise
    })

    it('should report isRefreshing=false after refresh completes', async () => {
      mockRefreshAccessToken.mockResolvedValue('new-token')
      mockAxiosInstance.mockResolvedValue({ data: 'ok' })

      await manager.handle401Error(createMockConfig('/api/data'))

      expect(manager.getQueueStatus().isRefreshing).toBe(false)
    })

    it('should report correct queueLength when requests are queued', async () => {
      let resolveRefresh!: (value: string) => void
      mockRefreshAccessToken.mockReturnValue(
        new Promise<string>((resolve) => { resolveRefresh = resolve })
      )

      // First call → starts refresh
      const p1 = manager.handle401Error(createMockConfig('/api/r1'))
      // Second call → queued
      const p2 = manager.handle401Error(createMockConfig('/api/r2'))
      // Third call → queued
      const p3 = manager.handle401Error(createMockConfig('/api/r3'))

      expect(manager.getQueueStatus().queueLength).toBe(2)

      // Clean up
      mockAxiosInstance.mockResolvedValue({ data: 'ok' })
      resolveRefresh('new-token')
      await Promise.all([p1, p2, p3])
    })
  })

  // ──────────────────────────────────────────────────────────
  // reset()
  // ──────────────────────────────────────────────────────────
  describe('reset()', () => {
    it('should reset to initial state from idle', () => {
      manager.reset()
      expect(manager.getQueueStatus()).toEqual({ isRefreshing: false, queueLength: 0 })
    })

    it('should reset after calling multiple times', () => {
      manager.reset()
      manager.reset()
      expect(manager.getQueueStatus()).toEqual({ isRefreshing: false, queueLength: 0 })
    })
  })

  // ──────────────────────────────────────────────────────────
  // handle401Error — auth endpoints (direct reject)
  // ──────────────────────────────────────────────────────────
  describe('handle401Error - auth endpoints', () => {
    it('should reject login endpoint without calling refreshAccessToken', async () => {
      const config = createMockConfig('/api/auth/admin/login')

      await expect(manager.handle401Error(config)).rejects.toThrow('Authentication failed')
      expect(mockClearAuth).toHaveBeenCalledTimes(1)
      expect(mockRefreshAccessToken).not.toHaveBeenCalled()
      expect(manager.getQueueStatus().isRefreshing).toBe(false)
    })

    it('should reject refresh endpoint without calling refreshAccessToken', async () => {
      const config = createMockConfig('/api/auth/refresh')

      await expect(manager.handle401Error(config)).rejects.toThrow('Authentication failed')
      expect(mockClearAuth).toHaveBeenCalledTimes(1)
      expect(mockRefreshAccessToken).not.toHaveBeenCalled()
    })

    it('should handle URL with path prefix before /api/auth/refresh', async () => {
      const config = createMockConfig('https://api.migaozn.com/api/auth/refresh')

      await expect(manager.handle401Error(config)).rejects.toThrow('Authentication failed')
      expect(mockClearAuth).toHaveBeenCalledTimes(1)
    })

    it('should reject when url is empty string', async () => {
      const config = createMockConfig('')

      // Empty string doesn't include auth paths, so it goes to normal flow
      mockRefreshAccessToken.mockResolvedValue('new-token')
      mockAxiosInstance.mockResolvedValue({ data: 'ok' })

      const result = await manager.handle401Error(config)
      expect(result).toEqual({ data: 'ok' })
      expect(mockRefreshAccessToken).toHaveBeenCalled()
    })
  })

  // ──────────────────────────────────────────────────────────
  // handle401Error — queue while refreshing
  // ──────────────────────────────────────────────────────────
  describe('handle401Error - concurrent requests (queue)', () => {
    it('should queue subsequent requests while refresh is in progress', async () => {
      let resolveRefresh!: (value: string) => void
      mockRefreshAccessToken.mockReturnValue(
        new Promise<string>((resolve) => { resolveRefresh = resolve })
      )

      // First call starts refresh → returns a promise (the retry)
      const p1 = manager.handle401Error(createMockConfig('/api/data1'))

      // Second call sees isRefreshing=true → queued, returns a new Promise
      const p2 = manager.handle401Error(createMockConfig('/api/data2'))

      expect(manager.getQueueStatus()).toEqual({ isRefreshing: true, queueLength: 1 })
      expect(p2).toBeInstanceOf(Promise)

      // Clean up
      mockAxiosInstance.mockResolvedValue({ data: 'ok' })
      resolveRefresh('new-token')
      await Promise.all([p1, p2])
    })

    it('should resolve queued requests with new token on refresh success', async () => {
      mockRefreshAccessToken.mockResolvedValue('new-token-abc')
      mockAxiosInstance.mockResolvedValue({ data: 'retry-result' })

      // Both calls start at the same microtask - the second gets queued
      const p1 = manager.handle401Error(createMockConfig('/api/a'))
      const p2 = manager.handle401Error(createMockConfig('/api/b'))

      // p1 should resolve with the retried axios result
      const result1 = await p1
      expect(result1).toEqual({ data: 'retry-result' })

      // p2 should resolve with the new token string
      const result2 = await p2
      expect(result2).toBe('new-token-abc')

      expect(manager.getQueueStatus()).toEqual({ isRefreshing: false, queueLength: 0 })
    })

    it('should reject queued requests when refresh returns null', async () => {
      mockRefreshAccessToken.mockResolvedValue(null)

      const p1 = manager.handle401Error(createMockConfig('/api/a'))
      const p2 = manager.handle401Error(createMockConfig('/api/b'))

      await expect(p1).rejects.toThrow('Token refresh failed')
      await expect(p2).rejects.toThrow('Token refresh failed')

      expect(mockClearAuth).toHaveBeenCalledTimes(1)
      expect(manager.getQueueStatus().isRefreshing).toBe(false)
      expect(manager.getQueueStatus().queueLength).toBe(0)
    })

    it('should reject queued requests when refresh throws', async () => {
      const refreshError = new Error('Network timeout')
      mockRefreshAccessToken.mockRejectedValue(refreshError)

      const p1 = manager.handle401Error(createMockConfig('/api/a'))
      const p2 = manager.handle401Error(createMockConfig('/api/b'))

      await expect(p1).rejects.toThrow('Network timeout')
      await expect(p2).rejects.toThrow('Network timeout')

      expect(mockClearAuth).toHaveBeenCalledTimes(1)
      expect(manager.getQueueStatus().isRefreshing).toBe(false)
    })

    it('should clear queue after processing', async () => {
      mockRefreshAccessToken.mockResolvedValue('fresh-token')
      mockAxiosInstance.mockResolvedValue({ data: 'ok' })

      const p1 = manager.handle401Error(createMockConfig('/api/a'))
      const p2 = manager.handle401Error(createMockConfig('/api/b'))
      const p3 = manager.handle401Error(createMockConfig('/api/c'))

      await Promise.all([p1, p2, p3])

      expect(manager.getQueueStatus().queueLength).toBe(0)
    })
  })

  // ──────────────────────────────────────────────────────────
  // handle401Error — refresh success
  // ──────────────────────────────────────────────────────────
  describe('handle401Error - refresh success', () => {
    it('should call refreshAccessToken', async () => {
      mockRefreshAccessToken.mockResolvedValue('new-token')
      mockAxiosInstance.mockResolvedValue({ data: 'ok' })

      await manager.handle401Error(createMockConfig('/api/data'))

      expect(mockRefreshAccessToken).toHaveBeenCalledTimes(1)
    })

    it('should set new Authorization header on original request', async () => {
      mockRefreshAccessToken.mockResolvedValue('shiny-new-token')
      mockAxiosInstance.mockResolvedValue({ data: 'ok' })

      const config = createMockConfig('/api/data')
      await manager.handle401Error(config)

      expect(config.headers.Authorization).toBe('Bearer shiny-new-token')
    })

    it('should set _retry flag on original request', async () => {
      mockRefreshAccessToken.mockResolvedValue('new-token')
      mockAxiosInstance.mockResolvedValue({ data: 'ok' })

      const config = createMockConfig('/api/data')
      await manager.handle401Error(config)

      expect((config as any)._retry).toBe(true)
    })

    it('should retry the original request via axios instance with updated config', async () => {
      mockRefreshAccessToken.mockResolvedValue('new-token')
      mockAxiosInstance.mockResolvedValue({ data: 'retried-response' })

      const config = createMockConfig('/api/data')
      const result = await manager.handle401Error(config)

      expect(mockAxiosInstance).toHaveBeenCalledTimes(1)
      expect(mockAxiosInstance).toHaveBeenCalledWith(config)
      expect(result).toEqual({ data: 'retried-response' })
    })

    it('should work with different URL paths', async () => {
      mockRefreshAccessToken.mockResolvedValue('tok')
      mockAxiosInstance.mockResolvedValue({ data: 'products' })

      const result = await manager.handle401Error(createMockConfig('/api/products/list'))

      expect(result).toEqual({ data: 'products' })
    })

    it('should override existing Authorization header', async () => {
      mockRefreshAccessToken.mockResolvedValue('final-token')
      mockAxiosInstance.mockResolvedValue({ data: 'ok' })

      const config = createMockConfig('/api/data', { Authorization: 'Bearer stale-token' })
      await manager.handle401Error(config)

      expect(config.headers.Authorization).toBe('Bearer final-token')
    })
  })

  // ──────────────────────────────────────────────────────────
  // handle401Error — refresh returns null
  // ──────────────────────────────────────────────────────────
  describe('handle401Error - refresh returns null', () => {
    it('should call clearAuth', async () => {
      mockRefreshAccessToken.mockResolvedValue(null)

      await expect(manager.handle401Error(createMockConfig('/api/data')))
        .rejects.toThrow('Token refresh failed')

      expect(mockClearAuth).toHaveBeenCalledTimes(1)
    })

    it('should not retry the request via axios instance', async () => {
      mockRefreshAccessToken.mockResolvedValue(null)

      await expect(manager.handle401Error(createMockConfig('/api/data')))
        .rejects.toThrow('Token refresh failed')

      expect(mockAxiosInstance).not.toHaveBeenCalled()
    })

    it('should set isRefreshing to false in finally block', async () => {
      mockRefreshAccessToken.mockResolvedValue(null)

      await expect(manager.handle401Error(createMockConfig('/api/data')))
        .rejects.toThrow('Token refresh failed')

      expect(manager.getQueueStatus().isRefreshing).toBe(false)
    })

    it('should redirect via window.location.href', async () => {
      mockRefreshAccessToken.mockResolvedValue(null)

      await expect(manager.handle401Error(createMockConfig('/api/data')))
        .rejects.toThrow('Token refresh failed')

      expect(hrefValue).toBe('/login')
    })
  })

  // ──────────────────────────────────────────────────────────
  // handle401Error — refresh throws
  // ──────────────────────────────────────────────────────────
  describe('handle401Error - refresh throws', () => {
    it('should propagate the original error', async () => {
      const originalError = new Error('refresh API 500')
      mockRefreshAccessToken.mockRejectedValue(originalError)

      await expect(manager.handle401Error(createMockConfig('/api/data')))
        .rejects.toThrow('refresh API 500')
    })

    it('should call clearAuth on refresh error', async () => {
      mockRefreshAccessToken.mockRejectedValue(new Error('timeout'))

      await expect(manager.handle401Error(createMockConfig('/api/data')))
        .rejects.toThrow('timeout')

      expect(mockClearAuth).toHaveBeenCalledTimes(1)
    })

    it('should not retry via axios instance on refresh error', async () => {
      mockRefreshAccessToken.mockRejectedValue(new Error('fail'))

      await expect(manager.handle401Error(createMockConfig('/api/data')))
        .rejects.toThrow('fail')

      expect(mockAxiosInstance).not.toHaveBeenCalled()
    })

    it('should set isRefreshing to false via finally on error', async () => {
      mockRefreshAccessToken.mockRejectedValue(new Error('fail'))

      await expect(manager.handle401Error(createMockConfig('/api/data')))
        .rejects.toThrow('fail')

      expect(manager.getQueueStatus().isRefreshing).toBe(false)
    })

    it('should redirect via window.location.href on refresh error', async () => {
      mockRefreshAccessToken.mockRejectedValue(new Error('fail'))

      await expect(manager.handle401Error(createMockConfig('/api/data')))
        .rejects.toThrow('fail')

      expect(hrefValue).toBe('/login')
    })
  })

  // ──────────────────────────────────────────────────────────
  // Edge cases
  // ──────────────────────────────────────────────────────────
  describe('edge cases', () => {
    it('should handle config with empty headers object', async () => {
      mockRefreshAccessToken.mockResolvedValue('tok')
      mockAxiosInstance.mockResolvedValue({ data: 'ok' })

      const config = createMockConfig('/api/orders', {})

      const result = await manager.handle401Error(config)

      expect(result).toEqual({ data: 'ok' })
      expect(config.headers.Authorization).toBe('Bearer tok')
    })

    it('should handle multiple sequential refreshes correctly', async () => {
      // First refresh
      mockRefreshAccessToken.mockResolvedValue('token-1')
      mockAxiosInstance.mockResolvedValue({ data: 'first' })
      await manager.handle401Error(createMockConfig('/api/a'))

      expect(manager.getQueueStatus().isRefreshing).toBe(false)

      // Second refresh (after first completed)
      mockRefreshAccessToken.mockResolvedValue('token-2')
      mockAxiosInstance.mockResolvedValue({ data: 'second' })
      const result = await manager.handle401Error(createMockConfig('/api/b'))

      expect(result).toEqual({ data: 'second' })
      expect(mockRefreshAccessToken).toHaveBeenCalledTimes(2)
    })

    it('should handle url with auth substring that is not actually an auth endpoint', async () => {
      // Only exact path matching — /api/auth/refresh must appear in the URL
      // A URL like /api/data-auth-refresh does NOT match /api/auth/refresh
      mockRefreshAccessToken.mockResolvedValue('tok')
      mockAxiosInstance.mockResolvedValue({ data: 'ok' })

      const config = createMockConfig('/api/something-auth-not-matching')
      const result = await manager.handle401Error(config)

      expect(result).toEqual({ data: 'ok' })
      expect(mockClearAuth).not.toHaveBeenCalled()
    })

    it('should handle a single request through full happy path end-to-end', async () => {
      mockRefreshAccessToken.mockResolvedValue('e2e-token')
      mockAxiosInstance.mockResolvedValue({ data: 'e2e-result' })

      const config = createMockConfig('/api/products')
      const result = await manager.handle401Error(config)

      expect(result).toEqual({ data: 'e2e-result' })
      expect(config.headers.Authorization).toBe('Bearer e2e-token')
      expect((config as any)._retry).toBe(true)
      expect(mockAxiosInstance).toHaveBeenCalledTimes(1)
      expect(mockAxiosInstance).toHaveBeenCalledWith(config)
      expect(manager.getQueueStatus()).toEqual({ isRefreshing: false, queueLength: 0 })
    })
  })
})
