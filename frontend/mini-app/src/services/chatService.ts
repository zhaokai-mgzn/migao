/**
 * 对话相关 API 服务
 *
 * 封装所有对话相关的 API 调用，与后端 ai-agent-service 对接
 * API 前缀: /api/chat (由 routes.py 注册)
 */

import { get, post, del } from '../utils/request'
import { SSEClient } from '../utils/sse'
import { AI_API_BASE_URL, API_BASE_URL } from '../utils/constants'
import type {
  ApiResponse,
  Session,
  Message,
  QuickAction,
  PageResponse,
} from '../types'

/** 人工客服会话消息（转人工后客服回复） */
export interface AgentSessionMessage {
  id: string
  senderType: 'customer' | 'agent' | 'system'
  senderName?: string
  content: string
  createdAt: string
}

/** 人工客服会话详情 */
export interface AgentSessionDetail {
  id: string
  aiSessionId: string
  status: 'waiting' | 'active' | 'ended' | 'transferred'
  messages?: AgentSessionMessage[]
}

/**
 * 获取人工客服会话（转人工后查询客服回复）
 * GET /api/customer/agent-sessions/by-ai/{aiSessionId}
 */
export async function getAgentSessionByAi(
  aiSessionId: string,
): Promise<AgentSessionDetail | null> {
  try {
    const res = await get<ApiResponse<AgentSessionDetail>>(
      `/api/customer/agent-sessions/by-ai/${aiSessionId}`,
      { baseURL: API_BASE_URL },
    )
    if (!res.success || !res.data) return null
    return res.data
  } catch (e) {
    console.error('获取人工会话失败:', e)
    return null
  }
}

/**
 * 向人工客服发送消息（转人工后）
 * POST /api/customer/agent-sessions/{sessionId}/messages
 */
export async function sendAgentMessage(
  sessionId: string,
  content: string,
): Promise<boolean> {
  try {
    const res = await post<ApiResponse<void>>(
      `/api/customer/agent-sessions/${sessionId}/messages`,
      { content },
      { baseURL: API_BASE_URL },
    )
    return res.success
  } catch (e) {
    console.error('发送人工消息失败:', e)
    return false
  }
}

/**
 * 创建新会话
 * POST /api/chat/sessions
 */
export async function createSession(title?: string): Promise<Session> {
  const res = await post<ApiResponse<Session>>(
    '/api/chat/sessions',
    { title, platform: 'wechat_mini' },
    { baseURL: AI_API_BASE_URL },
  )
  if (!res.success || !res.data) {
    throw new Error(res.error?.message || '创建会话失败')
  }
  return res.data
}

/**
 * 获取会话列表
 * GET /api/chat/sessions
 */
export async function getSessionList(
  page = 1,
  size = 20,
): Promise<PageResponse<Session>> {
  const res = await get<ApiResponse<PageResponse<Session>>>(
    '/api/chat/sessions',
    { baseURL: AI_API_BASE_URL, params: { page, size } },
  )
  if (!res.success || !res.data) {
    throw new Error(res.error?.message || '获取会话列表失败')
  }
  return res.data
}

/**
 * 删除会话
 * DELETE /api/chat/sessions/{id}
 */
export async function deleteSession(id: string): Promise<void> {
  const res = await del<ApiResponse<void>>(
    `/api/chat/sessions/${id}`,
    { baseURL: AI_API_BASE_URL },
  )
  if (!res.success) {
    throw new Error(res.error?.message || '删除会话失败')
  }
}

/**
 * 获取会话历史消息
 * GET /api/chat/history/{sessionId}
 */
export async function getSessionMessages(
  sessionId: string,
  limit = 50,
): Promise<Message[]> {
  const res = await get<ApiResponse<{ session_id: string; messages: any[] }>>(
    `/api/chat/history/${sessionId}`,
    { baseURL: AI_API_BASE_URL, params: { limit } },
  )
  if (!res.success || !res.data) {
    throw new Error(res.error?.message || '获取历史消息失败')
  }
  return (res.data.messages || []).map((msg: any) => ({
    id: msg.id,
    session_id: msg.session_id,
    role: msg.role,
    content: msg.content,
    content_type: msg.content_type,
    images: msg.images,
    tool_calls: msg.tool_calls,
    created_at: msg.created_at,
  }))
}

/**
 * 获取快捷操作列表
 * GET /api/chat/quick-actions
 */
export async function getQuickActions(): Promise<QuickAction[]> {
  const res = await get<ApiResponse<{ actions: QuickAction[] }>>(
    '/api/chat/quick-actions',
    { baseURL: AI_API_BASE_URL },
  )
  if (!res.success || !res.data) {
    return []
  }
  return res.data.actions || []
}

/**
 * 发送消息（SSE 流式）
 * POST /api/chat/send — 返回 SSEClient 实例供调用方控制
 */
export function createChatSSEClient(): SSEClient {
  return new SSEClient(AI_API_BASE_URL)
}

export default {
  createSession,
  getSessionList,
  deleteSession,
  getSessionMessages,
  getQuickActions,
  createChatSSEClient,
}
