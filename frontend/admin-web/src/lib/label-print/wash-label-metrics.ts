/**
 * 水洗唛**版面度量**的单一真值（issue #7776 建立 → **#7816 固定纸型** → **2026-10-27 纸长 150 → 110 → 119、正文 12pt → 11pt**）。
 *
 * ## 三次用户裁定的关系（别把前一次读成"仍然有效"）
 *
 * - 2026-10-25（#7776）：「字体太小了，可以把长度延长些，因为长度可以无限长……上下两头留白太多了」
 *   ⇒ 当版把纸长做成**按内容撑开**（夹在 70~150mm）。
 * - **2026-10-26（#7816）**：「水洗唛长度不足，设置为打印50*150」「字体还是太小，可以再大一点」
 *   ⇒ 纸型**固定 50mm × 150mm**（动态纸长整体退场），正文字号 9pt → **12pt**。
 * - **2026-10-27（现行）**：「客户要求小于120mm」「要不字体小一号？」⇒ 纸型固定 **50mm × 119mm**、
 *   正文 12pt → **11pt**；「二维码不能直接沉底，务必和底部留点距离」⇒ 码下沿与纸底（底部虚线）恒 ≥ **6mm**。
 *   ⇒ 现在的纸长只有一个来源：介质矩阵 `label-50x119.pageBoxMm` / `pageSize`（本文件不写第二份）。
 *   （同日更早的 50×110/12pt 只能装 11 行，已被本条取代。）
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
 * 版心宽 = 50 − 2 × 1.2 = **47.6mm**；11pt 汉字 ≈ 3.88mm ⇒ 每行约 **12.3 个汉字**
 * （12pt 时代是 11.2 个字）。119mm 的可用高度 = 119 − 1.2（上内边距）− 6（下沿净空）= **111.8mm**
 * ⇒ 满字段 15 行 = **110.99mm ≤ 111.8mm**（余 0.81mm）**刚好装下**；16 行 = 115.65mm > 111.8mm
 * ⇒ **有折行即裁**（文字块 `overflow-hidden`，二维码永不被裁且离底 ≥ 6mm；预算账见 `TaskCardPrint.tsx`）。
 */

/** 标签本体**上 / 左 / 右**内边距（mm）—— 与 `.task-card-label { padding: 1.2mm 1.2mm 6mm }` 的 1.2mm 同一口径；下沿不是内边距而是净空（见 `WASH_LABEL_BOTTOM_CLEARANCE_MM`） */
export const WASH_LABEL_PADDING_MM = 1.2
/** 正文行高倍数 —— 与 `.task-card-label { line-height: 1.2 }` 同一口径 */
export const WASH_LABEL_LINE_HEIGHT = 1.2
/** 正文基准字号（pt）—— 与 `.task-card-label { font-size }` 同一口径（2026-10-26：9pt → 12pt；2026-10-27 晚：12pt → 11pt） */
export const WASH_LABEL_BODY_FONT_PT = 11
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
/**
 * 二维码与正文之间隔**几行**（2026-10-26 用户逐字「二维码不要沉底，跟文字隔两行即可」）。
 * 行高 = {@link WASH_LABEL_BODY_FONT_PT} × {@link WASH_LABEL_LINE_HEIGHT} ⇒ 与系统打印的
 * `mt-[9.31mm]`（2 × 11pt × 1.2 = 26.4pt）**同源**，改一处两条通道一起变。
 */
export const WASH_LABEL_QR_TEXT_GAP_LINES = 2
/**
 * 纸面下沿（底部虚线）之上必须留出的空白（mm）—— 二维码不得贴虚线（用户 2026-10-26
 * 「要离底部虚线留空」；2026-10-27 再次逐字「二维码不能直接沉底，务必和底部留点距离」）。
 * 🔴 **从纸边起算**：系统打印 = `.task-card-label` 的 `padding-bottom: 6mm`；
 * 画布通道 = `wash-label.ts` 的 `footerBottomMax = heightPx - 本值`（两条通道同一数值，改一处另一处会红）。
 */
export const WASH_LABEL_BOTTOM_CLEARANCE_MM = 6
