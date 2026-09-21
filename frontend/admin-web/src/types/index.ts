// 通用 API 响应类型（后端统一格式：{success, data, error, requestId, timestamp}）
export interface ApiResponse<T = unknown> {
  success: boolean
  data: T
  error?: {
    code: string
    message: string
    details?: { field: string; message: string }[]
  }
  requestId?: string
  timestamp?: number
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
  /** 岗位（员工档案，User 实体 position 字段；#3099 右上角用户卡片展示） */
  position?: string
  roles?: string[]
  permissions?: string[]
  menus?: MenuItem[]
  tenantId?: number
  tenantName?: string
  /** 企业 Logo（「企业基础信息」设置） */
  tenantLogo?: string
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
export type ProductStatus = 'on_sale' | 'off_sale' | 'draft' | 'under_review'

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
  // SKU 总库存（后端聚合 SKU 库存得出，详情页优先展示）
  totalStock?: number
  status: ProductStatus
  images: string[]
  detailImages?: string[]
  specifications?: Record<string, string>
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
  // 是否商家推荐（C 端「新品推荐」位展示依据）
  recommended?: boolean
  // 是否允许退货回补库存（issue #2991：窗帘行业定制退货不可再售，默认 false）
  allowReturnRestock?: boolean
  // 库存预警阈值
  stockWarningThreshold?: number
  // 库存扣减模式：兼容后端('on_order' | 'on_payment')与表单('on_place' | 'on_pay')两套枚举
  stockDeductionMode?: 'on_order' | 'on_payment' | 'on_place' | 'on_pay'
  // 计价单位（部分接口会单独返回）
  pricingUnit?: string
  // SKU 列表（详情接口返回）
  skus?: ProductSku[]
  // 商品颜色列表
  colors?: ProductColor[]
  // 售卖方式列表
  sellingMethods?: SellingMethod[]
  // 门幅列表
  doorWidths?: string[]
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
  // 库存低于此值的筛选（#1200 低库存跳转过滤）
  stockBelow?: number
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
  // 是否允许退货回补库存（issue #2991：窗帘行业定制退货不可再售，默认 false）
  allowReturnRestock?: boolean
  status: ProductStatus
  images: string[]
  detailImages?: string[]
  specifications?: Record<string, string>
  colors?: ProductColor[]
  sellingMethods?: SellingMethod[]
  doorWidths?: string[]
  skus?: ProductSku[]
}

// 分类类型
export interface Category {
  id: string
  name: string
  parentId?: string
  sort?: number
  children?: Category[]
}

// 分类表单数据（issue #2905：仅名称；顺序通过上移/下移调整，不再提交 sort/parentId）
export interface CategoryFormData {
  name: string
}

// 加工项状态
export type ProcessingItemStatus = 'active' | 'inactive'

// 加工项类型
//
// issue #4882（用户裁定）：加工项的**单价**（`unitPrice` 及 legacy 别名 `basePrice`）与
// **计价方式**（`pricingMethod` / 独立的 `PricingMethod` 联合类型）整体退场 —— 加工项只是
// 「有哪些加工服务」的目录，它的价由「加工费组合」（`processing_fee_combinations`，元/米）决定。
export interface ProcessingItem {
  id: string
  name: string
  categoryId: string
  categoryName?: string
  unit: string
  status: ProcessingItemStatus
  /**
   * 该加工项**显式声明**的工艺（V78 的 `processing_items.craft_hint`，后端 `ProcessingItemResponse.craftHint`）。
   *
   * issue #4566（用户 2026-09-19 裁定「工艺…直接通过加工项来勾选」）：下单页的工艺维**从这里派生**
   * —— 目录里只有 5 个工艺项带它（`打孔`/`韩折`→韩褶/`韩定+S钩`→韩褶/`穿杆`/`平幔`），其余为 `null`。
   */
  craftHint?: string | null
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

// 加工项表单数据（issue #4882：只提交名称 / 分类 / 单位；单价与计价方式已退场）
export interface ProcessingItemFormData {
  name: string
  categoryId: string
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

// ===== LLM WIKI 知识卡片（issue #3051，替代 RAG 文档模型）=====
// 知识卡片状态（三端一致：Java KnowledgeCard.status = TS KnowledgeCardStatus = Agent 检索过滤条件）
export type KnowledgeCardStatus = 'draft' | 'pending_review' | 'published' | 'archived'

// 知识卡片来源（template/conversation/document/manual）
// 商品派生（product，#3083）/加工项派生（config，#3085）能力已移除且存量数据已清理（#3087），从枚举移除
export type KnowledgeCardSource = 'template' | 'conversation' | 'document' | 'manual'

// 知识卡片分类（faq/product/measure/aftersale/config）
export type KnowledgeCardCategory = 'faq' | 'product' | 'measure' | 'aftersale' | 'config'

// 知识卡片
export interface KnowledgeCard {
  id: string
  tenantId?: number
  title: string
  category?: KnowledgeCardCategory | string
  industry?: string
  sourceType: KnowledgeCardSource
  sourceRef?: string
  question?: string
  answer: string
  keywords?: string
  applyProducts?: string | null
  variables?: string | null
  status: KnowledgeCardStatus
  version: number
  reviewNote?: string
  createdBy?: string
  reviewedBy?: string
  reviewedAt?: string
  createdAt: string
  updatedAt: string
}

// 知识提炼候选（AI 提炼 → 待确认队列，issue #3051 P5）
export interface KnowledgeCandidate {
  id: string
  tenantId?: number
  sourceType: 'conversation' | 'document' | 'product' | 'config'
  sourceRef?: string
  suggestedTitle: string
  suggestedAnswer: string
  suggestedCategory?: string
  suggestedKeywords?: string
  confidence?: number | string
  evidence?: string
  status: 'pending' | 'adopted' | 'edited' | 'rejected'
  statusNote?: string
  reviewedAt?: string
  createdAt: string
}

// 行业模板（平台预置资产，issue #3051 P3）
export interface KnowledgeTemplateInfo {
  templateId: string
  industry: string
  name: string
  version: number
  description?: string
  entryCount: number
}

// 知识卡片列表查询参数
export interface KnowledgeCardListParams extends PageParams {
  keyword?: string
  category?: string
  sourceType?: string
  status?: KnowledgeCardStatus | string
}

// ===== 订单状态枚举 =====
export type OrderStatus = 'pending_payment' | 'pending_shipment' | 'shipped' | 'completed' | 'closed' | 'refund'

// 后端实际订单状态（数据库存储值）
export type BackendOrderStatus =
  | 'pending'
  | 'confirmed'
  | 'producing'
  | 'shipped'
  | 'completed'
  | 'cancelled'

// 前端到后端状态映射（用于API请求时的status参数）
export const FrontendToBackendStatus: Record<OrderStatus, BackendOrderStatus> = {
  pending_payment: 'pending',
  pending_shipment: 'confirmed', // confirmed 和 producing 都算待发货
  shipped: 'shipped',
  completed: 'completed',
  closed: 'cancelled',
  refund: 'cancelled', // 退款目前映射到 cancelled（后端暂无独立 refund 状态）
}

// 后端到前端状态映射（用于API响应的数据展示）
export const BackendToFrontendStatus: Record<BackendOrderStatus, OrderStatus> = {
  pending: 'pending_payment',
  confirmed: 'pending_shipment',
  producing: 'pending_shipment', // producing 也归入待发货
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

// 订单状态展示辅助（issue #3889）：backend producing 与 confirmed 的展示区分。
// producing（生产中）不再归入 pending_shipment（待发货）展示，避免用户误以为可直接发货。
// 仅影响展示；OrderStatus 联合类型与 FrontendToBackendStatus（过滤/请求语义）保持不变。
export interface OrderStatusDisplay {
  label: string
  color: string
}

export function displayOrderStatus(status: string | undefined | null): OrderStatusDisplay {
  if (status === 'producing') return { label: '生产中', color: 'warning' }
  const normalized = normalizeOrderStatus(status)
  return { label: OrderStatusLabels[normalized], color: OrderStatusColors[normalized] }
}

// 订单状态流转顺序（正常流程）
export const OrderStatusFlow: OrderStatus[] = ['pending_payment', 'pending_shipment', 'shipped', 'completed']

// 订单分类（8 个横向切分 tab）— #390 规范
// 分类 ≠ 状态：分类是 UI 层的横向过滤维度，"含加工订单" 是 has_processing 维度
export const ORDER_CATEGORIES = [
  { key: 'all', label: '全部' },
  { key: 'pending_payment', label: '待付款' },
  { key: 'pending_shipment', label: '待发货' },
  { key: 'shipped', label: '已发货' },
  { key: 'completed', label: '已完成' },
  { key: 'closed', label: '已关闭' },
  { key: 'refund', label: '退款/售后' },
  { key: 'has_processing', label: '含加工订单' },
] as const

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

// 加工项（订单级聚合快照）
//
// issue #4882：`unitPrice` 与 `amount` 一并删除 —— 后端 `OrderDetailResponse.ProcessingItemBrief`
// 只剩 `id` / `name` / `quantity`（加工项目录已无单价；加工费的真值源是行级
// `OrderItem.processingFee` = 组合价 × 加工费米数）。⚠️ 不要与**商品行**的 `unitPrice` / `subtotal` 混为一谈。
export interface OrderProcessingItem {
  id?: string
  name: string                // 加工项名称（如"韩式打褶定型"、"打孔"）
  quantity: number            // 数量（米）
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

// 加工单（issue #3340）
// issue #4882：快照里的 `unitPrice` 同步退场（加工项不再有单价）—— 后端加工单
// `ProcessingOrderResponse.ProcessingItemSnapshot` 一并删除该字段。名称 / 数量 / 单位保留。
export interface ProcessingItemSnapshot {
  id?: string
  name: string
  quantity?: number
  unit?: string
  options?: unknown
}

export interface ProcessingOrderItem {
  productName?: string
  sku?: string
  colorName?: string
  sellingMethod?: string
  doorWidth?: string
  width?: number
  height?: number
  quantity?: number
  unit?: string
  processingItems?: ProcessingItemSnapshot[]
  /**
   * 工艺规格 + 算料输出（issue #4355 / 设计文档 §4.9 ③）。
   *
   * 快照由 Java `buildSnapshot` 从 `order_items.processing_info` **逐键透传**，
   * 键名口径与订单层一致（§4.5：工艺规格 camelCase、算料输出 snake_case）。
   * 未扩白名单的存量加工单**缺键** ⇒ 前端「缺值不渲染」（键缺席 = 未携带，不是错值）。
   */
  curtainType?: string
  craft?: string
  cuttingMode?: string
  openCount?: number
  isShaped?: boolean
  style?: string
  specialOptions?: string[]
  pleatSpacing?: number
  hasPattern?: boolean
  patternRepeat?: number
  fabric_meters?: number
  processing_meters?: number
  /** 加工费米数（camelCase 载体，§4.5；与 `processing_meters` 同值不同键） */
  processingMeters?: number
  pleat_count?: number
  per_panel_pleats?: number
  panels?: number
  fullness?: number
  fullness_actual?: number
  /**
   * 可读**算料公式串**（issue #4555）：车间/任务卡纸面据此告知「用料是怎么算出来的」。
   * 快照层是 snake_case 载体（订单层 `processing_info` 落的是 camelCase `formulaText`，
   * 展示映射 `lib/craft-display.ts` 两个别名同登记）。存量加工单无该键 ⇒ 该行不出现。
   */
  formula_text?: string
  remark?: string
}

export interface ProcessingOrder {
  id: string
  orderId: string
  orderNo?: string
  customerName?: string
  /** 客户手机号（列表/详情接口返回，订单详情块未用到） */
  customerPhone?: string
  processingOrderNo: string
  processor?: string
  expectedDeliveryDate?: string
  status: 'generated' | 'issued' | 'in_processing' | 'completed' | 'cancelled'
  items?: ProcessingOrderItem[]
  remark?: string
  templateVersion?: number
  generatedAt?: string
  issuedAt?: string
  inProcessingAt?: string
  completedAt?: string
  cancelledAt?: string
  cancelledReason?: string
  printCount?: number
  /** 本单工序来源的路线键（**实际使用**），形如 `布帘×韩褶`（issue #4308 新增列） */
  routeKey?: string
  /** 派生出的路线键（可能工序库里没有；两维全不命中时为 null）—— 只有 missing_route 提示要用它 */
  routeRequestedKey?: string
  /**
   * 路线来源（四态，见 #4308 冻结清单 + 末尾「冻结补遗」）：
   * derived 正常派生 / partial 只命中一维 / missing_route 两维命中但库里没这条路线 /
   * default 两维全不命中取默认（静默回落的可观测面）。
   */
  routeSource?: 'derived' | 'partial' | 'missing_route' | 'default' | string
}

export interface ProcessingOrderGenerateResult {
  orderRef: string
  success: boolean
  message?: string
  processingOrderNo?: string
}

export interface ProcessingOrderUpdateParams {
  action: 'issue' | 'start' | 'complete' | 'cancel'
  processor?: string
  expectedDeliveryDate?: string
  reason?: string
}

// ── 生产报工（issue #4000，M4-H；后端 ProductionController 返回 Map ⇒ 键为 snake_case）──

/** 工序实例（加工单 × 部位 × 工序；应做数量由算料引擎给出，报工只确认） */
export interface ProductionOperation {
  id: string
  seq?: number
  /**
   * ⚠️ **工人端快照名**（变体名，如 `精裁-布`）：其它消费者仍要读它 ⇒ 保留；
   * **web 界面不得直接渲染该键**（issue #4621）—— 界面用 `operationDisplayName()`
   * 渲染 `logical_name` + `position`。
   */
  operation: string
  /** 逻辑工序名（后端读时派生，如 `精裁`）；老数据 / 自建工序可能缺 ⇒ helper 退回 `operation` 原文 */
  logical_name?: string | null
  /** 部位（如 `布帘`）；部位无关工序 / 老数据为空 ⇒ 只显示逻辑名 */
  position?: string | null
  /** 工序分组：裁剪 / 车位 / 后道 / 其他 */
  group?: string | null
  /** 单位：米/套/件/个/折 */
  unit?: string | null
  /** 应做数量 */
  qty?: number
  /**
   * 实例快照单价（元/单位）；`null` = **未定价**（V90，issue #4696）——
   * 与「定价为 0 元」（`0`）**必须可区分**：界面不得把 null 折成 ¥0.00。
   */
  unit_price?: number | null
  /**
   * 单价三态（V90，issue #4696）：`priced` = 有价（含显式定价 0 元）；
   * `unpriced` = **未定价**（单价为 null）⇒ 界面显示「未定价」+ 定价入口。
   * 老实例（本键引入前）缺省 ⇒ 按 `unit_price == null` 兜底判定（安全方向）。
   */
  price_state?: PriceState | null
  // 计件系数（`factor`）**不再下发**（issue #4589）：计件工资 = 数量 × 计件单价，
  // 系数已从算法与读面退场 —— 保留字段只会让界面显示一个「有值却不算钱」的数。
  /** 必完工序：完成才可打包（完工门槛） */
  is_must_finish?: boolean
  /** 标记生产开始的首工序 */
  is_start_marker?: boolean
  /** pending 待做 / done 已完成 */
  status?: string | null
  done_qty?: number
  /**
   * 报工人（issue #4309）：该工序实例下报过工的人（`production_work_logs.worker_name`）。
   * 后端已去重、按首次报工时间升序、只取 `work_type='normal'`、空名折「未署名」；
   * 无报工 = 空数组 ⇒ 表格渲染「—」。**商家侧**生产明细专用，不得进顾客面卡片。
   */
  workers?: string[]
}

/** 按部位（布帘/纱帘/帘头…）分组的工序实例 */
export interface ProductionPosition {
  position_name?: string | null
  /**
   * 订单行主键（`order_items.id`）—— **商品行 = 部位**的定位键（issue #4388 起为分组键）。
   * 洗水码靠它与加工单快照明细对齐（`ProcessingOrderItem` 快照里的 `itemId`），
   * 逐张取该商品自己的工艺摘要；存量行如实 `null`（读面不编值）⇒ 消费方按缺键渲染，不猜。
   */
  order_item_id?: string | null
  /** 部位类型码（布帘/纱帘/帘头…）；老数据缺省 ⇒ 只显示 `position_name` */
  position_kind?: string | null
  /**
   * 樘窗（套）键（issue #4784）：与计件报表 `per_set` 的 `set_no` **同一份口径**
   * （后端 `ProductionService.setKey`：V92 落库套号优先、无号回落樘窗组键
   * `craftLineId ?? itemId`）—— 一樘「布 + 纱 + 帘头」= **1 套**。
   *
   * ⚠️ 它**不改变**分组契约（#4388 冻结：本列表仍按 `order_item_id` = **部位**分组）；
   * 缺键（老数据 / 读面未升级）⇒ 消费方退回「每个部位自成一套」，不猜。
   */
  set_no?: string | null
  /**
   * 该部位（= 商品行）的扫码报工 token（issue #4946，洗水码粒度 = 商品行）。
   * 与加工单级 `qr_token` **不是一回事**：它只覆盖本商品自己的工序集；可撤销 ⇒ 缺键如实 `null`。
   */
  part_token?: string | null
  /** 该部位码的**人可读短码**（8 位，如 `7K3M9QP2`）：扫码枪/人眼读不出来时工人可手输 */
  part_short_code?: string | null
  /** 该部位二维码的**确切内容**（如 `https://app.migaozn.com/s/7K3M9QP2`）—— 前端**不拼**，逐字用 */
  scan_url?: string | null
  /** 订单行商品名（读面按 `order_item_id` 回查订单行）：纸面/弹层标「这一张是给哪一件的」 */
  product_name?: string | null
  /** 订单行宽度（米；V63 列，读面回查；缺键不补默认值） */
  width?: number | null
  /** 订单行高度（米；V63 列，读面回查；缺键不补默认值） */
  height?: number | null
  operations?: ProductionOperation[]
}

export interface ProductionProgress {
  total?: number
  done?: number
  percent?: number
}

/**
 * 计件单价三态（V90，issue #4696；后端闭词表，前端只消费、不发明取值）：
 * - `priced`   有价（**含显式定价 0 元** —— 0 是定价，不是「没定价」）；
 * - `unpriced` **未定价**（矩阵格 `NULL`）⇒ 单价为 `null`、**不得**按 0 计件，界面必须显示
 *   「未定价」并给出定价入口（否则工人白干且无人知道）。
 *
 * 与读面（`GET /operation-layers`）的 `price_state` **同一份词表**（`multiple_prices` 是读面聚合专有，
 * 实例化侧按本行单值取值，不会出现；`no_applicable_position` 已随 #4951 去部位化彻底版退场）。
 */
export type PriceState = 'priced' | 'unpriced'

/**
 * 未定价块（V90，issue #4696）：计件面（per-order 汇总 / 期间报表）的**显式可见**载体。
 *
 * 为什么必须有它：未定价此前只活在**读面徽标**上，而真正算钱的地方把它静默折成 0 元
 * ⇒ 工人白干、商家看不出。`qty` = 未定价工序的合格数量合计（**未计入任何金额**）；
 * `operations` = 逐条工序（该给哪道定价）；`hint` = 可行动提示（指向定价入口）。
 */
export interface UnpricedPieceworkRow {
  /**
   * ⚠️ **工人端快照名**（变体名，如 `精裁-布`）：其它消费者仍要读它 ⇒ 保留；
   * **web 界面不得直接渲染该键**（issue #4621/#4630）—— 界面用 `operationDisplayName()` 渲染。
   */
  operation: string
  /** 逻辑工序名（后端读时派生）；老数据可能缺 ⇒ helper 退回 `operation` 原文 */
  logical_name?: string | null
  /** 部位（如 `布帘`）；部位无关工序 / 老数据为空 ⇒ 只显示逻辑名 */
  position?: string | null
  /** 未定价工序的合格数量（**未计入任何金额**） */
  qty: number
}

export interface UnpricedPiecework {
  qty: number
  operations: UnpricedPieceworkRow[]
  hint?: string
}

/**
 * 未定价实例的**显式补价**结果（issue #4709 C）
 *
 * `POST /api/admin/production/orders/{orderId}/repricing`：只把 `unit_price IS NULL` 的实例行
 * 补成**当前矩阵价**（已有价含显式定价 0 元一律不动、报工进度不清零）。`filled` = 本次补上的
 * 实例行数；`already_priced` = 已有价而未动的行数（红线的可观测面）；`still_unpriced` =
 * 补价后矩阵格仍为空的工序数（需先去矩阵定价）；`batch_id` = 留痕批次（`filled=0` 时为 null），
 * 可交给 `POST /production/repricing/{batchId}/rollback` 撤销。
 */
export interface UnpricedRepricingResult {
  order_id?: string
  processing_order_id?: string | null
  batch_id?: string | null
  filled: number
  already_priced: number
  still_unpriced: number
  filled_operations?: UnpricedPieceworkRow[]
  still_unpriced_operations?: UnpricedPieceworkRow[]
  hint?: string
}

/** GET /api/admin/production/orders/{orderId}/operations */
export interface ProductionOperations {
  order_id?: string
  /** 加工单二维码 token（工人扫码进小程序报工） */
  qr_token?: string | null
  positions?: ProductionPosition[]
  progress?: ProductionProgress
}

export interface PieceworkOperationAmount {
  /**
   * ⚠️ **工人端快照名**（变体名，如 `精裁-布`）：其它消费者仍要读它 ⇒ 保留；
   * **web 界面不得直接渲染该键**（issue #4621/#4630）—— 计件表用 `operationDisplayName()` 渲染。
   */
  operation: string
  /** 逻辑工序名（后端读时派生，如 `精裁`）；老数据 / 商家自建工序可能缺 ⇒ helper 退回 `operation` 原文 */
  logical_name?: string | null
  /** 部位（如 `布帘`）；部位无关工序 / 老数据为空 ⇒ 只显示逻辑名 */
  position?: string | null
  amount: number
}

/** GET /api/admin/production/orders/{orderId}/piecework（内部计件，与对外加工费两套账分离） */
export interface PieceworkSummary {
  total?: number
  /** 分人金额：工人姓名 → 金额 */
  per_worker?: Record<string, number>
  per_operation?: PieceworkOperationAmount[]
  /** 未定价块（V90，issue #4696）：键的在场性恒定（零条未定价也给空块） */
  unpriced?: UnpricedPiecework
}

/**
 * 「卡在哪」卡点报表（issue #4776 = #4698 切片 ③；`GET /api/admin/production/stuck-points`）。
 *
 * 🔴 **A 模式只查「没开工」那一种**（设计 §6 裁定②-3）⇒ `stuck[].kind` 今天恒为 `not_started`；
 * 「开了没完」（仅 C 模式）**不在本报表**。三态互斥且完备：`not_started`（从未报过工）/
 * `in_progress`（`0 < done_qty < qty`）/ `completed`（`done_qty ≥ qty`）。
 *
 * ⚠️ `stalled_hours` 的起算点是**上道完成时刻**（`predecessor.done_at`），**不是** `updated_at`
 * （后者会被任何更新污染 ⇒ 会静默给出错数，设计 §6.1 逐字点名）。`threshold_source` 恒为
 * `default`（S3 全局兜底）—— **不得**在前端把它渲染成「业务标准工时」。
 */
export interface StuckPointsReport {
  /** 判定模式：`A`（A 模式只查「没开工」那一种） */
  mode?: string
  /** 等开工多久算卡的阈值（小时）= S3 全局默认常量，可配 */
  threshold_hours?: number
  /** 阈值来源：`default`（S3 兜底）/ `history`（S1 历史中位数，**尚未落码**） */
  threshold_source?: string
  scope?: { processing_order_id?: string | null }
  /** 三态计数（与报表同范围）—— 三态可区分、不混 */
  states?: { not_started?: number; in_progress?: number; completed?: number }
  stuck_total?: number
  stuck?: StuckPointRow[]
}

/** 卡点报表的一行（按套 × 工序）。 */
export interface StuckPointRow {
  kind?: string
  processing_order_id?: string
  set_id?: string
  set_no?: string | null
  set_index?: number | null
  position?: { order_item_id?: string | null; position_kind?: string | null; position_name?: string | null }
  operation?: {
    operation_id?: string
    logical_name?: string | null
    position?: string | null
    seq?: number | null
    unit?: string | null
    qty?: number | null
    done_qty?: number | null
    state?: string
  }
  /** 立即前道（「上道几点完成」）—— `done_at` 是等待时长的**唯一**起算点 */
  predecessor?: { operation_id?: string; logical_name?: string | null; seq?: number | null; done_at?: string | null }
  stalled_hours?: number | null
  threshold_hours?: number
  threshold_source?: string
}

// ── 工序库 / 工艺路线 / 计件报表（issue #4203/#4204/#4205；后端 ProductionOperationQueryService）──

/**
 * provenance（来源可信度，issue #4361 冻结三态；前端只消费，不发明取值）：
 * - `实证`       有客户真实加工单/报价实证；
 * - `推算`       行业推算（如按同类帘种/工艺推导），非实证值；
 * - `占位待确认` 单价是**初始占位值**（V54 头注「【默】单价占位，商家可配」）⇒ 商家必须改价后才可当工资基数。
 *
 * 未知/缺省（老实例未升级）**不渲染任何徽标** —— 静默 = 未知，**不得**显示成「实证」。
 */
export type ProductionSource = '实证' | '推算' | '占位待确认'

/**
 * 工序作用域（V67，issue #4384 A1；后端闭词表，前端只消费、不发明取值）：
 * - `position` 部位级（默认）：每**部位**一次（今天的行为）；
 * - `set`      套级：每**樘窗**一次 —— 真值源 `docs/curtain-production-rules.md` §8 明写
 *   「**外帘**是加工单打印行部位，**不是**路线键」，但 V54/V58 种子把 外帘打卷/外帘装袋/外帘发货
 *   逐条写进每一条部位路线（含纱帘）⇒ 一樘「布 + 纱」时这 3 道各实例化 2 次 ⇒ 各 ¥1.0 双付。
 *   用户裁定（2026-09-19）：「套级先按**每樘窗一次**实现，打卷是否每帘一次**留成可配**」。
 *
 * ⚠️ 缺省（老实例未升级 / 键缺失）按 `position` 渲染：默认成 `set` 会让每道工序都被静默去重，
 * 而默认成 `position` 最坏只是保持今天的行为 —— 这是**安全方向**。
 */
export type ProductionScope = 'position' | 'set'

/** 工序库一道工序（库口径，非加工单实例） */
export interface CatalogOperation {
  /** 库主键（V54 种子为 `op-v54-01` 形态的字符串，勿假定为数字） */
  id: string | number
  /**
   * 工序名 —— **逻辑工序名**（issue #4642 读时归一；如 `精裁`，不是库口径旧名 `精裁-布`）。
   * 商家面显示名一律用它（+ `position`）。
   */
  name: string
  /**
   * **库口径原名**（如 `精裁-布` / `布三边`）—— 🔴 **web 界面不得渲染该键**：
   * 它的值域是**工人端快照名口径**，渲染它等于把变体名送回商家屏。只为「按库名寻址/对账」保留。
   */
  library_name?: string | null
  /** 工序分组：裁剪 / 车位 / 后道 / 其他 */
  group?: string | null
  /** 部位：布帘 / 纱帘 / 帘头 / 外帘 */
  position?: string | null
  /** 作用域：部位级 / 套级（每樘窗一次；缺省按部位级渲染，见 `ProductionScope`） */
  scope?: ProductionScope | null
  /** 单位：米/套/件/个/折 */
  unit?: string | null
  unit_price: number
  /** 此工序必须完成才可打包（完工门槛） */
  is_must_finish: boolean
  /** 标记生产开始的首工序 */
  is_start_marker: boolean
  /** 来源可信度（#4361；缺省 = 老实例，不渲染徽标） */
  source?: ProductionSource | null
}

export interface CatalogGroup {
  group: string
  operations: CatalogOperation[]
}

/** GET /api/admin/production/operations-catalog */
export interface OperationsCatalog {
  total?: number
  groups?: CatalogGroup[]
}

/**
 * 工艺路线模板（**具名主线 + 适用帘种 + 默认标记**，P2b / issue #4459 起的新结构）。
 *
 * ⚠️ 旧形态（`{curtain_type, craft, operation_count, operations}` 的「部位 × 工艺」展开快照）
 * **已随 P2b 退场**（`GET /routings` 的 javadoc 明写「前端由 P3（#4433）适配」）——
 * 工艺不再参与选路，它只触发 `production_route_rules`。
 */
export interface Routing {
  id: number
  /** 路线**总名**（如「窗帘工序路线（默认）」）—— 商家唯一可改的标识（改名只改它） */
  name: string
  /** 默认路线：**每租户恰一条**（DB 部分唯一索引保证 ≤1）—— 回落链的终点 */
  is_default: boolean
  /** 适用帘种集合（取值域同 `OperationPosition.position`：布帘/纱帘/帘头） */
  positions?: string[]
  /** 主线：**逻辑工序名**的有序序列（如 `["精裁","三边","韩褶"]`） */
  mainline?: string[]
  status?: string | null
}

/** GET /api/admin/production/routings */
export interface RoutingsResponse {
  total?: number
  routings?: Routing[]
}

// ── 行业生产模板目录（issue #4361 冻结契约；前端只消费，写面权限码与后端一致）──

/** GET /api/admin/production/seed-templates 的一项 */
export interface ProductionSeedTemplate {
  templateId: string
  /** 行业 code（受控词表，见 lib/industry.ts） */
  industry: string
  name: string
  version: number
  description?: string
}

/** POST /api/admin/production/seed-templates/{templateId}/apply 的响应（套用幂等：已存在即跳过） */
export interface ProductionSeedApplyResult {
  created_operations: number
  created_routings: number
  skipped: number
}

// ── 工艺路线商家可配（issue #4307 前端半边；契约所有者 = 后端 4308）──
// 端点与字段名以 issue #4308 的冻结清单为准，前端不得自行发明（新增字段一律登记在这里）。

/** 信号映射一行：加工项名/商品名里的信号 → 部位/工艺（库数据，不再读硬编码常量表） */
export interface RouteSignal {
  id: number
  signal: string
  curtain_type: string
  craft: string
  priority?: number
  status?: string
}

/** GET /api/admin/production/route-signals（列表包裹在 signals 键下） */
export interface RouteSignalsResponse {
  total?: number
  signals?: RouteSignal[]
}

/** PUT /api/admin/production/routings/{id} body —— **部分更新**：只写出现的字段（issue #4459 §1③） */
export interface RoutingUpdateParams {
  /** 改名**只改它**（不给 `mainline` 就不动序列） */
  name?: string
  /** 设为默认：**恰一条**（置 true 时服务端把既有默认降级）；⚠️ `false` ⇒ 422（零默认 ⇒ 建单全 fail-closed） */
  is_default?: boolean
  /** 主线：逻辑工序名的有序序列（seq 由服务端归一为 1..N） */
  mainline?: string[]
  /** 适用帘种集合 */
  positions?: string[]
  status?: string
}

/** POST /api/admin/production/routings body（新建路线；初版主线可缺省，随后在编辑区排） */
export interface RoutingCreateParams {
  name: string
  mainline?: string[]
  positions?: string[]
  is_default?: boolean
  status?: string
}

// ── 新模型只读面（issue #4500 = 母单 #4423 的 P2c，P3 #4433 的消费面）──
// ⚠️ 两个端点都**只读**（写面留 v1b）。顺序由服务端定（Java 侧显式比较器，环境无关）——
//    前端**不得**重排（重排会与服务端口径分叉）。

/**
 * 价目一行：**一道逻辑工序 = 一个单价**（issue #4937 / #4951 去部位化彻底版之后的终态）。
 *
 * ⚠️ `operation` 是**逻辑工序名**（`精裁` / `三边`），**不是** `production_operations.name`
 * （那边仍是旧名 `精裁-布` / `布三边`）—— 取错会让矩阵退化成「一行一道旧工序」。
 *
 * ⚠️ `position` **键仍在读面契约里**（`GET /operation-positions` 仍是 10 键）但值**恒 `通用`**
 * —— 部位维已随 #4951 **物理退场**（`production_operation_positions` 每逻辑工序**一行**、
 * V102/V104 后存活行的 `applicable` 恒 `TRUE`、`production_route_rules.position` 全 `NULL`
 * 且不再参与筛选）⇒ 它**不再是配置概念**，web 面**不得渲染**它（不把「通用」这种东西给商家看）。
 *
 * 🔴 **没有 `applicable`**（issue #4937 / O1）：部位适用性已退场 —— 读面该键恒 `true`（已无语义），
 * 写面收到它一律 **422**（「部位适用性已退场，不再受理该字段」，**拒绝**而非静默忽略）
 * ⇒ 前端**不持有、不发送、不判断**该字段。
 * 价的**两态**照旧：`unit_price = null` ⇒ **未定价**（**≠ ¥0.00**）；有值 ⇒ 有价（`0` 就是真 0 元）。
 *
 * `id` + 后 5 键是 issue #4588（契约 #4587 ①）新增的**写面寻址 + 逻辑名↔变体工序映射**：
 * - `id` = 本行（`production_operation_positions.id`）—— 就地改价用它寻址
 *   （`PUT /operation-positions/{id}`）；
 * - 后 5 键 = 该行**实际落到工人端**的那道工序的元数据，由后端
 *   `ProductionOperationQueryService.variantNameOf` 推导（**前端不得另写一份推导**）；
 *   查不到 ⇒ 5 键**全 `null`**（静默 = 未知，不发明元数据）。
 * ⚠️ **没有 `variant_name`**（issue #4622）：变体名（`布三边` / `精裁-布`）是**当前**工序库的旧名，
 *   web 面只用**一套工序名** = 逻辑工序名（`operation`）⇒ 后端响应里已去掉该键
 *   （键在响应里就仍是 web 可见的旧口径）；逻辑名 ↔ 变体的**寻址**用 `variant_operation_id`。
 */
export interface OperationPosition {
  /** 行标识（`PUT /operation-positions/{id}` 的 `{id}`） */
  id?: string | null
  operation: string
  /** 部位维已退场（值恒 `通用`）—— 键仍在读面契约里，web 面**不得渲染** */
  position: string
  unit_price?: number | null
  /** 该格对应的 `production_operations.id`（工人扫码端那道工序；抽屉的 `PUT/DELETE` 按它寻址） */
  variant_operation_id?: string | null
  /** 变体的单位（米/折/件/套） */
  unit?: string | null
  /** 变体的分组（裁剪/车位/后道/其他） */
  group?: string | null
  /** 变体的作用域（V67 闭词表） */
  scope?: ProductionScope | null
  /** 变体是否必完（缺这道工序不能打包） */
  is_must_finish?: boolean | null
}

/**
 * `PUT /api/admin/production/operation-positions/{id}` 的 body（issue #4588；契约 #4587 ②）。
 *
 * 🔴 **只剩一个键**（issue #4937 / O1 去部位化彻底版）：`{unit_price}`。
 * `applicable` **已退场** —— body 里出现它 ⇒ 后端 **422 + 可行动理由**
 * （「部位适用性已退场，不再受理该字段」），**拒绝**而**不静默忽略**
 * （静默 no-op 会让调用方以为改成了「不做」，而那行照旧参与实例化 ⇒ 工人按错工序拿钱且无报错）。
 * ⇒ **本类型不得再长出 `applicable`**（写面契约由后端 `ProductionOperationPositionCommandService` 冻结）。
 *
 * `unit_price: null` ⇒ 改回**未定价**（**≠ 0 元**；0 是「定价为 0」这个真值）。
 */
export interface OperationPositionUpdateParams {
  unit_price?: number | null
}

/**
 * `GET /operation-layers` 的「打包发货」段一行（issue #4677 = 设计
 * `docs/design/public-operations-and-craft-ui.md` §4.1/§4.5 方案 A；契约 #4676）。
 *
 * 分区判据 = **既有** `scope`（`scope='set'` ⇒ 本段；**不新造概念**）。本段的「一列价」是
 * 服务端按该工序**全部存活行**聚合出来的**显式规则**（**不是删行**）：
 *
 * - `priced` ⇒ 各行价全同，`price` = 那个价；
 * - `unpriced` ⇒ 有行没定价（**含零行** —— #4951 后零格也判这一态），`price = null`
 *   —— **未定价 ≠ ¥0.00**（回落工序库行价会把「未定价」变成真 0 元，工人白干）；
 * - `multiple_prices` ⇒ 各行价不同，`price = null` + `different_price_count`
 *   （**不静默取第一个**）。
 *
 * ⚠️ **四态 ⇒ 三态**（issue #4937 / #4951 去部位化彻底版）：第 4 态 `no_applicable_position`
 * （「一格『做』都没有」）**已退场** —— 存活价目行的 `applicable` 恒 `TRUE` ⇒「一格『做』都没有」
 * 这个状态**不可达**；零格行落 `unpriced`。
 * ⚠️ **键集一字不变（仍是 9 键）**：`applicable_positions` **键保留**但**恒 `[]`** ——
 * 部位维已退场，前端**不得**据它渲染任何逐部位控件。
 */
export interface OperationLayerDeliveryRow {
  operation: string
  scope: ProductionScope
  unit?: string | null
  group?: string | null
  is_must_finish?: boolean | null
  price?: number | null
  price_state: 'priced' | 'unpriced' | 'multiple_prices'
  different_price_count: number
  /** 部位维已退场 ⇒ **恒 `[]`**（键保留 = 9 键契约不变；前端**不得**据此渲染） */
  applicable_positions: string[]
}

/**
 * `GET /operation-layers` 的 `data`（issue #4676）。
 *
 * ⚠️ `operations` 段的每行与 `GET /operation-positions` **同形**（同一个 `positionView`）
 * ⇒ 前端同一份渲染代码；本端点只是**多给一层分区 + 一列价聚合**，**不替代**原端点
 * （抽屉的 `PUT /operation-positions/{id}` 仍按格的 `id` 寻址）。
 */
export interface OperationLayers {
  operations: OperationPosition[]
  delivery: OperationLayerDeliveryRow[]
}

/**
 * 算料公式**租户级配置**（issue #4528 = 包 E）—— 键与算料引擎
 * `curtain_calc.DEFAULT_CRAFT_CALC_CONFIG` **逐字同名**
 * （`GET|PUT /api/admin/production/craft-calc-config` 的 `data.config`）。
 *
 * ⚠️ 前端**不持有任何默认值**：本租户没有配置行时，后端返回的就是**引擎默认值**
 * （`source='default'`）⇒ 页面直接渲染它。在 TS 侧再抄一份默认值 = 第二份会漂的默认值
 * （引擎改默认、页面还显示旧值 ⇒ 商家按错的口径改配置）。
 */
export interface CraftCalcConfig {
  /** 单色每折吃布（米）—— 褶数法：用料 = 每折吃布 × 褶数 + 余量 */
  per_fold_single: number
  /** 拼色「拼次 → 每折吃布（米）」；键是拼次的字符串形态（JSON 对象键恒为字符串） */
  per_fold_mixed_times: Record<string, number>
  /** 单开余量（米） */
  margin_single: number
  /** 多开余量（米） */
  margin_multi: number
  /** 褶倍下限（行业红线，可配但不可关） */
  min_fullness: number
  /** 工艺档位 `{档位名: {fullness, label}}` */
  tiers: Record<string, { fullness: number; label?: string }>
  /** 兜底用料公式：`pleat` 韩褶公式（褶数法）/ `fullness` 褶倍数公式（倍数法） */
  default_formula: string
  /** 定宽买高上下卷边（米） */
  side_margin: number
  /** 用料**向上进位**步长（米） */
  meters_rounding_step: number
}

/**
 * 算料配置读面响应：`source='default'` = 本租户**没有**配置行（值 = 算料引擎默认值）；
 * `'stored'` = 已保存的商家配置。页面据此区分「系统默认值」与「我的配置」。
 */
export interface CraftCalcConfigResponse {
  source: string
  config: CraftCalcConfig
}

/** 统一规则区一条：工艺变体 ∪ 特殊选项的**路线编排**规则（`action` = insert / remove） */
export interface RouteRule {
  id: number
  /** 触发维：`craft` 工艺 / `option` 特殊选项 */
  trigger_kind?: string | null
  /** 触发键取值 —— **与 ERP 名逐字一致**（#4389 join key 纪律：前端不得拼写或"纠正"） */
  trigger_value?: string | null
  /**
   * 部位限定；`null` = 不限部位。
   * ⚠️ **规则级部位已退场**（issue #4937 / #4951）：`production_route_rules.position`
   * **全 `NULL` 且不再参与筛选** —— 键仍在读面契约里，前端**不得**据它渲染或过滤。
   */
  position?: string | null
  action?: string | null
  /** 目标工序（逻辑名）—— issue #4643 起写面落库前归一、读面返回前同样归一（存量行兜底） */
  operation?: string | null
  /** `insert` 的锚点工序（逻辑名）；`null` = 追加末尾 */
  after_operation?: string | null
  /** 规则应用顺序（`remove` 不先于 `insert` 完全由它决定）—— 顺序敏感 */
  priority?: number | null
  status?: string | null
  /**
   * 客户单价 —— **元/套**（V77；行业口径：特殊选项按**套**收费）。
   * `null` = **未定价**（**≠ 0 元**，不得渲染成 `¥0.00`）；非 `option` 行恒 `null`（工艺变体不按套计价）。
   */
  customer_unit_price?: number | string | null
}

/** `PUT /api/admin/production/route-rules/{id}/customer-unit-price` 的 body（元/套，issue #4567） */
export interface RouteRuleCustomerPriceParams {
  /**
   * 对客单价（**元/套**）。`null` = 显式改回**未定价**（语义是「还没定价」，**不是** 0 元）。
   * 服务端护栏：非 `option` 行 / 负数 / 超过两位小数 / 非数值 ⇒ 422 逐条理由。
   */
  customer_unit_price: number | string | null
}

/**
 * `POST /api/admin/production/route-rules` 的 body（**新增特殊选项**，issue #4570）。
 *
 * 用户裁定：「只要能新增工序项就行了，并可以设置为特殊选项或者工序，也支持设置单价」。
 * ⚠️ **两本账**：这里的 `customer_unit_price` 是**对客元/套**（`production_route_rules`），
 * 与工序库 `POST /operations` 的 `unit_price`（**计件**，元/件·米·折，给工人）**互不换算**
 * ⇒ 本 body **不带** `name` / `group_name` / `unit` / `unit_price` 那套工序字段。
 */
export interface RouteRuleCreateParams {
  /**
   * 触发维（**闭词表**，issue #4616）：`craft` 工艺 / `option` 特殊选项 / `processing_item` 加工项。
   *
   * 省略 = `option`（**反向护栏**：老调用方/老 bundle 行为一字不变）。`shaped` 是表结构预留、
   * 无种子行 ⇒ 后端收到即 422（前端也不提供该档）。
   */
  trigger_kind?: RouteRuleTriggerKind
  /** 触发值 —— `craft`/`processing_item` 必须**存在于对应词表**；`option` 可新建（#4389 join key 纪律） */
  trigger_value: string
  /** 动作：`insert` 插入 / `remove` 移除；省略 = `insert`（老调用方行为不变） */
  action?: 'insert' | 'remove'
  /** 目标工序（**逻辑工序名**，与 `production_route_rules.operation` 逐字一致，如 `精裁`） */
  operation: string
  /** 插入锚点（逻辑工序名）；省略 / `null` = 追加末尾（`remove` 不接受锚点） */
  after_operation?: string | null
  /** 规则应用顺序（越小越先）；省略 / `null` = 后端默认顺序 */
  priority?: number | null
  /** 对客单价（**元/套**）；`null` = 未定价。**只允许 `trigger_kind='option'`**（两套账不互读） */
  customer_unit_price?: number | string | null
}

/** 条件工序规则的触发维（issue #4616；与后端闭词表 `TRIGGER_KINDS` 同口径）。 */
export type RouteRuleTriggerKind = 'craft' | 'option' | 'processing_item'

/**
 * 规则创建弹窗的**触发值取值域**（issue #4616；`GET /api/admin/production/route-rule-options`）。
 *
 * 手输一个词表里没有的名字 = 建一条**永远不命中**的规则（商家以为配了、加工单上却没有）
 * ⇒ 触发值必须从对应词表取。特殊选项名**不在此列**（可新建，没有第二份词表）。
 */
export interface RouteRuleTriggerOptions {
  /** 活跃工艺词表（`production_crafts`） */
  crafts: string[]
  /** 活跃加工项目录（触发键 = 订单行的加工项名，**精确相等**） */
  processing_items: string[]
}


/**
 * 路线写端点失败时的响应体（护栏理由）—— 后端**真实**信封（issue #4308「冻结补遗 ②」）：
 * `{success:false, error:{code, message, details:[{field, message}]}, suggestion}`。
 * - `error.details[].message`：**逐条**护栏理由（空序列 / 工序不存在 / 重复 / 缺必完工序）—— **主口径**；
 * - `error.message`：一句话摘要 —— 仅在 `details` 缺失时退化使用；
 * - `field`：违规维度（如 `operations[2]` / `must_finish`），**只用于定位，不展示给商家**。
 *
 * 前端**不得**把这些理由吞成一句「保存失败」（issue #4307 交付物 1）。
 * ⚠️ 不存在顶层 `error_messages` 字段，`error` 也不是字符串 —— 按那个形状读会让失败路径静默退化。
 */
export interface RoutingGuardErrorBody {
  error?: {
    code?: string
    message?: string
    details?: { field?: string; message?: string }[]
  }
}

/** POST /api/admin/production/operations（新增工序：建新路线时必须有工序可选） */
export interface RouteOperationCreateParams {
  name: string
  group_name?: string
  unit?: string
  unit_price: number
  position?: string
  /**
   * **适用部位**（issue #4614，形态裁定 A）：给了就为每个部位建一行矩阵行
   * （`production_operation_positions`）⇒ 新工序**立刻出现在「工艺项」表里**且可就地定价。
   *
   * ⚠️ 不给 = 今天的行为（只建工序库行）—— 但那样新工序**在界面上无处可见**
   * （「工艺项」表只按矩阵行渲染，原「工序库明细」表已随 #4588 取消）⇒ 本页永远给。
   * 值域 = 矩阵里出现的部位 ∪ 基线三部位（与「新建路线」的适用帘种同一份口径）。
   */
  positions?: string[]
}

/**
 * 「按部位补建矩阵行」的**报数**（issue #4614）：新增路径（`POST /operations` 带 `positions`）与
 * 存量接入路径（`PUT /operations/{id}` 带 `positions`）**同一形状** —— 前端 toast 报的是
 * **服务端真实数字**，不得自行推算（缺结果体时显式报错，不假装成功）。
 */
export interface OperationPositionsAttachResult {
  /** 本次**新建**的矩阵行数 */
  created_positions?: number
  /** 本次**跳过**（已存在，保留商家改过的价）的矩阵行数 */
  skipped_positions?: number
}

/**
 * POST /api/admin/production/operations 的响应（issue #4614）：带 `positions` 时**如实附上**
 * 矩阵行写入结果 —— 前端 toast 报的是**服务端真实数字**，不得自行推算
 * （照 `applySeedTemplate` 的「新增/跳过」报数纪律；缺结果体时显式报错，不假装成功）。
 */
export interface RouteOperationCreateResult
  extends CatalogOperation,
    OperationPositionsAttachResult {}

/** 缺口语义（GET /api/admin/production/routing-gaps）：两类缺口**语义不同**，不得混渲 */
export interface RoutingGapOperation {
  name: string
  group_name?: string | null
  unit?: string | null
  unit_price?: number | null
  /**
   * **有意挂起、等客户确认**（issue #4261 提问清单：裁剪vs精裁是否两道 / 质检是否每单必做 /
   * 腰靠垫归属 / 罗马帘整套工序 / 纱帘熨烫定型）。
   *
   * ⚠️ 后端 `ProductionOperationQueryService.routingGaps` 明写：**「不要让商家/前端把它们
   * 读成「系统漏了」」** —— 猜出来的工序与单价会**直接算成工人工资**，故一律不猜。
   * ⇒ `true` 的条目必须与真缺口**分开渲染**，且不进「就绪度」的待处理计数。
   */
  pending_confirmation?: boolean
  /** 后端给的可读说明（挂起原因 / 该工序有价但无路线消费）—— 直接展示，不在前端重写一份 */
  note?: string | null
}

/** 库里没有任何（活跃）路线的信号组合 —— 这些组合目前会回落到默认路线 */
export interface RoutingGapSignalKey {
  curtain_type: string
  craft: string
  /** 派生出的完整路线键（如 `罗马帘×韩褶`）—— 服务端给，前端不自己拼 */
  route_key?: string
  /** 命中它时派生出该键的信号关键词 */
  signal?: string
}

/** GET /api/admin/production/routing-gaps */
export interface RoutingGaps {
  unrouted_operations?: RoutingGapOperation[]
  unrouted_operation_total?: number
  pending_confirmation_total?: number
  signal_keys_without_route?: RoutingGapSignalKey[]
}

// ── 加工费组合定价（issue #4386；契约所有者 = 后端 4386）────────────────────────
// 口径（用户裁定 2026-09-19）：「不是每个加工项收取一个费用，而且通常是组合」
// 「选配完的一个商品只会收取一种加工费」⇒ 一行 = 一组选配特征 → 一个单价（元/米）。

/**
 * 一行加工费组合定价。
 *
 * ⚠️ `composition_key` 是**服务端归一化**后的匹配键（与书写顺序无关）——
 * 前端**只读**它，**绝不**自己拼（自己拼 = 第二份口径，漂移后页面显示的组合与库里不是同一个）。
 * `items` 与 `composition_key` **同源**，展示用。
 */
export interface FeeCombination {
  id?: string
  /** 归一化后的选配特征集合（如 `定型+打孔+韩褶`）—— 取价的匹配键 */
  composition_key: string
  /** 归一化后的特征名有序列表（展示用） */
  items?: string[]
  /** 加工费单价（元/米） */
  unit_price?: number
  /** 展示单位（服务端给「元/米」） */
  unit?: string
  status?: string
  sort_order?: number
  /** provenance：实证 / 推算 / 占位待确认；null = 未知（商家自建） */
  source?: string | null
  updated_at?: string | null
}

/** GET /api/admin/production/processing-fee-combinations */
export interface FeeCombinationsResponse {
  total?: number
  combinations?: FeeCombination[]
}

/** POST /api/admin/production/processing-fee-combinations body（**只提交勾选集合**，key 由服务端归一） */
export interface FeeCombinationCreateParams {
  items: string[]
  unit_price: number
  sort_order?: number
  source?: string
}

/** PUT /api/admin/production/processing-fee-combinations/{id} body（部分更新） */
export interface FeeCombinationUpdateParams {
  unit_price?: number
  status?: string
  source?: string
  sort_order?: number
}

/** 未定价组合（GET /api/admin/production/processing-fee-gaps）—— 每一条都是**可行动项** */
export interface FeeGapCombination {
  composition_key: string
  items?: string[]
  /** 该组合在订单里出现的次数（商家按成交热度排序补价） */
  order_count: number
  note?: string
}

export interface FeeGaps {
  unpriced_combinations?: FeeGapCombination[]
  unpriced_combination_total?: number
  /** 已扫描的订单行数（缺口扫描有上限，超限时 scanned_truncated=true —— 不静默） */
  scanned_order_items?: number
  scanned_truncated?: boolean
}

export interface PieceworkWorkerAmount {
  worker_name: string
  amount: number
  qty: number
}

export interface PieceworkReportOperationAmount {
  /**
   * ⚠️ **工人端快照名**（变体名，如 `精裁-布`）：其它消费者仍要读它 ⇒ 保留；
   * **web 界面不得直接渲染该键**（issue #4621）—— 计件页用 `operationDisplayName()` 渲染。
   */
  operation: string
  /** 逻辑工序名（后端读时派生）；老数据可能缺 ⇒ helper 退回 `operation` 原文 */
  logical_name?: string | null
  /** 部位（如 `布帘`）；部位无关工序 / 老数据为空 ⇒ 只显示逻辑名 */
  position?: string | null
  amount: number
  qty: number
}

/**
 * 下钻维度行（issue #4347 §3.2 / 真值源 §4 的下钻链：部位 → 套）。
 *
 * <p>后端由**同一份聚合**产出（与按人/按工序同源）⇒ 各维合计恒等于 total。
 * 键名两维不同：部位用 `position_name`，套用 `set_no`（#4725：套 = **樘窗**（`craftLineId` 组），
 * 不是订单行 —— 键名此前叫 `order_item_id`，把「套」谎称成「订单行」）。</p>
 */
export interface PieceworkDrillDownRow {
  position_name?: string
  set_no?: string
  amount: number
  qty: number
}

/** GET /api/admin/production/piecework/summary?period=YYYY-MM[&worker_name=]（issue #4205） */
export interface PieceworkReport {
  period: string
  total: number
  per_worker: PieceworkWorkerAmount[]
  per_operation: PieceworkReportOperationAmount[]
  /** 按部位下钻（真值源 §4 下钻链） */
  per_position?: PieceworkDrillDownRow[]
  /** 按套下钻（`set_no` = 樘窗/套的**套号**；无号时 = 樘窗组键，issue #4725） */
  per_set?: PieceworkDrillDownRow[]
  /** 未定价块（V90，issue #4696）：与 per-order 汇总**同一份聚合** ⇒ 两处恒等 */
  unpriced?: UnpricedPiecework
}

/** 工序可写字段（PUT /api/admin/production/operations/{id}，issue #4204；scope 见 #4384 A1） */
export interface ProductionOperationUpdateParams {
  unit_price?: number
  is_must_finish?: boolean
  is_start_marker?: boolean
  status?: string
  unit?: string
  group_name?: string
  sort_order?: number
  /** 作用域（V67，issue #4384 A1）：position 部位级 / set 套级（每樘窗一次） */
  scope?: ProductionScope
  /**
   * **按部位补建矩阵行**（issue #4614 范围补口，**存量孤儿接入路径**）：只**补**缺失的
   * `(逻辑名, 部位)` 行 —— 已存在的活跃行**跳过**（不覆盖已定价的格）、**不删**任何已有行；
   * 响应附 `created_positions` / `skipped_positions` 如实报数。
   * 停用工序不接部位（422）。值域与新增工序同一份（矩阵里出现的部位 ∪ 基线三部位）。
   */
  positions?: string[]
}

// 物流信息
export interface LogisticsInfo {  logisticsCompany?: string
  trackingNo?: string
  /**
   * 发货人（发货单纸面「经手人」，issue #3768）。
   * 存量已发货订单为 undefined/NULL（历史上从未采集）→ 纸面该栏显示「-」
   * （#3818 裁定，与 #3768 判据一致；不得留白、不得 undefined/null）。
   */
  shipperName?: string
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
  actualAmount: number         // 实收款
  discountAmount?: number      // 优惠金额 (issue #672)
  refundAmount?: number        // 已退款金额（>0 表示订单已退款；退款不再改变订单状态）
  refundAt?: string            // 退款时间
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
  /**
   * **常用物流/快递**（issue #4874；后端 #4872 在 `orders` 上新增的两列，
   * `OrderDetailResponse` 已透出）：`express` 快递 / `logistics` 物流专线。
   * 建单时由下单页把客户档案带出的值随单落库 ⇒ 发货页据此**优先**带出（缺省才回落到
   * 按收货手机号反查客户档案，见 `orders/[id]/ship/ShipOrder.tsx`）。
   */
  logisticsType?: string | null
  /** **常用物流公司**（issue #4874；同上）：自由文本 */
  logisticsCompany?: string | null
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
  actualAmount?: number           // 实收款（用户输入的实际收款金额）
  discountAmount?: number         // 优惠金额（后端校验 应收-优惠≈实收，必须随单携带）
  /**
   * **常用物流/快递**（issue #4874 顶层新列，后端 #4872）：`express` 快递 / `logistics` 物流专线。
   * 缺值不传 —— 「未指定」与「快递」是两个真值，写死默认值就是编造（#4419 同族口径）。
   */
  logisticsType?: string
  /** **常用物流公司**（issue #4874 顶层新列）：自由文本（词表只是候选，允许自定义） */
  logisticsCompany?: string
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
  /** 发货人（发货单「经手人」，issue #3768）：默认预填当前登录人姓名，可改成实际发货人 */
  shipperName?: string
  /** 物流类型：express 快递 / logistics 物流专线（issue #4419；后端 order_logistics.logistics_type，V47） */
  logisticsType?: string
}

// 关闭订单参数
export interface CloseOrderParams {
  reason: string               // 关闭原因
  remark?: string              // 其它原因备注
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
  // —— 地区（后端 CustomerProfile 省市区；#3102 下单选客户回填地址前缀）——
  regionProvince?: string
  regionCity?: string
  regionDistrict?: string
  // —— 默认收货信息与常用物流（issue #4419 / #3984，后端 CustomerProfile 原始列名）——
  // 收货地址优先于上面的 region* 回填（region* 是客户所在地区，不是收货地址）
  defaultReceiverName?: string
  defaultReceiverPhone?: string
  defaultReceiverAddress?: string
  /** express 快递 / logistics 物流专线（customer_profiles.default_logistics_type） */
  defaultLogisticsType?: string
  defaultLogisticsCompany?: string
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

// 客户档案（后端 CustomerProfile 实体序列化返回）
// GET /api/admin/customers/{id} → profile 字段
export interface CustomerProfile {
  id?: string
  wechatNickname?: string
  avatarUrl?: string
  phone?: string
  sourceChannel?: CustomerChannel | string
  // 后端返回字符串（normal/vip1/vip2/vip3）
  vipLevel?: number | string | null
  // 备注（后端字段名 agentNotes）
  agentNotes?: string
  lastActiveAt?: string
  registeredAt?: string
  // —— 默认收货信息与常用物流（issue #4419，V70 / #3984，V47）——
  defaultReceiverName?: string
  defaultReceiverPhone?: string
  defaultReceiverAddress?: string
  /** express 快递 / logistics 物流专线 */
  defaultLogisticsType?: string
  defaultLogisticsCompany?: string
}

// 客户详情页响应（后端契约：{ id, profile, tags, orders, sessions }）
export interface CustomerDetailResponse {
  id: string
  profile: CustomerProfile
  tags?: CustomerTag[] | null
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
// #3103: notificationEmail 为僵尸字段（站内信无需邮箱，后端无邮件消费逻辑），已从类型移除
export interface SystemSettings {
  companyName: string
  logo?: string
  notificationEnabled: boolean
}

// 修改密码参数
export interface ChangePasswordParams {
  oldPassword: string
  newPassword: string
  confirmPassword: string
}

// 登录日志（对应后端 AuditLog action=login 的字段）
export interface LoginLog {
  id: string
  userId?: string
  userName?: string
  ipAddress?: string
  userAgent?: string
  createdAt: string
}

// ========== Dashboard 类型 ==========

// Dashboard 统计数据
export interface DashboardStats {
  todayOrders: number
  todayOrdersChange: number
  todaySales: number
  todaySalesChange: number
  totalCustomers: number
  newCustomersToday: number
  activeSessions: number
  aiSessionRate: number
  monthRevenue: number
  monthRevenueChange: number
  totalProducts: number
  totalOrders: number
  totalTickets: number
  // 待处理区 3 卡片 (#387, #1396)
  pendingShipOrders: number
  processingPendingOrders: number
  lowStockItems: number
}

// 商品销量排行
export interface ProductRanking {
  rank: number
  productId: string
  productName: string
  salesQty: number
  salesAmount: number
  qtyDisplay: string
  amountDisplay: string
  dailyChange: number
}

// ========== 智能每日经营简报（issue #3468）==========

// 简报指标引用（数字回填校验：key/value 均来自聚合快照，禁止 LLM 编造）
export interface BriefingMetricRef {
  key: string
  value: number
}

// 简报条目（待办/风险/建议通用结构）
export interface BriefingItem {
  priority?: string
  severity?: string
  title: string
  reason?: string
  detail?: string
  link?: string
  metrics: BriefingMetricRef[]
}

// 简报回顾指标
export interface BriefingReviewItem {
  label: string
  value: number
  unit?: string
  change?: string
}

// 简报内容（四区块）
export interface BriefingContent {
  summary: string
  review: BriefingReviewItem[]
  todo: BriefingItem[]
  risks: BriefingItem[]
  suggestions: BriefingItem[]
}

// 今日简报响应
export interface TodayBriefingResponse {
  generated: boolean
  verifyStatus: string | null
  content: BriefingContent | null
  bizDate: string | null
}

// 简报配置（企业开关 + 生成时刻）
export interface BriefingConfig {
  enabled: boolean
  generateTime: string
}

// 待处理任务
export interface PendingTask {
  id: string
  type: 'order' | 'after_sales'
  title: string
  priority: 'high' | 'medium' | 'low'
  createdAt: string
  link: string
}

// 订单趋势数据点
export interface OrderTrendPoint {
  date: string
  orders: number
  amount?: number  // 当日订单总金额（分），字段与后端 OrderTrendPointResponse 对齐
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

// 交互式组件类型
export type InteractiveComponentType = 'choice' | 'confirm' | 'form'

// 选项卡片中的选项
export interface InteractiveOption {
  label: string
  value: string
  description?: string
}

// 确认卡片中的字段
export interface InteractiveField {
  label: string
  value: string
}

// 表单卡片中的字段（带 key，用于一次性收集多个信息）
export interface InteractiveFormField {
  key: string        // 字段标识，如 "name", "price"
  label: string      // 显示标签，如 "商品名称"
  placeholder?: string
  value?: string     // 预填值（如图片识别结果）
  required?: boolean
}

// 交互式组件数据
export interface InteractiveComponent {
  component: InteractiveComponentType
  title: string
  // choice 组件
  options?: InteractiveOption[]
  // 是否允许多选（加工项选择等场景）。为 true 时点击选项不锁死卡片，
  // 支持连续点击多个选项分别发送；配合 pageMeta 支持翻页继续选择。
  multiSelect?: boolean
  // 多选提交文案后端驱动（#3032）：色号/规格/换货目标等非加工项场景传自定义值，
  // 前端不再硬编码「已选加工项」「不需要加工项」。
  multiSelectSubmitPrefix?: string  // 提交文本前缀，默认「已选加工项：」
  multiSelectSubmitLabel?: string   // 完成按钮文字，默认「完成选择」
  multiSelectSkipLabel?: string     // 跳过按钮文字 + 跳过提交文本，默认「不需要加工项」
  // confirm 组件
  fields?: InteractiveField[]
  confirmLabel?: string
  cancelLabel?: string
  confirmValue?: string
  cancelValue?: string
  // form 组件
  formFields?: InteractiveFormField[]
  submitLabel?: string
  // 分页元数据（choice 组件可选）
  pageMeta?: {
    current: number
    total: number
    totalCount: number
    tool: string
    params: string  // JSON string
  }
}

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
  interactive?: InteractiveComponent  // 交互式组件
  // 该交互组件是否已被用户答复（issue #3036）：消息级状态作为只读锁的单一事实源，
  // 历史回放/刷新/FAB 重开后仍保持，防止已答复卡片「复活」重复提交。
  interactiveAnswered?: boolean
  wasAborted?: boolean  // 是否被用户主动中断（用于区分"已处理"与"对话已中断"）
}

// SSE 事件类型
export type SSEEventType = 'message_start' | 'text_delta' | 'text' | 'tool_start' | 'tool_call' | 'tool_result' | 'card' | 'loading' | 'message_end' | 'error' | 'message' | 'done' | 'suggestions' | 'interactive'

// 卡片类型
// 卡型联合 = 后端 `_detect_card_type` **真实可产出**的集合（#4016 P14 收敛对齐）：
// - 新增 `production_progress`：用户 2026-09-18 裁定「补发射点」，该工具返回的正是卡载荷
// - 移除 `knowledge`：后端从不下发该卡型（ToolResultCard 死分支已同批删除）
// 契约守卫：backend/ai-agent-service/tests/test_card_type_cross_end_contract.py（双向）
export type CardType = 'product_list' | 'product_detail' | 'logistics' | 'order' | 'production_progress'

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
  /** 权限 ID（后端 IdType.ASSIGN_UUID，字符串） */
  id: string
  name: string
  code: string
  resource: string
  action: string
  description?: string
}

// 角色
export interface Role {
  /** 角色 ID（后端 IdType.ASSIGN_UUID，字符串） */
  id: string
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
  permissionIds: string[]
}

// 员工
export interface Employee {
  id: number
  name: string
  phone?: string
  email?: string
  position?: string
  role: string
  roles: Role[]
  permissions?: string[]
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
  name: string
  phone: string
  position: string
  /** RBAC 角色码（admin/operator/product_manager/自定义角色）；此前 UI 不传导致新建员工恒为 operator */
  role?: string
  permissions: string[]
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
  /** AI 甄别来源：ai / system / manual */
  reviewSource?: string
  /** 风险标记 JSON 数组字符串 */
  riskFlags?: string
  /** AI 审查摘要 */
  reviewSummary?: string
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
  /** 蜜罐字段（隐藏，真人不会填写；被填充则判定为自动化脚本） */
  website?: string
}

// 入驻申请提交结果（AI 自动甄别）
export interface RegistrationResult {
  applicationId: number
  /** approved（AI 甄别通过）/ rejected（AI 甄别驳回）/ pending（兜底） */
  status: RegistrationStatus
  message: string
  /** status=rejected 时的驳回原因 */
  rejectReason?: string
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

// 商品颜色（id 为 BIGSERIAL，可能超过 JS 2^53，后端序列化为字符串）
export interface ProductColor {
  id: string
  colorName: string
  mainColorHex?: string
  colorImageUrl?: string
  remark?: string
  sortOrder?: number
}

// 商品 SKU（id/colorId 为 BIGSERIAL，可能超过 JS 2^53，后端序列化为字符串）
export interface ProductSku {
  id: string
  colorId: string
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

// ========== 财务对账相关类型 ==========

// 资金流水收支类型
export type FinanceTransactionType = 'income' | 'refund'

export const FinanceTransactionTypeLabels: Record<FinanceTransactionType, string> = {
  income: '收款',
  refund: '退款',
}

// 支付方式
export type FinancePaymentMethod = 'wechat' | 'alipay' | 'bank_transfer' | 'cash' | 'other'

export const FinancePaymentMethodLabels: Record<FinancePaymentMethod, string> = {
  wechat: '微信',
  alipay: '支付宝',
  bank_transfer: '银行转账',
  cash: '现金',
  other: '其他',
}

// 流水状态
export type FinanceTransactionStatus = 'pending' | 'success' | 'failed'

export const FinanceTransactionStatusLabels: Record<FinanceTransactionStatus, string> = {
  pending: '待处理',
  success: '成功',
  failed: '失败',
}

// 资金流水
export interface FinanceTransaction {
  id: string
  transactionNo: string
  orderId?: string
  orderNo?: string
  type: FinanceTransactionType
  amount: number
  paymentMethod?: FinancePaymentMethod
  status: FinanceTransactionStatus
  operator?: string
  occurredAt?: string
  remark?: string
  createdAt?: string
}

// 资金流水查询参数
export interface FinanceTransactionListParams extends PageParams {
  type?: FinanceTransactionType | ''
  paymentMethod?: FinancePaymentMethod | ''
  status?: FinanceTransactionStatus | ''
  startDate?: string
  endDate?: string
  keyword?: string
}

// 登记收支表单
export interface FinanceTransactionFormData {
  type: FinanceTransactionType
  amount: number
  paymentMethod?: FinancePaymentMethod
  orderId?: string
  occurredAt?: string
  remark?: string
}

// 收支汇总
export interface FinanceMethodSummary {
  paymentMethod: string
  income: number
  refund: number
  net: number
}

export interface FinanceDailySummary {
  date: string
  income: number
  refund: number
  net: number
}

export interface FinanceSummary {
  startDate?: string
  endDate?: string
  totalIncome: number
  totalRefund: number
  netIncome: number
  incomeCount: number
  refundCount: number
  pendingReceivable: number
  byPaymentMethod: FinanceMethodSummary[]
  dailyTrend: FinanceDailySummary[]
}

// 应收对账
export interface ReceivableReconciliationItem {
  orderId: string
  orderNo: string
  customerName?: string
  customerPhone?: string
  status: string
  receivableAmount: number
  receivedAmount: number
  refundAmount: number
  difference: number
  createdAt?: string
}
