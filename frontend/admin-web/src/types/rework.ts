// 返工单读面（issue #7377 段 2 后端 / 本页 = 商家面）
//
// 与后端 `ReworkOrderView` **逐字对齐**：状态机 draft → in_progress → done（或 cancelled），
// 金额字段**故意没有** —— 返工的成本走「返工报工」的计件金额，返工单本身不产生钱。

export type ReworkStatus = 'draft' | 'in_progress' | 'done' | 'cancelled'

export interface ReworkOrder {
  id: string
  reworkNo: string
  afterSalesTicketId: string
  orderId: string | null
  processingOrderId: string | null
  status: ReworkStatus
  reason: string | null
  createdByName: string | null
  startedAt: string | null
  completedAt: string | null
}

export interface ReworkOrderCreateRequest {
  afterSalesTicketId: string
  reason?: string
  processingOrderId?: string
}
