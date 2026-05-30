import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { authApi } from '@/lib/api'
import type { LoginParams, User } from '@/types'
import { toast } from 'sonner'

// Cookie 操作工具函数
const COOKIE_DOMAIN = process.env.NEXT_PUBLIC_COOKIE_DOMAIN || ''
const IS_HTTPS = typeof window !== 'undefined' && window.location.protocol === 'https:'

function setCookie(name: string, value: string, days = 7) {
  let cookieStr = `${name}=${encodeURIComponent(value)}; path=/; SameSite=Lax`
  if (days > 0) {
    const expires = new Date(Date.now() + days * 864e5).toUTCString()
    cookieStr += `; expires=${expires}`
  }
  // 生产环境设置 domain 以支持跨子域共享（.migaozn.com）
  if (COOKIE_DOMAIN) {
    cookieStr += `; domain=${COOKIE_DOMAIN}`
  }
  // HTTPS 环境下启用 Secure 标记
  if (IS_HTTPS) {
    cookieStr += '; Secure'
  }
  document.cookie = cookieStr
}

function deleteCookie(name: string) {
  let cookieStr = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`
  if (COOKIE_DOMAIN) {
    cookieStr += `; domain=${COOKIE_DOMAIN}`
  }
  document.cookie = cookieStr
}

interface AuthState {
  // 状态
  user: User | null
  accessToken: string | null
  refreshToken: string | null
  isAuthenticated: boolean
  isLoading: boolean
  rememberMe: boolean
  _hasHydrated: boolean

  // 方法
  login: (username: string, password: string, rememberMe?: boolean) => Promise<void>
  smsLogin: (phone: string, code: string) => Promise<void>
  logout: () => Promise<void>
  refreshAccessToken: () => Promise<string | null>
  fetchUserInfo: () => Promise<void>
  initialize: () => Promise<void>
  clearAuth: () => void
  setHasHydrated: (v: boolean) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      // 初始状态
      user: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      isLoading: false,
      rememberMe: true,
      _hasHydrated: false,

      setHasHydrated: (v: boolean) => set({ _hasHydrated: v }),

      // 登录
      login: async (username: string, password: string, rememberMe = true) => {
        set({ isLoading: true })
        try {
          const params: LoginParams = { username, password }
          const response = await authApi.login(params)
          const { data } = response.data

          const accessToken = data.accessToken
          const refreshToken = data.refreshToken

          // 设置 cookie 供 middleware 读取
          if (typeof window !== 'undefined' && accessToken) {
            setCookie('access_token', accessToken, rememberMe ? 7 : 1)
          }

          set({
            accessToken,
            refreshToken,
            isAuthenticated: true,
            isLoading: false,
            rememberMe,
          })

          // 登录成功后获取用户信息
          try {
            await get().fetchUserInfo()
          } catch {
            // 获取用户信息失败不阻塞登录
          }

          toast.success('登录成功')
        } catch (error) {
          set({ isLoading: false })
          throw error
        }
      },

      // 短信验证码登录
      smsLogin: async (phone: string, code: string) => {
        set({ isLoading: true })
        try {
          const response = await authApi.smsLogin(phone, code)
          const { data } = response.data

          const accessToken = data.accessToken
          const refreshToken = data.refreshToken

          // 设置 cookie 供 middleware 读取
          if (typeof window !== 'undefined' && accessToken) {
            setCookie('access_token', accessToken, 7)
          }

          set({
            accessToken,
            refreshToken,
            isAuthenticated: true,
            isLoading: false,
            rememberMe: true,
          })

          // 登录成功后获取用户信息
          try {
            await get().fetchUserInfo()
          } catch {
            // 获取用户信息失败不阻塞登录
          }

          toast.success('登录成功')
        } catch (error) {
          set({ isLoading: false })
          throw error
        }
      },

      // 登出
      logout: async () => {
        try {
          await authApi.logout()
        } catch {
          // 即使 API 失败也清除本地状态
        } finally {
          get().clearAuth()
          toast.success('已退出登录')
          if (typeof window !== 'undefined') {
            window.location.href = '/login'
          }
        }
      },

      // 刷新 access token
      refreshAccessToken: async () => {
        const { refreshToken } = get()
        if (!refreshToken) {
          get().clearAuth()
          return null
        }

        try {
          const response = await authApi.refreshToken(refreshToken)
          const { data } = response.data
          const newAccessToken = data.accessToken
          const newRefreshToken = data.refreshToken || refreshToken

          // 更新 cookie
          if (typeof window !== 'undefined' && newAccessToken) {
            setCookie('access_token', newAccessToken, get().rememberMe ? 7 : 1)
          }

          set({
            accessToken: newAccessToken,
            refreshToken: newRefreshToken,
          })

          return newAccessToken
        } catch {
          get().clearAuth()
          return null
        }
      },

      // 获取用户信息
      fetchUserInfo: async () => {
        try {
          const response = await authApi.getUserInfo()
          const { data } = response.data

          set({
            user: data,
            isAuthenticated: true,
          })
        } catch (error) {
          // 获取失败则清除登录状态
          get().clearAuth()
          throw error
        }
      },

      // 应用启动时从 localStorage 恢复 Token 并验证
      initialize: async () => {
        const { accessToken, isAuthenticated } = get()

        // 没有 token，无需初始化
        if (!accessToken || !isAuthenticated) {
          set({ isLoading: false })
          return
        }

        // 同步 token 到 cookie
        if (typeof window !== 'undefined') {
          setCookie('access_token', accessToken, get().rememberMe ? 7 : 1)
        }

        // 尝试获取用户信息验证 token 有效性
        try {
          await get().fetchUserInfo()
        } catch {
          // token 无效，已在 fetchUserInfo 中清除状态
        }
      },

      // 清除认证状态
      clearAuth: () => {
        if (typeof window !== 'undefined') {
          deleteCookie('access_token')
        }
        set({
          user: null,
          accessToken: null,
          refreshToken: null,
          isAuthenticated: false,
          isLoading: false,
        })
      },
    }),
    {
      name: 'auth-storage',
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return localStorage
        return localStorage
      }),
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        rememberMe: state.rememberMe,
      }),
      onRehydrateStorage: () => (state, error) => {
        if (state) {
          state.setHasHydrated(true)
          // 恢复后同步 token 到 cookie
          if (typeof window !== 'undefined' && state.accessToken) {
            setCookie('access_token', state.accessToken, state.rememberMe ? 7 : 1)
          } else if (typeof window !== 'undefined') {
            deleteCookie('access_token')
          }
        }
      },
    }
  )
)

export default useAuthStore
