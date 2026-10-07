/**
 * HTTP 请求封装
 *
 * 基于 Taro.request，提供统一的请求/响应/错误处理
 */

import Taro from '@tarojs/taro'
import { API_BASE_URL, STORAGE_KEYS, REQUEST_CONFIG } from './constants'

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

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

/** 工人端点前缀（issue #6467：`/api/worker/**` 的 401 与商家会话**无关**） */
const WORKER_API_PREFIX = '/api/worker/'

/** 工人端点 401 的兜底文案（**只在服务端没给 message 时**用；能取到就原样上屏） */
const WORKER_AUTH_EXPIRED_FALLBACK = '工人身份已失效，请重新用工号 + PIN 登录'

/** 服务端文案（`ApiResponse` 信封：`{success:false, error:{message}}`，兼容 `{message}`） */
function serverMessage(data: any): string {
  return String(data?.error?.message || data?.message || '')
}

/**
 * 统一错误处理
 *
 * @param path 本次请求的端点（`request()` 传入）—— 用于**身份分流**：工人端点的 401
 *   不是「商家会话过期」（issue #6467）。
 */
function handleErrorStatus(statusCode: number, data: any, path: string): void {
  switch (statusCode) {
    case 401:
      // 🔴 工人端点的 401（issue #6467 现场缺陷）：`/api/worker/**` 只认工人 session
      // （`X-Worker-Session-Id`，工号 + PIN 签发）——
      //   · 报工写入口 401 是「这台设备没有工人身份」，**不是**商家会话过期；
      //   · 工人登录输错 PIN 也是 401。
      // 旧行为把它读成「登录已过期」⇒ 清商家 token/user + 跳商家登录页
      // （实测：管理员在 H5 点「完成报工」→ 商家登录态被毁、踢回登录页，重登再点仍然如此），
      // 且服务端那句可行动文案（「尚未登录工人身份…请重新用工号 + PIN 登录」）被吞掉。
      // 现行为：只清工人态、上屏服务端文案、**不**做商家登录页跳转（引导交给页面自身的身份分流）。
      if (path.startsWith(WORKER_API_PREFIX)) {
        try {
          Taro.removeStorageSync(STORAGE_KEYS.WORKER_SESSION)
          Taro.removeStorageSync(STORAGE_KEYS.WORKER)
        } catch {}
        Taro.showToast({
          title: serverMessage(data) || WORKER_AUTH_EXPIRED_FALLBACK,
          icon: 'none',
        })
        break
      }
      // 只有「本来就有会话」才谈得上过期。无 token 时的 401 是**端点自己的业务拒绝**
      // （issue #5485：员工登录失败统一 `401` + `AUTH_FAILED` + 统一文案；改密同理）
      // ⇒ 文案归调用方展示（`serverMessage` 取 `error.data.error.message`）；
      // 这里再弹「登录已过期」+ 跳登录页会把反枚举文案盖成技术噪声、并多跳一次页面。
      if (!getToken()) break
      // 清除 Token，跳转登录页
      try {
        Taro.removeStorageSync(STORAGE_KEYS.TOKEN)
        Taro.removeStorageSync(STORAGE_KEYS.USER)
        // 工人登录态（issue #4733）一并清：401 = 会话无效/已闲置超时 ⇒ 留着只会让每次请求都白跑
        Taro.removeStorageSync(STORAGE_KEYS.WORKER_SESSION)
        Taro.removeStorageSync(STORAGE_KEYS.WORKER)
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

      // 非成功状态码（把 `path` 一并传下去：401 要按**端点归属**分流，issue #6467）
      handleErrorStatus(statusCode, responseData, path)

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

/**
 * PATCH（issue #5654）：入库单**过账 / 作废**是 `PATCH /api/admin/inbound-orders/{id}`
 * （`InboundOrderController` 的一个端点承载状态机动作，不为每个动作各开端点）。
 * 与既有 `get/post/put/del` 同形，不新造网络层。
 */
export function patch<T = any>(path: string, data?: any, options?: RequestOptions): Promise<T> {
  return request<T>('PATCH', path, data, options)
}

export function del<T = any>(path: string, options?: RequestOptions): Promise<T> {
  return request<T>('DELETE', path, undefined, options)
}

export default {
  get,
  post,
  put,
  patch,
  del,
  request,
}
