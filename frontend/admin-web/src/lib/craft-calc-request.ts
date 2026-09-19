/**
 * 下单页「算料试算」的**纯函数半边**（issue #4434 · 前置 #4421）。
 *
 * 拆出来的理由：判据要能**脱离页面**断言「参数不全 ⇒ 不发请求」「非韩褶 ⇒ 不发请求」
 * 这两条 fail-closed 行为 —— 埋在 `useEffect` 里就只能靠集成测试碰运气。
 *
 * ⚠️ **本文件不含任何算料公式**：用料米数由算料引擎（ai-agent）算，前端只负责
 * 「凑齐入参」与「渲染后端给的公式串」。在前端复制 0.25/2.0 这类常量 = **第二份算料逻辑**
 * （同族纪律见 `ProductionOperationQtyClient` 的「Java 侧不复制第二份算料逻辑」）。
 */

import type { CraftCalcParams } from './api'
import { CURTAIN_TYPE_SHEER, type CraftSpecInput } from './order-craft-fields'

/** 用料来源（真值源 §8：折数/用料**必须带来源**，防止多渠道不一致） */
export const METERS_SOURCE_FORMULA = '公式计算'
export const METERS_SOURCE_MANUAL = '人工指定'

/**
 * 下单页固定用**标准档**（用户 2026-09-19 裁定：用料米数按折数法（标准档））。
 * 档位是**算料口径**，不是本页可选项 ⇒ 常量放在这里、由请求带出（不在 Java/TS 侧补默认值 ——
 * 缺省值由 ai-agent 端点给，两处补默认值就是两份口径）。
 */
export const CRAFT_CALC_TIER = 'standard'

/** 折数法只在韩褶（`s_hook`）生效；其它悬挂方式后端会 400 ⇒ 前端**不该发**这种请求 */
export const CRAFT_CALC_MOUNTING = 's_hook'

/**
 * 用料**计算方法**（issue #4527，用户 2026-09-19 裁定：「根据用户要求选择不同的计算公式，**默认用韩折的**」）：
 * - `pleat` = **韩折公式**（折数法）：`总用料 = 每片用料 × 开数`，每片用料 = 每折吃布 × 每片折数 + 每片余量；
 * - `fullness` = **褶倍数公式**（倍数法）：`总用料 = 每片宽 × 褶倍 × 开数`（= 成品宽 × 褶倍，与开数无关）。
 *
 * ⚠️ 前端**只传公式名**，不实现任何公式（实现唯一落在算料引擎 `curtain_calc.py`；
 * 前端复制常量/算式 = **第二份算料逻辑**）。
 */
export const CRAFT_CALC_FORMULA_PLEAT = 'pleat'
export const CRAFT_CALC_FORMULA_FULLNESS = 'fullness'
export const CRAFT_CALC_FORMULAS = [
  CRAFT_CALC_FORMULA_PLEAT,
  CRAFT_CALC_FORMULA_FULLNESS,
] as const

/**
 * 工艺 → 用料公式 / 悬挂方式（用户 2026-09-19 追加裁定逐字：
 * 「**韩折用韩折公式算布料，打孔按倍数法算布料，默认选择 2 倍**」）。
 *
 * ⚠️ **这是「有守卫的副本」**：权威表 = 算料引擎 `curtain_calc.CRAFT_FORMULA` / `CRAFT_MOUNTING`；
 * 本表由 `tests/unit/lib/craft-calc-formula-sync.test.ts` **逐值读 Python 源文件比对**，漂移即红
 * （同族先例 = `craft-calc-defaults.test.ts` 对 `PLEAT_FABRIC_PER_FOLD` 的守卫）。
 * 为什么前端还要有一份：试算是**纯函数半边**（`craftCalcParamsOf`）—— 不查表就凑不出入参；
 * 但**推导逻辑只有一份**（Python），前端只做「名字 → 名字」的搬运，不做任何数值计算。
 *
 * 未登记工艺（四爪钩/穿杆/平幔）⇒ **不发请求**（与既有 fail-closed 一致：这些工艺无自动算料口径）。
 */
export const CRAFT_CALC_FORMULA_BY_CRAFT: Record<string, string> = {
  韩褶: CRAFT_CALC_FORMULA_PLEAT,
  打孔: CRAFT_CALC_FORMULA_FULLNESS,
}

/** 工艺 → 悬挂方式（`mounting` 是**英文枚举**，与 `craft` 中文枚举是两层，故各自成表） */
export const CRAFT_CALC_MOUNTING_BY_CRAFT: Record<string, string> = {
  韩褶: 's_hook',
  打孔: 'eyelet',
}

/** 走自动算料的工艺（空 = 未指定 ⇒ 按韩褶默认档试算）；其余工艺无自动算料口径 */
const CALC_CRAFTS = new Set(['韩褶', '打孔', ''])

export interface CalcLineInput {
  /** 成品宽（米）—— 必填 */
  width: number | null
  /** 成品高（米）—— 必填 */
  height: number | null
  craft: CraftSpecInput
  /**
   * 该行的**部位**（issue #4521）：`纱帘` ⇒ **不算料** —— 用户裁定「纱帘不需要算用料米数，
   * 买多少就是多少」。主帘（布帘）不写该键。
   */
  curtainType?: string
  /**
   * 用料计算方法（issue #4527）：缺省 ⇒ `'pleat'`（韩折公式）。
   * 页面上的**公式选择器**由后续小尾包接线（本包只把入参打通）。
   */
  formula?: string
}

/**
 * 把一行明细凑成试算入参；**凑不齐 ⇒ `null`（调用方不得发请求）**。
 *
 * 四条 fail-closed（都用 `null` 表达，**绝不**用默认窗宽/默认开数猜一个米数）：
 * 1. 缺宽或高（宽高是必填的「不可推导的原始输入」，§5.9.3）；
 * 2. **纱帘**（issue #4521）—— 用料由商家给定，发请求会把商家填的米数静默改回公式值；
 * 3. 工艺明确是**无自动算料口径**的（四爪钩/穿杆/平幔）—— 试算没有意义；
 * 4. 宽/高非正数。
 *
 * 公式与悬挂方式**由工艺推导**（用户 2026-09-19 追加裁定）：韩褶 ⇒ 折数法 + `s_hook`；
 * 打孔 ⇒ 倍数法 + `eyelet`（默认 2 倍）；未指定工艺 ⇒ 韩褶默认档。
 * 推导表是**有守卫的副本**（权威表在 `curtain_calc.CRAFT_FORMULA`，见文件头说明）。
 */
export function craftCalcParamsOf(line: CalcLineInput): CraftCalcParams | null {
  const width = Number(line.width)
  const height = Number(line.height)
  if (!Number.isFinite(width) || width <= 0) return null
  if (!Number.isFinite(height) || height <= 0) return null

  // 纱帘不算料（issue #4521）：买多少就是多少
  if (line.curtainType === CURTAIN_TYPE_SHEER) return null

  const craft = line.craft.craft
  if (craft !== undefined && !CALC_CRAFTS.has(craft)) return null

  const params: CraftCalcParams = {
    width,
    height,
    open_count: line.craft.openCount ?? 1,
    // 工艺 → 悬挂方式（打孔不是 s_hook：传错会被后端按韩褶口径算）
    mounting: (craft ? CRAFT_CALC_MOUNTING_BY_CRAFT[craft] : undefined) ?? CRAFT_CALC_MOUNTING,
    craft_tier: CRAFT_CALC_TIER,
    // 工艺 → 用料公式；未指定工艺 ⇒ 默认韩折公式（用户裁定「默认用韩折的」）
    formula:
      line.formula ??
      (craft ? CRAFT_CALC_FORMULA_BY_CRAFT[craft] : undefined) ??
      CRAFT_CALC_FORMULA_PLEAT,
  }
  // 工艺**原样带出**（后端据此再推导一次公式 —— 单一口径在算料引擎；此处不替它决定）
  if (craft) params.craft = craft
  if (line.craft.style) params.style = line.craft.style
  if (line.craft.specialOptions && line.craft.specialOptions.length > 0) {
    params.special_options = line.craft.specialOptions
  }
  return params
}

/**
 * 试算**触发签名**：签名不变就不重发请求。
 *
 * 为什么需要它：试算会**写回** `quantity`，而 `quantity` 不是入参 ⇒ 若直接用行数组当依赖，
 * 写回会再次触发 effect ⇒ 请求风暴。签名只含**入参**，把写回排除在触发条件之外。
 */
export function craftCalcSignature(params: CraftCalcParams | null): string {
  if (params === null) return ''
  return [
    params.width,
    params.height,
    params.open_count,
    params.mounting,
    params.craft_tier,
    params.formula ?? '',
    params.craft ?? '',
    params.style ?? '',
    (params.special_options ?? []).join(','),
  ].join('|')
}

/**
 * 试算失败 → 行内可读提示。
 *
 * **不返回任何「估算值」**：失败就是失败，数量保持原样（商家手填或上一次结果），
 * 由商家决定 —— 静默退回一个估算米数 = 算错钱且无人知道（#4308「静默回落」同族）。
 */
export function craftCalcErrorText(error: unknown): string {
  const anyErr = error as {
    response?: { data?: { message?: string; error?: { message?: string } } }
    message?: string
  }
  const detail =
    anyErr?.response?.data?.error?.message ||
    anyErr?.response?.data?.message ||
    anyErr?.message
  return detail ? `算料试算失败：${detail}` : '算料试算失败，请核对宽高与工艺后重试'
}

/**
 * 该行**不可能**自动算料吗（issue #4488，用户裁定「这些**不需要自动算**，
 * 这些**加工项直接体现费用**的，不用算米数」）。
 *
 * 与「参数没填齐」**必须区分**：前者是**口径**（无自动算料口径的工艺 ⇒ 永远算不出），
 * 后者只是还没填。页面据此给「该工艺无自动算料，请手填米数」的提示 ——
 * 否则数量会**静默停在默认 1 米**（实测截图为 `商品 1 米 × ¥23.80/米 = ¥23.80`，金额错）。
 */
export function isAutoCalcUnavailable(line: CalcLineInput): boolean {
  // 纱帘永远不算料（issue #4521）：不是「参数没填齐」，而是**口径**（买多少就是多少）
  if (line.curtainType === CURTAIN_TYPE_SHEER) return true
  const craft = line.craft.craft
  return craft !== undefined && !CALC_CRAFTS.has(craft)
}
