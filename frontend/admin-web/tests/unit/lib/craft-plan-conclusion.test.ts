// case_ids: OR-052
/**
 * 「用料方案（系统推导）」的**结论表达**（`lib/craft-plan-conclusion.ts`）—— 纯函数判据。
 *
 * 用户 2026-09-29 逐字：「`来源汇总：人工指定 0 项…` / `分幅 —` / `拼接 不拼接` / `接高 — 米` /
 * `接宽 — 米` 这里的几句话没看懂什么意思，这里到底是需要拼接？接高？接宽？分幅？
 * **给用户展示的推导结论要表达清晰**」。
 *
 * 三条判据：① 结论句回答「到底要不要」；② 逐项白话（`整幅（不分幅）` / `不需要`，不拿 `—` 冒充）；
 * ③ 拼接措辞与页面既有 `craftPlanSpliceText` **同源**（传了就照它显示，避免同一档两份文案）。
 */
import { describe, it, expect } from 'vitest'
import { craftPlanConclusionOf } from '@/lib/craft-plan-conclusion'

describe('用料方案结论（2026-09-29 用户裁定）', () => {
  it('判据 ①：定高买宽 + 零拼接 ⇒ 结论句「整幅裁：不用拼接、不用接高接宽」', () => {
    const c = craftPlanConclusionOf({
      panels: null,
      spliceTimes: 0,
      joinHeightM: null,
      joinWidthM: null,
      doorWidth: '3.2',
      craft: '韩褶',
    })
    expect(c.headline).toBe('整幅裁：不用拼接、不用接高接宽')
    expect(c.items).toEqual([
      { label: '工艺', value: '韩褶' },
      { label: '门幅', value: '3.2 米' },
      { label: '分幅', value: '整幅（不分幅）' },
      { label: '拼接', value: '不拼接' },
      { label: '接高', value: '不需要' },
      { label: '接宽', value: '不需要' },
    ])
  })

  it('判据 ①b：需要拼 / 接高 / 接宽 / 分幅时，结论句逐项列清（顺序稳定、去尾零）', () => {
    const c = craftPlanConclusionOf({
      panels: 2,
      spliceTimes: 2,
      joinHeightM: 0.05,
      joinWidthM: 0.1,
      doorWidth: 2.8,
    })
    expect(c.headline).toBe('需要：分 2 幅、拼2次、接高 0.05 米、接宽 0.1 米')
  })

  it('判据 ②：逐项白话 —— 「整幅（不分幅）」/「不需要」，**不拿 `—` 冒充**一个值', () => {
    const c = craftPlanConclusionOf({
      panels: null,
      spliceTimes: null,
      joinHeightM: null,
      joinWidthM: null,
      doorWidth: '2.8',
    })
    const text = c.items.map((i) => `${i.label} ${i.value}`).join(' · ')
    expect(text).toContain('分幅 整幅（不分幅）')
    expect(text).toContain('拼接 不拼接')
    expect(text).toContain('接高 不需要')
    expect(text).toContain('接宽 不需要')
    expect(text).not.toContain('—')
  })

  it('判据 ②b：工艺缺省 ⇒ 值里带「可在②加工项改」（旧文案的「③」是过期编号）', () => {
    const c = craftPlanConclusionOf({ craftIsDefault: true, doorWidth: '2.8' })
    const craft = c.items.find((i) => i.label === '工艺')
    expect(craft?.value).toBe('（系统默认 · 可在②加工项改）')
    expect(craft?.value).not.toContain('③')
  })

  it('判据 ③：拼接措辞与既有 `craftPlanSpliceText` 同源（传了就照它显示）', () => {
    const c = craftPlanConclusionOf({ spliceTimes: 3, spliceText: '拼3次', doorWidth: '2.8' })
    expect(c.items.find((i) => i.label === '拼接')?.value).toBe('拼3次')
    expect(c.headline).toContain('拼3次')
  })

  it('判据 ③b：拼接次数 ≥ 1 但没给措辞 ⇒ 回落 `拼N次`（与页面同一形态，不发明第三种写法）', () => {
    const c = craftPlanConclusionOf({ spliceTimes: 1, doorWidth: '2.8' })
    expect(c.items.find((i) => i.label === '拼接')?.value).toBe('拼1次')
  })
})
