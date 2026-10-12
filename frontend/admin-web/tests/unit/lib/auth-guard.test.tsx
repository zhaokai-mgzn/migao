// case_ids: DF-007, CU-010
// 追加（issue #6669 第 6 条）：403 面不摆内部权限码。
// 追加（issue #6758）：① 登录落点按**权限**算（复用 `@/lib/menu-nav` 的可见菜单单点实现，
//   不再是硬编码 `/dashboard`）；② 403 只替换**主内容区**、保留 Sidebar/Header 外壳
//   （缺 `dashboard:view` 的客服账号仍有导航出口）。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { act } from '@testing-library/react'

// Mock useAuthStore — 支持 selector 调用（usePermission 用 useAuthStore(s => s.user)）
const mockUseAuthStore = vi.fn()
vi.mock('@/store/auth', () => {
  const useAuthStore: any = (selector: any) => (selector ? selector(mockUseAuthStore()) : mockUseAuthStore())
  // issue #6758：登录落点必须从 store **现取** user —— 登录刚返回时组件渲染闭包里的 `user`
  // 还是登录前那一份（store 的 set 尚未触发重渲染），拿它算落点会算出空权限 ⇒ 又回到 /dashboard。
  useAuthStore.getState = () => mockUseAuthStore()
  return { useAuthStore }
})

// Mock next/navigation with controllable redirect
const mockRedirect = vi.fn()
const mockReplace = vi.fn()
const mockPush = vi.fn()
const mockUsePathname = vi.fn()
vi.mock('next/navigation', async () => {
  return {
    useRouter: () => ({
      push: mockPush,
      replace: mockReplace,
      back: vi.fn(),
      forward: vi.fn(),
      refresh: vi.fn(),
      prefetch: vi.fn(),
    }),
    usePathname: () => mockUsePathname(),
    useSearchParams: () => new URLSearchParams(),
    useParams: () => ({}),
    redirect: (...args: any[]) => mockRedirect(...args),
    notFound: vi.fn(),
  }
})

// 登录页用 `authApi.sendSmsCode`；其余导出保持**真实**（别把别人的导出抹成 undefined）
vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<any>()),
  authApi: { sendSmsCode: vi.fn(), employeeLogin: vi.fn(), smsLogin: vi.fn() },
}))

// Mock layout components
vi.mock('@/components/layout/Sidebar', () => ({
  default: ({ collapsed }: any) => <div data-testid="sidebar">Sidebar</div>,
}))
vi.mock('@/components/layout/Header', () => ({
  default: () => <div data-testid="header">Header</div>,
}))

import DashboardLayout from '@/app/(dashboard)/layout'
import LoginPage from '@/app/login/page'
import { AuthGuard } from '@/components/auth-guard'

describe('Auth Guard (Dashboard Layout)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUsePathname.mockReturnValue('/dashboard')
  })

  it('should render children when authenticated', () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: 'admin', roles: ['admin'], permissions: ['*'] },
      isAuthenticated: true,
    })

    render(
      <DashboardLayout>
        <div data-testid="protected-content">Protected Content</div>
      </DashboardLayout>
    )

    expect(screen.getByTestId('protected-content')).toBeInTheDocument()
    expect(screen.getByTestId('sidebar')).toBeInTheDocument()
    expect(screen.getByTestId('header')).toBeInTheDocument()
  })

  it('should render layout structure with sidebar and header', () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: 'admin', roles: ['admin'], permissions: ['*'] },
      isAuthenticated: true,
    })

    render(
      <DashboardLayout>
        <div>Page Content</div>
      </DashboardLayout>
    )

    expect(screen.getByTestId('sidebar')).toBeInTheDocument()
    expect(screen.getByTestId('header')).toBeInTheDocument()
  })

  it('should render the main content area', () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: 'admin', roles: ['admin'], permissions: ['*'] },
      isAuthenticated: true,
    })

    render(
      <DashboardLayout>
        <div data-testid="child-content">Child</div>
      </DashboardLayout>
    )

    expect(screen.getByTestId('child-content')).toBeInTheDocument()
  })

  it('should show 403 panel when user lacks route permission', () => {
    mockUsePathname.mockReturnValue('/employees')
    mockUseAuthStore.mockReturnValue({
      user: { id: '2', username: 'operator', roles: ['operator'], permissions: ['dashboard:view'] },
      isAuthenticated: true,
    })

    render(
      <DashboardLayout>
        <div data-testid="child-content">Child</div>
      </DashboardLayout>
    )

    // 路由级权限守卫（第二道防线）：无 employee:list 时渲染 403 而非子内容
    expect(screen.queryByTestId('child-content')).not.toBeInTheDocument()
    expect(screen.getByText(/无权访问该页面/)).toBeInTheDocument()
    // 🔴 issue #6669 第 6 条：**权限码不上商家屏**（修前这里逐字断言 `employee:list` 出现在页面上，
    // 那正是被本包撤掉的「不摆内部标识」形态 —— 判定仍用权限码，但显示只说人话）。
    expect(screen.queryByText('employee:list')).not.toBeInTheDocument()
    expect(screen.getByText(/你的岗位没有这个功能的权限/)).toBeInTheDocument()
    expect(screen.getByText(/员工管理/)).toBeInTheDocument()
    // 🔴 issue #6758：403 **不再是死路** —— 只替换主内容区，外壳（侧边栏 / Header）必须还在，
    // 否则「缺 dashboard:view 的客服账号」整页只剩一张卡片、没有任何导航出口（只能手输 URL）。
    // 真 Sidebar（`data-menu-key` 可取到）的渲染面判据见
    // tests/unit/components/dashboard-layout-403-shell.test.tsx。
    expect(screen.getByTestId('sidebar')).toBeInTheDocument()
    expect(screen.getByTestId('header')).toBeInTheDocument()
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// issue #6758：登录落点按**权限**算
// ══════════════════════════════════════════════════════════════════════════════
/** 客服岗位（种子 `customer_service`）：**不含** `dashboard:view`，含客服全套 4 码 */
const CUSTOMER_SERVICE_PERMISSIONS = ['agent:session', 'knowledge:view', 'after_sales:view', 'customer:view']
const CUSTOMER_SERVICE_USER = {
  id: '9',
  username: 'kefu',
  name: '客服小王',
  roles: ['customer_service'],
  permissions: CUSTOMER_SERVICE_PERMISSIONS,
}
/** 客服账号的第一个可见菜单项（菜单顺序单点实现 = `@/lib/menu-nav`） */
const FIRST_VISIBLE_PATH = '/agent-workspace/human-sessions'

describe('登录落点按权限算（issue #6758）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUsePathname.mockReturnValue('/login')
    window.history.pushState({}, '', '/login')
  })

  it('缺 dashboard:view、持客服码的账号登录 ⇒ 落第一个可见菜单项（不是 /dashboard）', async () => {
    const employeeLogin = vi.fn().mockResolvedValue({ mustChangePassword: false })
    mockUseAuthStore.mockReturnValue({
      user: CUSTOMER_SERVICE_USER,
      isAuthenticated: false,
      employeeLogin,
      smsLogin: vi.fn(),
    })

    render(<LoginPage />)
    fireEvent.change(screen.getByLabelText('账号'), { target: { value: 'kefu@migao' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'pw-123456' } })
    fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }))

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith(FIRST_VISIBLE_PATH))
    expect(employeeLogin).toHaveBeenCalledWith('kefu@migao', 'pw-123456')
    // 反向对照：硬编码落点当场判红
    expect(mockPush).not.toHaveBeenCalledWith('/dashboard')
  })

  it('显式 callbackUrl 仍优先于权限落点', async () => {
    window.history.pushState({}, '', '/login?callbackUrl=%2Forders')
    mockUseAuthStore.mockReturnValue({
      user: CUSTOMER_SERVICE_USER,
      isAuthenticated: false,
      employeeLogin: vi.fn().mockResolvedValue({ mustChangePassword: false }),
      smsLogin: vi.fn(),
    })

    render(<LoginPage />)
    fireEvent.change(screen.getByLabelText('账号'), { target: { value: 'kefu@migao' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'pw-123456' } })
    fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }))

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/orders'))
    expect(mockPush).not.toHaveBeenCalledWith(FIRST_VISIBLE_PATH)
  })

  it('零权限码账号 ⇒ 落到唯一无码项（通知中心 /notifications），不是 /dashboard 死页', async () => {
    // ⚠️ 现实菜单下**没有**「一个可见项都没有」的账号：通知中心（`/notifications`）无 `permissionCode`
    // ⇒ 恒可见。所以零权限账号的落点是 `/notifications`（一个真能打开的页面），而**不是** 403 死页。
    // `/dashboard` 的回落是 `landingPath` 的**防御分支**（连无码项都没有时才会走到）。
    mockUseAuthStore.mockReturnValue({
      user: { id: '10', username: 'none', roles: [], permissions: [] },
      isAuthenticated: false,
      employeeLogin: vi.fn().mockResolvedValue({ mustChangePassword: false }),
      smsLogin: vi.fn(),
    })

    render(<LoginPage />)
    fireEvent.change(screen.getByLabelText('账号'), { target: { value: 'none@migao' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'pw-123456' } })
    fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }))

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/notifications'))
    expect(mockPush).not.toHaveBeenCalledWith('/dashboard')
  })

  it('已登录访问 /login（auth-guard）⇒ 同样按权限落第一个可见菜单项', async () => {
    mockUseAuthStore.mockReturnValue({
      user: CUSTOMER_SERVICE_USER,
      isAuthenticated: true,
      _hasHydrated: true,
    })

    render(
      <AuthGuard>
        <div data-testid="guard-child">Child</div>
      </AuthGuard>
    )

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith(FIRST_VISIBLE_PATH))
    expect(mockReplace).not.toHaveBeenCalledWith('/dashboard')
  })
})

describe('Auth State Verification', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should expose isAuthenticated=false for unauthenticated users', () => {
    mockUseAuthStore.mockReturnValue({
      user: null,
      accessToken: null,
      isAuthenticated: false,
    })

    const state = mockUseAuthStore()
    expect(state.isAuthenticated).toBe(false)
    expect(state.user).toBeNull()
    expect(state.accessToken).toBeNull()
  })

  it('should expose isAuthenticated=true for authenticated users', () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: 'admin' },
      accessToken: 'valid-token',
      isAuthenticated: true,
    })

    const state = mockUseAuthStore()
    expect(state.isAuthenticated).toBe(true)
    expect(state.user).toBeDefined()
    expect(state.accessToken).toBe('valid-token')
  })

  it('should handle token expiry scenario', () => {
    mockUseAuthStore.mockReturnValue({
      user: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      clearAuth: vi.fn(),
    })

    const state = mockUseAuthStore()
    expect(state.isAuthenticated).toBe(false)
    expect(state.accessToken).toBeNull()
  })
})
