import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// Mock useAuthStore
const mockUseAuthStore = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: (...args: any[]) => mockUseAuthStore(...args),
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock lucide-react
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    ClipboardList: stub('clipboard'),
    Users: stub('users'),
    MessageSquare: stub('message'),
    DollarSign: stub('dollar'),
    Plus: stub('plus'),
    FileUp: stub('fileup'),
    CalendarDays: stub('calendar'),
  }
})

// Mock recharts (used in dashboard charts)
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: any) => <div data-testid="chart-container">{children}</div>,
  LineChart: ({ children }: any) => <div data-testid="line-chart">{children}</div>,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  Legend: () => null,
  PieChart: ({ children }: any) => <div data-testid="pie-chart">{children}</div>,
  Pie: () => null,
  Cell: () => null,
}))

// Mock dashboard components
vi.mock('@/components/dashboard/StatCard', () => ({
  default: ({ title, value }: any) => (
    <div data-testid={`stat-card-${title}`}>
      <span>{title}</span>
      <span>{value}</span>
    </div>
  ),
}))

vi.mock('@/components/dashboard/OrderTrendChart', () => ({
  default: ({ data, loading }: any) => (
    <div data-testid="order-trend-chart">{loading ? 'Loading...' : `${data.length} points`}</div>
  ),
}))

vi.mock('@/components/dashboard/OrderStatusChart', () => ({
  default: ({ data, loading }: any) => (
    <div data-testid="order-status-chart">{loading ? 'Loading...' : `${data.length} statuses`}</div>
  ),
}))

vi.mock('@/components/dashboard/RecentOrders', () => ({
  default: ({ orders, loading }: any) => (
    <div data-testid="recent-orders">{loading ? 'Loading...' : `${orders.length} orders`}</div>
  ),
}))

vi.mock('@/components/dashboard/ActiveSessions', () => ({
  default: ({ sessions, loading }: any) => (
    <div data-testid="active-sessions">{loading ? 'Loading...' : `${sessions.length} sessions`}</div>
  ),
}))

import DashboardPage from '@/app/(dashboard)/dashboard/page'

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: 'admin', name: '管理员' },
    })
  })

  it('should render welcome message with user name', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText(/欢迎回来，管理员/)).toBeInTheDocument()
    })
  })

  it('should render welcome message with fallback for anonymous user', async () => {
    mockUseAuthStore.mockReturnValue({ user: null })
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText(/欢迎回来，管理员/)).toBeInTheDocument()
    })
  })

  it('should render quick action links', () => {
    render(<DashboardPage />)
    expect(screen.getByText('新建订单')).toBeInTheDocument()
    expect(screen.getByText('上传文档')).toBeInTheDocument()
  })

  it('should show loading skeleton initially', () => {
    render(<DashboardPage />)
    // Charts should show loading initially
    expect(screen.getByTestId('order-trend-chart')).toHaveTextContent('Loading...')
    expect(screen.getByTestId('order-status-chart')).toHaveTextContent('Loading...')
  })

  it('should load dashboard data after mount', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByTestId('order-trend-chart')).not.toHaveTextContent('Loading...')
    }, { timeout: 2000 })
  })

  it('should render stat cards after loading', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByTestId('stat-card-今日订单')).toBeInTheDocument()
      expect(screen.getByTestId('stat-card-客户总数')).toBeInTheDocument()
      expect(screen.getByTestId('stat-card-活跃会话')).toBeInTheDocument()
      expect(screen.getByTestId('stat-card-本月收入')).toBeInTheDocument()
    }, { timeout: 2000 })
  })

  it('should render chart components', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByTestId('order-trend-chart')).toBeInTheDocument()
      expect(screen.getByTestId('order-status-chart')).toBeInTheDocument()
    })
  })

  it('should render recent orders and active sessions', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByTestId('recent-orders')).toBeInTheDocument()
      expect(screen.getByTestId('active-sessions')).toBeInTheDocument()
    })
  })

  it('should display formatted date', () => {
    render(<DashboardPage />)
    // The date string should contain the year
    expect(screen.getByText(/2026年/)).toBeInTheDocument()
  })

  it('should link to orders page', () => {
    render(<DashboardPage />)
    const link = screen.getByText('新建订单').closest('a')
    expect(link).toHaveAttribute('href', '/orders')
  })

  it('should link to knowledge page', () => {
    render(<DashboardPage />)
    const link = screen.getByText('上传文档').closest('a')
    expect(link).toHaveAttribute('href', '/knowledge')
  })
})
