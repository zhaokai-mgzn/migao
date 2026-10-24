// case_ids: UI-120
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import ProductionProgressTable from '@/components/production/ProductionProgressTable'
import type { ProductionPosition } from '@/types'

/**
 * 工序进度表的三态数量列（**合格 / 返工 / 报废**）—— issue #7140 = #5652 的商家面。
 *
 * ## 这三列为什么必须存在
 *
 * issue #5652 的商家面验收逐字要求「商家端能看到 `rework_qty` / `scrap_qty`（前端有真实消费者）」，
 * 而当时只落了服务端与工人端 ⇒ 商家在观星台上看不到「返工了多少、报废了多少」，
 * 只有问米宝才看得到（agent 读面）。本文件钉住这三列**真的在屏上**。
 *
 * ## 口径（不得改写）
 *
 * - 三列各自独立：**合格 ≠ 已完成**（`done_qty` 是进度列，合格/返工/报废是**报工三态**的数量）；
 * - 返工 / 报废**既不推进进度也不计件**（既有口径）⇒ 本表不为它们做任何合计（避免被读成
 *   「已完成 = 合格 + 返工 + 报废」）；
 * - 缺报工 ⇒ 服务端给 0 ⇒ 渲染 `0`（「没有这一笔」是真事实），**不是**空白、也不是 `undefined`；
 * - 单位随列显示（与服务端下发的 `unit` 同源），不去猜。
 */
const positions: ProductionPosition[] = [
  {
    position_name: '布帘',
    order_item_id: 'item-1',
    product_name: '布艺遮光帘A',
    operations: [
      {
        id: 'op-1',
        seq: 1,
        operation: '精裁-布',
        logical_name: '精裁',
        position: '布帘',
        group: '裁剪',
        unit: '套',
        qty: 10,
        unit_price: 8,
        status: 'done',
        done_qty: 10,
        qualified_qty: 7,
        rework_qty: 2,
        scrap_qty: 1,
        workers: ['王秀兰'],
      },
      {
        id: 'op-2',
        seq: 2,
        operation: '车缝-布',
        logical_name: '车缝',
        position: '布帘',
        group: '车位',
        unit: '套',
        qty: 4,
        unit_price: 5,
        status: 'pending',
        done_qty: 0,
        workers: [],
      },
    ],
  },
]

describe('工序进度表 · 合格 / 返工 / 报废 三列', () => {
  it('① 表头三列都在（合格 / 返工 / 报废）', () => {
    render(<ProductionProgressTable positions={positions} />)

    expect(screen.getByText('合格')).toBeInTheDocument()
    expect(screen.getByText('返工')).toBeInTheDocument()
    expect(screen.getByText('报废')).toBeInTheDocument()
  })

  it('② 逐工序渲染服务端下发的三态数量（含单位），缺报工 ⇒ 0（不是空白 / undefined）', () => {
    render(<ProductionProgressTable positions={positions} />)

    const rows = screen.getAllByTestId(/^operation-row-/)
    expect(rows).toHaveLength(2)

    const first = rows[0]
    expect(first.querySelector('[data-testid="op-qualified"]')?.textContent).toBe('7 套')
    expect(first.querySelector('[data-testid="op-rework"]')?.textContent).toBe('2 套')
    expect(first.querySelector('[data-testid="op-scrap"]')?.textContent).toBe('1 套')

    // 第二道零报工：三列都是 0（服务端给的值），且**不是** undefined / 空白
    const second = rows[1]
    expect(second.querySelector('[data-testid="op-qualified"]')?.textContent).toBe('0 套')
    expect(second.querySelector('[data-testid="op-rework"]')?.textContent).toBe('0')
    expect(second.querySelector('[data-testid="op-scrap"]')?.textContent).toBe('0')
  })

  it('③ 合格列与「已完成数量」是两列（返工/报废不参与进度）', () => {
    render(<ProductionProgressTable positions={positions} />)

    const first = screen.getAllByTestId(/^operation-row-/)[0]
    // 已完成 = 10（进度口径），合格 = 7（报工三态口径）—— 两者故意不等
    expect(first.querySelector('[data-testid="op-done"]')?.textContent).toBe('10 套')
    expect(first.querySelector('[data-testid="op-qualified"]')?.textContent).toBe('7 套')
  })
})
