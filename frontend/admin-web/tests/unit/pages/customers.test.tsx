import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock API
const mockGetCustomers = vi.fn()
const mockGetCustomerTags = vi.fn()
const mockCreateCustomerTag = vi.fn()
const mockDeleteCustomerTag = vi.fn()

vi.mock('@/lib/api', () => ({
  customerApi: {
    getCustomers: (...args: any[]) => mockGetCustomers(...args),
    getCustomerTags: (...args: any[]) => mockGetCustomerTags(...args),
    createCustomerTag: (...args: any[]) => mockCreateCustomerTag(...args),
    deleteCustomerTag: (...args: any[]) => mockDeleteCustomerTag(...args),
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
    Tags: stub('tags'),
    X: stub('x'),
    Star: stub('star'),
    Search: stub('search'),
    ChevronUp: stub('chevron-up'),
    ChevronDown: stub('chevron-down'),
    ChevronLeft: stub('chevron-left'),
    ChevronRight: stub('chevron-right'),
  }
})

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: string) => ({
    format: (fmt: string) => date ? '04-20 14:30' : '2026-04-25',
  }),
}))

// Mock types
vi.mock('@/types', () => ({
  CustomerChannelLabels: {
    wechat_mini: '微信小程序',
    wechat_mp: '公众号',
    web: 'Web',
  },
}))

// Need to re-export TableColumn type
vi.mock('@/components/ui', async (importOriginal) => {
  return {
    Table: ({ columns, dataSource, loading, rowKey, onRowClick }: any) => (
      <div data-testid="data-table">
        {loading && <div data-testid="table-loading">加载中...</div>}
        {!loading && dataSource.length === 0 && <div>暂无数据</div>}
        {dataSource.map((record: any) => (
          <div
            key={typeof rowKey === 'function' ? rowKey(record) : record[rowKey]}
            data-testid={`customer-${record.id}`}
            onClick={() => onRowClick?.(record)}
          >
            <span>{record.name}</span>
            <span>{record.phone}</span>
          </div>
        ))}
      </div>
    ),
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
    Badge: ({ children, variant }: any) => <span data-variant={variant}>{children}</span>,
    SearchBar: ({ fields, onSearch, onReset }: any) => (
      <div data-testid="search-bar">
        {fields.map((f: any) => <span key={f.key}>{f.label}</span>)}
        <button onClick={() => onSearch({})}>搜索</button>
        <button onClick={onReset}>重置</button>
      </div>
    ),
  }
})

import CustomersPage from '@/app/(dashboard)/customers/page'

describe('CustomersPage', () => {
  const user = userEvent.setup()

  beforeEach(() => {
    vi.clearAllMocks()

    // Mock API responses
    mockGetCustomers.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: '1', name: '张美丽', phone: '138****1234', channel: 'wechat_mini', vipLevel: 'gold', totalOrders: 5, totalSpent: 12000, createdAt: '2026-04-20T14:30:00Z' },
            { id: '2', name: '李优雅', phone: '139****5678', channel: 'wechat_mp', vipLevel: 'silver', totalOrders: 3, totalSpent: 8000, createdAt: '2026-04-21T10:00:00Z' },
          ],
          total: 2,
          page: 1,
          pageSize: 10,
        },
      },
    })

    mockGetCustomerTags.mockResolvedValue({
      data: {
        data: [
          { id: '1', name: 'VIP客户', color: '#ff6b6b' },
          { id: '2', name: '窗帘定制', color: '#4ecdc4' },
        ],
      },
    })
  })

  it('should render page title', async () => {
    render(<CustomersPage />)
    expect(screen.getByText('客户管理')).toBeInTheDocument()
    expect(screen.getByText(/管理客户信息/)).toBeInTheDocument()
  })

  it('should render tag management button', () => {
    render(<CustomersPage />)
    expect(screen.getByText('标签管理')).toBeInTheDocument()
  })

  it('should render search bar', () => {
    render(<CustomersPage />)
    expect(screen.getByTestId('search-bar')).toBeInTheDocument()
  })

  it('should load and display customers', async () => {
    render(<CustomersPage />)
    await waitFor(() => {
      expect(screen.getByTestId('customer-1')).toBeInTheDocument()
      expect(screen.getByText('张美丽')).toBeInTheDocument()
    })
  })

  it('should display customer phone numbers', async () => {
    render(<CustomersPage />)
    await waitFor(() => {
      expect(screen.getByText('138****1234')).toBeInTheDocument()
    })
  })

  it('should render pagination', async () => {
    render(<CustomersPage />)
    await waitFor(() => {
      expect(screen.getByTestId('pagination')).toBeInTheDocument()
    })
  })

  it('should open tag management modal', async () => {
    render(<CustomersPage />)
    // Click the button (not the h2 title in modal)
    const buttons = screen.getAllByText('标签管理')
    await user.click(buttons[0])
    expect(screen.getByTestId('modal')).toBeInTheDocument()
  })

  it('should show existing tags in tag modal', async () => {
    render(<CustomersPage />)
    await user.click(screen.getByText('标签管理'))
    await waitFor(() => {
      expect(screen.getByText('VIP客户')).toBeInTheDocument()
      expect(screen.getByText('窗帘定制')).toBeInTheDocument()
    })
  })

  it('should render search fields', () => {
    render(<CustomersPage />)
    expect(screen.getByText('关键词')).toBeInTheDocument()
    expect(screen.getByText('来源渠道')).toBeInTheDocument()
    expect(screen.getByText('VIP 等级')).toBeInTheDocument()
  })
})
