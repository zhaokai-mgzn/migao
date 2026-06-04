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
    RefreshCw: stub('refresh-cw'),
    Calendar: stub('calendar'),
  }
})

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: string) => ({
    format: (fmt: string) => date || '2026-04-25 10:00',
    subtract: (amount: number, unit: string) => ({
      format: (fmt: string) => '2026-04-19',
    }),
  }),
}))

// Mock OrderTable component
vi.mock('@/components/orders', () => ({
  OrderTable: ({ orders, loading, onView, onClose, onRemark }: any) => (
    <div data-testid="order-table">
      {loading && <div data-testid="table-loading">加载中...</div>}
      {!loading && orders.length === 0 && <div>暂无数据</div>}
      {orders.map((o: any) => (
        <div key={o.id} data-testid={`order-${o.id}`}>
          <span>{o.orderNo}</span>
          <span>{o.customerName}</span>
          <button onClick={() => onView(o)} data-testid={`view-${o.id}`}>查看</button>
          <button onClick={() => onClose(o)} data-testid={`close-${o.id}`}>关闭</button>
        </div>
      ))}
    </div>
  ),
  CloseOrderModal: ({ open, onClose, onConfirm }: any) => (
    open ? <div data-testid="modal" role="dialog"><button onClick={() => onConfirm('缺货')}>确认关闭</button></div> : null
  ),
  RemarkModal: ({ open, onClose, onConfirm }: any) => (
    open ? <div data-testid="remark-modal" role="dialog"><button onClick={() => onConfirm('备注内容')}>确认备注</button></div> : null
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
  FrontendToBackendStatus: {
    pending_payment: 'pending',
    pending_shipment: 'confirmed',
    shipped: 'shipped',
    completed: 'completed',
    closed: 'cancelled',
  },
  OrderStatusTabs: [
    { key: 'all', label: '全部' },
    { key: 'pending_payment', label: '待付款' },
    { key: 'pending_shipment', label: '待发货' },
    { key: 'shipped', label: '已发货' },
    { key: 'completed', label: '已完成' },
    { key: 'processing', label: '含加工订单' },
    { key: 'closed', label: '已关闭' },
    { key: 'refund', label: '退款/售后' },
  ],
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
    expect(screen.getByText('订单列表')).toBeInTheDocument()
  })

  it('should render create order button', () => {
    render(<OrdersPage />)
    expect(screen.getByText('新增订单')).toBeInTheDocument()
  })

  it('should render status tab bar', () => {
    render(<OrdersPage />)
    expect(screen.getAllByText('全部').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('待付款').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('待发货').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('已发货').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('已完成').length).toBeGreaterThanOrEqual(1)
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
    expect(screen.getByPlaceholderText('请输入订单ID')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('请输入收货人姓名或手机号')).toBeInTheDocument()
  })

  it('should render pagination', async () => {
    render(<OrdersPage />)
    await waitFor(() => {
      // 页面使用内联分页按钮（‹ / ›），不使用 Pagination 组件
      expect(screen.getByText('‹')).toBeInTheDocument()
      expect(screen.getByText('›')).toBeInTheDocument()
    })
  })

  it('should open close order modal', async () => {
    render(<OrdersPage />)
    await waitFor(() => {
      expect(screen.getByTestId('order-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('close-1'))
    expect(screen.getByTestId('modal')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('should open view order detail', async () => {
    render(<OrdersPage />)
    await waitFor(() => {
      expect(screen.getByTestId('order-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('view-1'))
    // onView should trigger router navigation
  })

  it('should show reset and search buttons', () => {
    render(<OrdersPage />)
    expect(screen.getByText('重置')).toBeInTheDocument()
    expect(screen.getByText('查询')).toBeInTheDocument()
  })

  it('should display customer names in order list', async () => {
    render(<OrdersPage />)
    await waitFor(() => {
      expect(screen.getByText('张先生')).toBeInTheDocument()
      expect(screen.getByText('李女士')).toBeInTheDocument()
    })
  })
})
