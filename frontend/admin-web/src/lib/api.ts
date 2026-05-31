import request from './request'
import type { 
  ApiResponse, 
  PageResponse, 
  PageParams,
  Product, 
  ProductListParams, 
  ProductFormData,
  Category,
  CategoryFormData,
  ProcessingItem,
  ProcessingItemListParams,
  ProcessingItemFormData,
  ProcessingCategory,
  ProcessingCategoryFormData,
  ProcessingCalculateParams,
  ProcessingCalculateResult,
  KnowledgeDocument,
  KnowledgeDocumentListParams,
  KnowledgeDocumentUploadForm,
  LoginParams,
  LoginResponse,
  RefreshTokenResponse,
  UserInfoResponse,
  Order,
  OrderListParams,
  OrderFormData,
  OrderStatusUpdateParams,
  LogisticsFormData,
  CloseOrderParams,
  ProductStatus,
  AfterSalesTicket,
  AfterSalesListParams,
  AfterSalesFormData,
  AfterSalesStatusUpdateParams,
  DashboardStats,
  OrderTrendPoint,
  OrderStatusDistribution,
  ActiveSession,
  KnowledgeSearchResult,
  KnowledgeSearchParams,
  Customer,
  CustomerListParams,
  CustomerDetail,
  CustomerTag,
  CustomerTagFormData,
  AiConfig,
  SystemSettings,
  ChangePasswordParams,
  LoginLog,
  UploadedFile,
  Employee,
  EmployeeListParams,
  EmployeeFormData,
  EmployeeStatus,
  ResetPasswordParams,
  Role,
  RoleFormData,
  Permission,
  RegistrationData,
  Registration,
  RegistrationListParams,
  Notification,
  NotificationQueryParams,
  CreateNotificationRequest,
  UnreadCountResponse,
} from '@/types'
import { FrontendToBackendStatus } from '@/types'

// 认证 API
export const authApi = {
  login: (data: LoginParams) => 
    request.post<ApiResponse<LoginResponse>>('/api/auth/admin/login', data),
      
  refreshToken: (refreshToken: string) =>
    request.post<ApiResponse<RefreshTokenResponse>>('/api/auth/refresh', { refreshToken }),
  
  logout: () => 
    request.post('/api/auth/logout'),
  
  getUserInfo: () => 
    request.get<ApiResponse<UserInfoResponse>>('/api/auth/me'),

  sendSmsCode: (phone: string) =>
    request.post<ApiResponse>('/api/auth/sms/send', { phone }),

  smsLogin: (phone: string, code: string) =>
    request.post<ApiResponse<LoginResponse>>('/api/auth/sms/login', { phone, code }),

  submitRegistration: (data: RegistrationData) =>
    request.post<ApiResponse>('/api/auth/register', data),
}

// 商品 API
export const productApi = {
  getProducts: (params?: ProductListParams) => 
    request.get<ApiResponse<PageResponse<Product>>>('/api/admin/products', { params }),
  
  getProduct: (id: string) => 
    request.get<ApiResponse<Product>>(`/api/admin/products/${id}`),
  
  createProduct: (data: ProductFormData) => {
    const { price, images, ...rest } = data
    return request.post<ApiResponse<Product>>('/api/admin/products', {
      ...rest,
      basePrice: price,
      mainImage: images?.[0] || null,
      images,
    })
  },
  
  updateProduct: (id: string, data: ProductFormData) => {
    const { price, images, ...rest } = data
    return request.put<ApiResponse<Product>>(`/api/admin/products/${id}`, {
      ...rest,
      basePrice: price,
      mainImage: images?.[0] || null,
      images,
    })
  },
  
  deleteProduct: (id: string) => 
    request.delete<ApiResponse<void>>(`/api/admin/products/${id}`),
  
  updateProductStatus: (id: string, status: ProductStatus) => 
    request.put<ApiResponse<Product>>(`/api/admin/products/${id}/status`, { status }),

  // 批量上架
  batchOnShelf: (productIds: string[]) =>
    request.post<ApiResponse<void>>('/api/admin/products/batch/on-shelf', { productIds }),

  // 批量下架
  batchOffShelf: (productIds: string[]) =>
    request.post<ApiResponse<void>>('/api/admin/products/batch/off-shelf', { productIds }),

  // 批量删除
  batchDelete: (productIds: string[]) =>
    request.post<ApiResponse<void>>('/api/admin/products/batch/delete', { productIds }),

  // 导出商品（返回 blob）
  exportProducts: (params?: ProductListParams) =>
    request.get<Blob>('/api/admin/products/export', { params, responseType: 'blob' }),

  // 获取指定商品的可选加工项（按商品过滤）
  getProductProcessingItems: (productId: string) =>
    request.get<ApiResponse<ProductProcessingItem[]>>(
      `/api/admin/products/${productId}/processing-items`
    ),
}

// 商品维度的加工项（用于订单创建按商品过滤）
export interface ProductProcessingItem {
  id: string
  name: string
  pricingMethod: string // per_meter | per_piece | fixed | per_area
  unitPrice: number
  customPrice: number | null
  finalPrice: number
  unit: string
}

// 分类 API
export const categoryApi = {
  getCategories: () => 
    request.get<ApiResponse<Category[]>>('/api/admin/categories'),
  
  createCategory: (data: CategoryFormData) => 
    request.post<ApiResponse<Category>>('/api/admin/categories', data),
  
  updateCategory: (id: string, data: CategoryFormData) => 
    request.put<ApiResponse<Category>>(`/api/admin/categories/${id}`, data),
  
  deleteCategory: (id: string) => 
    request.delete<ApiResponse<void>>(`/api/admin/categories/${id}`),
}

// 加工项 API
export const processingItemApi = {
  getProcessingItems: (params?: ProcessingItemListParams) => 
    request.get<ApiResponse<PageResponse<ProcessingItem>>>('/api/admin/processing-items', { params }),
  
  getProcessingItem: (id: string) => 
    request.get<ApiResponse<ProcessingItem>>(`/api/admin/processing-items/${id}`),
  
  createProcessingItem: (data: ProcessingItemFormData) => 
    request.post<ApiResponse<ProcessingItem>>('/api/admin/processing-items', data),
  
  updateProcessingItem: (id: string, data: ProcessingItemFormData) => 
    request.put<ApiResponse<ProcessingItem>>(`/api/admin/processing-items/${id}`, data),
  
  deleteProcessingItem: (id: string) => 
    request.delete<ApiResponse<void>>(`/api/admin/processing-items/${id}`),
  
  calculatePrice: (data: ProcessingCalculateParams) => 
    request.post<ApiResponse<ProcessingCalculateResult>>('/api/admin/processing-items/calculate', data),
}

// 加工分类 API
export const processingCategoryApi = {
  getProcessingCategories: () => 
    request.get<ApiResponse<ProcessingCategory[]>>('/api/admin/processing-categories'),
  
  createProcessingCategory: (data: ProcessingCategoryFormData) => 
    request.post<ApiResponse<ProcessingCategory>>('/api/admin/processing-categories', data),
}

// 知识库 API
export const knowledgeApi = {
  getDocuments: (params?: KnowledgeDocumentListParams) => 
    request.get<ApiResponse<PageResponse<KnowledgeDocument>>>('/api/admin/knowledge/documents', { params }),
  
  uploadDocument: (data: KnowledgeDocumentUploadForm) => {
    const formData = new FormData()
    formData.append('name', data.name)
    formData.append('type', data.type)
    if (data.description) formData.append('description', data.description)
    if (data.file) formData.append('file', data.file)
    
    return request.post<ApiResponse<KnowledgeDocument>>('/api/admin/knowledge/documents', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  
  deleteDocument: (id: string) => 
    request.delete<ApiResponse<void>>(`/api/admin/knowledge/documents/${id}`),

  resyncDocument: (id: string) =>
    request.post<ApiResponse<void>>(`/api/admin/knowledge/documents/${id}/embed`),

  searchKnowledge: (params: KnowledgeSearchParams) =>
    request.post<ApiResponse<{ results: KnowledgeSearchResult[] }>>('/api/admin/knowledge/test-search', params),
}

// 售后工单 API
// TODO: 后端 Controller 尚未完成，使用约定的 RESTful 路径
export const afterSalesApi = {
  getTickets: (params?: AfterSalesListParams) =>
    request.get<ApiResponse<PageResponse<AfterSalesTicket>>>('/api/admin/after-sales', { params }),

  getTicket: (id: string) =>
    request.get<ApiResponse<AfterSalesTicket>>(`/api/admin/after-sales/${id}`),

  createTicket: (data: AfterSalesFormData) =>
    request.post<ApiResponse<AfterSalesTicket>>('/api/admin/after-sales', data),

  updateTicketStatus: (id: string, data: AfterSalesStatusUpdateParams) =>
    request.put<ApiResponse<void>>(`/api/admin/after-sales/${id}/status`, data),
}

// 订单 API
export const orderApi = {
  // 获取订单列表（支持分页和筛选）
  getOrders: (params?: OrderListParams) => 
    request.get<ApiResponse<PageResponse<Order>>>('/api/admin/orders', { params }),
  
  // 获取单个订单详情
  getOrder: (id: string) => 
    request.get<ApiResponse<Order>>(`/api/admin/orders/${id}`),
  
  // 创建订单
  createOrder: (data: OrderFormData) => 
    request.post<ApiResponse<Order>>('/api/admin/orders', data),
  
  // 更新订单状态（可选携带物流信息）
  // 后端只接收 { status }，且 status 为后端枚举。这里自动将前端枚举映射为后端枚举。
  updateOrderStatus: (id: string, data: OrderStatusUpdateParams) => {
    const backendStatus = FrontendToBackendStatus[data.status] ?? (data.status as unknown as string)
    return request.put<ApiResponse<void>>(`/api/admin/orders/${id}/status`, {
      status: backendStatus,
    })
  },
  
  // 更新物流信息（发货）
  // 后端实际只接收 { logisticsCompany, trackingNo }。
  updateLogistics: (id: string, data: LogisticsFormData) =>
    request.put<ApiResponse<void>>(`/api/admin/orders/${id}/logistics`, {
      logisticsCompany: data.company,
      trackingNo: data.trackingNo,
    }),

  // 关闭订单 → 后端实际为取消订单接口（无 body）
  closeOrder: (id: string, _data?: CloseOrderParams) =>
    request.put<ApiResponse<void>>(`/api/admin/orders/${id}/cancel`),

  // 确认付款
  confirmPayment: (id: string) =>
    request.put<ApiResponse<void>>(`/api/admin/orders/${id}/payment`),

  // 退款
  refundOrder: (id: string) =>
    request.put<ApiResponse<void>>(`/api/admin/orders/${id}/refund`),

  // 添加备注：后端暂未提供该接口，暂返回 mock 成功响应
  addRemark: async (id: string, content: string): Promise<{ data: ApiResponse<void> }> => {
    console.warn(
      `[orderApi.addRemark] 后端暂未提供 POST /api/admin/orders/${id}/remarks 接口，跳过请求。content=`,
      content
    )
    return { data: { code: 0, message: 'mock', data: undefined as unknown as void, success: true } }
  },

  // 删除订单
  deleteOrder: (id: string) =>
    request.delete<ApiResponse<void>>(`/api/admin/orders/${id}`),
}

// Dashboard API
// TODO: 后端 API 尚未完全就绪，当前使用 Mock 数据
export const dashboardApi = {
  getStats: () =>
    request.get<ApiResponse<DashboardStats>>('/api/admin/dashboard/stats'),

  getOrderTrend: (days: number = 7) =>
    request.get<ApiResponse<OrderTrendPoint[]>>('/api/admin/dashboard/order-trend', { params: { days } }),

  getOrderStatusDistribution: () =>
    request.get<ApiResponse<OrderStatusDistribution[]>>('/api/admin/dashboard/order-status'),

  getRecentOrders: (limit: number = 5) =>
    request.get<ApiResponse<Order[]>>('/api/admin/dashboard/recent-orders', { params: { limit } }),

  getActiveSessions: (limit: number = 5) =>
    request.get<ApiResponse<ActiveSession[]>>('/api/admin/dashboard/active-sessions', { params: { limit } }),
}

// 上传 API
export const uploadApi = {
  uploadImage: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return request.post<ApiResponse<{ url: string }>>('/api/admin/upload/image', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
}

// 文件上传 API
export const fileApi = {
  /** 单文件上传 */
  uploadFile: (file: File, directory?: string, onProgress?: (percent: number) => void) => {
    const formData = new FormData()
    formData.append('file', file)
    if (directory) formData.append('directory', directory)
    return request.post<ApiResponse<UploadedFile>>('/api/admin/files/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total)
          onProgress(percent)
        }
      },
    })
  },

  /** 批量上传 */
  uploadFiles: (files: File[], directory?: string, onProgress?: (percent: number) => void) => {
    const formData = new FormData()
    files.forEach((file) => formData.append('files', file))
    if (directory) formData.append('directory', directory)
    return request.post<ApiResponse<UploadedFile[]>>('/api/admin/files/upload-batch', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total)
          onProgress(percent)
        }
      },
    })
  },

  /** 删除文件 */
  deleteFile: (fileId: string, url?: string) =>
    request.delete<ApiResponse<void>>(`/api/admin/files/${fileId}`, {
      data: url ? { url } : undefined,
    }),
}

// ========== 聊天 API ==========
// AI Agent 服务部署地址（通过环境变量配置，见 .env.production / .env.development）
const AI_SERVICE_URL = process.env.NEXT_PUBLIC_AI_API_BASE_URL || 'http://localhost:8001'

export const chatApi = {
  /** 获取会话列表 */
  getSessions: async (token: string) => {
    const res = await fetch(`${AI_SERVICE_URL}/api/chat/sessions`, {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
    if (!res.ok) throw new Error(`获取会话列表失败: ${res.status}`)
    return res.json()
  },

  /** 创建新会话 */
  createSession: async (token: string) => {
    const res = await fetch(`${AI_SERVICE_URL}/api/chat/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ platform: 'web' }),
    })
    if (!res.ok) throw new Error(`创建会话失败: ${res.status}`)
    return res.json()
  },

  /** 获取历史消息 */
  getHistory: async (sessionId: string, token: string) => {
    const res = await fetch(`${AI_SERVICE_URL}/api/chat/history/${sessionId}`, {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
    if (!res.ok) throw new Error(`获取历史消息失败: ${res.status}`)
    return res.json()
  },

  /** 结束会话（仅转换状态为 closed，保留历史消息） */
  closeSession: async (sessionId: string, token: string) => {
    const res = await fetch(`${AI_SERVICE_URL}/api/chat/sessions/${sessionId}/close`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
    if (!res.ok) throw new Error(`结束会话失败: ${res.status}`)
    return res.json()
  },

  /** 删除会话（物理删除会话及其所有消息） */
  deleteSession: async (sessionId: string, token: string) => {
    const res = await fetch(`${AI_SERVICE_URL}/api/chat/sessions/${sessionId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
    if (!res.ok) throw new Error(`结束会话失败: ${res.status}`)
    return res.json()
  },

  /** 发送消息（SSE 流式，返回 Response 供调用方处理流） */
  sendMessage: async (sessionId: string, message: string, token: string) => {
    const res = await fetch(`${AI_SERVICE_URL}/api/chat/send`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({
        session_id: sessionId,
        message,
      }),
    })
    if (!res.ok) throw new Error(`发送消息失败: ${res.status}`)
    return res
  },

  /** 聊天图片上传（最多3张） */
  uploadChatImages: async (files: File[], token: string) => {
    const formData = new FormData()
    files.forEach((file) => formData.append('files', file))
    const res = await fetch(`${AI_SERVICE_URL}/api/chat/upload-image`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
      },
      body: formData,
    })
    if (!res.ok) throw new Error(`图片上传失败: ${res.status}`)
    return res.json() as Promise<{ success: boolean; data: { files: { id: string; url: string; name: string; size: number }[] } }>
  },

  /** AI 服务基地址 */
  AI_SERVICE_URL,
}

// 客户管理 API
export const customerApi = {
  getCustomers: (params?: CustomerListParams) =>
    request.get<ApiResponse<PageResponse<Customer>>>('/api/admin/customers', { params }),

  getCustomer: (id: string) =>
    request.get<ApiResponse<CustomerDetail>>(`/api/admin/customers/${id}`),

  updateCustomer: (id: string, data: Partial<Customer>) =>
    request.put<ApiResponse<Customer>>(`/api/admin/customers/${id}`, data),

  getCustomerTags: () =>
    request.get<ApiResponse<CustomerTag[]>>('/api/admin/customer-tags'),

  createCustomerTag: (data: CustomerTagFormData) =>
    request.post<ApiResponse<CustomerTag>>('/api/admin/customer-tags', data),

  updateCustomerTag: (id: string, data: CustomerTagFormData) =>
    request.put<ApiResponse<CustomerTag>>(`/api/admin/customer-tags/${id}`, data),

  deleteCustomerTag: (id: string) =>
    request.delete<ApiResponse<void>>(`/api/admin/customer-tags/${id}`),

  addTagToCustomer: (customerId: string, tagId: string) =>
    request.post<ApiResponse<void>>(`/api/admin/customers/${customerId}/tags/${tagId}`),

  removeTagFromCustomer: (customerId: string, tagId: string) =>
    request.delete<ApiResponse<void>>(`/api/admin/customers/${customerId}/tags/${tagId}`),
}

// 系统设置 API
export const settingsApi = {
  getSettings: () =>
    request.get<ApiResponse<SystemSettings>>('/api/admin/settings'),

  updateSettings: (data: Partial<SystemSettings>) =>
    request.put<ApiResponse<SystemSettings>>('/api/admin/settings', data),

  getAiConfig: () =>
    request.get<ApiResponse<AiConfig>>('/api/admin/tenant/ai-config'),

  updateAiConfig: (data: Partial<AiConfig>) =>
    request.put<ApiResponse<AiConfig>>('/api/admin/tenant/ai-config', data),

  changePassword: (data: ChangePasswordParams) =>
    request.put<ApiResponse<void>>('/api/admin/settings/password', data),

  getLoginLogs: (params?: PageParams) =>
    request.get<ApiResponse<PageResponse<LoginLog>>>('/api/admin/settings/login-logs', { params }),
}

// 员工管理 API
export const employeeApi = {
  getEmployees: (params?: EmployeeListParams) =>
    request.get<ApiResponse<PageResponse<Employee>>>('/api/admin/users', { params }),

  getEmployee: (id: number) =>
    request.get<ApiResponse<Employee>>(`/api/admin/users/${id}`),

  createEmployee: (data: EmployeeFormData) =>
    request.post<ApiResponse<Employee>>('/api/admin/users', data),

  updateEmployee: (id: number, data: Partial<EmployeeFormData>) =>
    request.put<ApiResponse<Employee>>(`/api/admin/users/${id}`, data),

  deleteEmployee: (id: number) =>
    request.delete<ApiResponse<void>>(`/api/admin/users/${id}`),

  resetPassword: (id: number, data: ResetPasswordParams) =>
    request.put<ApiResponse<void>>(`/api/admin/users/${id}/reset-password`, data),

  toggleEmployeeStatus: (id: number, status: EmployeeStatus) =>
    request.put<ApiResponse<void>>(`/api/admin/users/${id}/status`, { status }),
}

// 角色管理 API
export const roleApi = {
  getRoles: (params?: PageParams) =>
    request.get<ApiResponse<PageResponse<Role>>>('/api/admin/roles', { params }),

  getAllRoles: () =>
    request.get<ApiResponse<Role[]>>('/api/admin/roles/all'),

  getRole: (id: number) =>
    request.get<ApiResponse<Role>>(`/api/admin/roles/${id}`),

  createRole: (data: RoleFormData) =>
    request.post<ApiResponse<Role>>('/api/admin/roles', data),

  updateRole: (id: number, data: RoleFormData) =>
    request.put<ApiResponse<Role>>(`/api/admin/roles/${id}`, data),

  deleteRole: (id: number) =>
    request.delete<ApiResponse<void>>(`/api/admin/roles/${id}`),
}

// 权限管理 API
export const permissionApi = {
  getPermissions: () =>
    request.get<ApiResponse<Permission[]>>('/api/admin/permissions'),
}

// 通知 API
export const notificationApi = {
  getNotifications: (params?: NotificationQueryParams) =>
    request.get<ApiResponse<PageResponse<Notification>>>('/api/admin/notifications', { params }),

  getUnreadCount: () =>
    request.get<ApiResponse<UnreadCountResponse>>('/api/admin/notifications/unread-count'),

  markAsRead: (id: string) =>
    request.put<ApiResponse<void>>(`/api/admin/notifications/${id}/read`),

  markAllAsRead: () =>
    request.put<ApiResponse<void>>('/api/admin/notifications/read-all'),

  deleteNotification: (id: string) =>
    request.delete<ApiResponse<void>>(`/api/admin/notifications/${id}`),

  createNotification: (data: CreateNotificationRequest) =>
    request.post<ApiResponse<Notification>>('/api/admin/notifications', data),
}

// 超管 - 企业入驻审批 API
export const registrationApi = {
  getRegistrations: (params?: RegistrationListParams) =>
    request.get<ApiResponse<PageResponse<Registration>>>('/api/super-admin/registrations', { params }),

  getRegistrationDetail: (id: number) =>
    request.get<ApiResponse<Registration>>(`/api/super-admin/registrations/${id}`),

  approveRegistration: (id: number) =>
    request.put<ApiResponse<void>>(`/api/super-admin/registrations/${id}/approve`, {}),

  rejectRegistration: (id: number, reason: string) =>
    request.put<ApiResponse<void>>(`/api/super-admin/registrations/${id}/reject`, { rejectReason: reason }),
}

// ==================== 客服工作台类型 ====================

/** 客服工作台会话（内部客服人员接待C端消费者的人工服务会话） */
export interface AgentSession {
  id: string
  customerId: string
  customerName?: string
  employeeId: string
  employeeName?: string
  aiSessionId: string
  status: 'waiting' | 'active' | 'ended' | 'transferred'
  priority: number
  reason: string
  queuePosition: number
  messageCount?: number
  startedAt: string
  endedAt?: string
  createdAt: string
}

/** 客服工作台会话详情 */
export interface AgentSessionDetail extends AgentSession {
  messages: AgentMessageItem[]
  customerPhone?: string
  customerAvatarUrl?: string
}

/** 客服工作台消息 */
export interface AgentMessageItem {
  id: string
  senderType: 'customer' | 'agent' | 'system'
  senderId: string
  senderName?: string
  contentType: 'text' | 'image' | 'file' | 'system'
  content: string
  isInternal: boolean
  createdAt: string
}

/** 监控面板统计数据 */
export interface MonitorStats {
  onlineEmployeeCount: number
  activeSessionCount: number
  waitingSessionCount: number
  todayTotalSessions: number
  todayAvgResponseTime: number
  onlineEmployees: EmployeeStatusInfo[]
}

/** 员工状态信息 */
export interface EmployeeStatusInfo {
  id: string
  name: string
  status: string
  activeSessionCount: number
  maxConcurrentSessions: number
}

/** 快捷回复模板 */
export interface QuickReplyTemplate {
  id: string
  category: string
  title: string
  content: string
  shortcut?: string
  usageCount: number
  isPublic: boolean
  createdBy?: string
  createdAt: string
  updatedAt: string
}

/** 创建快捷回复请求 */
export interface QuickReplyCreateParams {
  category: string
  title: string
  content: string
  shortcut?: string
  isPublic?: boolean
}

/** 更新快捷回复请求 */
export interface QuickReplyUpdateParams {
  category?: string
  title?: string
  content?: string
  shortcut?: string
  isPublic?: boolean
}

/** 会话列表查询参数 */
export interface AgentSessionListParams {
  page?: number
  size?: number
  status?: string
  employeeId?: string
  keyword?: string
}

/** 快捷回复列表查询参数 */
export interface QuickReplyListParams {
  page?: number
  size?: number
  category?: string
  keyword?: string
}

// ==================== 客服工作台 API ====================

/** 客服工作台会话管理API（面向企业内部客服人员） */
export const agentSessionApi = {
  /** 分页查询会话列表 */
  getSessions: (params?: AgentSessionListParams) =>
    request.get<ApiResponse<PageResponse<AgentSession>>>('/api/admin/agent-sessions', { params }),
  /** 获取会话详情（含消息列表） */
  getSession: (id: string) =>
    request.get<ApiResponse<AgentSessionDetail>>(`/api/admin/agent-sessions/${id}`),
  /** 手动分配会话给客服员工 */
  assignSession: (id: string, employeeId: string) =>
    request.post<ApiResponse<void>>(`/api/admin/agent-sessions/${id}/assign`, { employeeId }),
  /** 结束会话 */
  endSession: (id: string) =>
    request.post<ApiResponse<void>>(`/api/admin/agent-sessions/${id}/end`),
  /** 获取监控面板数据 */
  getMonitorStats: () =>
    request.get<ApiResponse<MonitorStats>>('/api/admin/agent-sessions/monitor'),
}

/** 快捷回复模板管理API */
export const quickReplyApi = {
  /** 分页查询模板列表 */
  getTemplates: (params?: QuickReplyListParams) =>
    request.get<ApiResponse<PageResponse<QuickReplyTemplate>>>('/api/admin/quick-replies', { params }),
  /** 创建模板 */
  createTemplate: (data: QuickReplyCreateParams) =>
    request.post<ApiResponse<QuickReplyTemplate>>('/api/admin/quick-replies', data),
  /** 更新模板 */
  updateTemplate: (id: string, data: QuickReplyUpdateParams) =>
    request.put<ApiResponse<QuickReplyTemplate>>(`/api/admin/quick-replies/${id}`, data),
  /** 删除模板 */
  deleteTemplate: (id: string) =>
    request.delete<ApiResponse<void>>(`/api/admin/quick-replies/${id}`),
  /** 获取所有分类列表 */
  getCategories: () =>
    request.get<ApiResponse<string[]>>('/api/admin/quick-replies/categories'),
}

const api = {
  auth: authApi,
  product: productApi,
  category: categoryApi,
  processingItem: processingItemApi,
  processingCategory: processingCategoryApi,
  knowledge: knowledgeApi,
  afterSales: afterSalesApi,
  order: orderApi,
  dashboard: dashboardApi,
  upload: uploadApi,
  file: fileApi,
  chat: chatApi,
  customer: customerApi,
  settings: settingsApi,
  employee: employeeApi,
  role: roleApi,
  permission: permissionApi,
  registration: registrationApi,
  notification: notificationApi,
  agentSession: agentSessionApi,
  quickReply: quickReplyApi,
}

export default api
