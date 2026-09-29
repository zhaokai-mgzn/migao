// case_ids: OR-052, OR-041
/**
 * 用料公式的**参数说明**（`lib/meters-formula-legend.ts`）—— 纯函数判据。
 *
 * 用户 2026-09-29 逐字：「这里的公式展示很 ok，但是**用户看不懂里面的数字代表什么**，
 * 应该要把**参数名**带上，如果用户要修改参数也知道去改什么」。
 *
 * 三条判据：
 * ① **参数名 + 出现顺序**与公式串一致（值取自同一次算料响应 / 算料配置）；
 * ② **缺值不编**：取不到的数该条整条不出现（配置未加载 / 试算还没回来）；
 * ③ **不复算**：倍数法只说明**输入侧**三个数（每片宽 / 每片米是引擎的中间量，前端不得再算一遍）；
 *    表外公式 ⇒ 不出说明（宁可没有，也不说错）。
 */
import { describe, it, expect } from 'vitest'
import { marginForOpenCount, metersFormulaLegend } from '@/lib/meters-formula-legend'

const CONFIG = { margin_single: 0.3, margin_multi: 0.3 }

describe('用料公式参数说明（2026-09-29 用户裁定）', () => {
  it('判据 ①：韩褶公式 —— 逐条「数 = 参数名」，顺序与公式串一致', () => {
    const legend = metersFormulaLegend({
      formula: 'pleat',
      width: 6.6,
      openCount: 2,
      pleatCount: 52,
      perFold: 0.25,
      fullness: 2,
      config: CONFIG,
    })
    expect(legend).not.toBeNull()
    // 公式串 `(6.6+0.3)×2.0 → 52折 → 0.25×52+0.3 = 13.3米` 里出现的数 = 这五个
    expect(legend!.params).toEqual([
      { value: '6.6', name: '净窗宽（米）' },
      { value: '0.3', name: '每片余量（米 · 算料配置）' },
      { value: '2', name: '褶倍（算料配置）' },
      { value: '52', name: '自动算出的褶数' },
      { value: '0.25', name: '每折吃布（米 · 算料配置）' },
    ])
    // 「要改去哪改」——用户口径「如果用户要修改参数也知道去改什么」
    expect(legend!.where).toContain('净尺寸')
    expect(legend!.where).toContain('打开方式')
    expect(legend!.where).toContain('工艺配置 → 算料配置')
  })

  it('判据 ①b：余量按**开数**取键（单开 ⇒ margin_single；多开 ⇒ margin_multi），与引擎同口径', () => {
    const config = { margin_single: 0.2, margin_multi: 0.35 }
    expect(marginForOpenCount(1, config)).toBe(0.2)
    expect(marginForOpenCount(2, config)).toBe(0.35)
    // 开数缺省 ⇒ 按单开取（引擎 `open_count <= 1` 同一口径）
    expect(marginForOpenCount(null, config)).toBe(0.2)
    // 配置取不到 ⇒ `null`（宁可不说明，也不说一个错的余量）
    expect(marginForOpenCount(2, null)).toBeNull()

    const legend = metersFormulaLegend({
      formula: 'pleat',
      width: 6.6,
      openCount: 2,
      pleatCount: 52,
      perFold: 0.25,
      fullness: 2,
      config,
    })
    expect(legend!.params[1]).toEqual({ value: '0.35', name: '每片余量（米 · 算料配置）' })
  })

  it('判据 ②：缺值不编 —— 配置未加载 / 试算未回来 ⇒ 对应那条**整条不出现**', () => {
    // 试算还没回来（无 pleatCount / perFold / fullness）+ 配置未加载 ⇒ 只剩「净窗宽」一条
    const sparse = metersFormulaLegend({ formula: 'pleat', width: 6.6, config: null })
    expect(sparse!.params).toEqual([{ value: '6.6', name: '净窗宽（米）' }])
    // 连窗宽都没有 ⇒ 整条说明不出现（**不编一个 0 或默认值**）
    expect(metersFormulaLegend({ formula: 'pleat', config: null })).toBeNull()
  })

  it('判据 ③：倍数法只说明**输入侧**三个数（派生量由引擎算，前端不复算）', () => {
    const legend = metersFormulaLegend({
      formula: 'fullness',
      width: 5.5,
      openCount: 2,
      fullness: 2,
      config: CONFIG,
    })
    expect(legend!.params).toEqual([
      { value: '5.5', name: '净窗宽（米）' },
      { value: '2', name: '开数（打开方式）' },
      { value: '2', name: '褶倍（算料配置）' },
    ])
  })

  it('判据 ③b：公式缺失 / 表外取值 ⇒ 不出说明（宁可没有，也不说错）', () => {
    expect(metersFormulaLegend({ formula: '', width: 6.6, config: CONFIG })).toBeNull()
    expect(metersFormulaLegend({ formula: 'unknown_formula', width: 6.6, config: CONFIG })).toBeNull()
  })
})
