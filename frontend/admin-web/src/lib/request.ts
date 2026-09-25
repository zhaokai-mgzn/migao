import axios, { AxiosInstance, AxiosResponse, InternalAxiosRequestConfig, AxiosError } from 'axios'
import { toast } from 'sonner'
import { useAuthStore } from '@/store/auth'
import { shouldRedirectToLogin } from '@/lib/auth-redirect'
import { markErrorToastShown } from '@/lib/api-error'

// 创建 Axios 实例
const request: AxiosInstance = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8080',
  timeout: 30000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

/**
 * 跳转登录页（带死循环守卫）：已在公开路由（如 /login 自身）时不强制跳转。
 * 否则 refresh 401 → 跳 /login → 页面重载 → initialize → 401 → 死循环（issue #2757）。
 */
function redirectToLogin() {
  if (typeof window === 'undefined') return
  if (shouldRedirectToLogin(window.location.pathname)) {
    window.location.href = '/login'
  }
}

/**
 * 认证**入口**端点（issue #5485）：这些 URL 自身的 401 = 凭据问题，
 * **绝不能**走「刷新 token → 重试」那条路 —— 那会把「账号或密码错误」吞成
 * 「登录已过期，请重新登录」，并丢掉服务端的反枚举文案（AU-003 要求三种病因同码同文案）。
 */
const AUTH_ENTRY_PATHS = ['/api/auth/refresh', '/api/auth/sms/login', '/api/auth/employee/login']

/** 首登强制改密的错误码（后端 `PasswordChangeRequiredFilter`，issue #5485 I4） */
const PASSWORD_CHANGE_REQUIRED = 'PASSWORD_CHANGE_REQUIRED'

/** 首登强制改密页路径（与 `src/app/change-password/page.tsx` 一致） */
const CHANGE_PASSWORD_PATH = '/change-password'

/**
 * 引导到「首登强制改密」页（issue #5485 I4）。
 *
 * 未改密的会话访问**任何**业务 API 都会得到 403 `PASSWORD_CHANGE_REQUIRED` ——
 * 所以必须在**拦截层全局**处理：只在一个页面处理的话，别的页面照样一屏报错。
 * 已在改密页时不重复赋值（避免无谓的整页重载）。
 */
function redirectToChangePassword() {
  if (typeof window === 'undefined') return
  if (window.location.pathname !== CHANGE_PASSWORD_PATH) {
    window.location.href = CHANGE_PASSWORD_PATH
  }
}

// ========== Token 刷新队列 ==========
let isRefreshing = false
let failedQueue: Array<{
  resolve: (token: string | null) => void
  reject: (error: unknown) => void
}> = []

const processQueue = (error: unknown, token: string | null = null) => {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) {
      markErrorToastShown(error) // 排队失败的请求同样认为已提示，避免页面再叠一条
      reject(error)
    } else {
      resolve(token)
    }
  })
  failedQueue = []
}

// ========== 请求拦截器 ==========
request.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = useAuthStore.getState().accessToken
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// ========== 响应拦截器 ==========
request.interceptors.response.use(
  (response: AxiosResponse) => {
    const { data } = response

    // 后端统一返回 { success: boolean, data, error, requestId, timestamp }
    // success === false 视为业务错误
    if (data.success === false) {
      const errorMessage = data.error?.message || '请求失败'
      toast.error(errorMessage)
      const error = new Error(errorMessage)
      markErrorToastShown(error)
      return Promise.reject(error)
    }

    return response
  },
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    // 401 处理：尝试刷新 Token
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      // 认证入口端点自身的 401：交给调用方展示服务端原文（登录页/改密页的内联错误区），
      // 不走刷新重试（见 AUTH_ENTRY_PATHS 注释）
      const url = originalRequest.url || ''
      if (AUTH_ENTRY_PATHS.some((p) => url.includes(p))) {
        if (url.includes('/api/auth/refresh')) {
          // 刷新端点自己 401 ⇒ 会话确实过期：清态并回登录页
          useAuthStore.getState().clearAuth()
          redirectToLogin()
        }
        return Promise.reject(error)
      }

      // 如果已经在刷新中，将请求加入队列
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({
            resolve: (token: string | null) => {
              if (token) {
                originalRequest.headers.Authorization = `Bearer ${token}`
                resolve(request(originalRequest))
              } else {
                reject(error)
              }
            },
            reject,
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const newToken = await useAuthStore.getState().refreshAccessToken()
        if (newToken) {
          // 刷新成功，重试原请求
          originalRequest.headers.Authorization = `Bearer ${newToken}`
          processQueue(null, newToken)
          return request(originalRequest)
        } else {
          // 刷新失败
          processQueue(error)
          toast.error('登录已过期，请重新登录')
          markErrorToastShown(error)
          redirectToLogin()
          return Promise.reject(error)
        }
      } catch (refreshError) {
        processQueue(refreshError)
        toast.error('登录已过期，请重新登录')
        markErrorToastShown(refreshError)
        redirectToLogin()
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    // 其他 HTTP 错误处理
    if (error.response) {
      const { status, data } = error.response as { status: number; data: any }
      switch (status) {
        case 403:
          // #5485 I4：首登未改密的会话访问业务 API ⇒ 403 PASSWORD_CHANGE_REQUIRED。
          // 文案用面向用户的说法 —— 后端那句是给开发者看的（"请调用 POST /api/auth/password/change"）。
          if (data?.error?.code === PASSWORD_CHANGE_REQUIRED) {
            toast.error('首次登录请先修改密码')
            markErrorToastShown(error)
            redirectToChangePassword()
            return Promise.reject(error)
          }
          toast.error('没有权限执行此操作')
          break
        case 404:
          toast.error('请求的资源不存在')
          break
        case 500:
          toast.error('服务器内部错误')
          break
        default:
          toast.error(data?.error?.message || data?.message || `请求失败 (${status})`)
      }
    } else if (error.request) {
      toast.error('网络连接失败，请检查网络设置')
    } else {
      toast.error(error.message || '请求发生错误')
    }
    markErrorToastShown(error) // 以上分支均已 toast，页面 catch 不应再重复提示

    return Promise.reject(error)
  }
)

export default request
