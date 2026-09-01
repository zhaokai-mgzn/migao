import { create } from 'zustand'
import { authApi } from '@/lib/api'
import type { LoginParams, User } from '@/types'
import { toast } from 'sonner'

// ⚠️ 审计 07 P1-F1/P1-5：JWT 一律不落 localStorage、不写 JS 可读 cookie。
// access_token/refresh_token 均由后端 HttpOnly+Secure cookie 承载（withCredentials 自动携带），
// 前端内存仅持有 accessToken 用于 Bearer 请求头（刷新页面后经 /api/auth/me 恢复会话）。

interface AuthState {
  // 状态（仅内存，不持久化）
  user: User | null
  accessToken: string | null
  isAuthenticated: boolean
  isLoading: boolean
  rememberMe: boolean
  _hasHydrated: boolean

  // 方法
  login: (username: string, password: string, rememberMe?: boolean, tenantCode?: string) => Promise<void>
  smsLogin: (phone: string, code: string) => Promise<void>
  logout: () => Promise<void>
  refreshAccessToken: () => Promise<string | null>
  fetchUserInfo: () => Promise<void>
  initialize: () => Promise<void>
  clearAuth: () => void
  setHasHydrated: (v: boolean) => void
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  // 初始状态
  user: null,
  accessToken: null,
  isAuthenticated: false,
  isLoading: false,
  rememberMe: true,
  _hasHydrated: true,

  setHasHydrated: (v: boolean) => set({ _hasHydrated: v }),

  // 登录（密码登录后端已禁用 #375，保留兼容签名）
  login: async (username: string, password: string, rememberMe = true, tenantCode?: string) => {
    set({ isLoading: true })
    try {
      // 后端要求 tenantId（数字类型），将企业编号输入解析为数字；为空或非法时回退到默认租户 1
      const parsedTenantId = tenantCode && tenantCode.trim() ? Number(tenantCode.trim()) : NaN
      const tenantId = Number.isFinite(parsedTenantId) && parsedTenantId > 0 ? parsedTenantId : 1
      const params: LoginParams = { username, password, tenantId }
      if (tenantCode && tenantCode.trim()) {
        params.tenantCode = tenantCode.trim()
      }
      const response = await authApi.login(params)
      const { data } = response.data

      // 审计 07 P1-F1：token 仅存内存；refresh token 由后端 HttpOnly cookie 承载
      set({
        accessToken: data.accessToken,
        isAuthenticated: true,
        isLoading: false,
        rememberMe,
      })

      // 登录成功后获取用户信息
      try {
        await get().fetchUserInfo()
      } catch (e) {
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

      set({
        accessToken: data.accessToken,
        isAuthenticated: true,
        isLoading: false,
        rememberMe: true,
      })

      // 登录成功后获取用户信息
      try {
        await get().fetchUserInfo()
      } catch (e) {
        // 获取用户信息失败不阻塞登录
      }

      toast.success('登录成功')
    } catch (error) {
      set({ isLoading: false })
      throw error
    }
  },

  // 登出（后端清除 HttpOnly cookies + 黑名单）
  logout: async () => {
    try {
      await authApi.logout()
    } catch (e) {
      // 即使 API 失败也清除本地状态
    } finally {
      get().clearAuth()
      toast.success('已退出登录')
      if (typeof window !== 'undefined') {
        window.location.href = '/login'
      }
    }
  },

  // 刷新 access token：后端从 HttpOnly refresh_token cookie 读取并轮换（审计 07 P1-5）
  refreshAccessToken: async () => {
    try {
      const response = await authApi.refreshToken()
      const { data } = response.data
      set({ accessToken: data.accessToken })
      return data.accessToken
    } catch (e) {
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
    } catch (error: any) {
      // 仅认证错误（401/403）时清除登录状态
      // 网络异常不应导致用户登出（如 E2E fixture 模式无后端、临时网络抖动）
      const status = error?.response?.status
      if (status === 401 || status === 403) {
        get().clearAuth()
      }
      throw error
    }
  },

  // 应用启动时恢复会话：无内存 token → 依赖 HttpOnly cookie 调 /api/auth/me 校验（审计 07 P1-F1）
  initialize: async () => {
    const { accessToken, isAuthenticated } = get()

    if (accessToken && isAuthenticated) {
      // 已有内存会话，静默校验
      try {
        await get().fetchUserInfo()
      } catch (e) {
        // 无效则已清态
      }
      set({ isLoading: false })
      return
    }

    // 无内存 token：尝试用 cookie 恢复会话（后端 HttpOnly cookie 自动携带）
    try {
      await get().fetchUserInfo()
    } catch (e) {
      // 未登录或会话过期：保持未认证状态
    }
    set({ isLoading: false })
  },

  // 清除认证状态（仅内存；cookie 由后端登出接口清除）
  clearAuth: () => {
    set({
      user: null,
      accessToken: null,
      isAuthenticated: false,
      isLoading: false,
    })
  },
}))

export default useAuthStore
