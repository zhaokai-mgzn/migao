import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'

// Override next/navigation mock from setup.ts with controllable usePathname
const mockUsePathname = vi.fn()
vi.mock('next/navigation', () => ({
  usePathname: () => mockUsePathname(),
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock Logo component
vi.mock('@/components/ui/Logo', () => ({
  default: (props: any) => <span data-testid="logo" {...props} />,
}))

import PlatformSidebar from '@/components/platform/PlatformSidebar'

describe('PlatformSidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUsePathname.mockReturnValue('/registrations')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // ── 基础结构 ──

  it('should render logo', () => {
    render(<PlatformSidebar />)
    expect(screen.getByTestId('logo')).toBeInTheDocument()
  })

  it('should render brand title 米高', () => {
    render(<PlatformSidebar />)
    expect(screen.getByText('米高')).toBeInTheDocument()
  })

  it('should render subtitle 平台管理', () => {
    render(<PlatformSidebar />)
    expect(screen.getByText('平台管理')).toBeInTheDocument()
  })

  it('should render footer text', () => {
    render(<PlatformSidebar />)
    expect(screen.getByText('超级管理员专属')).toBeInTheDocument()
  })

  // ── 菜单项 ──

  it('should render 入驻审批 menu item', () => {
    render(<PlatformSidebar />)
    expect(screen.getByText('入驻审批')).toBeInTheDocument()
  })

  it('should render 平台概览 menu item with badge', () => {
    render(<PlatformSidebar />)
    expect(screen.getByText('平台概览')).toBeInTheDocument()
    expect(screen.getByText('即将上线')).toBeInTheDocument()
  })

  it('should render icons for menu items', () => {
    render(<PlatformSidebar />)
    expect(screen.getByTestId('icon-clipboard-check')).toBeInTheDocument()
    expect(screen.getByTestId('icon-layout-dashboard')).toBeInTheDocument()
  })

  // ── 导航链接 ──

  it('should have correct href for 入驻审批', () => {
    render(<PlatformSidebar />)
    const link = screen.getByText('入驻审批').closest('a')
    expect(link).toHaveAttribute('href', '/registrations')
  })

  it('should have correct href for 平台概览', () => {
    render(<PlatformSidebar />)
    const link = screen.getByText('平台概览').closest('a')
    expect(link).toHaveAttribute('href', '/platform-dashboard')
  })

  // ── 激活状态 ──

  it('should highlight 入驻审批 when on /registrations', () => {
    mockUsePathname.mockReturnValue('/registrations')
    render(<PlatformSidebar />)
    const link = screen.getByText('入驻审批').closest('a')!
    expect(link.className).toContain('bg-blue-50')
    expect(link.className).toContain('text-blue-700')
  })

  it('should highlight 平台概览 when on /platform-dashboard', () => {
    mockUsePathname.mockReturnValue('/platform-dashboard')
    render(<PlatformSidebar />)
    const link = screen.getByText('平台概览').closest('a')!
    expect(link.className).toContain('bg-blue-50')
    expect(link.className).toContain('text-blue-700')
  })

  it('should NOT highlight 入驻审批 when on /platform-dashboard', () => {
    mockUsePathname.mockReturnValue('/platform-dashboard')
    render(<PlatformSidebar />)
    const link = screen.getByText('入驻审批').closest('a')!
    expect(link.className).not.toContain('bg-blue-50')
    expect(link.className).toContain('text-gray-600')
  })

  it('should NOT highlight 平台概览 when on /registrations', () => {
    mockUsePathname.mockReturnValue('/registrations')
    render(<PlatformSidebar />)
    const link = screen.getByText('平台概览').closest('a')!
    expect(link.className).not.toContain('bg-blue-50')
    expect(link.className).toContain('text-gray-600')
  })

  // ── 嵌套路由匹配 ──

  it('should highlight 入驻审批 for nested route /registrations/123', () => {
    mockUsePathname.mockReturnValue('/registrations/123')
    render(<PlatformSidebar />)
    const link = screen.getByText('入驻审批').closest('a')!
    expect(link.className).toContain('bg-blue-50')
    expect(link.className).toContain('text-blue-700')
  })

  it('should highlight 入驻审批 for nested route /registrations/123/detail', () => {
    mockUsePathname.mockReturnValue('/registrations/123/detail')
    render(<PlatformSidebar />)
    const link = screen.getByText('入驻审批').closest('a')!
    expect(link.className).toContain('bg-blue-50')
    expect(link.className).toContain('text-blue-700')
  })

  it('should highlight 平台概览 for nested route /platform-dashboard/analytics', () => {
    mockUsePathname.mockReturnValue('/platform-dashboard/analytics')
    render(<PlatformSidebar />)
    const link = screen.getByText('平台概览').closest('a')!
    expect(link.className).toContain('bg-blue-50')
    expect(link.className).toContain('text-blue-700')
  })

  // ── Badge ──

  it('should render 即将上线 badge with correct styling', () => {
    render(<PlatformSidebar />)
    const badge = screen.getByText('即将上线')
    expect(badge).toBeInTheDocument()
    expect(badge.className).toContain('bg-amber-100')
    expect(badge.className).toContain('text-amber-700')
  })

  it('should not render badge for 入驻审批', () => {
    render(<PlatformSidebar />)
    // 入驻审批 does not have a badge — only 平台概览 does
    const badges = screen.getAllByText('即将上线')
    expect(badges.length).toBe(1)
  })

  // ── 结构完整性 ──

  it('should render exactly 2 menu items', () => {
    render(<PlatformSidebar />)
    const menuItems = [screen.getByText('入驻审批'), screen.getByText('平台概览')]
    expect(menuItems).toHaveLength(2)
  })

  it('should render as an aside element', () => {
    const { container } = render(<PlatformSidebar />)
    expect(container.querySelector('aside')).toBeInTheDocument()
  })
})
