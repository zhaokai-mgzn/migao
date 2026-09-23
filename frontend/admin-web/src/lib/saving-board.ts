/**
 * 省料看板的**纯前端薄助手**（issue #5159 L2/L3）。
 *
 * 🔴 本文件**只做两件事**：①「无数据」与真值的**区分渲染**；② 两条指标的**文案组装**。
 *
 * 它**不做**（本仓库明令的口径红线，见 `migao-dev-flow` §15 / §22）：
 * - **不算米数 / 不算占比 / 不算金额**：`savedMeters` / `savedAmount` / `le0_2Share` /
 *   `metersPerM2` 全部**原样渲染服务端值** —— 要求是「看板汇总与逐单落账**逐值相等**」，
 *   在浏览器里再算一遍就是第二份会漂的口径（本仓点名的 bug 类）。
 * - **不写死数字**：档位文案（如「≤0.2 米」）**一律取自服务端** `buckets[].label`
 *   （§22 基线纪律①：文案里不出现数字，数值由真值渲染）。写死一个数 = 造第二份口径，
 *   改了档位而说明不跟着变 ⇒ 说明变假话。
 */

/** 无数据的统一文案（判据 4：不得用 `0` 冒充 —— 0 会被读成「没有浪费」） */
export const NO_DATA = '无数据'

/** 量不出 / 缺值 ⇒ `无数据`；**真 0 照实回 `0`**（两者必须可区分，判据 4 的落点） */
export function formatMetric(value: number | string | null | undefined, digits = 2): string {
  const n = toNumber(value)
  if (n === null) return NO_DATA
  return digits === 0 ? String(Math.round(n)) : trimTrailingZeros(n.toFixed(digits))
}

/** 占比渲染（服务端给 0~1 的比；`null` ⇒ 无数据） */
export function formatShare(share: number | string | null | undefined): string {
  const n = toNumber(share)
  return n === null ? NO_DATA : `${(n * 100).toFixed(1)}%`
}

/** 米数渲染（服务端给米；`null` ⇒ 无数据） */
export function formatMeters(meters: number | string | null | undefined, digits = 2): string {
  const text = formatMetric(meters, digits)
  return text === NO_DATA ? NO_DATA : `${text} 米`
}

/**
 * 两条指标的卡片规格（**恒两条** —— 判据 3：缺任一条 ⇒ 红）。
 *
 * 🔴 **必须并用**（#5144 已锁）：
 * ①「剩余最小档的批次占比 ↑」治「用不尽」；②「入库/采购总米数 ↓」治「买太多」。
 * **单看①会被 A 类排料误导**：排料省料 ⇒ 批次**剩得更多** ⇒ 只留①会把效率提升**显示成变差**。
 *
 * 卡片的 label 里的档位文案来自**服务端** `cohorts[].buckets[0].label`（真值渲染）。
 * 服务端恒回四档，故正常情况下 `buckets[0]` 必在；取不到时退回**不含数字**的措辞
 * （绝不自己编一个「≤0.2 米」）。
 */
export function metricCards(board: SavingBoardLite | null): SavingMetricCard[] {
  const bucketLabel = board?.cohorts?.[0]?.buckets?.[0]?.label
  const purchase = board?.cohorts?.find((c) => c.cohort === 'purchase')
  return [
    {
      key: 'le_0_2',
      label: bucketLabel ? `剩余 ${bucketLabel} 的批次占比` : '剩余最小档的批次占比',
      value: formatShare(purchase?.le0_2Share),
      hint: '治「用不尽」—— 越多批次被用到几乎不剩，说明料真的被用掉了',
      testId: 'saving-metric-le-0-2',
    },
    {
      key: 'purchased',
      label: '入库/采购总米数',
      value: formatMeters(board?.trend?.purchasedTotalMeters),
      hint: '治「买太多」—— 切换后的采购入库总米数，不含存量导入',
      testId: 'saving-metric-purchased',
    },
  ]
}

/**
 * 「两条必须并用」的说明文案（**页面上必须看得见**，不是只写进文档）。
 *
 * 与 {@link metricCards} 同源：档位文案同样取自服务端 label。
 */
export function coexistenceNote(board: SavingBoardLite | null): string {
  const bucketLabel = board?.cohorts?.[0]?.buckets?.[0]?.label
  const first = bucketLabel ? `「剩余 ${bucketLabel} 的批次占比」` : '「剩余最小档的批次占比」'
  return `两条指标必须并用：①${first}治「用不尽」，②「入库/采购总米数」治「买太多」。`
    + '单看①会被排料省料误导 —— 排料省料 ⇒ 批次剩得更多 ⇒ 只留①会把效率提升显示成变差。'
}

/** 存量导入组的固定标识（判据 2：它必须**单列**，不进「切换后」的分子分母） */
export const OPENING_COHORT = 'opening'

/** 来源组标签：存量导入组额外标「单列」徽标（页面据此与「切换后」并列而不是相加） */
export function cohortBadge(cohort: string): string | null {
  if (cohort === OPENING_COHORT) return '存量导入·单列'
  if (cohort === 'unknown') return '来源未知'
  return null
}

/** 时间桶文案：`null`（批次未记收货日期）⇒ 不猜 */
export function formatPeriod(period: string | null | undefined): string {
  return period ? period : '未记收货日期'
}

/** 金额读不出的行数提示（`unknownCostLines > 0` ⇒ 金额不含这些行，必须说出来） */
export function unknownCostHint(unknownCostLines: number | null | undefined): string | null {
  const n = toNumber(unknownCostLines)
  return n === null || n <= 0 ? null : `另有 ${n} 行未记批次均价，金额不含这些行`
}

export interface SavingMetricCard {
  key: string
  label: string
  value: string
  hint: string
  testId: string
}

/** 本助手消费的最小读面形状（只声明用到的字段，避免与 `types` 循环依赖） */
export interface SavingBoardLite {
  cohorts?: {
    cohort: string
    le0_2Share?: number | null
    buckets?: { label?: string }[]
  }[]
  trend?: { purchasedTotalMeters?: number | null } | null
}

function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'string' ? Number(value) : value
  return Number.isFinite(n) ? n : null
}

/** `2.70` → `2.7`、`2.00` → `2`（纯展示，不改数值） */
function trimTrailingZeros(text: string): string {
  return text.includes('.') ? text.replace(/\.?0+$/, '') : text
}
