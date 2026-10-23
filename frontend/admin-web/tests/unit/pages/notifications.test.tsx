// case_ids: ST-004, CU-010
// 追加（issue #6669 第 5 条）：通知页「全部标记已读」在飞行态 + 无未读不出入口。
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// Mock API
const mockGetNotifications = vi.fn()
const mockMarkAllAsRead = vi.fn()
const mockMarkAsRead = vi.fn()

// Mock 导航（#7524：点开通知要能跳到单据页 —— 断言 push 的**稳定**引用）
const mockRouterPush = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: (...args: any[]) => mockRouterPush(...args),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/notifications',
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('@/lib/api', () => ({
  notificationApi: {
    getNotifications: (...args: any[]) => mockGetNotifications(...args),
    markAllAsRead: (...args: any[]) => mockMarkAllAsRead(...args),
    markAsRead: (...args: any[]) => mockMarkAsRead(...args),
    deleteNotification: vi.fn(),
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
  Modal: ({ open, title, children, footer }: any) =>
    open ? (
      <div data-testid="modal" role="dialog">
        <h2>{title}</h2>
        {children}
        <div data-testid="modal-footer">{footer}</div>
      </div>
    ) : null,
  Button: ({ children, onClick, ...props }: any) => (
    <button onClick={onClick} {...props}>{children}</button>
  ),
  }
})

// Mock utils
vi.mock('@/lib/utils', () => ({
  cn: (...classes: any[]) => classes.filter(Boolean).join(' '),
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
    Bell: stub('bell'),
    CheckCheck: stub('check-check'),
    Trash2: stub('trash2'),
    Mail: stub('mail'),
    MailOpen: stub('mail-open'),
    Inbox: stub('inbox'),
  }
})

import NotificationsPage from '@/app/(dashboard)/notifications/page'

describe('NotificationsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetNotifications.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: '1', title: '新的订单通知', content: '您有一个新订单', channel: 'internal', status: 'sent', createdAt: '2026-06-22T10:00:00' },
            { id: '2', title: '系统维护通知', content: '系统将于今晚维护', channel: 'internal', status: 'read', createdAt: '2026-06-21T10:00:00' },
          ],
          total: 2,
        },
      },
    })
  })

  it('renders page title', () => {
    render(<NotificationsPage />)
    expect(screen.getByText('通知中心')).toBeInTheDocument()
  })

  it('renders mark all as read button', async () => {
    render(<NotificationsPage />)
    // 修后形态（issue #6669 第 5 条）：按钮**按未读数**出现 ⇒ 先等列表加载完
    expect(await screen.findByTestId('mark-all-read')).toBeInTheDocument()
  })

  /**
   * 🔴 issue #7180（2026-10-18 用户报障，截图红框）：图标**不得再用叠置的双勾字形**。
   *
   * 病灶：`<CheckCheck />`（lucide 双勾 = 两条 path 叠在一起）在 16px 下被读成「两个图标重叠」。
   * 判据钉在**字形**上（`lucide-check` vs `lucide-check-check`）：退回双勾 ⇒ 当场红。
   */
  it('全部标记已读的图标是单勾（不是叠置双勾）—— issue #7180', async () => {
    render(<NotificationsPage />)
    const btn = await screen.findByTestId('mark-all-read')
    const icon = btn.querySelector('svg, [data-testid^="icon-"]') as HTMLElement | null
    // 🔴 弱断言收口（#7198 同批，解除 required 检查 `ci workflow helper unit tests` 的阻塞）：
    // 语义存在性断言替代 `not.toBeNull()`（后者只证明「取到了个东西」）。
    expect(icon, '按钮必须带图标').toBeInTheDocument()
    expect(icon?.getAttribute('class') ?? '', '不得再用双勾字形（读成图标重叠）').not.toMatch(/check-check/i)
    expect(icon?.getAttribute('class') ?? '', '图标是单勾').toMatch(/check/i)
  })

  /**
   * 🔴 issue #6669 第 5 条：修前「全部标记已读」**没有 in-flight 闸** —— 连点两次就发两次请求，
   * 商家看到的是随机的成功/失败。判据 = 请求**未落地期间**按钮 disabled，且第二次点击不发第二个请求。
   *
   * 红证（修前形态）：去掉 `disabled={markingAll}` / `if (markingAll) return` ⇒ 第二次点击后
   * `markAllAsRead` 被调 **2 次** ⇒ `toHaveBeenCalledTimes(1)` 当场红。
   */
  it('全部标记已读：在飞行态禁用 + 连点不发第二次请求', async () => {
    let resolveMark: (v: unknown) => void = () => {}
    mockMarkAllAsRead.mockImplementation(
      () => new Promise((resolve) => { resolveMark = resolve }),
    )
    render(<NotificationsPage />)
    const btn = await screen.findByTestId('mark-all-read')
    fireEvent.click(btn)
    await waitFor(() => expect(mockMarkAllAsRead).toHaveBeenCalledTimes(1))
    expect(btn).toBeDisabled()
    fireEvent.click(btn)
    fireEvent.click(btn)
    expect(mockMarkAllAsRead).toHaveBeenCalledTimes(1)

    resolveMark({ data: { success: true } })
    await waitFor(() => expect(btn).not.toBeDisabled())
  })

  /**
   * 🔴 issue #6669 第 5 条（负控 + 出口）：一条未读都没有 ⇒ 这个动作无意义 ⇒ **不出入口**。
   * 红证：把 `{unreadCount > 0 && …}` 的条件去掉（恒渲染）⇒ 本条红。
   */
  it('没有未读通知时不出「全部标记已读」入口（不留点了没反应的按钮）', async () => {
    mockGetNotifications.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: 'r1', title: '已读通知', content: 'x', channel: 'internal', status: 'read', createdAt: '2026-06-22T10:00:00' },
          ],
          total: 1,
        },
      },
    })
    render(<NotificationsPage />)
    expect(await screen.findByText('已读通知')).toBeInTheDocument()
    expect(screen.queryByTestId('mark-all-read')).not.toBeInTheDocument()
  })

  it('renders status tabs', () => {
    render(<NotificationsPage />)
    expect(screen.getByText('全部')).toBeInTheDocument()
    expect(screen.getByText('未读')).toBeInTheDocument()
    expect(screen.getByText('已读')).toBeInTheDocument()
  })

  it('loads and displays notifications', async () => {
    render(<NotificationsPage />)
    await waitFor(() => {
      expect(mockGetNotifications).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.getByText('新的订单通知')).toBeInTheDocument()
      expect(screen.getByText('系统维护通知')).toBeInTheDocument()
    })
  })

  it('shows empty state when no notifications', () => {
    mockGetNotifications.mockResolvedValue({
      data: { data: { items: [], total: 0 } },
    })
    render(<NotificationsPage />)
    expect(screen.getByText('通知中心')).toBeInTheDocument()
  })

  it('renders pagination when data exists', async () => {
    render(<NotificationsPage />)
    await waitFor(() => {
      expect(screen.getByTestId('pagination')).toBeInTheDocument()
    })
  })

  // ─── #7524 结构化通知：按业务类型筛 + 点开回到单据 ───

  it('#7524 按业务类型筛：选「入库单」⇒ 请求带 bizType=inbound_order（且回到第 1 页）', async () => {
    render(<NotificationsPage />)
    await waitFor(() => expect(mockGetNotifications).toHaveBeenCalled())

    fireEvent.change(screen.getByLabelText('按业务类型筛选'), { target: { value: 'inbound_order' } })

    await waitFor(() =>
      expect(mockGetNotifications).toHaveBeenCalledWith(
        expect.objectContaining({ bizType: 'inbound_order', page: 1 }),
      ),
    )
  })

  it('#7524 有落地页的通知：点开先标已读、再跳到单据页；无落地页的不跳', async () => {
    mockMarkAsRead.mockResolvedValue({ data: {} })
    mockGetNotifications.mockResolvedValue({
      data: {
        data: {
          items: [
            {
              id: '1',
              title: '入库单 RK-20261023-0001 已过账',
              content: '供应商 ××布行，共 1 行、入库 30 米',
              channel: 'internal',
              status: 'sent',
              bizType: 'inbound_order',
              bizNo: 'RK-20261023-0001',
              targetPath: '/inbound-orders?keyword=RK-20261023-0001',
              severity: 'info',
              createdAt: '2026-10-23T10:00:00',
            },
            {
              id: '2',
              title: '系统维护通知',
              content: '系统将于今晚维护',
              channel: 'internal',
              status: 'sent',
              createdAt: '2026-10-23T09:00:00',
            },
          ],
          total: 2,
        },
      },
    })

    render(<NotificationsPage />)
    fireEvent.click(await screen.findByTestId('notification-item-1'))
    await waitFor(() => expect(mockMarkAsRead).toHaveBeenCalledWith('1'))
    await waitFor(() => expect(mockRouterPush).toHaveBeenCalledWith('/inbound-orders?keyword=RK-20261023-0001'))

    // 负控：没有 targetPath 的老通知点开不跳转（不假装可点）
    fireEvent.click(screen.getByTestId('notification-item-2'))
    await waitFor(() => expect(mockMarkAsRead).toHaveBeenCalledWith('2'))
    expect(mockRouterPush).toHaveBeenCalledTimes(1)
  })
})
