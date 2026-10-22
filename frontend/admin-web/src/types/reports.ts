// 报表读面的类型（issue #7376 / #7377）。
//
// 🔴 四张表统一口径：`totals` 在**没有数据时是 null**（不是 0）；
// 未定价 / 未采集 / 未发生的分项同样是 null，并用 `complete` + `unknownComponents` 说明缺哪几项。

export interface MarginReportRow {
  orderId: string
  orderNo: string
  status: string | null
  revenue: number | null
  refunded: number | null
  fabricCost: number | null
  laborCost: number | null
  grossMargin: number | null
  costKnown: boolean
}

export interface ReportOrderMargins {
  startDate: string | null
  endDate: string | null
  hasData: boolean
  rows: MarginReportRow[]
  totals: {
    revenue: number | null
    refunded: number | null
    fabricCost: number | null
    laborCost: number | null
    grossMargin: number | null
  } | null
  unknownCostOrders: number
}

export interface ReportInventoryAging {
  slowMovingDays: number
  hasData: boolean
  rows: {
    batchId: number
    batchNo: string
    skuCode: string | null
    warehouse: string | null
    onHand: number | null
    lastMovementDate: string | null
    daysSinceMovement: number
    slowMoving: boolean
    reason: string
  }[]
  totals: { onHand: number | null; slowMovingOnHand: number | null; slowMovingBatches: number } | null
  undeterminedRows: number
}

export interface ReportStaffPerformance {
  startDate: string | null
  endDate: string | null
  hasData: boolean
  rows: {
    staffId: string | null
    staffName: string | null
    orderCount: number
    revenue: number | null
    avgOrderValue: number | null
  }[]
  totals: { orderCount: number; revenue: number | null } | null
  unattributedOrders: number
}

export interface ReportQualityCost {
  startDate: string | null
  endDate: string | null
  components: {
    code: string
    label: string
    amount: number | null
    known: boolean
    note: string
    unknownItems: number
  }[]
  total: number | null
  complete: boolean
  unknownComponents: string[]
}
