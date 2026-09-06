/**
 * B 端移动坐席服务（米宝商家端，issue #2977）
 *
 * 复用 admin-api AgentSessionController 现成端点：
 * - GET /api/admin/agent-sessions?status=&page=&size= — 人工会话列表（waiting/active…）
 * - GET /api/admin/agent-sessions/monitor — 队列统计
 * - GET /api/admin/agent-sessions/{id} — 会话详情（含消息）
 * - POST /api/admin/agent-sessions/{id}/assign — 接管会话
 * - POST /api/admin/agent-sessions/{id}/messages — 发送回复
 * - POST /api/admin/agent-sessions/{id}/end — 结束会话
 */

import { get, post } from '../utils/request'
import { API_BASE_URL } from '../utils/constants'
import type { ApiResponse, PageResponse } from '../types'

/** /api/admin/agent-sessions 列表项 */
export interface AgentSessionItem {
  id: string
  customerId: string
  customerName: string | null
  employeeId: string | null
  employeeName: string | null
  aiSessionId: string | null
  status: 'waiting' | 'active' | 'ended' | 'transferred'
  priority: number | null
  reason: string | null
  queuePosition: number | null
  messageCount: number | null
  startedAt: string | null
  createdAt: string | null
}

/** 会话详情消息 */
export interface AgentSessionMessage {
  id: string
  senderType: 'customer' | 'agent' | 'system'
  senderName?: string
  content: string
  createdAt: string
}

/** /api/admin/agent-sessions/{id} 详情 */
export interface AgentSessionDetail {
  id: string
  customerId: string
  customerName: string | null
  employeeId: string | null
  employeeName: string | null
  aiSessionId: string | null
  status: string
  reason: string | null
  messages: AgentSessionMessage[]
  customerPhone?: string | null
  aiContextSummary?: string | null
}

/** /api/admin/agent-sessions/monitor 队列统计 */
export interface AgentMonitor {
  waiting: number
  active: number
  todayHandled?: number
}

/**
 * 查询人工会话列表（status=waiting 为待接管队列）
 */
export async function getAgentSessions(
  status: 'waiting' | 'active' | 'ended' | 'transferred' | '',
  page = 1,
  size = 20,
): Promise<PageResponse<AgentSessionItem>> {
  try {
    const res = await get<ApiResponse<PageResponse<AgentSessionItem>>>(
      '/api/admin/agent-sessions',
      {
        baseURL: API_BASE_URL,
        params: { page, size, ...(status ? { status } : {}) },
      },
    )
    if (!res.success || !res.data) {
      return { items: [], total: 0, page: 1, size }
    }
    return res.data
  } catch (e) {
    console.error('获取人工会话列表失败:', e)
    return { items: [], total: 0, page: 1, size }
  }
}

/**
 * 获取会话详情（含消息）
 */
export async function getAgentSessionDetail(id: string): Promise<AgentSessionDetail | null> {
  try {
    const res = await get<ApiResponse<AgentSessionDetail>>(
      `/api/admin/agent-sessions/${id}`,
      { baseURL: API_BASE_URL },
    )
    if (!res.success || !res.data) return null
    return res.data
  } catch (e) {
    console.error('获取会话详情失败:', e)
    return null
  }
}

/**
 * 接管会话（assign 给自己）
 */
export async function assignAgentSession(id: string): Promise<boolean> {
  try {
    const res = await post<ApiResponse<void>>(
      `/api/admin/agent-sessions/${id}/assign`,
      {},
      { baseURL: API_BASE_URL },
    )
    return res.success
  } catch (e) {
    console.error('接管会话失败:', e)
    return false
  }
}

/**
 * 向会话发送回复消息
 */
export async function sendAgentReply(id: string, content: string): Promise<boolean> {
  try {
    const res = await post<ApiResponse<void>>(
      `/api/admin/agent-sessions/${id}/messages`,
      { content },
      { baseURL: API_BASE_URL },
    )
    return res.success
  } catch (e) {
    console.error('发送回复失败:', e)
    return false
  }
}

/**
 * 结束会话
 */
export async function endAgentSession(id: string): Promise<boolean> {
  try {
    const res = await post<ApiResponse<void>>(
      `/api/admin/agent-sessions/${id}/end`,
      {},
      { baseURL: API_BASE_URL },
    )
    return res.success
  } catch (e) {
    console.error('结束会话失败:', e)
    return false
  }
}

/**
 * 获取坐席队列统计（monitor）
 */
export async function getAgentMonitor(): Promise<AgentMonitor | null> {
  try {
    const res = await get<ApiResponse<AgentMonitor>>('/api/admin/agent-sessions/monitor', {
      baseURL: API_BASE_URL,
    })
    if (!res.success || !res.data) return null
    return res.data
  } catch (e) {
    console.error('获取坐席队列统计失败:', e)
    return null
  }
}

export default {
  getAgentSessions,
  getAgentSessionDetail,
  assignAgentSession,
  sendAgentReply,
  endAgentSession,
  getAgentMonitor,
}