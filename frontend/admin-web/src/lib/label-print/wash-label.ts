/**
 * 洗水码**精简版位图**（issue #6439）—— 走免驱动直连通道时打在热敏标签上的那一份。
 *
 * ## 为什么是精简版（用户 2026-10-06 选定）
 *
 * 浏览器打印那份（`frontend/admin-web/src/components/production/TaskCardPrint.tsx`）是 **50mm×60mm 全字段面**，
 * 给**标签机 / A4** 用。直连通道打的是**缝在布上的水洗唛**，且常见机型只有 **203dpi**
 * （8 dot/mm，6pt 字 = 2.1mm ⇒ 打出来易糊）⇒ 只印**工人真正要用的三样**：
 * **二维码 + 大字短码 + 件名/部位**。
 *
 * ## 为什么版式是**纯函数**
 *
 * 不纯的那一半（真 canvas）在 jsdom 里**根本跑不了**（本仓没装 `canvas` 包）⇒ 版式若写在绘制回调里，
 * 就只能靠「跑起来看看」验证。⇒ 拆成：{@link layoutWashLabel} **纯函数算位置与字号**（可断言），
 * {@link paintWashLabel} **只照单绘制**（可用假 ctx 断言调用面）。
 *
 * ## 硬约束
 *
 * - **几何由机器自报值推出**（`printerDPI` / `printerWidth`）——「不做打印机定制功能」的落点：
 *   接别家机器**不改码**。写死机型口径 ⇒ 守卫判红；兜底值从介质矩阵取。
 * - **短码是功能件、永不被裁**：窄纸靠**缩字号**活下来；窄到连最小字号都放不下 ⇒ **显式抛错**
 *   （fail-closed），绝不静默裁掉。短码是设计里明写的手输降级入口
 *   （`docs/design/worker-h5-scan-and-report.md` §1.4「不是可选项」）。
 * - **件名放不下 ⇒ 显式省略号**（看得见的截断），不是静默切掉。
 */

import { printDotGeometry } from '@/lib/print-media'

/** 渲染一张洗水码需要的**数据**（与 React 无关：页面把 `ProductionPosition` 映射成它） */
export interface WashLabelInput {
  /** 二维码内容（该部位自己的 `scan_url ?? part_token`）；`null` ⇒ **不画假码** */
  qrValue: string | null
  /** 人可读短码（**大字**、纸面的手输降级入口） */
  shortCode: string
  /** 件名（部位名优先，退回商品名） */
  pieceName?: string
  /** 部位类型（如「布帘」）—— 与件名拼一行 */
  positionKind?: string
}

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

/** 兜底口径的**唯一真值源** = `lib/print-media.json` 的 `label-50x60.dotGeometry`（本文件不写第二份） */
const FALLBACK_GEOMETRY = printDotGeometry('label-50x60')

/** 未连上机器时的通用兜底（**不是**本文件的口径：连上后立刻按机器自报值重算） */
export const LABEL_DPI_DEFAULT = FALLBACK_GEOMETRY.dpi
export const LABEL_HEAD_DOTS_DEFAULT = FALLBACK_GEOMETRY.headWidthPx
/** 水洗唛默认长度（mm）—— 长度随纸卷，页面可覆盖 */
export const WASH_LABEL_DEFAULT_LENGTH_MM = 40
/** 短码的最小字号（mm）：再小就失去「手输降级入口」的意义，宁可报错 */
export const WASH_LABEL_MIN_SHORT_CODE_FONT_MM = 2.5

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

/**
 * 画布几何：**由机器自报值推出**（写死机型口径 ⇒ 守卫判红；兜底值来自介质矩阵 `dotGeometry`）。
 *
 * @param printer   机器自报参数（未连上传 null/undefined）
 * @param paperWidthMm 纸宽（mm）；给了就取「纸宽 × dpmm」与**打印头宽度**的**较小者**（不越纸、不越头）
 * @param labelLengthMm 标签长度（mm）
 */
export function resolveLabelGeometry(
  printer?: LabelPrinterInfoLike | null,
  paperWidthMm?: number | null,
  labelLengthMm: number = WASH_LABEL_DEFAULT_LENGTH_MM,
): LabelDotGeometry {
  const dpi = positive(printer?.printerDPI) ?? LABEL_DPI_DEFAULT
  const headDots = positive(printer?.printerWidth) ?? LABEL_HEAD_DOTS_DEFAULT
  const dpmm = dpi / 25.4
  const byPaper = positive(paperWidthMm)
  return {
    dpmm,
    widthPx: byPaper ? Math.min(Math.round(byPaper * dpmm), headDots) : headDots,
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

export interface WashLabelLayout {
  geometry: LabelDotGeometry
  margin: number
  /** `null` = 该部位无码（**不画假码**，短码位置上移） */
  qr: LabelRect | null
  shortCode: LabelText
  pieceName: LabelText | null
}

/**
 * 版式（**纯函数**）：二维码居中在上、大字短码居中、件名/部位在下。
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
  const margin = Math.round(mm(2))
  const innerW = widthPx - 2 * margin
  if (innerW <= 0) throw new WashLabelLayoutError(`纸宽 ${widthPx}px 放不下边距 ${margin}px`)

  const qrValue = (input.qrValue ?? '').trim()
  let qr: LabelRect | null = null
  let cursorY = margin
  if (qrValue) {
    const size = Math.max(
      1,
      Math.min(Math.round(mm(14)), innerW, Math.round((heightPx - 2 * margin) * 0.5)),
    )
    qr = { x: Math.round((widthPx - size) / 2), y: margin, size }
    cursorY = margin + size + Math.round(mm(1.5))
  }

  const codeText = (input.shortCode ?? '').trim() || '—'
  const fit = fitFontSize(codeText, innerW, mm(5), mm(WASH_LABEL_MIN_SHORT_CODE_FONT_MM), measure)
  if (!fit.fits) {
    throw new WashLabelLayoutError(
      `短码「${codeText}」在 ${widthPx}px 纸宽下放不下（最小字号 ${Math.round(mm(WASH_LABEL_MIN_SHORT_CODE_FONT_MM))}px）`,
    )
  }
  const codeW = measure(codeText, fit.fontPx)
  const shortCode: LabelText = {
    text: codeText,
    fontPx: fit.fontPx,
    x: Math.round((widthPx - codeW) / 2),
    y: cursorY,
  }

  const piece = [input.positionKind, input.pieceName]
    .map((part) => (part ?? '').trim())
    .filter((part) => part !== '')
    .join(' · ')
  let pieceName: LabelText | null = null
  if (piece) {
    const fontPx = Math.max(1, Math.round(mm(2.5)))
    const text = ellipsize(piece, innerW, fontPx, measure)
    pieceName = {
      text,
      fontPx,
      x: Math.round((widthPx - measure(text, fontPx)) / 2),
      y: Math.round(cursorY + fit.fontPx + mm(1.5)),
    }
  }

  return { geometry, margin, qr, shortCode, pieceName }
}

/** 绘制上下文的最小面（只取本模块要用的那几个 —— 假 ctx 因此可测） */
export interface WashLabelPaintContext {
  /** 真 `CanvasRenderingContext2D` 的 `fillStyle` 是联合类型 ⇒ 这里按**可赋值**的最宽面声明 */
  fillStyle: string | CanvasGradient | CanvasPattern
  font: string
  textAlign: CanvasTextAlign
  textBaseline: CanvasTextBaseline
  fillRect(x: number, y: number, w: number, h: number): void
  fillText(text: string, x: number, y: number): void
  drawImage(image: CanvasImageSource, dx: number, dy: number, dw: number, dh: number): void
}

/**
 * 执行层：**只照单绘制**，不再二次排版（版式已在 {@link layoutWashLabel} 算好）。
 *
 * ⚠️ 热敏纸必须**先铺白底**：不铺 = 整幅反色（打出黑底废纸）。
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
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'

  if (layout.qr && qrImage) {
    ctx.drawImage(qrImage, layout.qr.x, layout.qr.y, layout.qr.size, layout.qr.size)
  }
  ctx.font = `bold ${layout.shortCode.fontPx}px ui-monospace, SFMono-Regular, Menlo, monospace`
  ctx.fillText(layout.shortCode.text, layout.shortCode.x, layout.shortCode.y)
  if (layout.pieceName) {
    ctx.font = `${layout.pieceName.fontPx}px -apple-system, "PingFang SC", sans-serif`
    ctx.fillText(layout.pieceName.text, layout.pieceName.x, layout.pieceName.y)
  }
}

/** 部位（`ProductionPosition`）的**窄读面**：只取本模块要用的键，避免把整包类型拖进来 */
export interface WashLabelPositionLike {
  scan_url?: string | null
  part_token?: string | null
  part_short_code?: string | null
  position_name?: string | null
  product_name?: string | null
  position_kind?: string | null
}

/**
 * 部位 ⇒ 洗水码数据（**单一处映射**：页面与测试都走它，不各写一份）。
 *
 * - 码 = `scan_url ?? part_token`，两者都没有 ⇒ `null`（**不画假码**，与 `TaskCardPrint` 同口径）
 * - 短码缺失 ⇒ `'—'`（纸面如实显示「没有」，**不编造**）
 */
export function toWashLabelInputs(positions?: WashLabelPositionLike[] | null): WashLabelInput[] {
  return (positions ?? []).map((position) => ({
    qrValue: position.scan_url ?? position.part_token ?? null,
    shortCode: (position.part_short_code ?? '').trim() || '—',
    pieceName: (position.position_name || position.product_name || '').trim(),
    positionKind: (position.position_kind ?? '').trim(),
  }))
}
