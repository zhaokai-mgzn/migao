/**
 * 本次打印的目标（issue #4965 / #5651）。
 *
 * 🔴 **每新增一份纸质单据都必须在这里加一个 target**：订单详情页**同页挂着多份**单据，
 * 它们的 `visibility: visible` 打印防御**同特异性**，后渲染者胜 ⇒ 不加限定会把兄弟单据
 * 重新藏成 invisible（补打纸面空白，#4965 实测）。调用方「点谁置谁」。
 */
export type PrintTarget = 'shipment' | 'quotation' | 'processing' | 'sales'

export { default as OrderTable } from './OrderTable'
export { default as RemarkPopover } from './RemarkPopover'
export { default as OrderStatusBadge } from './OrderStatusBadge'
export { default as OrderTimeline } from './OrderTimeline'
export { default as OrderProgressSteps } from './OrderProgressSteps'
export { default as OrderItemList } from './OrderItemList'
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
