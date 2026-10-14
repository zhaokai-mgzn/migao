// case_ids: UI-040, UI-053, UI-061, UI-062, UI-095
/**
 * 纸面「商品 SKU 身份」唯一取值口（issue #6869）—— 实例判据 + 红证。
 *
 * 为什么必须有这一层：四份单据（报价单 / 销售单 / 加工单 / 发货单）原先**各自**读
 * `item.productCode` / `item.color` / `item.specification`，而 `OrderItemResponse` 里
 * **没有这三个键**（真字段 = `skuCode` + `processingInfo.colorName` / `doorWidth`）⇒
 * 纸面那几列在真单上恒空，而测试夹具自己造了幽灵字段 ⇒ **没有任何东西会红**。
 * ⇒ 取值口收敛到 `orderItemSku()`：本文件钉住它的口径，类级守卫
 * （`tests/unit_ci_workflows/test_print_media_matrix_guard.py` 判据 C7）钉住「单据必须走它」。
 */
import { describe, expect, it } from 'vitest'
import { orderItemSku, type OrderItemSkuSource } from '@/lib/order-item-sku'
import type { OrderItem } from '@/types'

function buildItem(overrides: Partial<OrderItem> = {}): OrderItem {
  return {
    id: 'item-1',
    productName: '布艺遮光帘A',
    skuCode: '0012',
    quantity: 12.5,
    unitPrice: 100,
    amount: 1250,
    subtotal: 1250,
    processingInfo: { colorName: '米白', doorWidth: '2.8米', curtainType: '纱帘', craft: '韩褶' },
    ...overrides,
  }
}

describe('orderItemSku — 纸面商品身份唯一取值口（issue #6869）', () => {
  it('取响应真字段：品名 = productName / 货号 = skuCode / 颜色 = colorName / 门幅 = doorWidth', () => {
    expect(orderItemSku(buildItem())).toMatchObject({
      name: '布艺遮光帘A',
      code: '0012',
      color: '米白',
      doorWidth: '2.8米',
    })
  })

  it('🔴 红证：**只给 `skuCode`**（真 wire 形态，没有 `productCode`）⇒ 货号仍有值', () => {
    // 修前形态 = 实现读 `item.productCode`（`OrderItemResponse` 里没有这个键）——
    // 把 `orderItemSku` 的 code 一行改回 `text(item.productCode)` ⇒ 本用例当场红。
    const item = buildItem()
    // 语料自证：样本里确实没有那个幽灵字段（issue #6882 起它连类型都不在 `OrderItem` 上）
    expect('productCode' in item).toBe(false)
    expect(orderItemSku(item).code).toBe('0012')
  })

  it('历史别名：`skuCode` 缺则回落 `productCode`（**列表行**用的就是这个键）', () => {
    const brief: OrderItemSkuSource = { productName: '布艺遮光帘A', productCode: 'LEGACY-9' }
    expect(orderItemSku(brief).code).toBe('LEGACY-9')
  })

  it('颜色只认 `processingInfo.colorName`（行级 `color` 已从类型里删除 —— 见 order-item-shape.test.ts）', () => {
    const source: OrderItemSkuSource = { productName: 'x', processingInfo: { colorName: '米白' } }
    expect(orderItemSku(source).color).toBe('米白')
  })

  it('门幅走 `craftSpecRows` 同一份格式化（`2.8` 与 `2.8米` 两种存量形态同值）', () => {
    expect(orderItemSku(buildItem({ processingInfo: { doorWidth: '2.8' } })).doorWidth).toBe('2.8米')
    expect(orderItemSku(buildItem({ processingInfo: { doorWidth: '2.8米' } })).doorWidth).toBe('2.8米')
  })

  it('`specRows` 排除「门幅」（它有自己的列）、**保留**「部位」（#4521 后只此一处可见）', () => {
    const labels = orderItemSku(buildItem()).specRows.map((row) => row.label)
    expect(labels).toContain('部位')
    expect(labels).toContain('工艺')
    expect(labels).not.toContain('门幅')
  })

  it('缺值 ⇒ 空串（纸面占位由各单据自己决定；绝不返回 undefined/null/NaN）', () => {
    const sku = orderItemSku({
      id: 'x',
      productName: '',
      quantity: 0,
      unitPrice: 0,
      amount: 0,
      subtotal: 0,
    } as OrderItem)
    expect(sku).toEqual({ name: '', code: '', color: '', doorWidth: '', specRows: [] })
    expect(JSON.stringify(sku)).not.toMatch(/undefined|null|NaN/)
  })

  it('无 `processingInfo` / 非对象 ⇒ 不抛错、`specRows` 为空（旧单没有工艺键）', () => {
    for (const bad of [undefined, null, 'not-an-object', [1, 2]] as unknown[]) {
      const sku = orderItemSku(buildItem({ processingInfo: bad as Record<string, unknown> }))
      expect(sku.specRows).toEqual([])
      expect(sku.doorWidth).toBe('')
    }
  })
})
