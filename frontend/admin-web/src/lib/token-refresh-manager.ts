/**
 * TokenRefreshManager - 提取Token刷新逻辑为可测试的类
 * 
 * 将 request.ts 中的刷新逻辑提取为独立类，便于单元测试
 */

import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/store/auth'

interface FailedRequest {
  resolve: (token: string | null) => void
  reject: (error: unknown) => void
  config: InternalAxiosRequestConfig
}

export class TokenRefreshManager {
  private isRefreshing = false
  private failedQueue: FailedRequest[] = []
  private axiosInstance: AxiosInstance

  constructor(axiosInstance: AxiosInstance) {
    this.axiosInstance = axiosInstance
  }

  /**
   * 处理队列中的请求
   */
  private processQueue(error: unknown, token: string | null = null): void {
    this.failedQueue.forEach(({ resolve, reject }) => {
      if (error) {
        reject(error)
      } else {
        resolve(token)
      }
    })
    this.failedQueue = []
  }

  /**
   * 处理401错误
   */
  async handle401Error(errorConfig: InternalAxiosRequestConfig): Promise<any> {
    const originalRequest = errorConfig as InternalAxiosRequestConfig & { _retry?: boolean }

    // 如果是刷新token或登录请求本身返回401，直接拒绝
    const url = originalRequest.url || ''
    if (url.includes('/api/auth/refresh') || url.includes('/api/auth/admin/login')) {
      useAuthStore.getState().clearAuth()
      if (typeof window !== 'undefined') {
        window.location.href = '/login'
      }
      return Promise.reject(new Error('Authentication failed'))
    }

    // 如果已经在刷新中，将请求加入队列
    if (this.isRefreshing) {
      return new Promise((resolve, reject) => {
        this.failedQueue.push({
          resolve,
          reject,
          config: originalRequest,
        })
      })
    }

    // 开始刷新token
    originalRequest._retry = true
    this.isRefreshing = true

    try {
      const newToken = await useAuthStore.getState().refreshAccessToken()
      
      if (newToken) {
        // 刷新成功，重试原请求
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        this.processQueue(null, newToken)
        return this.axiosInstance(originalRequest)
      } else {
        // 刷新失败
        this.processQueue(new Error('Token refresh failed'))
        useAuthStore.getState().clearAuth()
        if (typeof window !== 'undefined') {
          window.location.href = '/login'
        }
        return Promise.reject(new Error('Token refresh failed'))
      }
    } catch (refreshError) {
      this.processQueue(refreshError)
      useAuthStore.getState().clearAuth()
      if (typeof window !== 'undefined') {
        window.location.href = '/login'
      }
      return Promise.reject(refreshError)
    } finally {
      this.isRefreshing = false
    }
  }

  /**
   * 获取队列状态（用于测试）
   */
  getQueueStatus() {
    return {
      isRefreshing: this.isRefreshing,
      queueLength: this.failedQueue.length,
    }
  }

  /**
   * 重置状态（用于测试）
   */
  reset(): void {
    this.isRefreshing = false
    this.failedQueue = []
  }
}

/**
 * 使用示例：
 * 
 * const tokenManager = new TokenRefreshManager(request)
 * 
 * // 在响应拦截器中使用
 * request.interceptors.response.use(
 *   (response) => response,
 *   async (error) => {
 *     if (error.response?.status === 401) {
 *       return tokenManager.handle401Error(error.config)
 *     }
 *     return Promise.reject(error)
 *   }
 * )
 */
