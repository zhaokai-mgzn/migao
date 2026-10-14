// case_ids: OR-034
/**
 * 类级元守卫（issue #6882）：订单行**两个形态**的类型面 —— 详情行 `OrderItem` 不得再声明
 * 后端响应里没有的键；列表行 `OrderBriefItem` 不得声明列表不下发的键。
 *
 * ## 病灶（本仓实测）
 *
 * 屏幕面六处在读「后端根本没下发的键」：`productCode` / `color` / `specification` / `sku`
 * （`order_items` 表没有那几列，`OrderDetailResponse.OrderItemResponse` 也不含那几个键）
 * ⇒ 发货页「商品货号 / 颜色 / 规格」三列**恒 `-`**、详情「SKU / 规格」两行**恒不渲染**、
 * 余料页候选行的行身份比较退化成 `undefined === undefined`（**恒真** ⇒ 可能认错行）。
 * 而那四个键此前都挂在 `OrderItem` 上做**可选字段** ⇒ 编译器与测试**都不拦**。
 *
 * ## 本守卫为什么是**编译期**判据
 *
 * `@ts-expect-error` 只在「该行**确实**报错」时才算通过：谁把字段加回类型，这一行就变成
 * 「未使用的 `@ts-expect-error`」⇒ `tsc --noEmit`（CI job `admin-web typecheck`）**当场红**。
 * 运行时那一半（`toBeUndefined`）同时钉住「真对象上也没有这个键」，两半缺一不可。
 */
import { describe, expect, it } from 'vitest'
import type { OrderBriefItem, OrderItem } from '@/types'

describe('订单行类型面：详情形态 vs 列表形态（issue #6882）', () => {
  it('详情行 `OrderItem`：四个幽灵键在类型上不存在，在真对象上也不存在', () => {
    const item: OrderItem = {
      id: 'item-1',
      productName: '布艺遮光帘A',
      skuCode: '0012',
      quantity: 12.5,
      unitPrice: 100,
      amount: 1250,
      subtotal: 1250,
    }

    // 真字段在（对照组：本文件不是「什么都读不到」的恒真判据）
    expect(item.skuCode).toBe('0012')

    // @ts-expect-error `productCode` 不在 OrderDetailResponse.OrderItemResponse 里（真值 = skuCode）
    expect(item.productCode).toBeUndefined()
    // @ts-expect-error `color` 不在响应里（真值 = processingInfo.colorName）
    expect(item.color).toBeUndefined()
    // @ts-expect-error `specification` 不在响应里（真值 = processingInfo.doorWidth）
    expect(item.specification).toBeUndefined()
    // @ts-expect-error `sku` 不在响应里（真值 = skuCode）
    expect(item.sku).toBeUndefined()
  })

  it('列表行 `OrderBriefItem`：**有** productCode（真货号）与行主键 id、**没有** skuCode', () => {
    const brief: OrderBriefItem = {
      // issue #6883：列表**补下发**行主键（余料「按商品行搜索」靠它指认「是哪一行」）
      id: 'item-1',
      productName: '布艺遮光帘A',
      productCode: '0012',
      quantity: 12.5,
      unitPrice: 100,
      amount: 1250,
      subtotal: 1250,
    }

    // 列表**确实**下发真货号（后端填的是 products.sku_code）—— 所以列表读它是对的
    expect(brief.productCode).toBe('0012')
    expect(brief.id).toBe('item-1')

    // @ts-expect-error 列表不填 skuCode（那是详情侧从 products 回填的键）
    expect(brief.skuCode).toBeUndefined()
  })
})
