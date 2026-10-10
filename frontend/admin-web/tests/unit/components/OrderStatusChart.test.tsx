// case_ids: DA-005, DA-006, UI-003
/**
 * 订单状态分布组件的三态（issue #6715）—— **实例判据**（组件层）。
 *
 * ## 病灶
 *
 * `total = data.reduce((sum, item) => sum + item.count, 0)`，而 `data` 是调用方的
 * `useState([])` 初值 ⇒ 读面失败时把「**读不到**」印成**事实性断言**「共 0 单」
 * （健康基线是「共 308 单」）。加 `data-testid="order-status-count"` 是为了让
 * 「计数位在不在屏上」可被判据直接问（此前只能按 `SPAN.text-xs.text-neutral-400` 认）。
 *
 * ## 三条（每条都能单独红）
 *
 * ① 读成功且真为 0 单 ⇒ 印「共 0 单」（**反向对照**：真 0 是事实，不许被当成失败态吃掉）；
 * ② 读成功有数据 ⇒ 印真合计（`3 + 4 = 7`）；
 * ③ 读失败（`readFailed`）⇒ **不渲染计数位**，改印「订单状态分布没读到」（与失败横幅同一口径）。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import OrderStatusChart from '@/components/dashboard/OrderStatusChart'
import type { OrderStatusDistribution } from '@/types'

const rows: OrderStatusDistribution[] = [
  { status: 'pending_payment', label: '待支付', count: 3, color: '#f59e0b' },
  { status: 'pending_shipment', label: '待发货', count: 4, color: '#48618f' },
]

describe('OrderStatusChart（issue #6715）', () => {
  it('读成功且**真为 0 单** ⇒ 照旧印「共 0 单」（反向对照：真 0 是事实）', () => {
    render(<OrderStatusChart data={[]} loading={false} />)
    expect(screen.getByTestId('order-status-count')).toHaveTextContent('共 0 单')
    expect(screen.queryByTestId('order-status-read-failed')).toBeNull()
  })

  it('读成功有数据 ⇒ 印真合计（合计由每行 count 派生：3 + 4 = 7）', () => {
    render(<OrderStatusChart data={rows} loading={false} />)
    expect(screen.getByTestId('order-status-count')).toHaveTextContent('共 7 单')
  })

  it('读失败（readFailed）⇒ **不渲染计数位**，改印「没读到」（不印 0，也不印空态）', () => {
    render(<OrderStatusChart data={[]} loading={false} readFailed />)
    expect(screen.queryByTestId('order-status-count')).toBeNull()
    expect(screen.getByTestId('order-status-read-failed')).toHaveTextContent('订单状态分布没读到')
    // 屏上任何位置都不该出现「共 0 单」（改前的形态）
    expect(document.body.textContent ?? '').not.toMatch(/共\s*0\s*单/)
    expect(document.body.textContent ?? '').not.toContain('暂无')
  })
})
