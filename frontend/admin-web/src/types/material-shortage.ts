/**
 * 用品级用料缺口与耗尽风险的类型（issue #6280 后端 / #6282 页面）。
 *
 * 为什么单独一个文件：`src/types/index.ts` 在 `tests/unit_ci_workflows/loc_freeze_ledger.json`
 * 的冻结面里（只许缩短），新增类型面下沉到本文件即可，不必抬高冻结值。
 */

// ── 用料缺口与耗尽风险（具名跨域视图 `material_shortage`，issue #6280 / 页面 #6282）─────

/**
 * 六档风险分层（服务端 `MaterialShortageViews.RISK_BANDS`，**行序的第一键**，紧急度降序）。
 *
 * `unknown` = 该商品单位不可比（需求与缺口**读不出**），与「不紧急」不是一回事 ⇒ 排最后。
 */
export type MaterialShortageBand = 'blocked' | 'critical' | 'soon' | 'short' | 'safe' | 'unknown'

/** 逐字段三态（`reason == null ⟺ status == wired`） */
export interface MaterialShortageFieldInfo {
  status: 'wired' | 'not_wired' | 'incomplete'
  reason?: string | null
  source?: string | null
  truth: 'has_truth' | 'no_truth'
  note?: string | null
  label?: string | null
}

/**
 * 视图行（一行 = 一个**商品**）。
 *
 * 🔴 服务端 `default-property-inclusion: non_null` ⇒ 读不出的字段**键缺失**（**不是 0**）：
 * 单位不可比时 `demandQty` / `demandLines` / `orderCount` / `gapMeters` 全部缺键；
 * 交期未知时 `daysToDeadline` 缺键。页面必须渲染「未知」，不得回落成 0。
 */
export interface MaterialShortageRow {
  productId: string
  productName: string
  /** 需求 = Σ 未完成订单行用量（米）；**单位不可比 ⇒ 缺键** */
  demandQty?: number | null
  demandLines?: number | null
  orderCount?: number | null
  /** 供给 = Σ SKU 库存（米）—— 不读 `products.stock`（派生冗余列） */
  stockMeters?: number
  /** 需求 − 供给；负 = 有余量（照实返回）；**单位不可比 ⇒ 缺键** */
  gapMeters?: number | null
  riskBand: MaterialShortageBand
  /** 距交期天数；**缺键 = 紧迫性未知**（不是「今天到期」） */
  daysToDeadline?: number | null
  earliestRequiredDeliveryDate?: string | null
  /** v1 未接线 ⇒ 恒缺键（历史深度不足以开预测层） */
  ratePerWeek?: number | null
  exhaustDate?: string | null
  /** 本行读不出的字段名（服务端口径；**不上屏**） */
  unwired?: string[]
}

/** 单位不可比的披露（「未知 ≠ 0」的落点） */
export interface MaterialShortageNonComparable {
  lines: number
  products: number
}

/** 历史深度判定 —— 预测层的**唯一**开关（`sufficient == false` ⇒ 速率 / 耗尽日一律未知） */
export interface MaterialShortageHistoryDepth {
  weeks: number
  activeWeeks: number
  requiredWeeks: number
  sufficient: boolean
  reason?: string | null
}

/** 用料缺口视图根（键名 = 冻结契约 v1；`limit` 只截断 `rows`，聚合用全量行） */
export interface MaterialShortageView {
  view: string
  tenantId: number
  asOf: string
  /** 口径自述（**内部键名**，不上屏） */
  basis?: Record<string, string>
  /** 逐字段三态（**字段名**，不上屏） */
  fields?: Record<string, MaterialShortageFieldInfo>
  rows: MaterialShortageRow[]
  count: number
  rowsTotal: number
  truncated: boolean
  noTruthFields?: string[]
  hasTruthFields?: string[]
  /** 六档计数（恒六键、空档回 0；用**全量**行算，不随 limit 变） */
  bandCounts?: Record<string, number>
  nonComparable?: MaterialShortageNonComparable
  nonComparableLines?: number
  nonComparableProducts?: number
  historyDepth?: MaterialShortageHistoryDepth
}
