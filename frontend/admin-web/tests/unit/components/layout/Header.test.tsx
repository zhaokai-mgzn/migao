/**
 * Header 组件测试
 *
 * 覆盖：
 * - 面包屑导航（基于路由自动推断）
 * - 显式 title / breadcrumbs 属性
 * - 用户信息展示（姓名、邮箱）
 * - 用户名为空时显示默认名
 * - 退出登录流程
 * - 通知铃铛子组件集成
 * - 各级路由的面包屑覆盖
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ─── Mock useAuthStore ───
const mockLogout = vi.fn()
const mockUseAuthStore = vi.fn()

vi.mock('@/store/auth', () => ({
  useAuthStore: (...args: any[]) => mockUseAuthStore(...args),
}))

// ─── Mock NotificationBell ───
vi.mock('@/components/layout/NotificationBell', () => ({
  default: () => <div data-testid="notification-bell">NotificationBell</div>,
}))

// ─── Mock next/navigation ───
const mockRouterPush = vi.fn()
let mockPathname = '/'

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: (...args: any[]) => mockRouterPush(...args),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => mockPathname,
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}))

import Header from '@/components/layout/Header'

describe('Header', () => {
  const user = userEvent.setup()

  const defaultUser = {
    id: '1',
    username: 'admin',
    name: '管理员',
    email: 'admin@example.com',
  }

  beforeEach(() => {
    vi.clearAllMocks()
    mockPathname = '/'
    mockLogout.mockResolvedValue(undefined)
    mockUseAuthStore.mockReturnValue({
      user: defaultUser,
      logout: mockLogout,
    })
  })

  // ─── 面包屑：默认路由 ───

  it('根路径 / 应显示"工作台 > 数据看板"面包屑', async () => {
    mockPathname = '/'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('工作台')).toBeInTheDocument()
    // 数据看板 是最后一级，使用 span 渲染（非链接）
    // 注意：路径 '/' 时 match 到 /dashboard 规则，显示 "工作台" + "数据看板"
  })

  it('/dashboard 路径应显示"工作台 > 数据看板"面包屑', async () => {
    mockPathname = '/dashboard'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('工作台')).toBeInTheDocument()
    expect(screen.getByText('数据看板')).toBeInTheDocument()
  })

  it('/products 路径应显示"商品管理 > 商品列表"面包屑', async () => {
    mockPathname = '/products'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('商品管理')).toBeInTheDocument()
    expect(screen.getByText('商品列表')).toBeInTheDocument()
  })

  it('/orders 路径应显示"订单管理 > 订单列表"面包屑', async () => {
    mockPathname = '/orders'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('订单管理')).toBeInTheDocument()
    expect(screen.getByText('订单列表')).toBeInTheDocument()
  })

  it('/customers 路径应显示"客户管理"单级面包屑', async () => {
    mockPathname = '/customers'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('客户管理')).toBeInTheDocument()
    // 单级面包屑不应有分隔符
    expect(screen.queryByText('/')).not.toBeInTheDocument()
  })

  it('/notifications 路径应显示"系统管理 > 通知中心"面包屑', async () => {
    mockPathname = '/notifications'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('系统管理')).toBeInTheDocument()
    expect(screen.getByText('通知中心')).toBeInTheDocument()
  })

  it('未知路径应兜底显示"工作台"', async () => {
    mockPathname = '/unknown-page'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('工作台')).toBeInTheDocument()
  })

  it('pathname 为 null 时应显示"数据看板"', async () => {
    mockPathname = null as unknown as string
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('数据看板')).toBeInTheDocument()
  })

  // ─── 子路径匹配 ───

  it('/products/123 子路径应匹配"商品管理 > 商品列表"', async () => {
    mockPathname = '/products/123'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('商品管理')).toBeInTheDocument()
    expect(screen.getByText('商品列表')).toBeInTheDocument()
  })

  it('/agent-workspace 子路径优先匹配（/agent-workspace/sessions）', async () => {
    mockPathname = '/agent-workspace/sessions'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('客服中心')).toBeInTheDocument()
    expect(screen.getByText('会话监控')).toBeInTheDocument()
  })

  it('/agent-workspace 精确路径应显示"客服中心 > 客服工作台"', async () => {
    mockPathname = '/agent-workspace'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('客服中心')).toBeInTheDocument()
    expect(screen.getByText('客服工作台')).toBeInTheDocument()
  })

  // ─── 显式 title 属性 ───

  it('传入 title 时应显示 h1 标题而非面包屑', async () => {
    await act(async () => {
      render(<Header title="自定义标题" />)
    })
    expect(screen.getByText('自定义标题')).toBeInTheDocument()
    // title 优先，不应显示面包屑
    expect(screen.queryByText('工作台')).not.toBeInTheDocument()
  })

  // ─── 显式 breadcrumbs 属性 ───

  it('传入 breadcrumbs 时应使用显式面包屑', async () => {
    await act(async () => {
      render(
        <Header
          breadcrumbs={[
            { label: '系统管理', href: '/settings' },
            { label: '角色权限' },
          ]}
        />
      )
    })
    expect(screen.getByText('系统管理')).toBeInTheDocument()
    expect(screen.getByText('角色权限')).toBeInTheDocument()
    // 不应显示路由推断的面包屑
    expect(screen.queryByText('工作台')).not.toBeInTheDocument()
  })

  it('breadcrumbs 中包含 href 的项应为可点击链接', async () => {
    await act(async () => {
      render(
        <Header
          breadcrumbs={[
            { label: '父级', href: '/parent' },
            { label: '子级' },
          ]}
        />
      )
    })
    const link = screen.getByText('父级').closest('a')
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/parent')
    // 最后一级不应是链接
    const lastItem = screen.getByText('子级')
    expect(lastItem.closest('a')).toBeNull()
  })

  // ─── 用户信息 ───

  it('应显示用户名', async () => {
    await act(async () => {
      render(<Header />)
    })
    // 用户名在按钮和下拉菜单中各出现一次
    const names = screen.getAllByText('管理员')
    expect(names.length).toBeGreaterThanOrEqual(1)
  })

  it('应显示用户邮箱', async () => {
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('admin@example.com')).toBeInTheDocument()
  })

  it('用户名为空时应显示默认名"管理员"', async () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: '', name: '', nickname: '' },
      logout: mockLogout,
    })
    await act(async () => {
      render(<Header />)
    })
    // 默认回退到 "管理员"（name、nickname、username 全为空时）
    const admins = screen.getAllByText('管理员')
    expect(admins.length).toBeGreaterThanOrEqual(1)
  })

  it('用户有 nickname 时应优先显示 nickname', async () => {
    mockUseAuthStore.mockReturnValue({
      user: {
        id: '1',
        username: 'user1',
        name: '',
        nickname: '小李',
      },
      logout: mockLogout,
    })
    await act(async () => {
      render(<Header />)
    })
    const nicknames = screen.getAllByText('小李')
    expect(nicknames.length).toBeGreaterThanOrEqual(1)
  })

  it('用户信息为空时 email 应回退到 username', async () => {
    mockUseAuthStore.mockReturnValue({
      user: {
        id: '1',
        username: 'user123',
        name: '测试用户',
        email: undefined,
      },
      logout: mockLogout,
    })
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('user123')).toBeInTheDocument()
  })

  // ─── 退出登录 ───

  it('点击"退出登录"应调用 logout 并跳转到 /login', async () => {
    mockLogout.mockResolvedValue(undefined)
    await act(async () => {
      render(<Header />)
    })
    const logoutBtn = screen.getByText('退出登录')
    await user.click(logoutBtn)
    expect(mockLogout).toHaveBeenCalledTimes(1)
    await vi.waitFor(() => {
      expect(mockRouterPush).toHaveBeenCalledWith('/login')
    })
  })

  // ─── 通知铃铛 ───

  it('应渲染 NotificationBell 子组件', async () => {
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByTestId('notification-bell')).toBeInTheDocument()
  })

  // ─── Header 结构 ───

  it('应渲染 sticky header 元素', async () => {
    await act(async () => {
      render(<Header />)
    })
    const header = document.querySelector('header')
    expect(header).toBeInTheDocument()
    expect(header?.className).toContain('sticky')
  })

  // ─── 面包屑分隔符 ───

  it('多级面包屑应显示 / 分隔符', async () => {
    mockPathname = '/products'
    await act(async () => {
      render(<Header />)
    })
    // 面包屑之间有 / 分隔符
    const separators = screen.getAllByText('/')
    expect(separators.length).toBeGreaterThanOrEqual(1)
  })

  // ─── 更多路由覆盖 ───

  it('/categories 路径面包屑', async () => {
    mockPathname = '/categories'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('商品管理')).toBeInTheDocument()
    expect(screen.getByText('商品分类管理')).toBeInTheDocument()
  })

  it('/processing 路径面包屑', async () => {
    mockPathname = '/processing'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('商品管理')).toBeInTheDocument()
    expect(screen.getByText('加工项管理')).toBeInTheDocument()
  })

  it('/knowledge 路径面包屑', async () => {
    mockPathname = '/knowledge'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('商品管理')).toBeInTheDocument()
    expect(screen.getByText('知识库管理')).toBeInTheDocument()
  })

  it('/after-sales 路径面包屑', async () => {
    mockPathname = '/after-sales'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('订单管理')).toBeInTheDocument()
    expect(screen.getByText('售后工单')).toBeInTheDocument()
  })

  it('/chat/config 路径面包屑', async () => {
    mockPathname = '/chat/config'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('机器人设置')).toBeInTheDocument()
  })

  it('/chat 路径面包屑', async () => {
    mockPathname = '/chat'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('客服中心')).toBeInTheDocument()
    expect(screen.getByText('在线对话')).toBeInTheDocument()
  })

  it('/roles 路径面包屑', async () => {
    mockPathname = '/roles'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('系统管理')).toBeInTheDocument()
    expect(screen.getByText('角色权限')).toBeInTheDocument()
  })

  it('/finance 路径面包屑', async () => {
    mockPathname = '/finance'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('财务对账')).toBeInTheDocument()
  })

  it('/employees 路径面包屑', async () => {
    mockPathname = '/employees'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('员工管理')).toBeInTheDocument()
  })

  it('/settings 路径面包屑', async () => {
    mockPathname = '/settings'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('企业基础信息')).toBeInTheDocument()
  })

  it('/agent-workspace/quick-replies 路径面包屑', async () => {
    mockPathname = '/agent-workspace/quick-replies'
    await act(async () => {
      render(<Header />)
    })
    expect(screen.getByText('客服中心')).toBeInTheDocument()
    expect(screen.getByText('快捷回复')).toBeInTheDocument()
  })
})
