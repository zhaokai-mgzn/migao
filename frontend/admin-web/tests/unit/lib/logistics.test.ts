// case_ids: CU-009, UI-047, UI-053

import { describe, it, expect } from 'vitest'
import {
  LOGISTICS_TYPES,
  LOGISTICS_COMPANIES,
  logisticsTypeLabel,
  describeLogisticsProfile,
} from '@/lib/logistics'
import { lineSubtotal } from '@/lib/order-amount'

/**
 * 物流口径单一真值（issue #4419）——客户管理「收货信息」卡片与发货页共用同一份词表。
 *
 * 这层看起来「只是常量」，但它承载两条会静默出错的约定：
 * ① 类型枚举值必须与后端列口径一致（`express` 快递 / `logistics` 物流专线，V47 列注释），
 *    写错值不会报错，只会让 order_logistics.logistics_type 变成未知值；
 * ② `describeLogisticsProfile` **缺值不得补默认值** —— 否则「客户没录过常用物流」会被
 *    渲染成「快递」，看起来像已配置（假信息比空白更坏）。
 */
describe('logistics 词表（issue #4419）', () => {
  it('物流类型枚举值与后端列口径一致（express/logistics）', () => {
    expect(LOGISTICS_TYPES.map((t) => t.value)).toEqual(['express', 'logistics'])
    expect(LOGISTICS_TYPES.map((t) => t.label)).toEqual(['快递', '物流/专线'])
  })

  it('常用承运商候选含原发货页 6 家 + 域文档点名的物流专线承运商', () => {
    // 发货页原有 6 家必须保留（E2E 断言默认值为「德邦快递」，顺序不可乱）
    expect(LOGISTICS_COMPANIES.slice(0, 6)).toEqual([
      '德邦快递',
      '顺丰速运',
      '中通快递',
      '圆通速递',
      '韵达快递',
      '申通快递',
    ])
    expect(LOGISTICS_COMPANIES).toContain('四季安物流')
  })

  it('logisticsTypeLabel：已知值给中文，未知/空值回退「快递」（与列默认 express 一致）', () => {
    expect(logisticsTypeLabel('express')).toBe('快递')
    expect(logisticsTypeLabel('logistics')).toBe('物流/专线')
    expect(logisticsTypeLabel('')).toBe('快递')
    expect(logisticsTypeLabel(undefined)).toBe('快递')
    expect(logisticsTypeLabel(null)).toBe('快递')
    expect(logisticsTypeLabel('未知值')).toBe('快递')
  })

  it('describeLogisticsProfile：方式+公司都给时拼接，只给一个时只显示一个', () => {
    expect(describeLogisticsProfile('logistics', '四季安物流')).toBe('物流/专线 · 四季安物流')
    expect(describeLogisticsProfile('express', '顺丰速运')).toBe('快递 · 顺丰速运')
    expect(describeLogisticsProfile('logistics', '')).toBe('物流/专线')
    expect(describeLogisticsProfile(undefined, '四季安物流')).toBe('四季安物流')
  })

  it('describeLogisticsProfile：两者都缺返回空串（不编造「快递」默认值）', () => {
    expect(describeLogisticsProfile(undefined, undefined)).toBe('')
    expect(describeLogisticsProfile(null, null)).toBe('')
    expect(describeLogisticsProfile('', '   ')).toBe('')
  })
})

/**
 * 行金额口径**单一真值**（issue #4965）—— `lineSubtotal` 是屏幕（订单详情明细行）
 * 与纸面（报价单「本套金额」/加工费行）**共用**的那一份。
 *
 * 为什么值得单测：两处各写一次 `subtotal + processingFee` 时，任何一处口径变化都会让
 * 「屏幕显示的金额」与「打给客户的纸面金额」静默不一致 —— 而商家是照纸面对账的。
 * 本用例锁住口径本身（含 `processingFee` 缺省按 0 的存量单形态）。
 */
describe('lineSubtotal 行金额口径（issue #4965）', () => {
  it('行小计 = subtotal + processingFee', () => {
    expect(lineSubtotal({ subtotal: 1250, processingFee: 250 })).toBe(1500)
  })

  it('processingFee 缺省/为 0 ⇒ 按 0（存量单没有该字段，不得 NaN）', () => {
    expect(lineSubtotal({ subtotal: 1250 })).toBe(1250)
    expect(lineSubtotal({ subtotal: 1250, processingFee: 0 })).toBe(1250)
    expect(Number.isNaN(lineSubtotal({ subtotal: 1250 }))).toBe(false)
  })

  it('缺 subtotal 按 0（不 NaN）', () => {
    expect(lineSubtotal({ subtotal: 0, processingFee: 30 })).toBe(30)
  })
})
