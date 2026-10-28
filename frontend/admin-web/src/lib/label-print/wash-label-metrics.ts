/**
 * 水洗唛**版面度量**的单一真值（issue #7776 建立 → #7816 固定纸型 → 2026-10-27 50×119/11pt
 * → **2026-10-28（issue #7979）纸型 50×140、顶部留白 15mm、二维码紧挨正文**）。
 *
 * ## 历次用户裁定的关系（别把前一次读成"仍然有效"）
 *
 * - 2026-10-25（#7776）：「字体太小了，可以把长度延长些，因为长度可以无限长……上下两头留白太多了」
 *   ⇒ 当版把纸长做成**按内容撑开**（夹在 70~150mm）。
 * - 2026-10-26（#7816）：「水洗唛长度不足，设置为打印50*150」「字体还是太小，可以再大一点」
 *   ⇒ 纸型固定 50mm × 150mm，正文字号 9pt → 12pt。
 * - 2026-10-27（#7960）：「客户要求小于120mm」「要不字体小一号？」⇒ 纸型 50mm × 119mm、正文 12pt → 11pt。
 * - **2026-10-28（#7979，现行）**：「水洗唛还是要调整到50*150，当前是50*120，多的30要添加到顶部和
 *   底部虚线下处各15，顶部需要让最顶端的字体上面留白15」+「二维码紧挨文字排版，当前留白太多，
 *   这样尺寸就能缩小到50*140」⇒ 纸型 **50mm × 140mm**；**顶部留白 15mm**（最顶端的字 = 纸面抬头
 *   首行，距纸边 15mm）；**二维码紧挨正文**（正文末行之下只留 0.5mm 块间距，不再空两行）；
 *   **码下沿距纸边（底部虚线）15mm**。
 *   ⇒ 纸长只有一个来源：介质矩阵 `label-50x140.pageBoxMm` / `pageSize`（本文件不写第二份）。
 *
 * ## 单一真值纪律（本模块是什么、不是什么）
 *
 * - **是**：字号 / 行高 / 左右内边距 / 顶部留白 / 底部净空 / 块间距 / 二维码边长的**唯一一份** TS 常量 ——
 *   画布通道（`wash-label.ts`）与系统打印通道（`TaskCardPrint.tsx` 的 CSS / Tailwind 字号）都从这里取。
 * - **不是**：内容真值（印什么、行序 = `lib/wash-label-content.ts`）、也不是纸型真值（`lib/print-media.json`）。
 * - CSS 与 TS 两份字面量的一致性由 `tests/unit/lib/label-print/wash-label-metrics.test.ts` 钉住
 *   （它**解析组件源码**逐值比对）—— 改 CSS 不改这里 ⇒ 红。
 *
 * ## 字号取值理由（50mm 宽的物理约束）
 *
 * 版心宽 = 50 − 2 × 1.2 = **47.6mm**；11pt 汉字 ≈ 3.88mm ⇒ 每行约 **12.3 个汉字**（12pt 时代是 11.2 个）。
 * 140mm 扣掉**上下留白各 15mm** ⇒ 可用高度 = 140 − 15 − 15 = **110mm**
 * ⇒ 满字段 15 行 = 抬头块 10.16 + 块距 0.5 + 正文 69.85 + 块距 0.5 + 二维码 21.17 = **102.18mm ≤ 110mm**
 * （余 7.82mm ≈ 1.6 行）；17 行 = 111.49mm > 110mm ⇒ **有折行即裁**（文字块 `overflow-hidden`；
 * 二维码永不被裁、离纸边恒 ≥ 15mm；预算账见 `TaskCardPrint.tsx`）。
 */

/** 纸面行的类型（引真值模块的类型，避免本文件另立一套键名） */
import type { WashLabelRowKey } from '@/lib/wash-label-content'

/** 标签本体**左 / 右**内边距（mm）—— 与 `.task-card-label { padding: 15mm 1.2mm 15mm }` 的左右值同一口径；
 *  上沿是「顶部留白」（见 `WASH_LABEL_TOP_BLANK_MM`）、下沿是「底部净空」（见 `WASH_LABEL_BOTTOM_CLEARANCE_MM`） */
export const WASH_LABEL_PADDING_MM = 1.2
/**
 * **顶部留白**（mm）：最顶端的字（纸面抬头首行）上方必须空出的高度，**从纸边起算**。
 *
 * 用户 2026-10-28 逐字「顶部需要让最顶端的字体上面留白15」。
 * 🔴 系统打印 = `.task-card-label` 的 `padding-top: 15mm`；画布通道 = `wash-label.ts` 的 `topBlank`
 * （两条通道同一数值，改一处另一处会红）。
 */
export const WASH_LABEL_TOP_BLANK_MM = 15
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
/**
 * 块间距（mm）—— 抬头块 → 正文块、正文块 → 二维码**共用同一个值**（与 `mt-[0.5mm]` 同口径）。
 *
 * 🔴 二维码这一处 2026-10-28 由「隔两行（9.31mm）」改成本值（用户逐字「二维码紧挨文字排版，
 * 当前留白太多」）—— 码**紧挨正文**，纸长才能从 150mm 收到 140mm；两条通道同读这一个常量。
 */
export const WASH_LABEL_BLOCK_GAP_MM = 0.5
/**
 * 需要**加黑加粗**的纸面行（用户 2026-10-28 逐字「把加工项信息加黑加粗」）。
 *
 * 「加工项」= 加工方式那一行（`craft`，值形如 `韩褶 · 超高 · 倒幅 · 双开 · 定型`）——
 * 它是车间一眼要看的活：哪些附加项做了（超高 / 超宽 / 倒幅 / 定型…）。
 *
 * 🔴 **单一真值**：系统打印（`TaskCardPrint` 的 `font-bold`）与位图通道（`wash-label.ts` 的 `bold` 字体）
 * 都读这一份 —— 一方加粗一方不加 ⇒ 两条通道画得不一样，`wash-label-metrics.test.ts` 判红。
 */
export const WASH_LABEL_EMPHASIS_ROW_KEYS: readonly WashLabelRowKey[] = ['craft']

/**
 * 纸面下沿（底部虚线）之上必须留出的空白（mm）—— 二维码不得贴虚线
 * （用户 2026-10-26「要离底部虚线留空」；2026-10-27 再次逐字「二维码不能直接沉底，务必和底部留点距离」；
 * 2026-10-28 定值 **6mm → 15mm**：「多的30要添加到顶部和底部虚线下处各15」）。
 * 🔴 **从纸边起算**：系统打印 = `.task-card-label` 的 `padding-bottom: 15mm`；
 * 画布通道 = `wash-label.ts` 的 `footerBottomMax = heightPx - 本值`（两条通道同一数值，改一处另一处会红）。
 */
export const WASH_LABEL_BOTTOM_CLEARANCE_MM = 15
