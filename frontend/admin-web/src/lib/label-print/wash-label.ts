/**
 * 水洗唛**位图版式**（issue #6439 建立 → #6656 与系统打印同一份纸面 → **#7816 固定纸型 50×150**）。
 *
 * ## 与系统打印的关系（issue #6656 的核心，别改回去）
 *
 * 用户 2026-10-10 逐字：「**直连打印机打印的样式和水洗唛预览打印的样式完全不一样，能不能做成一样的**」
 * ⇒ 本模块与 `frontend/admin-web/src/components/production/TaskCardPrint.tsx` 读**同一份**：
 * 同一份有序行清单（`lib/wash-label-content.ts` 的 `washLabelRows` = 唯一内容真值）、
 * 同一份介质（`label-50x150`）、同一份字号口径（`lib/label-print/wash-label-metrics.ts`）。
 * 本文件只负责**排版**（CSS 与 canvas 是两套排版引擎）。
 *
 * ## 两条通道**唯一不可统一**的一处：纸的物理宽度
 *
 * 预览印在 **50mm** 纸上，而标签机打印头只有 **384 点 = 48mm**
 * （`lib/print-media.json` 的 `label-50x150.dotGeometry` 已登记「纸宽 50mm ⇒ 400px，打印头只有 384px
 * ⇒ 右侧约 2mm 打不到」）⇒ 位图最宽 48mm。**字段一致、整体窄 2mm，这是物理上限**。
 * 清晰度同理如实登记：203dpi = 8 点/mm，12pt 汉字约 34 点高 —— 能画，但比浏览器渲染的 12pt 毛糙。
 *
 * ## 本版（issue #7816 → **issue #7833**，2026-10-26 用户逐字）
 *
 * - 「水洗唛长度不足，设置为打印50*150」⇒ 纸型固定 50mm × 150mm（`pageBoxMm.heightPx` = 1200）；
 * - 「字体还是太小，可以再大一点」⇒ 正文 9pt → **12pt**（抬头 14pt / 副标题 10pt）；
 * - 「二维码放到底部居中」「移除扫码报工和短码文字」「二维码可以放大一点」⇒ 底部只有**居中**二维码
 *   （80 CSS px = 21.17mm），不再画短码与说明字；
 * - **issue #7833**：「打印后的结果出现了文字缩写…自动去换行打印」⇒ 正文行**不再按行数预算以省略号收尾**
 *   （`washLabelRows` 已无 `maxLines`）、抬头也改为折行；「头尾加下虚线」⇒ 起初上下各一条，
 *   2026-10-26 后续裁定「水洗唛的顶部虚线移除掉」⇒ **只留底部一条**（issue #7839）。
 *
 * ⚠️ **短码退场是有意接受的缺口**：`docs/design/worker-h5-scan-and-report.md` §1.4 原把「人可读短码」
 * 定为"不是可选项"的手输降级入口；2026-10-26 用户明确要求移除。⇒ 纸上不再有手输码，
 * 扫不出码时走屏幕/重新出码。**不是漏画**，别"顺手加回"。
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
 * - **文字块装不下 ⇒ 只裁文字块**（底部码 `shrink-0`，与 `.task-card-label` 的 flex 布局同口径）。
 *   🔴 **issue #7833 起不再有"看得见的省略号"**：行不设行数预算 ⇒ 折行印全文；纸高真的不够时，
 *   裁切发生在**块的边界**（不吞半句），并由系统打印通道的「打印预览纸面自检」如实报出
 *   「内容 Xmm > 可用 Ymm」——预览是两条通道共同的**事前**出口。
 */
import { printDotGeometry, printPageBoxMm, type PrintMediaId } from '@/lib/print-media'
import { WASH_LABEL_COMPANY_SUBTITLE, type WashLabelInput, type WashLabelRow } from '@/lib/wash-label-content'
// 🔴 版面度量的**唯一一份**（issue #7776 建立）：字号 / 行高 / 内边距 / 二维码 / 块间距全在
// `wash-label-metrics` —— 系统打印的 CSS 与画布通道读同一份，改一处另一处不会静默漂移。
import {
  WASH_LABEL_BLOCK_GAP_MM as LABEL_BLOCK_GAP_MM,
  WASH_LABEL_BODY_FONT_PT as LABEL_BODY_FONT_PT,
  WASH_LABEL_COMPANY_FONT_PT as LABEL_COMPANY_FONT_PT,
  WASH_LABEL_COMPANY_SUBTITLE_FONT_PT as LABEL_COMPANY_SUBTITLE_FONT_PT,
  WASH_LABEL_LINE_HEIGHT as LABEL_LINE_HEIGHT,
  WASH_LABEL_PADDING_MM as LABEL_PADDING_MM,
  WASH_LABEL_QR_CSS_PX as LABEL_QR_CSS_PX,
  WASH_LABEL_QR_TEXT_GAP_LINES as LABEL_QR_TEXT_GAP_LINES,
  WASH_LABEL_BOTTOM_CLEARANCE_MM as LABEL_BOTTOM_CLEARANCE_MM,
  WASH_LABEL_QR_PLACEHOLDER_FONT_PT,
  WASH_LABEL_QR_PLACEHOLDER_MM as LABEL_QR_PLACEHOLDER_MM,
} from './wash-label-metrics'

export type { WashLabelInput, WashLabelRow }

/** 两条通道**同一份介质**（系统打印的 `@page` 与直连的画布都指它）—— 这是 #6656 的核心 */
export const WASH_LABEL_MEDIA: PrintMediaId = 'label-50x150'

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

/** 兜底口径的**唯一真值源** = `lib/print-media.json` 的 `label-50x150`（本文件不写第二份） */
const FALLBACK_GEOMETRY = printDotGeometry(WASH_LABEL_MEDIA)
const FALLBACK_BOX = printPageBoxMm(WASH_LABEL_MEDIA)

/** 未连上机器时的通用兜底（**不是**本文件的口径：连上后立刻按机器自报值重算） */
export const LABEL_DPI_DEFAULT = FALLBACK_GEOMETRY.dpi
export const LABEL_HEAD_DOTS_DEFAULT = FALLBACK_GEOMETRY.headWidthPx
/** 纸宽 / 纸长（mm）—— 取自介质矩阵（`label-50x150` = 50mm × 150mm），本文件不写第二份 */
export const WASH_LABEL_DEFAULT_WIDTH_MM = FALLBACK_BOX.widthMm
export const WASH_LABEL_DEFAULT_LENGTH_MM = FALLBACK_BOX.heightMm
// 字号 / 行高 / 内边距 / 二维码 / 块间距的**取值全在** `./wash-label-metrics`（上面按原名 import），
// 本文件不再写第二份字面量。

const CSS_PX_TO_MM = 25.4 / 96

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
 *
 * 纸长**不由调用方给**（issue #7816）：固定 = 介质矩阵的 `pageBoxMm.heightMm`（150mm ⇒ 1200px）。
 */
export function resolveLabelGeometry(
  printer?: LabelPrinterInfoLike | null,
  paperWidthMm?: number | null,
): LabelDotGeometry {
  const dpi = positive(printer?.printerDPI) ?? LABEL_DPI_DEFAULT
  const headDots = positive(printer?.printerWidth) ?? LABEL_HEAD_DOTS_DEFAULT
  const dpmm = dpi / 25.4
  const byPaper = positive(paperWidthMm) ?? WASH_LABEL_DEFAULT_WIDTH_MM
  return {
    dpmm,
    widthPx: Math.min(Math.round(byPaper * dpmm), headDots),
    heightPx: Math.round(WASH_LABEL_DEFAULT_LENGTH_MM * dpmm),
  }
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
 * `maxLines` 是**可选**的行数预算：缺省 = 不设上限（**印全文**，issue #7833）。
 * 只有「占位框文案」这类**非正文**用途才显式给上限（给上限 ⇒ 末行以省略号收尾）。
 */
export function wrapText(
  text: string,
  maxW: number,
  fontPx: number,
  measure: TextMeasure,
  maxLines = Number.POSITIVE_INFINITY,
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
  /** 对齐（缺省 `left`）；纸面抬头块居中，与系统打印的 `text-center` 同口径 */
  align?: 'left' | 'center'
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
  /** 纸面抬头（企业名 + 副标题，居中）；企业名缺值 ⇒ 空数组（整块不渲染） */
  company: LabelText[]
  /** 正文块（可裁区）：已切好的行，逐行带位置与字号 */
  lines: LabelText[]
  /** 二维码位（有码时，**底部居中**）；无码 ⇒ `null`（**不画假码**） */
  qr: LabelRect | null
  /** 无码时的占位框（虚线方框 + 占位文案，居中） */
  qrPlaceholder: LabelPlaceholder | null
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
  const fontPx = ptToPx(WASH_LABEL_QR_PLACEHOLDER_FONT_PT, dpmm)
  const padding = Math.round(size * 0.1)
  const centerX = x + Math.round(size / 2)
  const step = Math.round(fontPx * LABEL_LINE_HEIGHT)
  const lines = wrapText(hint, size - 2 * padding, fontPx, measure, 3)
  const top = y + Math.max(0, Math.round((size - lines.length * step) / 2))
  return lines.map((text, index) => ({ text, x: centerX, y: top + index * step, fontPx }))
}

/**
 * 版式（**纯函数**）：抬头在上、正文块居中、底部 = **居中二维码**（issue #7816；
 * 不再有加工单号行 / 扫码报工 / 人可读短码）。
 *
 * @throws WashLabelLayoutError 纸宽连内边距都放不下（fail-closed，**不静默**）
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

  const bodyFontPx = ptToPx(LABEL_BODY_FONT_PT, dpmm)
  const lineStep = Math.round(bodyFontPx * LABEL_LINE_HEIGHT)
  const gap = Math.round(mm(LABEL_BLOCK_GAP_MM))

  // ① 纸面抬头（`shrink-0`）：企业名 + 副标题，居中（与系统打印的抬头块同口径）
  const company: LabelText[] = []
  const companyName = (input.companyName ?? '').trim()
  if (companyName !== '') {
    const nameFontPx = ptToPx(LABEL_COMPANY_FONT_PT, dpmm)
    const subtitleFontPx = ptToPx(LABEL_COMPANY_SUBTITLE_FONT_PT, dpmm)
    const centerX = Math.round(widthPx / 2)
    // 🔴 抬头也**折行印全文**（issue #7833）：两条通道都不得靠省略号掩盖长企业名。
    let companyCursor = margin
    for (const text of wrapText(companyName, innerW, nameFontPx, measure)) {
      company.push({ text, x: centerX, y: companyCursor, fontPx: nameFontPx, align: 'center' })
      companyCursor += Math.round(nameFontPx * LABEL_LINE_HEIGHT)
    }
    for (const text of wrapText(WASH_LABEL_COMPANY_SUBTITLE, innerW, subtitleFontPx, measure)) {
      company.push({ text, x: centerX, y: companyCursor, fontPx: subtitleFontPx, align: 'center' })
      companyCursor += Math.round(subtitleFontPx * LABEL_LINE_HEIGHT)
    }
  }
  // 抬头块占高 = **逐行真实行高之和**（企业名 14pt 与副标题 10pt 不同字号，按 bodyFont 一刀切会少算）
  const companyHeight =
    company.length > 0 ? company.reduce((sum, line) => sum + Math.round(line.fontPx * LABEL_LINE_HEIGHT), 0) + gap : 0

  // ② 二维码（`shrink-0`）：**跟在正文后两行**，不沉底 —— 2026-10-26 用户逐字
  //    「二维码不要沉底，跟文字隔两行即可，要离底部虚线留空」。
  //    版式与系统打印（`TaskCardPrint`：文字块不 flex-1 + `mt-[10.16mm]`）逐条同口径；
  //    两者共用 {@link LABEL_QR_TEXT_GAP_LINES} / {@link LABEL_BOTTOM_CLEARANCE_MM}。
  const qrValue = (input.qrValue ?? '').trim()
  const qrSize = Math.round(mm(LABEL_QR_CSS_PX * CSS_PX_TO_MM))
  const placeholderSize = Math.round(mm(LABEL_QR_PLACEHOLDER_MM))
  const footerSize = qrValue === '' ? placeholderSize : qrSize
  const textGap = lineStep * LABEL_QR_TEXT_GAP_LINES
  const bottomClearance = Math.round(mm(LABEL_BOTTOM_CLEARANCE_MM))
  /** 二维码**最低**允许的下沿（再往下就贴底部虚线了 ⇒ 正文在这里之前必须收住） */
  const footerBottomMax = heightPx - margin - bottomClearance
  const footerTopMax = footerBottomMax - footerSize
  const footerX = Math.round((widthPx - footerSize) / 2)

  // ③ 正文块（`min-h-0 overflow-hidden`）：**空间不够时只裁这里**；止于「二维码上沿再往上两行」
  const blockTop = margin + companyHeight
  const blockBottom = footerTopMax - textGap
  const lines: LabelText[] = []
  let cursor = blockTop
  let exhausted = false
  for (const row of input.rows ?? []) {
    if (exhausted) break
    for (const text of wrapText(row.text, innerW, bodyFontPx, measure)) {
      if (cursor + lineStep > blockBottom) {
        exhausted = true
        break
      }
      lines.push({ text, x: margin, y: cursor, fontPx: bodyFontPx })
      cursor += lineStep
    }
  }
  // 二维码 y = 正文最后一行的下方**两行**；正文很短时也不许沉底（`min` 兜住纸底 + 留白）
  const footerTop = Math.min(cursor + textGap, footerTopMax)

  const qr: LabelRect | null = qrValue === '' ? null : { x: footerX, y: footerTop, size: qrSize }
  const qrPlaceholder: LabelPlaceholder | null =
    qrValue !== ''
      ? null
      : {
          rect: { x: footerX, y: footerTop, size: placeholderSize },
          lines: placeholderHintLines(
            (input.qrPlaceholderHint ?? '').trim() || WASH_LABEL_QR_PLACEHOLDER_HINT,
            footerX,
            footerTop,
            placeholderSize,
            dpmm,
            measure,
          ),
        }

  return { geometry, margin, company, lines, qr, qrPlaceholder }
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

/** 底部虚线的划长 / 间隔 / 线粗（px）—— 与 CSS 的 `1px dashed` 同一观感（issue #7833） */
const DASH_PX = 8
const DASH_GAP_PX = 6
const DASH_THICKNESS_PX = 2

/**
 * 画一条**横向虚线**（用 `fillRect` 逐段画，不扩 `WashLabelPaintContext` 的面 —— 假 ctx 照旧可测）。
 *
 * 位置 = 纸的**下沿**（`y = heightPx - 线粗`），与 `.task-card-label` 的 `border-bottom: 1px dashed`
 * 同口径：用户 2026-10-26「头尾加下虚线，这样能清晰知道界线」；同批后续「水洗唛的顶部虚线移除掉」
 * ⇒ **顶部不画**（issue #7839）。
 */
export function paintDashedRule(
  ctx: WashLabelPaintContext,
  widthPx: number,
  y: number,
): void {
  const step = DASH_PX + DASH_GAP_PX
  for (let x = 0; x < widthPx; x += step) {
    ctx.fillRect(x, y, Math.min(DASH_PX, widthPx - x), DASH_THICKNESS_PX)
  }
}

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

  // 底部虚线（issue #7833 → #7839）：只画下沿；顶部按用户裁定不画（正文/二维码都落在内边距之内）
  paintDashedRule(ctx, widthPx, heightPx - DASH_THICKNESS_PX)

  for (const line of layout.company) {
    ctx.textAlign = 'center'
    ctx.font = `${line.fontPx === layout.company[0]?.fontPx ? 'bold ' : ''}${line.fontPx}px ${BODY_FONT}`
    ctx.fillText(line.text, line.x, line.y)
  }
  if (layout.company.length > 0) ctx.textAlign = 'left'

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
}
