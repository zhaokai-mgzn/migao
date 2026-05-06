import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock API
const mockGetTickets = vi.fn()
const mockGetOrders = vi.fn()
const mockCreateTicket = vi.fn()

vi.mock('@/lib/api', () => ({
  afterSalesApi: {
    getTickets: (...args: any[]) => mockGetTickets(...args),
    createTicket: (...args: any[]) => mockCreateTicket(...args),
  },
  orderApi: {
    getOrders: (...args: any[]) => mockGetOrders(...args),
  },
}))

// Mock lucide-react
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    Plus: stub('plus'),
    Search: stub('search'),
    RotateCcw: stub('reset'),
    FileText: stub('filetext'),
    ExternalLink: stub('external'),
    ChevronLeft: stub('chevron-left'),
    ChevronRight: stub('chevron-right'),
  }
})

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: string) => ({
    format: (fmt: string) => date || '2026-04-25 10:00',
  }),
}))

// Mock types
vi.mock('@/types', () => ({
  AfterSalesStatusLabels: {
    pending: '待处理',
    processing: '处理中',
    resolved: '已完成',
    rejected: '已拒绝',
    closed: '已关闭',
  },
  AfterSalesStatusColors: {},
  AfterSalesTypeLabels: {
    return: '退货',
    exchange: '换货',
    repair: '维修',
    refund: '退款',
    complaint: '投诉',
    other: '其他',
  },
  AfterSalesPriorityLabels: {
    normal: '普通',
    urgent: '紧急',
    critical: '严重',
  },
}))

// Mock UI components
vi.mock('@/components/ui', () => ({
  Pagination: ({ current, total }: any) => (
    <div data-testid="pagination">第 {current} 页, 共 {total} 条</div>
  ),
  Modal: ({ open, onClose, title, children, footer }: any) => (
    open ? (
      <div data-testid="modal" role="dialog">
        <h2>{title}</h2>
        {children}
        <div data-testid="modal-footer">{footer}</div>
      </div>
    ) : null
  ),
  Button: ({ children, onClick, ...props }: any) => <button onClick={onClick} {...props}>{children}</button>,
  Input: ({ label, value, onChange, onKeyDown, ...props }: any) => (
    <div>
      <label htmlFor={`input-${label}`}>{label}</label>
      <input id={`input-${label}`} value={value} onChange={onChange} onKeyDown={onKeyDown} {...props} />
    </div>
  ),
  Select: ({ label, options, value, onChange }: any) => (
    <div>
      <label>{label}</label>
      <select value={value} onChange={onChange}>
        {options?.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  ),
  Badge: ({ children, variant }: any) => <span data-testid="badge" data-variant={variant}>{children}</span>,
}))

import AfterSalesPage from '@/app/(dashboard)/after-sales/page'

const mockTickets = [
  {
    id: 'as1', ticketNo: 'AS20260001', orderNo: 'MG202600001',
    customerName: '张先生', ticketType: 'return', status: 'pending',
    priority: 'normal', createdAt: '2026-04-25T10:00:00', updatedAt: '2026-04-25T10:00:00',
  },
  {
    id: 'as2', ticketNo: 'AS20260002', orderNo: 'MG202600002',
    customerName: '李女士', ticketType: 'refund', status: 'processing',
    priority: 'urgent', createdAt: '2026-04-24T09:00:00', updatedAt: '2026-04-24T12:00:00',
  },
]

describe('AfterSalesPage', () => {
  const user = userEvent.setup()

  beforeEach(() => {
    vi.clearAllMocks()
    mockGetTickets.mockResolvedValue({
      data: { data: { items: mockTickets, total: 2 } },
    })
  })

  it('should render page title', () => {
    render(<AfterSalesPage />)
    expect(screen.getByText('售后管理')).toBeInTheDocument()
    expect(screen.getByText(/管理客户售后工单/)).toBeInTheDocument()
  })

  it('should render create ticket button', () => {
    render(<AfterSalesPage />)
    expect(screen.getByText('新建工单')).toBeInTheDocument()
  })

  it('should render status tab bar', () => {
    render(<AfterSalesPage />)
    // Use getAllByText for duplicated labels in tabs and dropdowns
    expect(screen.getAllByText('全部').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('待处理').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('处理中').length).toBeGreaterThanOrEqual(1)
  })

  it('should load and display tickets', async () => {
    render(<AfterSalesPage />)
    await waitFor(() => {
      expect(mockGetTickets).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.getByText('AS20260001')).toBeInTheDocument()
      expect(screen.getByText('张先生')).toBeInTheDocument()
    })
  })

  it('should render search filters', () => {
    render(<AfterSalesPage />)
    expect(screen.getByText('关键词搜索')).toBeInTheDocument()
    expect(screen.getByText('状态筛选')).toBeInTheDocument()
  })

  it('should render reset and search buttons', () => {
    render(<AfterSalesPage />)
    expect(screen.getByText('重置')).toBeInTheDocument()
    expect(screen.getByText('搜索')).toBeInTheDocument()
  })

  it('should show empty state when no tickets', async () => {
    mockGetTickets.mockResolvedValue({
      data: { data: { items: [], total: 0 } },
    })
    render(<AfterSalesPage />)
    await waitFor(() => {
      expect(screen.getByText('暂无售后工单')).toBeInTheDocument()
    })
  })

  it('should open create ticket modal', async () => {
    render(<AfterSalesPage />)
    await user.click(screen.getByText('新建工单'))
    expect(screen.getByTestId('modal')).toBeInTheDocument()
    expect(screen.getByText('新建售后工单')).toBeInTheDocument()
  })

  it('should display ticket type badges', async () => {
    render(<AfterSalesPage />)
    await waitFor(() => {
      expect(screen.getByText('退货')).toBeInTheDocument()
      expect(screen.getByText('退款')).toBeInTheDocument()
    })
  })

  it('should render pagination', async () => {
    render(<AfterSalesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('pagination')).toBeInTheDocument()
    })
  })
})
