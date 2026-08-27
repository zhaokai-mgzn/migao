import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// Mock useRouteId to return a valid customer ID
vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => 'cus-001',
}))

// Mock UI components — only the ones used by CustomerDetail
vi.mock('@/components/ui', () => ({
  Button: ({ children, onClick, loading, ...props }: any) => (
    <button onClick={onClick} disabled={loading} {...props}>{children}</button>
  ),
  StatusBadge: ({ label, color, dot, className, onClick }: any) => React.createElement('span', { onClick, className, title: label }, dot ? React.createElement('span', { className: 'w-1.5 h-1.5 rounded-full' }) : null, label),
  Badge: ({ children, variant }: any) => <span data-variant={variant}>{children}</span>,
}))

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: string) => ({
    format: (fmt: string) => {
      if (!date) return ''
      if (fmt === 'YYYY-MM-DD') return '2026-01-15'
      return '2026-04-20 14:30'
    },
  }),
}))

// Mock lucide-react — icons used by CustomerDetail
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    ArrowLeft: stub('arrow-left'),
    Phone: stub('phone'),
    MapPin: stub('map-pin'),
    Star: stub('star'),
    Plus: stub('plus'),
    X: stub('x'),
    MessageSquare: stub('message-square'),
    ShoppingCart: stub('shopping-cart'),
    StickyNote: stub('sticky-note'),
    Save: stub('save'),
  }
})

// Mock customerApi — 模拟后端真实响应（{ id, profile, tags, orders, sessions }）
vi.mock('@/lib/api', () => {
  const mockDetail = {
    id: 'cus-001',
    profile: {
      id: 'cus-001',
      wechatNickname: '张三',
      phone: '13800138000',
      sourceChannel: 'wechat_mini',
      vipLevel: 'vip1',
      agentNotes: '老客户，偏好遮光窗帘',
      lastActiveAt: '2026-04-20T14:30:00',
      registeredAt: '2026-01-15T10:00:00',
    },
    tags: [
      { id: 't1', name: 'VIP客户', color: '#EF4444' },
      { id: 't2', name: '窗帘定制', color: '#48618f' },
    ],
    orders: [
      { id: 'o1', orderNo: 'ORD20260415001', totalAmount: 2680, status: 'completed', createdAt: '2026-04-15T10:00:00' },
    ],
    sessions: [
      { id: 's1', lastMessage: '我想看看新款遮光窗帘', channel: 'wechat_mini', isAI: true, createdAt: '2026-04-20T14:30:00' },
    ],
  }
  const mockAllTags = [
    { id: 't1', name: 'VIP客户', color: '#EF4444' },
    { id: 't2', name: '窗帘定制', color: '#48618f' },
    { id: 't3', name: '需要跟进', color: '#F59E0B' },
  ]
  return {
    customerApi: {
      getCustomer: vi.fn().mockResolvedValue({ data: { data: mockDetail } }),
      getCustomerTags: vi.fn().mockResolvedValue({ data: { data: mockAllTags } }),
      addTagToCustomer: vi.fn().mockResolvedValue({ data: { success: true } }),
      removeTagFromCustomer: vi.fn().mockResolvedValue({ data: { success: true } }),
      updateCustomer: vi.fn().mockResolvedValue({ data: { success: true } }),
    },
  }
})

import CustomerDetailPage from '@/app/(dashboard)/customers/[id]/CustomerDetail'
import { customerApi } from '@/lib/api'

describe('CustomerDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading state initially', () => {
    render(<CustomerDetailPage />)
    expect(screen.getByText('加载中...')).toBeInTheDocument()
  })

  it('loads and displays real customer name from API (not hardcoded)', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(customerApi.getCustomer).toHaveBeenCalledWith('cus-001')
    })
    await waitFor(() => {
      expect(screen.getAllByText('张三').length).toBeGreaterThan(0)
    })
    // 硬编码的 mock 客户不应出现
    expect(screen.queryByText('张美丽')).not.toBeInTheDocument()
  })

  it('displays customer phone from API', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('13800138000')).toBeInTheDocument()
    })
  })

  it('displays linked tags from API', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('VIP客户')).toBeInTheDocument()
      expect(screen.getByText('窗帘定制')).toBeInTheDocument()
    })
  })

  it('displays tab bar with Orders, Sessions, Notes', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('订单历史')).toBeInTheDocument()
      expect(screen.getByText('会话历史')).toBeInTheDocument()
      expect(screen.getByText('跟进记录')).toBeInTheDocument()
    })
  })

  it('displays order list by default', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('ORD20260415001')).toBeInTheDocument()
    })
  })

  it('displays remark textarea', async () => {
    render(<CustomerDetailPage />)
    await waitFor(() => {
      const textarea = screen.getByPlaceholderText('添加客户备注...')
      expect(textarea).toBeInTheDocument()
    })
  })
})
