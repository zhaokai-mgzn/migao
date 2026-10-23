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

/** 账龄一档（金额 + 该档单数；`bucket` 是稳定标识，`label` 是中文名）。 */
export interface AgingBucket {
  bucket: string
  label: string
  amount: number | null
  orderCount: number
}

/** 按客户的账龄分行。 */
export interface AgingCustomer {
  customerName: string | null
  customerPhone: string | null
  paymentTermsDays: number | null
  total: number | null
  overdue: number | null
  buckets: AgingBucket[]
}

/**
 * 应收账龄报表（issue #7376 段 5）。
 *
 * 🔴 与其余四张表同口径：`totals` 在**没有欠款单时是 null**（不是 0）——
 * 页面据此写「暂无数据」，绝不画成「应收 0.00」。
 */
export interface ReportReceivableAging {
  asOf: string | null
  hasData: boolean
  customerCount: number
  buckets: AgingBucket[]
  customers: AgingCustomer[]
  totals: { outstanding: number | null; overdue: number | null; orderCount: number } | null
}
