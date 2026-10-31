/**
 * 成品入库块（issue #7845 的服务端契约 → bmini 渲染层；issue #8287 补齐手机端）。
 *
 * 数据**全部**来自服务端随扫码 / 报工回执下发的 `finished_inbound`：
 * `{ already, bin_code, inbound_no, label: { rows, short_code }, quality: { result, reason } }`
 * （服务端唯一来源 = `FinishedGoodsService#inboundView`）。
 *
 * 🔴 本层**不拼业务字段**：卡片上的每一行 / 入库单号 / 仓位 / 质检结论都原样取服务端；
 * 这里只做「缺值怎么说」（`未分配` / `—` / 无记录 = 正常）与标签行映射。
 */
import { rowsLabelPaper, type RowsLabelRow, type RowsLabelSpec } from './rowsLabel'

/** 服务端 `label.rows[]` 的一行（标签行文案由服务端给，前端不另起一套中文名）。 */
export interface FinishedInboundLabelRow {
  label?: string | null
  value?: string | null
}

/** 服务端下发的标签块（`FinishedGoodsService#labelOf`）。 */
export interface FinishedInboundLabel {
  rows?: FinishedInboundLabelRow[] | null
  short_code?: string | null
}

/** 质检结论（`QualityCheckService#latest` 的投影；无记录 = `null` = 正常，不是「未检」）。 */
export interface FinishedInboundQuality {
  result?: string | null
  reason?: string | null
}

/** 回执 / 扫码视图里的 `finished_inbound` 块。 */
export interface FinishedInboundView {
  already?: boolean
  bin_code?: string | null
  inbound_no?: string | null
  label?: FinishedInboundLabel | null
  quality?: FinishedInboundQuality | null
}

/**
 * 质检结论词 —— 与 `frontend/worker-h5/src/render.mjs` 的 `QUALITY_LABELS` **同值**：
 * 默认态说「正常」；返工 / 报废照实说，不用「合格」替服务端下结论。
 */
export const FINISHED_QUALITY_LABELS: Record<string, string> = {
  pass: '正常',
  rework: '已记做工返工',
  scrap: '已记报废',
}

/** 卡片标题里的仓位：服务端没给 ⇒ `未分配`（与 H5 同口径；不是「-」也不是空）。 */
export function finishedInboundBinText(view: FinishedInboundView | null | undefined): string {
  const bin = view?.bin_code == null ? '' : String(view.bin_code).trim()
  return bin === '' ? '未分配' : bin
}

/** 质检一行：无记录 = 正常（**不**写「未检」吓人）；有记录 = 词 + 可选原因。 */
export function finishedInboundQualityText(view: FinishedInboundView | null | undefined): string {
  const quality = view?.quality ?? null
  if (!quality) return '正常'
  const key = quality.result == null ? '' : String(quality.result)
  const label = FINISHED_QUALITY_LABELS[key] ?? '已检'
  const reason = quality.reason == null ? '' : String(quality.reason).trim()
  return reason === '' ? label : `${label}（原因：${reason}）`
}

/**
 * 标签行：**原样**取服务端的 `label.rows`（行序 = 服务端顺序；前端不排、不补、不改写）。
 * 只丢掉「连标签名都没有」的残行（服务端异常形态，不能画到纸上）。
 */
export function finishedInboundRows(view: FinishedInboundView | null | undefined): RowsLabelRow[] {
  const rows = Array.isArray(view?.label?.rows) ? view.label.rows : []
  return rows
    .map((row, index) => ({
      key: `server-${index}`,
      label: String(row?.label ?? '').trim(),
      value: String(row?.value ?? ''),
    }))
    .filter((row) => row.label !== '')
}

/** 纸面输入：固定 70mm（成品入库标签不是「按内容撑开」的连续纸） + 服务端短码。 */
export function finishedInboundSpec(view: FinishedInboundView | null | undefined): RowsLabelSpec {
  return {
    rows: finishedInboundRows(view),
    shortCode: view?.label?.short_code ?? null,
    fixedLengthMm: rowsLabelPaper().heightMm,
  }
}
