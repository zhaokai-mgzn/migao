// case_ids: UI-002, UI-057, UI-058
// 本包（issue #6703）只复用既有用例号，不新开用例；合并原声明 UI-002（同文件两处声明时第二处会被遮蔽）。
// ⚠️ 声明行必须是 `//` / `#` / ` * ` 起始（`CASE_IDS_RE` 不认 `/* ` 起始），且其后不得再出现 case_ids 字样。
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock API
const mockGetTickets = vi.fn()

// issue #5792：`?overdue=1` 要能被判据控制（看板「超时工单」卡就是这么跳过来的）。
// `vi.hoisted` 是因为 vi.mock 会被提升到文件顶部，普通顶层变量在工厂里会命中 TDZ。
const h = vi.hoisted(() => ({ params: new URLSearchParams() }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => h.params,
}))
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
  StatusBadge: ({ label, color, dot, className, onClick }: any) => React.createElement('span', { onClick, className: [color, className].filter(Boolean).join(' '), title: label }, dot ? React.createElement('span', { className: 'w-1.5 h-1.5 rounded-full' }) : null, label),
  Badge: ({ children, variant }: any) => <span data-testid="badge" data-variant={variant}>{children}</span>,
  }
})

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

  // issue #8048：加载态 = 通用表格骨架（#8036 口径），不再是 tbody 里的裸「加载中…」+ 空白表体。
  it('加载中：渲染 table-skeleton，且不出现裸「加载中…」文案（#8048）', async () => {
    mockGetTickets.mockReturnValue(new Promise(() => {}))
    render(<AfterSalesPage />)
    expect(await screen.findByTestId('table-skeleton')).toBeInTheDocument()
    // 红证：把加载分支改回 tbody 里的裸「加载中…」行 ⇒ 本条红
    expect(screen.queryByText(/加载中/)).not.toBeInTheDocument()
  })

  it('should render search filters', () => {
    render(<AfterSalesPage />)
    expect(screen.getByText('关键词搜索')).toBeInTheDocument()
    expect(screen.getByText('状态筛选')).toBeInTheDocument()
  })

  it('should render reset and search buttons', () => {
    render(<AfterSalesPage />)
    expect(screen.getByText('重置')).toBeInTheDocument()
    expect(screen.getByText('查询')).toBeInTheDocument()
  })

  it('空态分流（issue #8040）：真没有工单 ⇒ 说清去哪建；筛了状态 ⇒ 说清换个条件', async () => {
    mockGetTickets.mockResolvedValue({
      data: { data: { items: [], total: 0 } },
    })
    render(<AfterSalesPage />)

    // ① 真为空：不只说「没有」，还说清下一步（去哪里建单）—— 裸「暂无售后工单」不再出现
    const trulyEmpty = await screen.findByText(/还没有售后工单/)
    expect(trulyEmpty.textContent, '空态要说清去哪建（「新建工单」）').toContain('新建工单')
    expect(screen.queryByText('暂无售后工单')).toBeNull()

    // ② 筛选下为空：改口说「换个条件」，不让商家以为一张工单都没有过
    await user.click(screen.getByRole('button', { name: '待处理' }))
    expect(await screen.findByText(/没有符合筛选条件的工单/)).toBeInTheDocument()
    expect(screen.queryByText(/还没有售后工单/)).toBeNull()
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

  it('五种售后状态渲染语义色 chips，未知状态回退 neutral 且 label=暂无数据', async () => {
    const base = {
      customerName: '张先生', ticketType: 'return', priority: 'normal',
      createdAt: '2026-04-25T10:00:00', updatedAt: '2026-04-25T10:00:00',
    }
    mockGetTickets.mockResolvedValue({
      data: { data: { items: [
        { id: 's1', ticketNo: 'T1', orderNo: 'O1', status: 'pending', ...base },
        { id: 's2', ticketNo: 'T2', orderNo: 'O2', status: 'processing', ...base },
        { id: 's3', ticketNo: 'T3', orderNo: 'O3', status: 'resolved', ...base },
        { id: 's4', ticketNo: 'T4', orderNo: 'O4', status: 'rejected', ...base },
        { id: 's5', ticketNo: 'T5', orderNo: 'O5', status: 'closed', ...base },
        { id: 's6', ticketNo: 'T6', orderNo: 'O6', status: 'unknown-status' as any, ...base },
      ], total: 6 } },
    })

    render(<AfterSalesPage />)
    await waitFor(() => {
      expect(screen.getByText('T1')).toBeInTheDocument()
    })

    const findByTone = (text: string, toneClass: string) =>
      screen.getAllByText(text).find((el) => el.className.includes(toneClass))

    expect(findByTone('待处理', 'bg-amber-50')).toBeTruthy()
    expect(findByTone('处理中', 'bg-primary-50')).toBeTruthy()
    expect(findByTone('已完成', 'bg-emerald-50')).toBeTruthy()
    expect(findByTone('已拒绝', 'bg-red-50')).toBeTruthy()
    expect(findByTone('已关闭', 'bg-neutral-100')).toBeTruthy()

    // 未知状态 → neutral + 「暂无数据」
    const unknownChip = screen.getAllByText('暂无数据').find((el) => el.className.includes('bg-neutral-100'))
    expect(unknownChip).toBeTruthy()
  })

  // ── #5792：看板「超时工单」卡的下钻必须**真的筛**（否则就是新的"计数与下钻不一致"）──

  it('🔴 `?overdue=1` ⇒ 请求带 `overdue: true`，并显示可清除的筛选指示', async () => {
    h.params = new URLSearchParams('overdue=1')
    render(<AfterSalesPage />)
    await waitFor(() => expect(mockGetTickets).toHaveBeenCalled())
    // ① **真的发给服务端**（口径与服务端同源，不是前端假装筛）
    expect(mockGetTickets.mock.calls.at(-1)?.[0]).toMatchObject({ overdue: true })
    // ② 可见指示（用户要知道列表为什么变短）
    expect(screen.getByTestId('after-sales-overdue-chip')).toBeInTheDocument()
  })

  it('🔴 点掉筛选指示 ⇒ 重新拉取且**不再带** `overdue`（筛选可撤销，不是单程票）', async () => {
    h.params = new URLSearchParams('overdue=1')
    render(<AfterSalesPage />)
    await waitFor(() => expect(screen.getByTestId('after-sales-overdue-chip')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('after-sales-overdue-chip'))
    await waitFor(() => {
      const last = mockGetTickets.mock.calls.at(-1)?.[0] as Record<string, unknown>
      expect(last.overdue).toBeUndefined()
    })
    expect(screen.queryByTestId('after-sales-overdue-chip')).toBeNull()
  })
})
