/**
 * 小程序共享类型定义
 */

// ========== 用户相关 ==========

export interface User {
  id: string
  nickname: string
  avatar: string | null
  tenant_id: number
}

export interface LoginResult {
  success: boolean
  user?: User
  error?: string
}

// ========== 会话相关 ==========

export interface Session {
  id: string
  title: string
  tenant_id?: number
  user_id?: string
  last_message?: string
  message_count?: number
  created_at: string
  updated_at: string
}

// ========== 消息相关 ==========

export interface Message {
  id: string
  session_id?: string
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
  type?: 'text' | 'card' | 'tool_call'
  content_type?: 'text' | 'mixed'
  images?: string[]
  isStreaming?: boolean
  cardData?: CardData
  cards?: CardData[]
  toolCall?: ToolCallData
  tool_calls?: ToolCallData[]
}

export interface CardData {
  type: string // 'product_list' | 'product_detail' | 'logistics' | 'order'
  data: any
}

export interface ToolCallData {
  tool: string
  args?: any
  result?: any
  status: 'running' | 'completed' | 'error'
}

// ========== 快捷操作 ==========

export interface QuickAction {
  id: string
  name: string
  prompt: string
  icon?: string
}

// ========== API 响应 ==========

export interface ApiResponse<T = any> {
  success: boolean
  data?: T
  error?: {
    code: string
    message: string
  }
}

export interface PageResponse<T = any> {
  items: T[]
  page: number
  size: number
  total: number
}

// ========== SSE 事件 ==========

export interface SSETextEvent {
  content: string
}

export interface SSEToolCallEvent {
  tool: string
  args: Record<string, any>
}

export interface SSEToolResultEvent {
  tool: string
  result: Record<string, any>
}

export interface SSECardEvent {
  type: string
  data: any
}

export interface SSEDoneEvent {
  session_id: string
  message_id: string
}

export interface SSEErrorEvent {
  message: string
  code?: string
}

export interface SSELoadingEvent {
  content: string
}
