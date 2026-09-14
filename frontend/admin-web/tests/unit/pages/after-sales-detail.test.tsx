// case_ids: AS-004
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock API
const mockGetTicket = vi.fn()
const mockUpdateTicketStatus = vi.fn()

vi.mock('@/lib/api', () => ({
  afterSalesApi: {
    getTicket: (...args: any[]) => mockGetTicket(...args),
    updateTicketStatus: (...args: any[]) => mockUpdateTicketStatus(...args),
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
  StatusBadge: ({ label, color, dot, className, onClick }: any) => React.createElement('span', { onClick, className, title: label }, dot ? React.createElement('span', { className: 'w-1.5 h-1.5 rounded-full' }) : null, label),
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

// 关闭后的工单（后端 closed 会写 closedAt + closeReason，closeReason 取自 request.remark）
const closedTicket = {
  ...mockTicket,
  status: 'closed' as const,
  closedAt: '2026-06-20T12:00:00Z',
  closeReason: '重复工单，线下已处理',
  statusHistory: [
    ...mockTicket.statusHistory,
    {
      status: 'closed' as const,
      time: '2026-06-20T12:00:00Z',
      operator: '管理员',
    },
  ],
}

// 处理中的工单——用于核对 pending 的关闭项与既有 processing 关闭项「形态一致」
const processingTicket = { ...mockTicket, status: 'processing' as const }

describe('AfterSalesDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // clearAllMocks 不重置实现：显式 mockReset，避免上一用例的 mockResolvedValue 泄漏
    mockGetTicket.mockReset()
    mockUpdateTicketStatus.mockReset()
    mockGetTicket.mockResolvedValue({
      data: { data: mockTicket },
    })
    mockUpdateTicketStatus.mockResolvedValue({ data: { success: true } })
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

  // ── 售后 pending 工单关闭入口（issue #3541 裁定：pending → closed 允许） ──
  // case_ids: AS-004

  it('pending 工单渲染「关闭工单」，且与 processing 的关闭项形态一致（同 label / 同 variant）', async () => {
    const { unmount } = render(<AfterSalesDetailPage />)
    await screen.findByRole('button', { name: '接受处理' })

    const pendingClose = screen.getByRole('button', { name: '关闭工单' })
    // 形态一致：label 语义与 variant（secondary）与既有 processing 关闭项相同
    expect(pendingClose).toHaveAttribute('variant', 'secondary')

    // 操作顺序：正向主操作（接受处理）→ 中性归档（关闭工单）→ 负向终态（拒绝）
    const actionLabels = screen
      .getAllByRole('button')
      .map((b) => b.textContent || '')
      .filter((t) => ['接受处理', '关闭工单', '拒绝'].includes(t))
    expect(actionLabels).toEqual(['接受处理', '关闭工单', '拒绝'])

    // 对照组：processing 的关闭项形态与 pending 完全一致
    unmount()
    mockGetTicket.mockResolvedValue({ data: { data: processingTicket } })
    render(<AfterSalesDetailPage />)
    await screen.findByRole('button', { name: '完成处理' })
    const processingClose = screen.getByRole('button', { name: '关闭工单' })
    expect(processingClose).toHaveAttribute('variant', 'secondary')
    expect(processingClose.textContent).toBe(pendingClose.textContent)
  })

  it('pending 工单关闭：走确认弹窗收集关闭原因（remark）→ 调 API status=closed → 详情刷新后已关闭与关闭原因可见', async () => {
    const user = userEvent.setup()
    mockGetTicket
      .mockResolvedValueOnce({ data: { data: mockTicket } }) // 首次加载：待处理
      .mockResolvedValueOnce({ data: { data: closedTicket } }) // 关闭后刷新：已关闭
    render(<AfterSalesDetailPage />)

    await user.click(await screen.findByRole('button', { name: '关闭工单' }))

    // 复用既有确认路径：同一个「确认操作」弹窗 + 处理备注收集（关闭原因即 remark）
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('确认操作')).toBeInTheDocument()
    // 弹窗明确告知目标状态 = 已关闭，且与既有路径同形态（同一「确认操作」弹窗 + 备注收集）
    expect(within(dialog).getByText('已关闭')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: '确认关闭工单' })).toBeInTheDocument()
    await user.type(
      within(dialog).getByPlaceholderText('请输入处理备注...'),
      '重复工单，线下已处理',
    )
    await user.click(within(dialog).getByRole('button', { name: '确认关闭工单' }))

    // 契约：状态值英文枚举 closed，原因字段是 remark（不是 reason）
    await waitFor(() => {
      expect(mockUpdateTicketStatus).toHaveBeenCalledWith('ticket-001', {
        status: 'closed',
        remark: '重复工单，线下已处理',
      })
    })

    // 结果可见：详情重新拉取 + 已关闭状态文案 / 关闭时间 / 关闭原因渲染出来
    await waitFor(() => expect(mockGetTicket).toHaveBeenCalledTimes(2))
    expect((await screen.findAllByText('已关闭')).length).toBeGreaterThan(0)
    expect(screen.getByText('关闭时间')).toBeInTheDocument()
    expect(screen.getByText('关闭原因')).toBeInTheDocument()
    expect(screen.getByText('重复工单，线下已处理')).toBeInTheDocument()
    // 已关闭为终态：不再显示任何状态操作入口
    expect(screen.queryByRole('button', { name: '关闭工单' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '接受处理' })).not.toBeInTheDocument()
  })

  it('pending 工单在确认弹窗点取消：不下发状态更新、工单保持待处理', async () => {
    const user = userEvent.setup()
    render(<AfterSalesDetailPage />)

    await user.click(await screen.findByRole('button', { name: '关闭工单' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: '取消' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(mockUpdateTicketStatus).not.toHaveBeenCalled()
    expect(mockGetTicket).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: '接受处理' })).toBeInTheDocument()
  })

  // issue #3686：来源三值都要有中文标签（旧实现只认 customer/agent，merchant 会渲染成 '-'）
  it.each([
    ['customer', '客户提交'],
    ['agent', '客服创建'],
    ['merchant', '商家创建'],
  ])('来源 %s 渲染为「%s」（无 - 回退）', async (source, label) => {
    mockGetTicket.mockResolvedValue({ data: { data: { ...mockTicket, source } } })

    render(<AfterSalesDetailPage />)

    const sourceRow = (await screen.findByText('来源')).parentElement as HTMLElement
    expect(within(sourceRow).getByText(label)).toBeInTheDocument()
  })
})
