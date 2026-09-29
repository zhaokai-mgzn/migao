/**
 * 「用料方案（系统推导）」的**结论表达**（2026-09-29 用户裁定，原话：
 * 「这里的几句话没看懂什么意思，这里到底是需要拼接？接高？接宽？分幅？
 * 给用户展示的推导结论要表达清晰」）。
 *
 * 病因：旧形态把引擎的**内部读数**原样摊开（`来源汇总：人工指定 0 项 · 系统推导 4 项（逐项见括号）`
 * / `分幅 —` / `拼接 不拼接（系统推导）` / `接高 — 米` / `接宽 — 米`）——
 * 商家要的是**结论**（这一套帘要不要拼、要不要接高接宽、分几幅），不是坐标系。
 *
 * 两条口径：
 * ① **只做措辞**：数一律取自算料引擎的推导方案（`plan`），本函数**不重算**任何几何/用料；
 * ② **不说没有的话**：分幅在定高买宽下**无定义**（`panels === null`）⇒ 说「整幅（不分幅）」，
 *    不拿 `—` 或 `0` 冒充一个数（「缺值不渲染」的同一纪律）。
 *
 * ⚠️ 本函数**不复述**「选优顺序」（那份口径的单一真值源 = `docs/design/order-auto-derivation.md`，
 * 在别处复述会被 `tests/unit_ci_workflows/test_craft_calc_ranking_order_single_source.py` 判红）。
 */
export interface CraftPlanConclusionInput {
  /** 分幅数（`plan.panels`；定高买宽 ⇒ `null` = **无定义**） */
  panels?: number | null
  /** 拼接次数（`plan.splice_times`；0 ⇒ 不拼接） */
  spliceTimes?: number | null
  /**
   * 拼接的**既有措辞**（页面用 `craftPlanSpliceText(plan)` 给）—— 传了就照它显示，
   * 避免同一档出现两份文案（`拼2次` / `拼 2 次` 这种漂移会让既有判据红）。
   */
  spliceText?: string | null
  /** 接高缺口（米；`null` / 0 ⇒ 不需要） */
  joinHeightM?: number | null
  /** 接宽缺口（米；`null` / 0 ⇒ 不需要） */
  joinWidthM?: number | null
  /** 门幅（米；来自所选 SKU） */
  doorWidth?: number | string | null
  /** 工艺（来自勾选的工艺项） */
  craft?: string | null
  /** `true` = 工艺是**系统默认**（没勾任何工艺项）⇒ 措辞里带上「可在②加工项改」 */
  craftIsDefault?: boolean
}

export interface CraftPlanConclusionItem {
  label: string
  value: string
}

export interface CraftPlanConclusion {
  /** 一句话结论：**到底要不要**拼接 / 接高 / 接宽 / 分幅 */
  headline: string
  /** 逐项白话（加工类型 / 工艺 / 门幅 / 分幅 / 拼接 / 接高 / 接宽） */
  items: CraftPlanConclusionItem[]
}

/** 正数才认（`null` / `0` / 负数 / 非数 ⇒ `null` = 「不需要」） */
function positive(value: number | null | undefined): number | null {
  const n = Number(value)
  return Number.isFinite(n) && n > 0 ? n : null
}

/** 数字 → 展示文本（去掉多余的尾零：`0.050` ⇒ `0.05`） */
function num(value: number): string {
  return String(Number(value.toFixed(3)))
}

export function craftPlanConclusionOf(input: CraftPlanConclusionInput): CraftPlanConclusion {
  const spliceTimes = positive(input.spliceTimes)
  const splices = spliceTimes === null ? 0 : Math.trunc(spliceTimes)
  const joinHeight = positive(input.joinHeightM)
  const joinWidth = positive(input.joinWidthM)
  const panels = positive(input.panels)
  const panelLabel = panels !== null && panels > 1 ? `分 ${Math.trunc(panels)} 幅` : '整幅（不分幅）'

  const spliceText =
    input.spliceText && input.spliceText.trim() !== ''
      ? input.spliceText
      : splices > 0
        ? `拼${splices}次`
        : '不拼接'

  // 结论句只列**真的要做的事**：不拼接且不用接高接宽 ⇒ 明说「整幅裁」，
  // 不让商家从一堆「—」里自己推断（那正是旧形态被读错的地方）。
  const needs: string[] = []
  if (panels !== null && panels > 1) needs.push(panelLabel)
  if (splices > 0) needs.push(spliceText)
  if (joinHeight !== null) needs.push(`接高 ${num(joinHeight)} 米`)
  if (joinWidth !== null) needs.push(`接宽 ${num(joinWidth)} 米`)
  const headline = needs.length > 0 ? `需要：${needs.join('、')}` : '整幅裁：不用拼接、不用接高接宽'

  const doorWidthText =
    input.doorWidth === null || input.doorWidth === undefined || String(input.doorWidth).trim() === ''
      ? '—'
      : `${input.doorWidth} 米`
  const craftText =
    input.craft && input.craft.trim() !== ''
      ? input.craft
      : input.craftIsDefault
        ? '（系统默认 · 可在②加工项改）'
        : '—'

  return {
    headline,
    items: [
      ...(input.craftIsDefault || (input.craft && input.craft.trim() !== '')
        ? [{ label: '工艺', value: craftText }]
        : []),
      { label: '门幅', value: doorWidthText },
      { label: '分幅', value: panelLabel },
      { label: '拼接', value: spliceText },
      { label: '接高', value: joinHeight !== null ? `${num(joinHeight)} 米` : '不需要' },
      { label: '接宽', value: joinWidth !== null ? `${num(joinWidth)} 米` : '不需要' },
    ],
  }
}
