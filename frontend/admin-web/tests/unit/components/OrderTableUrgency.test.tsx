// case_ids: PR-079
//
// PR-079（issue #5177）：订单列表表格上的**加急徽标 + 到货日**。
//
// 两条口径：
//   ① 显示的是**服务端值**（`isUrgent` 缺省 = 库列 NOT NULL DEFAULT FALSE ⇒ 不加急）——
//      前端不做客户端默认、不编造；
//   ② `requiredDeliveryDate === null` ⇒ 「未指定」（不猜一个日期）。
//
// 反空断言（§15.1）：本文件同时钉**正反两态** —— 只断言「加急出现」的实现
// （比如永远渲染一个加急徽标）会在「不加急」那条上立刻红。
import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import OrderTable from '@/components/orders/OrderTable'
import type { Order } from '@/types'

const noop = () => {}

const order = (over: Partial<Order>): Order =>
  ({
    id: 'order-001',
    orderNo: 'MG-0001',
    status: 'pending_shipment',
    totalAmount: 299,
    actualAmount: 299,
    customerName: '测试客户',
    customerPhone: '13800000000',
    hasProcessing: false,
    createdAt: '2026-06-15T10:00:00Z',
    items: [],
    ...over,
  }) as Order

const renderTable = (orders: Order[]) =>
  render(
    <OrderTable
      orders={orders}
      loading={false}
      selectedIds={[]}
      onSelectChange={noop}
      onView={noop}
      onRemark={noop}
      onClose={noop}
      onShip={noop}
    />,
  )

describe('OrderTable · 加急 / 到货日（PR-079）', () => {
  it('表头有「加急」「到货日」两列（列表上看得见，不是只藏在详情页）', () => {
    renderTable([order({})])
    expect(screen.getByRole('columnheader', { name: '加急' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '到货日' })).toBeInTheDocument()
  })

  it('加急单：徽标显示「加急」+ 到货日按服务端值显示', () => {
    renderTable([
      order({ isUrgent: true, requiredDeliveryDate: '2026-09-30' }),
    ])

    const cell = screen.getByTestId('order-urgent-order-001')
    expect(cell).toHaveTextContent('加急')
    expect(screen.getByTestId('order-delivery-order-001')).toHaveTextContent('2026-09-30')
  })

  it('非加急（服务端 false ⇒ 库列缺省）：**不出现加急徽标**，到货日显示「未指定」', () => {
    renderTable([order({ isUrgent: false, requiredDeliveryDate: null })])

    const cell = screen.getByTestId('order-urgent-order-001')
    expect(cell).toHaveTextContent('不加急')
    // 🔴 反向断言（非空断言的关键）：非加急单上**不得**出现「加急」徽标
    // —— 「永远渲染一个加急徽标」的实现会在这里红
    expect(within(cell).queryByText('加急')).toBeNull()
    expect(cell.textContent).toBe('不加急')
    expect(screen.getByTestId('order-delivery-order-001')).toHaveTextContent('未指定')
  })

  it('字段整体缺席（老响应/未下发）⇒ 按库列缺省渲染「不加急 / 未指定」，不崩、不编造', () => {
    // `isUrgent` / `requiredDeliveryDate` 都不给 = 后端列缺省（NOT NULL DEFAULT FALSE / NULL）
    renderTable([order({})])

    expect(screen.getByTestId('order-urgent-order-001').textContent).toBe('不加急')
    expect(screen.getByTestId('order-delivery-order-001')).toHaveTextContent('未指定')
  })

  it('多单同屏：徽标逐单取自各自的 `isUrgent`（不是整表同一个值）', () => {
    renderTable([
      order({ id: 'o-a', orderNo: 'MG-A', isUrgent: true, requiredDeliveryDate: '2026-10-03' }),
      order({ id: 'o-b', orderNo: 'MG-B', isUrgent: false, requiredDeliveryDate: null }),
    ])

    expect(screen.getByTestId('order-urgent-o-a').textContent).toBe('加急')
    expect(screen.getByTestId('order-urgent-o-b').textContent).toBe('不加急')
    expect(screen.getByTestId('order-delivery-o-a')).toHaveTextContent('2026-10-03')
    expect(screen.getByTestId('order-delivery-o-b')).toHaveTextContent('未指定')
  })
})
