/**
 * 水洗唛**位图版式**（issue #6439 建立 → **issue #6656 改判：与系统打印同一份纸面**）。
 *
 * ## 为什么改判（用户 2026-10-10 逐字）
 *
 * 「**直连打印机打印的样式和水洗唛预览打印的样式完全不一样，能不能做成一样的**」
 * ⇒ 本版把 #6439 的**精简版**（二维码 + 大字短码 + 件名/部位）换成**与 `TaskCardPrint.tsx`
 * 同一份纸面**：同一份有序行清单（`lib/wash-label-content.ts` 的 `washLabelRows` = 唯一内容真值）、
 * 同一份介质（`label-50x60`）、同一套字号口径（正文 = 介质矩阵的 `minFontPt`、表头 7pt、短码 8pt、行高 1.2）。
 *
 * ## 两条通道**唯一不可统一**的一处：纸的物理宽度
 *
 * 预览印在 **50mm** 纸上，而标签机打印头只有 **384 点 = 48mm**
 * （`lib/print-media.json` 的 `label-50x60.dotGeometry` 已登记「纸宽 50mm ⇒ 400px，打印头只有 384px
 * ⇒ 右侧约 2mm 打不到」）⇒ 位图最宽 48mm。**字段一致、整体窄 2mm，这是物理上限**。
 * 清晰度同理如实登记：203dpi = 8 点/mm，6pt 汉字约 17 点高 —— 能画，但比浏览器渲染的 6pt 毛糙。
 *
 * ## 为什么版式是**纯函数**
 *
 * 不纯的那一半（真 canvas）在 jsdom 里**根本跑不了**（本仓没装 `canvas` 包）⇒ 版式若写在绘制回调里，
 * 就只能靠「跑起来看看」验证。⇒ 拆成：{@link layoutWashLabel} **纯函数算位置与字号**（可断言），
 * {@link paintWashLabel} **只照单绘制**（可用假 ctx 断言调用面）。
 *
 * ## 硬约束（与 #6439 一字未动）
 *
 * - **几何由机器自报值 + 介质矩阵推出**（`printerDPI` / `printerWidth` / `pageBoxMm`）——
 *   「不做打印机定制功能」的落点：接别家机器**不改码**，写死机型口径 ⇒ 守卫判红。
 * - **短码是功能件、永不被裁**：窄纸靠**缩字号**活下来；窄到连最小字号都放不下 ⇒ **显式抛错**
 *   （fail-closed），绝不静默裁掉。短码是设计里明写的手输降级入口
 *   （`docs/design/worker-h5-scan-and-report.md` §1.4「不是可选项」）。
 * - **文字块装不下 ⇒ 只裁文字块**（表头与底部码 / 短码 `shrink-0`，与 `.task-card-label` 的
 *   flex 布局同口径）。
 */
import { printBodyFontPt, printDotGeometry, printPageBoxMm, type PrintMediaId } from '@/lib/print-media'
import type { WashLabelInput, WashLabelRow } from '@/lib/wash-label-content'

export type { WashLabelInput, WashLabelRow }

/** 两条通道**同一份介质**（系统打印的 `@page` 与直连的画布都指它）—— 这是 #6656 的核心 */
export const WASH_LABEL_MEDIA: PrintMediaId = 'label-50x60'

/** 机器自报的打印参数（`getPrinterInfo()` 的子集） */
export interface LabelPrinterInfoLike {
  printerDPI?: number
  printerWidth?: number
}

export interface LabelDotGeometry {
  /** 每毫米点数（= dpi / 25.4） */
  dpmm: number
  widthPx: number
  heightPx: number
}

/** 兜底口径的**唯一真值源** = `lib/print-media.json` 的 `label-50x60`（本文件不写第二份） */
const FALLBACK_GEOMETRY = printDotGeometry(WASH_LABEL_MEDIA)
const FALLBACK_BOX = printPageBoxMm(WASH_LABEL_MEDIA)

/** 未连上机器时的通用兜底（**不是**本文件的口径：连上后立刻按机器自报值重算） */
export const LABEL_DPI_DEFAULT = FALLBACK_GEOMETRY.dpi
export const LABEL_HEAD_DOTS_DEFAULT = FALLBACK_GEOMETRY.headWidthPx
/** 纸宽 / 纸长（mm）—— 取自介质矩阵（`label-50x60` = 50mm × 60mm），本文件不写第二份 */
export const WASH_LABEL_DEFAULT_WIDTH_MM = FALLBACK_BOX.widthMm
export const WASH_LABEL_DEFAULT_LENGTH_MM = FALLBACK_BOX.heightMm
/** 短码的最小字号（mm）：再小就失去「手输降级入口」的意义，宁可报错 */
export const WASH_LABEL_MIN_SHORT_CODE_FONT_MM = 2.5

/** 标签本体内边距（mm）—— 与 `.task-card-label { padding: 1.2mm }` 同一口径 */
const LABEL_PADDING_MM = 1.2
/** 正文行高倍数 —— 与 `.task-card-label { line-height: 1.2 }` 同一口径 */
const LABEL_LINE_HEIGHT = 1.2
/** 表头（加工单号）字号（pt）—— 与 `.task-card-label` 的 `text-[7pt]` 同一口径 */
const LABEL_HEADER_FONT_PT = 7
/** 底部人可读短码字号（pt）—— 与 `text-[8pt] font-bold` 同一口径 */
const LABEL_SHORT_CODE_FONT_PT = 8
/** 二维码边长（CSS px）—— 与 `QRCodeSVG size={45}` 同一口径（1 CSS px = 1/96 英寸） */
const LABEL_QR_CSS_PX = 45
const CSS_PX_TO_MM = 25.4 / 96
/** 缺码时占位方框的边长（mm）—— 与 `h-[12mm] w-[12mm]` 同一口径 */
const LABEL_QR_PLACEHOLDER_MM = 12
/** 占位框内文案字号（pt）—— 与 `text-[5pt]` 同一口径 */
const LABEL_QR_PLACEHOLDER_FONT_PT = 5
/** 二维码与右侧文字的间距（mm）—— 与 `gap-[1mm]` 同口径 */
const LABEL_QR_GAP_MM = 1
/** 表头与正文块 / 正文块与底部行的间距（mm）—— 与 `mt-[0.5mm]` 同口径 */
const LABEL_BLOCK_GAP_MM = 0.5

/** 缺码时的缺省占位文案（与 `TaskCardPrint` 的缺省一致：**不谎称**「已撤销」） */
export const WASH_LABEL_QR_PLACEHOLDER_HINT = '待生成'

export class WashLabelLayoutError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'WashLabelLayoutError'
  }
}

/** 量字函数（注入：真机走 canvas `measureText`，测试走确定性替身） */
export type TextMeasure = (text: string, fontPx: number) => number

const positive = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : undefined

/** pt ⇒ 点阵像素（1pt = 1/72 英寸） */
const ptToPx = (pt: number, dpmm: number): number => Math.max(1, Math.round((pt / 72) * 25.4 * dpmm))

/**
 * 画布几何：**由机器自报值 + 介质矩阵推出**（写死机型口径 ⇒ 守卫判红；兜底值取矩阵）。
 *
 * @param printer   机器自报参数（未连上传 null/undefined ⇒ 用矩阵兜底）
 * @param paperWidthMm 纸宽（mm）；取「纸宽 × dpmm」与**打印头宽度**的**较小者**（不越纸、不越头）
 * @param labelLengthMm 标签长度（mm）；缺省 = 介质矩阵的纸长（`label-50x60` = 60mm）
 */
export function resolveLabelGeometry(
  printer?: LabelPrinterInfoLike | null,
  paperWidthMm?: number | null,
  labelLengthMm: number = WASH_LABEL_DEFAULT_LENGTH_MM,
): LabelDotGeometry {
  const dpi = positive(printer?.printerDPI) ?? LABEL_DPI_DEFAULT
  const headDots = positive(printer?.printerWidth) ?? LABEL_HEAD_DOTS_DEFAULT
  const dpmm = dpi / 25.4
  const byPaper = positive(paperWidthMm) ?? WASH_LABEL_DEFAULT_WIDTH_MM
  return {
    dpmm,
    widthPx: Math.min(Math.round(byPaper * dpmm), headDots),
    heightPx: Math.round((positive(labelLengthMm) ?? WASH_LABEL_DEFAULT_LENGTH_MM) * dpmm),
  }
}

/** 逐级缩小字号直到放得下；返回是否真的放得下（**不静默**：调用方据此决定抛错还是接着排） */
export function fitFontSize(
  text: string,
  maxW: number,
  startPx: number,
  minPx: number,
  measure: TextMeasure,
): { fontPx: number; fits: boolean } {
  const floor = Math.max(1, Math.round(minPx))
  let fontPx = Math.max(floor, Math.round(startPx))
  while (fontPx > floor && measure(text, fontPx) > maxW) fontPx -= 1
  return { fontPx, fits: measure(text, fontPx) <= maxW }
}

/** 放不下就**看得见地**截断（省略号收尾） */
export function ellipsize(text: string, maxW: number, fontPx: number, measure: TextMeasure): string {
  if (measure(text, fontPx) <= maxW) return text
  let cut = text
  while (cut.length > 0 && measure(`${cut}…`, fontPx) > maxW) cut = cut.slice(0, -1)
  return `${cut}…`
}

/**
 * 按**字**折行（中文没有空格可断）—— 返回该行预算内**已切好**的文本数组。
 *
 * `maxLines` 是行数预算：折到第 `maxLines` 行还没完 ⇒ 最后一行以**省略号**收尾
 * （看得见的截断，**不静默吞字**）。
 */
export function wrapText(
  text: string,
  maxW: number,
  fontPx: number,
  measure: TextMeasure,
  maxLines = 1,
): string[] {
  const source = text.trim()
  if (source === '') return []
  const budget = Math.max(1, Math.floor(maxLines))
  const lines: string[] = []
  let current = ''
  let index = 0
  for (; index < source.length; index += 1) {
    const next = current + source[index]
    if (current !== '' && measure(next, fontPx) > maxW) {
      // `current` 已经是**最后一行**（预算用完）⇒ 余下的全部交给省略号
      if (lines.length + 1 === budget) break
      lines.push(current)
      current = source[index]
    } else {
      current = next
    }
  }
  if (index >= source.length) {
    if (current !== '') lines.push(current)
    return lines
  }
  lines.push(ellipsize(`${current}${source.slice(index)}`, maxW, fontPx, measure))
  return lines
}

export interface LabelRect {
  x: number
  y: number
  size: number
}

export interface LabelText {
  text: string
  x: number
  y: number
  fontPx: number
}

/** 缺码（或位图缺失）时的占位框：**看得见**的「这里本来有码」，不是留白也不是假码 */
export interface LabelPlaceholder {
  rect: LabelRect
  /** 框内文案（已切好行、水平居中）；空数组 = 只画框 */
  lines: LabelText[]
}

export interface WashLabelLayout {
  geometry: LabelDotGeometry
  margin: number
  /** 表头（加工单号，7pt 粗体）；缺 ⇒ `null` */
  header: LabelText | null
  /** 正文块（可裁区）：已切好的行，逐行带位置与字号 */
  lines: LabelText[]
  /** 二维码位（有码时）；无码 ⇒ `null`（**不画假码**） */
  qr: LabelRect | null
  /** 无码时的占位框（虚线方框 + 占位文案） */
  qrPlaceholder: LabelPlaceholder | null
  /** 「扫码报工」小字（二维码右侧）—— 恒有（位图与系统打印同口径，不留白） */
  qrNote: LabelText
  /** 人可读短码（**永不被裁**） */
  shortCode: LabelText
}

/** 占位框内的文案行（居中，按框宽折行，最多 3 行） */
function placeholderHintLines(
  hint: string,
  x: number,
  y: number,
  size: number,
  dpmm: number,
  measure: TextMeasure,
): LabelText[] {
  const fontPx = ptToPx(LABEL_QR_PLACEHOLDER_FONT_PT, dpmm)
  const padding = Math.round(size * 0.1)
  const centerX = x + Math.round(size / 2)
  const step = Math.round(fontPx * LABEL_LINE_HEIGHT)
  const lines = wrapText(hint, size - 2 * padding, fontPx, measure, 3)
  const top = y + Math.max(0, Math.round((size - lines.length * step) / 2))
  return lines.map((text, index) => ({ text, x: centerX, y: top + index * step, fontPx }))
}

/**
 * 版式（**纯函数**）：表头在上、正文块居中、底部 `shrink-0` 行 = 二维码 + 「扫码报工」 + 大字短码。
 *
 * @throws WashLabelLayoutError 短码在最小字号下仍放不下（fail-closed，**不静默裁**）
 */
export function layoutWashLabel(
  input: WashLabelInput,
  geometry: LabelDotGeometry,
  measure: TextMeasure,
): WashLabelLayout {
  const { dpmm, widthPx, heightPx } = geometry
  const mm = (value: number) => value * dpmm
  const margin = Math.round(mm(LABEL_PADDING_MM))
  const innerW = widthPx - 2 * margin
  if (innerW <= 0) throw new WashLabelLayoutError(`纸宽 ${widthPx}px 放不下边距 ${margin}px`)

  const bodyFontPx = ptToPx(printBodyFontPt(WASH_LABEL_MEDIA), dpmm)
  const lineStep = Math.round(bodyFontPx * LABEL_LINE_HEIGHT)
  const headerFontPx = ptToPx(LABEL_HEADER_FONT_PT, dpmm)
  const gap = Math.round(mm(LABEL_BLOCK_GAP_MM))

  // ① 表头（`shrink-0`）
  const orderNo = (input.processingOrderNo ?? '').trim()
  const header: LabelText | null =
    orderNo === '' ? null : { text: orderNo, x: margin, y: margin, fontPx: headerFontPx }

  // ② 底部行（`shrink-0`）：二维码（或占位框）+ 「扫码报工」 + 大字短码
  const qrValue = (input.qrValue ?? '').trim()
  const qrSize = Math.round(mm(LABEL_QR_CSS_PX * CSS_PX_TO_MM))
  const placeholderSize = Math.round(mm(LABEL_QR_PLACEHOLDER_MM))
  const footerSize = qrValue === '' ? placeholderSize : qrSize
  const footerTop = heightPx - margin - footerSize

  // ③ 正文块（`flex-1 min-h-0 overflow-hidden`）：**空间不够时只裁这里**
  const blockTop = margin + (header ? Math.round(headerFontPx * LABEL_LINE_HEIGHT) + gap : 0)
  const blockBottom = footerTop - gap
  const lines: LabelText[] = []
  let cursor = blockTop
  let exhausted = false
  for (const row of input.rows ?? []) {
    if (exhausted) break
    for (const text of wrapText(row.text, innerW, bodyFontPx, measure, row.maxLines)) {
      if (cursor + lineStep > blockBottom) {
        exhausted = true
        break
      }
      lines.push({ text, x: margin, y: cursor, fontPx: bodyFontPx })
      cursor += lineStep
    }
  }

  // ④ 短码：**永不被裁** —— 窄纸缩字号；窄到最小字号仍放不下 ⇒ 显式抛错（fail-closed）
  const codeText = (input.shortCode ?? '').trim() || '—'
  const textX = margin + footerSize + Math.round(mm(LABEL_QR_GAP_MM))
  const codeMaxW = widthPx - margin - textX
  const fit = fitFontSize(
    codeText,
    codeMaxW,
    ptToPx(LABEL_SHORT_CODE_FONT_PT, dpmm),
    Math.round(mm(WASH_LABEL_MIN_SHORT_CODE_FONT_MM)),
    measure,
  )
  if (!fit.fits) {
    throw new WashLabelLayoutError(
      `短码「${codeText}」在 ${widthPx}px 纸宽下放不下（最小字号 ${Math.round(mm(WASH_LABEL_MIN_SHORT_CODE_FONT_MM))}px）`,
    )
  }
  const shortCode: LabelText = { text: codeText, x: textX, y: footerTop + lineStep, fontPx: fit.fontPx }
  const qrNote: LabelText = { text: '扫码报工', x: textX, y: footerTop, fontPx: bodyFontPx }

  const qr: LabelRect | null = qrValue === '' ? null : { x: margin, y: footerTop, size: qrSize }
  const qrPlaceholder: LabelPlaceholder | null =
    qrValue !== ''
      ? null
      : {
          rect: { x: margin, y: footerTop, size: placeholderSize },
          lines: placeholderHintLines(
            (input.qrPlaceholderHint ?? '').trim() || WASH_LABEL_QR_PLACEHOLDER_HINT,
            margin,
            footerTop,
            placeholderSize,
            dpmm,
            measure,
          ),
        }

  return { geometry, margin, header, lines, qr, qrPlaceholder, qrNote, shortCode }
}

/** 绘制上下文的最小面（只取本模块要用的那几个 —— 假 ctx 因此可测） */
export interface WashLabelPaintContext {
  /** 真 `CanvasRenderingContext2D` 的 `fillStyle` 是联合类型 ⇒ 这里按**可赋值**的最宽面声明 */
  fillStyle: string | CanvasGradient | CanvasPattern
  strokeStyle: string | CanvasGradient | CanvasPattern
  font: string
  textAlign: CanvasTextAlign
  textBaseline: CanvasTextBaseline
  lineWidth: number
  fillRect(x: number, y: number, w: number, h: number): void
  strokeRect(x: number, y: number, w: number, h: number): void
  fillText(text: string, x: number, y: number): void
  drawImage(image: CanvasImageSource, dx: number, dy: number, dw: number, dh: number): void
  /** 虚线占位框用（真 canvas 有；假 ctx 可省 ⇒ 可选调用） */
  setLineDash?(segments: number[]): void
}

/** 正文字族（与 `.task-card-label` 的默认无衬线栈同口径：中文优先系统字体） */
const BODY_FONT = '-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif'
/** 短码字族（与 `font-mono` 同口径） */
const MONO_FONT = 'ui-monospace, SFMono-Regular, Menlo, monospace'

/**
 * 执行层：**只照单绘制**，不再二次排版（版式已在 {@link layoutWashLabel} 算好）。
 *
 * - 热敏纸必须**先铺白底**：不铺 = 整幅反色（打出黑底废纸）。
 * - **有码才 `drawImage`**；无码（或位图缺失）⇒ 画**虚线占位框**（不画假码，也不静默留白）。
 */
export function paintWashLabel(
  ctx: WashLabelPaintContext,
  layout: WashLabelLayout,
  qrImage: CanvasImageSource | null,
): void {
  const { widthPx, heightPx } = layout.geometry
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, widthPx, heightPx)

  ctx.fillStyle = '#000000'
  ctx.strokeStyle = '#000000'
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'

  if (layout.header) {
    ctx.font = `bold ${layout.header.fontPx}px ${BODY_FONT}`
    ctx.fillText(layout.header.text, layout.header.x, layout.header.y)
  }
  for (const line of layout.lines) {
    ctx.font = `${line.fontPx}px ${BODY_FONT}`
    ctx.fillText(line.text, line.x, line.y)
  }

  if (layout.qr && qrImage) {
    ctx.drawImage(qrImage, layout.qr.x, layout.qr.y, layout.qr.size, layout.qr.size)
  } else if (layout.qrPlaceholder) {
    const { rect, lines } = layout.qrPlaceholder
    ctx.lineWidth = 1
    ctx.setLineDash?.([2, 2])
    ctx.strokeRect(rect.x + 0.5, rect.y + 0.5, rect.size - 1, rect.size - 1)
    ctx.setLineDash?.([])
    ctx.textAlign = 'center'
    for (const line of lines) {
      ctx.font = `${line.fontPx}px ${BODY_FONT}`
      ctx.fillText(line.text, line.x, line.y)
    }
    ctx.textAlign = 'left'
  }

  ctx.font = `${layout.qrNote.fontPx}px ${BODY_FONT}`
  ctx.fillText(layout.qrNote.text, layout.qrNote.x, layout.qrNote.y)
  ctx.font = `bold ${layout.shortCode.fontPx}px ${MONO_FONT}`
  ctx.fillText(layout.shortCode.text, layout.shortCode.x, layout.shortCode.y)
}
