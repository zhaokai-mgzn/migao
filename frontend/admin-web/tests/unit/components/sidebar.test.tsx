import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock useAuthStore
const mockUseAuthStore = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: (...args: any[]) => mockUseAuthStore(...args),
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock next/navigation
const mockUsePathname = vi.fn()
vi.mock('next/navigation', () => ({
  usePathname: () => mockUsePathname(),
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
  }),
}))

// Mock Logo component
vi.mock('@/components/ui/Logo', () => ({
  default: (props: any) => <span data-testid="logo" {...props} />,
}))

import Sidebar from '@/components/layout/Sidebar'

describe('Sidebar', () => {
  const user = userEvent.setup()
  const mockOnToggle = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    mockUsePathname.mockReturnValue('/dashboard')
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: 'admin', name: '管理员' },
    })
  })

  // ── 基础结构 ──

  it('should render the sidebar with logo', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getByTestId('logo')).toBeInTheDocument()
  })

  it('should render all menu items', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // 一级菜单
    expect(screen.getByText('工作台（数据看板）')).toBeInTheDocument()
    // 分组标题
    expect(screen.getByText('商品管理')).toBeInTheDocument()
    expect(screen.getByText('订单管理')).toBeInTheDocument()
    // 子菜单项
    expect(screen.getByText('商品列表')).toBeInTheDocument()
    expect(screen.getByText('商品分类管理')).toBeInTheDocument()
    expect(screen.getByText('加工项管理')).toBeInTheDocument()
    expect(screen.getByText('订单列表')).toBeInTheDocument()
    expect(screen.getByText('售后工单')).toBeInTheDocument()
    // 独立菜单项
    expect(screen.getByText('客户管理')).toBeInTheDocument()
    expect(screen.getByText('财务对账')).toBeInTheDocument()
    expect(screen.getByText('机器人设置')).toBeInTheDocument()
    expect(screen.getByText('员工管理')).toBeInTheDocument()
    expect(screen.getByText('企业基础信息')).toBeInTheDocument()
  })

  it('should render navigation links with correct paths', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getByText('工作台（数据看板）').closest('a')).toHaveAttribute('href', '/dashboard')
    expect(screen.getByText('商品列表').closest('a')).toHaveAttribute('href', '/products')
    expect(screen.getByText('订单列表').closest('a')).toHaveAttribute('href', '/orders')
  })

  // ── 折叠状态 ──

  it('should hide text labels when collapsed', () => {
    render(<Sidebar collapsed={true} onToggle={mockOnToggle} />)
    expect(screen.queryByText('工作台（数据看板）')).not.toBeInTheDocument()
    expect(screen.queryByText('米高')).not.toBeInTheDocument()
    expect(screen.queryByText('商品管理')).not.toBeInTheDocument()
  })

  it('should show expand button when collapsed', () => {
    render(<Sidebar collapsed={true} onToggle={mockOnToggle} />)
    expect(screen.getByTitle('展开侧边栏')).toBeInTheDocument()
  })

  it('should show collapse button when expanded', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getByText('收起')).toBeInTheDocument()
  })

  it('should call onToggle when collapse button is clicked', async () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    await user.click(screen.getByText('收起'))
    expect(mockOnToggle).toHaveBeenCalledTimes(1)
  })

  // ── 高亮激活 ──

  function getActiveClass(el: HTMLElement) {
    return el.className
  }

  it('should highlight active menu item for /dashboard', () => {
    mockUsePathname.mockReturnValue('/dashboard')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = screen.getByText('工作台（数据看板）').closest('a')!
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  it('should highlight active menu item for /products', () => {
    mockUsePathname.mockReturnValue('/products')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = screen.getByText('商品列表').closest('a')!
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  it('should not highlight inactive menu items', () => {
    mockUsePathname.mockReturnValue('/dashboard')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = screen.getByText('商品列表').closest('a')!
    expect(getActiveClass(link)).not.toContain('bg-primary-600')
  })

  it('should highlight nested route for /products/123', () => {
    mockUsePathname.mockReturnValue('/products/123')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = screen.getByText('商品列表').closest('a')!
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  it('should highlight for root path as dashboard', () => {
    mockUsePathname.mockReturnValue('/')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = screen.getByText('工作台（数据看板）').closest('a')!
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  // ── 分组折叠/展开 ──

  it('should toggle group expansion when clicking group header', async () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getByText('商品列表')).toBeInTheDocument()

    await user.click(screen.getByText('商品管理'))
    expect(screen.queryByText('商品列表')).not.toBeInTheDocument()
  })

  // ── 独立菜单项 ──

  it('should render standalone items exactly once each', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getAllByText('客户管理').length).toBe(1)
    expect(screen.getAllByText('机器人设置').length).toBe(1)
  })
})
