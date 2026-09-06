/**
 * Auth Zustand Store 测试
 *
 * 覆盖: 初始化、登录、登出、状态持久化、Token检查
 */
import Taro from '@tarojs/taro'
import { STORAGE_KEYS } from '../src/utils/constants'

// Mock auth utils
jest.mock('../src/utils/auth', () => ({
  miniAppLogin: jest.fn(),
  getToken: jest.fn(() => null),
  getUser: jest.fn(() => null),
  logout: jest.fn(),
  checkTokenValidity: jest.fn(() => false),
}))

import { miniAppLogin, getToken, getUser, checkTokenValidity, logout as authLogout } from '../src/utils/auth'
const mockMiniAppLogin = miniAppLogin as jest.MockedFunction<typeof miniAppLogin>
const mockGetToken = getToken as jest.MockedFunction<typeof getToken>
const mockGetUser = getUser as jest.MockedFunction<typeof getUser>
const mockCheckTokenValidity = checkTokenValidity as jest.MockedFunction<typeof checkTokenValidity>

// 重新加载 store (隔离状态)
function getAuthStore() {
  jest.resetModules()
  // Re-mock after resetModules
  jest.mock('../src/utils/auth', () => ({
    miniAppLogin: jest.fn(),
    getToken: jest.fn(() => null),
    getUser: jest.fn(() => null),
    logout: jest.fn(),
    checkTokenValidity: jest.fn(() => false),
  }))
  const { useAuthStore } = require('../src/store/authStore')
  return useAuthStore
}

describe('authStore', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
  })

  describe('初始状态', () => {
    it('初始状态为未登录', () => {
      const useAuthStore = getAuthStore()
      const state = useAuthStore.getState()
      expect(state.token).toBeNull()
      expect(state.user).toBeNull()
      expect(state.isLoggedIn).toBe(false)
      expect(state.isLoading).toBe(false)
    })
  })

  describe('login', () => {
    it('登录成功应更新状态', async () => {
      const useAuthStore = getAuthStore()
      const { miniAppLogin: mockLogin, getToken: mockGt } = require('../src/utils/auth')

      const mockUser = { id: 'u1', nickname: '测试', avatar: null, tenant_id: 1 }
      mockLogin.mockResolvedValueOnce({ success: true, user: mockUser })
      mockGt.mockReturnValue('new-token')

      const success = await useAuthStore.getState().login(1)

      expect(success).toBe(true)
      const state = useAuthStore.getState()
      expect(state.user).toEqual(mockUser)
      expect(state.isLoggedIn).toBe(true)
      expect(state.isLoading).toBe(false)
    })

    it('登录失败应保持未登录状态', async () => {
      const useAuthStore = getAuthStore()
      const { miniAppLogin: mockLogin } = require('../src/utils/auth')

      mockLogin.mockResolvedValueOnce({ success: false, error: '登录失败' })

      const success = await useAuthStore.getState().login(1)

      expect(success).toBe(false)
      expect(useAuthStore.getState().isLoggedIn).toBe(false)
      // showToast is called via the re-imported Taro inside the store
      const TaroInStore = require('@tarojs/taro').default || require('@tarojs/taro')
      expect(TaroInStore.showToast).toHaveBeenCalled()
    })

    it('正在登录时不应重复调用', async () => {
      const useAuthStore = getAuthStore()
      const { miniAppLogin: mockLogin } = require('../src/utils/auth')

      // 让登录挂起
      mockLogin.mockReturnValue(new Promise(() => {}))

      // 第一次登录
      useAuthStore.getState().login(1)
      // 第二次应该直接返回 false
      const result = await useAuthStore.getState().login(1)
      expect(result).toBe(false)
    })
  })

  describe('logout', () => {
    it('登出应清除所有状态', async () => {
      const useAuthStore = getAuthStore()
      const { miniAppLogin: mockLogin, getToken: mockGt, logout: mockLogout } = require('../src/utils/auth')

      const mockUser = { id: 'u1', nickname: '测试', avatar: null, tenant_id: 1 }
      mockLogin.mockResolvedValueOnce({ success: true, user: mockUser })
      mockGt.mockReturnValue('token')

      await useAuthStore.getState().login(1)
      useAuthStore.getState().logout()

      const state = useAuthStore.getState()
      expect(state.token).toBeNull()
      expect(state.user).toBeNull()
      expect(state.isLoggedIn).toBe(false)
      expect(mockLogout).toHaveBeenCalled()
    })
  })

  describe('setUser / setToken', () => {
    it('setUser 应更新用户信息', () => {
      const useAuthStore = getAuthStore()
      const user = { id: 'u2', nickname: '新用户', avatar: 'url', tenant_id: 1 }

      useAuthStore.getState().setUser(user)

      expect(useAuthStore.getState().user).toEqual(user)
      const TaroInStore = require('@tarojs/taro').default || require('@tarojs/taro')
      expect(TaroInStore.setStorageSync).toHaveBeenCalledWith(
        STORAGE_KEYS.USER,
        JSON.stringify(user),
      )
    })

    it('setToken 应更新 Token 并标记已登录', () => {
      const useAuthStore = getAuthStore()

      useAuthStore.getState().setToken('new-token')

      expect(useAuthStore.getState().token).toBe('new-token')
      expect(useAuthStore.getState().isLoggedIn).toBe(true)
    })
  })

  describe('checkAuth', () => {
    it('无 Token 时返回 false', () => {
      const useAuthStore = getAuthStore()
      const { getToken: mockGt } = require('../src/utils/auth')
      mockGt.mockReturnValue(null)

      const result = useAuthStore.getState().checkAuth()

      expect(result).toBe(false)
      expect(useAuthStore.getState().isLoggedIn).toBe(false)
    })

    it('Token 有效时返回 true', () => {
      const useAuthStore = getAuthStore()
      const { getToken: mockGt, checkTokenValidity: mockCtv } = require('../src/utils/auth')
      mockGt.mockReturnValue('valid-token')
      mockCtv.mockReturnValue(true)

      const result = useAuthStore.getState().checkAuth()

      expect(result).toBe(true)
      expect(useAuthStore.getState().isLoggedIn).toBe(true)
    })

    it('Token 过期时登出', () => {
      const useAuthStore = getAuthStore()
      const { getToken: mockGt, checkTokenValidity: mockCtv, logout: mockLogout } = require('../src/utils/auth')
      mockGt.mockReturnValue('expired-token')
      mockCtv.mockReturnValue(false)

      const result = useAuthStore.getState().checkAuth()

      expect(result).toBe(false)
      expect(mockLogout).toHaveBeenCalled()
    })
  })

  describe('initialize', () => {
    it('有效 Token + User 应恢复登录状态', () => {
      const useAuthStore = getAuthStore()
      const { getToken: mockGt, getUser: mockGu, checkTokenValidity: mockCtv } = require('../src/utils/auth')

      const user = { id: 'u1', nickname: '用户', avatar: null, tenant_id: 1 }
      mockGt.mockReturnValue('valid-token')
      mockGu.mockReturnValue(user)
      mockCtv.mockReturnValue(true)

      useAuthStore.getState().initialize()

      const state = useAuthStore.getState()
      expect(state.token).toBe('valid-token')
      expect(state.user).toEqual(user)
      expect(state.isLoggedIn).toBe(true)
    })

    it('Token 过期时应执行登出', () => {
      const useAuthStore = getAuthStore()
      const { getToken: mockGt, getUser: mockGu, checkTokenValidity: mockCtv, logout: mockLogout } = require('../src/utils/auth')

      mockGt.mockReturnValue('expired')
      mockGu.mockReturnValue(null)
      mockCtv.mockReturnValue(false)

      useAuthStore.getState().initialize()

      expect(mockLogout).toHaveBeenCalled()
    })
  })
})
