/**
 * 省料看板的**纯前端薄助手**（读面 issue #5159；首屏形态按 issue #6459 用户裁定重做）。
 *
 * 🔴 本文件只做两件事：①「无数据」与真值的**区分渲染**；② **文案组装**（把服务端口径翻译成人话）。
 *
 * 它**不做**（本仓库明令的口径红线，见 `migao-dev-flow` §15 / §22）：
 * - **不算米数 / 不算占比 / 不算金额 / 不算环比**：`savedMeters` / `savedAmount` / `le0_2Share` /
 *   `comparison.*` 全部**原样渲染服务端值** —— 要求是「看板汇总与逐单落账**逐值相等**」，
 *   在浏览器里再算一遍就是第二份会漂的口径（本仓点名的 bug 类）。
 * - **不判好坏**：`变好了 / 变差了 / 持平 / 还判不出` 一律由服务端 `verdict` **映射**得到
 *   （见 {@link verdictWord}）—— 页面上没有一处自己的比较或结论。
 * - **不写死数字**：档位文案（如「≤0.2 米」）**一律取自服务端** `buckets[].label`
 *   （§22 基线纪律①）。写死一个数 = 造第二份口径，改了档位而说明不跟着变 ⇒ 说明变假话。
 *
 * 🔴 **文案纪律**（issue #6459，用户逐字「这么多废话文字留在页面上只会干扰用户」）：
 * 本文件产出的**首屏**文案 = 页头一句「怎么算的」（{@link savedRule}）+ 趋势表一句
 * （{@link batchTrendNote}）；其余口径全部收进折叠区（{@link footnotes}）。
 * **没有**门道卡 / 术语词典 / 逐卡 hint —— 要加一句话之前先问：它是不是数据本身？不是就别放。
 *
 * 🔴 **内部口径词不上屏**：`切换后` / `存量导入` / `来源未知` 这类**服务端分组标签**
 * （`SavingMetricViews.cohortLabel`）一个都不许出现在本文件与页面里 ——
 * 新用户读不懂（issue #6459 用户逐字「让新用户如何理解」）。
 * 类级元守卫 = `frontend/admin-web/tests/unit/user-copy-jargon-guard.test.ts` 的形态③。
 * ⚠️ 边界（照实登记）：元守卫扫的是**源码字面量**，服务端**下发的字符串**（例如黄金策会话卡
 * `BatchStockCard` 直接渲染 `cohortLabel`）不在它的射程内 —— 那一面另单登记，本单**有意不做**。
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

/** 时间桶文案：`null`（批次未记收货日期）⇒ 不猜 */
export function formatPeriod(period: string | null | undefined): string {
  return period ? period : '未记收货日期'
}

/** 金额读不出的行数提示（`unknownCostLines > 0` ⇒ 金额不含这些行，必须说出来） */
export function unknownCostHint(unknownCostLines: number | null | undefined): string | null {
  const n = toNumber(unknownCostLines)
  return n === null || n <= 0 ? null : `另有 ${n} 行未记批次均价，金额不含这些行`
}

/**
 * 页头**唯一一句**规则（issue #6459：用户要求「用数据和规则说清楚我们是如何省下多少布料」）。
 *
 * 🔴 它是**解释**，不是第三个数据源：两个数字仍原样来自服务端 `total` / `comparison`。
 */
export function savedRule(): string {
  return '省下的布 = 按公式该领的米数 − 排料实际领走的米数；省下的钱 = 省下的布 × 那批布当时的进价。'
}

/**
 * 趋势表标题：档位文案取自**服务端** `buckets[].label`（真值渲染，不写死数字）。
 *
 * 服务端恒回四档，故正常情况下 `buckets[0]` 必在；取不到时退回**不含数字**的措辞
 * （绝不自己编一个「≤0.2 米」）。
 */
export function batchTrendTitle(bucketLabel?: string | null): string {
  return bucketLabel
    ? `几乎用完的布（剩余 ${bucketLabel}）· 批数`
    : '几乎用完的布（剩余最少的那一档）· 批数'
}

/** 趋势表说明：**一句话**（加长即违反 issue #6459 的「少废话」裁定） */
export function batchTrendNote(): string {
  return '剩得越少，说明这批布被用得越干净。'
}

/** 「口径与边界」折叠区：首屏之外的口径一次说完（默认收起，不干扰读数字的人） */
export function footnotes(timezone?: string | null): string[] {
  return [
    savedRule(),
    '无数据 ≠ 0：算不出的地方显示「无数据」（0 会被读成「没有浪费」）。',
    '省下的钱是下界：读不出进价的行不计入金额，表里会写出有几行。',
    '趋势只统计系统里采购入库的批次：开业时导入的老库存不算，否则历史包袱会让改善永远看不出来。',
    '明细表按「这笔料哪个月被用掉」分月；趋势表按「这批布哪个月进的货」分月 —— 两张表的时间不是一回事。',
    '占比按批数算，不是按米数；占比的方向会被排料省料反向影响，故只给数、不给好坏。',
    `时区：${timezone || '-'}。`,
  ]
}

/** 环比单位：米 / 元 / 占比 / 米每平方米 */
export type ComparisonKind = 'meters' | 'amount' | 'share' | 'perM2'

/**
 * 环比文案。
 *
 * 🔴 **好坏词只来自服务端 `verdict`**（{@link verdictWord}）；`verdict` 为 `null` ⇒
 * 只给两期数值并**明说「不给好坏」**。期间同理来自服务端 —— 前端不自己算「上个月」，
 * 也不推断哪一期是「本期」。
 */
export function comparisonText(
  delta: MetricDeltaLite | null | undefined,
  kind: ComparisonKind
): string | null {
  if (!delta || !delta.period) return null
  const now = delta.current
  if (now === null || now === undefined) return null
  const fmt = (v: number | string | null | undefined): string => {
    if (kind === 'share') return formatShare(v)
    if (kind === 'amount') return `${formatMetric(v)} 元`
    if (kind === 'perM2') return `${formatMetric(v, 4)} 米/㎡`
    return formatMeters(v)
  }
  if (!delta.previousPeriod || delta.previous === null || delta.previous === undefined) {
    return `本期 ${delta.period}：${fmt(now)}（没有上期数据，还判不出变化）`
  }
  const word = verdictWord(delta.verdict)
  const tail = word ?? '不给好坏（这个数的方向会被排料省料反向污染）'
  return `上期 ${delta.previousPeriod}：${fmt(delta.previous)} → 本期 ${delta.period}：${fmt(now)} · ${tail}`
}

/**
 * 服务端 `verdict` → 人话。
 *
 * `null` 返回 `null` = **有意不给好坏**（与「判不了」的 `unknown` 是两件事）；
 * 未知取值同样返回 `null`（不猜、不回落成「持平」）。
 */
export function verdictWord(verdict?: string | null): string | null {
  if (verdict === 'better') return '变好了'
  if (verdict === 'worse') return '变差了'
  if (verdict === 'same') return '持平'
  if (verdict === 'unknown') return '还判不出'
  // 「本期还没过完」：拿半截期间与整期比大小，会把「这个月还没进货」读成「买得更克制」⇒ 不给方向
  if (verdict === 'partial') return '本期还没过完，环比先不算'
  return null
}

/** 首屏两个大数字的取值（**服务端原值**，前端不参与任何计算） */
export interface MetricView {
  /** 本期（服务端 `comparison.*.period`）；`null` ⇒ 后端未部署或该指标本期读不出 */
  period: string | null
  /** 大数字：本期值；读不出 ⇒ 退回**服务端累计值**（`total`），不自己算 */
  value: number | string | null | undefined
  /** 副行：服务端累计值（`total`） */
  cumulative: number | string | null | undefined
}

/**
 * 首屏大数字 = 服务端「本期」值；后端未部署（无 `comparison`）⇒ 退回服务端**累计**值。
 *
 * 🔴 两个来源都是服务端给的：本函数只做**取值**，不做任何四则运算。
 */
export function metricView(
  delta: MetricDeltaLite | null | undefined,
  cumulative: number | string | null | undefined
): MetricView {
  const current = delta?.current
  const hasCurrent = current !== null && current !== undefined
  return {
    period: hasCurrent ? (delta?.period ?? null) : null,
    value: hasCurrent ? current : cumulative,
    cumulative,
  }
}

/** 环比读面的最小形状（只声明用到的字段，避免与 `types` 循环依赖） */
export interface MetricDeltaLite {
  period?: string | null
  previousPeriod?: string | null
  current?: number | string | null
  previous?: number | string | null
  verdict?: string | null
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
