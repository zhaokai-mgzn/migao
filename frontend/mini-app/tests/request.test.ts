/**
 * HTTP 请求层测试
 *
 * 覆盖: Token注入、401处理、请求重试、错误处理、快捷方法
 */
import Taro from '@tarojs/taro'
import { get, post, put, del } from '../src/utils/request'
import { STORAGE_KEYS, REQUEST_CONFIG } from '../src/utils/constants'

describe('request utils', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    jest.useFakeTimers()
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  // ========== Token 自动注入 ==========

  describe('Token 注入', () => {
    it('有 Token 时自动添加 Authorization header', async () => {
      Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'my-token')
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: { ok: true },
      })

      await get('/api/test')

      expect(Taro.request).toHaveBeenCalledWith(
        expect.objectContaining({
          header: expect.objectContaining({
            Authorization: 'Bearer my-token',
          }),
        }),
      )
    })

    it('无 Token 时不添加 Authorization header', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: { ok: true },
      })

      await get('/api/test')

      const callArgs = (Taro.request as jest.Mock).mock.calls[0][0]
      expect(callArgs.header.Authorization).toBeUndefined()
    })

    it('skipAuth 时不添加 Authorization header', async () => {
      Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'my-token')
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: { ok: true },
      })

      await get('/api/test', { skipAuth: true })

      const callArgs = (Taro.request as jest.Mock).mock.calls[0][0]
      expect(callArgs.header.Authorization).toBeUndefined()
    })
  })

  // ========== 请求方法 ==========

  describe('快捷方法', () => {
    it('GET 请求', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: { items: [] },
      })

      const result = await get('/api/items')

      expect(Taro.request).toHaveBeenCalledWith(
        expect.objectContaining({ method: 'GET' }),
      )
      expect(result).toEqual({ items: [] })
    })

    it('POST 请求带 body', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: { id: 1 },
      })

      const result = await post('/api/items', { name: 'test' })

      expect(Taro.request).toHaveBeenCalledWith(
        expect.objectContaining({
          method: 'POST',
          data: { name: 'test' },
        }),
      )
      expect(result).toEqual({ id: 1 })
    })

    it('PUT 请求', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: { updated: true },
      })

      await put('/api/items/1', { name: 'updated' })

      expect(Taro.request).toHaveBeenCalledWith(
        expect.objectContaining({ method: 'PUT' }),
      )
    })

    it('DELETE 请求', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: null,
      })

      await del('/api/items/1')

      expect(Taro.request).toHaveBeenCalledWith(
        expect.objectContaining({ method: 'DELETE' }),
      )
    })
  })

  // ========== URL 参数拼接 ==========

  describe('URL params', () => {
    it('应拼接 query 参数到 URL', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: {},
      })

      await get('/api/items', { params: { page: 1, size: 20 } })

      const callArgs = (Taro.request as jest.Mock).mock.calls[0][0]
      expect(callArgs.url).toContain('page=1')
      expect(callArgs.url).toContain('size=20')
    })

    it('应忽略 undefined/null 参数', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: {},
      })

      await get('/api/items', { params: { page: 1, filter: undefined, sort: null } })

      const callArgs = (Taro.request as jest.Mock).mock.calls[0][0]
      expect(callArgs.url).toContain('page=1')
      expect(callArgs.url).not.toContain('filter')
      expect(callArgs.url).not.toContain('sort')
    })
  })

  // ========== 错误处理 ==========

  describe('错误处理', () => {
    it('401 应清除 Token 并跳转登录页', async () => {
      Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'expired-token')
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 401,
        data: { message: 'Unauthorized' },
      })

      await expect(get('/api/protected')).rejects.toThrow('Request failed with status 401')

      expect(Taro.removeStorageSync).toHaveBeenCalledWith(STORAGE_KEYS.TOKEN)
      expect(Taro.showToast).toHaveBeenCalledWith(
        expect.objectContaining({ title: expect.stringContaining('登录已过期') }),
      )
    })

    it('403 应提示无权限', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 403,
        data: {},
      })

      await expect(get('/api/admin')).rejects.toThrow('Request failed with status 403')
      expect(Taro.showToast).toHaveBeenCalledWith(
        expect.objectContaining({ title: '无权限访问' }),
      )
    })

    it('500 应提示服务器错误', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 500,
        data: {},
      })

      await expect(get('/api/broken')).rejects.toThrow('Request failed with status 500')
      expect(Taro.showToast).toHaveBeenCalledWith(
        expect.objectContaining({ title: expect.stringContaining('服务器错误') }),
      )
    })
  })

  // ========== 请求重试 ==========

  describe('请求重试', () => {
    it('网络超时应重试后成功', async () => {
      const timeoutError: any = new Error('request:fail timeout')
      timeoutError.errMsg = 'request:fail timeout'

      ;(Taro.request as jest.Mock)
        .mockRejectedValueOnce(timeoutError)
        .mockResolvedValueOnce({ statusCode: 200, data: { ok: true } })

      const resultPromise = get('/api/test')

      // 推进定时器让 delay 完成
      await jest.advanceTimersByTimeAsync(REQUEST_CONFIG.RETRY_DELAY)

      const result = await resultPromise
      expect(result).toEqual({ ok: true })
      expect(Taro.request).toHaveBeenCalledTimes(2)
    })

    it('HTTP 错误状态码不重试', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 404,
        data: { message: 'Not Found' },
      })

      await expect(get('/api/not-exist')).rejects.toThrow()
      expect(Taro.request).toHaveBeenCalledTimes(1)
    })
  })

  // ========== 自定义 headers ==========

  describe('自定义配置', () => {
    it('应发送自定义 headers', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: {},
      })

      await get('/api/test', { headers: { 'X-Custom': 'value' } })

      expect(Taro.request).toHaveBeenCalledWith(
        expect.objectContaining({
          header: expect.objectContaining({ 'X-Custom': 'value' }),
        }),
      )
    })

    it('应使用自定义 baseURL', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: {},
      })

      await get('/api/test', { baseURL: 'https://custom.api.com' })

      const callArgs = (Taro.request as jest.Mock).mock.calls[0][0]
      expect(callArgs.url).toStartWith('https://custom.api.com/api/test')
    })
  })
})

// 扩展 Jest matchers
expect.extend({
  toStartWith(received: string, expected: string) {
    const pass = received.startsWith(expected)
    return {
      message: () => `expected "${received}" to start with "${expected}"`,
      pass,
    }
  },
})

declare global {
  namespace jest {
    interface Matchers<R> {
      toStartWith(expected: string): R
    }
  }
}
