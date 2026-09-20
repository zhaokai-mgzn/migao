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

/** 金额文案（两位小数 + 千分位；与页面其它金额行同口径） */
function money(amount: number): string {
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

/** 服务端 `special_options[]` 的一项（键名 snake_case，契约 §4.3） */
interface RawSpecialOption {
  name: string
  unit_price: number | null
  sets: number
  amount: number
  priced: boolean
  billing?: string
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
      billing:
        typeof entry.billing === 'string' && entry.billing !== ''
          ? entry.billing
          : BILLING_PER_SET,
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
      ? `${mixedColorMeters} 米 × ${money(mixedColorPerMeter)}/米`
      : '按米计'

  const parsed = parseSpecialOptions(detail?.special_options)
  const specialOptionRows: SpecialOptionDisplayRow[] = parsed.map((option) => ({
    key: option.name,
    label: option.name,
    expr:
      option.billing === BILLING_PER_METER
        ? // 改按元/米计（拼1次 / 拼2次）：金额为 0，钱在「拼色加价」那行 —— 不在这里重复显示一个价
          mixedColorPerMeter !== null
          ? `按 ${money(mixedColorPerMeter)}/米 计（已并入拼色加价）`
          : '按米计（已并入拼色加价）'
        : option.priced && option.unit_price !== null
          ? `${money(option.unit_price)}/套 × ${option.sets} 套`
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
