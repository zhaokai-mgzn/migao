/**
 * 认证工具函数测试
 *
 * 覆盖: Token存取、登录态判断、登出清理、JWT过期检查、微信登录流程
 */
import Taro from '@tarojs/taro'
import {
  getToken,
  getUser,
  getTenantId,
  isLoggedIn,
  logout,
  checkTokenValidity,
  miniAppLogin,
} from '../src/utils/auth'
import { STORAGE_KEYS } from '../src/utils/constants'

// Mock request 模块
jest.mock('../src/utils/request', () => ({
  post: jest.fn(),
}))

import { post } from '../src/utils/request'
const mockPost = post as jest.MockedFunction<typeof post>

describe('auth utils', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
  })

  // ========== Token 存取 ==========

  describe('getToken', () => {
    it('应返回 null 当无 Token 时', () => {
      expect(getToken()).toBeNull()
    })

    it('应返回存储的 Token', () => {
      Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'test-token-123')
      expect(getToken()).toBe('test-token-123')
    })

    it('应在 storage 异常时返回 null', () => {
      ;(Taro.getStorageSync as jest.Mock).mockImplementationOnce(() => {
        throw new Error('storage error')
      })
      expect(getToken()).toBeNull()
    })
  })

  // ========== 用户信息存取 ==========

  describe('getUser', () => {
    it('应返回 null 当无用户信息时', () => {
      expect(getUser()).toBeNull()
    })

    it('应解析 JSON 字符串并返回用户对象', () => {
      const user = { id: 'u1', nickname: '测试用户', avatar: null, tenant_id: 1 }
      Taro.setStorageSync(STORAGE_KEYS.USER, JSON.stringify(user))
      expect(getUser()).toEqual(user)
    })

    it('应在 JSON 解析失败时返回 null', () => {
      Taro.setStorageSync(STORAGE_KEYS.USER, 'invalid-json{')
      expect(getUser()).toBeNull()
    })
  })

  // ========== 租户 ID ==========

  describe('getTenantId', () => {
    it('应返回 null 当无租户 ID 时', () => {
      expect(getTenantId()).toBeNull()
    })

    it('应返回存储的租户 ID', () => {
      Taro.setStorageSync(STORAGE_KEYS.TENANT_ID, 42)
      expect(getTenantId()).toBe(42)
    })
  })

  // ========== 登录态判断 ==========

  describe('isLoggedIn', () => {
    it('无 Token 时返回 false', () => {
      expect(isLoggedIn()).toBe(false)
    })

    it('有 Token 时返回 true', () => {
      Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'some-token')
      expect(isLoggedIn()).toBe(true)
    })
  })

  // ========== 登出清理 ==========

  describe('logout', () => {
    it('应清除 Token、User、TenantId', () => {
      Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'token')
      Taro.setStorageSync(STORAGE_KEYS.USER, '{}')
      Taro.setStorageSync(STORAGE_KEYS.TENANT_ID, 1)

      logout()

      expect(Taro.removeStorageSync).toHaveBeenCalledWith(STORAGE_KEYS.TOKEN)
      expect(Taro.removeStorageSync).toHaveBeenCalledWith(STORAGE_KEYS.USER)
      expect(Taro.removeStorageSync).toHaveBeenCalledWith(STORAGE_KEYS.TENANT_ID)
    })
  })

  // ========== JWT 过期检查 ==========

  describe('checkTokenValidity', () => {
    it('无 Token 时返回 false', () => {
      expect(checkTokenValidity()).toBe(false)
    })

    it('非 JWT 格式返回 false', () => {
      Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'not-a-jwt')
      expect(checkTokenValidity()).toBe(false)
    })

    it('未过期的 JWT 返回 true', () => {
      // 构造未过期的 JWT payload
      const payload = { exp: Math.floor(Date.now() / 1000) + 3600 } // 1小时后过期
      const token = `header.${btoa(JSON.stringify(payload))}.signature`
      Taro.setStorageSync(STORAGE_KEYS.TOKEN, token)
      expect(checkTokenValidity()).toBe(true)
    })

    it('已过期的 JWT 返回 false', () => {
      const payload = { exp: Math.floor(Date.now() / 1000) - 3600 } // 1小时前过期
      const token = `header.${btoa(JSON.stringify(payload))}.signature`
      Taro.setStorageSync(STORAGE_KEYS.TOKEN, token)
      expect(checkTokenValidity()).toBe(false)
    })

    it('无 exp 字段的 JWT 返回 true (交由后端验证)', () => {
      const payload = { sub: 'user1' }
      const token = `header.${btoa(JSON.stringify(payload))}.signature`
      Taro.setStorageSync(STORAGE_KEYS.TOKEN, token)
      expect(checkTokenValidity()).toBe(true)
    })
  })

  // ========== 微信小程序登录 ==========

  describe('miniAppLogin', () => {
    it('登录成功应存储 Token 和用户信息', async () => {
      const mockUser = { id: 'u1', nickname: '用户1', avatar: null, tenant_id: 1 }
      mockPost.mockResolvedValueOnce({
        success: true,
        data: { token: 'jwt-token-abc', user: mockUser },
      })

      const result = await miniAppLogin(1)

      expect(result.success).toBe(true)
      expect(result.user).toEqual(mockUser)
      expect(Taro.login).toHaveBeenCalled()
      expect(Taro.setStorageSync).toHaveBeenCalledWith(STORAGE_KEYS.TOKEN, 'jwt-token-abc')
      expect(Taro.setStorageSync).toHaveBeenCalledWith(STORAGE_KEYS.USER, JSON.stringify(mockUser))
      expect(Taro.setStorageSync).toHaveBeenCalledWith(STORAGE_KEYS.TENANT_ID, 1)
    })

    it('微信 code 获取失败应返回错误', async () => {
      ;(Taro.login as jest.Mock).mockResolvedValueOnce({ code: '' })

      const result = await miniAppLogin(1)

      expect(result.success).toBe(false)
      expect(result.error).toContain('微信登录凭证')
    })

    it('后端返回失败应返回错误信息', async () => {
      mockPost.mockResolvedValueOnce({
        success: false,
        error: { code: 'AUTH_FAILED', message: '认证失败' },
      })

      const result = await miniAppLogin(1)

      expect(result.success).toBe(false)
      expect(result.error).toBe('认证失败')
    })

    it('网络异常应捕获并返回错误', async () => {
      mockPost.mockRejectedValueOnce(new Error('Network Error'))

      const result = await miniAppLogin(1)

      expect(result.success).toBe(false)
      expect(result.error).toBe('Network Error')
    })
  })
})
