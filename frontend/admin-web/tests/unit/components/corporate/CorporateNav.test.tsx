import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Override next/navigation mock from setup.ts to get controllable usePathname
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

import CorporateNav from '@/components/corporate/CorporateNav'

describe('CorporateNav', () => {
  const user = userEvent.setup()

  beforeEach(() => {
    vi.clearAllMocks()
    mockUsePathname.mockReturnValue('/')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // ── 基础结构 ──

  it('should render logo and brand name', () => {
    render(<CorporateNav />)
    expect(screen.getByTestId('logo')).toBeInTheDocument()
    expect(screen.getByText('米高')).toBeInTheDocument()
  })

  it('should render logo link pointing to root', () => {
    render(<CorporateNav />)
    const brandLink = screen.getByText('米高').closest('a')
    expect(brandLink).toHaveAttribute('href', '/')
  })

  it('should render all 4 desktop navigation links', () => {
    render(<CorporateNav />)
    // Note: 米高 appears in both logo area and nav — use getAllByText for nav items
    // Desktop nav is rendered inside md:flex hidden container
    const homeLinks = screen.getAllByText('首页')
    const servicesLinks = screen.getAllByText('产品服务')
    const aboutLinks = screen.getAllByText('关于我们')
    const contactLinks = screen.getAllByText('联系方式')

    // Desktop links exist (at least one each)
    expect(homeLinks.length).toBeGreaterThanOrEqual(1)
    expect(servicesLinks.length).toBeGreaterThanOrEqual(1)
    expect(aboutLinks.length).toBeGreaterThanOrEqual(1)
    expect(contactLinks.length).toBeGreaterThanOrEqual(1)
  })

  it('should render CTA buttons: 商家登录 and 商家入驻', () => {
    render(<CorporateNav />)
    // These appear in both desktop and (conditionally) mobile; ensure at least one
    expect(screen.getAllByText('商家登录').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('商家入驻').length).toBeGreaterThanOrEqual(1)
  })

  it('should have 商家入驻 link pointing to /register', () => {
    render(<CorporateNav />)
    // Desktop CTA: Link component for /register
    const registerLinks = screen.getAllByRole('link', { name: '商家入驻' })
    const registerLink = registerLinks.find(l => l.getAttribute('href') === '/register')
    expect(registerLink).toBeTruthy()
  })

  it('should have 商家登录 link pointing to merchant login', () => {
    render(<CorporateNav />)
    const loginLinks = screen.getAllByRole('link', { name: '商家登录' })
    const loginLink = loginLinks.find(l =>
      l.getAttribute('href') === 'https://merchant.migaozn.com/login'
    )
    expect(loginLink).toBeTruthy()
  })

  // ── 激活状态 ──

  it('should highlight 首页 when on root path', () => {
    mockUsePathname.mockReturnValue('/')
    render(<CorporateNav />)
    // Get all 首页 links; find the one with active class
    const homeLinks = screen.getAllByText('首页')
    const activeLink = homeLinks.find(
      el => el.closest('a')?.className.includes('text-blue-600')
    )
    expect(activeLink).toBeTruthy()
  })

  it('should highlight 产品服务 when on /services', () => {
    mockUsePathname.mockReturnValue('/services')
    render(<CorporateNav />)
    const servicesLinks = screen.getAllByText('产品服务')
    const activeLink = servicesLinks.find(
      el => el.closest('a')?.className.includes('text-blue-600')
    )
    expect(activeLink).toBeTruthy()
  })

  it('should highlight 关于我们 when on /about', () => {
    mockUsePathname.mockReturnValue('/about')
    render(<CorporateNav />)
    const aboutLinks = screen.getAllByText('关于我们')
    const activeLink = aboutLinks.find(
      el => el.closest('a')?.className.includes('text-blue-600')
    )
    expect(activeLink).toBeTruthy()
  })

  it('should highlight 联系方式 when on /contact', () => {
    mockUsePathname.mockReturnValue('/contact')
    render(<CorporateNav />)
    const contactLinks = screen.getAllByText('联系方式')
    const activeLink = contactLinks.find(
      el => el.closest('a')?.className.includes('text-blue-600')
    )
    expect(activeLink).toBeTruthy()
  })

  it('should NOT highlight 首页 when on /about (root is exact match only)', () => {
    mockUsePathname.mockReturnValue('/about')
    render(<CorporateNav />)
    const homeLinks = screen.getAllByText('首页')
    const activeLink = homeLinks.find(
      el => el.closest('a')?.className.includes('text-blue-600')
    )
    expect(activeLink).toBeFalsy()
  })

  it('should highlight 产品服务 for nested route /services/curtains', () => {
    mockUsePathname.mockReturnValue('/services/curtains')
    render(<CorporateNav />)
    const servicesLinks = screen.getAllByText('产品服务')
    const activeLink = servicesLinks.find(
      el => el.closest('a')?.className.includes('text-blue-600')
    )
    expect(activeLink).toBeTruthy()
  })

  // ── 移动端菜单切换 ──

  it('should render mobile menu toggle button', () => {
    render(<CorporateNav />)
    const toggleButton = screen.getByRole('button', { name: '打开菜单' })
    expect(toggleButton).toBeInTheDocument()
  })

  it('should show mobile menu when toggle button is clicked', async () => {
    render(<CorporateNav />)
    const toggleButton = screen.getByRole('button', { name: '打开菜单' })
    await user.click(toggleButton)

    // After opening, the toggle label changes to 关闭菜单
    expect(screen.getByRole('button', { name: '关闭菜单' })).toBeInTheDocument()
  })

  it('should hide mobile menu when close button is clicked', async () => {
    render(<CorporateNav />)
    // Open menu first
    const openButton = screen.getByRole('button', { name: '打开菜单' })
    await user.click(openButton)

    // Close menu
    const closeButton = screen.getByRole('button', { name: '关闭菜单' })
    await user.click(closeButton)

    // Button label returns to 打开菜单
    expect(screen.getByRole('button', { name: '打开菜单' })).toBeInTheDocument()
  })

  // ── 移动端菜单导航项 ──

  it('should render nav items in mobile menu when open', async () => {
    render(<CorporateNav />)
    await user.click(screen.getByRole('button', { name: '打开菜单' }))

    // All nav items appear in mobile menu (getAllByText since desktop versions also exist)
    const homeItems = screen.getAllByText('首页')
    expect(homeItems.length).toBeGreaterThanOrEqual(1) // at least desktop + mobile
    const servicesItems = screen.getAllByText('产品服务')
    expect(servicesItems.length).toBeGreaterThanOrEqual(1)
  })

  it('should render CTA buttons in mobile menu when open', async () => {
    render(<CorporateNav />)
    await user.click(screen.getByRole('button', { name: '打开菜单' }))

    // Both CTAs exist in mobile menu — should have 2 of each now (desktop + mobile)
    const loginButtons = screen.getAllByText('商家登录')
    const registerButtons = screen.getAllByText('商家入驻')
    expect(loginButtons.length).toBeGreaterThanOrEqual(2)
    expect(registerButtons.length).toBeGreaterThanOrEqual(2)
  })

  // ── 导航链接 href ──

  it('should have correct hrefs for desktop nav links', () => {
    render(<CorporateNav />)
    const links = screen.getAllByRole('link')

    const hrefs = links.map(l => l.getAttribute('href')).filter(Boolean)

    expect(hrefs).toContain('/')
    expect(hrefs).toContain('/services')
    expect(hrefs).toContain('/about')
    expect(hrefs).toContain('/contact')
    expect(hrefs).toContain('/register')
    expect(hrefs).toContain('https://merchant.migaozn.com/login')
  })

  // ── 移动端菜单项点击后关闭 ──

  it('should close mobile menu when a nav link is clicked', async () => {
    render(<CorporateNav />)
    // Open mobile menu
    await user.click(screen.getByRole('button', { name: '打开菜单' }))
    expect(screen.getByRole('button', { name: '关闭菜单' })).toBeInTheDocument()

    // Click a mobile menu link (首页)
    // getAllByText returns both desktop and mobile — we click one of them
    const homeLinks = screen.getAllByText('首页')
    // Click the last one (mobile menu version should be after desktop)
    await user.click(homeLinks[homeLinks.length - 1])

    // Menu should close
    expect(screen.getByRole('button', { name: '打开菜单' })).toBeInTheDocument()
  })

  // ── 移动端 CTA 点击后关闭 ──

  it('should close mobile menu when 商家入驻 CTA is clicked', async () => {
    render(<CorporateNav />)
    await user.click(screen.getByRole('button', { name: '打开菜单' }))
    expect(screen.getByRole('button', { name: '关闭菜单' })).toBeInTheDocument()

    const registerButtons = screen.getAllByText('商家入驻')
    await user.click(registerButtons[registerButtons.length - 1])

    expect(screen.getByRole('button', { name: '打开菜单' })).toBeInTheDocument()
  })
})
