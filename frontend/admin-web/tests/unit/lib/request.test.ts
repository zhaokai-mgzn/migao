import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import axios from 'axios'
import type { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import { toast } from 'sonner'

// Mock the auth store before importing request
const mockGetState = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: {
    getState: () => mockGetState(),
  },
}))

// Import request after mocks are set up
import request from '@/lib/request'

describe('request (Axios instance)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default mock: no token
    mockGetState.mockReturnValue({
      accessToken: null,
      refreshToken: null,
      clearAuth: vi.fn(),
      refreshAccessToken: vi.fn(),
    })
  })

  describe('request interceptor', () => {
    it('should add Authorization header when token exists', async () => {
      mockGetState.mockReturnValue({
        accessToken: 'test-token-123',
        refreshToken: null,
        clearAuth: vi.fn(),
        refreshAccessToken: vi.fn(),
      })

      let capturedConfig: InternalAxiosRequestConfig | null = null
      const mockAdapter = vi.fn().mockImplementation((config: InternalAxiosRequestConfig) => {
        capturedConfig = config
        return Promise.resolve({
          status: 200,
          data: { code: 200 },
          headers: {},
          config,
          statusText: 'OK',
        })
      })

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      await request.get('/test')

      request.defaults.adapter = originalAdapter

      expect(capturedConfig).not.toBeNull()
      expect(capturedConfig!.headers.Authorization).toBe('Bearer test-token-123')
    })

    it('should not add Authorization header when no token', async () => {
      mockGetState.mockReturnValue({
        accessToken: null,
        refreshToken: null,
        clearAuth: vi.fn(),
        refreshAccessToken: vi.fn(),
      })

      let capturedConfig: InternalAxiosRequestConfig | null = null
      const mockAdapter = vi.fn().mockImplementation((config: InternalAxiosRequestConfig) => {
        capturedConfig = config
        return Promise.resolve({
          status: 200,
          data: { code: 200 },
          headers: {},
          config,
          statusText: 'OK',
        })
      })

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      await request.get('/test')

      request.defaults.adapter = originalAdapter

      expect(capturedConfig).not.toBeNull()
      expect(capturedConfig!.headers.Authorization).toBeUndefined()
    })
  })

  describe('response interceptor - success', () => {
    it('should pass through response when success is true', async () => {
      const mockAdapter = vi.fn().mockResolvedValue({
        status: 200,
        data: { success: true, data: { id: 1 } },
        headers: {},
        config: {} as InternalAxiosRequestConfig,
        statusText: 'OK',
      })

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      const response = await request.get('/test')
      expect(response.data).toEqual({ success: true, data: { id: 1 } })

      request.defaults.adapter = originalAdapter
    })

    it('should reject when success is false', async () => {
      const mockAdapter = vi.fn().mockResolvedValue({
        status: 200,
        data: { success: false, error: { code: "VALIDATION_ERROR", message: '参数错误' } },
        headers: {},
        config: {} as InternalAxiosRequestConfig,
        statusText: 'OK',
      })

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      await expect(request.get('/test')).rejects.toThrow('参数错误')
      expect(toast.error).toHaveBeenCalledWith('参数错误')

      request.defaults.adapter = originalAdapter
    })

    it('should use default error message when success is false without error message', async () => {
      const mockAdapter = vi.fn().mockResolvedValue({
        status: 200,
        data: { success: false },
        headers: {},
        config: {} as InternalAxiosRequestConfig,
        statusText: 'OK',
      })

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      await expect(request.get('/test')).rejects.toThrow('请求失败')
      expect(toast.error).toHaveBeenCalledWith('请求失败')

      request.defaults.adapter = originalAdapter
    })

    it('should pass through response when no code field (raw data)', async () => {
      const mockAdapter = vi.fn().mockResolvedValue({
        status: 200,
        data: { name: 'test' },
        headers: {},
        config: {} as InternalAxiosRequestConfig,
        statusText: 'OK',
      })

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      const response = await request.get('/test')
      expect(response.data).toEqual({ name: 'test' })

      request.defaults.adapter = originalAdapter
    })
  })

  describe('response interceptor - HTTP errors', () => {
    it('should show toast for 403 error', async () => {
      const mockAdapter = vi.fn().mockRejectedValue(
        createAxiosError(403, { message: 'Forbidden' })
      )

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      await expect(request.get('/test')).rejects.toBeDefined()
      expect(toast.error).toHaveBeenCalledWith('没有权限执行此操作')

      request.defaults.adapter = originalAdapter
    })

    it('should show toast for 404 error', async () => {
      const mockAdapter = vi.fn().mockRejectedValue(
        createAxiosError(404, { message: 'Not Found' })
      )

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      await expect(request.get('/test')).rejects.toBeDefined()
      expect(toast.error).toHaveBeenCalledWith('请求的资源不存在')

      request.defaults.adapter = originalAdapter
    })

    it('should show toast for 500 error', async () => {
      const mockAdapter = vi.fn().mockRejectedValue(
        createAxiosError(500, { message: 'Internal Server Error' })
      )

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      await expect(request.get('/test')).rejects.toBeDefined()
      expect(toast.error).toHaveBeenCalledWith('服务器内部错误')

      request.defaults.adapter = originalAdapter
    })

    it('should show network error toast when no response', async () => {
      const error = new Error('Network Error') as AxiosError
      error.isAxiosError = true
      error.config = { url: '/test', headers: {} } as InternalAxiosRequestConfig
      error.request = {}
      error.response = undefined
      error.toJSON = () => ({})

      const mockAdapter = vi.fn().mockRejectedValue(error)

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      await expect(request.get('/test')).rejects.toBeDefined()
      expect(toast.error).toHaveBeenCalledWith('网络连接失败，请检查网络设置')

      request.defaults.adapter = originalAdapter
    })
  })

  describe('response interceptor - 401 and token refresh', () => {
    it('should attempt token refresh on 401 and retry request', async () => {
      const mockClearAuth = vi.fn()
      const mockRefreshAccessToken = vi.fn().mockResolvedValue('new-token-456')
      mockGetState.mockReturnValue({
        accessToken: 'expired-token',
        refreshToken: 'refresh-token',
        clearAuth: mockClearAuth,
        refreshAccessToken: mockRefreshAccessToken,
      })

      let callCount = 0
      const mockAdapter = vi.fn().mockImplementation((config: InternalAxiosRequestConfig) => {
        callCount++
        if (callCount === 1) {
          // First call: 401
          return Promise.reject(createAxiosError(401, { message: 'Unauthorized' }, config))
        }
        // Retry after refresh: success
        return Promise.resolve({
          status: 200,
          data: { code: 200, data: { result: 'ok' } },
          headers: {},
          config,
          statusText: 'OK',
        })
      })

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      const response = await request.get('/api/some-endpoint')
      expect(response.data).toEqual({ code: 200, data: { result: 'ok' } })
      expect(mockRefreshAccessToken).toHaveBeenCalled()

      request.defaults.adapter = originalAdapter
    })

    it('should redirect to login when refresh token request itself returns 401', async () => {
      const mockClearAuth = vi.fn()
      mockGetState.mockReturnValue({
        accessToken: 'expired-token',
        refreshToken: 'refresh-token',
        clearAuth: mockClearAuth,
        refreshAccessToken: vi.fn(),
      })

      const mockAdapter = vi.fn().mockRejectedValue(
        createAxiosError(401, { message: 'Unauthorized' }, {
          url: '/api/auth/refresh',
          headers: {},
          _retry: false,
        } as any)
      )

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      await expect(request.post('/api/auth/refresh')).rejects.toBeDefined()
      expect(mockClearAuth).toHaveBeenCalled()

      request.defaults.adapter = originalAdapter
    })

    it('should redirect to login when token refresh fails', async () => {
      const mockClearAuth = vi.fn()
      const mockRefreshAccessToken = vi.fn().mockResolvedValue(null)
      mockGetState.mockReturnValue({
        accessToken: 'expired-token',
        refreshToken: 'refresh-token',
        clearAuth: mockClearAuth,
        refreshAccessToken: mockRefreshAccessToken,
      })

      const mockAdapter = vi.fn().mockRejectedValue(
        createAxiosError(401, { message: 'Unauthorized' })
      )

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      await expect(request.get('/api/data')).rejects.toBeDefined()
      expect(toast.error).toHaveBeenCalledWith('登录已过期，请重新登录')

      request.defaults.adapter = originalAdapter
    })
  })

  describe('response interceptor - concurrent 401 (processQueue)', () => {
    it('should queue concurrent 401 requests and retry all after single token refresh', async () => {
      const mockClearAuth = vi.fn()
      const mockRefreshAccessToken = vi.fn().mockResolvedValue('new-token-shared')

      mockGetState.mockReturnValue({
        accessToken: 'expired-token',
        refreshToken: 'refresh-token',
        clearAuth: mockClearAuth,
        refreshAccessToken: mockRefreshAccessToken,
      })

      let callCount = 0
      const mockAdapter = vi.fn().mockImplementation((config: InternalAxiosRequestConfig) => {
        callCount++
        if (callCount <= 2) {
          // First two calls: both 401
          return Promise.reject(createAxiosError(401, { message: 'Unauthorized' }, config))
        }
        // Retries after refresh: 3rd and 4th calls succeed
        return Promise.resolve({
          status: 200,
          data: { code: 200, data: { result: `ok-${callCount}` } },
          headers: {},
          config,
          statusText: 'OK',
        })
      })

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      // Two concurrent requests — both get 401 at the same time
      const [r1, r2] = await Promise.all([
        request.get('/api/endpoint-a'),
        request.get('/api/endpoint-b'),
      ])

      // Both should succeed after the shared token refresh
      expect(r1.data.code).toBe(200)
      expect(r2.data.code).toBe(200)

      // Token refresh should only be called ONCE (not once per request)
      expect(mockRefreshAccessToken).toHaveBeenCalledTimes(1)

      request.defaults.adapter = originalAdapter
    })

    it('should reject all queued requests when token refresh fails', async () => {
      const mockClearAuth = vi.fn()
      const mockRefreshAccessToken = vi.fn().mockResolvedValue(null) // refresh fails

      mockGetState.mockReturnValue({
        accessToken: 'expired-token',
        refreshToken: 'refresh-token',
        clearAuth: mockClearAuth,
        refreshAccessToken: mockRefreshAccessToken,
      })

      let callCount = 0
      const mockAdapter = vi.fn().mockImplementation((config: InternalAxiosRequestConfig) => {
        callCount++
        if (callCount <= 2) {
          return Promise.reject(createAxiosError(401, { message: 'Unauthorized' }, config))
        }
        return Promise.resolve({
          status: 200,
          data: { code: 200 },
          headers: {},
          config,
          statusText: 'OK',
        })
      })

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      // Two concurrent requests — refresh fails, both should reject
      const results = await Promise.allSettled([
        request.get('/api/endpoint-a'),
        request.get('/api/endpoint-b'),
      ])

      expect(results[0].status).toBe('rejected')
      expect(results[1].status).toBe('rejected')

      // Each failed queue entry triggers clearAuth via processQueue → toast
      // The main refresh path also calls toast. We just verify refresh was called once.
      expect(mockRefreshAccessToken).toHaveBeenCalledTimes(1)

      request.defaults.adapter = originalAdapter
    })
  })

  describe('response interceptor - other HTTP errors', () => {
    it('should use backend error message for non-standard status codes', async () => {
      const mockAdapter = vi.fn().mockRejectedValue(
        createAxiosError(422, { message: '商品名称已存在' })
      )

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      await expect(request.post('/api/products')).rejects.toBeDefined()
      expect(toast.error).toHaveBeenCalledWith('商品名称已存在')

      request.defaults.adapter = originalAdapter
    })

    it('should fall back to status code message for non-standard errors without message', async () => {
      const mockAdapter = vi.fn().mockRejectedValue(
        createAxiosError(429, {})
      )

      const originalAdapter = request.defaults.adapter
      request.defaults.adapter = mockAdapter

      await expect(request.get('/api/data')).rejects.toBeDefined()
      expect(toast.error).toHaveBeenCalledWith('请求失败 (429)')

      request.defaults.adapter = originalAdapter
    })
  })
})

// Helper to create AxiosError-like objects
function createAxiosError(status: number, data: any, config?: any): AxiosError {
  const error = new Error(`Request failed with status code ${status}`) as AxiosError
  error.isAxiosError = true
  error.config = config || { url: '/test', headers: {} } as InternalAxiosRequestConfig
  error.response = {
    status,
    data,
    headers: {},
    config: error.config!,
    statusText: status.toString(),
  } as AxiosResponse
  error.request = {}
  error.toJSON = () => ({})
  return error
}
