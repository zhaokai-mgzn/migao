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

import CustomerDetailPage from '@/app/(dashboard)/customers/[id]/CustomerDetail'

describe('CustomerDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading state initially', () => {
    render(<CustomerDetailPage />)
    expect(screen.getByText('加载中...')).toBeInTheDocument()
  })

  it('loads and displays customer name after mock data loads', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<CustomerDetailPage />)
    // Fast-forward past the 500ms setTimeout in loadCustomer
    vi.advanceTimersByTime(600)
    await vi.runAllTimersAsync()

    await waitFor(() => {
      expect(screen.getByText('张美丽')).toBeInTheDocument()
    })
    vi.useRealTimers()
  })

  it('displays customer phone after loading', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<CustomerDetailPage />)
    vi.advanceTimersByTime(600)
    await vi.runAllTimersAsync()

    await waitFor(() => {
      expect(screen.getByText('13812341234')).toBeInTheDocument()
    })
    vi.useRealTimers()
  })

  it('displays tab bar with Orders, Sessions, Notes', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<CustomerDetailPage />)
    vi.advanceTimersByTime(600)
    await vi.runAllTimersAsync()

    await waitFor(() => {
      expect(screen.getByText('订单历史')).toBeInTheDocument()
      expect(screen.getByText('会话历史')).toBeInTheDocument()
      expect(screen.getByText('跟进记录')).toBeInTheDocument()
    })
    vi.useRealTimers()
  })

  it('displays order list by default', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<CustomerDetailPage />)
    vi.advanceTimersByTime(600)
    await vi.runAllTimersAsync()

    await waitFor(() => {
      expect(screen.getByText('ORD20260415001')).toBeInTheDocument()
    })
    vi.useRealTimers()
  })

  it('displays remark textarea', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<CustomerDetailPage />)
    vi.advanceTimersByTime(600)
    await vi.runAllTimersAsync()

    await waitFor(() => {
      const textarea = screen.getByPlaceholderText('添加客户备注...')
      expect(textarea).toBeInTheDocument()
    })
    vi.useRealTimers()
  })
})
