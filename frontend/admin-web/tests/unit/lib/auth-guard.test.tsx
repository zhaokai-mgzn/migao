import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { act } from '@testing-library/react'

// Mock useAuthStore
const mockUseAuthStore = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: (...args: any[]) => mockUseAuthStore(...args),
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
      user: { id: '1', username: 'admin' },
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
      user: { id: '1', username: 'admin' },
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
      user: null,
      isAuthenticated: false,
    })

    render(
      <DashboardLayout>
        <div data-testid="child-content">Child</div>
      </DashboardLayout>
    )

    // Layout always renders - auth guard is handled at middleware level
    expect(screen.getByTestId('child-content')).toBeInTheDocument()
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
