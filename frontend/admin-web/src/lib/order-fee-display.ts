/**
 * 费用明细的**展示拆分**（issue #4526 包 B · 设计文档 §4.3 / §9 判据 5）—— 唯一实现。
 *
 * 病根：服务端 `processingFeeDetail` 新增 `special_options[]`（按套收费）后，
 * 页面若仍把「加工」行显示成整个 `processingFee`（= 组合那半 + 特殊选项），再单列特殊选项行
 * ⇒ **双算**，费用明细逐行之和 ≠ 订单金额（判据 5 红）。
 *
 * 本模块只做一件事：把服务端那一份数拆成**三段**，三段相加 === `processingFee`：
 * ```
 * 加工行金额     = processingFeeDetail.amount        （组合那半：元/米 × 米数）
 * 特殊选项行     = special_options[] 逐项 单价/套 × 套数
 * 特殊选项合计   = special_options_total（键缺席 ⇒ 逐项求和兜底）
 * 拼色加价行     = mixed_color_surcharge（#4855：拼色款另加 2.4 元/米 × 面料米数）
 * ⇒ baseAmount + specialOptionsTotal + mixedColorSurcharge === processingFee（订单金额里的那个数）
 * ```
 *
 * 三条纪律：
 * 1. **同一真值**：页面不自己乘、不自己加价 —— 数全部来自服务端 detail（#4406 的 R10 同族）；
 * 2. **未定价显式可见**（判据 3 的展示面）：`priced:false` ⇒ `未定价（按 0 计）`，不许静默；
 *    `billing=per_meter`（拼1次 / 拼2次，用户 2026-09-21 裁定改按米计）⇒ 显式写「已并入拼色加价」，
 *    **不得**读成「未定价」；
 * 3. **新增键只加不改**：服务端未返回 `special_options` / `mixed_color_surcharge`（键缺席）⇒
 *    对应块不出现、加工行回落为整个 `processingFee` —— 显示口径逐字等于改造前，不引入第三个口径。
 *
 * ⚠️ 本文件**不渲染**（只产出行数据）：页面据它渲染，判据可脱离页面断言（#4434 同族拆法）。
 *
 * ── 订单级费用构成（issue #5843）──
 *
 * 用户 2026-10-01 报障：订单详情页 `商品合计 ¥245.14` 与 `订单金额 ¥368.74` 之间那笔
 * **¥123.60 加工费在页面上任何位置都不出现**（详情页原先自己算的「商品金额」不含加工费，
 * 而页脚用的是订单级总额）⇒ 商家看到两个数对不上、无从对账。
 *
 * ⇒ 本文件新增 {@link buildOrderFeeComposition}：把订单**已落库**的构成拼成
 * `商品合计 + 加工费 + 其它构成 === 订单金额`（差额非 0 ⇒ 显式解释行）。
 * **它只读服务端已算好的数**（`order_items.processing_fee` / `processing_info`，
 * 即「落库快照」）—— 与新增订单页的**试算预览**（`feePreviewApi`）是两回事，
 * 详情页**不得**按单价 × 米数重算。行级算式 / 未定价标记与 `OrderItemList` **同一份实现**
 * （{@link feeFormula} / {@link isUnpriced} / {@link readFeeDetail}，issue #5843 由该组件上移到本文件）。
 */

/** 一行特殊选项的展示数据 */
export interface SpecialOptionDisplayRow {
  /** React key（同一行内选项名唯一，服务端已按 Unicode 码点升序去重） */
  key: string
  /** 展示名（ERP 选项名 = join key，逐字不加工） */
  label: string
  /** 算式（`¥6.00/套 × 1 套`；未定价 ⇒ `未定价（按 0 计）`；改按米计 ⇒ `按 ¥2.40/米 计（已并入拼色加价）`） */
  expr: string
  /** 该行金额（元；未定价 / 改按米计 = 0） */
  amount: number
  /** 计价口径（服务端 `billing`；键缺席 ⇒ `per_set` —— 存量单当时全是按套收的） */
  billing: string
}

export interface FeeDetailDisplay {
  /** 「加工」行金额 = 组合那半（元） */
  baseAmount: number
  /** 特殊选项合计（元）= `special_options_total` */
  specialOptionsTotal: number
  /** 拼色加价（元）= `mixed_color_surcharge`；0 = 本行没有这一笔（不渲染该行） */
  mixedColorSurcharge: number
  /** 拼色加价算式（`34.10 米 × ¥2.40/米`；米数 / 单价缺失 ⇒ `按米计`） */
  mixedColorSurchargeExpr: string
  /** 逐项特殊选项行（空数组 ⇒ 不渲染该块） */
  specialOptionRows: SpecialOptionDisplayRow[]
}

/** 计价口径：按**元/套**计（服务端 `billing` 取值，与 `ProcessingFeeCalculator.BILLING_PER_SET` 同字面） */
export const BILLING_PER_SET = 'per_set'
/** 计价口径：按**元/米**计（拼1次 / 拼2次 —— 用户 2026-09-21 裁定，金额并入「拼色加价」那半） */
export const BILLING_PER_METER = 'per_meter'

/** 金额文案（两位小数 + 千分位；与页面其它金额行同口径）—— 组件与本模块共用同一份 */
export function formatMoney(amount: number): string {
  return `¥${amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** 有限数（容忍 JSON 里以字符串承载的数字）；其余 ⇒ 缺省值 */
function finiteOr(value: unknown, fallback: number): number {
  if (typeof value === 'number') return Number.isFinite(value) ? value : fallback
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return fallback
}

/** 可空有限数（`null` / 非数值 ⇒ `null`，与 0 区分） */
function nullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

/** 2 位小数的浮点归一（金额相加的噪声：`245.14 + 123.60 = 368.73999999999995`） */
function round2(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100
}

// ── 行级加工费展示（issue #4406 起住在 `OrderItemList.tsx`，issue #5843 上移到本文件）──────
// 为什么上移：详情页此前**没有任何加工费渲染点** ⇒ 补这一块时若在页面里再写一份
// 「读 detail / 编算式 / 判未定价」，就会出现第二套口径（同一个数两种显示）。
// 现在「明细行的加工费列」（`OrderItemList`）与「订单级费用构成」（{@link buildOrderFeeComposition}）
// 消费的是**同一份**实现。

/**
 * 加工费构成（后端 #4406 落库 → 展示层**只展示**，不重算）。
 *
 * 键名是 **snake_case**（设计文档 §4.5：算料/计价输出键与 `CALC_INFO_KEYS` 同口径）。
 * `fee_source` 三态：`matched` 命中组合 / `unpriced` 未定价 / `manual` 人工改价。
 */
export interface ProcessingFeeDetail {
  /** 参与计价的选配特征集合（组合键） */
  composition?: string
  /** 服务端给的**展示用**归一化加工项名（与 `composition` 同源；用于把未定价的组合**点名**） */
  items?: unknown
  unit_price?: number
  meters?: number
  meters_source?: string
  fee_source?: string
  amount?: number
  /** 特殊选项合计（元/套 那半，issue #4525；未定价组合下也照常计入，issue #4594） */
  special_options_total?: number
  /** 未定价时的可行动提示（后端给） */
  hint?: string
}

/** 从 `processingInfo` 取加工费构成；缺席 / 形态不对 ⇒ `null`（存量单：接线前生成，无该键） */
export function readFeeDetail(info: unknown): ProcessingFeeDetail | null {
  if (info === null || typeof info !== 'object' || Array.isArray(info)) return null
  const raw = (info as Record<string, unknown>).processingFeeDetail
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return null
  return raw as ProcessingFeeDetail
}

/**
 * 加工费算式（用户口径：「**窗帘米数 × 组合加工费 = 具体费用**」）。
 *
 * **缺单价或米数 ⇒ 不编算式**（返回 `null`）：宁可只显示金额，
 * 也不给商家一个对不上的算式（那比不显示更糟 —— 商家会照着它去核账）。
 */
export function feeFormula(detail: ProcessingFeeDetail | null): string | null {
  if (!detail) return null
  const meters = nullableNumber(detail.meters)
  const unit = nullableNumber(detail.unit_price)
  if (meters === null || unit === null) return null
  const amount = nullableNumber(detail.amount)
  const left = `${meters} 米 × ${formatMoney(unit)}/米`
  return amount === null ? left : `${left} = ${formatMoney(amount)}`
}

/**
 * 未定价（`fee_source=unpriced`）。
 *
 * 为什么单独判它：未定价时**组合那半**按 0 计（`amount` = 0），而 `¥0.00` 与
 * 「这一行本来就不收加工费」**长得一模一样** ⇒ 必须显式标「未定价」，否则就是静默改钱的外观。
 *
 * ⚠️ 它只表示**组合那半**未定价（用户裁定 2026-09-19 / issue #4594）：已定价的特殊选项
 * **照常计入行金额** ⇒ 本判据**不蕴含**「行金额 = 0」，行金额一律看 `item.processingFee`
 * （后端 `lineAmount()` = 组合那半 + Σ 选项价）。
 */
export function isUnpriced(detail: ProcessingFeeDetail | null): boolean {
  return detail?.fee_source === 'unpriced'
}

/** 未定价行**没有可匹配的组合**时的展示名（issue #4590 的边界）：服务端 `composition` 为空 = 缺选配信息 */
const UNPRICED_NO_COMPOSITION = '没有可匹配的组合（缺选配信息）'

/**
 * 未定价行的**组合展示名**（issue #4590 口径，issue #5843 上移到本文件）：
 * `items.join(' + ')` → 归一化组合键 → `没有可匹配的组合（缺选配信息）`。
 *
 * ⚠️ 新增订单页（`orders/new/page.tsx`）里还留着一份**同名局部实现**（那份文件被并发包独占，
 * 本单不动它）—— 两处口径必须逐字一致，收敛到本函数属后续包。
 */
export function unpricedCombinationLabel(detail: { composition?: unknown; items?: unknown } | undefined): string {
  const items = Array.isArray(detail?.items)
    ? detail.items.filter((v): v is string => typeof v === 'string' && v.trim() !== '')
    : []
  if (items.length > 0) return items.join(' + ')
  // `items` 缺席（旧服务端）⇒ 回落到归一化组合键（与定价页的兜底同口径），再空才算「缺选配信息」
  const composition = typeof detail?.composition === 'string' ? detail.composition.trim() : ''
  return composition !== '' ? composition : UNPRICED_NO_COMPOSITION
}

/** 服务端 `special_options[]` 的一项（键名 snake_case，契约 §4.3） */
interface RawSpecialOption {
  name: string
  unit_price: number | null
  sets: number
  amount: number
  priced: boolean
  billing: string
}

/** 计价口径（`billing` 缺席 ⇒ `per_set` —— 存量单当时全是按套收的，不发明第三种口径） */
function billingOf(value: unknown): string {
  return typeof value === 'string' && value !== '' ? value : BILLING_PER_SET
}

/** 解析 `special_options[]`（脏数据不猜：无名 / 非对象一律丢弃） */
function parseSpecialOptions(value: unknown): RawSpecialOption[] {
  if (!Array.isArray(value)) return []
  const rows: RawSpecialOption[] = []
  for (const raw of value) {
    if (raw === null || typeof raw !== 'object') continue
    const entry = raw as Record<string, unknown>
    const name = typeof entry.name === 'string' ? entry.name.trim() : ''
    if (name === '') continue
    const sets = finiteOr(entry.sets, 1)
    const unitPrice = nullableNumber(entry.unit_price)
    // `priced` 缺席 ⇒ 以「有没有单价」为准（fail-closed：没价就是未定价）
    const priced = typeof entry.priced === 'boolean' ? entry.priced : unitPrice !== null
    rows.push({
      name,
      unit_price: unitPrice,
      sets,
      amount: finiteOr(entry.amount, unitPrice === null ? 0 : unitPrice * sets),
      priced,
      // `billing` 缺席 ⇒ `per_set`（存量单：那时确实全是按套收的 —— 不发明第三种口径）
      billing: billingOf(entry.billing),
    })
  }
  return rows
}

/**
 * 把一行的取价结果拆成「加工 + 特殊选项」两半（判据 5 的落点）。
 *
 * @param row 服务端取价行（`processingFee` = 该行加工费；`processingFeeDetail` = 可审计构成）
 */
export function buildFeeDetailDisplay(row: {
  processingFee?: number | null
  processingFeeDetail?: Record<string, unknown> | null
}): FeeDetailDisplay {
  const processingFee = finiteOr(row?.processingFee, 0)
  const detail = row?.processingFeeDetail
  const hasSpecialOptions = detail !== null && detail !== undefined && 'special_options' in detail

  // 拼色加价（#4855，用户 2026-09-21 裁定「两处都按 2.4 元/米」）：行金额的**第三个分量**。
  // 键缺席（存量单 / 旧服务端）⇒ 0 ⇒ 下面的拆分逐字等于改造前（不引入第三个口径）。
  const hasMixedColor = detail !== null && detail !== undefined && 'mixed_color_surcharge' in detail
  const mixedColorSurcharge = hasMixedColor ? finiteOr(detail?.mixed_color_surcharge, 0) : 0
  const mixedColorPerMeter = nullableNumber(detail?.mixed_color_surcharge_per_meter)
  const mixedColorMeters = nullableNumber(detail?.mixed_color_meters)
  const mixedColorSurchargeExpr =
    mixedColorPerMeter !== null && mixedColorMeters !== null
      ? `${mixedColorMeters} 米 × ${formatMoney(mixedColorPerMeter)}/米`
      : '按米计'

  const parsed = parseSpecialOptions(detail?.special_options)
  const specialOptionRows: SpecialOptionDisplayRow[] = parsed.map((option) => ({
    key: option.name,
    label: option.name,
    expr:
      option.billing === BILLING_PER_METER
        ? // 改按元/米计（拼1次 / 拼2次）：金额为 0，钱在「拼色加价」那行 —— 不在这里重复显示一个价
          mixedColorPerMeter !== null
          ? `按 ${formatMoney(mixedColorPerMeter)}/米 计（已并入拼色加价）`
          : '按米计（已并入拼色加价）'
        : option.priced && option.unit_price !== null
          ? `${formatMoney(option.unit_price)}/套 × ${option.sets} 套`
          : '未定价（按 0 计）',
    amount: option.amount,
    billing: option.billing,
  }))

  // 合计以服务端 `special_options_total` 为准（逐项求和只作兜底：键缺席时才算）
  const summed = specialOptionRows.reduce((sum, r) => sum + r.amount, 0)
  const specialOptionsTotal =
    detail && 'special_options_total' in detail
      ? finiteOr(detail.special_options_total, summed)
      : summed

  // 组合那半：优先取 detail.amount；缺失 ⇒ 用「行金额 − 特殊选项合计 − 拼色加价」反推（仍不双算）。
  // 服务端未返回 `special_options`（键缺席）⇒ 两半不存在，加工行回落为整个 processingFee（减加价那半）。
  const baseAmount = hasSpecialOptions
    ? finiteOr(detail?.amount, processingFee - specialOptionsTotal - mixedColorSurcharge)
    : processingFee - mixedColorSurcharge

  return { baseAmount, specialOptionsTotal, mixedColorSurcharge, mixedColorSurchargeExpr, specialOptionRows }
}

// ── 订单级费用构成（issue #5843）────────────────────────────────────────────

/** 「费用构成」区的一行（订单详情页）—— 数全部来自落库快照，展示层不重算 */
export interface OrderFeeLine {
  /** React key（订单行 id；存量行可能缺 id ⇒ 用序号兜底） */
  key: string
  /** 行名（商品名；缺 ⇒ 「第 N 行」） */
  label: string
  /** 该行加工费（元）= 服务端 `order_items.processing_fee` **原样** */
  amount: number
  /** 算式（`10.3 米 × ¥12.00/米 = ¥123.60`）；缺单价 / 米数 ⇒ `null`（不编算式） */
  expr: string | null
  /** 未定价（`fee_source=unpriced`）⇒ 该行按 0 计，**必须显式标出**（不许渲染成 `¥0.00`） */
  unpriced: boolean
  /** 未定价时的组合展示名（口径 = {@link unpricedCombinationLabel}） */
  unpricedLabel: string | null
  /** 人工改价（`fee_source=manual`）—— 与明细行同一标记 */
  manual: boolean
}

/** 订单级费用构成的**判定结果**（页面据它渲染；判据可脱离页面断言） */
export interface OrderFeeComposition {
  /** 商品合计（元）—— 调用方按**页面同一份**行金额口径算好传入（不在这里重算第二份） */
  goodsTotal: number
  /** 加工费合计（元）= Σ 落库 `items[].processingFee`（**原样相加，不按单价 × 米数重算**） */
  processingFeeTotal: number
  /** 差额（元）= 订单金额 −（商品合计 + 加工费合计）；非 0 ⇒ 渲染「其它构成」解释行 */
  remainder: number
  /** 订单金额（服务端 `order.totalAmount`；未取到 ⇒ `null` ⇒ 不编差额） */
  orderTotal: number | null
  /** 逐行加工费（只列**有这笔钱**的行与**未定价**行 —— 布料单一行都不出现） */
  lines: OrderFeeLine[]
  /** 未定价行数（按 0 计入订单金额，必须显式告知） */
  unpricedCount: number
  /** 未定价行的组合展示名（去重、保持出现顺序） */
  unpricedLabels: string[]
  /** 是否渲染「加工费」行：有任何一笔**实收**加工费 */
  showProcessingFee: boolean
  /** 是否渲染「其它构成」解释行：差额非 0 */
  showRemainder: boolean
  /** 整块是否可见：**布料单（无加工费 / 无未定价 / 无差额）⇒ 不可见**（没有加工是正常，不是缺失） */
  visible: boolean
}

/** 差额判 0 的阈值 = 半分钱（小于它就当等式闭合，不渲染解释行） */
export const REMAINDER_EPSILON = 0.005

/**
 * 订单级费用构成（issue #5843）：把**落库快照**拼成页面读得出来的等式
 * `商品合计 + 加工费 + 其它构成 === 订单金额`。
 *
 * 四条硬口径（用户 2026-10-01 报障后的展示裁定）：
 * 1. **只展示服务端已算好的数、不重算** —— 加工费合计 = Σ `items[].processingFee`（落库值），
 *    行级算式只是**复述** `processingFeeDetail`（米数 × 单价/米 = 金额），不参与求和；
 * 2. **未定价不渲染 `¥0.00`**：那半按 0 计，于是显式标「未定价」并**点名组合**；
 * 3. **布料单不出现空行 / `¥0.00` 行**：没有加工是正常，不是缺失（`visible=false` ⇒ 整块不渲染）；
 * 4. **差额有显式解释行**：`|订单金额 −（商品 + 加工费）| ≥ 1 分` ⇒ 「其它构成」把它报出来，
 *    而不是让商家自己猜（差额为 0 时**不渲染那一行**）。
 *
 * @param rows 订单行（读 `id` / `productName` / `processingFee` / `processingInfo`）
 * @param options `goodsTotal` = 页面「商品合计」列之和（调用方按同一份行金额口径算好）；
 *                `orderTotal` = 订单级总额（服务端 `totalAmount`；未取到传 `null`）
 */
export function buildOrderFeeComposition(
  rows: Array<{
    id?: string
    productName?: string
    processingFee?: number | null
    processingInfo?: unknown
  }>,
  options: { goodsTotal?: number | null; orderTotal?: number | null }
): OrderFeeComposition {
  const list = Array.isArray(rows) ? rows : []
  const goodsTotal = round2(finiteOr(options?.goodsTotal, 0))
  const orderTotal = nullableNumber(options?.orderTotal)

  // 加工费合计 = Σ 落库 `items[].processingFee`（**原样相加**：不按 unit_price × meters 重算 ——
  // 详情页是**落库快照**面，试算口径只属于新增订单页）
  const processingFeeTotal = round2(
    list.reduce((sum, row) => sum + finiteOr(row?.processingFee, 0), 0)
  )

  const lines: OrderFeeLine[] = []
  const unpricedLabels: string[] = []
  list.forEach((row, index) => {
    const amount = finiteOr(row?.processingFee, 0)
    const detail = readFeeDetail(row?.processingInfo)
    const unpriced = isUnpriced(detail)
    // 布料单：金额 0 且不是「未定价」⇒ 这一行不进费用构成（不渲染空行 / ¥0.00 行）
    if (amount === 0 && !unpriced) return
    const label = typeof row?.productName === 'string' && row.productName !== '' ? row.productName : `第 ${index + 1} 行`
    const unpricedLabel = unpriced ? unpricedCombinationLabel(detail ?? undefined) : null
    if (unpricedLabel !== null && !unpricedLabels.includes(unpricedLabel)) {
      unpricedLabels.push(unpricedLabel)
    }
    lines.push({
      key: row?.id ? String(row.id) : `row-${index}`,
      label,
      amount,
      expr: feeFormula(detail),
      unpriced,
      unpricedLabel,
      manual: detail?.fee_source === 'manual',
    })
  })

  const unpricedCount = lines.filter((line) => line.unpriced).length
  const showProcessingFee = processingFeeTotal > 0
  const remainder = orderTotal === null ? 0 : round2(orderTotal - (goodsTotal + processingFeeTotal))
  const showRemainder = orderTotal !== null && Math.abs(remainder) >= REMAINDER_EPSILON

  return {
    goodsTotal,
    processingFeeTotal,
    remainder,
    orderTotal,
    lines,
    unpricedCount,
    unpricedLabels,
    showProcessingFee,
    showRemainder,
    visible: showProcessingFee || unpricedCount > 0 || showRemainder,
  }
}
