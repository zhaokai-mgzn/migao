/**
 * 用户相关 API 服务
 */

import { get, put, post } from '../utils/request'
import { API_BASE_URL, AI_API_BASE_URL } from '../utils/constants'
import type { ApiResponse, User } from '../types'

/**
 * 获取当前用户信息
 * GET /api/auth/me
 */
export async function getUserInfo(): Promise<User> {
  const res = await get<ApiResponse<User>>(
    '/api/auth/me',
    { baseURL: AI_API_BASE_URL },
  )
  if (!res.success || !res.data) {
    throw new Error(res.error?.message || '获取用户信息失败')
  }
  return res.data
}

/**
 * 更新用户信息
 * PUT /api/auth/me
 */
export async function updateUserInfo(data: Partial<User>): Promise<User> {
  const res = await put<ApiResponse<User>>(
    '/api/auth/me',
    data,
    { baseURL: AI_API_BASE_URL },
  )
  if (!res.success || !res.data) {
    throw new Error(res.error?.message || '更新用户信息失败')
  }
  return res.data
}

/**
 * 微信授权手机号绑定（小程序客户关联名下历史订单）
 *
 * code 来自 <button open-type="getPhoneNumber"> 的 bindgetphonenumber 回调
 * e.detail.code（动态令牌）；微信不直接给前端手机号，由后端换号。
 * 端点走 admin-api（API_BASE_URL）——小程序登录在 admin-api，JWT 一致。
 *
 * POST /api/auth/mini/bind-phone
 */
export interface BindPhoneResult {
  phone: string
  boundOrders: number
}

export async function bindMiniPhone(code: string): Promise<BindPhoneResult> {
  const res = await post<ApiResponse<BindPhoneResult>>(
    '/api/auth/mini/bind-phone',
    { code },
    { baseURL: API_BASE_URL },
  )
  if (!res.success || !res.data) {
    throw new Error(res.error?.message || '手机号绑定失败')
  }
  return res.data
}

export default {
  getUserInfo,
  updateUserInfo,
  bindMiniPhone,
}
