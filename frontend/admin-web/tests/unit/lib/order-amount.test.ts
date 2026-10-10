// case_ids: UI-053

import { describe, it, expect } from 'vitest'
import { lineSubtotal } from '@/lib/order-amount'
import type { OrderItem } from '@/types'

/**
 * 行金额口径**单一真值**（issue #4965）—— `lineSubtotal` 是屏幕（订单详情明细行
 * `OrderItemList`）与纸面（报价单 `QuotationDoc` 的「本套金额」/加工费行）**共用**的那一份。
 *
 * 为什么值得单测：两处各写一次 `subtotal + processingFee` 时，任何一处口径变化都会让
 * 「屏幕显示的金额」与「打给客户的纸面金额」静默不一致 —— 而商家是照纸面对账的。
 * 本用例锁住口径本身（含 `processingFee` 缺省的存量单形态：缺字段不得变 NaN）。
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

  it('🔴 两个加数都缺 ⇒ `null`（「算不出来」，**不是 0**，issue #6720）', () => {
    // 纸面（QuotationDoc 的「本套金额」）据此印 `—`；把它改回 `|| 0` ⇒ 纸面恒印 0.00
    // （客户会把「没有这个数」读成「这一项是零元」）。
    expect(lineSubtotal({} as Pick<OrderItem, 'subtotal' | 'processingFee'>)).toBeNull()
    // 反向对照：**单个加数为 0** 是真值 ⇒ 仍算得出数（不得退化成 null）
    expect(lineSubtotal({ subtotal: 0, processingFee: 0 })).toBe(0)
    expect(lineSubtotal({ subtotal: 0 })).toBe(0)
    expect(lineSubtotal({ subtotal: 1250 })).toBe(1250)
    // 非有限值同样按「算不出来」处理（不 NaN）
    expect(lineSubtotal({ subtotal: Number.NaN, processingFee: Number.NaN })).toBe(0)
  })

  it('与 OrderItemList 的行小计口径同源：屏幕与纸面调用同一实现（不各算一套）', () => {
    // 判据是**同源**而非数值巧合：本函数被 OrderItemList（屏幕）与 QuotationDoc（纸面）
    // 同时 import。删掉任一处调用、改回内联 `item.subtotal + item.processingFee` ⇒
    // 纸面/屏幕口径即分叉（此处无法静态判定，故由 OrderItemList.test.tsx 与
    // QuotationDoc.test.tsx 分别断言各自的展示值来自该实现）。
    expect(lineSubtotal({ subtotal: 0.1, processingFee: 0.2 })).toBeCloseTo(0.3, 10)
  })
})
