// case_ids: ST-004, CU-010
// 追加（issue #6669 第 5 条）：通知页「全部标记已读」在飞行态 + 无未读不出入口。
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// Mock API
const mockGetNotifications = vi.fn()
const mockMarkAllAsRead = vi.fn()

vi.mock('@/lib/api', () => ({
  notificationApi: {
    getNotifications: (...args: any[]) => mockGetNotifications(...args),
    markAllAsRead: (...args: any[]) => mockMarkAllAsRead(...args),
    markAsRead: vi.fn(),
    deleteNotification: vi.fn(),
  },
}))

// Mock UI components
vi.mock('@/components/ui', () => ({
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
}))

// Mock utils
vi.mock('@/lib/utils', () => ({
  cn: (...classes: any[]) => classes.filter(Boolean).join(' '),
}))

// Mock lucide-react
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
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
})
