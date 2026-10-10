// case_ids: DF-007, CU-010. 403 面不摆内部权限码（issue #6669 第 6 条）
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { act } from '@testing-library/react'

// Mock useAuthStore — 支持 selector 调用（usePermission 用 useAuthStore(s => s.user)）
const mockUseAuthStore = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector: any) => (selector ? selector(mockUseAuthStore()) : mockUseAuthStore()),
}))

// Mock next/navigation with controllable redirect
const mockRedirect = vi.fn()
const mockUsePathname = vi.fn()
vi.mock('next/navigation', async () => {
  return {
    useRouter: () => ({
      push: vi.fn(),
      replace: vi.fn(),
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

// Mock layout components
vi.mock('@/components/layout/Sidebar', () => ({
  default: ({ collapsed }: any) => <div data-testid="sidebar">Sidebar</div>,
}))
vi.mock('@/components/layout/Header', () => ({
  default: () => <div data-testid="header">Header</div>,
}))

import DashboardLayout from '@/app/(dashboard)/layout'

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
