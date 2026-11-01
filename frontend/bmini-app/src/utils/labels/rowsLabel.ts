/**
 * **50×70 行式标签**（成品入库标签 / 发货联）的版面与渲染 —— 纯函数 + 一条薄渲染。
 *
 * ## 为什么单独一层
 *
 * 两张纸的**内容来源不同**，但**纸面形态相同**：一个「标题（可选）+ 若干行（标签 / 值）+
 * 可选的短码」。版面 / 换行 / 纸长夹取 / 缺值占位只写一次，两个页面（报工详情、待发货单）
 * 都从这里取 —— 否则第二份版面必然与第一份分叉（同一类缺陷在 `labelPageKit.ts` 的文件头已固化）。
 *
 * ## 纸型真值
 *
 * 宽度 / 像素口径 / 纸长范围**全部**来自 `frontend/admin-web/src/lib/print-media.json` 的
 * `label-50x70`（经 `../inbound/truth` 的 `labelGeometry` / `labelLengthRange` / `labelPaperBox`）。
 * 本文件**一个像素字面量都没有**（守卫 `tests/inbound-print-geometry-single-source.test.ts`
 * 的全仓 `384` 判据会点名任何第二份口径）。
 *
 * ## 三条硬口径
 *
 * 1. **缺值印 `—`**（不是 0、不是空串）：纸面是给车间核对的，空着会被当成「漏印」；
 *    可选行（帘种 / 安装信息 / 备注）由调用方的行清单决定**整行不出现**（不印「帘种 —」白吃行高）；
 * 2. **长内容可见**：单行超宽 ⇒ 可见省略号；可折行行（地址 / 备注）按字数折行；装不下上限纸长 ⇒
 *    停止追加并写 `warnings`（**不静默裁切**）；
 * 3. **预览与打印同一份计划**：`renderRowsLabel` 只把 `layoutRowsLabel` 的结果画出来，不另算一套坐标。
 */
import { estimateTextWidth, fitTextVisible, type InboundLabelPlan, type LabelPaintOp } from '../inbound/labelLayout'
import { renderLabelPlan, type LabelCanvasElementLike, type RenderedLabel } from '../inbound/labelCanvas'
import {
  SHIP_LABEL_MEDIA_ID,
  labelGeometry,
  labelLengthRange,
  labelPaperBox,
} from '../inbound/truth'

/** 纸面的一行（`label` / `value` 均为**服务端或唯一行清单**给的展示串，本层不拼业务字段）。 */
export interface RowsLabelRow {
  key: string
  label: string
  value: string
  /** 地址 / 备注这类可折行；其余行一律单行 + 可见省略号 */
  multiline?: boolean
}

/**
 * 一张 50×70 行式标签的**业务输入**。
 *
 * - `fixedLengthMm`：固定纸长（成品入库标签 = 70mm）；缺省 ⇒ 按内容撑开（发货联，70~150mm）；
 * - `shortCode`：纸面底部的人可读短码（成品入库标签有；发货联没有 ⇒ 不印）。
 */
export interface RowsLabelSpec {
  title?: string | null
  rows: RowsLabelRow[]
  shortCode?: string | null
  fixedLengthMm?: number
}

/** 缺值占位（与发货单纸面 `—` 同口径：**不是** 0、不是空串、不是「未知」）。 */
export const ROWS_LABEL_MISSING = '—'

/** 版面常数（mm）—— 只描述版面，不是像素口径（像素一律从 `truth` 取）。 */
const PADDING_MM = 1.5
const TITLE_LINE_MM = 5.1
const ROW_LINE_MM = 3.5
const ROW_GAP_MM = 0.6
const LABEL_COL_MM = 12
const COL_GAP_MM = 1
const CODE_LINE_MM = 5
/** 底部安全白边（mm）：标签末端（间隙/剥离区）印不出来 ⇒ 纸尾要留白，否则最后一行被切（真机实测 1.5mm 不够） */
const BOTTOM_SAFE_MM = 5

/** 字体（pt）—— 与 `frontend/worker-h5/src/ship-label.css` 的 8pt 正文同档（介质 `minFontPt` 是 9pt 下限值，见下）。 */
const TITLE_PT = 8
const ROW_PT = 8
const CODE_PT = 9

/** pt ⇒ 点阵像素（203dpi 下 8pt ≈ 23px；不写死像素值，跟随介质 dpi）。 */
function fontPxOf(pt: number, dpi: number): number {
  return Math.max(1, Math.round((pt * dpi) / 72))
}

/** 行值：空 / 纯空白 ⇒ `—`（缺值不编造）。 */
export function rowsLabelValue(value: unknown): string {
  const text = value == null ? '' : String(value).trim()
  return text === '' ? ROWS_LABEL_MISSING : text
}

/**
 * 折行：按**字**累加（CJK 全角 ≈ 1em / ASCII ≈ 0.55em，与 `estimateTextWidth` 同一把尺）。
 * 只在 `multiline` 行使用；单行行走 `fitTextVisible`（可见省略号）。
 */
export function wrapRowsLabelText(text: string, maxWidthPx: number, fontPx: number): string[] {
  const raw = String(text ?? '')
  if (raw === '') return ['']
  // 显式换行（地址 / 安装位置 / 备注里可能是多行）**先按行切**：画布 `fillText` 不认 `\n`，
  // 不切会把换行符当成一个「打不出来」的字，纸面上两行粘成一行。
  const lines: string[] = []
  for (const segment of raw.split(/\r?\n/)) {
    if (segment === '') {
      lines.push('')
      continue
    }
    let line = ''
    for (const ch of segment) {
      const candidate = line + ch
      if (line !== '' && estimateTextWidth(candidate, fontPx) > maxWidthPx) {
        lines.push(line)
        line = ch
        continue
      }
      line = candidate
    }
    if (line !== '') lines.push(line)
  }
  return lines.length > 0 ? lines : ['']
}

function textOp(
  text: string,
  x: number,
  y: number,
  fontPx: number,
  maxWidthPx: number,
  bold: boolean,
  truncated: boolean,
): LabelPaintOp {
  return { kind: 'text', text, x, y, fontPx, bold, maxWidthPx, truncated }
}

/**
 * 版面：算出一份**可直接绘制**的计划（画布 = 有效打宽 × 纸长；坐标 1:1）。
 *
 * 行序 = 调用方给的顺序（纸面上从上到下核对的顺序），本层**不重排**。
 */
export function layoutRowsLabel(spec: RowsLabelSpec): InboundLabelPlan {
  const geometry = labelGeometry(SHIP_LABEL_MEDIA_ID)
  const range = labelLengthRange(SHIP_LABEL_MEDIA_ID)
  const dpi = geometry.dpi
  const pxPerMm = geometry.dotsPerMm
  const widthPx = geometry.canvasWidthPx
  const padding = Math.round(PADDING_MM * pxPerMm)
  const contentWidth = widthPx - padding * 2
  const labelColPx = Math.round(LABEL_COL_MM * pxPerMm)
  const colGap = Math.round(COL_GAP_MM * pxPerMm)
  const valueX = padding + labelColPx + colGap
  const valueWidth = Math.max(0, contentWidth - labelColPx - colGap)
  const rowLine = Math.round(ROW_LINE_MM * pxPerMm)
  const rowGap = Math.round(ROW_GAP_MM * pxPerMm)
  const titleLine = Math.round(TITLE_LINE_MM * pxPerMm)
  const codeLine = Math.round(CODE_LINE_MM * pxPerMm)
  const titlePx = fontPxOf(TITLE_PT, dpi)
  const rowPx = fontPxOf(ROW_PT, dpi)
  const codePx = fontPxOf(CODE_PT, dpi)

  const bottomSafe = Math.round(BOTTOM_SAFE_MM * pxPerMm)
  const minHeightPx = spec.fixedLengthMm
    ? Math.round(spec.fixedLengthMm * pxPerMm)
    : Math.round(range.minMm * pxPerMm)
  const maxHeightPx = spec.fixedLengthMm
    ? minHeightPx
    : Math.round(range.maxMm * pxPerMm)

  const ops: LabelPaintOp[] = []
  const warnings: string[] = []
  let y = padding
  // 短码先取出来：它占纸面底部的固定高度，行区必须**先给它留位**（否则码会压在最后一行上）
  const shortCode = spec.shortCode == null ? '' : String(spec.shortCode).trim()
  const codeReserve = shortCode !== '' ? codeLine + rowGap : 0

  const title = spec.title == null ? '' : String(spec.title).trim()
  if (title !== '') {
    const fitted = fitTextVisible(title, contentWidth, titlePx)
    ops.push(textOp(fitted.text, padding, y, titlePx, contentWidth, true, fitted.truncated))
    y += titleLine
  }

  let truncatedByHeight = false
  for (const row of spec.rows ?? []) {
    const label = String(row?.label ?? '').trim()
    const value = rowsLabelValue(row?.value)
    const fittedValue = row.multiline ? null : fitTextVisible(value, valueWidth, rowPx)
    const lines = row.multiline
      ? wrapRowsLabelText(value, valueWidth, rowPx)
      : [fittedValue!.text]
    const truncated = fittedValue?.truncated === true
    const blockHeight = lines.length * rowLine
    // 装不下上限纸长（且要给底部短码留位）⇒ 停止追加并**可见登记**（不静默把后面的行裁掉）
    if (y + blockHeight > maxHeightPx - bottomSafe - codeReserve) {
      truncatedByHeight = true
      break
    }
    lines.forEach((line, index) => {
      if (index === 0 && label !== '') {
        const fittedLabel = fitTextVisible(label, labelColPx, rowPx)
        ops.push(textOp(fittedLabel.text, padding, y, rowPx, labelColPx, false, fittedLabel.truncated))
      }
      ops.push(textOp(line, valueX, y, rowPx, valueWidth, false, truncated))
    })
    y += blockHeight + rowGap
  }
  if (truncatedByHeight) {
    warnings.push('内容超出纸长上限：后面的行未印（请拆单或精简备注）')
  }

  const contentHeightPx = Math.ceil(y + bottomSafe + codeReserve)
  let heightPx = spec.fixedLengthMm
    ? minHeightPx
    : Math.min(Math.max(contentHeightPx, minHeightPx), maxHeightPx)
  if (heightPx < contentHeightPx) {
    warnings.push('内容超出固定纸长：请拆单或精简备注')
  }

  if (shortCode !== '') {
    const textWidth = estimateTextWidth(shortCode, codePx)
    const x = Math.max(padding, Math.round((widthPx - textWidth) / 2))
    const codeY = Math.max(padding, heightPx - bottomSafe - codeLine)
    ops.push(textOp(shortCode, x, codeY, codePx, contentWidth, true, false))
  }

  return {
    widthPx,
    heightPx,
    ops,
    qr: null,
    codeText: shortCode,
    warnings,
  }
}

/** 纸型（mm）：屏幕侧文案 / 判据只读它，不另写一份尺寸。 */
export function rowsLabelPaper(): { widthMm: number; heightMm: number } {
  return labelPaperBox(SHIP_LABEL_MEDIA_ID)
}

/**
 * 渲染一张 50×70 行式标签（预览与送打印**同一份计划**）。
 *
 * @throws 取不到位图 ⇒ 抛错（**不静默打印白图**）
 */
export function renderRowsLabel(
  spec: RowsLabelSpec,
  createCanvas: (widthPx: number, heightPx: number) => LabelCanvasElementLike,
): RenderedLabel {
  return renderLabelPlan(layoutRowsLabel(spec), createCanvas, { requirePixels: true })
}
