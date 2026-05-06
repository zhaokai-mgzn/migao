/**
 * 用户相关 API 服务
 */

import { get, put } from '../utils/request'
import { AI_API_BASE_URL } from '../utils/constants'
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

export default {
  getUserInfo,
  updateUserInfo,
}
