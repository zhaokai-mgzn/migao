// case_ids: PR-098
/**
 * 余料台账「按商品行搜索」的候选行摊平（issue #6883）。
 *
 * ## 病灶
 *
 * 页面上原写死的映射有两处依赖**拿不到的键**：
 * - `filter((it) => !!it.id)` —— **列表**响应不下发 `order_items.id` ⇒ **恒 false** ⇒ 候选恒空，
 *   「按商品行搜索」整条链路**搜不出任何一行**；
 * - 选中行之后还要**重新拉一次详情、再靠「品名 + 颜色 + 规格 + 数量」把它猜回来** ——
 *   而后两个键在详情响应里也不存在 ⇒ 判据退化成「品名 + 数量」⇒ **同名同量的两行会被认成同一行**
 *   （余料可能挂到错行）。
 *
 * ## 本判据钉什么
 *
 * ① 同名同量的两行必须摊成**两条**候选、**各带各的行主键**（不许合并、不许猜）；
 * ② 颜色 / 门幅取真值源（`processingInfo`）+ 门幅归一；
 * ③ 没有行主键的行**丢弃**（宁可少列，也不给挂不上账的假候选）。
 *
 * 红证：把 `remnantLineCandidates` 里的 `item.id` 换成任何「猜」的写法（或恢复
 * `filter` 掉 id 的旧行为）⇒ ①②③ 至少一条当场红。
 */
import { describe, expect, it } from 'vitest'
import { remnantLineCandidates } from '@/lib/remnant-line-candidates'
import type { OrderBrief } from '@/types'

const order = (items: OrderBrief['items']): OrderBrief =>
  ({
    id: 'order-1',
    orderNo: 'ORD-20261014-0001',
    customerName: '张三',
    items,
  }) as OrderBrief

describe('remnantLineCandidates（issue #6883）', () => {
  it('同名同量的两行 = 两条候选，各带各的行主键（不猜、不合并）', () => {
    const candidates = remnantLineCandidates([
      order([
        {
          id: 'item-a',
          productName: '蜂巢帘',
          quantity: 2,
          processingInfo: { colorName: '米白', doorWidth: '2.8' },
        },
        {
          id: 'item-b',
          productName: '蜂巢帘', // 同名
          quantity: 2, // 同量 —— 旧实现靠「品名 + 数量」猜 ⇒ 两行分不开
          processingInfo: { colorName: '深灰', doorWidth: '3.2米' },
        },
      ]),
    ])

    expect(candidates).toHaveLength(2)
    expect(candidates.map((c) => c.itemId)).toEqual(['item-a', 'item-b'])
    // 颜色 / 门幅来自真值源，且门幅归一到「…米」
    expect(candidates.map((c) => c.color)).toEqual(['米白', '深灰'])
    expect(candidates.map((c) => c.specification)).toEqual(['2.8米', '3.2米'])
    expect(candidates.map((c) => c.orderNo)).toEqual(['ORD-20261014-0001', 'ORD-20261014-0001'])
  })

  it('没有行主键的行被丢弃（挂不上账的行不出现在候选里）', () => {
    const candidates = remnantLineCandidates([
      order([
        { id: 'item-a', productName: '蜂巢帘', quantity: 2 },
        { productName: '没有主键的行', quantity: 1 },
      ]),
    ])
    expect(candidates.map((c) => c.itemId)).toEqual(['item-a'])
  })

  it('缺颜色 / 门幅 ⇒ 空串（不编占位、不印 undefined）', () => {
    const candidates = remnantLineCandidates([
      order([{ id: 'item-a', productName: '蜂巢帘', quantity: 2 }]),
    ])
    expect(candidates[0].color).toBe('')
    expect(candidates[0].specification).toBe('')
  })

  it('空列表 / 无明细行 ⇒ 空数组（不抛）', () => {
    expect(remnantLineCandidates([])).toEqual([])
    expect(remnantLineCandidates([order(undefined)])).toEqual([])
  })
})
