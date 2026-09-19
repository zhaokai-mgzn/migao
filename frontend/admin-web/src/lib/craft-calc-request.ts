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
import type { CraftSpecInput } from './order-craft-fields'

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

/** 走折数法的工艺（空 = 未指定 ⇒ 按韩褶默认档试算） */
const PLEAT_CRAFTS = new Set(['韩褶', ''])

export interface CalcLineInput {
  /** 成品宽（米）—— 必填 */
  width: number | null
  /** 成品高（米）—— 必填 */
  height: number | null
  craft: CraftSpecInput
}

/**
 * 把一行明细凑成试算入参；**凑不齐 ⇒ `null`（调用方不得发请求）**。
 *
 * 三条 fail-closed（都用 `null` 表达，**绝不**用默认窗宽/默认开数猜一个米数）：
 * 1. 缺宽或高（宽高是必填的「不可推导的原始输入」，§5.9.3）；
 * 2. 工艺明确是**非韩褶**（打孔/四爪钩/穿杆/平幔）—— 折数法不适用，试算没有意义；
 * 3. 宽/高非正数。
 */
export function craftCalcParamsOf(line: CalcLineInput): CraftCalcParams | null {
  const width = Number(line.width)
  const height = Number(line.height)
  if (!Number.isFinite(width) || width <= 0) return null
  if (!Number.isFinite(height) || height <= 0) return null

  const craft = line.craft.craft
  if (craft !== undefined && !PLEAT_CRAFTS.has(craft)) return null

  const params: CraftCalcParams = {
    width,
    height,
    open_count: line.craft.openCount ?? 1,
    mounting: CRAFT_CALC_MOUNTING,
    craft_tier: CRAFT_CALC_TIER,
  }
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
