// case_ids: CU-001, CU-010
// 追加（issue #6669 第 4 条）：删标签二次确认 + 「最后互动」日期口径收敛到 DateTimeCell。
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
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

// 🔴 不再 mock dayjs（issue #6669 第 4 条）：原来的 mock 把**任何** format 都返回 `04-20 14:30`
// —— 那恰好是修前的坏形态（无年份），而「日期口径是否收敛到 DateTimeCell」正是本包要判的东西。
// 留着这个 mock 会把判据变成空的（新旧两种形态渲染成同一串）⇒ 用真 dayjs，让日期列**真的**被断言。
// （本文件其它用例只查客户名/手机号/标签/pagination，不依赖日期文本。）

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
            {/* 逐列调用真实的 column.render（issue #6669 第 4 条的日期口径判据就落在这一层） */}
            {columns.map((c: any) => (
              <span key={c.key}>{c.render ? c.render(record, 0) : String(record[c.key] ?? '')}</span>
            ))}
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
    StatusBadge: ({ label, color, dot, className, onClick }: any) => React.createElement('span', { onClick, className, title: label }, dot ? React.createElement('span', { className: 'w-1.5 h-1.5 rounded-full' }) : null, label),
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
    mockDeleteCustomerTag.mockResolvedValue({ data: { success: true } })

    // Mock API responses
    mockGetCustomers.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: '1', name: '张美丽', phone: '138****1234', channel: 'wechat_mini', vipLevel: 'gold', totalOrders: 5, totalSpent: 12000, createdAt: '2026-04-20T14:30:00Z', lastActiveAt: '2026-04-20T14:30:00Z' },
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

  /**
   * 🔴 issue #6669 第 4 条（破坏性动作要有二次确认）：
   * 标签会被**客户绑定**，修前点 ✕ 当场就删（没有确认、没有「不可撤销」说明）。
   * 红证：把 `onClick={() => setDeletingTag(tag)}` 改回 `onClick={() => handleDeleteTag(tag)}` ⇒
   * 本条的 `expect(mockDeleteCustomerTag).not.toHaveBeenCalled()` 当场红。
   */
  it('删标签先确认：点 ✕ 不发请求，确认后才调 API；取消则什么都不做', async () => {
    render(<CustomersPage />)
    await user.click(screen.getByText('标签管理'))
    await waitFor(() => expect(screen.getByTestId('tag-delete-1')).toBeInTheDocument())

    await user.click(screen.getByTestId('tag-delete-1'))
    expect(mockDeleteCustomerTag).not.toHaveBeenCalled()
    expect(screen.getByText(/无法恢复/)).toBeInTheDocument()

    // 取消 ⇒ 关闭、不发请求
    await user.click(screen.getByText('取消'))
    expect(mockDeleteCustomerTag).not.toHaveBeenCalled()

    // 再点一次并确认 ⇒ 才真的删
    await user.click(screen.getByTestId('tag-delete-1'))
    await user.click(screen.getByTestId('tag-delete-confirm'))
    await waitFor(() => expect(mockDeleteCustomerTag).toHaveBeenCalledWith('1'))
  })

  /**
   * 🔴 issue #6669 第 4 条（日期口径收敛）：修前「最后互动」是 `MM-DD HH:mm`（**无年份**），
   * 而同域客户详情页是 `YYYY-MM-DD HH:mm` ⇒ 跨年的单看起来像今年。
   * 现收敛到既有唯一组件 `@/components/common/DateTimeCell`（YYYY-MM-DD + HH:mm 两行）。
   *
   * ⚠️ 本文件把 dayjs mock 成 `'04-20 14:30'`（见文件头）—— 那正是**修前的坏形态**；
   * DateTimeCell 走原生 Date 合法性检查 + dayjs 格式化 ⇒ 断言"含 4 位年份"即可把两者分开。
   * 红证：把 render 改回 `dayjs(record.lastActiveAt).format('MM-DD HH:mm')` ⇒ 本条红（读数是 `04-20 14:30`）。
   */
  it('「最后互动」带年份（收敛到 DateTimeCell，不再是无年份的 MM-DD HH:mm）', async () => {
    render(<CustomersPage />)
    await waitFor(() => expect(screen.getByTestId('customer-1')).toBeInTheDocument())
    const cell = within(screen.getByTestId('customer-1')).getByText(/^\d{4}-\d{2}-\d{2}$/)
    expect(cell).toBeInTheDocument()
    expect(within(screen.getByTestId('customer-1')).queryByText(/^\d{2}-\d{2} \d{2}:\d{2}$/)).toBeNull()
  })
})
