import axios, { AxiosInstance, AxiosResponse, InternalAxiosRequestConfig, AxiosError } from 'axios'
import { toast } from 'sonner'
import { useAuthStore } from '@/store/auth'

// 创建 Axios 实例
const request: AxiosInstance = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8080',
  timeout: 30000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ========== Token 刷新队列 ==========
let isRefreshing = false
let failedQueue: Array<{
  resolve: (token: string | null) => void
  reject: (error: unknown) => void
}> = []

const processQueue = (error: unknown, token: string | null = null) => {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) {
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
      return Promise.reject(new Error(errorMessage))
    }

    return response
  },
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    // 401 处理：尝试刷新 Token
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      // 如果是刷新 token 或登录请求本身返回 401，直接跳转登录
      const url = originalRequest.url || ''
      if (url.includes('/api/auth/refresh') || url.includes('/api/auth/admin/login')) {
        useAuthStore.getState().clearAuth()
        if (typeof window !== 'undefined') {
          window.location.href = '/login'
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
          if (typeof window !== 'undefined') {
            window.location.href = '/login'
          }
          return Promise.reject(error)
        }
      } catch (refreshError) {
        processQueue(refreshError)
        toast.error('登录已过期，请重新登录')
        if (typeof window !== 'undefined') {
          window.location.href = '/login'
        }
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
          toast.error('没有权限执行此操作')
          break
        case 404:
          toast.error('请求的资源不存在')
          break
        case 500:
          toast.error('服务器内部错误')
          break
        default:
          toast.error(data?.message || `请求失败 (${status})`)
      }
    } else if (error.request) {
      toast.error('网络连接失败，请检查网络设置')
    } else {
      toast.error(error.message || '请求发生错误')
    }

    return Promise.reject(error)
  }
)

export default request
