/**
 * 入库标签 **50×80mm 版面**（纯函数，issue #5052 P3 / CP-1；设计 §7.1 / §7.2；
 * 尺寸与版面由用户 2026-10-26 裁定改版 —— 见 issue #7820）
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
  /**
   * **商品货号**（`products.sku_code`，例 2659）—— 纸面「货号」印这一行。
   *
   * 🔴 与下面的 `skuCode`（规格编码，例 2659-04-28）**不是一回事**：用户 2026-11-01 裁定
   * 「货号展示商品货号更好，不应该展示 sku 的货号……sku 不要等于货号」。
   */
  productCode?: string | null
  /** **规格编码**（`product_skus.sku_code`：色号 + 门幅的组合，例 2659-04-28） */
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
export const MISSING_CODE_TEXT = '编号缺失'

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

/** 版面栅格（相对量：都是「版心宽」的比例，最终像素由几何算出来 —— 本文件不写死像素） */
const GRID = {
  padRatio: 0.05, // ≈19px ≈ 2.4mm
  headFontRatio: 0.098, // ≈38px ≈ 4.7mm（货号 —— 纸面第一眼要看的那一行）
  colorFontRatio: 0.075, // ≈29px ≈ 3.6mm
  metersFontRatio: 0.082, // ≈32px ≈ 3.9mm
  fieldFontRatio: 0.065, // ≈25px ≈ 3.1mm
  codeFontRatio: 0.075, // ≈29px（人可读短码：手输兜底用）
  qrBoxRatio: 0.4, // 上限 ≈22mm 见方（2026-11-01 用户裁定「二维码太大了，可以缩小些」；每模块仍 ≥5 点）
  qrMinRatio: 0.32, // 下限 ≈17mm 见方（再小就扫不动了）—— 字段多时按可用高度自适应收
  gapRatio: 0.021, // ≈8px 行间（50×80 的纸面更宽，行间跟着放宽一档 —— 空隙均摊在字段区，不留大块空白）
} as const

/** 色号行的**缩字号梯度**：先缩字号，仍放不下才可见省略号（**绝不静默裁切**） */
const COLOR_FONT_STEPS = [1, 0.88, 0.77] as const

/**
 * 按宽度换行（优先在空格 / 斜杠 / 顿号处断开，否则按字断）。
 *
 * **不截断**：放不下就多出几行，由调用方决定「缩字号」还是「可见省略号」。
 */
export function wrapTextLines(text: string, maxWidthPx: number, fontPx: number): string[] {
  const raw = String(text ?? '').trim()
  if (!raw) return ['']
  const lines: string[] = []
  let rest = raw
  while (rest) {
    if (estimateTextWidth(rest, fontPx) <= maxWidthPx) {
      lines.push(rest)
      break
    }
    let cut = 0
    for (let i = 1; i <= rest.length; i += 1) {
      if (estimateTextWidth(rest.slice(0, i), fontPx) > maxWidthPx) break
      cut = i
    }
    if (cut <= 0) {
      // 连一个字都放不下（字号远大于版心）⇒ 原样返回，让上层的「超宽」判据判红
      lines.push(rest)
      break
    }
    const window = rest.slice(0, cut)
    let breakAt = -1
    for (let i = window.length - 1; i >= Math.max(1, Math.floor(cut * 0.6)); i -= 1) {
      if (' /·、'.includes(window[i])) {
        breakAt = i + 1
        break
      }
    }
    const take = breakAt > 0 ? breakAt : cut
    const line = rest.slice(0, take).replace(/[ /·、]+$/, '')
    const tail = rest.slice(take).replace(/^[ /·、]+/, '')
    // 分隔符被吃掉后不能变空行（退化 ⇒ 按原 cut 硬断）
    if (!line) {
      lines.push(rest.slice(0, cut).trim())
      rest = rest.slice(cut).trim()
      continue
    }
    lines.push(line)
    rest = tail.trim()
  }
  return lines.length > 0 ? lines : ['']
}

/** 色号行：两行内放下（先缩字号），仍放不下才把最后一行可见省略 */
function fitColorLines(
  text: string,
  maxWidthPx: number,
  baseFontPx: number,
): { lines: string[]; fontPx: number; truncated: boolean } {
  for (const scale of COLOR_FONT_STEPS) {
    const fontPx = Math.max(1, Math.round(baseFontPx * scale))
    const lines = wrapTextLines(text, maxWidthPx, fontPx)
    if (lines.length <= 2) return { lines, fontPx, truncated: false }
  }
  const fontPx = Math.max(1, Math.round(baseFontPx * COLOR_FONT_STEPS[COLOR_FONT_STEPS.length - 1]))
  const wrapped = wrapTextLines(text, maxWidthPx, fontPx)
  const tailLine = fitTextVisible(wrapped.slice(1).join(''), maxWidthPx, fontPx)
  return { lines: [wrapped[0], tailLine.text], fontPx, truncated: tailLine.truncated }
}

/**
 * 生成标签绘制计划。
 *
 * ## 版面（2026-10-26 用户裁定 · 50×80mm；顺序即阅读顺序）
 *
 * 1. `货号`（headline）—— **原来的顶部「品名」已去掉**（用户逐字「移除顶部的商品名」）
 * 2. `色号 / 门幅` —— **全宽**（不再与二维码左右分栏 ⇒ 色号不再被挤成省略号）
 * 3. `米数`（醒目：贴在布卷上的那张纸要以它为准）
 * 4. `批次` / `单号` / `入库 <日期>` / `缸号` / `送单`（缺字段整行不画，**不编造**）
 * 5. 分隔线 + **二维码（居中，在底部）** + 人可读短码（居中）
 *
 * @param view 读面字段（缺字段 ⇒ 该行不画，**不编造**）
 */
export function layoutInboundLabel(view: InboundLabelView): InboundLabelPlan {
  const geometry = inboundLabelGeometry()
  const width = geometry.canvasWidthPx
  const height = geometry.canvasHeightPx
  const pad = Math.round(width * GRID.padRatio)
  const inner = width - pad * 2
  const gap = Math.round(width * GRID.gapRatio)
  const warnings: string[] = []
  const ops: LabelPaintOp[] = []

  const headFont = Math.round(width * GRID.headFontRatio)
  const colorFont = Math.round(width * GRID.colorFontRatio)
  const metersFont = Math.round(width * GRID.metersFontRatio)
  const fieldFont = Math.round(width * GRID.fieldFontRatio)
  const codeFont = Math.round(width * GRID.codeFontRatio)

  /** 自上而下逐行排（整行文字；超宽 ⇒ 可见截断） */
  // 顶部只留基础内边距（`pad`）。2026-11-01 16:16 用户复看：顶部再留 5mm 后，
  // 纸面上「文字与二维码之间」的空隙变大 ⇒ 这段白边只加在**二维码那一侧**（见 BOTTOM_SAFE_MM）。
  // 顶部同样按 BOTTOM_SAFE_MM 留白：真机出纸方向与画布上下**相反**（两次实拍取证：纸面最上面的
  // 二维码其实是画布最底部），只在画布底部留 ⇒ 白边落在了纸面顶部。两端对称留，纸面首尾才有白边。
  const safePx = Math.round((geometry.dotsPerMm || 8) * bottomSafeMm())
  let cursorY = Math.max(pad, safePx)
  const pushRow = (raw: string, fontPx: number, bold: boolean, extraGap = 0) => {
    const fitted = fitTextVisible(raw, inner, fontPx)
    if (fitted.truncated) warnings.push(`字段行超宽已截断：${fitted.text}`)
    ops.push({
      kind: 'text',
      text: fitted.text,
      x: pad,
      y: cursorY,
      fontPx,
      bold,
      maxWidthPx: inner,
      truncated: fitted.truncated,
    })
    cursorY += fontPx + gap + extraGap
  }

  // ── ① 货号（headline）────────────────────────────────────────────────────
  const productCode = String(view.productCode ?? '').trim()
  if (productCode) pushRow(`货号 ${productCode}`, headFont, true, gap)

  // ── ② 色号 / 门幅（全宽；两行内放下）──────────────────────────────────────
  // 🔴 门幅**不并入色号行**（用户 2026-10-26：色号不要有遮挡）—— 两格各自占满整行，
  //    色号再长也不会被门幅挤掉一个字（旧形态把两者拼成一行再截断）
  const colorValue = String(view.colorName ?? '').trim()
  if (colorValue) {
    const fit = fitColorLines(`色号 ${colorValue}`, inner, colorFont)
    fit.lines.forEach((line, index) => {
      ops.push({
        kind: 'text',
        text: line,
        x: pad,
        y: cursorY + index * (fit.fontPx + Math.round(gap * 0.5)),
        fontPx: fit.fontPx,
        bold: false,
        maxWidthPx: inner,
        truncated: fit.truncated && index === fit.lines.length - 1,
      })
    })
    if (fit.truncated) warnings.push(`色号超宽已截断：${fit.lines.join('')}`)
    cursorY += fit.lines.length * (fit.fontPx + Math.round(gap * 0.5)) + Math.round(gap * 0.5)
  }

  const doorWidth = String(view.doorWidth ?? '').trim()
  if (doorWidth) pushRow(`门幅 ${doorWidth}`, fieldFont, false, gap)

  // ── ③ 米数（醒目）────────────────────────────────────────────────────────
  const meters = String(view.quantity ?? '').trim()
  if (meters) pushRow(`米数 ${meters}`, metersFont, true, gap)

  // ── ④ 其余字段（缺字段整行不画，**不编造**）──────────────────────────────
  const rows: string[] = []
  if (String(view.batchNo ?? '').trim()) rows.push(`批次 ${view.batchNo}`)
  if (String(view.inboundNo ?? '').trim()) rows.push(`单号 ${view.inboundNo}`)
  if (String(view.inboundDate ?? '').trim()) rows.push(`入库 ${view.inboundDate}`)
  if (String(view.dyeLot ?? '').trim()) rows.push(`缸号 ${view.dyeLot}`)
  if (String(view.supplierDocNo ?? '').trim()) rows.push(`送单 ${view.supplierDocNo}`)
  rows.forEach((line) => pushRow(line, fieldFont, false))

  // ── ⑤ 底部：只有二维码（居中）──────────────────────────────────────────
  //
  // 🔴 2026-11-01 用户裁定：「移除二维码下面的短码」—— 短码仍印在标签的**人可读**位置（页面读面 +
  //    补打页手输入口），纸面上不再重复一行文字，把高度还给二维码。
  // 🔴 底部安全区 = 3mm：标签末端（间隙/剥离区）印不出来，留白不足会把码的下沿切掉
  //    （真机出纸实测：原先只剩 1mm 白边）。按介质矩阵的 dotsPerMm 换算，**不写死像素**。
  const payload = labelCodePayload(view.shortCode)
  const codeRaw = payload ? String(view.shortCode).trim().toUpperCase() : MISSING_CODE_TEXT
  const code = fitTextVisible(codeRaw, inner, codeFont)
  const bottomSafePx = safePx
  // 码**紧跟文字**（分隔线 → 2mm → 码），剩下多少高度全给码那一侧做白边：
  //   用户 2026-11-01 16:16「文字和二维码之间留白变大了」⇒ 不再把码钉在版心底部；
  //   同一轮「下面留白」⇒ 剩余高度就是纸面那一侧的白边（两种出纸方向下都 ≥10mm）。
  const qrBottom = Math.min(height - Math.max(bottomSafePx, pad), cursorY + gap + Math.round(width * GRID.qrBoxRatio))
  // 码区上限 = 版心宽的 62%；下限 = 40%；两者之间按「文字排完剩下的高度」自适应
  const qrMax = Math.round(width * GRID.qrBoxRatio)
  const qrMin = Math.round(width * GRID.qrMinRatio)
  const qrRoom = qrBottom - (cursorY + gap * 2)
  const qrBox = Math.max(qrMin, Math.min(qrMax, qrRoom))

  let qr: LabelQrPlan | null = null
  let codeTop = qrBottom - qrBox
  if (payload) {
    const { moduleCount, matrix } = buildQrMatrix(payload)
    const cellPx = Math.max(1, Math.floor(qrBox / moduleCount))
    const sizePx = cellPx * moduleCount
    if (sizePx < qrBox * 0.6) {
      // 码太密（cell 取整后缩水太多）⇒ 纸面仍按整数倍画，但登记出来
      warnings.push(`二维码点阵偏密：${moduleCount}×${moduleCount} 模块，每模块 ${cellPx}px`)
    }
    qr = {
      payload,
      moduleCount,
      cellPx,
      x: Math.round((width - sizePx) / 2),
      y: qrBottom - sizePx,
      sizePx,
      matrix,
    }
    codeTop = qr.y
  } else {
    // 🔴 缺码不画假码：留空位 + 可见标注（红证：画占位二维码 ⇒ 判据必红）
    warnings.push('标签编号缺失或非法：未绘制二维码（不画占位码）')
    const mark = fitTextVisible(MISSING_CODE_TEXT, qrBox, fieldFont)
    const boxX = Math.round((width - qrBox) / 2)
    ops.push({ kind: 'rect', x: boxX, y: qrBottom - qrBox, w: qrBox, h: qrBox, color: '#ffffff' })
    ops.push({
      kind: 'text',
      text: mark.text,
      x: boxX,
      y: qrBottom - Math.round(qrBox / 2),
      fontPx: fieldFont,
      bold: false,
      maxWidthPx: qrBox,
      truncated: mark.truncated,
    })
  }

  // 分隔线：把「字段区」与「码区」分开（版面纪律：二维码只在下半区，不许压字）
  const dividerY = Math.max(pad, codeTop - gap * 2)
  ops.push({ kind: 'rect', x: pad, y: dividerY, w: inner, h: 2, color: '#000000' })
  if (cursorY > dividerY - gap) {
    // 字段多到压到码区 ⇒ 纸面照样画（不静默丢字段），但把事实登记出来
    warnings.push('版面偏挤：字段区与二维码区可能重叠（请核对字段数量）')
  }

  return {
    widthPx: width,
    heightPx: height,
    ops,
    qr,
    codeText: code.text,
    warnings,
  }
}

/** 标签末端的安全白边（mm）：热敏标签机在标签间隙/剥离区印不出来。3mm 真机仍被切 ⇒ 改 5mm（用户 2026-11-01 裁定） */
export const BOTTOM_SAFE_MM = 10

function bottomSafeMm(): number {
  return BOTTOM_SAFE_MM
}

/** 版面声明的纸型（与矩阵同源；渲染器/打印适配层读它，不写 `50mm 80mm` 字面量） */
export function inboundLabelPageSize(): string {
  return inboundLabelMedia().pageSize
}
