/**
 * B 端移动坐席服务（黄金策商家端，issue #2977）
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
 *
 * 🔴 2026-10-18：改前这里把**任何失败**吞成「空清单」⇒ 没有 `agent:session` 的员工
 * 拿到 403 也被画成「队列空闲，AI 正在处理中」= **把「看不到」说成「没有」**
 * （用户同日裁定「底栏 4 项一律可见」之后，这条路径第一次会被无权限的岗位走到）。
 * 现在失败**上抛**（403 的 `statusCode` 一路带到页面），由页面分三态显示：
 * `forbidden` ⇒「没有移动坐席权限」，`error` ⇒「加载失败，点此重试」。
 */
export async function getAgentSessions(
  status: 'waiting' | 'active' | 'ended' | 'transferred' | '',
  page = 1,
  size = 20,
): Promise<PageResponse<AgentSessionItem>> {
  const res = await get<ApiResponse<PageResponse<AgentSessionItem>>>(
    '/api/admin/agent-sessions',
    {
      baseURL: API_BASE_URL,
      params: { page, size, ...(status ? { status } : {}) },
    },
  )
  if (!res.success || !res.data) {
    throw new Error('获取人工会话列表失败')
  }
  return res.data
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