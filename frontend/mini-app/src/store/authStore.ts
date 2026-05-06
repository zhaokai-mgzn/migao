/**
 * 认证状态管理
 *
 * 使用 Zustand + persist middleware，storage 适配 Taro
 */

import Taro from '@tarojs/taro'
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { miniAppLogin, getToken, getUser, logout as authLogout, checkTokenValidity } from '../utils/auth'
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
