/**
 * 本次打印的目标（issue #4965 / #5651 → 2026-10-01 收敛到 `lib/print-doc.ts`，issue #5914）。
 *
 * 🔴 **每新增一份纸质单据都必须登记 target**，唯一真值 = `lib/print-doc.ts` 的 `PRINT_TARGETS`
 * （`PRINT_TARGET_SPECS` 同时给它标题与介质 id）。口径（#5914 起）：
 * **一次只允许一份单据上纸** —— 各单据的 `@page` 与打印态 `display` 都按 target 限定
 * （同页多份并存时 `@page` 是**文档级**规则、最后声明的那条赢 ⇒ 纸型会被兄弟单据覆盖）。
 */
export type { PrintTarget } from '@/lib/print-doc'
export { PRINT_TARGETS, PRINT_TARGET_SPECS, usePrintDoc } from '@/lib/print-doc'
// 打印前的**纸面自检层**（真尺寸纸框 + 溢出/页数自检 + 「打印 / 复制截图」，issue #5914）
export { default as PrintDocPreview } from './PrintDocPreview'

export { default as OrderTable } from './OrderTable'
export { default as RemarkPopover } from './RemarkPopover'
export { default as OrderStatusBadge } from './OrderStatusBadge'
export { default as OrderTimeline } from './OrderTimeline'
export { default as OrderProgressSteps } from './OrderProgressSteps'
export { default as OrderItemList } from './OrderItemList'
// 订单详情页「费用构成」（issue #5843）：商品合计 + 加工费 + 其它构成 = 订单金额
export { default as OrderFeeBreakdown } from './OrderFeeBreakdown'
export { default as LogisticsInfo } from './LogisticsInfo'
export { default as LogisticsForm } from './LogisticsForm'
export { default as CloseOrderModal } from './CloseOrderModal'
export { default as RefundOrderModal } from './RefundOrderModal'
export { default as RemarkModal } from './RemarkModal'
export { default as ProcessingOrderBlock } from './ProcessingOrderBlock'
// 订单加急 / 要求到货日（issue #5177）—— 订单详情页上的改单控件（PUT /orders/{id}/urgency）
export { default as OrderUrgencyPanel } from './OrderUrgencyPanel'
export { default as ShipmentDoc } from './ShipmentDoc'
export { default as QuotationDoc } from './QuotationDoc'
// 加工单（A4，issue #5651）与销售单（三联纸 241mm × 140mm，issue #5651）——
// 介质矩阵见 `lib/print-media.json`（介质是参数，不是各写一份的副本）
export { default as ProcessingDoc } from './ProcessingDoc'
export { default as SalesDoc } from './SalesDoc'
// 修改订单（**待付款**内容编辑，issue #5842）：收货信息 / 商品明细 / 加工项 + 金额服务端重算
export { default as EditOrderContentModal } from './EditOrderContentModal'
