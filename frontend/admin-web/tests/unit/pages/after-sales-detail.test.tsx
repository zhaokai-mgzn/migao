import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// Mock API
const mockGetTicket = vi.fn()

vi.mock('@/lib/api', () => ({
  afterSalesApi: {
    getTicket: (...args: any[]) => mockGetTicket(...args),
    updateTicketStatus: vi.fn(),
  },
}))

// Mock useRouteId
vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => 'ticket-001',
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock sonner
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: string) => ({
    format: () => date || '2026-06-20 10:00',
  }),
}))

// Mock next/image
vi.mock('next/image', () => ({
  default: (props: any) => <img {...props} />,
}))

// Mock UI components
vi.mock('@/components/ui', () => ({
  Button: ({ children, onClick, ...props }: any) => (
    <button onClick={onClick} {...props}>{children}</button>
  ),
  Card: ({ children, className }: any) => <div className={className}>{children}</div>,
  Loading: ({ text }: any) => <div>{text}</div>,
  Modal: ({ open, title, children, footer }: any) =>
    open ? (
      <div data-testid="modal" role="dialog">
        <h2>{title}</h2>
        {children}
        <div data-testid="modal-footer">{footer}</div>
      </div>
    ) : null,
  Badge: ({ children, variant }: any) => (
    <span data-testid="badge" data-variant={variant}>{children}</span>
  ),
}))

// Mock types
vi.mock('@/types', () => ({
  AfterSalesStatusLabels: {
    pending: '待处理',
    processing: '处理中',
    resolved: '已解决',
    rejected: '已拒绝',
    closed: '已关闭',
  },
  AfterSalesTypeLabels: {
    refund: '退款',
    exchange: '换货',
    complaint: '投诉',
  },
  AfterSalesPriorityLabels: {
    normal: '普通',
    urgent: '紧急',
    critical: '严重',
  },
}))

import AfterSalesDetailPage from '@/app/(dashboard)/after-sales/[id]/AfterSalesDetail'

const mockTicket = {
  id: 'ticket-001',
  ticketNo: 'AS202606001',
  ticketType: 'refund' as const,
  status: 'pending' as const,
  priority: 'normal' as const,
  description: '测试售后描述',
  orderId: 'order-001',
  orderNo: 'MG202606001',
  customerName: '测试客户',
  customerPhone: '13800138000',
  createdAt: '2026-06-20T10:00:00Z',
  statusHistory: [
    {
      status: 'pending' as const,
      time: '2026-06-20T10:00:00Z',
      operator: '系统',
      remark: '客户提交售后申请',
    },
  ],
}

describe('AfterSalesDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetTicket.mockResolvedValue({
      data: { data: mockTicket },
    })
  })

  it('should show loading state initially', () => {
    render(<AfterSalesDetailPage />)
    expect(screen.getByText('加载工单详情...')).toBeInTheDocument()
  })

  it('should render page title after loading', async () => {
    render(<AfterSalesDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('工单详情')).toBeInTheDocument()
    })
  })

  it('should display ticket number', async () => {
    render(<AfterSalesDetailPage />)
    await waitFor(() => {
      expect(screen.getByText(/AS202606001/)).toBeInTheDocument()
    })
  })

  it('should render ticket info section', async () => {
    render(<AfterSalesDetailPage />)
    // 工单信息在页面左右两侧各出现一次
    const ticketInfos = await screen.findAllByText('工单信息')
    expect(ticketInfos.length).toBeGreaterThanOrEqual(1)
  })

  it('should render customer info section', async () => {
    render(<AfterSalesDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('客户信息')).toBeInTheDocument()
      expect(screen.getByText('测试客户')).toBeInTheDocument()
    })
  })

  it('should render linked order section', async () => {
    render(<AfterSalesDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('关联订单')).toBeInTheDocument()
    })
  })

  it('should render status action buttons for pending ticket', async () => {
    render(<AfterSalesDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('接受处理')).toBeInTheDocument()
      expect(screen.getByText('拒绝')).toBeInTheDocument()
    })
  })

  it('should render timeline section', async () => {
    render(<AfterSalesDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('处理时间线')).toBeInTheDocument()
    })
  })

  it('should show empty state when ticket not found', async () => {
    mockGetTicket.mockResolvedValue({ data: { data: null } })
    render(<AfterSalesDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('工单不存在或已被删除')).toBeInTheDocument()
    })
  })
})
