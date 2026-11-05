// case_ids: MC-226
/**
 * 三个「读面」的判据与格式化（issue #7813 P2b）—— 纯函数，零 DOM、零 Taro。
 *
 * ## 这一层是什么
 *
 * P2b 把 `/w/` 抄成小程序的三块**只读**面搬进 bmini（裁高计算 / 精裁清单 / 质检）。
 * `frontend/worker-h5/src/render.mjs` 文件头那**四条硬约束**是在事故里长出来的，而它们
 * 治的**不是**「报工页长什么样」，是「谁可以记账 / 哪一套是哪一套 / 哪个数是服务端给的」
 * —— 换个页面就重犯一次。所以搬迁的第一步是把判据搬成**可被单测直接钉住的纯函数**
 * （判据与页面分开：页面只渲染与装配），三条新页都**只许**从这里取判据，不许各写一份。
 *
 * | # | 硬约束（`/w/` 原文） | 本文件的落点 | 落在哪几面 |
 * |---|---|---|---|
 * | ① | 旧码（`granularity:"order"`）⇒ 进 select 态，**绝不默认取第 1 套** | {@link applyReadScan}（`selection` 恒清空）/ {@link readSelection}（半截不成立） | 精裁清单 · 质检（两面都先经扫码解析） |
 * | ② | 工序未确定（`operation == null`）⇒ **不得出现报工按钮** | {@link operationNotReadyHint}（读面一个动作都不给，只说明为什么） | 三个面全部 |
 * | ③ | 未登录（`worker == null`）⇒ **不得出现报工按钮** | {@link readFaceInitial}（`mode='unauthorized'` ⇒ 页面上没有任何动作） | 三个面全部 |
 * | ④ | 报工回执 ⇒ 屏上只认「下一道 / 本套已完成」，**前端不猜** | {@link qualityStateText}（判定只认服务端；读到「没记录」才敢说正常）/ {@link reportHandoffUrl}（去报工**只交码**，不交猜出来的套 / 工序） | 三个面全部 |
 *
 * ## 与 `reportState.ts` 的关系（真值只有一份）
 *
 * ① 的判据**不在这里另写一份**：旧码判据 = `reportState.isLegacyScan`，套号清单 = `reportState.legacySets`
 * （服务端的降级形态把候选放在 `selections`，`needs_selection` 只是 `["set","position"]` 标记
 * —— 见 `ProductionScanService#degradedView`）。本文件只把它们接到「读面」的状态机上。
 *
 * ## 边界（照实登记，§19.1）
 *
 * ① 本文件**不发起任何写请求**，也**不导出**任何写函数：三个读面是只读面（P2b 的口径 =
 *    「一条入口 + 读面复用」）。写入口仍只有报工页那两条具名路（`production-single-write-entry`）。
 * ② 它判的是**状态与文案的形态**，不是「工人在真机上点得到」——后者由页面装配判据承担。
 * ③ 缺值一律 `—`（与纸面 / 同族工人页同口径）：**不印 0、不摆空占位**。
 */
import {
  MISSING,
  isLegacyScan,
  legacySets,
  type CutPlanRow,
  type ReportOperation,
  type ReportSelectionSet,
  type ReportView,
} from './reportState'

/** 精裁清单行（形状定义在 `reportState`：它属于扫码响应，不属于本层）。 */
export type { CutPlanRow }

/** 缺值占位符**原样转出**（三个读面与共享件都从这一处取，避免各自写一份 `'—'`）。 */
export { MISSING }

/** 机器屏精度兜底（服务端 `rounding.digits` 是唯一真值，这里只是渲染兜底，与 `/w/` 同值）。 */
export const DEFAULT_DIGITS = 3

/** 读面标语（三个面共用；说清「这一页只给人看、不记账」——避免工人等一个不存在的按钮）。 */
export const READ_ONLY_NOTICE = '本页只看不记：报工请在报工页提交'

/** 读面模式（互斥）。`unauthorized` = 本机没有工人身份（③）。 */
export type ReadFaceMode = 'unauthorized' | 'scan' | 'select' | 'ready'

/** 当前工人（服务端来源；`null` = 未登录）。 */
export interface ReadFaceWorker {
  worker_name?: string | null
  worker_no?: string | null
}

/** 读面状态机（三个面共用一份）。 */
export interface ReadFaceState {
  worker: ReadFaceWorker | null
  view: ReportView | null
  /** 旧码的「套 + 部位」两截选择（新码恒空） */
  selection: { setId: string | null; orderItemId: string | null }
  mode: ReadFaceMode
  notice: string | null
  error: string | null
}

/** 初始态：没身份 ⇒ `unauthorized`（③：屏上没有任何动作）；有身份 ⇒ 等扫码。 */
export function readFaceInitial(worker: ReadFaceWorker | null = null): ReadFaceState {
  return {
    worker,
    view: null,
    selection: { setId: null, orderItemId: null },
    mode: worker ? 'scan' : 'unauthorized',
    notice: null,
    error: null,
  }
}

/**
 * 扫码解析结果 → 读面状态。
 *
 * 🔴 硬约束 ①：旧码 ⇒ `mode='select'` 且 **`selection` 清空**（绝不默认取第 1 套 ——
 * 取错套的代价是把「这一套的裁多长 / 这一件的质检记录」当成另一套的给工人照做）。
 * 🔴 未登录时**不接受**任何解析结果（③：没有身份就没有这一屏）。
 */
export function applyReadScan(state: ReadFaceState, view: ReportView | null): ReadFaceState {
  if (!state.worker) {
    return { ...readFaceInitial(null), error: '尚未登录工人身份，请先用工号 + PIN 登录' }
  }
  const legacy = isLegacyScan(view)
  return {
    ...state,
    view,
    selection: { setId: null, orderItemId: null },
    mode: !view ? 'scan' : legacy ? 'select' : 'ready',
    notice: legacy ? '这是一张旧码：请先选择套号与部位' : null,
    error: null,
  }
}

/** 旧码：选中一套（部位随之清空 —— 半截选择不算选完）。 */
export function readPickSet(
  state: ReadFaceState,
  setId: string,
  setNo?: number | string | null,
): ReadFaceState {
  return {
    ...state,
    selection: { setId, orderItemId: null },
    notice: `已选第 ${setNo ?? '?'} 套，请再选部位`,
  }
}

/** 旧码：选中一个部位（两截齐全 ⇒ 调用方带着 selection 重新解析）。 */
export function readPickPosition(
  state: ReadFaceState,
  orderItemId: string,
  positionName?: string | null,
): ReadFaceState {
  const set = legacySets(state.view).find((s) => s.set_id === state.selection.setId)
  const position = (set?.positions ?? []).find((p) => p.order_item_id === orderItemId)
  const name = positionName ?? position?.position_name ?? ''
  return {
    ...state,
    selection: { ...state.selection, orderItemId },
    notice: `已选：第 ${set?.set_no ?? '?'} 套 · ${name}`.trim(),
  }
}

/** 旧码的完整选择（**两个都选**才算；半截选择不发给服务端）。 */
export function readSelection(state: ReadFaceState): { setId: string; orderItemId: string } | null {
  const { setId, orderItemId } = state.selection
  if (!setId || !orderItemId) return null
  return { setId, orderItemId }
}

/** 本屏的候选套（旧码才非空；新码 / 未解析 ⇒ 空数组 —— 不拿第 1 套冒充）。 */
export function readSetChoices(state: ReadFaceState): ReportSelectionSet[] {
  return legacySets(state.view)
}

/**
 * 🔴 硬约束 ②：工序未确定（`operation == null`）时屏上怎么说。
 *
 * 读面**没有报工按钮**（那是报工页的事）⇒ 这条判据在读面上的形态是「明说为什么没有动作 +
 * 下一步去哪」，而不是一个点了会失败的空按钮。返回 `null` = 工序已确定，无需提示。
 */
export function operationNotReadyHint(view: ReportView | null | undefined): string | null {
  if (!view) return null
  if (view.operation?.operation_id) return null
  return '这道工序还没定：请到报工页选好工序再报工'
}

/**
 * 🔴 硬约束 ④（交接形态）：把工人送到报工页时**只交这次扫到的码**。
 *
 * 为什么不能顺手带上套 / 工序：那等于前端替服务端猜「这一笔算哪一套、哪一道」——
 * `/w/` 的原文是「前端不猜下一道（猜错 = 把下一笔计件记到错的工序上）」。报工页自己按
 * 服务端解析结果决定（含旧码必须由工人选一对）。
 *
 * @param route 报工页路由（`REPORT_PAGE_ROUTE`；不在这里写第二份字面量）
 * @param token 本次扫到的码（空 ⇒ 只回报工页，不编参数）
 */
export function reportHandoffUrl(route: string, token: string | null | undefined): string {
  const code = String(token ?? '').trim()
  return code === '' ? route : `${route}?t=${encodeURIComponent(code)}`
}

// ══════════════════════════════════════════════════════════════════════════════
// 裁高计算（`GET /api/worker/production/cutting-height`）
//
// 数据**只有**服务端一份（复用商家端 `CuttingHeightConfigService.preview` 的同一份口径）：
// 本层只格式化，**不重算命中**、不猜缺值（缺 ⇒ `null` ⇒ 屏上 `—`）。
// ══════════════════════════════════════════════════════════════════════════════

/** 命中项（服务端预勾的全部增量项）。 */
export interface CutHeightHit {
  key?: string | null
  name?: string | null
  value?: number | string | null
  direction?: 'add' | 'subtract' | string | null
}

/** 未配置取值的项（`misses[].reason='unresolved'`）—— **标黄、不计入**（不按 0 算）。 */
export interface CutHeightMiss {
  name?: string | null
  reason?: string | null
}

/** 一个部位的裁剪高度（字段名与 `WorkerCuttingHeightService` 逐字同名）。 */
export interface CutHeightPosition {
  order_item_id?: string | null
  position_kind?: string | null
  position_name?: string | null
  /** 本次扫码命中的那一樘窗（水洗唛就在手上那件帘上） */
  scanned?: boolean | null
  width?: number | string | null
  height?: number | string | null
  craft?: string | null
  cutting_mode?: string | null
  fabric_meters?: number | string | null
  /** 成品高（裁高的起点） */
  base?: number | string | null
  /** 服务端算出的裁剪高度（**规则值**；本页不重算） */
  cutting_height?: number | string | null
  rounding?: { mode?: string | null; digits?: number | string | null } | null
  hits?: CutHeightHit[] | null
  misses?: CutHeightMiss[] | null
  /** 缺哪些必需取值（非空 ⇒ 算不出裁高，**不猜数**） */
  missing?: string[] | null
  missing_reason?: string | null
}

/** 裁高读面的一屏。 */
export interface CutHeightData {
  order?: {
    order_no?: string | null
    processing_order_no?: string | null
    customer_name?: string | null
    set_no?: number | string | null
    set_count?: number | string | null
  } | null
  positions?: CutHeightPosition[] | null
  /** 未指派批次（`/w/` 只能指路到报工页 —— 机台页没有文本输入元素） */
  batch_required?: boolean | null
  batch_no?: string | null
}

/** 显示精度（服务端 `rounding.digits`；0~3 之外 / 缺 ⇒ 3）。 */
export function digitsOf(position: CutHeightPosition | null | undefined): number {
  const digits = Number(position?.rounding?.digits)
  // 🔴 显式判 0：`digits && …` 会把合法的 0 位（整米取整）当成缺值退回 3 位（少印一位 = 机器屏输错数）
  return Number.isInteger(digits) && digits >= 0 && digits <= 3 ? digits : DEFAULT_DIGITS
}

/** 数值 → 定长文本；缺值 / 非数 ⇒ `—`（**不印 0**）。 */
export function fmtNumber(value: number | string | null | undefined, digits = DEFAULT_DIGITS): string {
  if (value === null || value === undefined || value === '') return MISSING
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(digits) : MISSING
}

/** 文本兜底：空 / null ⇒ `—`。 */
export function textOr(value: unknown): string {
  if (value === null || value === undefined) return MISSING
  const text = String(value).trim()
  return text === '' ? MISSING : text
}

/** 本屏的部位（逐部位一行；缺 ⇒ 空数组）。 */
export function cutHeightPositions(data: CutHeightData | null | undefined): CutHeightPosition[] {
  return Array.isArray(data?.positions) ? data.positions : []
}

/** 默认选中的部位 = 服务端标记 `scanned` 的那一个；没有标记 ⇒ 第 1 个（0 个 ⇒ -1）。 */
export function scannedPositionIndex(data: CutHeightData | null | undefined): number {
  const positions = cutHeightPositions(data)
  const index = positions.findIndex((p) => p?.scanned === true)
  return index >= 0 ? index : positions.length > 0 ? 0 : -1
}

/** 选中部位（越界 / 没有部位 ⇒ `null`）。 */
export function cutHeightPosition(
  data: CutHeightData | null | undefined,
  index: number,
): CutHeightPosition | null {
  const positions = cutHeightPositions(data)
  const at = Number.isInteger(index) ? index : 0
  return positions[at] ?? null
}

/**
 * 大字那句话：算得出来 ⇒ `请在机器屏输入 X.XXX 米`；算不出来 ⇒ **明说缺什么**（不猜数）。
 *
 * 与 `/w/` 机台屏同一句口径（`machine.mjs` 的 `reportBlock`）—— 换端不换话，
 * 免得车间里两种说法指的是同一件事。
 */
export function cutHeightText(position: CutHeightPosition | null): string {
  if (!position) return '这次扫码没有解析出任何部位：请重新扫码'
  const missing = Array.isArray(position.missing) ? position.missing : []
  if (missing.length > 0) {
    return `缺少${missing.join(' / ')}：算不出裁剪高度，请在机器上按工艺复核`
  }
  const value = position.cutting_height
  if (value === null || value === undefined || value === '') {
    return '本部位没有裁高值：请在机器上按工艺复核'
  }
  return `请在机器屏输入 ${fmtNumber(value, digitsOf(position))} 米`
}

/** 命中项行（`+` / `−` 前缀由方向决定；顺序 = 服务端下发顺序）。 */
export function cutHitRows(position: CutHeightPosition | null): {
  key: string
  name: string
  value: string
  direction: '+' | '−'
}[] {
  return (position?.hits ?? []).map((hit, index) => ({
    key: String(hit?.key ?? index),
    name: textOr(hit?.name),
    value: fmtNumber(hit?.value, digitsOf(position)),
    direction: hit?.direction === 'subtract' ? '−' : '+',
  }))
}

/** 未配置取值的项（`reason='unresolved'`）：**标黄、不计入**，绝不按 0 算。 */
export function unresolvedRows(position: CutHeightPosition | null): string[] {
  return (position?.misses ?? [])
    .filter((miss) => miss?.reason === 'unresolved')
    .map((miss) => textOr(miss?.name))
}

/** 明细行（成品高 / 规则值 / 取整）—— 缺值 `—`，不摆空占位。 */
export function cutHeightDetailRows(position: CutHeightPosition | null): { label: string; value: string }[] {
  if (!position) return []
  const digits = digitsOf(position)
  return [
    { label: '成品高', value: fmtNumber(position.base, digits) },
    { label: '裁高（系统算）', value: fmtNumber(position.cutting_height, digits) },
    { label: '取整', value: `${textOr(position.rounding?.mode)} · ${digits} 位` },
    { label: '用料', value: fmtNumber(position.fabric_meters, digits) },
  ]
}

/** 批次阻断（与服务端 `batch_required` 同口径）：要批次却没指派 ⇒ 只能指路到报工页。 */
export function cutBatchBlockedText(data: CutHeightData | null | undefined): string | null {
  if (data?.batch_required !== true) return null
  const no = typeof data?.batch_no === 'string' ? data.batch_no.trim() : ''
  return no === '' ? '本单未指派批次：请到报工页填写批次后再报工' : null
}

// ══════════════════════════════════════════════════════════════════════════════
// 精裁清单（`set_overview.cut_plan`；与商家端加工单详情**同一份**取数）
// ══════════════════════════════════════════════════════════════════════════════

/** 精裁清单的格式化行（只格式化，不算第二份 —— 米数 / 片数都是服务端给的）。 */
export interface CutPlanRowText {
  key: string
  /** 「裁 6.15 米 × 2 片」；缺值 ⇒ 「裁 — × —」 */
  size: string
  /** 「布帘 · 左片」；缺 ⇒ `—` */
  name: string
  /** 「用料 6.15 米」；缺 ⇒ `—` */
  meters: string
  /** 「批次 PC-01 · 裁 12.30 米」；未指派 ⇒ `null`（不摆空占位） */
  batch: string | null
  /** 缺什么（只在真缺时出现） */
  reason: string | null
}

/** 精裁清单行（**只取有 `order_item_id` 的行**；其余视为脏数据，不渲染）。 */
export function cutPlanRows(view: ReportView | null | undefined): CutPlanRowText[] {
  const rows = Array.isArray(view?.set_overview?.cut_plan)
    ? (view?.set_overview?.cut_plan ?? []).filter((row) => row && row.order_item_id)
    : []
  return rows.map((row, index) => {
    const positionName = String(row.position_name ?? row.position_kind ?? '').trim()
    const component = typeof row.component === 'string' ? row.component.trim() : ''
    const name = [positionName, component].filter((part) => part !== '').join(' · ')
    const size =
      row.panel_length_m === null || row.panel_length_m === undefined ||
      row.panel_count === null || row.panel_count === undefined
        ? `裁 ${MISSING} × ${MISSING}`
        : `裁 ${fmtNumber(row.panel_length_m)} 米 × ${textOr(row.panel_count)} 片`
    const meters =
      row.fabric_meters === null || row.fabric_meters === undefined
        ? `用料 ${MISSING}`
        : `用料 ${fmtNumber(row.fabric_meters)} 米`
    const batchNo = typeof row.batch_no === 'string' ? row.batch_no.trim() : ''
    const batchMeters =
      row.batch_meters === null || row.batch_meters === undefined
        ? ''
        : ` · 裁 ${fmtNumber(row.batch_meters)} 米`
    const reason = typeof row.missing_reason === 'string' && row.missing_reason.trim() !== ''
      ? row.missing_reason.trim()
      : null
    return {
      key: String(row.order_item_id ?? index),
      size,
      name: name === '' ? MISSING : name,
      meters,
      batch: batchNo === '' ? null : `批次 ${batchNo}${batchMeters}`,
      reason,
    }
  })
}

/**
 * 精裁清单的空态 —— **具名**（说清「为什么没有」与「下一步做什么」）。
 *
 * 判据面：读失败 ≠ 空态（前者由页面单独一态）；这里只管「读到了、但这一套没有裁片」。
 */
export const CUT_PLAN_EMPTY_HINT =
  '这一套没有精裁输出（系统还没算出裁片长度与片数）：请让商家核对算料后再看'

// ══════════════════════════════════════════════════════════════════════════════
// 质检（`GET /api/worker/quality/latest`）
// ══════════════════════════════════════════════════════════════════════════════

/** 质检记录一行（服务端字段；`reason_label` = 字典中文名，`reason` = 自由补充）。 */
export interface QualityRecord {
  result?: string | null
  reason_label?: string | null
  reason?: string | null
  inspector_name?: string | null
  inspected_at?: string | null
}

/** 质检读面的状态（`loading` / `error` / `latest` 三者互斥地说明「现在能说什么」）。 */
export interface QualityRead {
  loading: boolean
  latest?: QualityRecord | null
  records?: QualityRecord[] | null
  error?: string | null
}

/** 质检**状态**词（记录卡右上角）—— 只描述**下一步**：待复检 ≠ 已解决。 */
const QUALITY_STATE_LABELS: Record<string, string> = {
  pass: '正常',
  rework: '待复检',
  scrap: '已判报废',
}

/**
 * 🔴 硬约束 ④ 的**质检形态**：状态词只认服务端。
 *
 * - `loading` ⇒ 「读取中」；`error` ⇒ 「未读到」（**不说「正常」**，也不说「没有记录」——
 *   那是在替服务端断言「这一件没问题」）；
 * - 读到且无记录 ⇒ 「正常」（用户 2026-10-25 裁定：默认没问题，屏上**不出现「合格」**）；
 * - 有最新判定 ⇒ 按服务端的 `result` 取词（未知值不硬猜成「正常」，落回「已记录」）。
 *
 * 红证：把 `error` 分支合并进「正常」⇒ 读失败被说成没问题（判据当场红）。
 */
export function qualityStateText(quality: QualityRead | null | undefined): string {
  const records = Array.isArray(quality?.records) ? quality?.records ?? [] : []
  const latest = quality?.latest ?? null
  if (quality?.loading === true && records.length === 0 && latest === null) return '读取中'
  if (quality?.error && records.length === 0 && latest === null) return '未读到'
  const result = latest?.result
  if (result === null || result === undefined || result === '') return records.length === 0 ? '正常' : '已记录'
  return QUALITY_STATE_LABELS[result] ?? '已记录'
}

/** 质检记录 → 屏上行（顺序 = 服务端下发顺序，最新在前；**不聚合、不排序**）。 */
export function qualityRecordRows(records: QualityRecord[] | null | undefined): {
  key: string
  label: string
  time: string
  reason: string | null
  inspector: string | null
}[] {
  return (Array.isArray(records) ? records : []).map((row, index) => {
    const label = QUALITY_STATE_LABELS[String(row?.result ?? '')] ?? '已记录'
    const reasonLabel = typeof row?.reason_label === 'string' ? row.reason_label.trim() : ''
    const note = typeof row?.reason === 'string' ? row.reason.trim() : ''
    const reason = reasonLabel !== '' && note !== '' ? `${reasonLabel}（${note}）` : reasonLabel || note
    const inspector = typeof row?.inspector_name === 'string' ? row.inspector_name.trim() : ''
    return {
      key: `${String(row?.inspected_at ?? '')}-${index}`,
      label,
      time: typeof row?.inspected_at === 'string' ? row.inspected_at.trim() : '',
      reason: reason === '' ? null : reason,
      inspector: inspector === '' ? null : inspector,
    }
  })
}

/** 质检空态（读到「没有记录」时的那一句；读失败不显示它）。 */
export const QUALITY_EMPTY_HINT = '这一件还没有质检记录（默认没问题；做工有问题才记）'

/** 未开通质检面（服务端 403 / `inspect` 不在工人档案的页面集里）—— 可行动，不责备。 */
export const QUALITY_NOT_ENABLED_HINT =
  '这台设备没有开通「质检」：请让管理员在工人档案里勾上「质检」后再看'

/** 本件（套号 × 部位）—— 水洗唛是部位级码，扫码已指到这一件；精裁清单也用它说「哪一套」。 */
export function pieceText(view: ReportView | null | undefined): string {
  const setNo = view?.set_no === null || view?.set_no === undefined ? MISSING : String(view.set_no)
  const name = String(view?.position?.position_name ?? view?.position?.position_kind ?? '').trim()
  return name === '' ? `第 ${setNo} 套` : `第 ${setNo} 套 · ${name}`
}

/** 工序显示名（`logical_name` 优先，退化到快照名；都缺 ⇒ `—`）。 */
export function operationText(operation: ReportOperation | null | undefined): string {
  const name = (operation?.logical_name ?? '').trim() || (operation?.operation ?? '').trim()
  return name === '' ? MISSING : name
}
