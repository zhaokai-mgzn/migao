// case_ids: OR-001, OR-002, OR-003, OR-004, OR-005, UI-057, UI-058, UI-130
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// issue #5983：「新增订单」按钮改为按 `order:create` 显隐（`canWrite = hasPermission('order:create')`）
// ⇒ 渲染必须带**登录态**，否则 user 为 null ⇒ 按钮恒不渲染（该页其余用例会假红）。
// 默认给管理员（`permissions: ['*']`）；要测「无码看不见」请改 `authMock.state.user.permissions`。
const authMock = vi.hoisted(() => ({
  state: {
    user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'] as string[], roles: [] as string[] },
  },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
}))

// Mock API
const mockGetOrders = vi.fn()
const mockDeleteOrder = vi.fn()
const mockUpdateOrderStatus = vi.fn()
const mockRefundOrder = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrders: (...args: any[]) => mockGetOrders(...args),
    deleteOrder: (...args: any[]) => mockDeleteOrder(...args),
    updateOrderStatus: (...args: any[]) => mockUpdateOrderStatus(...args),
    refundOrder: (...args: any[]) => mockRefundOrder(...args),
  },
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock lucide-react
vi.mock('lucide-react', async (importOriginal) => {
  // ⚠️ 必须 spread `...actual`：本 mock 是**闭合集合**（只列页面直接用到的那几个图标），
  // 而模块一旦经 `@/components/ui` 桶加载真 `EmptyState`（它自己 import `Package`），
  // 闭集就漏了它 ⇒ 报 `No "Package" export is defined on the "lucide-react" mock`
  // （与「整模块 mock `@/components/ui`」同一种病，见 issue #7007）。
  // `...actual` 在前 ⇒ 显式桩的 testid 仍然赢。
  const actual = await importOriginal<Record<string, unknown>>()
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    ...actual,
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
// issue #8052：同时记下页面**实际传下去的 props** —— 选择态（`selectedIds` / `onSelectChange`）
// 已随假勾选框一起移除；红证 = 页面把这两个 props 传回来 ⇒ 下面「不再传选择态」那条当场红。
const orderTableProps = vi.hoisted(() => ({ current: null as Record<string, unknown> | null }))
vi.mock('@/components/orders', () => ({
  OrderTable: (props: any) => {
    orderTableProps.current = props
    const { orders, loading, onView, onClose, onRemark, onRefund, emptyText } = props
    return (
    <div data-testid="order-table">
      {loading && <div data-testid="table-loading">加载中...</div>}
      {/* issue #8040：把页面传的 `emptyText` **真的**渲染出来 —— 改前这里写死「暂无数据」，
          页面怎么改空态话术，判据都看不见。 */}
      {!loading && orders.length === 0 && <div data-testid="order-table-empty">{emptyText}</div>}
      {orders.map((o: any) => {
        // 镜像真实 OrderTable 的退款按钮条件（后端可退状态 + refundAmount === 0）
        const refundable = ['confirmed', 'producing', 'shipped', 'completed'].includes(o.status)
          && (o.refundAmount ?? 0) === 0
        return (
          <div key={o.id} data-testid={`order-${o.id}`}>
            <span>{o.orderNo}</span>
            <span>{o.customerName}</span>
            <button onClick={() => onView(o)} data-testid={`view-${o.id}`}>查看</button>
            <button onClick={() => onClose(o)} data-testid={`close-${o.id}`}>关闭</button>
            {refundable && (
              <button onClick={() => onRefund(o)} data-testid={`refund-${o.id}`}>处理退款</button>
            )}
          </div>
        )
      })}
    </div>
    )
  },
  CloseOrderModal: ({ open, onClose, onConfirm }: any) => (
    open ? <div data-testid="modal" role="dialog"><button onClick={() => onConfirm('缺货')}>确认关闭</button></div> : null
  ),
  RemarkModal: ({ open, onClose, onConfirm }: any) => (
    open ? <div data-testid="remark-modal" role="dialog"><button onClick={() => onConfirm('备注内容')}>确认备注</button></div> : null
  ),
  RefundOrderModal: ({ open, onConfirm }: any) => (
    open ? (
      <div data-testid="refund-modal" role="dialog">
        <button data-testid="confirm-refund" onClick={() => onConfirm({ refundAmount: 500, refundReason: '质量问题' })}>
          确认退款
        </button>
      </div>
    ) : null
  ),
}))

// Mock UI components
vi.mock('@/components/ui', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    // issue #7007：**先摊开真原语，再覆盖**（`...actual` 在前 ⇒ 显式 mock 仍然赢）。
    // 此前这里是**整模块** mock 且不合并真值，只列被替身的几个原语 ⇒ 页面一旦用上
    // **当时不存在的原语**（本轮加了 PageHeader / PageCard / SearchPanel）就报
    // `No "PageHeader" export is defined on the "@/components/ui" mock` ——
    // 报错离病灶很远（本轮 144 条红的根因，与页面改动对错无关）。
    // 摊开真值后，新增原语不必再逐个补 mock。口径与同目录
    // `production-remnants-paging.test.tsx` 既有写法同源。
    ...actual,
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
  }
})

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
  // issue #8040 的空态分流用例要点一次状态 tab ⇒ 页面的 `loadOrders` 会调它
  // （真实实现把前端 tab 映射成后端状态；本文件只需它存在且原样下传）。
  toBackendStatusParam: (s: string) => s,
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
  { id: '4', orderNo: 'MG202600004', customerName: '赵女士', status: 'completed', refundAmount: 100, totalAmount: 500, createdAt: '2026-04-22T08:00:00' },
]

describe('OrdersPage', () => {
  const user = userEvent.setup()

  beforeEach(() => {
    vi.clearAllMocks()
    mockGetOrders.mockResolvedValue({
      data: { data: { items: mockOrders, total: 4 } },
    })
  })

  it('should render page title', () => {
    render(<OrdersPage />)
    expect(screen.getByText('销售订单')).toBeInTheDocument()
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

  // issue #8052：勾选框是**假动作**（选完没有任何批量动作消费它）⇒ 用户 2026-10-29 裁定先移除。
  // 页面侧的判据 = 不再向表格传选择态 props；列头 / 行内形态与列数一致性由**真组件**的判据覆盖
  // （`tests/unit/components/OrderTable.test.tsx` 与 `tests/unit/pages/orders-list-row-actions.test.tsx`）。
  it('不再向 OrderTable 传选择态 props（selectedIds / onSelectChange 已移除）', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())
    expect(orderTableProps.current).toBeTruthy()
    // 红证：把页面里的 `const [selectedIds, ...]` 与这两个 props 注回去 ⇒ 下面两条当场红
    expect('selectedIds' in orderTableProps.current!).toBe(false)
    expect('onSelectChange' in orderTableProps.current!).toBe(false)
  })

  // issue #8048：加载态 = **通用表格骨架**（#8036 已验收口径），不再是裸「加载中…」+ 空白表体
  // （页面级三元 —— 骨架不在 OrderTable 内部渲染，组件被 mock 掉也照样能断言）。
  it('加载中：渲染 table-skeleton，且不出现裸「加载中…」文案（#8048）', async () => {
    // 取数挂起 ⇒ 页面停在加载态
    mockGetOrders.mockReturnValue(new Promise(() => {}))
    render(<OrdersPage />)
    expect(await screen.findByTestId('table-skeleton')).toBeInTheDocument()
    // 红证：把加载分支改回「裸文案 / 交给 OrderTable 内部 loading」⇒ 本条红
    expect(screen.queryByText(/加载中/)).not.toBeInTheDocument()
    expect(screen.queryByTestId('table-loading')).not.toBeInTheDocument()
  })

  it('空态分流（issue #8040）：真没有订单 ⇒ 说清「近一个月」与去哪建；筛了 tab ⇒ 说清换个条件', async () => {
    mockGetOrders.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    render(<OrdersPage />)

    // ① 真为空：说清默认只覆盖近一个月 + 去哪建（不再是裸「暂无数据」）
    const trulyEmpty = await screen.findByTestId('order-table-empty')
    expect(trulyEmpty.textContent).toContain('最近一个月还没有订单')
    expect(trulyEmpty.textContent).toContain('新增订单')
    expect(screen.queryByText('暂无数据')).toBeNull()

    // ② 切了状态 tab ⇒ 改口说「没有符合当前筛选的订单」（与「真没有单」分开说）
    await user.click(screen.getAllByRole('button', { name: '待付款' })[0])
    await waitFor(() =>
      expect(screen.getByTestId('order-table-empty').textContent).toContain('没有符合当前筛选的订单'),
    )
  })

  it('should render search filters（筛选区默认收起：展开后才在）', async () => {
    // issue #7388：筛选区默认折叠 ⇒ 字段默认**不进 DOM**，展开后才在（折叠不是 CSS 隐藏）。
    render(<OrdersPage />)
    expect(screen.queryByPlaceholderText('请输入订单ID')).not.toBeInTheDocument()
    await user.click(screen.getByTestId('search-panel-toggle'))
    expect(screen.getByPlaceholderText('请输入订单ID')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('请输入收货人姓名或手机号')).toBeInTheDocument()
  })

  it('筛选区默认收起：一行摘要（当前在筛什么）+ 展开入口；字段/查询按钮都不进 DOM', () => {
    render(<OrdersPage />)
    const toggle = screen.getByTestId('search-panel-toggle')
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    // 默认时间范围一直在生效 ⇒ 收起态必须说出来，否则看着像「全部订单」。
    expect(screen.getByTestId('search-panel-summary').textContent).toContain('近一个月')
    // 收起态要**引导**「这里能打开去查询」（用户 2026-10-20 追加要求）。
    expect(screen.getByTestId('search-panel-toggle-label').textContent).toContain('展开筛选')
    expect(screen.queryByPlaceholderText('请输入订单ID')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '查询' })).not.toBeInTheDocument()
  })

  it('展开筛选 ⇒ 7 个筛选项全在 + 查询/重置/刷新三个动作；再点收起 ⇒ 全部消失', async () => {
    render(<OrdersPage />)
    await user.click(screen.getByTestId('search-panel-toggle'))
    for (const placeholder of [
      '请输入订单ID',
      '请输入收货人姓名或手机号',
      '请输入制单人姓名',
      '请输入商品货号',
      '请输入商品标题',
    ]) {
      expect(screen.getByPlaceholderText(placeholder)).toBeInTheDocument()
    }
    // 日期区间两框（placeholder = 开始/结束日期）与「是否加工」下拉
    expect(screen.getAllByPlaceholderText('开始日期').length).toBe(1)
    expect(screen.getAllByPlaceholderText('结束日期').length).toBe(1)
    for (const name of ['查询', '重置', '刷新']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument()
    }

    await user.click(screen.getByTestId('search-panel-toggle'))
    expect(screen.queryByPlaceholderText('请输入订单ID')).not.toBeInTheDocument()
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

  it('should show reset and search buttons（展开筛选后可见）', async () => {
    render(<OrdersPage />)
    await user.click(screen.getByTestId('search-panel-toggle'))
    expect(screen.getByText('重置')).toBeInTheDocument()
    expect(screen.getByText('查询')).toBeInTheDocument()
  })

  it('查询和重置按钮都应使用 inline-flex items-center 保证图标与文字垂直居中对齐 (#1831)', async () => {
    render(<OrdersPage />)
    // issue #7388：按钮行在折叠区里 ⇒ 先展开，否则这里量的是「不存在」而不是「对齐」。
    await user.click(screen.getByTestId('search-panel-toggle'))
    const searchBtn = screen.getByText('查询').closest('button')
    const resetBtn = screen.getByText('重置').closest('button')

    expect(searchBtn).toBeTruthy()
    expect(resetBtn).toBeTruthy()

    // 查询按钮：必须包含 inline-flex 和 items-center（修复 #1831）
    expect(searchBtn!.className).toMatch(/\binline-flex\b/)
    expect(searchBtn!.className).toMatch(/\bitems-center\b/)

    // 重置按钮：已是 inline-flex items-center（参照基准）
    expect(resetBtn!.className).toMatch(/\binline-flex\b/)
    expect(resetBtn!.className).toMatch(/\bitems-center\b/)
  })

  it('should display customer names in order list', async () => {
    render(<OrdersPage />)
    await waitFor(() => {
      expect(screen.getByText('张先生')).toBeInTheDocument()
      expect(screen.getByText('李女士')).toBeInTheDocument()
    })
  })

  // ===== 退款流程（P0：处理退款按钮 + 弹窗 + 提交调用 api） =====

  it('退款按钮出现在可退款订单（confirmed/completed 未退款），不出现在 pending/已退款订单', async () => {
    render(<OrdersPage />)
    await waitFor(() => {
      expect(screen.getByTestId('order-1')).toBeInTheDocument()
    })
    // confirmed / completed 未退款 → 有按钮
    expect(screen.getByTestId('refund-2')).toBeInTheDocument()
    expect(screen.getByTestId('refund-3')).toBeInTheDocument()
    // pending（待付款）→ 无按钮
    expect(screen.queryByTestId('refund-1')).not.toBeInTheDocument()
    // 已退款订单（refundAmount > 0）→ 无按钮
    expect(screen.queryByTestId('refund-4')).not.toBeInTheDocument()
  })

  it('点击 处理退款 弹出退款 Modal', async () => {
    render(<OrdersPage />)
    await waitFor(() => {
      expect(screen.getByTestId('refund-2')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('refund-2'))
    expect(screen.getByTestId('refund-modal')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('提交退款调用 orderApi.refundOrder(id, payload) 并刷新列表', async () => {
    render(<OrdersPage />)
    await waitFor(() => {
      expect(screen.getByTestId('refund-2')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('refund-2'))
    await user.click(screen.getByTestId('confirm-refund'))

    await waitFor(() => {
      expect(mockRefundOrder).toHaveBeenCalledWith('2', { refundAmount: 500, refundReason: '质量问题' })
    })
    // 成功后刷新列表（初始 1 次 + 退款后 1 次）
    await waitFor(() => {
      expect(mockGetOrders.mock.calls.length).toBeGreaterThanOrEqual(2)
    })
    // 成功后关闭弹窗
    await waitFor(() => {
      expect(screen.queryByTestId('refund-modal')).not.toBeInTheDocument()
    })
  })
})
