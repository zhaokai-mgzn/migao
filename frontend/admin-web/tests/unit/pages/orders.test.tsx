import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock API
const mockGetOrders = vi.fn()
const mockDeleteOrder = vi.fn()
const mockUpdateOrderStatus = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrders: (...args: any[]) => mockGetOrders(...args),
    deleteOrder: (...args: any[]) => mockDeleteOrder(...args),
    updateOrderStatus: (...args: any[]) => mockUpdateOrderStatus(...args),
  },
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock lucide-react
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    Plus: stub('plus'),
    Search: stub('search'),
    RotateCcw: stub('reset'),
    ChevronLeft: stub('chevron-left'),
    ChevronRight: stub('chevron-right'),
    ChevronUp: stub('chevron-up'),
    ChevronDown: stub('chevron-down'),
    Eye: stub('eye'),
    Trash2: stub('trash'),
  }
})

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: string) => ({
    format: (fmt: string) => date || '2026-04-25 10:00',
  }),
}))

// Mock OrderTable component
vi.mock('@/components/orders', () => ({
  OrderTable: ({ orders, loading, onStatusUpdate, onDelete }: any) => (
    <div data-testid="order-table">
      {loading && <div data-testid="table-loading">加载中...</div>}
      {!loading && orders.length === 0 && <div>暂无数据</div>}
      {orders.map((o: any) => (
        <div key={o.id} data-testid={`order-${o.id}`}>
          <span>{o.orderNo}</span>
          <span>{o.customerName}</span>
          <button onClick={() => onStatusUpdate(o)} data-testid={`status-${o.id}`}>更新状态</button>
          <button onClick={() => onDelete(o)} data-testid={`delete-${o.id}`}>删除</button>
        </div>
      ))}
    </div>
  ),
}))

// Mock UI components
vi.mock('@/components/ui', () => ({
  Pagination: ({ current, total, pageSize }: any) => (
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
}))

// Mock types
vi.mock('@/types', () => ({
  OrderStatusLabels: {
    pending: '待确认',
    confirmed: '已确认',
    producing: '生产中',
    shipped: '已发货',
    completed: '已完成',
    cancelled: '已取消',
  },
}))

import OrdersPage from '@/app/(dashboard)/orders/page'

const mockOrders = [
  { id: '1', orderNo: 'MG202600001', customerName: '张先生', status: 'pending', totalAmount: 1999, createdAt: '2026-04-25T10:00:00' },
  { id: '2', orderNo: 'MG202600002', customerName: '李女士', status: 'confirmed', totalAmount: 3500, createdAt: '2026-04-24T09:00:00' },
  { id: '3', orderNo: 'MG202600003', customerName: '王先生', status: 'completed', totalAmount: 899, createdAt: '2026-04-23T08:00:00' },
]

describe('OrdersPage', () => {
  const user = userEvent.setup()

  beforeEach(() => {
    vi.clearAllMocks()
    mockGetOrders.mockResolvedValue({
      data: { data: { items: mockOrders, total: 3 } },
    })
  })

  it('should render page title', () => {
    render(<OrdersPage />)
    expect(screen.getByText('订单管理')).toBeInTheDocument()
    expect(screen.getByText(/管理客户订单/)).toBeInTheDocument()
  })

  it('should render create order button', () => {
    render(<OrdersPage />)
    expect(screen.getByText('创建订单')).toBeInTheDocument()
  })

  it('should render status tab bar', () => {
    render(<OrdersPage />)
    // Use getAllByText for text that may appear in both tabs and dropdowns
    expect(screen.getAllByText('全部').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('待确认').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('已确认').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('生产中').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('已发货').length).toBeGreaterThanOrEqual(1)
  })

  it('should load and display orders', async () => {
    render(<OrdersPage />)
    await waitFor(() => {
      expect(mockGetOrders).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.getByTestId('order-1')).toBeInTheDocument()
      expect(screen.getByText('MG202600001')).toBeInTheDocument()
    })
  })

  it('should render search filters', () => {
    render(<OrdersPage />)
    expect(screen.getByText('关键词搜索')).toBeInTheDocument()
    expect(screen.getByText('状态筛选')).toBeInTheDocument()
  })

  it('should render pagination', async () => {
    render(<OrdersPage />)
    await waitFor(() => {
      expect(screen.getByTestId('pagination')).toBeInTheDocument()
    })
  })

  it('should open delete confirmation modal', async () => {
    render(<OrdersPage />)
    await waitFor(() => {
      expect(screen.getByTestId('order-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('delete-1'))
    expect(screen.getByTestId('modal')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('should open status update modal', async () => {
    render(<OrdersPage />)
    await waitFor(() => {
      expect(screen.getByTestId('order-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('status-1'))
    expect(screen.getByTestId('modal')).toBeInTheDocument()
    expect(screen.getByText('更新订单状态')).toBeInTheDocument()
  })

  it('should show reset and search buttons', () => {
    render(<OrdersPage />)
    expect(screen.getByText('重置')).toBeInTheDocument()
    expect(screen.getByText('搜索')).toBeInTheDocument()
  })

  it('should display customer names in order list', async () => {
    render(<OrdersPage />)
    await waitFor(() => {
      expect(screen.getByText('张先生')).toBeInTheDocument()
      expect(screen.getByText('李女士')).toBeInTheDocument()
    })
  })
})
