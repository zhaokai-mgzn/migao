/**
 * API Helper — Direct HTTP client for test setup / teardown / assertions.
 *
 * Mirrors every endpoint defined in src/lib/api.ts.
 * Uses Playwright's APIRequestContext so it integrates with test fixtures.
 *
 * Backend base URL: http://localhost:8080  (NEXT_PUBLIC_API_BASE_URL)
 * AI service URL:  http://localhost:8001  (NEXT_PUBLIC_AI_API_BASE_URL)
 *
 * All admin APIs: /api/admin/*
 * Auth APIs:      /api/auth/*
 * Chat APIs:      ${AI_SERVICE_URL}/api/chat/*
 */
import { type APIRequestContext, type APIResponse, request as pwRequest } from '@playwright/test'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8080'
const AI_SERVICE_URL = process.env.NEXT_PUBLIC_AI_API_BASE_URL || 'http://localhost:8001'

export class ApiHelper {
  private ctx: APIRequestContext
  private token: string

  constructor(accessToken: string) {
    this.token = accessToken
    // Lazy-init: Playwright request context is created in the static factory.
    // We assign it externally in create().
    this.ctx = null as unknown as APIRequestContext
  }

  /** Factory — creates the underlying APIRequestContext */
  static async create(accessToken: string): Promise<ApiHelper> {
    const helper = new ApiHelper(accessToken)
    helper.ctx = await pwRequest.newContext({
      extraHTTPHeaders: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
    })
    return helper
  }

  /** Dispose the underlying request context */
  async dispose(): Promise<void> {
    await this.ctx?.dispose()
  }

  /** Update the auth token (e.g. after token refresh) */
  setToken(token: string): void {
    this.token = token
  }

  // ────────────────────────────────────────────
  // Internal helpers
  // ────────────────────────────────────────────

  private url(path: string): string {
    return `${API_BASE_URL}${path}`
  }

  private aiUrl(path: string): string {
    return `${AI_SERVICE_URL}${path}`
  }

  // ────────────────────────────────────────────
  // Auth
  // ────────────────────────────────────────────

  async login(data: { username: string; password: string; tenantId?: number }): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/auth/admin/login'), { data })
  }

  async refreshToken(refreshToken: string): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/auth/refresh'), { data: { refreshToken } })
  }

  async logout(): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/auth/logout'))
  }

  async getUserInfo(): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/auth/me'))
  }

  async sendSmsCode(phone: string): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/auth/sms/send'), { data: { phone } })
  }

  async smsLogin(phone: string, code: string): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/auth/sms/login'), { data: { phone, code } })
  }

  // ────────────────────────────────────────────
  // Products
  // ────────────────────────────────────────────

  async createProduct(data: Record<string, unknown>): Promise<APIResponse> {
    // api.ts maps `price` → `basePrice` and `images[0]` → `mainImage`
    const { price, images, ...rest } = data as any
    return this.ctx.post(this.url('/api/admin/products'), {
      data: { ...rest, basePrice: price, mainImage: images?.[0] ?? null, images },
    })
  }

  async getProduct(id: string): Promise<APIResponse> {
    return this.ctx.get(this.url(`/api/admin/products/${id}`))
  }

  async listProducts(params?: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/products'), { params: params as Record<string, string> })
  }

  async updateProduct(id: string, data: Record<string, unknown>): Promise<APIResponse> {
    const { price, images, ...rest } = data as any
    return this.ctx.put(this.url(`/api/admin/products/${id}`), {
      data: { ...rest, basePrice: price, mainImage: images?.[0] ?? null, images },
    })
  }

  async deleteProduct(id: string): Promise<APIResponse> {
    return this.ctx.delete(this.url(`/api/admin/products/${id}`))
  }

  async updateProductStatus(id: string, status: string): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/admin/products/${id}/status`), { data: { status } })
  }

  async batchOnShelf(productIds: string[]): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/admin/products/batch/on-shelf'), { data: { productIds } })
  }

  async batchOffShelf(productIds: string[]): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/admin/products/batch/off-shelf'), { data: { productIds } })
  }

  async batchDelete(productIds: string[]): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/admin/products/batch/delete'), { data: { productIds } })
  }

  // ────────────────────────────────────────────
  // Orders
  // ────────────────────────────────────────────

  async createOrder(data: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/admin/orders'), { data })
  }

  async getOrder(id: string): Promise<APIResponse> {
    return this.ctx.get(this.url(`/api/admin/orders/${id}`))
  }

  async listOrders(params?: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/orders'), { params: params as Record<string, string> })
  }

  /**
   * Update order status.
   * api.ts maps frontend status → backend status via FrontendToBackendStatus.
   * We accept the frontend status here and do the same mapping.
   */
  async updateOrderStatus(id: string, frontendStatus: string): Promise<APIResponse> {
    const FE_TO_BE: Record<string, string> = {
      pending_payment: 'pending',
      pending_shipment: 'confirmed',
      shipped: 'shipped',
      completed: 'completed',
      closed: 'cancelled',
      refund: 'cancelled',
    }
    const backendStatus = FE_TO_BE[frontendStatus] ?? frontendStatus
    return this.ctx.put(this.url(`/api/admin/orders/${id}/status`), {
      data: { status: backendStatus },
    })
  }

  async updateLogistics(id: string, company: string, trackingNo: string): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/admin/orders/${id}/logistics`), {
      data: { logisticsCompany: company, trackingNo },
    })
  }

  async confirmPayment(id: string): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/admin/orders/${id}/payment`))
  }

  async closeOrder(id: string, reason?: string): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/admin/orders/${id}/cancel`), {
      data: { closeReason: reason || '' },
    })
  }

  async refundOrder(id: string): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/admin/orders/${id}/refund`))
  }

  async addOrderRemark(id: string, content: string): Promise<APIResponse> {
    return this.ctx.post(this.url(`/api/admin/orders/${id}/remark`), { data: { content } })
  }

  async deleteOrder(id: string): Promise<APIResponse> {
    return this.ctx.delete(this.url(`/api/admin/orders/${id}`))
  }

  // ────────────────────────────────────────────
  // Categories
  // ────────────────────────────────────────────

  async createCategory(data: { name: string; parentId?: string; sort?: number }): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/admin/categories'), { data })
  }

  async listCategories(): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/categories'))
  }

  async updateCategory(id: string, data: { name: string; parentId?: string; sort?: number }): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/admin/categories/${id}`), { data })
  }

  async deleteCategory(id: string): Promise<APIResponse> {
    return this.ctx.delete(this.url(`/api/admin/categories/${id}`))
  }

  // ────────────────────────────────────────────
  // Processing Items
  // ────────────────────────────────────────────

  async createProcessingItem(data: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/admin/processing-items'), { data })
  }

  async listProcessingItems(params?: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/processing-items'), { params: params as Record<string, string> })
  }

  async getProcessingItem(id: string): Promise<APIResponse> {
    return this.ctx.get(this.url(`/api/admin/processing-items/${id}`))
  }

  async updateProcessingItem(id: string, data: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/admin/processing-items/${id}`), { data })
  }

  async deleteProcessingItem(id: string): Promise<APIResponse> {
    return this.ctx.delete(this.url(`/api/admin/processing-items/${id}`))
  }

  // ────────────────────────────────────────────
  // Customers
  // ────────────────────────────────────────────

  async listCustomers(params?: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/customers'), { params: params as Record<string, string> })
  }

  async getCustomer(id: string): Promise<APIResponse> {
    return this.ctx.get(this.url(`/api/admin/customers/${id}`))
  }

  async updateCustomer(id: string, data: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/admin/customers/${id}`), { data })
  }

  async listCustomerTags(): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/customer-tags'))
  }

  async createCustomerTag(data: { name: string; color: string }): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/admin/customer-tags'), { data })
  }

  async deleteCustomerTag(id: string): Promise<APIResponse> {
    return this.ctx.delete(this.url(`/api/admin/customer-tags/${id}`))
  }

  // ────────────────────────────────────────────
  // After-Sales
  // ────────────────────────────────────────────

  async createAfterSalesTicket(data: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/admin/after-sales'), { data })
  }

  async getAfterSalesTicket(id: string): Promise<APIResponse> {
    return this.ctx.get(this.url(`/api/admin/after-sales/${id}`))
  }

  async listAfterSalesTickets(params?: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/after-sales'), { params: params as Record<string, string> })
  }

  async updateAfterSalesStatus(id: string, status: string, remark?: string): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/admin/after-sales/${id}/status`), {
      data: { status, remark },
    })
  }

  // ────────────────────────────────────────────
  // Employees / Users
  // ────────────────────────────────────────────

  async createEmployee(data: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/admin/users'), { data })
  }

  async listEmployees(params?: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/users'), { params: params as Record<string, string> })
  }

  async getEmployee(id: number): Promise<APIResponse> {
    return this.ctx.get(this.url(`/api/admin/users/${id}`))
  }

  async updateEmployee(id: number, data: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/admin/users/${id}`), { data })
  }

  async deleteEmployee(id: number): Promise<APIResponse> {
    return this.ctx.delete(this.url(`/api/admin/users/${id}`))
  }

  async resetPassword(id: number, newPassword: string): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/admin/users/${id}/reset-password`), {
      data: { newPassword },
    })
  }

  async toggleEmployeeStatus(id: number, status: 'active' | 'disabled'): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/admin/users/${id}/status`), { data: { status } })
  }

  // ────────────────────────────────────────────
  // Roles
  // ────────────────────────────────────────────

  async createRole(data: { name: string; code: string; description?: string; permissionIds: number[] }): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/admin/roles'), { data })
  }

  async listRoles(params?: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/roles'), { params: params as Record<string, string> })
  }

  async getAllRoles(): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/roles/all'))
  }

  async getRole(id: number): Promise<APIResponse> {
    return this.ctx.get(this.url(`/api/admin/roles/${id}`))
  }

  async updateRole(id: number, data: { name: string; code: string; description?: string; permissionIds: number[] }): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/admin/roles/${id}`), { data })
  }

  async deleteRole(id: number): Promise<APIResponse> {
    return this.ctx.delete(this.url(`/api/admin/roles/${id}`))
  }

  // ────────────────────────────────────────────
  // Permissions
  // ────────────────────────────────────────────

  async listPermissions(): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/permissions'))
  }

  // ────────────────────────────────────────────
  // Notifications
  // ────────────────────────────────────────────

  async listNotifications(params?: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/notifications'), { params: params as Record<string, string> })
  }

  async getUnreadCount(): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/notifications/unread-count'))
  }

  async markNotificationRead(id: string): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/admin/notifications/${id}/read`))
  }

  async markAllNotificationsRead(): Promise<APIResponse> {
    return this.ctx.put(this.url('/api/admin/notifications/read-all'))
  }

  async deleteNotification(id: string): Promise<APIResponse> {
    return this.ctx.delete(this.url(`/api/admin/notifications/${id}`))
  }

  async createNotification(data: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/admin/notifications'), { data })
  }

  // ────────────────────────────────────────────
  // Dashboard
  // ────────────────────────────────────────────

  async getDashboardStats(): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/dashboard/stats'))
  }

  async getOrderTrend(days = 7): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/dashboard/order-trend'), {
      params: { days: String(days) },
    })
  }

  async getOrderStatusDistribution(): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/dashboard/order-status'))
  }

  async getRecentOrders(limit = 5): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/dashboard/recent-orders'), {
      params: { limit: String(limit) },
    })
  }

  async getActiveSessions(limit = 5): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/dashboard/active-sessions'), {
      params: { limit: String(limit) },
    })
  }

  // ────────────────────────────────────────────
  // Knowledge
  // ────────────────────────────────────────────

  async listKnowledgeDocuments(params?: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/knowledge/documents'), { params: params as Record<string, string> })
  }

  async deleteKnowledgeDocument(id: string): Promise<APIResponse> {
    return this.ctx.delete(this.url(`/api/admin/knowledge/documents/${id}`))
  }

  async resyncKnowledgeDocument(id: string): Promise<APIResponse> {
    return this.ctx.post(this.url(`/api/admin/knowledge/documents/${id}/embed`))
  }

  async searchKnowledge(query: string, topK = 5): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/admin/knowledge/test-search'), {
      data: { query, topK },
    })
  }

  // ────────────────────────────────────────────
  // Chat (AI Service)
  // ────────────────────────────────────────────

  async createChatSession(): Promise<APIResponse> {
    return this.ctx.post(this.aiUrl('/api/chat/sessions'), {
      data: { platform: 'web' },
    })
  }

  /**
   * Send a chat message — returns the raw APIResponse (SSE stream).
   * The caller should use SSEHelper to parse the stream.
   */
  async sendChatMessage(sessionId: string, message: string): Promise<APIResponse> {
    return this.ctx.post(this.aiUrl('/api/chat/send'), {
      data: { session_id: sessionId, message },
    })
  }

  async getChatSessions(): Promise<APIResponse> {
    return this.ctx.get(this.aiUrl('/api/chat/sessions'))
  }

  async getChatHistory(sessionId: string): Promise<APIResponse> {
    return this.ctx.get(this.aiUrl(`/api/chat/history/${sessionId}`))
  }

  async closeChatSession(sessionId: string): Promise<APIResponse> {
    return this.ctx.put(this.aiUrl(`/api/chat/sessions/${sessionId}/close`))
  }

  async deleteChatSession(sessionId: string): Promise<APIResponse> {
    return this.ctx.delete(this.aiUrl(`/api/chat/sessions/${sessionId}`))
  }

  // ────────────────────────────────────────────
  // Settings
  // ────────────────────────────────────────────

  async getSettings(): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/settings'))
  }

  async updateSettings(data: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.put(this.url('/api/admin/settings'), { data })
  }

  async getAiConfig(): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/tenant/ai-config'))
  }

  async updateAiConfig(data: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.put(this.url('/api/admin/tenant/ai-config'), { data })
  }

  async changePassword(oldPassword: string, newPassword: string, confirmPassword: string): Promise<APIResponse> {
    return this.ctx.put(this.url('/api/admin/settings/password'), {
      data: { oldPassword, newPassword, confirmPassword },
    })
  }

  async getLoginLogs(params?: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/settings/login-logs'), { params: params as Record<string, string> })
  }

  // ────────────────────────────────────────────
  // Agent Sessions (客服工作台)
  // ────────────────────────────────────────────

  async listAgentSessions(params?: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/agent-sessions'), { params: params as Record<string, string> })
  }

  async getAgentSession(id: string): Promise<APIResponse> {
    return this.ctx.get(this.url(`/api/admin/agent-sessions/${id}`))
  }

  async assignAgentSession(id: string, employeeId: string): Promise<APIResponse> {
    return this.ctx.post(this.url(`/api/admin/agent-sessions/${id}/assign`), { data: { employeeId } })
  }

  async endAgentSession(id: string): Promise<APIResponse> {
    return this.ctx.post(this.url(`/api/admin/agent-sessions/${id}/end`))
  }

  async getMonitorStats(): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/agent-sessions/monitor'))
  }

  // ────────────────────────────────────────────
  // Quick Replies
  // ────────────────────────────────────────────

  async listQuickReplies(params?: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/admin/quick-replies'), { params: params as Record<string, string> })
  }

  async createQuickReply(data: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.post(this.url('/api/admin/quick-replies'), { data })
  }

  async updateQuickReply(id: string, data: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/admin/quick-replies/${id}`), { data })
  }

  async deleteQuickReply(id: string): Promise<APIResponse> {
    return this.ctx.delete(this.url(`/api/admin/quick-replies/${id}`))
  }

  // ────────────────────────────────────────────
  // Registrations (超管 — 企业入驻审批)
  // ────────────────────────────────────────────

  async listRegistrations(params?: Record<string, unknown>): Promise<APIResponse> {
    return this.ctx.get(this.url('/api/super-admin/registrations'), { params: params as Record<string, string> })
  }

  async approveRegistration(id: number): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/super-admin/registrations/${id}/approve`), { data: {} })
  }

  async rejectRegistration(id: number, reason: string): Promise<APIResponse> {
    return this.ctx.put(this.url(`/api/super-admin/registrations/${id}/reject`), {
      data: { rejectReason: reason },
    })
  }
}
