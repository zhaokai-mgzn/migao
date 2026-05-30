// 通用 API 响应类型（后端统一格式）
export interface ApiResponse<T = unknown> {
  code: number
  message?: string
  data: T
  success?: boolean
}

// 分页响应类型
export interface PageResponse<T> {
  items: T[]
  total: number
  page: number
  size: number
}

// 分页请求参数
export interface PageParams {
  page?: number
  size?: number
}

// 用户类型
export interface User {
  id: string
  username: string
  name: string
  nickname?: string
  email?: string
  phone?: string
  avatar?: string
  roles?: string[]
  permissions?: string[]
  tenantId?: number
  tenantName?: string
}

// 菜单项类型
export interface MenuItem {
  key: string
  name: string
  icon: string
  path: string
  children?: MenuItem[]
}

// 登录参数
export interface LoginParams {
  username: string
  password: string
  tenantId?: number
}

// 登录响应
export interface LoginResponse {
  accessToken: string
  refreshToken: string
  expiresIn: number
  tokenType: string
}

// Token 刷新响应
export interface RefreshTokenResponse {
  accessToken: string
  refreshToken?: string
  expiresIn: number
  tokenType: string
}

// 用户信息响应（GET /api/auth/me 直接返回 User）
export type UserInfoResponse = User

// 商品状态
export type ProductStatus = 'on_sale' | 'off_sale' | 'draft' | 'in_warehouse' | 'under_review'

// 计价方式
export type PricingType = 'per_meter' | 'per_piece' | 'fixed' | 'per_area'

export const PricingTypeLabels: Record<PricingType, string> = {
  per_meter: '按米',
  per_piece: '按片',
  fixed: '固定价',
  per_area: '按面积',
}

export const ProductStatusLabels: Record<ProductStatus, string> = {
  on_sale: '上架',
  off_sale: '下架',
  draft: '草稿',
  in_warehouse: '在仓',
  under_review: '审核中',
}

// 商品类型
export interface Product {
  id: string
  name: string
  sku?: string
  brand?: string
  categoryId: string
  categoryName?: string
  description?: string
  pricingType?: PricingType
  price: number
  costPrice?: number
  unit: string
  stock?: number
  status: ProductStatus
  images: string[]
  detailImages?: string[]
  specifications?: Record<string, string>
  processingItems?: string[]
  createdAt?: string
  updatedAt?: string
}

// 商品列表查询参数
export interface ProductListParams extends PageParams {
  keyword?: string
  categoryId?: string
  status?: ProductStatus
}

// 商品表单数据
// 库存扣减模式
export type StockDeductionMode = 'on_place' | 'on_pay'

// 商品加工项配置
export interface ProductProcessingItemConfig {
  processingItemId: number
  processingItemName?: string
  customPrice: number
}

export interface ProductFormData {
  name: string
  sku?: string
  skuCode?: string
  brand?: string
  categoryId: string
  description?: string
  pricingType?: PricingType
  price: number
  costPrice?: number
  unit: string
  stockDeductionMode?: StockDeductionMode
  supportsProcessing?: boolean
  status: ProductStatus
  images: string[]
  detailImages?: string[]
  specifications?: Record<string, string>
  processingItems?: string[]
  colors?: ProductColor[]
  sellingMethods?: SellingMethod[]
  doorWidths?: string[]
  skus?: ProductSku[]
  processingItemConfigs?: ProductProcessingItemConfig[]
}

// 分类类型
export interface Category {
  id: string
  name: string
  parentId?: string
  sort?: number
  children?: Category[]
}

// 分类表单数据
export interface CategoryFormData {
  name: string
  parentId?: string
  sort?: number
}

// 加工项状态
export type ProcessingItemStatus = 'active' | 'inactive'

// 加工项类型
export interface ProcessingItem {
  id: string
  name: string
  categoryId: string
  categoryName?: string
  unit: string
  basePrice: number
  status: ProcessingItemStatus
  pricingRules?: Record<string, unknown>
  description?: string
  createdAt?: string
  updatedAt?: string
}

// 加工项列表查询参数
export interface ProcessingItemListParams extends PageParams {
  keyword?: string
  categoryId?: string
}

// 加工项表单数据
export interface ProcessingItemFormData {
  name: string
  categoryId: string
  unit: string
  basePrice: number
  status: ProcessingItemStatus
  pricingRules?: Record<string, unknown>
  description?: string
}

// 加工分类类型
export interface ProcessingCategory {
  id: string
  name: string
  description?: string
  sort?: number
}

// 加工分类表单数据
export interface ProcessingCategoryFormData {
  name: string
  description?: string
  sort?: number
}

// 加工价格计算参数
export interface ProcessingCalculateParams {
  processingItemId: string
  params: {
    width?: number
    height?: number
    [key: string]: unknown
  }
}

// 加工价格计算结果
export interface ProcessingCalculateResult {
  price: number
  details?: Record<string, unknown>
}

// 知识库文档类型
export type KnowledgeDocType = 'faq' | 'product' | 'guide'

// 知识库文档状态
export type KnowledgeDocStatus = 'processed' | 'processing' | 'failed'

// 知识库文档类型
export interface KnowledgeDocument {
  id: string
  name: string
  type: KnowledgeDocType
  chunkCount: number
  status: KnowledgeDocStatus
  description?: string
  fileUrl?: string
  fileSize?: number
  uploadedAt: string
}

// 知识库文档列表查询参数
export interface KnowledgeDocumentListParams extends PageParams {
  keyword?: string
  type?: KnowledgeDocType
  status?: KnowledgeDocStatus
}

// 知识库文档上传表单
export interface KnowledgeDocumentUploadForm {
  name: string
  type: KnowledgeDocType
  description?: string
  file?: File
}

// 订单状态
export type OrderStatus = 'pending' | 'confirmed' | 'producing' | 'shipped' | 'completed' | 'cancelled'

// 订单状态标签映射
export const OrderStatusLabels: Record<OrderStatus, string> = {
  pending: '待确认',
  confirmed: '已确认',
  producing: '生产中',
  shipped: '已发货',
  completed: '已完成',
  cancelled: '已取消',
}

// 订单状态颜色映射
export const OrderStatusColors: Record<OrderStatus, string> = {
  pending: 'warning',
  confirmed: 'info',
  producing: 'purple',
  shipped: 'indigo',
  completed: 'success',
  cancelled: 'error',
}

// 订单状态流转顺序
export const OrderStatusFlow: OrderStatus[] = ['pending', 'confirmed', 'producing', 'shipped', 'completed']

// 下一步状态映射
export const NextStatusMap: Partial<Record<OrderStatus, OrderStatus>> = {
  pending: 'confirmed',
  confirmed: 'producing',
  producing: 'shipped',
  shipped: 'completed',
}

// 下一步操作标签映射
export const NextStatusActionLabels: Partial<Record<OrderStatus, string>> = {
  pending: '确认订单',
  confirmed: '开始生产',
  producing: '确认发货',
  shipped: '确认完成',
}

// 订单跟进状态
export type OrderFollowStatus = 'pending' | 'following' | 'completed'

export const OrderFollowStatusLabels: Record<OrderFollowStatus, string> = {
  pending: '待跟进',
  following: '跟进中',
  completed: '已完成',
}

// 订单明细类型
export interface OrderItem {
  id: string
  productId?: string
  productName: string
  sku?: string
  specifications?: string
  quantity: number
  unitPrice: number
  width?: number
  height?: number
  processingInfo?: Record<string, unknown>
  processingFee?: number
  subtotal: number
  createdAt?: string
}

// 物流轨迹
export interface LogisticsTrack {
  time: string
  description: string
  status?: string
}

// 物流信息
export interface LogisticsInfo {
  company?: string
  trackingNo?: string
  status?: string
  tracks?: LogisticsTrack[]
}

// 状态变更历史
export interface StatusHistory {
  status: OrderStatus
  time: string
  operator?: string
  remark?: string
}

// 订单类型
export interface Order {
  id: string
  orderNo: string
  customerName: string
  customerPhone: string
  customerAddress?: string
  totalAmount: number
  status: OrderStatus
  remark?: string
  items?: OrderItem[]
  logistics?: LogisticsInfo
  statusHistory?: StatusHistory[]
  createdAt?: string
  updatedAt?: string
}

// 订单列表查询参数
export interface OrderListParams extends PageParams {
  keyword?: string
  status?: OrderStatus
  startDate?: string
  endDate?: string
}

// 订单表单数据
export interface OrderFormData {
  customerName: string
  customerPhone: string
  customerAddress?: string
  remark?: string
  items: OrderItemFormData[]
}

// 订单明细表单数据
export interface OrderItemFormData {
  productId?: string
  productName: string
  quantity: number
  unitPrice: number
  width?: number
  height?: number
  processingInfo?: Record<string, unknown>
  subtotal: number
}

// 订单状态更新参数
export interface OrderStatusUpdateParams {
  status: OrderStatus
  logistics?: {
    company: string
    trackingNo: string
  }
}

// 物流信息表单
export interface LogisticsFormData {
  company: string
  trackingNo: string
}

// ========== 知识库搜索类型 ==========

// 知识库搜索结果
export interface KnowledgeSearchResult {
  chunkId: string
  content: string
  score: number
  source: {
    documentId: string
    title: string
    docType: string
  }
}

// 知识库搜索参数
export interface KnowledgeSearchParams {
  query: string
  topK?: number
}

// ========== 客户管理类型 ==========

// 客户来源渠道
export type CustomerChannel = 'wechat_mini' | 'wechat_mp' | 'web'

// 客户来源渠道标签映射
export const CustomerChannelLabels: Record<CustomerChannel, string> = {
  wechat_mini: '微信小程序',
  wechat_mp: '公众号',
  web: 'Web',
}

// 客户标签
export interface CustomerTag {
  id: string
  name: string
  color: string
  customerCount?: number
  createdAt?: string
}

// 客户标签表单
export interface CustomerTagFormData {
  name: string
  color: string
}

// 客户类型
export interface Customer {
  id: string
  name: string
  nickname?: string
  phone?: string
  avatar?: string
  channel: CustomerChannel
  vipLevel: number
  tags: CustomerTag[]
  remark?: string
  lastActiveAt?: string
  createdAt?: string
}

// 客户列表查询参数
export interface CustomerListParams extends PageParams {
  keyword?: string
  channel?: CustomerChannel | ''
  vipLevel?: number | ''
  tagId?: string
}

// 客户详情（含订单和会话）
export interface CustomerDetail extends Customer {
  orders?: CustomerOrder[]
  sessions?: CustomerSession[]
}

// 客户订单摘要
export interface CustomerOrder {
  id: string
  orderNo: string
  totalAmount: number
  status: string
  createdAt: string
}

// 客户会话摘要
export interface CustomerSession {
  id: string
  lastMessage: string
  channel: string
  isAI: boolean
  createdAt: string
}

// ========== 系统设置类型 ==========

// AI 模型选项
export type AiModel = 'qwen-turbo' | 'qwen-plus' | 'qwen-max'

// AI 配置
export interface AiConfig {
  model: AiModel
  systemPrompt: string
  temperature: number
  topP: number
  autoReply: boolean
  handoffThreshold: number
  greetingTemplate?: string
  autoHandoffKeywords?: string[]
}

// 系统设置
export interface SystemSettings {
  companyName: string
  logo?: string
  notificationEnabled: boolean
  notificationEmail?: string
}

// 修改密码参数
export interface ChangePasswordParams {
  oldPassword: string
  newPassword: string
  confirmPassword: string
}

// 登录日志
export interface LoginLog {
  id: string
  ip: string
  device: string
  location?: string
  createdAt: string
}

// ========== Dashboard 类型 ==========

// Dashboard 统计数据
export interface DashboardStats {
  todayOrders: number
  todayOrdersChange: number // 环比变化百分比
  totalCustomers: number
  newCustomersToday: number
  activeSessions: number
  aiSessionRate: number // AI 处理占比
  monthRevenue: number
  monthRevenueChange: number // 环比变化百分比
}

// 订单趋势数据点
export interface OrderTrendPoint {
  date: string
  orders: number
  sessions?: number
}

// 订单状态分布
export interface OrderStatusDistribution {
  status: OrderStatus
  label: string
  count: number
  color: string
}

// 活跃会话
export interface ActiveSession {
  id: string
  customerName: string
  channel: string
  lastMessage: string
  duration: string
  isAI: boolean
  startedAt: string
}

// ========== 售后工单类型 ==========

// 售后类型
export type AfterSalesType = 'return' | 'exchange' | 'repair' | 'refund' | 'complaint' | 'other'

export const AfterSalesTypeLabels: Record<AfterSalesType, string> = {
  return: '退货',
  exchange: '换货',
  repair: '维修',
  refund: '退款',
  complaint: '投诉',
  other: '其他',
}

// 售后工单状态
export type AfterSalesStatus = 'pending' | 'processing' | 'resolved' | 'rejected' | 'closed'

export const AfterSalesStatusLabels: Record<AfterSalesStatus, string> = {
  pending: '待处理',
  processing: '处理中',
  resolved: '已完成',
  rejected: '已拒绝',
  closed: '已关闭',
}

export const AfterSalesStatusColors: Record<AfterSalesStatus, string> = {
  pending: 'warning',
  processing: 'info',
  resolved: 'success',
  rejected: 'error',
  closed: 'default',
}

// 售后优先级
export type AfterSalesPriority = 'normal' | 'urgent' | 'critical'

export const AfterSalesPriorityLabels: Record<AfterSalesPriority, string> = {
  normal: '普通',
  urgent: '紧急',
  critical: '严重',
}

// 售后工单
export interface AfterSalesTicket {
  id: string
  ticketNo: string
  orderId: string
  orderNo?: string
  customerId: string
  customerName?: string
  customerPhone?: string
  ticketType: AfterSalesType
  status: AfterSalesStatus
  description: string
  images?: string[]
  source?: 'customer' | 'agent'
  priority?: AfterSalesPriority
  handlerId?: string
  handlerName?: string
  assignedAt?: string
  refundAmount?: number
  refundMethod?: 'original_route' | 'bank_transfer' | 'balance'
  evidenceImages?: string[]
  internalNotes?: string
  deadline?: string
  closedAt?: string
  closeReason?: string
  statusHistory?: AfterSalesStatusHistory[]
  createdAt?: string
  updatedAt?: string
}

// 售后状态变更历史
export interface AfterSalesStatusHistory {
  status: AfterSalesStatus
  time: string
  operator?: string
  remark?: string
}

// 售后工单列表查询参数
export interface AfterSalesListParams extends PageParams {
  keyword?: string
  status?: AfterSalesStatus | ''
  ticketType?: AfterSalesType | ''
}

// 创建售后工单表单
export interface AfterSalesFormData {
  orderId: string
  ticketType: AfterSalesType
  description: string
  images?: string[]
  priority?: AfterSalesPriority
  refundAmount?: number
}

// 售后状态更新参数
export interface AfterSalesStatusUpdateParams {
  status: AfterSalesStatus
  remark?: string
}

// ========== 聊天相关类型 ==========

// 聊天会话状态
export type ChatSessionStatus = 'active' | 'closed'

// 聊天会话
export interface ChatSession {
  session_id: string
  title: string
  status: ChatSessionStatus
  customer_name?: string
  last_message?: string
  message_count?: number
  created_at: string
  updated_at: string
}

// 工具调用信息
export interface ChatToolCall {
  name: string
  input?: Record<string, unknown>
  result?: unknown
  status: 'running' | 'completed' | 'error'
}

// 聊天消息角色
export type ChatMessageRole = 'user' | 'assistant' | 'system'

// 聊天消息
export interface ChatMessage {
  id: string
  session_id?: string
  role: ChatMessageRole
  content: string
  content_type?: 'text' | 'mixed'
  images?: string[]
  tool_calls?: ChatToolCall[]
  cards?: ChatCard[]
  created_at?: string
  isStreaming?: boolean
  suggestions?: string[]  // 后续问题建议列表
}

// SSE 事件类型
export type SSEEventType = 'message_start' | 'text_delta' | 'text' | 'tool_start' | 'tool_call' | 'tool_result' | 'card' | 'loading' | 'message_end' | 'error' | 'message' | 'done' | 'suggestions'

// 卡片类型
export type CardType = 'product_list' | 'product_detail' | 'logistics' | 'order' | 'knowledge'

// 卡片数据
export interface ChatCard {
  type: CardType
  data: Record<string, unknown>
}

// 商品卡片数据
export interface ProductCardData {
  id: string
  name: string
  price: number
  unit?: string
  images?: string[]
  specifications?: Record<string, string>
  description?: string
}

// 物流卡片数据
export interface LogisticsCardData {
  trackingNo: string
  company: string
  status: string
  tracks: Array<{
    time: string
    description: string
    status?: string
  }>
}

// 知识检索卡片数据
export interface KnowledgeCardData {
  title: string
  content: string
  source: string
  score?: number
}

// 快捷操作
export interface QuickAction {
  id: string
  name: string
  icon: string
  prompt: string
}

// 客户面板信息
export interface ChatCustomerInfo {
  name: string
  source?: string
  vipLevel?: string
  phone?: string
  totalOrders?: number
  totalSessions?: number
  registeredDays?: number
  recentOrders?: Array<{
    id: string
    orderNo: string
    status: string
    totalAmount: number
    createdAt: string
  }>
}

// ========== 员工管理类型 ==========

// 员工状态
export type EmployeeStatus = 'active' | 'disabled'

export const EmployeeStatusLabels: Record<EmployeeStatus, string> = {
  active: '启用',
  disabled: '禁用',
}

// 权限
export interface Permission {
  id: number
  name: string
  code: string
  resource: string
  action: string
  description?: string
}

// 角色
export interface Role {
  id: number
  name: string
  code: string
  description?: string
  permissions: Permission[]
  createdAt: string
}

// 角色表单数据
export interface RoleFormData {
  name: string
  code: string
  description?: string
  permissionIds: number[]
}

// 员工
export interface Employee {
  id: number
  username: string
  name: string
  phone?: string
  email?: string
  role: string
  roles: Role[]
  status: EmployeeStatus
  createdAt: string
  updatedAt: string
}

// 员工列表查询参数
export interface EmployeeListParams extends PageParams {
  keyword?: string
  status?: EmployeeStatus | ''
}

// 员工表单数据
export interface EmployeeFormData {
  username: string
  password?: string
  name: string
  phone?: string
  email?: string
  roleIds: number[]
}

// 重置密码参数
export interface ResetPasswordParams {
  newPassword: string
}

// ========== 企业入驻注册类型 ==========

// 入驻申请状态
export type RegistrationStatus = 'pending' | 'approved' | 'rejected'

export const RegistrationStatusLabels: Record<RegistrationStatus, string> = {
  pending: '待审核',
  approved: '已通过',
  rejected: '已驳回',
}

export const RegistrationStatusColors: Record<RegistrationStatus, 'warning' | 'success' | 'error'> = {
  pending: 'warning',
  approved: 'success',
  rejected: 'error',
}

// 入驻申请详情
export interface Registration {
  id: number
  companyName: string
  contactName: string
  phone: string
  businessLicenseUrl?: string
  industry?: string
  address?: string
  description?: string
  status: RegistrationStatus
  rejectReason?: string
  reviewedBy?: number
  reviewedAt?: string
  createdAt: string
  updatedAt: string
}

// 入驻申请列表查询参数
export interface RegistrationListParams extends PageParams {
  status?: RegistrationStatus | ''
}

// 企业入驻申请数据
export interface RegistrationData {
  companyName: string
  contactName: string
  phone: string
  smsCode: string
  businessLicenseUrl?: string
  industry?: string
  address?: string
  description?: string
}

// ========== 通知类型 ==========

// 通知状态
export type NotificationStatus = 'pending' | 'sent' | 'failed' | 'read'

// 通知渠道
export type NotificationChannel = 'internal' | 'sms' | 'wechat' | 'email'

// 接收人类型
export type NotificationRecipientType = 'user' | 'employee'

// 通知
export interface Notification {
  id: string
  tenantId: number
  ruleId?: string
  templateId?: string
  recipientId: string
  recipientType: NotificationRecipientType
  channel: NotificationChannel
  title: string
  content: string
  status: NotificationStatus
  sentAt?: string
  readAt?: string
  errorMessage?: string
  retryCount: number
  createdAt: string
}

// 通知查询参数
export interface NotificationQueryParams extends PageParams {
  status?: NotificationStatus | ''
  channel?: NotificationChannel | ''
  dateFrom?: string
  dateTo?: string
}

// 创建通知请求
export interface CreateNotificationRequest {
  recipientId: string
  recipientType: NotificationRecipientType
  title: string
  content: string
  channel?: NotificationChannel
  templateId?: string
  variables?: Record<string, string>
}

// 未读数响应
export interface UnreadCountResponse {
  count: number
}

// ========== 文件上传类型 ==========

// ========== SKU 与颜色类型 ==========

// 售卖方式
export type SellingMethod = 'bulk_cut' | 'full_roll'

export const SellingMethodLabels: Record<SellingMethod, string> = {
  bulk_cut: '散剪',
  full_roll: '整卷',
}

// SKU 状态
export type SkuStatus = 'active' | 'inactive' | 'disabled'

export const SkuStatusLabels: Record<SkuStatus, string> = {
  active: '启用',
  inactive: '停用',
  disabled: '已禁用',
}

// 商品颜色
export interface ProductColor {
  id: number
  colorName: string
  mainColorHex?: string
  colorImageUrl?: string
  remark?: string
  sortOrder?: number
}

// 商品 SKU
export interface ProductSku {
  id: number
  colorId: number
  colorName?: string
  sellingMethod: SellingMethod
  doorWidth: string
  price: number
  costPrice?: number
  stock: number
  salesCount?: number
  skuCode?: string
  status: SkuStatus
}

// 上传文件信息
export interface UploadedFile {
  id: string
  url: string
  name: string
  size: number
  type: string
  createdAt?: string
}
