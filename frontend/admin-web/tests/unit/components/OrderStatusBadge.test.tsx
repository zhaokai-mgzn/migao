// @vitest-environment jsdom
// case_ids: UI-002
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

  it('renders pending_payment with amber (warning) styles', () => {
    render(<OrderStatusBadge status="pending_payment" />)
    const badge = screen.getByText('待付款')
    expect(badge.className).toContain('bg-amber-50')
  })

  it('renders shipped with primary (info) chip, not legacy indigo', () => {
    render(<OrderStatusBadge status="shipped" />)
    const badge = screen.getByText('已发货')
    expect(badge.className).toContain('bg-primary-50')
    expect(badge.className).not.toContain('bg-indigo-50')
    expect(badge.className).not.toContain('text-indigo-')
  })

  it('renders closed with neutral chip, not legacy gray', () => {
    render(<OrderStatusBadge status="closed" />)
    const badge = screen.getByText('已关闭')
    expect(badge.className).toContain('bg-neutral-100')
    expect(badge.className).not.toContain('bg-gray-50')
  })

  it('renders completed with emerald (success) chip', () => {
    render(<OrderStatusBadge status="completed" />)
    const badge = screen.getByText('已完成')
    expect(badge.className).toContain('bg-emerald-50')
  })

  it('never renders legacy blue/indigo/green/gray color classes', () => {
    render(<OrderStatusBadge status="pending_shipment" />)
    const badge = screen.getByText('待发货')
    expect(badge.className).not.toContain('bg-blue-')
    expect(badge.className).not.toContain('bg-indigo-')
    expect(badge.className).not.toContain('text-indigo-')
    expect(badge.className).not.toContain('bg-green-')
    expect(badge.className).not.toContain('bg-gray-')
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
