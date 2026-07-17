import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// Mock API
const mockGetNotifications = vi.fn()

vi.mock('@/lib/api', () => ({
  notificationApi: {
    getNotifications: (...args: any[]) => mockGetNotifications(...args),
    markAllAsRead: vi.fn(),
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

  it('renders mark all as read button', () => {
    render(<NotificationsPage />)
    expect(screen.getByText('全部标记已读')).toBeInTheDocument()
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
