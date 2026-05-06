/**
 * HTTP 请求封装
 *
 * 基于 Taro.request，提供统一的请求/响应/错误处理
 */

import Taro from '@tarojs/taro'
import { API_BASE_URL, STORAGE_KEYS, REQUEST_CONFIG } from './constants'

type Method = 'GET' | 'POST' | 'PUT' | 'DELETE'

interface RequestOptions {
  /** 自定义 baseURL，不传则使用 API_BASE_URL */
  baseURL?: string
  /** 请求头 */
  headers?: Record<string, string>
  /** 查询参数 */
  params?: Record<string, any>
  /** 超时时间 ms */
  timeout?: number
  /** 是否跳过自动认证头 */
  skipAuth?: boolean
}

/**
 * 将 params 对象拼接到 URL 上
 */
function appendParams(url: string, params?: Record<string, any>): string {
  if (!params) return url
  const parts: string[] = []
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    }
  })
  if (parts.length === 0) return url
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}${parts.join('&')}`
}

/**
 * 获取存储的 Token
 */
function getToken(): string | null {
  try {
    return Taro.getStorageSync(STORAGE_KEYS.TOKEN) || null
  } catch {
    return null
  }
}

/**
 * 统一错误处理
 */
function handleErrorStatus(statusCode: number, data: any): void {
  switch (statusCode) {
    case 401:
      // 清除 Token，跳转登录页
      try {
        Taro.removeStorageSync(STORAGE_KEYS.TOKEN)
        Taro.removeStorageSync(STORAGE_KEYS.USER)
      } catch {}
      Taro.showToast({ title: '登录已过期，请重新登录', icon: 'none' })
      setTimeout(() => {
        Taro.redirectTo({ url: '/pages/auth/login/index' })
      }, 1500)
      break
    case 403:
      Taro.showToast({ title: '无权限访问', icon: 'none' })
      break
    case 404:
      // 不提示，由业务层处理
      break
    case 500:
    default:
      if (statusCode >= 500) {
        Taro.showToast({ title: '服务器错误，请稍后重试', icon: 'none' })
      }
      break
  }
}

/**
 * 判断是否需要重试的网络错误
 */
function isRetryableError(error: any): boolean {
  if (!error) return false
  const msg = String(error.errMsg || error.message || '')
  return msg.includes('timeout') || msg.includes('fail') || msg.includes('网络')
}

/**
 * 延迟函数
 */
function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

/**
 * 核心请求方法
 */
async function request<T = any>(
  method: Method,
  path: string,
  data?: any,
  options: RequestOptions = {},
): Promise<T> {
  const {
    baseURL = API_BASE_URL,
    headers = {},
    params,
    timeout = REQUEST_CONFIG.TIMEOUT,
    skipAuth = false,
  } = options

  const url = appendParams(`${baseURL}${path}`, params)

  // 构建请求头
  const requestHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Client-Type': 'wechat_mini',
    ...headers,
  }

  // 自动添加 Token
  if (!skipAuth) {
    const token = getToken()
    if (token) {
      requestHeaders['Authorization'] = `Bearer ${token}`
    }
  }

  // 带重试的请求
  let lastError: any = null
  for (let attempt = 0; attempt <= REQUEST_CONFIG.MAX_RETRIES; attempt++) {
    try {
      if (attempt > 0) {
        // 指数退避
        await delay(REQUEST_CONFIG.RETRY_DELAY * Math.pow(2, attempt - 1))
      }

      const response = await Taro.request({
        url,
        method,
        data,
        header: requestHeaders,
        timeout,
      })

      const { statusCode, data: responseData } = response

      // 成功响应
      if (statusCode >= 200 && statusCode < 300) {
        return responseData as T
      }

      // 非成功状态码
      handleErrorStatus(statusCode, responseData)

      const error: any = new Error(`Request failed with status ${statusCode}`)
      error.statusCode = statusCode
      error.data = responseData
      throw error
    } catch (error: any) {
      lastError = error

      // 如果不是可重试的网络错误，或者已经有 HTTP 状态码，直接抛出
      if (error.statusCode || !isRetryableError(error)) {
        throw error
      }

      // 最后一次重试失败
      if (attempt === REQUEST_CONFIG.MAX_RETRIES) {
        Taro.showToast({ title: '网络异常，请检查网络连接', icon: 'none' })
        throw error
      }
    }
  }

  throw lastError
}

// ========== 快捷方法 ==========

export function get<T = any>(path: string, options?: RequestOptions): Promise<T> {
  return request<T>('GET', path, undefined, options)
}

export function post<T = any>(path: string, data?: any, options?: RequestOptions): Promise<T> {
  return request<T>('POST', path, data, options)
}

export function put<T = any>(path: string, data?: any, options?: RequestOptions): Promise<T> {
  return request<T>('PUT', path, data, options)
}

export function del<T = any>(path: string, options?: RequestOptions): Promise<T> {
  return request<T>('DELETE', path, undefined, options)
}

export default {
  get,
  post,
  put,
  del,
  request,
}
