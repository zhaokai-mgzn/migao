/**
 * 「用料公式」的**参数说明**（2026-09-29 用户裁定逐字：
 * 「这里的公式展示很 ok，但是用户看不懂里面的数字代表什么，应该要把**参数名**带上，
 * 如果用户要修改参数也知道去改什么」）。
 *
 * 两条硬约束：
 * ① **绝不解析公式串** —— 公式串由算料引擎产出（`curtain_calc._formula_text`）。
 *    按串里的数字反推名字 = 第二个真值源：串一改，说明就说谎，而且**没有任何东西会变红**。
 *    本函数按**引擎同序**的参数表拼说明，数值全部取自**同一次算料响应 / 算料配置**。
 * ② **缺值不编** —— 取不到的数（试算还没回来 / 算料配置未加载）：该条**整条不出现**
 *    （宁缺勿滥），而不是补一个默认值 —— 编出来的数就是第二份算料逻辑。
 *
 * 公式串的两种形态与参数顺序（真值源 = `backend/ai-agent-service/app/tools/curtain_calc.py::_formula_text`）：
 * - 韩褶公式（褶数法）：`韩褶公式：(窗宽+余量)×褶倍 → N折 → 每折吃布×N折+余量 = 米数米`；
 * - 褶倍数公式（倍数法）：`褶倍数公式：(窗宽÷开数)×褶倍 → 每片 每片宽×褶倍=每片米 ×开数片 = 米数米`
 *   —— 后一条里的「每片宽 / 每片米 / 总数」是**引擎算出来的中间量**，前端**不复算**
 *   （复算 = 第二份算料逻辑）⇒ 只说明**输入侧**的那三个数（窗宽 / 开数 / 褶倍）。
 */
import type { CraftCalcConfig } from '@/types'

/** 公式串里的一个数 + 它的中文名（`value` 已格式化成与公式串同形的文本） */
export interface MetersFormulaParam {
  /** 公式串里出现的数（如 `6` / `0.3`） */
  value: string
  /** 它的中文名 + 来源（如 `每片余量（米 · 算料配置）`） */
  name: string
}

export interface MetersFormulaLegendInput {
  /** 生效用料公式（`pleat` / `fullness`）；空 / 不认识的公式 ⇒ `null`（不出说明） */
  formula?: string | null
  /** **净窗宽**（米）—— 推导链的原始输入（`order_items.width`） */
  width?: number | null
  /** 开数（打开方式）；缺省 ⇒ 不出现「开数」那条 */
  openCount?: number | null
  /** 算料响应 `pleat_count`（总褶数） */
  pleatCount?: number | null
  /** 算料响应 `per_fold`（每折吃布，米） */
  perFold?: number | null
  /** 算料响应 `fullness`（理论褶倍，随档位） */
  fullness?: number | null
  /** 算料配置（取不到 ⇒ 「每片余量」那条不出现 —— 不编数） */
  config?: Pick<CraftCalcConfig, 'margin_single' | 'margin_multi'> | null
}

export interface MetersFormulaLegend {
  /** 逐条「数 = 名字」—— 与公式串里的**出现顺序一致**（先出现的先说） */
  params: MetersFormulaParam[]
  /** 「要改这个参数，去哪儿改」—— 按参数名给出页面上的入口（不含公式串里的派生量） */
  where: string
}

const FORMULA_PLEAT = 'pleat'

/** 数字 → 与公式串同形的文本（`6` / `0.25`）；**缺值 / 非有限值 ⇒ `null`**（该条不出现） */
function num(value: number | null | undefined): string | null {
  // ⚠️ 必须先挡 `null` / `undefined`：`Number(null) === 0`（有限！）⇒ 漏这一挡就会把
  // 「算料配置未加载 ⇒ 余量取不到」渲染成 **`0=每片余量`**（一个凭空造出来的参数值）。
  // 红证：tests/unit/lib/meters-formula-legend.test.ts「判据 ②：缺值不编」。
  if (value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? String(n) : null
}

/**
 * 「每片余量」的取值 —— 与引擎**同一口径**（`curtain_calc.py` 的 `_margin_for`：
 * `open_count <= 1` ⇒ `margin_single`，否则 `margin_multi`）。
 *
 * ⚠️ 这是「取配置里的数」不是「算料」：本函数不产生任何数值，只按开数**选一个键**。
 * 配置取不到 ⇒ `null`（宁可不说明，也不说一个错的余量）。
 */
export function marginForOpenCount(
  openCount: number | null | undefined,
  config: Pick<CraftCalcConfig, 'margin_single' | 'margin_multi'> | null | undefined
): number | null {
  if (!config) return null
  const key = Number(openCount ?? 1) <= 1 ? 'margin_single' : 'margin_multi'
  const value = Number(config[key])
  return Number.isFinite(value) ? value : null
}

export function metersFormulaLegend(
  input: MetersFormulaLegendInput
): MetersFormulaLegend | null {
  const formula = typeof input.formula === 'string' ? input.formula.trim() : ''
  if (formula === '') return null

  const params: MetersFormulaParam[] = []
  const push = (value: number | null | undefined, name: string) => {
    const text = num(value)
    if (text !== null) params.push({ value: text, name })
  }
  const where =
    '改参数：净窗宽 / 净窗高 → 上方「净尺寸」；开数（打开方式）与用料公式 →「改工艺参数」；' +
    '每片余量 / 每折吃布 / 褶倍 →「工艺配置 → 算料配置」'

  if (formula === FORMULA_PLEAT) {
    // 顺序 = 公式串里出现的先后：窗宽 → 余量 → 褶倍 → 褶数 → 每折吃布
    push(input.width, '净窗宽（米）')
    push(marginForOpenCount(input.openCount, input.config), '每片余量（米 · 算料配置）')
    push(input.fullness, '褶倍（算料配置）')
    push(input.pleatCount, '自动算出的褶数')
    push(input.perFold, '每折吃布（米 · 算料配置）')
    return params.length === 0 ? null : { params, where }
  }

  // 褶倍数公式：`(窗宽÷开数)×褶倍 → 每片 …` —— 只说明**输入侧**三个数（派生量由引擎算，前端不复算）
  if (formula === 'fullness') {
    push(input.width, '净窗宽（米）')
    push(input.openCount, '开数（打开方式）')
    push(input.fullness, '褶倍（算料配置）')
    return params.length === 0 ? null : { params, where }
  }

  // 表外公式（引擎新增而本表未跟进）⇒ 不出说明：宁可没有，也不说错
  return null
}
