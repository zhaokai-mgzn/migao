/**
 * B 端数据一屏服务（米宝商家端，issue #2977）
 *
 * 复用 admin-api DashboardController 现成端点：
 * - GET /api/admin/dashboard/stats — 核心经营数字（今日订单/销售额/活跃会话/AI 接管率…）
 * - GET /api/admin/dashboard/pending-tasks — 待办（待支付订单/待处理售后）
 * - GET /api/admin/dashboard/active-sessions — 活跃会话
 */

import { get } from '../utils/request'
import { API_BASE_URL } from '../utils/constants'
import type { ApiResponse } from '../types'

/** /api/admin/dashboard/stats 响应 */
export interface DashboardStats {
  todayOrders: number
  todayOrdersChange: number
  todaySales: number
  todaySalesChange: number
  totalCustomers: number
  newCustomersToday: number
  activeSessions: number
  aiSessionRate: number
  monthRevenue: number
  monthRevenueChange: number
  totalProducts: number
  totalOrders: number
  totalTickets: number
  pendingShipOrders: number
  processingPendingOrders: number
  lowStockItems: number
}

/** /api/admin/dashboard/pending-tasks 单项 */
export interface PendingTask {
  id: string
  type: string // "order" | "after_sales"
  title: string
  priority: string // "high" | "medium" | "low"
  createdAt: string | null
  link: string | null
}

/** /api/admin/dashboard/active-sessions 会话项 */
export interface ActiveSession {
  id: string
  customerName?: string
  customerPhone?: string
  status?: string
  startedAt?: string
  lastActiveAt?: string
  messageCount?: number
}

/**
 * 获取核心经营数据一屏
 */
export async function getDashboardStats(): Promise<DashboardStats | null> {
  try {
    const res = await get<ApiResponse<DashboardStats>>('/api/admin/dashboard/stats', {
      baseURL: API_BASE_URL,
    })
    if (!res.success || !res.data) return null
    return res.data
  } catch (e) {
    console.error('获取经营数据失败:', e)
    return null
  }
}

/**
 * 获取待办任务（待支付订单 / 待处理售后）
 */
export async function getPendingTasks(): Promise<PendingTask[]> {
  try {
    const res = await get<ApiResponse<PendingTask[]>>('/api/admin/dashboard/pending-tasks', {
      baseURL: API_BASE_URL,
    })
    if (!res.success || !res.data) return []
    return res.data
  } catch (e) {
    console.error('获取待办失败:', e)
    return []
  }
}

/**
 * 获取活跃会话
 */
export async function getActiveSessions(limit = 5): Promise<ActiveSession[]> {
  try {
    const res = await get<ApiResponse<ActiveSession[]>>('/api/admin/dashboard/active-sessions', {
      baseURL: API_BASE_URL,
      params: { limit },
    })
    if (!res.success || !res.data) return []
    return res.data
  } catch (e) {
    console.error('获取活跃会话失败:', e)
    return []
  }
}

/** 金额展示：元（后端分 → 元） */
export function formatYuan(cents: number): string {
  return (cents / 100).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

/** 百分比展示（后端已算好百分数值，如 12.5 = 12.5%） */
export function formatPercent(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`
}

export default {
  getDashboardStats,
  getPendingTasks,
  getActiveSessions,
}