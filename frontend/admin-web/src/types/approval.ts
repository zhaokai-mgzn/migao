// 审批读面（issue #7374，P1-2）：与后端 `ApprovalView` 字段逐字对齐。
//
// 五类业务对象共用一张审批表（改价 / 超授信 / 退款 / 采购超量 / 盘点差异），
// 「批一次用一次」由服务端 CAS 保证（`consumed_at` 只写一次）。

export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'withdrawn'

export type ApprovalObjectType =
  | 'credit_override'
  | 'price_change'
  | 'refund'
  | 'purchase_over'
  | 'stocktake_diff'

export interface ApprovalItem {
  id: string
  objectType: ApprovalObjectType | string
  objectRef: string
  objectLabel: string | null
  amount: number | null
  payload: string | null
  reason: string | null
  status: ApprovalStatus | string
  requestedBy: string | null
  requestedByName: string | null
  requestedAt: string | null
  decidedBy: string | null
  decidedByName: string | null
  decidedAt: string | null
  decisionNote: string | null
  /** 非空 ⇒ 这张审批已经被业务用掉了（批一次用一次）。 */
  consumedAt: string | null
  consumedRef: string | null
}
