/**
 * 工人端**库存修正**的纯逻辑（issue #8104；用户 2026-10-29 逐字
 * 「手机端还要增加一个库存修正的功能，apk程序也要同步增加这个功能，允许工人对某个批次的布匹进行修正」）。
 *
 * ## 为什么单独一个文件（而不是写在页面里）
 *
 * 页面只做接线：校验口径、提交体字段集、回执文案都必须是**纯函数**，才能被 `node --test` /
 * jest 逐值钉住（页面测试只能证明「点了有没有发请求」）。同族先例 =
 * `src/utils/inbound/shipment.ts`（`buildShipBody` 的构造式白名单）。
 *
 * ## 三条口径（与服务端逐字对齐，不在这里「再宽松一点」）
 *
 * 1. 🔴 **提交体是构造式白名单**：只有 `batch_id` / `actual_meters` / `reason` / `note` /
 *    `client_request_id` 五个键 —— `worker_id` / `worker_name` / `tenant_id` **结构上不存在**
 *    （身份由 `X-Worker-Session-Id` 解；工人端点的请求体里带身份字段 = 把责任凭证交给客户端）；
 * 2. 🔴 **米数口径与库存链路同一把尺**：0.1 米粒度、**不接受负数**、**不做静默取整**
 *    （服务端 `StockQuantity.requireOneDecimal` 会 422；前端先拦一道只是少一次往返，不是第二条判据）；
 * 3. 🔴 **三态各有各的话**：`applied` / `unchanged` / `replayed` 是三个不同事实
 *    （真的改了 / 与系统一致 / 这次提交此前已记过账）—— 混成一句「提交成功」会让工人以为改了两次。
 */

/** 一个批次（字段面照后端 `WorkerBatchStockViews.BatchRow` 逐字同名，蛇形键）。 */
export interface StockBatchRow {
  batch_id: number
  batch_no: string
  product_id?: string | null
  product_name?: string | null
  sku_code?: string | null
  dye_lot?: string | null
  inbound_no?: string | null
  received_date?: string | null
  remaining_meters?: number | string | null
}

/** 修正原因（服务端下发：`code` 机器可判、`label` 给人看 —— 端侧**不**另写一份选项）。 */
export interface CorrectionReason {
  code: string
  label: string
}

/** 一次修正的回执（四数一起回：盘前 / 实盘 / 差异 / 盘后）。 */
export interface CorrectionReceipt {
  run_id?: string
  batch_id?: number
  batch_no?: string
  product_name?: string | null
  sku_code?: string | null
  status?: string
  before_meters?: number | string | null
  actual_meters?: number | string | null
  delta_meters?: number | string | null
  after_meters?: number | string | null
  worker_name?: string | null
  worker_no?: string | null
}

/** 提交体（**构造式白名单**：多一个键都要在这里显式加，页面不能自己拼）。 */
export interface CorrectionBody {
  batch_id: number
  actual_meters: number
  reason: string
  note?: string
  client_request_id: string
}

/** 服务端三态（与 `BatchStockViews.STOCKTAKE_*` 逐字同名）。 */
export const CORRECTION_APPLIED = 'applied'
export const CORRECTION_UNCHANGED = 'unchanged'
export const CORRECTION_REPLAYED = 'replayed'

/** 备注上限（与服务端 `WorkerBatchStockService.MAX_NOTE_LENGTH` 逐值相同）。 */
export const MAX_NOTE_LENGTH = 60

/** 缺值占位（与工人端其它页同口径：不是 0、不是空串）。 */
export const MISSING = '—'

/**
 * 一次提交的**幂等键**（端侧生成、重试复用；服务端把它拼成盘点运行标识 `wc-<id>`）。
 *
 * 优先 `crypto.randomUUID()`（36 字符，符合服务端「≤48、只含字母数字连字符」的准入）；
 * 老 WebView 没有它 ⇒ 用「时间戳 + 随机串」兜底（同样在准入范围内，且同一毫秒重复的概率可忽略）。
 */
export function newCorrectionRequestId(): string {
  const cryptoObj: any = typeof globalThis !== 'undefined' ? (globalThis as any).crypto : undefined
  if (cryptoObj && typeof cryptoObj.randomUUID === 'function') {
    return String(cryptoObj.randomUUID())
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/**
 * 解析工人输入的实盘米数（**纯函数**：页面只渲染它的结果）。
 *
 * 与服务端同口径：非负、最多 1 位小数、不做静默取整。
 * 返回 `error` 时 `value` 必为 `null`（不给「半合法值」让调用方去猜）。
 */
export function parseActualMeters(
  raw: string | null | undefined,
): { value: number | null; error: string } {
  const text = raw == null ? '' : String(raw).trim()
  if (text === '') return { value: null, error: '请填实盘米数（这一批现在实际还剩多少米）' }
  if (!/^\d+(?:\.\d+)?$/.test(text)) {
    return { value: null, error: '实盘米数只能填数字（如 42 或 42.5）' }
  }
  const value = Number(text)
  if (!Number.isFinite(value)) return { value: null, error: '实盘米数只能填数字（如 42 或 42.5）' }
  const fraction = text.split('.')[1] ?? ''
  if (fraction.length > 1) {
    return { value: null, error: '实盘米数最多 1 位小数（例如 42.5）' }
  }
  return { value, error: '' }
}

/**
 * 构造提交体（**构造式白名单**）。
 *
 * @param row       工人选中的批次（`batch_id` 来自服务端，不由前端拼）
 * @param actual    实盘米数（已过 {@link parseActualMeters}）
 * @param reason    原因 code（服务端闭词表里的值）
 * @param note      备注（可空；超出上限的由页面先拦，这里再截一道不静默发送脏值）
 * @param requestId 幂等键（同一次提交的重试必须复用同一个）
 */
export function buildCorrectionBody(
  row: Pick<StockBatchRow, 'batch_id'>,
  actual: number,
  reason: string,
  note: string | null | undefined,
  requestId: string,
): CorrectionBody {
  const body: CorrectionBody = {
    batch_id: Number(row.batch_id),
    actual_meters: Number(actual),
    reason,
    client_request_id: requestId,
  }
  const trimmed = note == null ? '' : String(note).trim()
  if (trimmed !== '') {
    body.note = trimmed.slice(0, MAX_NOTE_LENGTH)
  }
  return body
}

/** 米数文案：缺值 ⇒ `—`（**不**回落 0 —— 「0 米」是一个事实，「没读到」是另一个）。 */
export function formatMeters(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return MISSING
  const num = Number(value)
  if (!Number.isFinite(num)) return MISSING
  return `${num.toFixed(1).replace(/\.0$/, '')} 米`
}

/** 差异文案（带符号；0 ⇒ 「无差异」——不印 `+0`，那会被读成"改了一点"）。 */
export function formatDelta(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return MISSING
  const num = Number(value)
  if (!Number.isFinite(num)) return MISSING
  if (num === 0) return '无差异'
  const text = num.toFixed(1).replace(/\.0$/, '')
  return `${num > 0 ? '+' : ''}${text} 米`
}

/**
 * 回执文案（**三态分开说**；未知状态如实显示原值，不猜成成功）。
 *
 * 这也是「不再修正一次」的唯一可见面：`replayed` / `unchanged` 都**没有**写库，
 * 文案必须让工人一眼看出来（否则他会以为系统抽风、再点一次）。
 */
export function describeCorrection(receipt: CorrectionReceipt | null | undefined): string {
  const status = receipt?.status ?? ''
  const batchNo = receipt?.batch_no ?? ''
  const after = formatMeters(receipt?.after_meters)
  if (status === CORRECTION_APPLIED) {
    return `已修正：批次 ${batchNo} 现在记为 ${after}（盘前 ${formatMeters(receipt?.before_meters)}，差异 ${formatDelta(receipt?.delta_meters)}）`
  }
  if (status === CORRECTION_UNCHANGED) {
    return `批次 ${batchNo} 与系统一致（${after}），本次未写入任何变更`
  }
  if (status === CORRECTION_REPLAYED) {
    return `这次提交此前已记过账（批次 ${batchNo} 已是 ${after}），未重复修正`
  }
  return status === '' ? '提交完成，但系统未返回状态，请刷新后核对批次余量' : `提交完成（状态：${status}）`
}

/** 一行搜索结果的副标题：品名 · 货号 · 缸号（都缺 ⇒ `—`；**不**摆内部 id）。 */
export function rowSubtitle(row: StockBatchRow | null | undefined): string {
  const parts = [row?.product_name, row?.sku_code, row?.dye_lot]
    .map((part) => (part == null ? '' : String(part).trim()))
    .filter((part) => part !== '')
  return parts.length > 0 ? parts.join(' · ') : MISSING
}
