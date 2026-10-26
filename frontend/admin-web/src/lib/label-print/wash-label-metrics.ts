/**
 * 水洗唛**版面度量**的单一真值（issue #7776 建立 → **issue #7816 改判：固定纸型 50×150**）。
 *
 * ## 两次用户裁定的关系（别把前一次读成"仍然有效"）
 *
 * - 2026-10-25（#7776）：「字体太小了，可以把长度延长些，因为长度可以无限长……上下两头留白太多了」
 *   ⇒ 当版把纸长做成**按内容撑开**（夹在 70~150mm）。
 * - **2026-10-26（#7816，现行）**：「水洗唛长度不足，设置为打印50*150」「字体还是太小，可以再大一点」
 *   ⇒ 纸型**固定 50mm × 150mm**（动态纸长整体退场），正文字号 9pt → **12pt**。
 *   ⇒ 现在的纸长只有一个来源：介质矩阵 `label-50x150.pageBoxMm` / `pageSize`（本文件不写第二份）。
 *
 * ## 单一真值纪律（本模块是什么、不是什么）
 *
 * - **是**：字号 / 行高 / 内边距 / 二维码边长 / 块间距的**唯一一份** TS 常量 ——
 *   画布通道（`wash-label.ts`）与系统打印通道（`TaskCardPrint.tsx` 的 CSS / Tailwind 字号）都从这里取。
 * - **不是**：内容真值（印什么、行序 = `lib/wash-label-content.ts`）、也不是纸型真值（`lib/print-media.json`）。
 * - CSS 与 TS 两份字面量的一致性由 `tests/unit/lib/label-print/wash-label-metrics.test.ts` 钉住
 *   （它**解析组件源码**逐值比对）—— 改 CSS 不改这里 ⇒ 红。
 *
 * ## 字号取值理由（50mm 宽的物理约束）
 *
 * 版心宽 = 50 − 2 × 1.2 = **47.6mm**；12pt 汉字 ≈ 4.233mm ⇒ 每行约 **11.2 个汉字**
 * （9pt 时代是 15 个字）。再往上抬（14pt ⇒ 9.6 字/行）常规行的折行数会把 13 行正文推到
 * 150mm 的可用高度之外（147.6mm）⇒ **12pt 是"更大且装得下"的最优档**。
 */

/** 标签本体内边距（mm）—— 与 `.task-card-label { padding }` 同一口径 */
export const WASH_LABEL_PADDING_MM = 1.2
/** 正文行高倍数 —— 与 `.task-card-label { line-height: 1.2 }` 同一口径 */
export const WASH_LABEL_LINE_HEIGHT = 1.2
/** 正文基准字号（pt）—— 与 `.task-card-label { font-size }` 同一口径（2026-10-26：9pt → 12pt） */
export const WASH_LABEL_BODY_FONT_PT = 12
/** 纸面抬头「企业名」字号（pt）—— 与抬头块 `text-[14pt]` 同一口径 */
export const WASH_LABEL_COMPANY_FONT_PT = 14
/** 纸面抬头副标题（「成品定制」）字号（pt）—— 与抬头块副行 `text-[10pt]` 同一口径 */
export const WASH_LABEL_COMPANY_SUBTITLE_FONT_PT = 10
/**
 * 二维码边长（CSS px）—— 与 `QRCodeSVG size={80}` / `size={80}` 同一口径（1 CSS px = 1/96 英寸）。
 *
 * 2026-10-26 用户逐字「二维码可以放大一点」⇒ 45px（11.9mm）→ **80px（21.2mm）**，底部居中；
 * 同时**退场**「扫码报工」小字与人可读短码（用户逐字「移除扫码报工和短码文字」）。
 */
export const WASH_LABEL_QR_CSS_PX = 80
/** 缺码时占位方框的边长（mm）—— 与 `h-[20mm] w-[20mm]` 同一口径（与二维码同量级） */
export const WASH_LABEL_QR_PLACEHOLDER_MM = 20
/** 占位框内文案字号（pt）—— 与 `text-[9pt]` 同一口径 */
export const WASH_LABEL_QR_PLACEHOLDER_FONT_PT = 9
/** 表头 / 正文块 / 底部码之间的间距（mm）—— 与 `mt-[0.5mm]` / `mt-[1mm]` 同口径 */
export const WASH_LABEL_BLOCK_GAP_MM = 0.5
/** 正文块与底部二维码之间多留的一点间距（mm）—— 码是功能件，别和文字挤在一起 */
export const WASH_LABEL_QR_GAP_MM = 1
