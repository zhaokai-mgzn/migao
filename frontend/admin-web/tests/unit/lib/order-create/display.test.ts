// case_ids: MC-243
/**
 * `lib/order-create/display.ts` —— 下单页切片的**展示 / 价格预览口径**（issue #8725 第一档）。
 *
 * 单一职责：把「数字与枚举」变成用户可读的字。本文件钉住四类口径：
 * ① 金额格式化（**几位小数 / 千分位 / 脏值兜底** —— 涉钱面，改一位就改变商家看到的钱数）；
 * ② 未定价组合的展示名（与加工费定价页逐字一致）；
 * ③ 计价失败话术（服务端三种错误形状都要落到同一句可读文案）；
 * ④ 颜色去重（同色多门幅只出一种，缺名字给「颜色<id>」兜底）。
 */
import { describe, it, expect } from 'vitest'
import {
  FEE_SOURCE_LABELS,
  OPEN_COUNT_LABEL,
  SPLICE_OVERRIDE_OPTIONS,
  UNPRICED_NO_COMPOSITION,
  feePreviewErrorText,
  formatAmount,
  uniqueColors,
  unpricedCombinationLabel,
} from '@/lib/order-create/display'

describe('display — 金额格式化（涉钱面）', () => {
  it('恒两位小数 + 千分位', () => {
    expect(formatAmount(1395.555)).toBe('¥1,395.56')
    expect(formatAmount(1234567)).toBe('¥1,234,567.00')
    expect(formatAmount(0.5)).toBe('¥0.50')
  })

  it('零与脏值不炸、不出现 `¥NaN`', () => {
    expect(formatAmount(0)).toBe('¥0.00')
    expect(formatAmount(Number.NaN)).toBe('¥0.00')
    expect(formatAmount(undefined as unknown as number)).toBe('¥0.00')
  })
})

describe('display — 未定价组合的展示名', () => {
  it('items 优先（与加工费定价页同一写法）', () => {
    expect(unpricedCombinationLabel({ items: ['韩褶', '定型'], composition: 'X' })).toBe('韩褶 + 定型')
  })

  it('items 缺席 ⇒ 回落 composition；两者都空 ⇒ 具名兜底文案（不许留空）', () => {
    expect(unpricedCombinationLabel({ composition: ' 韩褶+定型 ' })).toBe('韩褶+定型')
    expect(unpricedCombinationLabel({})).toBe(UNPRICED_NO_COMPOSITION)
    expect(unpricedCombinationLabel(undefined)).toBe(UNPRICED_NO_COMPOSITION)
  })
})

describe('display — 计价失败话术', () => {
  it('三种服务端错误形状都带出具名原因', () => {
    expect(feePreviewErrorText({ response: { data: { error: { message: '组合价目缺失' } } } })).toBe(
      '加工费计价失败：组合价目缺失'
    )
    expect(feePreviewErrorText({ response: { data: { message: '网关超时' } } })).toBe(
      '加工费计价失败：网关超时'
    )
    expect(feePreviewErrorText(new Error('Network Error'))).toBe('加工费计价失败：Network Error')
  })

  it('拿不到原因时给可重试的兜底话术（不是空白）', () => {
    expect(feePreviewErrorText({})).toBe('加工费计价失败，请稍后重试')
  })
})

describe('display — 颜色表', () => {
  it('同色多门幅只出一种；缺名字给「颜色<id>」兜底；无 skus ⇒ 空表', () => {
    expect(
      uniqueColors([
        { id: 's1', colorId: 'c1', colorName: '米白', price: 1, doorWidth: '2.8' },
        { id: 's2', colorId: 'c1', colorName: '米白', price: 1, doorWidth: '3.2' },
        { id: 's3', colorId: 'c2', price: 1 },
      ])
    ).toEqual([
      { id: 'c1', name: '米白' },
      { id: 'c2', name: '颜色c2' },
    ])
    expect(uniqueColors(undefined)).toEqual([])
  })
})

describe('display — 标签表', () => {
  it('打开方式 / 费用来源 / 拼接选项逐字固定（下游按 label 比对）', () => {
    expect(OPEN_COUNT_LABEL[2]).toBe('双开')
    expect(FEE_SOURCE_LABELS.matched).toBe('组合价目')
    expect(SPLICE_OVERRIDE_OPTIONS.map((o) => o.label)).toEqual([
      '由推导决定',
      '不拼接',
      '拼1次',
      '拼2次',
      '拼3次',
    ])
  })
})
