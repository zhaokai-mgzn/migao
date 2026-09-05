/**
 * 小程序共享类型定义
 */

// ========== 用户相关 ==========

export interface User {
  id: string
  nickname: string
  avatar: string | null
  tenant_id: number
  /** 企业名（租户公司名，来自企业基础信息设置；C 端导航副标题展示用，UI-016）。
   *  注意：数据源是 admin-api（camelCase JSON），字段名与后端 tenantName 一致 */
  tenantName?: string | null
  /** 智能客服名称（TenantAiConfig.botName，C 端思考中/空态/导航名展示，UI-018；未配置为 null → 前端兜底「小布」） */
  botName?: string | null
  /** 已绑定的手机号（微信授权绑定后回填；用于名下商户代录订单的 phone 兜底展示） */
  phone?: string | null
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
  /** 消息来源（GB/T 47746-2026 人机区分，issue #2780）：ai=AI 助手；human=人工客服 */
  source?: 'ai' | 'human'
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
  interactive?: InteractiveData
  suggestions?: string[]
}

export interface CardData {
  type: string // 'product_list' | 'product_detail' | 'logistics' | 'order'
  data: any
}

/** 交互式组件数据（interact 工具下发，SSE interactive 事件） */
export interface InteractiveData {
  type: 'choice' | 'confirm' | 'form'
  component?: string
  title: string
  options?: Array<{ label: string; value: string; description?: string }>
  fields?: Array<{ label: string; value: string }>
  confirmLabel?: string
  cancelLabel?: string
  confirmValue?: string
  cancelValue?: string
  formFields?: Array<{
    key: string
    label: string
    placeholder?: string
    value?: string
    required?: boolean
  }>
  submitLabel?: string
  /** 订单确认附加交互（瑞幸式：配送方式/支付方式选择），仅 confirm 组件在说明是订单确认时携带 */
  orderConfirm?: boolean
  deliveryOptions?: Array<{ label: string; value: string }>
  paymentOptions?: Array<{ label: string; value: string }>
  /** 应付金额（展示用） */
  amount?: string
  /** 翻页元信息（choice 组件分页查询下发） */
  pageMeta?: {
    current: number
    total: number
    totalCount?: number
    tool?: string
    params?: string
  }
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

export interface SSEInteractiveEvent {
  type: string
  component?: string
  title?: string
  [key: string]: any
}

export interface SSESuggestionsEvent {
  questions: string[]
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
