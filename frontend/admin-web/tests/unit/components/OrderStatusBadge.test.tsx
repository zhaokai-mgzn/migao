// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import OrderStatusBadge from '@/components/orders/OrderStatusBadge'
import type { OrderStatus } from '@/types'

describe('OrderStatusBadge Component', () => {
  const allStatuses: OrderStatus[] = [
    'pending_payment',
    'pending_shipment',
    'shipped',
    'completed',
    'closed',
    'refund',
  ]

  const expectedLabels: Record<OrderStatus, string> = {
    pending_payment: '待付款',
    pending_shipment: '待发货',
    shipped: '已发货',
    completed: '已完成',
    closed: '已关闭',
    refund: '退款/售后',
  }

  it.each(allStatuses)('renders correct Chinese label for status %s', (status) => {
    render(<OrderStatusBadge status={status} />)
    expect(screen.getByText(expectedLabels[status])).toBeInTheDocument()
  })

  it.each(allStatuses)('renders colored dot for status %s', (status) => {
    render(<OrderStatusBadge status={status} />)
    const dot = document.querySelector('.rounded-full')
    expect(dot).toBeInTheDocument()
    expect(dot?.className).toContain('w-1.5')
    expect(dot?.className).toContain('h-1.5')
  })

  it('renders pending_payment with amber styles', () => {
    render(<OrderStatusBadge status="pending_payment" />)
    const badge = screen.getByText('待付款')
    expect(badge.className).toContain('bg-amber-50')
    expect(badge.className).toContain('text-amber-700')
  })

  it('renders shipped with indigo styles', () => {
    render(<OrderStatusBadge status="shipped" />)
    const badge = screen.getByText('已发货')
    expect(badge.className).toContain('bg-indigo-50')
    expect(badge.className).toContain('text-indigo-700')
  })

  it('renders completed with green styles', () => {
    render(<OrderStatusBadge status="completed" />)
    const badge = screen.getByText('已完成')
    expect(badge.className).toContain('bg-green-50')
    expect(badge.className).toContain('text-green-700')
  })

  it('calls onClick when clicked', () => {
    const onClick = vi.fn()
    render(<OrderStatusBadge status="pending_payment" onClick={onClick} />)
    fireEvent.click(screen.getByText('待付款'))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('has cursor-pointer when onClick is provided', () => {
    render(<OrderStatusBadge status="pending_payment" onClick={vi.fn()} />)
    const badge = screen.getByText('待付款')
    expect(badge.className).toContain('cursor-pointer')
  })

  it('does not have cursor-pointer when no onClick', () => {
    render(<OrderStatusBadge status="pending_payment" />)
    const badge = screen.getByText('待付款')
    expect(badge.className).not.toContain('cursor-pointer')
  })

  it('merges className', () => {
    render(<OrderStatusBadge status="completed" className="extra-class" />)
    expect(screen.getByText('已完成').className).toContain('extra-class')
  })
})
