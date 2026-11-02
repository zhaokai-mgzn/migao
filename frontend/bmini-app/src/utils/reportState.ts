// case_ids: BM-014, BM-015, BM-025
/**
 * 扫码报工的**状态机 + 判据**（issue #7812 P2a）—— 纯函数，零 DOM、零 Taro，
 * `node`/`jest` 里可直接钉住。
 *
 * ## 为什么状态机单独一层
 *
 * 这一页动的是**车间每天用的报工面**，而报一笔 = 一笔计件工资。H5 `/w/` 的那四条硬约束
 * （`frontend/worker-h5/src/render.mjs` 文件头）是在事故里长出来的，本次迁移**逐条搬过来**，
 * 并且**判据与页面分开**：判据在纯函数里（可被单测钉死），页面只负责渲染与装配。
 *
 * | # | 硬约束 | 本文件里的落点 |
 * |---|---|---|
 * | ① | 旧码（`granularity:"order"`）⇒ 进 select 态，**绝不默认取第 1 套** | {@link applyScan}（`needs_selection` 非空 ⇒ `mode='select'`，`selection` 恒清空） |
 * | ② | 工序未确定（`operation == null`）⇒ **不得出现报工按钮** | {@link canReport} |
 * | ③ | 未登录 ⇒ **不得出现报工按钮** | {@link canReport}（`state.worker` 为假即 false） |
 * | ④ | 回执 ⇒ 只认服务端给的「下一道 / 本套已完成」，**前端不猜** | {@link receiptLine} + {@link applyReceipt} |
 *
 * ## 不搬的东西（照实登记）
 *
 * 机台/裁高、精裁清单、质检区块属于 `/w/` 的其它面（P2b/P2c），本页**不渲染**；
 * 报工三态（正常/返工/报废）与裁剪批次（`batch_required`）**保留**——它们直接影响记账口径，
 * 少一个就会把返工记成正常、或让裁剪工序提交被服务端 422 拒。
 * **成品入库卡 + 入库标签打印**已随 issue #8287 搬到本页（数据 = 服务端随回执下发的
 * `finished_inbound`，端侧不拼字段；打印走 50×70 行式标签通道）。
 */

/** 缺值占位符（与纸面 / 其它工人面同口径：**不是** 0、不是空串）。 */
import { codeFromScanText } from './scanInput'
import type { FinishedInboundView } from './labels/finishedInbound'

export const MISSING = '—'

/** 报工三态（与后端 `ProductionService.WORK_TYPES`、H5 `render.mjs` 的 `WORK_TYPES` 逐字同名）。 */
export const WORK_TYPES = ['normal', 'rework', 'scrap'] as const
export type WorkType = (typeof WORK_TYPES)[number]

/** 三态的中文（上屏只用这一份，别处不另写）。 */
export const WORK_TYPE_LABELS: Record<WorkType, string> = {
  normal: '正常',
  rework: '返工',
  scrap: '报废',
}

/** 默认 = 正常（与 H5 同口径：`normal` 时请求体里**没有** `work_type` 键）。 */
export const DEFAULT_WORK_TYPE: WorkType = 'normal'

/** 页面模式（互斥）。`unauthorized` = 本机没有工人身份。 */
export type ReportMode = 'unauthorized' | 'scan' | 'select' | 'main'

/** 工序（服务端下发的候选/当前工序）。字段名与后端逐字同名。 */
export interface ReportOperation {
  operation_id: string
  logical_name?: string | null
  /** 快照/变体名（`global_name` 缺失时的兜底显示名） */
  operation?: string | null
  qty?: number | string | null
  unit?: string | null
  unit_price?: number | string | null
  done_qty?: number | string | null
}

/** 部位（本屏所在的那一樘窗的某个部位）。 */
export interface ReportPosition {
  order_item_id?: string | null
  position_name?: string | null
  position_kind?: string | null
}

/** 旧码降级清单里的一套（含它下面的部位）。 */
export interface ReportSelectionSet {
  set_id: string
  set_no?: number | string | null
  positions?: Array<{
    order_item_id: string
    position_name?: string | null
    position_kind?: string | null
  }> | null
}

/** 扫码解析的一屏（`GET /api/worker/production/scan` 的 `data`；只声明本页用到的键）。 */
export interface ReportView {
  granularity?: string | null
  set_no?: number | string | null
  position?: ReportPosition | null
  operation?: ReportOperation | null
  alternatives?: ReportOperation[] | null
  needs_selection?: ReportSelectionSet[] | null
  set_progress?: { done?: number | null; total?: number | null } | null
  completed?: boolean | null
  /** 工人档案绑定了工序时 = 那一道（服务端已自动选中 ⇒ 不出选择器） */
  worker_operation?: string | null
  /** 裁剪工序必须给批次（服务端 422 硬闸） */
  batch_required?: boolean | null
  batch_no?: string | null
  /** 报工回执带回来的「下一道」/「本套是否已完成」 */
  next_operation?: ReportOperation | null
  set_completed?: boolean | null
  /** 成品入库块（issue #8287；服务端注入，端侧只渲染） */
  finished_inbound?: FinishedInboundView | null
}

/** 本页状态。 */
export interface ReportState {
  /** 当前工人（**服务端**来源，蛇形键 = `GET /api/worker/production/current-worker` 的响应；`null` = 未登录 ⇒ 见 {@link canReport} ③） */
  worker: { worker_name?: string | null; worker_no?: string | null } | null
  view: ReportView | null
  /** 旧码的「套 + 部位」半截选择（新码恒空） */
  selection: { setId: string | null; orderItemId: string | null }
  mode: ReportMode
  notice: string | null
  error: string | null
  /** 提交在飞（涉计件正确性：置真期间按钮 disabled，防连点记两笔） */
  submitting: boolean
  workType: WorkType
  /** 工人**已经动过**批次输入框时的原样值；`null` = 用服务端预填 */
  batchNo: string | null
  /** 报工回执（只来自服务端；`null` = 本屏还没报过） */
  receipt: string | null
  /** 成品入库块（service 下发；`null` = 本屏没有入库动作 ⇒ 整卡不渲染） */
  finishedInbound: FinishedInboundView | null
}

/** 初始态（未登录、待扫码）。 */
export function initialState(worker: ReportState['worker'] = null): ReportState {
  return {
    worker,
    view: null,
    selection: { setId: null, orderItemId: null },
    mode: worker ? 'scan' : 'unauthorized',
    notice: null,
    error: null,
    submitting: false,
    workType: DEFAULT_WORK_TYPE,
    batchNo: null,
    receipt: null,
    finishedInbound: null,
  }
}

/** 登录成功 / 身份读到之后进入待扫码态。 */
export function signedIn(state: ReportState, worker: ReportState['worker']): ReportState {
  return { ...initialState(worker), notice: state.notice }
}

/** 旧码判据（**唯一**一份）：`granularity === 'order'` 或 `needs_selection` 非空。 */
export function isLegacyScan(view: ReportView | null | undefined): boolean {
  if (!view) return false
  if (Array.isArray(view.needs_selection) && view.needs_selection.length > 0) return true
  return view.granularity === 'order'
}

/**
 * 扫码解析结果 → 新状态。
 *
 * 🔴 硬约束 ①：旧码 ⇒ `mode='select'` 且 **`selection` 清空**（绝不默认取第 1 套）。
 * 🔴 新一屏 = 新的一笔 ⇒ `submitting` / `receipt` / `batchNo` 一并归零
 * （上一屏的「提交中」把这一屏按钮禁死，是 H5 #6667 第 3 条踩过的形态）。
 */
export function applyScan(state: ReportState, view: ReportView | null): ReportState {
  if (!state.worker) {
    return { ...initialState(null), error: '尚未登录工人身份，请先用工号 + PIN 登录' }
  }
  const legacy = isLegacyScan(view)
  return {
    ...state,
    view,
    selection: { setId: null, orderItemId: null },
    mode: !view ? 'scan' : legacy ? 'select' : 'main',
    notice: legacy ? '这是一张旧码：请先选择套号与部位' : null,
    error: null,
    submitting: false,
    receipt: null,
    batchNo: null,
    finishedInbound: view?.finished_inbound ?? null,
  }
}

/** 旧码：选中一套（部位随之清空 —— 半截选择不算选完）。 */
export function pickSet(state: ReportState, setId: string, setNo?: number | string | null): ReportState {
  return {
    ...state,
    selection: { setId, orderItemId: null },
    notice: `已选第 ${setNo ?? '?'} 套，请再选部位`,
  }
}

/** 旧码：选中一个部位（此时两截齐全 ⇒ 调用方带 selection 重新解析）。 */
export function pickPosition(state: ReportState, orderItemId: string, positionName?: string | null): ReportState {
  const set = (state.view?.needs_selection ?? []).find((s) => s.set_id === state.selection.setId)
  const position = (set?.positions ?? []).find((p) => p.order_item_id === orderItemId)
  const name = positionName ?? position?.position_name ?? ''
  return {
    ...state,
    selection: { ...state.selection, orderItemId },
    notice: `已选：第 ${set?.set_no ?? '?'} 套 · ${name}`.trim(),
  }
}

/** 旧码的完整选择（**两个都选**才算；否则 `null` —— 半截选择不发给服务端）。 */
export function legacySelection(
  state: ReportState,
): { setId: string; orderItemId: string } | null {
  const { setId, orderItemId } = state.selection
  if (!setId || !orderItemId) return null
  return { setId, orderItemId }
}

/** 「质检」工序（issue #7186：判定即报工 ⇒ 本页不出报工按钮，服务端同款判据）。 */
export function isQualityOperation(operation: ReportOperation | null | undefined): boolean {
  if (!operation) return false
  const name = `${operation.logical_name ?? ''}${operation.operation ?? ''}`
  return name.includes('质检')
}

/**
 * 🔴 **报工按钮能不能出现**（唯一判据；四条硬约束里的 ①②③）。
 *
 * 依次判：未登录 → 本屏已完成 → 旧码未选完 → 工序未确定 → 质检工序。
 * 任一条为真 ⇒ **不出按钮**（按钮与「提交」动作同生同灭，不做"按钮在但点了报错"）。
 */
export function canReport(state: ReportState, view: ReportView | null = state.view): boolean {
  if (!state.worker) return false // ③ 未登录不能报工
  if (!view || view.completed === true) return false
  if (isLegacyScan(view) && (view.needs_selection ?? []).length > 0) return false // ① 旧码未选定
  if (!view.operation?.operation_id) return false // ② 工序未确定不得记账
  if (isQualityOperation(view.operation)) return false
  return true
}

/** 工序显示名（`logical_name` 优先，退化到快照名；都缺 ⇒ `—`）。 */
export function operationName(operation: ReportOperation | null | undefined): string {
  const name = (operation?.logical_name ?? '').trim() || (operation?.operation ?? '').trim()
  return name === '' ? MISSING : name
}

/** 数值 → 纸面文本（缺值 `—`，**不印 0**）。 */
export function qtyText(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return MISSING
  const n = Number(value)
  return Number.isFinite(n) ? String(n) : MISSING
}

/** 本套进度（`{done,total}`；缺任一侧 ⇒ `—`，不拿 0 冒充）。 */
export function progressText(view: ReportView | null | undefined): string {
  const done = view?.set_progress?.done
  const total = view?.set_progress?.total
  if (done === null || done === undefined || total === null || total === undefined) return MISSING
  return `${done}/${total} 道工序已报`
}

/** 帘种（部位种类；缺 ⇒ `—`）。 */
export function kindText(view: ReportView | null | undefined): string {
  const kind = (view?.position?.position_kind ?? '').trim()
  return kind === '' ? MISSING : kind
}

/** 本屏标题：`第 N 套 · 部位名`。 */
export function titleText(view: ReportView | null | undefined): string {
  if (!view) return '扫码报工'
  const setNo = view.set_no === null || view.set_no === undefined ? '?' : String(view.set_no)
  const position = (view.position?.position_name ?? '').trim()
  return `第 ${setNo} 套${position ? ` · ${position}` : ''}`
}

/**
 * 🔴 硬约束 ④：回执文案**只**来自服务端（`next_operation` / `set_completed`）。
 *
 * 前端**不推**下一道 —— 猜错的代价是把下一笔计件记到错的工序上（H5 #4792）。
 */
export function receiptLine(receipt: {
  nextOperation?: ReportOperation | null
  setCompleted?: boolean | null
}): string {
  const next = receipt?.nextOperation
  if (next?.operation_id) return `已报工 · 下一道：${operationName(next)}`
  if (receipt?.setCompleted === true) return '已报工 · 本套工序已全部完成'
  return '已报工'
}

/**
 * 报工回执 → 新状态（**回执驱动**：屏上换成服务端给的下一道 / 已完成）。
 *
 * @param view      回执里的 `next_operation` / `set_completed`（不是重新扫码）
 * @param overrides 回执可能不带完整一屏（如 `set_completed`）⇒ 用原 view 打底
 */
export function applyReceipt(
  state: ReportState,
  receipt: {
    nextOperation?: ReportOperation | null
    setCompleted?: boolean | null
    setProgress?: any
    /** 本笔的成品入库块（`null` / 缺省 ⇒ 保留上一屏的块，不因回执缺键而闪掉） */
    finishedInbound?: FinishedInboundView | null
  },
  message?: string,
): ReportState {
  const base: ReportView = { ...(state.view ?? {}) }
  const next = receipt?.nextOperation ?? null
  const view: ReportView = {
    ...base,
    operation: next,
    alternatives: [],
    needs_selection: [],
    completed: receipt?.setCompleted === true || !next,
    set_completed: receipt?.setCompleted === true,
    next_operation: next,
    set_progress: receipt?.setProgress ?? base.set_progress ?? null,
  }
  return {
    ...state,
    view,
    selection: { setId: null, orderItemId: null },
    mode: 'main',
    submitting: false,
    receipt: receiptLine({ nextOperation: next, setCompleted: receipt?.setCompleted }),
    notice: message ?? null,
    error: null,
    batchNo: null,
    finishedInbound: receipt?.finishedInbound ?? state.finishedInbound,
  }
}

/**
 * 扫一扫的 `result` → token（**三种形态**都认；认不出就原样当短码/单号）。
 *
 * 🔴 **实现只有一份**（issue #7879）：本函数是 `utils/scanInput.ts` 的 `codeFromScanText` 的**转发**
 * —— h5 落地（`?t=`）、小程序扫一扫、小程序码（`scene`）、扫普通链接二维码（`q`）与页面参数
 * 全部收口到同一个解析器，禁止在这里另写一套。
 *
 * | 形态 | 例子 |
 * |---|---|
 * | 短链 | `https://app.migaozn.com/s/ab12cd34` |
 * | 带 t 参数 | `https://app.migaozn.com/b/?t=<token>`（#7879 前的旧落点 `/w/?t=` 同样认） |
 * | 裸短码 / 单号 | `ab12cd34` / `JG-20260901-001` |
 */
export function tokensFromScanResult(text: string | null | undefined): string {
  return codeFromScanText(text)
}
