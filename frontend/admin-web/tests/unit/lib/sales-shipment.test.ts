// case_ids: UI-065
// @vitest-environment jsdom
/**
 * 销售单数量口径判定（issue #5651 收口）—— `resolveSalesQuantity` 的**四态**与缺值边界。
 *
 * 为什么这些判据要**单独**钉在 lib 上（而不是只测纸面）：
 * 「数量列印的是**实发**还是**下单数量**」是纸面与账目对得上的前提，而它的判定是**纯逻辑**
 * （跨多张发货单累加、发齐与否、挂不上订单行的行）—— 只测纸面会把逻辑错误藏在格式化后面：
 * 错误的口径**也能渲染出一个好看的数**（那正是「账实不符」在纸面上最危险的形态）。
 *
 * 四条判据（每条都有红证；红证机具 = `scripts/sales-doc-shipment-red-proof.py`）：
 * ① 四态各自可判（已发货 / 部分发货 / 未发货 / **读面没取到**）—— 后两者**必须不同**；
 * ② 未发 / 未知值 ⇒ `value === null`（纸面标「未发」或显式占位），**绝不填 0**；
 * ③ 实发跨**多张**发货单累加（补发场景）；
 * ④ 挂不到订单行的实发行 ⇒ 计入 `unmatchedShippedLines`（**显式**，不静默丢）。
 */
import { describe, it, expect } from 'vitest'
import {
  resolveSalesQuantity,
  SALES_QTY_BASIS,
  SALES_QTY_NOT_SHIPPED,
  SALES_QTY_STATES,
  type OrderShipmentRead,
} from '@/lib/sales-shipment'

const ITEMS = [
  { id: 'item-1', quantity: 3 },
  { id: 'item-2', quantity: 5 },
]

function read(
  shipments: { shipped_at?: string | null; items: { order_item_id?: string | null; shipped_quantity?: number | string | null; unit?: string }[] }[],
  status = 'shipped',
): OrderShipmentRead {
  return { order_id: 'order-1', status, shipments }
}

describe('resolveSalesQuantity（销售单数量口径 · issue #5651）', () => {
  it('① 未发货（一条实发明细都没有）⇒ 数量列 = 订单数量，且口径文案是「未发货」', () => {
    const r = resolveSalesQuantity(ITEMS, read([]))
    expect(r.state).toBe('not-shipped')
    expect(r.basisLabel).toBe(SALES_QTY_BASIS['not-shipped'])
    expect(r.cells.map((c) => c.basis)).toEqual(['ordered', 'ordered'])
    expect(r.cells.map((c) => c.value)).toEqual([3, 5])
  })

  it('① 已发货（每行都发齐）⇒ 数量列 = 实发数量（不是下单数量）', () => {
    const r = resolveSalesQuantity(ITEMS, read([
      { shipped_at: '2026-09-27T10:00:00+08:00', items: [
        { order_item_id: 'item-1', shipped_quantity: 3, unit: '米' },
        { order_item_id: 'item-2', shipped_quantity: 5, unit: '米' },
      ] },
    ]))
    expect(r.state).toBe('shipped')
    expect(r.cells.map((c) => c.basis)).toEqual(['shipped', 'shipped'])
    expect(r.cells.map((c) => c.value)).toEqual([3, 5])
    expect(r.basisLabel).toBe(SALES_QTY_BASIS.shipped)
  })

  it('① 部分发货（有一行没发）⇒ partial；未发行 value = null（纸面标「未发」）', () => {
    const r = resolveSalesQuantity(ITEMS, read([
      { shipped_at: '2026-09-27T10:00:00+08:00', items: [{ order_item_id: 'item-1', shipped_quantity: 3, unit: '米' }] },
    ]))
    expect(r.state).toBe('partial')
    expect(r.cells[0]).toEqual({ basis: 'shipped', value: 3 })
    expect(r.cells[1]).toEqual({ basis: 'shipped', value: null })
    // 🔴 null ≠ 0：0 会被读成「实发为零」，而这一行是「**没有**实发记录」
    expect(r.cells[1].value).not.toBe(0)
    expect(SALES_QTY_NOT_SHIPPED).toBe('未发')
  })

  it('① 少发（有实发但小于下单）⇒ partial（纸面据此可判「没发齐」）', () => {
    const r = resolveSalesQuantity(ITEMS, read([
      { shipped_at: '2026-09-27T10:00:00+08:00', items: [
        { order_item_id: 'item-1', shipped_quantity: 2, unit: '米' },
        { order_item_id: 'item-2', shipped_quantity: 5, unit: '米' },
      ] },
    ]))
    expect(r.state).toBe('partial')
    expect(r.cells[0].value).toBe(2)
  })

  it('① 读面没取到（null / undefined）⇒ **unavailable**，与「未发货」不是同一个态', () => {
    const nullRead = resolveSalesQuantity(ITEMS, null)
    const undefinedRead = resolveSalesQuantity(ITEMS, undefined)
    expect(nullRead.state).toBe('unavailable')
    expect(undefinedRead.state).toBe('unavailable')
    expect(nullRead.state).not.toBe('not-shipped')
    expect(nullRead.basisLabel).toBe(SALES_QTY_BASIS.unavailable)
    expect(nullRead.basisLabel).not.toBe(SALES_QTY_BASIS['not-shipped'])
    // 退回订单数量是对的（已标明），但它**不是**实发口径
    expect(nullRead.cells.map((c) => c.basis)).toEqual(['ordered', 'ordered'])
  })

  it('① 红证：把四态合并成一种显示 ⇒ 上面各组判据必红', () => {
    const labels = SALES_QTY_STATES.map((s) => SALES_QTY_BASIS[s])
    expect(new Set(labels).size).toBe(labels.length)
    const states = [
      resolveSalesQuantity(ITEMS, read([{ items: [{ order_item_id: 'item-1', shipped_quantity: 3 }, { order_item_id: 'item-2', shipped_quantity: 5 }] }])).state,
      resolveSalesQuantity(ITEMS, read([{ items: [{ order_item_id: 'item-1', shipped_quantity: 3 }] }])).state,
      resolveSalesQuantity(ITEMS, read([])).state,
      resolveSalesQuantity(ITEMS, null).state,
    ]
    expect(new Set(states).size).toBe(4) // 四种业务情形 ⇒ 四个**各自可判**的态
  })

  it('② 缺值不填 0：订单行数量缺失 ⇒ value = null（纸面显式占位），不是 0', () => {
    const rowsWithoutQuantity: { id: string; quantity?: number }[] = [{ id: 'item-1' }]
    const r = resolveSalesQuantity(rowsWithoutQuantity, read([]))
    expect(r.cells[0].value).toBeNull()
    expect(r.cells[0].value).not.toBe(0)
  })

  it('③ 补发（第二张发货单）⇒ 实发**累加**（不是只取最后一张）', () => {
    const r = resolveSalesQuantity(ITEMS, read([
      { shipped_at: '2026-09-26T10:00:00+08:00', items: [{ order_item_id: 'item-1', shipped_quantity: 1, unit: '米' }] },
      { shipped_at: '2026-09-27T10:00:00+08:00', items: [{ order_item_id: 'item-1', shipped_quantity: 2, unit: '米' }] },
    ]))
    expect(r.cells[0].value).toBe(3)
    expect(r.state).toBe('partial') // item-2 仍未发 ⇒ 整单没发齐
  })

  it('④ 挂不到订单行的实发行 ⇒ 计入 unmatchedShippedLines（不静默丢）', () => {
    const r = resolveSalesQuantity(ITEMS, read([
      { shipped_at: '2026-09-27T10:00:00+08:00', items: [
        { order_item_id: 'item-1', shipped_quantity: 3, unit: '米' },
        { order_item_id: null, shipped_quantity: 2, unit: '米' },
        { order_item_id: 'other-order-item', shipped_quantity: 1, unit: '米' },
      ] },
    ]))
    expect(r.unmatchedShippedLines).toBe(2)
  })

  it('④ 红证：把挂不上的行静默丢掉 ⇒ unmatched 变 0，上面那条必红', () => {
    const r = resolveSalesQuantity(ITEMS, read([
      { items: [{ order_item_id: null, shipped_quantity: 2, unit: '米' }] },
    ]))
    expect(r.unmatchedShippedLines).toBe(1)
    expect(r.unmatchedShippedLines).not.toBe(0)
  })

  it('边界：空订单行（无商品明细）⇒ 不抛错、不产生假行', () => {
    const r = resolveSalesQuantity([], read([]))
    expect(r.cells).toEqual([])
    expect(r.state).toBe('not-shipped')
    expect(resolveSalesQuantity(null, read([{ items: [{ order_item_id: 'x', shipped_quantity: 1 }] }])).unmatchedShippedLines).toBe(1)
  })
})
