// case_ids: API-010, AU-001, AU-002, AU-003, BM-001, BM-002, BM-003
/**
 * 认证工具函数测试
 *
 * 覆盖: Token 存取、登录态判断、登出清理、JWT 过期检查、
 *       C 端微信登录（miniAppLogin 不动）、
 *       B 端员工账号密码登录（employeeLogin，issue #5485：租户只由标识里的企业编码解析）
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
  employeeLogin,
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
      const user = { id: 'u1', nickname: '测试用户', avatar: null, tenantId: 1 }
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

  // ========== C 端微信小程序登录（本次不动） ==========

  describe('miniAppLogin', () => {
    it('登录成功应存储 Token 和用户信息', async () => {
      const mockUser = { id: 'u1', nickname: '用户1', avatar: null, tenantId: 1 }
      mockPost.mockResolvedValueOnce({
        success: true,
        data: { accessToken: 'jwt-token-abc', user: mockUser },
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

  // ========== B 端员工账号密码登录（issue #5485 起＝用户名@企业编码 + 密码） ==========

  describe('employeeLogin', () => {
    const mockEmpUser = {
      id: 'emp-1',
      nickname: '运营小王',
      avatar: null,
      role: 'operator',
      roles: ['operator'],
      tenantId: 7,
      tenantName: '词元通达',
      mustChangePassword: false,
      identityType: 'employee',
    }

    it('登录成功应落 Token/用户，租户由响应回填（AU-001 / BM-001）', async () => {
      mockPost.mockResolvedValueOnce({
        success: true,
        data: { accessToken: 'employee-jwt-token', user: mockEmpUser },
      })

      const result = await employeeLogin('zhangsan@acme', 'init-pass-123')

      expect(result.success).toBe(true)
      expect(result.user).toEqual(mockEmpUser)
      expect(mockPost).toHaveBeenCalledWith(
        '/api/auth/employee/login',
        { identifier: 'zhangsan@acme', password: 'init-pass-123' },
        { baseURL: expect.any(String), skipAuth: true },
      )
      expect(Taro.setStorageSync).toHaveBeenCalledWith(STORAGE_KEYS.TOKEN, 'employee-jwt-token')
      expect(Taro.setStorageSync).toHaveBeenCalledWith(STORAGE_KEYS.USER, JSON.stringify(mockEmpUser))
      // 租户 = 服务端按标识里的企业编码解析所得（不是前端传的）
      expect(Taro.setStorageSync).toHaveBeenCalledWith(STORAGE_KEYS.TENANT_ID, 7)
    })

    it('请求体只含 identifier + password：不传 tenantId（AU-002 前端侧判据）', async () => {
      mockPost.mockResolvedValueOnce({
        success: true,
        data: { accessToken: 'employee-jwt-token', user: mockEmpUser },
      })

      await employeeLogin('zhangsan@acme', 'init-pass-123')

      const body = mockPost.mock.calls[0][1] as Record<string, unknown>
      expect(Object.keys(body).sort()).toEqual(['identifier', 'password'])
      expect(body).not.toHaveProperty('tenantId')
    })

    it('不调用 Taro.login()：微信授权换码路径已退场（BM-002）', async () => {
      mockPost.mockResolvedValueOnce({
        success: true,
        data: { accessToken: 'employee-jwt-token', user: mockEmpUser },
      })

      await employeeLogin('zhangsan@acme', 'init-pass-123')

      expect(Taro.login).not.toHaveBeenCalled()
    })

    it('后端拒绝时原样透传统一文案且不落 Token（AU-003 / BM-003）', async () => {
      mockPost.mockResolvedValueOnce({
        success: false,
        error: { code: 'AUTH_FAILED', message: '账号或密码错误' },
      })

      const result = await employeeLogin('zhangsan@acme', 'wrong-pass')

      expect(result.success).toBe(false)
      // 反枚举：前端不加工、不添加「用户名存在/密码错」这类区分信息
      expect(result.error).toBe('账号或密码错误')
      expect(Taro.setStorageSync).not.toHaveBeenCalledWith(STORAGE_KEYS.TOKEN, expect.any(String))
      expect(Taro.setStorageSync).not.toHaveBeenCalledWith(STORAGE_KEYS.TENANT_ID, expect.anything())
    })

    it('网络异常应捕获并返回错误', async () => {
      mockPost.mockRejectedValueOnce(new Error('Network Error'))

      const result = await employeeLogin('zhangsan@acme', 'init-pass-123')

      expect(result.success).toBe(false)
      expect(result.error).toBe('Network Error')
    })
  })
})