// case_ids: CU-001, CU-010, UI-057, UI-058
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

// Mock lucide-react —— issue #7007：整模块 mock 换成 **真实模块 + 局部覆盖**（helper 与 #6664 同源）。
// 逐个列图标名的写法会在「任一被导入的 UI 组件新增图标」时炸
// `No "X" export is defined on the "lucide-react" mock`。本轮客户页把 `SearchBar` 换成
// `SearchPanel`（内部用 `lucide-react` 的 `Search` / `RotateCcw` / `RefreshCw`）后，
// 本文件先炸在缺 `Package`（`EmptyState` 的图标）上 —— 正是这条脆弱的写法。
vi.mock('lucide-react', async (importOriginal) =>
  (await import('../helpers/lucide-mock')).lucideMock((await importOriginal()) as Record<string, unknown>))

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
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    // issue #7007：**先摊开真原语，再覆盖**（`...actual` 在前 ⇒ 显式 mock 仍然赢）。
    // 本工厂此前虽声明了 `importOriginal`，却**没用它**（收下参数就丢掉）⇒ 等价于整模块 mock：
    // 客户页本轮把 `SearchBar` 换成 `SearchPanel` 后，页面要用的 `Select` 在工厂里没有
    // ⇒ `No "Select" export is defined on the "@/components/ui" mock`（本文件 11 条红）。
    // 摊开真值后，新增 / 换用原语不必再逐个补 mock。
    ...actual,
    Table: ({ columns, dataSource, loading, rowKey, onRowClick, emptyText }: any) => (
      <div data-testid="data-table">
        {loading && <div data-testid="table-loading">加载中...</div>}
        {/* issue #8040：把页面传的 `emptyText` **真的**渲染出来 —— 改前这里写死「暂无数据」，
            页面怎么改空态话术，判据都看不见（撞的正是本单要修的那句裸文案）。 */}
        {!loading && dataSource.length === 0 && <div data-testid="table-empty">{emptyText}</div>}
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

  // issue #8048：加载态 = 通用表格骨架（#8036 口径），不再是裸「加载中…」+ 空白表体。
  it('加载中：渲染 table-skeleton，且不出现裸「加载中…」文案（#8048）', async () => {
    mockGetCustomers.mockReturnValue(new Promise(() => {}))
    render(<CustomersPage />)
    expect(await screen.findByTestId('table-skeleton')).toBeInTheDocument()
    // 红证：把加载分支改回交给共享 `Table` 的 loading 分支 ⇒ 本条红
    expect(screen.queryByText(/加载中/)).not.toBeInTheDocument()
    expect(screen.queryByTestId('table-loading')).not.toBeInTheDocument()
  })

  it('should render search bar', async () => {
    render(<CustomersPage />)
    // 🔴 2026-10-16（issue #7007）改判：客户页的筛选区由 `SearchBar`（自带 state）
    // 换成共享原语 `SearchPanel`（无状态，值由页面持有）⇒ 锚点从 `search-bar` 变为
    // 原语的 `search-area`。**同时保留一条更硬的**：三个筛选控件（关键词 / 渠道 / 会员等级）
    // 必须真的渲染出来 —— 换组件时「容器在、控件没了」是最容易溜过的退步。
    expect(screen.getByTestId('search-area')).toBeInTheDocument()
    for (const label of ['关键词', '来源渠道', 'VIP 等级']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('should load and display customers', async () => {
    render(<CustomersPage />)
    await waitFor(() => {
      expect(screen.getByTestId('customer-1')).toBeInTheDocument()
      expect(screen.getByText('张美丽')).toBeInTheDocument()
    })
  })

  it('空态分流（issue #8040）：真没有客户 ⇒ 说清客户从哪来；筛选下为空 ⇒ 说清换个条件', async () => {
    mockGetCustomers.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    render(<CustomersPage />)

    // ① 真为空：说清客户怎么来的（不再是裸「暂无数据」）
    const trulyEmpty = await screen.findByTestId('table-empty')
    expect(trulyEmpty.textContent).toContain('还没有客户')
    expect(trulyEmpty.textContent).toContain('自动建档')
    expect(screen.queryByText('暂无数据')).toBeNull()

    // ② 筛选下为空：改口说「换个条件」，不让商家以为一个客户都没有
    await user.type(screen.getByPlaceholderText('客户名/手机号'), '不存在的客户')
    await user.click(screen.getByRole('button', { name: '查询' }))
    await waitFor(() =>
      expect(mockGetCustomers).toHaveBeenLastCalledWith(expect.objectContaining({ keyword: '不存在的客户' })),
    )
    expect((await screen.findByTestId('table-empty')).textContent).toContain('没有符合筛选条件的客户')
  })

  it('标签空态说清下一步（issue #8040）：不是裸「暂无标签」', async () => {
    mockGetCustomerTags.mockResolvedValue({ data: { data: [] } })
    render(<CustomersPage />)
    await user.click(screen.getByText('标签管理'))
    expect(await screen.findByText(/还没有标签/)).toBeInTheDocument()
    expect(screen.queryByText('暂无标签')).toBeNull()
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
