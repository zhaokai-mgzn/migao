/**
 * 认证工具
 *
 * 提供 B 端员工账号密码登录、C 端微信小程序登录、Token 管理、用户信息等
 */

import Taro from '@tarojs/taro'
import { post } from './request'
import { API_BASE_URL, STORAGE_KEYS } from './constants'
import type { User, LoginResult, ApiResponse } from '../types'

/**
 * 微信小程序登录
 * 1. 调用 Taro.login() 获取微信 code
 * 2. POST /api/auth/mini/login { code, tenantId }（admin-api camelCase 入参；历史注释误写
 *    的 `tenant_id` 与响应字段无关，勿据它推字段名）
 * 3. 存储 Token 和用户信息（`auth_user` 存 `data.user` 原样 JSON —— 形状见 types 的 `User`）
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
 * B 端员工登录（米宝商家端，issue #5485 起＝「用户名@企业编码 + 密码」）
 *
 * 1. POST /api/auth/employee/login，body `{ identifier, password }`
 * 2. `identifier` 形如 `zhangsan@acme`（**原样发服务端**）——租户**只**由标识里的
 *    企业编码解析，前端**不解析租户、不传 tenantId**（否则「任意数字即可切租户」）
 * 3. 存储 Token / 用户 / 租户（`user.tenantId` 由服务端回填）
 *
 * 原「微信授权手机号 → 跨租户匹配员工 → 绑定 openid → 二次免密」整条退场：
 * 本函数**不调用 `Taro.login()`**，`POST /api/auth/bmini/login` 已废弃
 * （旧版调用会拿到明确拒绝 + 引导文案，不是 404）。
 *
 * 格式合规 / 账号是否存在 / 密码是否正确的判定**单一真值在后端**：
 * 三者统一 401 同一文案（反枚举），前端不复制校验规则、不区分字段报错。
 */
export async function employeeLogin(identifier: string, password: string): Promise<LoginResult> {
  try {
    // 调用后端员工登录接口（admin-api，JWT + HttpOnly cookie 由后端处理）
    const data = await post<ApiResponse<{ accessToken: string; user: User }>>(
      '/api/auth/employee/login',
      {
        identifier,
        password,
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

    // 存储到本地（tenantId 由后端按标识里的企业编码解析，无需前端传入）
    Taro.setStorageSync(STORAGE_KEYS.TOKEN, token)
    Taro.setStorageSync(STORAGE_KEYS.USER, JSON.stringify(user))
    if (user?.tenantId != null) {
      Taro.setStorageSync(STORAGE_KEYS.TENANT_ID, user.tenantId)
    }

    return { success: true, user }
  } catch (error: any) {
    console.error('B 端员工登录失败:', error)
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
