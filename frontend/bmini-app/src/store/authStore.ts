/**
 * 认证状态管理
 *
 * 使用 Zustand + persist middleware，storage 适配 Taro
 */

import Taro from '@tarojs/taro'
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { miniAppLogin, employeeLogin, adminSmsLogin, changePassword, getToken, getUser, logout as authLogout, checkTokenValidity } from '../utils/auth'
import { refreshAccessToken } from '../utils/request'
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
  /** 企业管理员短信登录（issue #5721）：手机号 + 验证码 → `POST /api/auth/sms/login` */
  smsLoginAction: (phone: string, code: string) => Promise<boolean>
  /** 首登强制改密（issue #5485）：成功后用**响应里的新凭据**覆盖本地凭据 */
  changePasswordAction: (oldPassword: string, newPassword: string) => Promise<boolean>
  logout: () => void
  setUser: (user: User) => void
  setToken: (token: string) => void
  checkAuth: () => Promise<boolean>
  initialize: () => Promise<void>
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
       * 初始化：从本地存储恢复状态。
       *
       * 🔴 access token 只有 2 小时（issue #7249）⇒ exp 过期时**先续期**（HttpOnly
       * `refresh_token` cookie，30 天）再决定去留：改前这里直接 `logout()` ⇒
       * 隔一段时间打开 `/b/` 必被踢回登录页（续期失败才登出，与改前一致）。
       */
      initialize: async () => {
        const token = getToken()
        const user = getUser()
        if (!token) return

        if (checkTokenValidity()) {
          set({ token, user, isLoggedIn: true })
          return
        }

        const freshToken = await refreshAccessToken()
        if (freshToken) {
          set({ token: freshToken, user, isLoggedIn: true })
        } else {
          // 续期失败（cookie 过期 / 被吊销）⇒ 清除（行为与改前一致）
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
       * 企业管理员短信登录（issue #5721）：手机号 + 验证码。
       * 角色门禁在服务端（非管理员 ⇒ 401 + 引导文案），此处原样展示服务端文案、不自行判角色。
       * 与员工登录同款收尾：本层**不决定去向**，由登录页读 `user.mustChangePassword` 后路由。
       */
      smsLoginAction: async (phone: string, code: string) => {
        const { isLoading } = get()
        if (isLoading) return false

        set({ isLoading: true })

        try {
          const result = await adminSmsLogin(phone, code)

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
       * 检查认证状态（**异步**：exp 过期时先续期，issue #7249）。
       *
       * 页面在**发任何请求之前**调它（`pages/chat/index`）⇒ 若这里仍按「exp 过期 = 未登录」，
       * 请求层补的续期就永远走不到（页面先跳登录页了）。
       */
      checkAuth: async () => {
        const token = getToken()
        if (!token) {
          set({ isLoggedIn: false })
          return false
        }
        if (checkTokenValidity()) {
          set({ isLoggedIn: true })
          return true
        }
        const freshToken = await refreshAccessToken()
        if (!freshToken) {
          get().logout()
          return false
        }
        set({ token: freshToken, isLoggedIn: true })
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
