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
import type { CraftCalcConfig } from '@/types'
import type { CraftSpecInput } from './order-craft-fields'

/** 用料来源（真值源 §8：折数/用料**必须带来源**，防止多渠道不一致） */
export const METERS_SOURCE_FORMULA = '公式计算'
export const METERS_SOURCE_MANUAL = '人工指定'

/**
 * **未选档位时的缺省档**（issue #4874 改判）。
 *
 * ⚠️ 它**不再是"本页固定用标准档"**（旧口径：`craft_tier` 被钉死为 `standard`）——
 * 现在档位是**商家可选项**（用料公式 = 褶倍数公式时展示「经济档 / 标准档」chips），
 * 本常量只表达「商家没选时按哪个档」。
 *
 * ⚠️ 缺省必须落在**算料配置里真实存在的档位键**上：租户把 `tiers` 改成别的键集时，
 * 钉死 `standard` 会让请求带一个不存在的档 ⇒ 引擎只能报错或静默回落。
 * 取值一律走 {@link defaultCraftCalcTier}（它读**配置的** `tiers` 键集）。
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
 * 公式的**可读文案**（issue #4874；**唯一一份**）—— 下单页「用料公式」chips 与
 * 工艺配置页的「兜底用料公式」下拉**共用它**（原先只有工艺配置页里的一份局部常量，
 * 下单页再接一份 = 同一真值两处推导，改一处忘一处）。
 *
 * ⚠️ 键 = {@link CRAFT_CALC_FORMULAS}（值域与算料引擎 `curtain_calc.FORMULA_LABELS` 同源，
 * 由 `craft-calc-formula-sync.test.ts` 逐值守）；本映射**只做展示**，不引入新取值。
 */
export const CRAFT_CALC_FORMULA_LABELS: Record<string, string> = {
  [CRAFT_CALC_FORMULA_PLEAT]: '韩折公式（折数法）',
  [CRAFT_CALC_FORMULA_FULLNESS]: '褶倍数公式（倍数法）',
}


/**
 * **生效用料公式**（issue #4874 的**唯一口径**）—— 优先级：
 * ① 商家**显式选**的（页面 chips）⇒ ② **工艺推导**（`CRAFT_CALC_FORMULA_BY_CRAFT`，
 * 权威表在算料引擎 `resolve_craft_rule` 的**有守卫副本**）⇒ ③ **算料配置的兜底**
 * `default_formula` ⇒ ④ 常量 `pleat`。
 *
 * 为什么必须先工艺推导再配置兜底：算料引擎的优先级逐字是「`formula` 入参**保留为显式覆盖**
 * （显式 > 本表 > `default_formula` 兜底）」⇒ 前端若把「配置兜底」当默认值**显式**发出去，
 * 就等于把「打孔 ⇒ 倍数法」（#4527 用户裁定）顶掉（页面按韩折口径发请求、后端按打孔口径算）。
 * 页面与 chips 展示**共用本函数**（同一份解析 ⇒ 页面显示 = 请求 = 落库）。
 */
export function effectiveCraftCalcFormula(
  input: { formula?: string; craft?: string },
  config: Pick<CraftCalcConfig, 'default_formula'> | null | undefined
): string {
  const explicit = typeof input.formula === 'string' ? input.formula.trim() : ''
  if (explicit !== '') return explicit
  const byCraft = input.craft ? CRAFT_CALC_FORMULA_BY_CRAFT[input.craft] : undefined
  if (byCraft) return byCraft
  return defaultCraftCalcFormula(config)
}

/**
 * 算料配置未加载（或没配）时的**兜底公式** —— 用户裁定「默认用韩折的」（#4527），
 * 与引擎 `DEFAULT_CRAFT_CALC_CONFIG.default_formula` 同值（`pleat`）。
 *
 * 为什么取**配置的** `default_formula` 优先：那是租户在「工艺配置 → 算料配置」里定的兜底口径
 * （读面取值，前端不写第二份真值）；配置取不到才落回本常量，并且页面**必须显式提示**
 * 「配置未加载」（静默按缺省走 = 商家以为按自己配的口径算）。
 */
export function defaultCraftCalcFormula(
  config: Pick<CraftCalcConfig, 'default_formula'> | null | undefined
): string {
  const value = typeof config?.default_formula === 'string' ? config.default_formula.trim() : ''
  return value !== '' ? value : CRAFT_CALC_FORMULA_PLEAT
}

/**
 * **缺省档位键**（issue #4874）：`standard` 在配置的 `tiers` 里存在 ⇒ 用它；
 * 否则取配置里的**第一个档位键**；配置整个取不到 ⇒ 落回 {@link CRAFT_CALC_TIER}。
 *
 * ⚠️ 这就是「缺省要落在算料配置里真实存在的档位键上」的落点 —— 前端**不持有**档位清单。
 */
export function defaultCraftCalcTier(
  config: Pick<CraftCalcConfig, 'tiers'> | null | undefined
): string {
  const keys = Object.keys(config?.tiers ?? {})
  if (keys.includes(CRAFT_CALC_TIER)) return CRAFT_CALC_TIER
  return keys[0] ?? CRAFT_CALC_TIER
}

/**
 * 档位可选清单 = 算料配置 `tiers` 的**键**（值）+ `tiers[key].label`（文案）。
 *
 * 文案缺省时**回落键本身**（不编一个中文名 —— 编了就等于在前端持有第二份档位真值）。
 * 配置未加载 ⇒ 空数组（页面据此不渲染档位 chips，只出「配置未加载」提示）。
 */
export function craftCalcTierOptions(
  config: Pick<CraftCalcConfig, 'tiers'> | null | undefined
): Array<{ value: string; label: string }> {
  return Object.entries(config?.tiers ?? {}).map(([key, tier]) => ({
    value: key,
    label: typeof tier?.label === 'string' && tier.label.trim() !== '' ? tier.label.trim() : key,
  }))
}

/**
 * 工艺 → 用料公式 / 悬挂方式（用户 2026-09-19 追加裁定逐字：
 * 「**韩折用韩折公式算布料，打孔按倍数法算布料，默认选择 2 倍**」）。
 *
 * ⚠️ **这是「有守卫的副本」**：权威表 = 算料引擎 `curtain_calc.resolve_craft_rule`（工艺契约枚举值 → 公式/悬挂方式）；
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
   * 该行的**部位**（工序路线的索引键；主帘（布帘）不写该键 = 下游缺省即布帘）。
   *
   * ⚠️ **2026-09-21 用户裁定（口径反转）**：纱帘与布帘**用料算法完全一致** ⇒ 本键
   * **不再**决定「算不算料」（原 #4521 的「纱帘不算料」已作废）；保留它是因为入参要自描述
   * 部位（取错路线会让加工单工序全错），与用料算法无关。
   */
  curtainType?: string
  /**
   * 用料计算方法（issue #4527）：缺省 ⇒ `'pleat'`（韩折公式）。
   * issue #4874 起由页面上的**用料公式 chips** 接线（{@link CRAFT_CALC_FORMULAS}）。
   */
  formula?: string
  /**
   * 算料档位（issue #4874）：缺省 ⇒ {@link CRAFT_CALC_TIER}（页面用
   * {@link defaultCraftCalcTier} 从算料配置的 `tiers` 键集里解析后显式传入）。
   */
  craftTier?: string
}

/**
 * 把一行明细凑成试算入参；**凑不齐 ⇒ `null`（调用方不得发请求）**。
 *
 * 三条 fail-closed（都用 `null` 表达，**绝不**用默认窗宽/默认开数猜一个米数）：
 * 1. 缺宽或高（宽高是必填的「不可推导的原始输入」，§5.9.3）；
 * 2. 工艺明确是**无自动算料口径**的（四爪钩/穿杆/平幔）—— 试算没有意义；
 * 3. 宽/高非正数。
 *
 * ⚠️ **2026-09-21 用户裁定（口径反转）**：「订单中选择纱帘时，用料算法和布帘的用料算法完全一致，
 * 之前给的信息是错误的」⇒ 原 #4521「**纱帘不需要算用料米数，买多少就是多少**」**作废**，
 * 上面原第 2 条 fail-closed（`curtainType=纱帘 ⇒ null`）已删除：纱帘走**与布帘完全相同**的
 * 算料链路（同一公式 / 同一档位 / 同一次试算）。
 *
 * 公式与悬挂方式**由工艺推导**（用户 2026-09-19 追加裁定）：韩褶 ⇒ 折数法 + `s_hook`；
 * 打孔 ⇒ 倍数法 + `eyelet`（默认 2 倍）；未指定工艺 ⇒ 韩褶默认档。
 * 推导表是**有守卫的副本**（权威表在 `curtain_calc.resolve_craft_rule`，见文件头说明）。
 */
export function craftCalcParamsOf(line: CalcLineInput): CraftCalcParams | null {
  const width = Number(line.width)
  const height = Number(line.height)
  if (!Number.isFinite(width) || width <= 0) return null
  if (!Number.isFinite(height) || height <= 0) return null

  const craft = line.craft.craft
  if (craft !== undefined && !CALC_CRAFTS.has(craft)) return null

  const params: CraftCalcParams = {
    width,
    height,
    open_count: line.craft.openCount ?? 1,
    // 工艺 → 悬挂方式（打孔不是 s_hook：传错会被后端按韩褶口径算）
    mounting: (craft ? CRAFT_CALC_MOUNTING_BY_CRAFT[craft] : undefined) ?? CRAFT_CALC_MOUNTING,
    // 档位：商家选的（或页面按算料配置解析出的缺省）优先，没有 ⇒ 常量缺省（#4874 起不再钉死）
    craft_tier: line.craftTier ?? CRAFT_CALC_TIER,
    // 用料公式：显式选择 ⇒ 工艺推导 ⇒ 配置兜底（唯一口径；见 effectiveCraftCalcFormula）
    formula: effectiveCraftCalcFormula({ formula: line.formula, craft }, null),
  }
  // 工艺**原样带出**（后端据此再推导一次公式 —— 单一口径在算料引擎；此处不替它决定）
  if (craft) params.craft = craft
  if (line.craft.style) params.style = line.craft.style
  if (line.craft.specialOptions && line.craft.specialOptions.length > 0) {
    params.special_options = line.craft.specialOptions
  }
  // 对花 / 花距（issue #4571）：**只在「对花 = 是」时带出** —— 与 `buildCraftSpec` 同口径
  // （对花为否时留着花距是自相矛盾的输入，会让引擎多算一个花距）。
  // 为什么必须传：定宽买高时引擎按 `每幅长 = 窗高 + 卷边 + 花距` 算（`has_pattern` 是**唯一**开关），
  // 不传 ⇒ 试算比落库口径**少算「幅数 × 花距」**（页面预填的米数偏小 ⇒ 少收面料钱）。
  if (line.craft.hasPattern === true) {
    params.has_pattern = true
    const repeat = Number(line.craft.patternRepeat)
    if (Number.isFinite(repeat) && repeat > 0) {
      params.pattern_repeat = repeat
    }
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
    // 对花 / 花距进签名（issue #4571）：改了它**必须重发试算** —— 否则页面留着旧口径的米数
    // （定宽买高下差「幅数 × 花距」），而签名不变 ⇒ effect 不触发 ⇒ 静默错数。
    params.has_pattern ? '1' : '0',
    params.pattern_repeat ?? '',
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
 *
 * ⚠️ **2026-09-21 用户裁定（口径反转）**：纱帘与布帘用料算法完全一致 ⇒
 * 原「`curtainType=纱帘` ⇒ 恒无自动算料」那条已删除（原 #4521 口径作废）。
 */
export function isAutoCalcUnavailable(line: CalcLineInput): boolean {
  const craft = line.craft.craft
  return craft !== undefined && !CALC_CRAFTS.has(craft)
}
