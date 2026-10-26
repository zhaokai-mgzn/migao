// 返工单读面（issue #7377 段 2 后端 / 本页 = 商家面）
//
// 与后端 `ReworkOrderView` **逐字对齐**：状态机 draft → in_progress → done（或 cancelled），
// 金额字段**故意没有** —— 返工的成本走「返工报工」的计件金额，返工单本身不产生钱。

export type ReworkStatus = 'draft' | 'in_progress' | 'done' | 'cancelled'

/** 返工单来源：售后开单 / 车间工人报返工（issue #7860）。 */
export type ReworkSource = 'after_sales' | 'worker'

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

  // 来源与车间报返工带出来的现场信息（issue #7860）。
  // 只有 `source='worker'` 的行才有工序 / 数量 / 报工人 —— 售后开单没有这三项，是 `null` 而不是 0。
  source: ReworkSource
  operationName: string | null
  qty: number | null
  workerName: string | null
  orderNo: string | null
  /** 加工单号：展示优先于 `processingOrderId`（后者是老数据/内部 id）。 */
  processingOrderNo: string | null
}

export interface ReworkOrderCreateRequest {
  afterSalesTicketId: string
  reason?: string
  processingOrderId?: string
}
