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
  ProductImportResult,
  Category,
  CategoryFormData,
  ProcessingItem,
  ProcessingItemListParams,
  ProcessingItemFormData,
  ProcessingCategory,
  ProcessingCategoryFormData,
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
  ProcessingOrderGenerateBatch,
  ProcessingOrderUpdateParams,
  InboundOrder,
  InboundOrderLine,
  InboundBatch,
  InboundOrderCreateParams,
  InboundOrderListParams,
  BatchRemaining,
  BatchDistribution,
  BatchReconcile,
  BatchCandidates,
  ProductionOperations,
  PieceworkSummary,
  StuckPointsReport,
  OperationsCatalog,
  RoutingsResponse,
  PieceworkReport,
  CatalogOperation,
  ProductionOperationUpdateParams,
  Routing,
  RoutingCreateParams,
  RoutingUpdateParams,
  OperationPosition,
  OperationPositionUpdateParams,
  OperationLayers,
  RouteRule,
  RouteRuleCustomerPriceParams,
  RouteRuleCreateParams,
  RouteRuleTriggerOptions,
  CraftCalcConfig,
  CraftCalcConfigResponse,
  RoutingGaps,
  // 加工费组合定价（issue #4386）
  FeeCombination,
  FeeCombinationsResponse,
  FeeCombinationCreateParams,
  FeeCombinationUpdateParams,
  FeeGaps,
  RouteOperationCreateParams,
  RouteOperationCreateResult,
  OperationPositionsAttachResult,
  RouteSignalsResponse,
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
  UnpricedRepricingResult,
  PaymentQrcodeMap,
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

  // 批量导入商品 + SKU（issue #5154）——「导出」的对偶入口。
  // 后端**恒返 200 + 逐行报告**（行级原子，不是整包回滚）：合法的行照常落库，
  // 非法的行在 data.errors[] 里带「行号 + 货号 + 可行动原因」。
  importProducts: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return request.post<ApiResponse<ProductImportResult>>('/api/admin/products/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  // 下载导入模板（表头与导入解析共用同一常量 ⇒ 模板填得了的列，导入一定认识）
  downloadImportTemplate: () =>
    request.get<Blob>('/api/admin/products/import-template', { responseType: 'blob' }),
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
//
// issue #4882（用户裁定）：加工项的单价 / 计价方式整体退场 ⇒ `POST /processing-items/calculate`
// （`calculatePrice`）的调用面已不存在，随之删除（后端端点亦在本次下线）。
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
  /** 悬挂方式（仅 `s_hook` 韩褶走褶数法） */
  mounting?: string
  /** 工艺档位（standard 2.0 / economy 1.8） */
  craft_tier?: string
  /** 款式（单色 / 拼色）；拼色需同时给拼次特殊选项才有拼色用料系数 */
  style?: string
  /** 部位级特殊选项（逐字名）；拼色用料系数由 `拼1次` / `拼2次` 决定 */
  special_options?: string[]
  /**
   * 用料**计算方法**（issue #4527，用户 2026-09-19 裁定）：
   * `pleat` = 韩褶公式（褶数法，**默认**）/ `fullness` = 褶倍数公式（倍数法）。
   * 缺省由算料引擎的配置默认值给（前端不补默认值 = 不制造第二份口径）。
   */
  formula?: string
  /**
   * 安装工艺（用户 2026-09-19 追加裁定「韩褶用韩褶公式算布料，打孔按倍数法算布料」）：
   * 韩褶/打孔/四爪钩/穿杆/平幔。**公式由工艺推导**，权威表在算料引擎（`curtain_calc.resolve_craft_rule`）。
   */
  craft?: string
  /**
   * 是否对花（issue #4571）：**只在「定宽买高」时影响用料** —— 每幅长 +1 个花距
   * （算料引擎 `curtain_calc` 的 `has_pattern`；定高买宽下它不改变用料）。
   * 缺省 `false` = 不按对花算（**不是**「未指定」：本键不进三态语义）。
   */
  has_pattern?: boolean
  /** 花距（米），仅 `has_pattern=true` 时有意义；行业常见 0.3~0.6 */
  pattern_repeat?: number
}

/** 试算结果 —— 算料输出子集（§4.5 snake_case） */
export interface CraftCalcResult {
  /** 面料米数（= 下单页「数量」的预填值） */
  fabric_meters: number
  /** 总褶数 */
  pleat_count: number
  /** 每片褶数 */
  per_panel_pleats?: number
  /** 每折吃布（米）：单色 0.25 / 拼色·拼1次 0.65 / 拼色·拼2次 1.2 */
  per_fold: number
  /** **理论**褶倍（随档位） */
  fullness: number
  /** **实际**褶倍（= 用料 ÷ 窗宽） */
  fullness_actual?: number
  formula_used?: string
  /**
   * 可读公式串（**后端产出，前端只渲染**）—— 串首写明所用公式，issue #4527：
   * `韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米` /
   * `褶倍数公式：(5.5÷2)×2 → 每片 2.75×2=5.5米 ×2片 = 11.0米`
   */
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

/** 自动特征判定**入参**（issue #4976 包 2b）—— 判定移到服务端的读面入参 */
export interface AutoFeaturesParams {
  /** **净窗宽**（米）—— issue #5130：与 `oversize_width_threshold` 比（不看门幅、不看褶倍） */
  width: number
  /** **净窗高**（米）—— issue #5130：与 `oversize_height_threshold` 比 */
  height: number
  /**
   * **该商品/SKU 的门幅**（米）。⚠️ **没有缺省门幅**（issue #4877）：拿不到 ⇒ **不发该键**。
   *
   * 🔴 issue #5130 起**判定面已不读它**（判据改为与**企业阈值参数**比）—— 它只剩
   * 「几何矛盾」提示（`notices`）与回显用途。
   */
  fabric_width?: number
  /** 加工类型（`定高买宽` / `定宽买高`）；**只决定要不要推导「倒幅」**（issue #5130 已退役分流） */
  cutting_mode?: string
  /**
   * **该租户的算料配置**（issue #5036 包 2a）—— 判定要用**该租户**的两个企业阈值
   * （`oversize_width_threshold` / `oversize_height_threshold`），提示用 `hem_margin`；**不是前端常量副本**。
   * 缺省 ⇒ 引擎默认值（未配置租户口径一字不变）。
   */
  config?: CraftCalcConfig
}

/** 自动特征判定**结果**（issue #4976 包 2b）：判定 + 判定用的门幅回显 + 几何矛盾提示 */
export interface AutoFeaturesResult {
  /** 判定出的特征（`{name, source, reason}`）；**空数组 = 不判**（不是「没算」） */
  auto_features: Array<{ name: string; source: string; reason: string }>
  /**
   * 回显请求里的门幅（缺 ⇒ `null`）。
   *
   * ⚠️ **不是**「判定用的门幅」—— issue #5130 起判定面（超高/超宽）**不读门幅**，
   * 它只剩几何层（用量 / 加工类型 / 规则面）与「几何矛盾」提示的用途。
   */
  door_width: number | null
  /**
   * **商家可见提示**（issue #5036）—— `[{kind, reason}]`，键恒在（空数组 = 无提示）。
   *
   * 🔴 提示由**服务端**给（用户 2026-09-21 裁定「统一迁移到服务端；未来 agent 也需要」）：
   * 引擎读的是**该租户配置**的 `hem_margin` ⇒ 判定与提示**同源**。
   *
   * 🔴 **issue #5130 改判：只剩 `cutting-mode-conflict` 一条** —— 它说的是**几何层**
   * （成品高 + 卷边 vs 门幅 ⇒ 引擎实际按哪种算），仍然为真。
   * `missing-door-width` 与 `missing-fullness` **已退役**（它们的文案在新判据下是**假话**：
   * 「未维护门幅 ⇒ 超高/超宽都判不了」/「缺褶倍 ⇒ 未判超宽」）。
   */
  notices: Array<{
    kind: 'cutting-mode-conflict'
    reason: string
  }>
}

export const autoFeaturesApi = {
  /**
   * 自动特征判定（**不落库、不算用料**）—— issue #4976 包 2b，用户裁定 B「判定移到服务端」。
   *
   * ⚠️ 与 `craftCalcApi` **分开**是有意的：算料试算对**四爪钩 / 穿杆 / 平幔**没有口径
   * （那三类工艺不发试算请求），而自动特征是**每一行**都要判的 —— 挂在试算上会让那些行
   * **丢特征** ⇒ 加工费组合键少一项 ⇒ 匹配不到组合价。
   */
  preview: (params: AutoFeaturesParams) =>
    request.post<ApiResponse<AutoFeaturesResult>>('/api/admin/orders/auto-features', params),
}

/** 门幅规则**只读**请求（issue #5043 包 2b）—— 前端 `door-width-plan.ts` 的口径搬到服务端。 */
export interface DoorWidthPlanParams {
  /** 成品宽（米） */
  width: number
  /** 成品高（米）；缺 ⇒ 服务端返回 `undecidable: missing-size`（不猜朝向） */
  height?: number
  /** 候选门幅（米，来自该颜色的 SKU）；**先经 `parseDoorWidth` 归一**（服务端只收数字） */
  door_widths: number[]
  /** 加工类型（`定高买宽` / `定宽买高`）；缺 ⇒ 服务端**自动推导** */
  cutting_mode?: string
  /** **客服所选**门幅（米）；裁决用 */
  selected_door_width?: number
  /** 门幅**有效余量**（米） */
  allowance?: number
  open_count?: number
  mounting?: string
  fullness?: number
  craft?: string
  craft_tier?: string
  pleat_count?: number
  formula?: string
  has_pattern?: boolean
  pattern_repeat?: number
}

/**
 * 门幅规则**结果**（issue #5043 包 2b）—— 规则解 + 四态裁决。
 *
 * ⚠️ **规则解与幅数由引擎给**（`build_quote(..., fabric_widths=...)` → `resolve_fabric_plan`）——
 * 前端**不再本地算**（迁移前本地那份「恒按倍数法」的分子与引擎实测差 0.65 米）。
 */
export interface DoorWidthPlanResult {
  /** `single_panel`（单幅可做）/ `needs_splice`（需接高）/ `undecidable`（判不了） */
  state: 'single_panel' | 'needs_splice' | 'undecidable'
  /** `undecidable` 的原因：`no-door-width` / `missing-size` / `missing-cutting-mode`；其余 ⇒ `''` */
  code: string
  /** **实际据以求解**的加工类型（缺省入参 ⇒ 服务端自动推导的那一档） */
  effective_cutting_mode: string | null
  /** 选中的**标称**门幅（米） */
  door_width: number | null
  /** 定宽买高 ⇒ 分幅数；定高买宽 ⇒ `null`（**幅数无定义**，不发明数字） */
  panels: number | null
  splice: boolean
  /** 四态裁决：`optimal` / `suboptimal` / `infeasible` / `unknown` */
  verdict: 'optimal' | 'suboptimal' | 'infeasible' | 'unknown'
  /** 可执行建议（`suboptimal` / `infeasible` 时非空；其余 ⇒ `null`） */
  suggestion: string | null
  /** 规则解的可读依据（引擎给，前端不编） */
  reason: string
}

export const doorWidthPlanApi = {
  /**
   * 门幅规则（**只读**：不算钱、不落库）—— issue #5043 包 2b。
   *
   * ⚠️ 与 `craftCalcApi` **分开**是有意的：规则要在**发试算请求之前**用（靠它决定选哪个 SKU/门幅），
   * 而试算请求本身要带门幅 ⇒ 鸡生蛋；且 **四爪钩 / 穿杆 / 平幔** 不发试算请求
   * （用户 2026-09-21 裁定：这三类工艺**不影响用料和门幅**）⇒ 规则面不能挂在试算上。
   */
  preview: (params: DoorWidthPlanParams) =>
    request.post<ApiResponse<DoorWidthPlanResult>>('/api/admin/orders/door-width-plan', params),
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
// 入库单 API（V111，issue #5034）
// 端点与后端 InboundOrderController 一一对应：
//   GET    /api/admin/inbound-orders            列表（keyword/status）
//   POST   /api/admin/inbound-orders            建单（草稿，不动库存）
//   GET    /api/admin/inbound-orders/{id}       详情（id 可为 UUID/单号/前缀）
//   PATCH  /api/admin/inbound-orders/{id}       动作：post 过账 / cancel 作废
//   GET    /api/admin/inbound-orders/batches    批次查询（skuId/dyeLot/inboundNo/legacyBatchNo）
//   GET    /api/admin/inbound-orders/opening-template  期初建账模板（.xlsx）
//   POST   /api/admin/inbound-orders/opening-import    期初建账 Excel 批量导入（V118 / issue #5153）
export const inboundOrderApi = {
  list: (params?: InboundOrderListParams) =>
    request.get<ApiResponse<InboundOrderLine[]>>('/api/admin/inbound-orders', { params }),

  detail: (id: string) =>
    request.get<ApiResponse<InboundOrder>>(`/api/admin/inbound-orders/${id}`),

  create: (data: InboundOrderCreateParams) =>
    request.post<ApiResponse<InboundOrder>>('/api/admin/inbound-orders', data),

  // 过账：服务端自动生成批次号 + 加库存 + 落台账 + 按移动加权平均算成本（幂等闸：仅草稿可过账）
  post: (id: string) =>
    request.patch<ApiResponse<InboundOrder>>(`/api/admin/inbound-orders/${id}`, { action: 'post' }),

  // 作废：仅草稿可作废（已过账的库存已进台账，冲销须另开单据）
  cancel: (id: string, reason?: string) =>
    request.patch<ApiResponse<InboundOrder>>(`/api/admin/inbound-orders/${id}`, { action: 'cancel', reason }),

  batches: (params?: { skuId?: number; dyeLot?: string; inboundNo?: string; legacyBatchNo?: string }) =>
    request.get<ApiResponse<InboundBatch[]>>('/api/admin/inbound-orders/batches', { params }),

  // 期初建账模板（.xlsx）：第 1 表只有表头 + 第 2 表填写说明（**不放示例行** —— 原样上传会建出假账）
  openingTemplate: () =>
    request.get<Blob>('/api/admin/inbound-orders/opening-template', { responseType: 'blob' }),

  // 期初建账 Excel 批量导入（V118 / issue #5153）：**importRunId 必填**（幂等键，重跑不重复建账）
  openingImport: (file: File, importRunId: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('importRunId', importRunId)
    return request.post<ApiResponse<OpeningImportReport>>(
      '/api/admin/inbound-orders/opening-import',
      form,
    )
  },
}

/**
 * 批次账只读查询（V116 / issue #5145 阶段 1；后端 `StockBatchController`，权限复用 `product:list`）。
 *
 * 四个读面 + 一个派工候选面，**全是只读**：批次账的写方在库存变更的既有实现点
 * （加工单生成/作废驱动），不经过这些端点。
 */
export const batchStockApi = {
  // 批次余量（派生 = 入库量 − 已派工消耗）；onlyAvailable=true ⇒ 只回余量 > 0 的批次
  batches: (params: { productId?: string; skuId?: number; onlyAvailable?: boolean }) =>
    request.get<ApiResponse<BatchRemaining[]>>('/api/admin/batch-stock/batches', { params }),

  // 剩余量分布（恒四档：≤0.2 / 0.2~0.5 / 0.5~1 / >1 米；空档回 0）
  distribution: (params: { productId?: string }) =>
    request.get<ApiResponse<BatchDistribution>>('/api/admin/batch-stock/distribution', { params }),

  // 对账：Σ批次余量 vs product_skus.stock（差额可读出、可解释；reconciled=false ⇒ 须排查）
  reconcile: (params: { productId?: string; skuId?: number }) =>
    request.get<ApiResponse<BatchReconcile>>('/api/admin/batch-stock/reconcile', { params }),

  // 派工候选 + 建议值（meters = 本行米数，用于算 enough 与建议值）
  candidates: (params: { productId?: string; skuId?: number; meters?: number }) =>
    request.get<ApiResponse<BatchCandidates>>('/api/admin/batch-stock/candidates', { params }),
}

export const processingOrderApi = {
  // 批量生成加工单（仅已确认且含加工项订单；联动订单进入 producing）
  //
  // V116 / issue #5145 阶段 1：可带 `batches` 逐面料行指定批次（与生成同事务扣批次库存）。
  // **缺省 = 不指派**（请求体只有 `orderIds`，与今天逐字相同）—— 故空数组也要落成「不带该键」，
  // 不能落成 `batches: []`（虽然后端同义，但「不指派 ⇒ 与今天逐字相同」要能在请求体上核验）。
  generate: (orderIds: string[], batches?: ProcessingOrderGenerateBatch[]) =>
    request.post<ApiResponse<ProcessingOrderGenerateResult[]>>(
      '/api/admin/processing-orders/generate',
      batches && batches.length > 0 ? { orderIds, batches } : { orderIds },
    ),

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

  // 「卡在哪」卡点报表（切片 ③，issue #4776；只读；设计 §6）：
  // **A 模式只查「没开工」那一种**（裁定②-3）；等待时长取**上道 done_at**（不用 updated_at）。
  // 传 processingOrderId ⇒ 只看该加工单；缺省 = 本租户全部活跃加工单。
  getStuckPoints: (processingOrderId?: string) =>
    request.get<ApiResponse<StuckPointsReport>>(
      processingOrderId
        ? `/api/admin/production/stuck-points?processing_order_id=${encodeURIComponent(processingOrderId)}`
        : '/api/admin/production/stuck-points',
    ),

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
  // issue #4614 范围补口：body 可带 `positions` ⇒ **存量孤儿接入**（只补缺失的矩阵行，
  // 不删已有行、不覆盖已定价的格），响应附 `created_positions` / `skipped_positions` 如实报数。
  updateOperation: (id: string | number, data: ProductionOperationUpdateParams) =>
    request.put<ApiResponse<CatalogOperation & OperationPositionsAttachResult>>(
      `/api/admin/production/operations/${id}`,
      data,
    ),

  // 工序**软删**（issue #4588；契约 #4587 ③）：`deleted=1`（不物理删 —— 历史报工仍引用它）。
  // 三条护栏**一次报全**（422 + `error.details[].message`：被活跃主线 / 活跃规则 / 矩阵格引用）；
  // 已软删 ⇒ 200 幂等 no-op。权限 processing:manage。
  // ⚠️ `opts.detachPositions`（issue #4665）= 一键「设为不做并删除」，走**独立端点**
  // `DELETE /operations/{id}/detach-and-delete`：后端**同一事务**里先把受影响的矩阵格设为不做
  // （价清空）再软删工序 + **级联软删矩阵行**（删干净）⇒ 商家不用手工两步、也没有「第一步成功
  // 第二步失败」的中间态。护栏①主线 / ②规则**照样拦**（主线涉及车间顺序，必须人工确认）。
  deleteOperation: (id: string | number, opts?: { detachPositions?: boolean }) =>
    request.delete<ApiResponse<{ id: string; deleted: boolean; detached_positions?: number; deleted_positions?: number }>>(
      opts?.detachPositions
        ? `/api/admin/production/operations/${id}/detach-and-delete`
        : `/api/admin/production/operations/${id}`,
    ),

  // ── 新路线模型只读面（issue #4500 = 母单 #4423 的 P2c；消费方 = P3 #4433）──
  // 两个端点**只读**（写面留 v1b）；顺序由服务端定（Java 侧显式比较器，环境无关）⇒ 前端不得重排。
  // ① 工序单价表（issue #4886 起**一道工序一行、一个单价**；issue #4937/#4951 去部位化彻底版起
  // `applicable` 退场 —— 读面该键恒 true、写面收到即 422 ⇒ 前端不持有该字段）。
  // issue #4588（契约 #4587 ①）：每行多出 `id`（写面寻址）+ 6 个变体元数据键（逻辑名↔变体名映射）。
  getOperationPositions: () =>
    request.get<ApiResponse<OperationPosition[]>>('/api/admin/production/operation-positions'),
  // ①-0 **两层分区**读面（issue #4677 = 设计 §4.1/§4.2；后端 #4676 已合并 `6908122bb`）：
  // 按**既有** `scope` 分区 —— `scope='set'` ⇒ `delivery`（打包发货：打包 / 外帘打卷 / 外帘装袋 /
  // 外帘发货，**一列价**）；其余（`'position'` 或 `null`）⇒ `operations`（工序层，一道工序一行）。
  // ⚠️ 「一列价」是**服务端聚合的显式规则**（不静默取第一个、不回落工序库行价）⇒ 前端**不重算**：
  // 在 TS 侧再写一份聚合 = 第二份会漂的口径。
  getOperationLayers: () =>
    request.get<ApiResponse<OperationLayers>>('/api/admin/production/operation-layers'),
  // ①-b 工序单价**写面**（issue #4588；契约 #4587 ②；权限 processing:manage）：
  // **部分更新** ⇒ body 只带变了的键（#4937/O1 起**只收** `{unit_price}` —— `applicable` 已退场，
  // 收到它一律 **422**「部位适用性已退场，不再受理该字段」，**拒绝**而非静默忽略）；
  // `unit_price=null` = 改回**未定价**（≠ 0 元）；校验失败 ⇒ 422 + `error.details[].message`（一次报全）。
  // 响应与 ① 的单行同构。
  updateOperationPosition: (id: string, data: OperationPositionUpdateParams) =>
    request.put<ApiResponse<OperationPosition>>(`/api/admin/production/operation-positions/${id}`, data),
  // ② 统一规则区：26 条（工艺 10 + 选项 16）—— 只含路线编排档（insert/remove），不含计件系数档
  getRouteRules: () =>
    request.get<ApiResponse<RouteRule[]>>('/api/admin/production/route-rules'),
  // ②-a 规则创建弹窗的**触发值取值域**（issue #4616；权限 processing:manage）：
  // `{crafts:[…], processing_items:[…], positions:[…]}` —— 活跃工艺词表 + 活跃加工项目录
  // ＋ **部位闭词表**（#4962 新增键：`trigger_kind='position'` 的取值域，基线三部位 ∪ `布料`）。
  // 触发值必须从对应词表取（手输一个词表里没有的名字 = 建一条永远不命中的规则）。
  // 特殊选项名不在此列（可新建，没有第二份词表）。
  getRouteRuleOptions: () =>
    request.get<ApiResponse<RouteRuleTriggerOptions>>('/api/admin/production/route-rule-options'),
  // ②-b 条件工序规则**软删**（issue #4588；契约 #4587 ④；权限 processing:manage）：
  // 无硬护栏（规则只影响「插/删一道工序」，删错了重加即可）；不存在/跨租户/已软删 ⇒ 404。
  deleteRouteRule: (id: string | number) =>
    request.delete<ApiResponse<{ id: number; deleted: boolean }>>(`/api/admin/production/route-rules/${id}`),
  // ③ 特殊选项**对客单价**写面（issue #4567；权限 processing:manage）：
  // 只写 `production_route_rules.customer_unit_price`（元/套）—— 与工序库的**计件**单价两套账不互读。
  // `null` = 显式改回**未定价**（≠ 0 元）；非 option 行 / 负数 / 三位小数 ⇒ 422 逐条理由。
  updateRuleCustomerUnitPrice: (id: number | string, data: RouteRuleCustomerPriceParams) =>
    request.put<ApiResponse<RouteRule>>(`/api/admin/production/route-rules/${id}/customer-unit-price`, data),
  // ④ 新增**特殊选项**（issue #4570；权限 processing:manage）：
  // body = `{trigger_value, operation, after_operation?, priority?, customer_unit_price?}` ——
  // `operation` 是**逻辑工序名**（与 `production_route_rules.operation` 逐字一致），
  // 与 `createOperation` 的**计件**单价是两本账（不互换算、不混字段）。
  // 失败 ⇒ `error.details[].message` 逐条理由（页面就地展示，**不吞成一句**）。
  createOptionRule: (data: RouteRuleCreateParams) =>
    request.post<ApiResponse<unknown>>('/api/admin/production/route-rules', data),

  // ── 工艺路线商家可配（契约所有者 = 后端 #4459；权限 processing:manage）──
  // 部分更新（只写出现的字段）：`{name?, is_default?, mainline?, positions?, status?}`
  // ⚠️ 改名只给 `name`（不给 mainline 就不动序列）；`is_default:false` 服务端 422 ⇒ 前端不得发。
  // （服务端护栏：空主线 / 工序不存在 / 重复 / 缺必完工序 / 重名 409 / 删默认 / 删最后一条
  //   —— 失败响应体带逐条理由，页面照单展示）
  updateRouting: (id: number, data: RoutingUpdateParams) =>
    request.put<ApiResponse<Routing>>(`/api/admin/production/routings/${id}`, data),

  // 新建路线（具名；初版主线可空，随后在编辑区排；positions 缺省 = 三种帘种全适用）
  createRouting: (data: RoutingCreateParams) =>
    request.post<ApiResponse<Routing>>('/api/admin/production/routings', data),

  // 删路线（**软删**；服务端护栏：删默认 ⇒ 422 / 删最后一条 ⇒ 422）
  deleteRouting: (id: number) =>
    request.delete<ApiResponse<Routing>>(`/api/admin/production/routings/${id}`),

  // 新增工序（建新路线时必须有工序可选）
  // issue #4614：body 可带 `positions`（适用部位）⇒ 同一事务建出矩阵行，新工序**建完即可见**；
  // ⚠️ issue #4886：「工艺配置」页（本批次）**已不再传 `positions`**（配置面不再有部位概念）——
  // 新工序如何进价目表由配套后端负责（字段保留给其它调用方）。
  // 响应附 `created_positions` / `skipped_positions`（如实报数，前端 toast 照报，不自行推算）。
  createOperation: (data: RouteOperationCreateParams) =>
    request.post<ApiResponse<RouteOperationCreateResult>>('/api/admin/production/operations', data),

  // 信号映射**只读**（库数据：派生读库而非读硬编码常量表）——写面已随 #4452 退役，
  // 存量单仍需读面兜底 ⇒ 只留 `getRouteSignals`（#4534 已删三个死写方法）。
  getRouteSignals: () =>
    request.get<ApiResponse<RouteSignalsResponse>>('/api/admin/production/route-signals'),

  // ── 算料公式**租户级配置**（issue #4528 = 包 E；契约所有者 = 后端 #4528，权限 processing:manage）──
  // 缺配置行 ⇒ 后端返回**引擎默认值** + `source='default'`（前端不抄第二份默认值）。
  // PUT = **全量替换**：缺键 / 未知键 / 非法值 ⇒ 422 + `error.details[].message` 逐条理由
  //（**不得静默回退默认值** —— 静默 = 商家以为改了、系统按默认算 ⇒ 算错钱且无人知道）。
  /**
   * 读算料配置。
   *
   * @param withDefaults 是否**额外**附**引擎默认值**（`defaults` + `defaults_source`，
   *   §22 P3 逐键「我改过没有」，issue #5131 增量 2）。
   *   🔴 **默认 false** —— 既有调用方（算料配置页）响应**逐字节不变**，也**不新增**
   *   「读配置要依赖引擎可达性」这条依赖；只有「参数总览」要它。
   */
  getCraftCalcConfig: (withDefaults = false) =>
    request.get<ApiResponse<CraftCalcConfigResponse>>(
      '/api/admin/production/craft-calc-config' + (withDefaults ? '?with_defaults=true' : '')
    ),
  updateCraftCalcConfig: (data: CraftCalcConfig) =>
    request.put<ApiResponse<CraftCalcConfigResponse>>('/api/admin/production/craft-calc-config', data),

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

  // 按当前价重算未定价工序实例（issue #4709 C）：只补 `unit_price IS NULL` 的实例行，
  // 已有价（含显式定价 0 元）一律不动、报工进度不清零；返回 batch_id 供回滚。
  // 注意：方法级 processing:manage（写面），与同类只读端点的类级 order:list 不同口径。
  repriceUnpricedInstances: (orderId: string) =>
    request.post<ApiResponse<UnpricedRepricingResult>>(
      `/api/admin/production/orders/${orderId}/repricing`,
      {},
    ),

  // 回滚一次补价动作（只还原本批补上的行；商家自己定的价不在账本里 ⇒ 永不被回滚）
  rollbackRepricing: (batchId: string) =>
    request.post<ApiResponse<{ batch_id?: string; reverted?: number; skipped?: number; hint?: string }>>(
      `/api/admin/production/repricing/${batchId}/rollback`,
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

  /**
   * 本租户收款二维码（微信/支付宝各一张；issue #4965 报价单页脚「扫码支付」用）。
   * 后端 `SettingsController.getPaymentQrcodes` 按 `payment_type` 分组返回；
   * 无码 ⇒ 空 map（调用方据此**整块不渲染**，不画假码）。
   */
  getPaymentQrcodes: () =>
    request.get<ApiResponse<PaymentQrcodeMap>>('/api/admin/settings/payment-qrcodes'),
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
  batchStock: batchStockApi,
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
