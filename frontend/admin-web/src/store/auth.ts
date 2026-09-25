import { create } from 'zustand'
import { authApi } from '@/lib/api'
import type { LoginResponse, User } from '@/types'
import { toast } from 'sonner'

// ⚠️ 审计 07 P1-F1/P1-5：JWT 一律不落 localStorage、不写 JS 可读 cookie。
// access_token/refresh_token 均由后端 HttpOnly+Secure cookie 承载（withCredentials 自动携带），
// 前端内存仅持有 accessToken 用于 Bearer 请求头（刷新页面后经 /api/auth/me 恢复会话）。

/**
 * 登录结果（issue #5485）。
 *
 * 页面据此决定「先去改密页」还是「进业务」——`mustChangePassword === true` 时必须
 * **直接引导到改密页**，而不是先进业务页再等业务 API 回 403（那是更差的体验：
 * 用户看到的是一个报错的半截页面）。
 */
export interface LoginOutcome {
  mustChangePassword: boolean
}

interface AuthState {
  // 状态（仅内存，不持久化）
  user: User | null
  accessToken: string | null
  isAuthenticated: boolean
  isLoading: boolean
  rememberMe: boolean
  _hasHydrated: boolean

  // 方法
  /** 员工登录：`identifier` = `用户名@企业编码`（**原样发服务端**，前端不解析租户） */
  employeeLogin: (identifier: string, password: string) => Promise<LoginOutcome>
  /** 短信登录：仅平台超管 + 企业管理员（#5485 I2，服务端按角色门禁） */
  smsLogin: (phone: string, code: string) => Promise<LoginOutcome>
  /** 自助改密：首登强制改密的唯一出口 */
  changePassword: (oldPassword: string, newPassword: string) => Promise<void>
  logout: () => Promise<void>
  refreshAccessToken: () => Promise<string | null>
  fetchUserInfo: () => Promise<void>
  initialize: () => Promise<void>
  clearAuth: () => void
  setHasHydrated: (v: boolean) => void
}

// 🔴 已删除的旧 `login()`（issue #5485）：它把企业编码 `Number(tenantCode)` 解析成
// `tenantId`，非法时**静默回落默认租户 1** —— 那正是「A 企业员工进到 B 企业」的形态，
// 绝不能沿用；且它打的 `POST /api/auth/admin/login` 自 #375 起后端就是禁用的。
// 两条合法的登录路只有：`employeeLogin`（员工账号密码）与 `smsLogin`（管理员短信）。

export const useAuthStore = create<AuthState>()((set, get) => {
  /**
   * 落会话（两条登录路 + 改密成功共用）。
   *
   * - token 仅存内存（审计 07 P1-F1）；refresh token 由后端 HttpOnly cookie 承载
   * - `mustChangePassword` 取自**登录/改密响应**（改密响应同样下发该键，值为 false）；
   *   `GET /api/auth/me` 也下发它 ⇒ 页面刷新后 store 里仍是真值
   */
  const applySession = async (data: LoginResponse | undefined): Promise<LoginOutcome> => {
    const loginUser = data?.user
    set({
      accessToken: data?.accessToken ?? null,
      isAuthenticated: true,
      isLoading: false,
      rememberMe: true,
      // 登录响应内层 user 只含登录时下发的键（permissions/menus 在 /me 里），
      // 先写一份是为了「/me 失败时右上角仍有昵称/企业名」；随后 fetchUserInfo 会覆盖为完整版
      ...(loginUser ? { user: loginUser as User } : {}),
    })

    try {
      await get().fetchUserInfo()
    } catch (e) {
      // 获取用户信息失败不阻塞登录（/api/auth/me 在强制改密白名单内，不会 403）
    }

    return { mustChangePassword: !!loginUser?.mustChangePassword }
  }

  return {
    // 初始状态
    user: null,
    accessToken: null,
    isAuthenticated: false,
    isLoading: false,
    rememberMe: true,
    _hasHydrated: true,

    setHasHydrated: (v: boolean) => set({ _hasHydrated: v }),

    // 员工登录（issue #5485）：标识原样发服务端，租户由服务端按企业编码解析
    employeeLogin: async (identifier: string, password: string) => {
      set({ isLoading: true })
      try {
        const response = await authApi.employeeLogin(identifier, password)
        const outcome = await applySession(response.data?.data)
        toast.success('登录成功')
        return outcome
      } catch (error) {
        set({ isLoading: false })
        throw error
      }
    },

    // 短信验证码登录（仅管理员；非 admin 由服务端拒绝并给出引导文案）
    smsLogin: async (phone: string, code: string) => {
      set({ isLoading: true })
      try {
        const response = await authApi.smsLogin(phone, code)
        const outcome = await applySession(response.data?.data)
        toast.success('登录成功')
        return outcome
      } catch (error) {
        set({ isLoading: false })
        throw error
      }
    },

    // 自助改密（#5485）：成功响应**直接带新凭据**，用它继续即可 ——
    // 不要再手动调 refreshAccessToken（旧 token 仍带 claim ⇒ 改完密码反而全站 403）
    changePassword: async (oldPassword: string, newPassword: string) => {
      set({ isLoading: true })
      try {
        const response = await authApi.changePassword({ oldPassword, newPassword })
        await applySession(response.data?.data)
        toast.success('密码修改成功')
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

        // #3099: /api/auth/me 返回 { user:{...}, roles, permissions, menus } 包装结构，
        // 必须把内层 user 与角色/权限/菜单合并后写入 store —— 否则顶层 nickname/username/
        // tenantName/tenantLogo 全部 undefined（右上角恒显「管理员」、侧边栏企业名/Logo 静默失效）。
        // 兼容历史扁平响应（部分测试/旧契约 data 直接是 user 对象）。
        // #5485: 内层还带 mustChangePassword —— 强制改密页跳转的判据靠它（刷新页面后也拿得到）。
        const payload = data as any
        const inner = payload?.user && typeof payload.user === 'object' ? payload.user : payload
        set({
          user: {
            ...inner,
            roles: payload?.roles,
            permissions: payload?.permissions,
            menus: payload?.menus,
          } as User,
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
  }
})

export default useAuthStore