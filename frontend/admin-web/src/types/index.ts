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
  tenantCode?: string
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
  on_sale: '出售中',
  off_sale: '已下架',
  draft: '草稿',
  in_warehouse: '仓库中',
  under_review: '审核中',
}

// 商品类型
export interface Product {
  id: string
  name: string
  sku?: string
  skuCode?: string
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
  // 在售颜色数量
  colorCount?: number
  // 累计销量
  salesCount?: number
  // 累计销售额
  salesAmount?: number
  // 最后编辑人
  editedBy?: string
  // 最后编辑时间
  editedAt?: string
  // 库存预警阈值
  stockWarningThreshold?: number
  // 库存扣减模式：兼容后端('on_order' | 'on_payment')与表单('on_place' | 'on_pay')两套枚举
  stockDeductionMode?: 'on_order' | 'on_payment' | 'on_place' | 'on_pay'
  // 计价单位（部分接口会单独返回）
  pricingUnit?: string
  // SKU 列表（详情接口返回）
  skus?: ProductSku[]
  createdAt?: string
  updatedAt?: string
}

// 商品列表查询参数
export interface ProductListParams extends PageParams {
  // 商品ID搜索
  productId?: string
  // 商品标题搜索
  name?: string
  // 关键词（保持兼容）
  keyword?: string
  // 商品货号搜索
  skuCode?: string
  // 分类过滤
  categoryId?: string
  // 状态过滤
  status?: ProductStatus | ''
  // 创建时间起始 (yyyy-MM-dd)
  createdFrom?: string
  // 创建时间截止 (yyyy-MM-dd)
  createdTo?: string
  // 排序字段
  sortBy?: 'stock' | 'salesCount' | 'salesAmount' | 'createdAt'
  // 排序方向
  sortOrder?: 'asc' | 'desc'
}

// 批量操作请求
export interface BatchOperationRequest {
  productIds: string[]
}

// 批量操作响应
export interface BatchOperationResponse {
  success: number
  failed: number
  errors?: string[]
}

// 商品表单数据
// 库存扣减模式
export type StockDeductionMode = 'on_place' | 'on_pay'

// 商品加工项配置
export interface ProductProcessingItemConfig {
  // 加工项 ID（与后端一致为字符串/UUID，例如 "proc_item_punch_nano"）
  processingItemId: string | null
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

// 加工项计价方式
export type PricingMethod = 'per_meter' | 'per_piece' | 'fixed' | 'per_area'

// 加工项类型
export interface ProcessingItem {
  id: string
  name: string
  categoryId: string
  categoryName?: string
  pricingMethod: PricingMethod
  unitPrice: number
  unit: string
  basePrice?: number // legacy alias for unitPrice
  status: ProcessingItemStatus
  pricingRules?: Record<string, unknown>
  options?: Record<string, unknown>[]
  description?: string
  minQuantity?: number
  maxQuantity?: number
  processingDays?: number
  aiRecommended?: boolean
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
  pricingMethod: PricingMethod
  unitPrice: number
  unit?: string
  status?: ProcessingItemStatus
  description?: string
  options?: Record<string, unknown>[]
  minQuantity?: number
  maxQuantity?: number
  processingDays?: number
  aiRecommended?: boolean
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

// ===== 订单状态枚举 =====
export type OrderStatus = 'pending_payment' | 'pending_shipment' | 'shipped' | 'completed' | 'closed' | 'refund'

// 后端实际订单状态（数据库存储值）
export type BackendOrderStatus =
  | 'pending'
  | 'confirmed'
  | 'processing'
  | 'shipped'
  | 'completed'
  | 'cancelled'

// 前端到后端状态映射（用于API请求时的status参数）
export const FrontendToBackendStatus: Record<OrderStatus, BackendOrderStatus> = {
  pending_payment: 'pending',
  pending_shipment: 'confirmed', // confirmed 和 processing 都算待发货
  shipped: 'shipped',
  completed: 'completed',
  closed: 'cancelled',
  refund: 'cancelled', // 退款目前映射到 cancelled（后端暂无独立 refund 状态）
}

// 后端到前端状态映射（用于API响应的数据展示）
export const BackendToFrontendStatus: Record<BackendOrderStatus, OrderStatus> = {
  pending: 'pending_payment',
  confirmed: 'pending_shipment',
  processing: 'pending_shipment', // processing 也归入待发货
  shipped: 'shipped',
  completed: 'completed',
  cancelled: 'closed',
}

// 将任意状态值（前端或后端）规范化为前端展示状态
export function normalizeOrderStatus(status: string | undefined | null): OrderStatus {
  if (!status) return 'pending_payment'
  if (status in BackendToFrontendStatus) {
    return BackendToFrontendStatus[status as BackendOrderStatus]
  }
  return status as OrderStatus
}

// 状态标签映射
export const OrderStatusLabels: Record<OrderStatus, string> = {
  pending_payment: '待付款',
  pending_shipment: '待发货',
  shipped: '已发货',
  completed: '已完成',
  closed: '已关闭',
  refund: '退款/售后',
}

// 状态颜色映射
export const OrderStatusColors: Record<OrderStatus, string> = {
  pending_payment: 'warning',
  pending_shipment: 'info',
  shipped: 'indigo',
  completed: 'success',
  closed: 'default',
  refund: 'error',
}

// 订单状态流转顺序（正常流程）
export const OrderStatusFlow: OrderStatus[] = ['pending_payment', 'pending_shipment', 'shipped', 'completed']

// 下一状态映射
export const NextStatusMap: Partial<Record<OrderStatus, OrderStatus>> = {
  pending_payment: 'pending_shipment',
  pending_shipment: 'shipped',
  shipped: 'completed',
}

// 下一步操作标签
export const NextStatusActionLabels: Partial<Record<OrderStatus, string>> = {
  pending_payment: '确认付款',
  pending_shipment: '确认发货',
  shipped: '确认收货',
}

// 订单状态Tab定义（含特殊筛选项）
export type OrderStatusTab = OrderStatus | 'all' | 'processing'

export const OrderStatusTabs: { key: OrderStatusTab; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'pending_payment', label: '待付款' },
  { key: 'pending_shipment', label: '待发货' },
  { key: 'shipped', label: '已发货' },
  { key: 'completed', label: '已完成' },
  { key: 'processing', label: '含加工订单' },
  { key: 'closed', label: '已关闭' },
  { key: 'refund', label: '退款/售后' },
]

// ===== 订单数据类型 =====

// 订单明细项（单个SKU行）
export interface OrderItem {
  id: string
  productId?: string
  productName: string         // 商品标题
  productCode?: string        // 商品货号
  color?: string              // 颜色
  specification?: string      // 规格尺寸（如"门幅2.8米"）
  quantity: number            // 数量（米）
  unitPrice: number           // 单价（元/米）
  amount: number              // 金额 = unitPrice * quantity
  sku?: string
  width?: number
  height?: number
  processingInfo?: Record<string, unknown>
  processingFee?: number
  subtotal: number
  createdAt?: string
}

// 加工项
export interface OrderProcessingItem {
  id?: string
  name: string                // 加工项名称（如"韩式打褶定型"、"打孔"）
  unitPrice: number           // 单价（元/米）
  quantity: number            // 数量（米）
  amount: number              // 金额 = unitPrice * quantity
}

// 订单备注
export interface OrderRemark {
  id: string
  content: string
  createdAt: string
  operator?: string
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
  shippingMethod?: 'logistics' | 'none'  // 物流发货 / 无需物流
  tracks?: LogisticsTrack[]
}

// 订单状态变更历史
export interface StatusHistory {
  status: OrderStatus
  time: string
  operator?: string
  remark?: string
}

// 订单主体
export interface Order {
  id: string
  orderNo: string
  customerName: string
  customerPhone: string
  customerAddress?: string
  totalAmount: number          // 累计金额
  actualAmount: number         // 实收款（累计金额 - 优惠）
  status: OrderStatus
  hasProcessing: boolean       // 是否含加工
  paymentDeadline?: string     // 支付截止时间（待付款状态用）
  paymentNo?: string           // 支付宝交易号
  paidAt?: string              // 支付时间
  shippedAt?: string           // 发货时间
  receivedAt?: string          // 确认收货时间
  items?: OrderItem[]          // 商品明细
  processingItems?: OrderProcessingItem[]  // 加工项列表
  logistics?: LogisticsInfo    // 物流信息
  statusHistory?: StatusHistory[]
  remarks?: OrderRemark[]      // 备注列表
  closeReason?: string         // 关闭原因
  remark?: string              // 兼容旧字段
  createdAt?: string
  updatedAt?: string
}

// ===== 表单与请求参数 =====

// 订单列表查询参数
export interface OrderListParams extends PageParams {
  orderId?: string             // 订单ID精准搜索
  receiver?: string            // 收货人姓名或手机号精准搜索
  startDate?: string           // 开始日期 (YYYY-MM-DD)
  endDate?: string             // 结束日期 (YYYY-MM-DD)
  productCode?: string         // 商品货号精准搜索
  productTitle?: string        // 商品标题模糊搜索
  hasProcessing?: boolean | '' // 是否加工筛选
  status?: OrderStatus | 'processing' | ''  // 状态筛选
  keyword?: string             // 关键词搜索（售后关联订单等场景）
}

// 订单表单数据（创建/编辑）
export interface OrderFormData {
  customerName: string
  customerPhone: string
  customerAddress?: string
  remark?: string
  items: OrderItemFormData[]
}

// 订单明细表单
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
    shippingMethod?: 'logistics' | 'none'
  }
}

// 物流信息表单
export interface LogisticsFormData {
  company: string
  trackingNo: string
  shippingMethod: 'logistics' | 'none'
}

// 关闭订单参数
export interface CloseOrderParams {
  reason: string               // 关闭原因
  remark?: string              // 其它原因备注
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
// 后端值：wechat_mini / wechat_mp / web / h5 / order（订单自动建档）
export type CustomerChannel = 'wechat_mini' | 'wechat_mp' | 'web' | 'h5' | 'order'

// 客户来源渠道标签映射
export const CustomerChannelLabels: Record<CustomerChannel, string> = {
  wechat_mini: '微信小程序',
  wechat_mp: '公众号',
  web: 'Web',
  h5: 'H5',
  order: '订单',
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
// 注意：后端 CustomerProfile 实体直接序列化返回，字段名使用 wechatNickname / sourceChannel / avatarUrl，
// 且 vipLevel 是字符串（normal/vip1/vip2/vip3）；这里同时声明前端期望字段与后端字段，以兼容渲染。
export interface Customer {
  id: string
  // —— 前端别名字段（可选，便于自定义/Mock 数据）——
  name?: string
  nickname?: string
  avatar?: string
  channel?: CustomerChannel
  // —— 后端 CustomerProfile 原始字段 ——
  wechatNickname?: string
  avatarUrl?: string
  sourceChannel?: CustomerChannel | string
  // —— 公共字段 ——
  phone?: string
  // 后端返回字符串（normal/vip1/vip2/vip3），前端 mock 用数字
  vipLevel?: number | string | null
  tags?: CustomerTag[] | null
  remark?: string
  lastActiveAt?: string
  createdAt?: string
}

// 客户列表查询参数
// 后端接收参数名为 sourceChannel；vipLevel 为字符串（normal/vip1/vip2/vip3）。
export interface CustomerListParams extends PageParams {
  keyword?: string
  channel?: CustomerChannel | ''
  sourceChannel?: CustomerChannel | string | ''
  vipLevel?: number | string | ''
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

// AI 配置
export interface AiConfig {
  botName: string
  greetingTemplate: string
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
