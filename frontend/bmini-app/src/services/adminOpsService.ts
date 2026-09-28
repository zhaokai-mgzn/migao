/**
 * 管理面（手机端）服务层 —— 排产/派单 · 入库过账 · 售后处理 · 计件工资报表（issue #5654）
 *
 * 🔴 **本文件只做三件事**：拼请求、判「无权限 / 失败 / 有数据」三态、把服务端字段原样带给页面。
 * 它**不做**（本仓库明令的口径红线）：
 * - **不重算**任何米数/金额（`savedMeters` / `poolingGainMeters` / 计件 `total` 一律服务端值）；
 * - **不重排**服务端排好序的列表（池的 `urgentLines` / `groups[].lines` 顺序即口径）；
 * - **不造第二份聚合**（计件报表与 PC 端读**同一个** `GET /api/admin/production/piecework/summary`）。
 *
 * 🔴 三态**必须可区分**（issue 验收：无权限不许静默空白/转圈）：
 * `forbidden`（403 ⇒ 文案「无「XX」查看权限（需要权限码 …）」）/ `error`（失败，带服务端文案）
 * / `ok`（含空数组 —— 「没有数据」与「看不到」是两件事，把它们混起来就是把「看不到」说成「没有」）。
 *
 * 端点全部复用既有（本单**不新增后端端点**，也不改任何返回形状）；权限码真值见
 * `src/utils/adminPermission.ts` 的台账（与后端注解逐值比对）。
 */
import { get, patch, post, put } from '../utils/request'
import { API_BASE_URL } from '../utils/constants'
import { missingPermissionText, type AdminSurfaceKey } from '../utils/adminPermission'
import type { ApiResponse } from '../types'

// ══════════════════════════════════════════════════════════════════════════
// 三态结果（「无权限 / 失败 / 有数据」互不混淆）
// ══════════════════════════════════════════════════════════════════════════

export type AdminOpsResult<T> =
  | { status: 'ok'; data: T }
  | { status: 'forbidden'; message: string }
  | { status: 'error'; message: string }

/** 服务端文案优先（admin-api 的业务失败把话写在 `error.message` / `message` 里） */
function serverMessage(error: any, fallback: string): string {
  return (
    error?.data?.error?.message ||
    error?.data?.message ||
    error?.message ||
    fallback
  )
}

/**
 * 失败分类：**403 是有身份无权限**（⇒ 说清缺哪个码），其余是业务/网络失败（⇒ 说服务端那句）。
 * 404 / 422 走 `error` 分支并原样透出服务端文案（不吞、不泛化）。
 */
function classify<T>(
  error: any,
  key: AdminSurfaceKey,
  kind: 'read' | 'write',
  fallback: string,
): AdminOpsResult<T> {
  if (error?.statusCode === 403) {
    return { status: 'forbidden', message: missingPermissionText(key, kind) }
  }
  return { status: 'error', message: serverMessage(error, fallback) }
}

/** 拉一次并归一化（`success=false` / 空 data 都算失败 —— 不把「服务端说失败」渲染成空列表） */
async function run<T>(
  fn: () => Promise<ApiResponse<T>>,
  key: AdminSurfaceKey,
  kind: 'read' | 'write',
  fallback: string,
): Promise<AdminOpsResult<T>> {
  try {
    const res = await fn()
    if (!res || res.success !== true || res.data === undefined || res.data === null) {
      return { status: 'error', message: res?.error?.message || fallback }
    }
    return { status: 'ok', data: res.data }
  } catch (error: any) {
    return classify<T>(error, key, kind, fallback)
  }
}

/** 无 data 的写动作（如 `PUT .../status` 回 `ApiResponse<Void>`）：成功只判 `success` */
async function runVoid(
  fn: () => Promise<ApiResponse<void>>,
  key: AdminSurfaceKey,
  kind: 'read' | 'write',
  fallback: string,
): Promise<AdminOpsResult<true>> {
  try {
    const res = await fn()
    if (!res || res.success !== true) {
      return { status: 'error', message: res?.error?.message || fallback }
    }
    return { status: 'ok', data: true }
  } catch (error: any) {
    return classify<true>(error, key, kind, fallback)
  }
}

// ══════════════════════════════════════════════════════════════════════════
// 会话面：服务端下发的权限集合（端侧**不发明**码，只读这一份）
// ══════════════════════════════════════════════════════════════════════════

export interface MeResponse {
  permissions?: string[] | null
}

/**
 * 读当前登录员工的权限集合（`GET /api/auth/me`）。
 *
 * 拿不到（网络/未登录/服务端失败）⇒ `null` = **未知** ⇒ 调用方按 fail-open 处理
 * （入口照显、把判定交给服务端 403 + 显式文案）。**不得**把「未知」当「无权」。
 */
export async function fetchMyPermissions(): Promise<string[] | null> {
  try {
    const res = await get<ApiResponse<MeResponse>>('/api/auth/me', { baseURL: API_BASE_URL })
    const permissions = res?.data?.permissions
    return Array.isArray(permissions) ? permissions : null
  } catch {
    return null
  }
}

// ══════════════════════════════════════════════════════════════════════════
// ① 排产 / 派单（`ProductionPoolController`）
// ══════════════════════════════════════════════════════════════════════════

/** 池内一行 = 订单 × 物料（字段名逐字取 `ProductionPoolViews.PoolLine`） */
export interface PoolLine {
  orderId: string
  orderNo: string
  itemId: string
  productId: string
  productName: string
  skuCode: string
  /** 公式口径需求米数（服务端 BigDecimal）—— **不是**排料后的应领米数 */
  requiredMeters: number
  waitingSince: string
  waitHours: number
  /** 超过滞留上限（必须可行动，不得静默压单） */
  overdue: boolean
  /** 加急（这些行**不进池**，只在 `urgentLines` 插队区） */
  isUrgent: boolean
  requiredDeliveryDate?: string | null
  deliveryDaysLeft?: number | null
}

export interface PoolGroup {
  materialKey: string
  productId: string
  skuCode: string
  orderCount: number
  requiredMeters: number
  lines: PoolLine[]
}

export interface PoolWarning {
  orderId: string
  orderNo: string
  waitHours: number
  message: string
}

export interface PoolBoard {
  maxWaitHours: number
  /** 池化开关当前是否开启（池**看得见** ≠ **已开启**，两者分开报） */
  poolingEnabled: boolean
  orderCount: number
  lineCount: number
  overdueCount: number
  urgentCount: number
  warnings?: PoolWarning[]
  urgentLines?: PoolLine[]
  groups?: PoolGroup[]
}

/** 成批预览（五个米数全是服务端聚合，页面只渲染 —— 前端相减 = 第二份会漂的口径） */
export interface PoolPreview {
  orderCount: number
  assignmentRule: string
  formulaMeters: number
  pooledPlannedMeters: number
  /** = formulaMeters − pooledPlannedMeters；与派单后落账的 Σ saved_meters 逐值相等 */
  savedMeters: number
  perOrderPlannedMeters: number
  poolingGainMeters: number
}

/** 派单逐单结果（`orderRef` = **入参原样回显**，不是 orderId/orderNo） */
export interface PoolDispatchResult {
  orderRef: string
  processingOrderNo?: string | null
  success: boolean
  message?: string | null
  code?: string | null
  suggestion?: string | null
}

/** 派单/预览**同体**（契约四个键；`pooled: true` 才跨订单成组排料） */
export interface PoolDispatchBody {
  orderIds: string[]
  batches: unknown[]
  assignmentRule: string | null
  pooled: boolean
}

/** 池化派单请求体（唯一拼装处：页面不许自己拼，否则两个端点会出现两种形态） */
export function buildPoolDispatchBody(orderIds: string[], pooled: boolean): PoolDispatchBody {
  return { orderIds, batches: [], assignmentRule: null, pooled }
}

export async function getProductionPool(
  maxWaitHours?: number,
): Promise<AdminOpsResult<PoolBoard>> {
  return run(
    () =>
      get<ApiResponse<PoolBoard>>('/api/admin/production/pool', {
        baseURL: API_BASE_URL,
        params: maxWaitHours != null ? { maxWaitHours } : undefined,
      }),
    'pool',
    'read',
    '待派池加载失败，请下拉重试',
  )
}

/** 成批预览（**只读**，服务端不落台账；与派单同一条求解路径） */
export async function previewPoolDispatch(
  orderIds: string[],
): Promise<AdminOpsResult<PoolPreview>> {
  return run(
    () =>
      post<ApiResponse<PoolPreview>>(
        '/api/admin/production/pool/preview',
        buildPoolDispatchBody(orderIds, true),
        { baseURL: API_BASE_URL },
      ),
    'pool',
    'write',
    '预览失败，请重试',
  )
}

/**
 * 派单（成批 = `pooled: true`；**加急插队 = 同一个端点 + 单订单 + `pooled: false`**）。
 * 整批拒绝语义由服务端保证（加急单混进成批 ⇒ 422 整批拒绝，不静默少派）。
 */
export async function dispatchPoolOrders(
  orderIds: string[],
  pooled = true,
): Promise<AdminOpsResult<PoolDispatchResult[]>> {
  return run(
    () =>
      post<ApiResponse<PoolDispatchResult[]>>(
        '/api/admin/production/pool/dispatch',
        buildPoolDispatchBody(orderIds, pooled),
        { baseURL: API_BASE_URL },
      ),
    'pool',
    'write',
    '派单失败，请重试',
  )
}

// ══════════════════════════════════════════════════════════════════════════
// ② 入库过账（`InboundOrderController`）
// ══════════════════════════════════════════════════════════════════════════

/** 入库单列表行（含明细聚合；字段名逐字取 `InboundOrderLine`） */
export interface InboundOrderLine {
  id: string
  inboundNo: string
  supplier?: string | null
  supplierDocNo?: string | null
  warehouse?: string | null
  inboundDate?: string | null
  /** draft / posted / cancelled */
  status: string
  totalAmount?: number | null
  remark?: string | null
  postedAt?: string | null
  postedBy?: string | null
  createdAt?: string | null
  itemCount?: number | null
  totalQuantity?: number | null
}

/** 明细行（**一行 = 一个批次**） */
export interface InboundOrderItem {
  id?: number | null
  skuId?: number | null
  productId?: string | null
  skuCode?: string | null
  colorName?: string | null
  doorWidth?: string | null
  quantity?: number | null
  unitCost?: number | null
  amount?: number | null
  /** 批次号（**过账后才有**；草稿为 null） */
  batchNo?: string | null
  dyeLot?: string | null
  legacyBatchNo?: string | null
  rollLengthM?: number | null
  remark?: string | null
}

export interface InboundOrder {
  id: string
  inboundNo: string
  supplier?: string | null
  supplierDocNo?: string | null
  warehouse?: string | null
  inboundDate?: string | null
  status: string
  totalAmount?: number | null
  source?: string | null
  importRunId?: string | null
  remark?: string | null
  postedAt?: string | null
  postedBy?: string | null
  cancelledAt?: string | null
  cancelledBy?: string | null
  cancelledReason?: string | null
  createdBy?: string | null
  createdAt?: string | null
  items?: InboundOrderItem[]
}

export async function listInboundOrders(params?: {
  keyword?: string
  status?: string
}): Promise<AdminOpsResult<InboundOrderLine[]>> {
  const query: Record<string, string> = {}
  if (params?.keyword) query.keyword = params.keyword
  if (params?.status) query.status = params.status
  return run(
    () =>
      get<ApiResponse<InboundOrderLine[]>>('/api/admin/inbound-orders', {
        baseURL: API_BASE_URL,
        params: Object.keys(query).length ? query : undefined,
      }),
    'inbound',
    'read',
    '入库单加载失败，请重试',
  )
}

/** 详情（id 可为 UUID / 入库单号 / 单号前缀 —— 服务端口径，前端不解析） */
export async function getInboundOrder(id: string): Promise<AdminOpsResult<InboundOrder>> {
  return run(
    () =>
      get<ApiResponse<InboundOrder>>(`/api/admin/inbound-orders/${encodeURIComponent(id)}`, {
        baseURL: API_BASE_URL,
      }),
    'inbound',
    'read',
    '入库单详情加载失败，请重试',
  )
}

/**
 * **过账**（唯一写动作）：服务端在**同一事务**里生成批次号 + 加库存 + 落台账 + 按移动加权平均算成本。
 * 幂等闸在服务端（仅草稿可过账）⇒ 手机端不另造状态判断（页面只按 `status === 'draft'` 决定要不要出按钮）。
 */
export async function postInboundOrder(id: string): Promise<AdminOpsResult<InboundOrder>> {
  return run(
    () =>
      patch<ApiResponse<InboundOrder>>(
        `/api/admin/inbound-orders/${encodeURIComponent(id)}`,
        { action: 'post' },
        { baseURL: API_BASE_URL },
      ),
    'inbound',
    'write',
    '过账失败，请重试',
  )
}

// ══════════════════════════════════════════════════════════════════════════
// ③ 售后处理（`AfterSalesController`）
// ══════════════════════════════════════════════════════════════════════════

/** 工单（列表项与详情同形；详情多 `statusHistory`） */
export interface AfterSalesTicket {
  id: string
  ticketNo?: string | null
  orderId?: string | null
  orderNo?: string | null
  customerName?: string | null
  customerPhone?: string | null
  ticketType?: string | null
  status: string
  description?: string | null
  images?: string[] | null
  source?: string | null
  priority?: string | null
  handlerName?: string | null
  refundAmount?: number | null
  /** 内部备注（详情才有；**不外发客户**，页面上标注「内部」） */
  internalNotes?: string | null
  deadline?: string | null
  closedAt?: string | null
  closeReason?: string | null
  createdAt?: string | null
  updatedAt?: string | null
  statusHistory?: AfterSalesStatusHistoryItem[] | null
}

export interface AfterSalesStatusHistoryItem {
  status?: string | null
  time?: string | null
  operator?: string | null
  remark?: string | null
}

export interface AfterSalesPage {
  total?: number | null
  page?: number | null
  size?: number | null
  items?: AfterSalesTicket[] | null
}

export async function listAfterSales(params?: {
  page?: number
  size?: number
  status?: string
}): Promise<AdminOpsResult<AfterSalesPage>> {
  const query: Record<string, string | number> = { page: params?.page ?? 1, size: params?.size ?? 20 }
  if (params?.status) query.status = params.status
  return run(
    () =>
      get<ApiResponse<AfterSalesPage>>('/api/admin/after-sales', {
        baseURL: API_BASE_URL,
        params: query,
      }),
    'after-sales',
    'read',
    '售后工单加载失败，请重试',
  )
}

export async function getAfterSalesTicket(
  id: string,
): Promise<AdminOpsResult<AfterSalesTicket>> {
  return run(
    () =>
      get<ApiResponse<AfterSalesTicket>>(`/api/admin/after-sales/${encodeURIComponent(id)}`, {
        baseURL: API_BASE_URL,
      }),
    'after-sales',
    'read',
    '工单详情加载失败，请重试',
  )
}

/**
 * 改状态（**写**动作，服务端另有状态机校验：非法流转 ⇒ 422 + 中文文案，原样透出）。
 * 目标状态由页面按 `src/utils/afterSalesFlow.ts` 的镜像状态机给出（与后端逐值比对）。
 */
export async function updateAfterSalesStatus(
  id: string,
  status: string,
  remark?: string,
): Promise<AdminOpsResult<true>> {
  const body: Record<string, string> = { status }
  if (remark) body.remark = remark
  return runVoid(
    () =>
      put<ApiResponse<void>>(
        `/api/admin/after-sales/${encodeURIComponent(id)}/status`,
        body,
        { baseURL: API_BASE_URL },
      ),
    'after-sales',
    'write',
    '工单处理失败，请重试',
  )
}

// ══════════════════════════════════════════════════════════════════════════
// ④ 计件工资报表（`ProductionController#pieceworkSummary`）
// ══════════════════════════════════════════════════════════════════════════

export interface PieceworkWorkerAmount {
  worker_name: string
  amount: number
  qty: number
}

export interface PieceworkOperationAmount {
  /** 工人端快照名（变体名）—— 渲染走 `operationDisplayName`（#4621/#4630），不直接印这个键 */
  operation: string
  logical_name?: string | null
  position?: string | null
  amount: number
  qty: number
}

export interface PieceworkUnpricedRow {
  operation: string
  logical_name?: string | null
  position?: string | null
  qty: number
}

/** 未定价块（V90 / #4696）：未定价报工**不进 total**，但必须显式列出来（不折 0、不隐藏） */
export interface PieceworkUnpriced {
  qty: number
  operations: PieceworkUnpricedRow[]
  hint?: string
}

/** `GET /api/admin/production/piecework/summary?period=YYYY-MM[&worker_name=]`（issue #4205） */
export interface PieceworkReport {
  period: string
  /** 服务端聚合总额（元）；**前端不得重算**（Σ per_worker 是第二份口径） */
  total: number
  per_worker: PieceworkWorkerAmount[]
  per_operation: PieceworkOperationAmount[]
  per_position?: { position_name?: string; amount: number; qty: number }[]
  per_set?: { set_no?: string; amount: number; qty: number }[]
  unpriced?: PieceworkUnpriced
}

export async function getPieceworkReport(params: {
  period: string
  workerName?: string
}): Promise<AdminOpsResult<PieceworkReport>> {
  const query: Record<string, string> = { period: params.period }
  if (params.workerName) query.worker_name = params.workerName
  return run(
    () =>
      get<ApiResponse<PieceworkReport>>('/api/admin/production/piecework/summary', {
        baseURL: API_BASE_URL,
        params: query,
      }),
    'piecework',
    'read',
    '计件报表加载失败，请重试',
  )
}

// ══════════════════════════════════════════════════════════════════════════
// 展示助手（**只做格式化，不算业务数**）
// ══════════════════════════════════════════════════════════════════════════

/** 期间 YYYY-MM（手机端只需「本月 / 上月」两个入口，不引入日期 Picker 的平台差异） */
export function periodOf(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
}

/** 上月期间（跨年正确：1 月 → 上一年 12 月） */
export function previousPeriodOf(date: Date): string {
  const prev = new Date(date.getFullYear(), date.getMonth() - 1, 1)
  return periodOf(prev)
}

/** 金额（**元**，`money()` 两位小数）—— 服务端值只做展示取整，不做任何换算 */
export function formatYuanAmount(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || !Number.isFinite(Number(amount))) return '-'
  return `¥${Number(amount).toFixed(2)}`
}

/** 米数（服务端 JSON number，只做展示取整） */
export function formatMeters(meters: number | null | undefined, digits = 2): string {
  if (meters === null || meters === undefined || !Number.isFinite(Number(meters))) return '-'
  return Number(meters).toFixed(digits)
}

/** 等待时长（入参 = 服务端 `waitHours`，**不重算**） */
export function formatWaitHours(waitHours: number | null | undefined): string {
  if (waitHours === null || waitHours === undefined || !Number.isFinite(Number(waitHours))) return '-'
  const hours = Number(waitHours)
  if (hours < 24) return `${Math.round(hours * 10) / 10} 小时`
  const days = Math.floor(hours / 24)
  const rest = Math.round(hours - days * 24)
  return rest > 0 ? `${days} 天 ${rest} 小时` : `${days} 天`
}

/** 入库单状态文案（服务端枚举 draft/posted/cancelled，未登记原样回显） */
export const INBOUND_STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  posted: '已过账',
  cancelled: '已作废',
}

export function inboundStatusLabel(status: string | null | undefined): string {
  if (!status) return ''
  return INBOUND_STATUS_LABELS[status] ?? status
}

export default {
  fetchMyPermissions,
  getProductionPool,
  previewPoolDispatch,
  dispatchPoolOrders,
  listInboundOrders,
  getInboundOrder,
  postInboundOrder,
  listAfterSales,
  getAfterSalesTicket,
  updateAfterSalesStatus,
  getPieceworkReport,
}
