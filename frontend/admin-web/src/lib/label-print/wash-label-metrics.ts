/**
 * 水洗唛**版面度量 + 纸长**（issue #7776，用户 2026-10-25 逐字）：
 *
 * 「水洗唛打印效果不太好，**字体太小了**，可以把**长度延长些，因为长度可以无限长**，
 *   **宁愿长点也要把字体和信息都呈现出来**，其他标签打印也有同样的问题，都太小了，
 *   打印预览的时候我就发现**上下两头留白太多了**」
 *
 * ## 为什么纸长要按内容算（而不是写死一个更大的数）
 *
 * 打印头和纸卷都是**连续纸**（宽度 50mm 固定、长度不限）⇒ 纸长的唯一约束是「内容装得下」。
 * 写死纸长只有两种结局：① 迁就最坏内容 ⇒ 常规单两头留白（用户这次投诉的正是它）；
 * ② 迁就常规内容 ⇒ 最坏内容被裁（更糟，信息丢了）。⇒ **纸长 = 内容高度**（下限 70mm、
 * 上限 {@link WASH_LABEL_MAX_LENGTH_MM}），字号才能一步抬到可读口径。
 *
 * ## 单一真值纪律（本模块是什么、不是什么）
 *
 * - **是**：字号 / 行高 / 内边距 / 二维码边长 / 块间距 / 逐行折行估算的**唯一一份** TS 常量，
 *   画布通道（`wash-label.ts`）与系统打印通道（`TaskCardPrint.tsx` 的 CSS）都从这里取。
 * - **不是**：内容真值（印什么、行序 = `lib/wash-label-content.ts`）。
 * - CSS 与 TS 两份字面量的一致性由 `tests/unit/lib/label-print/wash-label-metrics.test.ts` 钉住
 *   （它**解析组件源码**逐值比对）—— 改 CSS 不改这里 ⇒ 红。
 *
 * ## 折行估算为什么要模拟逐字填充
 *
 * 浏览器按「字符」断行（中文没有空格可断），所以行数 ≈ 贪心填满版心的次数。用「总宽 ÷ 版心」
 * 上取整会**低估**（每行都吃不满的误差会累积）。故本模块与画布侧 `wrapText` 同口径**逐字**填行，
 * 字符宽度取 **CJK = 全角（1em）/ ASCII = 0.6em**（PingFang 实测 CJK 恰为 1em、数字 ≈ 0.55em、
 * 大写字母 ≈ 0.65em ⇒ 0.6em 是**安全侧**：估出来的行数只会多不会少，多算 1 行的代价是纸长多 3.8mm，
 * 少算 1 行则是把内容挤出纸外）。
 */

/** 标签本体内边距（mm）—— 与 `.task-card-label { padding }` 同一口径 */
export const WASH_LABEL_PADDING_MM = 1.2
/** 正文行高倍数 —— 与 `.task-card-label { line-height: 1.2 }` 同一口径 */
export const WASH_LABEL_LINE_HEIGHT = 1.2
/** 正文基准字号（pt）—— 与 `.task-card-label { font-size }` 同一口径（2026-10-25：6pt → 9pt） */
export const WASH_LABEL_BODY_FONT_PT = 9
/** 纸面抬头「企业名」字号（pt）—— 与抬头块 `text-[10pt]` 同一口径 */
export const WASH_LABEL_COMPANY_FONT_PT = 10
/** 纸面抬头副标题（「成品定制」）字号（pt）—— 与抬头块副行 `text-[7pt]` 同一口径 */
export const WASH_LABEL_COMPANY_SUBTITLE_FONT_PT = 7
/** 加工单号字号（pt）—— 与 `text-[10pt] font-bold` 同一口径 */
export const WASH_LABEL_HEADER_FONT_PT = 10
/** 底部人可读短码字号（pt）—— 与 `text-[12pt] font-bold` 同一口径（工人隔 1 米要能读） */
export const WASH_LABEL_SHORT_CODE_FONT_PT = 12
/** 二维码边长（CSS px）—— 与 `QRCodeSVG size={45}` 同一口径（1 CSS px = 1/96 英寸） */
export const WASH_LABEL_QR_CSS_PX = 45
/** 缺码时占位方框的边长（mm）—— 与 `h-[12mm] w-[12mm]` 同一口径 */
export const WASH_LABEL_QR_PLACEHOLDER_MM = 12
/** 二维码与右侧文字的间距（mm）—— 与 `gap-[1mm]` 同口径 */
export const WASH_LABEL_QR_GAP_MM = 1
/** 表头 / 正文块 / 底部行之间的间距（mm）—— 与 `mt-[0.5mm]` 同口径 */
export const WASH_LABEL_BLOCK_GAP_MM = 0.5
/** 短码的最小字号（mm）：再小就失去「手输降级入口」的意义，宁可报错 */
export const WASH_LABEL_MIN_SHORT_CODE_FONT_MM = 2.5

const CSS_PX_TO_MM = 25.4 / 96
const PT_TO_MM = 25.4 / 72

/** ASCII 字符宽度（em）—— 安全侧：PingFang 的数字 ≈0.55em / 大写 ≈0.65em，取 0.6em */
const ASCII_EM = 0.6
/** 全角判定（CJK + 全角标点）—— 与画布侧 `estimateTextWidth` 同口径（`> 0x2e80`） */
const isWide = (ch: string): boolean => ch.charCodeAt(0) > 0x2e80

/** 一行文字的估算宽度（mm） */
export function estimateTextWidthMm(text: string, fontPt: number): number {
  const emMm = fontPt * PT_TO_MM
  let width = 0
  for (const ch of text) width += isWide(ch) ? emMm : emMm * ASCII_EM
  return width
}

/**
 * 估算一段文字在版心内折成几行（**逐字贪心填行**，与浏览器断行同量级）。
 *
 * @param maxLines 行数预算（`washLabelRows` 的 `maxLines`）：折到预算上限即停（CSS `line-clamp-N`）
 */
export function estimateLineCount(text: string, innerWidthMm: number, fontPt: number, maxLines = 1): number {
  const source = text.trim()
  if (source === '' || innerWidthMm <= 0) return 0
  const budget = Math.max(1, Math.floor(maxLines))
  const emMm = fontPt * PT_TO_MM
  let lines = 1
  let current = 0
  for (const ch of source) {
    const width = isWide(ch) ? emMm : emMm * ASCII_EM
    if (current > 0 && current + width > innerWidthMm) {
      lines += 1
      current = width
      if (lines > budget) return budget
    } else {
      current += width
    }
  }
  return Math.min(lines, budget)
}

/** 行高（mm）：字号 × 行高倍数 */
function lineHeightMm(fontPt: number): number {
  return fontPt * PT_TO_MM * WASH_LABEL_LINE_HEIGHT
}

/** 纸面抬头块高度（mm）：企业名 + 副标题两行（没有企业名 ⇒ 整块不渲染） */
export function washLabelCompanyBlockMm(hasCompany: boolean): number {
  return hasCompany
    ? lineHeightMm(WASH_LABEL_COMPANY_FONT_PT) + lineHeightMm(WASH_LABEL_COMPANY_SUBTITLE_FONT_PT) +
        WASH_LABEL_BLOCK_GAP_MM
    : 0
}

/** 底部行高度（mm）：二维码位（有码 45 CSS px / 无码 12mm 占位框）—— 短码那两行不超过它 */
export function washLabelFooterMm(hasQr: boolean): number {
  return hasQr ? WASH_LABEL_QR_CSS_PX * CSS_PX_TO_MM : WASH_LABEL_QR_PLACEHOLDER_MM
}

/** 纸面**内容**总高（mm）：内边距 + 抬头块 + 加工单号 + 正文行 + 块间距 + 底部行 */
export function washLabelContentHeightMm(input: WashLabelLengthInput): number {
  const widthMm = input.widthMm ?? 50
  const innerWidthMm = widthMm - 2 * WASH_LABEL_PADDING_MM
  let height = 2 * WASH_LABEL_PADDING_MM
  height += washLabelCompanyBlockMm(input.hasCompany !== false)
  height += lineHeightMm(WASH_LABEL_HEADER_FONT_PT)
  height += WASH_LABEL_BLOCK_GAP_MM
  for (const row of input.rows ?? []) {
    height += estimateLineCount(row.text, innerWidthMm, WASH_LABEL_BODY_FONT_PT, row.maxLines) * lineHeightMm(WASH_LABEL_BODY_FONT_PT)
  }
  height += WASH_LABEL_BLOCK_GAP_MM
  height += washLabelFooterMm(input.hasQr !== false)
  return height
}

export interface WashLabelLengthInput {
  /** 纸面行（`washLabelRows` 的输出；只读 `text` / `maxLines`） */
  rows?: ReadonlyArray<{ text: string; maxLines: number }>
  /** 有企业抬头块（企业名非空） */
  hasCompany?: boolean
  /** 有二维码（无码时底部是占位框，尺寸不同） */
  hasQr?: boolean
  /** 纸宽（mm）；缺省 50 */
  widthMm?: number
  /** 纸长下限（mm）；缺省 {@link WASH_LABEL_MIN_LENGTH_MM} */
  minLengthMm?: number
  /** 纸长上限（mm）；缺省 {@link WASH_LABEL_MAX_LENGTH_MM} */
  maxLengthMm?: number
}

/**
 * 纸长下限（mm）—— 与介质矩阵 `label-50x70.pageBoxMm.heightMm` 同一份（守卫比对矩阵）。
 * 下限的意义：短内容单也不印得比这更短（驱动里登记的纸型、撕纸习惯）。
 */
export const WASH_LABEL_MIN_LENGTH_MM = 70
/** 纸长上限（mm）—— 超出即**夹住**（纸不可能无限长；真到这个量级说明内容该拆了） */
export const WASH_LABEL_MAX_LENGTH_MM = 150

/**
 * 一条洗水唛的**纸长（mm）**：内容高上取整到 1mm，夹在 `[min, max]`。
 *
 * 🔴 **两条通道（系统打印 / 蓝牙直连）与预览读的都是它** —— 三个数必须同源，
 * 否则「预览这张纸」与「打出这张纸」又会对不上（issue #6656 踩过的形态）。
 */
export function washLabelLengthMm(input: WashLabelLengthInput): number {
  const min = input.minLengthMm ?? WASH_LABEL_MIN_LENGTH_MM
  const max = input.maxLengthMm ?? WASH_LABEL_MAX_LENGTH_MM
  const height = washLabelContentHeightMm(input)
  const rounded = Math.ceil(height)
  const clamped = Math.min(Math.max(rounded, min), max)
  return Math.max(min, Math.min(max, clamped))
}

/**
 * 一批标签的**统一纸长**（mm）—— 一次打印任务里的每一页必须同高（`@page` 是文档级规则，
 * 每页纸型不能各不相同），故取该批的**最大值**：短内容的那几张宁可多留几毫米，
 * 也绝不让任何一张被裁。
 */
export function washLabelBatchLengthMm(labels: ReadonlyArray<WashLabelLengthInput>): number {
  if (labels.length === 0) return WASH_LABEL_MIN_LENGTH_MM
  return Math.max(...labels.map((label) => washLabelLengthMm(label)))
}
