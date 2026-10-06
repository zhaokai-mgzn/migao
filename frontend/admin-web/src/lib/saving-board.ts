/**
 * 省料看板的**纯前端薄助手**（issue #5159 L2/L3；issue #6430 重设计）。
 *
 * 🔴 本文件只做三件事：①「无数据」与真值的**区分渲染**；② **文案组装**（把服务端口径翻译成人话）；
 * ③ **纯排序**（异常优先，不改任何数值）。
 *
 * 它**不做**（本仓库明令的口径红线，见 `migao-dev-flow` §15 / §22）：
 * - **不算米数 / 不算占比 / 不算金额 / 不算环比**：`savedMeters` / `savedAmount` / `le0_2Share` /
 *   `metersPerM2` / `comparison.*` 全部**原样渲染服务端值** —— 要求是「看板汇总与逐单落账**逐值相等**」，
 *   在浏览器里再算一遍就是第二份会漂的口径（本仓点名的 bug 类）。
 * - **不判好坏**：`变好了 / 变差了 / 持平 / 还判不出` 一律由服务端 `verdict` **映射**得到
 *   （见 `verdictWord`）—— 页面上没有一处自己的比较或结论。
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
 * 三张结论卡（**原两张一个不少** —— 判据 3：两条指标缺任一条 ⇒ 红；#6430 新增第三张「省了多少」）。
 *
 * 🔴 **前两条必须并用**（#5144 已锁）：
 * ①「剩余最小档的批次占比」治「用不尽」；②「入库/采购总米数」治「买太多」。
 * **单看①会被排料误导**：排料省料 ⇒ 批次**剩得更多** ⇒ 只留①会把效率提升**显示成变差**。
 * ③ 是「省了多少」（逐单省料合计）—— 与①②是两个维度，各自独立。
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
      secondary: `${formatMetric(purchase?.le0_2Count, 0)} 批 / 共 ${formatMetric(purchase?.batchCount, 0)} 批`,
      hint: '治「用不尽」—— 越多批次被用到几乎不剩，说明料真的被用掉了；这个数低 = 还有大块布压着',
      testId: 'saving-metric-le-0-2',
    },
    {
      key: 'purchased',
      label: '入库/采购总米数',
      value: formatMeters(board?.trend?.purchasedTotalMeters),
      secondary: '只含「切换后」',
      hint: '治「买太多」—— 切换后的采购入库总米数，不含存量导入',
      testId: 'saving-metric-purchased',
    },
  ]
}

/**
 * 第三张卡 = **结论卡**（省了多少料），**不是第三个指标**（issue #6430）。
 *
 * 🔴 为什么与 {@link metricCards} 分开：`metricCards` 的契约是「**两条指标恒同在**」
 * （判据 3，锁定 —— 缺任一条即红）。省料汇总是**结论**，混进那一对会把
 * 「恒两条」悄悄放宽成「恒三条」，正好废掉那条判据想守的东西。
 */
export function savedCard(board: SavingBoardLite | null): SavingMetricCard {
  const total = board?.total
  const costHint = unknownCostHint(total?.unknownCostLines)
  return {
    key: 'saved',
    label: '省了多少料',
    value: formatMeters(total?.savedMeters),
    secondary: `${formatMetric(total?.savedAmount)} 元`,
    hint: costHint
      ? `排料比公式少领的布；${costHint}`
      : '排料比公式少领的布 —— 省料米数 × 这批布当时的均价',
    testId: 'saving-metric-saved',
  }
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

/** 门道卡的因果链（#6430）：把「为什么两个数会互相打架」讲成一句话 */
export function causalChain(): string {
  return '排料套裁得好 → 同一批布领得少 → 但这批布反而剩得更多 →「用不尽」看着更差。'
    + '所以这个看板一次给你两个数（用不尽 / 买太多）—— 两个一起看，才是真的省。'
}

/**
 * 术语词典（#6430）：新用户看不懂的词，一次性说清。
 *
 * ⚠️ 档位文案取自服务端 `buckets[].label`（真值渲染，不写死数字）。
 */
export function savedTerms(bucketLabels?: string[]): SavedTerm[] {
  const buckets = (bucketLabels ?? []).filter(Boolean)
  const bucketText = buckets.length ? buckets.join(' / ') : '四档（从小到大）'
  return [
    { term: '批次', meaning: '进货的一批（一卷）布。系统按「批」记库存，不按总数记' },
    { term: '批次余量', meaning: '这一批布还剩多少米 = 进多少 − 已用掉 + 作废回补' },
    { term: '公式米数', meaning: '按行业公式换算，这一单「该领」多少米布（只看订单，不看怎么排）' },
    { term: '排料米数', meaning: '真正排料套裁之后，实际领走（扣库存）的米数' },
    { term: '省料米数', meaning: '公式米数 − 排料米数（同一行两个口径相减，恒不为负）' },
    { term: '省料金额', meaning: '省料米数 × 这批布当时的均价；只算记得住均价的行走 ⇒ 它是「至少省了这么多」（下界）' },
    { term: '剩余分档', meaning: `按批次余量分档：${bucketText}；「几乎用完」这一档越高，说明布越是被用掉了` },
    { term: '占比的分母', meaning: '占比按**批数**算，不是按米数 —— 一次进 5000 米和一次进 3 米在分母里权重一样' },
    { term: '来源组', meaning: '这批布是从哪张入库单进来的：切换后 / 存量导入 / 来源未知' },
  ]
}

/**
 * 结论条（#6430）：先用一句人话把「所以呢」说清楚。
 *
 * 🔴 全部数值**原样取服务端**（合计腿用 `total`、来源组腿用 `cohorts[purchase]`、采购腿用 `trend` 合计），
 * 本函数只做**字符串拼装**、不做任何四则运算 —— 前端一旦"顺手"求和，结论条就会与合计腿对不上。
 */
export function headline(board: SavingBoardLite | null, trend: SavingTrendLite | null): string {
  const purchase = board?.cohorts?.find((c) => c.cohort === 'purchase')
  const total = board?.total
  return [
    `切换后：${formatMetric(purchase?.batchCount, 0)} 批布仍有 ${formatMeters(purchase?.remainingMeters)} 没用完`
      + `（其中「几乎用完」${formatMetric(purchase?.le0_2Count, 0)} 批 / ${formatShare(purchase?.le0_2Share)}）`,
    `累计省料 ${formatMeters(total?.savedMeters)} / ${formatMetric(total?.savedAmount)} 元`,
    `累计采购入库 ${formatMeters(trend?.purchasedTotalMeters)}（不含存量导入）`,
  ].join('；') + '。'
}

/** 环比单位：米 / 元 / 占比 / 米每平方米 */
export type ComparisonKind = 'meters' | 'amount' | 'share' | 'perM2'

/**
 * 环比文案（#6430）。
 *
 * 🔴 **好坏词只来自服务端 `verdict`**（{@link verdictWord}）；`verdict` 为 `null` ⇒
 * 只给两期数值并**明说「不给好坏」**（占比正是这一档：它的方向会被排料省料反向污染）。
 * 期间同理来自服务端 —— 前端不自己算「上个月」，也不推断哪一期是「本期」。
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

/**
 * 异常优先：把「布压得最多的」排到最前（**纯排序，不改数值**）。
 *
 * 余量为 `null`（无数据）的排在最后 —— 无数据不该冒充「余量 0」挤在最前。
 */
export function sortByRemainingDesc<T extends { remainingMeters?: number | null }>(groups: T[]): T[] {
  return [...groups].sort((a, b) => {
    const av = toNumber(a.remainingMeters)
    const bv = toNumber(b.remainingMeters)
    if (av === null && bv === null) return 0
    if (av === null) return 1
    if (bv === null) return -1
    return bv - av
  })
}

/** 两张表的「时间」不是一回事（#6430）—— 新用户最容易看混的一条 */
export function periodAxisNote(): string {
  return '「布剩在哪」按**这批布哪个月进的货**（收货月）分月；「省在哪」按**这笔料哪个月被用掉**（消耗月）分月'
    + ' —— 两张表的「时间」不是一回事。'
}

/** 趋势分母的口径警示（服务端 DTO 已登记该残余风险，页面上必须说出来） */
export function trendCaveat(): string {
  return '产出面积 = 同期派工明细覆盖的窗户面积（宽 × 高）—— 纱帘 / 遮光布 / 工程单的单位面积用料天生不同，'
    + '**跨品类不可比**：只跟自己的历史比，不要拿不同品类互相比。'
}

/** 「口径与边界」折叠区：把散落的口径说明集中收纳，一次说完（#6430） */
export function footnotes(timezone?: string | null): string[] {
  return [
    '无数据 ≠ 0：占比 / 合计 / 比率算不出时显示「无数据」—— 0 会被读成「没有浪费」。',
    '省料金额是下界：只算记得住均价的行走，读不出的行会在表里点名（「另有 N 行未记批次均价」）。',
    '存量导入单列：上系统前的历史包袱，永不与「切换后」相加；「来源未知」同理不与采购相加。',
    periodAxisNote(),
    '两张表的「时间」与占比的分母（**批数**）都来自服务端，页面不做任何重算。',
    `时区：${timezone || '-'}（跨月边界上是两个数的原因就在这）。`,
  ]
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
  /** 第二行补充（计数 / 单位），与 `value` 同一份服务端值 */
  secondary?: string
  hint: string
  testId: string
}

/** 术语词典的一行 */
export interface SavedTerm {
  term: string
  meaning: string
}

/** 环比读面的最小形状（只声明用到的字段，避免与 `types` 循环依赖） */
export interface MetricDeltaLite {
  period?: string | null
  previousPeriod?: string | null
  current?: number | string | null
  previous?: number | string | null
  verdict?: string | null
}

/** 本助手消费的最小读面形状（只声明用到的字段，避免与 `types` 循环依赖） */
export interface SavingBoardLite {
  cohorts?: {
    cohort: string
    batchCount?: number
    le0_2Count?: number
    le0_2Share?: number | string | null
    remainingMeters?: number | string | null
    buckets?: { label?: string }[]
  }[]
  total?: {
    savedMeters?: number | string | null
    savedAmount?: number | string | null
    unknownCostLines?: number | null
  } | null
  trend?: { purchasedTotalMeters?: number | string | null } | null
  comparison?: {
    savedMeters?: MetricDeltaLite | null
    savedAmount?: MetricDeltaLite | null
    le0_2Share?: MetricDeltaLite | null
  } | null
}

/** 趋势读面的最小形状 */
export interface SavingTrendLite {
  purchasedTotalMeters?: number | string | null
  timezone?: string | null
  comparison?: {
    purchasedMeters?: MetricDeltaLite | null
    metersPerM2?: MetricDeltaLite | null
  } | null
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
