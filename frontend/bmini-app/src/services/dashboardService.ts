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

// ══════════════════════════════════════════════════════════════════
// 生产概览（待办优先，issue #5641）
//
// 端点：GET /api/admin/production/todo-overview（服务端规则引擎聚合，前端只渲染）
// 口径：每一条待办都带 criterion（判据 id）+ evidence（判据数据）⇒「为什么是它」可追溯；
//       **没有任何一条来自 LLM**（不做生成式归因）。前端**不重算**任何数（重算 = 第二份口径）。
// ══════════════════════════════════════════════════════════════════

/** /api/admin/production/todo-overview 的一条待办 */
export interface ProductionTodo {
  id: string
  /** "to_schedule" 待排产 | "stuck" 卡在哪 | "to_ship" 待发货 */
  type: string
  type_label: string
  /** "high" | "medium" */
  priority: string
  title: string
  reason: string
  /** 判据 id（确定性规则名，服务端下发；前端只展示不判断） */
  criterion: string
  /** 可点即办的落脚页（服务端拼好；前端不猜对象路由） */
  link: string
  target?: Record<string, any>
  evidence?: Record<string, any>
}

/** /api/admin/production/todo-overview 响应 */
export interface ProductionTodoOverview {
  generated_at: string
  /** 第一屏的 N（= todos.length，服务端同源） */
  todo_total: number
  todos: ProductionTodo[]
  stats: {
    /** 第二屏计数（与第一屏**同一份 list**） */
    todo_total: number
    by_type: Record<string, number>
    /** 三态进度（没开工 / 做了一半 / 已完成） */
    operations: Record<string, number>
    stuck_threshold_hours: number
    threshold_source: string
    scan: { order_scan_limit: number; truncated: boolean }
  }
}

/**
 * 拉取结果：**「无权限 / 失败」必须与「空」可区分**。
 *
 * 🔴 403 静默当空 = 把「看不到」渲染成「没有待处理」—— 那正是本单要防的假数据形态
 * （同族反面教材：缺值渲染出 `undefined 米 / ¥NaN`）。
 */
export type ProductionTodoResult =
  | { status: 'ok'; data: ProductionTodoOverview }
  | { status: 'forbidden' }
  | { status: 'error' }

/** 生产待办总览（待办优先的一屏；端点权限 = 生产域读码 production:view） */
export async function getProductionTodoOverview(): Promise<ProductionTodoResult> {
  try {
    const res = await get<ApiResponse<ProductionTodoOverview>>(
      '/api/admin/production/todo-overview',
      { baseURL: API_BASE_URL },
    )
    if (!res.success || !res.data) return { status: 'error' }
    return { status: 'ok', data: res.data }
  } catch (e: any) {
    if (e?.statusCode === 403) return { status: 'forbidden' }
    console.error('获取生产待办失败:', e)
    return { status: 'error' }
  }
}

/**
 * 待办的落脚 URL（**由服务端给**，前端不猜对象路由）。
 *
 * 拿不到合法路由（缺 link / 不是页面路由）⇒ 返回 `null` ⇒ 该条**不可点**：
 * 宁可不给入口，也不给一个点进去是空白的死链。
 */
export function productionTodoTargetUrl(todo: ProductionTodo): string | null {
  const link = todo?.link
  return typeof link === 'string' && link.startsWith('/pages/') ? link : null
}

/** 三态进度的展示名（服务端口径；未知键不编名字） */
export const OPERATION_STATE_LABELS: Record<string, string> = {
  not_started: '没开工',
  in_progress: '做了一半',
  completed: '已完成',
}

/** 阈值来源展示（与 web 面同口径：history = 历史中位数，否则系统兜底默认值） */
export function thresholdSourceLabel(source?: string): string {
  return source === 'history' ? '历史中位数' : '系统兜底默认值'
}

export default {
  getDashboardStats,
  getPendingTasks,
  getActiveSessions,
  getProductionTodoOverview,
}