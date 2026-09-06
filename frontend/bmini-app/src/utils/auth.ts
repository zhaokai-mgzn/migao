/**
 * 认证工具
 *
 * 提供微信小程序登录、Token 管理、用户信息等
 */

import Taro from '@tarojs/taro'
import { post } from './request'
import { API_BASE_URL, STORAGE_KEYS } from './constants'
import type { User, LoginResult, ApiResponse } from '../types'

/**
 * 微信小程序登录
 * 1. 调用 Taro.login() 获取微信 code
 * 2. POST /api/auth/mini/login { code, tenant_id }
 * 3. 存储 Token 和用户信息
 */
export async function miniAppLogin(tenantId: number): Promise<LoginResult> {
  try {
    // 获取微信 code
    const loginRes = await Taro.login()
    if (!loginRes.code) {
      return { success: false, error: '获取微信登录凭证失败' }
    }

    // 调用后端登录接口（登录在 admin-api，走 API_BASE_URL）
    const data = await post<ApiResponse<{ accessToken: string; user: User }>>(
      '/api/auth/mini/login',
      {
        code: loginRes.code,
        tenantId: tenantId,
      },
      { baseURL: API_BASE_URL, skipAuth: true },
    )

    if (!data.success || !data.data) {
      return {
        success: false,
        error: data.error?.message || '登录失败',
      }
    }

    const { accessToken: token, user } = data.data

    // 存储到本地
    Taro.setStorageSync(STORAGE_KEYS.TOKEN, token)
    Taro.setStorageSync(STORAGE_KEYS.USER, JSON.stringify(user))
    Taro.setStorageSync(STORAGE_KEYS.TENANT_ID, tenantId)

    return { success: true, user }
  } catch (error: any) {
    console.error('小程序登录失败:', error)
    return {
      success: false,
      error: error.message || '登录失败，请稍后重试',
    }
  }
}

/**
 * B 端员工小程序登录（米宝商家端，issue #2977）
 * 1. 调用 Taro.login() 获取微信 code
 * 2. 首次需配合 <Button open-type="getPhoneNumber"> 授权，将返回的动态 code 作为 phoneCode 传入
 * 3. POST /api/auth/bmini/login { code, phoneCode }
 * 4. 后端：换 openid 查绑定 → 已绑定直接签发员工 JWT；未绑定则换手机号跨租户匹配员工
 *    （role∉customer/agent）→ 绑定 user_identities(bmini_app) → 签发含 permissions 的员工 JWT；
 *    匹配不到员工即时拒绝（禁止自动建号）。
 *
 * @param phoneCode 首次登录必传：getPhoneNumber 授权返回的动态 code；二次登录（已绑定）可不传
 */
export async function bminiLogin(phoneCode?: string): Promise<LoginResult> {
  try {
    // 获取微信 code
    const loginRes = await Taro.login()
    if (!loginRes.code) {
      return { success: false, error: '获取微信登录凭证失败' }
    }

    // 调用后端 B 端登录接口（admin-api，JWT + HttpOnly cookie 由后端处理）
    const data = await post<ApiResponse<{ accessToken: string; user: User }>>(
      '/api/auth/bmini/login',
      {
        code: loginRes.code,
        phoneCode: phoneCode || undefined,
      },
      { baseURL: API_BASE_URL, skipAuth: true },
    )

    if (!data.success || !data.data) {
      return {
        success: false,
        error: data.error?.message || '登录失败',
      }
    }

    const { accessToken: token, user } = data.data

    // 存储到本地（tenantId 由后端员工账号定位，无需前端传入）
    Taro.setStorageSync(STORAGE_KEYS.TOKEN, token)
    Taro.setStorageSync(STORAGE_KEYS.USER, JSON.stringify(user))
    if (user?.tenantId != null) {
      Taro.setStorageSync(STORAGE_KEYS.TENANT_ID, user.tenantId)
    }

    return { success: true, user }
  } catch (error: any) {
    console.error('B 端员工小程序登录失败:', error)
    return {
      success: false,
      error: error.message || '登录失败，请稍后重试',
    }
  }
}

/**
 * 获取本地存储的 Token
 */
export function getToken(): string | null {
  try {
    return Taro.getStorageSync(STORAGE_KEYS.TOKEN) || null
  } catch {
    return null
  }
}

/**
 * 获取本地存储的用户信息
 */
export function getUser(): User | null {
  try {
    const raw = Taro.getStorageSync(STORAGE_KEYS.USER)
    if (!raw) return null
    return typeof raw === 'string' ? JSON.parse(raw) : raw
  } catch {
    return null
  }
}

/**
 * 获取本地存储的租户 ID
 */
export function getTenantId(): number | null {
  try {
    return Taro.getStorageSync(STORAGE_KEYS.TENANT_ID) || null
  } catch {
    return null
  }
}

/**
 * 是否已登录
 */
export function isLoggedIn(): boolean {
  return !!getToken()
}

/**
 * 登出：清除本地 Token 和用户信息
 * 注意：导航跳转由调用方（Store / 页面）自行处理
 */
export function logout(): void {
  try {
    Taro.removeStorageSync(STORAGE_KEYS.TOKEN)
    Taro.removeStorageSync(STORAGE_KEYS.USER)
    Taro.removeStorageSync(STORAGE_KEYS.TENANT_ID)
  } catch {}
}

/**
 * 检查 Token 是否有效（解析 JWT exp）
 * 如果无法解析则返回 true（交由后端验证）
 */
export function checkTokenValidity(): boolean {
  const token = getToken()
  if (!token) return false

  try {
    // JWT 格式: header.payload.signature
    const parts = token.split('.')
    if (parts.length !== 3) return false

    // Base64 解码 payload
    const payload = JSON.parse(atob(parts[1]))
    if (!payload.exp) return true // 无过期时间，视为有效

    // 检查是否过期（exp 为秒级时间戳）
    const now = Math.floor(Date.now() / 1000)
    return payload.exp > now
  } catch {
    // 解析失败，交由后端验证
    return true
  }
}
