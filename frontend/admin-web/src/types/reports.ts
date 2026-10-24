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

/** 质量成本维度汇总的一行（issue #7377 段 5）。 */
export interface QualityCostBreakdownRow {
  key: string
  label: string
  rework: number | null
  reworkLines: number
  /** 报废工时（issue #7377 段 8）：与返工分列，别加在一起看 */
  scrap: number | null
  scrapLines: number
  compensation: number | null
  compensationCount: number
  total: number | null
}

/**
 * 质量成本的维度汇总（issue #7377 段 5）。
 *
 * 🔴 恒等式：`totals == Σrows + unattributed` —— 归属不了的金额**必须露出来**，
 * 页面据此写「另有 X 无法归属」，不许把它们悄悄丢掉。
 */
export interface ReportQualityCostBreakdown {
  dimension: 'customer' | 'process' | 'product'
  scope: string
  startDate: string | null
  endDate: string | null
  hasData: boolean
  rows: QualityCostBreakdownRow[]
  totals: {
    rework: number | null
    reworkLines: number
    scrap: number | null
    scrapLines: number
    compensation: number | null
    compensationCount: number
    total: number | null
  } | null
  unattributed: {
    rework: number | null
    reworkLines: number
    scrap: number | null
    scrapLines: number
    compensation: number | null
    compensationCount: number
    total: number | null
    reason: string
  }
  notes: string[]
}
