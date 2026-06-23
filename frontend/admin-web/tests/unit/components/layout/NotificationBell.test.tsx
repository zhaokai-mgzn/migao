/**
 * NotificationBell 组件测试
 *
 * 覆盖：
 * - 基础渲染（铃铛按钮、未读徽标）
 * - 下拉面板打开/关闭
 * - 通知列表（加载态、空态、列表态）
 * - 标记已读（单条 + 全部）
 * - 查看全部跳转
 * - 点击外部关闭
 * - 轮询未读数
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ─── Mock notification API ───
const mockGetUnreadCount = vi.fn()
const mockGetNotifications = vi.fn()
const mockMarkAsRead = vi.fn()
const mockMarkAllAsRead = vi.fn()

vi.mock('@/lib/api', () => ({
  notificationApi: {
    getUnreadCount: (...args: any[]) => mockGetUnreadCount(...args),
    getNotifications: (...args: any[]) => mockGetNotifications(...args),
    markAsRead: (...args: any[]) => mockMarkAsRead(...args),
    markAllAsRead: (...args: any[]) => mockMarkAllAsRead(...args),
  },
}))

// ─── Mock next/navigation ───
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
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}))

import NotificationBell from '@/components/layout/NotificationBell'

describe('NotificationBell', () => {
  const user = userEvent.setup()

  // 辅助工厂：创建模拟通知
  function createNotification(overrides: Record<string, unknown> = {}) {
    return {
      id: '1',
      tenantId: 1,
      recipientId: 'user-1',
      recipientType: 'user' as const,
      channel: 'internal' as const,
      title: '系统通知',
      content: '这是一条测试通知内容',
      status: 'pending' as const,
      retryCount: 0,
      createdAt: new Date().toISOString(),
      ...overrides,
    }
  }

  beforeEach(() => {
    vi.clearAllMocks()
    mockGetUnreadCount.mockResolvedValue({ data: { data: { count: 0 } } })
    mockGetNotifications.mockResolvedValue({
      data: { data: { items: [], total: 0, page: 1, size: 5 } },
    })
    mockMarkAsRead.mockResolvedValue({ data: {} })
    mockMarkAllAsRead.mockResolvedValue({ data: {} })
  })

  afterEach(() => {
    // 确保 fake timers 被清理
    try { vi.useRealTimers() } catch (_) { /* already real */ }
  })

  // ─── 基础渲染 ───

  it('应渲染铃铛按钮', () => {
    render(<NotificationBell />)
    expect(screen.getByTestId('icon-bell')).toBeInTheDocument()
  })

  it('挂载时应立即拉取未读数', async () => {
    render(<NotificationBell />)
    await waitFor(() => {
      expect(mockGetUnreadCount).toHaveBeenCalledTimes(1)
    })
  })

  // ─── 未读徽标 ───

  it('未读数为 0 时不显示徽标', async () => {
    render(<NotificationBell />)
    await waitFor(() => {
      expect(mockGetUnreadCount).toHaveBeenCalled()
    })
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  it('未读数大于 0 时显示未读徽标', async () => {
    mockGetUnreadCount.mockResolvedValue({ data: { data: { count: 3 } } })
    render(<NotificationBell />)
    await waitFor(() => {
      expect(screen.getByText('3')).toBeInTheDocument()
    })
  })

  it('未读数超过 99 时显示 99+', async () => {
    mockGetUnreadCount.mockResolvedValue({ data: { data: { count: 100 } } })
    render(<NotificationBell />)
    await waitFor(() => {
      expect(screen.getByText('99+')).toBeInTheDocument()
    })
  })

  it('未读数等于 99 时显示 99', async () => {
    mockGetUnreadCount.mockResolvedValue({ data: { data: { count: 99 } } })
    render(<NotificationBell />)
    await waitFor(() => {
      expect(screen.getByText('99')).toBeInTheDocument()
    })
  })

  // ─── 下拉面板打开/关闭 ───

  it('点击铃铛应打开下拉面板', async () => {
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('通知')).toBeInTheDocument()
    })
  })

  it('再次点击铃铛应关闭下拉面板', async () => {
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('通知')).toBeInTheDocument()
    })
    await user.click(bell)
    await waitFor(() => {
      expect(screen.queryByText('通知')).not.toBeInTheDocument()
    })
  })

  it('点击面板外部应关闭下拉面板', async () => {
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('通知')).toBeInTheDocument()
    })
    // 点击文档空白处触发 mousedown 关闭面板
    await user.click(document.body)
    await waitFor(() => {
      expect(screen.queryByText('通知')).not.toBeInTheDocument()
    })
  })

  // ─── 打开面板时拉取通知列表 ───

  it('打开面板时应自动拉取通知列表', async () => {
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(mockGetNotifications).toHaveBeenCalledWith({ page: 1, size: 5 })
    })
  })

  // ─── 加载态 ───

  it('加载通知列表时应显示 loading 动画', async () => {
    // 不 resolve，让 loading 保持
    mockGetNotifications.mockReturnValue(new Promise(() => {}))
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('通知')).toBeInTheDocument()
    })
    const spinner = document.querySelector('.animate-spin')
    expect(spinner).toBeInTheDocument()
  })

  // ─── 空状态 ───

  it('无通知时应显示暂无通知空状态', async () => {
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('暂无通知')).toBeInTheDocument()
    })
    expect(screen.getByTestId('icon-inbox')).toBeInTheDocument()
  })

  // ─── 通知列表 ───

  it('有通知时应渲染通知列表项', async () => {
    const notifications = [
      createNotification({ id: '1', title: '通知1', content: '内容1' }),
      createNotification({ id: '2', title: '通知2', content: '内容2' }),
    ]
    mockGetNotifications.mockResolvedValue({
      data: { data: { items: notifications, total: 2, page: 1, size: 5 } },
    })
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('通知1')).toBeInTheDocument()
      expect(screen.getByText('内容1')).toBeInTheDocument()
      expect(screen.getByText('通知2')).toBeInTheDocument()
      expect(screen.getByText('内容2')).toBeInTheDocument()
    })
  })

  it('未读通知应显示蓝色圆点和蓝色背景', async () => {
    const notifications = [
      createNotification({ id: '1', status: 'pending' }),
    ]
    mockGetNotifications.mockResolvedValue({
      data: { data: { items: notifications, total: 1, page: 1, size: 5 } },
    })
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      const dot = document.querySelector('.bg-blue-500')
      expect(dot).toBeInTheDocument()
    })
  })

  // ─── 标记单条已读 ───

  it('点击未读通知应调用 markAsRead', async () => {
    const notifications = [
      createNotification({ id: 'notif-1', status: 'pending' }),
    ]
    mockGetNotifications.mockResolvedValue({
      data: { data: { items: notifications, total: 1, page: 1, size: 5 } },
    })
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('系统通知')).toBeInTheDocument()
    })
    const item = screen.getByText('系统通知').closest('button')!
    await user.click(item)
    await waitFor(() => {
      expect(mockMarkAsRead).toHaveBeenCalledWith('notif-1')
    })
  })

  it('点击已读通知不应再次调用 markAsRead', async () => {
    const notifications = [
      createNotification({ id: 'notif-1', status: 'read' }),
    ]
    mockGetNotifications.mockResolvedValue({
      data: { data: { items: notifications, total: 1, page: 1, size: 5 } },
    })
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('系统通知')).toBeInTheDocument()
    })
    const item = screen.getByText('系统通知').closest('button')!
    await user.click(item)
    expect(mockMarkAsRead).not.toHaveBeenCalled()
  })

  // ─── 全部标记已读（面板头部按钮） ───

  it('面板头部"全部已读"按钮应调用 markAllAsRead', async () => {
    mockGetUnreadCount.mockResolvedValue({ data: { data: { count: 3 } } })
    mockGetNotifications.mockResolvedValue({
      data: { data: { items: [createNotification()], total: 1, page: 1, size: 5 } },
    })
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('全部已读')).toBeInTheDocument()
    })
    await user.click(screen.getByText('全部已读'))
    await waitFor(() => {
      expect(mockMarkAllAsRead).toHaveBeenCalled()
    })
  })

  it('未读数为 0 时面板头部不显示"全部已读"按钮', async () => {
    mockGetNotifications.mockResolvedValue({
      data: { data: { items: [createNotification()], total: 1, page: 1, size: 5 } },
    })
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('通知')).toBeInTheDocument()
    })
    expect(screen.queryByText('全部已读')).not.toBeInTheDocument()
  })

  // ─── 全部标记已读（底部操作栏按钮） ───

  it('底部"全部标记已读"按钮应调用 markAllAsRead', async () => {
    mockGetNotifications.mockResolvedValue({
      data: { data: { items: [createNotification()], total: 1, page: 1, size: 5 } },
    })
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('全部标记已读')).toBeInTheDocument()
    })
    await user.click(screen.getByText('全部标记已读'))
    await waitFor(() => {
      expect(mockMarkAllAsRead).toHaveBeenCalled()
    })
  })

  // ─── 查看全部跳转 ───

  it('点击"查看全部 →"应关闭面板并跳转到 /notifications', async () => {
    mockGetNotifications.mockResolvedValue({
      data: { data: { items: [createNotification()], total: 1, page: 1, size: 5 } },
    })
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('查看全部 →')).toBeInTheDocument()
    })
    await user.click(screen.getByText('查看全部 →'))
    expect(mockRouterPush).toHaveBeenCalledWith('/notifications')
    await waitFor(() => {
      expect(screen.queryByText('通知')).not.toBeInTheDocument()
    })
  })

  // ─── API 错误静默降级 ───

  it('获取未读数失败时应静默降级不抛出错误', async () => {
    mockGetUnreadCount.mockRejectedValue(new Error('Network error'))
    render(<NotificationBell />)
    await waitFor(() => {
      expect(screen.getByTestId('icon-bell')).toBeInTheDocument()
    })
  })

  it('获取通知列表失败时应静默降级', async () => {
    mockGetNotifications.mockRejectedValue(new Error('Network error'))
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('暂无通知')).toBeInTheDocument()
    })
  })

  it('标记已读失败时应静默降级', async () => {
    mockMarkAsRead.mockRejectedValue(new Error('Network error'))
    const notifications = [
      createNotification({ id: 'notif-1', status: 'pending' }),
    ]
    mockGetNotifications.mockResolvedValue({
      data: { data: { items: notifications, total: 1, page: 1, size: 5 } },
    })
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('系统通知')).toBeInTheDocument()
    })
    const item = screen.getByText('系统通知').closest('button')!
    await user.click(item)
    expect(mockMarkAsRead).toHaveBeenCalledWith('notif-1')
  })

  it('全部标记已读失败时应静默降级', async () => {
    mockMarkAllAsRead.mockRejectedValue(new Error('Network error'))
    mockGetNotifications.mockResolvedValue({
      data: { data: { items: [createNotification()], total: 1, page: 1, size: 5 } },
    })
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('全部标记已读')).toBeInTheDocument()
    })
    await user.click(screen.getByText('全部标记已读'))
    expect(mockMarkAllAsRead).toHaveBeenCalled()
  })

  // ─── 轮询 ───

  it('挂载后应启动轮询（每 30 秒拉取未读数）', () => {
    const setIntervalSpy = vi.spyOn(window, 'setInterval')
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval')

    const { unmount } = render(<NotificationBell />)

    expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 30_000)

    unmount()
    expect(clearIntervalSpy).toHaveBeenCalled()

    setIntervalSpy.mockRestore()
    clearIntervalSpy.mockRestore()
  })

  it('卸载时应清除轮询定时器', () => {
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval')

    const { unmount } = render(<NotificationBell />)

    // 此时 clearInterval 不应被调用
    expect(clearIntervalSpy).not.toHaveBeenCalled()

    unmount()
    expect(clearIntervalSpy).toHaveBeenCalled()

    clearIntervalSpy.mockRestore()
  })

  // ─── 相对时间格式化 ───

  it('应显示刚刚发布的通知为"刚刚"', async () => {
    const notifications = [
      createNotification({
        id: '1',
        createdAt: new Date().toISOString(),
      }),
    ]
    mockGetNotifications.mockResolvedValue({
      data: { data: { items: notifications, total: 1, page: 1, size: 5 } },
    })
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('刚刚')).toBeInTheDocument()
    })
  })

  // ─── 边界情况 ───

  it('API 返回 null items 时应显示空状态', async () => {
    mockGetNotifications.mockResolvedValue({
      data: { data: { items: null, total: 0, page: 1, size: 5 } },
    })
    render(<NotificationBell />)
    const bell = screen.getByTestId('icon-bell').closest('button')!
    await user.click(bell)
    await waitFor(() => {
      expect(screen.getByText('暂无通知')).toBeInTheDocument()
    })
  })

  it('API 返回 undefined count 时未读数应为 0', async () => {
    mockGetUnreadCount.mockResolvedValue({ data: { data: {} } })
    render(<NotificationBell />)
    await waitFor(() => {
      expect(mockGetUnreadCount).toHaveBeenCalled()
    })
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })
})
