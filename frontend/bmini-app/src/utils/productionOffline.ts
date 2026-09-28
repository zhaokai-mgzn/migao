/**
 * 工人端报工弱网降级（issue #4206；真值源 `docs/curtain-production-rules.md` §5
 * 「【默】弱网降级：扫码页缓存待做清单，离线报工补传」）
 *
 * 只做两件事，全部用小程序原生 storage（不引新依赖、不建本地队列库 —— 平台差异代价远大于收益）：
 *   ① **待做清单缓存**：`loadOrder` 成功即落盘；断网时命中缓存仍能出待做清单
 *      （调用方必须**显式标注离线**，不得把缓存冒充服务端真值）；
 *   ② **离线报工队列**：**传输层**失败（无 HTTP 状态码）的报工入队，联网后自动补传。
 *
 * ## 幂等键语义（最关键的一处，错了就会重复计件）
 * 入队时把**本次动作的** `requestId` 一起持久化，补传**复用同一个键** —— 服务端
 * `ClientRequestIdService` 按 `(tenant_id, client_request_id)` 去重，同键重放只回放
 * 首次结果、不再执行。若补传时用 `newReportRequestId()` 重新生成键，同一次报工会被
 * 服务端当成两次「首执」（`done_qty` 翻倍、计件虚高）——这正是本模块要消灭的形态。
 *
 * ## 凭证语义（issue #5647 G10，与幂等键同等重要）
 * 唯一写入口是 `scan/complete`，它按**码**定位「哪一套、哪个部位」⇒ 入队时连 `token`
 * 一起持久化（`sendQty` 记住在线时到底传没传数量）。补传若换成「URL 定工序」的老路，
 * 等于把防呆④⑤ / 一次事务 / `done_at` 整条丢掉。
 *
 * ## 为什么业务拒绝不入队
 * 有 HTTP 状态码的失败（422 数量超上限 / 404 非本部位 / 409 同键在飞）是服务端**已经答复**：
 * 失败路径上服务端会 `discard` 释放该键 ⇒ 换个时机重发会**真的再执行一次**（重复报工），
 * 且这类拒绝重试不会有别的结果。故只对「无状态码的传输层失败」降级。
 */
import Taro from '@tarojs/taro'
import { completeByScan } from '../services/productionService'
import type {
  OrderOperations,
  ProductionResponse,
  ReportPayload,
  ReportResult,
} from '../services/productionService'

/** storage 键（前缀区分命名空间，便于运维一眼看出是报工降级数据） */
const ORDER_CACHE_PREFIX = 'production:order-cache:'
const WORK_LOG_PREFIX = 'production:work-logs:'
const PENDING_KEY = 'production:pending-reports'

/** 本机保留的报工明细条数上限（storage 有容量上限，别让长驻单据无限增长） */
export const MAX_WORK_LOGS = 50

/** 待补传的报工（一条 = 一次用户动作；`requestId` 为该动作的幂等键） */
export interface PendingReport {
  /** 幂等键：本次**用户动作**一个键，补传必须复用（服务端据此去重） */
  requestId: string
  /**
   * 报工凭证 = 扫码 token（issue #5647 G10）：唯一写入口 `scan/complete` 靠**码**定位
   * 「哪一套、哪个部位」⇒ 补传必须原样带上（防呆④⑤ / 一次事务 / `done_at` 都挂在它上面）。
   * 空串 = 旧版本（URL 定工序那条路）入队的条目 ⇒ 补传时显式出队并回报原因。
   */
  token: string
  orderId: string
  operationId: string
  operationName: string
  unit: string
  /** 本机展示用（数量 / 合格数量 / 工种）；**是否随补传发出**见 `sendQty` */
  payload: ReportPayload
  /**
   * 补传时是否把数量三键一起发：
   * - `true` = 工序列表逐道报工（工人在界面上改过数量 ⇒ 必须原样补发）；
   * - `false` = A 模式一屏【开工】（在线路径**不传数量**，服务端取「剩余应做」）——
   *   补传要逐字同形，否则「这道已被别人推进」时会被服务端超上限拒（等于改了在线语义）。
   */
  sendQty: boolean
  /** 报工发生的本机时间（离线补传时明细用它，而不是补传成功那一刻） */
  createdAt: number
}

/** 补传被服务端拒绝的报工（出队 + 回报原因：不得静默丢单） */
export interface RejectedReport extends PendingReport {
  message: string
}

/** 本机报工明细（人 / 工序 / 数量 / 时间） */
export interface WorkLogEntry {
  requestId: string
  worker_name: string
  operation: string
  qty: number
  unit: string
  createdAt: number
}

export interface FlushResult {
  sent: PendingReport[]
  rejected: RejectedReport[]
  remaining: number
}

/** 读 JSON（兼容 storage 里存的是字符串或对象；损坏/缺失一律回落到 fallback） */
function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = Taro.getStorageSync(key)
    if (!raw) return fallback
    return (typeof raw === 'string' ? JSON.parse(raw) : raw) as T
  } catch {
    return fallback
  }
}

/** 写 JSON（写失败不得让报工主链路崩溃：缓存与队列都是**降级**能力，不是主路径） */
function writeJson(key: string, value: unknown): void {
  try {
    Taro.setStorageSync(key, JSON.stringify(value))
  } catch {
    // storage 不可用（配额满 / 隐私模式）⇒ 本次降级不可用，主链路照常
  }
}

/** 缓存本单待做清单（`loadOrder` 成功后调用） */
export function cacheOrderOperations(orderId: string, detail: OrderOperations): void {
  writeJson(ORDER_CACHE_PREFIX + orderId, detail)
}

/** 读本机缓存的待做清单；没有/损坏返回 null（调用方据此走原有的报错路径） */
export function getCachedOrderOperations(orderId: string): OrderOperations | null {
  const cached = readJson<OrderOperations | null>(ORDER_CACHE_PREFIX + orderId, null)
  return cached && Array.isArray(cached.positions) ? cached : null
}

export function listPendingReports(): PendingReport[] {
  const list = readJson<PendingReport[]>(PENDING_KEY, [])
  return Array.isArray(list) ? list.filter((item) => item && item.requestId && item.orderId) : []
}

/** 待补传条数（页面据此提示「待补传 N 条」，工人知道报工没丢） */
export function pendingReportCount(): number {
  return listPendingReports().length
}

/** 入队（同 `requestId` 不重复入队：一次动作只占一条） */
export function enqueuePendingReport(item: PendingReport): void {
  const list = listPendingReports().filter((existing) => existing.requestId !== item.requestId)
  list.push(item)
  writeJson(PENDING_KEY, list)
}

export function listWorkLogs(orderId: string): WorkLogEntry[] {
  const list = readJson<WorkLogEntry[]>(WORK_LOG_PREFIX + orderId, [])
  return Array.isArray(list) ? list.filter((item) => item && item.operation) : []
}

/**
 * 追加一条本机报工明细（新的在前）。
 * 同 `requestId` 幂等去重：补传与直报可能都记一次，同一动作在明细里**只能有一行**。
 */
export function appendWorkLog(orderId: string, entry: WorkLogEntry): void {
  const list = listWorkLogs(orderId)
  if (list.some((existing) => existing.requestId === entry.requestId)) return
  writeJson(WORK_LOG_PREFIX + orderId, [entry, ...list].slice(0, MAX_WORK_LOGS))
}

/** 补传发送函数（默认走真实网络层；单测注入替身即可断言「复用了同一个键 + 同一个凭证」） */
export type SendReport = (item: PendingReport) => Promise<ProductionResponse<ReportResult>>

/**
 * 默认补传实现 = **唯一写入口** `scan/complete`（issue #5647 G10）。
 *
 * <p>补传与在线报工必须走**同一条路**：否则「离线时按老路入队、联网后按新路补传」（或反之）
 * 会让同一次报工在两条口径下落地 —— 那正是本单要治的病。</p>
 */
async function sendByScan(item: PendingReport): Promise<ProductionResponse<ReportResult>> {
  return completeByScan(
    item.token,
    item.operationId,
    item.requestId,
    item.sendQty ? item.payload : undefined,
  )
}

/**
 * 补传队列（按入队顺序逐条重发，**复用入队时的幂等键与报工凭证**）。
 * - 缺凭证（旧版本入队）⇒ 出队并回报原因（不发一个注定被服务端拒的请求，也不静默丢单）；
 * - 成功 ⇒ 出队 + 记一条本机报工明细；
 * - 传输层失败（`offline`）⇒ 原样保留并**停止本轮**（还在断网，继续发只是白等）；
 * - 业务拒绝 ⇒ 出队并把原因回报给调用方（重发不会改变结果，且该键已被服务端释放）。
 */
export async function flushPendingReports(send: SendReport = sendByScan): Promise<FlushResult> {
  const pending = listPendingReports()
  const sent: PendingReport[] = []
  const rejected: RejectedReport[] = []
  const keep: PendingReport[] = []
  let offline = false

  for (const item of pending) {
    if (offline) {
      keep.push(item)
      continue
    }
    if (!item.token) {
      // 旧版本（`.../operations/{id}/report`）入队的条目：那条路已随 #5647 G10 退场，
      // 没有凭证就无法按「哪一套、哪个部位」重新定位 ⇒ 显式出队 + 指名原因（不静默丢单）
      rejected.push({ ...item, message: '这次补传缺少扫码凭证（旧版本入队），请重新报工' })
      continue
    }
    const res = await send(item)
    if (res.success) {
      sent.push(item)
      appendWorkLog(item.orderId, {
        requestId: item.requestId,
        // 🔴 身份已不在请求体里（issue #4733）：本机缓存的展示名取**服务端回执** ——
        // 服务端才知道这笔到底记到了谁头上（前端拼一个名字等于把工资凭证交给客户端）
        worker_name: res.data?.worker_name || '未署名',
        operation: item.operationName,
        qty: item.payload.qty,
        unit: item.unit,
        createdAt: item.createdAt,
      })
      continue
    }
    if (res.offline) {
      offline = true
      keep.push(item)
      continue
    }
    rejected.push({ ...item, message: res.message || '补传被服务端拒绝' })
  }

  writeJson(PENDING_KEY, keep)
  return { sent, rejected, remaining: keep.length }
}
