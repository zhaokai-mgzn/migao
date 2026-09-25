/**
 * 认证状态管理
 *
 * 使用 Zustand + persist middleware，storage 适配 Taro
 */

import Taro from '@tarojs/taro'
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { miniAppLogin, employeeLogin, changePassword, getToken, getUser, logout as authLogout, checkTokenValidity } from '../utils/auth'
import { STORAGE_KEYS, DEFAULT_TENANT_ID } from '../utils/constants'
import type { User } from '../types'

interface AuthState {
  // 状态
  token: string | null
  user: User | null
  isLoggedIn: boolean
  isLoading: boolean

  // Actions
  login: (tenantId?: number) => Promise<boolean>
  /** B 端员工登录（issue #5485）：identifier = `用户名@企业编码`，原样发服务端（前端不解析租户） */
  employeeLoginAction: (identifier: string, password: string) => Promise<boolean>
  /** 首登强制改密（issue #5485）：成功后用**响应里的新凭据**覆盖本地凭据 */
  changePasswordAction: (oldPassword: string, newPassword: string) => Promise<boolean>
  logout: () => void
  setUser: (user: User) => void
  setToken: (token: string) => void
  checkAuth: () => boolean
  initialize: () => void
}

/**
 * Taro 存储适配器，供 Zustand persist 使用
 */
const taroStorage = createJSONStorage(() => ({
  getItem: (key: string) => {
    try {
      return Taro.getStorageSync(key) || null
    } catch {
      return null
    }
  },
  setItem: (key: string, value: string) => {
    try {
      Taro.setStorageSync(key, value)
    } catch {}
  },
  removeItem: (key: string) => {
    try {
      Taro.removeStorageSync(key)
    } catch {}
  },
}))

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      isLoggedIn: false,
      isLoading: false,

      /**
       * 初始化：从本地存储恢复状态
       */
      initialize: () => {
        const token = getToken()
        const user = getUser()
        const valid = token ? checkTokenValidity() : false

        if (valid && token && user) {
          set({ token, user, isLoggedIn: true })
        } else if (token && !valid) {
          // Token 过期，清除
          get().logout()
        }
      },

      /**
       * 微信小程序登录
       */
      login: async (tenantId?: number) => {
        const { isLoading } = get()
        if (isLoading) return false

        set({ isLoading: true })

        try {
          const tid = tenantId || DEFAULT_TENANT_ID
          const result = await miniAppLogin(tid)

          if (result.success && result.user) {
            set({
              token: getToken(),
              user: result.user,
              isLoggedIn: true,
              isLoading: false,
            })
            return true
          }

          set({ isLoading: false })
          Taro.showToast({ title: result.error || '登录失败', icon: 'none' })
          return false
        } catch (error: any) {
          set({ isLoading: false })
          Taro.showToast({ title: '登录失败，请稍后重试', icon: 'none' })
          return false
        }
      },

      /**
       * B 端员工登录（issue #5485）：`用户名@企业编码` + 密码。
       * 失败原因（编码不存在 / 用户名不存在 / 密码错）由后端统一成同一 401 文案，此处原样展示。
       * 首登强制改密（`user.mustChangePassword`）本层**不弹提示、不决定去向** ——
       * 由登录页读到 `user.mustChangePassword` 后送往改密页（否则提示与路由会是两处口径）。
       */
      employeeLoginAction: async (identifier: string, password: string) => {
        const { isLoading } = get()
        if (isLoading) return false

        set({ isLoading: true })

        try {
          const result = await employeeLogin(identifier, password)

          if (result.success && result.user) {
            set({
              token: getToken(),
              user: result.user,
              isLoggedIn: true,
              isLoading: false,
            })
            return true
          }

          set({ isLoading: false })
          Taro.showToast({ title: result.error || '登录失败', icon: 'none' })
          return false
        } catch (error: any) {
          set({ isLoading: false })
          Taro.showToast({ title: '登录失败，请稍后重试', icon: 'none' })
          return false
        }
      },

      /**
       * 首登强制改密（issue #5485）：成功后后端**换发**新凭据（响应体同登录），
       * `changePassword` 已把新 token/user 落 storage ⇒ 这里同步内存态（`getToken()` 取新的）。
       * 失败（原密码不正确 / 新密码不符合策略）展示服务端文案，前端不造校验规则。
       */
      changePasswordAction: async (oldPassword: string, newPassword: string) => {
        const { isLoading } = get()
        if (isLoading) return false

        set({ isLoading: true })

        try {
          const result = await changePassword(oldPassword, newPassword)

          if (result.success && result.user) {
            set({
              token: getToken(),
              user: result.user,
              isLoggedIn: true,
              isLoading: false,
            })
            return true
          }

          set({ isLoading: false })
          Taro.showToast({ title: result.error || '密码修改失败', icon: 'none' })
          return false
        } catch (error: any) {
          set({ isLoading: false })
          Taro.showToast({ title: '密码修改失败，请稍后重试', icon: 'none' })
          return false
        }
      },

      /**
       * 登出
       */
      logout: () => {
        set({ token: null, user: null, isLoggedIn: false })
        authLogout()
      },

      /**
       * 设置用户信息
       */
      setUser: (user: User) => {
        Taro.setStorageSync(STORAGE_KEYS.USER, JSON.stringify(user))
        set({ user })
      },

      /**
       * 设置 Token
       */
      setToken: (token: string) => {
        Taro.setStorageSync(STORAGE_KEYS.TOKEN, token)
        set({ token, isLoggedIn: true })
      },

      /**
       * 检查认证状态
       */
      checkAuth: () => {
        const token = getToken()
        if (!token) {
          set({ isLoggedIn: false })
          return false
        }
        const valid = checkTokenValidity()
        if (!valid) {
          get().logout()
          return false
        }
        set({ isLoggedIn: true })
        return true
      },
    }),
    {
      name: 'auth-store',
      storage: taroStorage,
      // 只持久化关键字段
      partialize: (state) => ({
        token: state.token,
        user: state.user,
        isLoggedIn: state.isLoggedIn,
      }),
    },
  ),
)

export default useAuthStore
