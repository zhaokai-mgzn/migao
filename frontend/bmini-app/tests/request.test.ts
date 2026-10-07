// case_ids: BM-004, BM-036
/**
 * HTTP 请求层测试（B 端小程序基建，issue #2977）
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

    it('无 Token 时的 401 不弹「登录已过期」也不跳转（业务拒绝的文案归调用方，issue #5485）', async () => {
      // 员工登录失败就是 401 + {success:false,error:{...}} ⇒ 若这里照样弹会话过期 + 跳登录页，
      // 会把后端那句统一文案（「账号或密码错误」）盖成技术噪声，并多跳一次页面
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 401,
        data: { success: false, error: { code: 'AUTH_FAILED', message: '账号或密码错误' } },
      })

      await expect(
        post('/api/auth/employee/login', { identifier: 'zhangsan@acme', password: 'x' }),
      ).rejects.toThrow('Request failed with status 401')

      expect(Taro.showToast).not.toHaveBeenCalled()
      expect(Taro.redirectTo).not.toHaveBeenCalled()
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

  // ========== 401 身份分流（issue #6467 判据 4） ==========
  //
  // 现场（2026-10-07 生产）：管理员账号在 H5 点「完成报工」⇒ `POST /api/worker/production/scan/complete`
  // 401（报工写入口只认工人 session），而请求层把**任何** 401 都读成「商家会话过期」⇒
  // 弹「登录已过期，请重新登录」+ 清商家 token/user + 跳商家登录页 ⇒
  // 服务端那句「尚未登录工人身份…」被吞掉、有效的商家登录态被毁、重登再点仍然 401（死循环）。
  //
  // 口径：**工人端点**（`/api/worker/` 前缀）的 401 与商家会话无关 —— 不清商家态、不跳商家登录页、
  // 只清工人态、把服务端文案上屏；**商家端点** 401 行为**逐字不变**。
  describe('401 身份分流（issue #6467）', () => {
    const WORKER_401 = {
      success: false,
      error: {
        code: 'AUTH_FAILED',
        message: '尚未登录工人身份或登录已失效，请重新用工号 + PIN 登录',
      },
    }

    it('🔴 工人端点 401（本机有商家 token）⇒ 不清商家态、只清工人态、上屏服务端文案、不跳商家登录页', async () => {
      Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'merchant-token')
      Taro.setStorageSync(STORAGE_KEYS.USER, { id: 'u1', nickname: '管理员' })
      Taro.setStorageSync(STORAGE_KEYS.WORKER_SESSION, 'stale-worker-session')
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({ statusCode: 401, data: WORKER_401 })

      await expect(post('/api/worker/production/scan/complete', { qty: 1 })).rejects.toThrow(
        'Request failed with status 401',
      )

      // ① 商家登录态一字不动（实测：旧行为把它清掉 ⇒ 用户被踢回登录页）
      expect((Taro as any).__getStorage()[STORAGE_KEYS.TOKEN]).toBe('merchant-token')
      expect((Taro as any).__getStorage()[STORAGE_KEYS.USER]).toEqual({ id: 'u1', nickname: '管理员' })
      expect(Taro.removeStorageSync).not.toHaveBeenCalledWith(STORAGE_KEYS.TOKEN)
      expect(Taro.removeStorageSync).not.toHaveBeenCalledWith(STORAGE_KEYS.USER)
      // ② 只清工人 session / 缓存
      expect((Taro as any).__getStorage()[STORAGE_KEYS.WORKER_SESSION]).toBeUndefined()
      expect(Taro.removeStorageSync).toHaveBeenCalledWith(STORAGE_KEYS.WORKER_SESSION)
      // ③ 上屏**服务端**文案（可行动；不换成技术噪声、不换成通用兜底）
      expect(Taro.showToast).toHaveBeenCalledWith({
        title: WORKER_401.error.message,
        icon: 'none',
      })
      // ④ 不做商家登录页跳转（引导交给页面自身的身份分流）—— 连定时器推进后也不许跳
      await jest.advanceTimersByTimeAsync(5000)
      expect(Taro.redirectTo).not.toHaveBeenCalled()
    })

    it('工人端点 401 取不到服务端文案 ⇒ 用可行动兜底（不是「Request failed with status 401」）', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({ statusCode: 401, data: {} })

      await expect(get('/api/worker/production/current-worker')).rejects.toThrow(
        'Request failed with status 401',
      )

      const titles = (Taro.showToast as jest.Mock).mock.calls.map((call) => call[0].title)
      expect(titles).toContain('工人身份已失效，请重新用工号 + PIN 登录')
      expect(titles.join('\n')).not.toContain('Request failed')
    })

    it('🔴 工人登录输错 PIN（`POST /api/worker/login` 401）同样不误杀商家登录态', async () => {
      Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'merchant-token')
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 401,
        data: { success: false, error: { code: 'AUTH_FAILED', message: '工号或 PIN 不正确' } },
      })

      await expect(
        post('/api/worker/login', { workerNo: 'G001', pin: '0000' }, { skipAuth: true }),
      ).rejects.toThrow('Request failed with status 401')

      expect((Taro as any).__getStorage()[STORAGE_KEYS.TOKEN]).toBe('merchant-token')
      expect(Taro.showToast).toHaveBeenCalledWith({ title: '工号或 PIN 不正确', icon: 'none' })
      expect(Taro.redirectTo).not.toHaveBeenCalled()
    })

    it('商家端点 401 行为**逐字不变**：清商家 token/user + 弹「登录已过期」+ 跳商家登录页', async () => {
      Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'expired-token')
      Taro.setStorageSync(STORAGE_KEYS.USER, { id: 'u1' })
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 401,
        data: { message: 'Unauthorized' },
      })

      await expect(get('/api/admin/orders')).rejects.toThrow('Request failed with status 401')

      expect(Taro.removeStorageSync).toHaveBeenCalledWith(STORAGE_KEYS.TOKEN)
      expect(Taro.removeStorageSync).toHaveBeenCalledWith(STORAGE_KEYS.USER)
      expect((Taro as any).__getStorage()[STORAGE_KEYS.TOKEN]).toBeUndefined()
      expect(Taro.showToast).toHaveBeenCalledWith(
        expect.objectContaining({ title: expect.stringContaining('登录已过期') }),
      )
      await jest.advanceTimersByTimeAsync(1500)
      expect(Taro.redirectTo).toHaveBeenCalledWith({ url: '/pages/auth/login/index' })
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
