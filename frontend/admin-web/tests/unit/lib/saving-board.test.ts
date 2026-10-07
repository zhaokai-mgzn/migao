// case_ids: PR-095, UI-092
//
// 省料看板**纯函数面**的判据：
// - 判据 4「空数据不冒充 0」：`null` ⇒ 「无数据」，而**真 0 必须照实回 0** ——
//   两者可区分，才不会把「没有浪费」与「还没有数据」读成同一件事。
// - §22 基线纪律①「文案里不出现数字」：档位文案（如「≤0.2 米」）**必须**来自服务端 `buckets[].label`。
//   本文件用**假档位**（「≤9.9 米」）做判别性断言 —— 一旦实现里写死了「0.2」，这些断言立刻红。
// - issue #6459「少废话」：页面自带文案有**字数上限**（加一段解释就红）—— 免得门道卡那类散文再长回来。
// - issue #6459「首屏两个大数字」：本期取服务端 `comparison`，后端未部署 ⇒ 退回服务端 `total`，
//   两条路都**不自己算**。
import { describe, expect, it } from 'vitest'
import {
  NO_DATA,
  batchTrendNote,
  batchTrendTitle,
  comparisonText,
  footnotes,
  formatMeters,
  formatMetric,
  formatPeriod,
  formatShare,
  metricView,
  savedRule,
  unknownCostHint,
  verdictWord,
} from '@/lib/saving-board'

describe('#5159 省料看板：无数据不冒充 0', () => {
  it('null / undefined / 非数 ⇒ 无数据；真 0 ⇒ 照实回 0（两者可区分）', () => {
    expect(formatMetric(null)).toBe(NO_DATA)
    expect(formatMetric(undefined)).toBe(NO_DATA)
    expect(formatMetric(Number.NaN)).toBe(NO_DATA)
    // 🔴 红证：把 '0' 改成 NO_DATA（无数据冒充成「无数据」）或把上面的 null 改成 '0'
    //    （无数据冒充成 0）—— 两条断言必有一条红。
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

describe('#6459 省料看板：档位文案来自服务端 + 少废话 + 首屏取值', () => {
  it('🔴 档位文案来自**服务端 label**（写死「0.2」⇒ 红）', () => {
    const title = batchTrendTitle('≤9.9 米')
    expect(title).toContain('≤9.9 米')
    expect(title).not.toContain('0.2')
    expect(title).toContain('几乎用完的布')
  })

  it('取不到档位文案时退回**不含数字**的措辞（绝不自己编一个「≤0.2 米」）', () => {
    expect(batchTrendTitle(undefined)).not.toMatch(/\d/)
    expect(batchTrendTitle(null)).not.toMatch(/\d/)
  })

  it('🔴 页面自带文案有**字数上限**（加一段解释性散文 ⇒ 红：#6459 的「少废话」裁定）', () => {
    // 首屏两句话（页头规则 + 趋势说明）合计不超过 120 字
    expect(savedRule().length + batchTrendNote().length).toBeLessThanOrEqual(120)
    // 折叠区也不许变成第二个文档
    expect(footnotes('Asia/Shanghai').length).toBeLessThanOrEqual(7)
    // 规则必须说清三个量（数据 / 规则说清楚「怎么省下来」）
    expect(savedRule()).toContain('该领')
    expect(savedRule()).toContain('排料实际领走')
    expect(savedRule()).toContain('进价')
  })

  it('🔴 内部口径词不进这层文案（切换后 / 存量导入 / 来源未知）', () => {
    const text = [savedRule(), batchTrendNote(), ...footnotes()].join('\n')
    expect(text).not.toContain('切换后')
    expect(text).not.toContain('存量导入')
    expect(text).not.toContain('来源未知')
    // 历史库存这件事要用商家的话说（元守卫 `user-copy-jargon-guard` 的形态③ 是这条的类级收口）
    expect(text).toContain('老库存')
  })

  it('🔴 首屏大数字 = 服务端本期值；后端未部署 ⇒ 退回服务端累计值（两条路都不自己算）', () => {
    const delta = { period: '2026-10', current: 55, previous: 120, verdict: 'worse' }
    expect(metricView(delta, 99)).toEqual({ period: '2026-10', value: 55, cumulative: 99 })

    // 无 comparison（后端未部署）⇒ 大数字退回**累计**（服务端 total），期间不编一个
    expect(metricView(undefined, 99)).toEqual({ period: null, value: 99, cumulative: 99 })
    expect(metricView(null, null).value).toBeNull()

    // 本期读不出（current 为 null）⇒ 同样退回累计，且**不假装有本期**
    expect(metricView({ period: '2026-10', current: null }, 99)).toEqual({
      period: null,
      value: 99,
      cumulative: 99,
    })
  })

  it('环比文案：好坏词只来自服务端 verdict；null verdict ⇒ 明说「不给好坏」', () => {
    const worse = comparisonText(
      { period: '2026-10', previousPeriod: '2026-09', current: 55, previous: 120, verdict: 'worse' },
      'meters'
    )
    expect(worse).toContain('变差')
    expect(worse).toContain('55 米')

    const withheld = comparisonText(
      { period: '2026-10', previousPeriod: '2026-09', current: 55, previous: 120, verdict: null },
      'meters'
    )
    expect(withheld).toContain('不给好坏')
    expect(withheld).not.toContain('变好')
    expect(withheld).not.toContain('变差')

    // 未知取值不猜（不回落成「持平」）
    expect(verdictWord('weird')).toBeNull()
    expect(verdictWord('partial')).toContain('还没过完')
  })
})
