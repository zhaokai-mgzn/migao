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

  it('should render the sidebar with logo', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getByTestId('logo')).toBeInTheDocument()
  })

  it('should render all menu items', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getByText('数据看板')).toBeInTheDocument()
    expect(screen.getByText('商品管理')).toBeInTheDocument()
    expect(screen.getByText('订单管理')).toBeInTheDocument()
    expect(screen.getByText('售后管理')).toBeInTheDocument()
    expect(screen.getByText('加工项管理')).toBeInTheDocument()
    expect(screen.getByText('客服工作台')).toBeInTheDocument()
    expect(screen.getByText('客户管理')).toBeInTheDocument()
    expect(screen.getByText('系统设置')).toBeInTheDocument()
  })

  it('should render navigation links with correct paths', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const dashboardLink = screen.getByText('数据看板').closest('a')
    expect(dashboardLink).toHaveAttribute('href', '/dashboard')

    const productsLink = screen.getByText('商品管理').closest('a')
    expect(productsLink).toHaveAttribute('href', '/products')

    const ordersLink = screen.getByText('订单管理').closest('a')
    expect(ordersLink).toHaveAttribute('href', '/orders')
  })

  it('should hide text labels when collapsed', () => {
    render(<Sidebar collapsed={true} onToggle={mockOnToggle} />)
    expect(screen.queryByText('数据看板')).not.toBeInTheDocument()
    expect(screen.queryByText('有客')).not.toBeInTheDocument()
  })

  it('should show collapse toggle button', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getByText('收起')).toBeInTheDocument()
  })

  it('should call onToggle when collapse button is clicked', async () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    await user.click(screen.getByText('收起'))
    expect(mockOnToggle).toHaveBeenCalledTimes(1)
  })

  it('should highlight active menu item for /dashboard', () => {
    mockUsePathname.mockReturnValue('/dashboard')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const dashboardLink = screen.getByText('数据看板').closest('a')
    expect(dashboardLink?.className).toContain('bg-primary-600')
  })

  it('should highlight active menu item for /products', () => {
    mockUsePathname.mockReturnValue('/products')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const productsLink = screen.getByText('商品管理').closest('a')
    expect(productsLink?.className).toContain('bg-primary-600')
  })

  it('should not highlight inactive menu items', () => {
    mockUsePathname.mockReturnValue('/dashboard')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const productsLink = screen.getByText('商品管理').closest('a')
    expect(productsLink?.className).not.toContain('bg-primary-600')
  })

  it('should highlight products for nested routes like /products/123', () => {
    mockUsePathname.mockReturnValue('/products/123')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const productsLink = screen.getByText('商品管理').closest('a')
    expect(productsLink?.className).toContain('bg-primary-600')
  })

  it('should show expand tooltip when collapsed', () => {
    render(<Sidebar collapsed={true} onToggle={mockOnToggle} />)
    const toggleBtn = screen.getByTitle('展开侧边栏')
    expect(toggleBtn).toBeInTheDocument()
  })
})
