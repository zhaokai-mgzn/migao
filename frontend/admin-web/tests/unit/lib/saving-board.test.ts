// case_ids: PR-095
//
// PR-095（issue #5159）：省料看板的**空数据不冒充 0** 与「文案不写死数字」两条纪律。
//
// 这两条都是**纯函数面**的判据（不需要起栈）：
// - 判据「空数据不冒充 0」：`null` ⇒ 「无数据」，而**真 0 必须照实回 0** ——
//   两者可区分，才不会把「没有浪费」与「还没有数据」读成同一件事（0 冒充「没有浪费」是本单点名的坑）。
// - §22 基线纪律①「文案里不出现数字」：档位文案（如「≤0.2 米」）**必须**来自服务端 `buckets[].label`。
//   本文件用**假档位**（「≤9.9 米」）做判别性断言 —— 一旦实现里写死了「0.2」，这些断言立刻红。
import { describe, expect, it } from 'vitest'
import {
  NO_DATA,
  cohortBadge,
  coexistenceNote,
  formatMeters,
  formatMetric,
  formatPeriod,
  formatShare,
  metricCards,
  unknownCostHint,
} from '@/lib/saving-board'

const ok = {
  cohorts: [
    {
      cohort: 'purchase',
      le0_2Share: 0,
      buckets: [{ label: '≤9.9 米' }, { label: '9.9~8.8 米' }],
    },
  ],
  trend: { purchasedTotalMeters: 0 },
}

describe('#5159 省料看板：无数据不冒充 0', () => {
  it('null / undefined / 非数 ⇒ 无数据；真 0 ⇒ 照实回 0（两者可区分）', () => {
    expect(formatMetric(null)).toBe(NO_DATA)
    expect(formatMetric(undefined)).toBe(NO_DATA)
    expect(formatMetric(Number.NaN)).toBe(NO_DATA)
    // 🔴 红证：把下面的 '0' 改成 NO_DATA（= 无数据冒充成「无数据」）或把上面的 null 改成 '0'
    //    （= 无数据冒充成 0）——两条断言必有一条红。
    expect(formatMetric(0)).toBe('0')
    expect(formatMetric(0)).not.toBe(NO_DATA)
    expect(formatMetric(12.345)).toBe('12.35')
    expect(formatMetric(12.345, 4)).toBe('12.345')
    expect(formatMetric(2.7)).toBe('2.7')
  })

  it('占比：null ⇒ 无数据；0 ⇒ 0.0%（不是无数据）', () => {
    expect(formatShare(null)).toBe(NO_DATA)
    expect(formatShare(0)).toBe('0.0%')
    expect(formatShare(0.5)).toBe('50.0%')
    expect(formatShare(0.0001)).toBe('0.0%')
  })

  it('米数：null ⇒ 无数据（不带「米」后缀，免得读成 0 米）', () => {
    expect(formatMeters(null)).toBe(NO_DATA)
    expect(formatMeters(0)).toBe('0 米')
    expect(formatMeters(35)).toBe('35 米')
  })

  it('未记收货日期 ⇒ 不猜（不是空白、不是 1970）', () => {
    expect(formatPeriod(null)).toBe('未记收货日期')
    expect(formatPeriod('2026-08')).toBe('2026-08')
  })

  it('金额读不出的行数：>0 才提示（0 行不打扰）', () => {
    expect(unknownCostHint(0)).toBeNull()
    expect(unknownCostHint(null)).toBeNull()
    expect(unknownCostHint(3)).toContain('3')
    expect(unknownCostHint(3)).toContain('金额不含这些行')
  })
})

describe('#5159 省料看板：两条指标并用 + 文案不写死数字', () => {
  it('指标卡**恒两条**（缺任一条 ⇒ 红），值一律取自服务端', () => {
    const cards = metricCards(ok)
    expect(cards).toHaveLength(2)
    expect(cards.map((c) => c.testId)).toEqual(['saving-metric-le-0-2', 'saving-metric-purchased'])
    expect(cards[0].value).toBe('0.0%')
    expect(cards[1].value).toBe('0 米')
  })

  it('🔴 档位文案来自**服务端 label**（写死「0.2」⇒ 红）', () => {
    const cards = metricCards(ok)
    expect(cards[0].label).toContain('≤9.9 米')
    expect(cards[0].label).not.toContain('0.2')
    const note = coexistenceNote(ok)
    expect(note).toContain('≤9.9 米')
    expect(note).not.toContain('0.2')
  })

  it('取不到档位文案时退回**不含数字**的措辞（绝不自己编一个「≤0.2 米」）', () => {
    const cards = metricCards(null)
    expect(cards[0].label).toBe('剩余最小档的批次占比')
    expect(coexistenceNote(null)).not.toMatch(/\d/)
  })

  it('🔴 说明文案写明「单看①会被排料误导」（页面必须看得见，不是只写进文档）', () => {
    const note = coexistenceNote(ok)
    expect(note).toContain('两条指标必须并用')
    expect(note).toContain('排料')
    expect(note).toContain('误导')
    // 因果链条必须写出来：排料省料 ⇒ 批次剩得更多 ⇒ 把效率提升显示成变差
    expect(note).toContain('剩得更多')
    expect(note).toContain('显示成变差')
  })

  it('无数据时两张卡都显示「无数据」，**不是 0**', () => {
    const empty = metricCards({ cohorts: [], trend: { purchasedTotalMeters: null } })
    expect(empty).toHaveLength(2)
    expect(empty.map((c) => c.value)).toEqual([NO_DATA, NO_DATA])
    expect(empty.map((c) => c.value)).not.toContain('0')
  })

  it('存量导入组带「单列」徽标（判据 2 的可见形态）', () => {
    expect(cohortBadge('opening')).toContain('单列')
    expect(cohortBadge('purchase')).toBeNull()
    expect(cohortBadge('unknown')).toBe('来源未知')
  })
})
