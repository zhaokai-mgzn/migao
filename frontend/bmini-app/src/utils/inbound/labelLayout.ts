/**
 * 入库标签 **50×30mm 版面**（纯函数，issue #5052 P3；设计 §7.1 / §7.2）
 *
 * 这一层**只算坐标**，不碰 canvas、不碰蓝牙、不发请求 ⇒ 全部判据能在 CI 里跑
 * （`frontend/bmini-app/tests/inbound-label-layout.test.ts`）。
 *
 * ## 三条硬口径（每条都能红）
 *
 * 1. **像素口径不在本文件**：宽/高/有效打宽全部来自 `./truth`（= `print-media.json`）。
 *    本文件里**一个像素字面量都不许有** —— 守卫
 *    `frontend/bmini-app/tests/inbound-print-geometry-single-source.test.ts` 的 C2 会扫本文件。
 * 2. **缺码不画假码**（§7.1）：短码缺失 / 非法 ⇒ `qr = null` + 纸面**可见标注**，
 *    **绝不**用占位串画一张「扫出来是错的」二维码。
 * 3. **长名截断必须可见**（§7.1）：超出宽度的文本**截断 + 省略号**（`truncated: true` 同时进
 *    `warnings`）；**不静默裁切** —— 静默裁切是账实不符的另一种形态。
 *
 * ## 1:1 不缩放不裁切（§7.2 N9）
 *
 * 方案 = 画布就是**有效打印宽 × 纸高**的像素数，所有坐标都在其内、**没有缩放系数**；
 * 二维码按**整数倍点阵**画（`cellPx` 取整），避免非整数倍重采样把码糊掉。
 */
import qrcode from 'qrcode-generator'
import { inboundLabelGeometry, inboundLabelMedia } from './truth'
import { labelCodePayload } from './shortCode'

/** 标签的业务字段（读面 = `GET /api/worker/inbound/labels/{短码}` 的 `InboundLabelView`） */
export interface InboundLabelView {
  shortCode?: string | null
  inboundNo?: string | null
  skuCode?: string | null
  productName?: string | null
  colorName?: string | null
  doorWidth?: string | null
  quantity?: number | string | null
  dyeLot?: string | null
  batchNo?: string | null
  supplier?: string | null
  supplierDocNo?: string | null
  warehouse?: string | null
  inboundDate?: string | null
  printCount?: number | null
}

export interface LabelTextOp {
  kind: 'text'
  text: string
  x: number
  y: number
  fontPx: number
  bold: boolean
  /** 该行的可用宽度（px）——渲染器据此换行/校验，不自己算 */
  maxWidthPx: number
  /** 是否发生了可见截断（省略号已写进 `text`） */
  truncated: boolean
}

export interface LabelRectOp {
  kind: 'rect'
  x: number
  y: number
  w: number
  h: number
  color: string
}

export type LabelPaintOp = LabelTextOp | LabelRectOp

/** 二维码的**点阵**（已定 cellPx，渲染器只填方块，不做缩放） */
export interface LabelQrPlan {
  payload: string
  moduleCount: number
  /** 每个模块的像素边长（整数） */
  cellPx: number
  x: number
  y: number
  sizePx: number
  /** 行优先点阵：`matrix[r * moduleCount + c]` = 1（黑）/ 0（白） */
  matrix: number[]
}

export interface InboundLabelPlan {
  widthPx: number
  heightPx: number
  ops: LabelPaintOp[]
  /** `null` = **未画二维码**（短码缺失 / 非法）—— 纸面另有可见标注，见 `codeText` */
  qr: LabelQrPlan | null
  /** 纸面上的人可读短码（`qr === null` 时是**缺失说明**，不是占位码） */
  codeText: string
  /** 缺码 / 截断这类「必须让操作者知道」的事实（渲染器不吞） */
  warnings: string[]
}

/** 缺码时纸面上的可见标注（设计 §7.1「留空位并标注」） */
export const MISSING_CODE_TEXT = '短码缺失·未出码'

/** 文本宽度估算：CJK（含全角标点）按 1 em，ASCII 按 0.55 em —— 与 canvas `measureText` 同量级 */
export function estimateTextWidth(text: string, fontPx: number): number {
  let width = 0
  for (const ch of text) {
    width += ch.charCodeAt(0) > 0x2e80 ? fontPx : fontPx * 0.55
  }
  return width
}

/**
 * 可见截断：超宽 ⇒ 截断并补 `…`（**永不静默裁切**）。
 * 省略号本身占位，故循环上界是「连省略号也放得下」。
 */
export function fitTextVisible(
  text: string,
  maxWidthPx: number,
  fontPx: number,
): { text: string; truncated: boolean } {
  const raw = String(text ?? '')
  if (estimateTextWidth(raw, fontPx) <= maxWidthPx) return { text: raw, truncated: false }
  const ellipsis = '…'
  const ellipsisWidth = estimateTextWidth(ellipsis, fontPx)
  let out = ''
  for (const ch of raw) {
    if (estimateTextWidth(out + ch, fontPx) + ellipsisWidth > maxWidthPx) break
    out += ch
  }
  return { text: `${out}${ellipsis}`, truncated: true }
}

/** 二维码点阵（`qrcode-generator`；容错级别 M = 标签有磨损也能扫） */
function buildQrMatrix(payload: string): { moduleCount: number; matrix: number[] } {
  const qr = qrcode(0, 'M')
  qr.addData(payload)
  qr.make()
  const moduleCount = qr.getModuleCount()
  const matrix: number[] = []
  for (let row = 0; row < moduleCount; row += 1) {
    for (let col = 0; col < moduleCount; col += 1) {
      matrix.push(qr.isDark(row, col) ? 1 : 0)
    }
  }
  return { moduleCount, matrix }
}

/** 版面栅格（相对量：都是「版心宽/高」的比例，最终像素由几何算出来 —— 本文件不写死像素） */
const GRID = {
  padRatio: 0.021, // ≈8px / 384px
  qrBoxRatio: 0.44, // 二维码方块占版心宽的比例
  qrTopRatio: 0.17,
  textLeftRatio: 0.5,
  nameFontRatio: 0.052, // 相对版心宽
  fieldFontRatio: 0.042,
  codeFontRatio: 0.062,
  lineGapRatio: 0.032,
} as const

/**
 * 生成标签绘制计划。
 *
 * @param view 读面字段（缺字段 ⇒ 该行不画，**不编造**）
 */
export function layoutInboundLabel(view: InboundLabelView): InboundLabelPlan {
  const geometry = inboundLabelGeometry()
  const width = geometry.canvasWidthPx
  const height = geometry.canvasHeightPx
  const pad = Math.round(width * GRID.padRatio)
  const inner = width - pad * 2
  const warnings: string[] = []
  const ops: LabelPaintOp[] = []

  const textLeft = Math.round(width * GRID.textLeftRatio)
  const textMax = width - pad - textLeft
  const nameFont = Math.round(width * GRID.nameFontRatio)
  const fieldFont = Math.round(width * GRID.fieldFontRatio)
  const codeFont = Math.round(width * GRID.codeFontRatio)
  const lineGap = Math.round(height * GRID.lineGapRatio)

  // ── ① 品名（超宽 ⇒ 可见截断）────────────────────────────────────────────────
  const name = fitTextVisible(String(view.productName ?? '').trim() || '未填品名', inner, nameFont)
  if (name.truncated) warnings.push(`品名超宽已截断：${name.text}`)
  ops.push({
    kind: 'text',
    text: name.text,
    x: pad,
    y: pad,
    fontPx: nameFont,
    bold: true,
    maxWidthPx: inner,
    truncated: name.truncated,
  })

  // ── ② 右列字段（缺字段 ⇒ 整行不画）──────────────────────────────────────────
  const fields: string[] = []
  const colorLine = [view.colorName, view.doorWidth].filter((v) => String(v ?? '').trim()).join(' / ')
  if (colorLine) fields.push(`色号 ${colorLine}`)
  if (String(view.quantity ?? '').toString().trim()) fields.push(`米数 ${view.quantity}`)
  if (String(view.skuCode ?? '').trim()) fields.push(`货号 ${view.skuCode}`)
  if (String(view.batchNo ?? '').trim()) fields.push(`批次 ${view.batchNo}`)
  if (String(view.dyeLot ?? '').trim()) fields.push(`缸号 ${view.dyeLot}`)
  if (String(view.supplierDocNo ?? '').trim()) fields.push(`送单 ${view.supplierDocNo}`)
  if (String(view.inboundNo ?? '').trim()) fields.push(`单号 ${view.inboundNo}`)

  const fieldTop = pad + nameFont + lineGap
  fields.forEach((line, index) => {
    const fitted = fitTextVisible(line, textMax, fieldFont)
    if (fitted.truncated) warnings.push(`字段行超宽已截断：${fitted.text}`)
    ops.push({
      kind: 'text',
      text: fitted.text,
      x: textLeft,
      y: fieldTop + index * (fieldFont + Math.round(lineGap * 0.6)),
      fontPx: fieldFont,
      bold: false,
      maxWidthPx: textMax,
      truncated: fitted.truncated,
    })
  })

  // ── ③ 二维码（缺码 ⇒ 不画 + 可见标注）───────────────────────────────────────
  const payload = labelCodePayload(view.shortCode)
  const qrTop = Math.round(height * GRID.qrTopRatio)
  const qrBox = Math.round(width * GRID.qrBoxRatio)
  let qr: LabelQrPlan | null = null
  if (payload) {
    const { moduleCount, matrix } = buildQrMatrix(payload)
    const cellPx = Math.max(1, Math.floor(qrBox / moduleCount))
    const sizePx = cellPx * moduleCount
    if (sizePx < qrBox * 0.6) {
      // 码太密（cell 取整后缩水太多）⇒ 纸面仍按整数倍画，但登记出来
      warnings.push(`二维码点阵偏密：${moduleCount}×${moduleCount} 模块，每模块 ${cellPx}px`)
    }
    qr = { payload, moduleCount, cellPx, x: pad, y: qrTop, sizePx, matrix }
  } else {
    // 🔴 缺码不画假码：留空位 + 可见标注（红证：画占位二维码 ⇒ 判据必红）
    warnings.push('短码缺失或非法：未绘制二维码（不画占位码）')
    const mark = fitTextVisible(MISSING_CODE_TEXT, qrBox, fieldFont)
    ops.push({
      kind: 'rect',
      x: pad,
      y: qrTop,
      w: qrBox,
      h: qrBox,
      color: '#ffffff',
    })
    ops.push({
      kind: 'text',
      text: mark.text,
      x: pad,
      y: qrTop + Math.round(qrBox / 2),
      fontPx: fieldFont,
      bold: false,
      maxWidthPx: qrBox,
      truncated: mark.truncated,
    })
  }

  // ── ④ 人可读短码（纸面降级入口）───────────────────────────────────────────
  const codeRaw = payload ? String(view.shortCode).trim().toUpperCase() : MISSING_CODE_TEXT
  const code = fitTextVisible(codeRaw, inner, codeFont)
  ops.push({
    kind: 'text',
    text: code.text,
    x: pad,
    y: height - pad - codeFont,
    fontPx: codeFont,
    bold: true,
    maxWidthPx: inner,
    truncated: code.truncated,
  })

  return {
    widthPx: width,
    heightPx: height,
    ops,
    qr,
    codeText: code.text,
    warnings,
  }
}

/** 版面声明的纸型（与矩阵同源；渲染器/打印适配层读它，不写 `50mm 30mm` 字面量） */
export function inboundLabelPageSize(): string {
  return inboundLabelMedia().pageSize
}
