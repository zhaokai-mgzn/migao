import request from './request'
import {
  buildProductPayload,
  buildLogisticsPayload,
  buildCloseOrderPayload,
  buildRefundPayload,
} from './data-adapter'
import type { RefundOrderParams } from './data-adapter'
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
  KnowledgeCard,
  KnowledgeCardListParams,
  KnowledgeCandidate,
  KnowledgeTemplateInfo,
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
  ProcessingOrder,
  ProcessingOrderGenerateResult,
  ProcessingOrderUpdateParams,
  ProductionOperations,
  PieceworkSummary,
  OperationsCatalog,
  RoutingsResponse,
  PieceworkReport,
  CatalogOperation,
  ProductionOperationUpdateParams,
  Routing,
  RoutingCreateParams,
  RoutingGaps,
  // 加工费组合定价（issue #4386）
  FeeCombination,
  FeeCombinationsResponse,
  FeeCombinationCreateParams,
  FeeCombinationUpdateParams,
  FeeGaps,
  RouteOperationCreateParams,
  RouteSignal,
  RouteSignalsResponse,
  RouteSignalParams,
  RoutingSequenceParams,
  ProductionSeedTemplate,
  ProductionSeedApplyResult,
  ProductStatus,
  AfterSalesTicket,
  AfterSalesListParams,
  AfterSalesFormData,
  AfterSalesStatusUpdateParams,
  DashboardStats,
  OrderTrendPoint,
  OrderStatusDistribution,
  ActiveSession,
  PendingTask,
  ProductRanking,
  TodayBriefingResponse,
  BriefingConfig,
  BriefingContent,
  Customer,
  CustomerListParams,
  CustomerDetail,
  CustomerDetailResponse,
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
  RegistrationResult,
  Notification,
  NotificationQueryParams,
  CreateNotificationRequest,
  UnreadCountResponse,
  FinanceTransaction,
  FinanceTransactionListParams,
  FinanceTransactionFormData,
  FinanceSummary,
  ReceivableReconciliationItem,
} from '@/types'
import { FrontendToBackendStatus } from '@/types'

// 认证 API
export const authApi = {
  login: (data: LoginParams) => 
    request.post<ApiResponse<LoginResponse>>('/api/auth/admin/login', data),
      
  // 审计 07 P1-5：refresh token 由后端 HttpOnly cookie 承载，body 不再传参
  refreshToken: () =>
    request.post<ApiResponse<RefreshTokenResponse>>('/api/auth/refresh', {}),
  
  logout: () => 
    request.post('/api/auth/logout'),
  
  getUserInfo: () => 
    request.get<ApiResponse<UserInfoResponse>>('/api/auth/me'),

  sendSmsCode: (phone: string) =>
    request.post<ApiResponse>('/api/auth/sms/send', { phone }),

  smsLogin: (phone: string, code: string) =>
    request.post<ApiResponse<LoginResponse>>('/api/auth/sms/login', { phone, code }),

  submitRegistration: (data: RegistrationData) =>
    request.post<ApiResponse<RegistrationResult>>('/api/auth/register', data),
}

// 商品 API
export const productApi = {
  getProducts: (params?: ProductListParams) => 
    request.get<ApiResponse<PageResponse<Product>>>('/api/admin/products', { params }),
  
  getProduct: (id: string) => 
    request.get<ApiResponse<Product>>(`/api/admin/products/${id}`),
  
  createProduct: (data: ProductFormData) =>
    request.post<ApiResponse<Product>>('/api/admin/products', buildProductPayload(data)),
  
  updateProduct: (id: string, data: ProductFormData) =>
    request.put<ApiResponse<Product>>(`/api/admin/products/${id}`, buildProductPayload(data)),
  
  deleteProduct: (id: string) => 
    request.delete<ApiResponse<void>>(`/api/admin/products/${id}`),
  
  updateProductStatus: (id: string, status: ProductStatus) => 
    request.put<ApiResponse<Product>>(`/api/admin/products/${id}/status`, { status }),

  // 设置/取消商品推荐标记（C 端「新品推荐」位控制）
  updateProductRecommended: (id: string, recommended: boolean) =>
    request.put<ApiResponse<void>>(`/api/admin/products/${id}/recommend`, { recommended }),

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
  
  /** 上移/下移分类（issue #2905）：direction = 'up' | 'down' */
  moveCategory: (id: string, direction: 'up' | 'down') => 
    request.post<ApiResponse<void>>(`/api/admin/categories/${id}/move`, { direction }),
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

// 算料试算 API（issue #4434 · 前置 #4421）
//
// **薄封装**：不补默认值、不重算、不拼公式串。
// 缺省值由 ai-agent 端点给（在 Java/TS 侧补默认值 = **第二份口径**）；
// `formula_text` 由**后端**按同一次算料的数字产出（前端自拼 = **第二份算料逻辑**）。
//
// 键名口径（设计文档 §4.5）：**算料输出键 = snake_case**，与 `CALC_INFO_KEYS` /
// `craft-display.ts` 逐字一致 ⇒ 商家接受试算结果后，这些值可**原样**落进 `processingInfo`。
export interface CraftCalcParams {
  /** 窗宽（米，> 0）—— **必填**；系统不猜窗宽（缺 width ⇒ 后端 400，前端不该发这种请求） */
  width: number
  /** 窗高（米）；不传由 ai-agent 按常见层高处理 */
  height?: number
  /** 打开方式开数（1 单开 / 2 双开 / 3 三开 / 4 四开） */
  open_count?: number
  /** 悬挂方式（仅 `s_hook` 韩褶走折数法） */
  mounting?: string
  /** 工艺档位（standard 2.0 / economy 1.8） */
  craft_tier?: string
  /** 款式（单色 / 拼色）；拼色需同时给拼次特殊选项才有拼色用料系数 */
  style?: string
  /** 部位级特殊选项（逐字名）；拼色用料系数由 `拼1次` / `拼2次` 决定 */
  special_options?: string[]
}

/** 试算结果 —— 算料输出子集（§4.5 snake_case） */
export interface CraftCalcResult {
  /** 面料米数（= 下单页「数量」的预填值） */
  fabric_meters: number
  /** 总褶数 */
  pleat_count: number
  /** 每片折数 */
  per_panel_pleats?: number
  /** 每折吃布（米）：单色 0.25 / 拼色·拼1次 0.65 / 拼色·拼2次 1.2 */
  per_fold: number
  /** **理论**褶倍（随档位） */
  fullness: number
  /** **实际**褶倍（= 用料 ÷ 窗宽） */
  fullness_actual?: number
  formula_used?: string
  /** 可读公式串（如 `(6.6+0.3)×2.0 → 52折 → 0.25×52+0.3 = 13.3米`）—— **后端产出，前端只渲染** */
  formula_text: string
  /** 取值来源：`公式计算` / `人工指定` / `客户自报`（真值源 §8：用料必须带来源） */
  source?: string
  craft_tier?: string
  warning?: string
}

export const craftCalcApi = {
  /** 算料试算（**不落库**）—— 供下单页预填「数量」并展示公式串 */
  preview: (params: CraftCalcParams) =>
    request.post<ApiResponse<CraftCalcResult>>('/api/admin/orders/craft-calc', params),
}

/**
 * 加工费计价**预览**（issue #4450 · 前置 #4406）。
 *
 * **为什么必须有它**：下单页此前本地自算（Σ 加工项），而服务端创建订单按**选配组合取价**
 * ⇒ 页面总额 ≠ 服务端总额 ⇒ 命中「实收金额与应收不一致」校验 ⇒ **带加工项的订单被拒单**。
 * 用本端点把服务端的同一份取价结果提前拿到，页面显示 === 落库。
 *
 * 入参/出参与创建订单**同形**（`items[].processingInfo` / `{processingFee, processingFeeDetail}`），
 * 且服务端**复用同一份取价实现** —— 前端不得自算。
 */
export interface FeePreviewRow {
  /** 该行加工费（元）；未定价 / 缺米数 = 0 */
  processingFee: number
  /** 可审计构成（snake_case，与订单详情行同键名，可直接复用同一套渲染） */
  processingFeeDetail?: Record<string, unknown>
}

export interface FeePreviewResult {
  items: FeePreviewRow[]
  processingFeeTotal: number
}

export const feePreviewApi = {
  /** 加工费试算（**不落库**）—— 入参就是「即将提交的那一份」明细 */
  preview: (payload: { items: Array<{ processingInfo?: unknown }> }) =>
    request.post<ApiResponse<FeePreviewResult>>('/api/admin/orders/fee-preview', payload),
}

// 加工分类 API
export const processingCategoryApi = {
  getProcessingCategories: () => 
    request.get<ApiResponse<ProcessingCategory[]>>('/api/admin/processing-categories'),
  
  createProcessingCategory: (data: ProcessingCategoryFormData) => 
    request.post<ApiResponse<ProcessingCategory>>('/api/admin/processing-categories', data),
}

// 知识卡片 API（LLM WIKI 板块，issue #3051 — 替代旧文档/同步历史接口）
export const knowledgeApi = {
  getCards: (params?: KnowledgeCardListParams) =>
    request.get<ApiResponse<PageResponse<KnowledgeCard>>>('/api/admin/knowledge/cards', { params }),

  searchCards: (params: { query?: string; productId?: string; category?: string }) =>
    request.get<ApiResponse<KnowledgeCard[]>>('/api/admin/knowledge/cards/search', { params }),

  createCard: (data: Partial<KnowledgeCard>) =>
    request.post<ApiResponse<KnowledgeCard>>('/api/admin/knowledge/cards', data),

  updateCard: (id: string, data: Partial<KnowledgeCard>) =>
    request.put<ApiResponse<KnowledgeCard>>(`/api/admin/knowledge/cards/${id}`, data),

  deleteCard: (id: string) =>
    request.delete<ApiResponse<void>>(`/api/admin/knowledge/cards/${id}`),

  publishCard: (id: string) =>
    request.post<ApiResponse<KnowledgeCard>>(`/api/admin/knowledge/cards/${id}/publish`),

  archiveCard: (id: string) =>
    request.post<ApiResponse<KnowledgeCard>>(`/api/admin/knowledge/cards/${id}/archive`),

  // ===== 待确认队列（issue #3051 P5）=====
  getCandidates: (params: { status?: string; page?: number; size?: number }) =>
    request.get<ApiResponse<PageResponse<KnowledgeCandidate>>>('/api/admin/knowledge/candidates', { params }),
  getPendingCount: () =>
    request.get<ApiResponse<{ pending: number }>>('/api/admin/knowledge/candidates/pending-count'),
  adoptCandidate: (id: string) =>
    request.post<ApiResponse<KnowledgeCard>>(`/api/admin/knowledge/candidates/${id}/adopt`),
  adoptEditedCandidate: (id: string, patch: Partial<KnowledgeCandidate>) =>
    request.post<ApiResponse<KnowledgeCard>>(`/api/admin/knowledge/candidates/${id}/adopt-edited`, patch),
  rejectCandidate: (id: string, note?: string) =>
    request.post<ApiResponse<void>>(`/api/admin/knowledge/candidates/${id}/reject`, { note }),

  // ===== 行业模板（issue #3051 P3）=====
  getTemplates: () =>
    request.get<ApiResponse<KnowledgeTemplateInfo[]>>('/api/admin/knowledge/templates'),
  applyTemplate: (templateId: string) =>
    request.post<ApiResponse<{ templateId: string; created: number; skipped: number }>>(`/api/admin/knowledge/templates/${templateId}/apply`),

  // ===== 提炼触发（issue #3051 P5b/P6）=====
  // distillConversations 已移除：人工客服会话结束自动提炼（#3090），前端不再手动触发
  distillDocument: (data: { title?: string; content: string }) =>
    request.post<ApiResponse<{ candidates: number; created: number; skipped: number }>>('/api/admin/knowledge/distill/documents', data),
}

// 售后工单 API
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
  // 后端接收 { logisticsCompany, trackingNo, shipperName? }；shipperName 留空则后端按当前
  // 登录用户兜底（发货单「经手人」，issue #3768）。
  updateLogistics: (id: string, data: LogisticsFormData) =>
    request.put<ApiResponse<void>>(`/api/admin/orders/${id}/logistics`, buildLogisticsPayload(data)),

  // 关闭订单 → 后端实际为取消订单接口（无 body）
  closeOrder: (id: string, data?: CloseOrderParams) =>
    request.put<ApiResponse<void>>(`/api/admin/orders/${id}/cancel`, buildCloseOrderPayload(data)),

  // 确认付款
  confirmPayment: (id: string) =>
    request.put<ApiResponse<void>>(`/api/admin/orders/${id}/payment`),

  // 退款
  // 后端 PUT /api/admin/orders/{id}/refund，body: { refund_reason, refund_amount }（refund_amount 缺省=全额）
  refundOrder: (id: string, data?: RefundOrderParams) =>
    request.put<ApiResponse<void>>(`/api/admin/orders/${id}/refund`, buildRefundPayload(data)),

  addRemark: (id: string, content: string) =>
    request.post<ApiResponse<void>>(`/api/admin/orders/${id}/remark`, { content }),

  // 删除订单
  deleteOrder: (id: string) =>
    request.delete<ApiResponse<void>>(`/api/admin/orders/${id}`),
}

// 加工单 API（issue #3340）
export const processingOrderApi = {
  // 批量生成加工单（仅已确认且含加工项订单；联动订单进入 producing）
  generate: (orderIds: string[]) =>
    request.post<ApiResponse<ProcessingOrderGenerateResult[]>>('/api/admin/processing-orders/generate', { orderIds }),

  // 加工单列表（keyword=加工单号/订单号，status 可选）
  list: (params?: { keyword?: string; status?: string }) =>
    request.get<ApiResponse<ProcessingOrder[]>>('/api/admin/processing-orders', { params }),

  // 加工单详情（id 可为加工单号/订单号/UUID）
  detail: (id: string) =>
    request.get<ApiResponse<ProcessingOrder>>(`/api/admin/processing-orders/${id}`),

  // 状态更新：issue(发加工)/start/complete/cancel
  update: (id: string, data: ProcessingOrderUpdateParams) =>
    request.patch<ApiResponse<ProcessingOrder>>(`/api/admin/processing-orders/${id}`, data),
}

// 生产报工 API（issue #4000，M4-H；后端 ProductionController，权限 order:list）
// + 工序库/工艺路线只读消费者、计件工资报表、补生成工序、打印计数（issue #4202~#4205）
export const productionApi = {
  // 加工单工序树 + 进度（含加工单二维码 token）
  getOrderOperations: (orderId: string) =>
    request.get<ApiResponse<ProductionOperations>>(`/api/admin/production/orders/${orderId}/operations`),

  // 加工单计件汇总（内部计件：合计 + 分人 + 分工序）
  getPiecework: (orderId: string) =>
    request.get<ApiResponse<PieceworkSummary>>(`/api/admin/production/orders/${orderId}/piecework`),

  // 工艺库 + 工艺路线（只读；工序库页数据源）
  getOperationsCatalog: () =>
    request.get<ApiResponse<OperationsCatalog>>('/api/admin/production/operations-catalog'),

  getRoutings: () =>
    request.get<ApiResponse<RoutingsResponse>>('/api/admin/production/routings'),

  // ── 行业生产模板目录 + 一键套用（issue #4361 冻结契约；前端半边 #4363）──
  // 存量非 1 号租户工序库/路线库为空（V54/V56/V58/V59 只种 tenant_id=1）⇒ 这是其补救路径。
  // 套用幂等：已存在的工序/路线自动跳过（响应给出 created_operations / created_routings / skipped）。
  getSeedTemplates: () =>
    request.get<ApiResponse<ProductionSeedTemplate[]>>('/api/admin/production/seed-templates'),

  applySeedTemplate: (templateId: string) =>
    request.post<ApiResponse<ProductionSeedApplyResult>>(
      `/api/admin/production/seed-templates/${templateId}/apply`,
    ),

  // 工序库写：改单价 / 必完开关等（权限 processing:manage）
  updateOperation: (id: string | number, data: ProductionOperationUpdateParams) =>
    request.put<ApiResponse<CatalogOperation>>(`/api/admin/production/operations/${id}`, data),

  // ── 工艺路线商家可配（issue #4307 前端半边；契约所有者 = 后端 4308，权限 processing:manage）──
  // 路线序列写：body {operations: ["精裁-布", ...]}
  // （服务端护栏：空序列 / 工序不存在 / 重复 / 缺必完工序 —— 失败响应体带逐条理由，页面照单展示）
  updateRoutingSequence: (id: number, data: RoutingSequenceParams) =>
    request.put<ApiResponse<Routing>>(`/api/admin/production/routings/${id}`, data),

  // 新建路线（部位 + 工艺；初版序列随后在编辑区排）
  createRouting: (data: RoutingCreateParams) =>
    request.post<ApiResponse<Routing>>('/api/admin/production/routings', data),

  // 新增工序（建新路线时必须有工序可选）
  createOperation: (data: RouteOperationCreateParams) =>
    request.post<ApiResponse<CatalogOperation>>('/api/admin/production/operations', data),

  // 信号映射（库数据：派生读库而非读硬编码常量表）
  getRouteSignals: () =>
    request.get<ApiResponse<RouteSignalsResponse>>('/api/admin/production/route-signals'),
  createRouteSignal: (data: RouteSignalParams) =>
    request.post<ApiResponse<RouteSignal>>('/api/admin/production/route-signals', data),
  updateRouteSignal: (id: number, data: RouteSignalParams) =>
    request.put<ApiResponse<RouteSignal>>(`/api/admin/production/route-signals/${id}`, data),
  deleteRouteSignal: (id: number) =>
    request.delete<ApiResponse<void>>(`/api/admin/production/route-signals/${id}`),

  // 缺口：①有活跃工序但未进任何活跃路线 ②库中无路线的信号组合
  getRoutingGaps: () =>
    request.get<ApiResponse<RoutingGaps>>('/api/admin/production/routing-gaps'),

  // ── 加工费组合定价（issue #4386 前端半边；契约所有者 = 后端 4386，权限 processing:manage）──
  // 口径（用户裁定 2026-09-19）：「不是每个加工项收取一个费用，而且通常是组合」
  // 「选配完的一个商品只会收取一种加工费」⇒ 一行 = 一组选配特征 → 一个单价（元/米）。
  // ⚠️ `composition_key` 的归一化（与书写顺序无关）**在服务端**：前端只提交勾选的加工项名集合，
  //    自己拼 key 会变成第二份口径（两边漂移 ⇒ 页面显示的组合与库里不是同一个）。
  getFeeCombinations: () =>
    request.get<ApiResponse<FeeCombinationsResponse>>('/api/admin/production/processing-fee-combinations'),
  createFeeCombination: (data: FeeCombinationCreateParams) =>
    request.post<ApiResponse<FeeCombination>>('/api/admin/production/processing-fee-combinations', data),
  updateFeeCombination: (id: string, data: FeeCombinationUpdateParams) =>
    request.put<ApiResponse<FeeCombination>>(
      `/api/admin/production/processing-fee-combinations/${id}`,
      data,
    ),
  // 停用（软删语义：status=disabled，行保留可回溯）
  disableFeeCombination: (id: string) =>
    request.delete<ApiResponse<FeeCombination>>(
      `/api/admin/production/processing-fee-combinations/${id}`,
    ),
  // 缺口：订单里出现过、但库里查不到价的选配组合
  getFeeGaps: () => request.get<ApiResponse<FeeGaps>>('/api/admin/production/processing-fee-gaps'),

  // 计件工资报表（按期间 YYYY-MM 聚合，可按工人筛选）
  getPieceworkSummary: (params: { period: string; worker_name?: string }) =>
    request.get<ApiResponse<PieceworkReport>>('/api/admin/production/piecework/summary', { params }),

  // 补生成工序（存量加工单：positions 可选，空 body ⇒ 服务端按订单派生）
  instantiate: (orderId: string) =>
    request.post<ApiResponse<{ qr_token?: string; operation_count?: number }>>(
      `/api/admin/production/orders/${orderId}/instantiate`,
      {},
    ),

  // 撤销加工单二维码 token（issue #4240；真值源 §1「token 化、可撤销」）——
  // 撤销后 qr_token 置空 ⇒ 已打印的旧码立即失效；再次 instantiate 时重新生成新码。
  // 注意：该端点是**方法级** processing:manage（仅 operator/admin），与同类只读端点的类级 order:list 不同。
  revokeQrToken: (orderId: string) =>
    request.post<ApiResponse<{ order_id?: string; qr_token?: string | null; revoked?: boolean }>>(
      `/api/admin/production/orders/${orderId}/qr-token/revoke`,
    ),

  // 打印次数上报（fire-and-forget，失败不得阻断打印）
  recordPrint: (orderId: string) =>
    request.post<ApiResponse<{ order_id?: string; processing_order_no?: string; print_count?: number }>>(
      `/api/admin/production/orders/${orderId}/print`,
    ),
}

// Dashboard API
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

  getPendingTasks: () =>
    request.get<ApiResponse<PendingTask[]>>('/api/admin/dashboard/pending-tasks'),

  getProductRanking: (period: string = 'day', limit: number = 10) =>
    request.get<ApiResponse<ProductRanking[]>>('/api/admin/dashboard/product-ranking', { params: { period, limit } }),
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
      credentials: 'include',
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
      credentials: 'include',
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
      credentials: 'include',
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
      credentials: 'include',
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
    if (!res.ok) throw new Error(`结束会话失败: ${res.status}`)
    return res.json()
  },

  /** 重新打开已关闭的会话 */
  reopenSession: async (sessionId: string, token: string) => {
    const res = await fetch(`${AI_SERVICE_URL}/api/chat/sessions/${sessionId}/reopen`, {
      credentials: 'include',
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    })
    if (!res.ok) throw new Error(`重新打开会话失败: ${res.status}`)
    return res.json()
  },

  /** 删除会话（物理删除会话及其所有消息） */
  deleteSession: async (sessionId: string, token: string) => {
    const res = await fetch(`${AI_SERVICE_URL}/api/chat/sessions/${sessionId}`, {
      credentials: 'include',
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
      credentials: 'include',
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
      credentials: 'include',
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
      },
      body: formData,
    })
    if (!res.ok) throw new Error(`图片上传失败: ${res.status}`)
    return res.json() as Promise<{ success: boolean; data: { files: { id: string; url: string; name: string; size: number }[] } }>
  },

  /** 语音转文字 */
  transcribeAudio: async (audioBlob: Blob, token: string, language?: string) => {
    const formData = new FormData()
    formData.append('audio', audioBlob, 'recording.webm')
    const params = language ? `?language=${encodeURIComponent(language)}` : ''
    const res = await fetch(`${AI_SERVICE_URL}/api/chat/transcribe${params}`, {
      credentials: 'include',
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
      },
      body: formData,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `语音识别失败: ${res.status}`)
    }
    return res.json() as Promise<{ text: string; language: string; duration_ms: number }>
  },

  /** AI 服务基地址 */
  AI_SERVICE_URL,
}

// 客户管理 API
export const customerApi = {
  getCustomers: (params?: CustomerListParams) =>
    request.get<ApiResponse<PageResponse<Customer>>>('/api/admin/customers', { params }),

  getCustomer: (id: string) =>
    request.get<ApiResponse<CustomerDetailResponse>>(`/api/admin/customers/${id}`),

  // 更新客户档案。前端用 remark 表示备注，后端字段为 agentNotes，这里做字段映射。
  updateCustomer: (id: string, data: Partial<Customer>) => {
    const payload: Record<string, unknown> = { ...data }
    if (payload.remark !== undefined) {
      payload.agentNotes = payload.remark
      delete payload.remark
    }
    return request.put<ApiResponse<Customer>>(`/api/admin/customers/${id}`, payload)
  },

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

// 智能每日经营简报 API（issue #3468）
export const briefingApi = {
  /** 今日简报（未生成返回 generated=false，前端展示引导空态） */
  getToday: () =>
    request.get<ApiResponse<TodayBriefingResponse>>('/api/admin/briefing/today'),

  /** 简报配置（企业开关 + 生成时刻；菜单显隐 = 开关 ∧ 角色权限） */
  getConfig: () =>
    request.get<ApiResponse<BriefingConfig>>('/api/admin/briefing/config'),

  /** 更新简报配置（仅 admin；开启瞬间立即生成当日简报，关闭即熔断） */
  updateConfig: (data: Partial<BriefingConfig>) =>
    request.put<ApiResponse<BriefingConfig>>('/api/admin/briefing/config', data),

  /** 手动触发当日生成（仅 admin） */
  generate: () =>
    request.post<ApiResponse<{ generated: boolean; verifyStatus?: string; reason?: string; content?: BriefingContent }>>('/api/admin/briefing/generate'),
}

// 员工管理 API
export const employeeApi = {
  /** #2969 岗位=角色体系：岗位列表来自 roleApi.getAllRoles（含岗位默认权限） */
  loadPositions: () =>
    request.get<ApiResponse<Role[]>>('/api/admin/roles/all'),

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

  getRole: (id: string) =>
    request.get<ApiResponse<Role>>(`/api/admin/roles/${id}`),

  createRole: (data: RoleFormData) =>
    request.post<ApiResponse<Role>>('/api/admin/roles', data),

  updateRole: (id: string, data: RoleFormData) =>
    request.put<ApiResponse<Role>>(`/api/admin/roles/${id}`, data),

  deleteRole: (id: string) =>
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
  /** 转人工时点 AI 会话上下文摘要（管理端可见；GB/T 47746-2026） */
  aiContextSummary?: string | null
  /** 转人工前顾客与 AI 客服（小布）的对话快照（管理端可见） */
  aiContext?: AgentAiTurn[] | null
}

/** 转人工前 AI 对话快照消息 */
export interface AgentAiTurn {
  role: 'user' | 'assistant'
  content: string
  contentType?: string
  createdAt?: string
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

/** 会话列表查询参数 */
export interface AgentSessionListParams {
  page?: number
  size?: number
  status?: string
  employeeId?: string
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
  /** 客服发送消息 */
  sendMessage: (id: string, content: string, isInternal?: boolean) =>
    request.post<ApiResponse<AgentMessageItem>>(`/api/admin/agent-sessions/${id}/messages`, {
      content,
      isInternal,
    }),
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

// 财务对账 API
export const financeApi = {
  // 收支汇总
  getSummary: (params?: { startDate?: string; endDate?: string }) =>
    request.get<ApiResponse<FinanceSummary>>('/api/admin/finance/summary', { params }),

  // 资金流水（分页）
  getTransactions: (params?: FinanceTransactionListParams) =>
    request.get<ApiResponse<PageResponse<FinanceTransaction>>>('/api/admin/finance/transactions', { params }),

  // 手动登记收支
  createTransaction: (data: FinanceTransactionFormData) =>
    request.post<ApiResponse<FinanceTransaction>>('/api/admin/finance/transactions', data),

  // 应收对账（订单维度）
  getReconciliation: (params?: { page?: number; size?: number; startDate?: string; endDate?: string; keyword?: string }) =>
    request.get<ApiResponse<PageResponse<ReceivableReconciliationItem>>>('/api/admin/finance/reconciliation', { params }),
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
  craftCalc: craftCalcApi,
  feePreview: feePreviewApi,
  processingOrder: processingOrderApi,
  production: productionApi,
  dashboard: dashboardApi,
  upload: uploadApi,
  file: fileApi,
  chat: chatApi,
  customer: customerApi,
  settings: settingsApi,
  briefing: briefingApi,
  employee: employeeApi,
  role: roleApi,
  permission: permissionApi,
  registration: registrationApi,
  notification: notificationApi,
  agentSession: agentSessionApi,
  finance: financeApi,
}

export default api
