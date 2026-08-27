// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock OrderTable 的子依赖
vi.mock('@/components/common/DateTimeCell', () => ({
  default: () => <span>date-cell</span>,
}))
vi.mock('@/components/orders/OrderStatusBadge', () => ({
  default: () => <span>status-badge</span>,
}))
vi.mock('@/components/orders/RemarkPopover', () => ({
  default: ({ children }: any) => <span>{children}</span>,
}))

import OrderTable from '@/components/orders/OrderTable'
import type { Order } from '@/types'

// 列表接口返回后端状态值（confirmed/producing/pending/cancelled），与前端 OrderStatus 不同
type OrderOverrides = Omit<Partial<Order>, 'status'> & { status?: string }

const BASE_ORDER: Omit<Order, 'status'> = {
  id: 'o1',
  orderNo: 'MG202600001',
  customerName: '张三',
  customerPhone: '13800000000',
  totalAmount: 1000,
  actualAmount: 1000,
  hasProcessing: false,
  createdAt: '2026-06-20T10:00:00Z',
}

function makeOrder(overrides: OrderOverrides = {}): Order {
  return { ...BASE_ORDER, status: 'completed', ...overrides } as Order
}

function renderTable(orders: Order[], onRefund: ((o: Order) => void) | undefined = vi.fn()) {
  return render(
    <OrderTable
      orders={orders}
      loading={false}
      selectedIds={[]}
      onSelectChange={vi.fn()}
      onView={vi.fn()}
      onRemark={vi.fn()}
      onClose={vi.fn()}
      onShip={vi.fn()}
      onRefund={onRefund}
      onConfirmPayment={vi.fn()}
      onConfirmReceive={vi.fn()}
    />
  )
}

describe('OrderTable 退款按钮（基于真实状态 + refundAmount）', () => {
  it('confirmed 订单（未退款）显示 处理退款 按钮', () => {
    renderTable([makeOrder({ status: 'confirmed', refundAmount: 0 })])
    expect(screen.getByText('处理退款')).toBeInTheDocument()
  })

  it('producing 订单（未退款）显示 处理退款 按钮', () => {
    renderTable([makeOrder({ status: 'producing', refundAmount: 0 })])
    expect(screen.getByText('处理退款')).toBeInTheDocument()
  })

  it('shipped 订单（未退款）显示 处理退款 按钮', () => {
    renderTable([makeOrder({ status: 'shipped', refundAmount: 0 })])
    expect(screen.getByText('处理退款')).toBeInTheDocument()
  })

  it('completed 订单（未退款）显示 处理退款 按钮', () => {
    renderTable([makeOrder({ status: 'completed', refundAmount: 0 })])
    expect(screen.getByText('处理退款')).toBeInTheDocument()
  })

  it('已退款订单（refundAmount > 0）不显示 处理退款 按钮', () => {
    renderTable([makeOrder({ status: 'completed', refundAmount: 100 })])
    expect(screen.queryByText('处理退款')).not.toBeInTheDocument()
  })

  it('pending（待付款）订单不显示 处理退款 按钮', () => {
    renderTable([makeOrder({ status: 'pending', refundAmount: 0 })])
    expect(screen.queryByText('处理退款')).not.toBeInTheDocument()
  })

  it('cancelled（已关闭）订单不显示 处理退款 按钮', () => {
    renderTable([makeOrder({ status: 'cancelled', refundAmount: 0 })])
    expect(screen.queryByText('处理退款')).not.toBeInTheDocument()
  })

  it('未传 onRefund 时不渲染 处理退款 按钮', () => {
    // 直接渲染不传 onRefund prop（区别于默认 vi.fn()）
    const order = makeOrder({ status: 'completed', refundAmount: 0 })
    render(
      <OrderTable
        orders={[order]}
        loading={false}
        selectedIds={[]}
        onSelectChange={vi.fn()}
        onView={vi.fn()}
        onRemark={vi.fn()}
        onClose={vi.fn()}
        onShip={vi.fn()}
        onConfirmPayment={vi.fn()}
        onConfirmReceive={vi.fn()}
      />
    )
    expect(screen.queryByText('处理退款')).not.toBeInTheDocument()
  })

  it('点击 处理退款 调用 onRefund(order)', async () => {
    const user = userEvent.setup()
    const onRefund = vi.fn()
    const order = makeOrder({ status: 'completed', refundAmount: 0 })
    renderTable([order], onRefund)
    await user.click(screen.getByText('处理退款'))
    expect(onRefund).toHaveBeenCalledWith(order)
  })
})
