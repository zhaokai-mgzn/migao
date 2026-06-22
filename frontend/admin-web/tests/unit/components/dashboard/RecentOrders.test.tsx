import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

import RecentOrders from '@/components/dashboard/RecentOrders'
import type { Order } from '@/types'

const mockOrders: Order[] = [
  {
    id: '1',
    orderNo: 'ORDER-001',
    customerName: '张三',
    customerPhone: '13800138000',
    totalAmount: 299.0,
    actualAmount: 299.0,
    status: 'pending_payment',
    hasProcessing: false,
    createdAt: '2025-01-15T10:30:00Z',
  },
  {
    id: '2',
    orderNo: 'ORDER-002',
    customerName: '李四',
    customerPhone: '13900139000',
    totalAmount: 1250.5,
    actualAmount: 1250.5,
    status: 'completed',
    hasProcessing: false,
    createdAt: '2025-01-15T14:20:00Z',
  },
  {
    id: '3',
    orderNo: 'ORDER-003',
    customerName: '王五',
    customerPhone: '13700137000',
    totalAmount: 0,
    actualAmount: 0,
    status: 'closed',
    hasProcessing: false,
  },
]

describe('RecentOrders', () => {
  // --- Rendering basics ---
  it('renders the title "近期订单"', () => {
    render(<RecentOrders orders={[]} />)
    expect(screen.getByText('近期订单')).toBeInTheDocument()
  })

  it('renders "查看全部" link pointing to /orders', () => {
    render(<RecentOrders orders={mockOrders} />)
    const link = screen.getByText('查看全部')
    expect(link.closest('a')).toHaveAttribute('href', '/orders')
  })

  // --- Loading state ---
  it('shows loading spinner when loading=true', () => {
    render(<RecentOrders orders={[]} loading={true} />)
    expect(document.querySelector('.animate-spin')).toBeInTheDocument()
  })

  it('hides loading spinner when loading=false', () => {
    render(<RecentOrders orders={mockOrders} loading={false} />)
    expect(document.querySelector('.animate-spin')).not.toBeInTheDocument()
  })

  // --- Empty state ---
  it('shows "暂无订单数据" when orders is empty and not loading', () => {
    render(<RecentOrders orders={[]} />)
    expect(screen.getByText('暂无订单数据')).toBeInTheDocument()
  })

  it('does not show empty state when orders exist', () => {
    render(<RecentOrders orders={mockOrders} />)
    expect(screen.queryByText('暂无订单数据')).not.toBeInTheDocument()
  })

  // --- Table header ---
  it('renders table header with column labels', () => {
    render(<RecentOrders orders={mockOrders} />)
    expect(screen.getByText('订单号')).toBeInTheDocument()
    expect(screen.getByText('客户')).toBeInTheDocument()
    expect(screen.getByText('金额')).toBeInTheDocument()
    expect(screen.getByText('状态')).toBeInTheDocument()
    expect(screen.getByText('时间')).toBeInTheDocument()
  })

  // --- Order data rendering ---
  it('renders customer names', () => {
    render(<RecentOrders orders={mockOrders} />)
    expect(screen.getByText('张三')).toBeInTheDocument()
    expect(screen.getByText('李四')).toBeInTheDocument()
    expect(screen.getByText('王五')).toBeInTheDocument()
  })

  it('renders order numbers as links to order detail pages', () => {
    render(<RecentOrders orders={mockOrders} />)
    const link1 = screen.getByText('ORDER-001')
    expect(link1.closest('a')).toHaveAttribute('href', '/orders/1')

    const link2 = screen.getByText('ORDER-002')
    expect(link2.closest('a')).toHaveAttribute('href', '/orders/2')
  })

  // --- Amount formatting ---
  it('formats integer amount with two decimal places', () => {
    render(<RecentOrders orders={mockOrders} />)
    expect(screen.getByText('¥299.00')).toBeInTheDocument()
  })

  it('formats amount with thousands separator', () => {
    render(<RecentOrders orders={mockOrders} />)
    expect(screen.getByText('¥1,250.50')).toBeInTheDocument()
  })

  it('formats zero amount as ¥0.00', () => {
    render(<RecentOrders orders={mockOrders} />)
    expect(screen.getByText('¥0.00')).toBeInTheDocument()
  })

  // --- Status badges ---
  it('renders status badge for 待付款 (pending_payment)', () => {
    render(<RecentOrders orders={mockOrders} />)
    expect(screen.getByText('待付款')).toBeInTheDocument()
  })

  it('renders status badge for 已完成 (completed)', () => {
    render(<RecentOrders orders={mockOrders} />)
    expect(screen.getByText('已完成')).toBeInTheDocument()
  })

  it('renders status badge for 已关闭 (closed)', () => {
    render(<RecentOrders orders={mockOrders} />)
    expect(screen.getByText('已关闭')).toBeInTheDocument()
  })

  // --- Time formatting ---
  it('renders formatted time with MM-DD pattern', () => {
    render(<RecentOrders orders={mockOrders} />)
    // Two orders have 01-15 date, so use getAllByText
    const dateMatches = screen.getAllByText(/01-15/)
    expect(dateMatches.length).toBe(2)
  })

  it('renders "--" for missing createdAt', () => {
    render(<RecentOrders orders={mockOrders} />)
    // ORDER-003 has no createdAt
    expect(screen.getByText('--')).toBeInTheDocument()
  })
})
